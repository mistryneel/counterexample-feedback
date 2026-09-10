# Determinism Report — Phase 3 Gate

**Date:** 2026-08-23
**Verdict:** ✅ **PASS** — all six stages
**Executed by:** `scripts/determinism_gate.py --port 2000 --n 5`
**Machine-readable:** `data/results/determinism_gate.json`

Every number below was produced by executing the gate on this machine. Nothing is asserted
that was not run.

---

## Why this gate exists

A determinism or clock issue would quietly corrupt every ρ value downstream without ever
throwing an error. The ablation compares ρ between conditions F1–F4, so run-to-run noise
larger than the between-condition effect makes the entire result meaningless. Catching that
on episode one is far cheaper than after thirty.

---

## Environment under test

| | |
|---|---|
| CARLA server | 0.9.16 in `carlasim/carla:0.9.16`, digest `sha256:aaf1df22702780ece072069e23d03c4879b002ae028c79744b09c4c7ddbae953` |
| CARLA client | `carla==0.9.16`, wheel `cp312-cp312-manylinux_2_31_x86_64` |
| Version match | **Verified by handshake** (`get_client_version()` vs `get_server_version()`), not assumed |
| Map / junction | Town05, junction id **1126**, four traffic lights |
| Left turn | measured `dyaw = -90.42°`, direction **verified empirically** (see §Junction) |
| Gate scenario | `n_oncoming=2, v_oncoming=11.0, headway=3.0, ped_phase_offset=0.0` |
| Episode length | 508 ticks = 25.40 simulated seconds |

---

## 3.1 — Clock integrity ✅ PASS

| Check | Result |
|---|---|
| `delta_s` reported by server | `0.05000000074505806` on every tick |
| `max |delta_s − float32(0.05)|` | **0.000e+00 — BIT-EXACT** |
| `max |delta_s − float64 0.05|` | 7.451e-10 |
| Consecutive `t_s` spacing | max deviation **0.000e+00** from `float32(0.05)` |
| Frames strictly monotonic | **True** |
| Frame gaps (non-unit steps) | **0** |
| Frame duplicates | **0** |
| Ticks logged | 508 (episode ended on route completion, `status=ok`, not timeout) |
| Wall-clock | 0.668 s |
| **Real-time factor** | **38.01** simulated seconds per wall-clock second |

### The float32 finding — a trap worth recording

**CARLA stores `delta_seconds` as a 32-bit float.** The value it reports is therefore
`float32(0.05) = 0.05000000074505806`, not the float64 literal `0.05`.

A naive check of "consecutive timestamps differ by exactly 0.05" tests against the float64
literal and **fails by 7.451e-10 on a perfectly healthy server**. The gate originally did
exactly this. The correct test is against `float32(fixed_delta_seconds)`, and against that
the clock is bit-exact on every tick of every run.

This is representation, not clock drift. Recording it because the failure mode is
insidious in both directions: a strict float64 test cries wolf, while a loose tolerance
(say 1e-3) would mask real drift.

---

## 3.2 — Physics substepping ✅ PASS

Documented condition (CARLA 0.9.16 `adv_synchrony_timestep`, verbatim):

> "The condition to be fulfilled is: `fixed_delta_seconds <= max_substep_delta_time * max_substeps`"
> "The substep delta time should at least be below 0.01666 and ideally below 0.01."

| Source | `fixed_delta_seconds` | `max_substep_delta_time` | `max_substeps` | Product | Holds? |
|---|---|---|---|---|---|
| `config/sim.yaml` | 0.05 | 0.01 | 10 | 0.10 | ✅ 2× headroom |
| **Live server** | 0.05 | 0.01 | 10 | 0.10 | ✅ |

The server is queried directly, not just the config file — what matters is what the server is
actually running with. `scripts/health_check.py` asserts the same condition on every run and
exits non-zero if it is violated.

**CARLA does not raise when this condition is violated.** Physics silently becomes
non-deterministic and every ρ downstream is wrong. That is why it is checked in two places.

---

## 3.3 — ρ sanity, hand-checked ✅ PASS

```
rho = +1.5163   [argmin: C1 @ t=8.350 s, frame=411, row=167]
      C1 = +1.516327043 m      C2 = +3.273874035 s
```

### C1 — worked by hand from the raw log

At the argmin timestep the ego is **stationary at the stop line** (speed 0.000 m/s) while an
oncoming vehicle passes:

| | position | yaw | half-extents |
|---|---|---|---|
| ego | (−27.6754, −91.4353) | −179.91° | (2.396, 1.082) |
| oncoming id=147 | (−32.1426, −87.8461) | +0.06° | (2.1, 0.9) |
| oncoming id=148 | (−65.1390, −87.8920) | +0.07° | (2.1, 0.9) |

