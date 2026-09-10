#!/usr/bin/env python3
"""Adversarial falsifier: search, minimize, generalize, filter, account.

Six pieces, in the order a counterexample passes through them:

  1. SEARCH          uniform random over the six-parameter space, then
                     PER-CONTRACT rho-ranked local refinement
  2. DELTA DEBUGGING revert each parameter to nominal; drop the ones that do
                     not affect the violation                (Zeller & Hildebrandt)
  3. BOUNDARY SEARCH binary-search each surviving parameter for the rho=0
                     crossing, so the certificate reports a BOUNDARY not a point
  4. AVOIDABILITY    replay under a maximally conservative reference program;
                     admit only if a violation-free response existed (RSS rule 5)
  5. SIMULATION CACHE keyed by (program, config.param_hash) -- an identical
                     parameter set is never re-run
  6. ROLLOUT ACCOUNTING broken out by purpose, never a single total

Design note -- why (2) and (3) are pure functions over an injected `evaluate`
callable rather than methods that reach into CARLA: both are algorithms with
known answers on synthetic inputs, and the build plan requires them to be unit
tested on synthetic functions BEFORE being trusted on real data. Coupling them
to the simulator would make that impossible. `Falsifier` supplies a
CARLA-backed `evaluate`; `tests/test_falsifier.py` supplies an analytic one.

Spec: 01_TECHNICAL_SPEC_v2.md §6 and §7. Measured constraints that shape this
module: docs/sensitivity_analysis.md (per-contract ranking) and
data/scenarios/space.yaml (bounds, held-out hole, plausibility).
"""
from __future__ import annotations

import math
import pathlib
import random
import sys
from dataclasses import dataclass, field
from typing import Callable

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

from config import param_hash  # noqa: E402

# The sentinel a contract reports when its predicate was never applied (the
# ego never entered the conflict zone, no lead spawned, ...). Set in
# config/contracts.yaml as `vacuous_rho: 999.0`. A vacuous contract carries no
# gradient, so refinement must not rank on it.
VACUOUS_SENTINEL = 999.0


# ==========================================================================
# What one simulation produces, after scoring
# ==========================================================================

@dataclass
class Rollout:
    """One scored simulation. NEVER raises -- failures are data.

    `scoreable` is deliberately NOT `status == 'ok'`. An episode that ends in
    a collision is marked `collision`, has a real trace on disk, and is the
    least ambiguous violation there is. Filtering on status == 'ok' previously
    undercounted a program's failure rate by 18.8 points (37.3% reported
    against 56.1% true). The only thing that makes a rollout unscoreable is a
    MISSING TRACE.
    """

    params: dict
    param_hash: str
    program: str
    status: str
    trace_path: str | None = None
    scoreable: bool = False
    rho: float = float("nan")
    contract: str | None = None
    per_contract: dict[str, float] = field(default_factory=dict)
    vacuous: dict[str, bool] = field(default_factory=dict)
    argmin_index: int | None = None
    t_s: float | None = None
    frame: int | None = None
    node_type: str | None = None
    node_path: str | None = None
    tick_path: str | None = None
    phases_reached: list = field(default_factory=list)
    achieved_gap_s: float | None = None
    error: str | None = None

    @property
    def violated(self) -> bool:
        return self.scoreable and self.rho < 0.0

    def rho_of(self, contract: str) -> float:
        """Per-contract robustness, NaN if that contract was not evaluated."""
        return self.per_contract.get(contract, float("nan"))

    @property
    def active_node(self) -> str | None:
        """`bt_node_type:bt_node_path` at the argmin row.

        A LOOKUP, not an inference: the value is read straight off the trace
        row that compute_rho identified as the argmin. There is no attribution
        method here and there must not be one.
        """
        if self.node_type is None:
            return None
        return f"{self.node_type}:{self.node_path}"


# ==========================================================================
# Rollout accounting
# ==========================================================================

