#!/usr/bin/env python3
"""Measure the ego-speed threshold for C5, rather than guessing it.

CARLA 0.9.16 decelerates a braking vehicle at ~-27 m/s^2 below roughly 5 m/s,
regardless of brake command (docs/determinism_report.md). C5 bounds
|a_long| <= a_comfort and |jerk_long| <= j_comfort, so without a speed
restriction every yielding episode violates C5 on the simulator's brake model
rather than on the program's comfort decisions.

THE DERIVATIVE WINDOW MUST LIE ENTIRELY ABOVE THE THRESHOLD.

This is the subtlety that makes a naive filter fail. It is not enough for the
EVALUATION POINT to be above the threshold: the samples the derivative is
computed FROM must be too. Otherwise a sample at 5.1 m/s inherits an
artifact-contaminated acceleration from its neighbour at 4.6 m/s, and the
artifact leaks straight through the filter. A 5-tick moving average over
(-3.7, -17.3, -27.0, -26.8, -26.2) still averages about -20 m/s^2 for exactly
this reason.

Window widths, in samples:
    a_long   is a first difference of velocity     -> {i-1, i}
    jerk     is a first difference of a_long       -> {i-2, i-1, i}

A sample is ELIGIBLE only if ego_speed_mps >= threshold at EVERY index in its
window.
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

W_ACCEL = 1   # extra samples back, beyond i
W_JERK = 2


def eligible_mask(speed: np.ndarray, thr: float, window_back: int) -> np.ndarray:
    """True where speed >= thr across the whole derivative window ending at i."""
    ok = speed >= thr
    m = ok.copy()
    for k in range(1, window_back + 1):
        shifted = np.empty_like(ok)
        shifted[:k] = False          # no history -> not eligible
        shifted[k:] = ok[:-k]
        m &= shifted
    return m


def c5_for_trace(df, thr: float, a_comfort: float, j_comfort: float) -> dict:
    speed = df["ego_speed_mps"].to_numpy(float)
    a = df["ego_accel_long_mps2"].to_numpy(float)
    j = df["ego_jerk_long_mps3"].to_numpy(float)

    m_a = eligible_mask(speed, thr, W_ACCEL)
    m_j = eligible_mask(speed, thr, W_JERK) & ~np.isnan(j)

    rho_parts = []
    if m_a.any():
        rho_parts.append(float((a_comfort - np.abs(a[m_a])).min()))
    if m_j.any():
        rho_parts.append(float((j_comfort - np.abs(j[m_j])).min()))

    return {
        "rho5": min(rho_parts) if rho_parts else None,
        "n_elig_a": int(m_a.sum()),
        "n_elig_j": int(m_j.sum()),
        "n_ticks": int(len(df)),
        "max_abs_a": float(np.abs(a[m_a]).max()) if m_a.any() else None,
        "max_abs_j": float(np.abs(j[m_j]).max()) if m_j.any() else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/traces")
    ap.add_argument("--pattern", default="bank_*.parquet")
    ap.add_argument("--lo", type=float, default=2.0)
    ap.add_argument("--hi", type=float, default=8.0)
    ap.add_argument("--step", type=float, default=0.25)
    ap.add_argument("--out", default="data/results/c5_threshold_sweep.json")
    a = ap.parse_args()

    contracts = load_config("contracts")
    a_comfort = float(contracts["C5_comfort"]["a_comfort_mps2"])
    j_comfort = float(contracts["C5_comfort"]["j_comfort_mps3"])

    paths = sorted(glob.glob(str(pathlib.Path(a.dir) / a.pattern)))
    if not paths:
        # The input trajectories (data/traces/) are not part of the public
        # release. Fail loudly instead of writing an empty result over the
        # committed output.
        print(f"no trajectories match {pathlib.Path(a.dir) / a.pattern}; this script needs "
              "the unreleased data/traces/ files and cannot be re-run from the public "
              "release (see data/results/NOTES.md)", file=sys.stderr)
        return 2
    print(f"loading {len(paths)} traces ...")
    dfs = [stl.load_trace(p)[0] for p in paths]
    print(f"a_comfort = {a_comfort} m/s^2   j_comfort = {j_comfort} m/s^3\n")

    thresholds = np.arange(a.lo, a.hi + 1e-9, a.step)
    rows = []
    print(f"{'thr':>6} {'viol%':>8} {'elig%':>8} {'traces':>7} {'medRho5':>9} "
          f"{'max|a|':>9} {'max|j|':>9}  {'p95|a|':>8}")
    print("-" * 74)
    for thr in thresholds:
        res = [c5_for_trace(df, float(thr), a_comfort, j_comfort) for df in dfs]
        scored = [r for r in res if r["rho5"] is not None]
        if not scored:
            print(f"{thr:>6.2f}   (no eligible samples in any trace)")
            rows.append({"threshold_mps": float(thr), "n_scored": 0})
            continue
        rho5 = np.array([r["rho5"] for r in scored])
        viol = float((rho5 < 0).mean())
        elig = float(np.mean([(r["n_elig_a"] / r["n_ticks"]) for r in res]))
        maxa = np.array([r["max_abs_a"] for r in scored if r["max_abs_a"] is not None])
        maxj = np.array([r["max_abs_j"] for r in scored if r["max_abs_j"] is not None])
        print(f"{thr:>6.2f} {100*viol:>7.1f}% {100*elig:>7.1f}% {len(scored):>7} "
              f"{np.median(rho5):>+9.3f} {maxa.max():>9.3f} {maxj.max():>9.2f} "
              f"{np.percentile(maxa,95):>8.3f}")
        rows.append({
            "threshold_mps": float(thr),
            "violation_rate": viol,
            "n_scored": len(scored),
            "n_unscorable": len(res) - len(scored),
            "mean_eligible_fraction": elig,
            "median_rho5": float(np.median(rho5)),
            "max_abs_a": float(maxa.max()),
            "p95_max_abs_a": float(np.percentile(maxa, 95)),
            "max_abs_j": float(maxj.max()),
            "p95_max_abs_j": float(np.percentile(maxj, 95)),
        })

    # Largest drop in violation rate between adjacent thresholds = the cliff.
    print("\n" + "=" * 74)
    print("CLIFF DETECTION -- change in violation rate per threshold step")
    print("=" * 74)
    valid = [r for r in rows if r.get("n_scored")]
    print(f"{'from':>6} {'to':>6} {'viol% from':>11} {'viol% to':>10} {'drop (pp)':>11}")
    print("-" * 52)
    drops = []
    for x, y in zip(valid, valid[1:]):
        d = 100 * (x["violation_rate"] - y["violation_rate"])
        drops.append((d, x["threshold_mps"], y["threshold_mps"]))
        if abs(d) > 0.3:
            print(f"{x['threshold_mps']:>6.2f} {y['threshold_mps']:>6.2f} "
                  f"{100*x['violation_rate']:>10.1f}% {100*y['violation_rate']:>9.1f}% "
                  f"{d:>+11.1f}")
    if drops:
        d, lo, hi = max(drops, key=lambda t: t[0])
        print(f"\n  largest single-step drop: {d:+.1f} pp between {lo:.2f} and {hi:.2f} m/s")

    pathlib.Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(a.out).write_text(json.dumps({
        "a_comfort_mps2": a_comfort, "j_comfort_mps3": j_comfort,
        "window_back_accel": W_ACCEL, "window_back_jerk": W_JERK,
        "n_traces": len(paths), "sweep": rows,
    }, indent=2))
    print(f"\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
