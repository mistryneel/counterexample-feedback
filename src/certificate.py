"""Counterexample certificates, and the F1-F4 prompt renderers.

A THIN VIEW OVER WHAT IS ON DISK. `Certificate` loads a banked JSON file and
exposes its fields. It does not recompute rho, boundaries or blame; every
number it renders was computed by the falsifier and is read verbatim.

--------------------------------------------------------------------------
THE ONE INVARIANT THIS MODULE EXISTS TO PROTECT

F1-F4 must differ ONLY in information content. Not in polish, not in
formatting, not in instruction clarity, not in the length of the surrounding
scaffolding. If F4 wins because it reads better rather than because it says
more, the experiment measures writing quality.

Mechanically enforced here by construction:

  * ONE template, `data/prompts/patch_task.md`, with a single `{feedback}`
    placeholder. It is split ONCE at that placeholder into PREFIX and SUFFIX,
    and every condition's prompt is PREFIX + feedback + SUFFIX. There is no
    per-condition branch anywhere outside `feedback()`, so byte-identity of
    the scaffolding is a property of the code, not of a convention. It is
    additionally asserted by scripts/diff_prompts.py.
  * Every feedback block is written in the same `key: value` register, and
    F4a/F4b are literally F3's block with one further block appended -- so
    `f4.startswith(f3)` holds and the delta is exactly the blame field.

--------------------------------------------------------------------------
WHY THE BANKED `narrative` FIELD IS NOT USED VERBATIM  -- IMPORTANT

The `narrative` string on disk was composed by `falsifier.narrate()`, which
concatenates four clauses: the violation, the timestep, the ACTIVE NODE, and
the RAW `boundary_report`. Two of those four are information that the ablation
assigns to a strictly later condition:

  * `active_node` -- "while CommitTurn was the active behaviour" -- is the
    F4a-only field. Leaving it in would put blame localization into F2 and F3,
    which is the one contrast F4 exists to make.
  * `boundary_report` is the UNSUPPRESSED boundary. For the 7 certificates
    whose `headway` boundary is suppressed, the narrative prints exactly the
    string the suppression decision removed ("C1 fails for headway <= 7.529"),
    defeating it.

So the narrative is RE-COMPOSED here from the same banked fields, using the
same `CONTRACT_PHRASE` table `falsifier.narrate()` uses, with those two clauses
omitted. No wording is invented and nothing is recomputed: the identical prose
function is called with the two condition-specific clauses left empty. The
banked field is still exposed as `.narrative_banked` so the divergence is
auditable.

Consequence, and it is the point: `narrative_rendered` is byte-identical across
F2, F3, F4a and F4b. The boundary appears only in F3+, the blame only in F4+.

--------------------------------------------------------------------------
DEGRADED CERTIFICATES

`boundary_report_rendered` -- never `boundary_report` -- is what gets rendered.
Seven of the 20 have their only boundary parameter (`headway`) suppressed and
therefore render with NO boundary at all. That is a real weakening of the
"generalized" property (7.2) on 35% of the corpus, so it is surfaced as
`.degraded_no_boundary` rather than papered over, and the F3 block keeps the
`boundary:` field with an explicit "not established" value so the field
structure is constant across certificates.
"""
from __future__ import annotations

import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from bt_vocabulary import import_block  # noqa: E402
from config import load_config  # noqa: E402
from falsifier import CONTRACT_PHRASE  # noqa: E402

CERT_DIR = REPO_ROOT / "data" / "certificates"
# Repository copies of the 20 counterexample traces, one per certificate, named
# by the basename of the certificate's stored `trace_path`. See resolve_trace_path.
CERT_TRACE_DIR = CERT_DIR / "traces"
TEMPLATE_PATH = REPO_ROOT / "data" / "prompts" / "patch_task.md"
PROGRAM_PATH = REPO_ROOT / "data" / "scenarios" / "baseline_program.bt"

