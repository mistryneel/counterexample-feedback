"""`.bt` DSL — AST, parser, validator, and py_trees compilation.

Spec 01_TECHNICAL_SPEC_v2.md §4. Owning the AST is required for three things
that the paper depends on:

  * TREE EDIT DISTANCE between program versions (the interpretability metric)
  * NODE-LEVEL BLAME -- resolving the argmin timestep of rho to the leaf that
    was ticking
  * PRE-EXECUTION VALIDATION, so a malformed program is a distinct, separately
    counted outcome from an unsafe one (project rule 3)

Execution is delegated to py_trees: this module emits py_trees composites, so
the tick engine is a mature external component while the serialized format
stays under project control.

GRAMMAR -- deliberately the simplest thing an LLM can reliably emit:

    Selector()
      Sequence()
        TrafficLightIsGreen()
        OncomingGapExceeds(gap_s=3.0)
        CommitTurn(v_mps=5.0, accel_mps2=1.5)
      HoldAtStopLine(decel_mps2=2.0)

  * one node per line
  * two spaces of indentation per level, nothing else
  * `NodeName(param=value, param=value)`; `()` optional when there are none
  * `#` begins a comment; blank lines are ignored

Parentheses rather than bare `name value` pairs because the call form matches
the ProgPrompt import block the agent is shown, and matching forms cost fewer
malformed samples. Indentation rather than nested brackets because a missed
closing bracket is the commonest LLM structural error, and it fails the whole
program rather than one line.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import bt_vocabulary as V

INDENT = 2
_LINE_RE = re.compile(r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*(?:\((?P<args>.*)\))?\s*$")
_ARG_RE = re.compile(r"^\s*(?P<k>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<v>[-+0-9.eE]+)\s*$")


class ParseError(Exception):
    """Grammar-level failure. The program is MALFORMED, never 'unsafe'."""

    def __init__(self, message: str, line: int | None = None):
        self.line = line
        super().__init__(f"line {line}: {message}" if line else message)


@dataclass
class BTNode:
    """One node of the program AST. This structure is ours, not py_trees'."""

    name: str
    params: dict = field(default_factory=dict)
    children: list["BTNode"] = field(default_factory=list)
    line: int = 0
    node_id: str = ""       # assigned pre-order: n_0, n_1, ...
    path: str = ""          # root/Selector/Sequence/OncomingGapExceeds

    @property
    def spec(self) -> V.NodeSpec | None:
        return V.ALL_NODES.get(self.name)

    @property
    def kind(self) -> str:
        s = self.spec
        return s.kind if s else "unknown"

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()

    def depth(self) -> int:
        return 1 + max((c.depth() for c in self.children), default=0)

    def size(self) -> int:
        return 1 + sum(c.size() for c in self.children)

    def to_source(self, level: int = 0) -> str:
        pad = " " * (INDENT * level)
        args = ", ".join(f"{k}={_fmt(v)}" for k, v in self.params.items())
        out = [f"{pad}{self.name}({args})"]
        for c in self.children:
            out.append(c.to_source(level + 1))
        return "\n".join(out)

    def to_tuple(self):
        """Canonical hashable form. Used as the label space for tree edit distance."""
        return (self.name,
                tuple(sorted((k, round(float(v), 6)) for k, v in self.params.items())),
                tuple(c.to_tuple() for c in self.children))


def _fmt(v) -> str:
    if isinstance(v, float) and v == int(v):
        return str(int(v)) if abs(v) >= 1 or v == 0 else repr(v)
    return repr(v) if not isinstance(v, (int, float)) else str(v)


# ==========================================================================
# Parsing
# ==========================================================================

