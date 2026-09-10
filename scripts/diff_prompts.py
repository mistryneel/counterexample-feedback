#!/usr/bin/env python3
"""Prompt-symmetry evidence: prove F1-F4 differ ONLY in the feedback block.

This is EVIDENCE, not decoration. §9.1 promises the paper's appendix will carry
a diff a reviewer can check, because the entire ablation rests on the claim
that the conditions differ in information and in nothing else.

Two things are produced:

  1. A MECHANICAL ASSERTION, per certificate, that every byte outside the
     `{feedback}` region is identical across all five conditions. The check is
     done by INDEX, not by string replacement: each prompt is split at the
     known prefix length and the known suffix length, and the two remainders
     are compared byte for byte and by SHA-256. A `str.replace` check could be
     fooled by a feedback block that happens to contain scaffolding text.

  2. A unified diff between every ordered pair of conditions for one
     representative certificate, written to docs/prompt_symmetry.md.

    .venv/bin/python scripts/diff_prompts.py                 # all 20, assert
    .venv/bin/python scripts/diff_prompts.py --write-doc     # + the artifact
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import itertools
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from certificate import CONDITIONS, Certificate, template  # noqa: E402

DOC = REPO / "docs" / "prompt_symmetry.md"
# Representative certificate for the written artifact. A C1 one, because C1 is
# the only contract on which F4b carries information beyond F3: the 0.5 bits of
# H(authorising_node | contract) live entirely in C1's 5/5 Decelerate /
# HoldAtStopLine split (blame.py). F4a and F4b differ in TEXT everywhere, since
# active_node is always CommitTurn and authorising_node never is.
REPRESENTATIVE = "CE003"


def sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def check_one(cert: Certificate) -> dict:
    """Assert scaffolding byte-identity across the five conditions."""
    tpl = template()
    npre, nsuf = len(tpl.prefix), len(tpl.suffix)
    prefixes, suffixes, feedbacks, prompts = {}, {}, {}, {}
    for cond in CONDITIONS:
        p = cert.prompt(cond)
        fb = cert.feedback(cond)
        # Split by INDEX. The prefix is the first npre bytes and the suffix the
        # last nsuf bytes, by construction of PromptTemplate.render.
        prefixes[cond] = p[:npre]
        suffixes[cond] = p[len(p) - nsuf:] if nsuf else ""
        feedbacks[cond] = p[npre:len(p) - nsuf] if nsuf else p[npre:]
        prompts[cond] = p
        if feedbacks[cond] != fb:
            raise AssertionError(
                f"{cert.certificate_id}/{cond}: the feedback region recovered "
                "by index does not equal the rendered feedback block")

    distinct_prefix = {sha(v) for v in prefixes.values()}
    distinct_suffix = {sha(v) for v in suffixes.values()}
    ok = len(distinct_prefix) == 1 and len(distinct_suffix) == 1

    # F4a and F4b must be F3 plus exactly one appended block.
    f3 = feedbacks["F3"]
    appended = {}
    for cond in ("F4a", "F4b"):
        if not feedbacks[cond].startswith(f3):
            raise AssertionError(
                f"{cert.certificate_id}/{cond}: not a strict extension of F3")
        appended[cond] = feedbacks[cond][len(f3):]

    return {
        "certificate_id": cert.certificate_id,
        "contract": cert.contract,
        "ok": ok,
        "prefix_sha": distinct_prefix.pop() if ok else sorted(
            {sha(v) for v in prefixes.values()}),
        "suffix_sha": distinct_suffix.pop() if ok else sorted(
            {sha(v) for v in suffixes.values()}),
        "prefix_bytes": npre,
        "suffix_bytes": nsuf,
        "feedback_bytes": {c: len(v) for c, v in feedbacks.items()},
        "appended_blocks": appended,
        "prompts": prompts,
        "feedbacks": feedbacks,
    }


def unified(a: str, b: str, an: str, bn: str, context: int = 2) -> str:
    return "".join(difflib.unified_diff(
        a.splitlines(keepends=True), b.splitlines(keepends=True),
        fromfile=an, tofile=bn, n=context))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-doc", action="store_true")
    ap.add_argument("--representative", default=REPRESENTATIVE)
    ap.add_argument("--max-diff-lines", type=int, default=60,
                    help="truncate F1 diffs in the written artifact only; the "
                         "assertion always runs on the full text")
    a = ap.parse_args()

    certs = Certificate.load_all()
    results = [check_one(c) for c in certs]
    failed = [r for r in results if not r["ok"]]

    for r in results:
        fb = r["feedback_bytes"]
        print(f"{r['certificate_id']}  {r['contract']}  "
              f"{'PASS' if r['ok'] else 'FAIL'}  "
              f"prefix={r['prefix_sha'] if r['ok'] else r['prefix_sha']}  "
              "feedback_bytes=" + " ".join(f"{c}:{fb[c]}" for c in CONDITIONS))

    print(f"\nbyte-identity of everything outside the feedback block: "
          f"{'PASS' if not failed else 'FAIL'} over {len(results)} certificates")
    print(f"fixed scaffolding: {results[0]['prefix_bytes']} bytes before the "
          f"feedback block, {results[0]['suffix_bytes']} bytes after")
    if failed:
        print("FAILED:", [r["certificate_id"] for r in failed])
        return 1

    if a.write_doc:
        rep = next(r for r in results
                   if r["certificate_id"].startswith(a.representative))
        write_doc(rep, results, a.max_diff_lines)
        print(f"wrote {DOC.relative_to(REPO)}")
    return 0


def write_doc(rep: dict, results: list[dict], max_diff_lines: int) -> None:
    tpl = template()
    L = []
    L.append("# Prompt symmetry — the F1–F4 conditions differ only in the feedback block\n")
    L.append("Generated by `scripts/diff_prompts.py --write-doc`. Regenerate rather "
             "than edit.\n")
    L.append("The ablation's whole claim is that the conditions differ in *information*, "
             "not in polish. That is enforced structurally rather than by review: there "
             "is ONE template, `data/prompts/patch_task.md`, with a single `{feedback}` "
             "placeholder, and `src/certificate.py` splits it once into a prefix and a "
             "suffix. Every prompt in the campaign is `prefix + feedback + suffix`. No "
             "code path outside `Certificate.feedback()` can vary by condition.\n")

    L.append("## Mechanical assertion\n")
    L.append(f"- certificates checked: **{len(results)}**")
    L.append(f"- fixed scaffolding: **{rep['prefix_bytes']} bytes** before the feedback "
             f"block, **{rep['suffix_bytes']} bytes** after")
    L.append(f"- SHA-256/16 of the prefix, identical across all five conditions and all "
             f"{len(results)} certificates: `{rep['prefix_sha']}`")
    L.append(f"- SHA-256/16 of the suffix, likewise: `{rep['suffix_sha']}`")
    L.append("- result: **PASS** — every byte outside the feedback region is identical "
             "across F1, F2, F3, F4a and F4b.\n")
    L.append("The check splits each rendered prompt by *index* (first `len(prefix)` "
             "bytes, last `len(suffix)` bytes) rather than by `str.replace`, so a "
             "feedback block that happened to contain scaffolding text could not "
             "disguise a difference.\n")

    L.append("## What differs between conditions\n")
    L.append("Exactly one thing: the contents of the feedback block. Enumerated:\n")
    L.append("| Condition | Feedback block contains |")
    L.append("|---|---|")
    L.append("| F1 | the logged trajectory rows around the violation, every column, as CSV |")
    L.append("| F2 | `narrative:` — one or two sentences of plain English |")
    L.append("| F3 | `violated_contract:`, `rho:`, `rho_per_contract:`, "
             "`violation_time_s:`, `minimal_scenario:`, `irrelevant_parameters:`, "
             "`boundary:`, `narrative:` |")
    L.append("| F4a | F3's block verbatim, plus `blame_definition:` / `blame_node:` / "
             "`blame_meaning:` reading `active_node` |")
    L.append("| F4b | F3's block verbatim, plus the same three keys reading "
             "`authorising_node` |")
    L.append("")
    L.append("F4a and F4b are strict textual extensions of F3 — asserted mechanically, "
             "not judged by eye: `feedback(F4x).startswith(feedback(F3))` holds for all "
             f"{len(results)} certificates. The appended block for the representative "
             "certificate is shown in the diffs below.\n")
    L.append("Two asymmetries that are **not** scaffolding and are stated here so they "
             "are not mistaken for one:\n")
    L.append("- The `narrative:` line is byte-identical in F2, F3, F4a and F4b. It is "
             "NOT the banked `narrative` field, which additionally names the active "
             "node and the unsuppressed boundary; see the module docstring of "
             "`src/certificate.py`.")
    L.append("- F1's block is the only one whose length varies with the trace. It is "
             "raw signal, so it is longer than every other condition; that is the "
             "condition, not a formatting choice.\n")

    L.append(f"## Representative certificate — `{rep['certificate_id']}` "
             f"({rep['contract']})\n")
    L.append("A C1 counterexample, deliberately. F4a and F4b differ TEXTUALLY on all 20 "
             "certificates — `active_node` is always `CommitTurn` and `authorising_node` "
             "never is. What is confined to C1 is the INFORMATION: `authorising_node` "
             "takes two values within C1 (`Decelerate` 5, `HoldAtStopLine` 5) and exactly "
             "one within C2 (n=9) and within C3 (n=1), so outside C1 it is a redundant "
             "re-encoding of the contract, exactly as `active_node` is everywhere. "
             "H(authorising_node | contract) = 0.5000 bits, all of it inside C1; "
             "H(active_node | contract) = 0.000. See `src/blame.py`.\n")
    L.append("Feedback-block sizes, in bytes:\n")
    L.append("| Condition | bytes |")
    L.append("|---|---|")
    for c in CONDITIONS:
        L.append(f"| {c} | {rep['feedback_bytes'][c]} |")
    L.append("")

    L.append("### The block appended by F4a and F4b\n")
    for c in ("F4a", "F4b"):
        L.append(f"`{c}` appends, and nothing else:\n")
        L.append("```")
        L.append(rep["appended_blocks"][c].strip("\n"))
        L.append("```\n")

    L.append("## Unified diffs between every pair of conditions\n")
    L.append("Full prompts, `diff -u` with two lines of context. Every hunk lies inside "
             "the feedback region; no hunk touches the prefix or the suffix.\n")
    for x, y in itertools.combinations(CONDITIONS, 2):
        d = unified(rep["prompts"][x], rep["prompts"][y], x, y)
        lines = d.splitlines()
        truncated = ""
        if len(lines) > max_diff_lines:
            truncated = (f"\n... [{len(lines) - max_diff_lines} further diff lines "
                         f"omitted from this artifact only; the assertion above ran "
                         f"on the full text] ...")
            lines = lines[:max_diff_lines]
        L.append(f"### {x} → {y}\n")
        L.append("```diff")
        L.append("\n".join(lines) + truncated)
        L.append("```\n")

    L.append("## The template, verbatim\n")
    L.append("Prefix (sent as the cached system block; `src/llm.py` puts "
             "`cache_control` on it, so the invariant bulk is paid for once per "
             "campaign):\n")
    L.append("```")
    L.append(tpl.prefix.rstrip("\n"))
    L.append("```\n")
    L.append("Suffix (follows the feedback block in the user message):\n")
    L.append("```")
    L.append(tpl.suffix.strip("\n"))
    L.append("```")
    DOC.write_text("\n".join(L) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
