#!/usr/bin/env python3
"""Check every per-attempt record against the binding per-attempt log schema.

"Several metrics are permanently unrecoverable if these fields are not written
at the time of the run" -- so this runs on the DRY RUN, before 300 attempts,
and again on the finished campaign. Inspecting five records by eye is how a
missing field survives to attempt 250.

Fields are checked for PRESENCE and for PLAUSIBILITY, and the two are reported
separately: a field that is present but null is a different problem from a
field that is absent, and for some fields null is the correct value.

    .venv/bin/python scripts/check_attempts_schema.py data/results/dryrun_attempts.jsonl
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent

# Exactly the binding per-attempt schema, plus the two renames it mandates
# elsewhere (`temperature` -> `effort` on Opus 5) and the fields the campaign
# adds for traps the schema predates.
REQUIRED = [
    "attempt_id", "condition", "seed", "certificate_id", "git_commit", "timestamp",
    "model_id", "effort", "temperature",
    "prompt_path", "response_path",
    "tokens_prompt", "tokens_completion",
    "program_version_before", "program_version_after",
    "bt_source_before", "bt_source_after",
    "resolved",
    "validator_result", "dsl_expressible",
    "rho_before", "rho_after",
    "rho1_before", "rho2_before", "rho5_before",
    "rho1_after", "rho2_after", "rho5_after",
    "regression_failures",
    "ted_from_previous", "ted_from_original", "patch_type",
    "rollouts_falsification", "rollouts_minimization", "rollouts_boundary",
    "rollouts_regression", "rollouts_evaluation",
    # Added by this campaign, all for reasons recorded in the module docstrings.
    "outcome", "evaluated", "held_out_scvr", "searched_scvr",
    "generalization_gap", "icr", "pcr", "c4_binding_after",
    # Resolution-by-refusal, added after the dry run found that BOTH of its
    # resolutions were the ego declining to enter the junction. Permanently
    # unrecoverable if not written at the time of the run: `ce_phases_reached`
    # is not derivable from anything else on the record.
    "ce_phases_reached", "ce_vacuous_contracts", "ce_completed",
    "ce_entered_conflict_zone", "resolved_by_refusal", "resolved_and_completed",
]

# Fields whose value must be non-null on an `ok`, evaluated attempt.
NONNULL_WHEN_EVALUATED = [
    "rho_after", "rho1_after", "rho2_after", "rho5_after",
    "regression_failures", "held_out_scvr", "searched_scvr",
    "generalization_gap", "icr", "pcr",
    "ted_from_original", "patch_type", "bt_source_after",
]

# Fields that must be null ALWAYS, and where a value is the bug.
MUST_BE_NULL = {
    # There is no temperature on Claude Opus 5; sending one is a 400.
    "temperature": "Opus 5 has no temperature; the knob is output_config.effort",
    # Set by manual review during analysis, never automatically.
    "dsl_expressible": "set by manual review during analysis, not by the agent",
}

FORBIDDEN = {
    # A permanently-false column implies a component that does not exist.
    "shield_activations": "the shield was removed in full (spec v2 §8)",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?",
                    default=str(REPO / "data/results/attempts.jsonl"))
    a = ap.parse_args()
    p = pathlib.Path(a.path).resolve()
    if not p.exists():
        print(f"no such file: {p}")
        return 1
    rows = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    print(f"{p.relative_to(REPO)}: {len(rows)} records\n")

    missing, nulls, wrong, forbidden = {}, {}, {}, {}
    for r in rows:
        aid = r.get("attempt_id", "<no id>")
        for f in REQUIRED:
            if f not in r:
                missing.setdefault(f, []).append(aid)
        for f, why in FORBIDDEN.items():
            if f in r:
                forbidden.setdefault(f, []).append(aid)
        for f, why in MUST_BE_NULL.items():
            if r.get(f) is not None:
                wrong.setdefault(f, []).append(aid)
        if r.get("evaluated") and r.get("outcome") == "ok":
            for f in NONNULL_WHEN_EVALUATED:
                if r.get(f) is None:
                    nulls.setdefault(f, []).append(aid)

    def report(title, d, detail=""):
        if not d:
            print(f"  ok   {title}")
            return 0
        print(f"  FAIL {title}{detail}")
        for f, ids in sorted(d.items()):
            print(f"        {f}: {len(ids)} record(s), e.g. {ids[0]}")
        return 1

    bad = 0
    bad |= report(f"all {len(REQUIRED)} schema fields present on every record", missing)
    bad |= report("fields that must be null are null", wrong)
    bad |= report("no forbidden fields", forbidden)
    bad |= report("evaluated attempts have no null measurements", nulls)

    # bt_source is FULL TEXT, not a diff. Checked structurally.
    diffish = [r["attempt_id"] for r in rows
               if isinstance(r.get("bt_source_after"), str)
               and (r["bt_source_after"].lstrip().startswith(("@@", "---", "+++"))
                    or len(r["bt_source_after"].splitlines()) < 10)]
    bad |= report("bt_source_after is full program text, not a diff",
                  {"bt_source_after": diffish} if diffish else {})

    # Outcome buckets must be disjoint and exhaustive.
    from collections import Counter
    oc = Counter(r.get("outcome") for r in rows)
    print(f"\n  outcomes: {dict(oc)}")
    unknown = set(oc) - {"ok", "malformed", "truncated", "api_error"}
    bad |= report("outcome values are one of ok/malformed/truncated/api_error",
                  {"outcome": sorted(map(str, unknown))} if unknown else {})
    pooled = [r["attempt_id"] for r in rows
              if r.get("outcome") != "ok" and r.get("evaluated")]
    bad |= report("no non-ok attempt was evaluated (buckets not pooled)",
                  {"evaluated": pooled} if pooled else {})
    ok_unevaluated = [r["attempt_id"] for r in rows
                      if r.get("outcome") == "ok" and not r.get("evaluated")]
    bad |= report("every ok attempt was evaluated",
                  {"evaluated": ok_unevaluated} if ok_unevaluated else {})

    # Not a schema fault -- a WARNING about what the headline number contains.
    ev = [r for r in rows if r.get("evaluated")]
    res = [r for r in ev if r.get("resolved")]
    ref = [r for r in res if r.get("resolved_by_refusal")]
    if res:
        print(f"\n  resolutions: {len(res)}/{len(ev)} evaluated; "
              f"{len(ref)} of those are RESOLUTION BY REFUSAL "
              f"(rho >= 0 because the ego never entered the junction)")
        if ref:
            print(f"        e.g. {ref[0]['attempt_id']}")

    print(f"\n{'SCHEMA CHECK PASSED' if not bad else 'SCHEMA CHECK FAILED'}")
    return bad


if __name__ == "__main__":
    raise SystemExit(main())
