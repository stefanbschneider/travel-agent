"""``llm_parse_mode="extract_fill"``: the LLM may fill an empty family, never overwrite a regex one.

Why this mode exists, measured 2026-08-06 over all 904 released English queries
(``results/phase2_baselines/screens/20260806_llm_arms/README.md``): LLM-first extraction closes
40-65 % of the deterministic parse gaps on every differently-phrased released set and breaks none,
but its family *values* are less accurate than the regex's. Overwriting therefore costs precision
everywhere and is strictly harmful on ``tpc_phase2_familiar_100``, where the regex is already
perfect. Fill-only keeps the recall gain where the regex is silent and the regex's value where it is
not.

These tests use a scripted client, so they are offline and make no network call.
"""

from __future__ import annotations

from chinatravel.agent.phase2 import normalize as N
from chinatravel.agent.phase2.orchestrator import Flags


class ScriptedClient:
    """Returns one canned extract-mode payload, and records that it was asked."""

    timeout = 30.0

    def __init__(self, response: str):
        self.response = response
        self.calls = 0

    def complete(self, prompt: str, *, system=None, cache_key=None) -> str:
        self.calls += 1
        return self.response


QUERY = {
    "uid": "t1",
    "start_city": "Shanghai",
    "target_city": "Beijing",
    "days": 2,
    "people_number": 2,
    # The regex extracts budgets={"total": 6000} and room_type="single" from this text.
    "nature_language": "We are 2 people going to Beijing for 2 days with a budget of 6000 RMB "
                       "and want to book a single-bed room.",
}


def _ir(mode: str, response: str):
    client = ScriptedClient(response)
    flags = Flags(llm_parse=True, llm_parse_mode=mode)
    ir = N.parse_to_ir(dict(QUERY), llm_client=client, flags=flags)
    assert client.calls == 1, "the LLM must actually have been asked"
    assert not getattr(ir, "llm_parse_error", None), getattr(ir, "llm_parse_error", None)
    return ir


DISAGREEING = ('{"families": {"budgets": {"total": 9999}, "room_type": "twin", '
               '"required_attractions": ["Forbidden City"]}, "or_arms": []}')


def test_deterministic_baseline_extracts_budget_and_room_type():
    ir = N.parse_to_ir(dict(QUERY), llm_client=None, flags=Flags())
    assert ir.raw["budgets"] == {"total": 6000.0}
    assert ir.raw["room_type"] == "single"


def test_extract_mode_overwrites_the_regex_value():
    ir = _ir("extract", DISAGREEING)
    assert ir.raw["budgets"]["total"] == 9999
    assert ir.raw["room_type"] == "twin"


def test_extract_fill_keeps_the_regex_value_where_the_regex_spoke():
    ir = _ir("extract_fill", DISAGREEING)
    assert ir.raw["budgets"]["total"] == 6000.0
    assert ir.raw["room_type"] == "single"


def test_extract_fill_still_adds_a_family_the_regex_missed():
    ir = _ir("extract_fill", DISAGREEING)
    # This is the whole point: the recall gain survives, only the overwrite is forbidden.
    assert ir.raw.get("required_attractions") == ["Forbidden City"]


def test_extract_fill_adds_a_missing_budget_sub_key_but_not_an_existing_one():
    ir = _ir("extract_fill",
             '{"families": {"budgets": {"total": 1, "accommodation": 800}}, "or_arms": []}')
    assert ir.raw["budgets"]["total"] == 6000.0      # regex value survives
    assert ir.raw["budgets"]["accommodation"] == 800  # empty sub-key filled


def test_unknown_mode_falls_back_to_audit_not_to_extract():
    # Flags.from_env already clamps the vocabulary; parse_to_ir must not treat an unexpected value
    # as "extract" and start overwriting.
    client = ScriptedClient('{"patches": [], "or_arms": [], "field_alternatives": {}, '
                            '"field_confidence": {}}')
    ir = N.parse_to_ir(dict(QUERY), llm_client=client,
                       flags=Flags(llm_parse=True, llm_parse_mode="bogus"))
    assert client.calls == 1
    assert ir.raw["budgets"] == {"total": 6000.0}


def test_flags_from_env_accepts_extract_fill_and_still_defaults_to_audit():
    assert Flags.from_env({"TPC_P2_LLM_PARSE_MODE": "extract_fill"}).llm_parse_mode == "extract_fill"
    assert Flags.from_env({}).llm_parse_mode == "audit"
    assert Flags.from_env({}).llm_parse is False  # library default: zero LLM calls
