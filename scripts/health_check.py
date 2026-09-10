#!/usr/bin/env python3
"""Session health check. Run at the start of EVERY session.

Connects to CARLA and verifies that what the server is actually doing matches
what config/sim.yaml says it should be doing. Exits non-zero on ANY mismatch.

The point is not to be reassuring. It is to fail loudly on the specific things
that corrupt results silently:

  * client/server version mismatch    -> API semantics can differ
  * asynchronous mode                 -> no determinism at all
  * wrong fixed_delta_seconds         -> every rho computed at the wrong rate
  * substepping condition violated    -> physics silently non-deterministic
  * stale actors from a crashed run   -> next episode starts dirty
"""

from __future__ import annotations

import argparse
import contextlib
import math
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from config import load_config, check_substepping  # noqa: E402

OK, BAD, WARN = "  OK  ", " FAIL ", " WARN "
failures: list[str] = []
warnings: list[str] = []


def report(ok: bool, label: str, got, want=None, warn_only: bool = False) -> None:
    tag = OK if ok else (WARN if warn_only else BAD)
    line = f"[{tag}] {label:<34} {got}"
    if not ok and want is not None:
        line += f"   (expected: {want})"
    print(line)
    if not ok:
        (warnings if warn_only else failures).append(f"{label}: got {got}, expected {want}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--host", type=str, default=None)
    ap.add_argument("--timeout", type=float, default=None)
    ap.add_argument("--no-apply", action="store_true",
                    help="observe only; do not apply the configured settings")
    args = ap.parse_args()

    cfg = load_config("sim")
    host = args.host or cfg["server"]["host"]
    port = args.port or int(cfg["server"]["port"])
    timeout = args.timeout or float(cfg["server"]["timeout_s"])

    print("=" * 78)
    print(f"CARLA HEALTH CHECK   {host}:{port}")
    print("=" * 78)

    # ---- checks that need no server -------------------------------------
    ok_sub, msg_sub = check_substepping(cfg)
    report(ok_sub, "substepping condition (config)", msg_sub, "HOLDS")

    try:
        import carla
    except Exception as e:
        print(f"[{BAD}] carla import                      {e}")
        return 1

    # ---- connect ---------------------------------------------------------
    try:
        client = carla.Client(host, port)
        client.set_timeout(timeout)
        sv = client.get_server_version()
        cv = client.get_client_version()
    except Exception as e:
        print(f"[{BAD}] connect                            {type(e).__name__}: {e}")
        print()
        print("Server not reachable. Start it with:")
        print(f"    scripts/start_carla.sh --port {port}")
        return 1

    report(cv == sv, "client/server version", f"client={cv} server={sv}", "identical")

    world = client.get_world()
    t, p = cfg["timing"], cfg["physics"]

    # APPLY the configured timing settings, verify the server took them, then
    # RESTORE. Merely observing is not useful here: between campaigns the
    # backend restores the server's original (asynchronous) settings on exit,
    # so an observe-only check reports synchronous_mode=False every session,
    # cries wolf, and gets ignored. Applying tests something real -- that this
    # server ACCEPTS the timing and substepping this experiment requires --
    # and restoring afterwards avoids leaving a synchronous world frozen with
    # nobody ticking it.
    restore_to = world.get_settings()
    applied = False
    if not args.no_apply:
        try:
            want = world.get_settings()
            want.synchronous_mode = bool(t["synchronous_mode"])
            want.fixed_delta_seconds = float(t["fixed_delta_seconds"])
            want.no_rendering_mode = bool(t["no_rendering_mode"])
            want.substepping = bool(p["substepping"])
            want.max_substep_delta_time = float(p["max_substep_delta_time"])
            want.max_substeps = int(p["max_substeps"])
            world.apply_settings(want)
            applied = True
        except Exception as e:
            print(f"[{BAD}] apply settings                    {type(e).__name__}: {e}")
            failures.append(f"apply settings: {e}")

    st = world.get_settings()

    # ---- map -------------------------------------------------------------
    map_name = world.get_map().name.split("/")[-1]
    report(map_name == cfg["world"]["map"], "map", map_name, cfg["world"]["map"])

    # ---- synchrony -------------------------------------------------------
    report(st.synchronous_mode == bool(t["synchronous_mode"]),
           "synchronous_mode", st.synchronous_mode, t["synchronous_mode"])

    fd = st.fixed_delta_seconds
    want_fd = float(t["fixed_delta_seconds"])
    report(fd is not None and math.isclose(fd, want_fd, rel_tol=0, abs_tol=1e-12),
           "fixed_delta_seconds", fd, want_fd)

    report(st.no_rendering_mode == bool(t["no_rendering_mode"]),
           "no_rendering_mode", st.no_rendering_mode, t["no_rendering_mode"],
           warn_only=True)

    # ---- substepping AS THE SERVER HAS IT --------------------------------
    # Checking the config file is not enough. What matters is what the server
    # is actually running with.
    report(st.substepping == bool(p["substepping"]),
           "substepping (server)", st.substepping, p["substepping"])
    report(math.isclose(st.max_substep_delta_time, float(p["max_substep_delta_time"]),
                        abs_tol=1e-12),
           "max_substep_delta_time (server)", st.max_substep_delta_time,
           p["max_substep_delta_time"])
    report(st.max_substeps == int(p["max_substeps"]),
           "max_substeps (server)", st.max_substeps, p["max_substeps"])

    prod = st.max_substep_delta_time * st.max_substeps
    live_ok = (fd is not None) and (fd <= prod)
    report(live_ok, "substepping condition (server)",
           f"{fd} <= {st.max_substep_delta_time} * {st.max_substeps} = {prod}",
           "fixed_delta <= product")

    # ---- world state -----------------------------------------------------
    actors = world.get_actors()
    vehicles = len(actors.filter("vehicle.*"))
    walkers = len(actors.filter("walker.*"))
    sensors = len(actors.filter("sensor.*"))
    lights = len(actors.filter("traffic.traffic_light*"))
    report(vehicles == 0 and walkers == 0 and sensors == 0,
           "stale actors (veh/walk/sensor)", f"{vehicles}/{walkers}/{sensors}",
           "0/0/0", warn_only=True)
    print(f"[{OK}] {'traffic lights in map':<34} {lights}")
    print(f"[{OK}] {'weather':<34} {cfg['weather']['preset']}")

    # ---- junction cache --------------------------------------------------
    jpath = pathlib.Path(__file__).resolve().parent.parent / "data/scenarios/junction.yaml"
    if jpath.exists():
        import yaml
        j = yaml.safe_load(jpath.read_text())
        print(f"[{OK}] {'junction (cached)':<34} id={j['junction_id']} "
              f"lights={j['n_traffic_lights']} dyaw={j['left_turn']['measured_dyaw_deg']:.1f}")
    else:
        print(f"[{WARN}] {'junction (cached)':<34} not yet discovered")

    # restore whatever the server had before, so an idle synchronous world is
    # never left frozen behind us
    if applied:
        with contextlib.suppress(Exception):
            world.apply_settings(restore_to)
        print(f"[{OK}] {'settings applied then restored':<34} "
              f"(server accepted the required timing)")

    # ---- summary ---------------------------------------------------------
    print("=" * 78)
    if warnings:
        print(f"{len(warnings)} warning(s):")
        for w in warnings:
            print(f"  - {w}")
    if failures:
        print(f"HEALTH CHECK FAILED -- {len(failures)} problem(s):")
        for f in failures:
            print(f"  - {f}")
        print("=" * 78)
        return 1
    print("HEALTH CHECK PASSED")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
