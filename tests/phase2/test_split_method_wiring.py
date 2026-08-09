"""Solving and scoring must name the same split and the same results directory.

The failure this module pins was found on the packaged ``v2`` archive, and it is the kind that
survives review because every part of it succeeds:

``solve_script_with_harness.py --split tpc_phase2_test`` wrote 150 plans to
``results/phase2_e2e_tpc_phase2_test/`` and reported ``self_overall_mean: 90.95``. The obvious
next command, ``eval_tpc.py --split tpc_phase2_test``, looked in ``results/TPCAgent_TPCLLM_en/``
-- its own unrelated default -- found nothing, mapped every absent plan file to ``{}``, and
printed a complete, confident scorecard of ``0.0`` for every metric. Nothing raised, nothing
warned, and the output looks exactly like a solver that produces nothing but garbage.

Two more defaults compounded it: the two entry points defaulted to *different* splits (``easy``
vs ``tpc_phase1``), and ``easy``'s query JSON is not in the archive at all, so an argument-less
solve died inside the loader with a resolution error naming a split nobody asked for.

The organizers always pass both flags, so none of this can affect the submitted run. It affects
every human who checks the archive before uploading it, which is what these tests protect.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

import solve_script_with_harness as hb

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def eval_tpc():
    """Import ``eval_tpc.py`` as a module.

    It lives at the repository root and is normally run as a script; ``__main__``-guarded, so
    importing it executes only the helper definitions this module tests.
    """
    spec = importlib.util.spec_from_file_location(
        "eval_tpc_under_test", PROJECT_ROOT / "eval_tpc.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_solver_default_method_agrees_with_the_harness(eval_tpc):
    """``eval_tpc`` re-derives the harness's default method name; the two must not drift.

    ``eval_tpc`` copies the rule rather than importing it (importing the harness pulls in the
    whole solver stack for one string), so this is the seam that keeps the copy honest. If it
    ever fails, the auto-resolution below starts pointing at a directory the solver never wrote.
    """
    for split in [
        "tpc_phase2_test",
        "tpc_phase2_familiar_100_val",
        "held out 2026",
        "weird/name",
        "___",
    ]:
        assert eval_tpc._solver_default_method(split) == hb.default_method(
            None, split, hb.TPC_HARNESS
        ), split


def test_omitted_method_resolves_to_the_split_the_solver_wrote(eval_tpc, tmp_path, monkeypatch):
    """The user's exact broken command must find the plans instead of scoring 0.0."""
    monkeypatch.setattr(eval_tpc, "project_root_path", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    (tmp_path / "results" / "phase2_e2e_tpc_phase2_test").mkdir(parents=True)

    resolved = eval_tpc._resolve_method_dir(
        "TPCAgent_TPCLLM_en", "en", splits="tpc_phase2_test", explicit=False
    )
    assert resolved == "phase2_e2e_tpc_phase2_test"


def test_explicit_method_is_never_redirected(eval_tpc, tmp_path, monkeypatch):
    """An explicit ``--method`` is an instruction, not a hint.

    Redirecting it would silently score a *different* run than the one that was named -- the same
    class of bug as the one being fixed, only harder to notice because the caller was specific.
    """
    monkeypatch.setattr(eval_tpc, "project_root_path", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    (tmp_path / "results" / "phase2_e2e_tpc_phase2_test").mkdir(parents=True)

    resolved = eval_tpc._resolve_method_dir(
        "some_other_run", "en", splits="tpc_phase2_test", explicit=True
    )
    assert resolved == "some_other_run_en"


def test_no_plans_at_all_is_an_error_not_a_zero(eval_tpc, tmp_path, monkeypatch):
    monkeypatch.setattr(eval_tpc, "project_root_path", str(tmp_path))
    (tmp_path / "results" / "phase2_e2e_s").mkdir(parents=True)

    with pytest.raises(SystemExit) as excinfo:
        eval_tpc.check_results_present(
            ["a", "b"], {"a": {}, "b": {}}, "s", "wrong_dir", allow_missing=False
        )

    message = str(excinfo.value)
    # The message has to carry the fix, not just the complaint: the directory searched, what
    # actually exists, and the paired commands that would have worked.
    assert "wrong_dir" in message
    assert "phase2_e2e_s" in message
    assert "--method" in message
    assert "--allow_missing_results" in message


def test_allow_missing_results_keeps_the_old_behaviour(eval_tpc, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(eval_tpc, "project_root_path", str(tmp_path))
    eval_tpc.check_results_present(
        ["a", "b"], {"a": {}, "b": {}}, "s", "wrong_dir", allow_missing=True
    )
    assert "warning" in capsys.readouterr().out


def test_partial_results_warn_and_continue(eval_tpc, tmp_path, monkeypatch, capsys):
    """A run with gaps still scores -- that is a legitimate partial evaluation -- but says so."""
    monkeypatch.setattr(eval_tpc, "project_root_path", str(tmp_path))
    eval_tpc.check_results_present(
        ["a", "b", "c"], {"a": {"itinerary": []}, "b": {}, "c": {}}, "s", "m",
        allow_missing=False,
    )
    out = capsys.readouterr().out
    assert "plans=1/3" in out
    assert "2 of 3 queries have no plan" in out


def test_solve_without_a_split_refuses_instead_of_guessing():
    """No ``--split`` must not silently become ``easy``, a split this archive cannot load."""
    with pytest.raises(SystemExit) as excinfo:
        hb.resolve_split_argument(None, None, Path("agent_env/config.toml"))

    message = str(excinfo.value)
    assert "no split selected" in message
    assert "--method <method> --split <split>" in message
    assert "easy" not in message.split("nameable in this tree")[0]


def test_split_argument_precedence():
    """CLI beats config beats nothing, and an empty string is not a selection."""
    config_path = Path("agent_env/config.toml")
    assert hb.resolve_split_argument("cli", "cfg", config_path) == "cli"
    assert hb.resolve_split_argument(None, "cfg", config_path) == "cfg"
    assert hb.resolve_split_argument("  ", "cfg", config_path) == "cfg"


def test_available_splits_lists_names_without_the_suboptimal_sidecars():
    names = hb.available_splits()
    assert "tpc_phase2_test" in names
    assert not any(name.endswith("_suboptimal") for name in names)


def test_unresolvable_split_error_stays_readable():
    """Upstream's resolver names every missing UID; a 300-query split buried the actionable line."""
    with pytest.raises(RuntimeError) as excinfo:
        hb.load_queries_with_lang("definitely_not_a_split_x9", "en")

    message = str(excinfo.value)
    assert "did not resolve in either language" in message
    assert "nameable in this tree" in message
    # Each embedded loader error is abbreviated, so the whole message stays scannable.
    assert len(message) < 4000, len(message)


@pytest.mark.integration
def test_solve_prints_the_matching_eval_command():
    """The end of a solve must hand over the exact scoring command for the run it just wrote."""
    completed = subprocess.run(
        [
            sys.executable,
            "agent_env/scripts/solve_script_with_harness.py",
            "--split", "tpc_phase2_familiar_100_val",
            "--method", "wiring_smoke",
            "--limit", "1",
            "--total-budget-sec", "120",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert completed.returncode == 0, completed.stderr[-2000:]
    assert (
        "python eval_tpc.py --splits tpc_phase2_familiar_100_val --method wiring_smoke"
        in completed.stdout
    )
