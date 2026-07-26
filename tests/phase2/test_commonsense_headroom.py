"""Unit tests for the commonsense-first headroom diagnostic (scripts/).

The projection reproduces how ``evaluate_hard_constraints_v2`` scores C-LPR: the conditional
numerator only counts clauses of commonsense-passing queries while the denominator stays the full
batch clause count, so flipping every commonsense verdict to pass lifts C-LPR exactly to the
unconditional ``logical_micro``.
"""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "phase2_commonsense_headroom",
    PROJECT_ROOT / "scripts" / "phase2_commonsense_headroom.py",
)
headroom = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(headroom)


def _commonsense_row(uid: str, **failed):
    row = {
        "data_id": uid,
        "Invalid or ungrounded activity entity": 0,
        "Invalid Transport information across positions": 0,
        "Does not follow Chronological Order": 0,
    }
    row.update(failed)
    return row


# --- logical_counts --------------------------------------------------------------------------


def test_logical_counts_ignores_nan_padding():
    row = {"data_id": "u1", "logic_py_0": 1, "logic_py_1": 0, "logic_py_2": float("nan")}
    assert headroom.logical_counts(row) == (1, 2)


def test_logical_counts_empty_row_is_zero():
    assert headroom.logical_counts({}) == (0, 0)


def test_failed_commonsense_columns_lists_only_failures():
    row = _commonsense_row("u1", **{"Invalid Transport information across positions": 1})
    assert headroom.failed_commonsense_columns(row) == [
        "Invalid Transport information across positions"
    ]
    assert headroom.failed_commonsense_columns(_commonsense_row("u2")) == []


# --- projection ------------------------------------------------------------------------------


def _raw_two_uids():
    """Two queries, 4 clauses each. u1 passes commonsense (3/4 clauses), u2 fails it (2/4).

    micro = (3 + 2) / 8 = 62.5; conditional micro counts u1 only = 3 / 8 = 37.5; macro EPR = 50.
    """
    return {
        "commonsense_micro": 90.0,
        "commonsense_macro": 50.0,
        "commonsense_pass_count": 1,
        "logical_micro": 62.5,
        "conditional_logical_micro": 37.5,
        "all_pass_count": 0,
        "commonsense_details": [
            _commonsense_row("u1"),
            _commonsense_row("u2", **{"Does not follow Chronological Order": 1}),
        ],
        "logical_details": [
            {"data_id": "u1", "logic_py_0": 1, "logic_py_1": 1, "logic_py_2": 1, "logic_py_3": 0},
            {"data_id": "u2", "logic_py_0": 1, "logic_py_1": 1, "logic_py_2": 0, "logic_py_3": 0},
        ],
    }


def test_projection_lifts_clpr_to_unconditional_logical_micro():
    projection = headroom.project_commonsense_first(_raw_two_uids())

    assert projection["n"] == 2
    assert projection["projected"]["clpr"] == 62.5
    assert projection["observed"]["clpr"] == 37.5
    # 0.25 * (62.5 - 37.5) = 6.25 overall points from C-LPR alone.
    assert math.isclose(projection["delta_overall"]["clpr"], 6.25)
    # 0.10 * (100 - 50) = 5.0 from EPR-macro, 0.10 * (100 - 90) = 1.0 from EPR-micro.
    assert math.isclose(projection["delta_overall"]["mac_epr"], 5.0)
    assert math.isclose(projection["delta_overall"]["mic_epr"], 1.0)
    assert math.isclose(projection["delta_overall"]["total"], 12.25)
    assert math.isclose(projection["delta_overall"]["total_conservative_mic_epr_held"], 11.25)


def test_projection_reports_failing_uid_with_logic_fraction():
    projection = headroom.project_commonsense_first(_raw_two_uids())

    assert [item["uid"] for item in projection["failing"]] == ["u2"]
    failing = projection["failing"][0]
    assert failing["logic_passed"] == 2
    assert failing["logic_applicable"] == 4
    assert math.isclose(failing["logic_fraction"], 0.5)
    assert failing["failed_columns"] == ["Does not follow Chronological Order"]


def test_projection_is_zero_when_every_plan_already_passes():
    raw = _raw_two_uids()
    raw["commonsense_details"] = [_commonsense_row("u1"), _commonsense_row("u2")]
    raw["commonsense_micro"] = 100.0
    raw["commonsense_macro"] = 100.0
    raw["conditional_logical_micro"] = raw["logical_micro"]

    projection = headroom.project_commonsense_first(raw)

    assert projection["failing"] == []
    assert math.isclose(projection["delta_overall"]["total"], 0.0)


# --- preference formulas ---------------------------------------------------------------------


def test_preference_scores_match_eval_tpc_formulas():
    plan = {
        "itinerary": [
            {
                "activities": [
                    {"type": "breakfast", "transports": []},
                    {
                        "type": "attraction",
                        "transports": [{"start_time": "09:00", "end_time": "09:10"}],
                    },
                    {
                        "type": "lunch",
                        "transports": [{"start_time": "12:00", "end_time": "12:20"}],
                    },
                ]
            }
        ]
    }

    scores = headroom.preference_scores(plan)

    # 1 attraction over 1 day -> DAV = 1/4; 2 meals over 1 day -> DDR = (2/1)/3.
    assert math.isclose(scores["dav"], 0.25)
    assert math.isclose(scores["ddr"], 2.0 / 3.0)
    # Two activities carry transport, mean leg = (10 + 20) / 2 = 15 min -> ATT = -15/105 + 8/7 = 1.0.
    assert math.isclose(scores["att"], 1.0)


def test_preference_scores_none_for_empty_plan():
    assert headroom.preference_scores({}) is None
    assert headroom.preference_scores({"itinerary": []}) is None
