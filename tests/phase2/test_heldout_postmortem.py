"""Tests for the held-out postmortem's clause-shape key mapping (scripts/phase2_heldout_postmortem.py).

R38's distribution comparison maps each familiar-100 clause to one of the organizers' 53 template
keys by code shape. The mapping must abstract entity and number literals, yet keep activity-type
literals, or attraction and accommodation time windows (identical code apart from that literal)
would collapse into one key.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import phase2_heldout_postmortem as pm  # noqa: E402

_WINDOW = (
    "result=False\nfor activity in allactivities(plan):\n"
    "  if activity_type(activity)=='{kind}' and activity_position(activity)==\"{name}\":\n"
    "    if activity_start_time(activity)>=\"{a}\" and activity_end_time(activity)<=\"{b}\": result=True"
)


def test_shape_abstracts_names_and_numbers():
    one = _WINDOW.format(kind="attraction", name="West Lake", a="09:00", b="11:00")
    two = _WINDOW.format(kind="attraction", name="Canton Tower", a="13:15", b="14:40")
    assert pm.clause_shape(one) == pm.clause_shape(two)


def test_shape_keeps_activity_type_literal():
    attraction = _WINDOW.format(kind="attraction", name="West Lake", a="09:00", b="11:00")
    hotel = _WINDOW.format(kind="accommodation", name="Baiye Homestay", a="21:00", b="24:00")
    assert pm.clause_shape(attraction) != pm.clause_shape(hotel)


def test_shape_to_key_majority_vote():
    rows = [
        {"hard_logic_py": [_WINDOW.format(kind="attraction", name=n, a="09:00", b="10:00")],
         "constraint_keys": ["attraction_time_window"]}
        for n in ("A", "B")
    ] + [
        {"hard_logic_py": [_WINDOW.format(kind="accommodation", name="H", a="21:00", b="24:00")],
         "constraint_keys": ["accommodation_time_window"]}
    ]
    mapping = pm.shape_to_key(rows)
    probe = _WINDOW.format(kind="attraction", name="Z", a="08:00", b="09:30")
    assert mapping[pm.clause_shape(probe)] == "attraction_time_window"
    assert len(set(mapping.values())) == 2
