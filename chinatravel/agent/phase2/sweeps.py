"""Multi-pass, parallel, deadline-bounded scheduling of a whole split.

The organizers give the entire 100-query run a single 5-hour wall-clock budget and no per-query
timeout (confirmed 2026-08-04), and score every query equally. A one-pass "spend 1/n of the time
on each query in order" loop is the wrong shape for that:

- it can sink a large budget into a query that is unsolvable for structural reasons while a query
  later in the split never gets the 30 seconds that would have solved it;
- it stops as soon as it has visited every query, even with hours left;
- it spends the same effort on preference polish as on constraint satisfaction, though the
  evaluator zeroes every preference term of a query that fails its constraints.

So this module runs *sweeps* instead:

1. **triage** -- every query once, at a small budget, cheapest wins first. After this pass every
   query has a real plan on disk.
2. **repair** -- only the queries whose plan does not satisfy its constraints, at a larger budget
   each pass, ordered by how close they already are (most nearly-passing first).
3. **polish** -- once constraints are satisfied everywhere (or repair has stopped making
   progress), re-solve constraint-satisfying queries with the biggest preference headroom.

Every pass is executed across worker processes, since the evaluation host assigns 16 logical CPUs
and a single query's solve is single-threaded. Every result is scored oracle-free
(``selfscore``) and kept only if it beats what is already on disk, so no pass can regress a
query, and the run can be killed at any instant without losing the best plan found so far.
"""

from __future__ import annotations

import math
import os
import sys
import time
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from . import fallback as fallback_mod
from . import orchestrator as orch
from . import selfscore

PROJECT_ROOT = Path(__file__).resolve().parents[3]

# --- Budget shape -----------------------------------------------------------------------------
# Triage stays deliberately small: its job is to bank the easy wins and to guarantee every query
# has a real plan early, not to solve the hard ones.
DEFAULT_TRIAGE_CAP_SEC = 120.0
DEFAULT_TRIAGE_FRACTION = 0.25
# Later passes may spend up to half of what is left, and no single query may exceed the budget
# our development gates ran at -- beyond it the solver's own convergence patience has long since
# stopped finding anything.
DEFAULT_PASS_FRACTION = 0.5
DEFAULT_MAX_QUERY_SEC = 900.0
DEFAULT_MIN_QUERY_SEC = 20.0
# Re-solving a query at (nearly) the budget it already had reproduces its previous plan and wastes
# the envelope, so a query is only revisited when its new budget is meaningfully larger.
MIN_BUDGET_GROWTH = 1.25
# Two escalations that improve nothing mean the remaining failures are structural, not starved.
MAX_STALLED_REPAIR_PASSES = 2
DEFAULT_MAX_PASSES = 24


def default_workers() -> int:
    """One process per available CPU, leaving one for the parent.

    The evaluation host assigns all 16 of its logical CPUs to the harness process and a single
    query's solve is single-threaded (CP-SAT ``num_search_workers`` 1), so the cores are otherwise
    idle. ``TPC_P2_WORKERS`` overrides.
    """
    override = os.environ.get("TPC_P2_WORKERS")
    if override not in (None, ""):
        try:
            return max(1, int(override))
        except ValueError:
            pass
    return max(1, (os.cpu_count() or 2) - 1)


def rounds_needed(n_uids: int, workers: int) -> int:
    """Wall-clock rounds a pass takes: with W workers, W queries run at once."""
    if n_uids <= 0:
        return 0
    return math.ceil(n_uids / max(1, workers))


def pass_budget_sec(
    remaining_sec: float,
    n_uids: int,
    *,
    workers: int,
    fraction: float,
    cap_sec: float,
    floor_sec: float = DEFAULT_MIN_QUERY_SEC,
) -> float:
    """Per-query budget for one pass.

    Divides by the number of *rounds*, not by the number of queries: parallel workers make a pass
    over ``n`` queries cost ``ceil(n / workers)`` query-budgets of wall clock, not ``n``. This is
    what converts idle cores into per-query search time rather than just into a shorter run.
    """
    rounds = rounds_needed(n_uids, workers)
    if rounds == 0:
        return 0.0
    share = max(float(remaining_sec), 0.0) * float(fraction) / rounds
    return max(float(floor_sec), min(float(cap_sec), share))


