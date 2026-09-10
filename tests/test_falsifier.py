#!/usr/bin/env python3
"""Unit tests for delta debugging and boundary search on SYNTHETIC functions.

Both algorithms are tested here against closed-form oracles whose answers are
known by construction, BEFORE either is trusted on simulator output. That
ordering is the point: on real data a wrong minimal set or a wrong boundary
looks exactly like a right one -- there is nothing to compare against, and a
plausible-but-wrong certificate would propagate into every downstream repair
without ever throwing an error.

    .venv/bin/python tests/test_falsifier.py
"""
from __future__ import annotations

import pathlib
import random
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from falsifier import (  # noqa: E402
    Boundary, RolloutBudget, boundary_search, budget_delta, delta_debug,
    perturb, rank_seeds_per_contract, render_boundary_report,
)

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}{('  -- ' + detail) if detail else ''}")


# ==========================================================================
# Delta debugging
# ==========================================================================

def test_delta_debug() -> None:
    print("\ndelta_debug -- synthetic violation predicates with known answers")
    nominal = {"a": 0.0, "b": 0.0, "c": 0.0}
    start = {"a": 10.0, "b": 10.0, "c": 10.0}

    # 1. ONLY `a` matters. b and c must be dropped, a kept.
    n = {"i": 0}
    def only_a(cfg):
        n["i"] += 1
        return cfg["a"] > 5.0
    minimal, dropped, kept = delta_debug(start, nominal, only_a)
    check("only 'a' relevant -> kept == ['a']", kept == ["a"], f"kept={kept}")
    check("only 'a' relevant -> dropped == ['b','c']",
          sorted(dropped) == ["b", "c"], f"dropped={dropped}")
    check("only 'a' relevant -> minimal reverts b,c to nominal",
          minimal == {"a": 10.0, "b": 0.0, "c": 0.0}, f"minimal={minimal}")
    check("one evaluation per parameter", n["i"] == 3, f"n_evals={n['i']}")

    # 2. CONJUNCTION: a AND b are both needed, c is not.
    minimal, dropped, kept = delta_debug(
        start, nominal, lambda cfg: cfg["a"] > 5.0 and cfg["b"] > 5.0)
    check("conjunction a&b -> kept == ['a','b']", kept == ["a", "b"], f"kept={kept}")
    check("conjunction a&b -> dropped == ['c']", dropped == ["c"], f"dropped={dropped}")
    check("conjunction a&b -> minimal keeps both at 10",
          minimal == {"a": 10.0, "b": 10.0, "c": 0.0}, f"minimal={minimal}")

    # 3. NOTHING matters -- the violation is unconditional. Everything drops
    #    and the minimal configuration is exactly the nominal one.
    minimal, dropped, kept = delta_debug(start, nominal, lambda cfg: True)
    check("unconditional violation -> nothing kept", kept == [], f"kept={kept}")
    check("unconditional violation -> minimal == nominal",
          minimal == nominal, f"minimal={minimal}")

    # 4. EVERYTHING matters.
    minimal, dropped, kept = delta_debug(
        start, nominal,
        lambda cfg: cfg["a"] > 5.0 and cfg["b"] > 5.0 and cfg["c"] > 5.0)
    check("all three needed -> nothing dropped", dropped == [], f"dropped={dropped}")
    check("all three needed -> minimal == start", minimal == start)

    # 5. Drops are CUMULATIVE, not independent. Here a and b are
    #    interchangeable: the violation needs EITHER above 5. Testing them
    #    independently would drop both (each is individually removable) and
    #    produce a NON-violating "minimal" configuration. Cumulative reverting
    #    must keep the second one.
    minimal, dropped, kept = delta_debug(
        start, nominal, lambda cfg: cfg["a"] > 5.0 or cfg["b"] > 5.0)
    still_violates = minimal["a"] > 5.0 or minimal["b"] > 5.0
    check("interchangeable a|b -> minimal STILL VIOLATES (cumulative reverting)",
          still_violates, f"minimal={minimal}")
    check("interchangeable a|b -> exactly one of a,b retained",
          len(kept) == 1 and kept[0] in ("a", "b"), f"kept={kept}")

    # 6. An UNEVALUATABLE trial (None) must never cause a drop -- dropping on
    #    missing evidence silently shrinks the certificate.
    def none_for_b(cfg):
        if cfg["b"] == 0.0:
            return None
        return cfg["a"] > 5.0
    minimal, dropped, kept = delta_debug(start, nominal, none_for_b)
    check("None (unevaluatable) -> parameter is KEPT, not dropped",
          "b" in kept and "b" not in dropped, f"kept={kept} dropped={dropped}")

    # 7. A parameter already AT nominal is dropped without being simulated.
    n2 = {"i": 0}
    def counting(cfg):
        n2["i"] += 1
        return True
    at_nominal = {"a": 10.0, "b": 0.0, "c": 0.0}
    minimal, dropped, kept = delta_debug(at_nominal, nominal, counting)
    check("parameter already at nominal costs no evaluation", n2["i"] == 1,
          f"n_evals={n2['i']} (only 'a' differs from nominal)")
    check("parameter already at nominal is reported dropped",
          sorted(dropped) == ["a", "b", "c"], f"dropped={dropped}")


