#!/usr/bin/env python3
"""PHASE 3 — DETERMINISM GATE.

Run one full episode end to end and check STL robustness on the logged
trajectory BEFORE building anything else. A determinism or clock issue would
quietly corrupt every rho value; catching it on episode one is far cheaper
than after thirty.

Stages, run in order:
  3.1  clock integrity
  3.2  physics substepping
  3.3  rho sanity, hand-checked against the log
  3.4  within-process repeatability   (5 episodes, one process)
  3.5  across-process repeatability   (5 episodes, separate processes)
  3.6  seed sensitivity
  3.7  verdict

ANY failure in 3.1-3.6 is a hard stop. Nothing downstream is trustworthy.

    scripts/determinism_gate.py [--port N] [--stages 3.1,3.2,...] [--n 5]
"""
from __future__ import annotations

import argparse
import contextlib
import gc
import json
import math
import pathlib
import subprocess
import sys
import time
from dataclasses import asdict

import numpy as np
import pyarrow as pa

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

import trace_schema as ts          # noqa: E402
import stl                          # noqa: E402
from config import load_config, check_substepping   # noqa: E402

# The scenario used for every determinism stage. Fixed on purpose: the gate
# measures the simulator, not the search space.
GATE_PARAMS = {"n_oncoming": 2, "v_oncoming": 11.0,
               "headway": 3.0, "ped_phase_offset": 0.0}

REPORT: dict = {"stages": {}, "params": GATE_PARAMS}

# Columns that are ABSOLUTE SERVER BOOKKEEPING, not physics. On a persistent
# server (reload_between_episodes: false) these legitimately advance from one
# episode to the next, so requiring them to match across runs would be testing
# the wrong thing. They are still reported, just not gated on.
#   frame, sim_elapsed_s : monotonic server counters; 3.1 checks their INTERNAL
#                          consistency, which is the property that matters
#   actor_id             : CARLA reassigns ids on every spawn
# Everything else -- positions, velocities, accelerations, controls, t_s,
# delta_s, phase, tl_state -- IS physics and must reproduce.
BOOKKEEPING_COLUMNS = {"frame", "sim_elapsed_s", "actor_id"}


def hdr(title: str) -> None:
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)


def verdict(stage: str, ok: bool, detail: dict) -> bool:
    REPORT["stages"][stage] = {"pass": bool(ok), **detail}
    print(f"\n  >>> {stage}: {'PASS' if ok else 'FAIL'}")
    return ok


# ==========================================================================
# Trace comparison
# ==========================================================================

def compare_traces(paths: list[pathlib.Path]) -> dict:
    """Element-wise comparison of N traces. Returns max abs deviation per field.

    Traces of differing LENGTH are themselves a determinism failure and are
    reported as such rather than being truncated to a common prefix -- a
    silent truncation would hide exactly the bug we are looking for.
    """
    dfs = [stl.load_trace(p)[0] for p in paths]
    lengths = [len(d) for d in dfs]
    out: dict = {"n_traces": len(dfs), "lengths": lengths,
                 "length_identical": len(set(lengths)) == 1,
                 "max_abs_dev": {}, "bookkeeping_dev": {},
                 "worst_field": None, "worst_dev": 0.0}
    if not out["length_identical"]:
        return out

    ref = dfs[0]
    # String columns come in two shapes: scalar-per-row and list-per-row.
    # Treating the list ones as scalars raises "truth value of an array with
    # more than one element is ambiguous".
    # Every string-valued scalar column must be listed here. A new one that is
    # not listed falls through to the numeric branch and raises
    # "could not convert string to float" -- which is how bt_tick_path was
    # caught. Derived from the schema rather than hand-maintained.
    STR_SCALAR = tuple(
        f.name for f in ts.TRAJECTORY_SCHEMA
        if pa.types.is_string(f.type))
    STR_LIST = ("actor_type", "actor_role")

    for col in ts.COLUMNS:
        if col in STR_SCALAR:
            mism = 0
            for d in dfs[1:]:
                for x, y in zip(ref[col].tolist(), d[col].tolist()):
                    xn = x is None or (isinstance(x, float) and math.isnan(x))
                    yn = y is None or (isinstance(y, float) and math.isnan(y))
                    if xn and yn:
                        continue
                    if xn != yn or x != y:
                        mism += 1
            out["max_abs_dev"][col] = float(mism)
            continue

        if col in STR_LIST:
            mism = 0
            for d in dfs[1:]:
                for ra, rb in zip(ref[col], d[col]):
                    la, lb = list(ra), list(rb)
                    if len(la) != len(lb):
                        mism += max(len(la), len(lb))
                        continue
                    mism += sum(1 for x, y in zip(la, lb) if x != y)
            out["max_abs_dev"][col] = float(mism)
            continue

        worst = 0.0
        for d in dfs[1:]:
            if col in ts.LIST_COLUMNS:
                for ra, rb in zip(ref[col], d[col]):
                    if len(ra) != len(rb):
                        worst = math.inf
                        break
                    if len(ra):
                        worst = max(worst, float(np.nanmax(
                            np.abs(np.asarray(ra, float) - np.asarray(rb, float))
                        )) if len(ra) else 0.0)
                if worst == math.inf:
                    break
            else:
                a = np.asarray(ref[col].tolist(), dtype=float)
                b = np.asarray(d[col].tolist(), dtype=float)
                both_nan = np.isnan(a) & np.isnan(b)
                diff = np.abs(a - b)
                diff[both_nan] = 0.0
                if np.isnan(diff).any():
                    worst = math.inf
                else:
                    worst = max(worst, float(diff.max()) if diff.size else 0.0)
        if col in BOOKKEEPING_COLUMNS:
            out["bookkeeping_dev"][col] = worst
        else:
            out["max_abs_dev"][col] = worst
            if worst > out["worst_dev"]:
                out["worst_dev"], out["worst_field"] = worst, col
    return out


