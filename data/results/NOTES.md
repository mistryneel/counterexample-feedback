# data/results

Saved outputs of every stage of the experiment. The paper's results are read or recomputed
from these files together with `data/certificates/`, `data/scenarios/` and `logs/`, without
re-running the simulator or the model. `scripts/reproduce_paper_numbers.py` checks each
quantitative claim in `paper/main.tex` against them, states the basis of each, and lists any
mismatch or any number it cannot recompute.

Each entry names the script that wrote the file and what that script needs: **offline**
(Python only), **CARLA** (the simulator) or **API** (the hosted model). Result files are kept
exactly as written. Files that no script writes are marked as such.

## Repair campaign (E1)

| File | Contents | Written by |
|---|---|---|
| `patches.jsonl` | 300 records, one per repair attempt (5 conditions x 20 counterexamples x 3 replicates): prompt and response paths and hashes, model identifier, token usage, the program before and after the patch, validator result, patch type, tree edit distance. Phase A of the campaign. | `scripts/run_e1.py` (API) |
| `attempts.jsonl` | The same 300 records extended with the evaluation of each patched program: rho before and after (overall and per contract), resolution, refusal, completion, regression failures, held-out violations, rollout counts by purpose. Phase B. **The primary record of the experiment.** Schema check: `scripts/check_attempts_schema.py`. | `scripts/run_e1.py` (CARLA) |
| `patched_programs/` | The 300 patched programs, one `<attempt_id>.bt` each, identical to `bt_source_after` in `attempts.jsonl`. | `src/patcher.py`, called by `scripts/run_e1.py` |
| `baseline_eval.json` | The unpatched baseline scored on each counterexample and on the regression and held-out suites; the reference row for the generalization numbers. | `scripts/run_e1.py` (CARLA) |
| `dryrun_patches.jsonl`, `dryrun_attempts.jsonl`, `dryrun_baseline_eval.json` | Five-attempt dry run before the campaign (counterexample CE003, one attempt per condition). Not part of any reported result. | `scripts/run_e1.py --dry-run` (API, CARLA) |

The exact prompts sent and responses received in the campaign are in `logs/campaign/prompts/`
and `logs/campaign/responses/`, one file per `attempt_id`.

## Analysis (offline)

