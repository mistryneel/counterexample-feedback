"""STL contracts and robustness, computed from a logged trajectory.

Space robustness (Donze & Maler 2010): rho is POSITIVE when the contract is
satisfied and NEGATIVE when violated, and its magnitude is the margin --
readable directly as "metres of clearance" or "seconds of margin". That
readability matters because rho appears verbatim in the certificate shown to
the LLM.

TODAY'S SCOPE (23 Aug): C1 and C2 only, minimal forms, to validate the
pipeline end to end. C5 landed 24 Aug; C3 and C4 re-enabled 30 Aug.

This module imports NO CARLA. It reads a Parquet trace plus the small
committed `junction.yaml`, which is what lets rho be recomputed on any
machine with no simulator -- the trace-store architecture in 01 Compute plan.
"""

from __future__ import annotations

import json
import math
import pathlib
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pyarrow.parquet as pq
import yaml

from config import REPO_ROOT, load_config


# ==========================================================================
# Result types
# ==========================================================================

@dataclass
class ContractResult:
    """Robustness of a single contract over one trajectory."""

    name: str
    rho: float
    signal: np.ndarray               # per-timestep robustness, NaN where undefined
    argmin_index: int | None         # row index of the weakest timestep
    t_s: float | None                # simulation time at the argmin
    frame: int | None
    vacuous: bool = False            # predicate never applied (e.g. never in zone)
    detail: dict = field(default_factory=dict)


@dataclass
class RhoResult:
    """Overall robustness: rho = min over enabled contracts."""

    rho: float
    contract: str                    # WHICH contract is the argmin
    argmin_index: int | None         # WHICH timestep
    t_s: float | None
    frame: int | None
    per_contract: dict[str, ContractResult]

    def summary(self) -> str:
        parts = [
            f"{c.name}={c.rho:+.4f}" + ("(vacuous)" if c.vacuous else "")
            for c in self.per_contract.values()
        ]
        return (
            f"rho = {self.rho:+.4f}  [argmin: {self.contract} @ "
            f"t={self.t_s:.3f}s frame={self.frame} row={self.argmin_index}]  "
            + "  ".join(parts)
        )


# ==========================================================================
# Geometry: exact 2D oriented-bounding-box separation
# ==========================================================================
# `clearance` in C1 is "minimum bounding-box separation in metres, negative
# on overlap". A circle approximation would be cheaper but would make rho
# physically wrong by up to half a vehicle length -- and rho is the number
# the whole experiment rests on and that we hand-check in the determinism
# gate. So this is exact for convex rectangles.
# ==========================================================================

def obb_corners(cx: float, cy: float, yaw_deg: float,
                ex: float, ey: float) -> np.ndarray:
    """Four corners (CCW) of an oriented rectangle. ex/ey are HALF-extents."""
    c, s = math.cos(math.radians(yaw_deg)), math.sin(math.radians(yaw_deg))
    local = np.array([[+ex, +ey], [-ex, +ey], [-ex, -ey], [+ex, -ey]])
    rot = np.array([[c, -s], [s, c]])
    return local @ rot.T + np.array([cx, cy])


def _seg_seg_distance(p1, p2, q1, q2) -> float:
    """Minimum distance between two 2-D segments."""
    d1, d2 = p2 - p1, q2 - q1
    r = p1 - q1
    a, e, f = d1 @ d1, d2 @ d2, d2 @ r
    EPS = 1e-12
    if a <= EPS and e <= EPS:
        return float(np.linalg.norm(p1 - q1))
    if a <= EPS:
        s, t = 0.0, float(np.clip(f / e, 0, 1))
    else:
        c = d1 @ r
        if e <= EPS:
            t, s = 0.0, float(np.clip(-c / a, 0, 1))
        else:
            b = d1 @ d2
            denom = a * e - b * b
            s = float(np.clip((b * f - c * e) / denom, 0, 1)) if denom > EPS else 0.0
            t = (b * s + f) / e
            if t < 0:
                t, s = 0.0, float(np.clip(-c / a, 0, 1))
            elif t > 1:
                t, s = 1.0, float(np.clip((b - c) / a, 0, 1))
    return float(np.linalg.norm((p1 + d1 * s) - (q1 + d2 * t)))


