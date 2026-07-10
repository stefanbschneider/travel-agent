"""Unit tests for the full-val parser + llm-config ledger columns (Phase 2 plan Step 4).

Fold-scoped parser metrics can miss whatever a parser fix touched if the small seeded fold
doesn't happen to contain those uids (see roadmap-1c/step2: full-val behavioral agreement moved
0.706->0.757 while an n=20 fold row stayed flat). ``parser_full`` runs the same solver-free
diff over the entire val/test split so every ledger row carries the representative signal.
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
        "llm_config": {"backend": "infradeep", "model": "Qwen/Qwen3.6-27B"},
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


def test_to_history_row_projects_llm_config_columns():
    row = B._to_history_row(_record())
    assert row["llm_backend"] == "infradeep"
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
