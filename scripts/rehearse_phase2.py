#!/usr/bin/env python3
"""Phase 2 rehearsal runner (Task 7, basic).

Runs the no-oracle harness ("end-to-end") and/or the oracle-fed solver ("solver-only") over a
deterministic fold and prints the three-way attribution against the aspirational ceiling
(``results/best``):

    ceiling (oracle, unlimited + manual help)      = results/best
      gap = solver headroom lost to the time budget
    solver-only (oracle constraints, bounded)      = achievable in-harness solver ceiling
      gap = parsing loss
    end-to-end (no-oracle, bounded)                = what Phase 2 actually scores

Folds are drawn from the **validation** split by default. Touching the frozen **held-out test**
split requires ``--split-set test`` and prints a warning (see docs/tpc_phase2_eval.md).

Usage:
    python scripts/rehearse_phase2.py                       # both modes, val fold 0
    python scripts/rehearse_phase2.py --mode end-to-end --fold 0 --folds 10 --budget-sec 30
    python scripts/rehearse_phase2.py --split-set test --limit 20   # sparingly!
"""

from __future__ import annotations

import argparse
import os
import random
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "agent_env" / "scripts"))

import make_phase2_splits as splits  # noqa: E402

DEFAULT_SEED = 20260705
DEFAULT_FOLDS = 10


# --- Pure helpers (unit-tested) -------------------------------------------


def select_fold(uids: list[str], *, fold: int, folds: int, seed: int = DEFAULT_SEED) -> list[str]:
    """Deterministically partition ``uids`` into ``folds`` disjoint, covering parts; return one."""
    if folds < 1 or not (0 <= fold < folds):
        raise ValueError(f"fold {fold} out of range for {folds} folds")
    unique = sorted(set(uids))
    rng = random.Random(seed)
    rng.shuffle(unique)
    k, m = divmod(len(unique), folds)
    start = fold * k + min(fold, m)
    end = (fold + 1) * k + min(fold + 1, m)
    return sorted(unique[start:end])


def resolve_split_set(split_set: str) -> tuple[str, bool]:
    """Map 'val'/'test' to the split file name; warn (and flag) when the held-out test is used."""
    if split_set == "val":
        return "tpc_phase2_val", False
    if split_set == "test":
        print(
            "WARNING: using the HELD-OUT test split. Use this sparingly (final overfitting check "
            "only) — see docs/tpc_phase2_eval.md."
        )
        return "tpc_phase2_test", True
    raise ValueError(f"split_set must be 'val' or 'test', got {split_set!r}")


def format_attribution(*, ceiling: float, solver_only: float, end_to_end: float) -> str:
    """One-line three-way attribution with the two gaps."""
    solver_headroom = ceiling - solver_only
    parsing_loss = solver_only - end_to_end
    return (
        f"ceiling={ceiling:.1f} | solver-only={solver_only:.1f} | end-to-end={end_to_end:.1f}  "
        f"(solver headroom={solver_headroom:.1f}, parsing loss={parsing_loss:.1f})"
    )


# --- Metric helpers (reuse baseline evaluators) ---------------------------


def _fpr(metrics: dict, n: int) -> float:
    if not n:
        return 0.0
    return 100.0 * metrics.get("all_pass_count", 0) / n


def _evaluate_method(split_name: str, method: str, fold_uids: list[str], query_data: dict) -> dict:
    import solve_script_with_harness as hb

    metrics = hb.evaluate_split(split_name, method, fold_uids, query_data)
    return {"fpr": _fpr(metrics, len(fold_uids)), "raw": metrics}


# --- Mode runners (integration; touch WorldEnv/solver) --------------------


def _run_end_to_end(split_name, fold_uids, *, budget_sec):
    import solve_phase2 as runner

    method = f"phase2_e2e_{split_name}"
    runner.run_split(split_name, method=method, uids=fold_uids, budget_sec=budget_sec)
    return method


