# Parameter Sensitivity — why `headway` looked inert, and what it actually does

**Date:** 2026-08-24
**Data:** 300 generation-1 traces (`g1_*`), corrected parameter space, hardcoded controller
**Script:** `scripts/sensitivity_analysis.py` · **Output:** `data/results/sensitivity.json`

---

## The question

`headway` correlated **−0.039** with ρ over the 23 August bank. Gap to oncoming traffic should
be *the* determining variable for a yield decision, so that number was suspicious rather than
informative.

Two hypotheses were offered. **Both are rejected.** The cause was a third thing.

---

## H1 — "the traces predate the lane-spawn fix" · **REJECTED**

| Check | Result |
|---|---|
| Oncoming actors ~180° opposed to the ego at t=0 | ✅ yes |
| Every oncoming vehicle spawns on the far side of the conflict zone | ✅ 300/300 |
| Actor roles present | only `oncoming` |

The traces were banked *after* every fix; the campaign was the last thing run on 23 August.

## H2 — "the hardcoded controller ignores gaps entirely" · **REJECTED**

The controller's yield branch is `oncoming_ttc_s >= tau_yield_s`. If gaps were ignored,
`P2_yield_hold` would never appear.

| Phase | Traces reaching it |
|---|---|
| P1_approach | 300/300 |
| P2_yield_clear | 300/300 |
| **P2_yield_hold** | **264/300 (88.0%)** |
| P3_commit | 300/300 |
| P4_settle | 271/300 |

The controller yields in 88% of scenarios. It responds to gaps.

## H3 — `headway` did not control the gap the ego faced · **CONFIRMED**

The spawn rule was

```
d_i = oncoming_spawn_back_m + i * max(headway * v_oncoming, min_gap)
```

**For i = 0 the headway term is multiplied by zero.** The lead vehicle always spawned at a
fixed 60 m regardless of headway.

| Measurement | Value |
|---|---|
| Lead-vehicle distance to conflict zone at t=0 | 70.68 – 76.14 m, **std 1.639 m** |
| corr(headway, lead distance) | **−0.0665** |
| corr(v_oncoming, lead TTC) | **−0.9681** |
| Traces with `n_oncoming = 1`, where headway is provably inert | **93/300** |

The gap the ego faced was `d_lead / v_oncoming` with `d_lead` constant — i.e. set by
`v_oncoming` **alone**. That is precisely why `v_oncoming` correlated +0.669 and `headway`
−0.039: they were not two parameters, they were **one parameter and a no-op**.

### The fix

The lead vehicle is now phased against the **ego's** arrival:

```
d_lead_from_cz = v_oncoming * (t_ego_to_decision_s + headway)
```

so `headway` **is** the time-to-conflict-zone the ego faces when it takes its yield decision,
directly comparable with `tau_yield`. Spec §6 leaves `headway[0]` undefined — there is no
preceding vehicle for i = 0 — and this is the natural reading of that slot. Following vehicles
keep the spec's meaning: gap to the vehicle in front.

`t_ego_to_decision_s = 4.95` is **measured**, not assumed: 4.950 s with standard deviation
**0.000** across 300 traces. It must be re-measured when the behaviour tree drives the
approach, and `achieved_gap_s` is logged per episode so a drift between the knob and the
outcome is visible rather than silent — which is exactly how the original bug survived.

Verification, three episodes with everything else held fixed:

| `headway` requested | `achieved_gap_s` measured |
|---|---|
| 1.5 | 1.087 |
| 3.0 | 2.531 |
| 8.0 | 7.544 |

---

## Re-run on the corrected space

300 traces, parameters `n_oncoming`, `v_oncoming`, `headway`, `aggressiveness`.

| | |
|---|---|
| ρ range | −2.671 to +27.000, median +1.342 |
| **Violation rate (ρ < 0)** | **31.3%** — inside the 20–40% target band (was 19.3%) |
| Argmin contract | C2 171 · C1 129 |

### Correlations

| Parameter | Pearson | Spearman | p | Verdict |
|---|---|---|---|---|
| `aggressiveness` | −0.356 | **−0.379** | 1.2e−11 | moderate |
| `v_oncoming` | −0.366 | **−0.349** | 4.8e−10 | moderate |
| `n_oncoming` | −0.226 | −0.116 | 4.4e−02 | weak |
| `headway` | +0.044 | −0.068 | 2.4e−01 | none *(see below)* |

Spearman as well as Pearson, deliberately: a low Pearson with a high Spearman means "matters,
non-linearly", which is a completely different conclusion from "does not matter".

### ⚠️ The headline: `headway` is NOT inert — the `min()` hides it

| Parameter | ρ overall | **ρ_C1** | **ρ_C2** |
|---|---|---|---|
| `headway` | −0.068 | **+0.555** | **−0.435** |
| `achieved_gap_s` | −0.030 | **+0.607** | **−0.410** |
| `aggressiveness` | −0.379 | −0.470 | −0.262 |
| `v_oncoming` | −0.349 | −0.215 | −0.265 |
| `n_oncoming` | −0.116 | +0.017 | −0.168 |

`headway` has a **strong effect on both contracts, in opposite directions**, and
ρ = min(C1, C2) cancels them.

The mechanism is real, not an artefact:

- **Large gap** → the ego commits immediately → it is still inside the conflict zone when the
  oncoming vehicle arrives → **C2 margin falls**, but it never passed close to a moving
  vehicle → **C1 clearance rises**.
- **Small gap** → the ego holds at the stop line → the vehicle passes close by → **C1
  clearance falls** → then it commits onto a clear road → **C2 margin rises**.

### What this means for the falsifier

This is the **masking limitation of space robustness** already stated in spec §5 — only the
worst conjunct contributes gradient — showing up concretely. Consequences:

1. **`headway` is a legitimate search dimension.** Do not drop it on the overall correlation.
2. **A falsifier that ranks candidates on ρ alone gets almost no headway gradient.** The
   ρ-ranked local refinement should rank on **per-contract** robustness, not only the min, or
   it will push `v_oncoming` and `aggressiveness` to their bounds and never explore the
   headway axis.
3. **Certificates should report the per-contract vector**, not only ρ. "C1 = +0.6, C2 = −0.4"
   is a different and more actionable diagnosis than "ρ = −0.4".

Recorded here rather than discovered in the middle of the falsification campaign.

---

## Status of each parameter

| Parameter | Keep? | Reason |
|---|---|---|
| `v_oncoming` | ✅ | Moderate, consistent signal on both contracts |
| `aggressiveness` | ✅ | Restored 24 Aug. Strongest single correlate of C1 (−0.470) |
| `headway` | ✅ | Strong per-contract signal in **opposite** directions; see above |
| `n_oncoming` | ✅ with a caveat | Weak (−0.116) but cheap, and it interacts with headway through the platoon |
| `ped_phase_offset` | ❌ **dropped** | No pedestrian was ever spawned. Correlation −0.031, i.e. nothing |
