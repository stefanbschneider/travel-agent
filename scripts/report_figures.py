#!/usr/bin/env python3
"""Generate every figure in the technical report, from committed artifacts only.

The owner's review of report v1 asked for two things this script provides:

  * a figure showing the architecture / pipeline of the system, and
  * plots instead of (or in addition to) the result tables, with the plotting scripts
    committed alongside the report so the evaluation section is fully reproducible.

Every number plotted here is either read directly out of a committed row under
``results/phase2_baselines/`` or listed in ``LITERALS`` below with the committed screen it
comes from. Nothing is typed in from a local run, and nothing is recomputed at plot time.

Usage::

    .venv/bin/python scripts/report_figures.py                 # write report/figures/*.pdf
    .venv/bin/python scripts/report_figures.py --check         # verify sources, plot nothing

Outputs (PDF, vector, no external font dependency beyond matplotlib's default):

    report/figures/architecture.pdf     the pipeline, and where the model does and does not act
    report/figures/registers.pdf        score by query phrasing register, incl. the held-out point
    report/figures/ablation.pdf         mechanism ablation and external baselines
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
ROWS = REPO / "results" / "phase2_baselines" / "full_runs"
SCREENS = REPO / "results" / "phase2_baselines" / "screens"
OUT = REPO / "report" / "figures"

# --- Sources -------------------------------------------------------------------------------

#: Committed whole-run rows, by the label the report uses for them.
ROW_SOURCES: dict[str, str] = {
    "familiar_100": "20260807T152009Z.json",  # R28, current-main baseline
    "local_released_150": "20260806T132917Z.json",  # R18
    "pre_window_anchor": "20260805T081535Z.json",  # R7, one of three bit-identical repeats
    "window_anchor": "20260805T123142Z.json",  # R8
    "window_push_insert": "20260806T052925Z.json",  # R14
}


@dataclass(frozen=True)
class Literal:
    """A number that lives in a committed screen rather than in a row's JSON."""

    value: float
    source: str
    note: str = ""


#: Numbers from committed screens and from the organizers' portal. Each names its evidence so a
#: reader (or a later agent) can check it without rerunning anything.
LITERALS: dict[str, Literal] = {
    # The organizers' returned score for v1. Not a local measurement and not reproducible here.
    "held_out_v1": Literal(
        33.2473,
        "organizer portal, returned 2026-08-06 for submissions/phase2/fabiundstefan_v1.zip",
        "the only external calibration this project has",
    ),
    # Free-prose end-to-end pair, matched budget/workers/n against a familiar-100 control.
    "free_prose_before": Literal(
        41.6198, "screens/20260806_generalization_probe/e2e/official_scores.json"
    ),
    "free_prose_after": Literal(
        49.9909, "screens/20260806_parser_phrasing_fix/README.md", "after the phrasing fix"
    ),
    "familiar_30_control": Literal(
        64.56528973412726,
        "screens/20260806_parser_phrasing_fix/README.md",
        "n=30 control, identical before and after the fix to every decimal",
    ),
    # External baselines, same 8 uids per register (Exp 2) and 4 uids (Exp 3).
    "llm_only_familiar": Literal(1.88, "screens/20260806_llm_arms/README.md", "Act, n=8"),
    "llm_only_free_prose": Literal(2.64, "screens/20260806_llm_arms/README.md", "Act, n=8"),
    "ours_llm_only_familiar": Literal(67.71, "screens/20260806_llm_arms/README.md", "same 8 uids"),
    "ours_llm_only_free_prose": Literal(48.49, "screens/20260806_llm_arms/README.md", "same 8 uids"),
    "rulenesy_familiar": Literal(9.54, "screens/20260806_llm_arms/README.md", "RuleNeSy, n=4"),
    "rulenesy_free_prose": Literal(9.44, "screens/20260806_llm_arms/README.md", "RuleNeSy, n=4"),
    # Parse-gap rates from the static probe, as percentages of oracle clauses.
    "gap_familiar": Literal(0.0, "screens/20260806_generalization_probe/probe.json"),
    "gap_local_150": Literal(3.3, "screens/20260806_generalization_probe/probe.json"),
    "gap_hf_easy": Literal(13.9, "screens/20260806_generalization_probe/probe.json"),
    "gap_hf_human": Literal(21.2, "screens/20260806_generalization_probe/probe.json"),
    "gap_hf_medium": Literal(28.7, "screens/20260806_generalization_probe/probe.json"),
}


