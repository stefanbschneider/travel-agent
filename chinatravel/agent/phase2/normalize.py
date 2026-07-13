"""Normalization layer: NL query -> ParsedIR -> branch-local solver constraint variants.

Default behavior (all flags OFF): a faithful passthrough of the current no-oracle path, so output
is byte-identical to ``solver_constraint_variants(query, parse_query_no_oracle(query),
use_oracle=False)``.

Flag hooks (all OFF by default):
- ``TPC_P2_LLM_PARSE``  : LLM-assisted second-pass parse (corrective/additive proposals).
- ``TPC_P2_DISJUNCTION``: true no-oracle disjunctive branch generation (implemented below).
- ``TPC_P2_ENTITY_RESOLUTION``: deterministic name-entity canonicalization against the target
  city's POI catalog (implemented below, plan3 N2).

When flags are off, neither hook runs and the LLM client is never called.
"""

from __future__ import annotations

import csv
import difflib
import hashlib
import json
import re
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


# --- Deterministic entity resolution (plan3 N2) -----------------------------
#
# Canonicalizes name-bearing constraint families against the target city's POI catalog before they
# reach the solver/verifier, closing the G2 defect cluster (label-prefix garbage kept in names,
# list-splitting failures, type-vs-name collisions, category misrouting -- see docs/tpc_phase2_plan3.md).
# Env-less (same lazy/cached CSV-glob pattern as ``_extract_vocab`` above) so ``parser_vs_oracle.py``
# sees identical behavior to the harness. Recall-preserving per G1: an unresolved string is kept as
# cleaned text, never dropped.

_ENTITY_CSV_GLOBS = {
    "attraction": "chinatravel/environment/database_en/attractions/{slug}/*.csv",
    "restaurant": "chinatravel/environment/database_en/restaurants/{slug}/*.csv",
    "hotel": "chinatravel/environment/database_en/accommodations/{slug}/*.csv",
}
_ENTITY_CATEGORY_FOR_FIELD = {
    "required_attractions": "attraction",
    "excluded_attractions": "attraction",
    "required_restaurants": "restaurant",
    "excluded_restaurants": "restaurant",
    "required_hotels": "hotel",
    "excluded_hotels": "hotel",
}
_ENTITY_TYPE_FIELD_FOR = {
    "required_attractions": "required_attraction_types",
    "excluded_attractions": "excluded_attraction_types",
}
_ENTITY_FUZZY_THRESHOLD = 0.85

_ENTITY_LABEL_PREFIX_RES = [
    re.compile(r"^one of (?:the following|these)\s*(?:restaurants|hotels|attractions)?\s*:?\s*", re.IGNORECASE),
    re.compile(r"^the\s+(?:restaurant|hotel|attraction)s?\s+", re.IGNORECASE),
]
_ENTITY_LABEL_SUFFIX_RES = [
    re.compile(r"\s+for no less than\b.*$", re.IGNORECASE),
]
_ENTITY_PUNCT_RE = re.compile(r"[·\-_/,():;!?\"'’‘“”]")
_ENTITY_TRAILING_NUMBER_RE = re.compile(r"\s+\d+$")
_ENTITY_SPLIT_RE = re.compile(r"\s*(?:,|\band\b|\bor\b)\s*", re.IGNORECASE)

_entity_catalog_cache: dict[str, dict[str, list[str]]] = {}
_attraction_type_vocab_cache: dict[str, str] | None = None


def _city_slug(city) -> str | None:
    if not city or not isinstance(city, str):
        return None
    from chinatravel.environment.language import CITY_SLUGS, city_names

    lookup = {name.lower(): slug for slug, name in zip(CITY_SLUGS, city_names("en"))}
    return lookup.get(city.strip().lower())


