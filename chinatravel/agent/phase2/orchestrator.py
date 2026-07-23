"""Phase 2 orchestrator: Stage 1-4 control loop around the deterministic TPCAgent.

Stages:
  1. parse    - NL query -> ParsedIR -> branch-local solver constraint variants (normalize).
  2. solve    - deterministic TPCAgent (TPC_USE_ORACLE=0), time-boxed to the solve slice.
  3. improve  - deterministic densify happens inside TPCAgent; optional bounded, acceptance-gated
                LLM refine (repair-only v1; see ``llm_refine`` and ``phase2/refine.py``).
  4. finalize - validate; on failure/timeout return a guaranteed-valid fallback plan.

Everything LLM-related is OFF by default. On the default path the LLM client is never called; a
spy client passed in will record zero calls. Unit tests inject ``solve_fn`` so no WorldEnv/solver
is needed; the runner injects a TPCAgent-backed ``solve_fn`` (see ``make_tpcagent_solve_fn``).
"""

from __future__ import annotations

from copy import deepcopy
import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, TypeGuard

from func_timeout import FunctionTimedOut, func_timeout

from . import budget as budget_mod
from . import fallback as fallback_mod
from . import normalize
from . import refine as refine_mod

# Local Phase 2 sensitivity budgets. Public competition material currently does not specify an
# organizer-enforced per-query timeout or repeat count. Override per query via
# ``TPC_P2_BUDGET_SEC`` or the ``budget_sec`` argument. ``300s`` is the working default; ``900s``
# is a longer local sensitivity setting.
PHASE2_ORGANIZER_BUDGET_SEC = 900.0  # Retained name; local sensitivity setting, not organizer-confirmed.
PHASE2_ALT_BUDGET_SEC = 300.0        # Local working default.
DEFAULT_BUDGET_SEC = PHASE2_ALT_BUDGET_SEC
DEFAULT_SOLVE_TIMEOUT_GRACE_SEC = 1.0


def _truthy(value) -> bool:
    return str(value) not in ("0", "", "false", "False", "None", None)


def _valid_plan_shape(plan: Any) -> TypeGuard[dict]:
    return isinstance(plan, dict) and isinstance(plan.get("itinerary"), list)


def _append_error(telemetry: dict[str, Any], message: str) -> None:
    prev = telemetry.get("error")
    telemetry["error"] = message if not prev else f"{prev} | {message}"


def _recover_solve_plan(solve_fn) -> dict | None:
    getter = getattr(solve_fn, "get_timeout_recovery_plan", None)
    if not callable(getter):
        return None
    try:
        candidate = getter()
    except Exception:
        return None
    if not isinstance(candidate, dict):
        return None
    try:
        return deepcopy(candidate)
    except Exception:
        return candidate


@dataclass
class Flags:
    """Phase 2 feature flags. All OFF by default (deterministic path unchanged)."""

    llm_backend: str = "none"
    disjunction: bool = False
    llm_parse: bool = False
    llm_refine: bool = False
    dynamic_budget: bool = False
    entity_resolution: bool = False
    # Master switch stays llm_parse; this selects the strategy only when it is enabled.
    # "audit" (default): today's corrective-audit stub, everything round-trips through the regex.
    # "extract": LLM-first structured extraction + deterministic validation/merge, independent of
    # the regex parse. Any other value falls back to "audit".
    llm_parse_mode: str = "audit"

    @classmethod
    def from_env(cls, env: Mapping[str, Any] | None = None) -> "Flags":
        env_map = os.environ if env is None else env
        raw_mode = str(env_map.get("TPC_P2_LLM_PARSE_MODE", "audit") or "audit").lower()
        return cls(
            llm_backend=str(env_map.get("TPC_P2_LLM_BACKEND", "none") or "none").lower(),
            disjunction=_truthy(env_map.get("TPC_P2_DISJUNCTION", "0")),
            llm_parse=_truthy(env_map.get("TPC_P2_LLM_PARSE", "0")),
            llm_parse_mode=raw_mode if raw_mode in ("audit", "extract") else "audit",
            llm_refine=_truthy(env_map.get("TPC_P2_LLM_REFINE", "0")),
            dynamic_budget=_truthy(env_map.get("TPC_P2_DYNAMIC_BUDGET", "0")),
            entity_resolution=_truthy(env_map.get("TPC_P2_ENTITY_RESOLUTION", "0")),
        )


