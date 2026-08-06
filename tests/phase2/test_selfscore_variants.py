"""Roadmap P10: scheduler self-scoring must use the solver's exact parsed variants.

Before this change, ``run_sweeps_split`` scored every attempt against a single flat dict from
``selfscore.derive_parsed_constraints`` while the orchestrator solved against the real,
disjunction-expanded, entity-resolved variant list from ``normalize.parse_to_ir`` +
``normalize.ir_to_solver_variants``. On a disjunctive query that meant the scheduler's own
opinion was *systematically* stricter than the solver's (it demanded every OR arm instead of any
one), which is exactly the shape of the measured false negatives in
docs/tpc_phase2_roadmap.md#5. These tests pin the fix: ``score_plan`` now takes a ``variants``
list and accepts a plan whenever *any* variant's checks all pass.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from chinatravel.agent.phase2 import selfscore
from chinatravel.agent.phase2 import sweeps


def _plan_with_attraction(name: str) -> dict:
    return {
        "people_number": 1,
        "start_city": "Shanghai",
        "target_city": "Beijing",
        "itinerary": [
            {
                "day": 1,
                "activities": [
                    {
                        "position": name,
                        "type": "attraction",
                        "start_time": "09:00",
                        "end_time": "10:00",
                        "price": 0,
                        "cost": 0,
                        "transports": [],
                    }
                ],
            }
        ],
    }


class TestOrAcrossVariants:
    """The regression this item exists for: an 'A or B' query where a plan satisfying only B
    must score logical_ok and be kept. This fails on main today (pre-P10), because
    derive_parsed_constraints only ever sees variants[0]."""

    def test_plan_satisfying_only_the_second_variant_scores_logical_ok(self, query):
        variant_a = {"required_attractions": ["Forbidden City"]}
        variant_b = {"required_attractions": ["Summer Palace"]}
        plan = _plan_with_attraction("Summer Palace")  # only satisfies B

        score = selfscore.score_plan(
            plan, query, variants=[variant_a, variant_b], uid="or-test"
        )
        assert score.logical_ok is True
        assert score.logical_satisfied == score.logical_total == 1

    def test_a_single_flat_dict_that_fails_would_have_rejected_the_same_plan(self, query):
        """Same plan, but scored the old (pre-P10) way against variants[0] alone: it must fail,
        which is the miscalibration P10 fixes -- the OR semantics only appear once every variant
        is actually evaluated."""
        variant_a = {"required_attractions": ["Forbidden City"]}
        plan = _plan_with_attraction("Summer Palace")

        score = selfscore.score_plan(plan, query, variants=[variant_a], uid="single-variant")
        assert score.logical_ok is False

    def test_kept_by_is_better_when_it_flips_constraints_ok(self, query):
        variant_a = {"required_attractions": ["Forbidden City"]}
        variant_b = {"required_attractions": ["Summer Palace"]}
        plan = _plan_with_attraction("Summer Palace")

        candidate = selfscore.score_plan(
            plan, query, variants=[variant_a, variant_b], uid="or-keep"
        )
        # An empty-itinerary incumbent never satisfies anything.
        incumbent = selfscore.score_plan(
            {"people_number": 1, "start_city": "Shanghai", "target_city": "Beijing",
             "itinerary": []},
            query,
            variants=[variant_a, variant_b],
            uid="or-keep",
        )
        assert selfscore.is_better(candidate, incumbent)


class TestBestVariantSelection:
    def test_best_variant_is_the_all_true_one_even_if_listed_second(self, query):
        variant_fails = {"required_attractions": ["Forbidden City"], "required_restaurants": ["X"]}
        variant_passes = {"required_attractions": ["Summer Palace"]}
        plan = _plan_with_attraction("Summer Palace")

        score = selfscore.score_plan(
            plan, query, variants=[variant_fails, variant_passes], uid="best-variant"
        )
        assert score.logical_ok is True
        assert score.logical_total == 1
        assert score.logical_satisfied == 1

    def test_best_variant_when_none_all_true_is_the_highest_ratio(self, query):
        # Neither variant fully passes; the reported total/satisfied must come from the
        # higher-ratio variant (2/2 beats 0/1), not simply the first one in the list.
        variant_low_ratio = {"required_restaurants": ["Nonexistent Place"]}
        variant_high_ratio = {
            "required_attractions": ["Summer Palace"],
            "required_restaurants": ["Nonexistent Place 2"],
        }
        plan = _plan_with_attraction("Summer Palace")

        score = selfscore.score_plan(
            plan, query, variants=[variant_low_ratio, variant_high_ratio], uid="ratio-variant"
        )
        assert score.logical_ok is False
        assert score.logical_total == 2
        assert score.logical_satisfied == 1


class TestNonDisjunctiveFloorUnchanged:
    """A non-disjunctive query: PlanScore must be unchanged field-for-field against the
    pre-change value -- this is the floor P10 must not disturb."""

    def test_single_variant_matches_parsed_constraints_alias(self, query):
        variant = {"required_attractions": ["Summer Palace"]}
        plan = _plan_with_attraction("Summer Palace")

        via_variants = selfscore.score_plan(plan, query, variants=[variant], uid="floor")
        via_alias = selfscore.score_plan(plan, query, parsed_constraints=variant, uid="floor")
        assert via_variants == via_alias

    def test_omitting_both_falls_back_to_derive_parsed_constraints(self, query, monkeypatch):
        called = {}

        def fake_derive(visible_query):
            called["yes"] = True
            return {}

        monkeypatch.setattr(selfscore, "derive_parsed_constraints", fake_derive)
        plan = _plan_with_attraction("Summer Palace")
        selfscore.score_plan(plan, query, uid="fallback")
        assert called.get("yes") is True

    def test_empty_variants_list_also_falls_back(self, query, monkeypatch):
        called = {}

        def fake_derive(visible_query):
            called["yes"] = True
            return {}

        monkeypatch.setattr(selfscore, "derive_parsed_constraints", fake_derive)
        plan = _plan_with_attraction("Summer Palace")
        selfscore.score_plan(plan, query, variants=[], uid="fallback-empty")
        assert called.get("yes") is True


class TestEmptyOrFailedParseNeverRaises:
    def test_empty_itinerary_with_no_variants_yields_a_score_not_an_exception(self, query):
        score = selfscore.score_plan(
            {"people_number": 1, "start_city": "Shanghai", "target_city": "Beijing",
             "itinerary": []},
            query,
            variants=None,
            uid="zero",
        )
        assert score.overall == 0.0
        assert score.error is None

    def test_malformed_variant_entries_degrade_rather_than_raise(self, query):
        plan = _plan_with_attraction("Summer Palace")
        score = selfscore.score_plan(plan, query, variants=["not a dict", None], uid="malformed")
        assert score.error is None

    def test_malformed_variants_never_vacuously_pass(self, query, monkeypatch):
        """Regression for a real bug flagged in review: evaluate_parsed_constraints returns []
        for a non-dict variant (0 checks), and a naive ratio (0/0 => 1.0) would treat that as an
        all-true variant and wrongly flip logical_ok to True. Non-dict entries must be filtered
        out before scoring, not evaluated as if they were an unconstrained (trivially-passing)
        variant."""

        def fake_derive(visible_query):
            return {"required_attractions": ["Nonexistent Place"]}

        monkeypatch.setattr(selfscore, "derive_parsed_constraints", fake_derive)
        plan = _plan_with_attraction("Summer Palace")  # does not satisfy the fallback constraint
        score = selfscore.score_plan(plan, query, variants=["not a dict", None], uid="malformed-2")
        assert score.logical_ok is False

    def test_a_real_failing_variant_is_still_evaluated_alongside_malformed_ones(self, query):
        """A malformed entry must not short-circuit scoring of the real variants in the same
        list -- the failing real variant's checks must still be reported."""
        variant = {"required_attractions": ["Nonexistent Place"]}
        plan = _plan_with_attraction("Summer Palace")
        score = selfscore.score_plan(
            plan, query, variants=["not a dict", variant, None], uid="malformed-3"
        )
        assert score.logical_ok is False
        assert score.logical_total == 1
        assert score.logical_satisfied == 0


