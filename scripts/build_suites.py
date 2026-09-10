#!/usr/bin/env python3
"""Build and FREEZE the two evaluation suites E1 scores every patch on.

Both are frozen to disk with the seed, the git commit and the SHA of the
program they were measured against, because every attempt in the campaign must
be evaluated on the SAME scenarios or the per-condition numbers are not
comparable -- which is the entire point of the ablation.

  REGRESSION SUITE, 30 scenarios, drawn from the SEARCHED region.
      Filtered so the frozen baseline PASSES all 30 (rho >= 0). That filter is
      what makes "regression failure" mean something: a scenario the program
      used to handle and now does not.

  HELD-OUT SUITE, 30 scenarios, drawn EXCLUSIVELY from the reserved region of
  data/scenarios/space.yaml (v_oncoming in [11,13] AND headway in [3,4.5]),
  which the falsifier was never allowed to sample.
      NOT filtered. The reserved region is deliberately the hardest part of the
      space (§9.5: centred on tau_yield and the mid-range oncoming speed), and
      filtering it to baseline-passing scenarios would quietly select the easy
      corner of a region chosen for being hard.

⚠️ THE TWO SUITES ARE THEREFORE NOT SYMMETRIC, and the generalization gap has
to be read accordingly. `searched_scvr` is measured on a baseline-PASSING
sample, so it is 0.000 for the baseline by construction, while
`held_out_scvr` is measured on an unfiltered sample and is not. Subtracting
them for a single program gives a number contaminated by the filter. The fix
costs nothing and is applied throughout: the UNPATCHED BASELINE is evaluated
on both suites here and reported as a reference row, so every gap is read as a
CHANGE from the baseline's own gap rather than as an absolute. Spec §9.4
requires the unpatched baseline as a comparator anyway.

    .venv/bin/python scripts/build_suites.py --port 2000
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import random
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import stl  # noqa: E402
import yaml  # noqa: E402
from config import git_commit, load_config, param_hash  # noqa: E402

REG_PATH = REPO / "data" / "scenarios" / "regression_suite.json"
HELD_PATH = REPO / "data" / "scenarios" / "held_out_suite.json"
BASELINE = REPO / "data" / "scenarios" / "baseline_program.bt"

# Fixed, and recorded in both files. Re-running with the same seed against the
# same program reproduces the same suites.
DEFAULT_SEED = 20260831


def sha16(p) -> str:
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()[:16]


def load_space():
    y = yaml.safe_load((REPO / "data/scenarios/space.yaml").read_text())
    space = {k: tuple(v["range"]) for k, v in y["parameters"].items()}
    types = {k: v.get("type", "float") for k, v in y["parameters"].items()}
    held = {k: tuple(v) for k, v in y["held_out"].items() if k != "justification"}
    return space, types, held


def draw(rng, space, types, held, region: str) -> dict:
    """One sample. `region` is 'searched' (outside the hole) or 'held_out'.

    Held-out draws sample the two reserved axes from the reserved ranges
    directly rather than rejection-sampling the full box: the hole is ~4.6% of
    the space, so rejection sampling would work but would make the suite's
    reproducibility depend on the rejection count.
    """
    while True:
        p = {}
        for name, (lo, hi) in space.items():
            if region == "held_out" and name in held:
                lo, hi = held[name]
            if types.get(name) == "integer":
                p[name] = rng.randint(int(lo), int(hi))
            else:
                p[name] = round(rng.uniform(float(lo), float(hi)), 4)
        inside = all(held[k][0] <= p[k] <= held[k][1] for k in held)
        if region == "held_out":
            assert inside, "held-out draw escaped the reserved region"
            return p
        if not inside:
            return p


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--n-regression", type=int, default=30)
    ap.add_argument("--n-held-out", type=int, default=30)
    ap.add_argument("--program", default=str(BASELINE))
    ap.add_argument("--max-draws", type=int, default=400)
    a = ap.parse_args()

    cfg = load_config("sim")
    cfg["server"]["port"] = a.port
    contracts = load_config("contracts")
    junction = stl.load_junction()
    space, types, held = load_space()
    rng = random.Random(a.seed)

    from carla_backend import CarlaBackend
    from evaluate import Evaluator

    print(f"building suites: seed={a.seed} program={pathlib.Path(a.program).name} "
          f"sha={sha16(a.program)}")
    print(f"  held-out region: " + ", ".join(f"{k}={v}" for k, v in held.items()))

    be = CarlaBackend(cfg=cfg)
    be.__enter__()
    try:
        ev = Evaluator(be, contracts, junction)

        # -- regression: draw until 30 that the baseline PASSES -------------
        reg, tried, rejected = [], 0, 0
        while len(reg) < a.n_regression and tried < a.max_draws:
            p = draw(rng, space, types, held, "searched")
            tried += 1
            ro = ev.rollout(p, a.program, "regression")
            if ro.scoreable and ro.rho >= 0.0:
                reg.append(_record(p, ro))
                print(f"  reg {len(reg):>2}/{a.n_regression}  rho={ro.rho:+.4f} "
                      f"{ro.status}")
            else:
                rejected += 1
        if len(reg) < a.n_regression:
            print(f"FAILED: only {len(reg)} baseline-passing scenarios in "
                  f"{tried} draws")
            return 1

        # -- held-out: draw 30 from the reserved region, UNFILTERED ---------
        heldout = []
        while len(heldout) < a.n_held_out:
            p = draw(rng, space, types, held, "held_out")
            ro = ev.rollout(p, a.program, "evaluation")
            if not ro.scoreable:
                print(f"  held-out draw unscoreable ({ro.status}); redrawing")
                continue
            heldout.append(_record(p, ro))
            print(f"  held {len(heldout):>2}/{a.n_held_out}  rho={ro.rho:+.4f} "
                  f"{ro.status}  {'VIOLATES' if ro.rho < 0 else ''}")

        base_reg_scvr = sum(1 for r in reg if r["baseline_rho"] < 0) / len(reg)
        base_held_scvr = sum(1 for r in heldout if r["baseline_rho"] < 0) / len(heldout)

        meta = {
            "seed": a.seed, "git_commit": git_commit(),
            "built": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "program": str(pathlib.Path(a.program).relative_to(REPO)),
            "program_sha256_16": sha16(a.program),
            "held_out_region": {k: list(v) for k, v in held.items()},
        }
        _write(REG_PATH, {
            **meta, "suite": "regression", "region": "searched",
            "filter": "baseline rho >= 0", "n": len(reg),
            "draws_made": tried, "draws_rejected": rejected,
            "baseline_scvr": base_reg_scvr, "scenarios": reg})
        _write(HELD_PATH, {
            **meta, "suite": "held_out", "region": "reserved",
            "filter": "none -- see the module docstring", "n": len(heldout),
            "baseline_scvr": base_held_scvr, "scenarios": heldout})

        print(f"\nregression suite: {len(reg)} scenarios from {tried} draws "
              f"({rejected} rejected because the baseline failed them)")
        print(f"  baseline SCVR on it: {base_reg_scvr:.3f}  (0.000 by construction)")
        print(f"held-out suite:   {len(heldout)} scenarios, unfiltered")
        print(f"  baseline SCVR on it: {base_held_scvr:.3f}  "
              f"<- the reference the generalization gap is read against")
        print(f"  BASELINE'S OWN GAP: {base_reg_scvr - base_held_scvr:+.3f}")
        print(f"\nrollouts: regression {ev.budget['regression']}, "
              f"evaluation {ev.budget['evaluation']}, "
              f"cache hits {ev.cache_hits}")
        print(f"wrote {REG_PATH.relative_to(REPO)} and {HELD_PATH.relative_to(REPO)}")
    finally:
        be.__exit__(None, None, None)
    return 0


def _record(p: dict, ro) -> dict:
    return {
        "params": dict(p),
        "param_hash": param_hash(p),
        "baseline_rho": round(float(ro.rho), 6),
        "baseline_per_contract": {k: round(float(v), 6)
                                  for k, v in ro.per_contract.items()},
        "baseline_status": ro.status,
        "baseline_phases_reached": list(ro.phases_reached),
    }


def _write(path: pathlib.Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w") as fh:
        json.dump(obj, fh, indent=2, default=str)
        fh.flush()
        os.fsync(fh.fileno())
    tmp.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
