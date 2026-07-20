"""Unit tests for full-split parser and LLM-config ledger columns.

Fold-scoped parser metrics can miss a parser fix when its affected UIDs are outside the seeded
fold. ``parser_full`` runs the same solver-free diff over the full validation or test split, so
every ledger row carries a broader parser signal.
"""

from __future__ import annotations

import phase2_record_baseline as B


def _record(**overrides):
    record = {
        "rehearsal": {"modes": {}, "ceiling": {}},
        "parser": {"precision": 0.5, "recall": 0.5, "behavioral": {"agreement_rate": 0.9}},
        "parser_full": {
            "n": 850,
            "precision": 0.5472,
            "recall": 0.6981,
            "f1": 0.6135,
            "value_accuracy": 0.8107,
            "disjunction_flattened": 137,
            "behavioral": {"agreement_rate": 0.7565},
        },
        "llm_config": {"backend": "deepinfra", "model": "Qwen/Qwen3.6-27B"},
    }
    record.update(overrides)
    return record


def test_to_history_row_projects_full_val_parser_columns():
    row = B._to_history_row(_record())
    assert row["parser_full_n"] == 850
    assert row["parser_full_precision"] == 0.5472
    assert row["parser_full_recall"] == 0.6981
    assert row["parser_full_f1"] == 0.6135
    assert row["parser_full_value_accuracy"] == 0.8107
    assert row["parser_full_disjunction_flattened"] == 137
    assert row["parser_full_behavioral_agreement_rate"] == 0.7565


def test_to_history_row_keeps_behavioral_unavailable_as_none():
    # A data source with no best plans (e.g. familiar-100) yields None accept-side agreement.
    # It must stay None in the row -- a 0.0 would read as total parser/oracle disagreement.
    record = _record(
        parser={"precision": 0.5, "recall": 0.5, "behavioral": {"agreement_rate": None}},
    )
    record["parser_full"]["behavioral"] = {
        "agreement_rate": None,
        "behavioral_balanced": None,
    }
    row = B._to_history_row(record)
    assert row["behavioral_agreement_rate"] is None
    assert row["parser_full_behavioral_agreement_rate"] is None
    assert row["parser_full_behavioral_balanced"] is None


def test_to_history_row_projects_llm_config_columns():
    row = B._to_history_row(_record())
    assert row["llm_backend"] == "deepinfra"
    assert row["llm_parse"] is True


def test_to_history_row_llm_parse_false_when_backend_none():
    row = B._to_history_row(_record(llm_config={"backend": "none", "model": None}))
    assert row["llm_backend"] == "none"
    assert row["llm_parse"] is False


def test_to_history_row_defaults_are_safe_for_pre_step4_records():
    # Old ledger rows predate parser_full/llm_config; the projection must not crash on them.
    row = B._to_history_row({"rehearsal": {"modes": {}, "ceiling": {}}, "parser": {}})
    assert row["parser_full_n"] == 0
    assert row["parser_full_precision"] == 0.0
    assert row["llm_backend"] == "none"
    assert row["llm_parse"] is False


# --- resolved model recording (2026-07-14, Copilot review on PR #15) ---------------------------
#
# llm_cfg["model"] is only set when TPC_P2_LLM_MODEL/config.toml explicitly overrides it; the
# deepinfra client silently falls back to DEFAULT_DEEPINFRA_MODEL when neither is set, so a
# real deepinfra run recorded "model": null even though it genuinely used a concrete model
# (Qwen/Qwen3.6-27B as of this writing) -- misleading for reproducibility/comparability. The
# already-constructed llm_client used for fingerprinting has the real resolved model on
# ``.model``; prefer that over the raw config.


class _FakeClientWithModel:
    model = "Qwen/Qwen3.6-27B"


class _FakeClientWithoutModel:
    pass  # e.g. NoneLLMClient / FixtureLLMClient: no .model attribute


def test_resolve_llm_model_prefers_clients_resolved_model_over_raw_config():
    assert B._resolve_llm_model({"model": None}, _FakeClientWithModel()) == "Qwen/Qwen3.6-27B"


def test_resolve_llm_model_falls_back_to_config_when_client_has_no_model_attr():
    assert B._resolve_llm_model({"model": "explicit-override"}, _FakeClientWithoutModel()) == (
        "explicit-override"
    )


def test_resolve_llm_model_none_when_neither_source_has_one():
    assert B._resolve_llm_model({}, _FakeClientWithoutModel()) is None


def test_full_val_parser_columns_present_in_csv_fieldnames(tmp_path):
    history_path = tmp_path / "history.jsonl"
    history_path.write_text("", encoding="utf-8")
    csv_path = tmp_path / "history.csv"
    B._write_history_csv(csv_path, [_record(run_id="r1")])
    header = csv_path.read_text(encoding="utf-8").splitlines()[0]
    for col in (
        "parser_full_n",
        "parser_full_precision",
        "parser_full_recall",
        "parser_full_f1",
        "parser_full_value_accuracy",
        "parser_full_disjunction_flattened",
        "parser_full_behavioral_agreement_rate",
        "llm_backend",
        "llm_parse",
    ):
        assert col in header


def _familiar_record_with_unavailable_ceiling():
    record = _record(
        run_id="familiar-run",
        split_set="familiar_100",
        split_name="tpc_phase2_familiar_100",
        n=100,
        rehearsal={
            "ceiling": {"fpr": 0.0, "quality": {"evaluated": 0}},
            "modes": {
                "solver-only": {
                    "fpr": 26.0,
                    "quality": {
                        "overall_true": {"mean": 48.0},
                        "overall_parsed": {"mean": 42.0},
                    },
                },
                "end-to-end": {
                    "fpr": 2.0,
                    "quality": {
                        "overall_true": {"mean": 36.0},
                        "overall_parsed": {"mean": 53.0},
                    },
                },
            },
        },
    )
    record["parser_full"] = {**record["parser_full"], "n": 100}
    return record


def test_unavailable_ceiling_does_not_project_negative_headroom():
    row = B._to_history_row(_familiar_record_with_unavailable_ceiling())
    assert row["ceiling_fpr"] is None
    assert row["solver_headroom"] is None
    assert row["ceiling_overall_true"] is None
    assert row["overall_true_solver_headroom"] is None
    assert row["ceiling_overall_parsed"] is None
    assert row["overall_parsed_solver_headroom"] is None
    assert row["parsing_loss"] == 24.0
    assert row["overall_true_parsing_loss"] == 12.0


def test_latest_summary_labels_unavailable_ceiling_and_actual_full_split(tmp_path):
    path = tmp_path / "latest.md"
    B._write_latest_md(path, _familiar_record_with_unavailable_ceiling())
    text = path.read_text(encoding="utf-8")
    assert "ceiling_fpr: unavailable (no evaluated ceiling plans for this data source)" in text
    assert "solver_headroom: unavailable" in text
    assert "parsing_loss: 24.0000" in text
    assert "full split: tpc_phase2_familiar_100, n=100" in text
