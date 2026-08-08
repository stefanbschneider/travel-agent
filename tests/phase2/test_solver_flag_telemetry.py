"""The per-query telemetry must name the promoted deterministic solver flags.

Those passes (``TPC_PIN_TIMED_WINDOWS``, ``TPC_WINDOW_ANCHOR``, ``TPC_COMMONSENSE_FIRST``,
``TPC_SOLVE_CONVERGE_PATIENCE``) are read from the environment by ``TPCAgent``, not carried on
``Flags``, so before this snapshot a recorded row could not say which of them ran. The ledger's
comparability rule requires exactly that, and after R8 promoted ``TPC_WINDOW_ANCHOR`` it is also the
only way to tell a submission archive running the post-R8 configuration from one silently running
the pre-R8 one.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(PROJECT_ROOT), str(PROJECT_ROOT / "agent_env" / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from chinatravel.agent.phase2.orchestrator import (  # noqa: E402
    CANDIDATE_SOLVER_FLAGS,
    PROMOTED_SOLVER_FLAGS,
    RECORDED_SOLVER_FLAGS,
    _solver_flag_snapshot,
)


def test_unset_environment_reports_the_library_floor():
    assert _solver_flag_snapshot({}) == {
        "pin_timed_windows": False,
        "window_anchor": False,
        "commonsense_first": False,
        "solve_converge_patience": None,
        "window_push": False,
        "window_insert": False,
        "window_push_max_min": None,
        "window_relocate_day": False,
    }


def test_harness_promotion_is_visible_in_the_snapshot():
    env = {
        "TPC_PIN_TIMED_WINDOWS": "1",
        "TPC_WINDOW_ANCHOR": "1",
        "TPC_COMMONSENSE_FIRST": "1",
        "TPC_SOLVE_CONVERGE_PATIENCE": "15",
        "TPC_WINDOW_PUSH": "1",
        "TPC_WINDOW_INSERT": "1",
    }
    assert _solver_flag_snapshot(env) == {
        "pin_timed_windows": True,
        "window_anchor": True,
        "commonsense_first": True,
        "solve_converge_patience": "15",
        "window_push": True,
        "window_insert": True,
        "window_push_max_min": None,
        "window_relocate_day": False,
    }


def test_a_window_push_max_min_override_is_visible_in_the_snapshot():
    """TPC_WINDOW_PUSH_MAX_MIN stays a candidate after P14 promoted TPC_WINDOW_PUSH/
    TPC_WINDOW_INSERT -- it is a bound on the pass, not a pass of its own, and R14 measured it at
    its code default (30 min), so it is not part of the harness-default environment."""
    env = {
        "TPC_PIN_TIMED_WINDOWS": "1",
        "TPC_WINDOW_ANCHOR": "1",
        "TPC_COMMONSENSE_FIRST": "1",
        "TPC_SOLVE_CONVERGE_PATIENCE": "15",
        "TPC_WINDOW_PUSH": "1",
        "TPC_WINDOW_INSERT": "1",
    }
    snapshot = _solver_flag_snapshot(env)
    assert snapshot["window_push_max_min"] is None  # bound left at the code default (30 min)
    assert _solver_flag_snapshot({**env, "TPC_WINDOW_PUSH_MAX_MIN": "45"})[
        "window_push_max_min"
    ] == "45"


def test_snapshot_covers_exactly_what_the_harness_promotes(monkeypatch):
    """Drift guard: a flag promoted to harness-default-on but absent from the snapshot would make
    every later row silent about the configuration that produced it."""
    import solve_phase2 as runner

    for name in PROMOTED_SOLVER_FLAGS:
        monkeypatch.delenv(name, raising=False)
    before = {k for k in os.environ if k.startswith("TPC_")}

    # apply_deterministic_solver_defaults() writes os.environ directly (mirroring the shipped
    # harness), not through monkeypatch. monkeypatch.delenv only records an undo action for a key
    # it has already seen absent-then-set -- calling delenv *after* the write would make monkeypatch
    # treat the just-written value as "the original" and restore it at teardown, leaking a promoted
    # flag into every later test in the process. Restore with plain os.environ instead.
    try:
        runner.apply_deterministic_solver_defaults()

        promoted = {k for k in os.environ if k.startswith("TPC_")} - before
        assert promoted == set(PROMOTED_SOLVER_FLAGS)
    finally:
        for name in PROMOTED_SOLVER_FLAGS:
            os.environ.pop(name, None)


def test_candidate_flags_are_recorded_but_never_promoted():
    """A screened-but-unpromoted flag belongs in exactly one of the two tuples, and both are
    recorded. Promotion means *moving* it, so this fails if it is ever duplicated or dropped."""
    assert not set(PROMOTED_SOLVER_FLAGS) & set(CANDIDATE_SOLVER_FLAGS)
    assert set(RECORDED_SOLVER_FLAGS) == set(PROMOTED_SOLVER_FLAGS) | set(CANDIDATE_SOLVER_FLAGS)
    assert set(_solver_flag_snapshot({})) == {
        name[len("TPC_"):].lower() for name in RECORDED_SOLVER_FLAGS
    }


def test_off_values_match_the_agents_own_off_set():
    """``"0"``, ``"false"``, ``"False"`` and ``""`` are off for the agent, so they must read off
    here too -- otherwise a flags-off A/B arm would be recorded as flags-on."""
    for value in ("0", "false", "False", ""):
        assert _solver_flag_snapshot({"TPC_WINDOW_ANCHOR": value})["window_anchor"] is False, value
    for value in ("1", "true", "yes", "on"):
        assert _solver_flag_snapshot({"TPC_WINDOW_ANCHOR": value})["window_anchor"] is True, value


def test_solve_phase2_telemetry_carries_the_snapshot(monkeypatch, fast_solve_fn):
    """End of the wire: the key has to reach the telemetry dict a row is built from."""
    from chinatravel.agent.phase2.orchestrator import Flags, solve_phase2

    monkeypatch.setenv("TPC_WINDOW_ANCHOR", "1")
    query = {"uid": "u1", "start_city": "A", "target_city": "B", "days": 1, "people_number": 1,
             "nature_language": "one day in B"}

    _plan, telemetry = solve_phase2(
        query, budget_sec=5.0, flags=Flags(), solve_fn=fast_solve_fn
    )

    assert telemetry["solver_flags"]["window_anchor"] is True
