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
