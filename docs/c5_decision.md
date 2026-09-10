# C5 — how kinematic comfort is computed, and why

**Decided:** 2026-08-24, from measurement on 300 banked traces.
**Decision:** compute C5 from **commanded control**, via a measured
command→acceleration map. **No ego-speed threshold is applied**, because none is needed.

---

## What was asked

Sweep an ego-speed threshold from 2 to 8 m/s and pick the value where the CARLA sub-5-m/s
deceleration artifact stops dominating. Fall back to commanded control only if no clean cliff
appears.

## What the sweep found

`scripts/c5_threshold_sweep.py`, 300 traces, thresholds 2.00 → 8.00 in 0.25 steps, with the
derivative window required to lie **entirely** above the threshold (window `{i−1, i}` for
acceleration, `{i−2, i−1, i}` for jerk).

**No cliff. The violation rate was 100.0% at every threshold.** Full sweep in
`data/results/c5_threshold_sweep.json`.

But the sweep separated the two terms cleanly, which is what made the decision:

| Threshold | max\|a\| | **p95 max\|a\|** | max\|j\| |
|---|---|---|---|
| 4.00 | 121.3 | **26.87** | 2428 |
| 4.25 | 121.3 | **5.77** | 2428 |
| 4.75 | 6.64 | 5.76 | 93.3 |
| 7.00 | 3.58 | 3.58 | 59.2 |
| 7.25 | 2.19 | 2.17 | **58.0** |

- **Acceleration does have a cliff**, between 4.00 and 4.25 m/s: p95 max|a| falls 26.87 → 5.77.
  That is the braking artifact boundary, and a threshold would have handled it.
- **Jerk has no cliff anywhere.** It is still 58 m/s³ at 7.25 m/s, against a bound of 3.0.

## Why jerk cannot be recovered by any threshold

Jerk was never contaminated by the braking artifact. It is contaminated by **sampling noise**.

Measured in a clean cruising segment — speed above 6 m/s, no brake, throttle decreasing
*monotonically* from 0.65 to 0.30 — the reported acceleration oscillates:

```
row  speed   a_long    d(a)     jerk   thr
 38  6.696   +4.622            +18.57  0.65
 39  6.879   +3.648  -0.973    -19.47  0.56
 40  7.079   +4.005  +0.357     +7.14  0.46
 41  7.207   +2.558  -1.448    -28.95  0.40
 42  7.337   +2.605  +0.047     +0.94  0.33
 43  7.396   +1.170  -1.435    -28.70  0.30
```

The underlying trend is smooth; the signal is not.

| Quantity | Value |
|---|---|
| σ of `a_long` in clean cruising | **1.36 m/s²** |
| Mean \|Δa\| per tick | 0.509 m/s² |
| Implied mean \|jerk\| | 10.18 m/s³ |
| Δa required to satisfy `j_comfort = 3.0` at dt = 0.05 s | **0.15 m/s²** |

**The comfort bound demands a tick-to-tick resolution nine times finer than the accelerometer's
noise floor.** Differencing at 20 Hz multiplies that noise by 20. Jerk computed from CARLA's
measured acceleration is not a measurement of the vehicle; it is a measurement of the sampling
noise. No threshold, and no averaging window, changes that — a 5-tick mean over
(−3.7, −17.3, −27.0, −26.8, −26.2) still averages ≈ −20 m/s².

## A third contaminant

Measured acceleration is also polluted by **collisions**: |a| up to **61.7 m/s²** at the impact
tick. That is real physics, but it is C1's business. Pooling it into C5 would make a collision
also register as a comfort violation, double-counting one failure across two contracts and
distorting the min-across-contracts blame signal.

---

## The decision

**C5 is computed from commanded control**, converted to m/s² by a measured linear map.

```
a_cmd(t)    = k_throttle · throttle(t)  −  k_brake · brake(t)  +  a_coast
jerk_cmd(t) = ( a_cmd(t) − a_cmd(t−1) ) / dt

rho_5 = min over t of min( a_comfort − |a_cmd(t)| , j_comfort − |jerk_cmd(t)| )
```

### The map is measured, not assumed

`scripts/calibrate_control_map.py`, sampled entirely **above** the artifact regime (5.5–9.5 m/s),
using a least-squares slope of speed against time rather than per-tick differencing:

| Coefficient | Value |
|---|---|
| `k_throttle` | **+8.1429** m/s² per unit throttle |
| `k_brake` | **+1.4320** m/s² per unit brake |
| `a_coast` | **−2.2805** m/s² (drag + rolling resistance) |
| Max residual | 0.9158 m/s² |
| RMS residual | 0.4068 m/s² |

Stored in `data/results/control_map.json`. `stl.load_control_map()` **raises** if the file is
absent — C5 must never silently fall back to a guessed map.

Note `k_brake` is small: above 5.5 m/s the brake has little authority (0.05 → −2.41 m/s²,
0.50 → −3.07 m/s²), and then slams below 5 m/s. That is the same artifact seen from the other
side, and it is exactly what commanded control lets us step around.

### Why this is the right quantity, not merely the available one

