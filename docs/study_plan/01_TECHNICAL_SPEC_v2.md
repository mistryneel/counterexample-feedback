# 01 — Technical Specification **v2**

> **Supersedes `01_TECHNICAL_SPEC.md`.** That document remains in the repo as the record of
> the original design; where the two disagree, **this one governs**.
>
> **Revision date:** 23 August 2026. **Reason:** scope reduction to fit a five-day build
> (24–28 Aug) with a 13 September paper deadline, and to remove label collisions.
>
> Everything cut is listed in §12 with a limitations sentence already drafted. §13 states
> whether any cut damages the central claim. Read those two sections before the rest if you
> are short of time.

---

## §0 — What changed from v1

| # | Change | Section |
|---|---|---|
| 1 | Repair conditions **A/B/C/D → F1/F2/F3/F4** | §9 |
| 2 | **Three contracts** (C1, C2, C5). C3 and C4 deferred | §5 |
| 3 | **Runtime safety shield removed entirely.** SIR metric removed | §8 (deleted), §10 |
| 4 | Falsifier search space cut from 8 parameters to **4** | §6 |
| 5 | **Uniform random sampling + ρ-ranked local refinement.** No black-box optimizer | §6 |
| 6 | **E1 only.** E2 deferred. K = 8, 1 seed, regression suite of 5 | §9 |
| 7 | Held-out set is a **reserved region of parameter space**, not a new actor class | §9.5 |
| 8 | CARLA version and environment pinned in `docs/env_manifest.md` | §3 |

**Unchanged and non-negotiable:** the certificate's four properties (§7), blame localization
(§7.5), delta debugging (§7.1), boundary search (§7.2), the F1–F4 ablation (§9), and every
metric that survives the cuts (§10).

### On the label rename (change 1)

`A/B/C/D` collided with the contract labels `C1–C5` — "condition C" and "contract C2" in the
same sentence is a genuine ambiguity — and `B` collided with the token budget symbol `B`.
`F` for *feedback condition* is unambiguous against both. **This is a pure rename. No
condition's contents changed.** Any A/B/C/D in older documents is stale; the mapping is
A→F1, B→F2, C→F3, D→F4.

---

## §3 — Task and environment

Unchanged from v1 except the environment row. Task remains the **unprotected left turn**
(permissive green circular ball, signal ON) at a **Town05** four-way signalized junction.

| Setting | Value |
|---|---|
| Simulator | **CARLA 0.9.16**, UE4 line, release commit `294096eb1c38eabf246e4f3a9cdab704e33a7f4c` |
| Platform | **Native Linux build.** No Wine, no Windows binaries. Server runs in the official `carlasim/carla:0.9.16` container, which packages that same native Linux build with its own Ubuntu userland; the host is Ubuntu 24.04, outside CARLA's stated 20.04/22.04 support matrix, which is precisely why the server is containerized |
| Client | `carla==0.9.16` (`cp312-cp312-manylinux_2_31_x86_64`) on host Python 3.12.3 |
| Junction | Recorded as an **exact identifier** in `data/scenarios/junction.yaml`, discovered by `carla_backend.discover_left_turn_junction()` and frozen (closes open item O2) |
| Mode | Synchronous, fixed Δt **0.05 s** (20 Hz), `-RenderOffScreen`, quality `Low` |
| Weather | `ClearNoon`, fixed (D11) |
| Sensing | Ground-truth state only (D10) |

Full pinned versions: **`docs/env_manifest.md`**. That file is what makes the experiment
reproducible and is cited in the paper.

Entry conditions, exit conditions, failure termination, and phases P1–P4 are **unchanged from
v1 §3**. The phase reached is now recorded per timestep in the trace `phase` column
(`docs/log_schema.md`) rather than reconstructed afterwards.

---

## §5 — Safety contracts (three)

Space robustness throughout: **positive when satisfied**, magnitude = margin.

### C1 — No collision

```
□[0,T] ( clearance(ego, any_actor) ≥ 0 )
ρ₁ = min over t of clearance(t)
```

`clearance` = minimum **oriented bounding-box** separation in metres, negative on overlap
(penetration depth). Implemented exactly for convex rectangles in `src/stl.py:obb_clearance`
— SAT for the overlap case, segment-to-segment minimum for the disjoint case. A circle
approximation would misreport ρ₁ by up to half a vehicle length, and ρ₁ is a number the
paper quotes.