def pass_fits(remaining_sec: float, budget_sec: float, n_uids: int, workers: int) -> bool:
    """Whether a pass at this budget can finish inside the time left."""
    return rounds_needed(n_uids, workers) * budget_sec <= max(float(remaining_sec), 0.0)


def repair_order(scores: dict[str, selfscore.PlanScore | None]) -> list[str]:
    """Failing queries, most-nearly-passing first.

    Ratio of satisfied parsed constraints first, then the oracle-free overall. Cheap wins are
    taken before expensive ones, which is what keeps a hard query from starving easy ones.
    """

    def key(uid: str):
        score = scores.get(uid)
        if score is None:
            return (0.0, 0.0, uid)
        ratio = (
            score.logical_satisfied / score.logical_total if score.logical_total else 1.0
        )
        return (ratio, score.overall, uid)

    failing = [uid for uid, score in scores.items() if score is None or not score.constraints_ok]
    return sorted(failing, key=key, reverse=True)


def polish_order(scores: dict[str, selfscore.PlanScore | None]) -> list[str]:
    """Constraint-satisfying queries, largest remaining preference gain first."""
    passing = [uid for uid, score in scores.items() if score is not None and score.constraints_ok]
    return sorted(passing, key=lambda uid: selfscore.max_remaining_gain(scores[uid]), reverse=True)


@dataclass
class PassRecord:
    index: int
    kind: str
    n_uids: int
    budget_sec: float
    workers: int
    improved: int = 0
    completed: int = 0
    failed: int = 0
    elapsed_sec: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "kind": self.kind,
            "queries": self.n_uids,
            "budget_sec": round(self.budget_sec, 1),
            "workers": self.workers,
            "improved": self.improved,
            "completed": self.completed,
            "failed": self.failed,
            "elapsed_sec": round(self.elapsed_sec, 1),
        }


@dataclass
class SweepConfig:
    workers: int = 1
    triage_cap_sec: float = DEFAULT_TRIAGE_CAP_SEC
    triage_fraction: float = DEFAULT_TRIAGE_FRACTION
    pass_fraction: float = DEFAULT_PASS_FRACTION
    max_query_sec: float = DEFAULT_MAX_QUERY_SEC
    min_query_sec: float = DEFAULT_MIN_QUERY_SEC
    max_passes: int = DEFAULT_MAX_PASSES
    lang: str = "en"
    # Extra grace, per query, between the orchestrator's own internal timeout and the point at
    # which the parent stops waiting on a straggler.
    straggler_grace_sec: float = 30.0
    passes: list[PassRecord] = field(default_factory=list)

    # Every knob that shapes how the envelope is spent is env-overridable, so an A/B of the pass
    # shape needs no code edit -- see docs/tpc_phase2_eval_roadmap.md.
    ENV_OVERRIDES = {
        "triage_cap_sec": "TPC_P2_TRIAGE_CAP_SEC",
        "triage_fraction": "TPC_P2_TRIAGE_FRACTION",
        "pass_fraction": "TPC_P2_PASS_FRACTION",
        "max_query_sec": "TPC_P2_MAX_QUERY_SEC",
        "min_query_sec": "TPC_P2_MIN_QUERY_SEC",
        "max_passes": "TPC_P2_MAX_PASSES",
    }

    def apply_env_overrides(self, env: Any = None) -> "SweepConfig":
        env_map = os.environ if env is None else env
        for attr, name in self.ENV_OVERRIDES.items():
            raw = env_map.get(name)
            if raw in (None, ""):
                continue
            try:
                value = int(raw) if attr == "max_passes" else float(raw)
            except ValueError:
                continue
            setattr(self, attr, value)
        return self


# --- Worker side ------------------------------------------------------------------------------
# Module-level so the functions are importable by name in a spawned worker as well as inherited
# by a forked one. One WorldEnv + TPCAgent per process, built once and reused for every task.

_WORKER: dict[str, Any] = {}


def _load_runner_module():
    """The runner script owns flag/LLM-client resolution; reuse it rather than duplicating it.

    ``agent_env/scripts`` is not a package, so this mirrors how the runner itself imports its
    sibling module.
    """
    scripts_dir = PROJECT_ROOT / "agent_env" / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    import solve_phase2

    return solve_phase2


