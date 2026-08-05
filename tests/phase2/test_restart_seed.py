"""The multi-start search's RNG seed must depend only on (uid, salt).

Before 2026-08-05 it came from the built-in ``hash()``, which Python salts per interpreter unless
``PYTHONHASHSEED`` is pinned. Every worker process therefore drew a different restart sequence:
runs were irreproducible, and same-config runs differed by up to ``1.04`` overall. The
cross-process test below is the one that actually pins the fix -- an in-process test passes even
with the old implementation.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
# TPCAgent uses internal ``from agent.base import ...`` imports, which require the ``chinatravel``
# directory on sys.path.
for _p in (str(PROJECT_ROOT), str(PROJECT_ROOT / "chinatravel")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from chinatravel.agent.tpc_agent.tpc_agent import restart_seed  # noqa: E402

_SEED_IN_SUBPROCESS = """
import sys
sys.path.insert(0, {root!r})
sys.path.insert(0, {agent_root!r})
from chinatravel.agent.tpc_agent.tpc_agent import restart_seed
print(restart_seed({uid!r}, {salt!r}))
"""


def seed_in_fresh_process(uid: str, salt: str) -> str:
    code = _SEED_IN_SUBPROCESS.format(
        root=str(PROJECT_ROOT),
        agent_root=str(PROJECT_ROOT / "chinatravel"),
        uid=uid,
        salt=salt,
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True, cwd=PROJECT_ROOT
    )
    return out.stdout.strip()


def test_same_uid_and_salt_give_the_same_seed_in_separate_processes():
    """The property the old hash()-based seed did not have. Two fresh interpreters, no pinned
    PYTHONHASHSEED -- the workers a real run spawns."""
    first = seed_in_fresh_process("phase2_familiar_20250321012512564936_00022", "0")
    second = seed_in_fresh_process("phase2_familiar_20250321012512564936_00022", "0")
    assert first == second


def test_a_different_salt_gives_a_different_seed():
    """What TPC_SEED_SALT is for: a distinct salt must explore a distinct restart sequence."""
    base = seed_in_fresh_process("phase2_familiar_20250321012512564936_00022", "0")
    salted = seed_in_fresh_process("phase2_familiar_20250321012512564936_00022", "1")
    assert base != salted


def test_a_different_uid_gives_a_different_seed():
    assert restart_seed("uid-a", "0") != restart_seed("uid-b", "0")


def test_seed_is_in_random_seed_range():
    for uid in ("", "uid-a", "phase2_familiar_20250321012512564936_00022"):
        seed = restart_seed(uid, "0")
        assert isinstance(seed, int)
        assert 0 <= seed <= 0xFFFFFFFF


def test_non_string_salt_does_not_crash():
    """``seed_salt`` arrives from the environment, but callers may pass an int."""
    assert restart_seed("uid-a", 3) == restart_seed("uid-a", "3")
