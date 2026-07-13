"""Unit tests for parser_vs_oracle structural diff core (Task 8a).

The diff compares a parsed (no-oracle) solver-constraint dict against the oracle solver-constraint
dict, per constraint family, producing precision/recall/value-accuracy and failure buckets:
missing, spurious, wrong_value, disjunction_flattened. Pure function on curated dicts (no WorldEnv).
"""

from __future__ import annotations

from pathlib import Path

import parser_vs_oracle as pvo


def test_exact_match_scores_perfect():
    oracle = {"budgets": {"total": 1500.0}, "required_attractions": ["A"]}
    parsed = {"budgets": {"total": 1500.0}, "required_attractions": ["A"]}
    d = pvo.diff_constraints(parsed, oracle)
    assert d["counts"]["missing"] == 0
    assert d["counts"]["spurious"] == 0
    assert d["counts"]["wrong_value"] == 0
    assert d["precision"] == 1.0
    assert d["recall"] == 1.0


def test_missing_constraint_counts_as_recall_miss():
    oracle = {"budgets": {"total": 1500.0}, "required_attractions": ["A"]}
    parsed = {"budgets": {"total": 1500.0}}
    d = pvo.diff_constraints(parsed, oracle)
    assert d["counts"]["missing"] == 1
    assert "required_attractions" in d["buckets"]["missing"]
    assert d["recall"] < 1.0
    assert d["precision"] == 1.0  # nothing spurious


def test_spurious_constraint_counts_as_precision_miss():
    oracle = {"budgets": {"total": 1500.0}}
    parsed = {"budgets": {"total": 1500.0}, "excluded_attractions": ["Z"]}
    d = pvo.diff_constraints(parsed, oracle)
    assert d["counts"]["spurious"] == 1
    assert "excluded_attractions" in d["buckets"]["spurious"]
    assert d["precision"] < 1.0
    assert d["recall"] == 1.0


def test_wrong_value_is_flagged():
    oracle = {"budgets": {"total": 1500.0}}
    parsed = {"budgets": {"total": 999.0}}
    d = pvo.diff_constraints(parsed, oracle)
    assert d["counts"]["wrong_value"] == 1
    assert "budgets" in d["buckets"]["wrong_value"]


# --- plan3 N1/G6: metric hygiene (taxi default, hotel-distance mirror, branch dedup) --------


def test_taxi_cars_equals_matching_party_size_default_is_not_spurious():
    # parse_query_no_oracle always fills taxi_cars_equals = ceil(people/4); when the oracle never
    # mentions it, that deliberate default must not count against precision (plan3 G6a).
    oracle = {"budgets": {"total": 1500.0}}
    parsed = {"budgets": {"total": 1500.0}, "taxi_cars_equals": 2}  # ceil(5/4) == 2
    d = pvo.diff_constraints(parsed, oracle, people_number=5)
    assert d["counts"]["spurious"] == 0
    assert d["counts"]["defaulted"] == 1
    assert "taxi_cars_equals" in d["buckets"]["defaulted"]
    assert d["precision"] == 1.0


def test_taxi_cars_equals_not_matching_default_still_spurious():
    # A non-default value (e.g. an explicit NL override) is a real extraction, not the vacuous
    # default -- still counts as spurious/precision loss when the oracle doesn't have it.
    oracle = {"budgets": {"total": 1500.0}}
    parsed = {"budgets": {"total": 1500.0}, "taxi_cars_equals": 3}  # ceil(5/4) == 2, not 3
    d = pvo.diff_constraints(parsed, oracle, people_number=5)
    assert d["counts"]["spurious"] == 1
    assert d["counts"]["defaulted"] == 0


def test_taxi_cars_equals_spurious_without_people_number():
    # No people_number context (e.g. a raw curated dict in a unit test) -> can't compute the
    # default, so falls back to counting as spurious (conservative, matches pre-N1 behavior).
    oracle = {"budgets": {"total": 1500.0}}
    parsed = {"budgets": {"total": 1500.0}, "taxi_cars_equals": 2}
    d = pvo.diff_constraints(parsed, oracle)
    assert d["counts"]["spurious"] == 1
    assert d["counts"]["defaulted"] == 0