# The five conditions. F4a and F4b are both "F4"; they differ in WHICH blame
# definition is rendered. See src/blame.py -- F4a's field is provably constant
# on this baseline and is therefore a NEGATIVE CONTROL, not a bug.
CONDITIONS = ("F1", "F2", "F3", "F4a", "F4b")

# Contract one-liners, quoted so the LLM can act on the number it is being
# scored against. Identical in every condition that names a contract.
CONTRACT_NAME = {
    "C1": "no collision (minimum bounding-box clearance, metres)",
    "C2": "yield to oncoming traffic (time margin on the yield requirement, seconds)",
    "C3": "do not enter the intersection on red (time margin to red onset, seconds)",
    "C4": "RSS-safe distance behind the lead vehicle (metres)",
    "C5": "commanded-acceleration comfort (m/s^2)",
}

# --------------------------------------------------------------------------
# Plain-language blame. DERIVED MECHANICALLY from the node type, never written
# per certificate -- a hand-written gloss would make F4 a different piece of
# prose for every counterexample and would smuggle in analysis the field does
# not contain.
#
# Two clauses per node type:
#   STATE      what the ego was doing while that leaf ticked
#   TRANSITION the event of that leaf starting, used to place the prior leaf
#              in time for F4b ("... when it committed to the turn")
# --------------------------------------------------------------------------
NODE_STATE = {
    "CommitTurn": "the ego was driving through the junction",
    "Decelerate": "the ego was slowing down",
    "HoldAtStopLine": "the ego was stopping at, or holding on, the stop line",
    "Cruise": "the ego was cruising along the approach",
    "Creep": "the ego was creeping forward",
    "EmergencyStop": "the ego was braking as hard as the command allowed",
}
NODE_TRANSITION = {
    "CommitTurn": "it committed to the turn",
    "Decelerate": "it began slowing down",
    "HoldAtStopLine": "it began stopping at the stop line",
    "Cruise": "it began cruising",
    "Creep": "it began creeping forward",
    "EmergencyStop": "it began braking hard",
}


def _node_type(node: str | None) -> str | None:
    """Split a blame field 'CommitTurn:Selector/Sequence/CommitTurn'."""
    if not node:
        return None
    return node.split(":", 1)[0]


def _node_path(node: str | None) -> str | None:
    if not node or ":" not in node:
        return None
    return node.split(":", 1)[1]


def _state(node_type: str | None) -> str:
    return NODE_STATE.get(node_type, f"the ego was running {node_type}")


def _transition(node_type: str | None) -> str:
    return NODE_TRANSITION.get(node_type, f"{node_type} began running")


def _num(x) -> str:
    """One numeric format everywhere, so no condition looks more precise."""
    if x is None:
        return "not recorded"
    return f"{float(x):.4g}"


def resolve_trace_path(stored: str | pathlib.Path,
                       trace_dir: pathlib.Path | None = None) -> pathlib.Path:
    """Locate the trace a certificate points at.

    The banked certificates store the ABSOLUTE path the falsifier wrote the
    trace to on the original machine (`/home/.../data/traces/<name>.parquet`).
    The certificate JSON is a committed result and is left byte-identical, so
    the path is resolved here instead, in this order:

      1. `data/certificates/traces/<basename of the stored path>`, inside this
         repository. This is where the released copies live.
      2. The stored path itself, as written at banking time.

    The first candidate that exists is returned. If neither exists this raises
    FileNotFoundError naming both, rather than returning a path that fails
    later inside pandas with a less useful message.
    """
    stored_s = str(stored)
    # The stored paths are POSIX; PurePosixPath takes the basename correctly on
    # any platform.
    name = pathlib.PurePosixPath(stored_s).name
    local = (CERT_TRACE_DIR if trace_dir is None else trace_dir) / name
    if local.is_file():
        return local
    original = pathlib.Path(stored_s)
    if original.is_file():
        return original
    raise FileNotFoundError(
        f"trace {name!r} not found. Looked in, in order:\n"
        f"  1. {local}\n"
        f"  2. {original}  (path stored in the certificate)")


