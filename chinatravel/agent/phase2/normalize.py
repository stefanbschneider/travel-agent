"""Normalization layer: NL query -> ParsedIR -> branch-local solver constraint variants.

Default behavior (all flags OFF): a faithful passthrough of the current no-oracle path, so output
is byte-identical to ``solver_constraint_variants(query, parse_query_no_oracle(query),
use_oracle=False)``.

Flag hooks (all OFF by default):
- ``TPC_P2_LLM_PARSE``  : LLM-assisted second-pass parse (corrective/additive proposals).
- ``TPC_P2_DISJUNCTION``: true no-oracle disjunctive branch generation (implemented below).

When flags are off, neither hook runs and the LLM client is never called.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy

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

_LLM_PARSE_LIST_KEYS = {
    "required_attractions",
    "required_attraction_types",
    "excluded_attraction_types",
    "excluded_attractions",
    "required_restaurants",
    "excluded_restaurants",
    "excluded_cuisine_types",
    "timing_constraints",
    "activity_time_windows",
    "required_hotels",
    "excluded_hotels",
    "stay_duration",
    "position_presence",
    "required_hotel_any_types",
    "required_hotel_all_types",
    "excluded_inner_transport",
}
_LLM_PARSE_DICT_KEYS = {"budgets", "intercity_mode", "hotel_nearby", "conditional_transport"}
_LLM_PARSE_SCALAR_KEYS = {
    "free_attractions_only",
    "room_type",
    "cuisine_preference",
    "hotel_amenity",
}
_MAX_ALTERNATIVES_PER_FIELD = 3
_MAX_ALT_VARIANTS = 6


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
    # Enumerate the families the deterministic parser actually emitted so the model is forced to
    # audit each one against the quoted NL (confirm-or-remove), instead of optionally "refining".
    extracted_fields = [k for k in deterministic_raw.keys() if k in _LLM_PARSE_ALLOWED_KEYS]
    audit_list = ", ".join(extracted_fields) if extracted_fields else "(none)"
    return (
        "You are auditing the output of a deterministic (regex) travel-constraint parser.\n"
        "The regex parser is known to OVER-EXTRACT: it emits spurious constraint families that the\n"
        "traveler's request does not actually support (for example a negated \"do not want to visit\n"
        "X\" clause wrongly producing a `required_*` family, or a phrase captured under the wrong\n"
        "family). Your job is to catch those errors.\n\n"
        "Return STRICT JSON only (no markdown/code fences) with this schema:\n"
        "{\n"
        "  \"patches\": [\n"
        "    {\"mode\":\"add|replace|remove\", \"constraint_text\": string, \"fields\": [string], \"confidence\": number}\n"
        "  ],\n"
        "  \"or_arms\": [string, ...],\n"
        "  \"field_alternatives\": {\"field_name\": [{\"constraint_text\": string, \"confidence\": number}]},\n"
        "  \"field_confidence\": {\"field_name\": number}\n"
        "}\n"
        "AUDIT PROCEDURE (do this for EVERY extracted family, do not skip any):\n"
        f"  Extracted families to audit: {audit_list}\n"
        "  1. For each extracted family, find the exact span of the natural-language request that\n"
        "     supports it. Read the surrounding words, especially negations (\"do not\", \"don't\",\n"
        "     \"no\", \"avoid\", \"without\", \"except\").\n"
        "  2. If the quoted text does NOT support the extracted family, or supports the OPPOSITE\n"
        "     polarity (e.g. it is an exclusion mis-labeled as a requirement, or vice versa), emit a\n"
        "     `remove` patch naming that field. When the correct family is the opposite polarity,\n"
        "     also emit an `add`/`replace` patch with literal constraint_text for the correct family.\n"
        "  3. If the quoted text DOES support the extracted family, leave it untouched (no patch).\n"
        "  4. Add families only when the request clearly states a constraint the parser missed.\n\n"
        "Rules:\n"
        "- Use only facts inferable from the visible query; never invent hotels, attractions, or numbers.\n"
        "- Keep wording concise and literal; constraint_text must be parseable deterministically.\n"
        "- A `remove` patch must set \"fields\" to the exact family name(s) to drop; \"constraint_text\"\n"
        "  may quote the NL span that proves the family is wrong.\n"
        "- Prefer removing a demonstrably spurious family over leaving it in. Returning an empty\n"
        "  patch list asserts that EVERY extracted family is correct -- only do so after auditing all.\n"
        "- If, after auditing, nothing needs to change, return\n"
        "  {\"patches\":[],\"or_arms\":[],\"field_alternatives\":{},\"field_confidence\":{}}.\n"
        "Visible query JSON:\n"
        f"{json.dumps(visible, ensure_ascii=False, indent=2)}\n\n"
        "Current deterministic parse JSON (audit each family below):\n"
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


def _dedupe_json_items(values: list) -> list:
    out = []
    seen = set()
    for item in values:
        marker = json.dumps(item, ensure_ascii=False, sort_keys=True)
        if marker in seen:
            continue
        seen.add(marker)
        out.append(item)
    return out


def _apply_patch(base: dict, patch: dict, *, mode: str) -> dict:
    """Apply one parsed patch dict with conservative deterministic semantics."""
    out = deepcopy(base)
    if mode == "remove":
        for key in patch:
            if key in _LLM_PARSE_ALLOWED_KEYS:
                out.pop(key, None)
        return out

    for key, value in patch.items():
        if key not in _LLM_PARSE_ALLOWED_KEYS:
            continue
        if mode == "replace":
            if key == "budgets" and isinstance(out.get(key), dict) and isinstance(value, dict):
                merged = dict(out[key])
                merged.update(value)
                out[key] = merged
            elif key == "intercity_mode" and isinstance(out.get(key), dict) and isinstance(value, dict):
                merged = dict(out[key])
                merged.update(value)
                out[key] = merged
            else:
                out[key] = value
            continue

        # mode == add
        if key not in out:
            out[key] = value
            continue
        if key in _LLM_PARSE_DICT_KEYS and isinstance(out.get(key), dict) and isinstance(value, dict):
            merged = dict(out[key])
            for nested_key, nested_val in value.items():
                merged.setdefault(nested_key, nested_val)
            out[key] = merged
        elif key in _LLM_PARSE_LIST_KEYS and isinstance(out.get(key), list) and isinstance(value, list):
            out[key] = _dedupe_json_items(list(out[key]) + value)
        elif key in _LLM_PARSE_SCALAR_KEYS:
            out.setdefault(key, value)
    return out


def _parse_constraint_text(text: str) -> dict:
    parsed = parse_constraints.parse_single_constraint_text(text)
    if not isinstance(parsed, dict):
        return {}
    return {k: v for k, v in parsed.items() if k in _LLM_PARSE_ALLOWED_KEYS}


def _clamp_conf(value) -> float | None:
    try:
        conf = float(value)
    except (TypeError, ValueError):
        return None
    if conf < 0.0:
        return 0.0
    if conf > 1.0:
        return 1.0
    return conf


def _parse_llm_alternatives(payload: dict) -> dict:
    raw = payload.get("field_alternatives")
    if not isinstance(raw, dict):
        return {}

    alternatives: dict[str, list[dict]] = {}
    for field, entries in raw.items():
        if field not in _LLM_PARSE_ALLOWED_KEYS or not isinstance(entries, list):
            continue
        parsed_entries = []
        for entry in entries[:_MAX_ALTERNATIVES_PER_FIELD]:
            if not isinstance(entry, dict):
                continue
            text = str(entry.get("constraint_text") or "").strip()
            if not text:
                continue
            parsed = _parse_constraint_text(text)
            if field not in parsed:
                continue
            alt = {"value": parsed[field]}
            conf = _clamp_conf(entry.get("confidence"))
            if conf is not None:
                alt["confidence"] = conf
            parsed_entries.append(alt)
        if parsed_entries:
            alternatives[field] = parsed_entries
    return alternatives


def llm_parse_stub(ir: ParsedIR, query: dict, llm_client) -> ParsedIR:
    """LLM-assisted second-pass parse with strict fallback to deterministic behavior.

    The LLM proposes structured patch/alternative/OR-arm signals; deterministic parsers then
    re-parse and validate those proposals into known constraint families before they are consumed.
    Any error keeps ``ir`` unchanged by raising, so the orchestrator can degrade safely.
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
        field_alternatives=deepcopy(ir.field_alternatives),
        spans=dict(ir.spans),
        entity_candidates=dict(ir.entity_candidates),
        hard_vs_soft=dict(ir.hard_vs_soft),
    )

    # Backward-compatibility with older fixture schema.
    legacy_text = str(payload.get("constraint_text") or "").strip()
    if legacy_text:
        extra = _parse_constraint_text(legacy_text)
        if extra:
            updated.raw = _apply_patch(updated.raw, extra, mode="add")

    legacy_groups = payload.get("or_groups")
    if isinstance(legacy_groups, list) and len(updated.or_groups) < 2:
        parsed_groups = []
        for item in legacy_groups:
            if not isinstance(item, str):
                continue
            part = _parse_constraint_text(item.strip())
            if part:
                parsed_groups.append(part)
        if len(parsed_groups) >= 2:
            updated.or_groups = parsed_groups

    patches = payload.get("patches")
    if isinstance(patches, list):
        for patch in patches:
            if not isinstance(patch, dict):
                continue
            mode = str(patch.get("mode") or "add").lower().strip()
            if mode not in {"add", "replace", "remove"}:
                continue

            patch_dict: dict = {}
            if mode == "remove":
                fields = patch.get("fields")
                if isinstance(fields, list):
                    patch_dict = {f: True for f in fields if isinstance(f, str) and f in _LLM_PARSE_ALLOWED_KEYS}
            else:
                constraint_text = str(patch.get("constraint_text") or "").strip()
                if constraint_text:
                    patch_dict = _parse_constraint_text(constraint_text)
            if not patch_dict:
                continue

            updated.raw = _apply_patch(updated.raw, patch_dict, mode=mode)

            conf = _clamp_conf(patch.get("confidence"))
            if conf is not None:
                for key in patch_dict:
                    prev = updated.confidence.get(key)
                    if prev is None:
                        updated.confidence[key] = conf
                    else:
                        try:
                            updated.confidence[key] = max(float(prev), conf)
                        except (TypeError, ValueError):
                            updated.confidence[key] = conf

    # Extra per-field confidence signal.
    field_conf = payload.get("field_confidence")
    if isinstance(field_conf, dict):
        for key, raw_conf in field_conf.items():
            if key not in _LLM_PARSE_ALLOWED_KEYS:
                continue
            conf = _clamp_conf(raw_conf)
            if conf is not None:
                updated.confidence[key] = conf

    # Field-level alternatives are stored in IR and expanded into extra deterministic variants.
    updated.field_alternatives.update(_parse_llm_alternatives(payload))

    arms = payload.get("or_arms")
    if isinstance(arms, list) and len(updated.or_groups) < 2:
        parsed_groups = []
        for item in arms:
            if not isinstance(item, str):
                continue
            part = _parse_constraint_text(item.strip())
            if part:
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
    for corrective/additive proposals. Off by default, so the LLM is never called here on the
    default path.
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


