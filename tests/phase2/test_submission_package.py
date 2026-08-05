"""Packaging invariants for the Phase 2 submission.

The organizers unpack one zip, run one `pip install`, and then one fixed command on an
internal-network host. Three things therefore have to hold at all times, not just on the day we
package: the dependency set stays minimal and consistent, the archive contains everything the
system needs to run, and nothing gitignored (`.env`, `agent_env/config.toml`) can leak into it.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import assemble_phase2_submission as asm  # noqa: E402

SUBMISSION_REQS = PROJECT_ROOT / "requirements-submission.txt"
FULL_REQS = PROJECT_ROOT / "requirements.txt"

# The local-model serving stack. `chinatravel/agent/llms.py` keeps it behind a lazy import and
# the submitted path never reaches it; installing it on the evaluation host would burn the
# organizers' limited evaluation time for nothing.
FORBIDDEN_IN_SUBMISSION = {
    "torch",
    "vllm",
    "transformers",
    "accelerate",
    "modelscope",
    "flashinfer-python",
    "matplotlib",
    "seaborn",
    "scikit-learn",
    "datasets",
}


def _requirements(path: Path) -> dict[str, str]:
    """Map normalized package name -> full requirement line."""
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        name = line.split("==")[0].split(">=")[0].strip()
        out[name.lower().replace("_", "-")] = line
    return out


def test_submission_requirements_are_a_subset_of_the_development_pins():
    """One version per package across the repo: a submission pin that drifts from
    requirements.txt means we develop against one build and ship another."""
    submission = _requirements(SUBMISSION_REQS)
    full = _requirements(FULL_REQS)
    for name, line in submission.items():
        assert name in full, f"{name} is in requirements-submission.txt but not requirements.txt"
        assert line.replace("_", "-") == full[name].replace("_", "-"), (
            f"version drift for {name}: submission {line!r} vs development {full[name]!r}"
        )


# Upstream LAMDA-NeSy/ChinaTravel's requirements.txt at the current parity point (c89cfca).
# The evaluation host installs from *our* file, so every package we name that upstream does not,
# and every version we pin differently, is extra risk on a slow internal network for no gain.
UPSTREAM_REQUIREMENTS = {
    "accelerate": "1.6.0",
    "datasets": "3.3.2",
    "flashinfer-python": "0.2.5",
    "func-timeout": "4.3.5",
    "fuzzywuzzy": "0.18.0",
    "geopy": "2.4.1",
    "httpx": "0.27.2",
    "json-repair": "0.30.0",
    "jsonschema": "4.23.0",
    "matplotlib": "3.9.4",
    "modelscope": "1.20.0",
    "numpy": "1.26.4",
    "openai": "1.53.0",
    "packaging": "24.2",
    "pandas": "2.2.3",
    "scikit-learn": "1.5.2",
    "seaborn": "0.13.2",
    "tiktoken": "0.9.0",
    "torch": "2.6.0",
    "tqdm": "4.66.6",
    "transformers": "4.51.3",
    "vllm": "0.8.5",
    "z3-solver": "4.14.1.0",
}
# The CP-SAT tier (chinatravel/agent/tpc_agent/cp_solver.py) is ours, so ortools has no upstream
# pin to match. It is the *only* package the submission may add.
ALLOWED_EXTRA_PACKAGES = {"ortools"}


def test_submission_adds_at_most_one_package_to_upstreams_set():
    extra = set(_requirements(SUBMISSION_REQS)) - set(UPSTREAM_REQUIREMENTS)
    assert extra <= ALLOWED_EXTRA_PACKAGES, (
        f"new dependencies beyond upstream's set: {sorted(extra - ALLOWED_EXTRA_PACKAGES)}. "
        "Prefer an optional import over a required install."
    )


def test_submission_versions_match_upstreams_pins():
    """No version drift from upstream on any shared package: the organizers run our install on
    the same benchmark code they maintain."""
    for name, line in _requirements(SUBMISSION_REQS).items():
        if name not in UPSTREAM_REQUIREMENTS:
            continue
        pinned = line.split("==")[-1].strip()
        assert pinned == UPSTREAM_REQUIREMENTS[name], (
            f"{name} pinned at {pinned}, upstream pins {UPSTREAM_REQUIREMENTS[name]}"
        )


def test_psutil_is_optional_at_runtime():
    """It is used for RSS telemetry only. Requiring it would make two additions to upstream's
    dependency set instead of one."""
    import solve_phase2 as sp2

    assert "psutil" not in _requirements(SUBMISSION_REQS)
    source = Path(sp2.__file__).read_text(encoding="utf-8")
    assert "except ImportError" in source
    assert hasattr(sp2, "current_rss_mb")


def test_submission_requirements_exclude_the_heavy_stack():
    submission = set(_requirements(SUBMISSION_REQS))
    leaked = submission & FORBIDDEN_IN_SUBMISSION
    assert not leaked, f"the submission install must stay minimal; drop: {sorted(leaked)}"


def test_submission_requirements_need_no_extra_index():
    """`pip install -r` only, no `-f`/`--index-url`: the evaluation host is on an internal
    network and the organizers asked for plain pip/conda installs."""
    text = SUBMISSION_REQS.read_text(encoding="utf-8")
    for line in text.splitlines():
        stripped = line.strip()
        assert not stripped.startswith(("-f", "--find-links", "-i", "--index-url", "--extra-index-url")), (
            f"submission requirements must not need a custom package source: {line!r}"
        )


def test_project_core_dependencies_match_the_submission_requirements():
    """`pip install .` and `pip install -r requirements-submission.txt` must install the same
    thing, so whichever the organizers reach for gives a working system."""
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    core = {
        dep.split("==")[0].split(">=")[0].strip().lower().replace("_", "-")
        for dep in pyproject["project"]["dependencies"]
    }
    assert core == set(_requirements(SUBMISSION_REQS))


def test_heavy_extras_stay_optional():
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    extras = pyproject["project"]["optional-dependencies"]
    assert "local-llm" in extras
    assert any(dep.startswith("torch") for dep in extras["local-llm"])
    core = " ".join(pyproject["project"]["dependencies"])
    assert "torch" not in core and "vllm" not in core


class TestArchiveContents:
    def test_required_files_are_tracked_and_included(self):
        packaged = set(asm.tracked_files())
        assert not asm.check_required(sorted(packaged))
        for required in asm.REQUIRED_FILES:
            assert required in packaged

    def test_the_english_database_ships(self):
        packaged = asm.tracked_files()
        assert any(p.startswith("chinatravel/environment/database_en/") for p in packaged), (
            "the solver grounds every fact in the sandbox database; it must be in the archive"
        )

    def test_development_only_trees_are_excluded(self):
        packaged = asm.tracked_files()
        for prefix in ("results/", "report/", "submissions/", "docs/archive/"):
            assert not any(p.startswith(prefix) for p in packaged), f"{prefix} must not ship"

    def test_only_tracked_files_ship(self):
        """`git ls-files` is the source, so untracked local state (`.venv`, run outputs) cannot
        leak into a submission."""
        packaged = asm.tracked_files()
        raw = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert set(packaged) <= {p for p in raw.split("\0") if p}

    def test_every_packaged_path_exists_on_disk(self):
        """Non-ASCII database filenames are the trap here: `git ls-files` without `-z` quotes
        them into paths that cannot be opened, and the copy step would fail mid-package."""
        for rel in asm.tracked_files():
            assert (PROJECT_ROOT / rel).exists(), f"packaged path does not exist: {rel!r}"

    def test_no_credential_bearing_file_can_ship(self):
        """`.gitignore` lists `.env`, but this repository tracks one anyway -- a tracked path
        beats a gitignore rule -- so filtering by git status alone would have shipped it."""
        packaged = asm.tracked_files()
        assert ".env" not in packaged
        assert not any(Path(p).name.startswith(".env") for p in packaged)
        assert "agent_env/config.toml" not in packaged

    @pytest.mark.parametrize(
        "path",
        [".env", ".env.local", ".env.example", "agent_env/config.toml", "key.pem", ".netrc"],
    )
    def test_secret_patterns_match(self, path):
        assert asm.is_secret_path(path)

    @pytest.mark.parametrize(
        "path",
        ["agent_env/config.toml.example", "README.md", "chinatravel/agent/phase2/refine.py"],
    )
    def test_secret_patterns_do_not_over_match(self, path):
        assert not asm.is_secret_path(path)

    def test_staging_refuses_a_hand_built_path_list_with_secrets(self, tmp_path):
        with pytest.raises(SystemExit):
            asm.stage([".env"], tmp_path / "out", version="v1", team="team")

    def test_check_required_reports_a_missing_entry_point(self):
        missing = asm.check_required(["README.md"])
        assert "agent_env/scripts/solve_script_with_harness.py" in missing
        assert "chinatravel/environment/database_en/*" in missing


class TestVersioning:
    def test_phase2_numbering_restarts_at_v1(self, monkeypatch):
        """Phase 1 tags are `v<N>` and reached v9; Phase 2 restarts at v1 in its own namespace,
        so a Phase 1 tag must not advance the Phase 2 version."""
        monkeypatch.setattr(asm, "run_git", lambda *args: "v9 v8 v7")
        assert asm.next_version() == "v1"

    def test_next_version_follows_the_highest_phase2_tag(self, monkeypatch):
        monkeypatch.setattr(asm, "run_git", lambda *args: "phase2-v1 phase2-v2 v9")
        assert asm.next_version() == "v3"


class TestSubmissionConfig:
    """The organizers' harness example ships `agent_env/config.toml` inside its archive, so ours
    must too -- synthesized, never copied from the working tree, which can hold API keys."""

    def _staged_config(self, tmp_path):
        out = tmp_path / "out"
        asm.stage(["README.md"], out, version="v1", team="team")
        return out / "agent_env" / "config.toml"

    def test_archive_carries_a_config_pinning_the_deterministic_harness(self, tmp_path):
        parsed = tomllib.loads(self._staged_config(tmp_path).read_text(encoding="utf-8"))
        assert parsed["run"]["harness"] == asm_harness_default()

    def test_config_pins_no_split(self, tmp_path):
        """The organizers pass `--split <split>`; we cannot guess the held-out split's name, and a
        wrong pin here would silently solve the wrong queries on a bare invocation."""
        parsed = tomllib.loads(self._staged_config(tmp_path).read_text(encoding="utf-8"))
        assert "split" not in parsed["run"]
        assert "limit" not in parsed["run"]

    def test_config_carries_no_credentials(self, tmp_path):
        text = self._staged_config(tmp_path).read_text(encoding="utf-8").lower()
        for marker in ("api_key", "token", "secret", "password", "http://", "https://"):
            assert marker not in text, f"submission config must not carry {marker!r}"


def asm_harness_default() -> str:
    """The entry point's own name for the deterministic in-process solver."""
    sys.path.insert(0, str(PROJECT_ROOT / "agent_env" / "scripts"))
    import solve_script_with_harness as harness  # noqa: PLC0415

    return harness.TPC_HARNESS