def _print_compare(cmp_, rs) -> None:
    print(f"\n  trace lengths: {cmp_['lengths']}  identical={cmp_['length_identical']}")
    print(f"  PHYSICS fields -- worst: {cmp_['worst_field']}  "
          f"max abs deviation={cmp_['worst_dev']:.3e}")
    for k, v in sorted(cmp_["max_abs_dev"].items(), key=lambda kv: -kv[1])[:6]:
        print(f"    {k:<26} {v:.6e}")
    print("  BOOKKEEPING fields (absolute server counters -- expected to differ,")
    print("  reported but not gated on):")
    for k, v in sorted(cmp_["bookkeeping_dev"].items(), key=lambda kv: -kv[1]):
        print(f"    {k:<26} {v:.6e}")
    print(f"\n  rho values : {[f'{x:+.9f}' for x in rs['rho_values']]}")
    print(f"  rho spread : {rs['rho_spread']:.3e}")


def rho_spread(paths: list[pathlib.Path], contracts, junction) -> dict:
    rhos, contribs = [], []
    for p in paths:
        r = stl.compute_rho(p, contracts, junction)
        rhos.append(r.rho)
        contribs.append({k: v.rho for k, v in r.per_contract.items()})
    arr = np.asarray(rhos, float)
    return {"rho_values": [float(x) for x in rhos],
            "rho_min": float(arr.min()), "rho_max": float(arr.max()),
            "rho_spread": float(arr.max() - arr.min()),
            "per_contract": contribs}


# ==========================================================================
# 3.1 clock integrity
# ==========================================================================