def test_hotel_nearby_and_poi_distance_hotel_mirror_counted_once():
    # Both parser and oracle may mirror the same hotel-distance constraint into hotel_nearby
    # (dict) and poi_distance_hotel (list); must diff as one family, not two (plan3 G6b).
    item = {"reference": "Some POI", "distance_km": 1.0}
    oracle = {"hotel_nearby": item, "poi_distance_hotel": [item]}
    parsed = {"hotel_nearby": item, "poi_distance_hotel": [item]}
    d = pvo.diff_constraints(parsed, oracle)
    assert d["counts"]["matched"] == 1
    assert "hotel_nearby" not in d["buckets"]["matched"]
    assert "poi_distance_hotel" in d["buckets"]["matched"]


def test_hotel_nearby_only_oracle_canonicalized_to_poi_distance_hotel():
    # Oracle's accommodation_distance pattern sets only hotel_nearby (no poi_distance_hotel list);
    # canonicalization must still compare it head-to-head with the parser's always-mirrored value.
    item = {"reference": "Some POI", "distance_km": 1.0}
    oracle = {"hotel_nearby": item}
    parsed = {"hotel_nearby": item, "poi_distance_hotel": [item]}
    d = pvo.diff_constraints(parsed, oracle)
    assert d["counts"]["matched"] == 1
    assert d["counts"]["spurious"] == 0
    assert d["counts"]["missing"] == 0


def test_disjunction_flattened_detected():
    # Oracle has 2 branches; parsed has 1 -> the OR was flattened.
    d = pvo.diff_variants(
        parsed_variants=[{"budgets": {"total": 1500.0}}],
        oracle_variants=[{"budgets": {"total": 1500.0}}, {"required_hotels": ["H"]}],
    )
    assert d["disjunction_flattened"] is True


def test_no_disjunction_when_branch_counts_match():
    d = pvo.diff_variants(
        parsed_variants=[{"budgets": {"total": 1500.0}}],
        oracle_variants=[{"budgets": {"total": 1500.0}}],
    )
    assert d["disjunction_flattened"] is False


# --- Step 5: branch_aware family buckets (previously always empty) --------
#
# _branch_aware_diff only accumulated counts, never family names, so run_report's family_stats
# aggregation (which reads row["buckets"]) was silently vacuous whenever --branch-aware was used.


def test_branch_aware_diff_populates_buckets_not_just_counts():
    d = pvo.diff_variants(
        parsed_variants=[{"budgets": {"total": 1500.0}, "excluded_attractions": ["Z"]}],
        oracle_variants=[{"budgets": {"total": 1500.0}, "required_attractions": ["A"]}],
        branch_aware=True,
    )
    assert d["diff"]["counts"]["spurious"] == 1
    assert "excluded_attractions" in d["diff"]["buckets"]["spurious"]
    assert d["diff"]["counts"]["missing"] == 1
    assert "required_attractions" in d["diff"]["buckets"]["missing"]


def test_branch_aware_diff_buckets_include_unmatched_branch_families():
    # 2 oracle branches, 1 parsed -> the second oracle branch is unmatched; its family should
    # land in the aggregated "missing" bucket (not just inflate the count).
    d = pvo.diff_variants(
        parsed_variants=[{"budgets": {"total": 1500.0}}],
        oracle_variants=[{"budgets": {"total": 1500.0}}, {"required_hotels": ["H"]}],
        branch_aware=True,
    )
    assert "required_hotels" in d["diff"]["buckets"]["missing"]


def test_compute_query_diff_includes_buckets_for_family_stats():
    row = pvo.compute_query_diff({
        "uid": "t1",
        "nature_language": "no constraints here",
        "people_number": 1,
        "days": 1,
        "start_city": "A",
        "target_city": "B",
    })
    assert "buckets" in row
    assert set(row["buckets"].keys()) == {"matched", "missing", "spurious", "wrong_value", "defaulted"}