- Clearance to id=147 = **+1.516327 m** ← the minimum
- Clearance to id=148 = +33.007054 m
- Centre-to-centre distance = 5.7305 m
- Sum of bounding radii = 4.9450 m
- **Bracket check:** the box clearance must lie between (centre − radii) = **+0.7855** and
  (centre distance) = **+5.7305**. Measured **+1.5163** sits inside. ✅
- Independent recomputation from raw positions: **+1.516327043**, agrees to 1e-9 ✅

**Physical reading:** the ego is stopped at the stop line and an oncoming car passes 1.52 m
away. That is a plausible near-side pass at a junction, and 1.52 m is a believable lateral
gap for a 2.16 m-wide car in an adjacent lane.

### C2 — worked by hand

At t = 15.900 s the ego is **11.9129 m** from the conflict-zone centre (radius 12.0, so the
antecedent `in_conflict_zone` is true):

| oncoming | distance to CZ | speed | TTC |
|---|---|---|---|
| id=148 | 68.7460 m | 10.9575 m/s | 6.2739 s |

- ρ₂ = TTC − τ_yield = 6.273874 − 3.0 = **+3.273874** ✅ matches reported to 1e-9

**Physical reading:** the ego committed to the turn with 6.27 s to the nearest oncoming
vehicle, against a 3.0 s requirement. A margin of +3.27 s is exactly what a correctly
yielding program should produce.

### Independent cross-check via `rtamt`

`rtamt` 0.3.5 re-evaluates `always(x >= 0)` on our predicate signals as a **second,
independent implementation** of the number the whole experiment rests on:

| Contract | ours | rtamt | agree |
|---|---|---|---|
| C1 | +1.516327043 | +1.516327043 | ✅ to 1e-9 |
| C2 | +3.273874035 | +3.273874035 | ✅ to 1e-9 |

### OBB geometry unit tests

`stl.obb_clearance` was tested against 8 hand-computed cases before being trusted, all exact:
axis-aligned separation, exact touching, penetration, lateral separation, full overlap, 90°
rotation, 45° rotation, and **vertex-to-vertex diagonal**. The last matters: the naive
"maximum SAT gap" shortcut returns 0.60 m where the true distance is 0.721110 m — wrong by
0.121 m, which is the same order as the C1 values the paper quotes.

---

## 3.4 — Within-process repeatability ✅ PASS

5 episodes, identical parameters, one process, one persistent client.

| Run | Status | Ticks | Wall | RTF |
|---|---|---|---|---|
| 0 | ok | 508 | 0.53 s | 48.07 |
| 1 | ok | 508 | 0.50 s | 50.33 |
| 2 | ok | 508 | 0.53 s | 47.97 |
| 3 | ok | 508 | 0.52 s | 48.56 |
| 4 | ok | 508 | 0.53 s | 48.31 |

| Metric | Result |
|---|---|
| Trace lengths | [508, 508, 508, 508, 508] — identical |
| **Max absolute deviation, all physics fields** | **0.000e+00 — BIT-IDENTICAL** |
| ρ values | +1.516327043 × 5 |
| **ρ spread** | **0.000e+00** |

---

## 3.5 — Across-process repeatability ✅ PASS

5 episodes, identical parameters, **five separate process launches** — the case that matters
more, because campaigns restart and a bug appearing only across restarts would silently
corrupt half the data while every within-process check passed.

| Launch | Exit | Ticks | RTF |
|---|---|---|---|
| 0 | 0 | 508 | 46.75 |
| 1 | 0 | 508 | 45.47 |
| 2 | 0 | 508 | 48.74 |
| 3 | 0 | 508 | 48.54 |
| 4 | 0 | 508 | 48.79 |

| Metric | Result |
|---|---|
| Trace lengths | [508] × 5 — identical |
| **Max absolute deviation, all physics fields** | **0.000e+00 — BIT-IDENTICAL** |
| **ρ spread** | **0.000e+00** |

### Physics vs bookkeeping columns

Three columns are **absolute server counters** and are reported but not gated on:

| Column | Deviation (3.5) | Why it legitimately differs |
|---|---|---|
| `frame` | 2.680e+03 | Monotonic server frame counter; keeps advancing across episodes on a persistent server. 3.1 checks its *internal* consistency, which is the property that matters |
| `sim_elapsed_s` | 1.056e+02 | Same — absolute server clock, not reset per episode |
| `actor_id` | 1.600e+01 | CARLA reassigns actor ids on every spawn |

