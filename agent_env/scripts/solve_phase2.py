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
import tomllib
from pathlib import Path
from statistics import mean, pstdev
import urllib.request

import psutil

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
DEFAULT_BUDGET_SEC = orch.DEFAULT_BUDGET_SEC  # 300s (our working default); override via --budget-sec
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "agent_env" / "config.toml"
# Warn-only guard: if set, print a warning (never raise/abort) when a single process's RSS grows
# by more than this many MB since its first solved query. Catches leaks (e.g. func_timeout thread
# accumulation on timeouts) during long single-process runs; unset by default (opt-in via env).
MAX_RSS_GROWTH_MB = float(os.environ.get("TPC_P2_MAX_RSS_MB", "0") or "0")
LLM_MODEL_PROBE_TIMEOUT_SEC = 5.0
_OPENAI_BASE_URL_ENV_VARS = (
    "TPC_P2_LLM_BASE_URL",
    "OPENAI_BASE_URL",
    "OPENAI_API_BASE",
    "SGLANG_BASE_URL",
)


def _default_method_for_split(split: str) -> str:
    """Keep the script default aligned with Makefile P2_METHOD."""
    return f"{DEFAULT_METHOD_PREFIX}{split}"


def _read_local_config(path: Path = DEFAULT_CONFIG_PATH) -> dict:
    if not path.exists():
        return {}
    with path.open("rb") as f:
        return tomllib.load(f)


def _first_env_value(names: tuple[str, ...]) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value not in (None, ""):
            return str(value)
    return None


def _resolve_openai_api_key(cfg: dict) -> str:
    return str(
        cfg.get("api_key")
        or os.environ.get("TPC_P2_LLM_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or "EMPTY"
    )


def _probe_openai_model_id(base_url: str, *, api_key: str, timeout_sec: float = LLM_MODEL_PROBE_TIMEOUT_SEC) -> str | None:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/models",
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout_sec) as response:
        status = getattr(response, "status", None)
        if status is None and hasattr(response, "getcode"):
            status = response.getcode()
        if status not in (None, 200):
            return None
        payload = json.load(response)

    models = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(models, list) or not models:
        return None
    first = models[0]
    model_id = first.get("id") if isinstance(first, dict) else None
    return str(model_id) if model_id not in (None, "") else None


def _resolve_openai_model(cfg: dict, *, base_url: str | None, api_key: str) -> str | None:
    configured = cfg.get("model") or os.environ.get("TPC_P2_LLM_MODEL") or os.environ.get("OPENAI_MODEL")
    if configured not in (None, ""):
        return str(configured)
    if not base_url:
        return None
    return _probe_openai_model_id(base_url, api_key=api_key)


def _autodetect_openai_cfg() -> dict | None:
    base_url = _first_env_value(_OPENAI_BASE_URL_ENV_VARS)
    if not base_url:
        return None
    api_key = _resolve_openai_api_key({})
    try:
        model = _resolve_openai_model({}, base_url=base_url, api_key=api_key)
    except Exception:
        return None
    if not model:
        return None
    return {
        "backend": "openai",
        "backend_source": "autodetect",
        "base_url": base_url,
        "model": model,
        "api_key": api_key,
    }


def _phase2_llm_config() -> dict:
    cfg: dict = {}
    backend_source = "none"

    local_cfg = _read_local_config()
    phase2_cfg = local_cfg.get("phase2") if isinstance(local_cfg, dict) else None
    if isinstance(phase2_cfg, dict):
        llm_cfg = phase2_cfg.get("llm")
        if isinstance(llm_cfg, dict):
            cfg.update({k: v for k, v in llm_cfg.items() if v not in (None, "")})
            if llm_cfg.get("backend") not in (None, ""):
                backend_source = "config"

    env_cfg = {
        "backend": os.environ.get("TPC_P2_LLM_BACKEND"),
        "fixtures_dir": os.environ.get("TPC_P2_LLM_FIXTURES"),
        "model": os.environ.get("TPC_P2_LLM_MODEL"),
        "base_url": os.environ.get("TPC_P2_LLM_BASE_URL"),
        "api_key_env": os.environ.get("TPC_P2_LLM_API_KEY_ENV"),
        "api_key": os.environ.get("TPC_P2_LLM_API_KEY"),
        "temperature": os.environ.get("TPC_P2_LLM_TEMPERATURE"),
        "max_tokens": os.environ.get("TPC_P2_LLM_MAX_TOKENS"),
    }
    cfg.update({k: v for k, v in env_cfg.items() if v not in (None, "")})
    if env_cfg["backend"] not in (None, ""):
        backend_source = "env-explicit"

    backend = str(cfg.get("backend") or "none").lower()
    cfg["backend"] = backend

    if backend == "deepinfra":
        cfg.setdefault("api_key_env", "DEEPINFRA_API_KEY")
        if "base_url" not in cfg and os.environ.get("DEEPINFRA_BASE_URL"):
            cfg["base_url"] = os.environ["DEEPINFRA_BASE_URL"]
        if "model" not in cfg and os.environ.get("DEEPINFRA_MODEL"):
            cfg["model"] = os.environ["DEEPINFRA_MODEL"]
    elif backend == "openai":
        base_url = str(cfg.get("base_url") or _first_env_value(_OPENAI_BASE_URL_ENV_VARS) or "") or None
        if base_url:
            cfg["base_url"] = base_url
        api_key = _resolve_openai_api_key(cfg)
        try:
            model = _resolve_openai_model(cfg, base_url=base_url, api_key=api_key)
        except Exception:
            model = None
        if model:
            cfg["model"] = model
            cfg["api_key"] = api_key
        else:
            cfg["backend"] = "none"
    elif backend_source != "env-explicit":
        autodetected = _autodetect_openai_cfg()
        if autodetected is not None:
            cfg.update(autodetected)
            backend_source = "autodetect"

    cfg["backend_source"] = backend_source
    return cfg


