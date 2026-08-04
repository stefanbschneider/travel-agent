#!/usr/bin/env python
"""Assemble a Phase 2 harness submission zip.

Phase 1 submits predictions (``scripts/assemble_submission.py``); Phase 2 submits **the system**:
"agent code, prompts, dependencies, documentation, and all files required to run your system"
(organizers' 2026-08-03 advancement email). The organizers then run exactly

    python agent_env/scripts/solve_script_with_harness.py --split <split>

inside the unpacked archive, with no other flags.

What this script does:

1. resolves the next version from ``phase2-v<N>`` git tags -- Phase 2 numbering restarts at ``v1``
   and is tracked in its own tag namespace, so it never collides with Phase 1's ``v<N>`` tags;
2. copies the **tracked** files at the current commit (never the working tree's gitignored
   ``.env`` / ``agent_env/config.toml`` / ``.venv``), minus development-only trees that are not
   needed to run the system (see ``EXCLUDED_PREFIXES``);
3. writes ``SUBMISSION.md`` (install + run, verbatim commands) and ``submission_manifest.json``
   (commit, evaluator parity point, file count) into the archive root;
4. zips it as ``submissions/{team}_v{N}.zip`` with archive root ``{team}_v{N}/``, matching the
   confirmed ``{TeamName}_v{x}.zip`` naming;
5. **verifies** the packaged tree by unpacking it into a temporary directory and running the
   organizers' exact command shape there on one query, with ``opencode``/``codex`` unreachable --
   the submission is only as good as what the archive alone can do.

It never uploads anything. Submission stays a manual step at the portal in
``docs/reference/competition.md``.

Usage:
    python scripts/assemble_phase2_submission.py --dry-run
    python scripts/assemble_phase2_submission.py
    python scripts/assemble_phase2_submission.py --version v2 --no-verify
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEAM = "fabiundstefan"
TAG_PREFIX = "phase2-v"
SUBMISSION_PORTAL = "https://box.nju.edu.cn/u/d/5a1a84297f4b43eda42f/"

# Tracked trees that the system does not need to run. Everything else tracked at HEAD ships:
# the solver, the agent environment, the evaluator, the English database, tests, docs, Makefile.
EXCLUDED_PREFIXES = (
    "results/",        # 60 MB of Phase 1 predictions and the Phase 2 baseline ledger
    "submissions/",    # previous archives
    "report/",         # the technical report is submitted separately as a PDF
    "images/",         # README illustrations from upstream
    "slurm/",          # our own HPC job profiles
    "TPC@AIC2025/",    # unrelated prior-competition material
    "docs/archive/",   # superseded plans and chronology
    ".github/",        # our CI
)

# Belt and braces on top of the exclusions above. `.gitignore` lists `.env`, but this repository
# *tracks* one anyway (a tracked path beats a gitignore rule), so filtering by gitignore status
# alone would have shipped it. Anything matching these never enters an archive, whatever its git
# status, and `stage()` re-checks before writing.
SECRET_PATH_PATTERNS = (
    re.compile(r"(^|/)\.env($|\.)"),          # .env, .env.local, .env.example, ...
    re.compile(r"(^|/)config\.toml$"),        # agent_env/config.toml carries API keys
    re.compile(r"(^|/)\.netrc$"),
    re.compile(r"(^|/)[^/]*\.pem$"),
    re.compile(r"(^|/)id_(rsa|ed25519)$"),
)


def is_secret_path(path: str) -> bool:
    return any(pattern.search(path) for pattern in SECRET_PATH_PATTERNS)

# Without these the archive cannot run; a missing one is a packaging bug, not a warning.
REQUIRED_FILES = (
    "agent_env/scripts/solve_script_with_harness.py",  # the confirmed entry point
    "agent_env/scripts/solve_phase2.py",
    "chinatravel/agent/phase2/orchestrator.py",
    "chinatravel/agent/tpc_agent/tpc_agent.py",
    "chinatravel/evaluation/output_schema.json",
    "chinatravel/data/load_datasets.py",
    "parse_constraints.py",
    "requirements-submission.txt",
    "pyproject.toml",
    "README.md",
)
# The English sandbox database must ship: the solver grounds every fact in it.
REQUIRED_DIR_PREFIXES = ("chinatravel/environment/database_en/",)

SUBMISSION_README = """# {team} -- TPC @ IJCAI 2026, Phase 2 submission {version}

