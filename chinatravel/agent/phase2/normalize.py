"""Normalization layer: NL query -> ParsedIR -> branch-local solver constraint variants.

Default behavior (all flags OFF): a faithful passthrough of the current no-oracle path, so output
is byte-identical to ``solver_constraint_variants(query, parse_query_no_oracle(query),
use_oracle=False)``.

Flag hooks (all OFF by default):
- ``TPC_P2_LLM_PARSE``  : LLM-assisted second-pass parse (Stage 1 disambiguation; still a stub).
- ``TPC_P2_DISJUNCTION``: true no-oracle disjunctive branch generation (implemented below).

When flags are off, neither hook runs and the LLM client is never called.
"""

from __future__ import annotations

import parse_constraints
from chinatravel.agent.tpc_agent.solver_constraints import (
    _BRANCH_LOCAL_KEYS,
    solver_constraint_variants,
)

from .schema import ParsedIR, SolverConstraints


def llm_parse_stub(ir: ParsedIR, query: dict, llm_client) -> ParsedIR:
    """TODO(phase2, Milestone 3+): LLM-assisted second-pass parse.

    Will call ``llm_client`` for paraphrase/compound-clause disambiguation and merge the result into
    the IR, validating every proposed constraint/entity against WorldEnv before it reaches the solver.
    No-op placeholder for now (returns the IR unchanged, does not call the LLM).
    """
    return ir


def _detect_or_groups(query: dict) -> list[dict]:
    """Deterministically split a disjunctive query's NL into per-arm parsed constraint dicts.

    Returns a list of arm dicts (one per OR branch) when the query is NL-detectably disjunctive and
    splits cleanly into >=2 arms; otherwise returns an empty list (the flat single-variant path).

    Uses only the deterministic NL helpers in ``parse_constraints`` — no LLM, no network.
    """
    text = query.get("nature_language", "") or ""
    if not parse_constraints.detect_disjunctive(text):
        return []
    groups = parse_constraints.split_disjunctive_groups(text)

    # TODO(phase2, LLM disjunction assist): when the deterministic split fails or yields <2 arms,
    # and BOTH TPC_P2_DISJUNCTION and TPC_P2_LLM_PARSE are on with a configured backend, call the
    # LLM (via llm_client / build_llm_client) here to propose arm texts, then parse+validate each
    # arm below exactly as the deterministic path does. Keep the deterministic result as the
    # default and never call the network on the default path. See docs/tpc_phase2_design.md.
    if not groups or len(groups) < 2:
        return []

    arms = [parse_constraints.parse_single_constraint_text(g) for g in groups]
    # Keep only arms that contributed at least one recognized constraint; drop empties so an
    # unparsable arm does not silently widen the search to "anything goes".
    arms = [a for a in arms if a]
    return arms if len(arms) >= 2 else []


def parse_to_ir(query: dict, *, llm_client=None, flags=None) -> ParsedIR:
    """Parse a query into the parser IR.

    Wraps the deterministic no-oracle parse (source of truth for the flat single variant). When
    ``flags.disjunction`` is on and the query is NL-detectably disjunctive, also populate
    ``ir.or_groups`` with one parsed constraint dict per OR arm (consumed by
    ``ir_to_solver_variants``). When ``flags.llm_parse`` is on, route through ``llm_parse_stub``
    (a no-op placeholder). Off by default, so the LLM is never called here on the default path.
    """
    raw = parse_constraints.parse_query_no_oracle(query)
    if not isinstance(raw, dict):
        raw = {}
    ir = ParsedIR(raw=raw, variants=[raw])

    if flags is not None and getattr(flags, "disjunction", False):
        or_groups = _detect_or_groups(query)
        if or_groups:
            ir.or_groups = or_groups

    if flags is not None and getattr(flags, "llm_parse", False):
        ir = llm_parse_stub(ir, query, llm_client)

    return ir


def disjunction_stub(variants: list, ir: ParsedIR, query: dict) -> list:
    """Expand OR-groups from the IR into branch-local solver variants.

    Mirrors the oracle path (``solver_constraint_variants(..., use_oracle=True)``): a shared base
    context is stripped of branch-local keys, then each OR arm's facts are merged into a copy so
    constraints from one arm never contaminate another. Each per-arm dict is normalized through the
    existing ``solver_constraint_variants(use_oracle=False)`` path, guaranteeing the exact solver
    dict shape ``TPCAgent`` consumes.

    No-op when there are no OR-groups (non-disjunctive queries): returns ``variants`` unchanged, so
    the flat single-variant path is byte-identical to today.
    """
    or_groups = getattr(ir, "or_groups", None) or []
    if len(or_groups) < 2:
        return variants

    # Shared context = flat parse minus the branch-local families that an arm actually claims.
    # Only arm-claimed families are re-added per branch; global constraints stated once outside the
    # OR (e.g. a party-size-derived taxi_cars_equals, or a global budget) stay in every branch so
    # "A or B" is never encoded as "A and B" yet globals are not dropped.
    claimed = set().union(*[set(a) for a in or_groups])
    base = {
        k: v
        for k, v in ir.raw.items()
        if k != "disjunctive" and not (k in _BRANCH_LOCAL_KEYS and k in claimed)
    }

    expanded: list[SolverConstraints] = []
    for arm in or_groups:
        arm_raw = dict(base)
        arm_raw.update(arm)
        arm_raw["disjunctive"] = False
        expanded.extend(solver_constraint_variants(query, arm_raw, use_oracle=False))

    return expanded or variants


def ir_to_solver_variants(ir: ParsedIR, query: dict, *, env=None, flags=None) -> list[SolverConstraints]:
    """Turn the parser IR into branch-local solver constraint variants.

    Default: exactly reproduce the current no-oracle single variant. When ``flags.disjunction`` is
    on, route through ``disjunction_stub``, which expands ``ir.or_groups`` into one branch-local
    variant per OR arm (and is a no-op for non-disjunctive queries). ``env`` is the hook for
    WorldEnv-based validation/entity resolution (pass-through for now).
    """
    variants = solver_constraint_variants(query, ir.raw, use_oracle=False)

    if flags is not None and getattr(flags, "disjunction", False):
        variants = disjunction_stub(variants, ir, query)

    return variants
