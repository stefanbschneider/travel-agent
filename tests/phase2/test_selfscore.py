"""The oracle-free scorer must be the official metric, not a second opinion.

It decides what the scheduler works on and which of two plans is kept, so a scorer that drifts
from ``eval_tpc.py``'s weighting would quietly optimise the wrong thing for five hours.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

import eval_tpc
from chinatravel.agent.phase2 import selfscore


def test_weights_are_the_official_ones():
    assert (
        selfscore.W_EPR_MICRO,
        selfscore.W_EPR_MACRO,
        selfscore.W_CLPR,
        selfscore.W_FPR,
        selfscore.W_PREFERENCE,
    ) == (0.10, 0.10, 0.25, 0.40, 0.05)
    total = (
        selfscore.W_EPR_MICRO
        + selfscore.W_EPR_MACRO
        + selfscore.W_CLPR
        + selfscore.W_FPR
        + 3 * selfscore.W_PREFERENCE
    )
    assert total == pytest.approx(1.0)


def test_preference_snippets_come_from_eval_tpc_rather_than_a_copy():
    assert list(selfscore._preference_snippets()) == list(eval_tpc.DEFAULT_PR)


def test_constraints_are_worth_more_than_every_preference_term_combined():
    """Why the scheduler is constraint-first: 0.65 of the score is gated on constraints, and the
    remaining 0.15 is zeroed for a query that fails them."""
    constraint_weight = selfscore.W_FPR + selfscore.W_CLPR
    preference_weight = 3 * selfscore.W_PREFERENCE
    assert constraint_weight > 4 * preference_weight


class TestPlanScore:
    def _passing(self, **overrides) -> selfscore.PlanScore:
        base = selfscore.PlanScore(
            schema_ok=True,
            commonsense_ok=True,
            logical_ok=True,
            epr_micro=100.0,
            epr_macro=100.0,
            clpr=100.0,
            fpr=100.0,
            dav=40.0,
            att=60.0,
            ddr=50.0,
            overall=82.5,
            logical_total=3,
            logical_satisfied=3,
        )
        return replace(base, **overrides)

    def test_constraints_ok_needs_all_three_checks(self):
        assert self._passing().constraints_ok
        assert not self._passing(schema_ok=False).constraints_ok
        assert not self._passing(commonsense_ok=False).constraints_ok
        assert not self._passing(logical_ok=False).constraints_ok

    def test_remaining_gain_for_a_failing_plan_is_everything_it_has_not_earned(self):
        failing = self._passing(logical_ok=False, overall=30.0)
        assert selfscore.max_remaining_gain(failing) == pytest.approx(70.0)

    def test_remaining_gain_for_a_passing_plan_is_only_the_preference_remainder(self):
        gain = selfscore.max_remaining_gain(self._passing())
        assert gain == pytest.approx(0.05 * ((100 - 40) + (100 - 60) + (100 - 50)))

    def test_an_unsolved_query_outranks_every_polish_candidate(self):
        assert selfscore.max_remaining_gain(None) == 100.0
        assert selfscore.max_remaining_gain(None) > selfscore.max_remaining_gain(self._passing())


class TestScorePlan:
    """End-to-end against the real evaluators (they need the sandbox database)."""

    @pytest.fixture
    def query(self, sample_queries):
        return dict(next(iter(sample_queries.values())))

    def test_an_empty_itinerary_scores_zero_but_does_not_raise(self, query):
        visible = {k: v for k, v in query.items() if not k.startswith("hard_logic")}
        score = selfscore.score_plan(
            {"people_number": 1, "start_city": "Shanghai", "target_city": "Beijing",
             "itinerary": []},
            visible,
            uid="t1",
        )
        assert score.overall == 0.0
        assert not score.constraints_ok
        assert score.error is None

    def test_scoring_never_raises_on_a_malformed_plan(self, query):
        visible = {k: v for k, v in query.items() if not k.startswith("hard_logic")}
        score = selfscore.score_plan("not a plan", visible, uid="t2")  # type: ignore[arg-type]
        assert score.overall == 0.0
        assert not score.constraints_ok

    def test_the_scorer_is_never_handed_an_oracle_field(self, query):
        """Structural, not incidental: the signature takes the visible query, so there is no path
        by which hard_logic could reach it."""
        visible = {k: v for k, v in query.items() if not k.startswith("hard_logic")}
        assert not any(key.startswith("hard_logic") for key in visible)
        seen: dict = {}

        original = selfscore._score_plan

        def spy(plan, visible_query, variants, lang, quid):
            seen.update(visible_query)
            return original(plan, visible_query, variants, lang, quid)

        selfscore._score_plan = spy
        try:
            selfscore.score_plan({"itinerary": []}, visible, uid="t3")
        finally:
            selfscore._score_plan = original
        assert not any(key.startswith("hard_logic") for key in seen)
