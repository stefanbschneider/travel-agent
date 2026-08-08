"""Roadmap P4: the whole-run sweep scheduler's per-query cap must default to
``sweeps.DEFAULT_MAX_QUERY_SEC`` (900s), not silently inherit ``run_split``'s unrelated 300s
per-query *development*-gate default -- that inheritance was why the intended second repair pass
was structurally unreachable (``MIN_BUDGET_GROWTH``'s 1.25x re-entry threshold could never be met
once a query's ``last_budget`` was pinned at 300, see ``sweeps.pass_budget_sec``/``_choose_pass``
and the roadmap item for the full mechanism).

Non-integration: monkeypatches ``sweeps.run_sweeps`` so this needs no real WorldEnv/solver, just
the parent's own budget threading -- same pattern as ``test_run_sweeps_split_variants.py``.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest


def _one_uid_and_query():
    from chinatravel.data.load_datasets import load_query
    import argparse

    args = argparse.Namespace(splits="tpc_phase1", lang="en", oracle_translation=True)
    query_ids, query_data = load_query(args)
    uid = query_ids[0]
    query = query_data[uid]
    query.setdefault("uid", uid)
    return uid, query


def _run_sweeps_split_capturing_config(tmp_path, monkeypatch, *, budget_sec, method):
    """Call ``run_sweeps_split`` with ``sweeps.run_sweeps`` stubbed out, and return the
    ``SweepConfig`` it built -- the thing this item's fix actually changes."""
    import solve_phase2 as runner
    from chinatravel.agent.phase2 import sweeps

    uid, query = _one_uid_and_query()
    captured = {}

    def fake_run_sweeps(*, uids, queries, deadline, config, on_result, best=None,
                         variants=None, coverage_unknown=None, log=print):
        captured["config"] = config
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
        budget_sec=budget_sec,
        total_budget_sec=60.0,
        lang="en",
        workers=1,
        resume=False,
        result_method_dir=result_method_dir,
        work_root=work_root,
    )
    return captured["config"]


def test_run_sweeps_split_defaults_the_cap_to_sweeps_own_900s_when_budget_sec_is_none(
    tmp_path, monkeypatch
):
    """The shipped harness invocation never passes --budget-sec (organizers' entry point takes no
    other flags), so this is the configuration every real run actually uses."""
    from chinatravel.agent.phase2 import sweeps

    config = _run_sweeps_split_capturing_config(
        tmp_path, monkeypatch, budget_sec=None, method="phase2_p4_default")
    assert config.max_query_sec == sweeps.DEFAULT_MAX_QUERY_SEC == 900.0
    # Not this function's unrelated 300s per-query development-gate default.
    assert config.max_query_sec != 300.0


def test_run_sweeps_split_respects_an_explicit_budget_sec_override(tmp_path, monkeypatch):
    """scripts/phase2_quick_eval.py --mode whole-run relies on an explicit --budget-sec bounding
    the sweep scheduler's per-query cap for its calibrated per-pass timing -- this must keep
    working exactly as before."""
    config = _run_sweeps_split_capturing_config(
        tmp_path, monkeypatch, budget_sec=45.0, method="phase2_p4_explicit")
    assert config.max_query_sec == 45.0


def test_run_split_forwards_none_budget_sec_to_the_sweep_branch_by_default(tmp_path, monkeypatch):
    """run_split must not resolve the 300s per-query default before deciding whether to hand off
    to the sweep scheduler -- doing so is exactly the bug this item fixes."""
    import solve_phase2 as runner

    captured = {}

    def fake_run_sweeps_split(**kwargs):
        captured.update(kwargs)
        return {"strategy": "sweeps"}

    monkeypatch.setattr(runner, "run_sweeps_split", fake_run_sweeps_split)

    uid, query = _one_uid_and_query()
    runner.run_split(
        "tpc_phase1",
        method="phase2_p4_run_split_default",
        queries={uid: query},
        total_budget_sec=60.0,
        start_monotonic=time.monotonic(),
        work_dir=str(tmp_path / "runs"),
        results_dir=str(tmp_path / "results"),
    )
    assert captured["budget_sec"] is None


def test_run_split_forwards_an_explicit_budget_sec_to_the_sweep_branch(tmp_path, monkeypatch):
    import solve_phase2 as runner

    captured = {}

    def fake_run_sweeps_split(**kwargs):
        captured.update(kwargs)
        return {"strategy": "sweeps"}

    monkeypatch.setattr(runner, "run_sweeps_split", fake_run_sweeps_split)

    uid, query = _one_uid_and_query()
    runner.run_split(
        "tpc_phase1",
        method="phase2_p4_run_split_explicit",
        queries={uid: query},
        budget_sec=45.0,
        total_budget_sec=60.0,
        start_monotonic=time.monotonic(),
        work_dir=str(tmp_path / "runs"),
        results_dir=str(tmp_path / "results"),
    )
    assert captured["budget_sec"] == 45.0


def test_run_split_plain_per_query_loop_still_defaults_to_300s(tmp_path, monkeypatch):
    """The per-query *development* gate (no --total-budget-sec) is untouched by this item -- an
    omitted --budget-sec must still resolve to DEFAULT_BUDGET_SEC (300s) there, exactly as before.
    Captured at ``orchestrator.solve_phase2``'s own ``budget_sec`` kwarg -- the raw per-query
    budget ``run_split`` resolved -- rather than what a solve_fn receives, since
    ``orch.solve_phase2`` internally splits that budget across parse/solve/refine slices before
    a solve_fn ever sees it (unrelated to this item)."""
    import solve_phase2 as runner

    uid, query = _one_uid_and_query()
    captured = {}
    original_solve_phase2 = runner.orch.solve_phase2

    def spy_solve_phase2(query, **kwargs):
        captured["budget_sec"] = kwargs.get("budget_sec")
        return original_solve_phase2(query, **kwargs)

    monkeypatch.setattr(runner.orch, "solve_phase2", spy_solve_phase2)

    def fast_solve(q, variants, budget_sec):
        return {"itinerary": []}, {}

    runner.run_split(
        "tpc_phase1",
        method="phase2_p4_plain_default",
        queries={uid: query},
        limit=1,
        solve_fn=fast_solve,
        work_dir=str(tmp_path / "runs"),
        results_dir=str(tmp_path / "results"),
    )
    assert captured["budget_sec"] == runner.DEFAULT_BUDGET_SEC == 300.0


def test_run_split_summary_records_the_cap_actually_in_force(tmp_path, monkeypatch):
    """A recorded row must state its own configuration (CLAUDE.md's measurement-ledger rule) --
    the summary's budget_sec has to be the cap the sweep scheduler actually ran at, not the raw
    (possibly None) operator input."""
    import solve_phase2 as runner
    from chinatravel.agent.phase2 import sweeps

    uid, query = _one_uid_and_query()

    def fake_run_sweeps(*, uids, queries, deadline, config, on_result, best=None,
                         variants=None, coverage_unknown=None, log=print):
        return {"passes": [], "final_pass_scores": {}}

    monkeypatch.setattr(sweeps, "run_sweeps", fake_run_sweeps)

    summary = runner.run_split(
        "tpc_phase1",
        method="phase2_p4_summary",
        queries={uid: query},
        total_budget_sec=60.0,
        start_monotonic=time.monotonic(),
        work_dir=str(tmp_path / "runs"),
        results_dir=str(tmp_path / "results"),
    )
    assert summary["budget_sec"] == sweeps.DEFAULT_MAX_QUERY_SEC == 900.0
    assert summary["budget_sec_explicit"] is None