Self-contained harness for the ChinaTravel Travel Planning Challenge, Phase 2.
Built from commit `{commit}` on `{branch}`.

## Install (setup, not part of the timed run)

Python 3.12. From this directory:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-submission.txt
```

`uv` works the same way, if preferred:

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements-submission.txt
```

That is the whole installation: {dep_count} packages from PyPI, no extra index, no system
packages, no GPU stack, no model download. The travel database ships inside this archive at
`chinatravel/environment/database_en/`, so there is nothing to fetch.

## Run

```bash
.venv/bin/python agent_env/scripts/solve_script_with_harness.py --split <split>
```

That single command is the whole system. It:

- loads the split, strips every oracle verifier field (`hard_logic*`) before the agent path sees
  the query, and solves each query with the deterministic `TPCAgent` **in-process**;
- makes **zero LLM calls** and **zero network calls**, and spawns no subprocess -- the LLM-backed
  flags are off by default and no external CLI is invoked;
- keeps the whole run inside a {total_budget_hours:.0f}-hour wall-clock envelope by giving each
  query the smaller of its per-query budget and its fair share of the time remaining, so a slow
  query cannot starve the rest of the split;
- writes each plan to `results/phase2_e2e_<split>/<uid>.json`, and per-query telemetry plus a
  split summary under `agent_env/runs/phase2_e2e_<split>/`.

Optional overrides (not needed for evaluation): `--budget-sec` (per-query cap),
`--total-budget-sec` (whole-run envelope; `0` disables), `--limit`, `--resume`,
`--harness opencode|codex` (an external-CLI baseline, never the default).

## Layout

| Path | What |
| --- | --- |
| `agent_env/scripts/solve_script_with_harness.py` | the entry point above |
| `agent_env/` | the no-oracle environment wrapper and its tools |
| `chinatravel/agent/phase2/` | stage orchestration, budgets, fallback |
| `chinatravel/agent/tpc_agent/` | the deterministic planner and CP-SAT tier |
| `chinatravel/environment/` | world facts (POIs, transport, prices) and `WorldEnv` |
| `chinatravel/evaluation/`, `chinatravel/symbol_verification/` | the official evaluator, unmodified |
| `docs/`, `README.md` | method, evaluation methodology, and competition reference |
| `tests/` | unit tests (`python -m pytest`) |

Evaluator parity point: upstream `LAMDA-NeSy/ChinaTravel` `main` at `{evaluator_parity}`.
"""


def run_git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()


def next_version() -> str:
    """Next ``phase2-v<N>``. Phase 2 numbering restarts at v1, independent of Phase 1's tags."""
    tags = run_git("tag", "--list", f"{TAG_PREFIX}[0-9]*").split()
    numbers = [
        int(tag[len(TAG_PREFIX):])
        for tag in tags
        if re.fullmatch(rf"{re.escape(TAG_PREFIX)}\d+", tag)
    ]
    return f"v{max(numbers) + 1 if numbers else 1}"


def tracked_files() -> list[str]:
    # -z, not plain `ls-files`: the Chinese sandbox database has non-ASCII filenames, which git
    # otherwise renders as quoted C-style escapes that no filesystem call can open.
    raw = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    paths = [p for p in raw.split("\0") if p]
    return sorted(
        p for p in paths if not p.startswith(EXCLUDED_PREFIXES) and not is_secret_path(p)
    )


def evaluator_parity_sha() -> str:
    """Read the parity marker from the recorder rather than duplicating it here."""
    source = (ROOT / "scripts" / "phase2_record_baseline.py").read_text(encoding="utf-8")
    match = re.search(r'EVALUATOR_PARITY_SHA\s*=\s*"([^"]+)"', source)
    return match.group(1) if match else "unknown"


def dependency_count() -> int:
    lines = (ROOT / "requirements-submission.txt").read_text(encoding="utf-8").splitlines()
    return sum(1 for line in lines if line.strip() and not line.startswith("#"))


