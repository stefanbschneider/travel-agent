#!/usr/bin/env python3
"""Phase 2 per-query runner: our own orchestrator (not opencode/codex).

For each query it:
- loads the query with oracle fields available for evaluation, but hides them from the agent,
- runs ``chinatravel.agent.phase2.orchestrator.solve_phase2`` (deterministic; LLM off by default),
- writes the official ``results/<method>/<uid>.json`` plan,
- writes ``<work_dir>/<uid>/evaluation.json`` (official evaluators) and ``telemetry.json``,
- is resume-safe (skips queries whose result file already exists).

Usage:
    python agent_env/scripts/solve_phase2.py --split tpc_phase1 --limit 3
    python agent_env/scripts/solve_phase2.py --split tpc_phase2_val --resume --budget-sec 60
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from statistics import mean, pstdev

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
# Reuse the baseline harness helpers (visible_query, evaluate_one, write_json, ...).
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

import solve_script_with_harness as hb  # noqa: E402

from chinatravel.agent.phase2 import llm_client as p2_llm  # noqa: E402
from chinatravel.agent.phase2 import orchestrator as orch  # noqa: E402

DEFAULT_METHOD_PREFIX = "phase2_e2e_"
DEFAULT_BUDGET_SEC = orch.PHASE2_DEFAULT_BUDGET_SEC  # 15 min (TBC); override via --budget-sec


def _default_method_for_split(split: str) -> str:
    """Keep the script default aligned with Makefile P2_METHOD."""
    return f"{DEFAULT_METHOD_PREFIX}{split}"


def _phase2_llm_config_from_env() -> dict:
    cfg = {
        "backend": os.environ.get("TPC_P2_LLM_BACKEND", "none"),
        "fixtures_dir": os.environ.get("TPC_P2_LLM_FIXTURES"),
        "model": os.environ.get("TPC_P2_LLM_MODEL"),
        "base_url": os.environ.get("TPC_P2_LLM_BASE_URL"),
        "api_key_env": os.environ.get("TPC_P2_LLM_API_KEY_ENV"),
        "api_key": os.environ.get("TPC_P2_LLM_API_KEY"),
    }
    return {k: v for k, v in cfg.items() if v not in (None, "")}


def _score_stats(values: list[float]) -> dict:
    vals = [float(v) for v in values]
    if not vals:
        return {"count": 0, "mean": 0.0, "min": 0.0, "max": 0.0, "std": 0.0}
    return {
        "count": len(vals),
        "mean": mean(vals),
        "min": min(vals),
        "max": max(vals),
        "std": pstdev(vals),
    }


def _aggregate_overall_scores(evaluations: list[dict]) -> dict:
    return {
        "overall_true": _score_stats([e.get("overall_true", 0.0) for e in evaluations]),
        "overall_parsed": _score_stats([e.get("overall_parsed", 0.0) for e in evaluations]),
    }


def _load_queries(split: str, lang: str = "en"):
    """Load queries with oracle fields present (for evaluation only)."""
    from chinatravel.data.load_datasets import load_query

    args = argparse.Namespace(splits=split, lang=lang, oracle_translation=True)
    query_ids, query_data = load_query(args)
    if not query_ids:
        raise RuntimeError(f"No queries found for split: {split}")
    return query_ids, query_data


def run_split(
    split: str,
    *,
    method: str | None = None,
    limit: int | None = None,
    uid: str | None = None,
    uids: list[str] | None = None,
    resume: bool = False,
    budget_sec: float | None = None,
    lang: str = "en",
    work_dir: str | None = None,
    results_dir: str | None = None,
    env=None,
    solve_fn=None,
) -> dict:
    """Run the Phase 2 pipeline over a split. Returns a summary dict."""
    method = method or _default_method_for_split(split)
    budget_sec = float(budget_sec if budget_sec is not None else DEFAULT_BUDGET_SEC)
    results_root = Path(results_dir) if results_dir else PROJECT_ROOT / "results"
    work_root = Path(work_dir) if work_dir else PROJECT_ROOT / "agent_env" / "runs" / method
    result_method_dir = results_root / method
    result_method_dir.mkdir(parents=True, exist_ok=True)

    query_ids, query_data = _load_queries(split, lang=lang)
    if uids is not None:
        missing = [u for u in uids if u not in query_data]
        if missing:
            raise RuntimeError(f"{len(missing)} uid(s) not in split {split!r}, e.g. {missing[:3]}")
        selected = list(uids)
    elif uid:
        if uid not in query_data:
            raise RuntimeError(f"uid {uid!r} not in split {split!r}")
        selected = [uid]
    else:
        selected = query_ids[: int(limit)] if limit else query_ids

    # Build the deterministic TPCAgent-backed solve function once (unless injected).
    if solve_fn is None:
        if env is None:
            from chinatravel.environment.world_env import WorldEnv

            env = WorldEnv(lang=lang)
        solve_fn = orch.make_tpcagent_solve_fn(env, lang=lang)

    # Acceptance gate is OR-correct by default: enable disjunctive branch generation unless the
    # operator explicitly overrides TPC_P2_DISJUNCTION. The library default (Flags()) stays off, so
    # the deterministic byte-identical invariant tests are unaffected.
    flags = orch.Flags.from_env()
    if "TPC_P2_DISJUNCTION" not in os.environ:
        flags.disjunction = True

    done_uids: list[str] = []
    skipped = 0
    parse_failures = 0
    llm_parse_attempts = 0
    llm_fixture_missing = 0
    solved_evaluations: list[dict] = []

    llm_cfg = _phase2_llm_config_from_env()
    llm_client = p2_llm.build_llm_client(llm_cfg)

    for idx, quid in enumerate(selected, start=1):
        result_path = result_method_dir / f"{quid}.json"
        if resume and result_path.exists():
            skipped += 1
            done_uids.append(quid)
            continue

        full_query = query_data[quid]
        full_query.setdefault("uid", quid)
        visible = hb.visible_query(full_query)  # oracle hidden from the agent

        plan, telemetry = orch.solve_phase2(
            visible,
            env=env,
            llm_client=llm_client,
            budget_sec=budget_sec,
            solve_fn=solve_fn,
            flags=flags,
        )

        hb.write_json(result_path, plan)

        run_dir = work_root / quid
        hb.write_json(run_dir / "output.json", plan)
        hb.write_json(run_dir / "telemetry.json", telemetry)
        try:
            evaluation = hb.evaluate_one(split, quid, full_query, plan)
        except Exception as exc:  # never let evaluation crash the batch
            evaluation = {"uid": quid, "error": f"evaluation: {exc}", "all_pass": False}
        hb.write_json(run_dir / "evaluation.json", evaluation)
        solved_evaluations.append(evaluation)

        if telemetry.get("used_fallback"):
            parse_failures += 0  # fallback != parse failure; kept for future attribution
        if telemetry.get("flags", {}).get("llm_parse"):
            llm_parse_attempts += 1
            err = str(telemetry.get("error") or "")
            if "No fixture for key" in err:
                llm_fixture_missing += 1
        done_uids.append(quid)
        print(
            f"[{idx}/{len(selected)}] {quid} "
            f"valid={telemetry.get('valid_output')} fallback={telemetry.get('used_fallback')} "
            f"solve_sec={telemetry.get('stage_sec', {}).get('solve', 0):.2f} "
            f"overall_true={float(evaluation.get('overall_true', 0.0)):.4f} "
            f"overall_parsed={float(evaluation.get('overall_parsed', 0.0)):.4f}"
        )

    solved_overall_stats = _aggregate_overall_scores(solved_evaluations)
    print(
        "[overall/solved_this_run] "
        f"true(mean/min/max/std)="
        f"{solved_overall_stats['overall_true']['mean']:.4f}/"
        f"{solved_overall_stats['overall_true']['min']:.4f}/"
        f"{solved_overall_stats['overall_true']['max']:.4f}/"
        f"{solved_overall_stats['overall_true']['std']:.4f} "
        f"parsed(mean/min/max/std)="
        f"{solved_overall_stats['overall_parsed']['mean']:.4f}/"
        f"{solved_overall_stats['overall_parsed']['min']:.4f}/"
        f"{solved_overall_stats['overall_parsed']['max']:.4f}/"
        f"{solved_overall_stats['overall_parsed']['std']:.4f}"
    )

    resume_all_selected_stats = None
    if resume:
        all_selected_evals: list[dict] = []
        for quid in selected:
            eval_path = work_root / quid / "evaluation.json"
            if eval_path.exists():
                try:
                    all_selected_evals.append(hb.read_json(eval_path))
                    continue
                except Exception:
                    pass

            result_path = result_method_dir / f"{quid}.json"
            if not result_path.exists():
                continue
            full_query = query_data.get(quid)
            if full_query is None:
                continue
            full_query.setdefault("uid", quid)
            try:
                plan = hb.read_json(result_path)
                evaluation = hb.evaluate_one(split, quid, full_query, plan)
                hb.write_json(eval_path, evaluation)
                all_selected_evals.append(evaluation)
            except Exception:
                continue

        resume_all_selected_stats = _aggregate_overall_scores(all_selected_evals)
        print(
            "[overall/resume_all_selected] "
            f"true(mean/min/max/std)="
            f"{resume_all_selected_stats['overall_true']['mean']:.4f}/"
            f"{resume_all_selected_stats['overall_true']['min']:.4f}/"
            f"{resume_all_selected_stats['overall_true']['max']:.4f}/"
            f"{resume_all_selected_stats['overall_true']['std']:.4f} "
            f"parsed(mean/min/max/std)="
            f"{resume_all_selected_stats['overall_parsed']['mean']:.4f}/"
            f"{resume_all_selected_stats['overall_parsed']['min']:.4f}/"
            f"{resume_all_selected_stats['overall_parsed']['max']:.4f}/"
            f"{resume_all_selected_stats['overall_parsed']['std']:.4f}"
        )

    summary = {
        "split": split,
        "method": method,
        "budget_sec": budget_sec,
        "llm_backend": getattr(llm_client, "backend", "none"),
        "llm_parse_attempts": llm_parse_attempts,
        "llm_fixture_missing": llm_fixture_missing,
        "selected": len(selected),
        "skipped": skipped,
        "uids": done_uids,
        "overall_solved_this_run": solved_overall_stats,
    }
    if resume_all_selected_stats is not None:
        summary["overall_resume_all_selected"] = resume_all_selected_stats
    summary_path = work_root / f"{split}_summary.json"
    hb.write_json(summary_path, summary)
    return summary


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--split", default="tpc_phase2_val")
    p.add_argument("--uid", default=None)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--method", default=None)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--budget-sec", type=float, default=None)
    p.add_argument("--lang", default="en", choices=["en", "zh"])
    p.add_argument("--work-dir", default=None)
    p.add_argument("--results-dir", default=None)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    method = args.method or _default_method_for_split(args.split)
    summary = run_split(
        args.split,
        method=method,
        limit=args.limit,
        uid=args.uid,
        resume=args.resume,
        budget_sec=args.budget_sec,
        lang=args.lang,
        work_dir=args.work_dir,
        results_dir=args.results_dir,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
