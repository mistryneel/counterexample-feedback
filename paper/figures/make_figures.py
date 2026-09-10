#!/usr/bin/env python3
"""Generate the paper's DATA figures from data/results/attempts.jsonl.

WHY THIS IS A SCRIPT AND NOT AN IMAGE-GENERATION PROMPT.

Figures 2, 3 and 4 encode measured results. An image model asked to "draw a
bar chart showing 59 out of 60" produces a picture that *resembles* that
chart; it does not plot the data. In a paper reporting a null result whose
entire credibility rests on a 5.0-point noise floor, a figure whose bar
heights were invented is a fabrication, however innocent the intent.

So these three read the campaign log and plot what is actually in it. The two
CONCEPTUAL figures (the pipeline and the junction) carry no data and are the
ones for which generated art or TikZ is appropriate -- see FIGURES.md.

    python paper/figures/make_figures.py

Outputs PDF (vector, for LaTeX) and PNG (for slides) into this directory.
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
          "F4a": "F4a\n+node (control)", "F4b": "F4b\n+decision"}

INK = "#151A16"
MUTE = "#5A625B"
ACCENT = "#26418F"
NEG = "#9E1B32"
POS = "#0E6F5C"

plt.rcParams.update({
    "font.family": "serif",
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


def load():
    if not ATTEMPTS.exists():
        sys.exit(f"missing {ATTEMPTS} -- run the campaign first")
    return [json.loads(l) for l in ATTEMPTS.open()]


def save(fig, name):
    for ext in ("pdf", "png"):
        fig.savefig(HERE / f"{name}.{ext}", bbox_inches="tight")
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
    by_cert = collections.defaultdict(list)
    for r in rows:
        by_cert[r["certificate_id"].split("_")[0]].append(r)
    certs = sorted(by_cert)
    k = len(certs)
    rng = np.random.default_rng(0)

    def rate(rs, c, pred):
        v = [r for r in rs if r["condition"] == c]
        return 100.0 * sum(1 for r in v if pred(r)) / len(v) if v else float("nan")

    panels = [
        ("repair success\n(pre-registered)", lambda r: bool(r.get("resolved"))),
        ("repair success\n(refusals excluded)",
         lambda r: bool(r.get("resolved")) and not r.get("resolved_by_refusal")),
        ("structural edit", lambda r: r.get("patch_type") == "skeleton_edit"),
    ]
    others = ["F1", "F2", "F4a", "F4b"]

    fig, axes = plt.subplots(1, 3, figsize=(7.4, 2.9), sharey=True)
    for ax, (title, pred) in zip(axes, panels):
        pts, los, his = [], [], []
        for c in others:
            d = []
            for _ in range(4000):
                s = [r for i in rng.integers(0, k, k) for r in by_cert[certs[i]]]
                d.append(rate(s, c, pred) - rate(s, "F3", pred))
            pts.append(rate(rows, c, pred) - rate(rows, "F3", pred))
            los.append(np.percentile(d, 2.5))
            his.append(np.percentile(d, 97.5))
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
        ax.tick_params(labelsize=7.5)
        ax.invert_yaxis()
    axes[0].set_ylabel("vs F3", fontsize=8.5)
    fig.supxlabel("difference from F3, percentage points (95% CI, bootstrap clustered on certificate)",
                  fontsize=8, y=-0.04)
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
              ("satisfied the contract", resolved, ACCENT),
              ("not by refusing to drive", genuine, "#8A5A00"),
              ("and completed the turn", completed, POS),
              ("and broke nothing", clean, POS)]

    fig, ax = plt.subplots(figsize=(6.2, 2.5))
    for i, (lab, v, col) in enumerate(stages):
        ax.barh([i], [v], color=col, alpha=0.55, height=0.6)
        ax.annotate(f"{v}", (v, i), textcoords="offset points", xytext=(6, 0),
                    va="center", fontsize=9, weight="bold")
    ax.set_yticks(range(len(stages)))
    ax.set_yticklabels([s[0] for s in stages], fontsize=8.5)
    ax.set_xlim(0, n * 1.08)
    ax.set_xlabel("attempts")
    ax.invert_yaxis()
    ax.set_title(f"{refusals} of {resolved} apparent repairs "
                 f"({100*refusals/max(1,resolved):.0f}%) were refusals to drive",
                 fontsize=9, color=NEG, pad=10)
    save(fig, "fig4_funnel")


def main() -> int:
    rows = load()
    print(f"loaded {len(rows)} attempts")
    fig_uncertainty(rows)
    fig_patch_type(rows)
    fig_funnel(rows)
    print("done. Figures 1 and 5 are conceptual -- see FIGURES.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