def parse(source: str) -> BTNode:
    """Parse `.bt` source into an AST. Raises ParseError on any grammar fault."""
    rows: list[tuple[int, int, str]] = []      # (line_no, level, text)
    for i, raw in enumerate(source.splitlines(), start=1):
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        stripped = line.lstrip(" ")
        n_spaces = len(line) - len(stripped)
        if "\t" in line:
            raise ParseError("tabs are not permitted; use two spaces per level", i)
        if n_spaces % INDENT != 0:
            raise ParseError(
                f"indentation of {n_spaces} spaces is not a multiple of {INDENT}", i)
        rows.append((i, n_spaces // INDENT, stripped))

    if not rows:
        raise ParseError("program is empty")
    if rows[0][1] != 0:
        raise ParseError("the first node must not be indented", rows[0][0])

    root: BTNode | None = None
    stack: list[tuple[int, BTNode]] = []
    prev_level = -1

    for line_no, level, text in rows:
        node = _parse_line(text, line_no)
        if level > prev_level + 1:
            raise ParseError(
                f"indentation jumps from level {prev_level} to {level}; "
                "a child may only be one level deeper than its parent", line_no)
        if level == 0:
            if root is not None:
                raise ParseError(
                    "more than one root node; the program must be a single tree",
                    line_no)
            root = node
            stack = [(0, node)]
        else:
            while stack and stack[-1][0] >= level:
                stack.pop()
            if not stack:
                raise ParseError("node has no parent", line_no)
            stack[-1][1].children.append(node)
            stack.append((level, node))
        prev_level = level

    assert root is not None
    _assign_ids(root)
    return root


def _parse_line(text: str, line_no: int) -> BTNode:
    m = _LINE_RE.match(text)
    if not m:
        raise ParseError(
            f"cannot parse {text!r}; expected NodeName(param=value, ...)", line_no)
    name = m.group("name")
    args_raw = (m.group("args") or "").strip()
    params: dict = {}
    if args_raw:
        for part in args_raw.split(","):
            if not part.strip():
                continue
            am = _ARG_RE.match(part)
            if not am:
                raise ParseError(
                    f"cannot parse argument {part.strip()!r}; expected name=number",
                    line_no)
            key = am.group("k")
            if key in params:
                raise ParseError(f"duplicate parameter {key!r}", line_no)
            try:
                params[key] = float(am.group("v"))
            except ValueError:
                raise ParseError(
                    f"{am.group('v')!r} is not a number", line_no) from None
    return BTNode(name=name, params=params, line=line_no)


def _assign_ids(root: BTNode) -> None:
    """Pre-order ids and human-readable paths.

    node_id is positional and therefore changes when the tree is edited; `path`
    is the stable-ish handle quoted in certificates. Both are recorded so a
    reader can cross-check them.
    """
    counter = [0]

    def rec(n: BTNode, prefix: str) -> None:
        n.node_id = f"n_{counter[0]}"
        counter[0] += 1
        n.path = f"{prefix}/{n.name}" if prefix else n.name
        for c in n.children:
            rec(c, n.path)

    rec(root, "")


# ==========================================================================
# Validation
# ==========================================================================

@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.ok


def validate(root: BTNode, grammar_only: bool = False) -> ValidationResult:
    """Spec §4.4 checks.

    grammar_only=True runs only the checks that a parse already implies, and
    is the documented fallback if the validator is not finished in time -- see
    docs/dsl_reference.md.
    """
    errors: list[str] = []
    warnings: list[str] = []

    if grammar_only:
        return ValidationResult(ok=True, errors=[], warnings=[
            "validator running in GRAMMAR-ONLY mode: node names, arity, "
            "parameter types/ranges, reachability and depth are NOT checked"])

    for n in root.walk():
        spec = n.spec

        # --- known node -------------------------------------------------
        if spec is None:
            errors.append(
                f"line {n.line}: unknown node {n.name!r}. "
                f"Permitted: {', '.join(sorted(V.ALL_NODES))}")
            continue

        # --- arity ------------------------------------------------------
        if spec.kind == "composite":
            if len(n.children) < spec.min_children:
                errors.append(
                    f"line {n.line}: {n.name} needs at least "
                    f"{spec.min_children} child(ren), has {len(n.children)}")
            if len(n.children) > spec.max_children:
                errors.append(
                    f"line {n.line}: {n.name} takes at most "
                    f"{spec.max_children} children, has {len(n.children)}")
        elif n.children:
            errors.append(
                f"line {n.line}: {n.name} is a {spec.kind} and cannot have "
                f"children, has {len(n.children)}")

        # --- parameter names, types, ranges -----------------------------
        expected = {p.name: p for p in spec.params}
        for key in n.params:
            if key not in expected:
                errors.append(
                    f"line {n.line}: {n.name} has no parameter {key!r}. "
                    f"Expected: {sorted(expected) or 'none'}")
        for key, pspec in expected.items():
            if key not in n.params:
                errors.append(f"line {n.line}: {n.name} is missing "
                              f"required parameter {key!r}")
                continue
            err = pspec.check(n.params[key])
            if err:
                errors.append(f"line {n.line}: {n.name}: {err}")

    # --- depth ----------------------------------------------------------
    d = root.depth()
    if d > V.MAX_DEPTH:
        errors.append(f"tree depth {d} exceeds the maximum of {V.MAX_DEPTH}")

    # --- unreachable subtrees -------------------------------------------
    # Every action returns RUNNING, and RUNNING halts sibling evaluation in
    # both Sequence and Selector. So any sibling AFTER an action can never be
    # reached while that action is running -- it is dead code, and a program
    # full of dead code would score a misleadingly large tree edit distance.
    for n in root.walk():
        if n.kind != "composite":
            continue
        for i, c in enumerate(n.children[:-1]):
            if _always_running(c):
                errors.append(
                    f"line {n.children[i + 1].line}: unreachable. "
                    f"{c.name} (line {c.line}) always returns RUNNING, so the "
                    f"{len(n.children) - i - 1} sibling(s) after it in "
                    f"{n.name} can never be reached")
                break

    # --- soft advice ----------------------------------------------------
    if not any(x.name == "CommitTurn" for x in root.walk()):
        warnings.append("no CommitTurn node: this program can never complete the turn")

    return ValidationResult(ok=not errors, errors=errors, warnings=warnings)


def _always_running(n: BTNode) -> bool:
    """True if evaluating this subtree necessarily reaches an action."""
    if n.kind == "action":
        return True
    if n.kind != "composite":
        return False
    if n.name == "Sequence":
        # a Sequence reaches its action only if every preceding child succeeds,
        # which is not statically known -- so it is NOT necessarily running
        return False
    if n.name == "Selector":
        # a Selector is necessarily running only if its LAST child is
        return bool(n.children) and _always_running(n.children[-1])
    return False


def parse_and_validate(source: str, grammar_only: bool = False):
    """Returns (root, ValidationResult). Never raises on a malformed program."""
    try:
        root = parse(source)
    except ParseError as e:
        return None, ValidationResult(ok=False, errors=[f"PARSE: {e}"])
    return root, validate(root, grammar_only=grammar_only)


# ==========================================================================
# Runtime context — the typed world view the tree reads
# ==========================================================================
# The blackboard is an explicit dataclass rather than py_trees' string-keyed
# blackboard: every field is typed and named to carry its unit (project
# conventions), so a node cannot silently read metres where it wanted seconds.
# ==========================================================================

from dataclasses import dataclass as _dc     # noqa: E402


@_dc
class WorldView:
    """Ground-truth state presented to the tree at one tick."""

    t_s: float = 0.0
    ego_v_mps: float = 0.0
    dist_to_stopline_m: float = 0.0     # negative once past the stop line
    oncoming_gap_s: float = 30.0        # time-to-conflict-zone, nearest oncoming
    in_conflict_zone: bool = False
    light_is_green: bool = False
    path_clear_dist_m: float = 100.0    # free distance along the turn path
    stationary_time_s: float = 0.0
    route_complete: bool = False


@_dc
class ControlCommand:
    """What an action leaf asks the vehicle to do."""

    target_v_mps: float = 0.0
    accel_limit_mps2: float = 2.0
    source_node_id: str = ""
    source_node_type: str = ""
    source_node_path: str = ""


class ExecContext:
    """Shared between the harness and every compiled behaviour."""

    def __init__(self) -> None:
        self.world = WorldView()
        self.command = ControlCommand()
        self.evaluated: list[BTNode] = []    # leaves ticked, in order, this tick
        self.acting: BTNode | None = None    # the action leaf that issued command

    def begin_tick(self) -> None:
        self.evaluated = []
        self.acting = None


# ==========================================================================
# py_trees behaviours
# ==========================================================================

import py_trees                                 # noqa: E402
from py_trees.common import Status              # noqa: E402


class _Leaf(py_trees.behaviour.Behaviour):
    """Base for every compiled leaf. Records itself for blame localization."""

    def __init__(self, node: BTNode, ctx: ExecContext):
        super().__init__(name=f"{node.name}#{node.node_id}")
        self.node = node
        self.ctx = ctx

    def update(self) -> Status:
        # BLAME LOCALIZATION happens HERE, not by inference afterwards. Every
        # leaf that is ticked appends itself, so at any timestep we know
        # exactly which leaves were evaluated and in what order. This is only
        # possible because the policy is a readable program.
        self.ctx.evaluated.append(self.node)
        return self.tick_logic()

    def tick_logic(self) -> Status:
        raise NotImplementedError


class _Condition(_Leaf):
    def tick_logic(self) -> Status:
        return Status.SUCCESS if self.test(self.ctx.world) else Status.FAILURE

    def test(self, w: WorldView) -> bool:
        raise NotImplementedError


class _Action(_Leaf):
    def tick_logic(self) -> Status:
        cmd = self.act(self.ctx.world)
        cmd.source_node_id = self.node.node_id
        cmd.source_node_type = self.node.name
        cmd.source_node_path = self.node.path
        self.ctx.command = cmd
        self.ctx.acting = self.node
        return self.status_after(self.ctx.world)

    def act(self, w: WorldView) -> ControlCommand:
        raise NotImplementedError

    def status_after(self, w: WorldView) -> Status:
        return Status.RUNNING


# --- conditions -----------------------------------------------------------

class OncomingGapExceeds(_Condition):
    def test(self, w):
        return w.oncoming_gap_s >= self.node.params["gap_s"]


class EgoSpeedBelow(_Condition):
    def test(self, w):
        return w.ego_v_mps < self.node.params["v_mps"]


class DistanceToStopLineBelow(_Condition):
    def test(self, w):
        return w.dist_to_stopline_m < self.node.params["dist_m"]


class InConflictZone(_Condition):
    def test(self, w):
        return w.in_conflict_zone


class TrafficLightIsGreen(_Condition):
    def test(self, w):
        return w.light_is_green


class PathIsClear(_Condition):
    def test(self, w):
        return w.path_clear_dist_m >= self.node.params["dist_m"]


class WaitedLongerThan(_Condition):
    def test(self, w):
        return w.stationary_time_s >= self.node.params["t_s"]


# --- actions --------------------------------------------------------------

class Cruise(_Action):
    def act(self, w):
        return ControlCommand(self.node.params["v_mps"],
                              self.node.params["accel_mps2"])


class Decelerate(_Action):
    def act(self, w):
        return ControlCommand(self.node.params["v_mps"],
                              self.node.params["decel_mps2"])


class HoldAtStopLine(_Action):
    def act(self, w):
        # Target zero once at or past the stop line; otherwise ease down so the
        # stop lands ON the line rather than short of it.
        d = max(w.dist_to_stopline_m, 0.0)
        decel = self.node.params["decel_mps2"]
        v_target = 0.0 if d <= 0.5 else min(w.ego_v_mps, (2.0 * decel * d) ** 0.5)
        return ControlCommand(v_target, decel)


class CommitTurn(_Action):
    def act(self, w):
        return ControlCommand(self.node.params["v_mps"],
                              self.node.params["accel_mps2"])

    def status_after(self, w):
        return Status.SUCCESS if w.route_complete else Status.RUNNING


class Creep(_Action):
    def act(self, w):
        return ControlCommand(self.node.params["v_mps"],
                              self.node.params["accel_mps2"])


class EmergencyStop(_Action):
    def act(self, w):
        return ControlCommand(0.0, self.node.params["decel_mps2"])


_LEAF_CLASSES = {
    "OncomingGapExceeds": OncomingGapExceeds,
    "EgoSpeedBelow": EgoSpeedBelow,
    "DistanceToStopLineBelow": DistanceToStopLineBelow,
    "InConflictZone": InConflictZone,
    "TrafficLightIsGreen": TrafficLightIsGreen,
    "PathIsClear": PathIsClear,
    "WaitedLongerThan": WaitedLongerThan,
    "Cruise": Cruise,
    "Decelerate": Decelerate,
    "HoldAtStopLine": HoldAtStopLine,
    "CommitTurn": CommitTurn,
    "Creep": Creep,
    "EmergencyStop": EmergencyStop,
}


def compile_tree(root: BTNode, ctx: ExecContext) -> py_trees.behaviour.Behaviour:
    """AST -> py_trees. The AST stays ours; only execution is delegated."""

    def build(n: BTNode):
        if n.name in V.COMPOSITE_NAMES:
            children = [build(c) for c in n.children]
            # memory=False: re-evaluate conditions from the start every tick.
            # With memory=True a Sequence would resume after its last running
            # child and skip the yield test, so the program would stop
            # reacting to oncoming traffic after committing once.
            cls = (py_trees.composites.Sequence if n.name == "Sequence"
                   else py_trees.composites.Selector)
            return cls(name=f"{n.name}#{n.node_id}", memory=False, children=children)
        cls = _LEAF_CLASSES.get(n.name)
        if cls is None:
            raise ValueError(f"no runtime implementation for node {n.name!r}")
        return cls(n, ctx)

    return build(root)


class BehaviourProgram:
    """A parsed, validated, compiled program ready to tick."""

    def __init__(self, source: str, grammar_only: bool = False):
        self.source = source
        self.ast, self.validation = parse_and_validate(source, grammar_only)
        self.ctx = ExecContext()
        self.tree = None
        if self.ast is not None and self.validation.ok:
            self.tree = py_trees.trees.BehaviourTree(compile_tree(self.ast, self.ctx))

    @property
    def usable(self) -> bool:
        return self.tree is not None

    def tick(self, world: WorldView) -> ControlCommand:
        """Advance one tick and return the command the tree issued."""
        if self.tree is None:
            raise RuntimeError("program did not validate; cannot tick")
        self.ctx.begin_tick()
        self.ctx.world = world
        self.tree.tick()
        return self.ctx.command

    def blame(self) -> dict:
        """Which leaf was responsible at the tick just executed."""
        acting = self.ctx.acting
        return {
            "bt_node_id": acting.node_id if acting else None,
            "bt_node_type": acting.name if acting else None,
            "bt_node_path": acting.path if acting else None,
            "bt_tick_path": ",".join(n.node_id for n in self.ctx.evaluated) or None,
        }
