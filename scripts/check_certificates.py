#!/usr/bin/env python3
"""Verify every banked certificate is schema-complete and internally consistent.

Checks the required fields from the falsifier spec, plus consistency
properties that a silently-broken pipeline would violate while still producing
well-formed JSON:

  * the certificate's own rho matches rho<N> for the contract it blames
  * rho < 0 -- a certificate is a VIOLATION, always
  * `avoidable` is true -- an inadmissible counterexample must never be banked
  * `active_node` is present and matches bt_node_type:bt_node_path
  * the minimized configuration still violates the same contract
  * the scenario is outside the held-out region
  * boundary entries are either resolved with a threshold or carry a note

    .venv/bin/python scripts/check_certificates.py
"""
from __future__ import annotations

import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from run_campaign import in_held_out  # noqa: E402

REQUIRED = [
    "certificate_id", "param_hash", "git_commit", "timestamp",
    "scenario_params", "minimal_params", "violated_contract",
    "rho", "rho1", "rho2", "rho3", "rho4", "rho5",
    "argmin_t_s", "argmin_frame", "active_node", "boundary", "narrative",
    "avoidable", "rollouts_falsification", "rollouts_minimization",
    "rollouts_boundary", "rollouts_avoidability",
]
CONTRACT_KEYS = ("C1", "C2", "C3", "C4", "C5")


def main() -> int:
    paths = sorted((REPO / "data/certificates").glob("CE*.json"))
    if not paths:
        print("no certificates found")
        return 1
    problems: list = []
    for p in paths:
        c = json.loads(p.read_text())
        cid = c.get("certificate_id", p.name)

        for f in REQUIRED:
            if f not in c or c[f] is None:
                problems.append(f"{cid}: missing required field {f!r}")

        con = c.get("violated_contract")
        if con not in CONTRACT_KEYS:
            problems.append(f"{cid}: violated_contract {con!r} not in C1..C5")
        else:
            idx = CONTRACT_KEYS.index(con) + 1
            if c.get(f"rho{idx}") is None:
                problems.append(f"{cid}: rho{idx} is null for blamed {con}")
            elif abs(c[f"rho{idx}"] - c["rho"]) > 1e-6:
                problems.append(
                    f"{cid}: rho={c['rho']} != rho{idx}={c[f'rho{idx}']} "
                    f"for blamed contract {con}")

        if c.get("rho", 0) >= 0:
            problems.append(f"{cid}: rho={c.get('rho')} >= 0 -- not a violation")
        if c.get("avoidable") is not True:
            problems.append(f"{cid}: avoidable is not True")
        if c.get("active_node") != f"{c.get('bt_node_type')}:{c.get('bt_node_path')}":
            problems.append(f"{cid}: active_node inconsistent with bt_node_* fields")

        pcm = c.get("per_contract_minimal", {})
        if con in pcm and pcm[con] >= 0:
            problems.append(
                f"{cid}: minimized config no longer violates {con} "
                f"(rho={pcm[con]})")

        for label, params in (("scenario_params", c.get("scenario_params")),
                              ("minimal_params", c.get("minimal_params"))):
            if params and in_held_out(params):
                problems.append(f"{cid}: {label} lies INSIDE the held-out region")

        for b in c.get("boundary", []):
            if b.get("resolved") and b.get("threshold") is None:
                problems.append(f"{cid}: boundary {b.get('parameter')} "
                                f"resolved but has no threshold")
            if not b.get("resolved") and not b.get("note"):
                problems.append(f"{cid}: boundary {b.get('parameter')} "
                                f"unresolved with no explanation")

    print(f"checked {len(paths)} certificates")
    hashes = {json.loads(p.read_text())["param_hash"] for p in paths}
    print(f"distinct scenarios: {len(hashes)} of {len(paths)}")
    if len(hashes) != len(paths):
        problems.append(f"corpus contains duplicate scenarios "
                        f"({len(paths) - len(hashes)} repeats)")
    if problems:
        print(f"\n{len(problems)} PROBLEM(S):")
        for x in problems:
            print("  -", x)
        return 1
    print("ALL CERTIFICATES SCHEMA-COMPLETE AND CONSISTENT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
