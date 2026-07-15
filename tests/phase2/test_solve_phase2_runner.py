"""Integration test for the Phase 2 per-query runner.

Opt-in (marked ``integration``): touches the real WorldEnv + TPCAgent. Run with:
    .venv/bin/python -m pytest -m integration tests/phase2/test_solve_phase2_runner.py
"""

from __future__ import annotations

import json
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


@pytest.mark.integration
def test_runner_defaults_llm_parse_on_when_backend_configured(tmp_path, monkeypatch):
    """Mirrors the existing TPC_P2_DISJUNCTION default-on pattern: once a usable LLM backend is
    configured, llm_parse defaults on unless the operator explicitly sets TPC_P2_LLM_PARSE.
    Uses the fixture backend (zero network) with a pre-recorded empty-patch response for this
    split's first uid, so the deterministic parse is unchanged -- this checks the flag actually
    took effect and the audit call succeeds (not just that a missing fixture harmlessly falls
    back, which the step6a fix already covers separately)."""
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
    assert summary["llm_parse_attempts"] == 1
    assert summary["llm_fixture_missing"] == 0
    assert summary["uids"][0] == uid

    telem = json.loads((work_dir / uid / "telemetry.json").read_text(encoding="utf-8"))
    assert telem["flags"]["llm_parse"] is True
    assert "parse:" not in str(telem.get("error") or "")


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

    monkeypatch.setattr(runner.psutil, "Process", lambda: FakeProcess())
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

    monkeypatch.setattr(runner.psutil, "Process", lambda: FakeProcess())
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
