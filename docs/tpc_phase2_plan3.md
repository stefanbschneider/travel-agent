# Phase 2 Plan 3: gap map + near/mid/long-term roadmap (2026-07-12 deep review)

Self-contained roadmap produced by a full-repo deep review on 2026-07-12, written to be executed
by Sonnet/Opus agents over the following 1–2 weeks without access to the conversation that
produced it. It supersedes the *ordering* in `docs/tpc_phase2_sonnet_plan2.md` (plan 2) while
inheriting its ground rules verbatim; plan 2's unfinished Steps 4/6/7 are re-scoped here as M1/M2
and L3. Read plan 2's "Ground rules" section before starting any step — they all still apply
(branch `stefan/phase2`, green tests before commit, flags-off byte-identical invariant,
ledger + gate for promoted measurements, LLM economics, never touch the test split, no long evals
on the coding VM).

Competition timeline anchor: Phase 1 submission deadline **2026-08-01**, Phase 2 evaluation
**08-01 → 08-07**. This plan covers roughly 07-13 → 07-26, leaving the last week for submission
packaging and freeze.

## Current measured state (2026-07-12)

- Canonical row `20260712T060018Z` (300s, fold 0, n=85, repeats=2, LLM audit on, dynamic budget,
  post-step-5 parser): ceiling 100 / **solver-only FPR 95.29 / e2e FPR 82.35**. Parsing loss
  **12.94 pts**, solver headroom **4.71 pts**. Gate passed vs the pre-fix 300s row (80.00).
- Full-val (n=850) deterministic parser, solver-free: accept-side behavioral agreement **0.7988**,
  reject-side **0.8277**, balanced **0.8133**; `disjunction_flattened` 134.
- LLM corrective audit: accept-side 0.8694 (pre-step-5 measurement, now stale), e2e-regressive at
  60s pre-fix, net-positive in the combined 300s row. `llm_parse_failed=0` telemetry healthy.
- Fold-0 failure census at 300s: **11 uids fail e2e but pass solver-only** (parsing loss),
  **4 fail both** (solver headroom), 70 pass both.

## The gap map (evidence-backed findings, ranked by expected FPR impact)

### G1 — The precision/recall asymmetry: for e2e FPR, missing/wrong-value constraints are ~all of the loss; spurious constraints only cost solve time

The oracle check only evaluates *oracle* constraints. A plan solved under a **superset** of the
oracle constraints still passes the oracle; a plan solved under a set that is **missing** a real
constraint (or has the **wrong value** for one) violates it and fails. So:

- `spurious` families → no direct oracle failure; indirect cost only (shrunken feasible region →
  more timeouts, or an unsatisfiable garbage constraint burning restarts).
