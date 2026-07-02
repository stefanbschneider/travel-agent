#!/usr/bin/env python
"""Self-contained tests for the LLM preference optimizer helpers."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "chinatravel")):
    if p not in sys.path:
        sys.path.insert(0, p)

import scripts.llm_pref_optimize as L


def test_parse_llm_choice_filters_invalid_ids():
    raw = '{"candidate_ids":["x","b","a"]}'
    assert L._parse_llm_choice(raw, ["a", "b"]) == ["b", "a"]


def test_parse_llm_choice_rejects_bad_json():
    assert L._parse_llm_choice("not json", ["a", "b"]) == []


def test_choose_candidate_falls_back_to_best_delta():
    class FakeLLM:
        def __call__(self, messages, one_line=True, json_mode=False):
            return "not json"

    low = L.Candidate(
        id="low",
        lever="att",
        description="smaller gain",
        before=(0.0, 0.0, 0.0),
        after=(0.1, 0.0, 0.0),
        plan={"id": "low"},
    )
    high = L.Candidate(
        id="high",
        lever="att",
        description="larger gain",
        before=(0.0, 0.0, 0.0),
        after=(0.2, 0.0, 0.0),
        plan={"id": "high"},
    )
    selected = L._choose_candidate(FakeLLM(), "uid", {"nature_language": ""}, {}, [low, high])
    assert selected.id == "high", selected


def main():
    tests = [
        test_parse_llm_choice_filters_invalid_ids,
        test_parse_llm_choice_rejects_bad_json,
        test_choose_candidate_falls_back_to_best_delta,
    ]
    failures = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception as e:
            failures += 1
            print(f"FAIL {t.__name__}: {e}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