def obb_clearance(A: np.ndarray, B: np.ndarray) -> float:
    """Signed separation between two convex polygons.

    Positive  -> minimum distance between them.
    Negative  -> minus the penetration depth (SAT minimum overlap).
    Zero      -> touching.
    """
    # Separating Axis Theorem over the edge normals of both polygons.
    min_overlap = math.inf
    for poly in (A, B):
        n = len(poly)
        for i in range(n):
            edge = poly[(i + 1) % n] - poly[i]
            axis = np.array([-edge[1], edge[0]])
            norm = np.linalg.norm(axis)
            if norm < 1e-12:
                continue
            axis = axis / norm
            pa_, pb_ = A @ axis, B @ axis
            overlap = min(pa_.max(), pb_.max()) - max(pa_.min(), pb_.min())
            if overlap < 0:
                # A separating axis exists -> disjoint. The exact distance is
                # the min over edge-pair segment distances (the SAT gap alone
                # underestimates in vertex-vertex configurations).
                best = math.inf
                for i2 in range(len(A)):
                    for j2 in range(len(B)):
                        best = min(best, _seg_seg_distance(
                            A[i2], A[(i2 + 1) % len(A)],
                            B[j2], B[(j2 + 1) % len(B)]))
                return float(best)
            min_overlap = min(min_overlap, overlap)
    return float(-min_overlap)


# ==========================================================================
# Trace loading
# ==========================================================================

def load_trace(path: str | pathlib.Path):
    """Read a Parquet trace. Returns (DataFrame, file metadata dict)."""
    tbl = pq.read_table(path)
    meta = {}
    if tbl.schema.metadata:
        meta = {k.decode(): v.decode() for k, v in tbl.schema.metadata.items()}
    return tbl.to_pandas(), meta


def load_junction(path: str | pathlib.Path | None = None) -> dict:
    p = pathlib.Path(path) if path else REPO_ROOT / "data" / "scenarios" / "junction.yaml"
    if not p.exists():
        raise FileNotFoundError(
            f"missing {p} -- run carla_backend.discover_left_turn_junction() first"
        )
    return yaml.safe_load(p.read_text())


# ==========================================================================
# C1 -- no collision
# ==========================================================================

def rho_c1(df, cfg: dict) -> ContractResult:
    """C1: always over t of ( clearance(ego, any actor) >= 0 ).

    rho_1 = min over t of clearance(t).
    """
    n = len(df)
    sig = np.full(n, np.nan)
    closest = [None] * n

    for i in range(n):
        r = df.iloc[i]
        ids = list(r["actor_id"])
        if not ids:
            # No other actors -> nothing to collide with. Clearance is
            # unbounded; cap it so it cannot dominate the min-across-contracts
            # blame signal with a meaningless huge value.
            sig[i] = float(cfg.get("no_actor_clearance_m", 100.0))
            continue
        ego = obb_corners(r["ego_x_m"], r["ego_y_m"], r["ego_yaw_deg"],
                          r["ego_extent_x_m"], r["ego_extent_y_m"])
        best, best_id = math.inf, None
        for k in range(len(ids)):
            other = obb_corners(
                r["actor_x_m"][k], r["actor_y_m"][k], r["actor_yaw_deg"][k],
                r["actor_extent_x_m"][k], r["actor_extent_y_m"][k])
            d = obb_clearance(ego, other)
            if d < best:
                best, best_id = d, ids[k]
        sig[i] = best
        closest[i] = best_id

    idx = int(np.nanargmin(sig))
    return ContractResult(
        name="C1", rho=float(sig[idx]), signal=sig, argmin_index=idx,
        t_s=float(df.iloc[idx]["t_s"]), frame=int(df.iloc[idx]["frame"]),
        detail={"closest_actor_id": closest[idx],
                "units": "metres of bounding-box separation"},
    )


# ==========================================================================
# C2 -- yield to oncoming traffic
# ==========================================================================

