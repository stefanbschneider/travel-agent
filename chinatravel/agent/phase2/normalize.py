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


def parse_to_ir(query: dict, *, llm_client=None, flags=None) -> ParsedIR:
    """Parse a query into the parser IR.

    Skeleton: wrap the deterministic no-oracle parse. The ``llm_client`` and ``flags`` arguments are
    accepted for forward-compatibility but are unused while the LLM/disjunction flags are off, so the
    LLM is never called here on the default path.
    """
    raw = parse_constraints.parse_query_no_oracle(query)
    if not isinstance(raw, dict):
        raw = {}

    # --- Flag hooks (off by default; no-ops in the skeleton) -----------------
    if flags is not None and getattr(flags, "llm_parse", False):
        # TODO(phase2): LLM-assisted second-pass parse via llm_client. Must validate against
        # WorldEnv before merging. No-op stub for now.
        pass

    return ParsedIR(raw=raw, variants=[raw])


def ir_to_solver_variants(ir: ParsedIR, query: dict, *, env=None, flags=None) -> list[SolverConstraints]:
    """Turn the parser IR into branch-local solver constraint variants.

    Skeleton: exactly reproduce the current no-oracle variants. The ``env`` argument is the hook for
    WorldEnv-based validation/entity resolution (pass-through for now).
    """
    if flags is not None and getattr(flags, "disjunction", False):
        # TODO(phase2): true no-oracle disjunctive branch generation. No-op stub for now.
        pass

    return solver_constraint_variants(query, ir.raw, use_oracle=False)
