"""Blame localization: resolving a violation to a behaviour-tree node.

TWO DEFINITIONS, both reported. This module exists because the first one is
provably vacuous on the frozen baseline and the second is not, and a paper that
reports only the second would be hiding a researcher degree of freedom.

--------------------------------------------------------------------------
DEFINITION 1 -- `active_node`. The PRE-REGISTERED definition (spec 7.5):
"the behaviour-tree leaf that was ticking at the argmin timestep of rho."

    Measured over the 20 admitted counterexamples: H(node | contract) = 0.000
    bits. Every certificate blames CommitTurn. This is not a sampling accident,
    it is a THEOREM about the frozen baseline:

        the root Selector's FIRST child is Sequence(InConflictZone, CommitTurn)

    A Selector stops at its first succeeding child, so inside the conflict zone
    that branch always fires and no other branch is ever reached. C1, C2 and C3
    are all evaluated over conflict-zone timesteps -- C2 by definition, C3 via
    `use_conflict_zone`, C1 in practice because minimum clearance occurs during
    the turn. Therefore the argmin is always inside the zone, and inside the
    zone exactly one leaf can tick. `active_node` is a constant.

    A constant carries no information, so F4 (= F3 + active_node) is
    information-identical to F3 for this baseline. Adding contracts does not
    help: the two that could bind elsewhere are C4 (never the argmin) and C5
    (rho_5 = +1.0 on every episode).

--------------------------------------------------------------------------
DEFINITION 2 -- `authorising_node`. The leaf that was active immediately
before the argmin leaf's current run began.

    Rationale, and it is independent of the null result above: for a REPAIR
    task the useful blame target is the decision that authorised the action,
    not the action executing when the consequence lands. "CommitTurn was
    running when you collided mid-turn" is nearly contentless -- of course it
    was turning. "You were still decelerating when you entered the junction,
    having never evaluated a gap" names something a patch can change.

    Anchored to the argmin, exactly as definition 1 is, so the two differ only
    in WHICH node the argmin resolves to and not in where they look. Walk back
    from the argmin row while the leaf is unchanged; the first differing leaf
    is the one that was active when the tree switched into the failing branch.

    This is still a LOOKUP, not an inference -- it reads two columns of the
    trace and compares them. The interpretability property is unchanged.

--------------------------------------------------------------------------
HONESTY REQUIREMENT. Definition 2 was written after observing that definition
1 gives zero. Report both, always, with definition 1 labelled as the
pre-registered one. The finding is not "F4 beats F3"; it is that blame
localization is informative only when blame attaches to the DECISION rather
than the CONSEQUENCE, and that the naive definition is vacuous by construction
on any program whose commit branch is guarded by a region test.
"""
from __future__ import annotations

import collections
import math

# The leaf at the argmin. Pre-registered; spec 7.5.
ACTIVE = "active_node"
# The leaf active immediately before the argmin leaf's run began.
AUTHORISING = "authorising_node"


def _leaf(df, i: int) -> str:
    return f"{df['bt_node_type'].iloc[i]}:{df['bt_node_path'].iloc[i]}"


def active_node(df, argmin_index: int) -> str:
    """Definition 1: the leaf ticking at the argmin timestep."""
    return _leaf(df, int(argmin_index))


def authorising_node(df, argmin_index: int) -> str | None:
    """Definition 2: the last distinct leaf active before the argmin leaf.

    Returns None when the argmin leaf was active from the first logged tick --
    there is no prior decision to name, and that must be reported as absent
    rather than silently filled with the argmin leaf itself.
    """
    i = int(argmin_index)
    here = df["bt_node_path"].iloc[i]
    k = i
    while k > 0 and df["bt_node_path"].iloc[k] == here:
        k -= 1
    if df["bt_node_path"].iloc[k] == here:
        return None
    return _leaf(df, k)


def conditional_entropy(pairs: list[tuple[str, str]]) -> tuple[float, dict]:
    """H(node | contract) in bits, with the per-contract breakdown.

    Zero means the contract determines the node, so the node carries no
    information beyond the contract and the F3/F4 distinction collapses.
    """
    by: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for contract, node in pairs:
        by[contract][node] += 1
    total = len(pairs)
    if not total:
        return 0.0, {}
    h = 0.0
    detail = {}
    for contract, nodes in by.items():
        n_c = sum(nodes.values())
        h_c = -sum((c / n_c) * math.log2(c / n_c) for c in nodes.values())
        h += (n_c / total) * h_c
        detail[contract] = {"n": n_c, "distinct_nodes": len(nodes),
                            "H_bits": round(h_c, 4),
                            "nodes": dict(nodes.most_common())}
    return h, detail


def entropy(labels: list[str]) -> float:
    """Plain H(X) in bits. Used to show the corpus IS varied in contract."""
    n = len(labels)
    if not n:
        return 0.0
    c = collections.Counter(labels)
    return -sum((v / n) * math.log2(v / n) for v in c.values())