def _fmt_score(value) -> str:
    """Format a score for the per-uid log line; None (oracle-free query) prints as N/A rather
    than a misleading 0.0000."""
    return f"{float(value):.4f}" if value is not None else "N/A"


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
    # overall_true is None (present key, no value) rather than absent for oracle-free queries
    # (see evaluate_one's has_oracle gate), so `.get(key, 0.0)` alone would not catch it.
    return {
        "overall_true": _score_stats([e.get("overall_true", 0.0) or 0.0 for e in evaluations]),
        "overall_parsed": _score_stats([e.get("overall_parsed", 0.0) or 0.0 for e in evaluations]),
    }


def _load_queries(split: str, lang: str = "en"):
    """Load queries with oracle fields present (for evaluation only)."""
    from chinatravel.data.load_datasets import load_query

    args = argparse.Namespace(splits=split, lang=lang, oracle_translation=True)
    query_ids, query_data = load_query(args)
    if not query_ids:
        raise RuntimeError(f"No queries found for split: {split}")
    return query_ids, query_data


def resolve_llm_client_and_flags():
    """Build the LLM client + acceptance-gate flags exactly as ``run_split`` does.

    Factored out so a caller running a single ad hoc query (e.g. ``scripts/run_query.py``) can
    reproduce the same parse-time flags used inside a real ``run_split`` invocation -- e.g. to
    diff the resulting parse against an oracle with ``parser_vs_oracle.compute_query_diff``.
    """
    llm_cfg = _phase2_llm_config()
    llm_client = p2_llm.build_llm_client(llm_cfg)
    llm_backend_source = str(llm_cfg.get("backend_source") or "none")
    setattr(llm_client, "backend_source", llm_backend_source)

    # Acceptance gate is OR-correct by default: enable disjunctive branch generation unless the
    # operator explicitly overrides TPC_P2_DISJUNCTION. The library default (Flags()) stays off, so
    # the deterministic byte-identical invariant tests are unaffected.
    flags = orch.Flags.from_env()
    flags.llm_backend = getattr(llm_client, "backend", "none")
    if "TPC_P2_DISJUNCTION" not in os.environ:
        flags.disjunction = True
    # Dynamic budget reallocation is a pure timing win (gives Stage 2 whatever Stage 1 -- and
    # Stage 3 when off -- didn't use) with a floor at the static split, so default it on too.
    if "TPC_P2_DYNAMIC_BUDGET" not in os.environ:
        flags.dynamic_budget = True
    # TPC_P2_LLM_PARSE stays off by default even when a real backend is configured -- an explicit
    # recorded decision (roadmap W8), not an auto-enable like disjunction/dynamic_budget/
    # entity_resolution above. `flags.llm_parse` already came from Flags.from_env() above (off
    # unless TPC_P2_LLM_PARSE is explicitly set), so there is deliberately no auto-enable branch
    # here. The last paired same-SHA screen on current head was RED for audit-on vs. parse-off
    # (n=10, 60s, DeepInfra timeout 6s): parse off FPR 30.0/overall_true 54.48/1 timeout vs. audit
    # on FPR 20.0/overall_true 45.54/2 timeouts -- see docs/tpc_phase2_roadmap.md's "Current status
    # snapshot". An explicit off is also safer than an auto-enable that fires only when an
    # endpoint happens to be reachable, since it makes the organizer run behave the same as every
    # local run. An operator who wants the audit on (e.g. to re-screen against a reachable
    # endpoint) still can with an explicit TPC_P2_LLM_PARSE=1 override.
    # Deterministic entity resolution is pure recall/precision cleanup against the committed POI
    # catalogs. It has no LLM or network dependency, so default it on with disjunction and dynamic
    # budget unless the operator overrides TPC_P2_ENTITY_RESOLUTION. Library Flags() remains off
    # for byte-identical invariant tests.
    if "TPC_P2_ENTITY_RESOLUTION" not in os.environ:
        flags.entity_resolution = True

    return llm_client, flags


