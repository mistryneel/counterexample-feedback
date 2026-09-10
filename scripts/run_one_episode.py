#!/usr/bin/env python3
"""Run exactly ONE episode in a fresh process, then exit.

Used directly by the across-process repeatability stage of the determinism
gate (3.5), which is the stage that matters most: campaigns restart, and a
bug that only appears across restarts would silently corrupt half the data
while every within-process check passed.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from dataclasses import asdict

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from carla_backend import CarlaBackend  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--params", required=True, help="scenario parameters as JSON")
    ap.add_argument("--episode-id", required=True)
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--tm-port", type=int, default=None)
    ap.add_argument("--result-json", required=True)
    ap.add_argument("--program", type=str, default=None)
    ap.add_argument("--no-reload", action="store_true",
                    help="disable world reload between episodes")
    args = ap.parse_args()

    params = json.loads(args.params)

    from config import load_config
    cfg = load_config("sim")
    if args.port:
        cfg["server"]["port"] = args.port
    if args.tm_port:
        # Each concurrent CARLA instance needs its OWN Traffic Manager rpc
        # port. Two instances sharing one TM port collide on bind.
        cfg["seeds"]["tm_port"] = args.tm_port
    if args.no_reload:
        cfg["world"]["reload_between_episodes"] = False

    with CarlaBackend(cfg=cfg) as be:
        if args.program:
            be.load_program(args.program)
        res = be.run_episode(params, episode_id=args.episode_id)

    pathlib.Path(args.result_json).write_text(
        json.dumps(asdict(res), indent=2, default=str)
    )
    print(f"{res.episode_id}  status={res.status}  ticks={res.n_ticks}  "
          f"wall={res.wall_clock_s:.2f}s  rtf={res.real_time_factor:.3f}")
    # Exit non-zero only if the episode produced NO usable trajectory.
    return 0 if res.usable else 1


if __name__ == "__main__":
    sys.exit(main())
