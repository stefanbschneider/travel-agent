"""Tests for the deterministic entity-resolution layer.

Table-driven from real validation UIDs covering label-prefix garbage, list-splitting failures,
type-versus-name collisions, and category misrouting. Assert recall-style: expected constraints
must be present with correct values, but unrelated recall improvements must not require
full-dictionary equality.
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


def test_catalog_name_with_internal_and_segmented_within_one_string():
    # A catalog name can itself contain "and" ("Honey Lake 1979 Cultural and Creative Park"),
    # alongside two other real, distinct entries in the same comma/and-joined string. Naive
    # splitting at every delimiter would break the compound name into two garbage fragments;
    # maximum-munch segmentation must prefer the longest resolving span at each position.
    variant = {"required_attractions": [
        "Wutong Mountain Art Town, Honey Lake 1979 Cultural and Creative Park, Dameisha Seaside Park",
    ]}
    catalog = normalize.load_city_entity_catalog("Shenzhen")
    out = normalize.resolve_entities(variant, {"target_city": "Shenzhen"}, catalog)
    assert set(out["required_attractions"]) == {
        "Wutong Mountain Art Town",
        "Honey Lake 1979 Cultural and Creative Park",
        "Dameisha Seaside Park",
    }


def test_segmentation_does_not_overreach_into_the_next_real_entry():
    # Regression: the catalog also has shorter, unrelated entries ("Honey Lake", "Honey Lake
    # Park") that could tempt a lenient/containment match. Greedy segmentation must not let a
    # longer candidate span "Honey Lake 1979 Cultural and Creative Park and Dameisha Seaside
    # Park" swallow the next distinct real entry just because the first name is its prefix.
    variant = {"required_attractions": [
        "Honey Lake 1979 Cultural and Creative Park and Dameisha Seaside Park",
    ]}
    catalog = normalize.load_city_entity_catalog("Shenzhen")
    out = normalize.resolve_entities(variant, {"target_city": "Shenzhen"}, catalog)
    assert set(out["required_attractions"]) == {
        "Honey Lake 1979 Cultural and Creative Park",
        "Dameisha Seaside Park",
    }


def test_base_parser_pre_split_catalog_name_is_rejoined_across_list_items():
    # The base regex parser (parse_constraints.py) splits "...Cultural and Creative Park..."
    # into two separate *list items* before entity resolution ever sees a combined string --
    # this is the upstream case _segment_entity_list (a single-string fix) cannot reach.
    variant = {"required_attractions": [
        "Wutong Mountain Art Town", "Honey Lake 1979 Cultural", "Creative Park", "Dameisha Seaside Park",
    ]}
    catalog = normalize.load_city_entity_catalog("Shenzhen")
    out = normalize.resolve_entities(variant, {"target_city": "Shenzhen"}, catalog)
    assert set(out["required_attractions"]) == {
        "Wutong Mountain Art Town",
        "Honey Lake 1979 Cultural and Creative Park",
        "Dameisha Seaside Park",
    }


def test_list_level_merge_does_not_overreach_into_the_next_real_entry():
    # Regression, list-item-merge version of the same containment-overreach risk: merging
    # ["Honey Lake 1979 Cultural", "Creative Park", "Dameisha Seaside Park"] must stop after the
    # correct 2-item span, not swallow the third (distinct, unmerged) entry too.
    variant = {"required_attractions": [
        "Honey Lake 1979 Cultural", "Creative Park", "Dameisha Seaside Park",
    ]}
    catalog = normalize.load_city_entity_catalog("Shenzhen")
    out = normalize.resolve_entities(variant, {"target_city": "Shenzhen"}, catalog)
    assert set(out["required_attractions"]) == {
        "Honey Lake 1979 Cultural and Creative Park",
        "Dameisha Seaside Park",
    }


def test_oxford_comma_list_with_compound_name_segmented_within_one_string():
    # "A, B, and C" splits into an empty token between the ',' and 'and' delimiters (adjacent
    # delimiters, nothing between them) -- _segment_entity_list's explicit collapse pass handles
    # this deterministically rather than relying on the empty token happening to normalize away
    # when absorbed into a neighbouring span's exact-match candidate.
    variant = {"required_attractions": [
        "Wutong Mountain Art Town, Honey Lake 1979 Cultural and Creative Park, and Dameisha Seaside Park",
    ]}
    catalog = normalize.load_city_entity_catalog("Shenzhen")
    out = normalize.resolve_entities(variant, {"target_city": "Shenzhen"}, catalog)
    assert set(out["required_attractions"]) == {
        "Wutong Mountain Art Town",
        "Honey Lake 1979 Cultural and Creative Park",
        "Dameisha Seaside Park",
    }


def test_list_level_merge_preserves_relative_order():
    # Regression: a merge in the *middle* of the list must not reorder the surrounding entries --
    # the merged name belongs at the position the merge occurred, not appended ahead of everything
    # else in the list.
    variant = {"required_attractions": [
        "Wutong Mountain Art Town", "Honey Lake 1979 Cultural", "Creative Park", "Dameisha Seaside Park",
    ]}
    catalog = normalize.load_city_entity_catalog("Shenzhen")
    out = normalize.resolve_entities(variant, {"target_city": "Shenzhen"}, catalog)
    assert out["required_attractions"] == [
        "Wutong Mountain Art Town",
        "Honey Lake 1979 Cultural and Creative Park",
        "Dameisha Seaside Park",
    ]


def test_required_restaurants_resolves_against_hotel_catalog_for_breakfast():
    # The oracle's own symbolic extraction (hard_constraint.py) adds *every* breakfast/lunch/
    # dinner activity's position to the same restaurant-name set a required_restaurants clause
    # checks -- including a free hotel breakfast, positioned at the hotel's own name. So a
    # restaurant-family entry naming a hotel is not a mis-parse and must resolve within
    # required_restaurants, not reroute to position_presence.
    variant = {"required_restaurants": [
        "Jiahong Hotel (Shanghai Pudong Airport, Chuansha Metro Station)", "Sir Elly's Rooftop Restaurant",
    ]}
    catalog = normalize.load_city_entity_catalog("Shanghai")
    out = normalize.resolve_entities(variant, {"target_city": "Shanghai"}, catalog)
    assert set(out["required_restaurants"]) == {
        "Jiahong Hotel (Shanghai Pudong Airport, Chuansha Metro Station)",
        "Sir Elly's Rooftop Restaurant",
    }
    assert "position_presence" not in out


def test_required_restaurants_list_level_merge_rejoins_hotel_name_split_by_comma():
    # Combines both fixes: the base parser splits this hotel name's own internal comma into two
    # list items, and the rejoined name only resolves via the hotel catalog (not restaurants').
    variant = {"required_restaurants": [
        "Jiahong Hotel (Shanghai Pudong Airport", "Chuansha Metro Station)", "Sir Elly's Rooftop Restaurant",
    ]}
    catalog = normalize.load_city_entity_catalog("Shanghai")
    out = normalize.resolve_entities(variant, {"target_city": "Shanghai"}, catalog)
    assert set(out["required_restaurants"]) == {
        "Jiahong Hotel (Shanghai Pudong Airport, Chuansha Metro Station)",
        "Sir Elly's Rooftop Restaurant",
    }
    assert "position_presence" not in out


def test_required_attractions_still_reroutes_hotel_name_to_position_presence():
    # Unlike restaurants, an attraction activity's position can never come from the hotel
    # catalog, so the pre-existing category-misrouting reroute must be unaffected by the
    # restaurant/hotel pooling above.
    variant = {"required_attractions": ["Chiang Rai Bay (Vientiane Qianhai Branch)"]}
    catalog = normalize.load_city_entity_catalog("Shenzhen")
    out = normalize.resolve_entities(variant, {"target_city": "Shenzhen"}, catalog)
    assert "required_attractions" not in out
    assert "Chiang Rai Bay (Vientiane Qianhai Branch)" in out["position_presence"]


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
