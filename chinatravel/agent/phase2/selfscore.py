"""Oracle-free scoring of a finished plan: the harness's own estimate of the official score.

The Phase 2 scheduler has to decide, without any oracle field, three things: whether a plan is
good enough to stop working on, which of two plans for the same query to keep, and which queries
are worth more time. All three need a number, and the only honest number available inside the
no-oracle boundary is the official metric with *parsed* constraints standing in for the oracle's
hard logic.

This module computes exactly that. It takes the **visible** query -- never the full record -- so
oracle leakage is structurally impossible rather than merely avoided: there is no code path here
that could read ``hard_logic*`` because the caller never passes it.

The weighting mirrors ``eval_tpc.py``'s (and ``solve_script_with_harness.evaluate_one``'s), and
the preference snippets are imported from ``eval_tpc`` rather than copied, so this cannot drift
into being a second opinion. Two properties of that formula drive the whole scheduler:

- ``FPR`` (weight ``0.40``) is all-or-nothing on schema *and* commonsense *and* logical passing,
  and ``C-LPR`` (``0.25``) is conditional on commonsense passing. Constraints are therefore worth
  ``0.65`` before any preference term earns anything.
- Since the 2026-07-28 evaluator sync, ``DAV``/``ATT``/``DDR`` (``0.05`` each) are zero for a query
  that is not fully passing. Preference work on a constraint-failing plan is worth **nothing**.

Hence: satisfy constraints everywhere first, polish preferences only afterwards.
"""

from __future__ import annotations

import sys
from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Official weights (eval_tpc.py): 0.1*MicEPR + 0.1*MacEPR + 0.25*C-LPR + 0.4*FPR
# + 0.05*DAV + 0.05*ATT + 0.05*DDR.
W_EPR_MICRO = 0.10
W_EPR_MACRO = 0.10
W_CLPR = 0.25
W_FPR = 0.40
W_PREFERENCE = 0.05  # each of DAV, ATT, DDR


@dataclass(frozen=True)
class PlanScore:
    """One plan's oracle-free score. All metric fields are on the official 0-100 scale."""

    schema_ok: bool
    commonsense_ok: bool
    logical_ok: bool
    epr_micro: float
    epr_macro: float
    clpr: float
    fpr: float
    dav: float
    att: float
    ddr: float
    overall: float
    logical_total: int
    logical_satisfied: int
    error: str | None = None

    @property
    def constraints_ok(self) -> bool:
        """The FPR-bearing state: everything worth 0.65 of the score before preferences count."""
        return self.schema_ok and self.commonsense_ok and self.logical_ok

    def ranking_key(self) -> tuple[bool, float]:
        """Sort key for keep-best. Constraints first so no preference gain can ever buy out a
        constraint regression, then the oracle-free overall."""
        return (self.constraints_ok, self.overall)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["constraints_ok"] = self.constraints_ok
        return data


ZERO_SCORE = PlanScore(
    schema_ok=False,
    commonsense_ok=False,
    logical_ok=False,
    epr_micro=0.0,
    epr_macro=0.0,
    clpr=0.0,
    fpr=0.0,
    dav=0.0,
    att=0.0,
    ddr=0.0,
    overall=0.0,
    logical_total=0,
    logical_satisfied=0,
)


@lru_cache(maxsize=1)
def _output_schema() -> Any:
    from chinatravel.evaluation.utils import load_json_file

    return load_json_file(str(PROJECT_ROOT / "chinatravel" / "evaluation" / "output_schema.json"))


@lru_cache(maxsize=1)
def _preference_snippets() -> tuple[str, ...]:
    """The official DAV/ATT/DDR snippets, imported rather than copied.

    ``eval_tpc`` lives at the repository root, so it is importable but not a package module.
    """
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    import eval_tpc

    return tuple(eval_tpc.DEFAULT_PR)