def load_city_entity_catalog(city) -> dict[str, list[str]]:
    """Lazy, process-cached per-city name catalog: attraction/restaurant/hotel names read
    directly from the committed database_en CSVs (the same source WorldEnv loads), so this works
    without a live ``env`` object -- ``parser_vs_oracle.py`` and the real harness see identical
    resolution behavior. Unknown/unmapped city -> empty catalog (resolution is then a no-op)."""
    slug = _city_slug(city)
    if slug is None:
        return {"attraction": [], "restaurant": [], "hotel": []}
    if slug in _entity_catalog_cache:
        return _entity_catalog_cache[slug]

    root = _extract_project_root()
    catalog: dict[str, list[str]] = {}
    for category, glob_pattern in _ENTITY_CSV_GLOBS.items():
        names: list[str] = []
        for path in root.glob(glob_pattern.format(slug=slug)):
            with open(path, encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f):
                    n = (row.get("name") or "").strip()
                    if n:
                        names.append(n)
        catalog[category] = names
    _entity_catalog_cache[slug] = catalog
    return catalog


def _attraction_type_vocab() -> dict[str, str]:
    """normalized type string -> canonical (CSV-literal) type string, e.g. 'amusement
    park/sports entertainment' -> 'Amusement Park/Sports Entertainment'. The CSV 'type' column is
    used verbatim (not split on '/') -- the solver's own type matcher already does segment-level
    matching against a compound type at evaluation time."""
    global _attraction_type_vocab_cache
    if _attraction_type_vocab_cache is not None:
        return _attraction_type_vocab_cache
    root = _extract_project_root()
    vocab: dict[str, str] = {}
    for path in root.glob("chinatravel/environment/database_en/attractions/*/attractions.csv"):
        with open(path, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                t = (row.get("type") or "").strip()
                if t:
                    vocab.setdefault(_norm_entity_key(t), t)
    _attraction_type_vocab_cache = vocab
    return vocab


def _norm_entity_key(text: str) -> str:
    s = text.strip().lower()
    s = _ENTITY_PUNCT_RE.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def _strip_entity_label(text: str) -> str:
    """Step 1 of the resolution pipeline: strip label-prefix/suffix garbage the regex parser
    swept up along with the real name (e.g. 'one of the following hotels: X', 'the restaurant Y',
    'X for no less than 60 minutes')."""
    s = text.strip()
    changed = True
    while changed:
        changed = False
        for pat in _ENTITY_LABEL_PREFIX_RES:
            new_s = pat.sub("", s)
            if new_s != s:
                s, changed = new_s, True
        for pat in _ENTITY_LABEL_SUFFIX_RES:
            new_s = pat.sub("", s)
            if new_s != s:
                s, changed = new_s, True
    return s.strip()


def _match_catalog_name(text: str, catalog_names: list[str]) -> str | None:
    """Steps 2-3: exact match, then containment (catalog name is a substring of ``text`` -- fixes
    prefix garbage in one step), then fuzzy match (unique best above threshold)."""
    text = text.strip()
    if not text or not catalog_names:
        return None
    norm_text = _norm_entity_key(text)
    if not norm_text:
        return None
    norm_to_orig: dict[str, str] = {}
    for name in catalog_names:
        norm_to_orig.setdefault(_norm_entity_key(name), name)

    if norm_text in norm_to_orig:
        return norm_to_orig[norm_text]

    # Containment only fires when the catalog name covers most of the candidate text (residual
    # label garbage, not a genuine multi-entity string) -- otherwise a short catalog name that
    # happens to be a substring of a longer ", "/" and "/" or "-joined list (e.g. "Zhongshan Park"
    # inside "Zhongshan Park, Venice Town") would hijack the match and starve segmentation
    # (_segment_entity_list) of a chance to recover every name in the list.
    contained = sorted(
        (orig for norm, orig in norm_to_orig.items()
         if norm and norm in norm_text and len(norm) >= 0.6 * len(norm_text)),
        key=len, reverse=True,
    )
    if len(contained) == 1:
        return contained[0]
    if len(contained) > 1 and len(contained[0]) > len(contained[1]):
        return contained[0]  # unambiguous longest/most-specific containment
    if contained:
        return None  # tie -- ambiguous, don't guess

    scored = sorted(
        ((difflib.SequenceMatcher(None, norm_text, norm).ratio(), orig) for norm, orig in norm_to_orig.items()),
        key=lambda t: -t[0],
    )
    best_score, best_orig = scored[0]
    if best_score < _ENTITY_FUZZY_THRESHOLD:
        return None
    if len(scored) > 1 and scored[1][0] >= best_score:
        return None  # tie -- ambiguous, don't guess
    return best_orig


def _segment_entity_list(text: str, catalog_names: list[str]) -> list[str] | None:
    """Step 4: when a single string actually names multiple catalog entries (','/'and'/'or'
    -separated), split and resolve each segment. Only returns a result when every non-empty
    segment resolves -- a partial split is worse than leaving the original string alone."""
    parts = [p.strip() for p in _ENTITY_SPLIT_RE.split(text) if p.strip()]
    if len(parts) < 2:
        return None
    resolved = []
    for part in parts:
        match = _match_catalog_name(part, catalog_names)
        if not match:
            return None
        resolved.append(match)
    return _dedupe_preserve_order(resolved)


def _match_type_vocab(text: str) -> str | None:
    vocab = _attraction_type_vocab()
    norm = _norm_entity_key(text)
    if norm in vocab:
        return vocab[norm]
    # Numbered-list artifact: an OR-arm number glued onto the type string ("... Entertainment 2").
    stripped = _ENTITY_TRAILING_NUMBER_RE.sub("", text).strip()
    if stripped != text:
        norm2 = _norm_entity_key(stripped)
        if norm2 in vocab:
            return vocab[norm2]
    return None


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out = []
    for item in items:
        key = _norm_entity_key(item) if isinstance(item, str) else item
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _resolve_generic_location(text: str, catalog: dict[str, list[str]]) -> str:
    """Resolve a single free-standing location reference (position_presence entry,
    hotel_nearby/poi_distance_hotel reference, stay_duration/activity_time_windows location) --
    no family to reroute to, so just clean the label and canonicalize against any category."""
    cleaned = _strip_entity_label(text)
    if not cleaned:
        return text
    for category in ("attraction", "restaurant", "hotel"):
        match = _match_catalog_name(cleaned, catalog.get(category, []))
        if match:
            return match
    return cleaned


def _resolve_one_required_name(text: str, field: str, catalog: dict[str, list[str]]) -> dict:
    """Steps 1-6 of the resolution pipeline for one entry of a required_/excluded_ name family.
    Returns a tagged outcome so the caller can route the result into the right constraint family."""
    category = _ENTITY_CATEGORY_FOR_FIELD[field]
    cleaned = _strip_entity_label(text)
    if not cleaned:
        return {"kind": "keep", "value": text}

    own_catalog = catalog.get(category, [])

    match = _match_catalog_name(cleaned, own_catalog)
    if match:
        return {"kind": "name", "value": match}

    segments = _segment_entity_list(cleaned, own_catalog)
    if segments:
        return {"kind": "names", "value": segments}

    if field in _ENTITY_TYPE_FIELD_FOR:
        type_match = _match_type_vocab(cleaned)
        if type_match:
            return {"kind": "type", "value": type_match}

    for other_category in ("attraction", "restaurant", "hotel"):
        if other_category == category:
            continue
        other_match = _match_catalog_name(cleaned, catalog.get(other_category, []))
        if other_match:
            # Step 6: category misrouting -- e.g. a required_hotels entry that's actually an
            # attraction/restaurant. No other family fits a bare POI-presence fact, so reroute to
            # position_presence (any stay_duration the parser separately extracted is untouched).
            return {"kind": "reroute_position", "value": other_match}

    return {"kind": "keep", "value": cleaned}


def resolve_entities(variant: dict, query: dict, catalog: dict[str, list[str]] | None = None) -> dict:
    """Canonicalize name-bearing constraint families in one solver-constraint dict against the
    target city's POI catalog (plan3 N2). Operates on a single variant so it composes cleanly with
    OR-branch expansion and LLM-alternative expansion -- ``ir_to_solver_variants`` applies it to
    every variant in the already-expanded list, covering OR arms and alternatives generically."""
    if not isinstance(variant, dict):
        return variant
    if catalog is None:
        catalog = load_city_entity_catalog(query.get("target_city"))
    if not any(catalog.get(c) for c in ("attraction", "restaurant", "hotel")):
        return variant  # unknown city / no catalog -- nothing to resolve against

    out = dict(variant)

    for field, category in _ENTITY_CATEGORY_FOR_FIELD.items():
        values = out.get(field)
        if not isinstance(values, list) or not values:
            continue
        new_names: list[str] = []
        type_additions: list[str] = []
        position_additions: list[str] = []
        for raw in values:
            if not isinstance(raw, str):
                new_names.append(raw)
                continue
            outcome = _resolve_one_required_name(raw, field, catalog)
            kind = outcome["kind"]
            if kind == "name":
                new_names.append(outcome["value"])
            elif kind == "names":
                new_names.extend(outcome["value"])
            elif kind == "type":
                type_additions.append(outcome["value"])
            elif kind == "reroute_position":
                position_additions.append(outcome["value"])
            else:
                new_names.append(outcome["value"])

        if new_names:
            out[field] = _dedupe_preserve_order(new_names)
        else:
            out.pop(field, None)

        if type_additions:
            type_field = _ENTITY_TYPE_FIELD_FOR.get(field)
            if type_field:
                existing = out.get(type_field) or []
                out[type_field] = _dedupe_preserve_order(list(existing) + type_additions)

        if position_additions:
            existing = out.get("position_presence") or []
            out["position_presence"] = _dedupe_preserve_order(list(existing) + position_additions)

    pp = out.get("position_presence")
    if isinstance(pp, list) and pp:
        out["position_presence"] = _dedupe_preserve_order([
            _resolve_generic_location(v, catalog) if isinstance(v, str) else v
            for v in pp
        ])

    hn = out.get("hotel_nearby")
    if isinstance(hn, dict) and isinstance(hn.get("reference"), str):
        resolved_ref = _resolve_generic_location(hn["reference"], catalog)
        if resolved_ref != hn["reference"]:
            hn = dict(hn)
            hn["reference"] = resolved_ref
            out["hotel_nearby"] = hn

    pdh = out.get("poi_distance_hotel")
    if isinstance(pdh, list) and pdh:
        new_pdh = []
        for item in pdh:
            if isinstance(item, dict) and isinstance(item.get("reference"), str):
                item = dict(item)
                item["reference"] = _resolve_generic_location(item["reference"], catalog)
            new_pdh.append(item)
        out["poi_distance_hotel"] = new_pdh

    for loc_field in ("stay_duration", "activity_time_windows"):
        items = out.get(loc_field)
        if isinstance(items, list) and items:
            new_items = []
            for item in items:
                if isinstance(item, dict) and isinstance(item.get("location"), str):
                    item = dict(item)
                    item["location"] = _resolve_generic_location(item["location"], catalog)
                new_items.append(item)
            out[loc_field] = new_items

    return out


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
    variant per OR arm (and is a no-op for non-disjunctive queries). When
    ``flags.entity_resolution`` is on, every resulting variant (including OR arms and LLM
    alternatives) is canonicalized against the target city's POI catalog via ``resolve_entities``
    (plan3 N2). ``env`` is unused by entity resolution (it's env-less by design, see
    ``load_city_entity_catalog``) -- kept as a pass-through hook for future WorldEnv-based checks.
    """
    variants = solver_constraint_variants(query, ir.raw, use_oracle=False)

    if flags is not None and getattr(flags, "disjunction", False):
        variants = disjunction_stub(variants, ir, query)

    if flags is not None and getattr(flags, "llm_parse", False):
        variants = alternatives_stub(variants, ir, query, flags=flags)

    if flags is not None and getattr(flags, "entity_resolution", False):
        catalog = load_city_entity_catalog(query.get("target_city"))
        variants = [resolve_entities(v, query, catalog) for v in variants]

    return variants