- `missing` families → direct e2e failure whenever the freshly solved plan happens to violate the
  unknown constraint (frequently — that's what the constraint was stated for).
- `wrong_value` → direct failure whenever the parsed value is not tighter-or-equal to the oracle
  value (e.g. hotel-distance 2.11 parsed from NL vs oracle's unrounded 2.1037… — parsed is
  *looser*, so a hotel at 2.105 km passes our check and fails theirs).

This is why the LLM audit — whose prompt says the regex "is known to OVER-EXTRACT" and pushes for
`remove` patches — improved the solver-free accept-side proxy while regressing e2e at 60s: it
optimizes precision, the direction that barely matters. The reject-side proxy (plan-2 Step 5)
already penalizes missing constraints; treat **recall and value fidelity as the primary parser
objectives**, precision as a solve-time concern only. Consequences threaded through N3/N4/M2
below. Corollary for ambiguous numeric values: prefer the tighter-or-equal reading (see N3.4).

### G2 — The dominant parse-loss cluster is entity handling, and the designed fix (WorldEnv-backed resolution in `normalize.py`) was never built

6–7 of the 11 fold-0 e2e-only failures, plus the biggest `wrong_value`/`spurious` family buckets
(`required_restaurants` 42 spur/46 wrong, `required_hotels` 26/46, `required_attractions` 23/24,
`cuisine_preference` 28/32), come from one cluster of entity-span defects, all verified on real
uids:

- **Label-prefix garbage kept in names:** `required_restaurants = ["one of the following
  restaurants: OMBRA Terrace Garden Western Restaurant"]` (uid `20250321144415070996`);
  `["the restaurant Floral Mountain Retreat · Pure Vegetarian Lodge"]` (`20250320205205235224`);
  `required_hotels = ["one of the following hotels: X or Y", "X or Y"]` (`20250322191742398051`).
- **List splitting failures:** "Zhongshan Park, Venice Town, and Cloudrise Art Museum" → one
  merged string `"Zhongshan Park, Venice Town"` with the third name dropped
  (`20250324090426203118`, `20250322035350348919`).
- **Type-vs-name collisions:** "visit Cultural Tourism Area and Art Museum" (both are *types*)
  also emits a spurious `required_attractions` (`20250322103818184128`); "Starry Sky Art Museum"
  (a proper noun) emits a spurious `required_attraction_types=["Art Museum"]`.
- **Category misrouting:** "stay at Chiang Rai Bay (Vientiane Qianhai Branch) for no less than 60
  minutes" — the POI is an attraction; oracle encodes `position_presence` + `stay_duration`, we
  emit a garbage `required_hotels` and miss both real families (`20250322190941974828`).
- **Numbered-list artifacts:** `required_attractions=["Amusement Park/Sports Entertainment 2"]`
  — the OR-arm number glued onto a type string (`20250322123458076116`).

`normalize.ir_to_solver_variants` already takes an `env` hook documented as "the hook for
WorldEnv-based validation/entity resolution (pass-through for now)" — it is dead code today, and
`TPCAgent._resolve_required_names` (tpc_agent.py:334) already demonstrates the fuzzy-matching
approach downstream. A deterministic resolution layer against the per-city POI catalogs closes the
whole cluster at once. **This is the highest-leverage single item in the plan** → N2.

### G3 — Disjunctive queries still lose arm content (134 flattened; numbered arms parse to nothing)

`disjunction_flattened` = 134/850 val queries even with the deterministic splitter on. Verified
failure shapes: numbered arms whose text the family extractors can't parse (bare imperative "Visit
Shenzhen Art Museum (East Lake Branch)" or "Try one of these restaurants: gaga (Joy Hub City
Store)" — `20250321152015286634` — parse to empty dicts, so `_detect_or_groups` drops them and the
query flattens); budgets inside numbered arms extracted as nothing ("1. Intra-city travel budget
of 50.0 2. Total trip budget of 9600.0", `20250323010100845247` — both budget arms lost). Because
`disjunction_stub` requires ≥2 non-empty arms, one unparsable arm kills the whole branch
expansion → N3.1.

### G4 — Intercity-mode negation inverts polarity instead of inferring the complement

"do not want to take the train to the destination" → parser emits `intercity_mode` *requiring*
train (polarity flip: `20250322204425912419` parsed `{return: train}` where oracle says
`{outbound: airplane, return: airplane}`; `20250324210212304930` parsed `{outbound: train}` where
oracle says `{outbound: airplane, return: train}`). The mode domain is binary (train/airplane), so
the oracle resolves negations to the complement — a deterministic rule we can copy. Also missing:
the "take the train **to the destination**" outbound phrasing ("and take the train back" parses,
the outbound half doesn't — `20250321032641509206`), and multi-mode exclusion lists ("walking or
taxi" → only walk extracted, `20250322035350348919`) → N3.2/N3.3.

### G5 — The parsed verifier's substring matching hides parse garbage from the acceptance criterion

`parsed_verifier._match_text` accepts bidirectional substring containment, so a garbage constraint
name like "one of the following hotels: X" *matches* a plan activity at hotel X — the solver's
acceptance check passes while the oracle (exact names) fails. This launders G2's defects into
"accepted" plans and blinds the in-harness signal. Fix **after** N2 (with canonical names, exact
matching becomes safe; tightening first would strand garbage names as unsatisfiable) → M3.

### G6 — The family-stats diff has three artifacts that distort priorities

(a) `taxi_cars_equals` contributes 668 of 916 total `spurious` entries — it's a *deliberate*
party-size-derived default, vacuously true on taxi-free plans, yet it floods the precision metric;
(b) `hotel_nearby` and `poi_distance_hotel` are the same constraint mirrored into two families and
double-counted (54+54 wrong_value are the same defects); (c) counts are per-branch-variant, so
OR-heavy uids inflate family totals. All three are cheap reporting fixes that make the fast loop
trustworthy → N1.

### G7 — The "constraint-light feasible fallback" from the design was never built

`fallback.py` returns an **empty itinerary** (schema-valid floor scoring ~0 beyond schema). On val
this fires 0/85, but held-out surprises (unparseable phrasing, solver crash on unseen city shapes)
are exactly where it will fire, and the design doc promises a feasible constraint-light plan.
Cheap insurance → M4.

### G8 — Solver headroom (4.71 pts) is small, concentrated, and characterized

The 4 fold-0 solver-only failures at 300s: two are `activity_time_windows`+`position_presence` at
restaurants/cafés (arrive-by / between-times at a named meal POI), one is
`required_hotel_any_types=[homestay]` on a 4-day trip, one `required_hotels`+intercity-budget.
These are search-strategy gaps (the repair loop has no targeted move for "pin a timed visit at a
named POI"), not formulation impossibilities — `results/best` solves them. Defer behind parsing
work, but keep as the concrete worklist when solver work becomes the binding constraint → M5.

### G9 — Generalization to held-out phrasing has never been measured, and a free measurement exists

Phase 2 runs on held-out queries; every parser number so far is on val, which we have tuned
against for weeks. The HF `LAMDA-NeSy/ChinaTravel` `default` subset (654 queries, uid-disjoint
from tpc_phase1, has `hard_logic_py` + `nature_language_en`; see `docs/tpc_phase2_hf_dataset.md`)
supports the full solver-free parser-vs-oracle report — an honest overfitting probe for ~zero
cost. If behavioral agreement drops sharply there, the regex is overfit to val phrasing and the
LLM-first architecture question (M2) becomes urgent rather than optional → N5.

### G10 — Submission-facing ops gaps (each small, each a real submission-day risk)

- `llm_client.py` still passes `max_retries=1` — the SDK retries on timeout, so worst-case
  parse-stage latency is ~2× the intended bound (plan-1 Step 2's identified-but-unapplied fix).
- No SGLang preset / smoke script (plan-1 Step 7): the competition endpoint is SGLang, not
  DeepInfra.
- The 900s primary budget has never been run; all rows are ≤300s.
- 5-run averaging variance has only been characterized with the LLM cache warm (std 0.0 is partly
  a cache artifact; the organizers' runs share no cache — although temp-0 SGLang should still be
  near-deterministic, this is unverified).
- fastfpr (plan-2 Step 3) landed but its calibration run pair (|ΔFPR| ≤ 2 pts, ≥3× wall-clock win)
  has not been executed — until it runs, fastfpr rows are uncalibrated by policy.
- The plan-2 Step 4 eval worker code is landed (`e31ef2c2`, incl. `--once`/`--dry-run` smoke) but
  not yet deployed on VM 2; no `ci-300s` ledger-branch rows exist yet — every 300s row is still
  manually launched.

→ N6 (retries, trivial), M1 (eval worker + fastfpr calibration + 900s row), L3 (SGLang +
packaging + variance).

---

## Near-term (days; the current week's work — highest FPR return per hour)

Recommended order: N1 → N2 → N3 → N4, with N5/N6 slotted anywhere (N5 is read-only; N6 is a
two-line diff). N2 is the big one; if only one thing gets done, do N2. N7 is not a slot in the
order — it's the standing test-first rule applied throughout N2/N3/N4 (its one-off setup is ~an
hour; do it alongside the first parser fix).

### N1 — Make the family-level diff trustworthy (metric hygiene) [landed 2026-07-13]

**Files:** `scripts/parser_vs_oracle.py`, its tests, `docs/tpc_phase2_eval.md`.

- Exclude `taxi_cars_equals` from precision/`spurious` when the parsed value equals the
  party-size-derived default (report it in a separate `defaulted` bucket).
- Count the `hotel_nearby`/`poi_distance_hotel` mirror pair once (canonicalize to
  `poi_distance_hotel` in the diff).
- De-duplicate per-uid family counts across branch variants (count each (uid, family, defect)
  once; keep the per-variant view behind a flag if useful).
- Re-run the full-val report; record the corrected headline numbers in `docs/tpc_phase2_eval.md`
  (they will look worse on recall-ish families and much better on precision — that's the point).

**Accept:** unit tests for the three rules; corrected report committed; no solver metrics touched.

### N2 — Deterministic entity-resolution layer in `normalize.py` (the main event) [code landed 2026-07-13; rung-(a) behavioral proxy flat, VM2 gate is the decider — see below]

**Goal:** every name-bearing family (`required_/excluded_ attractions|restaurants|hotels`,
`position_presence`, `hotel_nearby.reference`, `stay_duration[].location`,
`activity_time_windows[].location`) is canonicalized against the target city's POI catalog before
it reaches the solver or the verifier.

**Landed 2026-07-13, code + rung (a) only — not yet a confirmed win:** full-val solver-free report
moves precision 0.7356→0.7794, recall 0.6903→0.7322, f1 0.7122→0.7551 (vs the N1-corrected
baseline); `required_hotels` wrong_value drops 46→9 with +41 matched. **But `behavioral_balanced`
— the metric this step's own accept criterion names — is flat (0.8133→0.8134) and
`reject_agreement` dipped (0.8277→0.8243).** Per G1/G5, the diff table is diagnostic, not
predictive; likely cause is `parsed_verifier._match_text`'s substring matching already laundering
garbage-prefixed names into accept-side passes before N2, so cleaning the name doesn't change the
accept decision (M3's verifier-fidelity pass may be needed to cash in the structural gain). Full
reasoning in `docs/tpc_phase2_eval.md`. Rungs (b)-(d) of the measurement ladder (diff-eval splice,
fastfpr row, canonical 300s row gated vs `20260712T060018Z`) are pending on VM 2 and are the real
decider — not run here per the two-VM rule (this step also touched `orchestrator.py`'s `Flags` and
`solve_phase2.py`'s default wiring, which aren't on `phase2_diff_eval.py`'s parse-only allowlist).

**Files:** `chinatravel/agent/phase2/normalize.py` (new `resolve_entities(ir, query, catalog)`
stage inside `ir_to_solver_variants`, applied to every variant including OR arms and
alternatives), a new small catalog helper (lazy, cached per city — load the same
attractions/restaurants/accommodations name columns `WorldEnv` uses; must work without a live
`env` object so `parser_vs_oracle.py` gets identical behavior), tests
`tests/phase2/test_entity_resolution.py`, flag `TPC_P2_ENTITY_RESOLUTION` (library `Flags()`
default OFF, `run_split` default ON — the `TPC_P2_DISJUNCTION` pattern; byte-identical invariant
preserved when off).

**Resolution pipeline per name string (deterministic, ordered):**
1. Strip label prefixes/suffixes: leading `the (restaurant|hotel|attraction)s? `, `one of (the
   following|these) (restaurants|hotels|attractions)?:?\s*`, trailing ` for no less than.*` style
   clause tails — then re-trim.
2. Exact match against the city catalog (casefold, punctuation-normalized) → canonical name.
3. Fuzzy match (difflib `SequenceMatcher` ratio ≥ ~0.85, unique best) → canonical name. Also try
   containment: catalog name ⊂ candidate (fixes prefix garbage in one step).
4. If unmatched and the string contains separators (`,`, ` and `, ` or `): greedy longest-match
   segmentation against the catalog → replace one garbage string with N canonical names (fixes
   merged lists *and* recovers dropped third items when the raw span is retained in IR — prefer
   segmenting the original span over the already-truncated value when available).
5. If unmatched but the string (or a segment) is a member of the relevant **type vocabulary**
   (attraction types / cuisine list / hotel-feature list, built once from the committed data) →
   move it to the corresponding type family (`required_attraction_types` etc.) and drop it from
   the name family.
6. If it matches a catalog entry of a **different category** (e.g. `required_hotels` name that is
   actually an attraction/restaurant) → reroute: for "stay at <non-hotel POI>" emit
   `position_presence` (and leave any separately-parsed `stay_duration` alone).
7. Still unresolved → **keep the cleaned string** (recall preservation per G1; log a
   `unresolved_entities` telemetry count so we can measure how often this happens and revisit).

**Tests:** table-driven from the real uids in G2 (at minimum `20250321144415070996`,
`20250320205205235224`, `20250322191742398051`, `20250324090426203118`, `20250322103818184128`,
`20250322190941974828`, `20250320230231800319`, `20250322035350348919`); flag-off byte-identity;
catalog helper works env-less.

**Measure (the ladder, cheapest first):** (a) full-val `parser_vs_oracle` with the flag on —
expect large `wrong_value`/`spurious` drops in the G2 families and `behavioral_balanced` up;
(b) `scripts/phase2_diff_eval.py` against the `20260712T060018Z` baseline (only changed uids
re-solve — note the validity guard's parse-module allowlist must be extended to the new
files); (c) one fastfpr fold-0 row if the diff is too wide; (d) canonical 300s row on the eval VM
(via `make phase2-baseline-at`), gated vs `20260712T060018Z`. **Accept:** gate passes and ≥3 of
the 11 fold-0 parse-loss uids flip to pass.

### N3 — Targeted extractor fixes (four small, evidenced substeps, TDD each) [landed 2026-07-13; behavioral_balanced up, see below]

**Files:** `parse_constraints.py`, `tests/phase2/test_parser_accuracy.py`; same measurement
ladder as N2 (they share one diff-eval/300s row at the end; commit per substep). Each substep's
failing test goes in first, per N7 Tier 1.

**Landed 2026-07-13, all 4 substeps.** Unlike N2, this one moved the metric its own accept
criteria name: combined with N3.2/N3.3, `behavioral_balanced` (the corrected primary signal —
see the N2 framing-correction note above) went **0.8134 → 0.8246** (`accept_agreement`
0.8024→0.8176, `reject_agreement` 0.8243→0.8315), and `disjunction_flattened` dropped 134→113
(short of the ≤100 target — the remaining flattened uids include at least one genuinely
unparseable case, `20250322123458076116`, whose second OR arm is truncated in the raw dataset
NL itself ("Total budget for" with no number — verified against the source JSON, not a parser
bug). N3.4's fix doesn't move the diff/proxy by design (it only tightens solver-internal
acceptance, not the parsed value) — validated instead by an empirical investigation (31 val
samples, gap always in `[0, 0.00991]` km, confirming the NL-states-a-ceiling hypothesis) plus 3
unit tests with a mocked distance function. Full writeup and numbers in
`docs/tpc_phase2_eval.md`. Rungs (b)-(d) of the measurement ladder are pending on VM 2, same as
N2.

1. **OR-arm content recovery (G3):** make the numbered/bare-imperative arm texts parseable —
   extend the relevant extractors to accept leading bare verbs ("Visit X", "Try one of these
   restaurants: Y") and arm-local budgets ("Intra-city travel budget of 50.0", "Total trip budget
   of 9600.0" — uid `20250323010100845247`); strip arm numbering before parsing (kills the
   `"… Entertainment 2"` artifact from `20250322123458076116`). Target: `disjunction_flattened`
   134 → ≤100 and both example uids produce 2 non-empty arms.
2. **Intercity negation → complement (G4):** on a negated mode mention, emit the complement
   (binary domain) for the stated leg(s): "do not take the train to the destination" →
   `outbound: airplane`; "do not fly back" → `return: train`. Guard with the existing negation
   helpers. Test uids: `20250322204425912419`, `20250324210212304930`.
3. **Coverage gaps:** outbound "take the X to the destination" (`20250321032641509206`);
   multi-mode exclusions "walking or taxi" (`20250322035350348919`).
4. **Tighter-or-equal numeric readings (G1 corollary):** NL distances are display-rounded from
   unrounded oracle floats (2.11 vs 2.1037…). Parse "within X km" as `X` but have the *verifier
   side* (and solver acceptance) use `X - 0.01` km (2-decimal display rounding bound) so accepted
   hotels are oracle-safe; keep the parsed display value in the constraint dict for diffing.
   Measure via reject-side proxy + the `hotel_nearby` wrong_value bucket; if data shows NL values
   are sometimes rounded *down*, drop this substep and document why.

### N4 — Recall-first LLM audit (rewrite the merge policy + prompt around G1)

Do after N2/N3 (each regex change cold-starts the audit's LLM cache anyway; batch them).

**Files:** `chinatravel/agent/phase2/normalize.py` (`build_llm_parse_prompt`, `_apply_patch` /
patch acceptance), fixture-backed tests for the merge guard (default suite) plus one live
DeepInfra smoke under the N7 `llm` marker.

- **Deterministic merge guard (the part that doesn't trust the model):** reject `remove` patches
  outright unless (a) accompanied by an opposite-polarity `add`/`replace` for the same span
  (polarity-flip case), or (b) the family is in a small removal-whitelist of demonstrated
  over-extractors. Families with strong extractors are never removable.
- **Prompt reframe:** drop "the parser is known to OVER-EXTRACT"; instruct the model to audit for
  (1) constraints the parser *missed* (recall), (2) *wrong values* (quote NL span + corrected
  value), (3) polarity errors; keep removes as the rare case requiring a quoted contradicting
  span.
- **Measure:** `scripts/phase2_llm_parse_probe.py` first (~40 disagreement uids, 1 call each);
  then one paid full-val `--llm-parse` run (~100 min, cold cache — budget for it once, after N2/N3
  are stable): recall must recover to ≥ the deterministic parser's recall, `behavioral_balanced`
  ≥ deterministic. Then the standard e2e ladder. This also refreshes the stale 0.8694 number.

### N5 — Generalization probe on the HF dataset (read-only, ~an hour of work)

Wire `scripts/parser_vs_oracle.py` to accept the HF `default` subset (654 queries; map
`nature_language_en` → `nature_language`, Chinese city names → English per
`docs/tpc_phase2_hf_dataset.md`; loader precedent exists in `load_datasets.py`). Run the full
report (deterministic first; LLM-audit run optional/paid). Record val-vs-HF deltas in
`docs/tpc_phase2_eval.md` as the first held-out-phrasing measurement. **Decision input:** a big
drop (> ~10 behavioral pts) escalates M2 (LLM-first extraction) from "A/B worth running" to
"likely necessary". Do not fix anything HF-specific — it's a measurement set, not a tuning set
(tuning on it would burn our only generalization signal).

### N6 — `max_retries=0` (two-line fix + test; close plan-1's known follow-up) [landed 2026-07-13]

`chinatravel/agent/phase2/llm_client.py:219` — `max_retries: 1 → 0`, assert single-attempt in a
test with a mocked transport. Unit-test only change.

### N7 — Parser regression harness: a fast pytest test for every parsing bug (TDD + stays-fixed guarantee) [landed 2026-07-13]

**Rationale:** `tests/phase2/test_parser_accuracy.py` already does exactly this for plan-1's three
fixes ("Phase A": taxi derivation, restaurant negation, budget disambiguation) — frozen NL snippet
in, asserted constraints out, milliseconds per test. Generalize that into a standing rule so every
gap-map bug gets a failing test *before* its fix and can never silently regress, and add an opt-in
live-LLM tier so the DeepInfra-facing plumbing is also covered (calls are cheap enough that a
handful per run is fine).

**Two tiers:**

**Tier 1 — deterministic (default suite; no network; runs in `make phase2-test`).**
- For each bug in G2/G3/G4 (and every parser bug found later): write the test first, quoting the
  evidencing NL verbatim from the val uid (uid in a comment), then fix. Home:
  `test_parser_accuracy.py` for `parse_constraints.py` fixes, `test_entity_resolution.py` (N2) for
  the normalize-layer resolution pipeline — test the layer that owns the fix (raw
  `parse_query_no_oracle` output vs. `parse_to_ir` + `ir_to_solver_variants` variants).
- **Assert recall-style, per G1:** the expected constraints are *present with correct values*;
  don't assert the absence of extras unless the bug itself is a polarity inversion or misrouting.
  Asserting exact full-dict equality would make every test brittle against unrelated recall
  improvements — the failure mode G1 says we should welcome.
- Green-before-commit applies to this tier as to everything else in the default suite.

**Tier 2 — live-LLM smokes (new opt-in pytest marker `llm`; DeepInfra; ~cents per run).**
- Register the `llm` marker in `pyproject.toml` and exclude it by default
  (`addopts = "-q -m 'not integration and not llm'"`). Tests `pytest.skip` at collection when
  `INFRADEEP_API_KEY` is unset; they must **not** use the `no_network` fixture. Run with
  `.venv/bin/python -m pytest tests/phase2 -m llm`.
- Scope: guard the real-endpoint plumbing and merge policy, not model quality — e.g. one
  unambiguous canonical query through the Stage-1 LLM path asserting
  `llm_parse_attempted and not llm_parse_failed`, the patch parses and touches only
  `_LLM_PARSE_ALLOWED_KEYS`, and (after N4) the merge guard's remove-rejection semantics hold
  against a live response. Keep it to ≤ ~5 calls per run.
- Model output is nondeterministic: assert **properties any correct response satisfies**
  (schema-validity, whitelisted keys, an unambiguous constraint present), never exact strings.
- Flake policy: Tier 2 is a pre-flight signal, not a commit gate — run it before paid full-val
  LLM runs and before any change to `llm_client.py` / the parse prompts ships, not on every
  commit.

**Accept:** marker registered + default suite still hermetic (SpyLLMClient/`no_network` invariants
untouched); every N2/N3 substep lands with its Tier-1 test; ≥1 Tier-2 smoke exists and passes
against DeepInfra; CLAUDE.md's Tests section updated to document the `llm` marker alongside
`integration` (do this in the same commit the marker lands, so fresh agents see it).

---

## Mid-term (week 2)

### M1 — Deploy the eval worker + the missing characterization rows

The worker code exists (`scripts/phase2_eval_worker.py`, `e31ef2c2`); what remains is VM-2
deployment per plan-2 Step 4's acceptance (a real `--once` run producing a ledger-branch row,
then leave the loop running under `nohup`/`tmux`). Then use it for:
- the **fastfpr calibration pair** (plan-2 Step 3 acceptance, still unexecuted),
- one **900s row** (organizers' primary budget; with dynamic budget the solver gets ~860s —
  verify solver-only approaches its ceiling and e2e parsing loss dominates even more),
- the **det-only anchor** at current HEAD (plan-2 Step 0.2, still missing — needed by M2).

### M2 — Parsing-architecture A/B: LLM-first extraction (plan-2 Step 6; implemented, verdict pending)

The extract mode is implemented and probe-tested (`79121a95`: `TPC_P2_LLM_PARSE_MODE=extract`,
sub-key-preserving dict merge, 0/20 control regressions after fixes; see the Step 6 status
section in `docs/tpc_phase2_design.md`). What remains is the measurement ladder rungs 2–4 (paid
full-val report, fastfpr fold rows per arm, canonical 300s row for the winner) and the written
promotion/kill verdict. Before running the paid rungs: (a) verify the merge policy is
**union-with-deterministic** everywhere per G1 (extraction may add families and correct values,
never silently drop deterministic recall — the dict-family fix suggests this lesson is already
partly absorbed; audit the list/scalar paths too); (b) note the known v1 gap that structured-dict
families (`stay_duration`, `activity_time_windows`, `timing_constraints`) cannot be populated by
extract mode yet — fine for the A/B, fix only on promotion. Decision inputs now include N5's
generalization verdict and the corrected (N1) family stats. If killed, the negative result plus
N4's guarded audit is the shipped architecture.

### M3 — Verifier fidelity pass (after N2 lands)

With canonical entity names, tighten `parsed_verifier._match_text` toward the oracle's comparison
semantics (exact/canonical equality for resolved names; keep substring only for unresolved
strings). Audit the remaining verifier families against the oracle DSL semantics the same way the
taxi-vacuity fix was done (read `hard_logic_py` encodings for each family; the
`required_hotel_all_types` all-vs-any semantics deserves a check). Measure: reject-side proxy up,
no accept-side drop, then diff-eval (verifier changes alter acceptance → full-run fallback if the
allowlist guard refuses).

### M4 — Constraint-light feasible fallback (close G7)

When Stage 2 produces nothing (no candidate, no recovery plan), spend the remaining pre-finalize
budget solving with an **empty constraint set** (schema+commonsense only — the solver's easiest
case) instead of returning an empty itinerary. Reuse `make_tpcagent_solve_fn` with `variants=[{}]`
and a small time box. Test via injected `solve_fn` failures; measure never (it's insurance —
verify on a synthetic unparsable query via `scripts/run_query.py --query-text`).

### M5 — Solver headroom worklist (only if M1's 900s row still shows ≥ ~4 pts headroom)

Work the G8 census: a targeted repair move that pins `activity_time_windows`/`position_presence`
POIs into the day schedule early (the current repair loop treats them as generic misses); check
CP-SAT's time-window encoding covers meal-POI windows; consider a 2-seed restart portfolio within
the same budget to blunt the formulation-sensitivity effect documented in
`docs/tpc_phase2_eval.md` (the 60s pass→fail flips without timeout). Gate each change on
solver-only FPR at 300s via the eval worker.

---

## Long-term (toward submission, week 3+ / as evidence dictates)

### L1 — Parse-hypothesis portfolio (research idea; only after M2 settles)

When Stage 1 confidence is low (audit and deterministic parse disagree, or extraction and regex
disagree), solve the top-2 constraint hypotheses within the budget and return the plan that
satisfies the **union** of both (superset-safe per G1) if feasible, else the higher-confidence
one. This converts parse uncertainty into solver work — which is cheap (headroom exists at 900s)
— instead of a coin flip. Measure like any parser change (it only helps if disagreement uids
flip). Skip entirely if N2–N4 push parsing loss below ~5 pts.

### L2 — Held-out robustness hardening

- One HF-`default` e2e row (harness end-to-end on foreign phrasing, oracle-scored) on VM 2.
- Optional paraphrase stress test: LLM-generate paraphrases of ~50 val queries offline, run the
  solver-free parser report on them (cheap recall-robustness probe; never tune on HF).
- Unseen-city smoke: verify the harness degrades gracefully (fallback, no crash) on a query whose
  city data is absent.

### L3 — Submission packaging and endpoint parity (must happen before 08-01)

Plan-1 Step 7 (SGLang preset + smoke script), organizer-shaped `agent_env/config.toml` defaults
(900s, method name, resume on), a cold-cache 5-run variance characterization at the final config
(repeats ≥ 2 *without* the LLM disk cache, or with it deleted between repeats — the organizers'
runs share no cache), a 900s RSS soak (the 150-query soak ran at 10s), and a final held-out-test
sanity run only at the very end per the split discipline. Freeze window: last 2–3 days before
submission, no non-critical merges.

### L4 — Preference-score optimization (explicitly deferred until e2e FPR ≥ ~90)

FPR is the primary metric, but the continuous score (`overall_true` e2e 86.4 vs solver-only 94.4)
carries its own ~8-pt parsing-flavored gap plus packing headroom (DAV/ATT/DDR). Once FPR
plateaus, revisit: preference-aware packing already exists in `TPCAgent._pack_plan`; the wins are
likely in giving it more time (fastfpr showed most budget goes to polish — quantify what polish
buys) and in soft-preference parsing (currently ignored entirely). Do not start this while
parsing loss > ~5 FPR pts.

### L5 — Stage 3 LLM refinement (keep the stub; trigger condition unchanged)

Only becomes relevant if solver headroom exceeds parsing loss at 900s (it never has: 4.7 vs 12.9
at 300s). If M1's 900s row changes that, design a bounded, acceptance-gated refine loop then —
not before.

## Priority summary

| Step | Expected FPR impact (fold-0 evidence) | Cost | Risk |
| --- | --- | --- | --- |
| N2 entity resolution | 3–7 pts of the 12.9 parsing loss | 2–3 days | low (flag-gated, deterministic) |
| N3 extractor fixes | 2–4 pts (OR-arms + negation uids) | 1–2 days | low |
| N4 recall-first audit | 1–3 pts (stops LLM-side recall loss) | 1 day + 1 paid run | medium (prompt iteration) |
| N1/N5/N6/N7 | 0 direct; unblock decisions + lock fixes in | hours | none |
| M1–M5 | characterization + ≤4.7 pts solver | days | medium |
| L1–L5 | robustness/preference tail | week 3 | — |

## Definition of done (plan level)

- N1–N7 landed with their measured acceptance checks; at least one post-N2/N3 canonical 300s row
  gated green vs `20260712T060018Z` and recorded in the ledger.
- M1's worker producing rows; 900s + det-anchor + fastfpr-calibration rows exist.
- M2 concluded with a written promotion/kill verdict (the standing architecture question closed).
- Docs current after every step (design/eval status sections + this file's step statuses + the
  ledger); all work committed and pushed on `stefan/phase2` with green tests.
