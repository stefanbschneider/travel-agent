"""Unit tests for phase2_timing: per-stage p50/p95, budget overruns, and variance."""

from __future__ import annotations

import json

import phase2_timing as T


def _telem(parse, solve, improve, finalize, *, budget=900.0, timed_out=False,
           used_fallback=False, valid=True):
    return {
        "stage_sec": {"parse": parse, "solve": solve, "improve": improve, "finalize": finalize},
        "budget_sec": budget,
        "timed_out": timed_out,
        "used_fallback": used_fallback,
        "valid_output": valid,
    }


def test_percentile_basic():
    assert T.percentile([10, 20, 30], 50) == 20
    assert T.percentile([], 50) == 0.0


def test_aggregate_per_stage_p50():
    telems = [
        _telem(1, 10, 0, 1),
        _telem(2, 20, 0, 2),
        _telem(3, 30, 0, 3),
    ]
    agg = T.aggregate_timings(telems)
    assert agg["per_stage"]["solve"]["p50"] == 20
    assert agg["per_stage"]["parse"]["p50"] == 2
    assert agg["n"] == 3
    assert agg["valid_output_rate"] == 1.0


def test_budget_overrun_flagged():
    telems = [
        _telem(1, 5, 0, 1, budget=10.0),     # total 7 <= 10 ok
        _telem(5, 8, 0, 2, budget=10.0),     # total 15 > 10 overrun
    ]
    agg = T.aggregate_timings(telems)
    assert agg["budget_overruns"] == 1
    assert agg["timed_out"] == 0


def test_reliability_counts():
    telems = [
        _telem(1, 5, 0, 1, timed_out=True, used_fallback=True, valid=True),
        _telem(1, 5, 0, 1, valid=False),
    ]
    agg = T.aggregate_timings(telems)
    assert agg["timed_out"] == 1
    assert agg["used_fallback"] == 1
    assert agg["valid_output_rate"] == 0.5


def test_score_variance():
    v = T.score_variance([1.0, 0.0, 1.0])
    assert abs(v["mean"] - (2 / 3)) < 1e-9
    assert v["n"] == 3
    assert v["min"] == 0.0 and v["max"] == 1.0
    assert v["stdev"] > 0.0


def test_aggregate_from_dir(tmp_path):
    for i, t in enumerate([_telem(1, 10, 0, 1), _telem(2, 20, 0, 2)]):
        d = tmp_path / f"uid{i}"
        d.mkdir()
        (d / "telemetry.json").write_text(json.dumps(t), encoding="utf-8")
    agg = T.aggregate_from_dir(str(tmp_path))
    assert agg["n"] == 2
    assert agg["per_stage"]["solve"]["p50"] in (10, 15, 20)
