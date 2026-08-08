"""Unit tests for scripts/materialize_hf_split.py, focused on the P23
``--translate-oracle-literals`` pass (the untranslated path is exercised implicitly by every
e2e screen that already relies on this script; see docs/tpc_phase2_roadmap.md#p23).

Uses the same ``datasets.load_dataset`` monkeypatch shape as
``tests/phase2/test_parser_vs_oracle.py`` so these run hermetically -- no network, no HF cache
dependency -- while still exercising the *real*, committed zh->en map (fast: local CSVs only).
"""

from __future__ import annotations

import json

import pytest

import materialize_hf_split as mhs


class _FakeSplit:
    def __init__(self, rows):
        self._rows = rows

    def to_list(self):
        return self._rows


def _fake_dataset(rows):
    return {"medium": _FakeSplit(rows)}


# --- naming enforcement: must fail before touching any data --------------------------------------


def test_translate_oracle_literals_requires_en_oracle_suffix(monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("must not reach the dataset loader before the name check")

    monkeypatch.setattr("datasets.load_dataset", _boom)
    with pytest.raises(ValueError, match="_en_oracle"):
        mhs.materialize("medium", "hf_medium_bad_name", translate_oracle_literals=True)


def test_translate_oracle_literals_accepts_correctly_suffixed_name(monkeypatch, tmp_path):
    monkeypatch.setattr("datasets.load_dataset", lambda path, **kw: _fake_dataset([
        {
            "uid": "e1", "start_city": "上海", "target_city": "北京", "days": 1,
            "people_number": 1, "nature_language_en": "text",
            "hard_logic_py": "[\"result=(day_count(plan)==1)\"]",
        },
    ]))
    result = mhs.materialize("medium", "hf_smoke_en_oracle", project_root=tmp_path,
                              translate_oracle_literals=True)
    assert result["name"] == "hf_smoke_en_oracle"
    assert "translation_report" in result


def test_non_translated_path_does_not_require_the_suffix(monkeypatch, tmp_path):
    monkeypatch.setattr("datasets.load_dataset", lambda path, **kw: _fake_dataset([
        {
            "uid": "e1", "start_city": "上海", "target_city": "北京", "days": 1,
            "people_number": 1, "nature_language_en": "text", "hard_logic_py": "[]",
        },
    ]))
    result = mhs.materialize("medium", "hf_medium_probe30", project_root=tmp_path)
    assert result["name"] == "hf_medium_probe30"
    assert "translation_report" not in result


# --- end-to-end translation pass, hermetic dataset, real map -------------------------------------


def test_translate_oracle_literals_rewrites_and_reports(monkeypatch, tmp_path):
    monkeypatch.setattr("datasets.load_dataset", lambda path, **kw: _fake_dataset([
        {
            "uid": "e1", "start_city": "上海", "target_city": "北京", "days": 1,
            "people_number": 1, "nature_language_en": "Visit a museum in Beijing.",
            # one fully-mappable clause, one with an unmappable POI-name-fragment literal, one
            # with no CJK at all.
            "hard_logic_py": json.dumps([
                "'博物馆' in attraction_type(x)",
                "'前门店' in attraction_name_set",
                "result=(day_count(plan)==1)",
            ]),
        },
    ]))

    result = mhs.materialize("medium", "hf_smoke_en_oracle", project_root=tmp_path,
                              translate_oracle_literals=True)

    report = result["translation_report"]
    assert report["map_entries"] > 10_000
    assert report["queries_changed"] == 1
    assert report["clauses_changed"] == 1
    assert report["queries_with_unmapped_residual"] == 1
    assert report["unmapped_residual_samples"]["e1"] == ["前门店"]

    written = json.loads((tmp_path / "chinatravel" / "data" / "en" /
                          "hf_smoke_en_oracle" / "e1.json").read_text(encoding="utf-8"))
    assert written["hard_logic_py"] == [
        "'Museum' in attraction_type(x)",
        "'前门店' in attraction_name_set",
        "result=(day_count(plan)==1)",
    ]


def test_translate_oracle_literals_output_is_gitignored():
    """The forced `_en_oracle` suffix must be covered by .gitignore -- belt and braces on top of
    the "delete after scoring" rule, since a translated split must never ship."""
    gitignore = (mhs.PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "_en_oracle" in gitignore