def _run_solver_only(split_name, fold_uids, *, budget_sec, lang="en"):
    """Feed oracle constraints to the solver, bounded + autonomous (Phase-1 path at Phase-2 budget)."""
    from func_timeout import FunctionTimedOut, func_timeout

    import solve_script_with_harness as hb
    from chinatravel.agent.load_model import init_llm
    from chinatravel.agent.tpc_agent.tpc_agent import TPCAgent
    from chinatravel.environment.world_env import WorldEnv

    os.environ["TPC_USE_ORACLE"] = "1"
    os.environ["TPC_SOLVE_BUDGET_SEC"] = str(max(float(budget_sec), 1.0))

    _, query_data = runner_load(split_name, lang)
    env = WorldEnv(lang=lang)
    agent = TPCAgent(env=env, backbone_llm=init_llm("TPCLLM"),
                     log_dir=os.path.join("cache", "phase2_solver_only"), lang=lang)
    agent.solve_budget_sec = max(float(budget_sec), 1.0)

    method = f"phase2_solver_only_{split_name}"
    out_dir = PROJECT_ROOT / "results" / method
    out_dir.mkdir(parents=True, exist_ok=True)
    for quid in fold_uids:
        q = query_data[quid]
        q.setdefault("uid", quid)
        try:
            _, plan = func_timeout(max(float(budget_sec), 1.0) + 5.0, agent.run, args=(q,))
        except (FunctionTimedOut, Exception):
            plan = {"people_number": q.get("people_number", 1), "start_city": q.get("start_city", ""),
                    "target_city": q.get("target_city", ""), "itinerary": []}
        hb.write_json(out_dir / f"{quid}.json", plan)
    return method


def runner_load(split_name, lang="en"):
    import solve_phase2 as runner

    return runner._load_queries(split_name, lang=lang)


# --- Orchestration --------------------------------------------------------


def rehearse(
    *,
    modes=("end-to-end", "solver-only"),
    split_set="val",
    fold=0,
    folds=DEFAULT_FOLDS,
    seed=DEFAULT_SEED,
    budget_sec=900.0,
    limit=None,
    lang="en",
) -> dict:
    split_name, _is_test = resolve_split_set(split_set)
    uids = splits.read_split(split_name)
    fold_uids = select_fold(uids, fold=fold, folds=folds, seed=seed)
    if limit:
        fold_uids = fold_uids[: int(limit)]

    _, query_data = runner_load(split_name, lang)

    report = {"split_name": split_name, "fold": fold, "folds": folds, "n": len(fold_uids), "modes": {}}

    if "end-to-end" in modes:
        m = _run_end_to_end(split_name, fold_uids, budget_sec=budget_sec)
        report["modes"]["end-to-end"] = _evaluate_method(split_name, m, fold_uids, query_data)
    if "solver-only" in modes:
        m = _run_solver_only(split_name, fold_uids, budget_sec=budget_sec, lang=lang)
        report["modes"]["solver-only"] = _evaluate_method(split_name, m, fold_uids, query_data)

    # Ceiling from results/best (only meaningful when not writing to a temp results_dir).
    try:
        report["ceiling"] = _evaluate_method(split_name, "best", fold_uids, query_data)
    except Exception as exc:
        report["ceiling"] = {"fpr": 0.0, "error": str(exc)}

    ceiling = report.get("ceiling", {}).get("fpr", 0.0)
    solver = report["modes"].get("solver-only", {}).get("fpr", 0.0)
    e2e = report["modes"].get("end-to-end", {}).get("fpr", 0.0)
    print(f"\nFold {fold}/{folds} of {split_name} (n={len(fold_uids)}), FPR:")
    print("  " + format_attribution(ceiling=ceiling, solver_only=solver, end_to_end=e2e))
    return report


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=["end-to-end", "solver-only", "both"], default="both")
    p.add_argument("--split-set", choices=["val", "test"], default="val")
    p.add_argument("--fold", type=int, default=0)
    p.add_argument("--folds", type=int, default=DEFAULT_FOLDS)
    p.add_argument("--seed", type=int, default=DEFAULT_SEED)
    p.add_argument(
        "--budget-sec",
        type=float,
        default=900.0,
        help="Per-query budget (default 900s = 15 min, TBC; 300s = 5 min alt). Use small values "
        "with --limit/--folds for quick smoke runs.",
    )
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--lang", default="en", choices=["en", "zh"])
    return p.parse_args()


def main() -> None:
    args = parse_args()
    modes = ("end-to-end", "solver-only") if args.mode == "both" else (args.mode,)
    rehearse(
        modes=modes,
        split_set=args.split_set,
        fold=args.fold,
        folds=args.folds,
        seed=args.seed,
        budget_sec=args.budget_sec,
        limit=args.limit,
        lang=args.lang,
    )


if __name__ == "__main__":
    main()
