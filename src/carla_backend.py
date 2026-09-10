"""CARLA backend — blackbox interface, PSY-TaLiRo style.

    scenario parameter dict  ->  trajectory (Parquet) + status

Nothing downstream may assume CARLA specifically. The only thing that leaves
this module is a trace file and an `EpisodeResult`.

Engineering invariants enforced here:

  * ONE persistent client for the whole campaign. `CarlaBackend` is a context
    manager; the client is created in `__enter__` and reused for every episode.
  * EVERY episode is wrapped so an exception returns a sentinel, never
    propagates. Losing run 47 of 200 to a spawn collision must not kill a
    campaign.
  * Original world settings are ALWAYS restored on exit, including on
    exception, including on KeyboardInterrupt.
  * Every spawned actor is tracked explicitly and destroyed, in a `finally`.
  * Python RNG, numpy RNG, and the Traffic Manager random device seed are all
    set, and re-set after every world reload (CARLA docs require this).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import math
import pathlib
import random
import time
import traceback
from dataclasses import dataclass, field, asdict
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

import carla

from config import REPO_ROOT, load_config, param_hash, git_commit, check_substepping
import trace_schema as ts


# ==========================================================================
# Result type
# ==========================================================================

@dataclass
class EpisodeResult:
    """What one simulation returns. Never raises; failures are data."""

    episode_id: str
    status: str
    param_hash: str
    scenario_params: dict
    n_ticks: int = 0
    wall_clock_s: float = 0.0
    real_time_factor: float = 0.0
    trace_path: str | None = None
    error: str | None = None
    meta: dict = field(default_factory=dict)

    @property
    def usable(self) -> bool:
        """True if a real trajectory exists and rho is defined.

        A `timeout` or `collision` run IS usable -- those are legitimate
        outcomes with real trajectories. Only TERMINAL_STATUSES are not.
        """
        return self.status not in ts.TERMINAL_STATUSES and self.n_ticks > 0


# ==========================================================================
# Geometry helpers (pure functions, no CARLA state)
# ==========================================================================

def _yaw_unit(yaw_deg: float) -> tuple[float, float]:
    r = math.radians(yaw_deg)
    return math.cos(r), math.sin(r)


def _signed_long_accel(ax: float, ay: float, yaw_deg: float) -> float:
    """Acceleration projected onto the heading unit vector.

    Signed, not magnitude: C5 bounds longitudinal comfort, and ||a|| would
    count centripetal acceleration during the turn as harsh braking.
    """
    ux, uy = _yaw_unit(yaw_deg)
    return ax * ux + ay * uy


# ==========================================================================
# Backend
# ==========================================================================

class CarlaBackend:
    """Persistent CARLA connection. Use as a context manager.

        with CarlaBackend() as be:
            for params in campaign:
                result = be.run_episode(params)
    """

    def __init__(self, cfg: dict | None = None, contracts: dict | None = None):
        self.cfg = cfg or load_config("sim")
        self.contracts = contracts or load_config("contracts")

        ok, msg = check_substepping(self.cfg)
        if not ok:
            raise RuntimeError(
                "PHYSICS SUBSTEPPING CONDITION VIOLATED -- refusing to start.\n"
                f"  {msg}\n"
                "CARLA does not raise on this. Physics would be silently "
                "non-deterministic and every rho downstream invalid."
            )
        self._substep_msg = msg

        self.client: carla.Client | None = None
        self.world: carla.World | None = None
        self.tm: carla.TrafficManager | None = None

        self._original_settings: carla.WorldSettings | None = None
        self._spawned: list[int] = []          # actor ids, tracked explicitly
        self._server_version: str | None = None
        self._client_version: str | None = None
        self._lights_frozen = False
        self._sensors: list = []
        self._prev_control = (0.0, 0.0)
        self._oncoming_state: dict[int, dict] = {}
        self._lead_state: dict[int, dict] = {}
        self._ego_tl = None          # resolved ego traffic light actor
        self._light_schedule: dict | None = None
        self._light_t0: float | None = None   # sim time the phase clock starts
        self._ego = None
        self._spawn_clamped = False
        self._control_map = None
        self._last_cmd_accel = None
        self.program = None          # BehaviourProgram, when one is loaded

        self.trace_dir = REPO_ROOT / self.cfg["logging"]["trace_dir"]
        self.trace_dir.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------- setup

    def __enter__(self) -> "CarlaBackend":
        s = self.cfg["server"]
        self.client = carla.Client(s["host"], int(s["port"]))
        self.client.set_timeout(float(s["timeout_s"]))

        # Version handshake: verify by connecting and
        # comparing. Do NOT assume pip resolved it correctly.
        self._client_version = self.client.get_client_version()
        self._server_version = self.client.get_server_version()
        if self._client_version != self._server_version:
            raise RuntimeError(
                "CARLA CLIENT/SERVER VERSION MISMATCH -- refusing to start.\n"
                f"  client: {self._client_version}\n"
                f"  server: {self._server_version}\n"
                "Mismatched versions can silently change API semantics."
            )

        target_map = self.cfg["world"]["map"]
        self.world = self.client.get_world()
        current_map = self.world.get_map().name.split("/")[-1]
        if current_map != target_map:
            self.world = self.client.load_world(target_map)

        # Save ORIGINAL settings before touching anything, so __exit__ can
        # restore them no matter how we leave.
        self._original_settings = self.world.get_settings()

        self._apply_sim_settings()
        self._setup_traffic_manager()
        self._apply_weather()
        return self

    def _apply_sim_settings(self) -> None:
        t = self.cfg["timing"]
        p = self.cfg["physics"]
        st = self.world.get_settings()
        st.synchronous_mode = bool(t["synchronous_mode"])
        st.fixed_delta_seconds = float(t["fixed_delta_seconds"])
        st.no_rendering_mode = bool(t["no_rendering_mode"])
        st.substepping = bool(p["substepping"])
        st.max_substep_delta_time = float(p["max_substep_delta_time"])
        st.max_substeps = int(p["max_substeps"])
        self.world.apply_settings(st)

    def _setup_traffic_manager(self) -> None:
        """Order matters and is dictated by the CARLA docs.

        adv_traffic_manager: "The CARLA server and the TM must be in
        synchronous mode BEFORE enabling deterministic mode." So:
        world sync (done above) -> tm sync -> tm seed. Never reorder.
        """
        if not self.cfg["traffic_manager"]["enabled"]:
            return
        tm_port = int(self.cfg["seeds"]["tm_port"])
        self.tm = self.client.get_trafficmanager(tm_port)
        self.tm.set_synchronous_mode(
            bool(self.cfg["traffic_manager"]["synchronous_mode"])
        )
        self.tm.set_hybrid_physics_mode(
            bool(self.cfg["traffic_manager"]["hybrid_physics_mode"])
        )
        self.tm.set_random_device_seed(int(self.cfg["seeds"]["traffic_manager"]))

    def _apply_weather(self) -> None:
        preset = self.cfg["weather"]["preset"]
        self.world.set_weather(getattr(carla.WeatherParameters, preset))

    # ------------------------------------------------------------- teardown

    def __exit__(self, exc_type, exc, tb) -> bool:
        """Always restore. Never suppress the caller's exception."""
        with contextlib.suppress(Exception):
            self._destroy_spawned()
        with contextlib.suppress(Exception):
            if getattr(self, "_lights_frozen", False) and self.world is not None:
                for tl in self.world.get_actors().filter("traffic.traffic_light*"):
                    tl.freeze(False)
                    break
        with contextlib.suppress(Exception):
            if self.tm is not None:
                self.tm.set_synchronous_mode(False)
        with contextlib.suppress(Exception):
            if self.world is not None and self._original_settings is not None:
                self.world.apply_settings(self._original_settings)
        self.release()
        return False   # do not swallow exceptions from the caller's block

    def release(self) -> None:
        """Drop every CARLA handle this object holds.

        Necessary before the SERVER is stopped. A live carla.Client keeps a
        background streaming thread; if the server dies underneath it, that
        thread throws carla::client::TimeoutException from a non-Python
        context, which reaches std::terminate and ABORTS the whole process
        (SIGABRT) rather than raising something catchable. Dropping the
        references first lets the client shut down cleanly.
        """
        self.tm = None
        self.world = None
        self.client = None
        self._sensors.clear()

    def _destroy_spawned(self) -> None:
        """Destroy every tracked actor, in one batch, then clear the list.

        Sensors are stop()ped FIRST. Destroying a listening sensor leaves it
        alive in the simulation and CARLA warns about it; over a 300-episode
        campaign those accumulate.
        """
        for sensor in self._sensors:
            with contextlib.suppress(Exception):
                if sensor.is_listening:
                    sensor.stop()
        self._sensors.clear()
        if not self._spawned or self.client is None:
            self._spawned.clear()
            return
        batch = [carla.command.DestroyActor(aid) for aid in self._spawned]
        with contextlib.suppress(Exception):
            self.client.apply_batch_sync(batch, True)
        self._spawned.clear()

    # --------------------------------------------------------------- seeding

    def _seed_everything(self, episode_seed_offset: int = 0) -> dict:
        """Seed Python, numpy, and the TM.

        CARLA docs: "the seed must be set for every simulation ... each time
        the world is reloaded, the seed must be set again." So this is called
        per episode, AFTER any world reload, not once at startup.
        """
        s = self.cfg["seeds"]
        py_seed = int(s["python"]) + episode_seed_offset
        np_seed = int(s["numpy"]) + episode_seed_offset
        tm_seed = int(s["traffic_manager"]) + episode_seed_offset

        random.seed(py_seed)
        np.random.seed(np_seed)
        if self.tm is not None:
            self.tm.set_random_device_seed(tm_seed)
        return {"python": py_seed, "numpy": np_seed, "traffic_manager": tm_seed}

    # ================================================================
    # Junction discovery
    # ================================================================
    # Design rule: record the exact junction identifier in Town05, not a
    # description; an unrecorded junction means unreproducible results. So
    # we discover once, cache to
    # data/scenarios/junction.yaml, and every later run reads the cache.
    # ================================================================

    JUNCTION_CACHE = REPO_ROOT / "data" / "scenarios" / "junction.yaml"

    def discover_left_turn_junction(self, force: bool = False) -> dict:
        """Find a four-way signalized junction and the left-turn manoeuvre in it.

        Returns a dict that is cached to junction.yaml and pinned thereafter.
        """
        import yaml as _yaml

        if self.JUNCTION_CACHE.exists() and not force:
            return _yaml.safe_load(self.JUNCTION_CACHE.read_text())

        cmap = self.world.get_map()
        lights = self.world.get_actors().filter("traffic.traffic_light*")

        # Group traffic lights by the junction their stop waypoints lead into.
        by_junction: dict[int, dict] = {}
        for tl in lights:
            for wp in tl.get_stop_waypoints():
                nxt = wp.next(6.0)
                for n in nxt:
                    j = n.get_junction()
                    if j is None:
                        continue
                    rec = by_junction.setdefault(
                        j.id, {"junction": j, "lights": set(), "entries": []}
                    )
                    rec["lights"].add(tl.id)
                    rec["entries"].append(wp)

        # A four-way signalized junction has 4 distinct traffic lights.
        candidates = [
            (jid, rec) for jid, rec in by_junction.items()
            if len(rec["lights"]) == 4
        ]
        if not candidates:
            raise RuntimeError(
                "No four-way signalized junction found in "
                f"{cmap.name}. Found junctions with light counts: "
                f"{ {jid: len(r['lights']) for jid, r in by_junction.items()} }"
            )

        # Deterministic choice: lowest junction id among candidates. Arbitrary
        # but REPRODUCIBLE, which is the whole point of O2.
        jid, rec = min(candidates, key=lambda kv: kv[0])
        junction: carla.Junction = rec["junction"]

        # Find the left-turn (entry, exit) pair.
        pairs = junction.get_waypoints(carla.LaneType.Driving)
        turns = []
        for entry, exit_ in pairs:
            dyaw = _norm_deg(exit_.transform.rotation.yaw
                             - entry.transform.rotation.yaw)
            turns.append((dyaw, entry, exit_))

        # CARLA/UE4 is left-handed with Y pointing right, so yaw INCREASES
        # clockwise seen from above. A left turn therefore has dyaw ~ -90.
        # We do not trust that from memory: pick the pair whose |dyaw + 90|
        # is smallest, and record the measured dyaw so the assumption is
        # visible in the cache file and checkable by eye.
        left = min(turns, key=lambda t: abs(t[0] + 90.0))
        dyaw, entry_wp, exit_wp = left

        if abs(dyaw + 90.0) > 30.0:
            raise RuntimeError(
                f"No ~-90 deg turn found in junction {jid}. "
                f"Best candidate dyaw={dyaw:.1f}. "
                f"All dyaw values: {sorted(round(t[0], 1) for t in turns)}. "
                "If these cluster near +90, the yaw sign convention is the "
                "opposite of what this code assumes -- fix it here, do not "
                "paper over it downstream."
            )

        # ---- resolve the ego and ONCOMING approaches -------------------
        # The oncoming corridor is the controlled approach whose heading is
        # ~180 deg opposed to the ego's junction-entry heading. It must NOT be
        # derived from the turn-exit waypoint: that waypoint is inside the
        # junction, where get_left_lane()/get_right_lane() both return None,
        # which silently collapses to the ego's OWN approach lane.
        ego_yaw = entry_wp.transform.rotation.yaw
        approaches = []
        for tl in lights:
            for wp in tl.get_stop_waypoints():
                if not any(n.get_junction() is not None and n.get_junction().id == jid
                           for n in wp.next(6.0)):
                    continue
                approaches.append(
                    (_norm_deg(wp.transform.rotation.yaw - ego_yaw), wp,
                     int(tl.id)))
        if not approaches:
            raise RuntimeError(
                f"junction {jid}: no controlled approaches resolved")

        ego_dyaw, ego_wp, ego_tl = min(approaches, key=lambda a: abs(a[0]))
        onc_dyaw, onc_wp, onc_tl = min(approaches,
                                       key=lambda a: abs(abs(a[0]) - 180.0))
        if abs(abs(onc_dyaw) - 180.0) > 20.0:
            raise RuntimeError(
                f"junction {jid}: no ~180 deg opposed approach found. "
                f"best dyaw={onc_dyaw:.1f}. Approach dyaws: "
                f"{sorted(round(a[0], 1) for a in approaches)}")

        bb = junction.bounding_box
        record = {
            "map": cmap.name,
            "junction_id": int(jid),
            "n_traffic_lights": len(rec["lights"]),
            # NOTE: traffic-light ACTOR ids are deliberately NOT cached.
            # They are reassigned on every world reload, so a cached id
            # silently matches nothing. Lights are resolved by geometry at
            # run time via resolve_traffic_lights().
            "traffic_light_ids_NOT_STABLE": sorted(int(x) for x in rec["lights"]),
            "ego_approach": {**_wp_record(ego_wp), "dyaw_vs_entry": float(ego_dyaw),
                             "traffic_light_id_at_discovery": ego_tl},
            "oncoming_approach": {**_wp_record(onc_wp), "dyaw_vs_entry": float(onc_dyaw),
                                  "traffic_light_id_at_discovery": onc_tl},
            "junction_center": {
                "x": float(bb.location.x),
                "y": float(bb.location.y),
                "z": float(bb.location.z),
            },
            "junction_extent": {
                "x": float(bb.extent.x),
                "y": float(bb.extent.y),
                "z": float(bb.extent.z),
            },
            "left_turn": {
                "measured_dyaw_deg": float(dyaw),
                "entry": _wp_record(entry_wp),
                "exit": _wp_record(exit_wp),
            },
            "all_turn_dyaw_deg": sorted(float(round(t[0], 2)) for t in turns),
            "discovered_by": "carla_backend.discover_left_turn_junction",
            "carla_version": self._server_version,
        }
        self.JUNCTION_CACHE.parent.mkdir(parents=True, exist_ok=True)
        self.JUNCTION_CACHE.write_text(
            "# Auto-discovered junction. Frozen once written -- delete this\n"
            "# file and re-run only if you intend to change the experiment.\n"
            + _yaml.safe_dump(record, sort_keys=False)
        )
        return record

    # ================================================================
    # Traffic lights
    # ================================================================

    def resolve_traffic_lights(self, junction_rec: dict) -> dict:
        """Find the ego and oncoming traffic lights BY GEOMETRY, every episode.

        Traffic-light actor ids are reassigned on every world reload, so a
        cached id silently matches nothing -- which is exactly how the first
        smoke run ended up driving through on Red. Lights are matched by the
        stop-line position recorded in junction.yaml, which is stable because
        it comes from OpenDRIVE.
        """
        want = {
            "ego": (junction_rec["ego_approach"]["x"],
                    junction_rec["ego_approach"]["y"]),
            "oncoming": (junction_rec["oncoming_approach"]["x"],
                         junction_rec["oncoming_approach"]["y"]),
        }
        found: dict[str, carla.TrafficLight] = {}
        for role, (tx, ty) in want.items():
            best, best_d = None, math.inf
            for tl in self.world.get_actors().filter("traffic.traffic_light*"):
                for wp in tl.get_stop_waypoints():
                    L = wp.transform.location
                    d = math.hypot(L.x - tx, L.y - ty)
                    if d < best_d:
                        best, best_d = tl, d
            if best is None or best_d > 3.0:
                raise RuntimeError(
                    f"could not resolve the {role} traffic light by geometry "
                    f"(nearest stop line {best_d:.2f} m from the recorded "
                    f"position). junction.yaml may be stale.")
            found[role] = best
        return found

    def set_permissive_green(self, junction_rec: dict) -> dict:
        """Ego and oncoming GREEN, cross traffic RED, then freeze.

        Spec D1: "unprotected" means a PERMISSIVE GREEN -- a circular green
        ball, not an arrow. The turn is legally permitted and the ego must
        yield to oncoming traffic. Both the ego and the oncoming approach are
        therefore green simultaneously; that is what makes the manoeuvre
        unprotected. Freezing removes signal phase as an uncontrolled source
        of variation (light_offset is not in the v2 parameter set).
        """
        tls = self.resolve_traffic_lights(junction_rec)
        green_ids = {tls["ego"].id, tls["oncoming"].id}
        for tl in self.world.get_actors().filter("traffic.traffic_light*"):
            if tl.id in green_ids:
                tl.set_state(carla.TrafficLightState.Green)
            else:
                tl.set_state(carla.TrafficLightState.Red)
        # freeze() is world-wide: it holds every light at its current state.
        # It STAYS frozen even with light_offset restored -- the phase is now
        # driven explicitly from the tick loop by _apply_light_schedule rather
        # than by CARLA's internal timer. Determinism is load-bearing here: a
        # simulator-driven phase would introduce a clock the seeds do not
        # control, which is precisely the class of bug the determinism gate
        # exists to catch.
        tls["ego"].freeze(True)
        self._lights_frozen = True
        self._ego_tl = tls["ego"]
        self._oncoming_tl = tls["oncoming"]
        return {"ego_tl_id": int(tls["ego"].id),
                "oncoming_tl_id": int(tls["oncoming"].id)}

    def _apply_light_schedule(self, params: dict, sc: dict, t_s: float,
                              junction: dict | None = None) -> None:
        """Drive the ego signal phase deterministically from `light_offset`.

        PHASED AGAINST THE EGO, NOT THE EPISODE CLOCK (changed 31 Aug).

        The phase clock starts when the ego first comes within
        `light_trigger_dist_m` of the junction centre, and from that instant:

            green   for dt <  light_offset
            yellow  for light_offset <= dt < light_offset + yellow_s
            red     for the next red_s
            green   thereafter

        so `light_offset` means "seconds of green remaining when the ego is
        light_trigger_dist_m out", the same quantity for every program.

        WHY. Under the previous rule the phase ran on the episode clock, so the
        signal state a program met depended on HOW FAST IT DROVE. Measured
        30 Aug: the hand-written reference program reached the conflict zone at
        a median 11.00 s while an LLM-synthesized candidate took 15.20 s --
        four seconds later, because a competent program actually waits behind
        the lead vehicle and for an oncoming gap. A bound tuned against the
        first program was catastrophically wrong for the second, and boundary
        search on the axis would have been measuring program speed as much as
        the scenario. Worse for the paper, a certificate reading "fails when
        light_offset <= 7" is not actionable, because the LLM cannot relate
        that number to anything it controls; "fails when under 2 s of green
        remain on approach" is.

        This is the same defect `headway` carried before 24 Aug, when it set a
        fixed spawn distance and was consequently a measured no-op, and it
        takes the same fix: phase the parameter against the ego's arrival.

        The oncoming signal is held green throughout. The manoeuvre is an
        UNPROTECTED left turn: if the oncoming approach went red the conflict
        would disappear and the scenario would stop being the one under study.
        """
        if self._ego_tl is None or not self._ego_tl.is_alive:
            return
        off = params.get("light_offset")
        if off is None:
            return                      # phase held green; C3 reports its cap

        # Start the phase clock the first time the ego is within the trigger
        # radius. Deterministic: it depends only on ego position, which is
        # itself deterministic.
        if self._light_t0 is None:
            ego = self._ego
            if ego is None or not ego.is_alive or junction is None:
                return
            c = junction["junction_center"]
            loc = ego.get_transform().location
            trig = float(sc.get("light_trigger_dist_m", 25.0))
            if math.hypot(loc.x - c["x"], loc.y - c["y"]) > trig:
                # Not there yet -- hold green.
                if self._ego_tl.get_state() != carla.TrafficLightState.Green:
                    self._ego_tl.set_state(carla.TrafficLightState.Green)
                return
            self._light_t0 = t_s
        t_s = t_s - self._light_t0
        yellow_s = float(sc.get("yellow_duration_s", 3.0))
        red_s = float(sc.get("red_duration_s", 6.0))
        off = float(off)
        # THE SIGNAL MUST CYCLE BACK TO GREEN. Measured 30 Aug with a
        # terminal red: C3 was satisfiable only for light_offset >= 9.0, i.e.
        # in the top 40% of the range. Below that the light went red before the
        # ego could clear and STAYED red, so the ego could only sit forever
        # (task never completed) or drive through on red (C3 violated) -- no
        # violation-free response existed. That fails the avoidability
        # requirement (spec 6.5, RSS rule 5) outright: every counterexample so
        # produced would be inadmissible, and C3 would be measuring bad luck
        # rather than bad driving. A real signalised junction cycles, so this
        # one does too: green -> yellow -> red -> green, and it then holds
        # green for the remainder of the episode.
        if t_s < off:
            want = carla.TrafficLightState.Green
        elif t_s < off + yellow_s:
            want = carla.TrafficLightState.Yellow
        elif t_s < off + yellow_s + red_s:
            want = carla.TrafficLightState.Red
        else:
            want = carla.TrafficLightState.Green
        if self._ego_tl.get_state() != want:
            self._ego_tl.set_state(want)

    # ================================================================
    # Route planning (own implementation; the pip carla wheel ships no
    # `agents` package, so GlobalRoutePlanner is unavailable)
    # ================================================================

    def plan_left_turn_route(
        self, junction_rec: dict, approach_m: float, exit_m: float, step: float = 1.0
    ) -> list[carla.Waypoint]:
        """Approach lane -> through the junction -> settle in the target lane.

        Greedy: at every branch take the successor closest to the goal. For a
        single fixed junction this is deterministic and has no hidden state,
        which matters more here than generality.
        """
        cmap = self.world.get_map()
        entry = _wp_from_record(cmap, junction_rec["left_turn"]["entry"])
        goal = _wp_from_record(cmap, junction_rec["left_turn"]["exit"])

        # Walk backwards from the junction entry to get the approach lane.
        approach: list[carla.Waypoint] = []
        wp = entry
        travelled = 0.0
        while travelled < approach_m:
            nxt = _walk_straight(wp, step, step=step, backwards=True)
            if nxt is None:
                break
            wp = nxt
            approach.append(wp)
            travelled += step
        approach.reverse()

        # Forwards from entry, greedily toward the goal, through the junction.
        through: list[carla.Waypoint] = [entry]
        wp = entry
        goal_loc = goal.transform.location
        for _ in range(int(200 / step)):
            nxts = wp.next(step)
            if not nxts:
                break
            wp = min(nxts, key=lambda w: w.transform.location.distance(goal_loc))
            through.append(wp)
            if wp.transform.location.distance(goal_loc) < step:
                break

        # Continue past the junction so the ego has somewhere to settle (P4).
        tail: list[carla.Waypoint] = []
        wp = through[-1]
        travelled = 0.0
        while travelled < exit_m:
            nxts = wp.next(step)
            if not nxts:
                break
            wp = nxts[0]
            tail.append(wp)
            travelled += step

        route = approach + through + tail
        if len(route) < 10:
            raise RuntimeError(
                f"Route planning produced only {len(route)} waypoints -- "
                "too short to be a real manoeuvre."
            )
        return route

    # ================================================================
    # Hardcoded left-turn controller
    # ================================================================
    # Placeholder for the behaviour tree. Lateral control is a fixed
    # pure-pursuit path follower -- the path is not what the experiment
    # varies. LONGITUDINAL control is the decision logic, and it is
    # longitudinal control that the BT will replace on 24 Aug.
    #
    # Deliberately simple and deliberately imperfect. Calibrating it to fail
    # on 20-40% of scenarios is tomorrow's job (a known trap); today
    # it exists only to produce a real trajectory.
    # ================================================================

    def _advance_and_steer(self, ego, route, idx, ctrl_cfg) -> tuple:
        """Route index advance + pure-pursuit steering.

        Shared by the behaviour tree and the hardcoded placeholder controller.
        LATERAL CONTROL IS NOT WHAT THE EXPERIMENT VARIES -- the path through
        the junction is fixed. The tree owns the LONGITUDINAL decision, which
        is what the contracts score.
        """
        tr = ego.get_transform()
        loc = tr.location
        vel = ego.get_velocity()
        speed = math.sqrt(vel.x ** 2 + vel.y ** 2)

        while idx < len(route) - 1:
            d_here = route[idx].transform.location.distance(loc)
            d_next = route[idx + 1].transform.location.distance(loc)
            if d_next < d_here:
                idx += 1
            else:
                break

        lookahead = ctrl_cfg["lookahead_min_m"] + ctrl_cfg["lookahead_k"] * speed
        j = idx
        while (j < len(route) - 1
               and route[j].transform.location.distance(loc) < lookahead):
            j += 1
        target = route[j].transform.location

        yaw = math.radians(tr.rotation.yaw)
        dx, dy = target.x - loc.x, target.y - loc.y
        fwd = dx * math.cos(yaw) + dy * math.sin(yaw)
        lat = -dx * math.sin(yaw) + dy * math.cos(yaw)
        alpha = math.atan2(lat, max(fwd, 1e-3))
        steer = max(-1.0, min(1.0, alpha / ctrl_cfg["steer_normaliser_rad"]))
        return idx, steer, speed

    def _phase_for(self, idx, sc, world) -> str:
        """Manoeuvre phase P1-P4, recorded as it happens (schema `phase`)."""
        entry = int(sc["controller"]["junction_entry_idx"])
        exit_ = int(sc["controller"]["junction_exit_idx"])
        if idx >= exit_:
            return "P4_settle"
        if idx >= entry:
            return "P3_commit"
        if world.dist_to_stopline_m <= float(sc["controller"]["yield_zone_m"]):
            return ("P2_yield_hold" if world.ego_v_mps < 0.5
                    else "P2_yield_clear")
        return "P1_approach"

    def _control(self, ego, route, idx, ctrl_cfg, oncoming_ttc_s) -> tuple:
        """Hardcoded placeholder controller. Superseded by the tree."""
        idx, steer, speed = self._advance_and_steer(ego, route, idx, ctrl_cfg)
        tr = ego.get_transform()

        # --- longitudinal: the decision logic ----------------------------
        entry_idx = ctrl_cfg["junction_entry_idx"]
        dist_to_entry = (entry_idx - idx) * ctrl_cfg["route_step_m"]

        if idx >= ctrl_cfg["junction_exit_idx"]:
            phase = "P4_settle"
            v_target = ctrl_cfg["v_cruise_mps"]
        elif idx >= entry_idx:
            phase = "P3_commit"
            v_target = ctrl_cfg["v_turn_mps"]
        elif dist_to_entry <= ctrl_cfg["yield_zone_m"]:
            # At the stop line. This is the yield decision -- the single
            # branch the behaviour tree will own tomorrow.
            if oncoming_ttc_s >= ctrl_cfg["tau_yield_s"]:
                phase = "P2_yield_clear"
                v_target = ctrl_cfg["v_turn_mps"]
            else:
                phase = "P2_yield_hold"
                v_target = 0.0
        else:
            phase = "P1_approach"
            v_target = ctrl_cfg["v_cruise_mps"]

        err = v_target - speed
        if err > 0:
            throttle = min(ctrl_cfg["throttle_max"], ctrl_cfg["kp_throttle"] * err)
            brake = 0.0
        else:
            throttle = 0.0
            brake = min(ctrl_cfg["brake_max"], -ctrl_cfg["kp_brake"] * err)
        if v_target == 0.0 and speed < 0.2:
            throttle, brake = 0.0, ctrl_cfg["brake_max"]

        # Actuator slew limiting. A real brake cannot go 0 -> full in 50 ms,
        # and the unlimited version was commanding exactly that (measured:
        # 2 single-tick jumps of 1.00 in one episode). Rate limiting is both
        # more physical and necessary for C5 to measure the program's comfort
        # choices rather than a step input.
        prev_t = self._prev_control[0]
        prev_b = self._prev_control[1]
        max_dt_ = float(ctrl_cfg["throttle_rate_per_tick"])
        max_db_ = float(ctrl_cfg["brake_rate_per_tick"])
        throttle = max(prev_t - max_dt_, min(prev_t + max_dt_, throttle))
        brake = max(prev_b - max_db_, min(prev_b + max_db_, brake))
        self._prev_control = (throttle, brake)

        return (
            carla.VehicleControl(
                throttle=float(throttle), brake=float(brake), steer=float(steer)
            ),
            idx,
            phase,
        )


    def load_program(self, path) -> "object":
        """Parse, validate and compile a .bt program for this backend to run.

        Returns the BehaviourProgram. A program that fails validation is NOT
        loaded and NOT run: malformed output is a distinct outcome from unsafe
        output and must never be pooled with it (project rule 3).
        """
        from program_parser import BehaviourProgram
        src = pathlib.Path(path).read_text()
        prog = BehaviourProgram(src)
        if not prog.usable:
            raise ValueError(
                "program failed validation:\n  " +
                "\n  ".join(prog.validation.errors))
        self.program = prog
        return prog

    # ================================================================
    # Behaviour-tree control
    # ================================================================

    def _load_control_map(self) -> dict:
        if self._control_map is None:
            import json as _json
            p = REPO_ROOT / "data" / "results" / "control_map.json"
            if not p.exists():
                raise FileNotFoundError(
                    f"missing {p} -- run scripts/calibrate_control_map.py. "
                    "The tree's chosen accel/decel cannot be converted to "
                    "control without the measured map, and guessing it would "
                    "make C5 meaningless.")
            self._control_map = _json.loads(p.read_text())
        return self._control_map

    def _command_to_control(self, cmd, speed: float, dt: float, ctrl_cfg) -> tuple:
        """Turn the tree's ControlCommand into throttle/brake.

        The tree chooses a target speed AND an acceleration limit. The limit is
        what makes C5 measure the PROGRAM: a_cmd follows the tree's chosen ramp
        rather than a fixed harness gain, so choosing a harsh stop and choosing
        a gentle one are different programs with different rho_5.

        Inverts the MEASURED map a_cmd = k_t*throttle - k_b*brake + a0.
        """
        cm = self._load_control_map()
        k_t = float(cm["k_throttle_mps2"])
        k_b = float(cm["k_brake_mps2"])
        a0 = float(cm["a_coast_mps2"])

        limit = max(1e-3, float(cmd.accel_limit_mps2))
        a_des = (float(cmd.target_v_mps) - speed) / dt
        a_des = max(-limit, min(limit, a_des))

        self._last_cmd_accel = a_des
        if a_des >= a0:
            throttle, brake = (a_des - a0) / k_t, 0.0
        else:
            throttle, brake = 0.0, (a0 - a_des) / k_b
        throttle = max(0.0, min(1.0, throttle))
        brake = max(0.0, min(1.0, brake))

        # Actuator slew (physics, not comfort -- see config/sim.yaml).
        pt, pb = self._prev_control
        mt = float(ctrl_cfg["throttle_rate_per_tick"])
        mb = float(ctrl_cfg["brake_rate_per_tick"])
        throttle = max(pt - mt, min(pt + mt, throttle))
        brake = max(pb - mb, min(pb + mb, brake))
        self._prev_control = (throttle, brake)
        return throttle, brake

    def _build_world_view(self, ego, route, idx, junction, sc, ttc, t_s,
                          stationary_s):
        """Ground-truth state handed to the tree. Typed, named by unit."""
        from program_parser import WorldView
        tr = ego.get_transform()
        loc = tr.location
        vel = ego.get_velocity()
        speed = math.sqrt(vel.x ** 2 + vel.y ** 2)

        stop = junction["ego_approach"]
        d_stop = math.hypot(loc.x - stop["x"], loc.y - stop["y"])
        # Signed: negative once the ego is past the stop line, which the DSL's
        # DistanceToStopLineBelow relies on.
        entry_idx = int(sc["approach_m"] / sc["route_step_m"])
        if idx >= entry_idx:
            d_stop = -d_stop

        c = junction["junction_center"]
        d_cz = math.hypot(loc.x - c["x"], loc.y - c["y"])
        radius = float(self.contracts["C2_yield"]["conflict_zone_radius_m"])

        # free distance along the remaining route before the nearest actor
        clear = float(sc.get("path_clear_max_m", 100.0))
        for a in self.world.get_actors().filter("vehicle.*"):
            if a.id == ego.id:
                continue
            al = a.get_transform().location
            for k in range(idx, min(idx + int(clear / sc["route_step_m"]), len(route))):
                wl = route[k].transform.location
                if wl.distance(al) < float(sc.get("path_clear_halfwidth_m", 2.5)):
                    clear = min(clear, (k - idx) * float(sc["route_step_m"]))
                    break

        tl_state = str(ego.get_traffic_light_state())
        return WorldView(
            t_s=t_s,
            ego_v_mps=speed,
            dist_to_stopline_m=d_stop,
            oncoming_gap_s=ttc,
            in_conflict_zone=(d_cz <= radius),
            light_is_green=("Green" in tl_state),
            path_clear_dist_m=clear,
            stationary_time_s=stationary_s,
            route_complete=(idx >= len(route) - 2),
        )

    # ================================================================
    # The episode. THE wrapped unit of work.
    # ================================================================

    def run_episode(self, params: dict, episode_id: str | None = None) -> EpisodeResult:
        """Run one scenario. NEVER raises -- failures come back as a sentinel.

        This is the blackbox interface: parameters in, trajectory out.
        """
        ph = param_hash(params)
        episode_id = episode_id or f"ep_{ph}"
        t0 = time.perf_counter()
        result = EpisodeResult(
            episode_id=episode_id, status=ts.STATUS_EXCEPTION,
            param_hash=ph, scenario_params=dict(params),
        )
        try:
            result = self._run_episode_inner(params, episode_id, result, t0)
        except KeyboardInterrupt:
            raise
        except Exception:
            # Sentinel, not a crash. Losing run 47 of 200 must not cost the
            # campaign. The full traceback is preserved for diagnosis.
            result.status = ts.STATUS_EXCEPTION
            result.error = traceback.format_exc()
        finally:
            # Actors are destroyed whatever happened, including on an
            # exception thrown midway through spawning.
            try:
                self._destroy_spawned()
            except Exception as e:
                result.error = (result.error or "") + f"\n[cleanup failed: {e}]"
            result.wall_clock_s = time.perf_counter() - t0
            dt = self.cfg["timing"]["fixed_delta_seconds"]
            result.real_time_factor = (
                (result.n_ticks * dt) / result.wall_clock_s
                if result.wall_clock_s > 0 else 0.0
            )
        return result

    def _run_episode_inner(self, params, episode_id, result, t0) -> EpisodeResult:
        cfg, dt = self.cfg, self.cfg["timing"]["fixed_delta_seconds"]
        horizon = float(cfg["timing"]["episode_horizon_s"])
        max_ticks = int(round(horizon / dt))

        # --- world reload, then reseed (CARLA docs demand this order) -----
        if cfg["world"]["reload_between_episodes"]:
            self.world = self.client.reload_world(False)
            self._apply_sim_settings()
            self._apply_weather()
        seeds = self._seed_everything()

        junction = self.discover_left_turn_junction()
        light_ids = self.set_permissive_green(junction)
        sc = cfg["scenario"]
        route = self.plan_left_turn_route(
            junction, sc["approach_m"], sc["exit_m"], sc["route_step_m"]
        )
        entry_idx = int(sc["approach_m"] / sc["route_step_m"])

        bp_lib = self.world.get_blueprint_library()
        ego_bp = bp_lib.find(sc["ego_blueprint"])
        ego_bp.set_attribute("role_name", "ego")

        # --- spawn ego ----------------------------------------------------
        spawn_wp = route[0]
        spawn_tf = carla.Transform(
            spawn_wp.transform.location + carla.Location(z=sc["spawn_z_offset_m"]),
            spawn_wp.transform.rotation,
        )
        ego = self.world.try_spawn_actor(ego_bp, spawn_tf)
        if ego is None:
            result.status = ts.STATUS_SPAWN_FAILED
            result.error = f"ego spawn failed at {spawn_tf.location}"
            return result
        self._spawned.append(ego.id)

        # --- spawn oncoming vehicles -------------------------------------
        self._ego = ego
        self._oncoming_state = {}
        actor_roles: dict[int, str] = {ego.id: "ego"}
        # Stable per-episode ordering key: (role rank, spawn index). Assigned
        # at spawn time so it does not depend on CARLA actor ids.
        actor_order: dict[int, tuple] = {}
        oncoming = self._spawn_oncoming(junction, params, sc, bp_lib,
                                        actor_roles, actor_order)
        n_spawned = len(oncoming)   # BEFORE retirement mutates the list

        # --- spawn lead vehicle (C4) --------------------------------------
        self._lead_state = {}
        self._light_t0 = None
        lead = self._spawn_lead(junction, params, sc, bp_lib, route, entry_idx,
                                actor_roles, actor_order)

        # --- collision sensor --------------------------------------------
        collided = {"hit": False}
        col_bp = bp_lib.find("sensor.other.collision")
        col = self.world.spawn_actor(col_bp, carla.Transform(), attach_to=ego)
        self._spawned.append(col.id)
        col.listen(lambda e: collided.__setitem__("hit", True))
        self._sensors.append(col)

        # Settle physics before t=0 so the first rows are not spawn transients.
        for _ in range(int(sc["settle_ticks"])):
            self.world.tick()

        # --- main loop ----------------------------------------------------
        rows: list[dict] = []
        phases_seen: set[str] = set()
        self._prev_control = (0.0, 0.0)
        stationary_s = 0.0
        idx = 0
        prev_accel_long = None
        t_first = None
        status = ts.STATUS_TIMEOUT

        achieved_gap_s = None
        for _tick in range(max_ticks):
            # Simulated time BEFORE this tick advances the world. The
            # determinism gate verified consecutive t_s spacing is exactly
            # float32(0.05) with 0.000e+00 deviation, so tick index times dt
            # is the same clock the trace records -- and unlike
            # snapshot.elapsed_seconds it is available before the tick.
            sim_t = _tick * dt
            self._apply_aggressiveness(oncoming, junction, params, sc)
            self._apply_lead_profile(lead, junction, sc)
            self._apply_light_schedule(params, sc, sim_t, junction)
            self.world.tick()
            snap = self.world.get_snapshot()

            ttc = self._oncoming_ttc(ego, oncoming, junction)

            if self.program is not None:
                # --- behaviour tree drives ------------------------------
                idx, steer, speed = self._advance_and_steer(
                    ego, route, idx, sc["controller"])
                t_now = (snap.timestamp.elapsed_seconds - t_first) if t_first is not None else 0.0
                stationary_s = stationary_s + dt if speed < 0.2 else 0.0
                world = self._build_world_view(
                    ego, route, idx, junction, sc, ttc, t_now, stationary_s)
                cmd = self.program.tick(world)
                throttle, brake = self._command_to_control(
                    cmd, speed, dt, sc["controller"])
                control = carla.VehicleControl(
                    throttle=float(throttle), brake=float(brake),
                    steer=float(steer))
                blame = self.program.blame()
                blame["cmd_accel_mps2"] = self._last_cmd_accel
                phase = self._phase_for(idx, sc, world)
            else:
                control, idx, phase = self._control(
                    ego, route, idx, sc["controller"], ttc)
                blame = {"bt_node_id": None, "bt_node_type": None,
                         "bt_node_path": None, "bt_tick_path": None,
                         "cmd_accel_mps2": None}
            ego.apply_control(control)

            row, prev_accel_long, t_first = self._sample_row(
                snap, ego, control, actor_roles, actor_order,
                prev_accel_long, t_first, dt
            )
            row["phase"] = phase
            row.update(blame)
            phases_seen.add(phase)
            # The ACHIEVED gap: time-to-conflict-zone of the nearest oncoming
            # vehicle at the instant the ego first takes its yield decision.
            # This is the physically meaningful quantity the certificate
            # reports; `headway` is only the knob that aims at it. Logging it
            # makes a drift between knob and outcome visible rather than
            # silent -- which is exactly how the old headway bug survived.
            if achieved_gap_s is None and phase.startswith("P2"):
                achieved_gap_s = float(ttc)
            ts.validate_row(row)
            rows.append(row)

            # Retire oncoming vehicles once they are well past the conflict
            # zone. They have left the scenario and contribute nothing to C1
            # or C2 from there on, but they keep driving until they hit the
            # map boundary and wreck -- and WRECK DYNAMICS ARE THE ONE THING
            # THAT WAS NOT REPRODUCING. Measured: with a persistent server,
            # consecutive episodes alternated between two post-crash states
            # (runs 0/2/4 identical, runs 1/3 identical), differing only in
            # actor_yaw_deg on the last 3 of 508 rows. Retiring them removes
            # the nondeterminism at its source instead of masking it, and
            # saves simulation.
            oncoming = self._retire_departed(oncoming, junction, sc,
                                             actor_roles, actor_order)

            if collided["hit"]:
                status = ts.STATUS_COLLISION
                break
            if idx >= len(route) - 2:
                status = ts.STATUS_OK
                break

        result.status = status
        result.n_ticks = len(rows)
        result.meta = {
            "seeds": seeds,
            "junction_id": junction["junction_id"],
            "traffic_lights": light_ids,
            "phase_final": rows[-1]["phase"] if rows else None,
            "phases_reached": sorted(phases_seen),
            "route_len": len(route),
            "entry_idx": entry_idx,
            "achieved_gap_s": achieved_gap_s,
            "spawn_clamped": bool(self._spawn_clamped),
            "n_oncoming_spawned": n_spawned,
            "n_oncoming_surviving": len(oncoming),
        }
        result.trace_path = str(
            self._write_trace(episode_id, rows, result, seeds, junction)
        )
        return result

    def _spawn_oncoming(self, junction, params, sc, bp_lib, actor_roles,
                        actor_order) -> list:
        """Spawn oncoming vehicles per the scenario parameters.

        HEADWAY PHASING -- fixed 24 Aug. The previous rule was

            d_i = oncoming_spawn_back_m + i * max(headway * v, min_gap)

        in which the i = 0 term VANISHES, so the lead vehicle always spawned at
        a fixed 60 m regardless of headway. Measured over 300 traces: the lead
        vehicle's distance to the conflict zone had a standard deviation of
        1.64 m, corr(headway, lead_distance) = -0.067, and in 93 of those
        traces n_oncoming = 1, where headway was provably inert. The gap the
        ego actually faced was set by v_oncoming alone -- which is exactly why
        v_oncoming correlated +0.669 with rho and headway -0.039. They were not
        two parameters; they were one parameter and a no-op.

        The lead vehicle is now phased against the EGO's arrival:

            d_0 = v_oncoming * (t_ego_to_decision + headway)

        so that `headway` IS the time-to-conflict-zone the ego faces when it
        takes its yield decision -- the determining variable for the manoeuvre,
        and directly comparable with tau_yield. Spec 6 leaves headway[0]
        undefined (there is no preceding vehicle for i = 0); this is the
        natural reading of that slot.

        Following vehicles keep the spec's meaning: gap to the preceding
        vehicle, i.e. headway * v behind the one in front.

        `t_ego_to_decision` is a CALIBRATED CONSTANT, measured at 4.950 s with
        standard deviation 0.000 over 300 traces. It must be re-measured when
        the behaviour tree takes over the approach -- the achieved gap is
        logged per episode as `achieved_gap_s` so a drift is visible rather
        than silent.
        """
        cmap = self.world.get_map()
        # The oncoming corridor, resolved at discovery time as the controlled
        # approach ~180 deg opposed to the ego's. See discover_left_turn_junction.
        opposite = _wp_from_record(cmap, junction["oncoming_approach"])

        n = int(params.get("n_oncoming", 1))
        v = float(params.get("v_oncoming", 10.0))
        headway = float(params.get("headway", 3.0))
        t_ego = float(sc["t_ego_to_decision_s"])
        max_back = float(sc["oncoming_max_spawn_back_m"])

        # Distance from the CONFLICT ZONE, converted below to a distance back
        # from the oncoming stop line.
        d_lead_cz = v * (t_ego + headway)
        stopline_to_cz = float(sc["oncoming_stopline_to_cz_m"])

        out = []
        self._spawn_clamped = False
        for i in range(n):
            d_cz = d_lead_cz + i * max(headway * v, sc["oncoming_min_gap_m"])
            d = max(d_cz - stopline_to_cz, sc["oncoming_min_gap_m"])
            if d > max_back:
                # Clamped rather than silently failing to spawn. The achieved
                # gap is logged, so a clamped scenario is identifiable and can
                # be excluded from boundary search rather than corrupting it.
                d = max_back
                self._spawn_clamped = True
            wp = _walk_straight(opposite, d, backwards=True)
            if wp is None:
                continue
            bp = bp_lib.find(sc["oncoming_blueprint"])
            bp.set_attribute("role_name", f"oncoming_{i}")
            tf = carla.Transform(
                wp.transform.location + carla.Location(z=sc["spawn_z_offset_m"]),
                wp.transform.rotation,
            )
            a = self.world.try_spawn_actor(bp, tf)
            if a is None:
                continue
            self._spawned.append(a.id)
            actor_roles[a.id] = "oncoming"
            actor_order[a.id] = (0, i)   # role rank 0 = oncoming, spawn index i
            # Constant-velocity: deterministic and exactly matches the
            # v_oncoming parameter the certificate will report. The Traffic
            # Manager would introduce its own controller dynamics between
            # the parameter and the observed speed.
            fwd = wp.transform.get_forward_vector()
            a.enable_constant_velocity(carla.Vector3D(fwd.x * v, fwd.y * v, 0.0))
            self._oncoming_state[a.id] = {
                "v_nominal": v,
                "v_current": v,
                "fwd": (float(fwd.x), float(fwd.y)),
            }
            out.append(a)
        return out

    def _spawn_lead(self, junction, params, sc, bp_lib, route, entry_idx,
                    actor_roles, actor_order):
        """Spawn one lead vehicle AHEAD of the ego, in the ego's own lane.

        C4 (RSS longitudinal safe distance) is vacuous without one. The lead is
        ALWAYS PRESENT and parameterised by a continuous `lead_gap_s`, rather
        than being gated by a binary `lead_present`. That follows the precedent
        set for the pedestrian in spec v2 6.1: keeping only the continuous
        quantity removes a binary factor while preserving the interaction that
        actually stresses the manoeuvre. It also keeps boundary search
        well-defined -- a boolean axis cannot be binary-searched, and boundary
        search is a non-negotiable property of the certificate (7.2).

        Initial separation is `lead_gap_s * v_approach`, i.e. a TIME gap, so
        the parameter is directly comparable with tau_resp and reads the same
        way in a certificate as `headway` does for C2.

        BEHAVIOUR: the lead decelerates to a stop at the stop line and holds,
        which is what a vehicle ahead of the ego at an unprotected left actually
        does -- it is waiting for the same gap. A constant-velocity lead would
        simply outrun the ego during the yield hold and C4 would never bind.
        Deceleration is bounded by the same plausibility ceiling as every other
        non-ego actor (spec 6.2), so the falsifier cannot buy a C4 violation
        with physically absurd braking.
        """
        gap_s = params.get("lead_gap_s")
        if gap_s is None:
            return None                 # C4 reports vacuous
        v_app = float(sc["lead_approach_speed_mps"])
        d_ahead = float(gap_s) * v_app

        # Walk FORWARD along the ego route from the ego spawn point.
        step = float(sc["route_step_m"])
        idx = int(round(d_ahead / step))
        if idx >= len(route):
            idx = len(route) - 1
        wp = route[idx]

        # DIRECTION OF TRAVEL comes from the route tangent, NOT from
        # wp.transform.rotation. Measured 30 Aug: the waypoint rotation on this
        # approach points AWAY from the junction, so a lead spawned with it
        # drove backwards into the ego and every episode ended in a rear-end
        # collision at ~1.6 s (lead distance to the conflict zone went
        # 35.5 -> 39.5 -> 48.6 m while the ego stood still). The tangent
        # between consecutive route waypoints is the direction the EGO
        # actually travels, which is the only direction that makes the lead a
        # lead rather than an oncoming vehicle.
        nxt = route[min(idx + 1, len(route) - 1)]
        prv = route[max(idx - 1, 0)]
        tx = nxt.transform.location.x - prv.transform.location.x
        ty = nxt.transform.location.y - prv.transform.location.y
        tnorm = math.hypot(tx, ty)
        if tnorm < 1e-6:
            return None
        tx, ty = tx / tnorm, ty / tnorm

        bp = bp_lib.find(sc.get("lead_blueprint", sc["oncoming_blueprint"]))
        bp.set_attribute("role_name", "lead")
        yaw_deg = math.degrees(math.atan2(ty, tx))
        rot = carla.Rotation(pitch=0.0, yaw=yaw_deg, roll=0.0)
        tf = carla.Transform(
            wp.transform.location + carla.Location(z=sc["spawn_z_offset_m"]),
            rot,
        )
        a = self.world.try_spawn_actor(bp, tf)
        if a is None:
            return None
        self._spawned.append(a.id)
        actor_roles[a.id] = "lead"
        actor_order[a.id] = (1, 0)      # role rank 1 = lead, after oncoming
        # enable_constant_velocity() TAKES A LOCAL-FRAME VECTOR, not a world
        # one. Measured 30 Aug: passing the world tangent (-1.000, -0.002) with
        # the actor spawned at yaw 180 deg produced a world velocity of
        # (+8.00, +0.02) -- exactly negated -- and the lead reversed into the
        # ego, ending every episode in a rear-end collision at ~1.3 s. Since
        # the spawn rotation is set from the tangent above, "forward at v_app"
        # is simply (v_app, 0, 0) in the actor's own frame.
        #
        # NOTE for _spawn_oncoming: it passes a world vector too, and is
        # currently correct ONLY because the oncoming approach lies at yaw ~= 0,
        # where local and world coincide. That is luck, not design. It is left
        # alone deliberately -- changing it would invalidate 480 validated
        # traces -- but it will break on any junction whose oncoming lane is
        # not axis-aligned.
        a.enable_constant_velocity(carla.Vector3D(v_app, 0.0, 0.0))
        self._lead_state[a.id] = {
            "v_nominal": v_app,
            "v_current": v_app,
            "fwd": (tx, ty),
            "dwell_s": 0.0,
            "resumed": False,
        }
        return a

    def _apply_lead_profile(self, lead, junction, sc) -> None:
        """Decelerate the lead to a stop at the stop line, then hold.

        Deterministic: the decision depends only on the lead's own distance to
        the conflict zone, which is itself deterministic.
        """
        if lead is None or not lead.is_alive:
            return
        st = self._lead_state.get(lead.id)
        if st is None:
            return
        c = junction["junction_center"]
        dt = float(self.cfg["timing"]["fixed_delta_seconds"])
        a_dec = float(sc["lead_max_decel_mps2"])
        hold_m = float(sc["lead_stop_before_cz_m"])

        dwell_limit = float(sc["lead_dwell_s"])

        loc = lead.get_transform().location
        d_cz = math.hypot(loc.x - c["x"], loc.y - c["y"])

        # THE LEAD MUST EVENTUALLY CLEAR. A lead that stops at the line and
        # holds forever blocks the ego permanently, which would drive ICR to
        # zero in every episode and make the whole scenario unrunnable -- the
        # program would be measured on a task it cannot complete regardless of
        # its quality. So: decelerate to the line, dwell (this is the interval
        # during which C4 bites hardest, because the ego is closing on a
        # stationary vehicle), then resume and drive on through.
        if st["resumed"]:
            st["v_current"] = min(st["v_nominal"], st["v_current"] + a_dec * dt)
        elif d_cz <= hold_m:
            st["v_current"] = max(0.0, st["v_current"] - a_dec * dt)
            if st["v_current"] <= 0.05:
                st["dwell_s"] += dt
                if st["dwell_s"] >= dwell_limit:
                    st["resumed"] = True

        # Local frame -- see the note in _spawn_lead. The lead's yaw is fixed
        # at spawn and it travels straight, so local +x is always its heading.
        lead.enable_constant_velocity(
            carla.Vector3D(st["v_current"], 0.0, 0.0))

    def _apply_aggressiveness(self, oncoming, junction, params, sc) -> None:
        """Oncoming vehicles decelerate for the ego, per `aggressiveness`.

        aggressiveness = 1.0 -> will not yield at all, holds v_oncoming
        aggressiveness = 0.0 -> yields fully, decelerating at the plausibility
                                ceiling

        Restored 24 Aug. Without it the falsifier searches a space in which
        only v_oncoming carries signal, which makes boundary search degenerate:
        every counterexample boundary collapses onto one axis.

        Deceleration is bounded by the plausibility constraints in spec 6
        (|a| <= 4.0 m/s^2 for non-ego actors), so the falsifier cannot buy a
        violation with physically absurd behaviour -- the AdvSim failure mode.

        Deterministic: the decision depends only on positions and the fixed
        parameter, both of which are themselves deterministic.
        """
        agg = float(params.get("aggressiveness", 1.0))
        if agg >= 1.0 or not oncoming:
            return
        c = junction["junction_center"]
        trigger_m = float(sc["aggressiveness_trigger_m"])
        a_max = float(sc["aggressiveness_max_decel_mps2"]) * (1.0 - agg)
        dt = float(self.cfg["timing"]["fixed_delta_seconds"])

        ego = self._ego
        if ego is None or not ego.is_alive:
            return
        eloc = ego.get_transform().location
        ego_near_cz = math.hypot(eloc.x - c["x"], eloc.y - c["y"]) <= trigger_m

        for a in oncoming:
            if not a.is_alive:
                continue
            st = self._oncoming_state.get(a.id)
            if st is None:
                continue
            loc = a.get_transform().location
            d_cz = math.hypot(loc.x - c["x"], loc.y - c["y"])
            approaching = d_cz <= trigger_m * 2.0
            if ego_near_cz and approaching:
                st["v_current"] = max(0.0, st["v_current"] - a_max * dt)
            else:
                st["v_current"] = min(st["v_nominal"], st["v_current"] + a_max * dt)
            fx, fy = st["fwd"]
            a.enable_constant_velocity(
                carla.Vector3D(fx * st["v_current"], fy * st["v_current"], 0.0))

    def _retire_departed(self, oncoming, junction, sc, actor_roles,
                         actor_order) -> list:
        """Destroy oncoming vehicles that are far past the conflict zone.

        Returns the surviving list. Deterministic: the decision depends only
        on the vehicle's own position, which is itself deterministic.
        """
        limit = float(sc.get("oncoming_retire_past_cz_m", 80.0))
        c = junction["junction_center"]
        keep = []
        for a in oncoming:
            if not a.is_alive:
                continue
            loc = a.get_transform().location
            d = math.hypot(loc.x - c["x"], loc.y - c["y"])
            fwd = a.get_transform().get_forward_vector()
            # departing = beyond the limit AND heading away from the centre
            departing = (d > limit and
                         ((loc.x - c["x"]) * fwd.x + (loc.y - c["y"]) * fwd.y) > 0)
            if departing:
                aid = a.id
                with contextlib.suppress(Exception):
                    a.destroy()
                if aid in self._spawned:
                    self._spawned.remove(aid)
                actor_roles.pop(aid, None)
                actor_order.pop(aid, None)
            else:
                keep.append(a)
        return keep


    def _oncoming_ttc(self, ego, oncoming, junction) -> float:
        """Minimum time for any oncoming vehicle to reach the conflict zone.

        Today the conflict zone is approximated by the junction centre. The
        real polygon lands 24 Aug with junction.yaml.
        """
        c = junction["junction_center"]
        cz = carla.Location(x=c["x"], y=c["y"], z=c["z"])
        cap = float(self.contracts["C2_yield"]["ttc_cap_s"])
        vmin = float(self.contracts["C2_yield"]["min_speed_for_ttc_mps"])

        best = cap
        for a in oncoming:
            if not a.is_alive:
                continue
            v = a.get_velocity()
            sp = math.sqrt(v.x ** 2 + v.y ** 2)
            if sp < vmin:
                continue        # not approaching; contributes no constraint
            d = a.get_transform().location.distance(cz)
            best = min(best, min(d / sp, cap))
        return best

    def _sample_row(self, snap, ego, control, actor_roles, actor_order,
                    prev_accel_long, t_first, dt) -> tuple:
        """Build one schema-conforming row from the current world snapshot."""
        row = ts.empty_row()
        stamp = snap.timestamp

        if t_first is None:
            t_first = stamp.elapsed_seconds
        row["frame"] = int(snap.frame)
        row["t_s"] = float(stamp.elapsed_seconds - t_first)
        row["sim_elapsed_s"] = float(stamp.elapsed_seconds)
        row["delta_s"] = float(stamp.delta_seconds)

        tr = ego.get_transform()
        vel = ego.get_velocity()
        acc = ego.get_acceleration()
        bb = ego.bounding_box

        row["ego_x_m"], row["ego_y_m"], row["ego_z_m"] = (
            float(tr.location.x), float(tr.location.y), float(tr.location.z))
        row["ego_yaw_deg"] = float(tr.rotation.yaw)
        row["ego_pitch_deg"] = float(tr.rotation.pitch)
        row["ego_roll_deg"] = float(tr.rotation.roll)
        row["ego_vx_mps"], row["ego_vy_mps"], row["ego_vz_mps"] = (
            float(vel.x), float(vel.y), float(vel.z))
        row["ego_speed_mps"] = float(math.sqrt(vel.x ** 2 + vel.y ** 2))
        row["ego_ax_mps2"], row["ego_ay_mps2"], row["ego_az_mps2"] = (
            float(acc.x), float(acc.y), float(acc.z))

        a_long = _signed_long_accel(acc.x, acc.y, tr.rotation.yaw)
        row["ego_accel_long_mps2"] = float(a_long)
        # NULL on the first sample -- there is no previous measurement, and a
        # fabricated 0.0 would silently enter min() when C5 lands.
        row["ego_jerk_long_mps3"] = (
            None if prev_accel_long is None else float((a_long - prev_accel_long) / dt)
        )

        row["ego_throttle"] = float(control.throttle)
        row["ego_brake"] = float(control.brake)
        row["ego_steer"] = float(control.steer)
        row["ego_extent_x_m"] = float(bb.extent.x)
        row["ego_extent_y_m"] = float(bb.extent.y)
        row["ego_extent_z_m"] = float(bb.extent.z)

        # C3 reads tl_state on EVERY tick, including while the ego is inside
        # the junction -- which is exactly the interval the contract is about.
        # ego.get_traffic_light() returns None once the ego leaves the light's
        # trigger volume, so it was null on 92% of ticks and C3 could never
        # observe a red onset. Read the RESOLVED ego light actor instead; it is
        # held for the whole episode and is the light the scenario controls.
        tl = self._ego_tl
        if tl is not None and tl.is_alive:
            row["tl_state"] = str(tl.get_state())
            row["tl_elapsed_s"] = float(tl.get_elapsed_time())
        else:
            fallback = ego.get_traffic_light()
            if fallback is not None:
                row["tl_state"] = str(ego.get_traffic_light_state())
                row["tl_elapsed_s"] = float(fallback.get_elapsed_time())

        # bt_node_* stay NULL today: the ego is a hardcoded controller, not a
        # tree. Populated from 24 Aug.

        # Canonical ordering. world.get_actors() does NOT guarantee a stable
        # order, and CARLA actor ids are reassigned every episode, so sorting
        # by id is not stable either. Without a canonical order the parallel
        # list columns get PERMUTED between otherwise-identical runs, and an
        # element-wise comparison then reports a deviation of exactly the
        # inter-vehicle spacing -- which looks like a determinism failure but
        # is only a bookkeeping one.
        tracked = [a for a in self.world.get_actors()
                   if a.id != ego.id and a.id in actor_roles]
        tracked.sort(key=lambda a: actor_order.get(a.id, (9, 9)))
        for actor in tracked:
            atr = actor.get_transform()
            av = actor.get_velocity()
            try:
                ext = actor.bounding_box.extent
                ex, ey = float(ext.x), float(ext.y)
            except Exception:
                ex, ey = 0.0, 0.0
            row["actor_id"].append(int(actor.id))
            row["actor_type"].append(str(actor.type_id))
            row["actor_role"].append(actor_roles[actor.id])
            row["actor_x_m"].append(float(atr.location.x))
            row["actor_y_m"].append(float(atr.location.y))
            row["actor_z_m"].append(float(atr.location.z))
            row["actor_yaw_deg"].append(float(atr.rotation.yaw))
            row["actor_vx_mps"].append(float(av.x))
            row["actor_vy_mps"].append(float(av.y))
            row["actor_speed_mps"].append(float(math.sqrt(av.x ** 2 + av.y ** 2)))
            row["actor_extent_x_m"].append(ex)
            row["actor_extent_y_m"].append(ey)

        return row, a_long, t_first

    def _write_trace(self, episode_id, rows, result, seeds, junction) -> pathlib.Path:
        """Write Parquet + sidecar JSON. Checkpoint: one run, not the batch."""
        cols = {name: [r[name] for r in rows] for name in ts.COLUMNS}
        table = pa.Table.from_pydict(cols, schema=ts.TRAJECTORY_SCHEMA)

        p = self.cfg["physics"]
        meta = {
            "episode_id": episode_id,
            "schema_version": ts.SCHEMA_VERSION,
            "status": result.status,
            "scenario_params": json.dumps(result.scenario_params, sort_keys=True),
            "param_hash": result.param_hash,
            "seeds": json.dumps(seeds, sort_keys=True),
            "carla_server_version": self._server_version or "",
            "carla_client_version": self._client_version or "",
            "map": self.cfg["world"]["map"],
            "junction_id": str(junction["junction_id"]),
            "fixed_delta_seconds": str(self.cfg["timing"]["fixed_delta_seconds"]),
            "max_substep_delta_time": str(p["max_substep_delta_time"]),
            "max_substeps": str(p["max_substeps"]),
            "n_ticks": str(len(rows)),
            "achieved_gap_s": str(result.meta.get("achieved_gap_s")),
            "spawn_clamped": str(result.meta.get("spawn_clamped")),
            "wall_clock_s": f"{time.perf_counter():.6f}",
            "git_commit": git_commit() or "",
            "program_source": (self.program.source if self.program else ""),
            "program_sha": (hashlib.sha256(self.program.source.encode()).hexdigest()[:16]
                            if self.program else ""),
        }
        table = table.replace_schema_metadata(
            {k: str(v) for k, v in meta.items()}
        )
        out = self.trace_dir / f"{episode_id}.parquet"
        pq.write_table(
            table, out, compression=self.cfg["logging"]["compression"]
        )
        # Sidecar JSON: survives tools that drop Parquet key-value metadata.
        (self.trace_dir / f"{episode_id}.json").write_text(
            json.dumps({**meta, "result": asdict(result)}, indent=2, default=str)
        )
        return out