def test_aggregate_family_stats_sorts_by_spurious_count_desc():
    rows = [
        {"uid": "u1", "buckets": {"matched": [], "missing": [], "spurious": ["a", "b"], "wrong_value": []}},
        {"uid": "u2", "buckets": {"matched": ["c"], "missing": [], "spurious": ["a"], "wrong_value": []}},
    ]
    stats = pvo._aggregate_family_stats(rows)
    by_family = {s["family"]: s for s in stats}
    assert by_family["a"]["spurious"] == 2
    assert by_family["b"]["spurious"] == 1
    assert by_family["c"]["matched"] == 1
    # sorted descending by spurious count
    assert [s["family"] for s in stats][0] == "a"
    assert by_family["a"]["example_spurious_uids"] == ["u1", "u2"]


def test_aggregate_family_stats_dedupes_per_uid_family_bucket_by_default():
    # plan3 N1/G6c: a family appearing in the same bucket across multiple OR branches of one uid
    # (branch-aware diff) must count once per uid, not once per branch occurrence.
    rows = [
        {"uid": "u1", "buckets": {"matched": [], "missing": [], "spurious": ["a", "a", "a"], "wrong_value": []}},
    ]
    deduped = pvo._aggregate_family_stats(rows)
    assert {s["family"]: s["spurious"] for s in deduped}["a"] == 1

    raw = pvo._aggregate_family_stats(rows, per_variant=True)
    assert {s["family"]: s["spurious"] for s in raw}["a"] == 3


# --- Two-sided behavioral proxy: reject-side probes (plan-2 Step 5) ----------


def _q(uid, target_city="Beijing", days=3):
    return {"uid": uid, "target_city": target_city, "days": days}


def test_group_key_is_target_city_and_days():
    assert pvo._group_key(_q("a", "Beijing", 3)) == ("Beijing", 3)
    assert pvo._group_key(_q("a", "Beijing", 4)) != pvo._group_key(_q("b", "Beijing", 3))


def test_select_reject_probes_filters_by_group_key_and_existing_plan(tmp_path):
    query_data = {
        "u1": _q("u1", "Beijing", 3),
        "u2": _q("u2", "Beijing", 3),  # same group, has a plan
        "u3": _q("u3", "Beijing", 3),  # same group, NO plan on disk
        "u4": _q("u4", "Shanghai", 3),  # different city
        "u5": _q("u5", "Beijing", 5),  # different days
    }
    (tmp_path / "u2.json").write_text("{}")
    probes = pvo.select_reject_probes("u1", query_data["u1"], query_data, results_best=tmp_path)
    assert probes == ["u2"]


def test_select_reject_probes_deterministic_sort_and_k_limit(tmp_path):
    query_data = {"u1": _q("u1")}
    for i in range(2, 8):
        uid = f"u{i}"
        query_data[uid] = _q(uid)
        (tmp_path / f"{uid}.json").write_text("{}")
    probes = pvo.select_reject_probes("u1", query_data["u1"], query_data, results_best=tmp_path, k=4)
    assert probes == ["u2", "u3", "u4", "u5"]  # sorted, first k, deterministic


def test_select_reject_probes_excludes_self():
    query_data = {"u1": _q("u1")}
    probes = pvo.select_reject_probes("u1", query_data["u1"], query_data, results_best=Path("/nonexistent"))
    assert probes == []


def test_reject_probe_check_keeps_only_oracle_rejected_probes(tmp_path, monkeypatch):
    # p1: oracle accepts (not a valid reject probe) -> dropped.
    # p2, p3: oracle rejects -> kept; parsed also rejects p2 (agree), but accepts p3 (miss).
    for uid in ("p1", "p2", "p3"):
        (tmp_path / f"{uid}.json").write_text(f'{{"itinerary": [], "_uid": "{uid}"}}')

    def fake_oracle_pass(query, plan):
        return plan["_uid"] == "p1"

    def fake_parsed_pass(parsed_variants, plan, target_city, *, disjunction):
        return plan["_uid"] == "p3"

    monkeypatch.setattr(pvo, "_oracle_pass", fake_oracle_pass)
    monkeypatch.setattr(pvo, "_parsed_pass", fake_parsed_pass)

    row = pvo.reject_probe_check(
        _q("u1"), parsed_variants=[{}], probe_uids=["p1", "p2", "p3"], results_best=tmp_path,
    )
    assert row["kept_probe_uids"] == ["p2", "p3"]
    assert row["n_kept"] == 2
    assert row["reject_agree"] == 1  # only p2
    assert row["reject_agreement"] == 0.5


