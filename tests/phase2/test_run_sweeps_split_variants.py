"""Roadmap P10: the parent (``run_sweeps_split``) must parse once through the canonical path
(``normalize.parse_to_ir`` + ``normalize.ir_to_solver_variants``) and hand the exact same variant
list to ``sweeps.run_sweeps`` that a solving worker would derive itself -- not the coarser,
single-variant ``selfscore.derive_parsed_constraints``.

Non-integration: monkeypatches ``sweeps.run_sweeps`` so this needs no real WorldEnv/solver, just
the parent's own parse + wiring.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _one_uid_and_query():
    from chinatravel.data.load_datasets import load_query
    import argparse

    args = argparse.Namespace(splits="tpc_phase1", lang="en", oracle_translation=True)
    query_ids, query_data = load_query(args)
    uid = query_ids[0]
    query = query_data[uid]
    query.setdefault("uid", uid)
    return uid, query


def test_run_sweeps_split_parses_once_via_canonical_path_and_forwards_variants(tmp_path, monkeypatch):
    import solve_phase2 as runner
    from chinatravel.agent.phase2 import normalize, selfscore, sweeps

    uid, query = _one_uid_and_query()

    captured = {}

    def fake_run_sweeps(*, uids, queries, deadline, config, on_result, best=None,
                         variants=None, log=print):
        captured["uids"] = list(uids)
        captured["variants"] = variants
        captured["queries"] = queries
        return {"passes": [], "final_pass_scores": {}}

    monkeypatch.setattr(sweeps, "run_sweeps", fake_run_sweeps)

    # Spy on the canonical parse path to assert it (and not derive_parsed_constraints) is what
    # the parent calls.
    parse_calls = {"parse_to_ir": 0, "ir_to_solver_variants": 0}
    derive_calls = {"count": 0}

    original_parse_to_ir = normalize.parse_to_ir
    original_ir_to_solver_variants = normalize.ir_to_solver_variants
    original_derive = selfscore.derive_parsed_constraints

    def spy_parse_to_ir(*args, **kwargs):
        parse_calls["parse_to_ir"] += 1
        assert kwargs.get("llm_client") is None, "the parent must stay zero-LLM"
        return original_parse_to_ir(*args, **kwargs)

    def spy_ir_to_solver_variants(*args, **kwargs):
        parse_calls["ir_to_solver_variants"] += 1
        return original_ir_to_solver_variants(*args, **kwargs)

    def spy_derive(*args, **kwargs):
        derive_calls["count"] += 1
        return original_derive(*args, **kwargs)

    monkeypatch.setattr(normalize, "parse_to_ir", spy_parse_to_ir)
    monkeypatch.setattr(normalize, "ir_to_solver_variants", spy_ir_to_solver_variants)
    monkeypatch.setattr(selfscore, "derive_parsed_constraints", spy_derive)

    result_method_dir = tmp_path / "results" / "phase2_p10_test"
    work_root = tmp_path / "runs" / "phase2_p10_test"
    result_method_dir.mkdir(parents=True)
    work_root.mkdir(parents=True)

    import time

    runner.run_sweeps_split(
        split="tpc_phase1",
        method="phase2_p10_test",
        selected=[uid],
        query_data={uid: query},
        deadline=time.monotonic() + 60.0,
        run_start=time.monotonic(),
        budget_sec=30.0,
        total_budget_sec=60.0,
        lang="en",
        workers=1,
        resume=False,
        result_method_dir=result_method_dir,
        work_root=work_root,
    )

    assert parse_calls["parse_to_ir"] == 1
    assert parse_calls["ir_to_solver_variants"] == 1
    assert derive_calls["count"] == 0, "the parent must not use the coarser fallback parse"
    assert captured["uids"] == [uid]
    assert uid in captured["variants"]
    assert isinstance(captured["variants"][uid], list)


def test_run_sweeps_split_degrades_to_empty_variants_on_parse_failure(tmp_path, monkeypatch):
    import solve_phase2 as runner
    from chinatravel.agent.phase2 import normalize, sweeps

    uid, query = _one_uid_and_query()

    captured = {}

    def fake_run_sweeps(*, uids, queries, deadline, config, on_result, best=None,
                         variants=None, log=print):
        captured["variants"] = variants
        return {"passes": [], "final_pass_scores": {}}

    def raising_parse_to_ir(*args, **kwargs):
        raise RuntimeError("simulated parse failure")

    monkeypatch.setattr(sweeps, "run_sweeps", fake_run_sweeps)
    monkeypatch.setattr(normalize, "parse_to_ir", raising_parse_to_ir)

    result_method_dir = tmp_path / "results" / "phase2_p10_fail"
    work_root = tmp_path / "runs" / "phase2_p10_fail"
    result_method_dir.mkdir(parents=True)
    work_root.mkdir(parents=True)

    import time

    runner.run_sweeps_split(
        split="tpc_phase1",
        method="phase2_p10_fail",
        selected=[uid],
        query_data={uid: query},
        deadline=time.monotonic() + 60.0,
        run_start=time.monotonic(),
        budget_sec=30.0,
        total_budget_sec=60.0,
        lang="en",
        workers=1,
        resume=False,
        result_method_dir=result_method_dir,
        work_root=work_root,
    )

    assert captured["variants"][uid] == [], "a parse failure must degrade to [], never crash"


def test_run_sweeps_split_records_parent_parse_failures_in_summary(tmp_path, monkeypatch, capsys):
    """Roadmap P13: a parent-side parse failure used to be silently discarded -- a run could not
    tell you which uids (if any) fell back to the per-worker re-parse. It is now surfaced as
    ``parent_parse_failed_uids`` on the written/printed run summary."""
    import solve_phase2 as runner
    from chinatravel.agent.phase2 import normalize, sweeps

    uid, query = _one_uid_and_query()

    def fake_run_sweeps(*, uids, queries, deadline, config, on_result, best=None,
                         variants=None, log=print):
        return {"passes": [], "final_pass_scores": {}}

    def raising_parse_to_ir(*args, **kwargs):
        raise RuntimeError("simulated parse failure")

    monkeypatch.setattr(sweeps, "run_sweeps", fake_run_sweeps)
    monkeypatch.setattr(normalize, "parse_to_ir", raising_parse_to_ir)

    result_method_dir = tmp_path / "results" / "phase2_p13_fail"
    work_root = tmp_path / "runs" / "phase2_p13_fail"
    result_method_dir.mkdir(parents=True)
    work_root.mkdir(parents=True)

    import time

    summary = runner.run_sweeps_split(
        split="tpc_phase1",
        method="phase2_p13_fail",
        selected=[uid],
        query_data={uid: query},
        deadline=time.monotonic() + 60.0,
        run_start=time.monotonic(),
        budget_sec=30.0,
        total_budget_sec=60.0,
        lang="en",
        workers=1,
        resume=False,
        result_method_dir=result_method_dir,
        work_root=work_root,
    )

    assert summary["parent_parse_failed_uids"] == [uid]
    written = json.loads((work_root / "tpc_phase1_summary.json").read_text(encoding="utf-8"))
    assert written["parent_parse_failed_uids"] == [uid]


def test_run_sweeps_split_records_no_parent_parse_failures_on_success(tmp_path, monkeypatch):
    """The floor: when the parent parse succeeds for every query, the new field is an empty
    list, not omitted -- so a reader never has to distinguish 'no failures' from 'field absent'."""
    import solve_phase2 as runner
    from chinatravel.agent.phase2 import sweeps

    uid, query = _one_uid_and_query()

    def fake_run_sweeps(*, uids, queries, deadline, config, on_result, best=None,
                         variants=None, log=print):
        return {"passes": [], "final_pass_scores": {}}

    monkeypatch.setattr(sweeps, "run_sweeps", fake_run_sweeps)

    result_method_dir = tmp_path / "results" / "phase2_p13_ok"
    work_root = tmp_path / "runs" / "phase2_p13_ok"
    result_method_dir.mkdir(parents=True)
    work_root.mkdir(parents=True)

    import time

    summary = runner.run_sweeps_split(
        split="tpc_phase1",
        method="phase2_p13_ok",
        selected=[uid],
        query_data={uid: query},
        deadline=time.monotonic() + 60.0,
        run_start=time.monotonic(),
        budget_sec=30.0,
        total_budget_sec=60.0,
        lang="en",
        workers=1,
        resume=False,
        result_method_dir=result_method_dir,
        work_root=work_root,
    )

    assert summary["parent_parse_failed_uids"] == []


def test_solve_one_reparses_and_scores_consistently_when_parent_variants_empty():
    """Roadmap P13, end to end through ``sweeps.solve_one``: a query whose parent parse raised
    (``task["variants"] = []``) must still end up with ``variants_count > 0`` after the worker's
    own re-parse succeeds, and the solver and self-score must agree on that query being
    constrained -- not one side unconstrained and the other scoring against real constraints.

    Builds the worker context by hand (env, a fast injected solve_fn, default flags) instead of
    going through ``sweeps.init_worker`` -- that helper also calls
    ``apply_deterministic_solver_defaults()``, which sets process environment variables
    (``TPC_WINDOW_ANCHOR`` and friends) with no restore path and is guarded to run only once per
    process, so it is unsafe to call from a unit test that must not leak state into whatever
    test runs next in the same session.
    """
    from chinatravel.agent.phase2 import orchestrator as orch_mod
    from chinatravel.agent.phase2 import sweeps

    uid, query = _one_uid_and_query()

    def fast_solve(q, variants, budget_sec):
        return {"itinerary": [{"day": 1, "activities": []}]}

    task = {
        "uid": uid,
        "query": query,
        "budget_sec": 30.0,
        "lang": "en",
        "variants": [],  # simulated parent-side parse failure
    }

    sweeps._WORKER.clear()
    sweeps._WORKER.update(
        ready=True,
        lang="en",
        env=None,
        solve_fn=fast_solve,
        llm_client=None,
        flags=orch_mod.Flags(),
    )
    try:
        result = sweeps.solve_one(task)
    finally:
        sweeps._WORKER.clear()

    assert result["telemetry"]["variants_source"] == "worker"
    assert result["telemetry"]["variants_count"] > 0
    # The self-score must have been computed against a real (non-vacuous) constraint set too --
    # a vacuous fallback would report logical_total == 0.
    assert result["score"]["logical_total"] > 0