PURPOSES = ("falsification", "minimization", "boundary", "avoidability")


@dataclass
class RolloutBudget:
    """Rollouts broken out by purpose. A single total is not usable.

    The cost-axis argument depends on attributing minimization and
    boundary cost to the stage that incurs it -- F1 and F2 pay that cost in E1
    (the corpus is shared) but would not in a deployed closed loop, and that
    asymmetry cannot be stated without these four numbers kept apart.
    """

    counts: dict = field(default_factory=lambda: {p: 0 for p in PURPOSES})
    cache_hits: dict = field(default_factory=lambda: {p: 0 for p in PURPOSES})

    def charge(self, purpose: str, cached: bool) -> None:
        if purpose not in self.counts:
            raise KeyError(f"unknown rollout purpose {purpose!r}")
        if cached:
            self.cache_hits[purpose] += 1
        else:
            self.counts[purpose] += 1

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    @property
    def total_cache_hits(self) -> int:
        return sum(self.cache_hits.values())

    @property
    def cache_hit_rate(self) -> float:
        seen = self.total + self.total_cache_hits
        return (self.total_cache_hits / seen) if seen else 0.0

    def as_dict(self) -> dict:
        return {
            "rollouts_falsification": self.counts["falsification"],
            "rollouts_minimization": self.counts["minimization"],
            "rollouts_boundary": self.counts["boundary"],
            "rollouts_avoidability": self.counts["avoidability"],
            "rollouts_total": self.total,
            "cache_hits": dict(self.cache_hits),
            "cache_hits_total": self.total_cache_hits,
            "cache_hit_rate": round(self.cache_hit_rate, 4),
        }

    def snapshot(self) -> dict:
        return {f"rollouts_{p}": self.counts[p] for p in PURPOSES}


def budget_delta(before: dict, after: dict) -> dict:
    """Per-purpose rollouts spent between two snapshots.

    The certificate records what THIS counterexample cost, not what the
    campaign has cost so far.
    """
    return {k: after[k] - before.get(k, 0) for k in after}


# ==========================================================================
# 2. Delta debugging  (spec §7.1, Zeller & Hildebrandt, IEEE TSE 2002)
# ==========================================================================

def delta_debug(params: dict,
                nominal: dict,
                violates: Callable[[dict], bool | None],
                order: list | None = None) -> tuple[dict, list, list]:
    """Revert each parameter to nominal one at a time; drop the irrelevant.

    A parameter is IRRELEVANT if setting it to its nominal value leaves the
    violation in place -- the violation did not need it, so the certificate
    must not mention it. Every drop is CONFIRMED by re-testing, and drops are
    cumulative: once a parameter is reverted it stays reverted, so the result
    is a locally minimal violating configuration rather than a set of
    independently-irrelevant parameters.

    `violates(cfg)` returns True (still violating), False (violation gone), or
    None (could not be evaluated -- refused sample, unscoreable episode). None
    is treated as "do not drop": an unevaluated parameter is kept, because
    dropping on missing evidence would silently shrink the certificate.

    Returns (minimal_params, dropped_names, kept_names).
    """
    current = dict(params)
    dropped, kept = [], []
    for name in (order if order is not None else list(params.keys())):
        if name not in nominal or name not in current:
            continue
        if current[name] == nominal[name]:
            # Already at nominal: it cannot be part of what made this fail.
            dropped.append(name)
            continue
        trial = dict(current)
        trial[name] = nominal[name]
        still = violates(trial)
        if still is True:
            current = trial          # confirmed: violation survives the revert
            dropped.append(name)
        else:
            kept.append(name)        # False or None -> keep
    return current, dropped, kept


# ==========================================================================
# 3. Boundary search  (spec §7.2)
# ==========================================================================