def alternatives_stub(variants: list, ir: ParsedIR, query: dict, *, flags=None) -> list:
    """Expand field alternatives into additional deterministic solver variants.

    The LLM only proposes alternatives; each alternative is run through the same deterministic
    normalization path as the base parse. No acceptance decision is taken here.
    """
    alternatives = getattr(ir, "field_alternatives", None) or {}
    if not alternatives:
        return variants

    expanded = list(variants)
    seen = {json.dumps(v, ensure_ascii=False, sort_keys=True) for v in expanded}

    alt_count = 0
    for field, entries in alternatives.items():
        if field not in _LLM_PARSE_ALLOWED_KEYS or not isinstance(entries, list):
            continue
        for entry in entries:
            if alt_count >= _MAX_ALT_VARIANTS:
                return expanded
            if not isinstance(entry, dict) or "value" not in entry:
                continue

            alt_raw = deepcopy(ir.raw)
            alt_raw = _apply_patch(alt_raw, {field: entry["value"]}, mode="replace")
            alt_ir = ParsedIR(raw=alt_raw, variants=[alt_raw], or_groups=list(ir.or_groups))

            alt_variants = solver_constraint_variants(query, alt_raw, use_oracle=False)
            if flags is not None and getattr(flags, "disjunction", False):
                alt_variants = disjunction_stub(alt_variants, alt_ir, query)

            for variant in alt_variants:
                marker = json.dumps(variant, ensure_ascii=False, sort_keys=True)
                if marker in seen:
                    continue
                seen.add(marker)
                expanded.append(variant)
            alt_count += 1
    return expanded


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

    if flags is not None and getattr(flags, "llm_parse", False):
        variants = alternatives_stub(variants, ir, query, flags=flags)

    return variants