def rho_c2(df, cfg: dict, junction: dict) -> ContractResult:
    """C2: always over t of ( in_conflict_zone(ego) -> ttc_oncoming >= tau ).

    rho_2 = min over { t : ego in conflict zone } of ( ttc_oncoming(t) - tau ).

    TODAY the conflict zone is a disc around the junction centre. The real
    polygon (ego turn path intersected with oncoming through-lane corridors)
    lands 24 Aug. That approximation is recorded in `detail` so a rho computed
    today is never silently compared against one computed tomorrow.
    """
    tau = float(cfg["tau_yield_s"])
    cap = float(cfg["ttc_cap_s"])
    vmin = float(cfg["min_speed_for_ttc_mps"])
    radius = float(cfg.get("conflict_zone_radius_m", 12.0))

    c = junction["junction_center"]
    czx, czy = float(c["x"]), float(c["y"])

    n = len(df)
    sig = np.full(n, np.nan)   # NaN where the ego is NOT in the conflict zone
    in_zone = np.zeros(n, dtype=bool)

    for i in range(n):
        r = df.iloc[i]
        d_ego = math.hypot(r["ego_x_m"] - czx, r["ego_y_m"] - czy)
        if d_ego > radius:
            continue                      # antecedent false -> vacuously true
        in_zone[i] = True

        ttc = cap
        for k in range(len(r["actor_id"])):
            if r["actor_role"][k] != "oncoming":
                continue
            sp = float(r["actor_speed_mps"][k])
            if sp < vmin:
                continue                  # not approaching; no constraint
            d = math.hypot(r["actor_x_m"][k] - czx, r["actor_y_m"][k] - czy)
            ttc = min(ttc, min(d / sp, cap))
        sig[i] = ttc - tau

    if not in_zone.any():
        # The ego never entered the conflict zone. C2 is VACUOUSLY satisfied.
        # Report the sentinel, not +inf, and flag it -- a program that never
        # enters the junction is not a safe program, it is a failed task, and
        # ICR/PCR are what must catch that.
        return ContractResult(
            name="C2", rho=float(cfg["vacuous_rho"]), signal=sig,
            argmin_index=None, t_s=None, frame=None, vacuous=True,
            detail={"reason": "ego never entered the conflict zone",
                    "conflict_zone": "disc approximation (23 Aug)",
                    "radius_m": radius},
        )

    idx = int(np.nanargmin(sig))
    return ContractResult(
        name="C2", rho=float(sig[idx]), signal=sig, argmin_index=idx,
        t_s=float(df.iloc[idx]["t_s"]), frame=int(df.iloc[idx]["frame"]),
        detail={"tau_yield_s": tau, "ttc_at_argmin_s": float(sig[idx] + tau),
                "n_ticks_in_zone": int(in_zone.sum()),
                "conflict_zone": "disc approximation (23 Aug)",
                "radius_m": radius,
                "units": "seconds of margin above tau_yield"},
    )


# ==========================================================================
# C5 -- kinematic comfort, computed from COMMANDED CONTROL
# ==========================================================================
# WHY NOT MEASURED ACCELERATION. Measured on 300 banked traces, 24 Aug:
#
#   * CARLA's accelerometer has a noise floor of sigma ~= 1.36 m/s^2
#     tick-to-tick, in clean cruising with monotonically decreasing throttle.
#   * j_comfort = 3.0 m/s^3 at dt = 0.05 s demands a tick-to-tick
#     acceleration change of only 0.15 m/s^2 -- NINE TIMES BELOW that floor.
#     Jerk from measured acceleration at 20 Hz is therefore not a measurement
#     of the vehicle, it is a measurement of the sampling noise.
#   * A speed-threshold sweep from 2 to 8 m/s produced NO cliff: the C5
#     violation rate was 100% at every threshold, because no threshold
#     recovers jerk. (It did clean up acceleration -- p95 max|a| fell from
#     26.87 to 5.77 between 4.00 and 4.25 m/s -- but acceleration was never
#     the binding term.)
#   * Measured acceleration is additionally contaminated by collisions
#     (|a| up to 61.7 m/s^2), which are C1's business, not C5's.
#
# Commanded control has none of these problems: it is exact, noise-free, and
# unaffected by the simulator's low-speed braking artifact. It also measures
# the right thing for C5's stated purpose (spec D4 -- catch "brake hard and
# never turn"): comfort is a property of the CONTROL POLICY, and what the
# program COMMANDS is precisely what the program is responsible for.
#
# The command is converted to m/s^2 through a MEASURED linear map
# (data/results/control_map.json, scripts/calibrate_control_map.py) so that
# rho_5 stays readable as an acceleration -- which matters because rho appears
# verbatim in the certificate shown to the LLM.
#
# LIMITATION, to be stated in the paper: this scores the commanded
# acceleration, not the realised one. A program whose commands are smooth but
# whose vehicle response is harsh would pass C5. Given that the realised
# signal is unmeasurable at this sample rate, that is the honest trade.
# ==========================================================================