@dataclass
class Boundary:
    """Where rho crosses zero along one parameter axis."""

    parameter: str
    threshold: float | None          # the crossing, None if not bracketed
    direction: str                   # ">=" (fails at/above) or "<=" (fails at/below)
    violating_value: float           # the counterexample's value on this axis
    nominal_value: float             # the benign end the search bisected toward
    bracket: tuple                   # (violating_side, safe_side) at termination
    n_evals: int = 0
    resolved: bool = False
    note: str = ""

    def render(self) -> str:
        """The phrasing that goes in the certificate, verbatim."""
        if not self.resolved or self.threshold is None:
            return f"{self.parameter}: {self.note or 'boundary not resolved'}"
        return f"{self.parameter} {self.direction} {self.threshold:.4g}"


def boundary_search(params: dict,
                    name: str,
                    nominal_value: float,
                    evaluate: Callable[[dict], float | None],
                    tol: float,
                    is_integer: bool = False,
                    max_evals: int = 12) -> Boundary:
    """Binary-search one axis for the rho = 0 crossing.

    The certificate must report a BOUNDARY, not a point: "fails for
    v_oncoming >= 13.6" rather than "fails at v_oncoming = 14.0". A point
    counterexample makes the LLM spend its token budget walking a number line,
    which is the CEGIS pathology §7.2 exists to avoid.

    Bisects between the counterexample's own value (known violating, rho < 0)
    and `nominal_value` (expected benign). All other parameters stay at their
    minimized counterexample values, so the reported threshold is conditional
    on them -- which is why the certificate conjoins the per-axis boundaries
    rather than reporting them as independent facts.

    `evaluate(cfg)` returns rho for the contract under test, or None if that
    configuration could not be evaluated (e.g. it lands in the held-out
    region, which must never be simulated). A None terminates the search with
    whatever bracket has been established, flagged -- it never guesses.
    """
    v_bad = float(params[name])
    v_safe = float(nominal_value)
    direction = ">=" if v_bad > v_safe else "<="
    b = Boundary(parameter=name, threshold=None, direction=direction,
                 violating_value=v_bad, nominal_value=v_safe,
                 bracket=(v_bad, v_safe))

    if v_bad == v_safe:
        b.note = "violating value equals nominal; nothing to bisect"
        return b

    # Confirm the safe end is actually safe. If the violation persists all the
    # way to nominal there is no crossing ON THIS AXIS inside the space, which
    # is itself a reportable fact -- and a stronger one than a threshold.
    safe_cfg = dict(params)
    safe_cfg[name] = int(round(v_safe)) if is_integer else v_safe
    r_safe = evaluate(safe_cfg)
    b.n_evals += 1
    if r_safe is None:
        b.note = "nominal end could not be evaluated"
        return b
    if r_safe < 0:
        b.note = (f"violates across the whole range: still fails at "
                  f"{name} = {v_safe:.4g}")
        b.bracket = (v_bad, v_safe)
        return b

    lo, hi = v_bad, v_safe            # lo violates, hi is safe
    while b.n_evals < max_evals and abs(hi - lo) > tol:
        mid = (lo + hi) / 2.0
        if is_integer:
            mid = float(int(round(mid)))
            if mid == lo or mid == hi:
                break
        cfg = dict(params)
        cfg[name] = int(mid) if is_integer else mid
        r = evaluate(cfg)
        b.n_evals += 1
        if r is None:
            b.note = (f"bisection stopped at {name} = {mid:.4g}: "
                      f"configuration could not be evaluated "
                      f"(held-out region or unscoreable episode)")
            break
        if r < 0:
            lo = mid
        else:
            hi = mid

    b.bracket = (lo, hi)
    # The crossing is bracketed by lo (violating) and hi (safe). Report the
    # VIOLATING side. "fails for v >= lo" is supported by measurement at every
    # value the search actually tested on that side; reporting `hi` would put
    # a number in the certificate that our own last evaluation scored as SAFE,
    # i.e. assert a failure we measured not to happen. The bracket is carried
    # alongside so the residual uncertainty stays visible rather than being
    # rounded away.
    b.threshold = round(lo, 4)
    b.resolved = True
    if not b.note:
        b.note = (f"crossing bracketed to [{min(lo, hi):.4g}, "
                  f"{max(lo, hi):.4g}] in {b.n_evals} evaluations")
    return b


