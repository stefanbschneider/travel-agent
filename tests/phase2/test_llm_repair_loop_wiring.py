"""Roadmap P6: run_sweeps_split's worker-count throttle for TPC_P2_LLM_REPAIR_LOOP.

"Throttle to at most eight concurrent requests for organizer parity" -- each worker process makes
at most one LLM call at a time, so clamping the worker pool size to 8 when the flag is on is
sufficient and needs no cross-process semaphore. Non-integration: monkeypatches
sweeps.default_workers/sweeps.run_sweeps so this needs no real WorldEnv/solver, same pattern as
test_coverage_unknown_wiring.py.
"""

from __future__ import annotations

import time


def _one_uid_and_query():
    from chinatravel.data.load_datasets import load_query
    import argparse

    args = argparse.Namespace(splits="tpc_phase1", lang="en", oracle_translation=True)
    query_ids, query_data = load_query(args)
    uid = query_ids[0]
    query = query_data[uid]
    query.setdefault("uid", uid)
    return uid, query


def _run(tmp_path, monkeypatch, *, method, workers, env=None):
    import solve_phase2 as runner
    from chinatravel.agent.phase2 import sweeps

    if env:
        for k, v in env.items():
            monkeypatch.setenv(k, v)

    uid, query = _one_uid_and_query()
    captured = {}

    def fake_run_sweeps(*, uids, queries, deadline, config, on_result, best=None,
                         variants=None, coverage_unknown=None, log=print):
        captured["config_workers"] = config.workers
        return {"passes": [], "final_pass_scores": {}}

    monkeypatch.setattr(sweeps, "run_sweeps", fake_run_sweeps)

    result_method_dir = tmp_path / "results" / method
    work_root = tmp_path / "runs" / method
    result_method_dir.mkdir(parents=True)
    work_root.mkdir(parents=True)

    runner.run_sweeps_split(
        split="tpc_phase1",
        method=method,
        selected=[uid],
        query_data={uid: query},
        deadline=time.monotonic() + 60.0,
        run_start=time.monotonic(),
        budget_sec=None,
        total_budget_sec=60.0,
        lang="en",
        workers=workers,
        resume=False,
        result_method_dir=result_method_dir,
        work_root=work_root,
    )
    return captured


def test_repair_loop_off_leaves_worker_count_untouched(tmp_path, monkeypatch):
    monkeypatch.delenv("TPC_P2_LLM_REPAIR_LOOP", raising=False)
    captured = _run(tmp_path, monkeypatch, method="phase2_p6_workers_off", workers=15)
    assert captured["config_workers"] == 15


def test_repair_loop_on_clamps_worker_count_to_eight(tmp_path, monkeypatch):
    captured = _run(
        tmp_path, monkeypatch, method="phase2_p6_workers_clamped", workers=15,
        env={"TPC_P2_LLM_REPAIR_LOOP": "1"})
    assert captured["config_workers"] == 8


def test_repair_loop_on_never_raises_a_smaller_worker_count(tmp_path, monkeypatch):
    captured = _run(
        tmp_path, monkeypatch, method="phase2_p6_workers_small", workers=2,
        env={"TPC_P2_LLM_REPAIR_LOOP": "1"})
    assert captured["config_workers"] == 2
