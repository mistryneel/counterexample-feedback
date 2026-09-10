#!/usr/bin/env python3
"""Score candidate baseline programs against the two freeze gates.

A candidate may only be frozen as `data/scenarios/baseline_program.bt` if it
passes BOTH gates. They are independent and they fail for different reasons.

GATE 1a -- violation rate in [0.20, 0.40]
    Too safe and the falsifier finds nothing to feed the experiment; too broken
    and all four conditions fix it trivially. Either way there is no dynamic
    range and therefore no result -- not a weak result, no result.

GATE 2 (DIAGNOSTIC ONLY, since 30 Aug) -- conditional blame entropy
    Blame localization is the ONLY thing F4 has that F3 does not. Measured on
    the reference program over 101 violations, `active_node` was a pure
    function of `violated_contract`:

        90 (89.1%)  C2 -> HoldAtStopLine
        11 (10.9%)  C1 -> CommitTurn

    Under such a program F4 and F3 are information-identical and the headline
    comparison of the paper measures nothing by construction. Note that adding
    MORE CONTRACTS does not fix this: it adds more (contract, node) pairs but
    leaves the mapping deterministic. What breaks the collapse is at least one
    contract being blameable on SEVERAL DISTINCT NODES, which is a property of
    the program's structure, not of the contract count.

GATE 1b -- task completion. ICR (fraction reaching P4_settle) must clear
    ICR_FLOOR. A program can hit a low violation rate simply by REFUSING TO
    TURN: it violates nothing and fails the task, and spec 5 says so directly
    ("a program that never enters the conflict zone is not a safe program, it
    is a failed task"). Scoring the violation rate alone would freeze exactly
    that program. Measured 31 Aug, the in-band candidate enters the junction in
    100% of scenarios and settles in 88.3%, so it passes on merit rather than
    by hiding.

Every candidate is scored on the SAME calibration scenarios -- same seed, same
parameter vectors -- or the violation rates are not comparable.

    scripts/calibrate_baseline.py --programs a.bt b.bt --n 120

Held-out region is excluded from sampling (it is reserved for evaluation), so
the rate reported here is the searched-region rate the falsifier will face.
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import pathlib
import random
import sys
import time
from dataclasses import asdict

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import stl  # noqa: E402
from config import load_config, param_hash  # noqa: E402
from run_campaign import sample, server_alive, restart_server  # noqa: E402

BAND_LO, BAND_HI = 0.20, 0.40
ICR_FLOOR = 0.60      # fraction of scenarios that must reach P4_settle
PHASES = ("P1_approach", "P2_yield_clear", "P2_yield_hold", "P3_commit", "P4_settle")


def conditional_entropy(pairs: list[tuple[str, str]]) -> tuple[float, dict]:
    """H(node | contract) in bits, plus the per-contract breakdown.

    Zero means the contract determines the node, i.e. `active_node` carries no
    information beyond `violated_contract` and the F3/F4 distinction collapses.
    """
    by_contract: dict[str, collections.Counter] = collections.defaultdict(
        collections.Counter)
    for contract, node in pairs:
        by_contract[contract][node] += 1

    total = len(pairs)
    h_total = 0.0
    detail = {}
    for contract, nodes in by_contract.items():
        n_c = sum(nodes.values())
        h_c = 0.0
        for count in nodes.values():
            p = count / n_c
            h_c -= p * math.log2(p)
        h_total += (n_c / total) * h_c
        detail[contract] = {
            "n": n_c,
            "distinct_nodes": len(nodes),
            "H_bits": round(h_c, 4),
            "nodes": dict(nodes.most_common()),
        }
    return h_total, detail


def score_program(be, program_path: str, params_list: list[dict], tag: str,
                  contracts, junction, port: int, gpu: int, cfg) -> dict:
    """Run every calibration scenario under one program and score the traces."""
    prog = be.load_program(program_path)
    print(f"\n=== {program_path}  depth={prog.ast.depth()} size={prog.ast.size()}")
    if prog.validation.warnings:
        print(f"    validator warnings: {prog.validation.warnings}")

    rows: list[dict] = []
    n_err = 0
    t0 = time.perf_counter()

    for i, params in enumerate(params_list):
        eid = f"cal_{tag}_{i:05d}_{param_hash(params)}"
        res = be.run_episode(params, episode_id=eid)

        if not res.usable and res.status in ("exception", "server_lost"):
            if not server_alive(port):
                print(f"  [{i}] server lost -- restarting", flush=True)
                try:
                    be.__exit__(None, None, None)
                except Exception:
                    pass
                restart_server(port, gpu)
                from carla_backend import CarlaBackend
                be = CarlaBackend(cfg=cfg)
                be.__enter__()
                be.load_program(program_path)
                res = be.run_episode(params, episode_id=eid)

        # A 'collision' episode is a legitimate sentinel termination with a
        # scoreable trace, and it is the LEAST ambiguous violation there is.
        # Filtering on status == 'ok' here undercounted the reference program
        # by 18.8 points (37.3% vs the true 56.1%). Score every trace that
        # exists; only a missing trace is excluded, and it is counted.
        if not res.trace_path or not pathlib.Path(res.trace_path).exists():
            n_err += 1
            continue

        try:
            df, meta = stl.load_trace(res.trace_path)
            r = stl.compute_rho(df, contracts, junction)
            row = df.iloc[int(r.argmin_index)]
            ph = set(res.meta.get("phases_reached") or [])
            rows.append({
                "params": params,
                "status": res.status,
                "settled": "P4_settle" in ph,
                "pcr": len(ph & set(PHASES)) / len(PHASES),
                "rho": r.rho,
                "contract": r.contract,
                "node": f"{row['bt_node_type']}:{row['bt_node_path']}",
                "per_contract": {k: v.rho for k, v in r.per_contract.items()},
            })
        except Exception as exc:
            print(f"  [{i}] scoring failed: {type(exc).__name__}: {exc}")
            n_err += 1

        if (i + 1) % 20 == 0:
            el = time.perf_counter() - t0
            print(f"  [{i+1}/{len(params_list)}] {(i+1)/el:.2f} ep/s", flush=True)

    viol = [x for x in rows if x["rho"] < 0]
    rate = len(viol) / len(rows) if rows else float("nan")
    h, detail = conditional_entropy([(x["contract"], x["node"]) for x in viol]) \
        if viol else (0.0, {})

    icr = (sum(1 for x in rows if x["settled"]) / len(rows)) if rows else 0.0
    pcr = (sum(x["pcr"] for x in rows) / len(rows)) if rows else 0.0
    gate1a = BAND_LO <= rate <= BAND_HI
    gate1b = icr >= ICR_FLOOR
    gate1 = gate1a and gate1b
    # GATE 2 IS REPORTED, NOT ENFORCED. It scores blame entropy over a UNIFORM
    # calibration sample, but the F3-vs-F4 comparison depends on entropy across
    # the K counterexamples the FALSIFIER SELECTS -- and the falsifier does not
    # sample uniformly, it searches for violations and then delta-debugs and
    # boundary-searches them. Measured 30 Aug, the two populations disagree
    # sharply: candidates near the band concentrate failures on one contract
    # and score H = 0.000, while candidates with diverse blame (H = 0.18-0.20)
    # sit at 99-100% violation. Blocking the freeze on the uniform number would
    # block on the wrong measurement.
    # The real check runs on the banked counterexamples once the falsifier
    # exists. If blame is still collapsed THERE, F4 is a placebo condition and
    # the paper must say so.
    gate2 = h > 0.0

    result = {
        "program": program_path,
        "n_scored": len(rows),
        "n_unscoreable": n_err,
        "violations": len(viol),
        "violation_rate": rate,
        "argmin_contract": dict(collections.Counter(x["contract"] for x in viol)),
        "distinct_blamed_nodes": len({x["node"] for x in viol}),
        "H_node_given_contract_bits": round(h, 4),
        "blame_detail": detail,
        "ICR": icr, "PCR": pcr,
        "gate1a_violation_band": gate1a,
        "gate1b_task_completion": gate1b,
        "gate1_violation_band": gate1,
        "gate2_blame_informative": gate2,
        "freezable": gate1,
        "gate2_is_diagnostic_only": True,
        "ast_depth": prog.ast.depth(),
        "ast_size": prog.ast.size(),
    }

    print(f"    violation rate      {rate:6.1%}   "
          f"[{'PASS' if gate1a else 'FAIL'}] band {BAND_LO:.0%}-{BAND_HI:.0%}")
    print(f"    ICR (P4_settle)     {icr:6.1%}   "
          f"[{'PASS' if gate1b else 'FAIL'}] floor {ICR_FLOOR:.0%}   PCR {pcr:.1%}")
    print(f"    H(node | contract)  {h:6.3f}b  "
          f"[{'>0' if gate2 else '=0'}] DIAGNOSTIC -- real check is post-falsification")
    print(f"    distinct nodes blamed: {result['distinct_blamed_nodes']}"
          f"   argmin: {result['argmin_contract']}")
    return result, be


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--programs", nargs="+", required=True,
                    help="candidate .bt files, scored on identical scenarios")
    ap.add_argument("--n", type=int, default=120,
                    help="calibration scenarios per candidate")
    ap.add_argument("--seed", type=int, default=20260830)
    ap.add_argument("--port", type=int, default=2000)
    ap.add_argument("--gpu", type=int, default=0)
    ap.add_argument("--out", default="data/results/baseline_calibration.json")
    a = ap.parse_args()

    cfg = load_config("sim")
    contracts = load_config("contracts")
    junction = stl.load_junction()
    print(f"active contracts: {contracts['combined']['active']}")

    # ONE scenario set, shared by every candidate. Without this the rates are
    # not comparable and the selection is meaningless.
    rng = random.Random(a.seed)
    params_list = [sample(rng) for _ in range(a.n)]
    print(f"calibration set: {a.n} scenarios, seed {a.seed}, "
          f"held-out region excluded")

    from carla_backend import CarlaBackend
    be = CarlaBackend(cfg=cfg)
    be.__enter__()
    results = []
    try:
        for p in a.programs:
            res, be = score_program(be, p, params_list, pathlib.Path(p).stem,
                                    contracts, junction, a.port, a.gpu, cfg)
            results.append(res)
    finally:
        try:
            be.__exit__(None, None, None)
        except Exception:
            pass

    out = {
        "seed": a.seed,
        "n_calibration_scenarios": a.n,
        "band": [BAND_LO, BAND_HI],
        "active_contracts": contracts["combined"]["active"],
        "candidates": results,
    }
    path = REPO / a.out
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2))

    print("\n" + "=" * 78)
    print(f"{'program':<44} {'rate':>7} {'H':>7}  verdict")
    print("-" * 78)
    for r in sorted(results, key=lambda x: abs(x["violation_rate"] - 0.30)):
        verdict = "FREEZABLE" if r["freezable"] else "out of band"
        print(f"{r['program'][:44]:<44} {r['violation_rate']:6.1%} "
              f"{r['H_node_given_contract_bits']:6.3f}  {verdict}")
    print("=" * 78)
    ok = [r for r in results if r["freezable"]]
    if ok:
        best = min(ok, key=lambda x: abs(x["violation_rate"] - 0.30))
        print(f"nearest band midpoint among freezable: {best['program']}")
    else:
        print("NO CANDIDATE IS FREEZABLE. Do not freeze one anyway.")
    print(f"written: {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