def render_boundary_report(boundaries: list, contract: str) -> str:
    """Conjoin per-axis boundaries into the sentence the certificate carries.

    e.g. "C2 fails for v_oncoming >= 13.6 when headway <= 3.4"
    """
    resolved = [b for b in boundaries if b.resolved and b.threshold is not None]
    if not resolved:
        unresolved = "; ".join(b.render() for b in boundaries)
        return f"{contract} boundary not resolved ({unresolved or 'no free parameters'})"
    head = resolved[0].render()
    if len(resolved) == 1:
        return f"{contract} fails for {head}"
    rest = " and ".join(b.render() for b in resolved[1:])
    return f"{contract} fails for {head} when {rest}"


# ==========================================================================
# 1. Search: uniform random + PER-CONTRACT rho-ranked local refinement
# ==========================================================================

def rank_seeds_per_contract(rollouts: list,
                            contracts: list,
                            r: int) -> list:
    """Top-`r` lowest-robustness points FOR EACH CONTRACT SEPARATELY.

    ⚠️ This is the whole reason the refinement is written out rather than
    calling `sorted(key=rho)`. Measured in docs/sensitivity_analysis.md,
    `headway` correlates +0.555 with C1 and -0.435 with C2 -- a strong effect
    on both contracts IN OPPOSITE DIRECTIONS. rho = min(C1..C5) cancels them
    to -0.068, so a search ranked on overall rho sees NO gradient on the
    headway axis at all and will push v_oncoming and aggressiveness to their
    bounds while never exploring headway.

    Ranking each contract on its OWN robustness restores the gradient: the
    C2-ranked list pulls toward large headway, the C1-ranked list toward
    small, and refinement explores both.

    Vacuous contracts are excluded. Their sentinel (999.0) is not a margin --
    ranking on it would seed refinement from scenarios where the contract was
    never even applied.

    Returns a list of (rollout, contract) seed pairs.
    """
    seeds = []
    for c in contracts:
        scored = [
            ro for ro in rollouts
            if ro.scoreable
            and not ro.vacuous.get(c, False)
            and not math.isnan(ro.rho_of(c))
            and ro.rho_of(c) < VACUOUS_SENTINEL
        ]
        scored.sort(key=lambda ro: ro.rho_of(c))
        for ro in scored[:r]:
            seeds.append((ro, c))
    return seeds


def perturb(params: dict,
            space: dict,
            types: dict,
            rng: random.Random,
            radius_frac: float) -> dict:
    """Resample inside a shrinking neighbourhood, clamped to the bounds.

    Plausibility is enforced HERE, at sample time, not checked afterwards
    (spec §6.2, following Scenic). Clamping to the declared range is what
    keeps refinement from wandering into the physically absurd corner where
    the LLM over-patches and task completion collapses -- the most likely way
    this project fails quietly.
    """
    out = {}
    for name, value in params.items():
        lo, hi = space[name]
        span = float(hi) - float(lo)
        step = rng.uniform(-radius_frac, radius_frac) * span
        v = float(value) + step
        v = max(float(lo), min(float(hi), v))
        if types.get(name) == "integer":
            out[name] = int(round(v))
        else:
            out[name] = round(v, 4)
    return out


# ==========================================================================
# 4./5./6. The falsifier proper -- CARLA-backed
# ==========================================================================