# --------------------------------------------------------------------------
# The template, split ONCE. Everything outside `{feedback}` is fixed here and
# cannot vary by condition.
# --------------------------------------------------------------------------
class PromptTemplate:
    """PREFIX + feedback + SUFFIX, with PREFIX/SUFFIX read from one file."""

    PLACEHOLDER = "{feedback}"

    def __init__(self, path: pathlib.Path = TEMPLATE_PATH,
                 program_path: pathlib.Path = PROGRAM_PATH):
        raw = path.read_text()
        if raw.count(self.PLACEHOLDER) != 1:
            raise ValueError(
                f"{path} must contain exactly one {self.PLACEHOLDER} placeholder; "
                f"found {raw.count(self.PLACEHOLDER)}")
        contracts = load_config("contracts")
        # `.replace`, not `.format`: the template embeds a fenced DSL program
        # and a vocabulary block, and `.format` would have to escape every
        # brace in them. One silent KeyError here would corrupt every prompt.
        filled = (raw
                  .replace("{vocab}", import_block())
                  .replace("{program}", program_path.read_text().strip())
                  .replace("{tau_yield}",
                           str(contracts["C2_yield"]["tau_yield_s"]))
                  .replace("{a_comfort}",
                           str(contracts["C5_comfort"]["a_comfort_mps2"])))
        i = filled.index(self.PLACEHOLDER)
        self.prefix = filled[:i]
        self.suffix = filled[i + len(self.PLACEHOLDER):]
        self.path = path
        self.program_path = program_path

    def render(self, feedback: str) -> str:
        return self.prefix + feedback + self.suffix

    def split_for_call(self, feedback: str) -> tuple[str, str]:
        """(system, user).

        The system block is the whole invariant prefix -- vocabulary, grammar,
        manoeuvre, contracts and the program -- because src/llm.py puts
        `cache_control` on the system block and nowhere else. Everything that
        varies across the campaign is therefore in the user message, and the
        cached prefix is as large as it can be.
        """
        return self.prefix.rstrip("\n"), feedback + self.suffix


_TEMPLATE: PromptTemplate | None = None


def template() -> PromptTemplate:
    global _TEMPLATE
    if _TEMPLATE is None:
        _TEMPLATE = PromptTemplate()
    return _TEMPLATE


