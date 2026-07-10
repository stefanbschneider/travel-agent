"""Two-layer constraint schema for the Phase 2 harness.

Layer 1 (parser IR, ``ParsedIR``): rich, uncertainty-aware, used only inside the harness. It can
hold alternative parses, disjunctive groups, confidence, raw spans, and entity-resolution
candidates.

Layer 2 (solver constraints): the stable normalized dict shape that ``TPCAgent`` already consumes
(``solver_constraint_variants`` output). We keep this unchanged so the solver never absorbs parser
ambiguity.

In the skeleton, ``ParsedIR`` is a faithful wrapper around the current deterministic no-oracle
parse (``raw``); the richer fields exist but are unused until the improvement milestones.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# The solver-facing constraint format is just a dict (kept identical to today's shape).
SolverConstraints = dict


@dataclass
class ParsedIR:
    """Parser-side intermediate representation.

    Attributes:
        raw: the deterministic parser output dict (source of truth for the skeleton passthrough).
        variants: alternative flat parses; skeleton holds exactly one (``raw``).
        or_groups: disjunctive branch descriptors (empty in the skeleton).
        confidence: per-field confidence scores (empty in the skeleton).
        field_alternatives: per-field alternative candidate values (optional).
        spans: raw extracted text spans per field (empty in the skeleton).
        entity_candidates: entity-resolution candidates per mention (empty in the skeleton).
        hard_vs_soft: split of constraints into hard vs soft (empty in the skeleton).
    """

    raw: dict = field(default_factory=dict)
    variants: list[dict] = field(default_factory=list)
    or_groups: list[Any] = field(default_factory=list)
    confidence: dict = field(default_factory=dict)
    field_alternatives: dict = field(default_factory=dict)
    spans: dict = field(default_factory=dict)
    entity_candidates: dict = field(default_factory=dict)
    hard_vs_soft: dict = field(default_factory=dict)
