"""Tests for the Phase 2 two-layer schema + normalization skeleton (Task 4).

The skeleton must be a faithful passthrough: turning a query into a ParsedIR and back into solver
constraint variants must equal exactly what the current no-oracle path produces today, i.e.
``solver_constraint_variants(query, parse_query_no_oracle(query), use_oracle=False)``.
"""

from __future__ import annotations

import parse_constraints
from chinatravel.agent.tpc_agent.solver_constraints import solver_constraint_variants

from chinatravel.agent.phase2 import normalize
from chinatravel.agent.phase2.schema import ParsedIR


def _baseline_variants(query):
    raw = parse_constraints.parse_query_no_oracle(query)
    return solver_constraint_variants(query, raw, use_oracle=False)


def test_parse_to_ir_returns_parsed_ir(one_query):
    ir = normalize.parse_to_ir(one_query)
    assert isinstance(ir, ParsedIR)
    # Skeleton IR carries at least one variant (the flat deterministic parse).
    assert len(ir.variants) >= 1


def test_passthrough_matches_current_no_oracle_variants(sample_queries):
    for uid, query in sample_queries.items():
        ir = normalize.parse_to_ir(query)
        got = normalize.ir_to_solver_variants(ir, query)
        expected = _baseline_variants(query)
        assert got == expected, f"variant mismatch for uid {uid}"


def test_parse_to_ir_does_not_call_llm_by_default(sample_queries, spy_llm):
    for query in sample_queries.values():
        normalize.parse_to_ir(query, llm_client=spy_llm)
    assert spy_llm.calls == [], "parse_to_ir must not call the LLM on the default path"


def test_llm_parse_adds_missing_constraint_without_overwriting_existing(one_query):
    class FakeLLM:
        def __init__(self, response):
            self.response = response
            self.calls = []

        def complete(self, prompt, *, system=None, cache_key=None):
            self.calls.append({"prompt": prompt, "cache_key": cache_key})
            return self.response

    # dining budget is often absent in deterministic parse for generic queries; use LLM hint text.
    llm = FakeLLM('{"constraint_text":"The budget for dining is 120."}')
    flags = type("Flags", (), {"disjunction": False, "llm_parse": True})()
    ir = normalize.parse_to_ir(one_query, llm_client=llm, flags=flags)

    assert len(llm.calls) == 1
    budgets = ir.raw.get("budgets", {})
    assert budgets.get("dining") == 120.0


def test_llm_parse_stub_invalid_json_raises(one_query):
    """llm_parse_stub itself still raises on a malformed response (its own documented contract:
    "Any error keeps ir unchanged by raising, so the orchestrator can degrade safely")."""
    class BadLLM:
        def complete(self, prompt, *, system=None, cache_key=None):
            return "not-json"

    ir = normalize.parse_to_ir(one_query)  # deterministic ir, llm_parse off
    try:
        normalize.llm_parse_stub(ir, one_query, BadLLM())
    except ValueError as exc:
        assert "llm_parse invalid JSON" in str(exc)
    else:
        raise AssertionError("Expected llm_parse invalid JSON to raise")


def test_parse_to_ir_falls_back_to_deterministic_ir_on_llm_failure(one_query):
    """parse_to_ir must catch llm_parse_stub's raise and keep the deterministic ir -- previously
    the exception propagated out of parse_to_ir, and orchestrator.solve_phase2's broad
    try/except around the whole parse stage discarded the (perfectly good) deterministic parse
    entirely (variants=[]) on any LLM hiccup, not just genuine parse bugs."""
    class BadLLM:
        def complete(self, prompt, *, system=None, cache_key=None):
            return "not-json"

    deterministic = normalize.parse_to_ir(one_query)  # llm_parse off -> no LLM call
    flags = type("Flags", (), {"disjunction": False, "llm_parse": True})()
    ir = normalize.parse_to_ir(one_query, llm_client=BadLLM(), flags=flags)
    assert ir == deterministic