def stage_3_1(res, cfg) -> bool:
    hdr("3.1  CLOCK INTEGRITY")
    df, meta = stl.load_trace(res.trace_path)
    dt = float(cfg["timing"]["fixed_delta_seconds"])
    horizon = float(cfg["timing"]["episode_horizon_s"])

    delta = df["delta_s"].to_numpy(float)
    # CARLA stores delta_seconds as a 32-bit float, so the value it reports is
    # float32(0.05) = 0.05000000074505806, NOT the float64 literal 0.05. The
    # correct exactness test is against float32(dt); testing against the
    # float64 literal fails by 7.45e-10 on a perfectly healthy server.
    dt32 = float(np.float32(dt))
    delta_dev32 = float(np.max(np.abs(delta - dt32))) if len(delta) else math.inf
    delta_dev64 = float(np.max(np.abs(delta - dt))) if len(delta) else math.inf
    delta_ok = delta_dev32 == 0.0
    print(f"  server-reported delta_s: min={delta.min():.17g} max={delta.max():.17g}")
    print(f"  float32({dt}) = {dt32:.17g}   float64 literal = {dt:.17g}")
    print(f"  max |delta_s - float32({dt})| = {delta_dev32:.3e}   -> "
          f"{'BIT-EXACT' if delta_ok else 'NOT EXACT'}")
    print(f"  (max |delta_s - float64 {dt}| = {delta_dev64:.3e}, i.e. CARLA's")
    print(f"   delta is float32; this is representation, not clock drift)")

    tdiff = np.diff(df["t_s"].to_numpy(float))
    tdev = float(np.max(np.abs(tdiff - dt32))) if len(tdiff) else math.inf
    print(f"  consecutive t_s spacing: max |dt - float32({dt})| = {tdev:.3e}")

    frames = df["frame"].to_numpy(np.int64)
    fdiff = np.diff(frames)
    mono = bool((fdiff > 0).all()) if len(fdiff) else False
    gaps = int((fdiff != 1).sum()) if len(fdiff) else -1
    dups = int(len(frames) - len(np.unique(frames)))
    print(f"  frames: strictly monotonic={mono}  non-unit steps={gaps}  duplicates={dups}")
    if gaps:
        bad = np.where(fdiff != 1)[0][:5]
        print(f"    first offending indices: {bad.tolist()} "
              f"steps={fdiff[bad].tolist()}")

    expected = int(round(horizon / dt))
    print(f"  ticks logged={len(df)}  expected(full horizon)={expected}  "
          f"status={res.status}")
    # A short trace is only legitimate if the episode ENDED early for a
    # declared reason (route complete / collision), never silently.
    len_ok = (len(df) == expected) or res.status in (
        ts.STATUS_OK, ts.STATUS_COLLISION)

    print(f"  wall-clock={res.wall_clock_s:.3f}s  "
          f"simulated={len(df)*dt:.3f}s  RTF={res.real_time_factor:.4f} "
          f"(simulated seconds per wall-clock second)")
    REPORT["real_time_factor"] = res.real_time_factor
    REPORT["wall_clock_s"] = res.wall_clock_s
    REPORT["n_ticks"] = len(df)

    ok = delta_ok and mono and gaps == 0 and dups == 0 and len_ok and tdev < 1e-9
    return verdict("3.1", ok, {
        "delta_s_max_dev_vs_float32": delta_dev32,
        "delta_s_max_dev_vs_float64": delta_dev64,
        "t_s_spacing_max_dev": tdev,
        "frames_monotonic": mono, "frame_gaps": gaps, "frame_duplicates": dups,
        "n_ticks": len(df), "expected_ticks": expected,
        "episode_status": res.status,
        "wall_clock_s": res.wall_clock_s,
        "real_time_factor": res.real_time_factor,
    })


# ==========================================================================
# 3.2 physics substepping
# ==========================================================================

def stage_3_2(cfg, port) -> bool:
    hdr("3.2  PHYSICS SUBSTEPPING")
    import carla
    ok_cfg, msg = check_substepping(cfg)
    print(f"  config: {msg}")

    c = carla.Client(cfg["server"]["host"], port)
    c.set_timeout(float(cfg["server"]["timeout_s"]))
    st = c.get_world().get_settings()
    fd = st.fixed_delta_seconds
    prod = st.max_substep_delta_time * st.max_substeps
    print(f"  server: substepping={st.substepping}  "
          f"max_substep_delta_time={st.max_substep_delta_time}  "
          f"max_substeps={st.max_substeps}")
    print(f"  server: fixed_delta_seconds={fd}")
    print(f"  condition: {fd} <= {st.max_substep_delta_time} * "
          f"{st.max_substeps} = {prod}")
    live_ok = fd is not None and fd <= prod
    print(f"  -> {'HOLDS' if live_ok else 'VIOLATED'}")
    if st.max_substep_delta_time >= 0.01666:
        print("  WARNING: max_substep_delta_time is at or above the documented "
              "ceiling of 0.01666")
    print("\n  Note: CARLA does NOT raise when this condition is violated.")
    print("  Physics silently becomes non-deterministic and every rho is wrong.")

    return verdict("3.2", ok_cfg and live_ok, {
        "config_msg": msg, "server_fixed_delta_seconds": fd,
        "server_max_substep_delta_time": st.max_substep_delta_time,
        "server_max_substeps": st.max_substeps,
        "product": prod, "condition_holds": live_ok,
    })


