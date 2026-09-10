#!/usr/bin/env python3
"""Zhang-Shasha on trees whose distances are worked out BY HAND.

The brief is explicit about why: a wrong TED silently corrupts the headline
interpretability result ("repairs are patches, not rewrites"), and it corrupts
it without erroring. So the algorithm is checked against cases where the answer
is derivable on paper before it is pointed at a single real program.

The classic literature example (Zhang & Shasha 1989 / the `zss` test suite) is
included as an independent check that this implementation agrees with a
published one, rather than only with my own reasoning.

Run:  .venv/bin/python tests/test_ted.py
"""
from __future__ import annotations

import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from program_parser import parse  # noqa: E402
from ted import (  # noqa: E402
    classify_patch, node_label, skeleton, ted_from_source, tree_edit_distance)

PASS, FAIL = [], []


def check(name, got, want) -> None:
    ok = got == want
    (PASS if ok else FAIL).append(name)
    print(f"  {'ok  ' if ok else 'FAIL'} {name}"
          + ("" if ok else f"   got {got}, want {want}"))


class N:
    """A bare labelled tree, so the algorithm can be tested without the DSL."""

    def __init__(self, label, *children):
        self.label = label
        self.children = list(children)
        self.params = {}
        self.name = label


def lab(n):
    return n.label


def d(a, b):
    return tree_edit_distance(a, b, label_fn=lab)


# ==========================================================================
def test_identity():
    print("\n[identity and symmetry]")
    t = N("f", N("d", N("a"), N("c", N("b"))), N("e"))
    check("distance from a tree to itself is 0", d(t, t), 0)
    u = N("f", N("c", N("d", N("a"), N("b"))), N("e"))
    check("symmetric: d(t,u) == d(u,t)", d(t, u) == d(u, t), True)


def test_single_nodes():
    print("\n[single nodes]")
    check("same single node", d(N("a"), N("a")), 0)
    check("relabel one node", d(N("a"), N("b")), 1)
    check("one node vs two: one insert", d(N("a"), N("a", N("b"))), 1)
    check("two nodes vs one: one delete", d(N("a", N("b")), N("a")), 1)


def test_hand_worked():
    print("\n[hand-worked cases]")
    # a(b,c) -> a(b,d): relabel c->d. One edit.
    check("relabel one leaf of three nodes",
          d(N("a", N("b"), N("c")), N("a", N("b"), N("d"))), 1)
    # a(b,c) -> a(b): delete c. One edit.
    check("delete one leaf", d(N("a", N("b"), N("c")), N("a", N("b"))), 1)
    # a(b,c) -> a(b,c,e): insert e. One edit.
    check("insert one leaf",
          d(N("a", N("b"), N("c")), N("a", N("b"), N("c"), N("e"))), 1)
    # a(b,c) -> a(c,b): ORDERED distance is 2 (relabel both), not 0.
    # This is the property that makes ordered TED the right choice here: a
    # Selector returns at its FIRST succeeding child, so swapping two branches
    # changes behaviour and must cost something.
    check("swapping two leaves costs 2 under an ORDERED distance",
          d(N("a", N("b"), N("c")), N("a", N("c"), N("b"))), 2)
    # Deleting an interior node: a(b(c)) -> a(c). One delete.
    check("delete an interior node", d(N("a", N("b", N("c"))), N("a", N("c"))), 1)
    # Disjoint 3-node trees: relabel all three.
    check("three relabels",
          d(N("a", N("b"), N("c")), N("x", N("y"), N("z"))), 3)
    # Empty-ish: a vs a(b,c) needs two inserts.
    check("two inserts", d(N("a"), N("a", N("b"), N("c"))), 2)


def test_literature_example():
    """Zhang & Shasha's worked example, as used by the `zss` test suite."""
    print("\n[published example]")
    # A = f(d(a, c(b)), e)   B = f(c(d(a, b)), e)
    A = N("f", N("d", N("a"), N("c", N("b"))), N("e"))
    B = N("f", N("c", N("d", N("a"), N("b"))), N("e"))
    check("Zhang-Shasha f(d(a,c(b)),e) -> f(c(d(a,b)),e) is 2", d(A, B), 2)


def test_deep_chain():
    print("\n[deep structures]")
    chain = lambda k: (N("n0") if k == 0 else N(f"n{k}", chain(k - 1)))  # noqa: E731
    check("chain of 6 vs itself", d(chain(5), chain(5)), 0)
    check("chain of 6 vs chain of 4: two deletes", d(chain(5), chain(3)), 2)


def test_on_real_dsl():
    print("\n[on the actual DSL]")
    base = (REPO / "data/scenarios/baseline_program.bt").read_text()
    check("baseline vs itself is 0", ted_from_source(base, base), 0)

    # A threshold change: one relabel.
    one = base.replace("OncomingGapExceeds(gap_s=5.5)",
                       "OncomingGapExceeds(gap_s=6.5)", 1)
    check("one threshold changed is TED 1", ted_from_source(base, one), 1)
    check("... and classifies as hole_fill", classify_patch(base, one), "hole_fill")

    # Cosmetic reprinting must be free: `2.0` and `2` are the same threshold.
    cosmetic = base.replace("HoldAtStopLine(decel_mps2=2.0)",
                            "HoldAtStopLine(decel_mps2=2)")
    check("cosmetic float reformatting is TED 0",
          ted_from_source(base, cosmetic), 0)
    check("... and classifies as no_change", classify_patch(base, cosmetic),
          "no_change")

    # Comments and blank lines are not nodes.
    commented = "# an added comment\n\n" + base
    check("adding a comment is TED 0", ted_from_source(base, commented), 0)

    # Inserting a guard node: one insert, and a skeleton change.
    ins = base.replace(
        "      Sequence\n        TrafficLightIsGreen\n        OncomingGapExceeds(gap_s=5.5)",
        "      Sequence\n        TrafficLightIsGreen\n        PathIsClear(dist_m=25.0)\n"
        "        OncomingGapExceeds(gap_s=5.5)", 1)
    check("inserting one node is TED 1", ted_from_source(base, ins), 1)
    check("... and classifies as skeleton_edit", classify_patch(base, ins),
          "skeleton_edit")

    check("unparseable source gives None", ted_from_source(base, "Sequence\n\tTab"),
          None)
    check("... and classifies as unparseable",
          classify_patch(base, "Sequence\n\tTab"), "unparseable")


def test_labels_and_skeleton():
    print("\n[labels and skeleton]")
    a = parse("Sequence\n  Cruise(v_mps=7.0, accel_mps2=1.5)\n")
    b = parse("Sequence\n  Cruise(accel_mps2=1.5, v_mps=7)\n")
    check("parameter ORDER does not change the label",
          node_label(a.children[0]) == node_label(b.children[0]), True)
    check("skeleton ignores parameters", skeleton(a) == skeleton(b), True)
    c = parse("Sequence\n  Cruise(v_mps=9.0, accel_mps2=1.5)\n")
    check("a different threshold DOES change the label",
          node_label(a.children[0]) != node_label(c.children[0]), True)
    check("... but not the skeleton", skeleton(a) == skeleton(c), True)


def main() -> int:
    test_identity()
    test_single_nodes()
    test_hand_worked()
    test_literature_example()
    test_deep_chain()
    test_on_real_dsl()
    test_labels_and_skeleton()
    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} pass")
    if FAIL:
        print("FAILED:")
        for f in FAIL:
            print("  -", f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