def test_parse_to_ir_falls_back_to_deterministic_ir_on_llm_exception(one_query):
    """Same contract, but for a client that raises outright (e.g. a network error) rather than
    returning malformed JSON."""
    class RaisingLLM:
        def complete(self, prompt, *, system=None, cache_key=None):
            raise RuntimeError("connection reset")

    deterministic = normalize.parse_to_ir(one_query)
    flags = type("Flags", (), {"disjunction": False, "llm_parse": True})()
    ir = normalize.parse_to_ir(one_query, llm_client=RaisingLLM(), flags=flags)
    assert ir == deterministic


def test_llm_parse_replace_can_correct_existing_value():
    class FakeLLM:
        def complete(self, prompt, *, system=None, cache_key=None):
            return (
                '{"patches":[{"mode":"replace",'
                '"constraint_text":"The budget for dining is 120.",'
                '"confidence":0.91}],"field_confidence":{"budgets":0.91}}'
            )

    query = {
        "uid": "q_replace_budget",
        "people_number": 2,
        "start_city": "Shanghai",
        "target_city": "Shanghai",
        "nature_language": "The budget for dining is 100.",
    }
    flags = type("Flags", (), {"disjunction": False, "llm_parse": True})()
    ir = normalize.parse_to_ir(query, llm_client=FakeLLM(), flags=flags)

    assert ir.raw.get("budgets", {}).get("dining") == 120.0
    assert ir.confidence.get("budgets") == 0.91


def test_llm_parse_or_arm_recovery_when_deterministic_split_missing():
    class FakeLLM:
        def complete(self, prompt, *, system=None, cache_key=None):
            return (
                '{"patches":[],"or_arms":['
                '"I want to visit West Lake.",'
                "\"I want to try Grandma's Home restaurant.\""
                '],"field_alternatives":{},"field_confidence":{}}'
            )

    query = {
        "uid": "q_or_recover",
        "people_number": 2,
        "start_city": "Hangzhou",
        "target_city": "Hangzhou",
        "nature_language": "Visit West Lake or try Grandma's Home restaurant.",
    }
    flags = type("Flags", (), {"disjunction": True, "llm_parse": True})()
    ir = normalize.parse_to_ir(query, llm_client=FakeLLM(), flags=flags)
    variants = normalize.ir_to_solver_variants(ir, query, flags=flags)

    assert len(ir.or_groups) >= 2
    assert len(variants) >= 2


def test_llm_parse_field_alternatives_expand_solver_variants():
    class FakeLLM:
        def complete(self, prompt, *, system=None, cache_key=None):
            return (
                '{"patches":[],"or_arms":[],"field_alternatives":{'
                '"budgets":['
                '{"constraint_text":"The budget for dining is 80.","confidence":0.40},'
                '{"constraint_text":"The budget for dining is 120.","confidence":0.80}'
                ']},"field_confidence":{"budgets":0.55}}'
            )

    query = {
        "uid": "q_alt_budget",
        "people_number": 2,
        "start_city": "Shanghai",
        "target_city": "Shanghai",
        "nature_language": "The budget for dining is 100.",
    }
    flags = type("Flags", (), {"disjunction": False, "llm_parse": True})()
    ir = normalize.parse_to_ir(query, llm_client=FakeLLM(), flags=flags)
    variants = normalize.ir_to_solver_variants(ir, query, flags=flags)

    dining_values = {
        float(v.get("budgets", {}).get("dining"))
        for v in variants
        if isinstance(v.get("budgets", {}).get("dining"), (int, float))
    }
    assert {80.0, 100.0, 120.0}.issubset(dining_values)


# --- Step 2: corrective audit prompt ---------------------------------------