# ==========================================================================
# 3.3 rho sanity, hand-checked
# ==========================================================================

def stage_3_3(res, contracts, junction) -> bool:
    hdr("3.3  RHO SANITY  (hand-checked against the log)")
    df, _ = stl.load_trace(res.trace_path)
    r = stl.compute_rho(df, contracts, junction)
    print(f"  {r.summary()}\n")

    checks: list[tuple[str, bool]] = []

    # ---- C1: recompute the argmin clearance from raw positions ----------
    c1 = r.per_contract.get("C1")
    if c1 is not None and c1.argmin_index is not None:
        i = c1.argmin_index
        row = df.iloc[i]
        print(f"  --- C1 at argmin row {i} (t={row['t_s']:.3f}s, "
              f"frame={row['frame']}) ---")
        print(f"    ego   pos=({row['ego_x_m']:+.4f}, {row['ego_y_m']:+.4f}) "
              f"yaw={row['ego_yaw_deg']:+.2f} "
              f"half-extents=({row['ego_extent_x_m']:.3f}, "
              f"{row['ego_extent_y_m']:.3f}) speed={row['ego_speed_mps']:.3f} m/s")
        ego_poly = stl.obb_corners(row["ego_x_m"], row["ego_y_m"],
                                   row["ego_yaw_deg"],
                                   row["ego_extent_x_m"], row["ego_extent_y_m"])
        best, best_k = math.inf, None
        for k in range(len(row["actor_id"])):
            poly = stl.obb_corners(row["actor_x_m"][k], row["actor_y_m"][k],
                                   row["actor_yaw_deg"][k],
                                   row["actor_extent_x_m"][k],
                                   row["actor_extent_y_m"][k])
            d = stl.obb_clearance(ego_poly, poly)
            print(f"    actor id={row['actor_id'][k]} role={row['actor_role'][k]:<10} "
                  f"pos=({row['actor_x_m'][k]:+.4f}, {row['actor_y_m'][k]:+.4f}) "
                  f"yaw={row['actor_yaw_deg'][k]:+.2f} "
                  f"speed={row['actor_speed_mps'][k]:.3f} m/s  clearance={d:+.6f} m")
            if d < best:
                best, best_k = d, k
        # centre-to-centre distance is the crude cross-check a human can do
        if best_k is not None:
            cc = math.hypot(row["ego_x_m"] - row["actor_x_m"][best_k],
                            row["ego_y_m"] - row["actor_y_m"][best_k])
            sum_half = (math.hypot(row["ego_extent_x_m"], row["ego_extent_y_m"])
                        + math.hypot(row["actor_extent_x_m"][best_k],
                                     row["actor_extent_y_m"][best_k]))
            print(f"    centre-to-centre={cc:.4f} m; sum of bounding radii="
                  f"{sum_half:.4f} m")
            print(f"    sanity: box clearance ({best:+.4f}) must lie between "
                  f"{cc - sum_half:+.4f} (radii bound) and {cc:+.4f} "
                  f"(centre distance)")
            band_ok = (cc - sum_half - 1e-6) <= best <= (cc + 1e-6)
            checks.append(("C1 clearance within radii/centre band", band_ok))
        agree = abs(best - c1.rho) < 1e-9
        print(f"    recomputed min clearance={best:+.9f}  reported rho_1="
              f"{c1.rho:+.9f}  agree={agree}")
        checks.append(("C1 rho == independent recomputation", agree))

    # ---- C2: recompute TTC from raw positions ---------------------------
    c2 = r.per_contract.get("C2")
    if c2 is not None and not c2.vacuous and c2.argmin_index is not None:
        i = c2.argmin_index
        row = df.iloc[i]
        cz = junction["junction_center"]
        tau = float(contracts["C2_yield"]["tau_yield_s"])
        print(f"\n  --- C2 at argmin row {i} (t={row['t_s']:.3f}s) ---")
        d_ego = math.hypot(row["ego_x_m"] - cz["x"], row["ego_y_m"] - cz["y"])
        print(f"    ego distance to conflict-zone centre = {d_ego:.4f} m "
              f"(radius {contracts['C2_yield']['conflict_zone_radius_m']} "
              f"-> ego IS in zone)")
        best_ttc = float(contracts["C2_yield"]["ttc_cap_s"])
        for k in range(len(row["actor_id"])):
            if row["actor_role"][k] != "oncoming":
                continue
            sp = float(row["actor_speed_mps"][k])
            d = math.hypot(row["actor_x_m"][k] - cz["x"],
                           row["actor_y_m"][k] - cz["y"])
            t_ = d / sp if sp >= contracts["C2_yield"]["min_speed_for_ttc_mps"] else math.inf
            print(f"    oncoming id={row['actor_id'][k]} dist_to_CZ={d:.4f} m "
                  f"speed={sp:.4f} m/s  ttc={t_:.4f} s")
            best_ttc = min(best_ttc, t_)
        hand = best_ttc - tau
        agree = abs(hand - c2.rho) < 1e-9
        print(f"    hand: rho_2 = ttc - tau = {best_ttc:.6f} - {tau} = "
              f"{hand:+.6f}   reported={c2.rho:+.6f}  agree={agree}")
        checks.append(("C2 rho == hand-computed ttc - tau", agree))
    elif c2 is not None and c2.vacuous:
        print(f"\n  --- C2 VACUOUS: {c2.detail.get('reason')} ---")
        print("    The ego never entered the conflict zone. rho_2 reports a "
              "sentinel and is excluded from the argmin.")
        print("    NOTE: this means C2 exercised nothing. It is not evidence "
              "that C2 works.")
        checks.append(("C2 exercised (non-vacuous)", False))

    # ---- rtamt independent cross-check ----------------------------------
    print("\n  --- independent cross-check via rtamt ---")
    tarr = df["t_s"].to_numpy(float)
    for name, c in r.per_contract.items():
        if c.vacuous:
            print(f"    {name}: skipped (vacuous)")
            continue
        x = stl.rtamt_crosscheck(c.signal, tarr)
        if math.isnan(x):
            # Fewer than two applicable timesteps, so rtamt has nothing to
            # integrate over. NOT a disagreement and NOT agreement -- the
            # cross-check simply did not run, and saying so is the only
            # honest option. Recorded, not silently passed.
            print(f"    {name}: SKIPPED (fewer than 2 applicable timesteps; "
                  f"ours={c.rho:+.9f}, not independently cross-checked)")
            continue
        ag = abs(x - c.rho) < 1e-9
        print(f"    {name}: ours={c.rho:+.9f}  rtamt={x:+.9f}  agree={ag}")
        checks.append((f"{name} rtamt cross-check", ag))

    # ---- physical plausibility of the numbers ---------------------------
    print("\n  --- physical plausibility ---")
    sp = df["ego_speed_mps"].to_numpy(float)
    al = df["ego_accel_long_mps2"].to_numpy(float)
    print(f"    ego speed: min={sp.min():.3f} max={sp.max():.3f} m/s")
    print(f"    ego long. accel: min={al.min():+.3f} max={al.max():+.3f} m/s^2")
    sane_speed = 0.0 <= sp.min() and sp.max() < 30.0
    print(f"    speed in [0, 30) m/s: {sane_speed}")
    checks.append(("ego speed physically plausible", sane_speed))

    # CARLA 0.9.16 has a measured low-speed braking artifact: below ~5 m/s a
    # braking vehicle decelerates at ~-27 m/s^2 regardless of brake command,
    # and reducing max_brake_torque 8x only softens it to -17.7. It is a
    # property of the simulator, not of our code, so the gate REPORTS it and
    # tests our correctness above the artifact regime. Failing the gate on a
    # documented simulator characteristic would be measuring the wrong thing.
    hi = np.abs(al[sp >= ARTIFACT_SPEED_MPS])
    lo = np.abs(al[sp < ARTIFACT_SPEED_MPS])
    hi_max = float(hi.max()) if hi.size else float("nan")
    lo_max = float(lo.max()) if lo.size else float("nan")
    print(f"    |accel| above {ARTIFACT_SPEED_MPS} m/s : max={hi_max:.3f} m/s^2  "
          f"({hi.size} ticks)")
    print(f"    |accel| below {ARTIFACT_SPEED_MPS} m/s : max={lo_max:.3f} m/s^2  "
          f"({lo.size} ticks)  <- CARLA low-speed artifact regime")
    sane_accel = (not hi.size) or hi_max < 12.0
    print(f"    |accel| < 12 m/s^2 in the NORMAL regime: {sane_accel}")
    checks.append(("ego acceleration plausible above the artifact regime",
                   sane_accel))
    REPORT["braking_artifact"] = {
        "artifact_speed_threshold_mps": ARTIFACT_SPEED_MPS,
        "max_abs_accel_above_threshold": hi_max,
        "max_abs_accel_below_threshold": lo_max,
        "ticks_above": int(hi.size), "ticks_below": int(lo.size),
        "note": "CARLA 0.9.16 low-speed braking artifact; see determinism_report.md",
    }

    print()
    for label, ok_ in checks:
        print(f"    [{'OK' if ok_ else 'FAIL'}] {label}")
    all_ok = all(o for _, o in checks) and len(checks) > 0
    return verdict("3.3", all_ok, {
        "rho": r.rho, "contract": r.contract, "t_s": r.t_s,
        "argmin_index": r.argmin_index,
        "per_contract": {k: {"rho": v.rho, "vacuous": v.vacuous,
                             "t_s": v.t_s, "detail": v.detail}
                         for k, v in r.per_contract.items()},
        "checks": {label: ok_ for label, ok_ in checks},
    })


