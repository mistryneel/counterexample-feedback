#!/usr/bin/env python3
"""Analyse the E1 campaign. Reads attempts.jsonl, emits the tables and the grid.

READ THE NEGATIVE CONTROL FIRST. F4a's extra field, `active_node`, is provably
constant on this baseline -- the root Selector's first child is
Sequence(InConflictZone, CommitTurn), a Selector stops at its first succeeding
child, and C1/C2/C3 all take their argmin inside the conflict zone, so exactly
one leaf can ever tick there. H(active_node | contract) = 0.000 bits over all
20 certificates. F4a therefore carries ZERO information beyond F3, and

    |F4a - F3| IS THIS EXPERIMENT'S NOISE FLOOR.

Every other difference in this output must be compared against it before it is
called a difference at all. A condition that beats F3 by less than the F4a-F3
gap has not been shown to beat F3.

Reported deliberately and separately, never pooled:
  * malformed vs truncated vs api_error -- three different failures with three
    different causes (project rule 3, applied one step earlier).
  * fix rate per 1k TOTAL tokens and per 1k FEEDBACK tokens. The shared
    scaffolding is 4513 tokens, 92-98% of every non-F1 prompt, paid identically
    by every condition, so the total-token figure is very nearly fix_rate/4.6
    and ranks F1 last almost regardless of what F1 does.
  * searched SCVR against an unfiltered held-out SCVR, with the UNPATCHED
    BASELINE as the reference row, because the regression suite is filtered to
    baseline-passing and the held-out suite is not.

    .venv/bin/python scripts/analyze_e1.py
"""
from __future__ import annotations

import argparse
import collections
import json
import pathlib
import statistics
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from certificate import CONDITIONS, Certificate  # noqa: E402

ATTEMPTS = REPO / "data" / "results" / "attempts.jsonl"
BUDGET = REPO / "data" / "results" / "prompt_budget.json"
BASELINE_EVAL = REPO / "data" / "results" / "baseline_eval.json"
OUT = REPO / "data" / "results" / "e1_analysis.json"


