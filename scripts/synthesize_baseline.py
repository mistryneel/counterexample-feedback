#!/usr/bin/env python3
"""Synthesize candidate baseline programs with the LLM.

ONE fixed prompt, N independent samples. That is the whole design, and it is
deliberate: the alternative -- re-prompting until a program lands in the 20-40%
violation band -- tunes the prompt against the outcome, which makes the
"LLM-synthesized" claim mean much less and quietly encodes the author's
knowledge of what makes the program fail.

Sampling N and SELECTING is honest as long as the selection is disclosed, so
this script reports the full distribution of every candidate it drew, not only
the one that gets frozen. That distribution doubles as the resample-and-select
baseline data spec 9.4 already asks for.

    scripts/synthesize_baseline.py --n 12

Candidates land in data/scenarios/candidates/ and are scored separately by
scripts/calibrate_baseline.py, which owns the two freeze gates. This script
never freezes anything.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

import llm  # noqa: E402
from bt_vocabulary import import_block  # noqa: E402
from program_parser import parse_and_validate  # noqa: E402
from config import load_config  # noqa: E402


SYSTEM = """You write behaviour-tree programs for an autonomous vehicle in a \
driving simulator. You output ONLY a program in the .bt DSL described below, \
inside a single ``` fenced block, with no prose before or after it.

{vocab}

GRAMMAR -- there are only five rules:
1. One node per line.
2. Two spaces of indentation per level. Tabs are rejected.
3. NodeName(param=value, param=value). The () may be omitted when there are no
   parameters.
4. # starts a comment. Blank lines are ignored.
5. Exactly one root.

Composite semantics, which matter:
- Sequence runs children in order, fails at the first failure, succeeds only if
  all succeed.
- Selector runs children in order and succeeds at the first success; its LAST
  child is the fallback.
- Both re-evaluate every condition from the top on EVERY tick (20 Hz). There is
  no memory of which child was running last tick. A Sequence will therefore
  abandon a running action the moment one of its earlier conditions stops
  holding.
"""


TASK = """Write a program that performs an UNPROTECTED LEFT TURN at a \
signalised four-way junction.

"Unprotected" means the ego has a circular green ball, not a green arrow: the
turn is legally permitted but oncoming traffic has right of way, and the ego
must find its own gap.

THE SITUATION
- The ego approaches the junction, must yield to oncoming traffic, turn left
  across their path, and settle into the target lane.
- Between one and three oncoming vehicles travel straight through at a constant
  6 to 16 m/s. They do not always slow down for the ego.
- One LEAD VEHICLE travels ahead of the ego in the ego's own lane at 6 m/s. It
  decelerates to a stop at the stop line, waits, then drives on and clears.
- The ego's signal is green at t=0, then turns yellow for 3 s, then red for 6 s,
  then returns to green. The time at which the green ends varies between runs
  from 3 s to 13 s after the start. The ego typically reaches the junction
  around 10 s.

YOU WILL BE SCORED ON FIVE SAFETY CONTRACTS
Each is a signed margin: positive means satisfied, negative means violated.

  C1  no collision -- minimum bounding-box clearance to any actor, in metres.
  C2  yield -- while inside the conflict zone, the nearest oncoming vehicle
      must need at least {tau_yield} s to reach it. Margin in seconds.
  C3  do not ENTER the intersection on red. Margin in seconds: positive is the
      green time remaining at the moment of entry, negative is how long the
      light had already been red. Being caught inside when the light changes is
      NOT penalised -- once you have lawfully entered you are expected to clear.
  C4  keep an RSS-safe longitudinal distance to the LEAD vehicle. The required
      distance grows with your speed and shrinks with the lead's. At 8 m/s
      behind a lead doing 6 m/s it is about 20 metres. Margin in metres.
  C5  comfort -- commanded longitudinal acceleration must stay within
      {a_comfort} m/s^2.

The overall score is the MINIMUM of the five, so the weakest one decides.

AND ON COMPLETING THE TASK
A program that never enters the junction violates nothing and still fails. It
must actually complete the turn and settle into the target lane. Waiting
forever is not a solution; there is a deadlock-escape condition in the
vocabulary for the case where no acceptable gap ever appears.

DESIGN NOTES
- Order the Selector's branches by priority. The last branch is the fallback.
- Remember conditions are re-checked every tick. If you gate the turn on a
  condition that stops holding halfway through, the ego will abandon the turn
  inside the junction, which is far more dangerous than completing it.
- Choose thresholds deliberately. A threshold exactly equal to a contract's
  limit leaves no margin for the time it takes to react.

Output the program and nothing else."""


def build_prompts() -> tuple[str, str]:
    contracts = load_config("contracts")
    system = SYSTEM.format(vocab=import_block())
    task = TASK.format(
        tau_yield=contracts["C2_yield"]["tau_yield_s"],
        a_comfort=contracts["C5_comfort"]["a_comfort_mps2"],
    )
    return system, task


def extract_program(text: str) -> str:
    """Pull the .bt source out of the response."""
    if "```" in text:
        parts = text.split("```")
        # take the first fenced block, dropping an optional language tag line
        body = parts[1]
        lines = body.splitlines()
        if lines and lines[0].strip() and "(" not in lines[0]:
            lines = lines[1:]
        return "\n".join(lines).strip() + "\n"
    return text.strip() + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=12)
    ap.add_argument("--outdir", default="data/scenarios/candidates")
    ap.add_argument("--effort", default="high")
    a = ap.parse_args()

    system, task = build_prompts()
    outdir = REPO / a.outdir
    outdir.mkdir(parents=True, exist_ok=True)

    print(f"synthesizing {a.n} candidates · model={llm.MODEL} effort={a.effort}")
    print(f"system prompt {len(system)} chars · task {len(task)} chars\n")

    rows = []
    tot_in = tot_out = tot_cache = 0
    for i in range(a.n):
        try:
            r = llm.call(task, system=system, tag=f"synth_{i:02d}",
                         effort=a.effort)
        except Exception as exc:
            print(f"  [{i:02d}] CALL FAILED: {type(exc).__name__}: {exc}")
            rows.append({"index": i, "ok": False, "error": str(exc)})
            continue

        u = r["usage"]
        tot_in += u["tokens_prompt"]; tot_out += u["tokens_completion"]
        tot_cache += u["cache_read"]

        truncated = u["stop_reason"] == "max_tokens"
        src = extract_program(r["text"])
        path = outdir / f"cand_{i:02d}.bt"
        path.write_text(src)

        # MALFORMED OUTPUT IS A SEPARATE OUTCOME from unsafe output and is
        # never pooled with it (project rule 3). Recorded here at
        # synthesis so the synthesis malformed rate is known before any
        # program reaches the simulator.
        try:
            ast, v = parse_and_validate(src)
            ok = bool(v.ok) and ast is not None
            # A parse failure returns ast=None. Reading ast.depth() first would
            # raise and mask the ACTUAL validator error behind an AttributeError,
            # which is the difference between "the model emitted bad indentation"
            # and "the harness crashed" -- and those must never be conflated.
            depth = ast.depth() if ast is not None else None
            size = ast.size() if ast is not None else None
            errs = list(v.errors)
        except Exception as exc:
            ok, depth, size, errs = False, None, None, [f"{type(exc).__name__}: {exc}"]

        try:
            rel = str(path.relative_to(REPO))
        except ValueError:
            rel = str(path)
        rows.append({"index": i, "path": rel,
                     "validator_ok": ok, "truncated": truncated, "errors": errs,
                     "depth": depth, "size": size,
                     "tokens_prompt": u["tokens_prompt"],
                     "tokens_completion": u["tokens_completion"],
                     "cache_read": u["cache_read"],
                     "call_id": u["call_id"]})
        flag = "ok  " if ok else ("TRUNCATED" if truncated else "MALFORMED")
        print(f"  [{i:02d}] {flag} depth={depth} size={size} "
              f"{u['tokens_prompt']}+{u['tokens_completion']}tok "
              f"cache_read={u['cache_read']} {u['elapsed_s']}s"
              + ("" if ok else f"  {errs}"))

    n_ok = sum(1 for r in rows if r.get("validator_ok"))
    n_trunc = sum(1 for r in rows if r.get("truncated"))
    # Malformed excludes truncation: a response cut off at max_tokens tells you
    # nothing about whether the model can write valid DSL.
    n_malformed = sum(1 for r in rows
                      if not r.get("validator_ok") and not r.get("truncated"))
    cost = llm.cost_usd(tot_in, tot_out, tot_cache)
    scoreable = len(rows) - n_trunc
    out = {"n_requested": a.n, "n_valid": n_ok, "n_truncated": n_trunc,
           "n_malformed": n_malformed,
           "malformed_rate": (n_malformed / scoreable) if scoreable else None,
           "malformed_rate_note": "truncated calls excluded from the denominator",
           "model": llm.MODEL, "effort": a.effort,
           "tokens_prompt": tot_in, "tokens_completion": tot_out,
           "cache_read": tot_cache, "cost_usd": round(cost, 4),
           "git_commit": llm.git_commit(), "candidates": rows}
    (REPO / "data/results/synthesis.json").write_text(json.dumps(out, indent=2))

    print(f"\n{n_ok}/{len(rows)} valid · {n_malformed} malformed · "
          f"{n_trunc} truncated (harness, not model)")
    if scoreable:
        print(f"malformed rate {100*n_malformed/scoreable:.0f}% "
              f"(of {scoreable} scoreable, truncated excluded)")
    print(f"tokens {tot_in} in / {tot_out} out / {tot_cache} cache-read"
          f"   cost ${cost:.3f}")
    print(f"candidates in {a.outdir}/ · written data/results/synthesis.json")
    print("\nNothing is frozen. Score these with:")
    print(f"  scripts/calibrate_baseline.py --programs {a.outdir}/*.bt --n 120")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
