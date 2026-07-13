"""Tests for the deterministic entity-resolution layer (plan3 N2).

Table-driven from the real val uids that evidence the G2 defect cluster in
docs/tpc_phase2_plan3.md (label-prefix garbage, list-splitting failures, type-vs-name collisions,
category misrouting). Per N7 Tier 1: assert recall-style (expected constraints present with
correct values), not full-dict equality -- unrelated recall improvements shouldn't break these.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chinatravel.agent.phase2 import normalize
from chinatravel.agent.phase2.orchestrator import Flags

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EN_DATA_DIR = PROJECT_ROOT / "chinatravel" / "data" / "en" / "TPC_IJCAI_2026_phase1_EN"


def _load(uid: str) -> dict:
    path = EN_DATA_DIR / f"{uid}.json"
    if not path.exists():
        pytest.skip(f"query file for {uid} not present locally")
    q = json.loads(path.read_text(encoding="utf-8"))
    q.setdefault("uid", uid)
    return q


# --- catalog helper: env-less, lazy, cached ---------------------------------


def test_catalog_loads_without_env_for_known_city():
    catalog = normalize.load_city_entity_catalog("Shanghai")
    assert "West Bund Art Center" in catalog["attraction"]
    assert any(catalog[c] for c in ("attraction", "restaurant", "hotel"))


def test_catalog_empty_for_unknown_city():
    catalog = normalize.load_city_entity_catalog("Atlantis")
    assert catalog == {"attraction": [], "restaurant": [], "hotel": []}


def test_catalog_is_cached(monkeypatch):
    first = normalize.load_city_entity_catalog("Beijing")
    calls = {"n": 0}
    orig_root = normalize._extract_project_root

    def spy():
        calls["n"] += 1
        return orig_root()

    monkeypatch.setattr(normalize, "_extract_project_root", spy)
    second = normalize.load_city_entity_catalog("Beijing")
    assert first is second
    assert calls["n"] == 0  # cache hit -- no re-glob


# --- flag-off byte-identity --------------------------------------------------


def test_entity_resolution_off_by_default_byte_identical(sample_queries):
    off = Flags()
    for uid, q in sample_queries.items():
        ir = normalize.parse_to_ir(q, flags=off)
        got = normalize.ir_to_solver_variants(ir, q, flags=off)
        import parse_constraints
        from chinatravel.agent.tpc_agent.solver_constraints import solver_constraint_variants

        baseline = solver_constraint_variants(q, parse_constraints.parse_query_no_oracle(q), use_oracle=False)
        assert got == baseline, uid


# --- G2 label-prefix garbage: strip + exact/containment match --------------


def test_label_prefix_one_of_the_following_restaurants_stripped():
    # uid 20250321144415070996: "...try one of the following restaurants: OMBRA Terrace Garden
    # Western Restaurant." -> parser keeps the label glued to the name.
    variant = {"required_restaurants": ["one of the following restaurants: OMBRA Terrace Garden Western Restaurant"]}
    catalog = normalize.load_city_entity_catalog("Shanghai")
    out = normalize.resolve_entities(variant, {"target_city": "Shanghai"}, catalog)
    assert out["required_restaurants"] == ["OMBRA Terrace Garden Western Restaurant"]


def test_label_prefix_the_restaurant_stripped():
    # uid 20250320205205235224: "...try the restaurant Floral Mountain Retreat · Pure
    # Vegetarian Lodge."
    variant = {"required_restaurants": ["the restaurant Floral Mountain Retreat · Pure Vegetarian Lodge"]}
    catalog = normalize.load_city_entity_catalog("Suzhou")
    out = normalize.resolve_entities(variant, {"target_city": "Suzhou"}, catalog)
    assert out["required_restaurants"] == ["Floral Mountain Retreat · Pure Vegetarian Lodge"]


def test_end_to_end_uid_20250321144415070996():
    q = _load("20250321144415070996")
    flags = Flags(entity_resolution=True)
    ir = normalize.parse_to_ir(q, flags=flags)
    variants = normalize.ir_to_solver_variants(ir, q, flags=flags)
    assert len(variants) >= 1
    assert variants[0]["required_restaurants"] == ["OMBRA Terrace Garden Western Restaurant"]


# --- G2 list-splitting: "X or Y" / "X, Y" segmentation ----------------------


def test_hotel_or_list_segmented_into_two_names():
    # uid 20250322191742398051: "...stay at one of the following hotels: Hangzhou West Lake
    # Zhongwei Xiangyi Hotel or Hangzhou Qianjiangwan New Century Grand Hotel."
    variant = {"required_hotels": [
        "one of the following hotels: Hangzhou West Lake Zhongwei Xiangyi Hotel or Hangzhou Qianjiangwan New Century Grand Hotel",
        "Hangzhou West Lake Zhongwei Xiangyi Hotel or Hangzhou Qianjiangwan New Century Grand Hotel",
    ]}
    catalog = normalize.load_city_entity_catalog("Hangzhou")
    out = normalize.resolve_entities(variant, {"target_city": "Hangzhou"}, catalog)
    assert set(out["required_hotels"]) == {
        "Hangzhou West Lake Zhongwei Xiangyi Hotel",
        "Hangzhou Qianjiangwan New Century Grand Hotel",
    }


def test_comma_separated_attraction_list_segmented():
    # uid 20250324090426203118: "...visit Zhongshan Park, Venice Town, and Cloudrise Art Museum."
    # -> the regex merges the first two into one string and drops the third; entity resolution
    # recovers the two names present in the (already-truncated) string it's given.
    variant = {"required_attractions": ["Zhongshan Park, Venice Town"]}
    catalog = normalize.load_city_entity_catalog("Shanghai")
    out = normalize.resolve_entities(variant, {"target_city": "Shanghai"}, catalog)
    assert set(out["required_attractions"]) == {"Zhongshan Park", "Venice Town"}


# --- G2 type-vs-name collision: reroute to the type family -----------------


def test_literal_type_strings_rerouted_out_of_required_attractions():
    # uid 20250322103818184128: "...visit Cultural Tourism Area and Art Museum..." -- both are
    # attraction *types* (literal CSV 'type' values), not proper nouns; the regex also emits a
    # spurious required_attractions duplicate of the type extraction.
    variant = {"required_attractions": ["Cultural Tourism Area", "Art Museum"]}
    catalog = normalize.load_city_entity_catalog("Shenzhen")
    out = normalize.resolve_entities(variant, {"target_city": "Shenzhen"}, catalog)
    assert "required_attractions" not in out
    assert set(out["required_attraction_types"]) == {"Cultural Tourism Area", "Art Museum"}


def test_type_reroute_merges_with_existing_required_attraction_types():
    variant = {"required_attractions": ["Art Museum"], "required_attraction_types": ["Park"]}
    catalog = normalize.load_city_entity_catalog("Shenzhen")
    out = normalize.resolve_entities(variant, {"target_city": "Shenzhen"}, catalog)
    assert set(out["required_attraction_types"]) == {"Park", "Art Museum"}


def test_numbered_list_artifact_type_string_resolved():
    # uid 20250322123458076116: OR-arm numbering glued onto a type string ("... Entertainment 2").
    variant = {"required_attractions": ["Amusement Park/Sports Entertainment 2"]}
    catalog = normalize.load_city_entity_catalog("Nanjing")
    out = normalize.resolve_entities(variant, {"target_city": "Nanjing"}, catalog)
    assert "required_attractions" not in out
    assert out["required_attraction_types"] == ["Amusement Park/Sports Entertainment"]


# --- G2 category misrouting: reroute to position_presence -------------------


def test_category_misrouted_hotel_rerouted_to_position_presence():
    # uid 20250322190941974828: "...stay at Chiang Rai Bay (Vientiane Qianhai Branch) for no less
    # than 60 minutes" -- the POI is actually a restaurant in the catalog, not a hotel; oracle
    # encodes position_presence (+ stay_duration, parsed separately and left untouched here).
    variant = {"required_hotels": ["Chiang Rai Bay (Vientiane Qianhai Branch) for no less than 60 minutes"]}
    catalog = normalize.load_city_entity_catalog("Shenzhen")
    out = normalize.resolve_entities(variant, {"target_city": "Shenzhen"}, catalog)
    assert "required_hotels" not in out
    assert "Chiang Rai Bay (Vientiane Qianhai Branch)" in out["position_presence"]


def test_category_reroute_preserves_existing_stay_duration():
    variant = {
        "required_hotels": ["Chiang Rai Bay (Vientiane Qianhai Branch)"],
        "stay_duration": [{"location": "Chiang Rai Bay (Vientiane Qianhai Branch)", "min_minutes": 60}],
    }
    catalog = normalize.load_city_entity_catalog("Shenzhen")
    out = normalize.resolve_entities(variant, {"target_city": "Shenzhen"}, catalog)
    assert out["stay_duration"] == [{"location": "Chiang Rai Bay (Vientiane Qianhai Branch)", "min_minutes": 60}]


# --- Recall preservation: unresolved strings are kept, not dropped ---------


def test_unresolved_name_is_kept_cleaned_not_dropped():
    variant = {"required_hotels": ["one of the following hotels: Totally Made Up Hotel Name"]}
    catalog = normalize.load_city_entity_catalog("Hangzhou")
    out = normalize.resolve_entities(variant, {"target_city": "Hangzhou"}, catalog)
    assert out["required_hotels"] == ["Totally Made Up Hotel Name"]


def test_unknown_city_is_a_no_op():
    variant = {"required_hotels": ["one of the following hotels: X"]}
    out = normalize.resolve_entities(variant, {"target_city": "Nowhereville"})
    assert out == variant


# --- location-bearing families: hotel_nearby / poi_distance_hotel / stay_duration / windows -


def test_hotel_nearby_reference_canonicalized():
    variant = {"hotel_nearby": {"reference": "the attraction West Bund Art Center", "distance_km": 1.0}}
    catalog = normalize.load_city_entity_catalog("Shanghai")
    out = normalize.resolve_entities(variant, {"target_city": "Shanghai"}, catalog)
    assert out["hotel_nearby"]["reference"] == "West Bund Art Center"


def test_stay_duration_location_canonicalized():
    variant = {"stay_duration": [{"location": "the attraction West Bund Art Center", "min_minutes": 60}]}
    catalog = normalize.load_city_entity_catalog("Shanghai")
    out = normalize.resolve_entities(variant, {"target_city": "Shanghai"}, catalog)
    assert out["stay_duration"][0]["location"] == "West Bund Art Center"
