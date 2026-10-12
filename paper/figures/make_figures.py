#!/usr/bin/env python3
"""Generate the paper's DATA figures from data/results/attempts.jsonl.

WHY THIS IS A SCRIPT AND NOT AN IMAGE-GENERATION PROMPT.

These figures encode measured results, so they are plotted from the campaign
log (data/results/attempts.jsonl) and the saved bootstrap output
(data/results/uncertainty.json), never drawn by hand or by an image model.
The conceptual pipeline figure (fig1_pipeline.png) carries no data.

File names predate the camera-ready numbering. In the camera-ready paper:
    fig4_funnel        -> Figure 2 (from 300 attempts to one clean repair)
    fig2_uncertainty   -> Figure 3 (paired differences vs F3)
    fig3_patch_type    -> Figure 4, Appendix C (structural edits by condition)

    python paper/figures/make_figures.py

Outputs PDF (vector, for LaTeX) and PNG (for slides) into this directory.
Fonts are embedded as TrueType (pdf.fonttype 42); the camera-ready rules
reject Type 3 fonts, which is matplotlib's default.
"""
from __future__ import annotations

import collections
import json
import pathlib
import sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent.parent
ATTEMPTS = REPO / "data" / "results" / "attempts.jsonl"

CONDS = ["F1", "F2", "F3", "F4a", "F4b"]
LABELS = {"F1": "F1\nraw trace", "F2": "F2\nsummary", "F3": "F3\ncertificate",
          "F4a": "F4a\n+node", "F4b": "F4b\n+decision"}

INK = "#151A16"
MUTE = "#5A625B"
ACCENT = "#26418F"
NEG = "#9E1B32"
POS = "#0E6F5C"

plt.rcParams.update({
    "font.family": "serif",
    # Liberation Serif is a TrueType font metric-compatible with Times, which
    # the paper body is set in (Nimbus Roman, the closer clone, is CFF-based and
    # matplotlib embeds it with a font-type mismatch). Without one of these
    # matplotlib falls back to DejaVu Serif, which it embeds as Type 3 by
    # default, and the camera-ready rules reject Type 3 fonts. fonttype 42
    # embeds TrueType instead, which the rules accept.
    "font.serif": ["Liberation Serif", "DejaVu Serif"],
    "mathtext.fontset": "stix",
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
    "font.size": 9,
    "axes.edgecolor": MUTE,
    "axes.labelcolor": INK,
    "text.color": INK,
    "xtick.color": MUTE,
    "ytick.color": MUTE,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "figure.dpi": 200,
})

try:  # the committed figures were drawn with Liberation Serif; say so if it is missing
    matplotlib.font_manager.findfont("Liberation Serif", fallback_to_default=False)
except ValueError:
    print("WARNING: Liberation Serif not found (install fonts-liberation); figures will "
          "fall back to DejaVu Serif and will not be byte-identical to the committed ones.",
          file=sys.stderr)


def load():
    if not ATTEMPTS.exists():
        sys.exit(f"missing {ATTEMPTS} -- run the campaign first")
    return [json.loads(l) for l in ATTEMPTS.open()]


# Regeneration must be byte-stable so that `git diff` after a rerun is empty.
# Matplotlib stamps every PDF with the current time (/CreationDate); setting it
# to None drops the field. /Creator and /Producer name the matplotlib version,
# which requirements.txt pins, so they are stable and kept as provenance. PNG
# output carries no timestamp and was already byte-stable.
SAVE_METADATA = {"pdf": {"CreationDate": None}, "png": None}


def save(fig, name):
    for ext in ("pdf", "png"):
        fig.savefig(HERE / f"{name}.{ext}", bbox_inches="tight",
                    metadata=SAVE_METADATA[ext])
    plt.close(fig)
    print(f"  wrote {name}.pdf / .png")


