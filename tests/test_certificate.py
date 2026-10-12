#!/usr/bin/env python3
"""Tests for the certificate renderers.

The subject of these tests is not "does the string come out". It is the four
properties the ablation depends on, each of which is a way the experiment could
be silently voided:

  1. SCAFFOLDING BYTE-IDENTITY. Everything outside the feedback block is the
     same bytes in all five conditions, for all 20 certificates.
  2. DEGRADED CERTIFICATES. The 7 whose only boundary parameter is suppressed
     render with no boundary and set the flag that carries that into the
     limitations section.
  3. NO INFORMATION LEAKS DOWNWARD. F2 must not carry numbers that F3
     introduces (boundary thresholds, per-contract rho, minimal parameter
     values), and neither F2 nor F3 may name the blamed node.
  4. F4a/F4b ARE F3 PLUS EXACTLY ONE BLOCK.

Run:  .venv/bin/python tests/test_certificate.py
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from certificate import (  # noqa: E402
    CONDITIONS, Certificate, PromptTemplate, resolve_trace_path, template)

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}" + (f"  -- {detail}" if detail and not cond else ""))


def numbers(s: str) -> set[str]:
    """Numeric literals in a string, normalised so 1.50 and 1.5 compare equal."""
    out = set()
    for m in re.findall(r"-?\d+(?:\.\d+)?", s):
        try:
            out.add(f"{float(m):.6g}")
        except ValueError:
            pass
    return out


# ==========================================================================
def test_template_single_placeholder(certs):
    print("\n[template]")
    raw = (REPO / "data" / "prompts" / "patch_task.md").read_text()
    check("exactly one {feedback} placeholder in the template file",
          raw.count("{feedback}") == 1)
    check("no unsubstituted placeholders survive rendering",
          not re.search(r"\{(vocab|program|tau_yield|a_comfort|feedback)\}",
                        certs[0].prompt("F3")))
    tpl = template()
    check("prefix and suffix are both non-empty",
          len(tpl.prefix) > 0 and len(tpl.suffix) > 0,
          f"{len(tpl.prefix)}/{len(tpl.suffix)}")


def test_scaffolding_identical(certs):
    """Property 1. The one that voids the experiment if it fails."""
    print("\n[scaffolding byte-identity]")
    tpl = template()
    npre, nsuf = len(tpl.prefix), len(tpl.suffix)
    bad = []
    for c in certs:
        pre, suf = set(), set()
        for cond in CONDITIONS:
            p = c.prompt(cond)
            pre.add(p[:npre])
            suf.add(p[len(p) - nsuf:])
            if p[npre:len(p) - nsuf] != c.feedback(cond):
                bad.append(f"{c.certificate_id}/{cond} feedback region mismatch")
        if len(pre) != 1:
            bad.append(f"{c.certificate_id} prefix differs across conditions")
        if len(suf) != 1:
            bad.append(f"{c.certificate_id} suffix differs across conditions")
    check(f"prefix+suffix byte-identical across 5 conditions x {len(certs)} certificates",
          not bad, "; ".join(bad[:3]))

    # ... and identical across CERTIFICATES too, since the program is frozen.
    prefixes = {c.prompt("F3")[:npre] for c in certs}
    check("scaffolding is also identical across all certificates",
          len(prefixes) == 1, f"{len(prefixes)} distinct")


def test_degraded(certs):
    """Property 2."""
    print("\n[degraded certificates]")
    degraded = [c for c in certs if c.degraded_no_boundary]
    check("exactly 7 of 20 render without a boundary",
          len(degraded) == 7, f"got {len(degraded)}")
    check("every degraded certificate had a suppression recorded",
          all(c.boundary_suppressed for c in degraded))
    check("every degraded certificate DOES have a raw boundary on disk",
          all(c.boundary_report.strip() for c in degraded),
          "degradation must come from suppression, not from a failed search")
    for c in degraded:
        f3 = c.feedback("F3")
        check(f"{c.certificate_id}: boundary field present and marked not established",
              "boundary: not established for this counterexample" in f3)
        check(f"{c.certificate_id}: minimal parameter set still reported",
              "minimal_scenario: " in f3 and "no parameter" not in f3)
    non = [c for c in certs if not c.degraded_no_boundary]
    check("non-degraded certificates render their boundary verbatim",
          all(c.boundary_rendered.strip() in c.feedback("F3") for c in non))


def test_no_raw_boundary_anywhere(certs):
    """The suppressed boundary string must never reach a prompt, in any condition."""
    print("\n[suppressed boundary never rendered]")
    bad = []
    for c in certs:
        if not c.boundary_suppressed:
            continue
        raw = c.boundary_report.strip()
        for cond in ("F2", "F3", "F4a", "F4b"):
            if raw and raw in c.feedback(cond):
                bad.append(f"{c.certificate_id}/{cond}")
    check("the unsuppressed boundary string appears in no rendered feedback block",
          not bad, ", ".join(bad[:5]))

    # And the suppressed parameter's THRESHOLD must not leak as a bare number.
    leaks = []
    for c in certs:
        for entry in c.raw.get("boundary", []):
            if entry["parameter"] in c.boundary_suppressed:
                thr = f"{float(entry['threshold']):.6g}"
                for cond in ("F2", "F3", "F4a", "F4b"):
                    if thr in numbers(c.feedback(cond)):
                        leaks.append(f"{c.certificate_id}/{cond}:{thr}")
    check("no suppressed boundary threshold leaks as a bare number",
          not leaks, ", ".join(leaks[:5]))


def test_f2_introduces_no_f3_numbers(certs):
    """Property 3, quantitative half.

    Stated precisely, because "F2 contains no numbers that F3 introduces" is
    ambiguous on its face: F3 CONTAINS F2's narrative verbatim, so every number
    in F2 necessarily also appears in F3. What must not happen is the reverse
    leak -- F2 carrying a quantity whose source is F3's structured block.
    Tested as: numbers(F2) is a subset of numbers(F3), AND none of the
    specifically F3-introduced quantities (boundary thresholds, per-contract
    rho other than the argmin one, minimal parameter values) occur in F2.
    """
    print("\n[F2 carries no F3-introduced numbers]")
    subset_bad, leak_bad = [], []
    for c in certs:
        n2, n3 = numbers(c.feedback("F2")), numbers(c.feedback("F3"))
        if not n2 <= n3:
            subset_bad.append(f"{c.certificate_id}:{sorted(n2 - n3)}")
        introduced = set()
        for entry in c.raw.get("boundary", []):
            introduced.add(f"{float(entry['threshold']):.6g}")
        for k, v in c.per_contract.items():
            if k != c.contract:
                introduced.add(f"{float(v):.6g}")
        for k in c.kept_parameters:
            introduced.add(f"{float(c.minimal_params[k]):.6g}")
        # The narrative legitimately verbalises the VIOLATED contract's own
        # margin to 2 dp, and the achieved gap. Those are F2-level facts, so a
        # numeric coincidence with an F3 field is not a leak. Measured case:
        # CE003 has |rho_1| = 0.2961 -> "0.30 m" in the narrative, and rho_3
        # happens to be exactly 0.3. Excluded by value, not by certificate.
        legitimate = {f"{round(abs(float(c.rho)), 2):.6g}"}
        if c.achieved_gap_s is not None:
            legitimate.add(f"{round(float(c.achieved_gap_s), 2):.6g}")
        hit = (introduced - legitimate) & n2
        if hit:
            leak_bad.append(f"{c.certificate_id}:{sorted(hit)}")
    check("numbers(F2) subset of numbers(F3)", not subset_bad, "; ".join(subset_bad[:3]))
    check("no boundary threshold, non-argmin rho_i or minimal-parameter value in F2",
          not leak_bad, "; ".join(leak_bad[:3]))


def test_blame_only_in_f4(certs):
    """Property 3, blame half. The contrast F4 exists to make."""
    print("\n[blame appears only in F4]")
    bad = []
    for c in certs:
        for cond in ("F1", "F2", "F3"):
            if cond == "F1":
                continue        # the raw trace legitimately carries bt_node_* columns
            fb = c.feedback(cond)
            for field in (c.active_node, c.authorising_node):
                if not field:
                    continue
                node_type = field.split(":", 1)[0]
                if node_type in fb or field.split(":", 1)[1] in fb:
                    bad.append(f"{c.certificate_id}/{cond}:{node_type}")
    check("no blamed node type or path appears in F2 or F3", not bad, ", ".join(bad[:5]))

    check("every certificate has an active_node", all(c.active_node for c in certs))
    for c in certs:
        a = c.feedback("F4a")
        b = c.feedback("F4b")
        check(f"{c.certificate_id}: F4a names {c.active_node.split(':')[0]}",
              f"blame_node: {c.active_node.split(':')[0]} " in a)
        if c.authorising_node:
            check(f"{c.certificate_id}: F4b names {c.authorising_node.split(':')[0]}",
                  f"blame_node: {c.authorising_node.split(':')[0]} " in b)


def test_f4_is_f3_plus_one_block(certs):
    """Property 4."""
    print("\n[F4a/F4b = F3 + exactly one block]")
    bad = []
    keys = {"blame_definition:", "blame_node:", "blame_meaning:"}
    for c in certs:
        f3 = c.feedback("F3")
        for cond in ("F4a", "F4b"):
            fb = c.feedback(cond)
            if not fb.startswith(f3):
                bad.append(f"{c.certificate_id}/{cond} is not an extension of F3")
                continue
            added = fb[len(f3):].strip("\n")
            lines = added.splitlines()
            if len(lines) != 3 or {l.split(" ", 1)[0] for l in lines} != keys:
                bad.append(f"{c.certificate_id}/{cond} added {len(lines)} lines")
    check("F4a and F4b each append exactly the 3-line blame block, nothing else",
          not bad, "; ".join(bad[:3]))

    # F4a is the NEGATIVE CONTROL: its field is provably constant here.
    nodes = {c.active_node for c in certs}
    check("active_node is constant over the corpus (F4a is a negative control)",
          len(nodes) == 1, f"{nodes}")
    auth = {c.authorising_node for c in certs}
    check("authorising_node takes more than one value (F4b is not)",
          len(auth) > 1, f"{auth}")
    # F4a vs F4b, stated correctly. They differ TEXTUALLY on every certificate,
    # because active_node is always CommitTurn and authorising_node never is.
    # What is confined to C1 is the INFORMATION: authorising_node is constant
    # within C2 and within C3, so on those it is a redundant re-encoding of the
    # contract, exactly as active_node is everywhere.
    check("F4a and F4b are textually different on every certificate",
          all(c.feedback("F4a") != c.feedback("F4b") for c in certs))
    by_contract = {}
    for c in certs:
        by_contract.setdefault(c.contract, set()).add(c.authorising_node)
    check("authorising_node is multi-valued only within C1",
          {k: len(v) for k, v in by_contract.items()} == {"C1": 2, "C2": 1, "C3": 1},
          str({k: len(v) for k, v in by_contract.items()}))


def test_narrative_recomposition(certs):
    print("\n[narrative re-composition]")
    # The leak evidence moved. Commit 3d0fed1 regenerated the banked `narrative`
    # field and kept the original verbatim as `narrative_pre_3c226ee`, so the
    # assertion that the ORIGINAL leaked now has to read the archived copy.
    # Keeping it (rather than deleting it) is the point: it is the standing
    # evidence for why the re-composition exists, and if the archive were ever
    # dropped the test would fail loudly instead of silently passing.
    pre = [c.raw.get("narrative_pre_3c226ee") for c in certs]
    check("the pre-regeneration narrative is archived on every certificate",
          all(isinstance(x, str) and x for x in pre))
    check("the ARCHIVED narrative DOES leak the active node (why we re-compose)",
          all("active behaviour" in (x or "") for x in pre))
    check("the archived narrative also leaks the unsuppressed boundary "
          "on the suppressed certificates",
          all(c.boundary_report.strip(" .") in (c.raw.get("narrative_pre_3c226ee") or "")
              for c in certs if c.boundary_suppressed))
    check("the re-composed narrative does not",
          all("active behaviour" not in c.narrative_rendered for c in certs))
    # PIN THE CORPUS TO WHAT THE PROMPTS ACTUALLY USE. The regenerated field on
    # disk and the string the renderer builds must be the same bytes; if a
    # future regeneration drifts from `narrative_rendered`, the paper would
    # describe a corpus the prompts do not match.
    drift = [c.certificate_id for c in certs
             if c.narrative_banked != c.narrative_rendered]
    check("banked `narrative` == `narrative_rendered` on all 20",
          not drift, ", ".join(drift[:5]))
    check("every certificate records WHY it was regenerated",
          all(c.raw.get("narrative_regenerated") for c in certs))
    check("the re-composed narrative is byte-identical in F2, F3, F4a, F4b",
          all(all(f"narrative: {c.narrative_rendered}" in c.feedback(x)
                  for x in ("F2", "F3", "F4a", "F4b")) for c in certs))


def test_f1_window(certs):
    print("\n[F1 excerpt]")
    rows = []
    for c in certs:
        csv, lo, hi, n = c.trace_excerpt(10)
        rows.append(hi - lo + 1)
        header = csv.split("\n", 1)[0]
        if c is certs[0]:
            check("F1 keeps every logged column", len(header.split(",")) == 45,
                  f"{len(header.split(','))} columns")
    check("the F1 window is a constant row count across certificates",
          len(set(rows)) == 1, f"row counts {sorted(set(rows))}")
    check("the window contains the argmin row",
          all(c.trace_excerpt(10)[1] <= c.argmin_index <= c.trace_excerpt(10)[2]
              for c in certs))


def test_trace_resolution(certs):
    """The certificates store absolute paths from the original machine and are
    kept byte-identical, so the trace is resolved by basename under
    data/certificates/traces/ first, and only then at the stored path."""
    print("\n[trace path resolution]")
    import tempfile
    trace_dir = REPO / "data" / "certificates" / "traces"
    check("every certificate's trace resolves to the copy inside the repo",
          all(c.trace_path == trace_dir / pathlib.PurePosixPath(
              c.trace_path_stored).name for c in certs),
          ", ".join(c.certificate_id for c in certs
                    if not c.trace_path.is_relative_to(trace_dir))[:200])
    check("no stored trace_path has been rewritten (all still absolute)",
          all(pathlib.PurePosixPath(c.trace_path_stored).is_absolute()
              for c in certs))
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        local, elsewhere = tmp / "local", tmp / "elsewhere"
        local.mkdir()
        elsewhere.mkdir()
        stored = elsewhere / "t.parquet"
        stored.write_bytes(b"stored")
        check("falls back to the stored path when no repo copy exists",
              resolve_trace_path(stored, trace_dir=local) == stored)
        (local / "t.parquet").write_bytes(b"local")
        check("prefers the repo copy when both exist",
              resolve_trace_path(stored, trace_dir=local) == local / "t.parquet")
        try:
            resolve_trace_path(elsewhere / "missing.parquet", trace_dir=local)
            check("raises FileNotFoundError when neither exists", False)
        except FileNotFoundError:
            check("raises FileNotFoundError when neither exists", True)


def test_bad_condition_raises(certs):
    print("\n[misuse]")
    try:
        certs[0].feedback("F4")
        check("an unknown condition name raises", False, "F4 was accepted")
    except ValueError:
        check("an unknown condition name raises", True)
    try:
        PromptTemplate(REPO / "data" / "scenarios" / "baseline_program.bt")
        check("a template without the placeholder raises", False)
    except ValueError:
        check("a template without the placeholder raises", True)


def main() -> int:
    certs = Certificate.load_all()
    print(f"loaded {len(certs)} certificates")
    test_template_single_placeholder(certs)
    test_scaffolding_identical(certs)
    test_degraded(certs)
    test_no_raw_boundary_anywhere(certs)
    test_f2_introduces_no_f3_numbers(certs)
    test_blame_only_in_f4(certs)
    test_f4_is_f3_plus_one_block(certs)
    test_narrative_recomposition(certs)
    test_f1_window(certs)
    test_trace_resolution(certs)
    test_bad_condition_raises(certs)
    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} pass")
    if FAIL:
        print("FAILED:")
        for f in FAIL:
            print("  -", f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