# ==========================================================================
# 3.4 within-process repeatability
# ==========================================================================

def stage_3_4(backend, n, contracts, junction) -> bool:
    hdr(f"3.4  WITHIN-PROCESS REPEATABILITY  ({n} episodes, one process)")
    paths, rtfs = [], []
    for i in range(n):
        res = backend.run_episode(GATE_PARAMS, episode_id=f"det_wp_{i}")
        print(f"  run {i}: status={res.status} ticks={res.n_ticks} "
              f"wall={res.wall_clock_s:.2f}s rtf={res.real_time_factor:.3f}")
        if not res.usable:
            print(f"    ERROR: {(res.error or '')[:400]}")
            return verdict("3.4", False, {"error": "episode not usable",
                                          "run": i, "status": res.status})
        paths.append(pathlib.Path(res.trace_path))
        rtfs.append(res.real_time_factor)

    cmp_ = compare_traces(paths)
    rs = rho_spread(paths, contracts, junction)
    _print_compare(cmp_, rs)
    ok = (cmp_["length_identical"] and cmp_["worst_dev"] <= TOL_FIELD
          and rs["rho_spread"] <= TOL_RHO)
    REPORT["rtf_within"] = rtfs
    return verdict("3.4", ok, {"compare": cmp_, "rho": rs,
                               "mean_rtf": float(np.mean(rtfs))})