### C2 — Yield to oncoming traffic

```
□[0,T] ( in_conflict_zone(ego) → ttc_oncoming ≥ τ_yield )
ρ₂ = min over { t : ego in conflict zone } of ( ttc_oncoming(t) − τ_yield )
```

τ_yield = **3.0 s**, sensitivity at 2.5 and 3.5. This is RSS rule 3 and the contract most
characteristic of the manoeuvre.

**Vacuity.** If the ego never enters the conflict zone, C2 is vacuously satisfied. It reports
a sentinel (999.0), flagged `vacuous=True`, and is **excluded from the argmin** — blame must
come from a contract that was actually evaluated. A program that never enters the junction is
not a safe program, it is a failed task, and ICR/PCR are what catch that.

### C5 — Kinematic comfort

```
□[0,T] ( |a_long| ≤ a_comfort ∧ |jerk_long| ≤ j_comfort )
ρ₅ = min over t of min( a_comfort − |a_long(t)|, j_comfort − |jerk_long(t)| )
```

a_comfort = 3.0 m/s², j_comfort = 3.0 m/s³.

**Longitudinal projection, not magnitude.** ‖**a**‖ would count centripetal acceleration
during the turn as harsh braking, penalising a program for turning correctly. C5 bounds
**a** projected onto the heading.

**C5 is mandatory (D4).** Without it, "brake hard and never turn" satisfies C1 and C2 and
scores as a successful repair. That failure would look like success in the numbers until
someone watched a video.

### Combined

```
ρ = min( ρ₁, ρ₂, ρ₅ )
```

Conjunction is minimum, so the **argmin identifies both the weakest contract and the timestep
at which it is weakest**. Both are recorded. The timestep is what blame localization resolves
against the behaviour tree, by reading the `bt_node_*` columns at that row — **a lookup, not
an inference**.

### Deferred: C3 and C4

C3 (do not occupy the intersection on red) and C4 (RSS longitudinal safe distance to lead)
are **deferred, not deleted**. Their v1 definitions stand; they are simply not evaluated.
`config/contracts.yaml` carries them with `enabled: false` so re-enabling is a one-line
change, not a re-implementation.

**This revises locked decision D3** ("Five contracts, not three"), whose stated rationale was
that five gives the min-across-contracts blame signal more discriminating power. That
rationale is correct and the cost is real — see §12.2. The roadmap's requirement is **≥ 3**,
so three is compliant.

### Stated limitations (unchanged from v1, still true)

- **Masking** — only the worst conjunct contributes gradient. Standard space robustness is
  kept anyway because ρ reads directly as "metres of clearance" or "seconds of margin", and
  ρ appears in the certificate shown to the LLM.
- **Sampling** — ρ is computed at 20 Hz, so a violation entirely between ticks can be missed.
  Fainekos & Pappas (2009) give conditions under which discrete-time analysis is sound for
  continuous-time signals; this work does not verify them.

---

## §6 — Adversarial falsification

### §6.1 Search space — four parameters

| Parameter | Range | Type | Justification recorded in |
|---|---|---|---|
| `n_oncoming` | 1–3 | integer | `data/scenarios/space.yaml` |
| `v_oncoming` | [6, 16] m/s | float, shared by all oncoming vehicles | `space.yaml` |
| `headway` | [1.5, 8.0] s | float, gap to preceding oncoming vehicle | `space.yaml` |
| `ped_phase_offset` | [0, 8] s | float, crosswalk entry timing | `space.yaml` |

Every bound carries its justification alongside it in `space.yaml`. "0 to 30 m/s" is not a
defensible bound; "5th–95th percentile of observed approach speeds" is.

**The pedestrian is now always present.** v1 had `pedestrian_present ∈ {0,1}` *and*
`ped_phase_offset`. Keeping only the offset removes a binary factor while preserving the
timing interaction that actually stresses the manoeuvre.

**`v_oncoming` is now scalar, not per-vehicle.** A per-vehicle vector makes the boundary
report ("fails for v_oncoming ≥ 13.6") ill-defined — there would be no single number to bound.
Boundary search is a non-negotiable property of the certificate (§7.2), so the parameter must
be scalar for the certificate to be expressible.

**The four dropped parameters map exactly onto the two dropped contracts.** This makes the cut
principled rather than arbitrary:

| Dropped parameter | Contract it primarily stressed | Status |
|---|---|---|
| `light_offset` | C3 (red light) | deferred with C3 |
| `lead_present` | C4 (RSS to lead) | deferred with C4 |
| `aggressiveness` | C1/C2 via oncoming deceleration | see below |
| `pedestrian_present` | C1 | folded into `ped_phase_offset` |

`aggressiveness` (oncoming willingness to decelerate for the ego) is dropped for a second,
stronger reason: oncoming vehicles are now driven at **constant velocity**
(`enable_constant_velocity`) rather than by the Traffic Manager. The TM interposes its own
controller dynamics between the commanded `v_oncoming` and the observed speed, so the number
the certificate reports would not be the number the vehicle drove. Constant velocity makes
`v_oncoming` mean exactly what the certificate says it means, and removes a large source of
non-determinism. The cost is that oncoming vehicles will not brake to avoid the ego, which
makes the scenario strictly harsher — recorded in §12.4.

### §6.2 Plausibility constraints

**Unchanged from v1 and still enforced at sample time**, declaratively, following Scenic
(Fremont et al., PLDI 2019) — not checked afterwards:

- Kinematic feasibility for all non-ego actors: |a| ≤ 4.0 m/s², |a_brake| ≤ 8.0 m/s²,
  |jerk| ≤ 5.0 m/s³
- No actor spawns overlapping another actor or off-lane (enforced by a minimum spawn gap, so
  a small `headway` at low `v_oncoming` cannot place one car inside another)
- Oncoming vehicles obey their own signal phase
- Pedestrians enter the crosswalk only on the walk phase

> **Rationale (AdvSim, CVPR 2021), unchanged and still the top project risk.** Without these,
> the falsifier finds a 40 m/s oncoming vehicle, the LLM patches to a twelve-second gap
> requirement, the regression suite passes, and instruction completion collapses while the
> safety metrics look excellent. **This is the most likely way for the project to fail
> quietly.**

### §6.3 Search strategy — uniform random + ρ-ranked local refinement

**No black-box optimizer.** Not simulated annealing, not CMA-ES, not Bayesian optimization.

1. **Sample** N points uniformly at random from the (constrained) 4-D box.
2. **Rank** by ρ ascending. The lowest-ρ points are the near-misses.
3. **Refine** locally around the top-*r* ranked points: resample within a shrinking
   neighbourhood, keeping any point with lower ρ.
4. **Stop** when a point with ρ < 0 is found, or the simulation budget for this counterexample
   is spent.

Justification, and it is a positive one rather than an apology: **the falsifier is not the
contribution.** The paper's claim is about feedback format, and the falsifier is held
*identical* across F1–F4 by construction. A more powerful optimizer would find counterexamples
in fewer simulations but would not change any measured quantity in the ablation. It would add
hyperparameters, a tuning burden, and a source of run-to-run variance, in exchange for
nothing the paper claims. Uniform-plus-refinement is also trivially reproducible from a seed,
which a stateful optimizer is not.

**Objective:** falsification = minimization of ρ.

### §6.4 Simulation caching

Every simulation is keyed by the SHA-256 of its canonicalized parameter dict
(`config.param_hash`). An identical parameter set is never re-run. This matters most during
delta debugging and boundary search, which revisit nearby points repeatedly.

### §6.5 Avoidability filter — unchanged

A counterexample is admitted only if a violation-free response existed. Implements RSS rule 5
and prevents the repair loop from being driven by failures no program expressible in the DSL
could address. This is certificate property 7.3 (**actionable**) and is not cut.

### §6.6 Soundness — unchanged

The falsifier is an **unsound bounded verifier**. It samples a bounded parameter space;
absence of a discovered violation does not establish absence of violations. Real CEGIS with a
complete decision procedure gets a guarantee at termination. **This work does not, and says
so in the paper.**

---

## §7 — The counterexample certificate

**Entirely unchanged from v1.** This is the scientific core and nothing here is cut. All four
properties are required:

**7.1 Minimal** — delta-debugged (Zeller & Hildebrandt, IEEE TSE 2002). Parameters reverted to
nominal one at a time; any that does not affect the violation is dropped.

**7.2 Generalized** — after minimization, each remaining parameter is binary-searched to find
where ρ crosses zero. The certificate reports a **boundary, not a point**: *"Fails for
v_oncoming ≥ 13.6 m/s when headway ≤ 3.4 s."* Cost ~5–10 extra simulations per counterexample.
Simulation is the cheap resource; tokens are the expensive one. Omitting this reproduces
CEGIS's 334455 pathology, where the budget is consumed walking a number line.

