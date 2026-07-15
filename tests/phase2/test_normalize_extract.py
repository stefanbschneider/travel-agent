"""Unit tests for LLM-first structured extraction.

Fixture-backend driven: no real network, no WorldEnv, no solver. Vocabulary-dependent tests use a
small fixed vocab (monkeypatched) rather than the real CSV-derived one, so they don't depend on
the committed data's exact contents.
"""

from __future__ import annotations

from chinatravel.agent.phase2 import normalize
from chinatravel.agent.phase2.orchestrator import Flags
from chinatravel.agent.phase2.schema import ParsedIR


_VOCAB = {
    "cuisine": frozenset({"hot pot", "japanese cuisine", "beijing cuisine"}),
    "hotel_feature": frozenset({"hot spring bathing", "family room"}),
    "room_type": frozenset({"single", "double", "twin"}),
}


class _FakeLLM:
    def __init__(self, response: str):
        self.response = response
        self.calls = []

    def complete(self, prompt, *, system=None, cache_key=None):
        self.calls.append({"prompt": prompt, "cache_key": cache_key})
        return self.response


# --- Flags.from_env: llm_parse_mode -----------------------------------------


def test_flags_from_env_default_mode_is_audit():
    flags = Flags.from_env({})
    assert flags.llm_parse_mode == "audit"


def test_flags_from_env_reads_extract_mode():
    flags = Flags.from_env({"TPC_P2_LLM_PARSE_MODE": "extract"})
    assert flags.llm_parse_mode == "extract"


def test_flags_from_env_unknown_mode_falls_back_to_audit():
    flags = Flags.from_env({"TPC_P2_LLM_PARSE_MODE": "bogus"})
    assert flags.llm_parse_mode == "audit"


def test_flags_from_env_mode_is_case_insensitive():
    flags = Flags.from_env({"TPC_P2_LLM_PARSE_MODE": "EXTRACT"})
    assert flags.llm_parse_mode == "extract"


# --- _validate_extract_field / validate_extract_families --------------------


def test_validate_room_type_accepts_known_value():
    assert normalize._validate_extract_field("room_type", "Twin", _VOCAB) == "twin"


def test_validate_room_type_rejects_unknown_value():
    assert normalize._validate_extract_field("room_type", "queen", _VOCAB) is None


def test_validate_room_type_rejects_non_string():
    assert normalize._validate_extract_field("room_type", ["twin"], _VOCAB) is None


def test_validate_cuisine_preference_keeps_only_vocab_hits_case_insensitive():
    out = normalize._validate_extract_field(
        "cuisine_preference", ["Hot Pot", "Nonsense Cuisine", "japanese cuisine"], _VOCAB
    )
    assert out == ["Hot Pot", "japanese cuisine"]


def test_validate_cuisine_preference_all_invalid_is_none():
    out = normalize._validate_extract_field("cuisine_preference", ["Nonsense"], _VOCAB)
    assert out is None


def test_validate_excluded_cuisine_types_same_vocab_as_preference():
    out = normalize._validate_extract_field("excluded_cuisine_types", ["Beijing cuisine"], _VOCAB)
    assert out == ["Beijing cuisine"]


def test_validate_hotel_feature_field_checks_hotel_vocab_not_cuisine_vocab():
    out = normalize._validate_extract_field(
        "required_hotel_any_types", ["Hot spring bathing", "Hot pot"], _VOCAB
    )
    assert out == ["Hot spring bathing"]  # "Hot pot" is a cuisine, not a hotel feature


def test_validate_free_attractions_only_bool_passthrough():
    assert normalize._validate_extract_field("free_attractions_only", True, _VOCAB) is True
    assert normalize._validate_extract_field("free_attractions_only", "true", _VOCAB) is None


def test_validate_budgets_dict_passthrough():
    assert normalize._validate_extract_field("budgets", {"total": 3000}, _VOCAB) == {"total": 3000}


def test_validate_budgets_rejects_non_dict_and_empty_dict():
    assert normalize._validate_extract_field("budgets", "3000", _VOCAB) is None
    assert normalize._validate_extract_field("budgets", {}, _VOCAB) is None


def test_validate_no_vocab_list_field_accepts_any_nonempty_strings():
    out = normalize._validate_extract_field(
        "required_attractions", ["Forbidden City", "", 5, "Summer Palace"], _VOCAB
    )
    assert out == ["Forbidden City", "Summer Palace"]


def test_validate_no_vocab_list_field_rejects_non_list():
    assert normalize._validate_extract_field("required_attractions", "Forbidden City", _VOCAB) is None


