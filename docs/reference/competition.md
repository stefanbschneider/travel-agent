# TPC @ IJCAI 2026 Competition Reference

**Accessed:** 2026-07-15.
The [competition website](https://chinatravel-competition.github.io/IJCAI2026/) is authoritative when this note conflicts with local material.
This is a concise repository reference, not a replacement for the rules.

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