# solve_fn signature: (query, variants, budget_sec) -> plan dict
SolveFn = Callable[[dict, list, float], dict]


def llm_refine(
    plan: dict, query: dict, llm_client, budget_sec: float,
    ground_and_check=None, apply_refine_edits=None,
) -> tuple[dict, dict]:
    """Stage 3: bounded, acceptance-gated LLM plan repair (v1, ``TPC_P2_LLM_REFINE``).

    Repair-only: no-ops on an already-accepted plan (preference-lift on a valid plan is deferred,
    see the roadmap's Stage 3 section). Otherwise asks ``llm_client`` for a small, typed edit list
    built from the checker's own oracle-free failure summary (``refine.build_llm_refine_prompt``),
    applies it via ``apply_refine_edits`` (every POI/window/leg re-grounded against WorldEnv), and
    commits only if ``ground_and_check`` then reports the whole batch accepted with a preference
    key that does not regress vs. the input. ``ground_and_check``/``apply_refine_edits`` are the
    hooks ``make_tpcagent_solve_fn`` attaches to the returned ``solve_fn``; either being ``None``
    (a bare injected ``solve_fn``, e.g. unit tests) makes this a pure no-op. Never raises; always
    returns ``(plan_or_repaired_plan, info)`` where ``info`` is a small telemetry fragment the
    caller merges into the orchestrator's telemetry dict.
    """
    info: dict[str, Any] = {
        "improve_llm_called": False,
        "improve_committed": False,
        "improve_edit_count": 0,
        "improve_edit_reasons": [],
        "improve_skip_reason": None,
    }
    if not callable(ground_and_check):
        info["improve_skip_reason"] = "no_ground_and_check_hook"
        return plan, info

    try:
        accepted, grounded_plan, before_key, failure_summary = ground_and_check(plan)
    except Exception:
        info["improve_skip_reason"] = "ground_and_check_error"
        return plan, info

    if accepted:
        info["improve_skip_reason"] = "already_accepted"
        return plan, info

    if llm_client is None or not hasattr(llm_client, "complete"):
        info["improve_skip_reason"] = "no_llm_client"
        return plan, info

    # Mirrors parse_to_ir's deadline check: a call that provably can't finish in the remaining
    # slice is skipped outright rather than started and left to time out mid-flight.
    client_timeout = getattr(llm_client, "timeout", None)
    if client_timeout is not None and budget_sec < client_timeout:
        info["improve_skip_reason"] = "skipped_deadline"
        return plan, info

    prompt = refine_mod.build_llm_refine_prompt(query, grounded_plan, failure_summary)
    cache_key = refine_mod.llm_refine_cache_key(query, prompt)
    info["improve_llm_called"] = True
    try:
        response = llm_client.complete(prompt, cache_key=cache_key)
        edits = refine_mod.parse_llm_refine_edits(response)
    except Exception:
        info["improve_skip_reason"] = "llm_error_or_invalid_json"
        return plan, info

    if not edits:
        info["improve_skip_reason"] = "no_edits_proposed"
        return plan, info

    if not callable(apply_refine_edits):
        info["improve_skip_reason"] = "no_apply_edits_hook"
        return plan, info

    try:
        trial, applied, edit_reasons = apply_refine_edits(grounded_plan, edits)
    except Exception:
        info["improve_skip_reason"] = "apply_edits_error"
        return plan, info
    info["improve_edit_count"] = applied
    info["improve_edit_reasons"] = edit_reasons
    if not applied:
        info["improve_skip_reason"] = "no_groundable_edits"
        return plan, info

    try:
        trial_accepted, trial_grounded, trial_key, _trial_failure = ground_and_check(trial)
    except Exception:
        info["improve_skip_reason"] = "ground_and_check_error_after_edit"
        return plan, info

    if trial_accepted and (before_key is None or trial_key >= before_key):
        info["improve_committed"] = True
        return trial_grounded, info

    info["improve_skip_reason"] = "not_accepted_or_regressed"
    return plan, info


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
    # Set by each _solve() call, read by the ground_and_check/apply_refine_edits hooks below so
    # Stage 3 (which runs after _solve returns) knows which query it's grounding/checking against.
    last_query: dict | None = None

    def _solve(query: dict, variants: list, budget_sec: float) -> dict:
        nonlocal last_query
        last_query = query
        os.environ["TPC_USE_ORACLE"] = "0"
        os.environ["TPC_SOLVE_BUDGET_SEC"] = str(max(float(budget_sec), 1.0))
        agent.solve_budget_sec = max(float(budget_sec), 1.0)
        agent.reset_timeout_recovery_plan()
        # Harness owns parsing: inject the (possibly disjunction-expanded) variants so the agent
        # uses them directly instead of re-parsing. Empty/None injection preserves the agent's own
        # no-oracle parse, so a parse failure upstream degrades gracefully rather than crashing.
        setattr(agent, "_injected_variants", variants if isinstance(variants, list) and variants else None)
        try:
            _succ, plan = agent.run(query)
        finally:
            setattr(agent, "_injected_variants", None)
        return plan

    def _get_timeout_recovery_plan() -> dict | None:
        return agent.get_timeout_recovery_plan()

    def _ground_and_check(plan: dict):
        if last_query is None:
            return False, plan, None, {}
        return agent.ground_and_check(plan, last_query)

    def _apply_refine_edits(plan: dict, edits: list):
        if last_query is None:
            return deepcopy(plan), 0
        return agent.apply_refine_edits(plan, last_query, edits)

    setattr(_solve, "get_timeout_recovery_plan", _get_timeout_recovery_plan)
    setattr(_solve, "ground_and_check", _ground_and_check)
    setattr(_solve, "apply_refine_edits", _apply_refine_edits)

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
            "llm_parse_mode": flags.llm_parse_mode,
            "llm_refine": flags.llm_refine,
            "dynamic_budget": flags.dynamic_budget,
            "entity_resolution": flags.entity_resolution,
        },
        "budget_sec": budget_sec,
        "stage_sec": {},
        "timed_out": False,
        "solve_recovered_from_timeout": False,
        "solve_recovered_from_error": False,
        "improve_timed_out": False,
        "improve_reverted_to_last_valid": False,
        "improve_llm_called": False,
        "improve_committed": False,
        "improve_edit_count": 0,
        "improve_edit_reasons": [],
        "improve_skip_reason": None,
        "used_fallback": False,
        "valid_output": False,
        "error": None,
        "llm_parse_error": None,
        "llm_parse_skipped_deadline": False,
        "variants_count": 0,
    }

    # --- Stage 1: parse ---------------------------------------------------
    t0 = time.perf_counter()
    try:
        ir = normalize.parse_to_ir(query, llm_client=llm_client, flags=flags, deadline=b.parse_sec)
        if ir.llm_parse_error:
            telemetry["llm_parse_error"] = ir.llm_parse_error
        if ir.llm_parse_skipped_deadline:
            telemetry["llm_parse_skipped_deadline"] = True
        variants = normalize.ir_to_solver_variants(ir, query, env=env, flags=flags)
    except Exception as exc:  # parsing must never crash the harness
        variants = []
        telemetry["error"] = f"parse: {exc}"
    telemetry["stage_sec"]["parse"] = time.perf_counter() - t0
    telemetry["variants_count"] = len(variants)

    if flags.dynamic_budget:
        b.solve_sec = budget_mod.dynamic_solve_sec(
            b, telemetry["stage_sec"]["parse"], improve_reserved=flags.llm_refine
        )
        telemetry["dynamic_solve_sec"] = b.solve_sec

    # --- Stage 2: solve (time-boxed) --------------------------------------
    if solve_fn is None:
        solve_fn = make_tpcagent_solve_fn(env) if env is not None else None

    plan_candidate: dict | None = None
    t0 = time.perf_counter()
    if solve_fn is not None:
        grace_cap = max(b.finalize_sec * 0.5, 0.0)
        solve_grace = min(
            max(float(os.environ.get("TPC_P2_SOLVE_TIMEOUT_GRACE_SEC", DEFAULT_SOLVE_TIMEOUT_GRACE_SEC)), 0.0),
            grace_cap,
        )
        solve_timeout = max(b.solve_sec + solve_grace, 0.01)
        try:
            plan_candidate = func_timeout(
                solve_timeout, solve_fn, args=(query, variants, b.solve_sec)
            )
        except FunctionTimedOut:
            telemetry["timed_out"] = True
            recovered = _recover_solve_plan(solve_fn)
            if _valid_plan_shape(recovered):
                plan_candidate = recovered
                telemetry["solve_recovered_from_timeout"] = True
        except Exception as exc:
            _append_error(telemetry, f"solve: {exc}")
            recovered = _recover_solve_plan(solve_fn)
            if _valid_plan_shape(recovered):
                plan_candidate = recovered
                telemetry["solve_recovered_from_error"] = True
            else:
                plan_candidate = None
    telemetry["stage_sec"]["solve"] = time.perf_counter() - t0

    # --- Stage 3: improve (deterministic densify already inside TPCAgent; optional bounded,
    # acceptance-gated LLM refine on top -- see llm_refine) --
    t0 = time.perf_counter()
    if flags.llm_refine and plan_candidate is not None:
        last_valid_plan = deepcopy(plan_candidate)
        ground_and_check = getattr(solve_fn, "ground_and_check", None) if solve_fn is not None else None
        apply_refine_edits = getattr(solve_fn, "apply_refine_edits", None) if solve_fn is not None else None
        improve_timeout = max(b.improve_sec, 0.01)
        try:
            result = func_timeout(
                improve_timeout,
                llm_refine,
                args=(plan_candidate, query, llm_client, b.improve_sec, ground_and_check, apply_refine_edits),
            )
            # llm_refine returns (plan, info); tolerate a bare plan too (older/simplified test
            # stubs monkeypatching this function need not return the tuple).
            improved, improve_info = result if isinstance(result, tuple) else (result, {})
            if isinstance(improve_info, dict):
                telemetry.update(improve_info)
            if _valid_plan_shape(improved):
                plan_candidate = improved
            else:
                telemetry["improve_reverted_to_last_valid"] = True
                plan_candidate = last_valid_plan
        except FunctionTimedOut:
            telemetry["timed_out"] = True
            telemetry["improve_timed_out"] = True
            telemetry["improve_reverted_to_last_valid"] = True
            plan_candidate = last_valid_plan
        except Exception as exc:
            _append_error(telemetry, f"improve: {exc}")
            telemetry["improve_reverted_to_last_valid"] = True
            plan_candidate = last_valid_plan
    telemetry["stage_sec"]["improve"] = time.perf_counter() - t0

    # --- Stage 4: finalize -------------------------------------------------
    t0 = time.perf_counter()
    if _valid_plan_shape(plan_candidate):
        final_plan = plan_candidate
    else:
        final_plan = fallback_mod.fallback_plan(query, best=plan_candidate)
        telemetry["used_fallback"] = True
    telemetry["valid_output"] = _valid_plan_shape(final_plan)
    telemetry["stage_sec"]["finalize"] = time.perf_counter() - t0

    return final_plan, telemetry