# ==========================================================================
# Module-level helpers
# ==========================================================================

def _norm_deg(a: float) -> float:
    """Normalise an angle in degrees to (-180, 180]."""
    while a <= -180.0:
        a += 360.0
    while a > 180.0:
        a -= 360.0
    return a



def _walk_straight(wp: "carla.Waypoint", distance: float, step: float = 2.0,
                   backwards: bool = True) -> "carla.Waypoint | None":
    """Walk `distance` along a lane, always taking the STRAIGHTEST branch.

    CARLA's next()/previous() return a LIST when a lane branches. Taking [0]
    is arbitrary -- and arbitrary is a determinism risk, because nothing
    documents that the list order is stable. It is also semantically wrong
    here: oncoming THROUGH traffic should stay on the through corridor, not
    wander into a turn lane. So at every branch we take the successor whose
    heading deviates least from the current heading.
    """
    travelled = 0.0
    cur = wp
    while travelled < distance:
        hop = min(step, distance - travelled)
        cands = cur.previous(hop) if backwards else cur.next(hop)
        if not cands:
            return None
        yaw = cur.transform.rotation.yaw
        cur = min(cands,
                  key=lambda c: abs(_norm_deg(c.transform.rotation.yaw - yaw)))
        travelled += hop
    return cur


def _wp_record(wp: "carla.Waypoint") -> dict:
    """Serialise a waypoint by its OpenDRIVE identity, not its coordinates.

    road_id/lane_id/s is stable across CARLA restarts; a raw XYZ is not
    guaranteed to snap back to the same lane. This is what makes the cached
    junction reproducible rather than merely recorded.
    """
    t = wp.transform
    return {
        "road_id": int(wp.road_id),
        "lane_id": int(wp.lane_id),
        "s": float(wp.s),
        "x": float(t.location.x),
        "y": float(t.location.y),
        "z": float(t.location.z),
        "yaw_deg": float(t.rotation.yaw),
    }


def _wp_from_record(cmap: "carla.Map", rec: dict) -> "carla.Waypoint":
    return cmap.get_waypoint_xodr(rec["road_id"], rec["lane_id"], rec["s"])
