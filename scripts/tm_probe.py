#!/usr/bin/env python3
"""Run ONE Traffic-Manager determinism probe in a fresh process.

Spawns N TM-controlled vehicles, records their positions for a fixed number
of ticks, writes them to .npy, exits.

Runs as a subprocess because the parent restarts the CARLA server between
probes, and a carla.Client that outlives its server aborts the process
(SIGABRT) from its background streaming thread -- dropping the Python
reference is not enough to stop that thread.
"""
from __future__ import annotations

import argparse
import contextlib
import math
import pathlib
import sys
import time

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
import carla  # noqa: E402
from config import load_config  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=2000)
    ap.add_argument("--seed", type=str, default="none",
                    help="integer seed, or 'none' to leave the TM unseeded")
    ap.add_argument("--n-veh", type=int, default=8)
    ap.add_argument("--ticks", type=int, default=150)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    cfg = load_config("sim")
    seed = None if a.seed == "none" else int(a.seed)

    client = carla.Client(cfg["server"]["host"], a.port)
    client.set_timeout(float(cfg["server"]["timeout_s"]))
    world = client.get_world()
    original = world.get_settings()
    spawned: list[int] = []
    try:
        t, p = cfg["timing"], cfg["physics"]
        st = world.get_settings()
        st.synchronous_mode = True
        st.fixed_delta_seconds = float(t["fixed_delta_seconds"])
        st.no_rendering_mode = True
        st.substepping = True
        st.max_substep_delta_time = float(p["max_substep_delta_time"])
        st.max_substeps = int(p["max_substeps"])
        world.apply_settings(st)

        # The Traffic Manager opens a CLIENT-SIDE rpc server on this port.
        # After a probe exits the socket sits in TIME_WAIT, so the next probe
        # gets "failed to create because of bind error". Retry on the SAME
        # port rather than falling back to a different one: every probe in a
        # compared pair must use identical settings, or the port becomes an
        # uncontrolled variable in a determinism test.
        tm_port = int(cfg["seeds"]["tm_port"])
        tm = None
        deadline = time.time() + 120.0
        while True:
            try:
                tm = client.get_trafficmanager(tm_port)
                break
            except RuntimeError as e:
                if "bind" not in str(e).lower() or time.time() > deadline:
                    raise
                time.sleep(3.0)
        print(f"  (traffic manager on port {tm_port})", file=sys.stderr)
        tm.set_synchronous_mode(True)
        tm.set_hybrid_physics_mode(False)
        if seed is not None:
            tm.set_random_device_seed(seed)

        bp = world.get_blueprint_library().filter("vehicle.*")[0]
        vehicles = []
        for sp in world.get_map().get_spawn_points()[: a.n_veh]:
            v = world.try_spawn_actor(bp, sp)
            if v is not None:
                spawned.append(v.id)
                v.set_autopilot(True, tm.get_port())
                vehicles.append(v)
        # Sort by spawn order, not by actor id: ids shift between runs.
        order = {vid: i for i, vid in enumerate(spawned)}
        vehicles.sort(key=lambda v: order[v.id])

        for _ in range(10):
            world.tick()
        out = np.zeros((a.ticks, len(vehicles), 2))
        for i in range(a.ticks):
            world.tick()
            for k, v in enumerate(vehicles):
                L = v.get_transform().location
                out[i, k] = (L.x, L.y)
        np.save(a.out, out)
        print(f"probe ok: seed={a.seed} vehicles={len(vehicles)} "
              f"ticks={a.ticks} -> {a.out}")
        return 0
    finally:
        with contextlib.suppress(Exception):
            if spawned:
                client.apply_batch_sync(
                    [carla.command.DestroyActor(v) for v in spawned], True)
        with contextlib.suppress(Exception):
            world.apply_settings(original)


if __name__ == "__main__":
    sys.exit(main())
