"""Normalization layer: NL query -> ParsedIR -> branch-local solver constraint variants.

Skeleton behavior (Milestone 1): a faithful passthrough of the current no-oracle path, so output is
byte-identical to ``solver_constraint_variants(query, parse_query_no_oracle(query), use_oracle=False)``.

Flag hooks (all OFF by default; implemented in a later milestone):
- ``TPC_P2_LLM_PARSE``  : LLM-assisted second-pass parse (Stage 1 disambiguation).
- ``TPC_P2_DISJUNCTION``: true no-oracle disjunctive branch generation.

When flags are off, neither hook runs and the LLM client is never called.
"""

from __future__ import annotations

import parse_constraints
from chinatravel.agent.tpc_agent.solver_constraints import solver_constraint_variants

from .schema import ParsedIR, SolverConstraints


def llm_parse_stub(ir: ParsedIR, query: dict, llm_client) -> ParsedIR:
    """TODO(phase2, Milestone 3+): LLM-assisted second-pass parse.

    Will call ``llm_client`` for paraphrase/compound-clause disambiguation and merge the result into
    the IR, validating every proposed constraint/entity against WorldEnv before it reaches the solver.
    No-op placeholder for now (returns the IR unchanged, does not call the LLM).
    """
    return ir


def disjunction_stub(variants: list, ir: ParsedIR, query: dict) -> list:
    """TODO(phase2, Milestone 3+): true no-oracle disjunctive branch generation.

    Will expand OR-groups from the IR into branch-local solver variants (like the oracle path does
    from hard_logic_py). No-op placeholder for now (returns variants unchanged).
    """
    return variants


def parse_to_ir(query: dict, *, llm_client=None, flags=None) -> ParsedIR:
    """Parse a query into the parser IR.

    Skeleton: wrap the deterministic no-oracle parse. When ``flags.llm_parse`` is on, route through
    ``llm_parse_stub`` (a no-op placeholder). Off by default, so the LLM is never called here on the
    default path.
    """
    raw = parse_constraints.parse_query_no_oracle(query)
    if not isinstance(raw, dict):
        raw = {}
    ir = ParsedIR(raw=raw, variants=[raw])

    if flags is not None and getattr(flags, "llm_parse", False):
        ir = llm_parse_stub(ir, query, llm_client)

    return ir


def ir_to_solver_variants(ir: ParsedIR, query: dict, *, env=None, flags=None) -> list[SolverConstraints]:
    """Turn the parser IR into branch-local solver constraint variants.

    Skeleton: exactly reproduce the current no-oracle variants. When ``flags.disjunction`` is on,
    route through ``disjunction_stub`` (a no-op placeholder). ``env`` is the hook for WorldEnv-based
    validation/entity resolution (pass-through for now).
    """
    variants = solver_constraint_variants(query, ir.raw, use_oracle=False)

    if flags is not None and getattr(flags, "disjunction", False):
        variants = disjunction_stub(variants, ir, query)

    return variants
