"""Phase C: acceptance-gate OR-awareness tests.

The agent accepts a plan that satisfies ANY disjunction branch (TPCAgent._solve keeps the best
plan across variants). The behavioral-equivalence metric must reflect that: with disjunction on,
``behavioral_check`` accepts if any expanded variant passes, instead of ANDing OR-arm constraints.
"""

from __future__ import annotations

import pytest

import parser_vs_oracle as pvo


def test_behavioral_check_or_semantics(monkeypatch):
    """Flat check ANDs both arms (fails); disjunction-aware OR accepts because arm B passes."""
    query = {"uid": "t", "target_city": "Nanjing", "hard_logic_py": ["result=True"]}

    # Two branch variants with distinct keys so the flattened dict is neither arm.
    variant_a = {"required_attractions": ["X"]}
    variant_b = {"excluded_attractions": ["Y"]}

    def fake_query_variants(q, *, disjunction=False, llm_parse=False, llm_client=None, entity_resolution=False):
        parsed = [variant_a, variant_b] if disjunction else [{**variant_a, **variant_b}]
        return parsed, [variant_a, variant_b]

    monkeypatch.setattr(pvo, "query_variants", fake_query_variants)

    import chinatravel.agent.tpc_agent.parsed_verifier as pv
    import chinatravel.symbol_verification.hard_constraint as hc

    # The plan satisfies arm B only (exact match to variant_b).
    def fake_eval_parsed(constraints, plan, target_city):
        return [constraints == variant_b]

    monkeypatch.setattr(pv, "evaluate_parsed_constraints", fake_eval_parsed)
    monkeypatch.setattr(hc, "evaluate_constraints_py", lambda *a, **k: [True])  # oracle accepts

    flat = pvo.behavioral_check(query, {"itinerary": []}, disjunction=False)
    disj = pvo.behavioral_check(query, {"itinerary": []}, disjunction=True)

    assert flat["parsed_pass"] is False and flat["agree"] is False
    assert disj["parsed_pass"] is True and disj["agree"] is True


@pytest.mark.integration
def test_or_behavioral_agreement_beats_flat_on_val(tmp_path):
    """On the val split, disjunction-aware behavioral agreement must be >= the flat metric."""
    flat = pvo.run_report("tpc_phase2_val", limit=120, behavioral=True, out_dir=str(tmp_path))
    disj = pvo.run_report("tpc_phase2_val", limit=120, behavioral=True, disjunction=True,
                          out_dir=str(tmp_path / "d"))
    assert disj["behavioral"]["agreement_rate"] >= flat["behavioral"]["agreement_rate"]