# ==========================================================================
# Boundary search
# ==========================================================================

def test_boundary_search() -> None:
    print("\nboundary_search -- step functions with known crossings")

    # 1. Crossing at 13.6, violating ABOVE. Mirrors the spec's own example:
    #    "fails for v_oncoming >= 13.6".
    ev = {"n": 0}
    def rho_desc(cfg):
        ev["n"] += 1
        return 13.6 - cfg["x"]          # < 0 exactly when x > 13.6
    b = boundary_search({"x": 16.0}, "x", 6.0, rho_desc, tol=0.1, max_evals=14)
    check("ascending axis -> direction '>='", b.direction == ">=", b.direction)
    check("ascending axis -> resolved", b.resolved, b.note)
    check("ascending axis -> threshold within tol of 13.6",
          abs(b.threshold - 13.6) <= 0.15, f"threshold={b.threshold}")
    check("ascending axis -> reported threshold ACTUALLY violates",
          rho_desc({"x": b.threshold}) < 0, f"rho({b.threshold})")
    check("ascending axis -> bracket straddles the true crossing",
          min(b.bracket) <= 13.6 <= max(b.bracket), f"bracket={b.bracket}")
    check("ascending axis -> renders as the spec phrasing",
          b.render().startswith("x >= 1"), b.render())

    # 2. Crossing at 3.4, violating BELOW: "fails for headway <= 3.4".
    def rho_asc(cfg):
        return cfg["y"] - 3.4           # < 0 exactly when y < 3.4
    b2 = boundary_search({"y": 1.5}, "y", 8.0, rho_asc, tol=0.065, max_evals=14)
    check("descending axis -> direction '<='", b2.direction == "<=", b2.direction)
    check("descending axis -> threshold within tol of 3.4",
          b2.resolved and abs(b2.threshold - 3.4) <= 0.1, f"threshold={b2.threshold}")
    check("descending axis -> reported threshold ACTUALLY violates",
          rho_asc({"y": b2.threshold}) < 0)

    # 3. NO crossing inside the range: still failing at the nominal end. This
    #    must be reported as such, never as a fabricated threshold.
    b3 = boundary_search({"x": 16.0}, "x", 6.0, lambda cfg: -1.0, tol=0.1)
    check("no crossing -> not resolved", not b3.resolved)
    check("no crossing -> threshold is None", b3.threshold is None)
    check("no crossing -> says so in the note",
          "whole range" in b3.note, b3.note)
    check("no crossing -> costs exactly ONE evaluation", b3.n_evals == 1)

    # 4. INTEGER axis. Crossing between 2 and 3, violating at >= 3.
    b4 = boundary_search({"n": 3}, "n", 1.0, lambda cfg: 2.5 - cfg["n"],
                         tol=1.0, is_integer=True)
    check("integer axis -> threshold is exactly 3", b4.resolved and b4.threshold == 3,
          f"threshold={b4.threshold}")
    check("integer axis -> bracket is (3, 2)", tuple(b4.bracket) == (3.0, 2.0),
          f"bracket={b4.bracket}")

    # 5. An UNEVALUATABLE midpoint (held-out region) must stop the search with
    #    the bracket it has, flagged -- never guess across the hole.
    def blocked(cfg):
        if 10.0 < cfg["x"] < 14.0:
            return None                 # the held-out hole
        return 13.6 - cfg["x"]
    b5 = boundary_search({"x": 16.0}, "x", 6.0, blocked, tol=0.1, max_evals=14)
    check("unevaluatable midpoint -> search stops, flagged",
          "could not be evaluated" in b5.note, b5.note)

    # 6. Nominal == violating value: nothing to bisect, no evaluations spent.
    b6 = boundary_search({"x": 6.0}, "x", 6.0, lambda cfg: -1.0, tol=0.1)
    check("degenerate axis -> no evaluations", b6.n_evals == 0 and not b6.resolved)

    # 7. The conjoined report reads the way the spec asks for.
    rep = render_boundary_report([b, b2], "C2")
    check("boundary report conjoins axes in the spec's phrasing",
          rep.startswith("C2 fails for x >= ") and " when y <= " in rep, rep)


# ==========================================================================
# Per-contract ranking -- the headway masking result
# ==========================================================================

class FakeRollout:
    """Minimal stand-in carrying only what ranking reads."""

    def __init__(self, name, per_contract, vacuous=None):
        self.name = name
        self.per_contract = per_contract
        self.vacuous = vacuous or {}
        self.scoreable = True

    def rho_of(self, c):
        return self.per_contract.get(c, float("nan"))