# --------------------------------------------------------------------------
class Certificate:
    """One banked counterexample certificate, plus its five renderings."""

    def __init__(self, raw: dict, path: pathlib.Path | None = None):
        self.raw = raw
        self.path = path

    # -- loading ----------------------------------------------------------
    @classmethod
    def from_path(cls, path: str | pathlib.Path) -> "Certificate":
        p = pathlib.Path(path)
        return cls(json.loads(p.read_text()), p)

    @classmethod
    def load_all(cls, directory: str | pathlib.Path = CERT_DIR) -> list["Certificate"]:
        return [cls.from_path(p)
                for p in sorted(pathlib.Path(directory).glob("CE*.json"))]

    # -- thin field accessors --------------------------------------------
    @property
    def certificate_id(self) -> str:
        return self.raw["certificate_id"]

    @property
    def contract(self) -> str:
        return self.raw["violated_contract"]

    @property
    def rho(self) -> float:
        return self.raw["rho"]

    @property
    def per_contract(self) -> dict:
        """rho_1..rho_5 on the counterexample scenario, read as banked."""
        return {c: self.raw[f"rho{c[1]}"] for c in ("C1", "C2", "C3", "C4", "C5")
                if f"rho{c[1]}" in self.raw}

    @property
    def argmin_t_s(self) -> float | None:
        return self.raw.get("argmin_t_s")

    @property
    def argmin_index(self) -> int:
        return int(self.raw["argmin_index"])

    @property
    def minimal_params(self) -> dict:
        return self.raw["minimal_params"]

    @property
    def kept_parameters(self) -> list:
        return list(self.raw.get("kept_parameters", []))

    @property
    def dropped_parameters(self) -> list:
        return list(self.raw.get("dropped_parameters", []))

    @property
    def boundary_report(self) -> str:
        """The RAW boundary. Never rendered into a prompt -- see module docstring."""
        return self.raw.get("boundary_report", "")

    @property
    def boundary_rendered(self) -> str:
        """The boundary AS RENDERED, i.e. with suppressed parameters removed."""
        return self.raw.get("boundary_report_rendered", "")

    @property
    def boundary_suppressed(self) -> list:
        return list(self.raw.get("boundary_suppressed", []))

    @property
    def degraded_no_boundary(self) -> bool:
        """True when suppression left this certificate with NO boundary at all.

        7 of 20. These are point counterexamples in everything but name: the
        "generalized" property of spec 7.2 is not delivered for them and the
        limitations section has to say so.
        """
        return not self.boundary_rendered.strip()

    @property
    def active_node(self) -> str | None:
        return self.raw.get("active_node")

    @property
    def authorising_node(self) -> str | None:
        return self.raw.get("authorising_node")

    @property
    def narrative_banked(self) -> str:
        """The narrative AS STORED. Leaks blame and the unsuppressed boundary."""
        return self.raw.get("narrative", "")

    @property
    def achieved_gap_s(self):
        return self.raw.get("achieved_gap_s")

    @property
    def trace_path_stored(self) -> str:
        """`trace_path` AS STORED: an absolute path on the original machine."""
        return self.raw["trace_path"]

    @property
    def trace_path(self) -> pathlib.Path:
        """The trace on THIS machine; see `resolve_trace_path` for the order."""
        return resolve_trace_path(self.trace_path_stored)

    # -- the re-composed narrative ---------------------------------------
    @property
    def narrative_rendered(self) -> str:
        """`falsifier.narrate()`'s prose with the blame and boundary clauses
        left empty, so the same sentence is safe to show from F2 upward.

        Built from the same CONTRACT_PHRASE table the banked narrative uses;
        no new wording is introduced here.
        """
        mag = abs(float(self.rho))
        c = self.contract
        if c == "C2":
            body = CONTRACT_PHRASE["C2"].format(
                ttc=3.0 - mag if self.rho < 0 else 3.0 + mag)
        else:
            body = CONTRACT_PHRASE.get(
                c, "violated {c} by {v:.2f}").format(v=mag, c=c)
        when = f" at t = {self.argmin_t_s:.2f} s" if self.argmin_t_s is not None else ""
        gap = ""
        if self.achieved_gap_s is not None:
            gap = (" The gap the ego actually faced was "
                   f"{self.achieved_gap_s:.2f} s.")
        return f"The ego {body}{when}.{gap}"

    # -- the raw trace excerpt (F1) ---------------------------------------
    def trace_excerpt(self, halfwidth: int | None = None) -> tuple[str, int, int, int]:
        """(csv, first_row, last_row, total_rows) around the argmin timestep.

        Every logged column is included. This is the RAW signal condition: no
        selection, no summarisation, no derived quantity. Selecting columns
        here would quietly turn F1 into a weak F3.
        """
        import pandas as pd
        if halfwidth is None:
            halfwidth = int(load_config("experiment")["f1_excerpt_halfwidth_rows"])
        df = pd.read_parquet(self.trace_path)
        n = len(df)
        i = self.argmin_index
        if halfwidth < 0:                    # negative means "the whole trace"
            lo, hi = 0, n
        else:
            # CONSTANT ROW COUNT, not a constant offset. In 18 of the 20 banked
            # traces the argmin IS the final logged row -- the episode ends at
            # the collision -- so a naive [i-w, i+w] clip hands those
            # certificates half a window (21 rows) and the other two a full one
            # (41 rows). That is a 2x information difference BETWEEN
            # certificates inside a single condition, which would show up in
            # the fix-rate-per-1k-tokens figure as if it were a property of the
            # counterexample. The window is therefore slid to stay inside the
            # trace rather than truncated.
            want = min(n, 2 * halfwidth + 1)
            lo = max(0, min(i - halfwidth, n - want))
            hi = lo + want
        return df.iloc[lo:hi].to_csv(index=False).rstrip("\n"), lo, hi - 1, n

    # -- the five feedback blocks -----------------------------------------
    def _block_f1(self, halfwidth: int | None = None) -> str:
        csv, lo, hi, n = self.trace_excerpt(halfwidth)
        ncol = len(csv.split("\n", 1)[0].split(","))
        return (f"trace: logged trajectory, rows {lo}-{hi} of {n}, "
                f"all {ncol} columns, comma-separated\n{csv}")

    def _block_f2(self) -> str:
        return f"narrative: {self.narrative_rendered}"

    def _block_f3(self) -> str:
        pc = self.per_contract
        kept = self.kept_parameters
        minimal = self.minimal_params
        lines = [
            f"violated_contract: {self.contract} -- {CONTRACT_NAME.get(self.contract, self.contract)}",
            f"rho: {_num(self.rho)}",
            "rho_per_contract: " + ", ".join(
                f"{k}={_num(v)}" for k, v in sorted(pc.items())),
            f"violation_time_s: {_num(self.argmin_t_s)}",
            "minimal_scenario: " + (
                ", ".join(f"{k}={_num(minimal[k])}" for k in kept)
                if kept else "no parameter was found to be necessary"),
            "irrelevant_parameters: " + (
                ", ".join(self.dropped_parameters)
                + " (reverted to their benign values and the violation persisted)"
                if self.dropped_parameters else "none"),
            "boundary: " + (self.boundary_rendered.strip()
                            if not self.degraded_no_boundary
                            else "not established for this counterexample"),
            f"narrative: {self.narrative_rendered}",
        ]
        return "\n".join(lines)

    def _blame_block(self, definition: str) -> str:
        """One block, one frame, parameterised by which banked field is read.

        F4a and F4b share this frame exactly. Only the field read and the
        one-line definition of that field differ, which is the whole of the
        information difference between them.
        """
        act_t = _node_type(self.active_node)
        if definition == "active":
            node, gloss = self.active_node, (
                "the behaviour-tree leaf that was executing at the timestep "
                "where rho reached its minimum")
            meaning = f"{_state(_node_type(node))} at the moment of the violation"
        elif definition == "authorising":
            node, gloss = self.authorising_node, (
                "the behaviour-tree leaf that was executing immediately before "
                "the failing leaf began running")
            if node is None:
                # blame.py returns None when the failing leaf was active from
                # the first logged tick. Report it absent, never backfilled.
                return ("blame_definition: " + gloss + "\n"
                        "blame_node: none -- the failing leaf was already "
                        "running at the first logged tick\n"
                        "blame_meaning: no prior behaviour exists to name")
            meaning = (f"{_state(_node_type(node))} when "
                       f"{_transition(act_t)}")
        else:
            raise ValueError(definition)
        return ("blame_definition: " + gloss + "\n"
                f"blame_node: {_node_type(node)} ({_node_path(node)})\n"
                f"blame_meaning: {meaning}")

    def feedback(self, condition: str, halfwidth: int | None = None) -> str:
        if condition == "F1":
            return self._block_f1(halfwidth)
        if condition == "F2":
            return self._block_f2()
        if condition == "F3":
            return self._block_f3()
        if condition == "F4a":
            return self._block_f3() + "\n" + self._blame_block("active")
        if condition == "F4b":
            return self._block_f3() + "\n" + self._blame_block("authorising")
        raise ValueError(f"unknown condition {condition!r}; expected one of {CONDITIONS}")

    # -- prompts -----------------------------------------------------------
    def prompt(self, condition: str, halfwidth: int | None = None) -> str:
        """The complete prompt text, for diffing and token counting."""
        return template().render(self.feedback(condition, halfwidth))

    def prompt_parts(self, condition: str,
                     halfwidth: int | None = None) -> tuple[str, str]:
        """(system, user) as sent to the API."""
        return template().split_for_call(self.feedback(condition, halfwidth))