def commanded_accel(df, cmap: dict) -> np.ndarray:
    """Longitudinal acceleration implied by the commanded control, in m/s^2."""
    return (float(cmap["k_throttle_mps2"]) * df["ego_throttle"].to_numpy(float)
            - float(cmap["k_brake_mps2"]) * df["ego_brake"].to_numpy(float)
            + float(cmap["a_coast_mps2"]))


def load_control_map(path: str | pathlib.Path | None = None) -> dict:
    p = pathlib.Path(path) if path else REPO_ROOT / "data" / "results" / "control_map.json"
    if not p.exists():
        raise FileNotFoundError(
            f"missing {p} -- run scripts/calibrate_control_map.py first. "
            "C5 must not fall back to a guessed control map.")
    return json.loads(p.read_text())


def rho_c5(df, cfg: dict, cmap: dict | None = None) -> ContractResult:
    """C5: always over t of ( |a_cmd| <= a_comfort AND |jerk_cmd| <= j_comfort ).

    rho_5 = min over t of min( a_comfort - |a_cmd(t)|, j_comfort - |jerk_cmd(t)| )

    No speed threshold is applied, and none is needed: the commanded signal
    carries no low-speed artifact. C5 is evaluated over the whole episode.
    """
    cmap = cmap or load_control_map()
    a_comfort = float(cfg["a_comfort_mps2"])
    j_comfort = float(cfg["j_comfort_mps3"])
    dt = float(cfg.get("dt_s", 0.05))

    # Prefer the acceleration the PROGRAM asked for, logged directly
    # (schema >= 1.2.0). Fall back to inverting the control map from
    # throttle/brake for traces that predate the column -- but note that the
    # fallback is contaminated by actuator slew limiting and gives C5 no
    # variance between programs.
    if "cmd_accel_mps2" in df.columns and df["cmd_accel_mps2"].notna().any():
        a_cmd = df["cmd_accel_mps2"].to_numpy(float)
        source = "program commanded acceleration (logged)"
    else:
        a_cmd = commanded_accel(df, cmap)
        source = "inverted control map from throttle/brake (pre-1.2.0 fallback)"
    # Jerk is NULL on the first sample -- there is no previous command, so
    # there is no measurement. A fabricated 0.0 would silently enter min().
    j_cmd = np.full(len(a_cmd), np.nan)
    if len(a_cmd) > 1:
        j_cmd[1:] = np.diff(a_cmd) / dt

    m_a = a_comfort - np.abs(a_cmd)
    m_j = j_comfort - np.abs(j_cmd)

    # THE JERK TERM IS COMPUTED AND REPORTED BUT DOES NOT CONTRIBUTE TO rho_5.
    #
    # At dt = 0.05 s, j_comfort = 3.0 m/s^3 demands that the commanded
    # acceleration change by no more than 0.15 m/s^2 per tick. The DSL has no
    # way to express a multi-tick acceleration ramp: an action selects an
    # acceleration and the next action selects a different one, so a switch is
    # a step. Measured across the plausible program space, max|jerk_cmd| ran
    # from 36 (the gentlest program expressible) to 260 -- every program
    # violates, so the term fires on 100% of episodes and would drive SCVR to
    # 100% by itself while distinguishing nothing.
    #
    # The ACCELERATION term does discriminate cleanly against the same 3.0
    # bound: 1.00 (gentle) / 2.00 (reference) / 7.50 (harsh). That is exactly
    # the discrimination C5 exists for -- decision D4, catching a program that
    # brakes hard and never turns.
    #
    # To restore the jerk term, the DSL must gain a ramp: either an explicit
    # jerk_mps3 parameter on the actions, or an interpretation of accel_mps2
    # as a rate toward a target acceleration. Recorded as future work rather
    # than papered over by relaxing the threshold until it stops firing.
    if bool(cfg.get("jerk_contributes", False)):
        sig = np.fmin(m_a, m_j)
    else:
        sig = m_a

    idx = int(np.nanargmin(sig))
    binding = "accel" if not bool(cfg.get("jerk_contributes", False)) else (
        "accel" if m_a[idx] <= (m_j[idx] if not np.isnan(m_j[idx]) else np.inf) else "jerk")
    return ContractResult(
        name="C5", rho=float(sig[idx]), signal=sig, argmin_index=idx,
        t_s=float(df.iloc[idx]["t_s"]), frame=int(df.iloc[idx]["frame"]),
        detail={"a_comfort_mps2": a_comfort, "j_comfort_mps3": j_comfort,
                "binding_term": binding,
                "jerk_contributes": bool(cfg.get("jerk_contributes", False)),
                "rho5_jerk_if_it_did": (
                    None if np.all(np.isnan(m_j)) else float(np.nanmin(m_j))),
                "a_cmd_at_argmin": float(a_cmd[idx]),
                "jerk_cmd_at_argmin": (None if np.isnan(j_cmd[idx]) else float(j_cmd[idx])),
                "max_abs_a_cmd": float(np.abs(a_cmd).max()),
                "max_abs_jerk_cmd": float(np.nanmax(np.abs(j_cmd))) if len(a_cmd) > 1 else None,
                "source": source,
                "units": "m/s^2 of comfort margin"},
    )


