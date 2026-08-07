"""Tests for the P19 density/family-gap screen (scripts/phase2_density_family_gap_analysis.py).

Pure-function tests over synthetic records -- no dataset dependency, no parser, no solve -- for the
two aggregation functions the screen's conclusions rest on:

- ``density_report``: the dense-tail vs. sparse-rest split and its coverage-ceiling proxy;
- ``family_gap_report``: families never produced anywhere, and the instances-x-miss_rate ranking.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(PROJECT_ROOT), str(PROJECT_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

p19 = pytest.importorskip("phase2_density_family_gap_analysis")


# --- density_report ----------------------------------------------------------


def _rec(n_clauses: int, n_parse_gap: int) -> dict:
    return {"uid": f"u{n_clauses}_{n_parse_gap}", "n_clauses": n_clauses, "n_parse_gap": n_parse_gap}


def test_density_report_splits_dense_from_sparse_at_threshold():
    records = [_rec(12, 2), _rec(9, 1), _rec(11, 0)]
    out = p19.density_report("s", records, dense_threshold=10)
    assert out["dense_tail"]["n_queries"] == 2  # 12 and 11
    assert out["sparse_rest"]["n_queries"] == 1  # 9


def test_density_report_ceiling_is_parse_gap_free_fraction():
    # 2 queries, 10 clauses total, 3 parse gaps -> ceiling = 100 * 7/10
    records = [_rec(6, 2), _rec(4, 1)]
    out = p19.density_report("s", records, dense_threshold=10)
    assert out["overall"]["n_oracle_clauses"] == 10
    assert out["overall"]["n_parse_gap"] == 3
    assert out["overall"]["clpr_ceiling_parse_gap_only"] == 70.0


def test_density_report_empty_dense_tail_ceiling_is_none_not_100():
    # No query reaches the threshold -- must not silently report a misleading 100.0 ceiling for
    # zero clauses (the roadmap's own worked example: every set but hf_medium has 0 dense
    # queries).
    records = [_rec(3, 1), _rec(4, 0)]
    out = p19.density_report("s", records, dense_threshold=10)
    assert out["dense_tail"]["n_queries"] == 0
    assert out["dense_tail"]["clpr_ceiling_parse_gap_only"] is None


def test_density_report_quantiles_cover_the_full_distribution():
    records = [_rec(n, 0) for n in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10)]
    out = p19.density_report("s", records, dense_threshold=10)
    q = out["clause_count_quantiles"]
    assert q["min"] == 1
    assert q["max"] == 10
    # index round(0.5*9); Python's banker's rounding takes round(4.5) -> 4 (0-indexed) -> value 5.
    assert q["p50"] == 5


# --- family_gap_report --------------------------------------------------------


def _diff_row(uid, *, matched=(), missing=(), spurious=(), wrong_value=()) -> dict:
    return {
        "uid": uid,
        "buckets": {
            "matched": list(matched), "missing": list(missing),
            "spurious": list(spurious), "wrong_value": list(wrong_value), "defaulted": [],
        },
    }


def test_family_gap_never_produced_requires_zero_matched_and_zero_wrong_value_everywhere():
    rows_by_set = {
        "set_a": [_diff_row("a1", missing=["ghost_family"])],
        "set_b": [_diff_row("b1", missing=["ghost_family"])],
    }
    out = p19.family_gap_report(rows_by_set)
    names = {e["family"] for e in out["never_produced_on_any_set"]}
    assert "ghost_family" in names


def test_family_gap_produced_on_one_set_excludes_it_from_never_produced():
    rows_by_set = {
        "set_a": [_diff_row("a1", missing=["fam"])],
        "set_b": [_diff_row("b1", matched=["fam"])],  # produced here
    }
    out = p19.family_gap_report(rows_by_set)
    names = {e["family"] for e in out["never_produced_on_any_set"]}
    assert "fam" not in names


def test_family_gap_ranking_weighs_instances_not_just_rate():
    # "rare_bad": 1 instance, 100% miss -> score 1.0. "common_ok": 10 instances, 30% miss ->
    # score 3.0. The common-but-imperfect family must outrank the rare-but-always-missed one.
    rows_by_set = {
        "set_a": (
            [_diff_row("r1", missing=["rare_bad"])]
            + [_diff_row(f"c{i}", matched=["common_ok"]) for i in range(7)]
            + [_diff_row(f"c{i}", missing=["common_ok"]) for i in range(7, 10)]
        ),
    }
    out = p19.family_gap_report(rows_by_set)
    ranked = {e["family"]: e for e in out["ranked_by_instances_x_miss_rate"]}
    assert ranked["common_ok"]["score_instances_x_miss_rate"] > ranked["rare_bad"]["score_instances_x_miss_rate"]


def test_family_gap_dedupes_family_within_a_uid_bucket_like_aggregate_family_stats():
    # _aggregate_family_stats de-dupes per (uid, family, bucket) by default -- a family appearing
    # twice in one uid's missing bucket (e.g. two OR branches) counts once.
    row = _diff_row("u1", missing=["fam", "fam"])
    out = p19.family_gap_report({"set_a": [row]})
    entry = next(e for e in out["ranked_by_instances_x_miss_rate"] if e["family"] == "fam")
    assert entry["oracle_instances"] == 1