# ==========================================================================
# 3.5 across-process repeatability
# ==========================================================================
# This matters MORE than 3.4: campaigns restart, and a bug that only appears
# across restarts would silently corrupt half the data while every
# within-process check passed.
# ==========================================================================

def stage_3_5(n, port, contracts, junction, program=None) -> bool:
    hdr(f"3.5  ACROSS-PROCESS REPEATABILITY  ({n} separate process launches)")
    paths, results = [], []
    for i in range(n):
        eid = f"det_xp_{i}"
        rj = REPO / "data" / "traces" / f"{eid}.result.json"
        cmd = [str(REPO / ".venv/bin/python"),
               str(REPO / "scripts/run_one_episode.py"),
               "--params", json.dumps(GATE_PARAMS),
               "--episode-id", eid, "--port", str(port),
               "--result-json", str(rj)]
        if program:
            cmd += ["--program", str(program)]
        t0 = time.perf_counter()
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        wall = time.perf_counter() - t0
        print(f"  launch {i}: exit={proc.returncode} "
              f"process_wall={wall:.2f}s  {proc.stdout.strip()[:110]}")
        if proc.returncode != 0:
            print(f"    STDERR: {proc.stderr[-600:]}")
            return verdict("3.5", False, {"error": "subprocess failed",
                                          "launch": i,
                                          "stderr": proc.stderr[-2000:]})
        results.append(json.loads(rj.read_text()))
        paths.append(REPO / "data" / "traces" / f"{eid}.parquet")

    cmp_ = compare_traces(paths)
    rs = rho_spread(paths, contracts, junction)
    _print_compare(cmp_, rs)
    ok = (cmp_["length_identical"] and cmp_["worst_dev"] <= TOL_FIELD
          and rs["rho_spread"] <= TOL_RHO)
    REPORT["rtf_across"] = [r["real_time_factor"] for r in results]
    return verdict("3.5", ok, {"compare": cmp_, "rho": rs})


