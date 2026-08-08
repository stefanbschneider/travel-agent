# R20 precondition — does the contemporaneous deterministic floor move, and does LLM extract_fill beat it?

**Date** 2026-08-08 · **Branch** `eval/r20-precondition-arm` · **git_sha** `fecdf7ca` (`main` tip
before this commit; includes P20/P22/P24 since the `311 < 320` comparison was last measured)
**Contract** Static parse-only A/B, `scripts/phase2_llm_parse_arms_probe.py` — one live LLM call per
query, deterministic and LLM-assisted arms computed in the same process on the same queries. No
solve, no held-out artifact.

## Why this run

[R20](../../../../docs/tpc_phase2_eval.md#r20--does-grounded-fill-only-llm-extraction-convert)'s own
re-open condition: *"Re-open R20 only when a changed parser/merge policy beats its contemporaneous
deterministic arm on `matched` without increasing `spurious`."* The last measurement (`311 < 320`)
predates P20, P22 and P24, all of which touch the deterministic parse path. Re-measuring both arms is
the cheap half of R20 — it either closes R20 with fresh numbers or earns the expensive cold-cache
harness rerun the doc otherwise forbids spending on. This does **not** attempt the expensive rerun;
it only checks the precondition.

## Command run

```bash
TPC_P2_LLM_BACKEND=deepinfra .venv/bin/python scripts/phase2_llm_parse_arms_probe.py \
  --set local_released_150 --limit 5 --mode extract_fill --entity-resolution \
  --out-dir <scratch>   # price probe first, n=5

TPC_P2_LLM_BACKEND=deepinfra .venv/bin/python scripts/phase2_llm_parse_arms_probe.py \
  --set local_released_150 --mode extract_fill --entity-resolution \
  --out-dir results/phase2_baselines/screens/20260808_r20_precondition_arm
```

`extract_fill` is the only merge policy the doc's re-open condition allows, and
`--entity-resolution` matches the doc's requirement that `TPC_P2_ENTITY_RESOLUTION=1` be part of the
candidate (it is now also the confirmed harness default per R29).

## Pricing (n=5, before the full run)

`live_calls=5 cache_hits=0 fail=0 cost=$0.0022` — **$0.00044/call**. Full `local_released_150`
(n=150) priced at ≈`$0.066`, well inside the available budget. Confirmed live, not a no-op:
`llm_sec_p50=0.66s`, `llm_sec_max=1.06s`, both far above an instant-fallback signature.

## Full run (n=150)

`live_calls=145 cache_hits=5 fail=0 cost=$0.0736`, `llm_sec_total=154.7s`, zero timeouts, zero
retries, zero empty responses — the call fired on every query and none of the arm is measuring a
silent fallback (the exact failure mode R29's methodology section warns about).

| arm | precision | recall | F1 | **matched** | missing | spurious | wrong_value |
| --- | --- | --- | --- | --- | --- | --- | --- |
| deterministic (current `main`) | `0.8222` | `0.8243` | `0.8233` | **`325`** | `32` | `38` | `36` |
| LLM-assisted (`extract_fill`, entity-resolution) | `0.7913` | `0.8108` | `0.8009` | **`318`** | `16` | `32` | `59` |

Clause-level parse-gap: `5/522 → 2/522` (LLM recovers 3 previously-missing clauses: `attraction_name
×2`, `attraction_type ×1`, breaks `0`). Per-query recall: `19` queries improve, `28` regress.

## Reading it against R20's own bar

**The deterministic floor moved on its own, independent of anything measured here.** The last
recorded contemporaneous floor was `320` (already stale relative to the original pre-P15 `309`
threshold R20's doc text also mentions). Current `main`'s deterministic arm reaches **`325`** —
P20/P22/P24 raised the floor `5` further since the last R20 measurement, before any LLM arm is
considered. The bar R20 must clear keeps moving, and this row is the first to re-measure it since
P24 landed.

**LLM `extract_fill` still does not clear it.** `matched 318 < 325`: the LLM arm is now `7` below the
*current* floor (it was `9` below the *stale* `320` floor last time — `311 < 320`), a smaller gap in
absolute terms but the floor gap has not closed proportionally, since the deterministic side gained
more than the LLM side did.

**`spurious` did fall (`38 → 32`)**, satisfying half of R20's "without increasing `spurious`"
clause — but the other half of the bar (`matched` must exceed the floor) is not met, and
**`wrong_value` rose sharply (`36 → 59`, `+64 %`)**. `matched`/`missing`/`wrong_value` are a strict
partition of the same `393` oracle-field slots in both arms (`325+36+32 = 393 = 318+59+16`), which
pins the accounting exactly: writing `c` for families that left `matched` for `wrong_value` and `a`
for previously-`missing` families the LLM filled correctly, `matched_new = 325 - c + a = 318` gives
`c = a + 7`, and since `a ≥ 0`, **at least `7` of the `59` `wrong_value` families were `matched`
before the LLM arm touched them** — a `matched → wrong` transition on a family the deterministic
regex already had right. `extract_fill`'s stated contract ("may only fill families the deterministic
parse left empty, never overwrite a regex value") says this transition should not be possible at
all, for any number of families. The n=5 price probe independently shows the same signature in
isolation: `matched 10 → 8`, `wrong_value 0 → 2`, `missing 0` in *both* arms — no empty family
existed for the LLM to fill, so those `2` can only be overwrites of an already-correct value.

**Open question for the implementation workstream, not resolved here:** either `extract_fill`'s merge
path has a contract violation, or `--entity-resolution` — applied only to the LLM arm's name-bearing
families per this probe's own `--help` text — is rewriting an already-correct value post-merge on
this run's candidate configuration. The second is the likelier cause (it is exactly the flag this row
adds, and the probe's own doc says the deterministic arm is unaffected by it) but this row does not
debug which. Whichever it is, it does not change this row's verdict below: `matched 318 < 325` is
true regardless of which mechanism produced the extra `wrong_value`s, so R20's precondition is unmet
either way. **This is a recall-for-precision trade, and it trades unfavorably**: the net field count
didn't just fail to improve, it moved the wrong direction on the metric (`wrong_value`) that's
hardest to recover from downstream, since a wrong value is scored as confidently as a right one until
the solver runs.

## Verdict: R20 stays HOLD, `TPC_P2_LLM_PARSE=0` stays library-default

The precondition is not met (`318 < 325`), so per R20's own bar the expensive half (a cold-cache
harness rerun, a free-prose e2e arm) is **not** earned by this measurement and is correctly not
spent here. This closes the "is the floor stale" question the last revision left open: it was stale,
by `5`, and the LLM arm has not kept pace. Re-open R20 again only after a future parser change if the
LLM arm is re-measured and clears whatever the deterministic floor is at that time.

**Follow-up, not built here:** the `missing → wrong_value` pattern above is itself informative for a
different lever — if `extract_fill`'s few genuine recoveries (`attraction_name`, `attraction_type`,
`3` clauses total) could be kept while suppressing the wrong-value fills, the LLM arm might clear the
floor. Not attempted here; this row only checks the precondition as the doc's bar states it.