def check_required(paths: list[str]) -> list[str]:
    present = set(paths)
    missing = [p for p in REQUIRED_FILES if p not in present]
    for prefix in REQUIRED_DIR_PREFIXES:
        if not any(p.startswith(prefix) for p in paths):
            missing.append(prefix + "*")
    return missing


def stage(paths: list[str], out_dir: Path, *, version: str, team: str) -> dict:
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    leaked = [p for p in paths if is_secret_path(p)]
    if leaked:  # unreachable via tracked_files(); guards a hand-built path list
        raise SystemExit(f"refusing to package credential-bearing paths: {leaked}")

    total_bytes = 0
    for rel in paths:
        src = ROOT / rel
        dst = out_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        total_bytes += dst.stat().st_size

    try:
        commit = run_git("rev-parse", "HEAD")
        branch = run_git("rev-parse", "--abbrev-ref", "HEAD")
    except subprocess.CalledProcessError:  # pragma: no cover - a git checkout is a precondition
        commit, branch = "unknown", "unknown"

    sys.path.insert(0, str(ROOT / "agent_env" / "scripts"))
    import solve_phase2  # noqa: PLC0415 - needs the sys.path entry above

    readme = SUBMISSION_README.format(
        team=team,
        version=version,
        commit=commit,
        branch=branch,
        dep_count=dependency_count(),
        total_budget_hours=solve_phase2.DEFAULT_TOTAL_BUDGET_SEC / 3600.0,
        evaluator_parity=evaluator_parity_sha(),
    )
    (out_dir / "SUBMISSION.md").write_text(readme, encoding="utf-8")

    manifest = {
        "team": team,
        "phase": 2,
        "version": version,
        "commit": commit,
        "branch": branch,
        "entry_point": "python agent_env/scripts/solve_script_with_harness.py --split <split>",
        "install": "pip install -r requirements-submission.txt",
        "python": ">=3.12",
        "file_count": len(paths),
        "bytes": total_bytes,
        "evaluator_parity": evaluator_parity_sha(),
        "llm_calls_by_default": 0,
        "total_budget_sec": solve_phase2.DEFAULT_TOTAL_BUDGET_SEC,
    }
    (out_dir / "submission_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def write_zip(out_dir: Path, zip_path: Path, name: str) -> int:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(out_dir.rglob("*")):
            if path.is_file():
                zf.write(path, arcname=str(Path(name) / path.relative_to(out_dir)))
                count += 1
    return count


def verify_archive(zip_path: Path, name: str, *, split: str, budget_sec: float) -> None:
    """Unpack the archive somewhere else and run the organizers' command shape inside it.

    Deliberately hostile: a stripped ``PATH`` so neither ``opencode`` nor ``codex`` could be
    found, no API keys, and a temporary ``HOME``. Only the archive's own contents may contribute.
    """
    with tempfile.TemporaryDirectory(prefix="tpc_phase2_verify_") as tmp:
        tmp_path = Path(tmp)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(tmp_path)
        pkg = tmp_path / name
        env = {
            "PATH": "/usr/bin:/bin",
            "HOME": str(tmp_path),
            "PYTHONIOENCODING": "utf-8",
        }
        cmd = [
            sys.executable,
            "agent_env/scripts/solve_script_with_harness.py",
            "--split",
            split,
            "--limit",
            "1",
            "--budget-sec",
            str(budget_sec),
        ]
        print(f"verifying: (cd {pkg} && {' '.join(cmd)})")
        completed = subprocess.run(
            cmd, cwd=pkg, env=env, capture_output=True, text=True, timeout=1800
        )
        if completed.returncode != 0:
            raise SystemExit(
                "verification FAILED: the packaged archive could not run the confirmed command\n"
                f"--- stdout ---\n{completed.stdout[-3000:]}\n"
                f"--- stderr ---\n{completed.stderr[-3000:]}"
            )

        plans = sorted((pkg / "results").rglob("*.json"))
        plans = [p for p in plans if p.parent.name.startswith("phase2_e2e_")]
        if not plans:
            raise SystemExit("verification FAILED: the run produced no plan file")
        plan = json.loads(plans[0].read_text(encoding="utf-8"))
        if not isinstance(plan.get("itinerary"), list) or not plan["itinerary"]:
            raise SystemExit(f"verification FAILED: {plans[0].name} has no itinerary")

        telemetry_files = sorted((pkg / "agent_env" / "runs").rglob("telemetry.json"))
        if not telemetry_files:
            raise SystemExit("verification FAILED: no telemetry written")
        telemetry = json.loads(telemetry_files[0].read_text(encoding="utf-8"))
        if telemetry.get("llm_backend") != "none":
            raise SystemExit(
                f"verification FAILED: llm_backend is {telemetry.get('llm_backend')!r}, "
                "the packaged default must make zero LLM calls"
            )
        print(
            f"verification OK: {plans[0].name} has {len(plan['itinerary'])} day(s), "
            f"llm_backend=none, valid_output={telemetry.get('valid_output')}"
        )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--version",
        default=None,
        help="submission version like v2; defaults to the next phase2-v<N> git tag",
    )
    ap.add_argument("--team", default=DEFAULT_TEAM, help="registered team name used in the zip name")
    ap.add_argument("--dry-run", action="store_true", help="report what would ship; write nothing")
    ap.add_argument("--no-verify", action="store_true", help="skip the unpack-and-run check")
    ap.add_argument(
        "--verify-split",
        default="tpc_phase2_familiar_100_val",
        help="split the verification run uses (one query from it)",
    )
    ap.add_argument("--verify-budget-sec", type=float, default=90.0)
    ap.add_argument(
        "--allow-dirty",
        action="store_true",
        help="package a working tree with uncommitted changes (not reproducible)",
    )
    args = ap.parse_args()

    version = args.version or next_version()
    if not re.fullmatch(r"v\d+", version):
        ap.error("version must look like v<number>, for example v2")

    dirty = run_git("status", "--porcelain")
    if dirty and not args.allow_dirty and not args.dry_run:
        print(
            "refusing to package a dirty working tree (the archive would not match any commit):\n"
            f"{dirty}\ncommit the changes, or pass --allow-dirty.",
            file=sys.stderr,
        )
        return 1

    paths = tracked_files()
    missing = check_required(paths)
    if missing:
        print("refusing to package: required files missing from the archive:", file=sys.stderr)
        for path in missing:
            print(f"  - {path}", file=sys.stderr)
        return 1

    name = f"{args.team}_{version}"
    total_bytes = sum(os.path.getsize(ROOT / p) for p in paths)
    print(f"phase 2 submission {name}: {len(paths)} files, {total_bytes / 1e6:.1f} MB unpacked")

    if args.dry_run:
        by_top: dict[str, int] = {}
        for path in paths:
            top = path.split("/")[0]
            by_top[top] = by_top.get(top, 0) + os.path.getsize(ROOT / path)
        for top, size in sorted(by_top.items(), key=lambda kv: -kv[1]):
            print(f"  {size / 1e6:8.2f} MB  {top}")
        print("(dry run: nothing written)")
        return 0

    out_dir = ROOT / "submissions" / name
    manifest = stage(paths, out_dir, version=version, team=args.team)
    zip_path = ROOT / "submissions" / f"{name}.zip"
    count = write_zip(out_dir, zip_path, name)
    print(
        f"wrote {zip_path} ({count} entries, {zip_path.stat().st_size / 1e6:.1f} MB compressed) "
        f"from commit {manifest['commit'][:12]}"
    )

    if args.no_verify:
        print("skipped verification (--no-verify): do not submit an unverified archive")
    else:
        verify_archive(
            zip_path, name, split=args.verify_split, budget_sec=args.verify_budget_sec
        )

    print("\nnext steps (manual, nothing was uploaded):")
    print(f"  1. upload {zip_path.name} to {SUBMISSION_PORTAL}")
    print("  2. upload the technical report PDF (report/, named after the team) to the same portal")
    print(f"  3. record the submission: git tag {TAG_PREFIX}{version[1:]} && git push origin {TAG_PREFIX}{version[1:]}")
    print("  note: the organizers evaluate at most two versions per team; the higher score counts.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
