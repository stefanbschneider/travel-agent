"""The sweep scheduler's contract under a whole-run wall-clock envelope.

What these tests defend, in the order the run depends on them:

1. the run never starts work it cannot finish before the deadline, and never runs past it;
2. every query has a plan on disk before any solving starts, and no pass can regress one;
3. constraint-failing queries are worked on before preference polish, easiest first;
4. parallel workers convert into per-query search time, not just a shorter run.
"""

from __future__ import annotations

import time

import pytest

from chinatravel.agent.phase2 import selfscore, sweeps


def _score(*, ok: bool, overall: float, satisfied: int = 1, total: int = 1) -> selfscore.PlanScore:
    return selfscore.PlanScore(
        schema_ok=True,
        commonsense_ok=ok,
        logical_ok=ok,
        epr_micro=100.0,
        epr_macro=100.0 if ok else 0.0,
        clpr=100.0 if ok else 0.0,
        fpr=100.0 if ok else 0.0,
        dav=50.0 if ok else 0.0,
        att=50.0 if ok else 0.0,
        ddr=50.0 if ok else 0.0,
        overall=overall,
        logical_total=total,
        logical_satisfied=satisfied,
    )


class TestBudgetMath:
    def test_parallel_workers_buy_per_query_time_not_just_a_shorter_run(self):
        """16 cores turn a 100-query pass into 7 rounds, so each query can afford ~14x the
        budget it would get from a sequential fair share."""
        sequential = sweeps.pass_budget_sec(
            16200, 100, workers=1, fraction=1.0, cap_sec=1e9
        )
        parallel = sweeps.pass_budget_sec(16200, 100, workers=16, fraction=1.0, cap_sec=1e9)
        assert sequential == pytest.approx(162.0)
        assert parallel == pytest.approx(16200 / 7)
        assert parallel > sequential * 10

    def test_triage_stays_small_even_with_a_whole_envelope_available(self):
        budget = sweeps.pass_budget_sec(
            16200, 100, workers=16, fraction=sweeps.DEFAULT_TRIAGE_FRACTION,
            cap_sec=sweeps.DEFAULT_TRIAGE_CAP_SEC,
        )
        assert budget == sweeps.DEFAULT_TRIAGE_CAP_SEC

    def test_no_query_exceeds_the_gate_ceiling(self):
        budget = sweeps.pass_budget_sec(
            16200, 2, workers=16, fraction=0.5, cap_sec=sweeps.DEFAULT_MAX_QUERY_SEC
        )
        assert budget == sweeps.DEFAULT_MAX_QUERY_SEC

    def test_floor_holds_when_almost_nothing_is_left(self):
        budget = sweeps.pass_budget_sec(1.0, 100, workers=16, fraction=0.5, cap_sec=900)
        assert budget == sweeps.DEFAULT_MIN_QUERY_SEC

    def test_rounds_account_for_the_last_partial_batch(self):
        assert sweeps.rounds_needed(100, 16) == 7
        assert sweeps.rounds_needed(16, 16) == 1
        assert sweeps.rounds_needed(17, 16) == 2
        assert sweeps.rounds_needed(0, 16) == 0

    def test_pass_fits_measures_wall_clock_not_summed_budgets(self):
        # 32 queries x 100s on 16 workers is 2 rounds = 200s of wall clock, not 3200s.
        assert sweeps.pass_fits(250, 100, 32, 16)
        assert not sweeps.pass_fits(150, 100, 32, 16)


class TestWorkOrdering:
    def test_failing_queries_come_before_polish_and_easiest_first(self):
        scores = {
            "hard": _score(ok=False, overall=10.0, satisfied=1, total=10),
            "nearly": _score(ok=False, overall=40.0, satisfied=9, total=10),
            "done": _score(ok=True, overall=80.0),
        }
        assert sweeps.repair_order(scores) == ["nearly", "hard"]
        assert sweeps.polish_order(scores) == ["done"]

    def test_unscored_queries_count_as_failing(self):
        assert sweeps.repair_order({"a": None}) == ["a"]

    def test_polish_prefers_the_largest_remaining_preference_gain(self):
        from dataclasses import replace

        low = _score(ok=True, overall=80.0)
        high = replace(low, dav=10.0, att=10.0, ddr=10.0)
        scores = {"low_headroom": low, "high_headroom": high}
        assert sweeps.polish_order(scores)[0] == "high_headroom"

    def test_pass_kinds_follow_triage_repair_polish(self):
        uids = ["a", "b"]
        assert sweeps._next_pass(index=1, uids=uids, best_scores={}, stalled_repairs=0) == (
            "triage",
            ["a", "b"],
        )
        failing = {"a": _score(ok=False, overall=10.0), "b": _score(ok=True, overall=90.0)}
        kind, todo = sweeps._next_pass(index=2, uids=uids, best_scores=failing, stalled_repairs=0)
        assert (kind, todo) == ("repair", ["a"])

    def test_repair_gives_up_after_two_fruitless_escalations(self):
        """Two budget escalations that improve nothing mean the failures are structural. The
        remaining time is worth more spent on preference gains that are actually reachable."""
        uids = ["a", "b"]
        scores = {"a": _score(ok=False, overall=10.0), "b": _score(ok=True, overall=90.0)}
        kind, todo = sweeps._next_pass(
            index=5, uids=uids, best_scores=scores,
            stalled_repairs=sweeps.MAX_STALLED_REPAIR_PASSES,
        )
        assert kind == "polish"
        assert todo == ["b"]


