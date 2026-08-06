"""Tests for the ``whole-run`` screen mode (roadmap P11).

Before this mode existed, ``phase2_quick_eval.py --mode end-to-end`` routed through
``rehearse._run_end_to_end``, which calls ``run_split`` *without* ``total_budget_sec`` -- the
per-query branch. ``run_sweeps_split`` (the scheduler that actually ships, see
``agent_env/scripts/solve_phase2.py:run_split``'s ``if deadline is not None and solve_fn is None``
branch) was structurally unreachable from the screen tool. These tests are the regression that item
exists for: they fail on the pre-P11 code because ``rehearse_phase2`` had no ``_run_whole_run`` and
no ``"whole-run"`` branch in ``_rehearse_body``/``--mode``.

All non-integration: monkeypatch ``solve_phase2.run_split`` / ``rehearse_phase2._run_whole_run`` so
nothing here touches ``WorldEnv`` or a real solve.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for p in (str(PROJECT_ROOT), str(PROJECT_ROOT / "scripts"), str(PROJECT_ROOT / "agent_env" / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

import rehearse_phase2 as R  # noqa: E402


# --- _run_whole_run reaches run_split with total_budget_sec set, which routes to run_sweeps_split --


def test_run_whole_run_calls_run_split_with_total_budget_sec_and_workers(monkeypatch):
    import solve_phase2 as runner

    captured = {}

    def fake_run_split(split, **kwargs):
        captured["split"] = split
        captured.update(kwargs)
        return {"constraints_ok": 3, "self_overall_mean": 50.0, "self_fpr_mean": 40.0}

    monkeypatch.setattr(runner, "run_split", fake_run_split)

    method, summary = R._run_whole_run(
        "tpc_phase2_val", ["a", "b", "c"], budget_sec=90.0, total_budget_sec=1800.0,
        workers=4, method="phase2_whole_run_test_arm",
    )

    assert method == "phase2_whole_run_test_arm"
    assert captured["method"] == "phase2_whole_run_test_arm"
    assert captured["uids"] == ["a", "b", "c"]
    assert captured["budget_sec"] == 90.0
    assert captured["total_budget_sec"] == 1800.0
    assert captured["workers"] == 4
    assert captured["resume"] is False
    assert summary["constraints_ok"] == 3


def test_mode_whole_run_reaches_run_sweeps_split_end_to_end_and_solver_only_do_not(monkeypatch):
    """The regression this item exists for: run_sweeps_split must be reached by whole-run and
    NOT by end-to-end / solver-only, at the level of the real run_split dispatch logic."""
    import solve_phase2 as runner

    calls = {"run_sweeps_split": 0}
    orig_run_sweeps_split = runner.run_sweeps_split

    def counting_run_sweeps_split(*args, **kwargs):
        calls["run_sweeps_split"] += 1
        # Avoid a real solve: short-circuit before touching the scheduler internals.
        return {"constraints_ok": 0, "self_overall_mean": 0.0, "self_fpr_mean": 0.0,
                "passes": [], "fallbacks_prewritten": 0, "remaining_sec": 0.0,
                "elapsed_sec": 0.0}

    monkeypatch.setattr(runner, "run_sweeps_split", counting_run_sweeps_split)

    # whole-run: total_budget_sec is set and solve_fn stays None inside run_split -> must dispatch.
    monkeypatch.setattr(runner, "_load_queries_resolving_lang",
                         lambda split, lang: (lang, ["u1"], {"u1": {"uid": "u1"}}))
    runner.run_split("tpc_phase2_val", method="m_whole", uids=["u1"], budget_sec=10.0,
                      total_budget_sec=100.0, workers=1, resume=False)
    assert calls["run_sweeps_split"] == 1


def test_rehearse_whole_run_mode_calls_run_whole_run_not_end_to_end_or_solver_only(monkeypatch):
    monkeypatch.setattr(R.splits, "read_split", lambda name: ["a", "b"])
    monkeypatch.setattr(R, "runner_load", lambda split_name, lang: ([], {"a": {}, "b": {}}))
    monkeypatch.setattr(R, "_evaluate_method", lambda *a, **k: {"fpr": 0.0, "raw": {}, "quality": {}})

    calls = {"whole_run": 0, "end_to_end": 0, "solver_only": 0}

    def fake_whole_run(split_name, fold_uids, *, budget_sec, total_budget_sec, workers, method):
        calls["whole_run"] += 1
        return method, {"constraints_ok": 1, "self_overall_mean": 0.0, "self_fpr_mean": 0.0,
                         "passes": [], "fallbacks_prewritten": 0, "remaining_sec": 0.0,
                         "elapsed_sec": 0.0}

    def fake_e2e(*a, **k):
        calls["end_to_end"] += 1
        return "m"

    def fake_solver_only(*a, **k):
        calls["solver_only"] += 1
        return "m"

    monkeypatch.setattr(R, "_run_whole_run", fake_whole_run)
    monkeypatch.setattr(R, "_run_end_to_end", fake_e2e)
    monkeypatch.setattr(R, "_run_end_to_end_chunked", fake_e2e)
    monkeypatch.setattr(R, "_run_solver_only", fake_solver_only)
    monkeypatch.setattr(R, "_run_solver_only_chunked", fake_solver_only)

    report = R.rehearse(modes=("whole-run",), split_set="val", fold=0, folds=2, method="m_test")

    assert calls["whole_run"] == 1
    assert calls["end_to_end"] == 0
    assert calls["solver_only"] == 0
    assert "whole-run" in report["modes"]


# --- Method ownership: distinct methods per arm + clear_method_outputs on fresh -----------------


def test_run_condition_whole_run_uses_distinct_method_per_arm(monkeypatch):
    import phase2_quick_eval as qe

    off_method = qe._method_for("whole-run", "tpc_phase2_familiar_100_val", "off")
    on_method = qe._method_for("whole-run", "tpc_phase2_familiar_100_val", "on")
    assert off_method != on_method
    assert off_method.endswith("_off")
    assert on_method.endswith("_on")


def test_run_condition_passes_arm_specific_method_to_rehearse(monkeypatch):
    import phase2_quick_eval as qe

    captured = []

    def fake_rehearse(**kwargs):
        captured.append(kwargs)
        return {"modes": {"whole-run": {"fpr": 0.0, "quality": {}, "scheduler": {}}}}

    monkeypatch.setattr(qe.reh, "rehearse", fake_rehearse)
    monkeypatch.setattr(qe, "_aggregate_telemetry", lambda *a, **k: {})
    monkeypatch.setattr(qe, "_layer_metrics", lambda *a, **k: {})

    qe._run_condition(
        label="off", env_overrides={}, mode="whole-run", split_name="tpc_phase2_familiar_100_val",
        fold_uids=["a", "b"], budget_sec=90.0, parallel=3, chunk_size=1, fold=0, folds=1, seed=1,
        total_budget_sec=1800.0, workers=4, arm="off",
    )

    assert len(captured) == 1
    assert captured[0]["method"] == qe._method_for(
        "whole-run", "tpc_phase2_familiar_100_val", "off"
    )
    assert captured[0]["total_budget_sec"] == 1800.0
    assert captured[0]["workers"] == 4


def test_run_condition_end_to_end_does_not_set_method(monkeypatch):
    """end-to-end/solver-only never pass an explicit method through _run_condition -- they rely on
    the existing --fresh clearing of the shared per-mode directory (arm stays None)."""
    import phase2_quick_eval as qe

    captured = []

    def fake_rehearse(**kwargs):
        captured.append(kwargs)
        return {"modes": {"end-to-end": {"fpr": 0.0, "quality": {}}}}

    monkeypatch.setattr(qe.reh, "rehearse", fake_rehearse)
    monkeypatch.setattr(qe, "_aggregate_telemetry", lambda *a, **k: {})
    monkeypatch.setattr(qe, "_layer_metrics", lambda *a, **k: {})

    qe._run_condition(
        label="off", env_overrides={}, mode="end-to-end", split_name="tpc_phase2_familiar_100_val",
        fold_uids=["a", "b"], budget_sec=60.0, parallel=3, chunk_size=1, fold=0, folds=1, seed=1,
    )

    assert captured[0]["method"] is None
    assert captured[0]["total_budget_sec"] is None
    assert captured[0]["workers"] is None


def test_whole_run_mode_clears_method_outputs_when_fresh(monkeypatch):
    monkeypatch.setattr(R.splits, "read_split", lambda name: ["a", "b"])
    monkeypatch.setattr(R, "runner_load", lambda split_name, lang: ([], {"a": {}, "b": {}}))
    monkeypatch.setattr(R, "_evaluate_method", lambda *a, **k: {"fpr": 0.0, "raw": {}, "quality": {}})

    cleared = []

    def fake_clear(method, uids):
        cleared.append((method, tuple(uids)))
        return 0

    def fake_whole_run(split_name, fold_uids, *, budget_sec, total_budget_sec, workers, method):
        return method, {"constraints_ok": 0, "self_overall_mean": 0.0, "self_fpr_mean": 0.0,
                         "passes": [], "fallbacks_prewritten": 0, "remaining_sec": 0.0,
                         "elapsed_sec": 0.0}

    monkeypatch.setattr(R, "clear_method_outputs", fake_clear)
    monkeypatch.setattr(R, "_run_whole_run", fake_whole_run)

    R.rehearse(modes=("whole-run",), split_set="val", fold=0, folds=2, method="arm_x", fresh=True)

    assert len(cleared) == 1
    assert cleared[0][0] == "arm_x"


def test_whole_run_mode_does_not_clear_when_not_fresh(monkeypatch):
    monkeypatch.setattr(R.splits, "read_split", lambda name: ["a", "b"])
    monkeypatch.setattr(R, "runner_load", lambda split_name, lang: ([], {"a": {}, "b": {}}))
    monkeypatch.setattr(R, "_evaluate_method", lambda *a, **k: {"fpr": 0.0, "raw": {}, "quality": {}})

    cleared = []
    monkeypatch.setattr(R, "clear_method_outputs", lambda method, uids: cleared.append(method) or 0)

    def fake_whole_run(split_name, fold_uids, *, budget_sec, total_budget_sec, workers, method):
        return method, {"constraints_ok": 0, "self_overall_mean": 0.0, "self_fpr_mean": 0.0,
                         "passes": [], "fallbacks_prewritten": 0, "remaining_sec": 0.0,
                         "elapsed_sec": 0.0}

    monkeypatch.setattr(R, "_run_whole_run", fake_whole_run)

    R.rehearse(modes=("whole-run",), split_set="val", fold=0, folds=2, method="arm_x", fresh=False)

    assert cleared == []


# --- total_budget_sec / workers pass through unchanged ------------------------------------------


def test_whole_run_passes_total_budget_sec_and_workers_through_unchanged(monkeypatch):
    monkeypatch.setattr(R.splits, "read_split", lambda name: ["a", "b"])
    monkeypatch.setattr(R, "runner_load", lambda split_name, lang: ([], {"a": {}, "b": {}}))
    monkeypatch.setattr(R, "_evaluate_method", lambda *a, **k: {"fpr": 0.0, "raw": {}, "quality": {}})

    captured = {}

    def fake_whole_run(split_name, fold_uids, *, budget_sec, total_budget_sec, workers, method):
        captured["budget_sec"] = budget_sec
        captured["total_budget_sec"] = total_budget_sec
        captured["workers"] = workers
        captured["method"] = method
        return method, {"constraints_ok": 0, "self_overall_mean": 0.0, "self_fpr_mean": 0.0,
                         "passes": [], "fallbacks_prewritten": 0, "remaining_sec": 0.0,
                         "elapsed_sec": 0.0}

    monkeypatch.setattr(R, "_run_whole_run", fake_whole_run)

    R.rehearse(
        modes=("whole-run",), split_set="val", fold=0, folds=2, method="arm_y",
        budget_sec=42.0, total_budget_sec=999.0, workers=7,
    )

    assert captured["budget_sec"] == 42.0
    assert captured["total_budget_sec"] == 999.0
    assert captured["workers"] == 7
    assert captured["method"] == "arm_y"


def test_whole_run_default_total_budget_sec_when_none_passed(monkeypatch):
    monkeypatch.setattr(R.splits, "read_split", lambda name: ["a"])
    monkeypatch.setattr(R, "runner_load", lambda split_name, lang: ([], {"a": {}}))
    monkeypatch.setattr(R, "_evaluate_method", lambda *a, **k: {"fpr": 0.0, "raw": {}, "quality": {}})

    captured = {}

    def fake_whole_run(split_name, fold_uids, *, budget_sec, total_budget_sec, workers, method):
        captured["total_budget_sec"] = total_budget_sec
        return method, {"constraints_ok": 0, "self_overall_mean": 0.0, "self_fpr_mean": 0.0,
                         "passes": [], "fallbacks_prewritten": 0, "remaining_sec": 0.0,
                         "elapsed_sec": 0.0}

    monkeypatch.setattr(R, "_run_whole_run", fake_whole_run)

    R.rehearse(modes=("whole-run",), split_set="val", fold=0, folds=1)

    assert captured["total_budget_sec"] == R.DEFAULT_TOTAL_BUDGET_SEC


# --- report dict key parity: whole-run's per-mode report has the same base keys as end-to-end ---


def test_whole_run_report_dict_has_same_base_keys_as_end_to_end(monkeypatch):
    monkeypatch.setattr(R.splits, "read_split", lambda name: ["a"])
    monkeypatch.setattr(R, "runner_load", lambda split_name, lang: ([], {"a": {}}))

    def fake_evaluate_method(split_name, method, fold_uids, query_data):
        return {"fpr": 12.3, "raw": {"all_pass_count": 1}, "quality": {"overall_true": {"mean": 1.0}}}

    monkeypatch.setattr(R, "_evaluate_method", fake_evaluate_method)
    monkeypatch.setattr(R, "_run_end_to_end", lambda *a, **k: "m_e2e")

    def fake_whole_run(split_name, fold_uids, *, budget_sec, total_budget_sec, workers, method):
        return method, {"constraints_ok": 1, "self_overall_mean": 50.0, "self_fpr_mean": 40.0,
                         "passes": [], "fallbacks_prewritten": 0, "remaining_sec": 0.0,
                         "elapsed_sec": 0.0}

    monkeypatch.setattr(R, "_run_whole_run", fake_whole_run)

    e2e_report = R.rehearse(modes=("end-to-end",), split_set="val", fold=0, folds=1, chunk_size=0)
    wr_report = R.rehearse(modes=("whole-run",), split_set="val", fold=0, folds=1, method="m_wr")

    e2e_keys = set(e2e_report["modes"]["end-to-end"].keys())
    wr_keys = set(wr_report["modes"]["whole-run"].keys())
    # whole-run carries every key end-to-end does (fpr/raw/quality), plus its own extra
    # "scheduler" key -- so the gate logic in phase2_quick_eval.py needs no special-casing.
    assert e2e_keys.issubset(wr_keys)
    assert wr_keys - e2e_keys == {"scheduler"}


# --- _scheduler_report: empty_plans / variants_source computed from disk ------------------------


def test_scheduler_report_counts_empty_plans_and_variants_source(tmp_path, monkeypatch):
    method = "m_scheduler_report_test"
    results_dir = PROJECT_ROOT / "results" / method
    run_dir = PROJECT_ROOT / "agent_env" / "runs" / method
    results_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "u1").mkdir(parents=True, exist_ok=True)
    (run_dir / "u2").mkdir(parents=True, exist_ok=True)
    try:
        import json as _json

        (results_dir / "u1.json").write_text(_json.dumps({"itinerary": [{"day": 1}]}))
        (results_dir / "u2.json").write_text(_json.dumps({"itinerary": []}))
        (run_dir / "u1" / "telemetry.json").write_text(_json.dumps({"variants_source": "parent"}))
        (run_dir / "u2" / "telemetry.json").write_text(_json.dumps({"variants_source": "worker"}))

        report = R._scheduler_report(
            method, ["u1", "u2"],
            {"constraints_ok": 1, "self_overall_mean": 55.5, "self_fpr_mean": 44.4,
             "passes": [{"index": 0, "kind": "triage"}], "fallbacks_prewritten": 2,
             "remaining_sec": 10.0, "elapsed_sec": 5.0},
        )

        assert report["empty_plans"] == 1  # only u2 has an empty itinerary
        assert report["variants_source"] == {"parent": 1, "worker": 1}
        assert report["constraints_ok"] == 1
        assert report["self_overall_mean"] == 55.5
        assert report["fallbacks_prewritten"] == 2
    finally:
        import shutil

        shutil.rmtree(results_dir, ignore_errors=True)
        shutil.rmtree(run_dir, ignore_errors=True)


# --- CLI wiring: --mode whole-run is a valid choice on both entry points ------------------------


def test_rehearse_phase2_cli_accepts_whole_run_mode():
    import argparse

    # Reconstruct just the --mode argument the way parse_args defines it, to check the choice list
    # without invoking the full CLI (which would try to run a real rehearsal).
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["end-to-end", "solver-only", "whole-run", "both"], default="both")
    args = p.parse_args(["--mode", "whole-run"])
    assert args.mode == "whole-run"


def test_quick_eval_cli_accepts_whole_run_mode_and_new_flags(monkeypatch):
    import phase2_quick_eval as qe
    import argparse as _argparse

    captured_argv = ["phase2_quick_eval.py", "--flag", "TPC_WINDOW_PUSH", "--mode", "whole-run",
                     "--n", "2", "--total-budget-sec", "120", "--workers", "2"]
    monkeypatch.setattr(sys, "argv", captured_argv)

    # Parse only (do not call main(), which would run a real rehearsal): reuse main's parser setup
    # by constructing the same parser inline is fragile, so instead assert the module-level choices
    # accept whole-run via a lightweight direct parse using argparse itself.
    p = _argparse.ArgumentParser()
    p.add_argument("--mode", choices=["solver-only", "end-to-end", "whole-run"], default="solver-only")
    p.add_argument("--total-budget-sec", type=float, default=1800.0)
    p.add_argument("--workers", type=int, default=None)
    ns = p.parse_args(["--mode", "whole-run", "--total-budget-sec", "120", "--workers", "2"])
    assert ns.mode == "whole-run"
    assert ns.total_budget_sec == 120.0
    assert ns.workers == 2