# ==========================================================================
# 3.6 seed sensitivity
# ==========================================================================

def stage_3_6(port, cfg) -> bool:
    """Delegate to scripts/seed_sensitivity.py.

    Must be a separate PROGRAM, not a function: 3.6 restarts the CARLA server,
    and any process that has ever held a carla.Client aborts (SIGABRT) from
    libcarla's background thread when its server disappears. Dropping the
    Python reference does not stop that thread. The gate process has already
    run a baseline episode by this point, so it can never safely restart the
    server itself.
    """
    hdr("3.6  SEED SENSITIVITY")
    print("  Evidence that seeding controls what it is believed to control.")
    print()
    print("  The Traffic Manager is tested ACROSS SERVER RESTARTS. Within a")
    print("  single process the test is confounded: reload_world() is unusable")
    print("  here (it segfaults CARLA 0.9.16), so a second probe would inherit")
    print("  world state from the first. Restarting is also the case that")
    print("  actually matters -- campaigns restart.")
    print()

    out = REPO / "data" / "results" / "seed_sensitivity.json"
    r = subprocess.run(
        [str(REPO / ".venv/bin/python"), "-u",
         str(REPO / "scripts/seed_sensitivity.py"),
         "--port", str(port),
         "--seed", str(int(cfg["seeds"]["traffic_manager"])),
         "--out", str(out)],
        capture_output=True, text=True, timeout=3600)
    print(r.stdout.rstrip())
    # An uncaught Python exception also exits 1, so the return code alone
    # cannot distinguish "ran and concluded FAIL" from "crashed". The JSON
    # file is the only reliable signal that the helper actually completed.
    if not out.exists():
        print(f"  stage 3.6 helper did not complete (exit={r.returncode}):")
        print("  " + (r.stderr or "<no stderr>").strip()[-1800:].replace("\n", "\n  "))
        return verdict("3.6", False,
                       {"error": "helper did not complete",
                        "returncode": r.returncode,
                        "stderr": (r.stderr or "")[-2000:]})
    detail = json.loads(out.read_text())
    return verdict("3.6", bool(detail.get("pass")), detail)


# ==========================================================================
# main
# ==========================================================================

