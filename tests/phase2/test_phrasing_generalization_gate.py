"""P18 -- the standing phrasing-generalization tripwire, as an executable gate.

R22 (docs/tpc_phase2_eval.md#r22--the-standing-phrasing-tripwire-open-2-min-run-with-every-parser-change)
used to be "run the probe and read the table by eye". This is that habit turned into a check:
``scripts/phase2_generalization_probe.py --check-floor`` compares a fresh run against
``results/phase2_baselines/phrasing_generalization_floor.json`` and fails when familiar-100 parse
gaps rise above their pinned ``0`` or any free-prose set's parse-gap clause count rises above its
recorded floor. See docs/tpc_phase2_roadmap.md#p18--make-phrasing-robustness-a-gate.

Two tiers here:

1. Fast, synthetic, no HF dependency -- runs in the default suite, and is the reason this gate is
   trustworthy even when tier 2 is skipped: it proves ``check_floor``/``write_floor`` actually fire
   on a regression, hold at the exact floor, skip (not fail) on a dataset-snapshot mismatch, and
   that ``--update-floor`` can only ratchet a set's recorded floor down, never up.
2. The real end-to-end gate over ``DEFAULT_SETS``, needing the local HF dataset cache
   (``LAMDA-NeSy/ChinaTravel``). Skips cleanly, not failing, when that cache is unavailable, and
   says which condition it skipped on -- required by P18's acceptance criteria.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Must be set before anything imports ``datasets``/``huggingface_hub`` -- they snapshot this into a
# module constant at import time, so setting it later (e.g. inside a fixture) is a no-op once some
# earlier-collected test module has already imported the library this session.
os.environ.setdefault("HF_HUB_OFFLINE", "1")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(PROJECT_ROOT), str(PROJECT_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

probe = pytest.importorskip("phase2_generalization_probe")

FLOOR_PATH = PROJECT_ROOT / "results" / "phase2_baselines" / "phrasing_generalization_floor.json"


def _set(label: str, name: str, n_parse_gap: int, n_oracle_clauses: int) -> dict:
    return {"label": label, "source": {"kind": "test", "name": name},
            "clause_coverage": {"n_parse_gap": n_parse_gap, "n_oracle_clauses": n_oracle_clauses}}


# --- 1. Fast, synthetic: does the gate actually fire? -----------------------


def test_check_floor_flags_a_regression():
    report = {"sets": [_set("hf_easy", "easy", 120, 1579)]}
    floor = {"easy": {"n_parse_gap": 97, "n_oracle_clauses": 1579}}
    violations, skipped = probe.check_floor(report, floor)
    assert not skipped
    assert len(violations) == 1
    assert "97 -> 120" in violations[0]


def test_check_floor_passes_exactly_at_the_recorded_floor():
    report = {"sets": [_set("hf_easy", "easy", 97, 1579)]}
    floor = {"easy": {"n_parse_gap": 97, "n_oracle_clauses": 1579}}
    violations, skipped = probe.check_floor(report, floor)
    assert violations == [] and skipped == []


def test_check_floor_passes_when_a_set_improves():
    report = {"sets": [_set("hf_easy", "easy", 50, 1579)]}
    floor = {"easy": {"n_parse_gap": 97, "n_oracle_clauses": 1579}}
    violations, skipped = probe.check_floor(report, floor)
    assert violations == [] and skipped == []


def test_check_floor_skips_not_fails_on_snapshot_drift():
    """If the dataset's own clause count moved, the gap counts aren't comparable -- this must be a
    skip, not a violation, or a routine cache refresh would red-line the gate for no code reason."""
    report = {"sets": [_set("hf_easy", "easy", 500, 1600)]}
    floor = {"easy": {"n_parse_gap": 97, "n_oracle_clauses": 1579}}
    violations, skipped = probe.check_floor(report, floor)
    assert violations == []
    assert len(skipped) == 1 and "1579 -> 1600" in skipped[0]


def test_check_floor_flags_structural_mismatch_both_directions():
    report = {"sets": [_set("hf_easy", "easy", 10, 1579), _set("hf_medium", "medium", 10, 1264)]}
    floor = {"easy": {"n_parse_gap": 97, "n_oracle_clauses": 1579},
             "human": {"n_parse_gap": 81, "n_oracle_clauses": 687}}
    violations, _skipped = probe.check_floor(report, floor)
    joined = "\n".join(violations)
    assert "medium" in joined and "no floor entry" in joined
    assert "human" in joined and "not measured" in joined


def test_familiar_100_control_floor_is_pinned_at_zero():
    """The control set's floor must never move off 0 -- raising it would hide a real regression on
    the one set we should be perfect on."""
    floor = probe.load_floor(FLOOR_PATH)
    entry = floor["tpc_phase2_familiar_100"]
    n_parse_gap = entry["n_parse_gap"] if isinstance(entry, dict) else entry
    assert n_parse_gap == 0


def test_write_floor_ratchets_down_only(tmp_path):
    existing = {"easy": {"n_parse_gap": 50, "n_oracle_clauses": 1579}}
    out = tmp_path / "floor.json"

    # Improvement: 30 < 50 -> floor drops to 30.
    improved_report = {"sets": [_set("hf_easy", "easy", 30, 1579)]}
    doc = probe.write_floor(improved_report, out, existing=existing)
    assert doc["floor"]["easy"]["n_parse_gap"] == 30

    # Regression relative to the *original* 50: --update-floor must keep 50, not adopt 80.
    regressed_report = {"sets": [_set("hf_easy", "easy", 80, 1579)]}
    doc = probe.write_floor(regressed_report, out, existing=existing)
    assert doc["floor"]["easy"]["n_parse_gap"] == 50, (
        "write_floor must never raise a recorded floor -- that would let --update-floor launder "
        "a regression"
    )


def test_write_floor_resets_on_snapshot_drift(tmp_path):
    """A clause-count change means the old recorded gap isn't comparable, so a fresh baseline is
    adopted outright rather than ratcheted against a stale number."""
    existing = {"easy": {"n_parse_gap": 50, "n_oracle_clauses": 1579}}
    out = tmp_path / "floor.json"
    drifted_report = {"sets": [_set("hf_easy", "easy", 200, 1600)]}
    doc = probe.write_floor(drifted_report, out, existing=existing)
    assert doc["floor"]["easy"] == {"n_parse_gap": 200, "n_oracle_clauses": 1600}


# --- 2. The real gate: needs the local HF dataset cache ---------------------


@pytest.fixture(scope="module")
def full_report():
    try:
        return {"sets": [probe.measure_set(label, kind, name)
                         for label, kind, name in probe.DEFAULT_SETS]}
    except Exception as exc:  # local HF cache absent / unreachable -- skip, do not fail
        pytest.skip(
            "local HF dataset cache (LAMDA-NeSy/ChinaTravel) unavailable, skipping the "
            f"phrasing-generalization gate: {exc!r}"
        )


def test_floor_file_exists():
    assert FLOOR_PATH.exists(), f"missing gate floor: {FLOOR_PATH}"


def test_no_default_set_regresses_past_its_recorded_floor(full_report):
    floor = probe.load_floor(FLOOR_PATH)
    violations, skipped = probe.check_floor(full_report, floor)
    for msg in skipped:
        print(f"[phrasing gate] SKIPPED (snapshot drift): {msg}")
    assert not violations, (
        "phrasing generalization gate regressed (docs/tpc_phase2_roadmap.md#p18):\n"
        + "\n".join(violations)
    )