# ==========================================================================
# C3 -- do not occupy the intersection on red
# ==========================================================================
# rho_3 = min over { t : ego in intersection } of ( t_red_onset - t )
#
# The robustness is a TIME MARGIN TO RED ONSET, not a boolean. A program that
# clears the junction with eight seconds to spare and one that scrapes through
# as the phase flips are both "not on red", and C3 is what tells them apart.
#
# Yellow is deliberately NOT red. Entering on yellow is legal in this scenario
# and C3 must not punish it -- yellow is the interval during which the margin
# shrinks, which is exactly the signal the contract exists to carry.
# ==========================================================================

def rho_c3(df, cfg: dict, junction: dict, cz_cfg: dict | None = None) -> ContractResult:
    """C3: always over t of ( in_intersection(ego) -> light_state != RED )."""
    red_states = set(cfg.get("red_states", ["Red"]))
    cap = float(cfg.get("no_red_onset_rho", 30.0))
    radius = float((cz_cfg or {}).get("conflict_zone_radius_m", 12.0))

    c = junction["junction_center"]
    czx, czy = float(c["x"]), float(c["y"])

    t = df["t_s"].to_numpy(float)
    n = len(df)

    # First tick at which the ego's own signal is red. There may be none.
    tl = df["tl_state"].tolist()
    t_red_onset = None
    for i in range(n):
        if tl[i] is not None and str(tl[i]) in red_states:
            t_red_onset = float(t[i])
            break

    ego_x = df["ego_x_m"].to_numpy(float)
    ego_y = df["ego_y_m"].to_numpy(float)
    in_zone = np.hypot(ego_x - czx, ego_y - czy) <= radius

    # PHASE-RELATIVE MARGIN, per tick.
    #
    # The v1 spec form is `t_red_onset - t` against a single global onset.
    # That is correct only for a signal with ONE red onset that never
    # recovers, which is what this harness first implemented -- and under it
    # C3 was satisfiable only for light_offset >= 9.0, because a light that
    # goes red and stays red leaves no violation-free response and every
    # counterexample fails the avoidability filter (spec 6.5). The signal now
    # cycles green -> yellow -> red -> green, so the margin must be measured
    # against the CURRENT phase rather than the first onset. This is a
    # generalisation of the v1 formula, not a replacement: with exactly one
    # onset and no recovery the two agree exactly.
    #
    #   ego in intersection, light NOT red -> +time until the next red onset
    #   ego in intersection, light IS  red -> -time since this red began
    #
    # so scraping through as the phase changes still scores near zero, which
    # is the property the v1 form was chosen for.
    is_red = np.array([tl[i] is not None and str(tl[i]) in red_states
                       for i in range(n)])

    # time until the next red onset, per tick (cap where none follows)
    next_onset = np.full(n, np.inf)
    nxt = np.inf
    for i in range(n - 1, -1, -1):
        if is_red[i] and (i == 0 or not is_red[i - 1]):
            nxt = t[i]                      # this tick begins a red run
        next_onset[i] = nxt

    # time at which the current red run began, per red tick
    cur_red_start = np.full(n, np.nan)
    start = None
    for i in range(n):
        if is_red[i]:
            if start is None:
                start = t[i]
            cur_red_start[i] = start
        else:
            start = None

    # ENTRY SEMANTICS, decided 30 Aug. The predicate is evaluated at the ticks
    # where the ego ENTERS the intersection, not across its whole occupancy.
    #
    # Under occupancy semantics a program was punished for being caught inside
    # when the phase changed. Measured over 100 episodes of a competent
    # hand-written probe: 45 violations were genuine (entered on red) but 32
    # entered on GREEN and were caught mid-crossing. The vocabulary exposes
    # TrafficLightIsGreen() but nothing about phase TIMING, so no program this
    # DSL can express is able to foresee those, and all 32 would be rejected by
    # the avoidability filter (spec 6.5, RSS rule 5) -- C3 was spending a third
    # of its signal measuring luck.
    #
    # Entry semantics is also what the traffic rule actually says: a driver who
    # has lawfully entered is expected to CLEAR the junction, not stop dead
    # inside it. Stopping mid-junction is the more dangerous response, and C1
    # and C2 already penalise it.
    #
    # DEVIATION FROM THE v1 SPEC FORM, which says "do not OCCUPY the
    # intersection on red". Recorded here and belongs in the limitations
    # section. Re-entry is handled: every outside->inside transition is an
    # entry event and the min is taken over all of them.
    sig = np.full(n, np.nan)   # NaN except at entry ticks
    entries = [i for i in range(n) if in_zone[i] and (i == 0 or not in_zone[i - 1])]
    for i in entries:
        if is_red[i]:
            sig[i] = -(t[i] - cur_red_start[i])
        else:
            sig[i] = cap if not np.isfinite(next_onset[i]) else min(
                next_onset[i] - t[i], cap)

    if not in_zone.any():
        return ContractResult(
            name="C3", rho=float(cfg["vacuous_rho"]), signal=sig,
            argmin_index=None, t_s=None, frame=None, vacuous=True,
            detail={"reason": "ego never entered the intersection",
                    "radius_m": radius},
        )

    idx = int(np.nanargmin(sig))
    return ContractResult(
        name="C3", rho=float(sig[idx]), signal=sig, argmin_index=idx,
        t_s=float(df.iloc[idx]["t_s"]), frame=int(df.iloc[idx]["frame"]),
        detail={"t_red_onset_s": t_red_onset,
                "red_onset_observed": t_red_onset is not None,
                "n_ticks_in_intersection": int(in_zone.sum()),
                "n_entry_events": len(entries),
                "semantics": "entry (not occupancy) -- see rho_c3 docstring",
                "radius_m": radius,
                "units": "seconds of margin before red onset"},
    )


