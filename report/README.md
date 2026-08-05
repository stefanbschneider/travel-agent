# Technical report

The Phase 2 technical report for team `fabiundstefan`, in the official IJCAI template.

`fabiundstefan.pdf` is a **first full draft** (2026-08-05): every section is written and every number
traces to a committed artefact, but five decisions are still open and are listed as an `OPEN TODOs`
block at the end of `fabiundstefan.tex`. The most important two: the Phase 1 placement sentence cites
a score taken on the pre-2026-07-28 evaluator whose leaderboard the organizers have said will be
re-scored, and Table 1 is the **pre-P1** reference row, so it must be replaced if a better whole-run
row lands before the deadline.

The draft's frame is deliberate and worth knowing before editing it: the report argues that the LLM
belongs in the loop that *writes* the solver, not the loop that *runs* it, and it supports the absent
inference-time LLM with an ablation table (parse audit `−3.20`, refine `0` of `18` edits committed,
oracle-constraint upper bound `≤ 0`). If the untried move-proposer direction (roadmap `P6`) ever
screens green, that frame changes rather than breaks — see TODO 3.

## What the organizers require

Confirmed by their 2026-08-04 reply (see
[`../docs/reference/competition.md`](../docs/reference/competition.md#technical-report-2026-08-04-organizer-reply)):

| | |
| --- | --- |
| Who | **every** team that qualified for Phase 2, not just top finishers |
| Format | official IJCAI paper template, **max 4 pages** |
| Anonymity | none — real names and affiliations |
| File | PDF named after the team: `fabiundstefan.pdf` |
| Where | the same Phase 2 portal as the harness zip |
| Deadline | 2026-08-10, 24:00 Beijing Time (UTC+8) |
| Judged on | technical reliability and soundness, innovation, clarity of presentation |

Content is free-form: system/method description, implementation details, ablations, results, and
error analysis are all acceptable.

## Files

| Path | Origin |
| --- | --- |
| `fabiundstefan.tex` | our report (skeleton) |
| `fabiundstefan.pdf` | built output — the file that gets submitted |
| `ijcai26.sty`, `named.bst`, `ijcai26.bib` | official [IJCAI author kit](https://www.ijcai.org/authors_kit), unmodified |
| `template/ijcai26_formatting_guidelines.tex` | the kit's own instructions document, kept for reference |
| `template/ijcai26.docx` | the kit's Word template, unused |

The author kit was downloaded on 2026-08-04 from
<https://www.ijcai.org/sites/default/files/Guidelines/FormattingGuidelines-IJCAI-ECAI-26.zip>.
Do not edit `ijcai26.sty` or `named.bst` — the formatting is part of the requirement.

## Build

```bash
cd report && make          # pdflatex -> bibtex -> pdflatex x2 -> fabiundstefan.pdf
make clean                 # remove aux/log/bbl/blg/out, keep the PDF
```

On macOS with MacTeX the binaries are not on `PATH` by default:

```bash
cd report && PATH="/Library/TeX/texbin:$PATH" make
```

Needs a TeX installation providing `pdflatex`, `bibtex`, and the packages the report loads
(`times`, `url`, `hyperref`, `caption`, `graphicx`, `amsmath`, `amsthm`, `booktabs`). On
Debian/Ubuntu that is three packages:

```bash
apt-get install -y --no-install-recommends \
  texlive-latex-base texlive-latex-recommended texlive-fonts-recommended
```

The author kit's own preamble also loads `soul`, `algorithm`, `algorithmic` and `lineno`; the
report drops them, since none is a formatting requirement (`ijcai26.sty` is) and they need the
much larger `texlive-latex-extra`. Add back whichever a section actually needs, with that package.

`make` prints a loud warning if the PDF exceeds 4 pages but still writes it — an over-long draft
is easier to cut down when you can read it. Check for that warning before submitting.

## Writing it

Take numbers only from committed rows under
[`../results/phase2_baselines/`](../results/phase2_baselines/) — never from an uncommitted local
run, and never compare rows across an evaluator sync (each row records its `evaluator_parity`).
[`../docs/tpc_phase2_eval.md`](../docs/tpc_phase2_eval.md) defines what a comparable row is, and
[`../docs/tpc_phase2_roadmap.md`](../docs/tpc_phase2_roadmap.md) carries the chronology of which
mechanism was promoted on which evidence — that is the ablation table's source.

The report is **not** the optional short system-description paper the site mentions; that one is
invited from top-ranked teams after final results.
