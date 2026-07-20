"""Unit tests for the resolved-flags ledger block.

A baseline row that records only backend/model is ambiguous: the real harness
(``solve_phase2.resolve_llm_client_and_flags``) defaults several Phase 2 features ON, and those
defaults live in code that can change over time. Recording the resolved ``Flags`` in the row makes
it reproducible and comparable. These tests pin that contract at the projection layer and confirm
the harness default set.
"""

from __future__ import annotations

import phase2_record_baseline as B
from chinatravel.agent.phase2 import orchestrator as orch


def _record(**overrides):
    record = {
        "rehearsal": {"modes": {}, "ceiling": {}},
        "parser": {"behavioral": {}},
        "parser_full": {"behavioral": {}},
        "llm_config": {"backend": "deepinfra", "model": "Qwen/Qwen3.6-27B"},
        "flags": {
            "disjunction": True,
            "llm_parse": True,
            "llm_parse_mode": "audit",
            "llm_refine": False,
            "dynamic_budget": True,
            "entity_resolution": True,
        },
    }
    record.update(overrides)
    return record


def test_flags_snapshot_serializes_every_recorded_field():
    flags = orch.Flags(
        disjunction=True,
        llm_parse=True,
        llm_parse_mode="extract",
        llm_refine=False,
        dynamic_budget=True,
        entity_resolution=True,
    )
    snap = B._flags_snapshot(flags)
    assert snap == {
        "disjunction": True,
        "llm_parse": True,
        "llm_parse_mode": "extract",
        "llm_refine": False,
        "dynamic_budget": True,
        "entity_resolution": True,
    }


def test_to_history_row_projects_flag_columns():
    row = B._to_history_row(_record())
    assert row["disjunction"] is True
    assert row["dynamic_budget"] is True
    assert row["entity_resolution"] is True
    assert row["llm_refine"] is False
    assert row["llm_parse_mode"] == "audit"


def test_to_history_row_llm_parse_prefers_recorded_flag_over_backend():
    # Flag says parsing was off even though a backend is configured -> trust the flag.
    row = B._to_history_row(_record(flags={"llm_parse": False}))
    assert row["llm_backend"] == "deepinfra"
    assert row["llm_parse"] is False


def test_to_history_row_llm_parse_falls_back_to_backend_for_legacy_rows():
    # Legacy row: no flags block at all -> fall back to the old backend heuristic, no crash.
    legacy = _record()
    legacy.pop("flags")
    row = B._to_history_row(legacy)
    assert row["llm_parse"] is True  # backend != "none"
    assert row["disjunction"] is None


def test_flag_columns_present_in_csv_fieldnames(tmp_path):
    csv_path = tmp_path / "history.csv"
    B._write_history_csv(csv_path, [_record(run_id="r1")])
    header = csv_path.read_text(encoding="utf-8").splitlines()[0]
    for col in ("disjunction", "dynamic_budget", "entity_resolution", "llm_refine", "llm_parse_mode"):
        assert col in header


def test_latest_md_includes_flags_section(tmp_path):
    md_path = tmp_path / "latest.md"
    B._write_latest_md(md_path, _record(run_id="r1"))
    text = md_path.read_text(encoding="utf-8")
    assert "## Phase 2 Flags (resolved for the e2e run)" in text
    assert "- entity_resolution: True" in text


def test_harness_defaults_enable_deterministic_features(monkeypatch, no_network):
    """The recorded contract's source of truth: with no operator overrides, the harness turns on
    disjunction, dynamic budgeting, and entity resolution (all deterministic, backend-independent).

    Pin the backend to ``none`` so the test is hermetic: ``resolve_llm_client_and_flags()`` otherwise
    reads ``agent_env/config.toml`` and could construct a real backend (and, via ``no_network``,
    fail) depending on the machine. With the backend forced off, ``llm_parse`` must stay off while
    the three deterministic features are still enabled.
    """
    import solve_phase2 as sp

    for var in (
        "TPC_P2_DISJUNCTION",
        "TPC_P2_DYNAMIC_BUDGET",
        "TPC_P2_ENTITY_RESOLUTION",
        "TPC_P2_LLM_PARSE",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("TPC_P2_LLM_BACKEND", "none")

    client, flags = sp.resolve_llm_client_and_flags()
    assert client.backend == "none"
    assert flags.disjunction is True
    assert flags.dynamic_budget is True
    assert flags.entity_resolution is True
    # Backend off => the LLM parse audit stays off even without an explicit TPC_P2_LLM_PARSE override.
    assert flags.llm_parse is False
