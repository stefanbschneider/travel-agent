"""The organizer-confirmed entry point must run *our* solver, bare.

The organizers invoke exactly ``python agent_env/scripts/solve_script_with_harness.py --split
<split>`` -- no other flags, no environment beyond a clean checkout -- so whatever a bare
invocation does *is* the Phase 2 submission. These tests pin the two facts that makes true:

1. bare (no ``--harness``, no local ``config.toml``) dispatches to the deterministic in-process
   solver and never shells out to ``opencode``/``codex``;
2. the run is bounded by the confirmed whole-run wall-clock envelope, not by a fixed per-query
   budget that would overrun it.

See ``docs/tpc_phase2_design.md`` ("Entry point") for the shipped contract.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import solve_phase2 as sp2
import solve_script_with_harness as hb

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def no_local_config(monkeypatch, tmp_path):
    """A clean checkout has no ``agent_env/config.toml`` (it is gitignored); a developer machine
    may. Point the default at a path that cannot exist so the test measures the shipped default,
    not the local one."""
    monkeypatch.setattr(hb, "DEFAULT_CONFIG_PATH", tmp_path / "absent-config.toml")


@pytest.fixture
def no_subprocess(monkeypatch):
    """Any subprocess call from the default path is a test failure, not a mocked success."""

    def _fail(*args, **kwargs):
        raise AssertionError(f"default harness must not spawn a subprocess: {args!r}")

    monkeypatch.setattr(hb.subprocess, "run", _fail)


def test_shipped_default_harness_is_the_deterministic_solver():
    assert hb.DEFAULT_HARNESS == hb.TPC_HARNESS == "tpc"
    assert hb.HARNESS_CHOICES[0] == "tpc"
    assert set(hb.EXTERNAL_HARNESSES) == {"opencode", "codex"}


def test_bare_invocation_runs_the_tpc_harness(monkeypatch, no_local_config, no_subprocess):
    captured: dict = {}

    def fake_run_tpc_split(**kwargs):
        captured.update(kwargs)
        return {"split": kwargs["split"], "selected": 0, "uids": []}

    monkeypatch.setattr(hb, "run_tpc_split", fake_run_tpc_split)
    monkeypatch.setattr(sys, "argv", ["solve_script_with_harness.py", "--split", "some_split"])

    hb.main()

    assert captured["split"] == "some_split"
    # Upstream PR #33 made English the harness default; the held-out split is not named
    # tpc_phase2_familiar_100, so nothing may infer the language from the split name.
    assert captured["lang"] == "en"
    assert captured["method"] == "phase2_e2e_some_split"
    # Unspecified: resolved to the organizer envelope inside run_tpc_split, not here.
    assert captured["total_budget_sec"] is None
    assert captured["budget_sec"] is None
    assert captured["workers"] is None  # resolved to CPU count - 1 inside run_tpc_split
    assert captured["uid"] is None and captured["limit"] is None


def test_external_harness_is_still_reachable_but_opt_in(monkeypatch, no_local_config):
    seen: list[str] = []

    monkeypatch.setattr(hb, "load_queries", lambda split, lang: (["u1"], {"u1": {"uid": "u1"}}))
    monkeypatch.setattr(hb, "evaluate_split", lambda *a, **k: {})
    monkeypatch.setattr(hb, "solve_query", lambda **kwargs: seen.append(kwargs["harness"]))
    monkeypatch.setattr(
        hb,
        "run_tpc_split",
        lambda **kwargs: pytest.fail("--harness codex must not run the tpc harness"),
    )
    monkeypatch.setattr(
        sys, "argv", ["solve_script_with_harness.py", "--split", "s", "--harness", "codex"]
    )

    hb.main()

    assert seen == ["codex"]


def test_tpc_method_matches_solve_phase2_so_the_two_entry_points_share_results():
    split = "tpc_phase2_familiar_100_val"
    assert hb.default_method(None, split, "tpc") == sp2._default_method_for_split(split)


def test_run_tpc_split_defaults_to_the_confirmed_five_hour_envelope(monkeypatch):
    captured: dict = {}

    class FakeSolvePhase2:
        DEFAULT_TOTAL_BUDGET_SEC = sp2.DEFAULT_TOTAL_BUDGET_SEC
        resolve_total_budget_sec = staticmethod(sp2.resolve_total_budget_sec)

        @staticmethod
        def run_split(split, **kwargs):
            captured.update(kwargs, split=split)
            return {}

    monkeypatch.delenv("TPC_P2_TOTAL_BUDGET_SEC", raising=False)
    monkeypatch.setattr(hb, "load_solve_phase2_module", lambda: FakeSolvePhase2)

    hb.run_tpc_split(
        split="s",
        lang="en",
        method="m",
        uid=None,
        limit=None,
        resume=False,
        budget_sec=None,
        total_budget_sec=None,
        workers=None,
        work_dir=None,
    )

    assert captured["total_budget_sec"] == 5 * 60 * 60
    # The clock starts at interpreter start, so database load counts against the envelope.
    assert captured["start_monotonic"] == hb.PROCESS_START_MONOTONIC


def test_run_tpc_split_honours_an_explicit_disable(monkeypatch):
    captured: dict = {}

    class FakeSolvePhase2:
        DEFAULT_TOTAL_BUDGET_SEC = sp2.DEFAULT_TOTAL_BUDGET_SEC
        resolve_total_budget_sec = staticmethod(sp2.resolve_total_budget_sec)

        @staticmethod
        def run_split(split, **kwargs):
            captured.update(kwargs, split=split)
            return {}

    monkeypatch.delenv("TPC_P2_TOTAL_BUDGET_SEC", raising=False)
    monkeypatch.setattr(hb, "load_solve_phase2_module", lambda: FakeSolvePhase2)

    hb.run_tpc_split(
        split="s",
        lang="en",
        method="m",
        uid=None,
        limit=None,
        resume=False,
        budget_sec=None,
        total_budget_sec=0,
        workers=None,
        work_dir=None,
    )

    assert captured["total_budget_sec"] is None


class TestQueryBudget:
    """``query_budget_sec`` is what keeps a 100-query run inside 5 hours."""

    def test_fair_share_binds_when_the_per_query_cap_would_overrun(self):
        # 100 queries x the 300s working default = 8.3h > the 5h envelope.
        budget = sp2.query_budget_sec(cap_sec=300.0, remaining_sec=16200.0, remaining_queries=100)
        assert budget == pytest.approx(162.0)

    def test_cap_binds_when_the_run_is_ahead_of_schedule(self):
        budget = sp2.query_budget_sec(cap_sec=300.0, remaining_sec=16200.0, remaining_queries=10)
        assert budget == 300.0

    def test_floor_holds_when_the_run_is_behind_schedule(self):
        budget = sp2.query_budget_sec(cap_sec=300.0, remaining_sec=1.0, remaining_queries=100)
        assert budget == sp2.MIN_QUERY_BUDGET_SEC

    def test_exhausted_envelope_never_returns_a_negative_budget(self):
        budget = sp2.query_budget_sec(cap_sec=300.0, remaining_sec=-500.0, remaining_queries=5)
        assert budget == sp2.MIN_QUERY_BUDGET_SEC

    def test_a_full_split_fits_the_envelope_when_every_query_uses_its_whole_budget(self):
        """Walk the real allocation loop: 100 queries, each consuming exactly what it was
        given, must not exceed the reserved envelope."""
        total = sp2.DEFAULT_TOTAL_BUDGET_SEC
        remaining = total * (1.0 - sp2.TOTAL_BUDGET_RESERVE_FRAC)
        spent = 0.0
        for i in range(100):
            budget = sp2.query_budget_sec(
                cap_sec=300.0, remaining_sec=remaining, remaining_queries=100 - i
            )
            spent += budget
            remaining -= budget
        assert spent <= total * (1.0 - sp2.TOTAL_BUDGET_RESERVE_FRAC) + 1e-6
        assert spent <= total

    def test_unused_time_flows_to_later_queries(self):
        remaining = 16200.0
        first = sp2.query_budget_sec(cap_sec=300.0, remaining_sec=remaining, remaining_queries=100)
        remaining -= first / 10  # the first query solved in a tenth of its budget
        second = sp2.query_budget_sec(cap_sec=300.0, remaining_sec=remaining, remaining_queries=99)
        assert second > first


def test_resolve_total_budget_sec_precedence(monkeypatch):
    monkeypatch.delenv("TPC_P2_TOTAL_BUDGET_SEC", raising=False)
    assert sp2.resolve_total_budget_sec(None) is None
    assert sp2.resolve_total_budget_sec(120) == 120.0
    assert sp2.resolve_total_budget_sec(0) is None

    monkeypatch.setenv("TPC_P2_TOTAL_BUDGET_SEC", "600")
    assert sp2.resolve_total_budget_sec(None) == 600.0
    assert sp2.resolve_total_budget_sec(120) == 120.0, "an explicit argument wins over the env"

    monkeypatch.setenv("TPC_P2_TOTAL_BUDGET_SEC", "not-a-number")
    assert sp2.resolve_total_budget_sec(None) is None


@pytest.mark.integration
def test_bare_command_end_to_end_produces_a_schema_valid_plan(tmp_path):
    """The ship bar: the organizers' exact command shape, in a real subprocess, with neither
    ``opencode`` nor ``codex`` installed and no API key set, produces an evaluator-valid plan."""
    from chinatravel.evaluation.schema_constraint import evaluate_schema_constraints
    from chinatravel.evaluation.utils import load_json_file

    method = "test_bare_entry_point"
    # The harness writes under results/<method>/ in the repo, and never regresses a query -- so a
    # stale plan from an earlier run would make this run improve nothing. Start clean.
    method_dir = PROJECT_ROOT / "results" / method
    if method_dir.exists():
        shutil.rmtree(method_dir)
    env = {
        "PATH": "/usr/bin:/bin",  # no opencode/codex binary reachable
        "HOME": str(tmp_path),
        "TPC_P2_TOTAL_BUDGET_SEC": "180",
    }
    completed = subprocess.run(
        [
            sys.executable,
            "agent_env/scripts/solve_script_with_harness.py",
            "--split",
            "tpc_phase2_familiar_100_val",
            # Not part of the organizer command; keeps the test to one query.
            "--limit",
            "1",
            "--method",
            method,
            "--work-dir",
            str(tmp_path / "runs"),
        ],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert completed.returncode == 0, completed.stderr[-4000:]
    assert "opencode" not in completed.stdout.lower()

    plans = sorted((PROJECT_ROOT / "results" / method).glob("*.json"))
    assert plans, "the bare command produced no plan"
    uid = plans[0].stem
    plan = json.loads(plans[0].read_text(encoding="utf-8"))
    schema = load_json_file(
        str(PROJECT_ROOT / "chinatravel" / "evaluation" / "output_schema.json")
    )
    rate, _, passed = evaluate_schema_constraints([uid], {uid: plan}, schema=schema)
    assert uid in passed, f"schema rate {rate}"

    telemetry = json.loads(
        (tmp_path / "runs" / uid / "telemetry.json").read_text(encoding="utf-8")
    )
    assert telemetry["llm_backend"] == "none"
    assert telemetry["valid_output"] is True
    # Telemetry is written for every attempt, so `kept` records whether *this* attempt beat the
    # incumbent -- and a later pass that fails to improve on an already-good plan is a normal,
    # non-failing outcome. Only its presence is a contract.
    assert "kept" in telemetry
