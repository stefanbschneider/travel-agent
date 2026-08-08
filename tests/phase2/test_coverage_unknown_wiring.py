"""Roadmap P17(a): TPC_P2_COVERAGE_UNKNOWN wiring in run_sweeps_split -- the flag must be a
library-default no-op, and when set must compute the per-uid signal once in the parent (from the
same visible text + parsed variants the loop already builds) and thread it through to
sweeps.run_sweeps and the run summary.

Non-integration: monkeypatches sweeps.run_sweeps so this needs no real WorldEnv/solver, same
pattern as test_run_sweeps_split_variants.py / test_sweep_budget_cap.py.
"""

from __future__ import annotations

import time
from pathlib import Path


def _uid_and_query_with_uncovered_budget():
    """A real query whose text states a per-person budget the deterministic parser does not
    extract (verified against the shipped parser: measured 4/154 on hf_human, see
    coverage_signal's module docstring) -- a query the coverage signal should flag."""
    from chinatravel.data.load_datasets import load_query
    import argparse

    args = argparse.Namespace(splits="tpc_phase1", lang="en", oracle_translation=True)
    query_ids, query_data = load_query(args)
    uid = query_ids[0]
    query = dict(query_data[uid])
    query.setdefault("uid", uid)
    query["nature_language"] = "A short trip with a budget of 5000 RMB per person."
    return uid, query


def _run(tmp_path, monkeypatch, *, method, env=None, query=None):
    import os
    import solve_phase2 as runner
    from chinatravel.agent.phase2 import sweeps

    if env:
        for k, v in env.items():
            monkeypatch.setenv(k, v)

    uid, q = query or _uid_and_query_with_uncovered_budget()
    captured = {}

    def fake_run_sweeps(*, uids, queries, deadline, config, on_result, best=None,
                         variants=None, coverage_unknown=None, log=print):
        captured["coverage_unknown"] = coverage_unknown
        return {"passes": [], "final_pass_scores": {}}

    monkeypatch.setattr(sweeps, "run_sweeps", fake_run_sweeps)

    result_method_dir = tmp_path / "results" / method
    work_root = tmp_path / "runs" / method
    result_method_dir.mkdir(parents=True)
    work_root.mkdir(parents=True)

    summary = runner.run_sweeps_split(
        split="tpc_phase1",
        method=method,
        selected=[uid],
        query_data={uid: q},
        deadline=time.monotonic() + 60.0,
        run_start=time.monotonic(),
        budget_sec=None,
        total_budget_sec=60.0,
        lang="en",
        workers=1,
        resume=False,
        result_method_dir=result_method_dir,
        work_root=work_root,
    )
    return uid, captured, summary


def test_flag_off_by_default_passes_none_and_records_nothing(tmp_path, monkeypatch):
    monkeypatch.delenv("TPC_P2_COVERAGE_UNKNOWN", raising=False)
    uid, captured, summary = _run(tmp_path, monkeypatch, method="phase2_p17a_off")
    assert captured["coverage_unknown"] is None
    assert summary["coverage_unknown_flag"] is False
    assert summary["coverage_unknown_uids"] == []


def test_flag_on_flags_a_query_with_an_uncovered_budget_mention(tmp_path, monkeypatch):
    uid, captured, summary = _run(
        tmp_path, monkeypatch, method="phase2_p17a_on",
        env={"TPC_P2_COVERAGE_UNKNOWN": "1"})
    assert captured["coverage_unknown"] == {uid: True}
    assert summary["coverage_unknown_flag"] is True
    assert summary["coverage_unknown_uids"] == [uid]


def test_flag_on_but_off_values_stay_off(tmp_path, monkeypatch):
    # The method name carries the loop index, not the value: "false" and "False" differ only in
    # case, and a case-insensitive filesystem (macOS default) then collides on the per-arm method
    # directory _run creates.
    for index, value in enumerate(("0", "false", "False", "")):
        uid, captured, summary = _run(
            tmp_path, monkeypatch, method=f"phase2_p17a_off_{index}",
            env={"TPC_P2_COVERAGE_UNKNOWN": value})
        assert captured["coverage_unknown"] is None, value
        assert summary["coverage_unknown_flag"] is False, value


def test_flag_on_but_query_fully_covered_flags_nothing(tmp_path, monkeypatch):
    from chinatravel.data.load_datasets import load_query
    import argparse

    args = argparse.Namespace(splits="tpc_phase1", lang="en", oracle_translation=True)
    query_ids, query_data = load_query(args)
    uid = query_ids[0]
    query = dict(query_data[uid])
    query.setdefault("uid", uid)
    query["nature_language"] = "We would like a relaxing trip with plenty of free time."

    uid, captured, summary = _run(
        tmp_path, monkeypatch, method="phase2_p17a_covered",
        env={"TPC_P2_COVERAGE_UNKNOWN": "1"}, query=(uid, query))
    assert captured["coverage_unknown"] == {uid: False}
    assert summary["coverage_unknown_uids"] == []
