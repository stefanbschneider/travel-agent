# R35 — the preference-verb trigger arm (P27's only measured survivor)

**Date** 2026-08-09 · **Branch** `submission/v2-candidate` · **host** 10-core macOS (Apple M1 Pro) ·
**Contract** paired free-prose A/B on **`hf_human`** (n=154 — the human-written register, not the
generator-written one), per-query mode, `--budget-sec 90`, `--lang en`, both arms launched
simultaneously with two shards each, each from its own `git worktree` at the same commit, differing
only by the trigger patch. Scored against a **translated** `hf_human` oracle
(`materialize_hf_split.py --translate-oracle-literals`: 86 of 154 queries carry a translated clause,
12 keep a residual), because `hf_human`'s raw oracle literals are Chinese and its FPR would otherwise
be read against a cap.

Why `hf_human` rather than `hf_medium`: this is the register the change acts on at all. Proven, not
assumed — see the parse-identity check below.

## Result: GREEN, small — overall `+0.7014`, two more queries fully pass

| metric | trigger off | trigger on | Δ |
| --- | --- | --- | --- |
| MicEPR / MacEPR | `99.9759` / `99.3506` | `99.9759` / `99.3506` | flat |
| C-LPR | `84.8617` | `85.0073` | `+0.1456` |
| FPR | `51.9481` | `53.2468` | **`+1.2987`** (2 more queries) |
| DAV / ATT / DDR | `35.71` / `47.11` / `34.66` | `36.60` / `48.26` / `35.52` | up (they follow FPR) |
| **overall** | **`67.8013`** | **`68.5027`** | **`+0.7014`** |

Clause level: **`2` fail→pass, `1` pass→fail**. Small numbers, and stated as such — this is a `+2/−1`
change on one register, not a mechanism with headroom.

## Blast radius, measured rather than inferred

The static probe reported `hf_medium`/`hf_easy`/familiar-100/`local_released_150` columns unchanged,
but equal aggregates do not prove equal parses. So the full parsed **solver dicts** were diffed query
by query between the two trees (`parse_identity.py`, importing each tree's `parse_constraints` in its
own subprocess):

| set | queries | with a different parse |
| --- | --- | --- |
| familiar-100 | 100 | **0** |
| `local_released_150` | 150 | **0** |
| `hf_easy` | 300 | **0** |
| `hf_medium` | 150 | **0** |
| `hf_human` | 154 | **4** |

**4 of 854.** Each of the four adds exactly one `required_attraction_types` value:
`h20241029143546424651` (`"I like natural scenery"` → `natural scenery`, which is what its oracle
requires), `h20241029143650282919` (`Cultural Tourism Area`), `h20241029143704161138`
(`natural scenery`), `h20241029143820591758` (`park`).

That also means **[R33](../20260809_v2_whole_run_gate/README.md) and
[R34](../20260809_r34_intercity_e2e/README.md) still describe the shipped configuration exactly**, since
neither of their registers changes.

## The honest caveat

`h20241029143704161138`'s text is *"I prefer cultural or natural attractions"* — an **OR**, of which
this change records one arm. P20's OR guard drops a window that yields two distinct values, but here
the two phrases share the noun (`"cultural or natural attractions"`), so only one value matches and the
guard never fires. It happens to be the arm the oracle wants in this instance. The general defect is
real, is not fixed here, and is the shape a future OR-aware phrase table would have to handle.

## What was rejected, and why it matters more than what was kept

Everything else P27 looked at. The remaining `attraction_type` residual is interpretive
(*"going on a date"* → `约会圣地`), and the oracle's own labels for the biggest phrase class are split
between two canonical values, so a deterministic mapping would be guessing. See
[P27](../../../../docs/tpc_phase2_roadmap.md#p27--the-remaining-attraction-type-residual-is-interpretive-not-lexical-investigated-and-closed-2026-08-09)
for the evidence table.