def load_row(key: str) -> dict[str, Any]:
    """Read one committed whole-run row."""
    path = ROWS / ROW_SOURCES[key]
    if not path.exists():
        raise FileNotFoundError(f"committed row missing: {path}")
    with path.open() as handle:
        row = json.load(handle)
    if row.get("kind") != "full_run":
        raise ValueError(f"{path} is not a whole-run row")
    return row


def check_sources() -> None:
    """Fail loudly if any cited artifact is missing, before plotting anything."""
    for key in ROW_SOURCES:
        row = load_row(key)
        scores = row["official_scores"]
        print(
            f"  row {key:<22} {ROW_SOURCES[key]}  overall {scores['overall']:.4f}  "
            f"FPR {scores['FPR']:.1f}  sha {row['git_sha'][:8]}"
        )
    for name, lit in LITERALS.items():
        marker = "screens/" in lit.source
        exists = (SCREENS / lit.source.split("screens/", 1)[1]).exists() if marker else True
        status = "ok" if exists else "MISSING"
        print(f"  literal {name:<24} {lit.value:>10}  [{status}] {lit.source}")


# --- Figures -------------------------------------------------------------------------------


def _style() -> None:
    import matplotlib as mpl

    mpl.rcParams.update(
        {
            "figure.dpi": 150,
            "font.size": 8,
            "axes.titlesize": 9,
            "axes.labelsize": 8,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "legend.frameon": False,
            "pdf.fonttype": 42,  # editable text in the PDF, not outlines
        }
    )