def test_validate_extract_families_drops_unwhitelisted_keys():
    out = normalize.validate_extract_families(
        {"required_attractions": ["A"], "not_a_real_family": "x"}, vocab=_VOCAB
    )
    assert out == {"required_attractions": ["A"]}


def test_validate_extract_families_non_dict_input_is_empty():
    assert normalize.validate_extract_families(None, vocab=_VOCAB) == {}
    assert normalize.validate_extract_families([], vocab=_VOCAB) == {}


# --- build_llm_extract_prompt: independence from the deterministic parse ----


def test_extract_prompt_does_not_embed_a_deterministic_parse():
    query = {
        "uid": "u1", "people_number": 2, "start_city": "A", "target_city": "B", "days": 3,
        "nature_language": "3 days in B, 2 people, stay in a twin room.",
    }
    prompt = normalize.build_llm_extract_prompt(query)
    assert "twin room" in prompt  # the raw NL is included
    assert "current deterministic parse" not in prompt.lower()  # audit-mode's own phrasing


# --- llm_extract_stub: merge policy -----------------------------------------


def _base_ir(raw):
    return ParsedIR(raw=dict(raw), variants=[dict(raw)])


def test_extract_stub_returns_ir_unchanged_when_client_is_none():
    ir = _base_ir({"room_type": "single"})
    out = normalize.llm_extract_stub(ir, {"uid": "u1"}, None)
    assert out is ir


def test_extract_stub_llm_value_overwrites_deterministic_value(monkeypatch):
    monkeypatch.setattr(normalize, "_extract_vocab", lambda: _VOCAB)
    ir = _base_ir({"room_type": "single"})
    llm = _FakeLLM('{"families": {"room_type": "twin"}, "or_arms": []}')
    out = normalize.llm_extract_stub(ir, {"uid": "u1"}, llm)
    assert out.raw["room_type"] == "twin"


def test_extract_stub_dict_family_merges_at_subkey_level_not_whole_value(monkeypatch):
    """Regression test for a live bug found via scripts/phase2_llm_parse_probe.py --llm-parse-mode
    extract: NL "the budget for sightseeing is 800" parses deterministically to
    budgets={"sightseeing": 800}, but the LLM mislabeled it budgets={"total": 800}. A whole-value
    replace would have silently dropped the correct "sightseeing" sub-key; the merge must instead
    fold the LLM's sub-keys into the existing dict, preserving ones the LLM didn't mention."""
    monkeypatch.setattr(normalize, "_extract_vocab", lambda: _VOCAB)
    ir = _base_ir({"budgets": {"sightseeing": 800.0}})
    llm = _FakeLLM('{"families": {"budgets": {"total": 800.0}}, "or_arms": []}')
    out = normalize.llm_extract_stub(ir, {"uid": "u1"}, llm)
    assert out.raw["budgets"] == {"sightseeing": 800.0, "total": 800.0}


def test_extract_stub_dict_family_llm_subkey_overwrites_matching_deterministic_subkey(monkeypatch):
    monkeypatch.setattr(normalize, "_extract_vocab", lambda: _VOCAB)
    ir = _base_ir({"budgets": {"total": 1000.0}})
    llm = _FakeLLM('{"families": {"budgets": {"total": 800.0}}, "or_arms": []}')
    out = normalize.llm_extract_stub(ir, {"uid": "u1"}, llm)
    assert out.raw["budgets"] == {"total": 800.0}


def test_extract_stub_keeps_deterministic_value_when_llm_says_nothing(monkeypatch):
    monkeypatch.setattr(normalize, "_extract_vocab", lambda: _VOCAB)
    ir = _base_ir({"room_type": "single", "required_attractions": ["Forbidden City"]})
    llm = _FakeLLM('{"families": {}, "or_arms": []}')
    out = normalize.llm_extract_stub(ir, {"uid": "u1"}, llm)
    assert out.raw["room_type"] == "single"
    assert out.raw["required_attractions"] == ["Forbidden City"]


def test_extract_stub_keeps_deterministic_value_when_llm_value_invalid(monkeypatch):
    """An invalid LLM value (fails vocab/type validation) must never delete deterministic recall
    -- plan-1 gap B6, the lesson the audit's remove-patch mode got wrong."""
    monkeypatch.setattr(normalize, "_extract_vocab", lambda: _VOCAB)
    ir = _base_ir({"room_type": "single"})
    llm = _FakeLLM('{"families": {"room_type": "queen-size"}, "or_arms": []}')
    out = normalize.llm_extract_stub(ir, {"uid": "u1"}, llm)
    assert out.raw["room_type"] == "single"