class TestSolveOneUsesTheSameVariantsForSolveAndScore:
    """run_sweeps (via solve_one) must pass the identical object to solve_phase2 and score_plan."""

    def test_solve_one_forwards_the_same_variants_object_to_solve_and_score(self, monkeypatch, query):
        uid = "same-object"
        sentinel_variants = [{"required_attractions": ["Summer Palace"]}]

        seen = {}

        def fake_solve_phase2(visible_query, *, env, llm_client, budget_sec, solve_fn, flags,
                               variants=None):
            seen["solve_variants"] = variants
            return _plan_with_attraction("Summer Palace"), {"uid": uid}

        def fake_score_plan(plan, visible_query, *, variants=None, parsed_constraints=None,
                             lang="en", uid=None):
            seen["score_variants"] = variants
            return selfscore.ZERO_SCORE

        monkeypatch.setattr(sweeps.orch, "solve_phase2", fake_solve_phase2)
        monkeypatch.setattr(sweeps.selfscore, "score_plan", fake_score_plan)
        monkeypatch.setitem(
            sweeps._WORKER,
            "ready", True,
        )
        sweeps._WORKER.update(
            env=object(), llm_client=object(), solve_fn=object(), flags=object(), lang="en",
        )

        task = {
            "uid": uid,
            "query": query,
            "budget_sec": 5.0,
            "lang": "en",
            "kind": "triage",
            "fast_accept": False,
            "variants": sentinel_variants,
        }
        result = sweeps.solve_one(task)

        assert seen["solve_variants"] is sentinel_variants
        assert seen["score_variants"] is sentinel_variants
        assert result["uid"] == uid


@pytest.fixture
def query(sample_queries):
    q = dict(next(iter(sample_queries.values())))
    return {k: v for k, v in q.items() if not k.startswith("hard_logic")}