def test_ranking() -> None:
    print("\nrank_seeds_per_contract -- the min() masking result, reproduced")

    # The measured situation from docs/sensitivity_analysis.md: `headway`
    # pushes C1 and C2 in OPPOSITE directions, so min() cancels it. Two points
    # sit at opposite ends of the headway axis; both are interesting, but they
    # are interesting to DIFFERENT contracts and their overall rho is
    # identical, so an overall-rho ranking cannot tell them apart.
    big_headway = FakeRollout("big_headway", {"C1": 2.0, "C2": 0.10})
    small_headway = FakeRollout("small_headway", {"C1": 0.10, "C2": 2.0})
    middling = FakeRollout("middling", {"C1": 1.0, "C2": 1.0})
    pool = [big_headway, small_headway, middling]

    overall = sorted(pool, key=lambda r: min(r.per_contract.values()))
    check("overall-rho ranking CANNOT separate the two headway extremes",
          overall[0].rho_of("C1") != overall[1].rho_of("C1")
          and min(overall[0].per_contract.values())
              == min(overall[1].per_contract.values()),
          "both score min = 0.10, so a single top-1 seed would drop one axis")

    seeds = rank_seeds_per_contract(pool, ["C1", "C2"], r=1)
    picked = {(ro.name, c) for ro, c in seeds}
    check("per-contract ranking seeds BOTH headway extremes",
          picked == {("small_headway", "C1"), ("big_headway", "C2")},
          f"picked={sorted(picked)}")

    # A vacuous contract's sentinel is not a margin and must never seed.
    vac = FakeRollout("vacuous", {"C1": 999.0, "C2": -5.0}, {"C1": True})
    seeds2 = rank_seeds_per_contract(pool + [vac], ["C1", "C2"], r=1)
    check("vacuous contract is excluded from its own ranking",
          all(not (ro.name == "vacuous" and c == "C1") for ro, c in seeds2),
          f"seeds={[(r.name, c) for r, c in seeds2]}")
    check("a vacuous-on-C1 rollout can still seed C2, where it is real",
          ("vacuous", "C2") in {(r.name, c) for r, c in seeds2})


# ==========================================================================
# Sample-time plausibility, held-out avoidance, accounting
# ==========================================================================

def test_perturb_clamps() -> None:
    print("\nperturb -- plausibility enforced AT SAMPLE TIME, never after")
    space = {"v_oncoming": (6.0, 16.0), "n_oncoming": (1, 3)}
    types = {"v_oncoming": "float", "n_oncoming": "integer"}
    rng = random.Random(7)
    at_bound = {"v_oncoming": 16.0, "n_oncoming": 3}
    ok_range, ok_int = True, True
    for _ in range(2000):
        p = perturb(at_bound, space, types, rng, radius_frac=0.9)
        if not (6.0 <= p["v_oncoming"] <= 16.0 and 1 <= p["n_oncoming"] <= 3):
            ok_range = False
        if not isinstance(p["n_oncoming"], int):
            ok_int = False
    check("2000 perturbations from the bound all stay inside it", ok_range)
    check("integer parameters stay integers", ok_int)


def test_budget() -> None:
    print("\nRolloutBudget -- cost attributed to the stage that incurs it")
    b = RolloutBudget()
    before = b.snapshot()
    for _ in range(7):
        b.charge("falsification", cached=False)
    for _ in range(3):
        b.charge("minimization", cached=False)
    for _ in range(5):
        b.charge("minimization", cached=True)
    b.charge("boundary", cached=False)
    b.charge("avoidability", cached=False)
    d = b.as_dict()
    check("purposes are counted separately",
          (d["rollouts_falsification"], d["rollouts_minimization"],
           d["rollouts_boundary"], d["rollouts_avoidability"]) == (7, 3, 1, 1),
          str(d))
    check("cache hits are NOT counted as rollouts", d["rollouts_total"] == 12)
    check("cache hit rate = 5/17", abs(d["cache_hit_rate"] - 5 / 17) < 1e-4,
          str(d["cache_hit_rate"]))
    after = b.snapshot()
    check("budget_delta charges only this counterexample's share",
          budget_delta(before, after) == {"rollouts_falsification": 7,
                                          "rollouts_minimization": 3,
                                          "rollouts_boundary": 1,
                                          "rollouts_avoidability": 1})
    try:
        b.charge("nonsense", cached=False)
        check("an unknown purpose is rejected", False)
    except KeyError:
        check("an unknown purpose is rejected", True)


def main() -> int:
    print("=" * 74)
    print("falsifier unit tests -- synthetic oracles, no simulator")
    print("=" * 74)
    test_delta_debug()
    test_boundary_search()
    test_ranking()
    test_perturb_clamps()
    test_budget()
    print("\n" + "=" * 74)
    print(f"{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        for f in FAIL:
            print(f"  FAILED: {f}")
    print("=" * 74)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