def test_extract_stub_adds_a_family_only_the_llm_found(monkeypatch):
    monkeypatch.setattr(normalize, "_extract_vocab", lambda: _VOCAB)
    ir = _base_ir({})
    llm = _FakeLLM('{"families": {"free_attractions_only": true}, "or_arms": []}')
    out = normalize.llm_extract_stub(ir, {"uid": "u1"}, llm)
    assert out.raw["free_attractions_only"] is True


def test_extract_stub_or_arms_used_when_fewer_than_two_deterministic_groups(monkeypatch):
    monkeypatch.setattr(normalize, "_extract_vocab", lambda: _VOCAB)
    ir = _base_ir({})
    llm = _FakeLLM(
        '{"families": {}, "or_arms": '
        '["Stay in a hotel with Hot spring bathing", "Only visit free attractions"]}'
    )
    out = normalize.llm_extract_stub(ir, {"uid": "u1", "nature_language": ""}, llm)
    assert len(out.or_groups) == 2


def test_extract_stub_or_arms_ignored_when_two_deterministic_groups_already_exist(monkeypatch):
    monkeypatch.setattr(normalize, "_extract_vocab", lambda: _VOCAB)
    ir = ParsedIR(raw={}, variants=[{}], or_groups=[{"a": 1}, {"b": 2}])
    llm = _FakeLLM('{"families": {}, "or_arms": ["x", "y", "z"]}')
    out = normalize.llm_extract_stub(ir, {"uid": "u1"}, llm)
    assert out.or_groups == [{"a": 1}, {"b": 2}]  # untouched


def test_extract_stub_malformed_json_raises(monkeypatch):
    monkeypatch.setattr(normalize, "_extract_vocab", lambda: _VOCAB)
    ir = _base_ir({"room_type": "single"})
    llm = _FakeLLM("not json")
    try:
        normalize.llm_extract_stub(ir, {"uid": "u1"}, llm)
        assert False, "expected ValueError"
    except ValueError:
        pass


# --- parse_to_ir routing + fallback contract ---------------------------------


def test_parse_to_ir_routes_to_extract_stub_when_mode_is_extract(monkeypatch, sample_queries):
    calls = {"extract": 0, "audit": 0}
    orig_extract = normalize.llm_extract_stub
    orig_audit = normalize.llm_parse_stub

    def spy_extract(ir, query, llm_client):
        calls["extract"] += 1
        return orig_extract(ir, query, llm_client)

    def spy_audit(ir, query, llm_client):
        calls["audit"] += 1
        return orig_audit(ir, query, llm_client)

    monkeypatch.setattr(normalize, "llm_extract_stub", spy_extract)
    monkeypatch.setattr(normalize, "llm_parse_stub", spy_audit)
    monkeypatch.setattr(normalize, "_extract_vocab", lambda: _VOCAB)

    q = next(iter(sample_queries.values()))
    llm = _FakeLLM('{"families": {}, "or_arms": []}')
    flags = Flags(llm_parse=True, llm_parse_mode="extract")
    normalize.parse_to_ir(q, llm_client=llm, flags=flags)
    assert calls["extract"] == 1
    assert calls["audit"] == 0


def test_parse_to_ir_routes_to_audit_stub_by_default(monkeypatch, sample_queries, spy_llm):
    calls = {"extract": 0, "audit": 0}
    orig_extract = normalize.llm_extract_stub
    orig_audit = normalize.llm_parse_stub

    def spy_extract(ir, query, llm_client):
        calls["extract"] += 1
        return orig_extract(ir, query, llm_client)

    def spy_audit(ir, query, llm_client):
        calls["audit"] += 1
        return orig_audit(ir, query, llm_client)

    monkeypatch.setattr(normalize, "llm_extract_stub", spy_extract)
    monkeypatch.setattr(normalize, "llm_parse_stub", spy_audit)

    q = next(iter(sample_queries.values()))
    flags = Flags(llm_parse=True)  # llm_parse_mode defaults to "audit"
    normalize.parse_to_ir(q, llm_client=spy_llm, flags=flags)
    assert calls["audit"] == 1
    assert calls["extract"] == 0


def test_parse_to_ir_falls_back_to_deterministic_on_extract_failure(monkeypatch, sample_queries):
    monkeypatch.setattr(normalize, "_extract_vocab", lambda: _VOCAB)
    q = next(iter(sample_queries.values()))
    llm = _FakeLLM("not json")
    flags = Flags(llm_parse=True, llm_parse_mode="extract")
    ir = normalize.parse_to_ir(q, llm_client=llm, flags=flags)
    assert ir.llm_parse_error is not None
    # Falls back to exactly the deterministic parse.
    import parse_constraints

    assert ir.raw == parse_constraints.parse_query_no_oracle(q)
