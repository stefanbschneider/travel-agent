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

import csv
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


def build_llm_parse_prompt(query: dict, deterministic_raw: dict, *, or_groups_count: int = 0) -> str:
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
    # Only ask for OR-arm recovery when the deterministic splitter (parse_constraints.
    # detect_disjunctive/split_disjunctive_groups) hasn't already resolved >=2 branches -- the
    # merge in llm_parse_stub ignores or_arms once that many are already present (see
    # normalize.py's `if isinstance(arms, list) and len(updated.or_groups) < 2`), so asking for it
    # otherwise would just burn tokens on a proposal that gets discarded.
    or_arm_section = (
        (
            "OR-ARM RECOVERY (the deterministic splitter found fewer than 2 branches for this\n"
            "query -- check whether it actually needs this):\n"
            "  Some requests are disjunctive: the itinerary only needs to satisfy ONE of several\n"
            "  numbered/alternative conditions (phrasing varies: \"either X or Y\", \"at least one of\n"
            "  the following\", \"must satisfy one of the following conditions\", ...). If the query\n"
            "  IS disjunctive but you don't see >=2 already-correct branches reflected above, set\n"
            "  \"or_arms\" to one string per branch -- each string must be the SELF-CONTAINED\n"
            "  constraint text for that branch ALONE, as if it were the entire request (strip the\n"
            "  \"either/one of the following/...\" framing and numbering; keep every constraint that\n"
            "  belongs to that branch, drop the constraints that belong to other branches).\n"
            "  Worked example --\n"
            "    NL: \"The itinerary must satisfy one of the following: 1. Do not want to visit\n"
            "    Elm Street Museum. 2. Want to only visit free attractions.\"\n"
            "    -> \"or_arms\": [\"Do not want to visit Elm Street Museum\",\n"
            "                     \"Want to only visit free attractions\"]\n"
            "  If the query is NOT disjunctive, leave \"or_arms\" empty -- do not invent branches.\n\n"
        )
        if or_groups_count < 2
        else ""
    )
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
        f"{or_arm_section}"
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

    prompt = build_llm_parse_prompt(query, ir.raw, or_groups_count=len(ir.or_groups))
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


# --- LLM-first structured extraction (plan-2 Step 6) -----------------------
#
# Alternative to the corrective-audit stub above: one LLM call reads the NL query directly (no
# deterministic parse in the prompt -- independence avoids anchoring on regex mistakes, and
# decouples the LLM cache from regex changes: audit-mode embeds ir.raw in the prompt, so every
# regex fix cold-starts the 850-uid cache; extract-mode's prompt depends only on query text).
# Deterministic validation (whitelist + closed-vocabulary checks, no LLM) gates every field before
# it can reach the solver; merge is additive-only -- a family only the deterministic parse found
# is always kept (an invalid/absent LLM value must never delete real recall, the lesson of the
# audit's B6 gap).

_EXTRACT_ROOM_TYPES = frozenset({"single", "double", "twin"})
_EXTRACT_CUISINE_FIELDS = {"cuisine_preference", "excluded_cuisine_types"}
_EXTRACT_HOTEL_FEATURE_FIELDS = {"required_hotel_any_types", "required_hotel_all_types", "hotel_amenity"}
_EXTRACT_RESTAURANTS_GLOB = "chinatravel/environment/database_en/restaurants/**/*.csv"
_EXTRACT_ACCOMMODATIONS_GLOB = "chinatravel/environment/database_en/accommodations/**/*.csv"
_EXTRACT_PROJECT_ROOT = None  # resolved lazily in _extract_vocab (import-time __file__ games are fragile)


def _extract_project_root():
    global _EXTRACT_PROJECT_ROOT
    if _EXTRACT_PROJECT_ROOT is None:
        from pathlib import Path

        _EXTRACT_PROJECT_ROOT = Path(__file__).resolve().parents[3]
    return _EXTRACT_PROJECT_ROOT


_extract_vocab_cache: dict | None = None


