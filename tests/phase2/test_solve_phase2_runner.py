"""Integration test for the Phase 2 per-query runner.

Opt-in (marked ``integration``): touches the real WorldEnv + TPCAgent. Run with:
    .venv/bin/python -m pytest -m integration tests/phase2/test_solve_phase2_runner.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import jsonschema
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads(
    (PROJECT_ROOT / "chinatravel" / "evaluation" / "output_schema.json").read_text(encoding="utf-8")
)


@pytest.mark.integration
def test_runner_writes_official_outputs(tmp_path):
    import solve_phase2 as runner

    method = "phase2_itest"
    results_dir = tmp_path / "results"
    work_dir = tmp_path / "runs"

    summary = runner.run_split(
        "tpc_phase1",
        method=method,
        limit=1,
        budget_sec=20.0,
        results_dir=str(results_dir),
        work_dir=str(work_dir),
    )

    uid = summary["uids"][0]
    result_path = results_dir / method / f"{uid}.json"
    assert result_path.exists(), "official result file must be written"
    plan = json.loads(result_path.read_text(encoding="utf-8"))
    jsonschema.validate(plan, SCHEMA)  # oracle-free plan is at least schema-valid

    eval_path = work_dir / uid / "evaluation.json"
    assert eval_path.exists(), "evaluation.json must be written"

    telem_path = work_dir / uid / "telemetry.json"
    assert telem_path.exists()
    telem = json.loads(telem_path.read_text(encoding="utf-8"))
    assert telem["llm_backend"] == "none"
    assert telem["llm_backend_source"] == "none"


@pytest.mark.integration
def test_runner_keeps_llm_parse_off_until_explicitly_enabled(tmp_path, monkeypatch):
    """A configured LLM backend must NOT switch the parse audit on by itself.

    This test previously asserted the opposite -- llm_parse defaulting on with a usable backend,
    mirroring TPC_P2_DISJUNCTION -- and had been failing since that decision was reversed in
    ``resolve_llm_client_and_flags`` (roadmap W8): the paired same-SHA screen came back RED for
    audit-on, and an auto-enable that fires only when an endpoint happens to be reachable would
    make the organizer run behave differently from every local run. Both arms are checked here,
    since "off by default" is only meaningful if the explicit opt-in still works.

    Uses the fixture backend (zero network) with a pre-recorded empty-patch response for this
    split's first uid, so the deterministic parse is unchanged: this checks the flag plumbing,
    not the audit's content."""
    import solve_phase2 as runner
    from chinatravel.agent.phase2 import normalize
    from chinatravel.data.load_datasets import load_query
    import parse_constraints as pc
    import argparse

    args = argparse.Namespace(splits="tpc_phase1", lang="en", oracle_translation=True)
    query_ids, query_data = load_query(args)
    uid = query_ids[0]
    query = query_data[uid]
    query.setdefault("uid", uid)
    raw = pc.parse_query_no_oracle(query)
    prompt = normalize.build_llm_parse_prompt(query, raw)
    cache_key = normalize.llm_parse_cache_key(query, prompt)

    fixtures_dir = tmp_path / "fixtures"
    fixtures_dir.mkdir()
    (fixtures_dir / f"{cache_key}.json").write_text(
        json.dumps({"response": json.dumps({"patches": []})}), encoding="utf-8"
    )
    method = "phase2_itest_llmparse"
    results_dir = tmp_path / "results"
    work_dir = tmp_path / "runs"

    monkeypatch.setenv("TPC_P2_LLM_BACKEND", "fixture")
    monkeypatch.setenv("TPC_P2_LLM_FIXTURES", str(fixtures_dir))
    monkeypatch.delenv("TPC_P2_LLM_PARSE", raising=False)

    summary = runner.run_split(
        "tpc_phase1",
        method=method,
        limit=1,
        budget_sec=20.0,
        results_dir=str(results_dir),
        work_dir=str(work_dir),
    )
    assert summary["llm_backend"] == "fixture"
    assert summary["llm_backend_source"] == "env-explicit"
    assert summary["llm_parse_attempts"] == 0, "a reachable backend must not enable the audit"
    assert summary["uids"][0] == uid

    telem = json.loads((work_dir / uid / "telemetry.json").read_text(encoding="utf-8"))
    assert telem["llm_backend_source"] == "env-explicit"
    assert telem["flags"]["llm_parse"] is False

    # ... and the explicit opt-in still reaches the LLM.
    monkeypatch.setenv("TPC_P2_LLM_PARSE", "1")
    opt_in_work_dir = tmp_path / "runs_opt_in"
    opt_in_summary = runner.run_split(
        "tpc_phase1",
        method=method + "_opt_in",
        limit=1,
        budget_sec=20.0,
        results_dir=str(results_dir),
        work_dir=str(opt_in_work_dir),
    )
    assert opt_in_summary["llm_parse_attempts"] == 1
    assert opt_in_summary["llm_fixture_missing"] == 0

    opt_in_telem = json.loads(
        (opt_in_work_dir / uid / "telemetry.json").read_text(encoding="utf-8")
    )
    assert opt_in_telem["flags"]["llm_parse"] is True
    assert "parse:" not in str(opt_in_telem.get("error") or "")


