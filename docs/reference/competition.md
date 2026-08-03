# TPC @ IJCAI 2026 Competition Reference

**Accessed:** 2026-07-15; dates and Phase 2 packaging updated 2026-08-03 from the organizers' advancement email and a re-check of the competition site.
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

### Still not specified anywhere we've checked

Neither the advancement email nor the [Agent Environment Guide](https://chinatravel-competition.github.io/IJCAI2026/agent-environment.html) nor the competition site's own bundled script (`app.js`, checked 2026-08-03) states:

- an **organizer-enforced per-query timeout** — keep treating local `300 s`/`900 s` as sensitivity assumptions, not budgets;
- a **repeat count** or retry policy per query;
- an **execution entry-point contract** for how the organizer's own harness invokes a submitted zip (the Agent Environment Guide documents *our* development-time CLI/HTTP/MCP surface, not the calling convention the organizers' evaluation harness will use against a submitted package — that remains unconfirmed);
- any **page limit, template, or format** for the mandatory technical report, or for the optional system description paper.

Confirm these before finalizing the submission layout; a clarification request following the pattern of issues [#27](https://github.com/LAMDA-NeSy/ChinaTravel/issues/27)/[#28](https://github.com/LAMDA-NeSy/ChinaTravel/issues/28) is the appropriate channel if they aren't answered by the portal page itself once it's reachable.

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
- Per-query timeout is still unannounced, so `300 s`/`900 s` remain local assumptions.

## Official development resources

- [Competition site](https://chinatravel-competition.github.io/IJCAI2026/)
- [Agent Environment Guide](https://chinatravel-competition.github.io/IJCAI2026/agent-environment.html)
- [Phase 2 familiar-100 data](https://chinatravel-competition.github.io/IJCAI2026/TPC_IJCAI_2026_phase2_familiar_100_data.zip)

The Agent Environment Guide and 100 familiar examples were released on 2026-07-15.
The examples are drawn from the same distribution as final evaluation but are development-only; final evaluation uses a separate held-out set.

## Evaluator version

**Parity point: upstream `LAMDA-NeSy/ChinaTravel` `main` at `764614c` (2026-07-28), integrated here on 2026-07-30.**

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

## Details not yet public

The organizers' 2026-08-03 advancement email resolved two of the three items that were still pending as
of the 2026-07-30 replies:

- ~~submission deadline and cutoff timezone~~ — **resolved**: harness and technical report both due
  2026-08-10, 24:00 Beijing Time (UTC+8);
- ~~submission portal and required package format~~ — **resolved**: portal linked above, zip named
  `{TeamName}_v{x}.zip` restarting from `v1`, containing "agent code, prompts, dependencies,
  documentation, and all files required to run your system";
- **organizer-enforced per-query timeout — still unannounced.** Neither the email nor the linked Agent
  Environment Guide nor the competition site mentions it (checked 2026-08-03). Treat local `300 s` and
  `900 s` settings as sensitivity assumptions, not official budgets, and keep the harness robust to a
  shorter timeout than assumed.

Two further items surfaced while reviewing the 2026-08-03 email that were never asked about explicitly:
a **technical-report page limit/template** (not stated anywhere we checked) and the **exact entry-point
contract** the organizers' harness will use to invoke a submitted zip (the Agent Environment Guide only
documents our own development-time interface). Both are candidates for a follow-up clarification issue.

Clarification issue status:

| Issue | Asks for | Status |
| --- | --- | --- |
| [#27](https://github.com/LAMDA-NeSy/ChinaTravel/issues/27) | Submission cutoff/timezone, portal and package format, host CPU/RAM, organizer-enforced per-query timeout | **Deadline, portal, and package format answered** (2026-07-30 host/runtime details, 2026-08-03 email for dates/portal/format); **per-query timeout still pending** |
| [#28](https://github.com/LAMDA-NeSy/ChinaTravel/issues/28) | Which verifier version Phase 2 scores against: unchanged public, patched internal, or a new canonical release | **Answered 2026-07-30**: the updated public evaluator is canonical for Phase 2; the Phase 1 leaderboard will be re-scored against it |
