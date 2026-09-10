"""Tree edit distance between two behaviour-tree programs (Zhang-Shasha).

TED is the interpretability result's quantitative half: "repairs are patches,
not rewrites" (project rule 4) is a claim about edit distance, and a
wrong TED silently corrupts it. So this is implemented from the algorithm
rather than eyeballed, and `tests/test_ted.py` checks it against hand-built
trees with distances worked out by hand BEFORE it is run on real data.

`zss` is not installed and `networkx` has no tree-edit-distance routine, so the
algorithm is written out here.

ZHANG-SHASHA, in one paragraph. Both trees are ORDERED and labelled, which a
behaviour tree is -- child order is semantically load-bearing (a Selector
returns at its first succeeding child), so an unordered edit distance would
score a reordering as free and reordering is exactly the edit type we most want
to detect. The algorithm numbers nodes in postorder, computes for each node the
postorder index of its leftmost leaf descendant, and takes as `keyroots` those
nodes that are not the leftmost child of their parent. Distances between all
pairs of keyroot subtrees are then filled in with a forest-distance dynamic
program; each cell is the cheapest of deleting from the left forest, inserting
into the right forest, or matching the two rightmost roots.

LABELS. A node's label is its name TOGETHER with its parameters, so changing a
threshold is a RELABEL of cost 1 rather than free. Parameters are rounded to 6
decimals and sorted so that formatting differences ("2" vs "2.0") are not
scored as edits -- the model reprints the whole program every time and cosmetic
reprinting must not register as repair work.

PATCH TYPE is decided from the SKELETON -- the tree of node names with all
parameters stripped. Identical skeleton and different labels means only
thresholds moved (`hole_fill`); a different skeleton means a node was inserted,
removed or reordered (`skeleton_edit`). This is a structural test, not a
threshold on TED, so it cannot be fooled by a large number of small edits.
"""
from __future__ import annotations

import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))


# --------------------------------------------------------------------------
# Labels
# --------------------------------------------------------------------------
def node_label(n) -> str:
    """`Name(p=v, ...)` with parameters sorted and rounded. Used as the label."""
    ps = ",".join(f"{k}={round(float(v), 6)}" for k, v in sorted(n.params.items()))
    return f"{n.name}({ps})"


def skeleton(n) -> tuple:
    """The tree of node NAMES only. Parameters stripped, child order kept."""
    return (n.name, tuple(skeleton(c) for c in n.children))


# --------------------------------------------------------------------------
# Zhang-Shasha
# --------------------------------------------------------------------------
def _postorder(root, label_fn):
    """(labels, leftmost) in postorder, both 1-indexed at position 0 unused."""
    labels: list = [None]
    leftmost: list = [0]

    def visit(n) -> int:
        """Append n's subtree in postorder; return n's own postorder index."""
        child_idx = [visit(c) for c in n.children]
        labels.append(label_fn(n))
        idx = len(labels) - 1
        # The leftmost leaf descendant of n is that of its FIRST child, or n
        # itself when n is a leaf.
        leftmost.append(leftmost[child_idx[0]] if child_idx else idx)
        return idx

    visit(root)
    return labels, leftmost


def _keyroots(leftmost: list) -> list:
    """Nodes that are not the leftmost child of their parent, plus the root.

    Computed the standard way: keep, for each distinct leftmost-leaf value, the
    LARGEST postorder index having it.
    """
    seen: dict = {}
    for i in range(1, len(leftmost)):
        seen[leftmost[i]] = i
    return sorted(seen.values())


def tree_edit_distance(a, b, label_fn=node_label) -> int:
    """Unit-cost Zhang-Shasha distance between two BTNode trees."""
    la, lma = _postorder(a, label_fn)
    lb, lmb = _postorder(b, label_fn)
    na, nb = len(la) - 1, len(lb) - 1

    INF = float("inf")
    td = [[0] * (nb + 1) for _ in range(na + 1)]

    for i in _keyroots(lma):
        for j in _keyroots(lmb):
            # Forest distance over the subforests rooted at i and j.
            oi, oj = lma[i], lmb[j]
            m, n = i - oi + 2, j - oj + 2
            fd = [[INF] * n for _ in range(m)]
            fd[0][0] = 0
            for x in range(1, m):
                fd[x][0] = fd[x - 1][0] + 1                 # delete
            for y in range(1, n):
                fd[0][y] = fd[0][y - 1] + 1                 # insert
            for x in range(1, m):
                for y in range(1, n):
                    ii, jj = oi + x - 1, oj + y - 1
                    if lma[ii] == oi and lmb[jj] == oj:
                        # Both are subTREES: the match arm is a relabel, and
                        # this cell is also the answer for (ii, jj).
                        cost = 0 if la[ii] == lb[jj] else 1
                        fd[x][y] = min(fd[x - 1][y] + 1,
                                       fd[x][y - 1] + 1,
                                       fd[x - 1][y - 1] + cost)
                        td[ii][jj] = fd[x][y]
                    else:
                        # General forests: the match arm splits off the already
                        # computed subtree distance.
                        p, q = lma[ii] - oi, lmb[jj] - oj
                        fd[x][y] = min(fd[x - 1][y] + 1,
                                       fd[x][y - 1] + 1,
                                       fd[p][q] + td[ii][jj])
    return int(td[na][nb])


# --------------------------------------------------------------------------
# Source-level entry points
# --------------------------------------------------------------------------
def ted_from_source(src_a: str, src_b: str) -> int | None:
    """TED between two `.bt` sources. None if either fails to parse."""
    from program_parser import parse
    try:
        return tree_edit_distance(parse(src_a), parse(src_b))
    except Exception:
        return None


def classify_patch(src_before: str, src_after: str) -> str:
    """`no_change` | `hole_fill` | `skeleton_edit` | `unparseable`.

    THREE outcomes where the plan names two, deliberately. A response that
    reprints the program unchanged is not a threshold change and must not be
    counted as one -- it is a distinct model behaviour, and pooling it into
    `hole_fill` would inflate the type that is supposed to carry the LOW
    regression risk with cases that carry none at all.
    """
    from program_parser import parse
    try:
        a, b = parse(src_before), parse(src_after)
    except Exception:
        return "unparseable"
    if skeleton(a) != skeleton(b):
        return "skeleton_edit"
    if a.to_tuple() == b.to_tuple():
        return "no_change"
    return "hole_fill"
