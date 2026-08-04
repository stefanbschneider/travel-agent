# TPC @ IJCAI 2026 Competition Reference

**Accessed:** 2026-07-15; dates and Phase 2 packaging updated 2026-08-03 from the organizers' advancement email and a re-check of the competition site; execution, versioning, feedback, per-query timeout, and technical-report answers added 2026-08-04 from the organizers' direct email reply to our clarification questions.
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

  "All harness-specific initialization and launch logic" must be integrated behind this single command; setup (dependency install, database download, config) is documented separately in the README and is not part of the timed run (see timeout below). Any extra environment must be reproducible with plain `pip`/`conda` — they explicitly asked teams to avoid dependencies needing special package sources or complicated system-level installs, since the evaluation machines sit on an internal network and slow installs cost their limited eval time.
  **This is now a hard, load-bearing fact for our submission layout — see the critical gap flagged just below and the top roadmap priority it drives.**
- **Versioning.** They evaluate **at most two submitted versions per team** (limited eval resources). If both run successfully, **the higher score is the team's final score.** (Unspecified: what happens if only one of two succeeds, or a third version is submitted anyway — treat "at most two" as the operative constraint and don't rely on a third attempt.)
- **Feedback.** Teams get feedback after *every* evaluation run: the score plus "relevant execution information." Feedback can be delayed because each run takes a while. If the organizers hit an environment issue, runtime error, or apparent bug during evaluation, they'll contact the team proactively.
- **Per-query timeout: there isn't one.** Instead there's a **single 5-hour wall-clock budget for the whole 100-query run**, starting when the command above is invoked; environment creation, dependency installation, and other setup are excluded from that 5 hours. This replaces every `300 s`/`900 s` per-query assumption this repository has carried since Phase 2 planning began — see the [roadmap](../tpc_phase2_roadmap.md#next-steps-priority-order) for what changes as a result.

### The gap this reply surfaced — CLOSED 2026-08-04

`agent_env/scripts/solve_script_with_harness.py` was the repository's (and upstream's) **generic OpenCode/Codex compatibility demo**: by default it shelled out to the external `opencode` CLI, which in turn calls an external LLM API (DashScope by default in `config.toml.example`). It was *not* the deterministic, no-oracle `TPCAgent` solver this project competes with — that ran only through the separate `agent_env/scripts/solve_phase2.py` entry point, which the organizers did not name. Since they invoke `solve_script_with_harness.py --split <split>` **verbatim, with no other flags**, whatever that bare invocation does by default *is* our Phase 2 submission, and the default would have needed an installed `opencode` npm binary plus network egress from an internal-network host.

**Fixed.** The script now defaults to `--harness tpc`: the deterministic solver, run in-process through `solve_phase2.run_split`, making zero LLM calls, zero network calls, and no subprocess. `opencode`/`codex` survive as explicit opt-ins for baseline comparison. The bare command additionally enforces the 5-hour envelope confirmed above rather than a fixed per-query budget — each query gets `min(per-query cap, remaining time / remaining queries)`, with the clock starting at interpreter start so database load counts against it. `tests/phase2/test_harness_entry_point.py` pins both facts, including an integration test that runs the organizers' command shape in a subprocess with `opencode`/`codex` unreachable and asserts a schema-valid plan.

### Packaging this into a submission

`scripts/assemble_phase2_submission.py` builds `submissions/{team}_v{N}.zip` (archive root `{team}_v{N}/`, version from `phase2-v<N>` git tags, which restart at `v1` for Phase 2) from the **tracked** files at the current commit, minus development-only trees (`results/`, `docs/archive/`, `report/`, `images/`, `slurm/`). Because it reads `git ls-files`, gitignored local state — `.env`, `agent_env/config.toml` — cannot leak into an archive. It writes a `SUBMISSION.md` (install + run) and a `submission_manifest.json` (commit, evaluator parity point) into the archive root, then verifies the result by unpacking it into a temporary directory and running the organizers' command shape there with a stripped `PATH`. It uploads nothing; submission stays manual at the portal above. Installation on the evaluation host is `pip install -r requirements-submission.txt` — nine PyPI packages, no extra index, no GPU stack, database included.

### Still open after the 2026-08-04 reply

- **How the harness reaches the evaluation host's Qwen3.6-27B/SGLang endpoint**, if any code path calls an LLM at all (base URL, auth, reachability from the harness process). Not asked, not answered. Low urgency while the default path stays LLM-free, but blocks any LLM-backed flag we might ship enabled.
- Behavior when only one of two submitted versions runs successfully (see versioning above) — inferred as "that one counts," not confirmed.
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
  `100.0 -> 61.16` exposure the local re-score shows (see the [Phase 1 playbook](../tpc_phase1_playbook.md#current-status-2026-07-30-after-the-upstream-evaluator-sync)).
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
[above](#confirmed-execution-versioning-feedback-and-timeout-2026-08-04-organizer-reply) and
[technical report](#technical-report-2026-08-04-organizer-reply)). What's left is narrower and mostly
inferred rather than asked:

- how the harness reaches the evaluation host's Qwen3.6-27B/SGLang endpoint, if a code path calls an LLM
  (base URL, auth) — not asked;
- scoring if only one of two submitted versions runs successfully — inferred, not confirmed;
- final-results date — "to be announced."

Clarification issue status:

| Issue | Asks for | Status |
| --- | --- | --- |
| [#27](https://github.com/LAMDA-NeSy/ChinaTravel/issues/27) | Submission cutoff/timezone, portal and package format, host CPU/RAM, organizer-enforced per-query timeout | **All items now answered**, though not all through this issue thread: host/runtime details via #27 itself (2026-07-30); dates/portal/format via the 2026-08-03 advancement email; execution/versioning/feedback/timeout via a separate 2026-08-04 direct email reply to our clarification questions (no per-query timeout, 5 h total for 100 queries) |
| [#28](https://github.com/LAMDA-NeSy/ChinaTravel/issues/28) | Which verifier version Phase 2 scores against: unchanged public, patched internal, or a new canonical release | **Answered 2026-07-30**: the updated public evaluator is canonical for Phase 2; the Phase 1 leaderboard will be re-scored against it |