# ---------------------------------------------------------------- fig 2
def fig_uncertainty(rows):
    """Paired differences vs F3 with cluster-bootstrap CIs.

    REPLACES the earlier "noise floor" figure, whose shaded band asserted that
    the F4a-F3 gap established the experiment's resolution. It does not.
    Information-identical is not response-identical: adding a constant field
    changes the prompt text, and an LLM's output distribution can shift because
    text was added. F4a bounds the effect of adding an uninformative field, no
    more. And the 5.0-point figure itself has a CI that includes zero, so it was
    never a stable estimate of anything.

    What is plotted instead: paired differences with 95% percentile intervals
    from a bootstrap clustered on certificate, which is what the design needs,
    because the 20 counterexamples are shared across conditions and each cell is
    attempted three times.
    """
    # Intervals are READ from data/results/uncertainty.json (scripts/uncertainty.py,
    # 10,000 resamples, seed 0) rather than recomputed here. Until Oct 2026 this
    # function ran its own 4,000-resample bootstrap, which gave one endpoint
    # (F2 - F3, structural edit) of +13.3 where the text and JSON say +11.7.
    # One bootstrap, one set of numbers.
    unc = json.loads((REPO / "data" / "results" / "uncertainty.json").read_text())
    panels = [
        ("S: contracts satisfied\n(pre-specified)", "resolved"),
        ("S and entered\n(refusals excluded)", "resolved_ex_refusal"),
        ("structural edit", "skeleton_edit"),
    ]
    others = ["F1", "F2", "F4a", "F4b"]

    fig, axes = plt.subplots(1, 3, figsize=(6.4, 2.5), sharey=True)
    for ax, (title, key) in zip(axes, panels):
        dv = unc[key]["diff_vs_F3"]
        pts = [dv[c]["point"] for c in others]
        los = [dv[c]["ci"][0] for c in others]
        his = [dv[c]["ci"][1] for c in others]
        y = np.arange(len(others))
        for i, (pt, lo, hi) in enumerate(zip(pts, los, his)):
            excl = lo > 0 or hi < 0
            col = ACCENT if excl else INK
            ax.plot([lo, hi], [i, i], color=col, lw=2.0,
                    solid_capstyle="butt", alpha=0.85)
            ax.plot([lo, lo], [i - .13, i + .13], color=col, lw=1.6)
            ax.plot([hi, hi], [i - .13, i + .13], color=col, lw=1.6)
            ax.scatter([pt], [i], s=34, color=col, zorder=3)
        ax.axvline(0, color=MUTE, lw=1.2, ls="--")
        ax.set_yticks(y)
        ax.set_yticklabels(others, fontsize=8.5)
        ax.set_title(title, fontsize=8.5, pad=7)
        ax.tick_params(labelsize=8.5)
        ax.invert_yaxis()
    axes[0].set_ylabel("vs F3", fontsize=8.5)
    fig.supxlabel("difference from F3, percentage points (95% CI, bootstrap clustered on certificate)",
                  fontsize=8.5, y=-0.04)
    save(fig, "fig2_uncertainty")


# ---------------------------------------------------------------- fig 3
def fig_patch_type(rows):
    """Structural-edit rate by condition. The largest clean effect."""
    by = collections.defaultdict(list)
    for r in rows:
        by[r["condition"]].append(r)
    vals = [sum(1 for r in by[c] if r.get("patch_type") == "skeleton_edit")
            for c in CONDS]

    fig, ax = plt.subplots(figsize=(6.2, 2.7))
    colors = [NEG if v > 40 else (ACCENT if v > 20 else POS) for v in vals]
    bars = ax.barh([LABELS[c] for c in CONDS], vals, color=colors, alpha=0.75,
                   height=0.62)
    for b, v in zip(bars, vals):
        ax.annotate(f"{v}", (v, b.get_y() + b.get_height() / 2),
                    textcoords="offset points", xytext=(5, 0),
                    va="center", fontsize=8.5, weight="bold")
    ax.set_xlim(0, 66)
    ax.set_xlabel("structural (skeleton) edits, of 60 attempts")
    ax.invert_yaxis()
    ax.tick_params(labelsize=8)
    save(fig, "fig3_patch_type")


# ---------------------------------------------------------------- fig 4
def fig_funnel(rows):
    """300 attempts -> 18 apparent -> genuine -> completed."""
    n = len(rows)
    resolved = sum(1 for r in rows if r.get("resolved"))
    refusals = sum(1 for r in rows if r.get("resolved_by_refusal"))
    genuine = resolved - refusals
    completed = sum(1 for r in rows if r.get("resolved_and_completed"))
    # ...and also broke nothing. Asked for by review: of the three that
    # repaired and drove, how many left the regression suite intact?
    clean = sum(1 for r in rows if r.get("resolved_and_completed")
                and (r.get("regression_failures") or 0) == 0)

    stages = [("attempts", n, MUTE),
              ("satisfied the contracts", resolved, ACCENT),
              ("and entered the conflict zone", genuine, "#8A5A00"),
              ("and completed the turn", completed, POS),
              ("and regression suite intact", clean, POS)]

    # Printed at 0.64 linewidth (about 3.5 in). bbox_inches="tight" widens the
    # saved PDF to fit the y labels, so it is the TIGHT box, labels included,
    # that must come out near that width for 8.5 pt text to print near 8 pt.
    # The message that used to be the title is in the LaTeX caption.
    fig, ax = plt.subplots(figsize=(3.2, 1.4))
    for i, (lab, v, col) in enumerate(stages):
        ax.barh([i], [v], color=col, alpha=0.55, height=0.6)
        ax.annotate(f"{v}", (v, i), textcoords="offset points", xytext=(6, 0),
                    va="center", fontsize=9, weight="bold")
    ax.set_yticks(range(len(stages)))
    ax.set_yticklabels([s[0] for s in stages], fontsize=8.5)
    ax.set_xlim(0, n * 1.08)
    ax.set_xlabel("attempts")
    ax.invert_yaxis()
    save(fig, "fig4_funnel")


def main() -> int:
    rows = load()
    print(f"loaded {len(rows)} attempts")
    fig_uncertainty(rows)
    fig_patch_type(rows)
    fig_funnel(rows)
    print("done. Figure 1 (fig1_pipeline.png) is a static schematic and is "
          "not generated here.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
