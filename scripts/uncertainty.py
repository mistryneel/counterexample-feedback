#!/usr/bin/env python3
"""Cluster bootstrap over certificates, replacing the noise-floor argument.

WHY THIS EXISTS, AND WHAT WAS WRONG BEFORE.

The draft argued: F4a carries provably zero INFORMATION beyond F3, therefore
any measured F4a-F3 difference is noise, therefore 5.0 points is the
experiment's resolution and no other effect can be believed below it.

That argument does not hold, and the reviewer was right to reject it.
Information-identical is not response-identical. Adding a constant field
changes the prompt text by ~91 tokens, and an LLM's output distribution can
shift because text was added, regardless of whether that text carries
information in the Shannon sense. F4a is therefore not a noise replicate of F3.
It is a different prompt that happens to carry no extra information, and its
difference from F3 bounds the effect of adding an uninformative field. It does
not establish a general resolution for the experiment, and it certainly does
not prove other effects are absent.

What replaces it is an actual uncertainty analysis. The design has two features
that a plain binomial interval ignores:

  * the 20 counterexamples are SHARED across all five conditions, so condition
    estimates are correlated through the certificate;
  * each (condition, certificate) cell is attempted 3 times, so attempts are
    clustered within certificate.

A cluster bootstrap over certificates handles both. We resample the 20
certificates with replacement, carry ALL attempts belonging to a resampled
certificate (across every condition), recompute the rates, and take paired
differences within each resample so the pairing is preserved.

    scripts/uncertainty.py [--boot 10000] [--out PATH]
"""
from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys

import numpy as np

REPO = pathlib.Path(__file__).resolve().parent.parent
CONDS = ["F1", "F2", "F3", "F4a", "F4b"]


def load():
    p = REPO / "data/results/attempts.jsonl"
    rows = [json.loads(l) for l in p.open()]
    for r in rows:
        r["_cert"] = r["certificate_id"].split("_")[0]
    return rows


def rate(rows, cond, key, pred=None):
    v = [r for r in rows if r["condition"] == cond]
    if not v:
        return np.nan
    if pred is None:
        pred = lambda r: bool(r.get(key))
    return 100.0 * sum(1 for r in v if pred(r)) / len(v)


def cluster_bootstrap(rows, key, pred=None, n_boot=10000, seed=0):
    """Percentile CIs for per-condition rates and for differences vs F3."""
    rng = np.random.default_rng(seed)
    by_cert = collections.defaultdict(list)
    for r in rows:
        by_cert[r["_cert"]].append(r)
    certs = sorted(by_cert)
    k = len(certs)

    point = {c: rate(rows, c, key, pred) for c in CONDS}
    draws = {c: [] for c in CONDS}
    diffs = {c: [] for c in CONDS if c != "F3"}

    for _ in range(n_boot):
        pick = rng.integers(0, k, k)
        res = [r for i in pick for r in by_cert[certs[i]]]
        rr = {c: rate(res, c, key, pred) for c in CONDS}
        for c in CONDS:
            draws[c].append(rr[c])
        for c in diffs:
            diffs[c].append(rr[c] - rr["F3"])

    def ci(a):
        a = np.asarray([x for x in a if np.isfinite(x)])
        return (float(np.percentile(a, 2.5)), float(np.percentile(a, 97.5)))

    return point, {c: ci(v) for c, v in draws.items()}, {c: ci(v) for c, v in diffs.items()}


def paired_diff_draws(rows, pred, pairs, n_boot=10000, seed=0):
    """Bootstrap draws of rate(a) - rate(b) for each (a, b) in `pairs`.

    Uses the identical RNG call pattern as `cluster_bootstrap` (one
    default_rng(seed), one rng.integers(0, k, k) per resample), so every
    difference computed here is taken on exactly the same resampled
    certificates as the intervals in every other block of the output.
    """
    rng = np.random.default_rng(seed)
    by_cert = collections.defaultdict(list)
    for r in rows:
        by_cert[r["_cert"]].append(r)
    certs = sorted(by_cert)
    k = len(certs)
    draws = {p: [] for p in pairs}
    for _ in range(n_boot):
        pick = rng.integers(0, k, k)
        res = [r for i in pick for r in by_cert[certs[i]]]
        for a, b in pairs:
            draws[(a, b)].append(rate(res, a, None, pred) - rate(res, b, None, pred))
    return {p: np.asarray(v) for p, v in draws.items()}


