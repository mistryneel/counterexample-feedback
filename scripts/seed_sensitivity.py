#!/usr/bin/env python3
"""Determinism gate stage 3.6 — Traffic Manager seed sensitivity.

Runs as its own program and NEVER IMPORTS carla. It only orchestrates
subprocesses: stop/start the server, and run scripts/tm_probe.py. That is
deliberate -- a process that has ever held a carla.Client aborts with SIGABRT
from libcarla's background thread when the server is stopped underneath it,
and dropping the Python reference does not prevent this.

Writes a JSON result the gate reads back.
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import subprocess
import sys

import numpy as np

REPO = pathlib.Path(__file__).resolve().parent.parent
TOL = 1e-6


def restart(port: int) -> None:
    subprocess.run([str(REPO / "scripts/stop_carla.sh"), "--port", str(port)],
                   capture_output=True, timeout=240)
    r = subprocess.run([str(REPO / "scripts/start_carla.sh"),
                        "--port", str(port), "--gpu", "0"],
                       capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        raise RuntimeError(f"server restart failed:\n{r.stdout[-800:]}\n{r.stderr[-800:]}")


def probe(port: int, seed, tag: str) -> np.ndarray:
    out = REPO / "data" / "results" / f"tm_probe_{tag}.npy"
    out.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        [str(REPO / ".venv/bin/python"), str(REPO / "scripts/tm_probe.py"),
         "--port", str(port), "--seed", str(seed), "--out", str(out)],
        capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        raise RuntimeError(f"probe {tag} failed:\n{r.stdout[-600:]}\n{r.stderr[-900:]}")
    return np.load(out)


def dev(a: np.ndarray, b: np.ndarray) -> float:
    if a.shape != b.shape:
        return math.inf
    return float(np.abs(a - b).max())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=2000)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    seed, port = a.seed, a.port

    print("  (a) TM seed SET to %d, two FRESH servers:" % seed, flush=True)
    restart(port); a1 = probe(port, seed, "a1")
    restart(port); a2 = probe(port, seed, "a2")
    dev_set = dev(a1, a2)
    print(f"      max positional deviation = {dev_set:.6e} m", flush=True)

    print(f"\n  (b) TM seeds {seed} vs {seed + 1}, two FRESH servers:", flush=True)
    restart(port); b1 = probe(port, seed, "b1")
    restart(port); b2 = probe(port, seed + 1, "b2")
    dev_diff = dev(b1, b2)
    print(f"      max positional deviation = {dev_diff:.6e} m", flush=True)

    same_reproduces = dev_set <= TOL
    diff_diverge = dev_diff > TOL

    print()
    print(f"  same seed  -> reproduces exactly : {same_reproduces}")
    print(f"  diff seeds -> diverge            : {diff_diverge}")
    print()
    if same_reproduces and diff_diverge:
        print("  => The TM seed DOES control TM-controlled traffic. Both halves of")
        print("     the evidence hold. A test showing only 'same seed reproduces'")
        print("     would also pass if the seed were ignored entirely and the TM")
        print("     happened to be deterministic, which is why (b) is run.")
    elif same_reproduces and not diff_diverge:
        print("  => INCONCLUSIVE. Same seed reproduces, but so do DIFFERENT seeds --")
        print("     consistent with the seed being ignored and the TM being")
        print("     deterministic regardless. Not a failure for E1, but the seed")
        print("     cannot be claimed to control anything.")
    else:
        print("  => The TM seed does NOT give reproducible TM traffic.")

    print()
    print("  SCOPE -- what this does and does not certify:")
    print("    E1 drives oncoming vehicles with enable_constant_velocity and the")
    print("    ego under program control. NO actor is under Traffic Manager")
    print("    control, so in E1 the TM seed governs nothing. That is a")
    print("    determinism ADVANTAGE, not a gap: it removes a stochastic")
    print("    subsystem from the experiment entirely. This stage probes the TM")
    print("    in isolation. The seeding E1 actually depends on is certified by")
    print("    3.4 and 3.5, which produced bit-identical trajectories and rho")
    print("    from identical parameters, within and across processes.")

    res = {
        "pass": bool(same_reproduces),
        "seed": seed,
        "max_dev_seed_set_m": dev_set,
        "max_dev_different_seeds_m": dev_diff,
        "same_seed_reproduces": bool(same_reproduces),
        "different_seeds_diverge": bool(diff_diverge),
        "e1_uses_tm_for_any_actor": False,
        "method": "across full server restarts; reload_world unavailable",
        "tolerance": TOL,
    }
    pathlib.Path(a.out).write_text(json.dumps(res, indent=2))
    return 0 if same_reproduces else 1


if __name__ == "__main__":
    sys.exit(main())
