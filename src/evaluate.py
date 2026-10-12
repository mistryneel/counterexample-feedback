"""Evaluation harness: score one program on the 61 E1 scenarios.

61 = 1 counterexample + 30 regression + 30 held-out, IDENTICAL for every
attempt in the campaign. If the scenarios varied by condition the per-condition
rates would not be comparable and the ablation would measure the suite instead
of the feedback.

WHAT IS COMPUTED, and why each one is here:

  resolved            rho >= 0 on the counterexample scenario. THE primary
                      outcome of E1.
  rho*_after          per-contract, not just the min. `headway` moves C1 and C2
                      in opposite directions (+0.555 / -0.435) so min() cancels
                      it; a mean-rho-only report reproduces exactly the mistake
                      docs/sensitivity_analysis.md exists to prevent.
  regression_failures scenarios the FROZEN BASELINE passed that this program
                      does not. Well-defined only because the regression suite
                      is filtered to baseline-passing at build time.
  held_out_scvr       violation rate in the reserved region the falsifier never
                      sampled -- the generalization measure.
  ICR / PCR           a patch that "fixes" a violation by refusing to turn
                      scores perfectly on safety and fails the task. Without
                      these that failure is invisible.

TWO TRAPS ARE GUARDED HERE EXPLICITLY:

  * `scoreable` is NOT `status == 'ok'`. 18 of the 20 banked counterexamples
    end in `status: collision`; filtering on 'ok' would discard 90% of the
    corpus. A rollout is unscoreable only when the trace is missing. This
    module never inspects `status` to decide whether a result counts.

  * C4 IS NON-DETERMINISTIC (docs/determinism_c4.md: up to 0.69 m over
    identical parameters). It is the argmin in 0 of 20 certificates, so the
    corpus is unaffected -- but `resolved` is scored as rho >= 0, so if C4
    became the binding contract AFTER a patch, a repair could be recorded as
    resolving a counterexample it did not. Every evaluation therefore flags
    `c4_binding_after`, and the campaign reports how many attempts tripped it.

SCORING IS NOT REIMPLEMENTED HERE. `Falsifier._score` is the tested path from
episode to Rollout (stl.compute_rho, the argmin lookup, the vacuity flags), and
a second scoring implementation is precisely how "plausible-looking rho from
broken code" gets in. This module composes a Falsifier purely to borrow it, with
the held-out guard disabled -- the falsifier must never sample the reserved
region, and the evaluator must sample nothing else for half its work.
"""
from __future__ import annotations

import math
import pathlib
import random
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from config import param_hash  # noqa: E402
from falsifier import Falsifier  # noqa: E402

CONTRACTS = ("C1", "C2", "C3", "C4", "C5")
PHASES = ("P1_approach", "P2_yield_clear", "P2_yield_hold", "P3_commit", "P4_settle")
PURPOSES = ("counterexample", "regression", "evaluation")


