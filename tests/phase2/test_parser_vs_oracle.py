"""Unit tests for parser_vs_oracle structural diff core (Task 8a).

The diff compares a parsed (no-oracle) solver-constraint dict against the oracle solver-constraint
dict, per constraint family, producing precision/recall/value-accuracy and failure buckets:
missing, spurious, wrong_value, disjunction_flattened. Pure function on curated dicts (no WorldEnv).
"""

from __future__ import annotations

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
    assert set(row["buckets"].keys()) == {"matched", "missing", "spurious", "wrong_value"}


def test_aggregate_family_stats_sorts_by_spurious_count_desc():
    rows = [
        {"uid": "u1", "buckets": {"matched": [], "missing": [], "spurious": ["a", "a", "b"], "wrong_value": []}},
        {"uid": "u2", "buckets": {"matched": ["c"], "missing": [], "spurious": ["a"], "wrong_value": []}},
    ]
    stats = pvo._aggregate_family_stats(rows)
    by_family = {s["family"]: s for s in stats}
    assert by_family["a"]["spurious"] == 3
    assert by_family["b"]["spurious"] == 1
    assert by_family["c"]["matched"] == 1
    # sorted descending by spurious count
    assert [s["family"] for s in stats][0] == "a"
    assert by_family["a"]["example_spurious_uids"] == ["u1", "u1", "u2"]
