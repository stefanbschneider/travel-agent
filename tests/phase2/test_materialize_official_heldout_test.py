"""Unit tests for scripts/materialize_official_heldout_test.py.

Hermetic: exercises materialize()/parse_rows() against an in-memory CSV fixture. No network
access -- see docs/tpc_phase2_eval.md#r37--identity-check-the-published-held-out-test-set for the
one-off, real-network verification this script was built for.
"""

from __future__ import annotations

import json
import sys

import pytest

import materialize_official_heldout_test as moht

_SAMPLE_CSV = (
    "uid,tag,start_city,target_city,days,people_number,hard_logic_py,hard_logic_nl,"
    "nature_language,constraint_keys,official_phase2_evaluation\n"
    'e1,phase2,Shenzhen,Shanghai,2,1,"[""result=(day_count(plan)==2)""]",nl,'
    '"go to shanghai",keys,true\n'
    'e2,phase2,Beijing,Xian,1,2,"[""result=True""]",nl,"go to xian",keys,false\n'
)


def test_parse_rows_keeps_only_official_evaluation_true():
    rows = moht.parse_rows(_SAMPLE_CSV)
    assert [r["uid"] for r in rows] == ["e1"]


def test_materialize_writes_expected_schema(tmp_path):
    result = moht.materialize(_SAMPLE_CSV, "hf_smoke_official_test", project_root=tmp_path)

    assert result["name"] == "hf_smoke_official_test"
    assert result["n"] == 1

    written = json.loads(
        (tmp_path / "chinatravel" / "data" / "en" / "hf_smoke_official_test" / "e1.json")
        .read_text(encoding="utf-8")
    )
    assert written == {
        "uid": "e1",
        "nature_language": "go to shanghai",
        "start_city": "Shenzhen",
        "target_city": "Shanghai",
        "days": 2,
        "people_number": 1,
        "hard_logic_py": ["result=(day_count(plan)==2)"],
    }

    split_ids = (
        tmp_path / "chinatravel" / "evaluation" / "default_splits" / "hf_smoke_official_test.txt"
    ).read_text(encoding="utf-8").splitlines()
    assert split_ids == ["e1"]


def test_materialize_raises_when_nothing_is_flagged_official(tmp_path):
    csv_text = _SAMPLE_CSV.replace(",true\n", ",false\n")
    with pytest.raises(ValueError, match="official_phase2_evaluation"):
        moht.materialize(csv_text, "hf_smoke_official_test", project_root=tmp_path)


def test_cli_rejects_name_without_hf_prefix(monkeypatch):
    monkeypatch.setattr(
        sys, "argv",
        ["materialize_official_heldout_test.py", "--name", "bad_name", "--from-csv", "/dev/null"],
    )
    with pytest.raises(SystemExit, match="hf_"):
        moht.main()


def test_output_name_default_and_gitignore_coverage():
    """The default --name must actually be covered by the existing hf_* .gitignore rule -- this
    dataset's hard_logic_py is the real answer key and must never be committed."""
    assert moht.DEFAULT_NAME.startswith("hf_")
    gitignore = (moht.PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "chinatravel/data/en/hf_*/" in gitignore
    assert "chinatravel/evaluation/default_splits/hf_*.txt" in gitignore