Everything else — positions, velocities, accelerations, controls, `t_s`, `delta_s`, `phase`,
`tl_state` — is physics and reproduces bit-exactly.

---

## 3.6 — Seed sensitivity ✅ PASS (with an important caveat)

Run **across full server restarts** by `scripts/seed_sensitivity.py`, which never imports
`carla` (see §Traps). Within a single process the test would be confounded, because
`reload_world()` is unusable here and a second probe would inherit world state from the first.

Probe: 8 Traffic-Manager-controlled vehicles at fixed spawn points, 150 ticks, positions
compared element-wise.

| Test | Max positional deviation |
|---|---|
| (a) Same seed (20260823), two fresh servers | **0.000000e+00 m** |
| (b) Different seeds (20260823 vs 20260824), two fresh servers | **0.000000e+00 m** |

### Reading this honestly

The same seed reproduces exactly. **But so do different seeds.** That is consistent with the
seed being ignored entirely and the TM simply being deterministic in this probe. The stage
passes on reproducibility, but **it is not evidence that the TM seed controls anything.**

Both halves were run deliberately. A test asking only (a) would have reported "seeding works"
and been wrong.

### Scope — what this does and does not certify

**The E1 scenario uses no Traffic Manager at all.** Oncoming vehicles are driven by
`enable_constant_velocity` and the ego is under program control. No actor is under TM control,
so in E1 the TM seed governs nothing. That is a determinism **advantage** — an entire
stochastic subsystem is removed from the experiment — not a gap.

The seeding E1 actually depends on is certified by 3.4 and 3.5, which produced bit-identical
trajectories **and** bit-identical ρ from identical parameters, both within a process and
across separate process launches.

---

## 3.7 — Verdict and tolerance

### Tolerances applied

| Quantity | Tolerance | Measured |
|---|---|---|
| Per-field max absolute deviation | 1e-6 | **0.0** |
| Spread in ρ across runs | 1e-6 | **0.0** |

### Justification

A synchronous, fixed-delta simulator replaying identical inputs should reproduce
**bit-identically** — deviation exactly 0.0. That is the standard actually met here, in both
3.4 and 3.5, so the tolerance was never exercised.

The 1e-6 tolerance exists as headroom for float64 accumulation differences without admitting
anything physically meaningful: **1e-6 m is a micrometre; 1e-6 s is a microsecond.** Neither
is observable in a trajectory sampled at 20 Hz with metre-scale contract thresholds.

Divergence in ρ at the second or third decimal would mean ρ values are **not comparable across
runs**. Since the ablation compares ρ between conditions F1–F4, run-to-run noise larger than
the between-condition effect would make the entire experiment meaningless. Measured
run-to-run noise is **zero**, so any observed between-condition difference is signal.

### Verdict

> **GATE VERDICT: PASS** — 3.1 ✅ 3.2 ✅ 3.3 ✅ 3.4 ✅ 3.5 ✅ 3.6 ✅

---

## Measured real-time factor

| Context | RTF (simulated s per wall-clock s) |
|---|---|
| Single episode, cold | 38.01 |
| Within-process, steady state | 47.97 – 50.33 |
| Across-process (incl. interpreter start) | 45.47 – 48.79 |
| **Design figure** | **~40** (conservative) |

Episode throughput, measured on the 300-scenario bank:

| Instances | Episodes | Wall | Aggregate |
|---|---|---|---|
| 1 | 20 | 18.7 s | 1.07 ep/s |
| 3 | 60 | 18.3 s | **3.28 ep/s** |
| 6 | 120 | 36.1 s | 3.32 ep/s (**no gain**) |
| 3 (300-scenario bank) | 300 | 74.2 s | **4.05 ep/s** |

**Scaling saturates at 3 instances. The binding resource is CPU, not VRAM** — each instance
draws ~350% CPU (≈3.5 of 24 threads), so 6 instances saturate the machine (load average 15.4)
while using only 5.8 GB of 24 GB VRAM per GPU and leaving 13 GB of system RAM free.

---

## Problems found and fixed during the gate

Recorded because each was silent, and each would have invalidated results.

### 1. `reload_world()` segfaults CARLA 0.9.16 — **and was costing 70% of throughput**

CARLA died with signal 11 roughly **3–4 s after the client disconnected**, reproducibly.
Isolated by bisection:

| Variant | Outcome |
|---|---|
| Traffic Manager disabled | still died at t+4 s |
| Traffic-light freeze disabled | still died at t+4 s |
| **World reload disabled** | **survived** |

Reload also dropped the real-time factor from ~43 to ~12.5.