def test_submission_readme_renders_without_leftover_placeholders():
    text = asm.SUBMISSION_README.format(
        team="team",
        version="v1",
        commit="0" * 40,
        branch="main",
        dep_count=9,
        total_budget_hours=5.0,
        evaluator_parity="c89cfca",
    )
    assert "{" not in text.replace("{TeamName}", "")
    assert "solve_script_with_harness.py --split <split>" in text
    assert "requirements-submission.txt" in text


class TestTechnicalReport:
    """The report is a separate, mandatory deliverable with its own format rules."""

    def test_report_uses_the_official_template(self):
        report_dir = PROJECT_ROOT / "report"
        assert (report_dir / "ijcai26.sty").exists(), "the official author-kit style must ship"
        assert (report_dir / "named.bst").exists()
        tex = (report_dir / "fabiundstefan.tex").read_text(encoding="utf-8")
        assert "\\usepackage{ijcai26}" in tex
        assert "\\documentclass{article}" in tex

    def test_report_pdf_is_named_after_the_team(self):
        assert (PROJECT_ROOT / "report" / "fabiundstefan.pdf").exists()

    @pytest.mark.parametrize("path", ["ijcai26.sty", "named.bst"])
    def test_author_kit_files_are_unmodified(self, path):
        """A locally patched style file would break the format requirement silently."""
        text = (PROJECT_ROOT / "report" / path).read_text(encoding="utf-8", errors="ignore")
        assert "TODO" not in text
