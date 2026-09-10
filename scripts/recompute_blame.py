#!/usr/bin/env python3
"""Recompute blame over the banked corpus under both definitions, and suppress
the `headway` boundaries that would mislead the repair.

Two jobs, both operating on banked traces only -- no re-simulation, so the
frozen baseline and the 20 certificates stay exactly as they are.

1. BLAME. Adds `authorising_node` alongside the pre-registered `active_node`
   and reports H(node | contract) under each. See src/blame.py for why there
   are two definitions and why both must be reported.

2. HEADWAY SUPPRESSION. `headway` is anti-correlated with the gap the ego
   actually observes under the frozen baseline: corr = -0.252, requesting
   6-8 s delivers a mean gap of 1.57 s while requesting 1.5-3 s delivers
   4.46 s. A certificate reading "fails for headway <= 7.529" therefore invites
   the model to demand a ~7.5 s gap when the gap it will observe is ~1.4 s --
   the over-patch that collapses task completion, which the project notes name as the
   most likely quiet failure. Root cause is `t_ego_to_decision_s = 4.95`,
   measured under the hardcoded controller; sim.yaml's own comment says to
   re-measure it once the behaviour tree drives the approach and that never
   happened. Fixing it changes every scenario and would invalidate both the
   baseline calibration and this corpus, so the boundary is SUPPRESSED FROM
   RENDERING instead, flagged, and recorded as a limitation. Nothing is
   deleted: `boundary` keeps every parameter it found.

    scripts/recompute_blame.py [--write]

Without --write it reports and changes nothing.
"""
from __future__ import annotations

import argparse
import glob
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

import blame  # noqa: E402
import stl  # noqa: E402

SUPPRESS = {"headway"}
SUPPRESS_REASON = (
    "headway is anti-correlated with the gap the ego observes under this "
    "baseline (corr -0.252; requesting 6-8 s yields a mean 1.57 s, requesting "
    "1.5-3 s yields 4.46 s), because t_ego_to_decision_s was measured under "
    "the hardcoded controller and never re-measured for the behaviour tree. "
    "Rendering this boundary would invite an over-patch. Suppressed from the "
    "prompt, retained in `boundary`."
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()

    paths = sorted(glob.glob(str(REPO / "data/certificates/*.json")))
    print(f"certificates: {len(paths)}\n")

    rows, missing, suppressed = [], 0, 0
    for p in paths:
        c = json.loads(pathlib.Path(p).read_text())
        df, _ = stl.load_trace(c["trace_path"])
        i = int(c["argmin_index"])

        act = blame.active_node(df, i)
        auth = blame.authorising_node(df, i)
        if auth is None:
            missing += 1
        if act != c["active_node"]:
            print(f"  !! {c['certificate_id']}: recomputed active_node differs "
                  f"from the banked one\n     banked {c['active_node']}\n"
                  f"     recomputed {act}")

        # which boundary parameters would be rendered, and which are held back
        bnd = c.get("boundary") or []
        hidden = sorted({b["parameter"] for b in bnd if b["parameter"] in SUPPRESS})
        shown = sorted({b["parameter"] for b in bnd if b["parameter"] not in SUPPRESS})
        if hidden:
            suppressed += 1

        rows.append({"id": c["certificate_id"], "contract": c["violated_contract"],
                     "active": act, "authorising": auth,
                     "hidden": hidden, "shown": shown})

        if a.write:
            c["authorising_node"] = auth
            c["blame_definitions"] = {
                "active_node": "leaf ticking at the argmin timestep (pre-registered, spec 7.5)",
                "authorising_node": "last distinct leaf active before the argmin leaf's run began",
            }
            c["boundary_suppressed"] = hidden
            if hidden:
                c["boundary_suppressed_reason"] = SUPPRESS_REASON
            c["boundary_report_rendered"] = _render(c, shown)
            pathlib.Path(p).write_text(json.dumps(c, indent=2))

    # ---- the measurement -------------------------------------------------
    contracts = [r["contract"] for r in rows]
    h_act, d_act = blame.conditional_entropy([(r["contract"], r["active"]) for r in rows])
    auth_rows = [r for r in rows if r["authorising"] is not None]
    h_auth, d_auth = blame.conditional_entropy(
        [(r["contract"], r["authorising"]) for r in auth_rows])

    print("=" * 74)
    print(f"{'definition':<22} {'H(node|contract)':>18} {'distinct nodes':>16}")
    print("-" * 74)
    print(f"{'active_node':<22} {h_act:>13.4f} bits {len({r['active'] for r in rows}):>16}"
          "   <- pre-registered")
    print(f"{'authorising_node':<22} {h_auth:>13.4f} bits "
          f"{len({r['authorising'] for r in auth_rows}):>16}")
    print("-" * 74)
    print(f"for contrast, H(contract) = {blame.entropy(contracts):.4f} bits "
          f"-- the corpus IS varied, just not in blame")
    if missing:
        print(f"{missing} certificate(s) had no prior leaf; excluded from the "
              "authorising_node figure rather than filled in")
    print("=" * 74)

    for name, d in (("active_node", d_act), ("authorising_node", d_auth)):
        print(f"\n{name}, per contract:")
        for k, v in sorted(d.items()):
            print(f"  {k}: n={v['n']:2d} distinct={v['distinct_nodes']} "
                  f"H={v['H_bits']:.4f}  {v['nodes']}")

    print(f"\nboundary suppression: {suppressed}/{len(rows)} certificates "
          f"carry a {'/'.join(sorted(SUPPRESS))} boundary")
    for r in rows:
        if r["hidden"]:
            print(f"  {r['id']}: hidden={r['hidden']} still shown={r['shown'] or 'NOTHING'}")

    empty = [r["id"] for r in rows if r["hidden"] and not r["shown"]]
    if empty:
        print(f"\n  !! {len(empty)} certificate(s) would render NO boundary at all "
              f"after suppression: {empty}")
        print("     Those fall back to reporting the minimal parameter set without a "
              "boundary, and that must be stated in the paper -- it weakens exactly "
              "the property (generalized) that boundary search exists to provide.")

    out = REPO / "data/results/blame_recompute.json"
    out.write_text(json.dumps({
        "n": len(rows),
        "H_active_node_bits": round(h_act, 4),
        "H_authorising_node_bits": round(h_auth, 4),
        "H_contract_bits": round(blame.entropy(contracts), 4),
        "detail_active": d_act, "detail_authorising": d_auth,
        "n_boundary_suppressed": suppressed,
        "certificates_with_no_rendered_boundary": empty,
        "rows": rows,
    }, indent=2))
    print(f"\nwritten: {out.relative_to(REPO)}"
          + ("" if a.write else "   (certificates NOT modified; pass --write)"))
    return 0


def _render(c: dict, shown: list[str]) -> str:
    """Re-render the boundary line with suppressed parameters left out."""
    if not shown:
        return ""
    parts = [b.get("rendered") or f"{b['parameter']} {b['direction']} {b['threshold']}"
             for b in (c.get("boundary") or []) if b["parameter"] in shown]
    return f"{c['violated_contract']} fails for " + " when ".join(parts)


if __name__ == "__main__":
    raise SystemExit(main())
