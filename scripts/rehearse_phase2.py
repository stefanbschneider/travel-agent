#!/usr/bin/env python3
"""Phase 2 rehearsal runner.

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
    .venv/bin/python scripts/rehearse_phase2.py                       # both modes, val fold 0
    .venv/bin/python scripts/rehearse_phase2.py --mode end-to-end --fold 0 --folds 10 --budget-sec 30
    .venv/bin/python scripts/rehearse_phase2.py --split-set test --limit 20   # sparingly!
"""

from __future__ import annotations

import argparse
import os
import random
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psutil

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "agent_env" / "scripts"))
# Some solver-only imports (chinatravel/agent/tpc_agent/tpc_agent.py) use `from agent...` rather
# than `from chinatravel.agent...`; include chinatravel/ on sys.path so _run_solver_only works
# standalone (previously it only worked when end-to-end mode ran first in the same process and
# happened to add this path as a side effect of importing tpc_llm.py).
CHINATRAVEL_ROOT = str(PROJECT_ROOT / "chinatravel")
if CHINATRAVEL_ROOT not in sys.path:
    sys.path.insert(0, CHINATRAVEL_ROOT)

import make_phase2_splits as splits  # noqa: E402
from chinatravel.agent.phase2 import orchestrator as orch  # noqa: E402

DEFAULT_SEED = 20260705
DEFAULT_FOLDS = 10
# Queries per subprocess for the chunked rehearsal. Each subprocess's memory (and any
# ``func_timeout`` thread that survives a timeout) is fully reclaimed by the OS when it exits, so a
# small chunk bounds cumulative growth across a large fold. Override with `P2_CHUNK`; <=0 disables
# chunking for a single in-process run, useful for short smoke runs where startup overhead dominates.
DEFAULT_CHUNK = int(os.environ.get("P2_CHUNK", "5") or "5")
# How many chunk subprocesses to run concurrently (each chunk subprocess still solves its own
# queries sequentially; this parallelizes *across* chunks). Each query's CP-SAT solve defaults to
# a single search worker (chinatravel/agent/tpc_agent/cp_solver.py), so N concurrent chunks uses
# ~N cores; per-process RSS floor is ~250MB (see the soak measurement in
# docs/tpc_phase2_design.md), so memory is not the limiting factor on a typical dev box -- size
# this to (core count - 1), leaving a core for the OS/orchestrator. 1 (default) preserves the
# original sequential-chunk behavior exactly. Override with the P2_PARALLEL env var.
DEFAULT_PARALLEL = int(os.environ.get("P2_PARALLEL", "1") or "1")


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
    """Map a split-set alias to its split file name; flag a held-out split when used.

    ``val``/``test`` partition the repository-local tpc_phase1 queries. ``familiar_100`` selects the
    organizers' full imported official development set (tpc_phase2_familiar_100, 100 records).
    ``familiar_100_val`` / ``familiar_100_test`` are its deterministic 80/20 partition
    (scripts/make_familiar_splits.py): screens and development gates use the val split;
    ``familiar_100_test`` is the held-out overfitting tripwire and prints a warning. Neither
    familiar split is the organizer final held-out set (see docs/tpc_phase2_eval.md).
    """
    if split_set == "val":
        return "tpc_phase2_val", False
    if split_set == "familiar_100":
        return "tpc_phase2_familiar_100", False
    if split_set == "familiar_100_val":
        return "tpc_phase2_familiar_100_val", False
    if split_set == "familiar_100_test":
        print(
            "WARNING: using the HELD-OUT familiar-100 test split. Use this sparingly (occasional "
            "overfitting tripwire only, never a per-change signal) — see docs/tpc_phase2_eval.md."
        )
        return "tpc_phase2_familiar_100_test", True
    if split_set == "test":
        print(
            "WARNING: using the HELD-OUT test split. Use this sparingly (final overfitting check "
            "only) — see docs/tpc_phase2_eval.md."
        )
        return "tpc_phase2_test", True
    raise ValueError(
        f"split_set must be 'val', 'test', 'familiar_100', 'familiar_100_val', or "
        f"'familiar_100_test', got {split_set!r}"
    )


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


