#!/usr/bin/env python3
"""Measure the map from commanded control to longitudinal acceleration.

C5 is computed from COMMANDED control rather than measured acceleration
(docs/c5_decision.md). To keep rho_5 readable in m/s^2 -- which matters
because rho appears verbatim in the certificate shown to the LLM -- the
command must be converted to an acceleration by a MEASURED map, not a guessed
constant.

Samples steady-state acceleration at a range of throttle and brake commands,
restricted to speeds above the CARLA low-speed braking artifact regime.
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
import carla  # noqa: E402
from config import load_config  # noqa: E402

ARTIFACT_SPEED = 5.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=2000)
    ap.add_argument("--out", default="data/results/control_map.json")
    a = ap.parse_args()

    cfg = load_config("sim")
    client = carla.Client(cfg["server"]["host"], a.port)
    client.set_timeout(60.0)
    world = client.get_world()
    orig = world.get_settings()
    spawned = []
    try:
        st = world.get_settings()
        st.synchronous_mode = True
        st.fixed_delta_seconds = 0.05
        st.no_rendering_mode = True
        st.substepping = True
        st.max_substep_delta_time = 0.01
        st.max_substeps = 10
        world.apply_settings(st)

        bp = world.get_blueprint_library().find(cfg["scenario"]["ego_blueprint"])
        sp = world.get_map().get_spawn_points()[0]
        v = None
        for _ in range(4):
            v = world.try_spawn_actor(bp, sp)
            if v:
                break
            for _ in range(5):
                world.tick()
        if v is None:
            print("spawn failed")
            return 1
        spawned.append(v)

        spawn_tf = sp

        def settle_to(target: float, tol: float = 0.15, timeout: int = 400) -> float:
            """Converge to `target` m/s and hold. Works from any starting speed.

            Every measurement starts from the MIDDLE of the speed band, so a
            decelerating command and an accelerating command both have room to
            move before leaving it. Starting at an edge -- which the first
            version did -- opens the window outside the band and measures
            nothing.
            """
            for _ in range(timeout):
                s_ = v.get_velocity()
                spd = math.hypot(s_.x, s_.y)
                if abs(spd - target) <= tol:
                    return spd
                if spd < target:
                    v.apply_control(carla.VehicleControl(throttle=0.6, brake=0.0))
                else:
                    v.apply_control(carla.VehicleControl(throttle=0.0, brake=0.2))
                world.tick()
            return math.hypot(v.get_velocity().x, v.get_velocity().y)

        def reset_pose() -> None:
            """Return the ego to the spawn pose at rest.

            Repeated accelerate/brake cycles walk the car down the road and
            eventually off it; a measurement taken on grass is not a
            measurement of the drivetrain.
            """
            v.set_target_velocity(carla.Vector3D(0, 0, 0))
            v.set_target_angular_velocity(carla.Vector3D(0, 0, 0))
            v.set_transform(spawn_tf)
            v.apply_control(carla.VehicleControl(throttle=0.0, brake=1.0))
            for _ in range(20):
                world.tick()

        def measure(throttle: float, brake: float,
                    v_lo: float = 5.5, v_hi: float = 9.5) -> float | None:
            """Least-squares dv/dt while speed stays inside [v_lo, v_hi].

            Least squares, not finite differencing: CARLA's accelerometer has
            a measured noise floor of sigma ~= 1.36 m/s^2 at 20 Hz, so a slope
            fit over many samples is far more stable than any per-tick
            difference.
            """
            reset_pose()
            settle_to(7.5)
            speeds = []
            for _ in range(300):
                s_ = v.get_velocity()
                spd = math.hypot(s_.x, s_.y)
                if spd < v_lo or spd > v_hi:
                    break
                speeds.append(spd)
                v.apply_control(carla.VehicleControl(throttle=throttle, brake=brake))
                world.tick()
            if len(speeds) < 6:
                return None
            t = np.arange(len(speeds)) * 0.05
            return float(np.polyfit(t, np.asarray(speeds), 1)[0])

        rows = []
        print("=== THROTTLE (measured over 5.5 -> 9.5 m/s, from 7.5 m/s) ===")
        print(f"{'throttle':>9} {'a_mps2':>9}")
        for th in [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.75]:
            acc = measure(th, 0.0)
            print(f"{th:>9.2f} {('n/a' if acc is None else f'{acc:+9.3f}')}")
            if acc is not None:
                rows.append({"throttle": th, "brake": 0.0, "a_mps2": acc})

        print("\n=== BRAKE (measured 9.5 -> 5.5 m/s, entirely above the artifact regime) ===")
        print(f"{'brake':>9} {'a_mps2':>9}")
        for br in [0.05, 0.1, 0.15, 0.2, 0.3, 0.4, 0.5]:
            acc = measure(0.0, br)
            print(f"{br:>9.2f} {('n/a' if acc is None else f'{acc:+9.3f}')}")
            if acc is not None:
                rows.append({"throttle": 0.0, "brake": br, "a_mps2": acc})

        # Fit a_cmd = k_t * throttle - k_b * brake + a0
        th_rows = [r for r in rows if r["brake"] == 0.0]
        br_rows = [r for r in rows if r["throttle"] == 0.0 and r["brake"] > 0]
        a0 = next((r["a_mps2"] for r in rows
                   if r["throttle"] == 0.0 and r["brake"] == 0.0), 0.0)
        k_t = float(np.polyfit([r["throttle"] for r in th_rows],
                               [r["a_mps2"] - a0 for r in th_rows], 1)[0]) if len(th_rows) > 1 else 0.0
        k_b = float(-np.polyfit([r["brake"] for r in br_rows],
                                [r["a_mps2"] - a0 for r in br_rows], 1)[0]) if len(br_rows) > 1 else 0.0

        print("\n=== FITTED LINEAR MAP ===")
        print(f"  a_cmd(throttle, brake) = {k_t:.4f}*throttle - {k_b:.4f}*brake + ({a0:.4f})")
        print(f"    k_throttle = {k_t:+.4f} m/s^2 per unit throttle")
        print(f"    k_brake    = {k_b:+.4f} m/s^2 per unit brake")
        print(f"    a0 (coast) = {a0:+.4f} m/s^2   (drag + rolling resistance)")
        if not rows:
            print("  NO MEASUREMENTS SUCCEEDED -- aborting rather than emitting a fitted zero")
            return 1
        resid = [r["a_mps2"] - (k_t*r["throttle"] - k_b*r["brake"] + a0) for r in rows]
        print(f"    max |residual| = {max(abs(x) for x in resid):.4f} m/s^2")
        print(f"    RMS  residual  = {float(np.sqrt(np.mean(np.square(resid)))):.4f} m/s^2")

        print("\n=== implied C5 headroom ===")
        slew = 0.10
        print(f"  actuator slew limit    = {slew} per tick")
        print(f"  -> max |d(a_cmd)|/tick = {max(k_t,k_b)*slew:.4f} m/s^2")
        print(f"  -> max |jerk_cmd|      = {max(k_t,k_b)*slew/0.05:.3f} m/s^3")
        print(f"  j_comfort bound        = 3.0 m/s^3")

        pathlib.Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(a.out).write_text(json.dumps({
            "measurements": rows,
            "k_throttle_mps2": k_t, "k_brake_mps2": k_b, "a_coast_mps2": a0,
            "speed_band_mps": [5.5, 9.5],
            "artifact_speed_mps": ARTIFACT_SPEED,
            "max_abs_residual_mps2": max(abs(x) for x in resid),
            "method": "least-squares slope of speed vs time, entirely above the artifact regime",
        }, indent=2))
        print(f"\nwrote {a.out}")
        return 0
    finally:
        for x in spawned:
            try:
                x.destroy()
            except Exception:
                pass
        world.apply_settings(orig)


if __name__ == "__main__":
    sys.exit(main())