def pct_ci(draws, alpha=0.05):
    return (float(np.percentile(draws, 100 * alpha / 2)),
            float(np.percentile(draws, 100 * (1 - alpha / 2))))


def report(title, rows, key, pred, n_boot, out_key, results):
    print(f"\n{'='*76}\n{title}\n{'='*76}")
    point, cis, dcis = cluster_bootstrap(rows, key, pred, n_boot)
    print(f"{'cond':<6} {'rate':>8}   {'95% CI (cluster bootstrap)':>28}")
    for c in CONDS:
        lo, hi = cis[c]
        print(f"{c:<6} {point[c]:7.1f}%   [{lo:6.1f}, {hi:6.1f}]")
    print(f"\npaired differences vs F3, same resampled certificates:")
    for c in CONDS:
        if c == "F3":
            continue
        lo, hi = dcis[c]
        crosses = lo <= 0 <= hi
        print(f"  {c:<4} - F3 = {point[c]-point['F3']:+6.1f}   "
              f"[{lo:+6.1f}, {hi:+6.1f}]   "
              f"{'CI includes 0' if crosses else 'CI EXCLUDES 0'}")
    results[out_key] = {
        "point": point,
        "ci": {c: list(v) for c, v in cis.items()},
        "diff_vs_F3": {c: {"point": point[c] - point["F3"], "ci": list(v)}
                       for c, v in dcis.items()},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--boot", type=int, default=10000)
    ap.add_argument("--out", default=str(REPO / "data/results/uncertainty.json"),
                    help="where to write the JSON (default: the committed file)")
    a = ap.parse_args()
    rows = load()
    print(f"{len(rows)} attempts, {len({r['_cert'] for r in rows})} certificates, "
          f"{a.boot} bootstrap resamples clustered on certificate")

    results: dict = {"n_attempts": len(rows), "n_certificates":
                     len({r["_cert"] for r in rows}), "n_boot": a.boot}

    report("REPAIR SUCCESS (pre-specified `resolved`)", rows,
           "resolved", None, a.boot, "resolved", results)

    report("REPAIR SUCCESS, refusals excluded", rows, None,
           lambda r: bool(r.get("resolved")) and not r.get("resolved_by_refusal"),
           a.boot, "resolved_ex_refusal", results)

    report("STRUCTURAL (SKELETON) EDIT RATE", rows, None,
           lambda r: r.get("patch_type") == "skeleton_edit",
           a.boot, "skeleton_edit", results)

    report("CAUSED >= 1 REGRESSION FAILURE", rows, None,
           lambda r: (r.get("regression_failures") or 0) >= 1,
           a.boot, "regression", results)

    # The headline contrast in the paper is F1 - F2 on structural edits. It is
    # computed on the same resamples as everything above. Added for the
    # camera-ready (Oct 2026): before this, that interval was reproducible but
    # not written by any committed script.
    skel = lambda r: r.get("patch_type") == "skeleton_edit"
    d = paired_diff_draws(rows, skel, [("F1", "F2")], a.boot)[("F1", "F2")]
    pt = rate(rows, "F1", None, skel) - rate(rows, "F2", None, skel)
    results["skeleton_edit_F1_minus_F2"] = {"point": pt, "ci": list(pct_ci(d))}
    print(f"\nstructural edit, F1 - F2 = {pt:+6.1f}   [{pct_ci(d)[0]:+6.1f}, {pct_ci(d)[1]:+6.1f}]")

    # All ten pairwise structural-edit contrasts, same resamples. Added after
    # camera-ready review: the paper says F1 differs from EVERY processed
    # condition, so F1 - F4a and F1 - F4b must be reported too, and F1 - F2
    # (the abstract's contrast) must be shown to be the largest of the ten,
    # i.e. chosen after seeing the data. F1-F4a and F1-F4b are reported in
    # addition to the 17 below; with them the paper reports 19 contrasts.
    pairs = [(x, y) for i, x in enumerate(CONDS) for y in CONDS[i + 1:]]
    dd = paired_diff_draws(rows, skel, pairs, a.boot)
    pw = {}
    for x, y in pairs:
        pt_xy = rate(rows, x, None, skel) - rate(rows, y, None, skel)
        pw[f"{x}-{y}"] = {"point": pt_xy, "ci": list(pct_ci(dd[(x, y)])),
                          "ci_bonferroni_19": list(pct_ci(dd[(x, y)], 0.05 / 19))}
    results["skeleton_edit_pairwise"] = pw
    print("\nstructural edit, all pairs (|point| descending):")
    for k, v in sorted(pw.items(), key=lambda kv: -abs(kv[1]["point"])):
        print(f"  {k:<8} {v['point']:+6.1f}  [{v['ci'][0]:+6.1f}, {v['ci'][1]:+6.1f}]"
              f"  bonf/19 [{v['ci_bonferroni_19'][0]:+6.1f}, {v['ci_bonferroni_19'][1]:+6.1f}]")

    # Multiplicity. The paper's intervals are UNADJUSTED. This block records how
    # many paired differences were computed in total and what a Bonferroni
    # adjustment over all of them gives, as a sensitivity check only.
    blocks = [
        ("resolved", lambda r: bool(r.get("resolved"))),
        ("resolved_ex_refusal",
         lambda r: bool(r.get("resolved")) and not r.get("resolved_by_refusal")),
        ("skeleton_edit", skel),
        ("regression", lambda r: (r.get("regression_failures") or 0) >= 1),
    ]
    contrasts = [(blk, pred, (c, "F3")) for blk, pred in blocks for c in CONDS if c != "F3"]
    contrasts.append(("skeleton_edit", skel, ("F1", "F2")))
    m = len(contrasts)
    bonf = {}
    for blk, pred, pair in contrasts:
        dd = paired_diff_draws(rows, pred, [pair], a.boot)[pair]
        bonf.setdefault(blk, {})[f"{pair[0]}-{pair[1]}"] = {
            "ci_95": list(pct_ci(dd)), "ci_bonferroni": list(pct_ci(dd, 0.05 / m))}
    # Every DISTINCT difference computed anywhere in this script: the 17 above
    # plus the five structural-edit pairs that involve neither F3 nor F1-F2.
    done = {frozenset(k.split("-")) for k in bonf["skeleton_edit"]}
    extra = [(x, y) for (x, y) in pairs if frozenset((x, y)) not in done]
    all_c = [(blk, pred, pair) for blk, pred, pair in contrasts] + \
            [("skeleton_edit", skel, pr) for pr in extra]
    m_all = len(all_c)
    surv = []
    for blk, pred, pair in all_c:
        dd = paired_diff_draws(rows, pred, [pair], a.boot)[pair]
        lo, hi = pct_ci(dd, 0.05 / m_all)
        if lo > 0 or hi < 0:
            surv.append(f"{blk}:{pair[0]}-{pair[1]}")
    results["multiplicity_all_computed"] = {
        "n_distinct_differences": m_all,
        "bonferroni_alpha": 0.05 / m_all,
        "exclude_zero_after_bonferroni": surv,
    }
    print(f"\n{m_all} distinct differences computed in total; excluding zero at 0.05/{m_all}: {surv}")

    results["multiplicity"] = {
        "n_contrasts_computed": m,
        "adjustment_in_paper": "none (intervals in the paper are unadjusted)",
        "bonferroni_alpha": 0.05 / m,
        "contrasts": bonf,
    }
    print(f"\n{m} paired differences computed; Bonferroni alpha = 0.05/{m}")
    for blk, cs in bonf.items():
        for name, v in cs.items():
            lo, hi = v["ci_bonferroni"]
            print(f"  {blk:<20} {name:<7} bonferroni [{lo:+6.1f}, {hi:+6.1f}]"
                  f"  {'EXCLUDES 0' if lo > 0 or hi < 0 else ''}")

    out = pathlib.Path(a.out)
    out.write_text(json.dumps(results, indent=2))
    print(f"\nwritten: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
