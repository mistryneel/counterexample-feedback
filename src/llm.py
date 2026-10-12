"""Anthropic client, with every call logged to disk.

Project convention: "Log every LLM prompt and response to disk, with pinned
model version and temperature." Two notes on that:

  * The MODEL VERSION logged is `response.model` -- what the server actually
    served -- not the string that was requested. Those can differ, and the
    reproducibility claim depends on the former.

  * THERE IS NO TEMPERATURE. `temperature`, `top_p` and `top_k` are removed on
    Claude Opus 5 and return a 400 if sent. The sampling knob is
    `output_config.effort`, so effort is logged in temperature's place. Any
    document in this repo that says "pinned model version and temperature"
    should be read as "pinned model version and effort".

Raw logs go to logs/llm_raw/ (git-ignored, can be large). Every call also
appends a compact record to logs/llm_index.jsonl so a campaign can be audited
without reading the payloads.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import subprocess
import time

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "logs" / "llm_raw"
INDEX = REPO_ROOT / "logs" / "llm_index.jsonl"

MODEL = "claude-opus-5"
EFFORT = "high"


def load_env(path: str | pathlib.Path | None = None) -> None:
    """Read KEY=VALUE lines from .env into os.environ without overwriting."""
    p = pathlib.Path(path) if path else REPO_ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()
    except Exception:
        return "unknown"


def client():
    load_env()
    import anthropic
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Put it in .env (git-ignored) -- see "
            "README.md. Identity-linked keys ALSO need "
            "ANTHROPIC_WORKSPACE_ID or every request returns 400.")
    # The SDK reads ANTHROPIC_WORKSPACE_ID from the environment itself.
    return anthropic.Anthropic()


def call(prompt: str, *, system: str | None = None, tag: str = "call",
         model: str = MODEL, effort: str = EFFORT, max_tokens: int = 48000,
         cache_system: bool = True) -> dict:
    """One Messages request. Returns a dict; logs prompt and response to disk.

    The system block is cached: across a campaign the vocabulary, grammar and
    contract description are byte-identical on every call, and only the
    per-counterexample feedback varies. Caching that prefix is the difference
    between paying full price 240 times and paying it once.
    """
    c = client()
    kwargs: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "output_config": {"effort": effort},
        "messages": [{"role": "user", "content": prompt}],
    }
    if system is not None:
        blk = {"type": "text", "text": system}
        if cache_system:
            blk["cache_control"] = {"type": "ephemeral"}
        kwargs["system"] = [blk]

    # STREAM. Adaptive thinking at effort=high spends most of the output
    # budget on reasoning: measured across 12 synthesis calls, output ran
    # 3.6k-16k tokens and 2 of 12 hit a 16k cap and were TRUNCATED mid-program.
    # A truncated response is a harness failure, not a model failure, and must
    # never be counted as malformed output -- different mechanism, different
    # meaning, and hard rule 3's logic applies to this boundary too. The SDK
    # requires streaming for large max_tokens or the HTTP request times out.
    t0 = time.perf_counter()
    with c.messages.stream(**kwargs) as stream:
        resp = stream.get_final_message()
    elapsed = time.perf_counter() - t0

    text = "".join(b.text for b in resp.content if b.type == "text")
    u = resp.usage
    digest = hashlib.sha256((system or "" + prompt).encode()).hexdigest()[:16]
    call_id = f"{tag}_{digest}_{int(t0)}"

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    (RAW_DIR / f"{call_id}.json").write_text(json.dumps({
        "call_id": call_id, "tag": tag,
        "model_requested": model, "model_served": resp.model,
        "effort": effort, "max_tokens": max_tokens,
        "system": system, "prompt": prompt, "response_text": text,
        "stop_reason": resp.stop_reason,
        "usage": u.model_dump() if hasattr(u, "model_dump") else dict(u),
        "git_commit": git_commit(),
    }, indent=2, default=str))

    if resp.stop_reason == "max_tokens":
        print(f"  !! {tag}: TRUNCATED at max_tokens={max_tokens}. "
              "Raise it; do NOT count this as malformed output.")

    rec = {
        "call_id": call_id, "tag": tag,
        "model_served": resp.model, "effort": effort,
        "stop_reason": resp.stop_reason,
        "tokens_prompt": u.input_tokens,
        "tokens_completion": u.output_tokens,
        "cache_read": getattr(u, "cache_read_input_tokens", 0) or 0,
        "cache_write": getattr(u, "cache_creation_input_tokens", 0) or 0,
        "elapsed_s": round(elapsed, 2),
        "git_commit": git_commit(),
        "raw_path": str((RAW_DIR / f"{call_id}.json").relative_to(REPO_ROOT)),
    }
    INDEX.parent.mkdir(parents=True, exist_ok=True)
    with INDEX.open("a") as fh:
        fh.write(json.dumps(rec) + "\n")
        fh.flush()
        os.fsync(fh.fileno())

    return {"text": text, "usage": rec, "response": resp}


def cost_usd(prompt_tokens: int, completion_tokens: int,
             cache_read: int = 0, model: str = MODEL) -> float:
    """Rates as of 2026-06-24. Cache reads bill at ~0.1x input."""
    rates = {"claude-opus-5": (5.00, 25.00), "claude-sonnet-5": (2.00, 10.00),
             "claude-haiku-4-5": (1.00, 5.00)}
    pin, pout = rates.get(model, rates["claude-opus-5"])
    return ((prompt_tokens / 1e6) * pin
            + (cache_read / 1e6) * pin * 0.1
            + (completion_tokens / 1e6) * pout)
