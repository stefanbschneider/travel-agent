"""Integration test for the Phase 2 per-query runner (Task 6).

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