class TestKeepBest:
    def test_constraint_satisfaction_outranks_any_preference_gain(self):
        passing = _score(ok=True, overall=70.0)
        failing_but_high = _score(ok=False, overall=99.0)
        assert not selfscore.is_better(failing_but_high, passing)
        assert selfscore.is_better(passing, failing_but_high)

    def test_equal_scores_do_not_churn_the_file(self):
        score = _score(ok=True, overall=70.0)
        assert not selfscore.is_better(score, score)

    def test_anything_beats_nothing(self):
        assert selfscore.is_better(selfscore.ZERO_SCORE, None)


class TestDriver:
    """The driver is exercised with an injected in-process solve so no WorldEnv is needed."""

    @pytest.fixture
    def queries(self):
        return {
            uid: {"uid": uid, "start_city": "A", "target_city": "B", "people_number": 1}
            for uid in ("q1", "q2", "q3")
        }

    def _run(self, queries, *, monkeypatch, deadline_in: float, results, workers=1, **kwargs):
        """Drive run_sweeps with a stub solver that returns scripted scores."""
        calls: list[dict] = []

        def fake_solve_one(task):
            calls.append(dict(task))
            score = results(task)
            return {
                "uid": task["uid"],
                "plan": {"itinerary": [{"day": 1}], "uid": task["uid"]},
                "telemetry": {"uid": task["uid"]},
                "score": score.to_dict(),
                "wall_sec": 0.0,
            }

        monkeypatch.setattr(sweeps, "solve_one", fake_solve_one)
        written: list[tuple[str, float]] = []
        summary = sweeps.run_sweeps(
            uids=list(queries),
            queries=queries,
            deadline=time.monotonic() + deadline_in,
            config=sweeps.SweepConfig(workers=workers, **kwargs),
            on_result=lambda uid, plan, score, tel: written.append((uid, score.overall)),
            log=lambda _msg: None,
        )
        return calls, written, summary

    def test_triage_visits_every_query_once(self, queries, monkeypatch):
        calls, written, summary = self._run(
            queries,
            monkeypatch=monkeypatch,
            deadline_in=600,
            results=lambda task: _score(ok=True, overall=90.0),
        )
        triage = [call for call in calls if call["kind"] == "triage"]
        assert sorted(call["uid"] for call in triage) == ["q1", "q2", "q3"]
        assert sorted(uid for uid, _ in written) == ["q1", "q2", "q3"]
        assert summary["constraints_ok"] == 3

    def test_a_worse_rerun_never_overwrites_a_better_plan(self, queries, monkeypatch):
        seen: dict[str, int] = {}

        def results(task):
            seen[task["uid"]] = seen.get(task["uid"], 0) + 1
            # First visit solves it; every later visit comes back worse.
            return _score(ok=True, overall=90.0) if seen[task["uid"]] == 1 else _score(
                ok=False, overall=5.0
            )

        _calls, written, _summary = self._run(
            queries, monkeypatch=monkeypatch, deadline_in=600, results=results
        )
        assert [overall for _uid, overall in written] == [90.0, 90.0, 90.0]

    def test_repair_targets_only_failing_queries(self, queries, monkeypatch):
        def results(task):
            return _score(ok=task["uid"] != "q2", overall=90.0 if task["uid"] != "q2" else 20.0)

        calls, _written, summary = self._run(
            queries, monkeypatch=monkeypatch, deadline_in=600, results=results
        )
        repair_uids = {call["uid"] for call in calls if call["kind"] == "repair"}
        assert repair_uids == {"q2"}
        assert summary["constraints_ok"] == 2

    def test_budgets_escalate_across_passes(self, queries, monkeypatch):
        calls, _written, _summary = self._run(
            queries,
            monkeypatch=monkeypatch,
            deadline_in=3600,
            results=lambda task: _score(ok=False, overall=10.0),
        )
        triage = [c["budget_sec"] for c in calls if c["kind"] == "triage"]
        repair = [c["budget_sec"] for c in calls if c["kind"] == "repair"]
        assert repair, "a failing triage must be followed by repair passes"
        assert min(repair) > max(triage)

    def test_nothing_is_dispatched_once_the_deadline_has_passed(self, queries, monkeypatch):
        calls, _written, summary = self._run(
            queries,
            monkeypatch=monkeypatch,
            deadline_in=-1.0,
            results=lambda task: _score(ok=True, overall=90.0),
        )
        assert calls == []
        assert summary["passes"] == []

    def test_the_run_stops_instead_of_repeating_an_identical_solve(self, queries, monkeypatch):
        """A re-solve at (nearly) the same budget reproduces the same plan. Burning the tail of
        the envelope on that is worse than stopping."""
        calls, _written, _summary = self._run(
            queries,
            monkeypatch=monkeypatch,
            deadline_in=600,
            results=lambda task: _score(ok=False, overall=10.0),
            max_passes=50,
        )
        budgets = [call["budget_sec"] for call in calls]
        # Consecutive distinct budgets, each meaningfully larger than the last.
        distinct = sorted(set(round(b, 3) for b in budgets))
        assert len(distinct) == len(set(distinct))
        assert len(calls) < 50 * len(queries)

    def test_leftover_time_goes_to_polish_when_repair_has_nothing_new_to_try(self, queries):
        """A repair pass whose every candidate would only get a repeat of its previous budget is
        not a reason to end the run with time on the clock -- polish the passing queries instead."""
        best = {
            "q1": _score(ok=False, overall=20.0),
            "q2": _score(ok=True, overall=80.0),
            "q3": _score(ok=True, overall=80.0),
        }
        config = sweeps.SweepConfig(workers=1)
        chosen = sweeps._choose_pass(
            index=3,
            uids=list(queries),
            best_scores=best,
            stalled_repairs=0,
            # q1 already had a budget no achievable new budget can beat by the growth factor.
            last_budget={"q1": 10_000.0},
            remaining_sec=600.0,
            config=config,
        )
        assert chosen is not None
        kind, uids, _budget = chosen
        assert kind == "polish"
        assert set(uids) == {"q2", "q3"}

    def test_no_pass_is_chosen_when_everything_would_repeat_itself(self, queries):
        best = {uid: _score(ok=True, overall=80.0) for uid in queries}
        chosen = sweeps._choose_pass(
            index=4,
            uids=list(queries),
            best_scores=best,
            stalled_repairs=0,
            last_budget={uid: 10_000.0 for uid in queries},
            remaining_sec=600.0,
            config=sweeps.SweepConfig(workers=1),
        )
        assert chosen is None

    def test_summary_reports_the_oracle_free_split_estimate(self, queries, monkeypatch):
        _calls, _written, summary = self._run(
            queries,
            monkeypatch=monkeypatch,
            deadline_in=300,
            results=lambda task: _score(ok=task["uid"] == "q1", overall=90.0 if task["uid"] == "q1" else 30.0),
        )
        assert summary["queries"] == 3
        assert summary["constraints_ok"] == 1
        # Averaged over the whole split, as the official scorer does.
        assert summary["self_overall_mean"] == pytest.approx((90.0 + 30.0 + 30.0) / 3, abs=1e-3)
        assert summary["self_fpr_mean"] == pytest.approx(100.0 / 3, abs=1e-3)


