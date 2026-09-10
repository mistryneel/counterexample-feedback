"""Behaviour-tree node vocabulary for the unprotected left turn.

SINGLE SOURCE OF TRUTH. The parser, the validator, the py_trees compiler, and
the import block shown to the coding agent all read this module. A vocabulary
duplicated across those four places is a vocabulary that drifts.

Presentation to the LLM follows ProgPrompt (Singh et al., ICRA 2023): the
available nodes are given as an IMPORT BLOCK with typed signatures and one-line
docstrings, not as prose.

FIELD NAMES CARRY THEIR TYPE (project conventions): v_mps, gap_s, dist_m,
t_s, accel_mps2, decel_mps2. Ambiguous names poison LLM output consistency --
`gap` alone is read as metres by one sample and seconds by the next.

NOTE ON REPO LAYOUT: the planned layout lists src/program_parser.py but not this file.
The vocabulary lives here because it has four consumers, one of which is prompt
construction rather than parsing.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ParamSpec:
    name: str
    type: str                 # "float" | "int"
    lo: float
    hi: float
    doc: str

    def check(self, value) -> str | None:
        """Return an error string, or None if the value is acceptable."""
        if self.type == "int":
            if not isinstance(value, int) or isinstance(value, bool):
                return f"{self.name} must be an integer, got {value!r}"
        else:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return f"{self.name} must be a number, got {value!r}"
        if not (self.lo <= float(value) <= self.hi):
            return (f"{self.name}={value} is outside the permitted range "
                    f"[{self.lo}, {self.hi}]")
        return None


@dataclass(frozen=True)
class NodeSpec:
    name: str
    kind: str                 # "composite" | "condition" | "action"
    params: tuple[ParamSpec, ...]
    doc: str
    min_children: int = 0
    max_children: int = 0

    def signature(self) -> str:
        args = ", ".join(f"{p.name}: {p.type}" for p in self.params)
        if self.kind == "composite":
            args = "*children" if not args else f"{args}, *children"
        return f"{self.name}({args})"


# --------------------------------------------------------------------------
# Composites
# --------------------------------------------------------------------------
COMPOSITES = [
    NodeSpec(
        "Sequence", "composite", (),
        "Run children in order. Fail at the first child that fails. "
        "Succeed only if every child succeeds. Use for 'do A, then B'.",
        min_children=1, max_children=8,
    ),
    NodeSpec(
        "Selector", "composite", (),
        "Run children in order. Succeed at the first child that succeeds. "
        "Use for 'try A, otherwise B' -- the LAST child is the fallback.",
        min_children=1, max_children=8,
    ),
]

# --------------------------------------------------------------------------
# Conditions -- read the world, return SUCCESS or FAILURE, never RUNNING
# --------------------------------------------------------------------------
CONDITIONS = [
    NodeSpec(
        "OncomingGapExceeds", "condition",
        (ParamSpec("gap_s", "float", 0.0, 15.0,
                   "required time-to-conflict-zone of the nearest oncoming vehicle"),),
        "SUCCESS if the nearest oncoming vehicle needs at least gap_s seconds "
        "to reach the conflict zone. This is the yield test.",
    ),
    NodeSpec(
        "EgoSpeedBelow", "condition",
        (ParamSpec("v_mps", "float", 0.0, 20.0, "speed threshold"),),
        "SUCCESS if the ego is travelling slower than v_mps.",
    ),
    NodeSpec(
        "DistanceToStopLineBelow", "condition",
        (ParamSpec("dist_m", "float", 0.0, 60.0, "distance threshold"),),
        "SUCCESS if the ego is within dist_m of the stop line. "
        "Becomes negative-distance (still SUCCESS) once past it.",
    ),
    NodeSpec(
        "InConflictZone", "condition", (),
        "SUCCESS if the ego bounding box is inside the conflict zone.",
    ),
    NodeSpec(
        "TrafficLightIsGreen", "condition", (),
        "SUCCESS if the signal governing the ego approach is green.",
    ),
    NodeSpec(
        "PathIsClear", "condition",
        (ParamSpec("dist_m", "float", 0.0, 60.0, "look-ahead distance"),),
        "SUCCESS if no actor lies within dist_m along the ego's turn path.",
    ),
    NodeSpec(
        "WaitedLongerThan", "condition",
        (ParamSpec("t_s", "float", 0.0, 30.0, "elapsed stationary time"),),
        "SUCCESS if the ego has been essentially stationary for t_s seconds. "
        "Use to escape a deadlock where no acceptable gap ever appears.",
    ),
]

# --------------------------------------------------------------------------
# Actions -- issue a control command, return RUNNING while working
# --------------------------------------------------------------------------
# EVERY action that changes speed takes an explicit accel_mps2 or decel_mps2.
#
# This is deliberate and load-bearing. C5 (kinematic comfort) is computed from
# COMMANDED control (docs/c5_decision.md). If the tree only chose target
# speeds and a fixed PID converted them to throttle and brake, C5 would score
# the PID and not the tree -- measured on 300 traces, rho_5 was a CONSTANT with
# zero variance, and therefore discriminated nothing. Making the ramp a program
# parameter is what lets "brake hard and never turn" and "brake gently and
# turn" be different programs with different rho_5.
# --------------------------------------------------------------------------
ACTIONS = [
    NodeSpec(
        "Cruise", "action",
        (ParamSpec("v_mps", "float", 0.0, 15.0, "target speed"),
         ParamSpec("accel_mps2", "float", 0.1, 6.0, "acceleration limit while reaching it")),
        "Drive along the route at v_mps, changing speed no faster than accel_mps2. "
        "Returns RUNNING.",
    ),
    NodeSpec(
        "Decelerate", "action",
        (ParamSpec("v_mps", "float", 0.0, 15.0, "speed to slow to"),
         ParamSpec("decel_mps2", "float", 0.1, 8.0, "deceleration to use")),
        "Slow to v_mps at decel_mps2. A large decel_mps2 is uncomfortable and "
        "is penalised by contract C5. Returns RUNNING.",
    ),
    NodeSpec(
        "HoldAtStopLine", "action",
        (ParamSpec("decel_mps2", "float", 0.1, 8.0, "deceleration to use"),),
        "Come to a stop at the stop line at decel_mps2 and hold there. "
        "Returns RUNNING.",
    ),
    NodeSpec(
        "CommitTurn", "action",
        (ParamSpec("v_mps", "float", 0.5, 15.0, "speed to carry through the turn"),
         ParamSpec("accel_mps2", "float", 0.1, 6.0, "acceleration limit")),
        "Commit to the left turn and drive through the conflict zone at v_mps. "
        "Returns RUNNING until the ego has cleared the junction.",
    ),
    NodeSpec(
        "Creep", "action",
        (ParamSpec("v_mps", "float", 0.1, 3.0, "creep speed"),
         ParamSpec("accel_mps2", "float", 0.1, 3.0, "acceleration limit")),
        "Edge forward slowly to improve visibility without entering the "
        "conflict zone. Returns RUNNING.",
    ),
    NodeSpec(
        "EmergencyStop", "action",
        (ParamSpec("decel_mps2", "float", 1.0, 8.0, "deceleration to use"),),
        "Brake as hard as decel_mps2 allows. Returns RUNNING.",
    ),
]

ALL_NODES = {n.name: n for n in COMPOSITES + CONDITIONS + ACTIONS}
COMPOSITE_NAMES = {n.name for n in COMPOSITES}
CONDITION_NAMES = {n.name for n in CONDITIONS}
ACTION_NAMES = {n.name for n in ACTIONS}

MAX_DEPTH = 8      # spec 4.4


def import_block() -> str:
    """The vocabulary as a ProgPrompt-style import block, for the LLM prompt.

    This string is what the coding agent sees. It is generated from the specs
    above so the prompt can never disagree with the validator.
    """
    lines = [
        "# Available behaviour-tree nodes. Use ONLY these.",
        "# Indentation is two spaces per level. Parameters are name=value.",
        "",
        "# --- composites (take children) ---",
    ]
    for n in COMPOSITES:
        lines.append(f"{n.signature()}")
        lines.append(f"    # {n.doc}")
        # STRUCTURAL LIMITS MUST BE STATED. The validator rejects a composite
        # with more than max_children, and a program rejected for a rule the
        # agent was never given is a MANUFACTURED malformed output: it inflates
        # the malformed-output rate for a reason unrelated to the research
        # question, and it does so inside the F1-F4 comparison as well. Read
        # from the same NodeSpec the validator reads, so the two cannot drift.
        lines.append(f"    # Takes {n.min_children} to {n.max_children} "
                     f"children. More than {n.max_children} is rejected.")
    lines += ["", "# --- conditions (return SUCCESS or FAILURE) ---"]
    for n in CONDITIONS:
        lines.append(f"{n.signature()}")
        lines.append(f"    # {n.doc}")
    lines += ["", "# --- actions (drive the vehicle) ---"]
    for n in ACTIONS:
        lines.append(f"{n.signature()}")
        lines.append(f"    # {n.doc}")
    lines += [
        "",
        "# Parameter ranges are enforced by the validator:",
    ]
    seen = {}
    for n in ALL_NODES.values():
        for p in n.params:
            seen.setdefault(p.name, (p.lo, p.hi, p.doc))
    for name, (lo, hi, doc) in sorted(seen.items()):
        lines.append(f"#   {name}: [{lo}, {hi}]  -- {doc}")
    lines += [
        f"#   maximum tree depth: {MAX_DEPTH}",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    print(import_block())
