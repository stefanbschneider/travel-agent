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
