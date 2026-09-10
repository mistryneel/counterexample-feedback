#!/usr/bin/env python3
"""ONE call per condition: does a rendered prompt come back as parseable .bt?

Five calls, not a campaign. This is a harness check, not a result: n = 1 per
condition says nothing about fix rates and no number from it may be reported as
one. What it does establish, before 300 calls are spent, is that each rendering
produces a prompt the model answers with a program the validator accepts.

Three outcomes are counted SEPARATELY and must never be pooled (project
rule 3, and the truncation trap):

  ok         a fenced program that parses and validates
  malformed  a complete response whose program does not parse or validate
  truncated  stop_reason == "max_tokens" -- a HARNESS failure, says nothing
             about whether the model can write valid DSL

    .venv/bin/python scripts/smoke_render.py
    .venv/bin/python scripts/smoke_render.py --cert CE003 --effort high
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import llm  # noqa: E402
from certificate import CONDITIONS, Certificate  # noqa: E402
from program_parser import parse_and_validate  # noqa: E402
from synthesize_baseline import extract_program  # noqa: E402

OUT = REPO / "data" / "results" / "renderer_smoke.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cert", default="CE003",
                    help="C1 by default: the only contract where F4a and F4b differ")
    ap.add_argument("--effort", default=llm.EFFORT)
    ap.add_argument("--max-tokens", type=int, default=48000)
    a = ap.parse_args()

    cert = next(c for c in Certificate.load_all()
                if c.certificate_id.startswith(a.cert))
    print(f"certificate {cert.certificate_id} ({cert.contract}), "
          f"model {llm.MODEL}, effort {a.effort}\n")

    rows = []
    for cond in CONDITIONS:
        system, user = cert.prompt_parts(cond)
        r = llm.call(user, system=system, tag=f"smoke_{cond}",
                     effort=a.effort, max_tokens=a.max_tokens)
        truncated = r["usage"]["stop_reason"] == "max_tokens"
        src = extract_program(r["text"])
        try:
            _, vr = parse_and_validate(src)
            parsed, errors = vr.ok, list(vr.errors)
        except Exception as e:                    # ParseError and anything else
            parsed, errors = False, [f"{type(e).__name__}: {e}"]

        outcome = "truncated" if truncated else ("ok" if parsed else "malformed")
        rows.append({
            "condition": cond, "outcome": outcome,
            "parsed_and_valid": bool(parsed),
            "truncated_at_max_tokens": truncated,
            "validator_errors": errors,
            "program_lines": len(src.strip().splitlines()),
            "identical_to_baseline": src.strip() == (
                REPO / "data/scenarios/baseline_program.bt").read_text().strip(),
            "tokens_prompt": r["usage"]["tokens_prompt"],
            "tokens_completion": r["usage"]["tokens_completion"],
            "cache_read": r["usage"]["cache_read"],
            "cache_write": r["usage"]["cache_write"],
            "elapsed_s": r["usage"]["elapsed_s"],
            "call_id": r["usage"]["call_id"],
            "raw_path": r["usage"]["raw_path"],
            "model_served": r["usage"]["model_served"],
            "effort": a.effort,
        })
        print(f"  {cond:<4} {outcome:<10} lines={rows[-1]['program_lines']:>3}  "
              f"prompt={rows[-1]['tokens_prompt']:>6} "
              f"completion={rows[-1]['tokens_completion']:>6} "
              f"cache_read={rows[-1]['cache_read']:>6} "
              f"{rows[-1]['elapsed_s']:>6.1f}s"
              + ("  " + "; ".join(errors[:2]) if errors else ""))

    n_ok = sum(r["outcome"] == "ok" for r in rows)
    n_mal = sum(r["outcome"] == "malformed" for r in rows)
    n_tr = sum(r["outcome"] == "truncated" for r in rows)
    cost = sum(llm.cost_usd(r["tokens_prompt"], r["tokens_completion"],
                            r["cache_read"]) for r in rows)
    print(f"\nok {n_ok}/5   malformed {n_mal}/5   truncated {n_tr}/5   "
          f"(counted separately, never pooled)")
    print(f"cost of this smoke test: ${cost:.2f}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "certificate_id": cert.certificate_id, "contract": cert.contract,
        "model": llm.MODEL, "effort": a.effort, "max_tokens": a.max_tokens,
        "git_commit": llm.git_commit(),
        "n_ok": n_ok, "n_malformed": n_mal, "n_truncated": n_tr,
        "cost_usd": round(cost, 4),
        "results": rows,
    }, indent=2))
    print(f"wrote {OUT.relative_to(REPO)}")
    return 0 if n_tr == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
