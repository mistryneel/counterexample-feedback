#!/usr/bin/env python3
"""Measure per-contract reproducibility across repeated identical episodes.

WHY THIS EXISTS. The determinism gate reports a single `rho_spread` over
rho = min(C1..C5). That hides a contract which drifts while a DIFFERENT
contract is the argmin -- the min() masking problem docs/sensitivity_analysis.md
already documented for gradients, showing up again for determinism. This
probe reports EVERY contract separately over N repeats of the same parameters.

It also runs the six-parameter space the campaign actually samples. The gate's
GATE_PARAMS predate it: they carry `ped_phase_offset` (dropped 24 Aug) and
omit `lead_gap_s`, and CarlaBackend._spawn_lead returns None without
`lead_gap_s`, so no lead vehicle is ever spawned and C4 is vacuous throughout
the gate. The gate therefore cannot observe C4 at all.

    .venv/bin/python scripts/probe_c4_determinism.py --repeats 6
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

import numpy as np

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

import stl  # noqa: E402
from config import load_config, param_hash  # noqa: E402

TOL_RHO = 1e-6          # the determinism gate's tolerance

SCENARIOS = [
    {"n_oncoming": 2, "v_oncoming": 14.0, "headway": 2.0,
     "aggressiveness": 0.9, "light_offset": 2.0, "lead_gap_s": 2.5},
    {"n_oncoming": 1, "v_oncoming": 8.0, "headway": 6.0,
     "aggressiveness": 0.2, "light_offset": 8.0, "lead_gap_s": 4.0},
    {"n_oncoming": 3, "v_oncoming": 10.0, "headway": 5.0,
     "aggressiveness": 0.5, "light_offset": 5.0, "lead_gap_s": 3.0},
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=6)
    ap.add_argument("--port", type=int, default=2000)
    ap.add_argument("--program", default=str(REPO / "data/scenarios/baseline_program.bt"))
    ap.add_argument("--out", default=str(REPO / "data/results/determinism_c4.json"))
    a = ap.parse_args()

    cfg = load_config("sim")
    cfg["server"]["port"] = a.port
    contracts = load_config("contracts")
    junction = stl.load_junction()

    from carla_backend import CarlaBackend
    be = CarlaBackend(cfg=cfg)
    be.__enter__()
    out = {"repeats": a.repeats, "program": a.program, "tolerance": TOL_RHO,
           "scenarios": []}
    try:
        be.load_program(a.program)
        for si, params in enumerate(SCENARIOS):
            per: dict = {}
            rhos, leads = [], []
            for t in range(a.repeats):
                res = be.run_episode(
                    params, episode_id=f"c4det_{si}_{t}_{param_hash(params)}")
                df, _ = stl.load_trace(res.trace_path)
                r = stl.compute_rho(df, contracts, junction)
                rhos.append(float(r.rho))
                for k, c in r.per_contract.items():
                    per.setdefault(k, []).append(float(c.rho))
                # lead vehicle trajectory, if one exists
                xs = []
                for row_i in range(len(df)):
                    roles = list(df["actor_role"].iloc[row_i])
                    for j, role in enumerate(roles):
                        if role == "lead":
                            xs.append(float(df["actor_x_m"].iloc[row_i][j]))
                            break
                leads.append(np.array(xs))
            rec = {"params": params,
                   "rho_spread": float(np.ptp(rhos)),
                   "per_contract": {}}
            for k, v in per.items():
                arr = np.array(v)
                rec["per_contract"][k] = {
                    "values": [round(float(x), 6) for x in arr],
                    "spread": float(np.ptp(arr)),
                    "reproduces": bool(np.ptp(arr) <= TOL_RHO),
                }
            n = min(len(x) for x in leads)
            if n:
                stack = np.stack([x[:n] for x in leads])
                dev = np.ptp(stack, axis=0)
                first = int(np.argmax(dev > 1e-9)) if (dev > 1e-9).any() else None
                rec["lead_x_max_spread_m"] = float(dev.max())
                rec["lead_first_divergent_row"] = first
            out["scenarios"].append(rec)
            print(f"\nscenario {si}: {params}")
            print(f"  rho spread {rec['rho_spread']:.3e}")
            for k, v in rec["per_contract"].items():
                flag = "OK " if v["reproduces"] else "*** DRIFTS ***"
                print(f"   {k}: spread={v['spread']:.6e} {flag} {v['values']}")
            print(f"  lead x max spread {rec.get('lead_x_max_spread_m', 0):.4f} m"
                  f"  first divergent row {rec.get('lead_first_divergent_row')}")
    finally:
        try:
            be.__exit__(None, None, None)
        except Exception:
            pass

    drifting = sorted({k for s in out["scenarios"]
                       for k, v in s["per_contract"].items()
                       if not v["reproduces"]})
    out["contracts_that_drift"] = drifting
    pathlib.Path(a.out).write_text(json.dumps(out, indent=2))
    print(f"\ncontracts that drift beyond {TOL_RHO}: {drifting or 'none'}")
    print(f"written: {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
