#!/usr/bin/env python3
"""Assert that traces are fit to back a paper claim.

Checks, over a directory of Parquet traces:
  1. non-empty git_commit          -- the code that produced it is recoverable
  2. bt_node_* populated           -- produced by a behaviour tree, so blame
                                      localization is possible
  3. no dropped falsifier params   -- e.g. ped_phase_offset, removed 24 Aug

Exits non-zero if any trace fails. Run before any analysis reaching the paper.
See docs/trace_provenance.md.
"""
from __future__ import annotations

import argparse
import glob
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

import pyarrow.parquet as pq  # noqa: E402

DROPPED_PARAMS = {"ped_phase_offset"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/traces")
    ap.add_argument("--pattern", default="*.parquet")
    ap.add_argument("--require-bt", action="store_true", default=True)
    ap.add_argument("--allow-no-bt", dest="require_bt", action="store_false",
                    help="skip the behaviour-tree check (pipeline traces only)")
    a = ap.parse_args()

    paths = sorted(glob.glob(str(pathlib.Path(a.dir) / a.pattern)))
    if not paths:
        # The input trajectories (data/traces/) are not part of the public
        # release. Fail loudly instead of writing an empty result over the
        # committed output.
        print(f"no trajectories match {pathlib.Path(a.dir) / a.pattern}; this script needs "
              "the unreleased data/traces/ files and cannot be re-run from the public "
              "release (see data/results/NOTES.md)", file=sys.stderr)
        return 2
    if not paths:
        print(f"no traces matched {a.dir}/{a.pattern}")
        return 1

    bad: list[tuple[str, str]] = []
    for p in paths:
        tbl = pq.read_table(p, columns=["bt_node_id"])
        meta = {}
        full = pq.read_metadata(p).metadata or {}
        for k, v in full.items():
            meta[k.decode()] = v.decode()

        if not meta.get("git_commit"):
            bad.append((p, "empty git_commit (pre-repository trace)"))
            continue
        if a.require_bt and tbl.column("bt_node_id").null_count == len(tbl):
            bad.append((p, "bt_node_id all null -- not produced by a behaviour tree"))
            continue
        try:
            params = json.loads(meta.get("scenario_params", "{}"))
        except json.JSONDecodeError:
            bad.append((p, "unparseable scenario_params"))
            continue
        stale = DROPPED_PARAMS & set(params)
        if stale:
            bad.append((p, f"uses dropped falsifier parameter(s): {sorted(stale)}"))

    print(f"checked {len(paths)} traces in {a.dir}")
    if bad:
        print(f"FAILED: {len(bad)} trace(s) are not fit to back a paper claim")
        for p, why in bad[:15]:
            print(f"  {pathlib.Path(p).name}: {why}")
        if len(bad) > 15:
            print(f"  ... and {len(bad) - 15} more")
        return 1
    print("PASSED: all traces carry a commit, a behaviour tree, and a current parameter set")
    return 0


if __name__ == "__main__":
    sys.exit(main())