C5 exists because of decision **D4**: without it, a program that brakes hard and never turns
satisfies every other contract and scores as a successful repair. What that failure consists of
is the program **commanding** harsh deceleration. Comfort is a property of the control policy,
and the control policy is what the program *is*.

Commanded control is also exact, noise-free, immune to the braking artifact, and immune to
collision spikes — so no speed threshold is required and C5 is evaluated over the whole episode.

### Limitation, for the paper

This scores the **commanded** acceleration, not the realised one. A program whose commands are
smooth but whose vehicle response is harsh would pass C5. Given that the realised jerk signal is
unmeasurable at 20 Hz on this simulator, that is the honest trade — and it is stated rather than
hidden.

---

## ⚠️ C5 has no discriminating power yet, and why that is a DSL requirement

Applying the above to all 300 banked traces:

| | |
|---|---|
| C5 violation rate | **100.0%** |
| Binding term | jerk, in **300 of 300** |
| `max\|a_cmd\|` | **3.827 m/s² in every trace** — zero variance |
| `max\|jerk_cmd\|` | **19.150 m/s³ in every trace** — zero variance |

Both numbers are exactly reproducible as controller saturation constants:

- `3.827 = 8.1429 × 0.75 − 2.2805` — the `throttle_max` ceiling
- `19.150 = (8.1429 × 0.10 + 1.4320 × 0.10) / 0.05` — throttle **and** brake both moving at the
  0.10/tick slew limit during the accelerate→brake transition, which every episode performs

**C5 is currently a constant, so it discriminates nothing.** That is not a flaw in the contract;
it is a consequence of the placeholder controller, whose gains and limits are fixed by the
harness rather than chosen by the program.

### The consequence for the behaviour-tree DSL

If the tree only selects *target speeds* and a fixed PID converts those to throttle and brake,
then C5 measures the PID and not the tree — it will stay pinned at the same two constants.

**The DSL must therefore expose the deceleration/ramp choice as a program parameter**, so that
choosing a harsh stop and choosing a gentle one are different programs producing different ρ₅.
This is why the node vocabulary includes an explicit `decel_mps2` on the yielding nodes rather
than a bare "stop" (see `docs/dsl_reference.md`).

The harness slew limit is correspondingly loosened from 0.10 to **0.20 per tick**, which
represents *actuator physics* (0.25 s full travel — what a brake actuator can do) rather than
*comfort* (what the program should choose). Comfort is the program's job, and C5 is how it is
scored.

### Thresholds kept as configured

`a_comfort = 3.0 m/s²` and `j_comfort = 3.0 m/s³` are retained. They are standard comfort values
and they are not the reason C5 is currently degenerate — the reason is zero variance in the
input. **Re-measure the C5 violation-rate distribution once the tree is driving**, before
freezing the baseline. If it is still pinned, the DSL is not exposing enough control authority
and that is the thing to fix, not the threshold.

---

## Addendum, 24 Aug — the jerk term, after the DSL landed

Once the behaviour tree exposed `accel_mps2`/`decel_mps2` as program parameters, C5 was
re-measured against three programs spanning the plausible space.

| Program | `max\|a_cmd\|` | `max\|jerk_cmd\|` | ρ₅ (accel only) | ρ₅ if jerk counted |
|---|---|---|---|---|
| gentle | 1.00 | 36.0 | **+2.00** | −33.0 |
| reference | 2.00 | 70.0 | **+1.00** | −67.0 |
| harsh | 7.50 | 260.0 | **−4.50** | −257.0 |

**The acceleration term discriminates cleanly.** Gentle and reference pass; harsh violates and
becomes the argmin, correctly identifying a comfort failure that C1 and C2 would have masked.
That is exactly decision D4's purpose.

**The jerk term fires on 100% of programs and is therefore excluded from ρ₅**
(`jerk_contributes: false`). At dt = 0.05 s, `j_comfort = 3.0 m/s³` demands the commanded
acceleration change by no more than **0.15 m/s² per tick**, and the DSL cannot express a
multi-tick acceleration ramp — an action selects an acceleration, so a switch between actions is
a step. Even the gentlest expressible program, switching between +0.8 and −1.0 m/s², produces
jerk 36. A term that fires on every program would drive SCVR to 100% while distinguishing
nothing.

It is still **computed and reported** (`rho5_jerk_if_it_did` in the contract detail), so the
magnitude ordering is available even though the term is not gated on.

**To restore it**, the DSL needs a ramp: either an explicit `jerk_mps3` parameter on the
actions, or an interpretation of `accel_mps2` as a rate toward a target acceleration. Recorded
as future work rather than papered over by relaxing the threshold until it stops firing.

### One more correction, worth recording

C5 initially read `ego_throttle`/`ego_brake` and inverted the measured map. That is the command
**after actuator slew limiting**, so the harness slew constant pinned `max|jerk_cmd|` to the
same value for every program — ρ₅ was identically −29.572 regardless of what the tree asked
for. Schema 1.2.0 added `cmd_accel_mps2`, the acceleration the **program** requested, logged
before actuator limiting. C5 reads that. Without this change C5 would have looked like it was
working while measuring only the harness.
