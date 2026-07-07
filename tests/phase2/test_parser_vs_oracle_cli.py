"""Integration test for the parser_vs_oracle split report + behavioral check (Task 8b).

Opt-in (loads the dataset and results/best). Run with:
    .venv/bin/python -m pytest -m integration tests/phase2/test_parser_vs_oracle_cli.py
"""

from __future__ import annotations

import pytest

import parser_vs_oracle as pvo


@pytest.mark.integration
def test_run_report_structural(tmp_path):
    agg = pvo.run_report("tpc_phase2_val", limit=3, out_dir=str(tmp_path))
    assert agg["n"] == 3
    for key in ("precision", "recall", "value_accuracy"):
        assert 0.0 <= agg[key] <= 1.0
    assert (tmp_path / "parser_vs_oracle_tpc_phase2_val.csv").exists()
    assert (tmp_path / "parser_vs_oracle_tpc_phase2_val.json").exists()


@pytest.mark.integration
def test_run_report_behavioral(tmp_path):
    agg = pvo.run_report("tpc_phase2_val", limit=3, behavioral=True, out_dir=str(tmp_path))
    assert "behavioral" in agg
    assert 0.0 <= agg["behavioral"]["agreement_rate"] <= 1.0