The CARLA docs state that reproducible physics requires "world reloading between repetitions".
`config/sim.yaml` now sets `reload_between_episodes: false`, **and determinism without reload
is verified empirically instead of assumed** — 3.4 and 3.5 are bit-identical. Had they failed,
the correct response would have been to restore reload and work around the crash, not to keep
the speed.

### 2. The "oncoming" vehicles were spawning in the ego's own lane

The oncoming corridor was derived from the turn-**exit** waypoint. That waypoint is *inside*
the junction, where `get_left_lane()` and `get_right_lane()` both return `None`, so the
fallback chain `left or right or anchor` silently collapsed to the anchor — the ego's own turn
path. Walking backwards from it put "oncoming" traffic on **road 6 lane −1, the ego's approach
lane**.

ρ₂ would have been measuring yield margin against a car in the ego's own lane, and would have
looked entirely plausible.

Fixed: the oncoming corridor is now resolved as the **controlled approach whose heading is
~180° opposed to the ego's**, recorded in `junction.yaml`. Verified: ego approach road 6 lane
−1 at −179.91°, oncoming approach road 7 lane +1 at +0.09° — exactly 180.00° opposed, stop
lines 39.70 m apart, heading confirmed toward the junction centre.

### 3. Traffic-light actor ids are not stable across world reloads

`junction.yaml` originally cached `traffic_light_ids: [92, 93, 94, 95]`. After a reload the
same lights were ids 198–251, so the cached ids matched nothing — and the first smoke run
**drove through the junction on Red** while the spec requires a permissive green.

Fixed: lights are resolved **by geometry** every episode from the stop-line position recorded
in OpenDRIVE coordinates (which are stable), then ego and oncoming are set Green, cross traffic
Red, and all lights frozen. At discovery the lights were ids 208/206; at run time they resolved
to 325/323 — the same physical lights.

### 4. Non-canonical actor ordering looked exactly like a determinism failure

`world.get_actors()` does not guarantee a stable order, and actor ids change every episode.
The parallel list columns were being permuted between otherwise-identical runs, producing an
`actor_x_m` deviation of **33.01 m — precisely the `headway × v_oncoming` spacing**, i.e. the
two oncoming vehicles swapped places in the list.

Fixed: a stable `(role rank, spawn index)` key assigned at spawn time.

### 5. Wrecked vehicles were the only thing not reproducing

After the ordering fix, one residue remained: runs **{0, 2, 4}** were bit-identical to each
other and runs **{1, 3}** were bit-identical to each other, but the two groups differed — a
period-2 alternation, at **row 505 of 508**, in `actor_yaw_deg` only.

Cause: oncoming vehicles kept driving 142 m past the junction, hit the map boundary, and
wrecked. Post-crash dynamics depended on residual server state.

Fixed at source: `oncoming_retire_past_cz_m: 80.0` destroys an oncoming vehicle once it is 80 m
past the conflict zone and still departing. It cannot influence C1 or C2 from there. After this
change, deviation is 0.000e+00 everywhere.

### 6. A stale `carla.Client` aborts the process when its server dies

Restarting the server while any `carla.Client` is alive causes libcarla's background streaming
thread to throw `carla::client::TimeoutException` from a non-Python context, reaching
`std::terminate` and **aborting with SIGABRT** — not catchable from Python. Dropping the Python
reference and calling `gc.collect()` is **not** sufficient.

Fixed structurally: stage 3.6 lives in `scripts/seed_sensitivity.py`, a program that never
imports `carla` and only orchestrates subprocesses; and the gate runs 3.6 **first**, before it
has ever connected.

### 7. `stop_carla.sh` killed every CARLA instance, not just the target

The SIGKILL escalation block re-ran `pgrep -f CarlaUE4-Linux-Shipping` and killed everything it
found, ignoring the port filter that the SIGTERM pass had correctly applied. Observed:
`stop_carla.sh --port 2050` left three unrelated containers at **Exited (137)**.

This would have destroyed a parallel overnight campaign. Fixed: escalation now targets only the
PIDs actually signalled. Regression-tested — stopping port 2010 leaves port 2000 running.

### 8. `sg docker` hangs forever on a password prompt

Probing docker access with `sg docker -c "docker info"` **prompts on stdin** when the user is
not in `/etc/group` for docker, so the script blocks indefinitely rather than failing. Fixed:
check `/etc/group` first and redirect stdin from `/dev/null`.

---

## CARLA low-speed braking artifact — **open issue for C5**

Not a determinism problem (it reproduces bit-exactly), but it threatens a contract, so it is
recorded here in full.

### Measurement

Braking from 8.1 m/s with a constant command, deceleration profile:

| Speed remaining | Deceleration |
|---|---|
| 8.10 → 5.06 m/s | −2.5 to −4.1 m/s² (smooth, physical) |
| **below ~5 m/s** | **−17.3, −27.0, −26.8, −26.2 m/s²** |

The transition is a **regime change at ≈5 m/s**, not a stop-snap at zero.

### It is not proportional to brake command

| Brake command | 0.15 | 0.20 | 0.25 | 0.30 | 0.40 | 0.60 | 1.00 |
|---|---|---|---|---|---|---|---|
| Peak deceleration (m/s²) | −21.8 | −27.0 | −26.9 | −27.2 | −27.0 | −27.0 | −27.1 |
| Mean deceleration (m/s²) | −2.7 | −5.8 | −6.2 | −6.5 | −7.0 | −8.1 | −10.1 |

### It is not brake torque

| `max_brake_torque` | above 5 m/s | below 5 m/s |
|---|---|---|
| 700 (default) | −4.81 | −27.01 |
| 350 | −4.16 | −27.04 |
| 175 | −3.83 | −23.16 |
| 84 (8× reduction) | −3.68 | −17.70 |

An 8× torque reduction only softens the artifact to −17.7 while making braking uselessly weak
everywhere else. **This is an intrinsic CARLA 0.9.16 low-speed vehicle-physics regime.**

`get_acceleration()` is *not* at fault — it agrees with finite-differenced velocity to within
noise, so the vehicle genuinely undergoes these accelerations.

### Why this matters, and what must be decided before C5 lands

C5 bounds `|a_long| ≤ 3.0 m/s²`. **Every yielding episode brings the ego to a stop, so every
yielding episode passes through the artifact regime** and would violate C5 regardless of how
gently the program brakes. C5 would then measure CARLA's brake model rather than the program's
comfort decisions, and — because ρ = min over contracts — would dominate the blame signal.

On the gate's baseline episode: `|a| ≤ 5.615 m/s²` across 148 ticks above 5 m/s, versus
`|a|` up to **26.953 m/s²** across 360 ticks below it.

**Mitigations already applied** (they improve realism but do not remove the artifact):
`brake_max` 1.0 → 0.5, and actuator slew limits of 0.10 per tick (2.0/s) on both throttle and
brake — the controller was previously commanding 0 → full brake within a single 50 ms tick.

**Recommended for 24 Aug, needs your decision:** evaluate C5 only where
`ego_speed_mps ≥ 5.0`, and state the restriction in the paper. This preserves C5's purpose —
D4's "brake hard and never turn" degenerate program still shows large deceleration in the
8→5 m/s band — while excluding a regime where the simulator is not physical. Task completion
is caught separately by ICR/PCR. The alternative, filtering the acceleration signal, is
insufficient on its own: a 5-tick moving average over −3.7, −17.3, −27.0, −26.8, −26.2 still
averages ≈ −20 m/s².

---

## Junction — recorded as an exact identifier (closes open item O2)

`data/scenarios/junction.yaml`, frozen.

| | |
|---|---|
| Map | Town05 |
| Junction id | **1126** |
| Traffic lights | 4 |
| Left-turn `dyaw` | **−90.42°** |
| Ego approach | road 6, lane −1, yaw −179.91°, stop line (−30.45, −91.44) |
| Oncoming approach | road 7, lane +1, yaw +0.09°, stop line (−70.00, −88.00) |
| Junction centre | (−50.69, −92.60) |

### Turn direction verified, not assumed

CARLA/UE4 is left-handed, so the sign of a left turn is a convention that is easy to get
backwards — and getting it backwards means running a **right** turn for the whole experiment.
Verified by projecting (exit − entry) onto the entry waypoint's own `get_right_vector()`:

| `dyaw` | lateral projection | verdict |
|---|---|---|
| +90.42 | +8.855 | RIGHT |
| **−90.42** | **−16.825** | **LEFT** ← selected |
| −77.27 | −12.043 | LEFT |
| +77.27 | +14.800 | RIGHT |
| +89.58 | +9.851 | RIGHT |
| −89.58 | −17.773 | LEFT |
| +102.73 | +12.353 | RIGHT |
| −102.73 | −21.029 | LEFT |

All four ~−90° pairs project negative (left); all four ~+90° project positive (right).
**Negative `dyaw` = LEFT turn, confirmed.** Left turns also show larger lateral displacement
(16–21 m) than right turns (9–15 m), which is the correct geometry for crossing a junction.

Waypoints are stored by **OpenDRIVE identity** (`road_id`, `lane_id`, `s`) rather than raw XYZ,
because OpenDRIVE identity is stable across restarts and a raw coordinate is not guaranteed to
snap back to the same lane.
