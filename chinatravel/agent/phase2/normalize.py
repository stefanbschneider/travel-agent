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

import hashlib
import json

import parse_constraints
from chinatravel.agent.tpc_agent.solver_constraints import (
    _BRANCH_LOCAL_KEYS,
    solver_constraint_variants,
)

from .schema import ParsedIR, SolverConstraints


_LLM_PARSE_ALLOWED_KEYS = {
    "budgets",
    "free_attractions_only",
    "intercity_mode",
    "excluded_inner_transport",
    "room_type",
    "required_hotel_any_types",
    "required_hotel_all_types",
    "hotel_nearby",
    "required_attractions",
    "required_attraction_types",
    "excluded_attraction_types",
    "excluded_attractions",
    "required_restaurants",
    "excluded_restaurants",
    "cuisine_preference",
    "excluded_cuisine_types",
    "timing_constraints",
    "activity_time_windows",
    "conditional_transport",
    "required_hotels",
    "excluded_hotels",
    "hotel_amenity",
    "stay_duration",
    "position_presence",
}


def _stable_prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12]


def llm_parse_cache_key(query: dict, prompt: str) -> str:
    uid = str(query.get("uid") or "unknown")
    return f"parse_{uid}_{_stable_prompt_hash(prompt)}"


def build_llm_parse_prompt(query: dict, deterministic_raw: dict) -> str:
    visible = {
        "uid": query.get("uid"),
        "people_number": query.get("people_number"),
        "start_city": query.get("start_city"),
        "target_city": query.get("target_city"),
        "nature_language": query.get("nature_language", ""),
    }
    return (
        "You are assisting a deterministic travel-constraint parser.\n"
        "Return STRICT JSON only (no markdown/code fences) with this schema:\n"
        "{\n"
        "  \"constraint_text\": string,\n"
        "  \"or_groups\": [string, ...]\n"
        "}\n"
        "Rules:\n"
        "- Use only facts inferable from the visible query.\n"
        "- Keep wording concise and literal.\n"
        "- If no useful refinement, return {\"constraint_text\":\"\",\"or_groups\":[]}.\n"
        "Visible query JSON:\n"
        f"{json.dumps(visible, ensure_ascii=False, indent=2)}\n\n"
        "Current deterministic parse JSON:\n"
        f"{json.dumps(deterministic_raw, ensure_ascii=False, indent=2)}"
    )


def _parse_llm_json_blob(text: str) -> dict:
    raw = (text or "").strip()
    if not raw:
        return {}
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else ""
        raw = raw.rsplit("```", 1)[0].strip()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"llm_parse invalid JSON: {exc}") from None
    if not isinstance(value, dict):
        raise ValueError("llm_parse response must be a JSON object")
    return value


def _merge_constraint_dict(base: dict, extra: dict) -> dict:
    merged = dict(base)
    for key, value in extra.items():
        if key not in _LLM_PARSE_ALLOWED_KEYS:
            continue
        if key not in merged:
            merged[key] = value
            continue

        # Conservative merge: keep deterministic values and only add missing detail.
        if key == "budgets" and isinstance(merged[key], dict) and isinstance(value, dict):
            out = dict(merged[key])
            for budget_key, budget_val in value.items():
                out.setdefault(budget_key, budget_val)
            merged[key] = out
        elif key == "intercity_mode" and isinstance(merged[key], dict) and isinstance(value, dict):
            out = dict(merged[key])
            for mode_key, mode_val in value.items():
                out.setdefault(mode_key, mode_val)
            merged[key] = out
        elif isinstance(merged[key], list) and isinstance(value, list):
            seen = {json.dumps(v, ensure_ascii=False, sort_keys=True) for v in merged[key]}
            for item in value:
                marker = json.dumps(item, ensure_ascii=False, sort_keys=True)
                if marker not in seen:
                    merged[key].append(item)
                    seen.add(marker)
    return merged


def llm_parse_stub(ir: ParsedIR, query: dict, llm_client) -> ParsedIR:
    """LLM-assisted second-pass parse with strict fallback to deterministic behavior.

    The LLM proposes extra parse signal as free text / OR-arm text only; deterministic parsers then
    re-parse and validate that signal into known constraint families. Any error keeps ``ir``
    unchanged by raising, so the orchestrator can degrade safely.
    """
    if llm_client is None or not hasattr(llm_client, "complete"):
        return ir

    prompt = build_llm_parse_prompt(query, ir.raw)
    cache_key = llm_parse_cache_key(query, prompt)
    response = llm_client.complete(prompt, cache_key=cache_key)
    payload = _parse_llm_json_blob(response)

    updated = ParsedIR(
        raw=dict(ir.raw),
        variants=list(ir.variants),
        or_groups=list(ir.or_groups),
        confidence=dict(ir.confidence),
        spans=dict(ir.spans),
        entity_candidates=dict(ir.entity_candidates),
        hard_vs_soft=dict(ir.hard_vs_soft),
    )

    extra_text = str(payload.get("constraint_text") or "").strip()
    if extra_text:
        extra = parse_constraints.parse_single_constraint_text(extra_text)
        if isinstance(extra, dict) and extra:
            updated.raw = _merge_constraint_dict(updated.raw, extra)

    groups = payload.get("or_groups")
    if isinstance(groups, list):
        parsed_groups = []
        for item in groups:
            if not isinstance(item, str):
                continue
            part = parse_constraints.parse_single_constraint_text(item.strip())
            if isinstance(part, dict) and part:
                parsed_groups.append(part)
        if len(parsed_groups) >= 2:
            updated.or_groups = parsed_groups

    return updated


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