**7.3 Actionable** — emitted only if the avoidability filter (§6.5) passes.

**7.4 Verbalized** — every certificate carries a one- or two-sentence natural-language
narrative alongside its structured fields. Reflexion's ablation is decisive: removing the
natural-language reflection step returned performance to baseline. **Structure alone is not
sufficient.**

**7.5 Schema** — as v1, with `violated_contract ∈ {C1, C2, C5}`. `active_node` is resolved by
reading the `bt_node_*` trace columns at the argmin timestep of ρ. **This is possible only
because the policy is a structured, readable program.** The interpretability property and the
blame-localization mechanism are the same property.

---

## §8 — Runtime safety shield — **REMOVED**

v1 §8 is deleted in full. No shield is implemented. The SIR metric and the §8.3 shield-migration
result are removed with it.

This also removes decisions **D5** (RSS-grounded brake-only shield) and **D6** (falsify
shield-OFF, evaluate shield-ON). D6's concern disappears rather than being violated:
falsification and evaluation are now both shield-free, so the confound D6 existed to prevent
cannot arise. That is a genuine simplification, not a workaround.

Consequences are in §12.1 and §13 — this is the most consequential cut and it is argued
explicitly, not buried.

---

## §9 — Experimental design

### §9.1 The manipulated variable — four feedback conditions

Falsifier, budget, program representation, contracts, and evaluation suite are **identical**
across all four. Only what enters the patching prompt changes.

| Condition | Repair signal contents |
|---|---|
| **F1** | Raw logged trajectory excerpt around the violation |
| **F2** | Natural-language failure summary only ("collided with oncoming vehicle while turning") |
| **F3** | Formal certificate minus blame: contract, ρ, minimal params, boundary, narrative |
| **F4** | Full certificate: F3 plus `active_node` blame localization |

> **F1–F4 must differ only in information content** — not in prompt polish, formatting, or
> instruction clarity. If F4 wins because it reads better rather than because it says more,
> the experiment measures nothing. All four share a single prompt template; only the
> `{feedback}` block differs. The templates are diffed and the diff is reported in the paper
> appendix so a reviewer can verify the asymmetry is informational.

### §9.2 Prior expectations — recorded before running anything (D13)

- **F1 ≈ baseline.** Reflexion's ablation predicts a raw error signal without verbalization
  produces little improvement.
- **F4 > F3 is NOT assumed.** Self-Debugging's `+Trace` condition underperformed plain
  unit-test feedback on Codex (87.9 vs 91.6). More structure is not monotonically better.
  **A finding of F4 < F3 is a result, not a failure.**

### §9.3 E1 only

**E1 — controlled repair experiment. The primary and only result.**

Build a fixed corpus of **K = 8** verified counterexamples against a frozen baseline program,
found once. Render each in all four conditions, ask the LLM to patch, measure. Perfectly
isolates the feedback-format variable: same counterexamples, same program, only the rendering
differs. The corpus is banked on disk, so every LLM-side experiment runs with no simulator.

| Setting | v1 | v2 |
|---|---|---|
| K (counterexamples) | ~30 | **8** |
| Seeds | 3 | **1** |
| Regression suite | unspecified | **5 scenarios** |
| E2 closed loop | included | **deferred** |

**K = 8 with 1 seed cannot support a statistical significance claim.** The paper reports
trends and says so explicitly. This is stated in the limitations, not left for a reviewer to
find. See §11 for what scaling would cost.

### §9.4 Baselines

- **Unpatched baseline** — the frozen program, no repair.
- **Resample-and-select** — sample N programs at synthesis, keep the safest, spend no tokens
  on repair. Tests whether Self-Debugging's finding (repair ~10× more sample-efficient than
  reranking) holds here.
- **Self-Refine style** — F2 serves as the free-form feedback baseline.

### §9.5 Held-out evaluation — a reserved region of parameter space

v1 proposed new actor classes (an oncoming motorcycle) and an alternative pedestrian arrival
distribution. **That is replaced** by a reserved sub-box of the *same* 4-D space that the
falsifier is never allowed to sample.

Reason: a new actor class changes two things at once — the parameter distribution *and* the
dynamics/geometry. A failure to generalize would then be uninterpretable, because it could be
either patch overfitting (what we want to measure) or a physical regime the program never
saw. A reserved region changes exactly one thing.

