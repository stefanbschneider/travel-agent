"""Unit tests for the HF-vs-local dataset comparison core (Task 12).

The comparison logic is pure over lists of query dicts, so we test it on small in-memory fixtures
(no network / no datasets library). An opt-in integration test can load the real HF dataset.
"""

from __future__ import annotations

import compare_hf_dataset as C


LOCAL = [
    {"uid": "20250320000000000001", "start_city": "Shanghai", "target_city": "Chengdu",
     "days": 5, "people_number": 2, "hard_logic_py": ["result=True"], "nature_language_en": "x"},
    {"uid": "20250320000000000002", "start_city": "Beijing", "target_city": "Shanghai",
     "days": 3, "people_number": 4, "hard_logic_py": ["result=True"]},
]
HF = [
    {"uid": "e20241028000000000001", "start_city": "Guangzhou", "target_city": "Shenzhen",
     "days": 1, "people_number": 1, "hard_logic_py": "['result=True']", "nature_language_en": "y"},
    {"uid": "20250320000000000001", "start_city": "Shanghai", "target_city": "Chengdu",
     "days": 5, "people_number": 2, "hard_logic_py": "['result=True']"},
]


def test_uid_overlap_detected():
    rep = C.compare(LOCAL, HF)
    assert rep["local_n"] == 2
    assert rep["hf_n"] == 2
    assert rep["uid_overlap"] == 1
    assert "20250320000000000001" in rep["overlap_uids"]


def test_field_presence_counts():
    rep = C.compare(LOCAL, HF)
    assert rep["hf_field_presence"]["hard_logic_py"] == 2
    assert rep["hf_field_presence"]["nature_language_en"] == 1


def test_city_coverage_extra_in_hf():
    rep = C.compare(LOCAL, HF)
    # Shenzhen / Guangzhou appear only in HF.
    assert "Shenzhen" in rep["hf_only_target_cities"]
    assert "Guangzhou" in rep["hf_only_start_cities"]


def test_day_and_people_distributions():
    rep = C.compare(LOCAL, HF)
    assert rep["hf_days_distribution"].get(1) == 1
    assert rep["local_days_distribution"].get(5) == 1
    assert rep["hf_people_distribution"].get(1) == 1


def test_recommendation_field_present():
    rep = C.compare(LOCAL, HF)
    assert "usable_as_generalization_set" in rep
    assert isinstance(rep["usable_as_generalization_set"], bool)
