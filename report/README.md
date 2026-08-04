# Technical report

The Phase 2 technical report for team `fabiundstefan`, in the official IJCAI template.

`fabiundstefan.pdf` is currently a **placeholder build of a skeleton** — every section of
`fabiundstefan.tex` is a TODO. It exists so the build path is proven and the submission checklist
has something to point at, not because the report is written.

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