**Design — an interior hole, not a corner.**

```
Falsifier may sample:   the full box MINUS the reserved region
Reserved (held-out):    v_oncoming ∈ [11.0, 13.0]  AND  headway ∈ [3.0, 4.5]
```

The reserved region is a **mid-range hole**, so the held-out test is **interpolation**, not
extrapolation. Reserving the hardest corner instead (highest speed, tightest headway) would
conflate two different failures: "the patch did not generalize" and "no program expressible
in the DSL could have passed here". An interior hole is a clean generalization test because
the surrounding region *is* searched, so we know passable programs exist nearby.

The extrapolation variant (reserving the hard corner) is a worthwhile secondary analysis if
time allows, reported separately and never pooled with the interpolation result.

---

## §10 — Metrics

| Metric | Definition | Status |
|---|---|---|
| **ICR** | Fraction of evaluation scenarios reaching exit conditions | kept |
| **PCR** | Mean fraction of phases P1–P4 reached (read from the trace `phase` column) | kept |
| **SCVR** | Fraction of scenarios with ρ < 0 for any contract | kept |
| **mean ρ, min ρ** | Across the evaluation suite | kept |
| **TLLME** | Cumulative tokens for synthesis + patching; hard cap at B | kept |
| **Repair rounds** | Falsification–patch cycles to pass the suite | kept |
| **Regression failure rate** | Previously-passing scenarios failing after a patch | kept |
| **TED per patch** | Tree edit distance between consecutive versions | kept |
| **Cumulative TED** | Distance from the original synthesized program | kept — **now the primary interpretability metric** |
| **Patch type** | Hole fill vs skeleton edit | kept |
| **Falsification cost** | Simulations per admitted counterexample | kept |
| **DSL expressiveness failures** | Repairs not expressible in the node vocabulary | kept |
| **Malformed output rate** | Validator rejections | kept — **never pooled with safety violations** |
| ~~**SIR**~~ | ~~Shield intervention rate~~ | **REMOVED with the shield** |

**Cumulative TED is promoted.** With SIR and shield migration gone, cumulative TED plus blame
localization is what carries the interpretability claim: if the tree balloons after eight
patches, the claim that the policy stays readable is hollow, and this metric shows it.

---

## §11 — What scaling in September would cost

Estimated simulation counts. **Wall-clock is left parametric in the measured real-time factor
(RTF) because RTF has not yet been measured on this machine** — `docs/determinism_report.md`
fills it in, and `docs/BUILD_PLAN.md` carries the arithmetic.

Per admitted counterexample:

| Stage | Simulations |
|---|---|
| Search until ρ < 0 (baseline failing ~30% of samples) | ~4 |
| Avoidability filter | ~2 |
| Delta debugging (4 parameters, revert-one-at-a-time with confirmation) | ~8 |
| Boundary search (binary search, 2 surviving parameters, ~6 steps each) | ~12 |
| **Total** | **~26** |

| Configuration | Falsification | E1 evaluation | **Total sims** |
|---|---|---|---|
| **K = 8, 1 seed** (this paper) | 8 × 26 ≈ **210** | 4 conditions × 8 × 1 × 16 scenarios ≈ **510** | **~720** |
| **K = 20, 3 seeds** (September) | 20 × 26 ≈ **520** | 4 × 20 × 3 × 16 ≈ **3 840** | **~4 360** |

"16 scenarios" per evaluation = the counterexample itself + 5 regression + 10 held-out.

Scaling is therefore roughly **6× the simulation budget**, and LLM cost scales as
4 × K × seeds = 32 calls now versus 240 calls in September. Both are dominated by the
evaluation campaign, not by falsification — which is the argument for banking traces and for
the simulation cache.

