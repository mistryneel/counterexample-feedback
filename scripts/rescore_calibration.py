#!/usr/bin/env python3
"""Re-score the frozen baseline's calibration run from its saved trajectories.

WHAT THIS REPRODUCES
    Section 3.2 of the paper: on the shared 100-scenario calibration set the
    frozen baseline violates on 20 scenarios, enters the junction in all 100
    and completes the turn in 90. The calibration harness recorded only the
    violation count (data/results/baseline_calibration.json, entry for the
    candidate that was frozen). Entry and completion are derived here from the
    100 trajectories of that run, with no simulator.

HOW THE TRACES ARE LINKED TO THE COMMITTED RUN
    1. Scenarios. scripts/calibrate_baseline.py drew its scenarios as
       random.Random(seed) followed by n calls of run_campaign.sample(), and
       recorded seed and n in baseline_calibration.json. The same draw is
       repeated here. Each trace is found by the file name the harness wrote,
       cal_<candidate>_<index>_<param_hash>, and its sidecar must record the
       same param_hash and the same parameter values.
    2. Program. Each trace records the program source it ran. Calibration ran
       the candidate file before it was frozen; baseline_program.bt is that
       file with a comment-only header prepended. The two files therefore hash
       differently while the program is the same. The script checks that each
       trace ran the candidate byte for byte, that the frozen file is a
       comment-only header followed by the candidate byte for byte, and that
       the two parse to equal trees.
    3. Agreement. The re-scored violation count, argmin-contract breakdown,
       blamed nodes and blame entropy must equal the committed entry.

DEFINITIONS
    violation  rho < 0, where rho is the minimum over the active contracts
               (src/stl.py, config/contracts.yaml).
    entered    C2 (yield) is not vacuous: the ego was inside the conflict zone
               on at least one tick. Same rule as src/evaluate.py.
    completed  phase P4_settle was reached. Same rule as the ICR of
               scripts/calibrate_baseline.py. Read from the sidecar's
               phases_reached and cross-checked against the trace's phase
               column.

TRACE LOCATION
    data/calibration_traces/ (the 100 traces and sidecars, committed) is
    preferred; data/traces/ (the original, git-ignored location) is the
    fallback. --trace-dir overrides both.

USAGE
    .venv/bin/python scripts/rescore_calibration.py           # write the JSON
    .venv/bin/python scripts/rescore_calibration.py --check   # compare only

    Exit code 0 when every check passes. Exit code 1 when any check fails or,
    with --check, when the output differs from the committed file. The output
    contains no timestamps or absolute paths, so a re-run is byte-identical.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import pathlib
import random
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import stl  # noqa: E402
from calibrate_baseline import PHASES, conditional_entropy  # noqa: E402
from config import load_config, param_hash  # noqa: E402
from program_parser import parse  # noqa: E402
from run_campaign import sample  # noqa: E402

COMMITTED = "data/results/baseline_calibration.json"
FROZEN = "data/scenarios/baseline_program.bt"
OUT = "data/results/baseline_calibration_frozen.json"
TRACE_DIRS = ("data/calibration_traces", "data/traces")

# The figures printed in paper/main.tex, Section 3.2 ("The frozen baseline
# violates on 20 of the 100 calibration scenarios, enters the junction in all
# of them, and completes the turn in 90"). Checked, never used to compute.
PAPER_SECTION_3_2 = {"n_scored": 100, "violations": 20, "entered": 100,
                     "completed": 90}

RHO_DP = 6   # rounding of stored rho values; far below any physical meaning


def sha16(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def sha256_file(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def split_comment_header(frozen: str, candidate: str) -> tuple[bool, int]:
    """True if `frozen` is comment or blank lines followed by `candidate`.

    Returns (holds, number of header lines).
    """
    if not frozen.endswith(candidate):
        return False, 0
    header = frozen[: len(frozen) - len(candidate)]
    lines = header.splitlines()
    ok = all(not ln.strip() or ln.lstrip().startswith("#") for ln in lines)
    return ok, len(lines)


def find_candidate(committed: dict, frozen_src: str) -> dict | None:
    """The committed candidate entry whose source the frozen file contains."""
    for cand in committed["candidates"]:
        src = (REPO / cand["program"]).read_text()
        if split_comment_header(frozen_src, src)[0]:
            return cand
    return None


def pick_trace_dir(tag: str, names: list[str], override: str | None):
    dirs = [override] if override else list(TRACE_DIRS)
    found = {}
    for d in dirs:
        p = REPO / d
        n = sum((p / f"{name}.parquet").exists() and (p / f"{name}.json").exists()
                for name in names)
        found[d] = n
        if n == len(names):
            return d, found
    return None, found


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--trace-dir", default=None,
                    help="directory holding the cal_<candidate>_* traces "
                         f"(default: first complete one of {', '.join(TRACE_DIRS)})")
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--check", action="store_true",
                    help="do not write; compare against the existing --out file")
    a = ap.parse_args()

    checks: list[dict] = []

    def check(name: str, ok: bool, detail="") -> None:
        checks.append({"check": name, "pass": bool(ok), "detail": detail})
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))

    committed = json.loads((REPO / COMMITTED).read_text())
    seed, n = committed["seed"], committed["n_calibration_scenarios"]
    frozen_src = (REPO / FROZEN).read_text()

    print("program")
    cand = find_candidate(committed, frozen_src)
    if cand is None:
        print(f"  [FAIL] no candidate in {COMMITTED} is the program in {FROZEN}")
        return 1
    cand_path = cand["program"]
    cand_src = (REPO / cand_path).read_text()
    tag = pathlib.Path(cand_path).stem
    header_ok, header_lines = split_comment_header(frozen_src, cand_src)
    check("frozen baseline = comment-only header + candidate, byte for byte",
          header_ok, f"{FROZEN} = {header_lines} comment lines + {cand_path}")
    ast_equal = parse(frozen_src).to_tuple() == parse(cand_src).to_tuple()
    check("frozen baseline and candidate parse to equal trees", ast_equal)

    print(f"scenarios: seed {seed}, n {n}, run_campaign.sample()")
    rng = random.Random(seed)
    params_list = [sample(rng) for _ in range(n)]
    names = [f"cal_{tag}_{i:05d}_{param_hash(p)}" for i, p in enumerate(params_list)]
    trace_dir, found = pick_trace_dir(tag, names, a.trace_dir)
    if trace_dir is None:
        print(f"  [FAIL] no directory holds all {n} traces and sidecars: {found}")
        return 1
    print(f"traces: {trace_dir}  ({n} of {n} found)")
    tdir = REPO / trace_dir

    contracts = load_config("contracts")
    junction = stl.load_junction()
    active = contracts["combined"]["active"]

    rows: list[dict] = []
    bad = collections.defaultdict(list)
    for i, (params, name) in enumerate(zip(params_list, names)):
        pq_path, js_path = tdir / f"{name}.parquet", tdir / f"{name}.json"
        side = json.loads(js_path.read_text())
        res = side["result"]
        df, meta = stl.load_trace(pq_path)

        h = param_hash(params)
        if not (side["param_hash"] == res["param_hash"] == meta["param_hash"] == h):
            bad["param_hash"].append(i)
        if not (res["scenario_params"] == params
                and json.loads(side["scenario_params"]) == params):
            bad["scenario_params"].append(i)
        if not (side["program_source"] == meta["program_source"] == cand_src
                and side["program_sha"] == meta["program_sha"] == sha16(cand_src)):
            bad["program"].append(i)

        r = stl.compute_rho(df, contracts, junction)
        row = df.iloc[int(r.argmin_index)]
        phases = list(res["meta"].get("phases_reached") or [])
        settled = "P4_settle" in phases
        if settled != bool((df["phase"] == "P4_settle").any()):
            bad["phase_column"].append(i)
        entered = not r.per_contract["C2"].vacuous

        rows.append({
            "index": i,
            "param_hash": h,
            "params": params,
            "trace": f"{name}.parquet",
            "trace_sha256": sha256_file(pq_path),
            "status": side["status"],
            "entered": entered,
            "reached_P4_settle": settled,
            "phases_reached": phases,
            "rho": round(float(r.rho), RHO_DP),
            "violated": bool(r.rho < 0),
            "argmin_contract": r.contract,
            "argmin_node": f"{row['bt_node_type']}:{row['bt_node_path']}",
            "rho_per_contract": {k: round(float(v.rho), RHO_DP)
                                 for k, v in r.per_contract.items()},
            "vacuous_contracts": sorted(k for k, v in r.per_contract.items()
                                        if v.vacuous),
        })

    print("trace provenance")
    check("sidecar and Parquet param_hash equal the regenerated hash",
          not bad["param_hash"], f"mismatches at {bad['param_hash']}" if bad["param_hash"] else f"{n}/{n}")
    check("recorded parameters equal the regenerated parameters",
          not bad["scenario_params"], f"mismatches at {bad['scenario_params']}" if bad["scenario_params"] else f"{n}/{n}")
    check(f"every trace ran {cand_path} (sha16 {sha16(cand_src)})",
          not bad["program"], f"mismatches at {bad['program']}" if bad["program"] else f"{n}/{n}")
    check("phases_reached agrees with the trace's phase column on P4_settle",
          not bad["phase_column"], f"mismatches at {bad['phase_column']}" if bad["phase_column"] else f"{n}/{n}")

    viol = [x for x in rows if x["violated"]]
    h_bits, blame = conditional_entropy([(x["argmin_contract"], x["argmin_node"])
                                         for x in viol]) if viol else (0.0, {})
    phase_counts = collections.Counter(p for x in rows for p in x["phases_reached"])
    totals = {
        "n_scored": len(rows),
        "n_unscoreable": n - len(rows),
        "violations": len(viol),
        "violation_rate": len(viol) / len(rows),
        "argmin_contract": dict(collections.Counter(x["argmin_contract"] for x in viol)),
        "distinct_blamed_nodes": len({x["argmin_node"] for x in viol}),
        "H_node_given_contract_bits": round(h_bits, 4),
        "blame_detail": blame,
        "entered": sum(x["entered"] for x in rows),
        "completed": sum(x["reached_P4_settle"] for x in rows),
        "ICR": sum(x["reached_P4_settle"] for x in rows) / len(rows),
        "PCR": round(sum(len(set(x["phases_reached"]) & set(PHASES)) / len(PHASES)
                         for x in rows) / len(rows), 6),
        "phases_reached": {p: phase_counts.get(p, 0) for p in PHASES},
        "status": dict(sorted(collections.Counter(x["status"] for x in rows).items())),
        "violations_entered": sum(x["entered"] for x in viol),
        "violations_completed": sum(x["reached_P4_settle"] for x in viol),
    }

    print(f"agreement with {COMMITTED} ({tag})")
    for key in ("n_scored", "n_unscoreable", "violations", "violation_rate",
                "argmin_contract", "distinct_blamed_nodes",
                "H_node_given_contract_bits", "blame_detail"):
        got, want = totals[key], cand[key]
        shown = "" if key == "blame_detail" else f"re-scored {got}, committed {want}"
        check(f"{key}", got == want, shown)

    print("agreement with paper/main.tex, Section 3.2")
    for key, want in PAPER_SECTION_3_2.items():
        got = totals[key]
        check(f"{key}", got == want, f"re-scored {got}, paper {want}")

    out = {
        "description": (
            "The frozen baseline's calibration run, re-scored from its saved "
            "trajectories by scripts/rescore_calibration.py. Supplies the "
            "junction entry and turn completion counts of paper Section 3.2, "
            f"which {COMMITTED} does not record."),
        "generated_by": "scripts/rescore_calibration.py",
        "calibration": {
            "source": COMMITTED,
            "seed": seed,
            "n_calibration_scenarios": n,
            "sampler": "scripts/run_campaign.py:sample, as in scripts/calibrate_baseline.py",
            "active_contracts": active,
        },
        "program": {
            "frozen_baseline": FROZEN,
            "frozen_baseline_sha16": sha16(frozen_src),
            "calibrated_as": cand_path,
            "calibrated_as_sha16": sha16(cand_src),
            "relation": (f"{FROZEN} is {header_lines} comment lines followed by "
                         f"{cand_path} byte for byte; the parsed trees are equal. "
                         "Traces record the candidate's hash because calibration "
                         "ran before the freeze."),
            "comment_header_lines": header_lines,
            "trees_equal": ast_equal,
        },
        "trace_dir": trace_dir,
        "definitions": {
            "violated": "rho < 0, rho = min over active contracts (src/stl.py)",
            "entered": "C2 not vacuous: the ego was in the conflict zone on at least one tick (as src/evaluate.py)",
            "reached_P4_settle": "P4_settle in the sidecar's phases_reached (the ICR of scripts/calibrate_baseline.py)",
            "argmin_node": "bt_node_type:bt_node_path at the argmin row (as scripts/calibrate_baseline.py)",
            "rho_values": f"rounded to {RHO_DP} decimal places; 999.0 is the vacuity sentinel",
        },
        "totals": totals,
        "paper_section_3_2": PAPER_SECTION_3_2,
        "checks": checks,
        "all_checks_pass": all(c["pass"] for c in checks),
        "scenarios": rows,
    }
    text = json.dumps(out, indent=2) + "\n"

    print(f"\ntotals: scored {totals['n_scored']}, entered {totals['entered']}, "
          f"completed {totals['completed']}, violations {totals['violations']} "
          f"{totals['argmin_contract']}, status {totals['status']}")

    path = REPO / a.out
    if a.check:
        same = path.exists() and path.read_text() == text
        print(f"--check: {a.out} {'is byte-identical' if same else 'DIFFERS'}")
        return 0 if (same and out["all_checks_pass"]) else 1
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    print(f"written: {a.out}")
    print("ALL CHECKS PASS" if out["all_checks_pass"] else "SOME CHECKS FAILED")
    return 0 if out["all_checks_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