def _fast_solve(query, variants, budget_sec):
    return {
        "people_number": query.get("people_number", 1),
        "start_city": query.get("start_city", ""),
        "target_city": query.get("target_city", ""),
        "itinerary": [{"day": 1, "activities": []}],
    }


def test_llm_parse_failed_counter_catches_a_broken_backend(tmp_path, monkeypatch):
    """Regression test for the silent-fallback gap that let a broken DeepInfra model string
    (2026-07-11: 'qwen3.6-27b' 404'd on every call) pass every baseline/gate check as green,
    because parse_to_ir's fallback-on-exception (by design, for production robustness) left no
    trace anywhere the summary or ledger could see. llm_parse_failed must count every query where
    the LLM call itself raised, distinct from llm_fixture_missing (a different, expected case)."""
    import solve_phase2 as runner

    class RaisingLLM:
        backend = "test-raising"

        def complete(self, prompt, *, system=None, cache_key=None):
            raise RuntimeError("simulated 404: model not found")

    monkeypatch.setenv("TPC_P2_LLM_PARSE", "1")
    monkeypatch.setattr(runner.p2_llm, "build_llm_client", lambda cfg: RaisingLLM())

    summary = runner.run_split(
        "tpc_phase1",
        method="phase2_llmfailtest",
        limit=2,
        budget_sec=5.0,
        results_dir=str(tmp_path / "results"),
        work_dir=str(tmp_path / "runs"),
        solve_fn=_fast_solve,
    )

    assert summary["llm_parse_attempts"] == 2
    assert summary["llm_parse_failed"] == 2
    assert summary["llm_fixture_missing"] == 0


def test_rss_guard_warns_when_growth_exceeds_threshold(tmp_path, monkeypatch, capsys):
    """TPC_P2_MAX_RSS_MB is warn-only: it must never abort the run, only print a warning once
    per-query growth (since the first solved query in this process) exceeds the threshold."""
    import solve_phase2 as runner

    rss_values_mb = iter([100.0, 100.0, 700.0])  # baseline, under, over threshold

    class FakeMemInfo:
        def __init__(self, rss_mb):
            self.rss = rss_mb * 1024 * 1024

    class FakeProcess:
        def memory_info(self):
            return FakeMemInfo(next(rss_values_mb))

    monkeypatch.setattr(runner, "current_rss_mb", lambda: FakeProcess().memory_info().rss / (1024 * 1024))
    monkeypatch.setattr(runner, "MAX_RSS_GROWTH_MB", 500.0)

    summary = runner.run_split(
        "tpc_phase1",
        method="phase2_rsstest_warn",
        limit=3,
        budget_sec=5.0,
        results_dir=str(tmp_path / "results"),
        work_dir=str(tmp_path / "runs"),
        solve_fn=_fast_solve,
    )

    assert summary["selected"] == 3, "guard must not abort the run"
    out = capsys.readouterr().out
    assert "[rss-warn]" in out
    assert "TPC_P2_MAX_RSS_MB=500" in out


def test_rss_guard_silent_when_disabled(tmp_path, monkeypatch, capsys):
    import solve_phase2 as runner

    rss_values_mb = iter([100.0, 100.0, 5000.0])

    class FakeMemInfo:
        def __init__(self, rss_mb):
            self.rss = rss_mb * 1024 * 1024

    class FakeProcess:
        def memory_info(self):
            return FakeMemInfo(next(rss_values_mb))

    monkeypatch.setattr(runner, "current_rss_mb", lambda: FakeProcess().memory_info().rss / (1024 * 1024))
    monkeypatch.setattr(runner, "MAX_RSS_GROWTH_MB", 0.0)  # disabled (default)

    runner.run_split(
        "tpc_phase1",
        method="phase2_rsstest_off",
        limit=3,
        budget_sec=5.0,
        results_dir=str(tmp_path / "results"),
        work_dir=str(tmp_path / "runs"),
        solve_fn=_fast_solve,
    )

    assert "[rss-warn]" not in capsys.readouterr().out


@pytest.mark.integration
def test_runner_resume_skips_existing(tmp_path):
    import solve_phase2 as runner

    method = "phase2_itest_resume"
    results_dir = tmp_path / "results"
    work_dir = tmp_path / "runs"
    common = dict(
        method=method,
        limit=1,
        budget_sec=20.0,
        results_dir=str(results_dir),
        work_dir=str(work_dir),
    )
    runner.run_split("tpc_phase1", **common)
    summary2 = runner.run_split("tpc_phase1", resume=True, **common)
    assert summary2["skipped"] >= 1


# --- Deterministic solver-flag promotion (not integration: pure env-var logic) ------------------

