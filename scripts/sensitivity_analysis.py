#!/usr/bin/env python3
"""Parameter sensitivity of rho over a banked campaign.

Answers: does each falsifier parameter actually move rho? A parameter that
does not is not a search dimension, it is wasted sampling -- and a space in
which only one parameter carries signal makes boundary search degenerate,
because every counterexample boundary collapses onto one axis.

Reports Pearson (linear) AND Spearman (monotone) correlation. Pearson alone is
misleading here: `headway` is expected to be monotone-but-not-linear in rho,
and a low Pearson with a high Spearman means "matters, non-linearly", which is
a completely different conclusion from "does not matter".
"""
from __future__ import annotations

import argparse
import glob
import json
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
import stl  # noqa: E402
from config import load_config  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/traces")
    ap.add_argument("--pattern", default="g1_*.parquet")
    ap.add_argument("--contracts", default="C1,C2",
                    help="contracts to include in the combined rho for this analysis")
    ap.add_argument("--out", default="data/results/sensitivity.json")
    a = ap.parse_args()

    from scipy import stats

    contracts = load_config("contracts")
    want = [c.strip() for c in a.contracts.split(",")]
    contracts["combined"]["active"] = want
    contracts["combined"]["report_only"] = []
    for key, name in (("C1_collision", "C1"), ("C2_yield", "C2"),
                      ("C5_comfort", "C5")):
        contracts[key]["enabled"] = name in want
    junction = stl.load_junction()

    paths = sorted(glob.glob(str(pathlib.Path(a.dir) / a.pattern)))
    print(f"scoring {len(paths)} traces with contracts {want} ...")
    rows = []
    for p in paths:
        df, meta = stl.load_trace(p)
        r = stl.compute_rho(df, contracts, junction)
        params = json.loads(meta["scenario_params"])
        rec = {**params, "rho": r.rho, "contract": r.contract}
        for k, v in r.per_contract.items():
            rec[f"rho_{k}"] = v.rho
        gap = meta.get("achieved_gap_s")
        rec["achieved_gap_s"] = (float(gap) if gap not in (None, "", "None") else np.nan)
        rec["n_ticks"] = len(df)
        rows.append(rec)

    keys = [k for k in rows[0] if k not in
            ("rho", "contract", "n_ticks") and not k.startswith("rho_")]
    rho = np.array([r["rho"] for r in rows], float)

    print(f"\nrho over {len(rows)} traces: min={rho.min():+.3f} "
          f"median={np.median(rho):+.3f} max={rho.max():+.3f}")
    print(f"violation rate (rho < 0): {100 * (rho < 0).mean():.1f}%")
    import collections
    print(f"argmin contract: {dict(collections.Counter(r['contract'] for r in rows))}")

    print(f"\n{'parameter':<20} {'Pearson':>9} {'Spearman':>9} {'p(Spear)':>10}  verdict")
    print("-" * 68)
    out = {}
    for k in keys:
        x = np.array([r[k] for r in rows], float)
        m = ~np.isnan(x)
        if m.sum() < 10 or np.nanstd(x) == 0:
            print(f"{k:<20} {'n/a':>9} {'n/a':>9} {'n/a':>10}  constant or too few samples")
            continue
        pr = float(np.corrcoef(x[m], rho[m])[0, 1])
        sr, pv = stats.spearmanr(x[m], rho[m])
        strength = ("STRONG" if abs(sr) >= 0.5 else
                    "moderate" if abs(sr) >= 0.25 else
                    "weak" if abs(sr) >= 0.1 else "NONE")
        note = ""
        if abs(sr) - abs(pr) > 0.15:
            note = "  <- monotone but NON-LINEAR"
        print(f"{k:<20} {pr:>+9.3f} {sr:>+9.3f} {pv:>10.2e}  {strength}{note}")
        out[k] = {"pearson": pr, "spearman": float(sr), "p_value": float(pv),
                  "strength": strength}

    # per-contract, so a parameter that drives one contract but not another is
    # visible rather than averaged away
    print(f"\nper-contract Spearman:")
    hdr = f"{'parameter':<20}" + "".join(f"{c:>10}" for c in want)
    print(hdr); print("-" * len(hdr))
    for k in keys:
        x = np.array([r[k] for r in rows], float)
        m = ~np.isnan(x)
        if m.sum() < 10 or np.nanstd(x) == 0:
            continue
        line = f"{k:<20}"
        for c in want:
            y = np.array([r.get(f"rho_{c}", np.nan) for r in rows], float)
            mm = m & ~np.isnan(y)
            if mm.sum() < 10 or np.nanstd(y[mm]) == 0:
                line += f"{'n/a':>10}"
            else:
                sr, _ = stats.spearmanr(x[mm], y[mm])
                line += f"{sr:>+10.3f}"
        print(line)

    pathlib.Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(a.out).write_text(json.dumps(
        {"n_traces": len(rows), "contracts": want,
         "violation_rate": float((rho < 0).mean()), "correlations": out},
        indent=2))
    print(f"\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