class Falsifier:
    """Wires the algorithms above onto a persistent CARLA backend.

    ONE persistent client for the whole campaign (project engineering
    invariants). Every episode is wrapped so an exception returns a sentinel
    and never kills the campaign.
    """

    def __init__(self, backend, contracts_cfg, junction, space, types,
                 nominal, held_out_fn, program_path, probe_path,
                 rng, tag="fals"):
        self.be = backend
        self.contracts_cfg = contracts_cfg
        self.junction = junction
        self.space = space
        self.types = types
        self.nominal = nominal
        self._in_held_out = held_out_fn
        self.program_path = str(program_path)
        self.probe_path = str(probe_path)
        self.rng = rng
        self.tag = tag

        self.budget = RolloutBudget()
        self._cache: dict = {}
        self._loaded: str | None = None
        self.active_contracts = list(contracts_cfg["combined"]["active"])
        self.refusals = 0          # samples refused for landing in held-out

    # -- program handling -------------------------------------------------
    def _ensure_program(self, program: str) -> None:
        if self._loaded != program:
            self.be.load_program(program)
            self._loaded = program

    # -- 5. simulation cache ---------------------------------------------
    def rollout(self, params: dict, purpose: str,
                program: str | None = None) -> Rollout | None:
        """Simulate (or serve from cache) and score. Never raises.

        Returns None -- a REFUSAL, not a failure -- if the parameters land in
        the held-out region. That region is reserved for evaluation and the
        falsifier must never sample it, so this guard sits at the single point
        every rollout passes through rather than at each call site.

        The cache key includes the PROGRAM. The avoidability filter replays
        identical parameters under a different program, and a params-only key
        would serve the baseline's trace for the conservative probe and quietly
        make every counterexample look unavoidable.
        """
        program = program or self.program_path
        if self._in_held_out(params):
            self.refusals += 1
            return None

        ph = param_hash(params)
        key = f"{program}::{ph}"
        if key in self._cache:
            self.budget.charge(purpose, cached=True)
            return self._cache[key]

        self._ensure_program(program)
        prog_tag = "probe" if program == self.probe_path else self.tag
        res = self.be.run_episode(params, episode_id=f"{prog_tag}_{purpose[:4]}_{ph}")
        ro = self._score(res, params, ph, program)
        self._cache[key] = ro
        self.budget.charge(purpose, cached=False)
        return ro

    def _score(self, res, params, ph, program) -> Rollout:
        """Score a finished episode. Failures are recorded, never raised."""
        import stl

        ro = Rollout(params=dict(params), param_hash=ph, program=program,
                     status=res.status, trace_path=res.trace_path,
                     error=res.error)
        try:
            ro.phases_reached = list((res.meta or {}).get("phases_reached") or [])
            ro.achieved_gap_s = (res.meta or {}).get("achieved_gap_s")
        except Exception:
            pass

        # A missing trace is the ONLY thing that makes an episode unscoreable.
        # `collision` and `timeout` are legitimate terminations with real
        # trajectories -- see the Rollout docstring.
        if not res.trace_path or not pathlib.Path(res.trace_path).exists():
            return ro
        try:
            df, _meta = stl.load_trace(res.trace_path)
            r = stl.compute_rho(df, self.contracts_cfg, self.junction)
            ro.scoreable = True
            ro.rho = float(r.rho)
            ro.contract = r.contract
            ro.per_contract = {k: float(v.rho) for k, v in r.per_contract.items()}
            ro.vacuous = {k: bool(v.vacuous) for k, v in r.per_contract.items()}
            ro.argmin_index = (int(r.argmin_index)
                               if r.argmin_index is not None else None)
            ro.t_s = float(r.t_s) if r.t_s is not None else None
            ro.frame = int(r.frame) if r.frame is not None else None
            if ro.argmin_index is not None:
                row = df.iloc[ro.argmin_index]
                # LOOKUP, not inference (spec §7.5).
                ro.node_type = str(row["bt_node_type"])
                ro.node_path = str(row["bt_node_path"])
                ro.tick_path = str(row["bt_tick_path"])
        except Exception as exc:
            ro.scoreable = False
            ro.error = f"{type(exc).__name__}: {exc}"
        return ro

    def reproduce(self, params: dict, contract: str | None = None,
                  program: str | None = None):
        """Re-simulate a parameter set with the cache BYPASSED, to test rho.

        Determinism is load-bearing (project rule 6): identical parameters
        must give identical rho, and a silent determinism bug corrupts every
        result downstream without ever throwing. The cache means the campaign
        only ever simulates a given configuration ONCE, which makes the
        campaign internally consistent but also means it would never NOTICE
        such a bug. This deliberately pays for one extra simulation per
        admitted counterexample to turn that assumption into a measurement.

        Not charged to the four schema purposes -- it is verification, not
        falsification cost, and folding it into them would inflate exactly the
        numbers the cost-axis argument depends on. The driver counts it
        separately as `rollouts_verification`.
        """
        program = program or self.program_path
        if self._in_held_out(params):
            return None
        self._ensure_program(program)
        ph = param_hash(params)
        res = self.be.run_episode(params, episode_id=f"{self.tag}_verify_{ph}")
        return self._score(res, params, ph, program)

    # -- 1. search --------------------------------------------------------
    def uniform_batch(self, sampler, n: int) -> list:
        """N uniform samples, scored. The sampler already excludes held-out."""
        out = []
        for _ in range(n):
            ro = self.rollout(sampler(), "falsification")
            if ro is not None:
                out.append(ro)
        return out

    def refine(self, pool: list, r: int, n_per_seed: int,
               radius_frac: float) -> list:
        """Per-contract rho-ranked local refinement.

        Around each seed, resample within a shrinking neighbourhood and keep
        any point with LOWER robustness ON THAT SEED'S CONTRACT -- not on the
        overall min, for the reason set out in rank_seeds_per_contract.
        """
        found = []
        for ro, c in rank_seeds_per_contract(pool, self.active_contracts, r):
            best = ro
            radius = radius_frac
            for _ in range(n_per_seed):
                cand = self.rollout(
                    perturb(best.params, self.space, self.types,
                            self.rng, radius),
                    "falsification")
                if cand is None or not cand.scoreable:
                    continue
                found.append(cand)
                if cand.rho_of(c) < best.rho_of(c):
                    best = cand          # descend on THIS contract
                    radius *= 0.7        # shrink on success
            found.append(best)
        return found

    # -- 2. delta debugging ----------------------------------------------
    def minimize(self, ro: Rollout, contract: str) -> tuple[dict, list, list]:
        """Delta-debug a violating configuration down to what it needs.

        The test is `rho_contract < 0`, NOT `rho_overall < 0`. The certificate
        is about ONE violated contract; testing the overall min would let a
        reverted parameter keep the configuration "violating" via a different
        contract and silently change what the certificate is about.
        """
        def violates(cfg) -> bool | None:
            r = self.rollout(cfg, "minimization")
            if r is None or not r.scoreable:
                return None
            v = r.rho_of(contract)
            return None if math.isnan(v) else bool(v < 0.0)

        return delta_debug(ro.params, self.nominal, violates)

    # -- 3. boundary search ----------------------------------------------
    def boundaries(self, minimal: dict, kept: list, contract: str) -> list:
        """Binary-search every parameter delta debugging could not drop."""
        def evaluate(cfg) -> float | None:
            r = self.rollout(cfg, "boundary")
            if r is None or not r.scoreable:
                return None
            v = r.rho_of(contract)
            return None if math.isnan(v) else float(v)

        out = []
        for name in kept:
            lo, hi = self.space[name]
            is_int = self.types.get(name) == "integer"
            tol = 1.0 if is_int else 0.01 * (float(hi) - float(lo))
            out.append(boundary_search(
                minimal, name, self.nominal[name], evaluate,
                tol=tol, is_integer=is_int))
        return out

    # -- 4. avoidability filter ------------------------------------------
    def avoidability(self, params: dict, contract: str) -> dict:
        """Was a violation-free response available in this same scenario?

        Implements RSS rule 5 the cheap way the build plan specifies: replay
        the identical scenario under a maximally conservative reference
        program and see whether it survives.

        TWO readings are recorded, because they differ and the choice matters:

          `avoidable`        the probe does not violate THE SAME CONTRACT.
                             This is the primary test and the one that
                             matches the question being asked -- "could this
                             violation have been avoided?" It does not reject
                             a counterexample because the probe happened to
                             trip an unrelated contract.
          `avoidable_strict` the probe violates NOTHING (rho >= 0 overall).

        Both are written to the certificate so the corpus can be re-analysed
        under either without re-running the campaign.
        """
        ro = self.rollout(params, "avoidability", program=self.probe_path)
        if ro is None or not ro.scoreable:
            return {"avoidable": False, "avoidable_strict": False,
                    "probe_scoreable": False,
                    "probe_status": (ro.status if ro else "refused"),
                    "probe_rho": None, "probe_per_contract": {},
                    "probe_rho_on_contract": None}
        v = ro.rho_of(contract)
        return {
            "avoidable": bool(not math.isnan(v) and v >= 0.0),
            "avoidable_strict": bool(ro.rho >= 0.0),
            "probe_scoreable": True,
            "probe_status": ro.status,
            "probe_rho": round(float(ro.rho), 6),
            "probe_rho_on_contract": (None if math.isnan(v) else round(float(v), 6)),
            "probe_per_contract": {k: round(x, 6) for k, x in ro.per_contract.items()},
            "probe_phases_reached": ro.phases_reached,
        }