class Evaluator:
    """One persistent backend, one rollout cache, rollouts counted by purpose."""

    def __init__(self, backend, contracts_cfg, junction):
        self.be = backend
        self.contracts_cfg = contracts_cfg
        self.junction = junction
        self.budget = {p: 0 for p in PURPOSES}
        self.cache_hits = 0
        self._cache: dict = {}
        # Borrowed scorer. `lambda p: False` disables the held-out refusal:
        # half of this module's work is deliberately inside the reserved region.
        self._fz = Falsifier(
            backend, contracts_cfg, junction, space={}, types={}, nominal={},
            held_out_fn=lambda p: False,
            program_path=str(REPO_ROOT / "data/scenarios/baseline_program.bt"),
            probe_path=str(REPO_ROOT / "data/scenarios/conservative_probe.bt"),
            rng=random.Random(0), tag="eval")

    # -- one scored episode, cached by (program, params) -------------------
    def rollout(self, params: dict, program: str, purpose: str):
        if purpose not in self.budget:
            raise KeyError(f"unknown rollout purpose {purpose!r}")
        ph = param_hash(params)
        key = f"{program}::{ph}"
        if key in self._cache:
            self.cache_hits += 1
            return self._cache[key]
        self._fz._ensure_program(program)
        res = self.be.run_episode(params, episode_id=f"eval_{purpose[:4]}_{ph}")
        ro = self._fz._score(res, params, ph, program)
        self._cache[key] = ro
        self.budget[purpose] += 1
        return ro

    # -- the full 61-scenario evaluation -----------------------------------
    def evaluate(self, program: str, cert, regression: list, held_out: list) -> dict:
        """Score `program` on one certificate's scenario plus both suites."""
        out: dict = {}

        # --- 1. the counterexample itself: the primary outcome ------------
        ce_params = cert.raw["evaluation_params"]
        ce = self.rollout(ce_params, program, "counterexample")
        out["counterexample_scoreable"] = bool(ce.scoreable)
        out["counterexample_status"] = ce.status
        if ce.scoreable:
            out["rho_after"] = round(float(ce.rho), 6)
            for c in CONTRACTS:
                v = ce.per_contract.get(c)
                out[f"rho{c[1]}_after"] = (None if v is None or math.isnan(v)
                                           else round(float(v), 6))
            out["resolved"] = bool(ce.rho >= 0.0)
            out["argmin_contract_after"] = ce.contract
            out["active_node_after"] = ce.active_node

            # ---- RESOLUTION BY REFUSAL --------------------------------
            # FOUND IN THE DRY RUN, and it would have corrupted the headline
            # number. `resolved` is pre-specified as rho >= 0 on the
            # counterexample scenario, and a program that simply never enters
            # the junction satisfies that trivially: C2 and C3 both go VACUOUS
            # (999.0, the sentinel, excluded from the argmin), C1 is satisfied
            # because nothing is ever nearby, and rho falls through to C5. In
            # the 5-attempt dry run BOTH resolutions were of exactly this kind
            # -- status `timeout`, rho2 = rho3 = 999.0, argmin C5.
            #
            # The plan's answer to this is "ICR/PCR catch that separately",
            # and they do -- but only over the 60 SUITE scenarios. Nothing was
            # recording task completion on the COUNTEREXAMPLE scenario, which
            # is the one `resolved` is computed from, so the suite ICR stayed
            # at 0.93 while the counterexample timed out.
            #
            # `resolved` is NOT redefined here: it is pre-specified and it
            # stays exactly as specified. These are additional fields, and the
            # analysis reports the refusal count alongside the headline rather
            # than quietly subtracting it.
            out["ce_phases_reached"] = list(ce.phases_reached or [])
            out["ce_vacuous_contracts"] = sorted(
                k for k, v in (ce.vacuous or {}).items() if v)
            out["ce_completed"] = bool("P4_settle" in (ce.phases_reached or []))
            out["ce_entered_conflict_zone"] = not bool(
                (ce.vacuous or {}).get("C2", False))
            out["resolved_by_refusal"] = bool(
                out["resolved"] and not out["ce_entered_conflict_zone"])
            out["resolved_and_completed"] = bool(
                out["resolved"] and out["ce_completed"])
            # See the module docstring: C4 binding after a patch means the
            # `resolved` verdict for this attempt rests on a quantity known to
            # drift by up to 0.69 m over identical parameters.
            out["c4_binding_after"] = bool(ce.contract == "C4")
        else:
            # An unscoreable counterexample is NOT a resolution and must never
            # be counted as one. It is its own outcome.
            out["rho_after"] = None
            for c in CONTRACTS:
                out[f"rho{c[1]}_after"] = None
            out["resolved"] = False
            out["argmin_contract_after"] = None
            out["active_node_after"] = None
            out["c4_binding_after"] = False
            out["evaluation_error"] = ce.error
            out["ce_phases_reached"] = []
            out["ce_vacuous_contracts"] = []
            out["ce_completed"] = False
            out["ce_entered_conflict_zone"] = False
            out["resolved_by_refusal"] = False
            out["resolved_and_completed"] = False

        # --- 2. regression suite -----------------------------------------
        reg = [self.rollout(s["params"], program, "regression") for s in regression]
        fails = [s["param_hash"] for s, ro in zip(regression, reg)
                 if not (ro.scoreable and ro.rho >= 0.0)]
        out["regression_failures"] = len(fails)
        out["regression_failed_hashes"] = fails
        out["regression_n"] = len(regression)
        out["regression_unscoreable"] = sum(1 for ro in reg if not ro.scoreable)
        out["searched_scvr"] = round(len(fails) / len(regression), 6) if regression else None

        # --- 3. held-out suite -------------------------------------------
        ho = [self.rollout(s["params"], program, "evaluation") for s in held_out]
        ho_viol = [ro for ro in ho if ro.scoreable and ro.rho < 0.0]
        out["held_out_n"] = len(held_out)
        out["held_out_violations"] = len(ho_viol)
        out["held_out_unscoreable"] = sum(1 for ro in ho if not ro.scoreable)
        out["held_out_scvr"] = round(len(ho_viol) / len(held_out), 6) if held_out else None
        if out["searched_scvr"] is not None and out["held_out_scvr"] is not None:
            out["generalization_gap"] = round(
                out["searched_scvr"] - out["held_out_scvr"], 6)
        else:
            out["generalization_gap"] = None

        # --- 4. task completion, over all 60 suite scenarios --------------
        # The counterexample is EXCLUDED: it is one adversarially-chosen
        # scenario per attempt and pooling it with 60 sampled ones would let a
        # per-certificate quirk move a rate that is meant to describe the suite.
        suite = reg + ho
        scoreable = [ro for ro in suite if ro.scoreable]
        out["icr"] = (round(sum(1 for ro in scoreable
                                if "P4_settle" in (ro.phases_reached or [])
                                ) / len(scoreable), 6) if scoreable else None)
        out["pcr"] = (round(sum(len(set(ro.phases_reached or []) & set(PHASES))
                                / len(PHASES) for ro in scoreable
                                ) / len(scoreable), 6) if scoreable else None)

        # --- 5. per-contract means, so min() cannot hide a contract -------
        for c in CONTRACTS:
            vals = [ro.per_contract[c] for ro in scoreable
                    if c in ro.per_contract and not math.isnan(ro.per_contract[c])
                    and not ro.vacuous.get(c, False)]
            out[f"suite_mean_rho{c[1]}"] = (round(sum(vals) / len(vals), 6)
                                            if vals else None)
        out["suite_min_rho"] = (round(min(ro.rho for ro in scoreable), 6)
                                if scoreable else None)
        return out

    def snapshot(self) -> dict:
        return dict(self.budget)


def budget_delta(before: dict, after: dict) -> dict:
    """Rollouts spent by ONE attempt, per purpose."""
    return {f"rollouts_{k}": after[k] - before.get(k, 0) for k in after}


def load_suites() -> tuple[list, list, dict, dict]:
    """The two frozen suites, plus their metadata. Raises if either is missing."""
    import json
    reg_p = REPO_ROOT / "data" / "scenarios" / "regression_suite.json"
    held_p = REPO_ROOT / "data" / "scenarios" / "held_out_suite.json"
    for p in (reg_p, held_p):
        if not p.exists():
            raise FileNotFoundError(
                f"{p} does not exist. Run scripts/build_suites.py first -- "
                "without both suites there is no regression measure and no "
                "generalization result.")
    reg = json.loads(reg_p.read_text())
    held = json.loads(held_p.read_text())
    return reg["scenarios"], held["scenarios"], reg, held