# ==========================================================================
# C4 -- RSS longitudinal safe distance to the lead vehicle
# ==========================================================================
# rho_4 = min over t of ( d_long(ego, lead) - d_min_RSS(v_ego, v_lead) )
#
# d_min_RSS is Lemma 2 of Shalev-Shwartz, Shammah & Shashua, arXiv:1708.06374,
# for two cars travelling in the SAME direction. Verified against the paper
# text rather than recalled:
#
#   d_min = [ v_r*rho + 0.5*a_max_accel*rho^2
#             + (v_r + rho*a_max_accel)^2 / (2*a_min_brake)
#             - v_f^2 / (2*a_max_brake) ]_+
#
# The asymmetry between a_min_brake (rear, weak) and a_max_brake (front,
# strong) is the whole content of the lemma: it is a worst case, in which the
# car in front stops as hard as it can and the car behind brakes as gently as
# it is allowed to. Do not "tidy" the two into one constant.
#
# ONLY same-direction actors are scored. An oncoming vehicle is the opposite
# case, has a different formula in the paper, and is C2's business anyway.
# ==========================================================================

def d_min_rss(v_r: float, v_f: float, tau: float,
              a_max_accel: float, a_min_brake: float,
              a_max_brake: float) -> float:
    """Safe longitudinal distance, same direction. RSS Lemma 2."""
    d = (v_r * tau
         + 0.5 * a_max_accel * tau * tau
         + (v_r + tau * a_max_accel) ** 2 / (2.0 * a_min_brake)
         - v_f * v_f / (2.0 * a_max_brake))
    return max(d, 0.0)


