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
