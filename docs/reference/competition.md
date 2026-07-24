# TPC @ IJCAI 2026 Competition Reference

**Accessed:** 2026-07-15. **Last re-verified against the live site:** 2026-07-24 (facts below confirmed current).
The [competition website](https://chinatravel-competition.github.io/IJCAI2026/) is authoritative when this note conflicts with local material.
This is a concise repository reference, not a replacement for the rules.

> **2026-07-24 re-verification succeeded.** The live site was re-checked directly (its content is
> rendered client-side from `app.js`, so the facts were read from that bundle, not the empty static
> HTML). The earlier egress 403 no longer applies. Outcome: the dates, advancement rule, harness
> setup, hardware, and scoring below all **match the live site** and are current as of 2026-07-24.
> The two previously flagged unknowns remain **unresolved by the organizers** (not merely unverified
> by us): the **Round 2 submission portal/format** is still "announced later", and no
> **organizer-enforced per-query timeout or evaluation repeat count** appears anywhere on the live
> site — the archived "5 runs" figure is *not* present (see [Details not yet public](#details-not-yet-public)).

## Dates and advancement

| Milestone | Live-site label | Date |
| --- | --- | --- |
| Data release and submissions open | Data Release and Submission Opens | 2026-06-01 |
| **Phase 1** submission deadline | Stage 1 Submission Deadline | 2026-08-01 |
| **Phase 2** evaluation window | Stage 2 Evaluation | 2026-08-01 to 2026-08-07 |
| Technical-report deadline | Technical Report Deadline | 2026-08-07 |
| Final results | Final Results Announced | 2026-08-10 |

Phase 1 is open to all teams.
The top five Phase 1 teams, plus every team tied at the fifth-place cutoff, advance to Phase 2.

**What the 2026-08-01 deadline covers.** The live timeline labels 2026-08-01 explicitly as the
**"Stage 1 Submission Deadline"** — it is the Phase 1 (prediction) deadline only. Phase 2 has **no
published submission deadline**: its row is labelled "Stage 2 **Evaluation**" and spans 2026-08-01
to 2026-08-07, and the site states the Round 2 submission portal and format "will be announced
later." Because Phase 2 evaluation begins the same day Phase 1 closes (2026-08-01), the harness
submission deadline must fall on or just after 2026-08-01; expect the organizers to publish the
portal, format, and exact Phase 2 cut-off shortly before that window. Track it near the deadline.

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

Advancing teams submit a self-contained harness with agent code, prompts, scaffolding, and required files.
Organizers evaluate it per query on a separate held-out set using Qwen3.6-27B via SGLang on **2 × A800 80 GB GPUs without NVLink**.
The [official Agent Environment Guide](https://chinatravel-competition.github.io/IJCAI2026/agent-environment.html) describes the wrapper: its harness removes oracle-only verifier fields before the agent is asked to solve a query.
Final Phase 2 rankings determine first through third place.

## Official development resources

- [Competition site](https://chinatravel-competition.github.io/IJCAI2026/)
- [Agent Environment Guide](https://chinatravel-competition.github.io/IJCAI2026/agent-environment.html)
- [Phase 2 familiar-100 data](https://chinatravel-competition.github.io/IJCAI2026/TPC_IJCAI_2026_phase2_familiar_100_data.zip)

The Agent Environment Guide and 100 familiar examples were released on 2026-07-15.
The examples are drawn from the same distribution as final evaluation but are development-only; final evaluation uses a separate held-out set.

## Details not yet public

As re-confirmed on the live site 2026-07-24, the public material does **not** state an
organizer-enforced per-query timeout or evaluation repeat count, and the **Round 2 submission portal
and format are still "announced later"** (no portal, format, or exact Phase 2 submission deadline
yet). Treat local 300 s and 900 s settings as sensitivity assumptions, not official budgets.

**Repeat-count inconsistency — resolved for now.** The 2026-07-15 archive copy
([`docs/archive/reference/ijcai2026_competition_2026-07-15.md`](../archive/reference/ijcai2026_competition_2026-07-15.md))
records "each harness is run five times on the held-out test set and the scores are averaged." The
2026-07-24 live-site re-check found **no such "5 runs" statement** anywhere in the site content; the
only `repeatCount` token in the page is an SVG animation attribute, unrelated to evaluation. The
conservative statement above (repeat count not organizer-confirmed) therefore stands, and the "5
runs" figure remains un-promoted. Re-check if the organizers publish the Round 2 format.

## Phase 2 expected API (harness invocation)

Captured from the 2026-07-15 archive and the in-repo baseline harness
([`agent_env/scripts/solve_script_with_harness.py`](../../agent_env/scripts/solve_script_with_harness.py)).
The organizer path is **prompt-and-parse over the `agent_env.cli` tool environment**, not a Python
entry point the team implements:

- **Invocation:** per-query (not batch), sequential, each query with its own independent timeout.
  Supported runners are `opencode` (`opencode run`) and `codex` (`codex exec`), configured in
  `agent_env/config.toml` (`[opencode]` / `[codex]`: model, `timeout`, API-key env var, provider).
- **Agent input:** a text prompt (`build_prompt()`) carrying the **visible query JSON** with oracle
  verifier fields (`hard_logic`, `hard_logic_py`, `hard_logic_nl`) already stripped, plus the repo
  root and the exact Python command to use for `agent_env.cli` tool calls.
- **Tools:** `agent_env.cli tools` (catalog), `call <tool> '<json>'`, and a restricted
  `world '<WorldEnv cmd>'` allowlist. Categories cover query load; attraction / restaurant /
  accommodation search, keys, opening-hours, nearby; in-city `goto` and `intercity_transport_select`;
  and POI coordinates.
- **Agent output:** one JSON itinerary matching
  [`chinatravel/evaluation/output_schema.json`](../../chinatravel/evaluation/output_schema.json),
  wrapped in `<output>...</output>` tags, no prose. Schema-valid is necessary but not sufficient: it
  must also pass `chinatravel/symbol_verification/commonsense_constraint.py` and the hard-constraint
  evaluator. The full field-by-field itinerary contract is in
  [`agent_env/SKILL.md`](../../agent_env/SKILL.md).
- **Harness outputs per query:** `prompt.txt`, `output.txt`, `output.json`,
  `results/<method>/<uid>.json`, `evaluation.json`; plus `<split>_summary.json` for a full split.

This repo's own deterministic runner (`agent_env/scripts/solve_phase2.py` →
`orchestrator.solve_phase2()` returning `(plan, telemetry)`) is an internal orchestrator, not the
organizer-required interface.