def _float_stats(values: list[float]) -> dict:
    vals = [float(v) for v in values]
    if not vals:
        return {"count": 0, "mean": 0.0, "min": 0.0, "max": 0.0, "std": 0.0}
    return {
        "count": len(vals),
        "mean": statistics.fmean(vals),
        "min": min(vals),
        "max": max(vals),
        "std": statistics.pstdev(vals),
    }


def _quality_metrics(split_name: str, method: str, fold_uids: list[str], query_data: dict) -> dict:
    """Continuous quality metrics from per-query evaluate_one, not just binary FPR."""
    import solve_script_with_harness as hb

    result_dir = PROJECT_ROOT / "results" / method
    overall_true_vals: list[float] = []
    overall_parsed_vals: list[float] = []
    fpr_true_vals: list[float] = []
    fpr_parsed_vals: list[float] = []

    missing: list[str] = []
    invalid_json: list[str] = []
    eval_failed: list[str] = []

    for uid in fold_uids:
        result_path = result_dir / f"{uid}.json"
        if not result_path.exists():
            missing.append(uid)
            continue
        try:
            plan = hb.read_json(result_path)
        except Exception:
            invalid_json.append(uid)
            continue

        query = query_data[uid]
        query.setdefault("uid", uid)
        try:
            row = hb.evaluate_one(split_name, uid, query, plan)
        except Exception:
            eval_failed.append(uid)
            continue

        overall_true_vals.append(float(row.get("overall_true", 0.0)))
        overall_parsed_vals.append(float(row.get("overall_parsed", 0.0)))
        fpr_true_vals.append(float(row.get("fpr_true", 0.0)))
        fpr_parsed_vals.append(float(row.get("fpr_parsed", 0.0)))

    return {
        "requested": len(fold_uids),
        "evaluated": len(overall_true_vals),
        "missing": len(missing),
        "invalid_json": len(invalid_json),
        "eval_failed": len(eval_failed),
        "overall_true": _float_stats(overall_true_vals),
        "overall_parsed": _float_stats(overall_parsed_vals),
        "fpr_true": _float_stats(fpr_true_vals),
        "fpr_parsed": _float_stats(fpr_parsed_vals),
    }


def _valid_plan_shape(plan) -> bool:
    return isinstance(plan, dict) and isinstance(plan.get("itinerary"), list)


def _minimal_plan(query: dict) -> dict:
    return {
        "people_number": query.get("people_number", 1),
        "start_city": query.get("start_city", ""),
        "target_city": query.get("target_city", ""),
        "itinerary": [],
    }


def _recover_or_fallback(agent, query: dict) -> dict:
    recovered = _recover_plan(agent)
    if _valid_plan_shape(recovered):
        return recovered
    return _minimal_plan(query)


def _recover_plan(agent):
    recovered = None
    try:
        recovered = agent.get_timeout_recovery_plan()
    except Exception:
        recovered = None
    if _valid_plan_shape(recovered):
        return recovered
    return None


def _evaluate_method(split_name: str, method: str, fold_uids: list[str], query_data: dict) -> dict:
    import solve_script_with_harness as hb

    metrics = hb.evaluate_split(split_name, method, fold_uids, query_data)
    quality = _quality_metrics(split_name, method, fold_uids, query_data)
    return {"fpr": _fpr(metrics, len(fold_uids)), "raw": metrics, "quality": quality}


# --- Mode runners (integration; touch WorldEnv/solver) --------------------


def clear_method_outputs(method: str, uids: list[str]) -> int:
    """Delete per-uid result files and run dirs for ``method`` so a rerun is fresh.

    Without this, ``resume=True`` silently reuses plans produced by older code or a different
    budget, which contaminates baseline rows. Returns the number of result files removed.
    """
    removed = 0
    for uid in uids:
        result_path = PROJECT_ROOT / "results" / method / f"{uid}.json"
        if result_path.exists():
            result_path.unlink()
            removed += 1
        run_dir = PROJECT_ROOT / "agent_env" / "runs" / method / uid
        if run_dir.is_dir():
            shutil.rmtree(run_dir, ignore_errors=True)
    return removed


