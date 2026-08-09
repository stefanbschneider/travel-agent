# P28 — honor a stated room count. Both gates, both GREEN

**Date** 2026-08-09 · **Branch** `submission/v2-room-count` · **host** 10-core macOS (Apple M1 Pro)
· candidate `6c05b7d0`, baseline `599dd422` (`main`, i.e. the `v2` archive as first built). Both arms
of both gates ran from **pinned `git worktrees`**, concurrently, so contention is shared.

**What this fixes.** The oracle checks the hotel room count exactly
(`room_count(activity) != N -> result=False`, reading the plan's own `rooms` field). The solver always
*derived* that count as `ceil(people / beds_per_room)` — correct while the traveler says nothing, wrong
whenever they say otherwise. The generalization probe never flagged it, because it classifies this
family as "metadata-guaranteed" and therefore needs no extracted family to count as covered. It took a
different question to find it: *for each query failing exactly one clause, which clause is it?*

| register | queries failing exactly 1 clause | of which the sole failure is `rooms` |
| --- | --- | --- |
| `hf_medium` (before P28) | `50` of 150 | **`28`** |

`28` of `150` queries — `18.7 %` of the split — were one field away from passing everything.

## Extraction precision: 167 stated counts, 0 wrong values

Measured against every released set before any solve
(`parse_room_count` vs the oracle's own `room_count(activity) != N`):

| set | matched | wrong | missing | faithful-but-unchecked |
| --- | --- | --- | --- | --- |
| familiar-100 | `11` | **`0`** | `0` | `0` |
| `local_released_150` | `0` | **`0`** | `0` | `12` |
| `hf_easy` | `23` | **`0`** | `7` | `2` |
| `hf_medium` | `123` | **`0`** | `26` | `0` |
| `hf_human` | `6` | **`0`** | `1` | `0` |
| `hf_preference_base50` | `1` | **`0`** | `0` | `0` |

"Faithful-but-unchecked" means the text *does* state a count (`"stay in a single bed room"` → 1) on a
query whose oracle carries no count clause. Those are correct readings of the request, not inventions,
and they cost nothing: the commonsense checker has no room rule (verified — no `rooms` reference in
`chinatravel/evaluation/commonsense_constraint.py`), and a smaller count only relieves the budget.

## Gate 1 — free prose (`hf_medium`, n=150, paired, translated oracle)

| metric | pre-P28 | P28 | Δ |
| --- | --- | --- | --- |
| MicEPR / MacEPR | `100.0` / `100.0` | `100.0` / `100.0` | flat |
| C-LPR | `89.6361` | `92.3259` | **`+2.6899`** |
| FPR | `48.0000` | **`65.3333`** | **`+17.3333`** (26 more queries pass every clause) |
| DAV / ATT / DDR | `28.58` / `44.62` / `26.98` | `39.97` / `60.69` / `37.04` | up — they follow FPR |
| **overall** | **`66.6182`** | **`76.0996`** | **`+9.4814`** |

Untranslated control oracle, for continuity: C-LPR `83.7025 → 86.4715`, FPR `24.6667 → 35.3333`,
overall `53.4361 → 59.5865`. Logs in [`eval/`](eval/).

Clause level, per uid: **`35` fail→pass, `1` pass→fail**
([`clause_diff_pre_to_p28.txt`](clause_diff_pre_to_p28.txt)). Queries fully passing: `72 → 98` of 150.

The `pre` arm reproduces [R34](../20260809_r34_intercity_e2e/README.md)'s candidate arm to the last
decimal (`89.63607594936708` / `48.0` / `66.61823026511775`) — the third independent reproduction of
that configuration on this host, and this pair's determinism check.

## Gate 2 — the shipped shape (familiar-100 whole run, 5 h envelope, 4 workers)

Rows [`20260809T055547Z_p28gate_base`](../../full_runs/20260809T055547Z_p28gate_base.json) and
[`_cand`](../../full_runs/20260809T055547Z_p28gate_cand.json).

| metric | baseline | candidate | Δ |
| --- | --- | --- | --- |
| MicEPR / MacEPR | `99.6667` / `98.0` | `99.6667` / `98.0` | flat |
| C-LPR | `90.4418` | `90.6222` | `+0.1804` |
| FPR | `47.0000` | `49.0000` | **`+2.0000`** |
| DAV / ATT / DDR | `27.45` / `36.70` / `27.02` | `29.04` / `38.65` / `28.13` | up |
| **overall** | **`65.7354`** | **`66.8128`** | **`+1.0774`** |
| `empty_plans` | `0/100` | `0/100` | `0` |
| wall | `0.63 h` of `5 h` | `0.62 h` of `5 h` | — |

The baseline arm reproduces [R33](../20260809_v2_whole_run_gate/README.md)'s candidate row exactly
(`65.73543493802828`), so this pair is anchored to the previous one.

**Note what is unusual here: P28 gains on *both* registers.** Every earlier win was register-specific
— the phrasing work is inert on familiar-100, the relocation pass is inert on free prose. A room count
is stated in plain language in every register, so this one moves both.

## Cumulative, `v1` → `v2` as shipped, on free prose

| | `v1` (`be196d00`) | `v2` (`6c05b7d0`) |
| --- | --- | --- |
| C-LPR | `75.5538` | **`92.3259`** |
| FPR | `10.6667` | **`65.3333`** |
| overall | `44.4077` | **`76.0996`** |

`225` of `1264` clauses flip fail→pass against `13` lost
([`clause_diff_v1_to_p28.txt`](clause_diff_v1_to_p28.txt)).

## What is left on this register, measured

With P28 in, `98/150` `hf_medium` queries pass every clause and `31` fail exactly one: `18`
`attraction_name`, `6` `inner_transport_required`, `2` `attraction_type`, and one each of three others.
The second of those was implemented and **rejected** the same morning — see
[P29](../../../../docs/tpc_phase2_roadmap.md#p29--required-in-city-transport-mode-investigated-and-rejected-2026-08-09):
the family and its plumbing work, but no context cue tight enough to avoid `23` spurious readings on
familiar-100 kept enough recall to be worth it (`9` matches at best). Dropped rather than shipped.
