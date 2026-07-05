"""Phase 2 orchestrator: Stage 1-4 control loop around the deterministic TPCAgent.

Stages:
  1. parse    - NL query -> ParsedIR -> branch-local solver constraint variants (normalize).
  2. solve    - deterministic TPCAgent (TPC_USE_ORACLE=0), time-boxed to the solve slice.
  3. improve  - deterministic densify happens inside TPCAgent; optional bounded LLM refine (stub).
  4. finalize - validate; on failure/timeout return a guaranteed-valid fallback plan.

Everything LLM-related is OFF by default. On the default path the LLM client is never called; a
spy client passed in will record zero calls. Unit tests inject ``solve_fn`` so no WorldEnv/solver
is needed; the runner injects a TPCAgent-backed ``solve_fn`` (see ``make_tpcagent_solve_fn``).
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from func_timeout import FunctionTimedOut, func_timeout

from . import budget as budget_mod
from . import fallback as fallback_mod
from . import normalize

# Expected Phase 2 per-query budget: 15 min primary (to be confirmed); 5 min alternative.
# Override per query via the TPC_P2_BUDGET_SEC env var or the ``budget_sec`` argument.
PHASE2_DEFAULT_BUDGET_SEC = 900.0  # 15 minutes (primary, TBC)
PHASE2_ALT_BUDGET_SEC = 300.0      # 5 minutes (alternative)
DEFAULT_BUDGET_SEC = PHASE2_DEFAULT_BUDGET_SEC


def _truthy(value) -> bool:
    return str(value) not in ("0", "", "false", "False", "None", None)


@dataclass
class Flags:
    """Phase 2 feature flags. All OFF by default (deterministic path unchanged)."""

    llm_backend: str = "none"
    disjunction: bool = False
    llm_parse: bool = False
    llm_refine: bool = False

    @classmethod
    def from_env(cls, env: dict | None = None) -> "Flags":
        env = os.environ if env is None else env
        return cls(
            llm_backend=str(env.get("TPC_P2_LLM_BACKEND", "none") or "none").lower(),
            disjunction=_truthy(env.get("TPC_P2_DISJUNCTION", "0")),
            llm_parse=_truthy(env.get("TPC_P2_LLM_PARSE", "0")),
            llm_refine=_truthy(env.get("TPC_P2_LLM_REFINE", "0")),
        )


# solve_fn signature: (query, variants, budget_sec) -> plan dict
SolveFn = Callable[[dict, list, float], dict]


def llm_refine_stub(plan: dict, query: dict, llm_client, budget_sec: float) -> dict:
    """TODO(phase2, Milestone 3+): bounded, acceptance-gated LLM plan refinement.

    Will ask ``llm_client`` for a targeted improvement of an already-valid plan within
    ``budget_sec``, keeping the change only if the plan still passes acceptance. No-op placeholder
    for now (returns the plan unchanged, does not call the LLM).
    """
    return plan


def make_tpcagent_solve_fn(env, *, backbone_llm=None, log_dir=None, lang="en") -> SolveFn:
    """Build a solve_fn that drives the existing TPCAgent in no-oracle mode.

    Constructs one TPCAgent and reuses it. Sets ``TPC_USE_ORACLE=0`` and, per call, the solve
    budget via ``TPC_SOLVE_BUDGET_SEC``. Imported lazily so unit tests need neither TPCAgent nor
    WorldEnv.
    """
    os.environ["TPC_USE_ORACLE"] = "0"
    from chinatravel.agent.load_model import init_llm
    from chinatravel.agent.tpc_agent.tpc_agent import TPCAgent

    if backbone_llm is None:
        backbone_llm = init_llm("TPCLLM")
    agent = TPCAgent(
        env=env,
        backbone_llm=backbone_llm,
        log_dir=log_dir or os.path.join("cache", "phase2_solve"),
        lang=lang,
    )

    def _solve(query: dict, variants: list, budget_sec: float) -> dict:
        os.environ["TPC_USE_ORACLE"] = "0"
        os.environ["TPC_SOLVE_BUDGET_SEC"] = str(max(float(budget_sec), 1.0))
        agent.solve_budget_sec = max(float(budget_sec), 1.0)
        _succ, plan = agent.run(query)
        return plan

    return _solve


def solve_phase2(
    query: dict,
    *,
    env=None,
    llm_client=None,
    budget_sec: float | None = None,
    flags: Flags | None = None,
    solve_fn: SolveFn | None = None,
) -> tuple[dict, dict]:
    """Run the Phase 2 pipeline for one query. Returns ``(plan, telemetry)``.

    Never raises for solver failures: a raising or timed-out solve degrades to a schema-valid
    fallback. ``solve_fn`` may be injected (tests); otherwise a TPCAgent-backed solve is built from
    ``env``.
    """
    if flags is None:
        flags = Flags.from_env()
    if budget_sec is None:
        budget_sec = float(os.environ.get("TPC_P2_BUDGET_SEC", DEFAULT_BUDGET_SEC))
    b = budget_mod.split_budget(budget_sec)

    telemetry: dict[str, Any] = {
        "uid": query.get("uid"),
        "llm_backend": flags.llm_backend,
        "flags": {
            "disjunction": flags.disjunction,
            "llm_parse": flags.llm_parse,
            "llm_refine": flags.llm_refine,
        },
        "budget_sec": budget_sec,
        "stage_sec": {},
        "timed_out": False,
        "used_fallback": False,
        "valid_output": False,
        "error": None,
        "variants_count": 0,
    }

    # --- Stage 1: parse ---------------------------------------------------
    t0 = time.perf_counter()
    try:
        ir = normalize.parse_to_ir(query, llm_client=llm_client, flags=flags)
        variants = normalize.ir_to_solver_variants(ir, query, env=env, flags=flags)
    except Exception as exc:  # parsing must never crash the harness
        variants = []
        telemetry["error"] = f"parse: {exc}"
    telemetry["stage_sec"]["parse"] = time.perf_counter() - t0
    telemetry["variants_count"] = len(variants)

    # --- Stage 2: solve (time-boxed) --------------------------------------
    if solve_fn is None:
        solve_fn = make_tpcagent_solve_fn(env) if env is not None else None

    plan_candidate: dict | None = None
    t0 = time.perf_counter()
    if solve_fn is not None:
        solve_timeout = max(b.solve_sec, 0.01)
        try:
            plan_candidate = func_timeout(
                solve_timeout, solve_fn, args=(query, variants, b.solve_sec)
            )
        except FunctionTimedOut:
            telemetry["timed_out"] = True
        except Exception as exc:
            telemetry["error"] = f"solve: {exc}"
            plan_candidate = None
    telemetry["stage_sec"]["solve"] = time.perf_counter() - t0

    # --- Stage 3: improve (stub; deterministic densify already inside TPCAgent) --
    t0 = time.perf_counter()
    if flags.llm_refine and plan_candidate is not None:
        plan_candidate = llm_refine_stub(plan_candidate, query, llm_client, b.improve_sec)
    telemetry["stage_sec"]["improve"] = time.perf_counter() - t0

    # --- Stage 4: finalize -------------------------------------------------
    t0 = time.perf_counter()
    if isinstance(plan_candidate, dict) and isinstance(plan_candidate.get("itinerary"), list):
        final_plan = plan_candidate
    else:
        final_plan = fallback_mod.fallback_plan(query, best=plan_candidate)
        telemetry["used_fallback"] = True
    telemetry["valid_output"] = isinstance(final_plan.get("itinerary"), list)
    telemetry["stage_sec"]["finalize"] = time.perf_counter() - t0

    return final_plan, telemetry
