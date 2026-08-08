# Technical report

The Phase 2 technical report for team `fabiundstefan`, in the official IJCAI template.

`fabiundstefan.pdf` is **version 4** (2026-08-09), 4 pages, built from
`fabiundstefan.tex`. It supersedes v3. The owner's annotated review of v2 is kept at
[`feedback/fabiundstefan_v2.pdf`](feedback/fabiundstefan_v2.pdf); every annotation is addressed
below.

**What changed in v4.** The report now describes the *submitted* `v2` system and the evidence for it:
the five-team leaderboard reading (the whole gap to first place is the per-clause rate; a full-plan
rate of zero is the entire field, not one system's defect), a new subsection on what `v2` changes with
the paired free-prose measurement behind it (new `figures/v1_v2_free_prose.pdf`), the familiar-register
whole-run regression check, the negative validator-in-loop LLM-repair result, and a section on using the
competition as a deliberately low-risk vibe-coding experiment — including the repository-scale numbers
(798 commits, 100 merged pull requests of 109 opened, 1339 tests, 47 committed screens, 63 recorded
rows) and the two honest limits that go with them. The superseded phrasing-register figure was dropped
to stay inside four pages.

**Note on review comment 10.** v3 removed repository-history counts because the v2 review called them
questionable. v4 reintroduces them at the owner's explicit request (2026-08-08), with every number
taken from `git` at the commit the report is built from rather than estimated, and paired with a
statement that output volume is not itself a result.

## v2 review comments and how each is addressed

| # | Comment group | Resolution in v3 |
| --- | --- | --- |
| 1 | Remove Stefan's work affiliation; use the Outlook address; put the authors in separate columns | The title block now has two columns, no Stefan affiliation, and `stefanbschneider@outlook.com` |
| 2 | Use American English, consistent “itinerary” terminology, positive verifier wording, and simpler sentences | Rewritten throughout; the abstract says the gate can only emit confirmed-valid itineraries |
| 3 | Link and cite the challenge, retain the example query, and explain environmental validity concretely | The introduction links the challenge, cites ChinaTravel, keeps the Suzhou example, and names sandbox entities, hours, transportation, and costs |
| 4 | Expand the system section into pipeline, parsing, solver, and repair/densification; clarify the fallback | Section 2 now has four subsections. Figure 1 follows query → parsed constraints → simplified itinerary. The text states that an empty schema-valid fallback still scores zero |
| 5 | Distinguish the constrained agent phase from the earlier offline phase; explain the two-submission policy | The introduction contrasts the phases; §3 explains that the better of two harness versions is retained and v1 was submitted early for held-out feedback |
| 6 | Reduce journal-style chronology, internal split names, and number density; do not portray the in-distribution measurement choice as foolish | The body is organized around the final system and findings. Dataset descriptions are reader-facing, and §3 explains why prioritizing the advertised in-distribution set was reasonable |
| 7 | Include current-main improvements and evaluation | R28 and the official metric breakdown are in Table 1; current recall fixes and P22's zero-residual static screen are reported with their limits |
| 8 | Answer “why not just use the free LLM for parsing?” and discuss prompting, tools, and database vocabularies | §4 reports both extraction experiments, explains the value-grounding bottleneck, and describes direct catalog/tool or MCP access as the right next interface |
| 9 | Cite the neuro-symbolic baseline and make clear that reported experiments were run | RuleNeSy is cited through the ChinaTravel paper; §3 states the matched sample sizes and observed outcomes rather than extrapolating an unrun arm |
| 10 | Distinguish coding agents from the organizer-hosted Qwen model and remove questionable repository-history counts | §4 treats coding agents, model-based parsing, and Qwen itinerary generation separately; commit and line-count claims are removed |
| 11 | Broaden the conclusion to transferable lessons, production APIs, and personalized objectives | The conclusion covers agentic engineering, grounded language understanding, deterministic optimization, live APIs/MCP, replanning, and user-specific preferences |
| 12 | There are no post-submission competition next steps | Pending evaluation is described only to bound the P22 claim; outside-challenge work appears as production-oriented future work |

## What the organizers require

Confirmed by their 2026-08-04 reply (see
[`../docs/reference/competition.md`](../docs/reference/competition.md#technical-report-2026-08-04-organizer-reply)):

| | |
| --- | --- |
| Who | **every** team that qualified, not just top finishers |
| Format | official IJCAI paper template, **max 4 pages** |
| Anonymity | none — real names and affiliations |
| File | PDF named after the team: `fabiundstefan.pdf` |
| Where | the same portal as the harness zip |
| Deadline | 2026-08-10, 24:00 Beijing Time (UTC+8) |
| Judged on | technical reliability and soundness, innovation, clarity of presentation |

## Build

```bash
cd report && make          # pdflatex -> bibtex -> pdflatex x2 -> fabiundstefan.pdf
make clean                 # remove aux/log/bbl/blg/out, keep the PDF
```

On macOS with MacTeX the binaries are not on `PATH` by default:

```bash
cd report && PATH="/Library/TeX/texbin:$PATH" make
```

`make` prints a loud warning above 4 pages and still writes the PDF. **Check for that warning before
submitting** — v4 builds at exactly 4 pages, so any addition needs a matching cut.

Needs a TeX installation providing `pdflatex`, `bibtex` and the packages the report loads (`times`,
`url`, `hyperref`, `caption`, `graphicx`, `amsmath`, `amsthm`, `booktabs`). On Debian/Ubuntu:

```bash
apt-get install -y --no-install-recommends \
  texlive-latex-base texlive-latex-recommended texlive-fonts-recommended
```

The figures are committed as PDFs, so **the report builds without Python**. Regenerate them only when
a number changes:

```bash
.venv/bin/python scripts/report_figures.py            # writes report/figures/*.pdf
.venv/bin/python scripts/report_figures.py --check    # verify every cited artifact, plot nothing
```

The figure script uses matplotlib (in `requirements.txt`, not in the submission requirements) and
deliberately avoids TikZ, so the report needs no extra TeX packages.

## Files

| Path | Origin |
| --- | --- |
| `fabiundstefan.tex` | the report |
| `fabiundstefan.pdf` | built output — the file that gets submitted |
| `figures/*.pdf` | generated by `../scripts/report_figures.py`; committed so the build needs no Python |
| `feedback/fabiundstefan_v1.pdf` | the owner's annotated review of v1 |
| `feedback/fabiundstefan_v2.pdf` | the owner's annotated review of v2 |
| `ijcai26.sty`, `named.bst`, `ijcai26.bib` | official [IJCAI author kit](https://www.ijcai.org/authors_kit), unmodified |
| `template/` | the kit's own instructions and Word template, kept for reference |

Do not edit `ijcai26.sty` or `named.bst` — the formatting is part of the requirement.

## Writing it

Take numbers only from committed artifacts under
[`../results/phase2_baselines/`](../results/phase2_baselines/) — never from an uncommitted local run,
and never compare across an evaluator sync (each row records its `evaluator_parity`).
[`../docs/tpc_phase2_eval.md`](../docs/tpc_phase2_eval.md) defines what a comparable row is and, since
2026-08-06, what a local row does **not** license: it measures a configuration on one phrasing
register, not held-out performance.

Every number in the `.tex` has a comment naming its source, tagged `ROW` (whole-set run), `SCREEN`
(paired A/B at reduced scale) or `PORTAL` (the organizers' returned score, not reproducible locally).
Keep that convention — it is what makes the report auditable, and `report_figures.py --check` enforces
the figure half of it.

**Submission is a manual owner action.** No agent uploads the report or the archive.
