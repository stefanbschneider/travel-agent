"""Tests for the opt-in branch-aware matched-pair diff (parser_vs_oracle).

The default single-branch diff only scores parsed_variants[0] vs its best oracle branch, which
under-reports correct multi-branch parsing. The branch-aware diff matches each oracle branch to a
distinct parsed branch and aggregates precision/recall across the matched pairs, so a correctly
split N-branch query can score a perfect result. Unmatched oracle branches are recall misses;
extra parsed branches are precision misses.
"""

from __future__ import annotations

import parser_vs_oracle as pvo

A = {"required_attractions": ["A"]}
B = {"required_hotels": ["H"]}
B_WRONG = {"required_hotels": ["OTHER"]}


def test_two_branches_fully_matched_scores_perfect():
    dv = pvo.diff_variants(parsed_variants=[A, B], oracle_variants=[A, B], branch_aware=True)
    assert dv["diff"]["precision"] == 1.0
    assert dv["diff"]["recall"] == 1.0
    assert dv["diff"]["counts"]["matched"] == 2
    assert dv["disjunction_flattened"] is False


def test_branch_order_insensitive():
    # Parsed branches in the opposite order still match one-to-one.
    dv = pvo.diff_variants(parsed_variants=[B, A], oracle_variants=[A, B], branch_aware=True)
    assert dv["diff"]["recall"] == 1.0 and dv["diff"]["precision"] == 1.0


def test_flattened_second_branch_is_recall_miss():
    # Oracle has 2 branches; parser produced only 1 -> branch B's family is missing.
    dv = pvo.diff_variants(parsed_variants=[A], oracle_variants=[A, B], branch_aware=True)
    assert dv["disjunction_flattened"] is True
    assert dv["diff"]["counts"]["matched"] == 1
    assert dv["diff"]["counts"]["missing"] == 1
    assert dv["diff"]["recall"] == 0.5
    assert dv["diff"]["precision"] == 1.0  # nothing spurious


def test_extra_parsed_branch_is_precision_miss():
    dv = pvo.diff_variants(parsed_variants=[A, B], oracle_variants=[A], branch_aware=True)
    assert dv["diff"]["counts"]["matched"] == 1
    assert dv["diff"]["counts"]["spurious"] == 1
    assert dv["diff"]["precision"] == 0.5
    assert dv["diff"]["recall"] == 1.0


def test_wrong_value_across_branches():
    dv = pvo.diff_variants(parsed_variants=[A, B_WRONG], oracle_variants=[A, B], branch_aware=True)
    c = dv["diff"]["counts"]
    assert c["matched"] == 1 and c["wrong_value"] == 1
    assert dv["diff"]["value_accuracy"] == 0.5


def test_single_branch_matches_default_diff():
    # With one oracle branch, branch-aware equals the default single-branch diff.
    ba = pvo.diff_variants(parsed_variants=[A], oracle_variants=[A], branch_aware=True)
    default = pvo.diff_variants(parsed_variants=[A], oracle_variants=[A])
    assert ba["diff"]["precision"] == default["diff"]["precision"] == 1.0
    assert ba["diff"]["recall"] == default["diff"]["recall"] == 1.0


def test_default_path_unchanged_when_branch_aware_off():
    # Regression guard: existing single-branch behavior for a 2-branch query is unchanged.
    dv = pvo.diff_variants(parsed_variants=[A], oracle_variants=[A, B])
    assert dv["parsed_branches"] == 1 and dv["oracle_branches"] == 2
    assert dv["diff"]["recall"] == 1.0  # single-branch diff only sees branch A