# Tolerances. Justified in 3.7 and in docs/determinism_report.md.
TOL_FIELD = 1e-6     # per-field max absolute deviation across repeated runs
ARTIFACT_SPEED_MPS = 5.0   # below this, CARLA's braking deceleration is not physical
TOL_RHO = 1e-6       # spread in rho across repeated runs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--stages", type=str, default="3.1,3.2,3.3,3.4,3.5,3.6")
    ap.add_argument("--program", type=str, default=None,
                    help="path to a .bt program; omit for the placeholder controller")
    ap.add_argument("--out", type=str,
                    default=str(REPO / "data/results/determinism_gate.json"))
    args = ap.parse_args()

    want = set(s.strip() for s in args.stages.split(","))
    cfg = load_config("sim")
    port = args.port or int(cfg["server"]["port"])
    cfg["server"]["port"] = port
    contracts = load_config("contracts")

    results: dict[str, bool] = {}
    t_start = time.perf_counter()

    # ---- 3.6 MUST RUN FIRST ------------------------------------------------
    # It restarts the CARLA server. Any process that has held a carla.Client
    # aborts with SIGABRT from libcarla's background thread when its server
    # disappears -- and that is not catchable from Python. Running 3.6 before
    # this process has ever connected sidesteps it entirely, and leaves a
    # freshly restarted server for the remaining stages. Reported out of
    # numerical order; the report records the real execution order.
    if "3.6" in want:
        results["3.6"] = stage_3_6(port, cfg)
        REPORT["stage_execution_order"] = [
            "3.6 (first: restarts the server)", "3.1", "3.2", "3.3", "3.4", "3.5"]

    from carla_backend import CarlaBackend

    with CarlaBackend(cfg=cfg, contracts=contracts) as be:
        if args.program:
            prog = be.load_program(args.program)
            print(f"program: {args.program} depth={prog.ast.depth()} "
                  f"size={prog.ast.size()}")
            REPORT["program"] = args.program
        junction = be.discover_left_turn_junction()
        print(f"junction: id={junction['junction_id']} "
              f"lights={junction['n_traffic_lights']} "
              f"left-turn dyaw={junction['left_turn']['measured_dyaw_deg']:.2f} deg")
        REPORT["junction"] = junction

        hdr("BASELINE EPISODE (feeds 3.1 and 3.3)")
        res0 = be.run_episode(GATE_PARAMS, episode_id="det_baseline")
        print(f"  status={res0.status}  ticks={res0.n_ticks}  "
              f"wall={res0.wall_clock_s:.2f}s  rtf={res0.real_time_factor:.4f}")
        if not res0.usable:
            print(f"  BASELINE EPISODE PRODUCED NO USABLE TRAJECTORY.")
            print(f"  status={res0.status}")
            print((res0.error or "")[:3000])
            REPORT["stages"]["baseline"] = {"pass": False, "status": res0.status,
                                            "error": (res0.error or "")[:4000]}
            pathlib.Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            pathlib.Path(args.out).write_text(json.dumps(REPORT, indent=2, default=str))
            return 1
        REPORT["baseline"] = asdict(res0)

        if "3.1" in want:
            results["3.1"] = stage_3_1(res0, cfg)
        if "3.2" in want:
            results["3.2"] = stage_3_2(cfg, port)
        if "3.3" in want:
            results["3.3"] = stage_3_3(res0, contracts, junction)
        if "3.4" in want:
            results["3.4"] = stage_3_4(be, args.n, contracts, junction)
        REPORT["program_arg"] = args.program

    # 3.5 and 3.6 need the backend fully released, not merely closed. 3.6
    # RESTARTS the server, and any surviving carla.Client would abort the
    # process from its background thread when the server disappears.
    be.release()
    del be
    gc.collect()

    if "3.5" in want:
        results["3.5"] = stage_3_5(args.n, port, contracts, junction,
                                   program=args.program)
    # ---- 3.7 verdict -----------------------------------------------------
    hdr("3.7  VERDICT")
    print(f"  Tolerances applied:")
    print(f"    per-field max absolute deviation : {TOL_FIELD:.0e}")
    print(f"    spread in rho across runs        : {TOL_RHO:.0e}")
    print()
    print("  Justification: a synchronous, fixed-delta simulator replaying")
    print("  identical inputs should reproduce BIT-IDENTICALLY (deviation 0.0).")
    print("  A tolerance of 1e-6 allows for float64 accumulation differences")
    print("  without admitting anything physically meaningful: 1e-6 m is a")
    print("  micrometre and 1e-6 s is a microsecond. Divergence in rho at the")
    print("  second or third decimal would mean rho values are NOT comparable")
    print("  across runs, which would invalidate the entire experiment -- the")
    print("  ablation compares rho between conditions, so run-to-run noise")
    print("  larger than the between-condition effect makes the result")
    print("  meaningless.")
    print()
    for k in sorted(results):
        print(f"    {k}: {'PASS' if results[k] else 'FAIL'}")

    all_pass = all(results.values()) and len(results) > 0
    REPORT["tolerances"] = {"field": TOL_FIELD, "rho": TOL_RHO}
    REPORT["verdict"] = "PASS" if all_pass else "FAIL"
    REPORT["total_wall_clock_s"] = time.perf_counter() - t_start

    print()
    print("=" * 78)
    print(f"  GATE VERDICT: {'PASS' if all_pass else 'FAIL'}")
    if not all_pass:
        print("  DO NOT PROCEED TO PHASE 4. Diagnose first.")
    print("=" * 78)

    outp = pathlib.Path(args.out)
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(REPORT, indent=2, default=str))
    print(f"\n  machine-readable report: {outp}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
