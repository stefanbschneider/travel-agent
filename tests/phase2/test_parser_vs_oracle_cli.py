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


@pytest.mark.integration
def test_run_report_llm_parse_uses_none_backend_by_default(tmp_path, monkeypatch):
    """No TPC_P2_LLM_BACKEND configured -> the auto-built client is NoneLLMClient, so
    llm_parse_stub's early-return (llm_client without a usable complete()) keeps every query on
    the deterministic parse. This should be byte-identical to --llm-parse off."""
    monkeypatch.delenv("TPC_P2_LLM_BACKEND", raising=False)
    baseline = pvo.run_report("tpc_phase2_val", limit=3, out_dir=str(tmp_path / "base"))
    with_flag = pvo.run_report(
        "tpc_phase2_val", limit=3, llm_parse=True, out_dir=str(tmp_path / "llm")
    )
    assert with_flag["precision"] == baseline["precision"]
    assert with_flag["recall"] == baseline["recall"]


@pytest.mark.integration
def test_run_report_llm_parse_reuses_one_client_across_uids(tmp_path, monkeypatch):
    calls = []

    class SpyLLM:
        backend = "spy"

        def complete(self, prompt, *, system=None, cache_key=None):
            calls.append(cache_key)
            return '{"patches": []}'

    spy = SpyLLM()
    agg = pvo.run_report(
        "tpc_phase2_val", limit=3, llm_parse=True, llm_client=spy, out_dir=str(tmp_path)
    )
    assert agg["n"] == 3
    assert len(calls) == 3  # one LLM call per uid, using the single injected client instance