def _extract_vocab() -> dict[str, frozenset[str]]:
    """Closed vocabularies derived once from the committed environment data: cuisine names
    (restaurants CSVs' ``cuisine`` column) and hotel feature/type strings (accommodations CSVs'
    ``featurehoteltype`` column, '/'-separated). Case-folded for matching. room_type's vocabulary
    is the regex parser's own fixed 3-value set (``parse_constraints.parse_room_type``). Cached
    process-wide (module-level dict, not functools.lru_cache, so tests can monkeypatch it)."""
    global _extract_vocab_cache
    if _extract_vocab_cache is not None:
        return _extract_vocab_cache

    root = _extract_project_root()
    cuisines: set[str] = set()
    for path in root.glob(_EXTRACT_RESTAURANTS_GLOB):
        with open(path, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                c = (row.get("cuisine") or "").strip()
                if c:
                    cuisines.add(c.lower())
    hotel_features: set[str] = set()
    for path in root.glob(_EXTRACT_ACCOMMODATIONS_GLOB):
        with open(path, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                for part in (row.get("featurehoteltype") or "").split("/"):
                    part = part.strip()
                    if part:
                        hotel_features.add(part.lower())

    _extract_vocab_cache = {
        "cuisine": frozenset(cuisines),
        "hotel_feature": frozenset(hotel_features),
        "room_type": _EXTRACT_ROOM_TYPES,
    }
    return _extract_vocab_cache


def _validate_extract_field(key: str, value, vocab: dict[str, frozenset[str]]):
    """One field's deterministic validation. Returns the cleaned value, or None if nothing about
    it survives validation (caller drops the key entirely in that case)."""
    if key == "free_attractions_only":
        return bool(value) if isinstance(value, bool) else None
    if key == "room_type":
        if isinstance(value, str) and value.strip().lower() in vocab["room_type"]:
            return value.strip().lower()
        return None
    if key in _EXTRACT_CUISINE_FIELDS or key in _EXTRACT_HOTEL_FEATURE_FIELDS:
        pool = vocab["cuisine"] if key in _EXTRACT_CUISINE_FIELDS else vocab["hotel_feature"]
        candidates = value if isinstance(value, list) else [value]
        items = [
            v.strip() for v in candidates
            if isinstance(v, str) and v.strip().lower() in pool
        ]
        return items or None
    if key in _LLM_PARSE_LIST_KEYS:
        if not isinstance(value, list):
            return None
        items = [v for v in value if isinstance(v, str) and v.strip()]
        return items or None
    if key in _LLM_PARSE_DICT_KEYS:
        return value if isinstance(value, dict) and value else None
    # Remaining scalar keys (none left unhandled today, but future _LLM_PARSE_ALLOWED_KEYS
    # additions land here rather than being silently dropped by an exhaustive if/elif).
    if key in _LLM_PARSE_SCALAR_KEYS:
        return value if isinstance(value, str) and value.strip() else None
    return None


def validate_extract_families(raw_families, *, vocab: dict[str, frozenset[str]] | None = None) -> dict:
    """Deterministic validation layer for an LLM extraction response's ``families`` object: key
    whitelist (``_LLM_PARSE_ALLOWED_KEYS``) + type checks (the existing LIST/DICT/SCALAR key
    sets) + closed-vocabulary checks for room_type/cuisine/hotel-feature fields. Never raises;
    an invalid or unrecognized value is dropped, not guessed at."""
    if not isinstance(raw_families, dict):
        return {}
    vocab = vocab if vocab is not None else _extract_vocab()
    validated: dict = {}
    for key, value in raw_families.items():
        if key not in _LLM_PARSE_ALLOWED_KEYS:
            continue
        cleaned = _validate_extract_field(key, value, vocab)
        if cleaned is not None:
            validated[key] = cleaned
    return validated


_EXTRACT_FAMILY_SPEC = (
    "budgets: object mapping cost category to a CNY amount, e.g. {\"total\": 3000} for an"
    " overall trip budget, or {\"sightseeing\": 800} / {\"hotel\": ...} / {\"food\": ...} for a"
    " category-specific budget. Use the category the traveler actually named -- only use"
    " \"total\" when they said \"total\"/\"overall\"/\"the budget\" generically, not for a"
    " named category like sightseeing.\n"
    "free_attractions_only: boolean -- itinerary may only include free attractions.\n"
    "intercity_mode: object {go?: string, back?: string} -- required intercity transport mode(s)"
    " (e.g. \"train\", \"flight\").\n"
    "excluded_inner_transport: array of strings -- in-city transport modes to avoid"
    " (e.g. \"taxi\", \"metro\").\n"
    "room_type: one of \"single\", \"double\", \"twin\" -- required hotel room type.\n"
    "required_hotel_any_types/required_hotel_all_types: array of hotel feature/type strings from"
    " the traveler's request (e.g. \"Hot spring bathing\", \"Family Room\") -- ANY-of vs ALL-of.\n"
    "required_attractions/excluded_attractions: array of specific attraction names.\n"
    "required_attraction_types/excluded_attraction_types: array of attraction category strings.\n"
    "required_restaurants/excluded_restaurants: array of specific restaurant names.\n"
    "cuisine_preference/excluded_cuisine_types: array of cuisine names from the traveler's"
    " request (e.g. \"Hot pot\", \"Japanese cuisine\").\n"
    "required_hotels/excluded_hotels: array of specific hotel names.\n"
    "timing_constraints/activity_time_windows: array of {reference: string, ...time fields}"
    " describing a stated visiting-time requirement.\n"
    "conditional_transport: object describing a transport mode conditioned on some situation.\n"
    "hotel_nearby: object {reference: string, distance_km: number} -- hotel proximity requirement.\n"
    "stay_duration: array of {reference: string, minutes: number} -- minimum time to spend"
    " somewhere.\n"
    "position_presence: array of positional/ordering requirements.\n"
)

_EXTRACT_FEW_SHOT = (
    "Example 1 (simple):\n"
    "Query: \"3 days in Beijing, 2 people, budget 3000 CNY total, want to stay in a twin room, "
    "must visit the Forbidden City.\"\n"
    "Output: {\"families\": {\"budgets\": {\"total\": 3000}, \"room_type\": \"twin\", "
    "\"required_attractions\": [\"Forbidden City\"]}, \"or_arms\": []}\n\n"
    "Example 2 (negation -- do not invent a required_* family from a negated clause):\n"
    "Query: \"2 days in Shanghai, 1 person, do not want to visit any Amusement Park.\"\n"
    "Output: {\"families\": {\"excluded_attraction_types\": [\"Amusement Park\"]}, \"or_arms\": []}\n\n"
    "Example 3 (disjunctive):\n"
    "Query: \"4 days in Chengdu, 2 people. The itinerary must satisfy one of the following: "
    "1. Stay in a hotel with Hot spring bathing. 2. Only visit free attractions.\"\n"
    "Output: {\"families\": {}, \"or_arms\": [\"Stay in a hotel with Hot spring bathing\", "
    "\"Only visit free attractions\"]}\n"
)


def build_llm_extract_prompt(query: dict) -> str:
    """Prompt for LLM-first structured extraction. Deliberately does NOT include the
    deterministic parse (see the module-docstring note above this section) -- independence from
    regex mistakes, and it keeps the LLM cache stable across regex-only commits."""
    visible = {
        "uid": query.get("uid"),
        "people_number": query.get("people_number"),
        "start_city": query.get("start_city"),
        "target_city": query.get("target_city"),
        "days": query.get("days"),
        "nature_language": query.get("nature_language", ""),
    }
    return (
        "Extract structured travel-planning constraints from the traveler's request below.\n"
        "Return STRICT JSON only (no markdown/code fences) with this schema:\n"
        "{\"families\": {<field name>: <value>, ...}, \"or_arms\": [string, ...]}\n\n"
        "FIELDS (use only these names; omit any field the request does not mention):\n"
        f"{_EXTRACT_FAMILY_SPEC}\n"
        "OR-ARMS: some requests are disjunctive -- the itinerary only needs to satisfy ONE of\n"
        "several numbered/alternative conditions (phrasing varies: \"either X or Y\", \"at least\n"
        "one of the following\", \"must satisfy one of the following conditions\", ...). If the\n"
        "request IS disjunctive, set \"or_arms\" to one string per branch -- each string must be\n"
        "the SELF-CONTAINED constraint text for that branch ALONE, as if it were the entire\n"
        "request (strip the \"either/one of the following/...\" framing and numbering). If the\n"
        "request is NOT disjunctive, leave \"or_arms\" empty and put everything in \"families\".\n\n"
        f"{_EXTRACT_FEW_SHOT}\n"
        "Rules:\n"
        "- Use only facts stated in the request; never invent hotels, attractions, numbers, or\n"
        "  cuisine/hotel-feature names not present in the text.\n"
        "- Read negations carefully (\"do not\", \"don't\", \"no\", \"avoid\", \"without\",\n"
        "  \"except\") -- a negated clause is an excluded_*/excluded_attraction_types family, NOT\n"
        "  a required_* one.\n"
        "- If the request states no constraints at all, return {\"families\": {}, \"or_arms\": []}.\n\n"
        "Traveler's request JSON:\n"
        f"{json.dumps(visible, ensure_ascii=False, indent=2)}"
    )


def llm_extract_stub(ir: ParsedIR, query: dict, llm_client) -> ParsedIR:
    """LLM-first structured extraction with strict deterministic fallback (same contract as
    ``llm_parse_stub``: any error keeps ``ir`` unchanged by raising, so the orchestrator's
    try/except degrades to the deterministic parse). Merge policy is additive-only:

    - a validated LLM value overwrites the deterministic value for that family;
    - an invalid/absent LLM value keeps the deterministic value if the deterministic parse found
      one (the LLM can never silently delete a family the regex already recalled correctly --
      plan-1 gap B6, the audit's failure mode);
    - or_arms are only used when the deterministic splitter found fewer than 2 branches (same
      precedence as the audit path).
    """
    if llm_client is None or not hasattr(llm_client, "complete"):
        return ir

    prompt = build_llm_extract_prompt(query)
    cache_key = llm_parse_cache_key(query, prompt)
    response = llm_client.complete(prompt, cache_key=cache_key)
    payload = _parse_llm_json_blob(response)

    validated = validate_extract_families(payload.get("families"))

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
    # Additive merge: start from the deterministic raw parse, overwrite only with validated LLM
    # values. Deterministic-only families (the LLM omitted or produced an invalid value for them)
    # survive untouched. Dict-shaped families (budgets, ...) merge at the SUB-KEY level rather
    # than a whole-value replace -- a whole-value replace would silently drop a deterministic
    # sub-key the LLM's dict didn't happen to mention (observed live: NL "the budget for
    # sightseeing is 800" parses deterministically to budgets={"sightseeing": 800}, but the LLM
    # extracted budgets={"total": 800} -- a blind replace would have lost "sightseeing" entirely).
    for key, value in validated.items():
        if key in _LLM_PARSE_DICT_KEYS and isinstance(updated.raw.get(key), dict):
            merged = dict(updated.raw[key])
            merged.update(value)
            updated.raw[key] = merged
        else:
            updated.raw[key] = value

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


def parse_to_ir(query: dict, *, llm_client=None, flags=None, deadline: float | None = None) -> ParsedIR:
    """Parse a query into the parser IR.

    Wraps the deterministic no-oracle parse (source of truth for the flat single variant). When
    ``flags.disjunction`` is on and the query is NL-detectably disjunctive, also populate
    ``ir.or_groups`` with one parsed constraint dict per OR arm (consumed by
    ``ir_to_solver_variants``). When ``flags.llm_parse`` is on, routes through ``llm_parse_stub``
    (``flags.llm_parse_mode == "audit"``, the default) or ``llm_extract_stub``
    (``"extract"``, plan-2 Step 6) for corrective/additive proposals. Off by default, so the LLM
    is never called here on the default path.

    ``deadline``, when given, is the remaining parse-stage budget in seconds (the orchestrator's
    static or dynamic parse slice). If it's below the LLM client's configured request timeout, the
    call is guaranteed not to finish in time, so it's skipped entirely rather than started and
    left to time out (``ir.llm_parse_skipped_deadline`` records this for telemetry).
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
        # llm_parse_stub raises on any failure by design (network error, malformed response,
        # ...) so the deterministic ir it was given is never silently corrupted. That contract
        # only helps if the caller actually keeps the pre-call ir on failure instead of letting
        # the exception propagate -- previously it didn't: orchestrator.solve_phase2 wraps this
        # whole function in a broad try/except that discards ir entirely (variants=[]) on any
        # parse-stage exception, including a transient LLM failure that has nothing to do with
        # the deterministic parse already sitting in `ir`. Catch here instead, so a flaky LLM
        # backend degrades to the deterministic parse rather than to no parse at all.
        client_timeout = getattr(llm_client, "timeout", None)
        if deadline is not None and client_timeout is not None and deadline < client_timeout:
            ir.llm_parse_skipped_deadline = True
        else:
            mode = getattr(flags, "llm_parse_mode", "audit")
            stub = llm_extract_stub if mode == "extract" else llm_parse_stub
            try:
                ir = stub(ir, query, llm_client)
            except Exception as exc:
                ir.llm_parse_error = repr(exc)

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