def test_reject_probe_check_no_kept_probes_yields_none_agreement(tmp_path, monkeypatch):
    (tmp_path / "p1.json").write_text('{"itinerary": []}')
    monkeypatch.setattr(pvo, "_oracle_pass", lambda query, plan: True)  # oracle accepts everything
    row = pvo.reject_probe_check(
        _q("u1"), parsed_variants=[{}], probe_uids=["p1"], results_best=tmp_path,
    )
    assert row["n_kept"] == 0
    assert row["reject_agreement"] is None


def test_reject_probe_check_missing_plan_file_is_skipped(tmp_path):
    row = pvo.reject_probe_check(
        _q("u1"), parsed_variants=[{}], probe_uids=["does-not-exist"], results_best=tmp_path,
    )
    assert row["n_probes"] == 1
    assert row["kept_probe_uids"] == []
    assert row["reject_agreement"] is None


def test_attribute_reject_misses_credits_missing_families():
    family_stats = [
        {"family": "required_attractions", "matched": 0, "missing": 1, "spurious": 0,
         "wrong_value": 0, "reject_miss": 0},
        {"family": "budgets", "matched": 1, "missing": 0, "spurious": 0, "wrong_value": 0,
         "reject_miss": 0},
    ]
    rows_by_uid = {
        "u1": {"uid": "u1", "buckets": {"missing": ["required_attractions"], "matched": [],
                                        "spurious": [], "wrong_value": []}},
    }
    pvo._attribute_reject_misses(
        family_stats, rows_by_uid=rows_by_uid, reject_miss_uids=["u1"],
    )
    by_family = {s["family"]: s for s in family_stats}
    assert by_family["required_attractions"]["reject_miss"] == 1
    assert by_family["budgets"]["reject_miss"] == 0


def test_attribute_reject_misses_ignores_unknown_uid():
    family_stats = [{"family": "x", "matched": 0, "missing": 0, "spurious": 0, "wrong_value": 0,
                     "reject_miss": 0}]
    pvo._attribute_reject_misses(family_stats, rows_by_uid={}, reject_miss_uids=["ghost"])
    assert family_stats[0]["reject_miss"] == 0


# --- plan3 N5: HF dataset loader (generalization probe) --------------------


class _FakeSplit:
    def __init__(self, rows):
        self._rows = rows

    def to_list(self):
        return self._rows


def test_load_hf_queries_normalizes_language_and_city(monkeypatch):
    rows = {
        "easy": _FakeSplit([
            {
                "uid": "e1", "start_city": "上海", "target_city": "杭州", "days": 1,
                "people_number": 1, "nature_language": "zh text",
                "nature_language_en": "Travel from Shanghai to Hangzhou.",
                "hard_logic_py": "['result=(day_count(plan)==1)']",
            },
        ]),
    }
    monkeypatch.setattr("datasets.load_dataset", lambda path, **kw: rows)

    ids, data = pvo.load_hf_queries("default")
    assert ids == ["e1"]
    q = data["e1"]
    assert q["nature_language"] == "Travel from Shanghai to Hangzhou."
    assert q["start_city"] == "Shanghai"
    assert q["target_city"] == "Hangzhou"
    assert q["hard_logic_py"] == ["result=(day_count(plan)==1)"]


def test_load_hf_queries_dedupes_across_splits(monkeypatch):
    row = {
        "uid": "e1", "start_city": "上海", "target_city": "杭州", "days": 1,
        "people_number": 1, "nature_language_en": "text",
        "hard_logic_py": [],
    }
    rows = {"easy": _FakeSplit([row]), "medium": _FakeSplit([dict(row)])}
    monkeypatch.setattr("datasets.load_dataset", lambda path, **kw: rows)

    ids, data = pvo.load_hf_queries("default", splits=["easy", "medium"])
    assert ids == ["e1"]
    assert len(data) == 1
