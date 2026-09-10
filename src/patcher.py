"""The LLM patching harness: one repair attempt, rendered, called, classified.

One attempt = one (condition, certificate, replicate). This module does the
LLM half and the bookkeeping; `src/evaluate.py` does the simulation half.

--------------------------------------------------------------------------
THREE OUTCOME BUCKETS, NEVER TWO, AND NEVER POOLED

    truncated   stop_reason == "max_tokens". A HARNESS failure. It says
                nothing about whether the model can write valid DSL, and
                counting it as malformed would attribute a budget mistake of
                mine to the model.
    malformed   a complete response whose program does not parse or does not
                validate. A MODEL failure.
    ok          parsed and validated; goes on to evaluation.

Project rule 3 is about not pooling malformed with unsafe; the same
logic applies one step earlier, at truncated vs malformed. This project has
already made the pooling mistake once.

A fourth, separate outcome exists and is also never pooled:

    api_error   the call itself failed after retries. Not a model failure and
                not a harness classification -- the attempt simply has no
                response, and it must not be silently scored as unresolved.

--------------------------------------------------------------------------
WHAT "SEED" MEANS HERE, STATED HONESTLY

There is no sampling seed on the Claude API, and there is no `temperature` on
Claude Opus 5 at all -- it is removed and sending it is a 400 (the knob is
`output_config.effort`). So `seed` in this campaign is a REPLICATE INDEX, not a
controlled random seed: the three replicates send a BYTE-IDENTICAL prompt and
differ only through the model's own sampling nondeterminism, which is not
seeded, not reproducible, and not under our control.

That is a real limitation and it is recorded rather than dressed up. The
campaign measures how many replicates returned identical program text, which
is the only honest way to say how much independent information three
replicates carry.

--------------------------------------------------------------------------
`dsl_expressible` IS NOT SET HERE. Project rule: "DSL expressiveness failures are
set by manual review during analysis, not by the agent." The distinction being
drawn -- "the model reasoned badly" versus "the DSL could not say it" --
requires judgement. The field is written as null and left for a human.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

import llm  # noqa: E402
import ted as ted_mod  # noqa: E402
from certificate import Certificate  # noqa: E402
from program_parser import parse_and_validate  # noqa: E402

PROMPT_DIR = REPO_ROOT / "logs" / "campaign" / "prompts"
RESPONSE_DIR = REPO_ROOT / "logs" / "campaign" / "responses"
PROGRAM_DIR = REPO_ROOT / "data" / "results" / "patched_programs"
BASELINE = REPO_ROOT / "data" / "scenarios" / "baseline_program.bt"

OUTCOMES = ("ok", "malformed", "truncated", "api_error")


def utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def sha16(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def attempt_id(condition: str, certificate_id: str, seed: int) -> str:
    return f"{condition}__{certificate_id}__s{seed}"


def extract_program(text: str) -> str:
    """Pull the `.bt` source out of a response.

    Shared with scripts/synthesize_baseline.py by intent, reimplemented here so
    the campaign does not import a script. Kept byte-compatible: any change
    would make patched programs differ from synthesised ones for a reason
    unrelated to the model.
    """
    if "```" in text:
        parts = text.split("```")
        if len(parts) < 2:
            return text.strip() + "\n"
        body = parts[1]
        lines = body.splitlines()
        if lines and lines[0].strip() and "(" not in lines[0]:
            lines = lines[1:]
        return "\n".join(lines).strip() + "\n"
    return text.strip() + "\n"


def generate(cert: Certificate, condition: str, seed: int, *,
             effort: str = llm.EFFORT, max_tokens: int = 48000,
             model: str = llm.MODEL) -> dict:
    """Render, call, extract, validate, classify. Never raises.

    Returns the LLM half of the per-attempt record. Evaluation fields are added
    later by `scripts/run_e1.py` once the patch has been simulated.
    """
    aid = attempt_id(condition, cert.certificate_id, seed)
    system, user = cert.prompt_parts(condition)
    before = BASELINE.read_text()

    for d in (PROMPT_DIR, RESPONSE_DIR, PROGRAM_DIR):
        d.mkdir(parents=True, exist_ok=True)
    # The rendered prompt goes to disk VERBATIM, both halves, before the call.
    # If the call dies we still know exactly what was asked.
    prompt_path = PROMPT_DIR / f"{aid}.txt"
    prompt_path.write_text(system + "\n\n===== USER =====\n\n" + user)

    rec: dict = {
        "attempt_id": aid,
        "condition": condition,
        "seed": seed,
        "seed_is_replicate_index": True,
        "certificate_id": cert.certificate_id,
        "violated_contract": cert.contract,
        "git_commit": llm.git_commit(),
        "timestamp": utcnow(),
        "model_id_requested": model,
        "effort": effort,           # there is no temperature on Opus 5
        "temperature": None,
        "max_tokens": max_tokens,
        "prompt_path": str(prompt_path.relative_to(REPO_ROOT)),
        "prompt_sha256_16": sha16(system + user),
        "feedback_sha256_16": sha16(cert.feedback(condition)),
        "bt_source_before": before,          # FULL TEXT, never a diff
        "program_version_before": sha16(before),
    }

    try:
        r = llm.call(user, system=system, tag=f"e1_{condition}",
                     model=model, effort=effort, max_tokens=max_tokens)
    except Exception as exc:
        rec.update({
            "outcome": "api_error",
            "api_error": f"{type(exc).__name__}: {exc}",
            "response_path": None, "model_id": None,
            "tokens_prompt": None, "tokens_completion": None,
            "cache_read": None, "cache_write": None,
            "stop_reason": None, "validator_result": None,
            "dsl_expressible": None,
            "bt_source_after": None, "program_version_after": None,
            "ted_from_previous": None, "ted_from_original": None,
            "patch_type": None, "resolved": False,
        })
        return rec

    u = r["usage"]
    response_path = RESPONSE_DIR / f"{aid}.txt"
    response_path.write_text(r["text"])

    truncated = u["stop_reason"] == "max_tokens"
    src = extract_program(r["text"])
    _, vr = parse_and_validate(src)
    validator_ok = bool(vr.ok)

    # ORDER MATTERS. Truncation is checked FIRST: a response cut off at
    # max_tokens will usually also fail the validator, and classifying it as
    # malformed would blame the model for a budget I set.
    outcome = "truncated" if truncated else ("ok" if validator_ok else "malformed")

    rec.update({
        "outcome": outcome,
        "response_path": str(response_path.relative_to(REPO_ROOT)),
        "model_id": u["model_served"],       # as SERVED, not as requested
        "tokens_prompt": u["tokens_prompt"],
        "tokens_completion": u["tokens_completion"],
        "cache_read": u["cache_read"],
        "cache_write": u["cache_write"],
        "elapsed_s": u["elapsed_s"],
        "call_id": u["call_id"],
        "stop_reason": u["stop_reason"],
        "validator_result": ("ok" if validator_ok else "; ".join(vr.errors[:6])),
        "validator_ok": validator_ok,
        # Manual review during analysis. Never set by the agent.
        "dsl_expressible": None,
        "bt_source_after": src,              # FULL TEXT, never a diff
        "program_version_after": sha16(src),
        "response_identical_to_baseline": src.strip() == before.strip(),
    })

    # TED is computed from source and recomputed during analysis, so a bug here
    # costs a re-analysis rather than a re-run. In E1 there is exactly ONE
    # round, so `previous` and `original` are the same program by construction;
    # both are written because the schema has both and E2 would make them differ.
    if outcome == "ok":
        rec["ted_from_previous"] = ted_mod.ted_from_source(before, src)
        rec["ted_from_original"] = rec["ted_from_previous"]
        rec["patch_type"] = ted_mod.classify_patch(before, src)
        path = PROGRAM_DIR / f"{aid}.bt"
        path.write_text(src)
        rec["patched_program_path"] = str(path.relative_to(REPO_ROOT))
    else:
        rec["ted_from_previous"] = None
        rec["ted_from_original"] = None
        rec["patch_type"] = None
        rec["patched_program_path"] = None
        rec["resolved"] = False       # nothing was evaluated; not a resolution

    return rec


def certificate_fields(cert: Certificate) -> dict:
    """The pre-patch half of the record, read from the banked certificate.

    Not recomputed. These are the numbers the counterexample was certified
    with, and re-deriving them here would risk two different values of
    `rho_before` in the same project.
    """
    out = {
        "rho_before": cert.rho,
        "degraded_no_boundary": cert.degraded_no_boundary,
        "boundary_rendered": cert.boundary_rendered,
        "active_node": cert.active_node,
        "authorising_node": cert.authorising_node,
        "information_duplicate_of": cert.raw.get("information_duplicate_of"),
    }
    for c in ("C1", "C2", "C3", "C4", "C5"):
        out[f"rho{c[1]}_before"] = cert.raw.get(f"rho{c[1]}")
    # Corpus-construction cost, inherited by every attempt on this
    # counterexample. E1 amortises it across all five conditions -- F1 and F2
    # pay identical minimization and boundary cost, they simply do not render
    # those fields. Carried on the record so the cost-asymmetry limitation can
    # be quantified without re-reading the certificates.
    for k in ("rollouts_falsification", "rollouts_minimization",
              "rollouts_boundary", "rollouts_avoidability"):
        out[k] = cert.raw.get(k, 0)
    return out