At an RTF of *f*, a 30 s-horizon episode costs 30/*f* seconds of wall-clock, so
**720 sims ≈ 6.0/f hours** and **4 360 sims ≈ 36.3/f hours**, before any parallelism.

---

## §12 — Cuts, with limitations sentences drafted

Each is written to be pasted into the paper's limitations section.

### §12.1 The runtime safety shield and the SIR metric

> We do not implement a runtime safety shield, so we cannot report whether repairs migrate
> safety out of an opaque runtime override and into readable program logic; our
> interpretability evidence rests instead on blame localization and cumulative tree edit
> distance.

### §12.2 Contracts C3 and C4

> We evaluate three of the five specified contracts — collision, yield-to-oncoming, and
> kinematic comfort — deferring the red-light and RSS-lead-distance contracts; this narrows
> the min-across-contracts blame signal, so a repair that trades red-light compliance for
> yield margin would be invisible to our metrics.

### §12.3 Search-space reduction to four parameters

> Our falsifier searches four scenario parameters rather than eight; the excluded parameters
> are those that primarily stress the two deferred contracts, so the reduction is aligned with
> the contract set rather than independent of it.

### §12.4 Constant-velocity oncoming vehicles

> Oncoming vehicles travel at constant velocity and do not decelerate for the ego, which makes
> the scenario harsher than naturalistic traffic and means our violation rates are an upper
> bound on those a reactive-traffic evaluation would produce.

### §12.5 No black-box optimizer

> Our falsifier uses uniform sampling with ρ-ranked local refinement rather than a black-box
> optimizer, so it requires more simulations per counterexample than an optimized search
> would; because the falsifier is held identical across all four feedback conditions, this
> affects cost but not the comparison.

### §12.6 E2 and closed-loop repair

> We report the controlled repair experiment only; the closed-loop synthesis–falsification–
> repair system is demonstrated but not evaluated, so we characterise how feedback format
> affects a single repair step rather than its compounding effect over many rounds.

### §12.7 Sample size

> With K = 8 counterexamples and a single seed, we report trends rather than statistically
> significant differences between conditions, and we do not claim significance.

### §12.8 Ubuntu version outside the supported matrix

> Our host runs Ubuntu 24.04, outside CARLA's stated support matrix of 20.04 and 22.04; we
> therefore run the simulator in the official container image, which supplies its own
> supported userland, and we verify determinism explicitly rather than assuming it.

---

## §13 — Does any cut damage the central claim?

**The central claim:** *we measure how much formal structure in counterexample feedback is
worth.* Formally, an ablation over the rendering function applied to a fixed set of
counterexamples against a fixed program.

Tested against each cut:

| Cut | Damages the central claim? | Why |
|---|---|---|
| Shield / SIR | **No** — but see below | The shield is downstream of repair and identical across F1–F4. `00_PROJECT_BRIEF` itself calls shield migration a "near-free bonus result" |
| C3, C4 | **No** | The ablation compares conditions against *the same* contract set. Three contracts still give a min, an argmin, and a blame target |
| 8 → 4 parameters | **No** | Held identical across conditions. Also makes boundary search well-defined, which *strengthens* certificate property 7.2 |
| No optimizer | **No** | Falsifier is a fixed input to the ablation, not a variable |
| E2 deferred | **No** | `D8` already designated E1 the primary result and E2 the demonstration |
| K = 8, 1 seed | **Weakens, does not damage** | The comparison remains valid; only its statistical power is reduced. Honest reporting handles this |
| Held-out redesign | **No — improves it** | A reserved region isolates patch overfitting; a new actor class confounded it |

**Nothing in the "never cut" list has been cut.** The certificate's four properties, blame
localization, boundary search, and the F1–F4 distinction are all intact.

### The one cut that costs something real

**Dropping the shield removes the strongest interpretability result the project had.** v1 §8.3
was explicit that shield migration would be "the strongest interpretability result available",
and that is a fair assessment: a *falling* SIR with *held* task completion would have been a
measurement of interpretable safety rather than an assertion of it.

What remains to carry the interpretability claim is **blame localization** (only possible
because the policy is a readable program) and **cumulative TED** (which falsifies the
readability claim if the tree balloons). That is a genuine claim and it is measurable, but it
is *weaker*: it shows the program stays readable and that blame can be assigned, whereas
shield migration would have shown that readability bought something safety-relevant.

**Recommendation: accept the cut for this paper.** The shield is at least a full build-day
(RSS trigger, brake override, shield-on evaluation pass) out of five, it doubles the
evaluation campaign because every scenario must run shield-on *and* shield-off, and it is
orthogonal to the ablation. Restoring it is the obvious first extension for the full paper,
and §12.1 is written so a reviewer sees it was a scoping decision rather than an oversight.

**If you disagree, the cheapest partial restoration** is to keep the shield *only* in the
final evaluation of the best and worst conditions (F4 and F1), reporting SIR for those two.
That costs roughly a third of a full shield implementation and still yields a directional
shield-migration result — but it should be decided before 26 August, because the patching
harness is built that day and adding a shield afterwards means re-running the evaluation
campaign.