def figure_architecture(path: Path) -> None:
    """The per-query pipeline, the whole-run scheduler, and where a model does/does not act."""
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

    fig, ax = plt.subplots(figsize=(7.0, 2.75))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 41)
    ax.axis("off")

    solver_fc, solver_ec = "#eaf0f8", "#3a5f8f"
    gate_fc, gate_ec = "#e7f2e7", "#2f6b33"
    env_fc, env_ec = "#f4f0e6", "#8a7327"

    def box(x, y, w, h, label, fc, ec, *, bold=False, fontsize=7.4):
        ax.add_patch(
            FancyBboxPatch(
                (x, y),
                w,
                h,
                boxstyle="round,pad=0.5,rounding_size=1.2",
                linewidth=1.0,
                facecolor=fc,
                edgecolor=ec,
            )
        )
        ax.text(
            x + w / 2,
            y + h / 2,
            label,
            ha="center",
            va="center",
            fontsize=fontsize,
            fontweight="bold" if bold else "normal",
            color="#111111",
            linespacing=1.35,
        )

    def arrow(x1, y1, x2, y2, *, style="-|>", color="#444444", ls="-", rad=0.0):
        ax.add_patch(
            FancyArrowPatch(
                (x1, y1),
                (x2, y2),
                arrowstyle=style,
                mutation_scale=8,
                linewidth=0.9,
                color=color,
                linestyle=ls,
                connectionstyle=f"arc3,rad={rad}",
                shrinkA=1.5,
                shrinkB=1.5,
            )
        )

    y = 17.0
    h = 9.5
    stages = [
        (0.0, 13.0, '"3 days in Suzhou\nGarden 9--11\nbudget <= 3000"', "#ffffff", "#888888"),
        (16.0, 13.0, "parsed constraints\ncity=Suzhou\nbudget<=3000\nGarden@9--11", solver_fc, solver_ec),
        (33.0, 14.0, "normalize\nresolve POI\nkeep OR branches", solver_fc, solver_ec),
        (50.0, 14.0, "construct itinerary\nbuild · CP-SAT\nrepair · restarts", solver_fc, solver_ec),
    ]
    for x, w, label, fc, ec in stages:
        box(x, y, w, h, label, fc, ec, fontsize=6.2)
    box(67.0, y, 18.0, h, "acceptance gate\nschema\ncommonsense · logic",
        gate_fc, gate_ec, bold=True, fontsize=6.5)
    box(88.0, y, 11.0, h, "Day 1\n09:00 Garden\n12:00 lunch\n...", "#ffffff", "#888888", fontsize=6.2)

    for x1, x2 in [(13.0, 16.0), (29.0, 33.0), (47.0, 50.0), (64.0, 67.0), (85.0, 88.0)]:
        arrow(x1, y + h / 2, x2, y + h / 2)

    # Reject loop: the gate sends a plan back into search, never to output.
    arrow(74.0, y + h, 58.0, y + h, rad=0.55, color=gate_ec, ls="--")
    ax.text(66.0, y + h + 5.1,
            "reject → keep searching (nothing unverified is emitted)",
            ha="center", va="center", fontsize=6.5, color=gate_ec, style="italic")

    # Whole-run scheduler across the top.
    ax.text(0.0, 37.6, "one shared 5 h wall clock, $cores-1$ workers:", fontsize=6.9,
            color="#333333", va="center", ha="left")
    for sx, sw, slabel in [(41.0, 17.0, "triage"), (61.0, 17.0, "repair"), (81.0, 17.0, "polish")]:
        box(sx, 34.0, sw, 6.2, slabel, "#f2f2f2", "#888888", fontsize=7.0)
    arrow(58.0, 37.1, 61.0, 37.1)
    arrow(78.0, 37.1, 81.0, 37.1)

    # Environment: every fact is read from it.
    box(16.0, 2.5, 69.0, 6.2,
        "sandbox environment  ·  every POI, price, opening hour and travel time",
        env_fc, env_ec, fontsize=7.0)
    for ex in (22.5, 40.0, 57.0, 76.0):
        arrow(ex, 8.7, ex, y, color=env_ec, ls=":")

    ax.text(
        0.0,
        0.2,
        "AI roles: coding agents built the pipeline; optional Qwen parsing reads language; "
        "the deterministic solver and verifier own the itinerary.",
        fontsize=6.8,
        color="#555555",
        style="italic",
        va="center",
    )

    fig.tight_layout(pad=0.2)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def figure_registers(path: Path) -> None:
    """Score by phrasing register: the generalization gap, and the held-out point."""
    import matplotlib.pyplot as plt

    familiar = load_row("familiar_100")["official_scores"]
    local150 = load_row("local_released_150")["official_scores"]

    labels = [
        "local released\n(template)",
        "familiar-100\n(template)",
        "free prose\n(HF medium)",
        "organizer\nheld-out",
    ]
    values = [
        local150["overall"],
        familiar["overall"],
        LITERALS["free_prose_after"].value,
        LITERALS["held_out_v1"].value,
    ]
    before = LITERALS["free_prose_before"].value

    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(7.0, 2.5), gridspec_kw={"width_ratios": [1.15, 1]})

    colors = ["#9db8d6", "#3a5f8f", "#c98b3a", "#a33b3b"]
    bars = ax.bar(range(len(values)), values, color=colors, width=0.62)
    # The pre-fix free-prose score, so the plot shows both the gap and the repair.
    ax.plot([2], [before], marker="_", markersize=18, color="#6b4a17", linewidth=0)
    ax.annotate(
        f"{before:.1f} before\nthe phrasing fix",
        xy=(2.0, before),
        xytext=(2.62, before + 12.0),
        fontsize=6.2,
        color="#6b4a17",
        ha="center",
        arrowprops=dict(arrowstyle="-", color="#6b4a17", linewidth=0.6),
    )
    for rect, value in zip(bars, values):
        ax.text(
            rect.get_x() + rect.get_width() / 2,
            value + 1.6,
            f"{value:.1f}",
            ha="center",
            fontsize=7.4,
            fontweight="bold",
        )
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, fontsize=6.4)
    ax.set_ylabel("overall score (0–100)")
    ax.set_ylim(0, 100)
    ax.set_title("Same system, four query registers", loc="left")
    ax.axhline(LITERALS["held_out_v1"].value, color="#a33b3b", linewidth=0.7, linestyle=":")

    # Right panel: what we fail to extract, per register.
    gap_labels = ["familiar-100", "local\nreleased", "easy", "human", "medium"]
    gaps = [
        LITERALS["gap_familiar"].value,
        LITERALS["gap_local_150"].value,
        LITERALS["gap_hf_easy"].value,
        LITERALS["gap_hf_human"].value,
        LITERALS["gap_hf_medium"].value,
    ]
    gcolors = ["#3a5f8f"] + ["#9db8d6"] + ["#c98b3a"] * 3
    gbars = ax2.bar(range(len(gaps)), gaps, color=gcolors, width=0.62)
    for rect, value in zip(gbars, gaps):
        ax2.text(
            rect.get_x() + rect.get_width() / 2,
            value + 0.7,
            "0" if value == 0 else f"{value:.1f}",
            ha="center",
            fontsize=7.4,
            fontweight="bold" if value == 0 else "normal",
        )
    ax2.set_xticks(range(len(gaps)))
    ax2.set_xticklabels(gap_labels, fontsize=6.4)
    ax2.set_ylabel("requirements never extracted (%)")
    ax2.set_ylim(0, 34)
    ax2.set_title("Extraction is clean on exactly one register", loc="left")

    fig.tight_layout(pad=0.4)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def figure_registers_single(path: Path) -> None:
    """Single-column variant: score by phrasing register only.

    The two-panel :func:`figure_registers` does not fit the report's four-page limit as a
    full-width float. This variant keeps the panel that carries the argument; the extraction-gap
    percentages the second panel showed are stated in the text instead.
    """
    import matplotlib.pyplot as plt

    familiar = load_row("familiar_100")["official_scores"]
    local150 = load_row("local_released_150")["official_scores"]

    labels = ["local\nreleased", "familiar-100", "free\nprose", "organizer\nheld-out"]
    values = [
        local150["overall"],
        familiar["overall"],
        LITERALS["free_prose_after"].value,
        LITERALS["held_out_v1"].value,
    ]
    before = LITERALS["free_prose_before"].value

    fig, ax = plt.subplots(figsize=(3.4, 2.35))
    colors = ["#9db8d6", "#3a5f8f", "#c98b3a", "#a33b3b"]
    bars = ax.bar(range(len(values)), values, color=colors, width=0.66)
    ax.plot([2], [before], marker="_", markersize=13, color="#6b4a17", linewidth=0)
    ax.annotate(
        f"{before:.1f} before fix",
        xy=(2.0, before),
        xytext=(2.55, before + 14.0),
        fontsize=6.0,
        color="#6b4a17",
        ha="center",
        arrowprops=dict(arrowstyle="-", color="#6b4a17", linewidth=0.6),
    )
    for rect, value in zip(bars, values):
        ax.text(
            rect.get_x() + rect.get_width() / 2,
            value + 1.8,
            f"{value:.1f}",
            ha="center",
            fontsize=7.0,
            fontweight="bold",
        )
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, fontsize=6.6)
    ax.set_ylabel("overall score (0–100)", fontsize=7.2)
    ax.set_ylim(0, 100)
    ax.tick_params(axis="y", labelsize=7.0)
    ax.axhline(LITERALS["held_out_v1"].value, color="#a33b3b", linewidth=0.7, linestyle=":")

    fig.tight_layout(pad=0.3)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def figure_ablation(path: Path) -> None:
    """Mechanism ablation on the tuned register, and external baselines."""
    import matplotlib.pyplot as plt

    r7 = load_row("pre_window_anchor")["official_scores"]
    r8 = load_row("window_anchor")["official_scores"]
    r14 = load_row("window_push_insert")["official_scores"]
    r17 = load_row("familiar_100")["official_scores"]

    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(7.0, 2.4), gridspec_kw={"width_ratios": [1.1, 1]})

    steps = [
        ("base solver", r7["overall"], r7["FPR"]),
        ("+ window anchor", r8["overall"], r8["FPR"]),
        ("+ push / insert", r14["overall"], r14["FPR"]),
        ("+ verifier fixes", r17["overall"], r17["FPR"]),
    ]
    xs = range(len(steps))
    ax.plot(xs, [s[1] for s in steps], marker="o", markersize=4, color="#3a5f8f", label="overall")
    ax.plot(xs, [s[2] for s in steps], marker="s", markersize=4, color="#c98b3a",
            label="fully-passing queries (%)")
    for i, (_, overall, _) in enumerate(steps):
        ax.annotate(f"{overall:.2f}", (i, overall), textcoords="offset points", xytext=(0, 6),
                    ha="center", fontsize=6.6)
    ax.set_xticks(list(xs))
    ax.set_xticklabels([s[0] for s in steps], fontsize=6.4)
    ax.set_ylim(20, 75)
    ax.set_ylabel("score / rate")
    ax.set_title("One missing move dominates the tuned register", loc="left")
    ax.legend(fontsize=6.4, loc="lower right")

    # External baselines, paired on identical query subsets.
    groups = ["LLM only\n(no solver)", "upstream\nneuro-symbolic", "ours"]
    familiar_vals = [
        LITERALS["llm_only_familiar"].value,
        LITERALS["rulenesy_familiar"].value,
        LITERALS["ours_llm_only_familiar"].value,
    ]
    prose_vals = [
        LITERALS["llm_only_free_prose"].value,
        LITERALS["rulenesy_free_prose"].value,
        LITERALS["ours_llm_only_free_prose"].value,
    ]
    width = 0.36
    idx = range(len(groups))
    ax2.bar([i - width / 2 for i in idx], familiar_vals, width, label="template phrasing",
            color="#3a5f8f")
    ax2.bar([i + width / 2 for i in idx], prose_vals, width, label="free prose", color="#c98b3a")
    for i, (a, b) in enumerate(zip(familiar_vals, prose_vals)):
        ax2.text(i - width / 2, a + 1.4, f"{a:.1f}", ha="center", fontsize=6.6)
        ax2.text(i + width / 2, b + 1.4, f"{b:.1f}", ha="center", fontsize=6.6)
    ax2.set_xticks(list(idx))
    ax2.set_xticklabels(groups, fontsize=6.4)
    ax2.set_ylim(0, 80)
    ax2.set_ylabel("overall score (0–100)")
    ax2.set_title("Small paired subsets, same queries per pair", loc="left")
    ax2.legend(fontsize=6.4, loc="upper left")

    fig.tight_layout(pad=0.4)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify every cited artifact exists and print its value, without plotting",
    )
    parser.add_argument("--out-dir", type=Path, default=OUT)
    args = parser.parse_args()

    print("Sources:")
    check_sources()
    if args.check:
        return 0

    _style()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    figures = {
        "architecture.pdf": figure_architecture,
        "registers.pdf": figure_registers,
        "registers_single.pdf": figure_registers_single,
        "ablation.pdf": figure_ablation,
    }
    print("\nFigures:")
    for name, fn in figures.items():
        target = args.out_dir / name
        fn(target)
        print(f"  wrote {target.relative_to(REPO)} ({target.stat().st_size // 1024} KiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