def _clamp_unit(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except Exception:
        return 0.0


def preference_scores(plan: dict) -> tuple[float, float, float]:
    """DAV, ATT, DDR on the 0-100 scale, evaluated exactly as the official scorer does.

    Note these are the *raw* snippet values: the evaluator zeroes them for a non-passing query,
    which ``score_plan`` applies.
    """
    from chinatravel.symbol_verification.concept_func import func_dict

    scores: list[float] = []
    for snippet in _preference_snippets():
        namespace = deepcopy(func_dict)
        namespace["plan"] = plan
        try:
            exec(snippet, {"__builtins__": {"set": set}}, namespace)
            scores.append(_clamp_unit(namespace.get("result", 0.0)))
        except Exception:
            scores.append(0.0)
    while len(scores) < 3:
        scores.append(0.0)
    return scores[0] * 100.0, scores[1] * 100.0, scores[2] * 100.0


def score_plan(
    plan: dict,
    visible_query: dict,
    *,
    variants: list[dict] | None = None,
    parsed_constraints: dict | None = None,
    lang: str = "en",
    uid: str | None = None,
) -> PlanScore:
    """Score ``plan`` for ``visible_query`` without any oracle field.

    ``variants`` is the *exact* branch-local solver constraint list the query was solved against
    (``normalize.ir_to_solver_variants`` output: disjunction-expanded, entity-resolved). Logical
    acceptance is **OR across variants** -- a plan is ``logical_ok`` if any one variant's checks
    all pass, mirroring how a disjunctive oracle clause itself is satisfied by any one arm. Ranking
    (and the ``logical_total``/``logical_satisfied``/``clpr`` reported on ``PlanScore``) uses the
    single best-scoring variant, chosen by ``(all_true, satisfied / total)``, so ``PlanScore``'s
    shape and ``ranking_key`` stay unchanged.

    ``parsed_constraints`` is a one-variant compatibility alias: passing it is equivalent to
    ``variants=[parsed_constraints]``, kept so existing callers keep working. When neither is
    given, this falls back to ``derive_parsed_constraints`` (a coarser, single-variant parse --
    see its docstring for why that is no longer the scheduler's own path).

    Never raises: a scoring failure returns a zero score carrying the error, because the scheduler
    must keep running.
    """
    quid = uid or str(visible_query.get("uid") or "query")
    if variants is None and parsed_constraints is not None:
        variants = [parsed_constraints]
    try:
        return _score_plan(plan, visible_query, variants, lang, quid)
    except Exception as exc:  # scoring must never take down a run
        return replace(ZERO_SCORE, error=f"{type(exc).__name__}: {exc}")


def _score_plan(
    plan: dict,
    visible_query: dict,
    variants: list[dict] | None,
    lang: str,
    quid: str,
) -> PlanScore:
    from chinatravel.agent.tpc_agent.parsed_verifier import evaluate_parsed_constraints
    from chinatravel.evaluation.commonsense_constraint import evaluate_commonsense_constraints
    from chinatravel.evaluation.schema_constraint import evaluate_schema_constraints

    index = [quid]
    query_data = {quid: visible_query}
    result_data = {quid: plan}

    _rate, _agg, schema_pass_ids = evaluate_schema_constraints(
        index, result_data, schema=_output_schema()
    )
    schema_ok = quid in schema_pass_ids

    macro_epr, micro_epr, _agg, commonsense_pass_ids = evaluate_commonsense_constraints(
        index, query_data, result_data, verbose=False, lang=lang
    )
    commonsense_ok = quid in commonsense_pass_ids

    if not variants:
        fallback = derive_parsed_constraints(visible_query)
        variants = [fallback] if fallback else [{}]

    target_city = visible_query.get("target_city", "")
    best_key: tuple[bool, float] | None = None
    total = satisfied = 0
    logical_ok = False
    for variant in variants:
        checks = evaluate_parsed_constraints(variant, plan, target_city)
        v_total = len(checks)
        v_satisfied = sum(1 for check in checks if bool(check))
        v_all_true = v_satisfied == v_total
        v_ratio = (v_satisfied / v_total) if v_total else 1.0
        # Best variant: prefer an all-true variant, then the highest satisfied/total ratio --
        # matches the OR semantics of a disjunctive oracle clause (any one satisfied arm passes).
        key = (v_all_true, v_ratio)
        if best_key is None or key > best_key:
            best_key = key
            total, satisfied, logical_ok = v_total, v_satisfied, v_all_true
    logical_micro = (100.0 * satisfied / total) if total else 100.0
    # C-LPR is the *conditional* logical micro: a commonsense failure forfeits logical credit the
    # solver already earned. That is why commonsense-first finalization is worth so much.
    clpr = logical_micro if commonsense_ok else 0.0

    all_pass = schema_ok and commonsense_ok and logical_ok
    fpr = 100.0 if all_pass else 0.0
    dav, att, ddr = preference_scores(plan) if all_pass else (0.0, 0.0, 0.0)

    overall = (
        W_EPR_MICRO * micro_epr
        + W_EPR_MACRO * macro_epr
        + W_CLPR * clpr
        + W_FPR * fpr
        + W_PREFERENCE * dav
        + W_PREFERENCE * att
        + W_PREFERENCE * ddr
    )
    return PlanScore(
        schema_ok=schema_ok,
        commonsense_ok=commonsense_ok,
        logical_ok=logical_ok,
        epr_micro=float(micro_epr),
        epr_macro=float(macro_epr),
        clpr=float(clpr),
        fpr=fpr,
        dav=dav,
        att=att,
        ddr=ddr,
        overall=float(overall),
        logical_total=total,
        logical_satisfied=satisfied,
    )


def derive_parsed_constraints(visible_query: dict) -> dict:
    """A coarse, single-variant fallback parse -- **not** the scheduler's constraint path.

    This takes only ``variants[0]`` of a plain no-oracle parse: no disjunction expansion, no
    entity resolution. It exists as a last resort when the parent has no variants for a query (a
    parse failure, or a caller that never ran the canonical parse) and as the one-variant
    compatibility shape some callers/tests still construct by hand. The scheduler itself parses
    once through the canonical path (``normalize.parse_to_ir`` + ``normalize.ir_to_solver_variants``)
    and hands the full variant list to both the solver and ``score_plan`` -- see
    ``agent_env/scripts/solve_phase2.run_sweeps_split``.
    """
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    import parse_constraints

    from chinatravel.agent.tpc_agent.solver_constraints import solver_constraint_variants

    parsed = parse_constraints.parse_query_no_oracle(visible_query)
    variants = solver_constraint_variants(visible_query, parsed, use_oracle=False)
    return variants[0] if variants else {}


def is_better(candidate: PlanScore | None, incumbent: PlanScore | None) -> bool:
    """Keep-best comparison. Strictly greater, so an equal-scoring rerun never churns the file."""
    if candidate is None:
        return False
    if incumbent is None:
        return True
    return candidate.ranking_key() > incumbent.ranking_key()


# Kept next to the weights it depends on so a change to either is made in one place.
def max_remaining_gain(score: PlanScore | None) -> float:
    """Overall points still reachable for this query, used to rank what to work on next.

    A constraint-failing plan can still win everything the constraints carry plus the preference
    terms they unlock; a passing plan can only win the preference remainder. This is what makes
    the scheduler prefer an unsolved query over polishing a solved one.
    """
    if score is None:
        return 100.0
    if not score.constraints_ok:
        return 100.0 - score.overall
    return W_PREFERENCE * ((100.0 - score.dav) + (100.0 - score.att) + (100.0 - score.ddr))