def apply_deterministic_solver_defaults():
    """Promote gate-cleared deterministic solver features to harness-default-on.

    Same promotion pattern ``resolve_llm_client_and_flags`` uses for disjunction/dynamic_budget/
    entity_resolution: set the env default the ``TPCAgent`` reads, *unless the operator explicitly
    overrides it*, so the library default (the unset env var) -- and the byte-identical opt-in unit
    tests that assert it -- stay unchanged. These are deterministic (no LLM, no network) passes with
    a committed ``900 s`` gate, so this is the sanctioned "explicit measured configuration" path.

    - ``TPC_PIN_TIMED_WINDOWS=1``: the ``900 s`` ``familiar_100_val`` gate (roadmap step 1, rows
      ``20260723T200723Z`` floor / ``20260724T071840Z`` pin) cleared cleanly -- e2e continuous
      ``43.72 -> 48.04``, timeouts ``0 -> 0``. The earlier ``300 s`` timeout regression that blocked
      it was a budget-boundary artifact, not a real cost.
    - ``TPC_SOLVE_CONVERGE_PATIENCE=15``: paired with pin (row ``20260724T192503Z``) it held quality
      flat (e2e continuous ``47.98``) while cutting solve ``p50`` ``366 s -> 265 s`` (below even the
      floor's ``337 s``) -- reclaiming wall-clock and making the submission more robust to an
      organizer per-query timeout shorter than the assumed ``900 s``.
    - ``TPC_COMMONSENSE_FIRST=1``: the commonsense-first finalization policy (relaxed repair commit
      rule for unaccepted plans + the ``best_cs`` bucket in ``_solve``; see
      ``docs/agents/final_night_commonsense_first.md``). ``eval_tpc`` scores C-LPR as the
      *conditional* logical micro, so an emitted plan that fails commonsense forfeits its whole
      logical partial credit (weight ``0.25``) and its EPR-macro point (``0.10``). Paired same-SHA
      end-to-end screen (``results/phase2_baselines/screens/20260726_e2e_n40_b120_commonsense_first``,
      ``familiar_100_val`` fold 0, ``n=40``, ``120 s``, ``parallel=7``, LLM backend ``none``):
      ``overall_true`` ``51.34 -> 60.98``, commonsense pass ``30/40 -> 40/40``, EPR-macro
      ``75 -> 100``, C-LPR ``67.35 -> 89.95``, FPR ``32.5 -> 35.0``, ``all_pass`` ``13 -> 14``, zero
      parse failures. ``logical_micro`` is unchanged at ``89.95``, which is the proof of mechanism:
      the gain is entirely the commonsense gate releasing logical credit the solver had already
      earned. **Caveat:** timeouts rose ``4 -> 7`` at that deliberately tight budget (baseline solve
      ``p50`` is already ``108 s`` of ``120 s``), all recovered with ``used_fallback=0`` -- the same
      budget-boundary shape ``TPC_PIN_TIMED_WINDOWS`` showed at ``300 s`` and cleared at ``900 s``
      (``p50 265 s`` there). The probe cost is bounded proportionally
      (``TPC_CS_CHECK_TIME_FRAC=0.08`` of the solve budget, ``TPC_CS_CHECK_BUDGET=60``
      confirmations), and ``docs/agents/final_night_eval_commands.md`` carries the ``900 s`` pinned
      confirmation rows.

    Must run *before* ``make_tpcagent_solve_fn`` builds the agent: ``TPCAgent.__init__`` reads
    ``TPC_SOLVE_CONVERGE_PATIENCE`` eagerly (``TPC_PIN_TIMED_WINDOWS`` is read lazily at pack time,
    but both are set here for clarity)."""
    if "TPC_PIN_TIMED_WINDOWS" not in os.environ:
        os.environ["TPC_PIN_TIMED_WINDOWS"] = "1"
    if "TPC_SOLVE_CONVERGE_PATIENCE" not in os.environ:
        os.environ["TPC_SOLVE_CONVERGE_PATIENCE"] = "15"
    if "TPC_COMMONSENSE_FIRST" not in os.environ:
        os.environ["TPC_COMMONSENSE_FIRST"] = "1"


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
    queries: dict | None = None,
) -> dict:
    """Run the Phase 2 pipeline over a split. Returns a summary dict.

    ``queries``, when given, is used verbatim as ``{uid: query_dict}`` instead of loading
    ``split`` from the on-disk dataset -- lets a caller (e.g. a single-query CLI) feed an
    ad hoc or file-loaded query through the exact same solve/write/evaluate path used for
    real splits. ``split`` still becomes a label on the written results/evaluation.
    """
    method = method or _default_method_for_split(split)
    budget_sec = float(budget_sec if budget_sec is not None else DEFAULT_BUDGET_SEC)
    results_root = Path(results_dir) if results_dir else PROJECT_ROOT / "results"
    work_root = Path(work_dir) if work_dir else PROJECT_ROOT / "agent_env" / "runs" / method
    result_method_dir = results_root / method
    result_method_dir.mkdir(parents=True, exist_ok=True)

    if queries is not None:
        query_ids, query_data = list(queries.keys()), queries
    else:
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
        # Promote the gate-cleared deterministic solver features (timed-window pinning + early
        # convergence) to harness-default-on -- but only when we build the agent ourselves. It runs
        # before make_tpcagent_solve_fn, since TPCAgent.__init__ reads TPC_SOLVE_CONVERGE_PATIENCE
        # eagerly. Gated on ``solve_fn is None`` so an injected solve_fn (unit tests / embedded
        # callers) never triggers a process-global env mutation the caller didn't ask for. An
        # explicit operator override of either env var is still respected.
        apply_deterministic_solver_defaults()
        if env is None:
            from chinatravel.environment.world_env import WorldEnv

            env = WorldEnv(lang=lang)
        solve_fn = orch.make_tpcagent_solve_fn(env, lang=lang)

    llm_client, flags = resolve_llm_client_and_flags()

    done_uids: list[str] = []
    skipped = 0
    parse_failures = 0
    llm_parse_attempts = 0
    llm_fixture_missing = 0
    llm_parse_failed = 0
    solved_evaluations: list[dict] = []
    rss_baseline_mb: float | None = None

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
        telemetry["llm_backend_source"] = getattr(llm_client, "backend_source", "none")

        hb.write_json(result_path, plan)

        rss_mb = psutil.Process().memory_info().rss / (1024 * 1024)
        telemetry["rss_mb"] = rss_mb
        if MAX_RSS_GROWTH_MB > 0:
            if rss_baseline_mb is None:
                rss_baseline_mb = rss_mb
            elif rss_mb - rss_baseline_mb > MAX_RSS_GROWTH_MB:
                print(
                    f"[rss-warn] {quid}: RSS grew {rss_mb - rss_baseline_mb:.0f} MB since first "
                    f"query ({rss_baseline_mb:.0f} -> {rss_mb:.0f} MB), exceeds "
                    f"TPC_P2_MAX_RSS_MB={MAX_RSS_GROWTH_MB:.0f} (warn-only, continuing)"
                )

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
            if telemetry.get("llm_parse_error"):
                llm_parse_failed += 1
        done_uids.append(quid)
        print(
            f"[{idx}/{len(selected)}] {quid} "
            f"valid={telemetry.get('valid_output')} fallback={telemetry.get('used_fallback')} "
            f"solve_sec={telemetry.get('stage_sec', {}).get('solve', 0):.2f} "
            f"overall_true={_fmt_score(evaluation.get('overall_true'))} "
            f"overall_parsed={_fmt_score(evaluation.get('overall_parsed'))}"
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
        "llm_backend_source": getattr(llm_client, "backend_source", "none"),
        "llm_parse_attempts": llm_parse_attempts,
        "llm_fixture_missing": llm_fixture_missing,
        "llm_parse_failed": llm_parse_failed,
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
    p.add_argument(
        "--uids-file",
        default=None,
        help="Path to a file with one uid per line (blank lines ignored); feeds run_split's "
        "uids= param, overriding --limit/--uid. Used by rehearse_phase2.py's chunked subprocess "
        "workers to bound each process to a small uid set.",
    )
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
    uids = None
    if args.uids_file:
        uids = [
            line.strip()
            for line in Path(args.uids_file).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    summary = run_split(
        args.split,
        method=method,
        limit=args.limit,
        uid=args.uid,
        uids=uids,
        resume=args.resume,
        budget_sec=args.budget_sec,
        lang=args.lang,
        work_dir=args.work_dir,
        results_dir=args.results_dir,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
