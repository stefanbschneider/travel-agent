"""Unit tests for scripts/phase2_oracle_literal_translation.py (P23).

Two things are tested: (1) the zh->en map derivation raises on ambiguity rather than guessing --
the module's core safety property -- using a hermetic fake database pair, never the real one; (2)
the literal-level rewrite (`translate_clause` / `translate_hard_logic`) that
`materialize_hf_split.py --translate-oracle-literals` applies, exercised against the real,
committed map (fast: no network, no HF cache, just the row-parallel CSVs already on disk).
"""

from __future__ import annotations

import pandas as pd
import pytest

import phase2_oracle_literal_translation as polt


# --- build_map: ambiguity must raise, never guess -----------------------------------------------


def _write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)


def test_build_map_raises_on_ambiguous_translation(monkeypatch, tmp_path):
    """Two cities disagree on the English value for the same Chinese literal -> refuse to guess."""
    base = tmp_path / "chinatravel" / "environment"
    _write_csv(base / "database" / "attractions" / "a" / "attractions.csv",
               {"type": ["博物馆"], "name": ["x"]})
    _write_csv(base / "database_en" / "attractions" / "a" / "attractions.csv",
               {"type": ["Museum"], "name": ["X"]})
    _write_csv(base / "database" / "attractions" / "b" / "attractions.csv",
               {"type": ["博物馆"], "name": ["y"]})
    _write_csv(base / "database_en" / "attractions" / "b" / "attractions.csv",
               {"type": ["Gallery"], "name": ["Y"]})  # conflicts with city a's "Museum"

    monkeypatch.setattr(polt, "REPO_ROOT", tmp_path)
    with pytest.raises(ValueError, match="ambiguous"):
        polt.build_map()


def test_build_map_raises_on_row_count_mismatch(monkeypatch, tmp_path):
    base = tmp_path / "chinatravel" / "environment"
    _write_csv(base / "database" / "attractions" / "a" / "attractions.csv",
               {"type": ["博物馆", "公园"], "name": ["x", "y"]})
    _write_csv(base / "database_en" / "attractions" / "a" / "attractions.csv",
               {"type": ["Museum"], "name": ["X"]})  # one row short -> not row-parallel

    monkeypatch.setattr(polt, "REPO_ROOT", tmp_path)
    with pytest.raises(ValueError, match="row counts differ"):
        polt.build_map()


def test_build_map_on_real_data_is_large_and_unambiguous():
    """Regression tripwire: the real committed databases stay row-parallel and 1:1. If this ever
    fails, the translation's premise has drifted and needs re-diagnosing, not silencing."""
    mapping, meta = polt.build_map()
    assert meta["entries"] > 10_000
    assert len(mapping) == meta["entries"]
    # Spot-check a couple of stable, well-known category translations.
    assert mapping.get("博物馆") == "Museum"


# --- translate_clause / translate_hard_logic -----------------------------------------------------


def test_translate_clause_rewrites_fully_mapped_literal():
    mapping = {"博物馆": "Museum"}
    new_clause, unmapped = polt.translate_clause("'博物馆' in attraction_type(x)", mapping)
    assert new_clause == "'Museum' in attraction_type(x)"
    assert unmapped == []


def test_translate_clause_leaves_partially_mapped_literal_untouched_and_reports_it():
    """A POI-name fragment (branch suffix) must not be guessed at -- left verbatim, reported."""
    mapping = {"天安门": "Tiananmen"}  # "前门店" (branch suffix) has no map entry
    original = "'天安门前门店' in attraction_name_set"
    new_clause, unmapped = polt.translate_clause(original, mapping)
    assert new_clause == original
    assert unmapped == ["天安门前门店"]


def test_translate_clause_ignores_non_cjk_literals():
    mapping = {"博物馆": "Museum"}
    original = "'Beijing' in city_name(x)"
    new_clause, unmapped = polt.translate_clause(original, mapping)
    assert new_clause == original
    assert unmapped == []


def test_translate_clause_only_touches_string_literals_not_code():
    """A CJK run must never be introduced or removed outside a quoted literal."""
    mapping = {"博物馆": "Museum"}
    # Deliberately contrived: identifier-shaped text is not a string literal and must pass through.
    original = "result=(len(allactivities(plan))==1)"
    new_clause, unmapped = polt.translate_clause(original, mapping)
    assert new_clause == original
    assert unmapped == []


def test_translate_hard_logic_aggregates_across_clauses_and_dedupes_unmapped():
    mapping = {"博物馆": "Museum"}
    clauses = [
        "'博物馆' in attraction_type(x)",
        "'公园' in attraction_type(y)",  # unmapped in this tiny fixture map
        "'公园' in attraction_type(z)",  # same unmapped run again -> deduped in the report
        "result=(day_count(plan)==1)",  # no CJK at all -> unchanged, not counted as "changed"
    ]
    result = polt.translate_hard_logic(clauses, mapping)
    assert result["clauses"][0] == "'Museum' in attraction_type(x)"
    assert result["clauses"][1] == clauses[1]
    assert result["clauses"][3] == clauses[3]
    assert result["changed"] == 1
    assert result["unmapped"] == ["公园"]


def test_translate_hard_logic_on_real_map_matches_the_known_medium_split_shape():
    """End-to-end against the real map and a hand-picked real clause shape (not the HF cache --
    this is the exact literal the roadmap's residual example names, so it must stay unmapped)."""
    mapping, _ = polt.build_map()
    result = polt.translate_hard_logic(
        ["'博物馆' in attraction_type(x)", "'前门店' in attraction_name_set"], mapping)
    assert result["clauses"][0] == "'Museum' in attraction_type(x)"
    assert result["clauses"][1] == "'前门店' in attraction_name_set"  # fragment, no catalog row
    assert result["changed"] == 1
    assert "前门店" in result["unmapped"]