def test_build_llm_parse_prompt_audits_each_extracted_family():
    query = {
        "uid": "q_audit",
        "people_number": 2,
        "start_city": "Hangzhou",
        "target_city": "Wuhan",
        "nature_language": "Do not wish to stay at the following hotels: Yucheng Hotel.",
    }
    raw = {"excluded_hotels": ["Yucheng Hotel"], "required_attractions": ["Bogus Place"]}
    prompt = normalize.build_llm_parse_prompt(query, raw)
    # The prompt must frame the task as an audit (confirm-or-remove), not optional refinement.
    assert "audit" in prompt.lower()
    assert "remove" in prompt.lower()
    assert "negation" in prompt.lower() or "do not" in prompt.lower()
    # Every extracted family must be listed for the model to audit.
    assert "excluded_hotels" in prompt
    assert "required_attractions" in prompt
    # It must NOT invite the old passive "if no useful refinement" opt-out as the primary framing.
    assert "no useful refinement" not in prompt.lower()


# --- Step 7: OR-arm recovery prompt section ---------------------------------

def _q_or(nl):
    return {
        "uid": "q_or",
        "people_number": 2,
        "start_city": "Hangzhou",
        "target_city": "Wuhan",
        "nature_language": nl,
    }


def test_or_arm_section_present_when_deterministic_split_missing():
    prompt = normalize.build_llm_parse_prompt(
        _q_or("Must satisfy one of the following: 1. X. 2. Y."), {}, or_groups_count=0
    )
    assert "OR-ARM RECOVERY" in prompt
    assert "or_arms" in prompt
    # A worked example, not just the bare instruction, per the plan's "one worked or_arms example".
    assert "Worked example" in prompt


def test_or_arm_section_omitted_when_deterministic_split_already_found_2_arms():
    prompt = normalize.build_llm_parse_prompt(
        _q_or("Must satisfy one of the following: 1. X. 2. Y."), {}, or_groups_count=2
    )
    assert "OR-ARM RECOVERY" not in prompt


def test_or_arm_section_defaults_to_present_when_count_unspecified():
    # Backward-compat default (0): callers that don't pass or_groups_count still get the section.
    prompt = normalize.build_llm_parse_prompt(_q_or("Some non-disjunctive query."), {})
    assert "OR-ARM RECOVERY" in prompt


def test_llm_parse_removes_spurious_required_family():
    # The deterministic parse contains a spurious required_attractions family; the audit prompt
    # should let the LLM remove it via a remove patch (fields=[...]).
    class RemovingLLM:
        def complete(self, prompt, *, system=None, cache_key=None):
            # Sanity: the family we want removed is presented for audit.
            assert "required_attractions" in prompt
            return (
                '{"patches":[{"mode":"remove","fields":["required_attractions"],'
                '"constraint_text":"the request only says do NOT visit that place",'
                '"confidence":0.9}],"or_arms":[],"field_alternatives":{},"field_confidence":{}}'
            )

    query = {
        "uid": "q_remove_spurious",
        "people_number": 2,
        "start_city": "Shanghai",
        "target_city": "Nanjing",
        "nature_language": "We do not want to visit the Confucius Temple.",
    }
    flags = type("Flags", (), {"disjunction": False, "llm_parse": True})()
    # Seed a spurious family so we can assert removal deterministically.
    ir = normalize.parse_to_ir(query, flags=flags)
    ir.raw["required_attractions"] = ["Confucius Temple"]

    # Re-run only the llm parse stub over the seeded IR.
    updated = normalize.llm_parse_stub(ir, query, RemovingLLM())
    assert "required_attractions" not in updated.raw, updated.raw


def test_llm_parse_empty_patches_keep_parse_unchanged():
    class NoopLLM:
        def complete(self, prompt, *, system=None, cache_key=None):
            return '{"patches":[],"or_arms":[],"field_alternatives":{},"field_confidence":{}}'

    query = {
        "uid": "q_noop",
        "people_number": 2,
        "start_city": "Shanghai",
        "target_city": "Nanjing",
        "nature_language": "The budget for dining is 100.",
    }
    flags = type("Flags", (), {"disjunction": False, "llm_parse": True})()
    ir = normalize.parse_to_ir(query, flags=flags)
    before = dict(ir.raw)
    updated = normalize.llm_parse_stub(ir, query, NoopLLM())
    assert updated.raw == before