def rho_c4(df, cfg: dict) -> ContractResult:
    """C4: always over t of ( d_long(ego, lead) >= d_min_RSS )."""
    tau = float(cfg["tau_resp_s"])
    a_acc = float(cfg["a_max_accel_mps2"])
    a_minb = float(cfg["a_min_brake_mps2"])
    a_maxb = float(cfg["a_max_brake_mps2"])
    lead_role = cfg.get("lead_role", "lead")
    max_dyaw = float(cfg.get("same_direction_max_dyaw_deg", 45.0))
    cap = float(cfg.get("d_cap_m", 100.0))

    n = len(df)
    sig = np.full(n, np.nan)
    saw_lead = False

    for i in range(n):
        r = df.iloc[i]
        yaw = math.radians(float(r["ego_yaw_deg"]))
        hx, hy = math.cos(yaw), math.sin(yaw)      # ego heading unit vector
        v_r = float(r["ego_speed_mps"])

        best = None
        for k in range(len(r["actor_id"])):
            if r["actor_role"][k] != lead_role:
                continue
            # Same-direction test: heading difference within tolerance.
            dyaw = abs((float(r["actor_yaw_deg"][k]) - float(r["ego_yaw_deg"])
                        + 180.0) % 360.0 - 180.0)
            if dyaw > max_dyaw:
                continue
            dx = float(r["actor_x_m"][k]) - float(r["ego_x_m"])
            dy = float(r["actor_y_m"][k]) - float(r["ego_y_m"])
            # LONGITUDINAL projection onto the ego heading. The lemma is about
            # along-lane distance; Euclidean range would credit a car that is
            # beside the ego as though it were in front.
            d_long = dx * hx + dy * hy
            if d_long <= 0.0:
                continue                    # behind the ego: not a lead
            saw_lead = True
            v_f = float(r["actor_speed_mps"][k])
            margin = d_long - d_min_rss(v_r, v_f, tau, a_acc, a_minb, a_maxb)
            if best is None or margin < best:
                best = margin
        sig[i] = cap if best is None else min(best, cap)

    if not saw_lead:
        return ContractResult(
            name="C4", rho=float(cfg["vacuous_rho"]), signal=sig,
            argmin_index=None, t_s=None, frame=None, vacuous=True,
            detail={"reason": "no lead vehicle ahead of the ego in this episode",
                    "lead_role": lead_role},
        )

    idx = int(np.nanargmin(sig))
    return ContractResult(
        name="C4", rho=float(sig[idx]), signal=sig, argmin_index=idx,
        t_s=float(df.iloc[idx]["t_s"]), frame=int(df.iloc[idx]["frame"]),
        detail={"tau_resp_s": tau, "a_max_accel_mps2": a_acc,
                "a_min_brake_mps2": a_minb, "a_max_brake_mps2": a_maxb,
                "source": "RSS Lemma 2, arXiv:1708.06374, same direction",
                "units": "metres of margin above the RSS safe distance"},
    )


# ==========================================================================
# Combined
# ==========================================================================