def _run_end_to_end(split_name, fold_uids, *, budget_sec):
    import solve_phase2 as runner

    method = f"phase2_e2e_{split_name}"
    runner.run_split(
        split_name,
        method=method,
        uids=fold_uids,
        budget_sec=budget_sec,
        resume=True,
    )
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
    run_dir = PROJECT_ROOT / "agent_env" / "runs" / method
    run_dir.mkdir(parents=True, exist_ok=True)

    for quid in fold_uids:
        q = query_data[quid]
        q.setdefault("uid", quid)
        t0 = time.perf_counter()
        telemetry = {
            "uid": quid,
            "budget_sec": float(budget_sec),
            "timed_out": False,
            "completed_without_timeout": False,
            "recovered_from_timeout": False,
            "recovered_from_error": False,
            "used_fallback": False,
            "valid_output": False,
            "error": None,
            "stage_sec": {"solve": 0.0},
        }
        agent.reset_timeout_recovery_plan()
        try:
            _, plan = func_timeout(max(float(budget_sec), 1.0) + 5.0, agent.run, args=(q,))
        except FunctionTimedOut:
            telemetry["timed_out"] = True
            recovered = _recover_plan(agent)
            if recovered is not None:
                telemetry["recovered_from_timeout"] = True
                plan = recovered
            else:
                telemetry["used_fallback"] = True
                plan = _minimal_plan(q)
        except Exception as exc:
            telemetry["error"] = f"solve: {exc}"
            recovered = _recover_plan(agent)
            if recovered is not None:
                telemetry["recovered_from_error"] = True
                plan = recovered
            else:
                telemetry["used_fallback"] = True
                plan = _minimal_plan(q)

        telemetry["stage_sec"]["solve"] = time.perf_counter() - t0
        telemetry["valid_output"] = _valid_plan_shape(plan)
        telemetry["completed_without_timeout"] = bool(
            (not telemetry["timed_out"]) and (telemetry.get("error") in (None, ""))
        )
        telemetry["rss_mb"] = psutil.Process().memory_info().rss / (1024 * 1024)

        hb.write_json(out_dir / f"{quid}.json", plan)
        hb.write_json(run_dir / quid / "telemetry.json", telemetry)
    return method


# --- Chunked subprocess execution for larger end-to-end folds -------------------------------
#
# In-process, a large fold accumulates memory across queries: a timed-out solve's thread can't be
# killed by func_timeout and keeps running in the background (verified: RSS grows and a stray
# thread is still alive after a timeout), and every query adds to a single process's heap. Running
# each chunk of uids in its own subprocess bounds that growth -- the OS reclaims everything,
# leaked threads included, when the chunk's process exits.


def _split_into_chunks(uids: list[str], chunk_size: int) -> list[list[str]]:
    if chunk_size <= 0:
        return [list(uids)] if uids else []
    return [list(uids[i : i + chunk_size]) for i in range(0, len(uids), chunk_size)]


def _write_uids_file(uids: list[str]) -> Path:
    fd, name = tempfile.mkstemp(prefix="phase2_uids_", suffix=".txt")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("\n".join(uids))
    return Path(name)


def _split_set_for(split_name: str) -> str:
    if split_name == "tpc_phase2_val":
        return "val"
    if split_name == "tpc_phase2_test":
        return "test"
    if split_name == "tpc_phase2_familiar_100":
        return "familiar_100"
    if split_name == "tpc_phase2_familiar_100_val":
        return "familiar_100_val"
    if split_name == "tpc_phase2_familiar_100_test":
        return "familiar_100_test"
    raise ValueError(f"unknown Phase 2 split name: {split_name!r}")


def _run_chunk_subprocess(cmd: list[str], uids_file: Path) -> None:
    try:
        subprocess.run(cmd, check=True, cwd=str(PROJECT_ROOT))
    finally:
        uids_file.unlink(missing_ok=True)


def _run_chunks(chunks: list[list[str]], build_cmd, *, parallel: int) -> None:
    """Dispatch one subprocess per chunk. ``parallel<=1`` runs them sequentially (original
    behavior, byte-for-byte); ``parallel>1`` runs up to that many chunk subprocesses concurrently
    via a thread pool (each thread just blocks in ``subprocess.run``, so this costs threads, not
    extra memory). Safe because chunks partition ``fold_uids`` disjointly -- no two chunks ever
    write the same per-uid result/telemetry/evaluation file, and the per-chunk method-level
    summary.json a race could clobber is not read by the aggregation path (see
    ``_evaluate_method``, which reads per-uid files directly)."""
    jobs = []
    for chunk in chunks:
        uids_file = _write_uids_file(chunk)
        jobs.append((build_cmd(uids_file), uids_file))

    if parallel <= 1:
        for cmd, uids_file in jobs:
            _run_chunk_subprocess(cmd, uids_file)
        return

    with ThreadPoolExecutor(max_workers=parallel) as pool:
        futures = [pool.submit(_run_chunk_subprocess, cmd, uids_file) for cmd, uids_file in jobs]
        for f in futures:
            f.result()  # surface the first exception (subprocess.run(check=True) raises)