def read_jsonl(p):
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def mean(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.mean(xs), 4) if xs else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--attempts", default=str(ATTEMPTS))
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()

    rows = read_jsonl(pathlib.Path(a.attempts))
    if not rows:
        print("no attempts on disk")
        return 1
    certs = {c.certificate_id: c for c in Certificate.load_all()}
    budget = json.loads(BUDGET.read_text())
    scaffold = budget["scaffolding_tokens"]
    per_cert_tokens = budget["per_certificate"]

    conds = [c for c in CONDITIONS if any(r["condition"] == c for r in rows)]
    by_cond = {c: [r for r in rows if r["condition"] == c] for c in conds}
    n_certs = len({r["certificate_id"] for r in rows})
    n_seeds = len({r["seed"] for r in rows})

    print(f"attempts: {len(rows)}   conditions: {len(conds)}   "
          f"certificates: {n_certs}   replicates: {n_seeds}")
    print("\nK = 20 with 3 replicates does not support a significance claim. "
          "Everything below is a trend.\n")

    # ------------------------------------------------------------------
    summary = {}
    for c in conds:
        rs = by_cond[c]
        n = len(rs)
        outcomes = collections.Counter(r["outcome"] for r in rs)
        ok = [r for r in rs if r["outcome"] == "ok"]
        ev = [r for r in ok if r.get("evaluated")]
        resolved = [r for r in ev if r.get("resolved")]
        refusals = [r for r in resolved if r.get("resolved_by_refusal")]
        genuine = [r for r in resolved if not r.get("resolved_by_refusal")]

        # Token spend actually billed, from the API's own usage numbers.
        tok_prompt_billed = sum((r.get("tokens_prompt") or 0)
                                + (r.get("cache_read") or 0)
                                + (r.get("cache_write") or 0) for r in rs)
        tok_completion = sum(r.get("tokens_completion") or 0 for r in rs)
        # Feedback-block tokens: the full prompt minus the fixed scaffolding.
        # Exact, from the pre-campaign count_tokens measurement.
        fb = sum(per_cert_tokens[r["certificate_id"]][r["condition"]] - scaffold
                 for r in rs if r["certificate_id"] in per_cert_tokens)

        fix = len(resolved) / n if n else None
        summary[c] = {
            "n_attempts": n,
            "outcomes": dict(outcomes),
            "malformed_rate": round(outcomes["malformed"] / n, 4),
            "truncated_rate": round(outcomes["truncated"] / n, 4),
            "api_error_rate": round(outcomes["api_error"] / n, 4),
            "n_evaluated": len(ev),
            "n_resolved": len(resolved),
            "fix_rate": round(fix, 4) if fix is not None else None,
            "fix_rate_of_evaluated": (round(len(resolved) / len(ev), 4)
                                      if ev else None),
            # See the analysis header. `fix_rate` is the pre-registered metric
            # and is reported unchanged; these say what is inside it.
            "n_resolved_by_refusal": len(refusals),
            "n_resolved_genuine": len(genuine),
            "fix_rate_excluding_refusals": round(len(genuine) / n, 4) if n else None,
            "n_resolved_and_completed": sum(
                1 for r in resolved if r.get("resolved_and_completed")),
            "ce_completion_rate": (round(sum(1 for r in ev if r.get("ce_completed"))
                                         / len(ev), 4) if ev else None),
            "tokens_prompt_total": tok_prompt_billed,
            "tokens_completion_total": tok_completion,
            "tokens_feedback_total": fb,
            "fix_per_1k_total": (round(len(resolved) /
                                       ((tok_prompt_billed + tok_completion) / 1000), 4)
                                 if tok_prompt_billed + tok_completion else None),
            "fix_per_1k_feedback": (round(len(resolved) / (fb / 1000), 4)
                                    if fb else None),
            "mean_regression_failures": mean([r.get("regression_failures") for r in ev]),
            "mean_ted": mean([r.get("ted_from_original") for r in ok]),
            "patch_types": dict(collections.Counter(
                r.get("patch_type") for r in ok)),
            "mean_rho_after": mean([r.get("rho_after") for r in ev]),
            "mean_icr": mean([r.get("icr") for r in ev]),
            "mean_pcr": mean([r.get("pcr") for r in ev]),
            "searched_scvr": mean([r.get("searched_scvr") for r in ev]),
            "held_out_scvr": mean([r.get("held_out_scvr") for r in ev]),
            "generalization_gap": mean([r.get("generalization_gap") for r in ev]),
            "c4_binding_after": sum(1 for r in ev if r.get("c4_binding_after")),
        }
        for k in ("C1", "C2", "C5"):
            summary[c][f"mean_rho{k[1]}_after"] = mean(
                [r.get(f"rho{k[1]}_after") for r in ev])

    # ------------------------------------------------------------------
    print("== HEADLINE ==")
    hdr = (f"{'cond':<5} {'fix':>7} {'ex-refus':>9} {'fix/1k tot':>11} "
           f"{'fix/1k fb':>10} {'malf':>6} {'trunc':>6} {'apierr':>7} "
           f"{'regfail':>8} {'TED':>6} {'ICR':>6}")
    print(hdr)
    print("-" * len(hdr))
    for c in conds:
        s = summary[c]
        print(f"{c:<5} {_p(s['fix_rate']):>7} "
              f"{_p(s['fix_rate_excluding_refusals']):>9} "
              f"{_f(s['fix_per_1k_total']):>11} "
              f"{_f(s['fix_per_1k_feedback']):>10} {_p(s['malformed_rate']):>6} "
              f"{_p(s['truncated_rate']):>6} {_p(s['api_error_rate']):>7} "
              f"{_f(s['mean_regression_failures']):>8} {_f(s['mean_ted']):>6} "
              f"{_p(s['mean_icr']):>6}")

    # ------------------------------------------------------------------
    print("\n== RESOLUTION BY REFUSAL ==")
    print("  `resolved` is pre-registered as rho >= 0 on the counterexample "
          "scenario. A program that never enters the junction satisfies that "
          "trivially: C2 and C3 go vacuous and rho falls through to C5.")
    tot_res = sum(summary[c]["n_resolved"] for c in conds)
    tot_ref = sum(summary[c]["n_resolved_by_refusal"] for c in conds)
    print(f"  {tot_ref} of {tot_res} resolutions across all conditions are "
          f"refusals" + (f" ({tot_ref/tot_res*100:.0f}%)" if tot_res else ""))
    print(f"  {'cond':<5} {'resolved':>9} {'refusal':>9} {'genuine':>9} "
          f"{'fix ex-ref':>11} {'CE completed':>13}")
    for c in conds:
        s = summary[c]
        print(f"  {c:<5} {s['n_resolved']:>9} {s['n_resolved_by_refusal']:>9} "
              f"{s['n_resolved_genuine']:>9} "
              f"{_p(s['fix_rate_excluding_refusals']):>11} "
              f"{_p(s['ce_completion_rate']):>13}")
    if tot_res and tot_ref / tot_res > 0.5:
        print("  ** More than half of all resolutions are refusals. The headline "
              "fix rate is then largely an artefact of the metric, not a "
              "measurement of repair. Report both numbers, lead with neither "
              "alone. **")

    print("\n== NEGATIVE CONTROL: F4a vs F3 ==")
    noise = None
    if "F3" in summary and "F4a" in summary:
        noise = abs(summary["F4a"]["fix_rate"] - summary["F3"]["fix_rate"])
        print(f"  F3  fix rate {_p(summary['F3']['fix_rate'])}   "
              f"F4a fix rate {_p(summary['F4a']['fix_rate'])}")
        print(f"  |F4a - F3| = {noise:.4f} ({noise*100:.1f} points)")
        print("  F4a adds `active_node`, which is CONSTANT over this corpus "
              "(H = 0.000 bits).")
        print("  This gap is therefore pure noise, and NOTHING SMALLER THAN IT "
              "IS A DIFFERENCE.")
        if noise > 0.20:
            print("  ** WARNING: a >20-point gap on a zero-information field "
                  "means something is wrong with the setup. Investigate before "
                  "reporting any other comparison. **")
        for c in conds:
            if c in ("F3", "F4a"):
                continue
            d = summary[c]["fix_rate"] - summary["F3"]["fix_rate"]
            verdict = "ABOVE the noise floor" if abs(d) > noise else "within noise"
            print(f"  {c} - F3 = {d:+.4f}   {verdict}")

    # ------------------------------------------------------------------
    print("\n== OUTCOME GRID (fraction of replicates resolved) ==")
    cert_ids = sorted({r["certificate_id"] for r in rows})
    grid = {}
    print(f"{'certificate':<34} {'con':<4} " +
          " ".join(f"{c:>5}" for c in conds))
    for cid in cert_ids:
        cells = []
        for c in conds:
            rs = [r for r in by_cond[c] if r["certificate_id"] == cid]
            ev = [r for r in rs if r.get("evaluated")]
            cells.append(sum(1 for r in ev if r.get("resolved")) / len(rs)
                         if rs else None)
        grid[cid] = dict(zip(conds, cells))
        deg = "*" if certs[cid].degraded_no_boundary else " "
        print(f"{cid:<34}{deg}{certs[cid].contract:<4} " +
              " ".join(f"{_f(x):>5}" for x in cells))
    print("  * = degraded (renders no boundary)")

    # F3 vs F4b set relationship -- superset or different set?
    setrel = {}
    for other in ("F4a", "F4b"):
        if other not in by_cond or "F3" not in by_cond:
            continue
        f3 = {cid for cid in cert_ids if (grid[cid].get("F3") or 0) > 0}
        fx = {cid for cid in cert_ids if (grid[cid].get(other) or 0) > 0}
        setrel[other] = {
            "F3_only": sorted(f3 - fx), "both": sorted(f3 & fx),
            "other_only": sorted(fx - f3),
            "is_superset": bool(fx >= f3), "is_equal": bool(fx == f3),
        }
        rel = ("a SUPERSET of F3" if fx > f3 else
               "IDENTICAL to F3" if fx == f3 else
               "a SUBSET of F3" if fx < f3 else "a DIFFERENT SET from F3")
        print(f"\n  {other} resolves {rel}: "
              f"{len(f3 & fx)} shared, {len(f3 - fx)} F3-only, "
              f"{len(fx - f3)} {other}-only")

    # ------------------------------------------------------------------
    print("\n== GENERALIZATION ==")
    base = None
    if BASELINE_EVAL.exists():
        b = json.loads(BASELINE_EVAL.read_text())
        base = {
            "searched_scvr": mean([v["searched_scvr"] for v in b.values()]),
            "held_out_scvr": mean([v["held_out_scvr"] for v in b.values()]),
            "icr": mean([v["icr"] for v in b.values()]),
        }
        base["generalization_gap"] = round(
            base["searched_scvr"] - base["held_out_scvr"], 4)
        print(f"  {'BASELINE (unpatched)':<22} searched {_p(base['searched_scvr'])}"
              f"  held-out {_p(base['held_out_scvr'])}"
              f"  gap {base['generalization_gap']:+.3f}   <- reference row")
    for c in conds:
        s = summary[c]
        extra = ""
        if base is not None and s["generalization_gap"] is not None:
            extra = f"   change vs baseline {s['generalization_gap'] - base['generalization_gap']:+.3f}"
        print(f"  {c:<22} searched {_p(s['searched_scvr'])}"
              f"  held-out {_p(s['held_out_scvr'])}"
              f"  gap {_f(s['generalization_gap'])}{extra}")
    print("  The two suites are not symmetric: the regression suite is filtered to "
          "baseline-passing and the held-out suite is not. Read the gap as a "
          "CHANGE from the baseline row, not as an absolute.")

    # ------------------------------------------------------------------
    print("\n== CROSS-TABS ==")
    ok_all = [r for r in rows if r["outcome"] == "ok" and r.get("evaluated")]
    xt = collections.defaultdict(lambda: {"n": 0, "regfail": [], "resolved": 0})
    for r in ok_all:
        k = r.get("patch_type") or "unknown"
        xt[k]["n"] += 1
        xt[k]["regfail"].append(r.get("regression_failures"))
        xt[k]["resolved"] += bool(r.get("resolved"))
    print("  patch_type x regression failures (hypothesis: skeleton edits are riskier)")
    for k, v in sorted(xt.items()):
        print(f"    {k:<15} n={v['n']:<4} mean regression failures "
              f"{_f(mean(v['regfail'])):>6}   resolved {v['resolved']}/{v['n']}")
    patch_x = {k: {"n": v["n"], "mean_regression_failures": mean(v["regfail"]),
                   "resolved": v["resolved"]} for k, v in xt.items()}

    deg = {True: [], False: []}
    for r in ok_all:
        deg[bool(certs[r["certificate_id"]].degraded_no_boundary)].append(
            bool(r.get("resolved")))
    print("\n  degraded (no boundary rendered) x resolution")
    for k, v in deg.items():
        if v:
            print(f"    degraded={str(k):<5} n={len(v):<4} "
                  f"fix rate {sum(v)/len(v):.3f}")
    degraded_x = {str(k): {"n": len(v),
                           "fix_rate": round(sum(v)/len(v), 4) if v else None}
                  for k, v in deg.items()}

    # replicate agreement -- how much independent information 3 replicates carry
    agree = collections.defaultdict(set)
    for r in rows:
        if r.get("program_version_after"):
            agree[(r["condition"], r["certificate_id"])].add(
                r["program_version_after"])
    if agree:
        distinct = [len(v) for v in agree.values()]
        print(f"\n  replicate agreement: mean {statistics.mean(distinct):.2f} "
              f"DISTINCT programs per (condition, certificate) out of {n_seeds}")
        print("    `seed` is a replicate index, not a sampling seed: the API has "
              "no seed knob and no temperature on Opus 5.")

    out = {
        "n_attempts": len(rows), "n_certificates": n_certs, "n_seeds": n_seeds,
        "conditions": conds, "summary": summary,
        "noise_floor_f4a_minus_f3": noise,
        "outcome_grid": grid, "set_relationships": setrel,
        "baseline_reference": base,
        "patch_type_crosstab": patch_x,
        "degraded_crosstab": degraded_x,
        "distinct_programs_per_cell": (statistics.mean(distinct) if agree else None),
    }
    pathlib.Path(a.out).write_text(json.dumps(out, indent=2, default=str))
    print(f"\nwrote {a.out}")
    return 0


def _p(x):
    return "  n/a" if x is None else f"{x*100:.1f}%"


def _f(x):
    return "n/a" if x is None else f"{x:.3f}"


if __name__ == "__main__":
    raise SystemExit(main())