def compute_rho(trace, contracts: dict | None = None,
                junction: dict | None = None) -> RhoResult:
    """rho = min over enabled contracts, with the argmin identified.

    Because conjunction is minimum, the argmin identifies BOTH the weakest
    contract AND the timestep at which it is weakest. The timestep is what
    blame localization resolves against the behaviour tree.
    """
    if isinstance(trace, (str, pathlib.Path)):
        df, _ = load_trace(trace)
    else:
        df = trace
    contracts = contracts or load_config("contracts")
    junction = junction or load_junction()

    results: dict[str, ContractResult] = {}
    active = contracts["combined"]["active"]

    if "C1" in active and contracts["C1_collision"]["enabled"]:
        results["C1"] = rho_c1(df, contracts["C1_collision"])
    if "C2" in active and contracts["C2_yield"]["enabled"]:
        results["C2"] = rho_c2(df, contracts["C2_yield"], junction)
    if "C3" in active and contracts["C3_red_light"]["enabled"]:
        results["C3"] = rho_c3(df, contracts["C3_red_light"], junction,
                               contracts["C2_yield"])
    if "C4" in active and contracts["C4_rss_longitudinal"]["enabled"]:
        results["C4"] = rho_c4(df, contracts["C4_rss_longitudinal"])
    report_only = set(contracts["combined"].get("report_only", []))
    if contracts["C5_comfort"]["enabled"] and ("C5" in active or "C5" in report_only):
        results["C5"] = rho_c5(df, contracts["C5_comfort"])

    if not results:
        raise ValueError("no contracts enabled -- check config/contracts.yaml")

    # Contracts listed in `report_only` are computed and returned, but do NOT
    # contribute to the combined min or to the argmin. Used when a contract is
    # measurable but currently degenerate -- a constant inside min() wins every
    # argmin and destroys the blame signal of the contracts that do vary.
    contributing = [c for k, c in results.items() if k not in report_only]
    if not contributing:
        raise ValueError(
            "every enabled contract is report_only -- rho would be undefined")

    # A vacuous contract does not contribute an argmin. It still reports its
    # sentinel rho, but the blame timestep must come from a contract that was
    # actually evaluated.
    ranked = sorted(contributing, key=lambda c: c.rho)
    winner = ranked[0]
    if winner.vacuous and len(ranked) > 1:
        non_vacuous = [c for c in ranked if not c.vacuous]
        if non_vacuous:
            winner = non_vacuous[0]

    return RhoResult(
        rho=winner.rho, contract=winner.name, argmin_index=winner.argmin_index,
        t_s=winner.t_s, frame=winner.frame, per_contract=results,
    )


# ==========================================================================
# Independent cross-check via rtamt
# ==========================================================================

def rtamt_crosscheck(signal: np.ndarray, times: np.ndarray) -> float:
    """Re-evaluate always(x >= 0) on a predicate signal using rtamt.

    Why bother, when `always` over a space-robustness signal is just min():
    precisely because it is just min(). This is a SECOND, INDEPENDENT
    implementation of the number the whole experiment rests on. The project
    names "plausible-looking rho from broken code" as a top trap; a
    disagreement here is the cheapest possible way to catch it.

    NaNs (timesteps where the predicate does not apply) are dropped first.
    """
    import rtamt

    mask = ~np.isnan(signal)
    if not mask.any():
        return float("nan")
    if int(mask.sum()) < 2:
        # rtamt's discrete-time offline interpreter cannot evaluate a
        # single-sample trace: it computes the sampling period inside its
        # per-sample loop, so with one sample it raises UnboundLocalError on
        # an unset `duration`. This is REACHABLE, not hypothetical -- C3
        # writes exactly one non-NaN sample (the `no_red_onset_rho` sentinel)
        # whenever the light never turns red, which is every scenario with no
        # `light_offset` set. Return NaN meaning "not cross-checked"; the
        # caller must treat that as SKIPPED, never as agreement.
        return float("nan")

    spec = rtamt.StlDiscreteTimeSpecification()
    spec.declare_var("x", "float")
    spec.spec = "always(x >= 0.0)"
    spec.parse()
    out = spec.evaluate({
        "time": [float(t) for t in times[mask]],
        "x": [float(v) for v in signal[mask]],
    })
    return float(out[0][1])
