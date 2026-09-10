# C4 is not deterministic, and `rho = min(.)` hides it

**Date:** 2026-08-31 · **Script:** `scripts/probe_c4_determinism.py` ·
**Data:** `data/results/determinism_c4.json` · **Program:** frozen `baseline_program.bt`

---

## The claim

Across **6 repeats of identical parameters**, on three scenarios spanning the
six-parameter space:

| Contract | Spread over 6 repeats (scenario 0 / 1 / 2) | Reproduces? |
|---|---|---|
| C1 | 0.0 / 0.0 / 0.0 | ✅ exactly |
| C2 | 0.0 / 0.0 / 0.0 | ✅ exactly |
| C3 | 0.0 / 0.0 / 0.0 | ✅ exactly |
| **C4** | **0.6912 / 0.5396 / 0.0699 m** | ❌ **no** |
| C5 | 0.0 / 0.0 / 0.0 | ✅ exactly |
| **ρ = min(·)** | **0.0 / 0.0 / 0.0** | ✅ — *and this is the problem* |

Four of the five contracts are **bit-exact**. C4 drifts by up to **0.69 m**.
And the overall ρ spread is **zero in all three scenarios**, because C4 was
never the argmin.

## Why the determinism gate does not catch it

Two independent reasons, and either alone would be sufficient:

1. **The gate's parameters cannot spawn a lead vehicle.**
   `GATE_PARAMS` in `scripts/determinism_gate.py` is
   `{n_oncoming, v_oncoming, headway, ped_phase_offset}` — it still carries
   `ped_phase_offset`, dropped 24 Aug, and it omits `lead_gap_s`,
   `aggressiveness` and `light_offset`, all added since. `_spawn_lead` begins
   `gap_s = params.get("lead_gap_s"); if gap_s is None: return None`, so **no
   lead is ever spawned during the gate and C4 is vacuous in every gate
   episode** (confirmed: `C4 rho=+999.0 vacuous=True` on `det_baseline`).
   The gate cannot observe the contract that drifts.

2. **The gate scores the spread of `rho = min(·)`, not of each contract.**
   Even with a lead present, C4 only reaches ρ when it is the argmin. This is
   the same `min()` masking that `docs/sensitivity_analysis.md` documented for
   *gradients* — "`headway` has a strong effect on both contracts, in opposite
   directions, and `min()` cancels them" — reappearing for *determinism*.
   A per-contract spread is the fix in both cases.

## Mechanism

The ego is bit-exact; only the **lead vehicle** diverges. Its x-position
spreads by 0.039–0.058 m, first differing around row 52–81 of ~450.

`_apply_lead_profile` is open-loop in its own state except for one closed-loop
test: `d_cz <= hold_m`, where `d_cz` is read back from
`lead.get_transform().location`. Sub-centimetre float noise in that read-back
moves the tick on which deceleration starts, and a one-tick shift is a step of
`a_dec * dt = 4.0 * 0.05 = 0.20 m/s` in the lead's commanded speed — which is
the size of the first divergence observed. From there the gap to the ego
integrates the difference and C4's margin drifts by tenths of a metre.

The oncoming vehicles use the same `enable_constant_velocity` mechanism and
**do** reproduce exactly; they differ in that `_apply_aggressiveness` did not
cross its trigger in these scenarios. The defect is the threshold-on-measured-
state pattern, not constant-velocity control as such.

## What it does and does not invalidate

**Does not:** the 20 banked counterexamples. C4 was the argmin in **none** of
them (`violated_contracts: {C1: 8, C2: 12, C3: 0, C4: 0, C5: 0}`), and every
admitted certificate carries a re-simulation check showing C1/C2/C3/C5 matching
to ≤ 1e-6. The corpus is sound.

**Does:** any future result in which C4 is the argmin. ρ would then be
non-deterministic by up to ~0.7 m, and — because a repair is scored as
`rho >= 0` on the counterexample scenario — a repair could be recorded as
resolving a counterexample it did not resolve, or the reverse. This is exactly
the failure mode project rule 6 names: it corrupts results downstream
without ever throwing an error.

## Recommended fixes, in order

1. **Update `GATE_PARAMS`** to the current six-parameter space so the gate
   exercises a lead vehicle at all. This alone turns a silent PASS into a
   visible FAIL.
2. **Gate on per-contract spread**, not only on the spread of the min.
   `scripts/probe_c4_determinism.py` already computes it and can be folded in
   as a stage.
3. **Remove the read-back from `_apply_lead_profile`.** The lead travels a
   straight line at a known speed from a known spawn point, so its distance to
   the conflict zone can be integrated from its own state exactly as
   `v_current` already is, with no call to `get_transform()`. That removes the
   threshold-on-noisy-measurement pattern rather than tightening it.

Fix 3 changes lead dynamics and therefore invalidates banked traces, so it
should land together with a re-run, not before one.

---

## Corpus-wide confirmation (20 admitted counterexamples)

Every admitted certificate carries one cache-bypassing re-simulation. Over the
20 in `data/certificates/`:

| Contract | Certificates drifting > 1e-6 | Largest drift seen |
|---|---|---|
| C1 | 0 / 20 | 7.2e-08 |
| C2 | 2 / 20 | 4.97e-06 |
| C3 | 1 / 20 | 5.0e-02 (exactly one tick) |
| **C4** | **18 / 20** | **0.547 m** |
| C5 | 0 / 20 | 0.0 |

**The blamed contract's own ρ reproduced EXACTLY — `rho_delta = 0.00e+00` — in
all 20 certificates.** C4 is never the argmin in this corpus
(`{C1: 10, C2: 9, C3: 1, C4: 0, C5: 0}`), so no certified number is affected.

### The single C3 observation, and why it is left open

`CE004` recorded C3 = 1.05 on its original run and 1.00 on re-simulation — a
shift of exactly one tick (0.05 s). It did not reproduce under further
testing:

* 4 within-process repeats of CE004's parameters: ego bit-exact on **every**
  field (max deviation 0.000e+00), identical light schedule (first Red at row
  320 each time), C1 and C3 both exact. Only C4 varied (7.615–8.146).
* 3 **separate process launches** on the C3-violating scenario `CE017`:
  ρ = −0.700000 identically, ego bit-exact, first Red at row 315 each time.

So the ego trajectory is not contaminated by the lead, and C3 is reproducible
in every controlled test run against it. The one observation stands
unexplained. `_apply_light_schedule` does share the suspicious shape — it
starts the phase clock on `hypot(ego - centre) > trig`, a threshold on a
read-back position — so a one-tick trigger shift is the plausible mechanism,
but it was not isolated and is **recorded rather than fixed**.

### Why the gate is blind to BOTH of these contracts

`GATE_PARAMS` omits `light_offset` as well as `lead_gap_s`. Without
`light_offset`, `_apply_light_schedule` returns early and the signal is held
green for the whole episode, so C3 collapses to its `no_red_onset_rho`
sentinel on a single sample — which is also what makes `rtamt` raise on it
(see `stl.rtamt_crosscheck`). The two contracts the gate cannot exercise,
C3 and C4, are exactly the two that show non-reproducibility.