def _run_end_to_end_chunked(split_name, fold_uids, *, budget_sec, lang, chunk_size, parallel=1):
    """Same contract as ``_run_end_to_end`` (returns the method name), but runs each chunk of
    uids as its own ``solve_phase2.py`` subprocess so per-chunk memory is fully reclaimed."""
    method = f"phase2_e2e_{split_name}"
    solve_script = PROJECT_ROOT / "agent_env" / "scripts" / "solve_phase2.py"

    def build_cmd(uids_file: Path) -> list[str]:
        return [
            sys.executable,
            str(solve_script),
            "--split", split_name,
            "--method", method,
            "--uids-file", str(uids_file),
            "--budget-sec", str(budget_sec),
            "--lang", lang,
            "--resume",
        ]

    _run_chunks(_split_into_chunks(fold_uids, chunk_size), build_cmd, parallel=parallel)
    return method


def _run_solver_only_chunked(split_name, fold_uids, *, budget_sec, lang, chunk_size, parallel=1):
    """Same contract as ``_run_solver_only``, but each chunk is a self-exec worker subprocess
    (``--worker solver-only``) so leaked func_timeout/CP-SAT threads die with the subprocess."""
    method = f"phase2_solver_only_{split_name}"
    this_script = Path(__file__).resolve()

    def build_cmd(uids_file: Path) -> list[str]:
        return [
            sys.executable,
            str(this_script),
            "--worker", "solver-only",
            "--uids-file", str(uids_file),
            "--split-set", _split_set_for(split_name),
            "--budget-sec", str(budget_sec),
            "--lang", lang,
        ]

    _run_chunks(_split_into_chunks(fold_uids, chunk_size), build_cmd, parallel=parallel)
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
    budget_sec=orch.DEFAULT_BUDGET_SEC,
    limit=None,
    lang="en",
    fresh=False,
    chunk_size=DEFAULT_CHUNK,
    parallel=DEFAULT_PARALLEL,
    fast_fpr=False,
) -> dict:
    split_name, _is_test = resolve_split_set(split_set)
    uids = splits.read_split(split_name)
    fold_uids = select_fold(uids, fold=fold, folds=folds, seed=seed)
    if limit:
        fold_uids = fold_uids[: int(limit)]

    _, query_data = runner_load(split_name, lang)

    report = {
        "split_name": split_name,
        "fold": fold,
        "folds": folds,
        "n": len(fold_uids),
        "fresh": bool(fresh),
        "chunk_size": int(chunk_size),
        "parallel": int(parallel),
        "fast_fpr": bool(fast_fpr),
        "modes": {},
    }

    # Eval-tooling only: never set by run_split and never a library default. See
    # TPC_SOLVE_STOP_AT_ACCEPT in tpc_agent.py. Chunk subprocesses inherit this process's
    # environment, so setting it here before dispatching them is sufficient; restored afterward
    # so it never leaks into an unrelated call in the same process.
    _FAST_FPR_ENV = "TPC_SOLVE_STOP_AT_ACCEPT"
    _prev_fast_fpr_env = os.environ.get(_FAST_FPR_ENV)
    if fast_fpr:
        os.environ[_FAST_FPR_ENV] = "1"

    try:
        return _rehearse_body(
            report, split_name=split_name, fold_uids=fold_uids, query_data=query_data,
            modes=modes, budget_sec=budget_sec, lang=lang, fresh=fresh, chunk_size=chunk_size,
            parallel=parallel, fold=fold, folds=folds,
        )
    finally:
        if fast_fpr:
            if _prev_fast_fpr_env is None:
                os.environ.pop(_FAST_FPR_ENV, None)
            else:
                os.environ[_FAST_FPR_ENV] = _prev_fast_fpr_env


