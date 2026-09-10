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

    scripts/uncertainty.py [--boot 10000]
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
    a = ap.parse_args()
    rows = load()
    print(f"{len(rows)} attempts, {len({r['_cert'] for r in rows})} certificates, "
          f"{a.boot} bootstrap resamples clustered on certificate")

    results: dict = {"n_attempts": len(rows), "n_certificates":
                     len({r["_cert"] for r in rows}), "n_boot": a.boot}

    report("REPAIR SUCCESS (pre-registered `resolved`)", rows,
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

    out = REPO / "data/results/uncertainty.json"
    out.write_text(json.dumps(results, indent=2))
    print(f"\nwritten: {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