# ==========================================================================
# 7.4 Verbalized -- the natural-language narrative
# ==========================================================================

# A certificate only ever describes a VIOLATION, so every phrase below is
# written for rho < 0 and |rho| is the depth of the violation, not a margin.
# C1 in particular must not read as a near-miss: rho_1 is bounding-box
# clearance, so a negative value is an OVERLAP -- these episodes come back
# with status `collision`, and calling that "came within 0.30 m of collision"
# would describe the opposite of what happened.
CONTRACT_PHRASE = {
    "C1": "struck another vehicle, with the bounding boxes overlapping by "
          "{v:.2f} m (the contract requires positive clearance)",
    "C2": "was inside the conflict zone with only {ttc:.2f} s of margin on the "
          "3.0 s yield requirement",
    "C3": "was still occupying the intersection {v:.2f} s after the light "
          "turned red",
    "C4": "closed to {v:.2f} m inside the RSS safe following distance behind the lead",
    "C5": "commanded {v:.2f} m/s2 more acceleration than the 3.0 m/s2 comfort bound",
}


def narrate(contract: str, rho: float, t_s: float | None,
            node_type: str | None, minimal: dict, boundary_report: str,
            achieved_gap_s: float | None = None) -> str:
    """One or two sentences of plain English alongside the structured fields.

    Required by spec §7.4, and not decoration: Reflexion's ablation showed
    that removing the natural-language reflection step returned performance to
    baseline. Structure alone is not sufficient.
    """
    mag = abs(float(rho))
    if contract == "C2":
        body = CONTRACT_PHRASE["C2"].format(ttc=3.0 - mag if rho < 0 else 3.0 + mag)
    else:
        body = CONTRACT_PHRASE.get(
            contract, "violated {c} by {v:.2f}").format(v=mag, c=contract)
    when = f" at t = {t_s:.2f} s" if t_s is not None else ""
    who = f" while {node_type} was the active behaviour" if node_type else ""
    gap = ""
    if achieved_gap_s is not None:
        gap = f" The gap the ego actually faced was {achieved_gap_s:.2f} s."
    return (f"The ego {body}{when}{who}. {boundary_report}.{gap}").replace("..", ".")
