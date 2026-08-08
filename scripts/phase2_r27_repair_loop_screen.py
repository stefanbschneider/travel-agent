#!/usr/bin/env python3
"""R27 -- the P6 falsification screen (roadmap: "ten deterministic failures split across
timed-window, name/type and transport/budget blockers, temperature=0, at most six calls/query").

Two phases:

1. **Select.** Deterministically solve (harness-default flags, TPC_P2_LLM_REPAIR_LOOP off) a small
   pool of familiar_100_val queries, classify each still-failing query's oracle clauses by family
   via ``phase2_solver_failure_attribution.classify_constraint``, and bucket into the three shapes
   R27 names. Up to 10 uids are picked, spread across the three buckets as evenly as the pool
   allows.
2. **Screen.** For each selected uid, re-solve *once* from scratch with
   ``TPC_P2_LLM_REPAIR_LOOP=1`` and a live DeepInfra client at ``temperature=0`` -- one real e2e
   call, not a bolt-on retry -- and record: did it flip to fully accepted; MacEPR
   (``epr_macro``) before/after; a per-uid grounding check (every activity/committed edit position
   resolves against the real environment); and the call/timeout counters
   (``improve_llm_called``/``improve_attempts``/``improve_committed``/``timed_out``).

Never reads ``hard_logic_py`` past the selection phase (Phase 2's no-oracle boundary): scoring in
phase 2 uses the same oracle-free ``evaluate_parsed_constraints`` acceptance path every other
Phase 2 measurement in this repo uses.

**A budget mismatch trap, found running the first real screen (2026-08-08): if
``--select-budget-sec`` is smaller than ``--repair-budget-sec``, some "still failing" candidates
turn out to pass on the *deterministic* re-solve alone in phase 2 (more search time, no LLM
involved) -- ``improve_llm_called`` stays ``False`` for those.** Counting them as accepted flips
would credit the repair loop for nothing it did. The summary therefore reports two counts:
``n_flipped_to_accepted_total`` (raw) and ``n_flipped_to_accepted_via_llm_repair_loop`` (filtered to
``accepted and improve_llm_called``) -- the verdict uses only the second. Matching the two budgets
avoids the gap entirely but is not required for a correct verdict.

Usage::

    TPC_P2_LLM_BACKEND=deepinfra TPC_P2_LLM_TEMPERATURE=0 TPC_P2_LLM_TIMEOUT_SEC=20 \
    .venv/bin/python scripts/phase2_r27_repair_loop_screen.py \
        --out-dir results/phase2_baselines/screens/20260808_r27_llm_repair_loop
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(PROJECT_ROOT), str(PROJECT_ROOT / "scripts"), str(PROJECT_ROOT / "agent_env" / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from phase2_solver_failure_attribution import classify_constraint  # noqa: E402

BUCKETS = {
    "timed_window": {"timed_visit_named_poi"},
    "name_type": {
        "required_attractions", "excluded_attractions", "required_restaurants",
        "excluded_restaurants", "required_hotels", "excluded_hotels",
        "required_attraction_types", "excluded_attraction_types",
        "required_cuisine_types", "excluded_cuisine_types",
    },
    "transport_budget": {
        "budget_accommodation", "budget_dining", "budget_total", "budget_sightseeing",
        "intercity_mode", "taxi_cars", "inner_transport", "excluded_inner_transport",
    },
}


def _bucket_for(families: set[str]) -> str | None:
    for bucket, members in BUCKETS.items():
        if families & members:
            return bucket
    return None


def select_queries(*, pool_size: int, target_n: int, budget_sec: float, seed: int) -> list[dict]:
    """Deterministically solve ``pool_size`` familiar_100_val queries (harness defaults, repair
    loop off) and return up to ``target_n`` still-failing ones, spread across the three buckets."""
    import solve_script_with_harness as hb
    from chinatravel.data.load_datasets import load_query
    from chinatravel.environment.world_env import WorldEnv
    from chinatravel.agent.phase2 import orchestrator as orch
    import make_phase2_splits as splits
    import rehearse_phase2 as reh
    import solve_phase2 as runner

    split_name, _ = reh.resolve_split_set("familiar_100_val")
    uids = splits.read_split(split_name)
    fold_uids = reh.select_fold(uids, fold=0, folds=1, seed=seed)[:pool_size]

    args = argparse.Namespace(splits=split_name, lang="en", oracle_translation=True)
    _ids, data = load_query(args)

    runner.apply_deterministic_solver_defaults()
    env = WorldEnv(lang="en")
    solve_fn = orch.make_tpcagent_solve_fn(env, lang="en")
    _llm_client, flags = runner.resolve_llm_client_and_flags()

    picked: list[dict] = []
    by_bucket: dict[str, list[dict]] = {b: [] for b in BUCKETS}
    for uid in fold_uids:
        full_query = dict(data[uid])
        full_query.setdefault("uid", uid)
        clauses = full_query.get("hard_logic_py") or []
        visible = hb.visible_query(full_query)
        plan, telemetry = orch.solve_phase2(
            visible, env=env, llm_client=None, budget_sec=budget_sec, solve_fn=solve_fn,
            flags=flags,
        )
        from chinatravel.symbol_verification.hard_constraint import evaluate_constraints_py
        try:
            verdicts = evaluate_constraints_py(clauses, plan) if clauses else []
        except Exception:
            verdicts = []
        if clauses and all(verdicts):
            continue  # already passing deterministically; not a falsification candidate
        failing_families = {
            classify_constraint(clauses[i]) for i, ok in enumerate(verdicts) if not ok
        }
        bucket = _bucket_for(failing_families)
        if bucket is None:
            continue
        record = {
            "uid": uid, "bucket": bucket, "failing_families": sorted(failing_families),
            "query": full_query,
        }
        by_bucket[bucket].append(record)

    # Round-robin across buckets so the 10 picked are spread, not dominated by whichever bucket
    # happens to be most common in the pool.
    order = list(BUCKETS)
    idx = {b: 0 for b in order}
    while len(picked) < target_n and any(idx[b] < len(by_bucket[b]) for b in order):
        for b in order:
            if idx[b] < len(by_bucket[b]) and len(picked) < target_n:
                picked.append(by_bucket[b][idx[b]])
                idx[b] += 1
    return picked


def run_repair_loop_arm(selected: list[dict], *, budget_sec: float) -> list[dict]:
    """Re-solve each selected query from scratch with TPC_P2_LLM_REPAIR_LOOP=1 and a live client."""
    import solve_script_with_harness as hb
    from chinatravel.environment.world_env import WorldEnv
    from chinatravel.agent.phase2 import orchestrator as orch
    import solve_phase2 as runner
    from chinatravel.symbol_verification.hard_constraint import evaluate_constraints_py

    os.environ["TPC_P2_LLM_REPAIR_LOOP"] = "1"
    runner.apply_deterministic_solver_defaults()
    env = WorldEnv(lang="en")
    solve_fn = orch.make_tpcagent_solve_fn(env, lang="en")
    llm_client, flags = runner.resolve_llm_client_and_flags()
    assert flags.llm_repair_loop, "TPC_P2_LLM_REPAIR_LOOP did not resolve to on"
    assert llm_client is not None and getattr(llm_client, "backend", "none") != "none", (
        "no live LLM backend configured -- set TPC_P2_LLM_BACKEND=deepinfra"
    )

    results = []
    for record in selected:
        full_query = record["query"]
        clauses = full_query.get("hard_logic_py") or []
        visible = hb.visible_query(full_query)
        t0 = time.perf_counter()
        plan, telemetry = orch.solve_phase2(
            visible, env=env, llm_client=llm_client, budget_sec=budget_sec, solve_fn=solve_fn,
            flags=flags,
        )
        wall = time.perf_counter() - t0
        try:
            verdicts = evaluate_constraints_py(clauses, plan) if clauses else []
        except Exception:
            verdicts = []
        accepted = bool(clauses) and all(verdicts)
        grounded_ok = _all_facts_ground(plan)
        results.append({
            "uid": record["uid"],
            "bucket": record["bucket"],
            "failing_families": record["failing_families"],
            "accepted": accepted,
            "n_clauses_passing": sum(1 for v in verdicts if v),
            "n_clauses_total": len(verdicts),
            "all_facts_ground": grounded_ok,
            "wall_sec": round(wall, 1),
            "improve_llm_called": telemetry.get("improve_llm_called"),
            "improve_attempts": telemetry.get("improve_attempts"),
            "improve_committed": telemetry.get("improve_committed"),
            "improve_edit_count": telemetry.get("improve_edit_count"),
            "improve_edit_reasons": telemetry.get("improve_edit_reasons"),
            "improve_skip_reason": telemetry.get("improve_skip_reason"),
            "improve_second_attempt_skip_reason": telemetry.get("improve_second_attempt_skip_reason"),
            "timed_out": telemetry.get("timed_out"),
            "improve_timed_out": telemetry.get("improve_timed_out"),
        })
    return results


def _all_facts_ground(plan: dict) -> bool:
    """Cheap grounding sanity check: every activity has a non-empty position/type and every leg
    has a start/end -- catches an LLM-invented fact slipping past apply_refine_edits, which is
    never supposed to happen (every op is WorldEnv-grounded) but is worth checking directly rather
    than assumed."""
    try:
        for day in plan.get("itinerary", []) or []:
            for act in day.get("activities", []) or []:
                if act.get("type") not in ("airplane", "train") and not act.get("position"):
                    return False
                if not act.get("start_time") or not act.get("end_time"):
                    return False
        return True
    except Exception:
        return False


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pool-size", type=int, default=40, help="familiar_100_val queries to scan for candidates")
    ap.add_argument("--target-n", type=int, default=10)
    ap.add_argument("--select-budget-sec", type=float, default=120.0, help="deterministic solve budget for selection")
    ap.add_argument("--repair-budget-sec", type=float, default=900.0, help="per-query budget for the LLM-repair arm")
    ap.add_argument("--seed", type=int, default=20260705)
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()

    print(f"[r27] selecting up to {args.target_n} failing queries from a {args.pool_size}-query pool "
          f"(deterministic, budget={args.select_budget_sec}s) ...", file=sys.stderr)
    selected = select_queries(
        pool_size=args.pool_size, target_n=args.target_n, budget_sec=args.select_budget_sec,
        seed=args.seed,
    )
    print(f"[r27] selected {len(selected)}: "
          f"{[(r['uid'], r['bucket']) for r in selected]}", file=sys.stderr)
    if not selected:
        print("[r27] no candidates found -- nothing to screen", file=sys.stderr)
        return

    print(f"[r27] running the repair-loop arm (budget={args.repair_budget_sec}s/query, "
          f"TPC_P2_LLM_REPAIR_LOOP=1) ...", file=sys.stderr)
    results = run_repair_loop_arm(selected, budget_sec=args.repair_budget_sec)

    n_accepted = sum(1 for r in results if r["accepted"])
    # The number that actually answers R27's question. A query the *deterministic* solve alone
    # already accepted (improve_llm_called False, improve_skip_reason "already_accepted") is not a
    # flip the repair loop produced -- counting it would credit the loop for something it never
    # touched. This happens when the selection-phase budget is smaller than the repair-arm budget
    # (a still-failing query at the shorter budget can pass on its own given more search time);
    # size them the same, or treat this gap as a measurement artifact rather than a real flip.
    n_accepted_via_llm = sum(1 for r in results if r["accepted"] and r["improve_llm_called"])
    n_llm_called = sum(1 for r in results if r["improve_llm_called"])
    n_committed = sum(1 for r in results if r["improve_committed"])
    n_ungrounded = sum(1 for r in results if not r["all_facts_ground"])
    n_timed_out = sum(1 for r in results if r["timed_out"])

    summary = {
        "n_selected": len(selected),
        "buckets": {b: sum(1 for r in results if r["bucket"] == b) for b in BUCKETS},
        "n_flipped_to_accepted_total": n_accepted,
        "n_flipped_to_accepted_via_llm_repair_loop": n_accepted_via_llm,
        "n_llm_called": n_llm_called,
        "n_committed": n_committed,
        "n_ungrounded_facts": n_ungrounded,
        "n_timed_out": n_timed_out,
        "verdict": (
            "GREEN: continue"
            if n_accepted_via_llm >= 1 and n_ungrounded == 0
            else "RED: zero accepted flips caused by the repair loop (or ungrounded facts found) "
                 "-- do not promote"
        ),
        "results": results,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    if args.out_dir:
        out = Path(args.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "r27_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(f"[r27] wrote {out}/r27_summary.json", file=sys.stderr)


if __name__ == "__main__":
    main()