| File | Contents | Written by |
|---|---|---|
| `uncertainty.json` | Paired cluster bootstrap over the 20 counterexamples (10,000 resamples, seed 0): every interval in the paper, including the 17 tabulated differences and the multiplicity counts. Regenerates byte-identically. | `scripts/uncertainty.py` |
| `e1_analysis.json` | Per-condition point estimates (rates, refusal split, token cost, regression failures, edit distance, completion, violation rates, generalization gap, per-contract rho), the per-counterexample outcome grid and cross-tabulations. No intervals; those are in `uncertainty.json`. Regenerates byte-identically. | `scripts/analyze_e1.py` |
| `detectable_effect.json` | Simulation of how large an improvement over F3 this design could detect (the paper's appendix on detectable effects). | `scripts/detectable_effect.py` |

## Baseline synthesis and calibration

| File | Contents | Written by |
|---|---|---|
| `synthesis.json` | Summary of the last synthesis batch only (6 calls, 6 valid). All 21 synthesis calls are listed in `logs/llm_index.jsonl`. | `scripts/synthesize_baseline.py` (API) |
| `baseline_calibration.json` | The 14 valid candidates scored on one shared set of 100 calibration scenarios (seed 20260830): violation rate, binding contract, blame entropy, gate results. It records violations only, not junction entry or completion. | `scripts/calibrate_baseline.py` (CARLA) |
| `baseline_calibration_frozen.json` | The frozen baseline's calibration run re-scored from its 100 saved trajectories (`data/calibration_traces/`): 20 violations, entry in 100, completion in 90. Source of the entry and completion counts in Section 3.2. | `scripts/rescore_calibration.py` (offline) |
| `baseline_calibration_probe.json` | Pre-freeze diagnostic: the reference program and two hand-written probe programs (`data/scenarios/probes/`) under the five-contract gate. None of them is the baseline. | `scripts/calibrate_baseline.py --out` (CARLA) |

## Falsification and blame

| File | Contents | Written by |
|---|---|---|
| `falsification_summary.json` | The falsification run that produced the 20 certificates in `data/certificates/`: rollouts by stage, avoidability rejections, blame entropy, reproducibility checks. | `scripts/run_falsification.py` (CARLA) |
| `blame_recompute.json` | Blame entropy under both definitions (active node, authorizing node) and the suppressed `headway` boundaries, from the 20 counterexample trajectories. | `scripts/recompute_blame.py` (offline; reads `data/certificates/traces/`) |

## Prompts

| File | Contents | Written by |
|---|---|---|
| `prompt_budget.json` | Token count of every rendered prompt (20 counterexamples x 5 conditions), the size of the shared scaffolding, and the F1 trace-window ladder. | `scripts/check_prompt_budget.py` (API token counting) |
| `rendered_prompts/` | The five complete prompts for counterexample CE003, one per condition. Identical to what `Certificate.prompt` in `src/certificate.py` renders today. | written during renderer development |
| `renderer_smoke.json` | One model call per condition on CE003, checking that each prompt returns a parseable program. Not a result. | `scripts/smoke_render.py` (API) |

## Expressiveness and the clean repair (Table 4, Section 4.3)

| File | Contents | Written by |
|---|---|---|
| `dsl_probe_rescore.json` | Table 4 recomputed from the saved trajectories in `data/dsl_probe_traces/`, per row and per program variant, with per-episode values and a cross-check against `dsl_expressiveness.json`. | `scripts/rescore_dsl_probes.py` (offline) |
| `clean_repair_rescore.json` | The clean repair (`F1__CE005_C1_5b773c94ec4bb251__s3`) re-scored on all 20 counterexamples and on its six repeats, with a cross-check against `clean_repair_validation.json`. | `scripts/rescore_dsl_probes.py` (offline) |
| `dsl_expressiveness.json` | Hand-written summary of the constructive test: repairs written by hand and run on all 20 counterexamples. Partly superseded; see caveat 1. | hand-written |
| `clean_repair_validation.json` | Hand-written summary of the checks on the one attempt that satisfied the contracts, completed the turn and broke nothing. | hand-written |

## Simulator checks

| File | Contents | Written by |
|---|---|---|
| `determinism_gate.json` | Determinism gate: repeated episodes with identical parameters, physics settings, real-time factor. | `scripts/determinism_gate.py` (CARLA) |
| `determinism_c4.json` | Per-contract spread over 6 repeats on 3 scenarios; shows the C4 non-determinism (caveat 6). | `scripts/probe_c4_determinism.py` (CARLA) |
| `seed_sensitivity.json`, `tm_probe_{a1,a2,b1,b2}.npy` | Traffic Manager seed check across full server restarts; the `.npy` files are the raw vehicle positions it compares. | `scripts/seed_sensitivity.py` (run by `determinism_gate.py`) and `scripts/tm_probe.py` (CARLA) |
| `control_map.json` | Measured map from commanded throttle and brake to longitudinal acceleration; read by `src/stl.py` to compute C5. | `scripts/calibrate_control_map.py` (CARLA) |
| `c5_threshold_sweep.json` | Ego-speed threshold below which CARLA's low-speed braking artefact is excluded from C5. | `scripts/c5_threshold_sweep.py` (offline, but needs the `bank` trajectories in `data/traces/`, which are not released; cannot be re-run from this repository) |
| `sensitivity.json`, `sensitivity_g2.json` | Correlation of each scenario parameter with robustness: 300 `g1` episodes under C1 and C2, and 180 `g2` episodes under C1, C2 and C5. Development stage, before the six-parameter space. | `scripts/sensitivity_analysis.py` (offline, but needs the `g1`/`g2` trajectories in `data/traces/`, which are not released; cannot be re-run from this repository) |

## Development records

| File | Contents | Written by |
|---|---|---|
| `campaign_{bank,g1,g2,g3,g4,g5}_{shard}.jsonl` | Episode manifests (one line per simulated episode: parameters, status, trajectory path) of exploratory runs: `bank` (300 episodes, 23 Aug 2026, hardcoded controller rather than a behaviour tree; see `docs/trace_provenance.md`), `g1` (300) and `g2` (180) on 29 Aug, `g3` to `g5` (200 each) on 30 Aug. | `scripts/run_campaign.py` (CARLA) |
| `bank_rho.json` | C1 and C2 robustness of the 300 `bank` episodes. Predates the repository; no committed script writes it. | none |

## Caveats

1. **`dsl_expressiveness.json`: `finding` and `implication` are superseded.** `finding` says
   that, across the hand-written edits, no program both satisfied the contracts and completed
   the manoeuvre; `implication` concludes that refusal is the only expressible fix. The
   model's clean repair, which lies outside that family of edits, satisfies the contracts and
   completes the turn on all 20 counterexamples (`clean_repair_validation.json`, recomputed in
   `clean_repair_rescore.json`). The implication is therefore false, and the finding holds
   only for the edits tested. Section 4.3 of the paper gives the corrected account. The file
   is left byte-identical as a historical record. It also lists one variant that Table 4
   omits (adding `TrafficLightIsGreen` to branch C, 0 of 20 resolved).

2. **The header of `data/scenarios/baseline_program.bt` predates the corrected counts.** The
   file is frozen, so its header was not edited. It says the program was "sampled 1 of 20" and
   gives "ICR 88.3%". `logs/llm_index.jsonl` holds 21 synthesis calls: 18 with one fixed prompt
   (two truncated at the 16,000-token output cap, 14 of the other 16 valid) and 3 earlier calls
   with a different prompt. On the 100 calibration scenarios the frozen baseline completes the
   turn in 90 (`baseline_calibration_frozen.json`). 88.3% matches 53 of 60, which the header
   attributes to a separate 60-scenario draw whose results are not in this directory. Where the
   header and the paper differ, the paper is authoritative.

3. **`dsl_expressible` is null in all 300 attempts.** The planned manual review of
   sampled failures was not completed. The constructive test of Table 4 replaced it.

4. **Some raw API records in `logs/llm_raw/` were overwritten.** `src/llm.py` built `call_id`
   from a hash of the system prompt alone (an operator-precedence slip) and the whole-second
   value of a timer, so parallel calls with the same tag and system prompt that started in the
   same second shared an identifier. Among the 300 attempts there are 286 distinct `call_id`
   values; 25 attempts fall in 11 colliding groups, and for 14 attempts the raw record under
   their `call_id` holds a sibling's response. The per-attempt files in
   `logs/campaign/prompts/` and `logs/campaign/responses/` are named by `attempt_id` and are
   complete: 300 of each, and every prompt matches `prompt_sha256_16` in `attempts.jsonl`.
   No reported number uses a response text from `logs/llm_raw/`.

5. **Evaluation trajectories were not retained per attempt.** The campaign ran 18,300
   evaluation rollouts (300 counterexample, 9,000 regression, 9,000 held-out). Each
   trajectory file was named by the scenario's parameter hash only, so every attempt
   overwrote the previous attempt's file for the same scenario, and only the last write to
   each survived (80 trajectories, one per scenario). The simulator-derived fields of
   `attempts.jsonl` are therefore the record; they can be recomputed from it but not
   re-scored from trajectories.

6. **rho4 (C4, RSS lead distance) is not deterministic.** Over 6 repeats of 3 scenarios
   (`determinism_c4.json`) rho4 spreads by up to 0.69 m, while C1, C2, C3, C5 and the overall
   rho reproduce exactly. The cause is that the lead vehicle's speed profile switches on a
   position read back from the simulator (`docs/determinism_c4.md`). C4 is never the binding
   contract after any of the 300 patches (`c4_binding_after` is false in all of them), so no
   reported resolution depends on it.

7. **Means over rho2 include the vacuity sentinel.** A contract that never applies (C2 when
   the ego never enters the conflict zone) is scored 999.0 so that it never wins the minimum.
   `mean_rho2_after` in `e1_analysis.json` averages over these values: F1's 173.18 is 8.02 with
   its 10 sentinel values removed. Exclude 999.0 (see `ce_vacuous_contracts` in
   `attempts.jsonl`) before averaging any per-contract robustness. The paper reports no mean
   of rho2.

8. **No noise floor.** An earlier version of `e1_analysis.json` carried a key
   `noise_floor_f4a_minus_f3` (0.05). It was removed, and no other key or value changed. F4a
   carries no information beyond F3, but its prompt is 91 tokens longer, so it is not a noise
   replicate and its difference from F3 sets no resolution for the experiment. All intervals
   come from the paired cluster bootstrap in `scripts/uncertainty.py`.

9. **Absolute paths are historical.** The certificates (`trace_path`, 20 of 20), the
   `campaign_*.jsonl` manifests, `determinism_c4.json`, `determinism_gate.json` and
   `falsification_summary.json` store absolute paths (`/home/npk/Projects/cv_research/...`) from the machine that ran
   the experiment. They are left unchanged because the files are results. Certificate
   trajectories are resolved by file name: `resolve_trace_path` in `src/certificate.py`
   looks in `data/certificates/traces/` first, then at the stored path.
