"""A worker must not die because another worker created the shared log directory first.

The Phase 2 sweep builds one ``TPCAgent`` per worker process and every one of them points at the
same ``log_dir`` (``cache/phase2_solve``). ``BaseAgent`` used to check-then-create it, so on a
fresh checkout -- exactly what the organizers unpack -- all workers saw it missing, one created
it, and the rest raised ``FileExistsError``. That happens inside the ``ProcessPoolExecutor``
*initializer*, which breaks the entire pool: the run then emits the pre-written empty fallback for
every query in the split.

Caught by ``scripts/assemble_phase2_submission.py --verify-budget-sec``, which unpacks the archive
into a fresh directory and is therefore the only check that exercised the cold-cache path.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
# BaseAgent uses internal ``from agent...`` imports, which need ``chinatravel`` on sys.path.
for _p in (str(PROJECT_ROOT), str(PROJECT_ROOT / "chinatravel")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agent.base import BaseAgent  # noqa: E402


class _StubLLM:
    """BaseAgent reads ``backbone_llm.name`` after the log-dir step; nothing here calls it."""

    name = "stub"


def test_agent_survives_losing_the_log_dir_creation_race(tmp_path, monkeypatch):
    """Deterministic stand-in for the real race: the directory appears between the existence
    check and the ``makedirs`` call, which is what every worker but the winner observed."""
    log_dir = tmp_path / "cache" / "phase2_solve"
    log_dir.mkdir(parents=True)

    real_exists = os.path.exists

    def exists_but_lies_about_the_log_dir(path):
        if str(path) == str(log_dir):
            return False  # the loser's view: still absent when it looked
        return real_exists(path)

    monkeypatch.setattr(os.path, "exists", exists_but_lies_about_the_log_dir)

    agent = BaseAgent(name="race", log_dir=str(log_dir), backbone_llm=_StubLLM())
    assert agent.log_dir == str(log_dir)


def test_agent_still_creates_a_missing_log_dir(tmp_path):
    """The winner's path, and the reason the directory exists at all."""
    log_dir = tmp_path / "cache" / "phase2_solve"
    assert not log_dir.exists()

    BaseAgent(name="winner", log_dir=str(log_dir), backbone_llm=_StubLLM())
    assert log_dir.is_dir()


def test_repeated_agents_against_one_cold_log_dir_all_survive(tmp_path):
    """Sequential on purpose -- a genuinely concurrent version would be flaky (measured at roughly
    one hit in four, see ``test_cold_start.py``). This pins the observable outcome instead: the
    first agent creates the shared directory and every later one tolerates finding it there, which
    is what each worker process does after the winner has created it."""
    log_dir = tmp_path / "cache" / "phase2_solve"
    agents = [BaseAgent(name=f"worker-{i}", log_dir=str(log_dir), backbone_llm=_StubLLM()) for i in range(5)]

    assert log_dir.is_dir()
    assert all(a.log_dir == str(log_dir) for a in agents)
