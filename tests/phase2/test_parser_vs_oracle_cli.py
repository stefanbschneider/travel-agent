"""Integration test for the parser-versus-oracle split report and behavioral check.

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
def test_run_report_behavioral_unavailable_without_best_plans(tmp_path):
    """familiar-100 ships no results/best plans, so the accept-side check has nothing to score.
    It must report None (unavailable), not a 0.0 that reads as total disagreement."""
    agg = pvo.run_report(
        "tpc_phase2_familiar_100", limit=5, behavioral=True, out_dir=str(tmp_path)
    )
    behavioral = agg["behavioral"]
    assert behavioral["n"] == 0
    assert behavioral["accept_agreement"] is None
    assert behavioral["agreement_rate"] is None
    assert behavioral["behavioral_balanced"] is None


@pytest.mark.integration
def test_run_report_behavioral_two_sided_metrics(tmp_path):
    """Verify that accept, reject, and balanced behavioral metrics accompany the legacy
    ``agreement_rate``. The limit must provide at least one `(target_city, days)` group with two
    members so the reject-probe set is not trivially empty."""
    agg = pvo.run_report(
        "tpc_phase2_val", limit=40, behavioral=True, disjunction=True, out_dir=str(tmp_path)
    )
    behavioral = agg["behavioral"]
    assert behavioral["agreement_rate"] == behavioral["accept_agreement"]
    assert behavioral["reject_probes_n"] == agg["n"]
    if behavioral["reject_probes_kept_n"] > 0:
        assert behavioral["reject_agreement"] is not None
        assert 0.0 <= behavioral["reject_agreement"] <= 1.0
        assert 0.0 <= behavioral["behavioral_balanced"] <= 1.0
    else:
        assert behavioral["reject_agreement"] is None
        assert behavioral["behavioral_balanced"] == behavioral["accept_agreement"]


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