def test_apply_deterministic_solver_defaults_promotes_pin_and_converge(monkeypatch):
    import solve_phase2 as runner

    promoted_flags = ("TPC_PIN_TIMED_WINDOWS", "TPC_SOLVE_CONVERGE_PATIENCE", "TPC_COMMONSENSE_FIRST",
                       "TPC_WINDOW_ANCHOR", "TPC_WINDOW_PUSH", "TPC_WINDOW_INSERT")
    for name in promoted_flags:
        monkeypatch.delenv(name, raising=False)

    # apply_deterministic_solver_defaults() writes os.environ directly (mirroring the shipped
    # harness), not through monkeypatch -- monkeypatch has never seen these keys set, so a delenv
    # called *after* this write would capture the just-written value as "the original" and restore
    # it at teardown, leaking a promoted flag into every later test in the process. Clean up with
    # plain os.environ instead.
    try:
        runner.apply_deterministic_solver_defaults()

        assert os.environ["TPC_PIN_TIMED_WINDOWS"] == "1"
        assert os.environ["TPC_SOLVE_CONVERGE_PATIENCE"] == "15"
        # Promoted on the 2026-07-26 paired e2e screen (overall_true 51.34 -> 60.98, C-LPR
        # 67.35 -> 89.95, commonsense pass 30/40 -> 40/40).
        assert os.environ["TPC_COMMONSENSE_FIRST"] == "1"
        # Promoted on R8 (full_runs/20260805T123142Z): overall 63.58 vs R7's 57.75, FPR 43.0 vs
        # 32.0, constraints_ok 46/100 vs 36/100, against a baseline whose three repeats were
        # bit-identical.
        assert os.environ["TPC_WINDOW_ANCHOR"] == "1"
        # Promoted on R14 (full_runs/20260806T052925Z), the P8/P9 gate: overall 64.13167839953107
        # (+0.5471) vs the TPC_WINDOW_ANCHOR-only baseline, FPR 44.0 (+1.0), empty_plans 0/100.
        assert os.environ["TPC_WINDOW_PUSH"] == "1"
        assert os.environ["TPC_WINDOW_INSERT"] == "1"
    finally:
        for name in promoted_flags:
            os.environ.pop(name, None)


def test_apply_deterministic_solver_defaults_respects_operator_override(monkeypatch):
    """An explicit env value (e.g. the eval tooling's flags-off A/B arm) must win over the promoted
    default -- the same operator-override contract as the TPC_P2_* harness defaults."""
    import solve_phase2 as runner

    monkeypatch.setenv("TPC_PIN_TIMED_WINDOWS", "0")
    monkeypatch.setenv("TPC_SOLVE_CONVERGE_PATIENCE", "7")
    monkeypatch.setenv("TPC_COMMONSENSE_FIRST", "0")
    monkeypatch.setenv("TPC_WINDOW_ANCHOR", "0")
    monkeypatch.setenv("TPC_WINDOW_PUSH", "0")
    monkeypatch.setenv("TPC_WINDOW_INSERT", "0")

    runner.apply_deterministic_solver_defaults()

    assert os.environ["TPC_PIN_TIMED_WINDOWS"] == "0"
    assert os.environ["TPC_SOLVE_CONVERGE_PATIENCE"] == "7"
    assert os.environ["TPC_COMMONSENSE_FIRST"] == "0"
    # The R7-vs-R8 style A/B arm has to stay expressible after promotion, or the row that promoted
    # the flag could never be reproduced.
    assert os.environ["TPC_WINDOW_ANCHOR"] == "0"
    assert os.environ["TPC_WINDOW_PUSH"] == "0"
    assert os.environ["TPC_WINDOW_INSERT"] == "0"


def test_injected_solve_fn_does_not_leak_solver_defaults(tmp_path, monkeypatch):
    """Regression for the env-leak Copilot flagged on PR #41: run_split with an *injected* solve_fn
    builds no agent, so it must not mutate the process-global TPC_PIN_TIMED_WINDOWS /
    TPC_SOLVE_CONVERGE_PATIENCE / TPC_COMMONSENSE_FIRST / TPC_WINDOW_ANCHOR / TPC_WINDOW_PUSH /
    TPC_WINDOW_INSERT -- only the agent-building path (solve_fn is None) promotes them."""
    import solve_phase2 as runner

    monkeypatch.delenv("TPC_PIN_TIMED_WINDOWS", raising=False)
    monkeypatch.delenv("TPC_SOLVE_CONVERGE_PATIENCE", raising=False)
    monkeypatch.delenv("TPC_COMMONSENSE_FIRST", raising=False)
    monkeypatch.delenv("TPC_WINDOW_ANCHOR", raising=False)
    monkeypatch.delenv("TPC_WINDOW_PUSH", raising=False)
    monkeypatch.delenv("TPC_WINDOW_INSERT", raising=False)

    runner.run_split(
        "tpc_phase1",
        method="phase2_leakcheck",
        limit=1,
        budget_sec=5.0,
        results_dir=str(tmp_path / "results"),
        work_dir=str(tmp_path / "runs"),
        solve_fn=_fast_solve,
    )

    assert "TPC_PIN_TIMED_WINDOWS" not in os.environ
    assert "TPC_SOLVE_CONVERGE_PATIENCE" not in os.environ
    assert "TPC_COMMONSENSE_FIRST" not in os.environ
    assert "TPC_WINDOW_ANCHOR" not in os.environ
    assert "TPC_WINDOW_PUSH" not in os.environ
    assert "TPC_WINDOW_INSERT" not in os.environ
