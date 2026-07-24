# TPC @ IJCAI 2026 Competition Reference

**Accessed:** 2026-07-15. **Last re-verification attempt:** 2026-07-24 (see note below).
The [competition website](https://chinatravel-competition.github.io/IJCAI2026/) is authoritative when this note conflicts with local material.
This is a concise repository reference, not a replacement for the rules.

> **2026-07-24 re-verification blocked.** An attempt to re-check the live site from an agent
> session failed: the environment's egress proxy returns HTTP 403 for
> `chinatravel-competition.github.io` (an organization policy denial, not a transient error), and
> web search could not read the page either. The facts below therefore still date from the
> 2026-07-15 snapshot and are **~9 days stale**. Re-verify from a browser or an environment with
> site access before relying on them near a deadline. The two highest-value unknowns to confirm on
> the live site are the **Round 2 submission portal/format** and any **organizer-enforced per-query
> timeout / evaluation repeat count** (see [Details not yet public](#details-not-yet-public)).

## Dates and advancement

| Milestone | Date |
| --- | --- |
| Phase 1 data release and submissions open | 2026-06-01 |
| Phase 1 submission deadline | 2026-08-01 |
| Phase 2 evaluation | 2026-08-01 to 2026-08-07 |
| Technical-report deadline | 2026-08-07 |
| Final results | 2026-08-10 |

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

The public material does not state an organizer-enforced per-query timeout or evaluation repeat count.
It also says the Round 2 submission portal and format will be announced later.
Treat local 300 s and 900 s settings as sensitivity assumptions, not official budgets.

**Repeat-count inconsistency to resolve on re-verification.** The 2026-07-15 archive copy
([`docs/archive/reference/ijcai2026_competition_2026-07-15.md`](../archive/reference/ijcai2026_competition_2026-07-15.md))
records "each harness is run five times on the held-out test set and the scores are averaged." That
"5 runs" figure is *not* carried into this reference because it could not be reconfirmed; the
conservative statement above (repeat count not organizer-confirmed) stands until the live site is
re-checked. If the live site still states five runs, promote it here; if not, leave it unconfirmed.

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
