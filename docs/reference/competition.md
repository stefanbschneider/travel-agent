# TPC @ IJCAI 2026 Competition Reference

**Accessed:** 2026-07-15; dates and Phase 2 packaging updated 2026-08-03 from the organizers' advancement email and a re-check of the competition site; execution, versioning, feedback, per-query timeout, and technical-report answers added 2026-08-04 from the organizers' direct email reply to our clarification questions; harness resubmission requirement, runtime reconfirmation, and the confirmed SGLang/LLM endpoint added 2026-08-04 (later the same day) from the organizers' second update email — see [below](#harness-resubmission-and-the-confirmed-llm-endpoint-2026-08-04-second-organizer-email); the DSL-free held-out data, the "latest harness example / latest evaluation code" instructions, and the `--method <method>` argument added 2026-08-06 from the organizers' fourth email — see [below](#dsl-free-data-latest-harnessevaluator-and-the-method-argument-2026-08-06).
The [competition website](https://chinatravel-competition.github.io/IJCAI2026/) is authoritative when this note conflicts with local material.
This is a concise repository reference, not a replacement for the rules.

## Dates and advancement

| Milestone | Date |
| --- | --- |
| Phase 1 data release and submissions open | 2026-06-01 |
| Phase 1 submission deadline | 2026-08-03, 24:00 Beijing Time (UTC+8) |
| Phase 2 submission and evaluation period | 2026-08-04 to 2026-08-10 |
| Harness submission deadline | 2026-08-10, 24:00 Beijing Time (UTC+8) |
| Technical-report deadline | 2026-08-10, 24:00 Beijing Time (UTC+8) |
| Final results | To be announced |

Team fabiundstefan's advancement email (2026-08-03) confirms these dates directly; they also match the milestones rendered on the competition site (`app.js`). This supersedes the earlier `2026-08-01`/`2026-08-07` dates this doc previously carried.

Phase 1 is open to all teams.
The top five Phase 1 teams, plus every team tied at the fifth-place cutoff, advance to Phase 2.

## Phase 1: predictions

Teams generate predictions locally from the released official data and submit a prediction archive to the public leaderboard.
Any method is permitted; the submission is predictions, not code or models.
The website specifies a zip name of `{TeamName}_v{x}.zip`.
The leaderboard reports each team's best and latest submitted result.

The official score is:

$$
0.10\,\mathrm{EPR\!\text{-}micro} + 0.10\,\mathrm{EPR\!\text{-}macro} + 0.25\,\mathrm{C\!\text{-}LPR} + 0.40\,\mathrm{FPR} + 0.05\,\mathrm{DAV} + 0.05\,\mathrm{ATT} + 0.05\,\mathrm{DDR}.
$$

Hard-constraint metrics contribute 85%; DAV, ATT, and DDR contribute 15%.

## Phase 2: harness

Advancing teams submit a self-contained harness with agent code, prompts, dependencies, documentation, and all files required to run the system.
Organizers evaluate it per query on a separate held-out set using Qwen3.6-27B via SGLang on **2 × A800 80 GB GPUs without NVLink**.
The [official Agent Environment Guide](https://chinatravel-competition.github.io/IJCAI2026/agent-environment.html) describes the wrapper: its harness removes oracle-only verifier fields before the agent is asked to solve a query.
Final Phase 2 rankings determine first through third place. Top-ranked teams are separately invited to submit a short system description paper for the competition proceedings — this is distinct from the mandatory technical report above.

### Confirmed packaging (2026-08-03 advancement email)

- **Portal:** https://box.nju.edu.cn/u/d/5a1a84297f4b43eda42f/ (same link the competition site lists as "Phase 2 Submission Portal").
- **Zip name:** `{TeamName}_v{x}.zip`, e.g. `NJUTravel_v1.zip`, `NJUTravel_v2.zip`. **The version number restarts from `v1` in Phase 2** — do not continue the Phase 1 version sequence. The zip filename's team name must match the registered team name.
- **Contents:** "agent code, prompts, dependencies, documentation, and all files required to run your system" — i.e. a runnable checkout, not predictions.
- The competition site's own Round 1 packaging note ("extra top-level folders inside the zip are handled normally") is Phase-1-specific guidance; nothing on the site adds Phase-2-specific packaging detail beyond what the email states.

### Confirmed execution, versioning, feedback, and timeout (2026-08-04 organizer reply)

We asked the organizers directly (email + would-be GitHub issue) how evaluation is actually run. Their reply:

- **Execution is automated, one fixed command.** They run the existing ChinaTravel environment as the baseline and invoke exactly:

  ```
  python agent_env/scripts/solve_script_with_harness.py --split <split>
  ```

  **Amended 2026-08-06** — the command also carries `--method <method>`; see [the clarification
  below](#dsl-free-data-latest-harnessevaluator-and-the-method-argument-2026-08-06).

  "All harness-specific initialization and launch logic" must be integrated behind this single command; setup (dependency install, database download, config) is documented separately in the README and is not part of the timed run (see timeout below). Any extra environment must be reproducible with plain `pip`/`conda` — they explicitly asked teams to avoid dependencies needing special package sources or complicated system-level installs, since the evaluation machines sit on an internal network and slow installs cost their limited eval time.
  **This is now a hard, load-bearing fact for our submission layout — see the critical gap flagged just below and the top roadmap priority it drives.**
- **Versioning.** They evaluate **at most two submitted versions per team** (limited eval resources). If both run successfully, **the higher score is the team's final score.** (Unspecified: what happens if only one of two succeeds, or a third version is submitted anyway — treat "at most two" as the operative constraint and don't rely on a third attempt.)
- **Feedback.** Teams get feedback after *every* evaluation run: the score plus "relevant execution information." Feedback can be delayed because each run takes a while. If the organizers hit an environment issue, runtime error, or apparent bug during evaluation, they'll contact the team proactively.
- **Per-query timeout: there isn't one.** Instead there's a **single 5-hour wall-clock budget for the whole 100-query run**, starting when the command above is invoked; environment creation, dependency installation, and other setup are excluded from that 5 hours. This replaces every `300 s`/`900 s` per-query assumption this repository has carried since Phase 2 planning began — see the [design doc](../tpc_phase2_design.md#run-shape) for how the run is scheduled against it.

### DSL-free data, latest harness/evaluator, and the `--method` argument (2026-08-06)

A fourth organizer email, sent "to ensure that all Phase 2 teams prepare and test their harnesses
under consistent requirements". Four items, each checked against this repository on the day it
arrived:

**1. The held-out data contains no verifier fields.** Explicitly named as absent: `hard_logic`,
`hard_logic.py`, `hard_logic_py`, `hard_logic_nl`, "and any other DSL, constraint-code,
ground-truth, answer-related, or verifier-only fields."

*Conforming, and now tested on that shape rather than inferred.* The no-oracle contract was already
the design (`visible_query` strips anything matching `hard_logic*`, which covers the dotted
`hard_logic.py` spelling too), but every local run had oracle fields present and merely hidden. A
split rebuilt with the fields physically deleted was run end-to-end through both the whole-run
(sweeps) and per-query paths: plans written, exit 0, no code path required a verifier field.
`evaluate_one`'s `has_oracle` degrades to the oracle-free half — the numbers become `None`, not
zero, so a missing oracle is never mistaken for a failed check. Pinned by
`tests/phase2/test_harness_entry_point.py::TestNoVerifierFields`.

**2. Use the latest harness example.** Downloaded fresh from the competition site on 2026-08-06:
`sha256 758ca81e…f049`, **byte-identical** to the copy already committed at
`submissions/phase2/ChinaTravel_harness_example.zip` and already compared against our archive
([2026-08-05](#verified-against-the-official-harness-example-2026-08-05)). Its
`solve_script_with_harness.py` is byte-identical to upstream `main` at `456b60a`, and our entry
point remains a strict superset of its CLI. No action needed.

**3. Use the latest evaluation code.** Upstream `main` advanced `c89cfca` → `456b60a` ("Fix English
language propagation in agent harness", PR #33). That commit touches `agent_env/` and the baseline
harness only: `git diff c89cfca 456b60a` is **empty** across `chinatravel/evaluation/`,
`chinatravel/symbol_verification/`, `chinatravel/environment/concept_labels.py`,
`chinatravel/environment/tools/`, `eval_tpc.py` and `chinatravel/data/load_datasets.py`. So the
evaluator we score against is already the latest one, the parity point stays `c89cfca`, and
`EVALUATOR_PARITY_SHA` deliberately does **not** move — bumping it would mark every existing row
non-comparable to a new one across a boundary where no scoring code changed, which would break the
R14 gate for nothing.

**4. The evaluation command takes `--method`, and results have a fixed path.** Run from the root of
the submitted package:

```
python agent_env/scripts/solve_script_with_harness.py --method <method> --split <split>
```

with each query's result at `results/<method>/<uid>.json`, and an explicit instruction: *"Do not
hard-code the public dataset split, query list, number of queries, or method name."*

*Conforming; the required behavior predates the email, the enforcement does not.* `--method` has
always been accepted and is used verbatim — nothing sanitizes, prefixes, or derives it — and both
the whole-run and per-query writers already emit `results/<method>/<uid>.json`. Verified by running
`--method tpc_submission --split tpc_phase2_familiar_100_val` and reading the plans back out of
`results/tpc_submission/`. The archive's `agent_env/config.toml` pins neither `method` nor `split`
nor `limit`, so a command-line value is never overridden and no query list or count is fixed.
What changed on 2026-08-06:

- the assembler's unpack-and-run check now passes an `--method` value the code would never derive
  on its own and fails the build unless plans appear at exactly `results/<that value>/` — the
  organizers' path is now a build-blocking assertion, not an inspection;
- `SUBMISSION.md`, `submission_manifest.json` (`entry_point`, new `results_path`), `README.md`
  and this reference all state the two-argument command;
- the entry point echoes `Results: …/results/<method>/<uid>.json` before the run starts, so a run
  killed mid-split still shows where it wrote;
- `tests/phase2/test_harness_entry_point.py::TestOrganizerArguments` pins method-verbatim and
  split-from-the-flag behavior.

**One robustness fix this prompted.** `--split <name>` resolves through upstream's loader, which
looks for `en` splits under `chinatravel/data/en/` and `zh` splits under `chinatravel/data/` and
*raises* when the name is in neither. We are told the split name but not which tree the organizers
drop their held-out queries into, and an unresolved split is the worst failure available to us: no
plans at all, a zero for the whole run. `hb.load_queries_with_lang` now retries the other language
before giving up and reports which one it used, and `solve_phase2.run_split` builds `WorldEnv` and
the evaluators in the language the queries actually came from. The happy path never reaches it.

### The gap this reply surfaced — CLOSED 2026-08-04

`agent_env/scripts/solve_script_with_harness.py` was the repository's (and upstream's) **generic OpenCode/Codex compatibility demo**: by default it shelled out to the external `opencode` CLI, which in turn calls an external LLM API (DashScope by default in `config.toml.example`). It was *not* the deterministic, no-oracle `TPCAgent` solver this project competes with — that ran only through the separate `agent_env/scripts/solve_phase2.py` entry point, which the organizers did not name. Since they invoke `solve_script_with_harness.py --split <split>` **verbatim, with no other flags**, whatever that bare invocation does by default *is* our Phase 2 submission, and the default would have needed an installed `opencode` npm binary plus network egress from an internal-network host.

**Fixed.** The script now defaults to `--harness tpc`: the deterministic solver, run in-process through `solve_phase2.run_split`, making zero LLM calls, zero network calls, and no subprocess. `opencode`/`codex` survive as explicit opt-ins for baseline comparison. `tests/phase2/test_harness_entry_point.py` pins that, including an integration test that runs the organizers' command shape in a subprocess with `opencode`/`codex` unreachable and asserts a schema-valid plan.

The bare command also schedules the run against the 5-hour envelope confirmed above rather than giving each query a fixed budget (`chinatravel/agent/phase2/sweeps.py`): **triage** every query at a small budget, then **repair** only the constraint-failing ones at a growing budget, then **polish** preference terms on the rest, across `CPU count - 1` worker processes. Every result is scored oracle-free and kept only if it beats the plan already on disk, and a schema-valid fallback for every query is written before the first solve — so a run stopped at any point still submits a complete, non-regressed set. This matters because the organizers weight every query equally: a fixed per-query budget would let one hard query consume time that would have solved several easy ones, and 100 queries at our `300 s` working default is `8.3 h` against a `5 h` envelope.

### Packaging this into a submission

```bash
make phase2-submission-check   # dry run: what would ship, file count, unpacked size
make phase2-submission         # build submissions/phase2/{team}_v<N>.zip, then unpack and run it
```

`scripts/assemble_phase2_submission.py` builds `submissions/phase2/{team}_v{N}.zip` (archive root `{team}_v{N}/`, version from `phase2-v<N>` git tags, which restart at `v1` for Phase 2) from the **tracked** files at the current commit, minus development-only trees (`results/`, `submissions/`, `docs/archive/`, `report/`, `images/`, `slurm/`). It writes a `SUBMISSION.md` (install + run), a `submission_manifest.json` (commit, evaluator parity point) and a credential-free `agent_env/config.toml` into the archive root, then verifies the result by unpacking it into a temporary directory and running the organizers' command shape there with a stripped `PATH`. It uploads nothing; submission stays manual at the portal above. Installation on the evaluation host is `pip install -r requirements-submission.txt` — eight PyPI packages, no extra index, no GPU stack, database included.

**Credential exclusion, stated correctly.** An earlier version of this paragraph claimed that reading `git ls-files` is what keeps `.env` and `agent_env/config.toml` out of an archive, "because they are gitignored". That reasoning does not hold: `.gitignore` does not untrack a file that is already tracked, and **`.env` is in fact tracked in this repository** (committed in `82b0455`). What actually protects the archive is the separate `SECRET_PATH_PATTERNS` filter in the assembler, which drops any `.env*`, `config.toml`, `.netrc`, `*.pem` or SSH key path regardless of its git status — verified by `tests/phase2/test_submission_package.py` and by inspecting the built zip. The tracked `.env` remains a repository-hygiene problem in its own right (see below); it is not a submission leak.

### Pre-submission checklist — the cold-start rule (added 2026-08-05)

**Never upload an archive that has not been verified from a pristine tree with more than one worker.** This is not a formality; it caught a bug that would have scored the submission near zero.

```bash
.venv/bin/python -m pytest tests/phase2 -q                       # unit suite
.venv/bin/python -m pytest tests/phase2/test_cold_start.py -m integration -q
.venv/bin/python scripts/assemble_phase2_submission.py --verify-budget-sec 90
```

**The failure mode this exists for.** Every worker process builds a `TPCAgent` against the same `cache/phase2_solve`, which is resolved relative to the *working directory*. On a tree that has never been run in — exactly what the organizers unpack — `BaseAgent` check-then-created it, so all workers saw it missing, one created it, and the rest raised `FileExistsError`. That happens inside the `ProcessPoolExecutor` **initializer**, so it does not lose one query: it breaks the pool, and the run **still exits 0** while shipping the pre-written empty fallback for every query. Fixed in PR [#60](https://github.com/stefanbschneider/china-travel-agent/pull/60) (`os.makedirs(..., exist_ok=True)`).

Three properties made it nearly invisible, and they generalize to any future start-up bug:

| Property | Consequence |
| --- | --- |
| Only reproduces **cold** | A dev tree always has `cache/phase2_solve` from an earlier run, as does the second run in any tree. Every local run, every committed `full_runs/` row and the whole unit suite passed. |
| Needs **≥2 workers** | `ProcessPoolExecutor` spawns workers lazily, one per submitted task, so a single-query run starts a single worker. The verification used `--limit 1` and never exercised the pool at all. |
| Fails **silently** | Broken pool → exit code 0, plan files present, empty itineraries. Only a content check sees it. |

What changed as a result: the archive verification now solves `VERIFY_QUERIES` (6) queries rather than 1 so multiple workers actually start, checks **every** plan for a non-empty itinerary rather than just the first, and fails on `Exception in initializer` in stderr. `tests/phase2/test_cold_start.py` runs the same shape in CI, and `tests/phase2/test_log_dir_race.py` pins the specific mechanism deterministically.

**Honest limitation:** the integration test catches *deterministic* cold-start breakage reliably, but fired on only about **one run in four** against the known-broken code, because the race window is narrow and raising the worker count made it *worse* (lazy ramp-up, not simultaneous start). The deterministic unit test is the real regression guard for this instance; the integration test covers the class. Do not treat a green cold-start run as proof that no race exists.

### The `v1` archive as built (2026-08-05)

**Submission status: uploaded 2026-08-05.** `v1` is the team's first official post-reset submission,
and **one slot (`v2`) remains**. The organizers aim to return a score within 3 days of a valid
submission, i.e. around **2026-08-08**; both `v2` and the technical report are due
**2026-08-10, 24:00 Beijing Time** (16:00 UTC / 18:00 CEST). Identity of the uploaded bytes:

| | |
| --- | --- |
| File | `submissions/phase2/fabiundstefan_v1.zip` (committed, so the tested bytes are the uploaded bytes) |
| SHA-256 | `fab8a85f7b9b7714f28fbdf2b7ae510caae9e501e34a76f09600ca70d8e3e416` |
| Built from | `be196d005f6e61177d69c9e536c8a461bb1af91a` on `main`; committed and tagged `phase2-v1` at `96296dd8` |
| Configuration | R8 / R12's promoted defaults — `TPC_WINDOW_ANCHOR` on, P8/P9 (`TPC_WINDOW_PUSH`, `TPC_WINDOW_INSERT`) **off** |
| Expected score | `overall ≈ 63.58`, `FPR ≈ 43.0`, `±2σ` roughly `58–68` — see [the expectation table](../tpc_phase2_eval.md#what-the-submitted-v1-is-expected-to-score--an-expectation-not-a-measurement) |

**What `v2` requires, in order.** `scripts/assemble_phase2_submission.py` resolves `v2` automatically
from the `phase2-v1` tag, so packaging is not the work; deciding what goes in it is:

1. a GREEN [R14](../tpc_phase2_eval.md#r14--the-p8p9-gate-the-one-run-that-decides-whether-v2-exists)
   whole-run row promoting P8+P9 — the only measured candidate that exists today;
2. the promotion committed on `main` (`apply_deterministic_solver_defaults()` plus the flag moved from
   `CANDIDATE_SOLVER_FLAGS` to `PROMOTED_SOLVER_FLAGS`), because an archive is built from tracked
   files at a commit and never from an operator's environment;
3. the full [pre-submission checklist](#pre-submission-checklist--the-cold-start-rule-added-2026-08-05)
   re-run on a **pristine** tree with more than one worker, and `solver_flags` re-read from the
   unpacked archive to confirm the new configuration actually ships;
4. rebuild from `main` (never a feature branch — see the rebuild rule at the end of this section),
   tag `phase2-v2`, upload as `fabiundstefan_v2.zip`.

If R14 is flat or RED, **do not upload a `v2`**: an identical-configuration resubmission spends the
last slot for nothing, and the two-version cap means there is no third attempt.

`fabiundstefan_v1.zip` — `1683` entries, `4.3 MB` compressed / `16.6 MB` unpacked, `1680` tracked
files, `evaluator_parity c89cfca`, first `phase2-v<N>` tag namespace entry (Phase 2 numbering restarts
at `v1`, and the [resubmission
email](#harness-resubmission-and-the-confirmed-llm-endpoint-2026-08-04-second-organizer-email)
disregards everything uploaded before it). It carries the promoted post-R8 configuration.

**Built from `be196d00` on `main`** (the rebuild described below). The first build of this archive came
from `aba52e7a` on the `claude/phase2-eval-r12-r13` branch and was discarded under the rebuild rule at
the end of this section; only `docs/tpc_phase2_eval.md` and `docs/tpc_phase2_roadmap.md` differ between
the two, so no runnable file changed, but the uploaded artifact is the mainline one. The zip is
committed at `submissions/phase2/fabiundstefan_v1.zip` (force-added past the `submissions/` ignore rule)
so it can be pulled and tested without a rebuild, and tagged `phase2-v1`. The tag therefore sits one
commit *after* the `submission_manifest.json` commit: a zip cannot contain the commit that adds it. The
only difference between the two is this documentation record — no runnable file — and the tested bytes
are exactly the uploaded bytes, which is the property that matters.

Verified beyond the assembler's own unpack-and-run, because a warm tree proves nothing about the
organizers' cold one. Every row below was re-run against the `main` rebuild on a `4`-core box, so the
worker count is `3` (`CPU-1`) rather than the `9` of the earlier branch build; the requirement the
cold-start rule states is `>1`, not `9`:

| Check | Result |
| --- | --- |
| Unit suite + cold-start integration test | `869` passed, `1` skipped; `tests/phase2/test_cold_start.py -m integration` green |
| Install from the archive alone, `uv venv --python 3.12` + `requirements-submission.txt` | `34` packages resolved, no extra index, no GPU stack |
| Cold tree (no `cache/`), `env -i` with `PATH=/usr/bin:/bin`, `12` queries, `3` workers | `12/12` plans, `180` activities, `0` empty itineraries, `0` fallbacks, no `Exception in initializer` |
| Same again on a **third** pristine tree, driven by the archive's **own installed interpreter** rather than the development venv | `6/6` plans, `67` activities, `0` empty, `llm_backend=none` — the archive plus its own declared dependencies is sufficient |
| `solver_flags` on every query | `pin_timed_windows`, `window_anchor`, `commonsense_first` all `true`, `solve_converge_patience 15` — the archive ships the R8 configuration, not the pre-R8 one |
| LLM / network | `llm_backend=none` on every query; no `.env`, `*.pem`, `.netrc` or SSH key in the zip; `agent_env/config.toml` synthesized credential-free (`[run] harness = "tpc"`, no `split`, no `limit`) |
| Oracle leakage | no `hard_logic*` key in any emitted plan |
| **The bare command, no flags at all** (`--split tpc_phase2_familiar_100_test`) | reads its own config, resolves the split, reports `20 queries, 3 worker(s), 285.0 min usable of a 5.00 h envelope, per-query cap 300s`, pre-writes all `20` plans before the first solve |
| Interrupt safety | `SIGTERM` at `150 s` of a 5 h envelope left `20/20` plans on disk, **all schema-valid**, `7/20` already non-empty (fewer than the branch build's `18/20` because that ran with `9` workers, not `3`) |

**Envelope headroom on an unknown host.** R8 spent `4733 s` wall across `3` workers, so the whole
split costs at most `~14200` worker-seconds. Even a machine that gives us a single worker finishes in
`~3.9 h`, inside the 5 h budget; more cores only add slack. The `26%` envelope utilization is not
wasted time (see the [diagnosis](../tpc_phase2_roadmap.md#the-diagnosis)) but it is real robustness.

**Rebuild before uploading if the commit is not on `main`.** `submission_manifest.json` records the
commit *and branch* it was built from. An archive built from a feature branch is fine to test and
wrong to upload — the uploaded artifact should be reproducible from the mainline.

### Verified against the official harness example (2026-08-05)

The organizers' `ChinaTravel_harness_example.zip` (`submissions/`, 687 files) was unpacked and compared against our archive. Findings:

| Aspect | Example | Ours | Verdict |
| --- | --- | --- | --- |
| Archive root | `ChinaTravel_harness_example/` | `{team}_v{N}/` | matches the `{TeamName}_v{x}.zip` rule |
| Entry point CLI | 21 flags | the same 21, plus `--budget-sec`, `--total-budget-sec`, `--workers` | strict superset |
| Missing `config.toml` | `read_config` returns `{}` | byte-identical function | no crash either way |
| `agent_env/config.toml` in the zip | **shipped** (though gitignored in their repo) | **now shipped**, synthesized | aligned 2026-08-05 |
| Documented invocation | `uv run python agent_env/scripts/solve_script_with_harness.py` | `pip install -r requirements-submission.txt` then `python ...` | **both verified** |
| `pyproject.toml` deps | 23, incl. torch/vllm | 8 core, incl. `ortools` | ours is what `uv run` resolves |
| `.python-version` | `3.12` | `3.12` | matches |

Two things this comparison changed. First, the example ships `agent_env/config.toml` inside its archive even though its own `.gitignore` excludes it — so a submission is expected to carry one, and ours now synthesizes a credential-free `[run] harness = "tpc"` config. It deliberately pins **no** `split` and no `limit`: CLI beats config in `solve_script_with_harness.py`'s `choose()` precedence, and the split name the organizers' held-out data resolves under is not something we can guess.

Second, the example's `RUN_HARNESS.md` drives everything through **`uv run`**, not `pip`. That makes `pyproject.toml`'s `[project.dependencies]` — not `requirements-submission.txt` — the operative dependency contract on that path. Ours lists the 8 core packages including `ortools` (the CP-SAT tier needs it; it is the only package this repository adds to upstream's set), so both install routes work. Confirmed by unpacking the built archive and running `uv run --no-dev python agent_env/scripts/solve_script_with_harness.py --split tpc_phase2_familiar_100 --limit 1 --total-budget-sec 90` inside it with a stripped `PATH`: uv resolved the project, the deterministic solver ran, and passes/plans were written.

**`.env` is tracked in git — deliberately, and it is not a submission risk.** `git ls-files` lists it (598 bytes, committed in `82b0455`) despite `.gitignore` naming it, because gitignore does not untrack an already-tracked file. This is the owner's decision, not an accident: it lets agents working in cloud environments reach the DeepInfra endpoint, and the key is spend-capped at a few euros, so a leak is bounded. **Planned cleanup: remove the file and rotate the key the week after the competition** (rotation is the part that matters — deleting it from future commits does not remove it from history). The submission archive is unaffected either way; `SECRET_PATH_PATTERNS` drops it regardless of git status.

### Still open after the 2026-08-04 reply

- ~~How the harness reaches the evaluation host's Qwen3.6-27B/SGLang endpoint~~ **Answered the same
  day** by the organizers' second email — see [Harness resubmission and the confirmed LLM
  endpoint](#harness-resubmission-and-the-confirmed-llm-endpoint-2026-08-04-second-organizer-email)
  below: `http://127.0.0.1:30000/v1`, served model name `Qwen3.6-27B`, OpenAI-compatible.
- Behavior when only one of two submitted versions runs successfully (see versioning above) — inferred as "that one counts," not confirmed.
- ~~Whether the confirmed evaluation command literally omits `--split` (second email) or literally
  includes it (direct reply, same day)~~ **Resolved 2026-08-06:** the fourth email states the command
  as `--method <method> --split <split>` and asks that neither be hard-coded — see [DSL-free data,
  latest harness/evaluator, and the `--method`
  argument](#dsl-free-data-latest-harnessevaluator-and-the-method-argument-2026-08-06).
- Final-results date remains "to be announced."

### Confirmed evaluation host (2026-07-30)

From the organizers' reply to [issue #27](https://github.com/LAMDA-NeSy/ChinaTravel/issues/27):

| | |
| --- | --- |
| CPU | 16 OS-visible logical CPUs; **the harness process is assigned all 16** |
| RAM | 112 GiB total host memory — total, *not* a guaranteed exclusively reserved amount |
| GPU | 2 × NVIDIA A800 80 GB PCIe, driver `575.57.08` |
| OS | Debian GNU/Linux 12 |
| Python | 3.12.13 |
| Serving stack | SGLang `0.5.10`, sglang-kernel `0.4.1`, PyTorch `2.9.1+cu128` (CUDA 12.8), Transformers `5.3.0`, Triton `3.5.1`, FlashInfer `0.6.7.post2` |

What this changes for us:

- **16 logical CPUs, not the 1 our solver uses.** Local development runs on far fewer cores, so the
  per-query solve was tuned single-threaded (CP-SAT `num_search_workers` 1, sequential restarts).
  On the evaluation host that leaves most of the machine idle inside every per-query budget. Using
  the extra cores is the largest untapped, risk-free lever we know of — see the roadmap.
- **Memory is not a constraint** at our ~250 MB per-process floor, but it is shared, so do not size a
  change against 112 GiB as if it were reserved.
- **Python 3.12 matches our pin** (we require 3.12 through `.venv`). The host's torch/transformers
  versions are far newer than `requirements.txt`, which is fine only because the submitted path must
  not import them: the model is served over SGLang, and `chinatravel/agent/llms.py` keeps the local
  model stack behind a lazy import. A submission that eagerly imports `torch`/`vllm` would meet
  `2.9.1`/newer, not our pinned versions.
- **Confirmed 2026-08-04: there is no per-query timeout.** The real constraint is a single 5-hour
  wall-clock budget for the entire 100-query run (see below), so `300 s`/`900 s` per-query local gates
  were never the binding constraint — a slow query now only matters insofar as it eats into the shared
  5 h envelope for the rest of the split.

### Harness resubmission and the confirmed LLM endpoint (2026-08-04, second organizer email)

A second organizer email arrived the same day as the direct reply above ("updated information about
the TPC 2026 Phase 2 submission requirements, evaluation environment, runtime limit, and technical
report deadline"). Six new or reconfirmed facts:

1. **Harness ZIP contents, restated.** "Agent code, prompts, harness and execution scripts, required
   dependencies, configuration files, instructions, and all other files required to run the system" —
   consistent with, not a change from, the 2026-08-03 advancement email's packaging note and what
   `scripts/assemble_phase2_submission.py` already builds.
2. **Output format, now explicit.** `results/<method>/<uid>.json` — matches
   `solve_script_with_harness.py`'s existing `run_tpc_split` output path exactly; no code change
   needed.
3. **Resubmission reset — action required regardless of what was uploaded before.** *"All Phase 2
   files uploaded before this notice will be disregarded. They will not be formally evaluated and
   will not count toward the submission limit."* Every team must re-download the current harness
   submission example, re-verify their package against the startup command, evaluation environment,
   dependencies, file paths, and output format described in that email, and then upload it as
   `{TeamName}_v1.zip` — this becomes the team's first official submission regardless of anything
   uploaded earlier. The `{TeamName}_v1.zip` / `{TeamName}_v2.zip` naming and the two-version cap are
   unchanged from the [confirmed packaging](#confirmed-packaging-2026-08-03-advancement-email) note
   above; only the "what counts as v1" clock reset. **Uploaded 2026-08-05** — the archive described
   in [The `v1` archive as built](#the-v1-archive-as-built-2026-08-05) is our post-reset `v1`, so the
   reset cost us nothing and **one slot (`v2`) remains.**
4. **Hardware, reconfirmed unchanged.** 16 OS-visible logical CPUs (all assigned to the harness
   process), 112 GiB total host RAM, 2 × NVIDIA A800 80 GB PCIe without NVLink, driver `575.57.08` —
   identical to the [2026-07-30 confirmation](#confirmed-evaluation-host-2026-07-30) above.
5. **Runtime stack, reconfirmed unchanged.** Debian GNU/Linux 12, Python `3.12.13`, PyTorch
   `2.9.1+cu128` (CUDA 12.8), SGLang `0.5.10`, sglang-kernel `0.4.1`, Transformers `5.3.0`, Triton
   `3.5.1`, FlashInfer `0.6.7.post2`, evaluation model `Qwen3.6-27B` — identical to the table above.
6. **Evaluation turnaround.** After a valid `v1`, organizers aim to return a score within 3 days
   (resource/failure dependent); no real-time execution logs are available to participants, only the
   score plus "relevant execution information" per run. A team can use the `v1` score to decide
   whether to submit `v2` before the deadline. Schedule is unchanged: submission/evaluation window
   2026-08-04 to 2026-08-10, both the harness and the technical report due 2026-08-10, 24:00 Beijing
   Time.

**A wording discrepancy, since resolved (2026-08-06).** The fourth email settles it: the command is
`--method <method> --split <split>`, run from the package root. The paragraph below records what was
uncertain at the time and why it never changed our behavior.

This second email's own invocation line (item 1) is
`python agent_env/scripts/solve_script_with_harness.py` with no `--split` argument shown, unlike the
[explicit `--split <split>` command](#confirmed-execution-versioning-feedback-and-timeout-2026-08-04-organizer-reply)
the organizers gave in direct reply to our clarification question earlier the same day. We have not
re-asked which is literal. It does not change our behavior either way: `--split` has always been
optional here (`solve_script_with_harness.py` defaults to `split="easy"`, `lang="en"` when omitted —
see `[run]` in `agent_env/config.toml.example`), so both a bare invocation and an explicit
`--split <split>` run the same `--harness tpc` deterministic path. What it does mean is that if the
organizers truly invoke the script with zero arguments against the held-out set, the split name that
resolves the held-out queries is not something we control or can guess from here — only they know how
their harness supplies query data to whatever `--split` (or its absence) selects on their side.

**The previously open LLM-reachability question is now answered.** The organizers' reply to our
follow-up question on the LLM API gave the exact deployment:

```
CUDA_VISIBLE_DEVICES=0,1 sglang serve \
  --model-path /mnt/hdd/local_llm/Qwen3.6-27B \
  --served-model-name Qwen3.6-27B \
  --host 0.0.0.0 --port 30000 \
  --tp-size 2 --dtype bfloat16 --context-length 131072 \
  --mem-fraction-static 0.85 --chunked-prefill-size 4096 \
  --max-running-requests 8 \
  --reasoning-parser qwen3 --tool-call-parser qwen3_coder
```

So the OpenAI-compatible endpoint is `http://127.0.0.1:30000/v1`, served model name **`Qwen3.6-27B`**
(no `Qwen/` prefix — that is DeepInfra's org-qualified naming, a different backend). This closes the
"how does the harness reach the endpoint" item that was previously "not asked, not answered" below.
Concretely:

- `agent_env/config.phase2.example.toml`'s `[phase2.llm]` block now uses the exact confirmed
  `base_url`/`model`, since it previously carried a plausible-but-unconfirmed placeholder.
- `chinatravel/agent/phase2/llm_client.py`'s Qwen3 "thinking mode" default-off behavior (previously
  `deepinfra`-only) now also applies to the `openai` backend — the one this endpoint is reached
  through — since `--reasoning-parser qwen3` confirms the eval deployment does standard
  chain-of-thought reasoning unless the chat template explicitly suppresses it, and our per-call
  timeout is sized for the non-thinking case.
- `--max-running-requests 8` is a real server-side concurrency cap worth remembering if an LLM-backed
  flag is ever turned on for a run that uses more than 8 parallel workers (the whole-run scheduler
  defaults to `CPU count - 1` = up to 15): more in-flight requests than that queue or time out
  server-side, independent of anything our client does.
- This closes a reachability *question*, not a packaging decision. The invariant is unchanged:
  library-default Phase 2 flags make zero LLM calls (`TPC_P2_LLM_BACKEND` defaults to `none`,
  `agent_env/config.toml` is gitignored), and the packaged submission still never reaches this or any
  other endpoint unless an operator explicitly configures and measures it — see [LLM
  packaging](../tpc_phase2_roadmap.md#llm-packaging-the-submission-makes-zero-llm-calls).
- We still cannot reach *this specific* endpoint from here (it only exists on the evaluation host
  during a real evaluation run), so the client plumbing is verified against a real OpenAI-compatible
  DeepInfra endpoint (2026-07-31 night) and against the wire format this exact deployment expects, not
  against the endpoint itself.

## Official development resources

- [Competition site](https://chinatravel-competition.github.io/IJCAI2026/)
- [Agent Environment Guide](https://chinatravel-competition.github.io/IJCAI2026/agent-environment.html)
- [Phase 2 familiar-100 data](https://chinatravel-competition.github.io/IJCAI2026/TPC_IJCAI_2026_phase2_familiar_100_data.zip)

The Agent Environment Guide and 100 familiar examples were released on 2026-07-15.
The examples are drawn from the same distribution as final evaluation but are development-only; final evaluation uses a separate held-out set.

## Evaluator version

**Parity point: upstream `LAMDA-NeSy/ChinaTravel` `main` at `c89cfca` (2026-08-04), integrated here on 2026-08-04.**
The previous parity point was `764614c` (2026-07-28); the scoring contract described below is still
the current one — see [the 2026-08-04 sync](#second-upstream-sync-2026-08-04-pr-32) for what the
newer commits changed.

The organizers changed the *public* evaluator two days after our clarification issues were filed, via
two maintainer PRs ([#29](https://github.com/LAMDA-NeSy/ChinaTravel/pull/29) chronology and meal
limits, [#30](https://github.com/LAMDA-NeSy/ChinaTravel/pull/30) scoring and transport grounding).
Both are integrated; `chinatravel/evaluation/`, `chinatravel/symbol_verification/`, `eval_tpc.py` and
`chinatravel/data/load_datasets.py` now reproduce upstream behaviour exactly. Five behavioural
changes matter for plan design:

1. `Is_time_correct` enforces intra-day chronology: activities may not overlap, and an inbound
   transport may not depart before the previous activity ends.
2. `Is_restaurants_correct` allows at most one breakfast, lunch and dinner per day
   (`Repeated Meal Types in One Day`).
3. `Is_space_correct` rejects a non-empty `transports` list between two activities at the same
   position.
4. `DEFAULT_TRANS_PR` (ATT) scores `0` for a plan with no innercity transport; it previously scored
   `8/7`, clamped to `1.0`.
5. DAV/ATT/DDR are averaged over **all** queries, with a zero for every query that is not fully
   passing. They were previously averaged over passing queries only.

Items 1–3 close the leniencies this repository had documented and, in Phase 1, deliberately exploited;
items 4–5 remove the reward for degenerate plans. Any score recorded before 2026-07-28 — ours or a
leaderboard number — is on the old contract and is not comparable to one recorded after.

**Organizer confirmation** ([issue #28](https://github.com/LAMDA-NeSy/ChinaTravel/issues/28), reply by
maintainer `Cbphcr`, 2026-07-30): *"Phase 2 will use the updated evaluator that incorporates fixes for
the known verifier issues. These fixes have already been reflected in the latest version of the public
evaluation code, so the current updated public version should be treated as the canonical evaluator for
Phase 2."* Two consequences beyond the code sync:

- **The Phase 1 leaderboard will be re-scored.** The organizers state the fixes "may materially affect
  some existing scores and leaderboard rankings" and that they need time to rerun the relevant
  evaluations, verify results and update the leaderboard, with a public update to follow. Phase 1
  standing decides Phase 2 advancement, so our already-submitted Phase 1 predictions carry the same
  `100.0 -> 61.16` exposure the local re-score shows (see the [Phase 1 playbook](../tpc_phase1_playbook.md#current-status-2026-08-02-after-clearing-all-but-one-of-the-commonsense-tail)).
- **Track upstream `main`, not a pinned copy.** Teams are told to "use the latest public evaluator
  rather than the earlier verifier version". Re-check upstream before any measurement that matters.

### Second upstream sync (2026-08-04, PR #32)

Upstream merged [PR #32](https://github.com/LAMDA-NeSy/ChinaTravel/pull/32) ("Synchronize evaluator
normalization and performance fixes", commits `90d1fca` + `24adf87`, merged `c89cfca`) on 2026-08-04.
It is integrated here the same day. Three behavioural changes, none of which touches the seven
scoring rules above:

1. **Concept labels moved into the sandbox.** The English alias table that `concept_func` used to
   own now lives in `chinatravel/environment/concept_labels.py`, and `Attractions`, `Restaurants`
   and `Accommodations` canonicalize their `type`/`cuisine`/`featurehoteltype` columns at load time
   when `lang="en"`. The verifier already normalized both sides (constraint literals via
   `normalize_concept_constraint_source`, tool reads via `normalize_concept_value`), so **the score
   of a given plan is unchanged** — but an agent querying the environment now sees one canonical
   label per concept instead of a per-city mix (`Art Museum` and `Art museum` are both `Art museum`).
2. **`innercity_transport_{cost,distance,time}` honour the `mode` key.** They filtered on
   `transport["type"]`, which plan transports never carry — they carry `mode` — so a mode-filtered
   call silently returned `0`. `innercity_transport_time` additionally ignored its `mode` argument
   entirely. This *is* a scoring change for any query whose `hard_logic_py` passes a mode; no query
   in the released Phase 1 or familiar-100 data does, so no released-data score moves, but a
   held-out query could.
3. **Performance only:** one compiled `jsonschema` validator per batch instead of one per plan,
   a per-POI nearest-metro-station cache, and `geographiclib` called directly instead of through
   `geopy.distance.geodesic` (same WGS84 result).

Item 1 changes what the *solver* sees, so `solver_constraint_variants` now canonicalizes its own
concept literals through the same table (`tests/phase2/test_concept_label_alignment.py`); without
that, a constraint asking for `'Art Museum'` would match no attraction the verifier accepts.
`EVALUATOR_PARITY_SHA` moves to `c89cfca` accordingly, so the gate refuses to compare rows recorded
across this sync.

### Third upstream sync (2026-08-04, PR #33)

Upstream merged [PR #33](https://github.com/LAMDA-NeSy/ChinaTravel/pull/33) ("Fix English language
propagation in agent harness", `456b60a`) later the same day; integrated here. It touches
`agent_env/` only — no evaluator file, so the parity point stays `c89cfca` and the ledger marker
does not move.

The substance is that `agent_env` had no way to say "English". Every entry point built
`WorldEnv()` and called `load_query` without a language, so the wrapper served the **Chinese**
database while the TPC competition data is English — `attractions_keys('Shanghai')` simply
returned `success: false`. Upstream threads an explicit `zh`/`en` through the adapter (constructor
argument, or `CHINATRAVEL_LANG`), `agent_env.cli`, `agent_env.http_server`, and
`solve_script_with_harness.py`, which also passes it into the evaluator calls and into the CLI
examples in its generated prompt.

This matters for the confirmed entry point. Our local code previously guessed the language from
the split *name* (`lang="en" if split == "tpc_phase2_familiar_100"`), which would have silently
fallen back to Chinese on the held-out split, since that split will not be named
`tpc_phase2_familiar_100`. Upstream's default for the harness script is `en`, so the organizers'
exact `python agent_env/scripts/solve_script_with_harness.py --split <split>` now resolves to
English whatever the split is called. Verified: with no `config.toml` present, that command shape
resolves `lang=en` and loads the 100 English familiar queries.

## Technical report (2026-08-04 organizer reply)

- **Who:** required from **every** team that qualified for Phase 2 — not just top finishers. (Distinct
  from the site's separately-mentioned *optional* short system description paper invited from top-ranked
  teams for the proceedings, after final results.)
- **Where/when:** the same Phase 2 submission link as the harness, any time before the 2026-08-10, 24:00
  Beijing Time deadline.
- **File:** PDF named after the team, e.g. `TeamName.pdf`.
- **Format:** official **IJCAI paper template**, **max 4 pages**, **no double-blind/anonymous requirement**.
- **Content:** no fixed structure — system/method description, implementation details, ablations,
  results, and error analysis are all acceptable. Evaluated on three dimensions: **technical reliability
  and soundness, innovation, and clarity of presentation.**

## Details not yet public

As of 2026-08-04, every item we asked the organizers about directly has an answer (see
[above](#confirmed-execution-versioning-feedback-and-timeout-2026-08-04-organizer-reply),
[the confirmed LLM endpoint](#harness-resubmission-and-the-confirmed-llm-endpoint-2026-08-04-second-organizer-email),
and [technical report](#technical-report-2026-08-04-organizer-reply)). What's left is narrower and
mostly inferred rather than asked:

- scoring if only one of two submitted versions runs successfully — inferred, not confirmed;
- whether the evaluation command literally passes `--split` (not asked, and the two 2026-08-04 emails
  disagree on the command's own text — see the wording-discrepancy note above);
- final-results date — "to be announced."

Clarification issue status:

| Issue | Asks for | Status |
| --- | --- | --- |
| [#27](https://github.com/LAMDA-NeSy/ChinaTravel/issues/27) | Submission cutoff/timezone, portal and package format, host CPU/RAM, organizer-enforced per-query timeout | **All items now answered**, though not all through this issue thread: host/runtime details via #27 itself (2026-07-30); dates/portal/format via the 2026-08-03 advancement email; execution/versioning/feedback/timeout via a separate 2026-08-04 direct email reply to our clarification questions (no per-query timeout, 5 h total for 100 queries) |
| [#28](https://github.com/LAMDA-NeSy/ChinaTravel/issues/28) | Which verifier version Phase 2 scores against: unchanged public, patched internal, or a new canonical release | **Answered 2026-07-30**: the updated public evaluator is canonical for Phase 2; the Phase 1 leaderboard will be re-scored against it |