def _rehearse_body(
    report, *, split_name, fold_uids, query_data, modes, budget_sec, lang, fresh, chunk_size,
    parallel, fold, folds,
) -> dict:
    if "end-to-end" in modes:
        if fresh:
            removed = clear_method_outputs(f"phase2_e2e_{split_name}", fold_uids)
            if removed:
                print(f"fresh: cleared {removed} stale end-to-end result(s) for this fold")
        if chunk_size > 0:
            m = _run_end_to_end_chunked(
                split_name, fold_uids, budget_sec=budget_sec, lang=lang, chunk_size=chunk_size,
                parallel=parallel,
            )
        else:
            m = _run_end_to_end(split_name, fold_uids, budget_sec=budget_sec)
        report["modes"]["end-to-end"] = _evaluate_method(split_name, m, fold_uids, query_data)
    if "solver-only" in modes:
        if chunk_size > 0:
            m = _run_solver_only_chunked(
                split_name, fold_uids, budget_sec=budget_sec, lang=lang, chunk_size=chunk_size,
                parallel=parallel,
            )
        else:
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
    p.add_argument(
        "--split-set",
        choices=["val", "test", "familiar_100", "familiar_100_val", "familiar_100_test"],
        default="val",
    )
    p.add_argument("--fold", type=int, default=0)
    p.add_argument("--folds", type=int, default=DEFAULT_FOLDS)
    p.add_argument("--seed", type=int, default=DEFAULT_SEED)
    p.add_argument(
        "--budget-sec",
        type=float,
        default=orch.DEFAULT_BUDGET_SEC,
        help="Per-query local sensitivity budget (default: 300 s). 900 s is a longer local "
        "setting, not an organizer-confirmed limit. Use small values with --limit/--folds for "
        "quick smoke runs.",
    )
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--lang", default="en", choices=["en", "zh"])
    p.add_argument(
        "--fresh",
        action="store_true",
        help="Clear this fold's end-to-end results first so the run reflects the current code "
        "instead of resuming stale plans (recommended for any run used as a baseline).",
    )
    p.add_argument(
        "--chunk-size",
        type=int,
        default=DEFAULT_CHUNK,
        help="Queries per subprocess (default from P2_CHUNK env, else 5); <=0 runs everything "
        "in-process (original behavior, no subprocess isolation).",
    )
    p.add_argument(
        "--parallel",
        type=int,
        default=DEFAULT_PARALLEL,
        help="Chunk subprocesses to run concurrently (default from P2_PARALLEL env, else 1 = "
        "sequential, original behavior). Each query's CP-SAT solve uses 1 core by default, so "
        "size this to (core count - 1). Only applies when --chunk-size > 0. Memory is not "
        "usually the limit -- see docs/tpc_phase2_design.md for the per-process RSS floor.",
    )
    p.add_argument(
        "--worker",
        choices=["solver-only"],
        default=None,
        help=argparse.SUPPRESS,  # internal: self-exec entry point used by _run_solver_only_chunked
    )
    p.add_argument("--uids-file", default=None, help=argparse.SUPPRESS)  # internal, with --worker
    p.add_argument(
        "--fast-fpr",
        action="store_true",
        help="Eval-tooling only, never set by the real harness: stop each "
        "query's solve as soon as an accepted plan is found instead of spending the rest of the "
        "budget polishing preference score (TPC_SOLVE_STOP_AT_ACCEPT). Cuts iteration cost but "
        "the resulting FPR is a different, uncalibrated metric -- never compare its rows "
        "directly against normal ones.",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    if args.worker == "solver-only":
        # Self-exec worker: solve exactly the uids in --uids-file and exit. No aggregation here --
        # the parent process (_run_solver_only_chunked) evaluates once all chunks have run.
        split_name, _is_test = resolve_split_set(args.split_set)
        uids = [
            line.strip()
            for line in Path(args.uids_file).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        _run_solver_only(split_name, uids, budget_sec=args.budget_sec, lang=args.lang)
        return
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
        fresh=args.fresh,
        chunk_size=args.chunk_size,
        parallel=args.parallel,
        fast_fpr=args.fast_fpr,
    )


if __name__ == "__main__":
    main()