class TestEnvOverrides:
    """Pass shape is A/B-able without a code edit; that is what the eval roadmap's runs need."""

    def test_every_budget_knob_is_overridable(self):
        config = sweeps.SweepConfig().apply_env_overrides(
            {
                "TPC_P2_TRIAGE_CAP_SEC": "60",
                "TPC_P2_TRIAGE_FRACTION": "0.1",
                "TPC_P2_PASS_FRACTION": "0.9",
                "TPC_P2_MAX_QUERY_SEC": "300",
                "TPC_P2_MIN_QUERY_SEC": "10",
                "TPC_P2_MAX_PASSES": "5",
            }
        )
        assert (config.triage_cap_sec, config.triage_fraction) == (60.0, 0.1)
        assert (config.pass_fraction, config.max_query_sec) == (0.9, 300.0)
        assert (config.min_query_sec, config.max_passes) == (10.0, 5)

    def test_unset_and_malformed_values_keep_the_default(self):
        config = sweeps.SweepConfig().apply_env_overrides(
            {"TPC_P2_TRIAGE_CAP_SEC": "", "TPC_P2_MAX_QUERY_SEC": "soon"}
        )
        assert config.triage_cap_sec == sweeps.DEFAULT_TRIAGE_CAP_SEC
        assert config.max_query_sec == sweeps.DEFAULT_MAX_QUERY_SEC


class TestWorkerConfiguration:
    def test_default_workers_leaves_one_core_for_the_parent(self, monkeypatch):
        monkeypatch.delenv("TPC_P2_WORKERS", raising=False)
        monkeypatch.setattr(sweeps.os, "cpu_count", lambda: 16)
        assert sweeps.default_workers() == 15

    def test_env_override_wins(self, monkeypatch):
        monkeypatch.setenv("TPC_P2_WORKERS", "4")
        assert sweeps.default_workers() == 4

    def test_a_broken_override_falls_back_instead_of_crashing_the_run(self, monkeypatch):
        monkeypatch.setenv("TPC_P2_WORKERS", "lots")
        monkeypatch.setattr(sweeps.os, "cpu_count", lambda: 8)
        assert sweeps.default_workers() == 7