def init_worker(lang: str = "en") -> None:
    """Build this process's environment, solver, LLM client and flags exactly once."""
    if _WORKER.get("ready"):
        return
    runner = _load_runner_module()
    runner.apply_deterministic_solver_defaults()

    from chinatravel.environment.world_env import WorldEnv

    env = WorldEnv(lang=lang)
    llm_client, flags = runner.resolve_llm_client_and_flags()
    _WORKER.update(
        ready=True,
        lang=lang,
        env=env,
        solve_fn=orch.make_tpcagent_solve_fn(env, lang=lang),
        llm_client=llm_client,
        flags=flags,
    )


def solve_one(task: dict) -> dict:
    """Solve and oracle-free-score one query. Returns a picklable result dict.

    Never raises: a worker that dies takes the pool down with it, so a failing query degrades to
    a recorded error and a fallback plan instead.
    """
    uid = task["uid"]
    visible_query = task["query"]
    budget_sec = float(task["budget_sec"])
    started = time.monotonic()
    try:
        init_worker(task.get("lang", "en"))
        plan, telemetry = orch.solve_phase2(
            visible_query,
            env=_WORKER["env"],
            llm_client=_WORKER["llm_client"],
            budget_sec=budget_sec,
            solve_fn=_WORKER["solve_fn"],
            flags=_WORKER["flags"],
        )
        score = selfscore.score_plan(
            plan,
            visible_query,
            parsed_constraints=task.get("parsed_constraints"),
            lang=task.get("lang", "en"),
            uid=uid,
        )
        telemetry["llm_backend_source"] = getattr(_WORKER["llm_client"], "backend_source", "none")
        telemetry["pass_kind"] = task.get("kind")
        telemetry["self_score"] = score.to_dict()
        return {
            "uid": uid,
            "plan": plan,
            "telemetry": telemetry,
            "score": score.to_dict(),
            "wall_sec": time.monotonic() - started,
        }
    except Exception as exc:  # pragma: no cover - defensive; solve_phase2 already swallows
        return {
            "uid": uid,
            "plan": fallback_mod.minimal_plan(visible_query),
            "telemetry": {"uid": uid, "error": f"worker: {type(exc).__name__}: {exc}"},
            "score": selfscore.ZERO_SCORE.to_dict(),
            "wall_sec": time.monotonic() - started,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _score_from_dict(data: dict | None) -> selfscore.PlanScore | None:
    if not data:
        return None
    fields = {
        key: value
        for key, value in data.items()
        if key in selfscore.PlanScore.__dataclass_fields__
    }
    return selfscore.PlanScore(**fields)


# --- Driver -----------------------------------------------------------------------------------


def run_sweeps(
    *,
    uids: Sequence[str],
    queries: dict[str, dict],
    deadline: float,
    config: SweepConfig,
    on_result: Callable[[str, dict, selfscore.PlanScore, dict, bool], None],
    best: dict[str, selfscore.PlanScore] | None = None,
    parsed_constraints: dict[str, dict] | None = None,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Run triage -> repair -> polish passes until the deadline.

    ``queries`` holds **visible** queries only. ``on_result(uid, plan, score, telemetry, improved)``
    is called for every completed attempt, with ``improved`` saying whether it beat the incumbent
    for that query. The caller owns writing: persisting an improved plan immediately is what makes
    the run safe to kill at any moment. Returns a summary dict.
    """
    best_scores: dict[str, selfscore.PlanScore] = dict(best or {})
    last_budget: dict[str, float] = {}
    stalled_repairs = 0
    executor = None

    def remaining() -> float:
        return deadline - time.monotonic()

    try:
        if config.workers > 1:
            executor = _make_executor(config)

        for index in range(1, config.max_passes + 1):
            chosen = _choose_pass(
                index=index,
                uids=uids,
                best_scores=best_scores,
                stalled_repairs=stalled_repairs,
                last_budget=last_budget,
                remaining_sec=remaining(),
                config=config,
            )
            if chosen is None:
                log(
                    f"[sweep] {remaining():.0f}s left, but no pass would do anything new "
                    "(every candidate would repeat a solve it already had); stopping"
                )
                break
            kind, pass_uids, budget = chosen

            record = PassRecord(
                index=index,
                kind=kind,
                n_uids=len(pass_uids),
                budget_sec=budget,
                workers=config.workers,
            )
            log(
                f"[sweep] pass {index} ({kind}): {len(pass_uids)} queries x {budget:.0f}s "
                f"on {config.workers} worker(s), {remaining() / 60:.1f} min left"
            )
            started = time.monotonic()
            _run_pass(
                pass_uids=pass_uids,
                queries=queries,
                budget=budget,
                kind=kind,
                config=config,
                executor=executor,
                deadline=deadline,
                best_scores=best_scores,
                on_result=on_result,
                parsed_constraints=parsed_constraints or {},
                record=record,
                log=log,
            )
            record.elapsed_sec = time.monotonic() - started
            for uid in pass_uids:
                last_budget[uid] = budget
            config.passes.append(record)
            log(
                f"[sweep] pass {index} ({kind}) done: improved {record.improved}/{record.completed} "
                f"in {record.elapsed_sec / 60:.1f} min; "
                f"{_n_passing(best_scores)}/{len(uids)} queries satisfy their constraints"
            )

            if kind == "repair":
                stalled_repairs = stalled_repairs + 1 if record.improved == 0 else 0

            if executor is not None and record.completed and record.failed == record.completed:
                # Every task failing means the pool itself is broken (a worker killed by the OOM
                # killer poisons it for good), not that every query is hard. Rebuild it rather
                # than spending the rest of the envelope failing instantly.
                log("[sweep] every task in that pass failed; rebuilding the worker pool")
                executor.shutdown(wait=False, cancel_futures=True)
                executor = _make_executor(config)
            if remaining() <= config.min_query_sec:
                log("[sweep] envelope spent; stopping")
                break
    finally:
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)

    return summarize(uids, best_scores, config, remaining())


def _make_executor(config: SweepConfig):
    import multiprocessing

    try:  # fork inherits the already-resolved sys.path and env; cheapest and most predictable
        context = multiprocessing.get_context("fork")
    except ValueError:  # pragma: no cover - non-fork platforms
        context = multiprocessing.get_context()
    return ProcessPoolExecutor(
        max_workers=config.workers,
        mp_context=context,
        initializer=init_worker,
        initargs=(config.lang,),
    )


def _next_pass(
    *,
    index: int,
    uids: Sequence[str],
    best_scores: dict[str, selfscore.PlanScore],
    stalled_repairs: int,
) -> tuple[str, list[str]]:
    """The single highest-value pass to run next (see ``_candidate_passes`` for the fallbacks)."""
    return _candidate_passes(
        index=index, uids=uids, best_scores=best_scores, stalled_repairs=stalled_repairs
    )[0]


def _candidate_passes(
    *,
    index: int,
    uids: Sequence[str],
    best_scores: dict[str, selfscore.PlanScore],
    stalled_repairs: int,
) -> list[tuple[str, list[str]]]:
    """Passes worth running next, best first.

    More than one, because the best pass can turn out to be empty once budget growth is taken
    into account: when every failing query would only get a repeat of a solve it already had, the
    time is better spent polishing a passing query than not spent at all.
    """
    if index == 1:
        return [("triage", [uid for uid in uids if uid not in best_scores])]
    scores: dict[str, selfscore.PlanScore | None] = {uid: best_scores.get(uid) for uid in uids}
    repair = ("repair", repair_order(scores))
    polish = ("polish", polish_order(scores))
    if stalled_repairs >= MAX_STALLED_REPAIR_PASSES:
        return [polish, repair]
    return [repair, polish]


def _choose_pass(
    *,
    index: int,
    uids: Sequence[str],
    best_scores: dict[str, selfscore.PlanScore],
    stalled_repairs: int,
    last_budget: dict[str, float],
    remaining_sec: float,
    config: SweepConfig,
) -> tuple[str, list[str], float] | None:
    """Pick the pass to run and the budget to run it at, or ``None`` when nothing is worth doing.

    Two filters shape the pass, in this order:

    - **growth**: a query re-solved at (nearly) its previous budget reproduces its previous plan,
      so it is dropped from the pass rather than burning the envelope on a known answer;
    - **fit**: what is left of the envelope may not cover a full pass, so the pass is trimmed to
      the queries that actually fit instead of being started and cut off.
    """
    for kind, candidates in _candidate_passes(
        index=index, uids=uids, best_scores=best_scores, stalled_repairs=stalled_repairs
    ):
        if not candidates:
            continue
        cap = config.triage_cap_sec if kind == "triage" else config.max_query_sec
        fraction = config.triage_fraction if kind == "triage" else config.pass_fraction
        budget = pass_budget_sec(
            remaining_sec,
            len(candidates),
            workers=config.workers,
            fraction=fraction,
            cap_sec=cap,
            floor_sec=config.min_query_sec,
        )
        if kind != "triage":
            candidates = [
                uid for uid in candidates if budget >= last_budget.get(uid, 0.0) * MIN_BUDGET_GROWTH
            ]
            if not candidates:
                continue
        if not pass_fits(remaining_sec, budget, len(candidates), config.workers):
            affordable = max(0, int(remaining_sec // max(budget, 1e-6)) * config.workers)
            candidates = candidates[:affordable]
            if not candidates:
                continue
        return kind, candidates, budget
    return None


def _run_pass(
    *,
    pass_uids: Sequence[str],
    queries: dict[str, dict],
    budget: float,
    kind: str,
    config: SweepConfig,
    executor,
    deadline: float,
    best_scores: dict[str, selfscore.PlanScore],
    on_result: Callable[[str, dict, selfscore.PlanScore, dict, bool], None],
    parsed_constraints: dict[str, dict],
    record: PassRecord,
    log: Callable[[str], None],
) -> None:
    tasks = [
        {
            "uid": uid,
            "query": queries[uid],
            "budget_sec": budget,
            "lang": config.lang,
            "kind": kind,
            "parsed_constraints": parsed_constraints.get(uid),
        }
        for uid in pass_uids
    ]

    def handle(result: dict) -> None:
        record.completed += 1
        if result.get("error"):
            record.failed += 1
        uid = result["uid"]
        score = _score_from_dict(result.get("score")) or selfscore.ZERO_SCORE
        improved = selfscore.is_better(score, best_scores.get(uid))
        if improved:
            best_scores[uid] = score
            record.improved += 1
        # Reported either way: a five-hour run has to be readable afterwards, and "this query was
        # retried three times and never improved" is exactly the diagnostic worth having. The
        # caller decides what to persist for a non-improving attempt (telemetry, not the plan).
        on_result(uid, result["plan"], score, result.get("telemetry") or {}, improved)

    if executor is None:
        for task in tasks:
            if time.monotonic() >= deadline:
                log("[sweep] deadline reached mid-pass; leaving the rest for the next run")
                return
            handle(solve_one(task))
        return

    futures = {executor.submit(solve_one, task): task["uid"] for task in tasks}
    pending = set(futures)
    while pending:
        timeout = max(0.0, (deadline + config.straggler_grace_sec) - time.monotonic())
        done, pending = wait(pending, timeout=timeout, return_when=FIRST_COMPLETED)
        if not done:
            log(
                f"[sweep] deadline passed with {len(pending)} query(ies) still running; "
                "abandoning them (their results would land after the cutoff)"
            )
            for future in pending:
                future.cancel()
            return
        for future in done:
            try:
                handle(future.result())
            except Exception as exc:  # a worker died; keep the pass going
                record.failed += 1
                log(f"[sweep] worker failed on {futures.get(future)}: {exc}")


def _n_passing(best_scores: dict[str, selfscore.PlanScore]) -> int:
    return sum(1 for score in best_scores.values() if score.constraints_ok)


def summarize(
    uids: Iterable[str],
    best_scores: dict[str, selfscore.PlanScore],
    config: SweepConfig,
    remaining_sec: float,
) -> dict[str, Any]:
    uid_list = list(uids)
    scored = [best_scores[uid] for uid in uid_list if uid in best_scores]
    n = len(uid_list) or 1
    return {
        "queries": len(uid_list),
        "scored": len(scored),
        "constraints_ok": sum(1 for score in scored if score.constraints_ok),
        "workers": config.workers,
        "passes": [record.to_dict() for record in config.passes],
        "remaining_sec": round(remaining_sec, 1),
        # Oracle-free estimate over the *whole* split, zeroing unscored queries exactly as the
        # official scorer averages over all queries.
        "self_overall_mean": round(sum(score.overall for score in scored) / n, 4),
        "self_fpr_mean": round(sum(score.fpr for score in scored) / n, 4),
    }
