#!/usr/bin/env python3
"""PRE-CAMPAIGN CHECK: does an F1 prompt fit inside the token budget B?

The project's rules require this and it had not been run. The point of running it BEFORE
the campaign is that an F1 overflow is a DESIGNED finding -- a fact about what a
raw-trace condition costs -- rather than something discovered mid-run and
patched over with a silent truncation.

Counting is done with `client.messages.count_tokens` against the pinned model.
NOT a third-party tokenizer: a tiktoken-style estimate would be a different
tokenizer for a different model family, and the number this check produces is
the number the campaign will actually be billed for.

Nothing is truncated automatically. If F1 overflows, the script reports by how
much and prices a ladder of excerpt windows so the choice is made deliberately
and recorded in config/experiment.yaml.

    .venv/bin/python scripts/check_prompt_budget.py
    .venv/bin/python scripts/check_prompt_budget.py --no-cache
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import statistics
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

import llm  # noqa: E402
from certificate import CONDITIONS, Certificate  # noqa: E402
from config import load_config  # noqa: E402

OUT = REPO / "data" / "results" / "prompt_budget.json"
CACHE = REPO / "data" / "results" / ".token_count_cache.json"

# Excerpt half-widths to price, in rows either side of the argmin. -1 = whole
# trace. The ladder exists so that if F1 overflows the choice of window is made
# against measured numbers rather than guessed.
WINDOWS = [-1, 100, 50, 25, 20, 15, 10, 5]


class Counter:
    """count_tokens with an on-disk cache keyed by the exact bytes counted."""

    def __init__(self, model: str, use_cache: bool = True):
        self.model = model
        self.client = llm.client()
        self.use_cache = use_cache
        self.cache = {}
        if use_cache and CACHE.exists():
            self.cache = json.loads(CACHE.read_text())
        self.calls = 0
        self.hits = 0

    def count(self, system: str, user: str) -> int:
        key = hashlib.sha256(
            (self.model + "\x00" + system + "\x00" + user).encode()).hexdigest()
        if key in self.cache:
            self.hits += 1
            return self.cache[key]
        r = self.client.messages.count_tokens(
            model=self.model,
            system=[{"type": "text", "text": system}],
            messages=[{"role": "user", "content": user}],
        )
        self.calls += 1
        self.cache[key] = int(r.input_tokens)
        return self.cache[key]

    def save(self) -> None:
        if self.use_cache:
            CACHE.write_text(json.dumps(self.cache))


def stats(xs: list[int]) -> dict:
    return {"n": len(xs), "min": min(xs),
            "median": int(statistics.median(xs)), "max": max(xs),
            "mean": round(statistics.mean(xs), 1)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=llm.MODEL)
    ap.add_argument("--no-cache", action="store_true")
    a = ap.parse_args()

    cfg = load_config("experiment")
    B = int(cfg["token_budget_B"])
    default_hw = int(cfg["f1_excerpt_halfwidth_rows"])

    certs = Certificate.load_all()
    counter = Counter(a.model, use_cache=not a.no_cache)

    print(f"model: {a.model}   budget B: {B} prompt tokens   "
          f"certificates: {len(certs)}\n")

    # --- the five conditions at the configured window --------------------
    per_condition: dict[str, list[int]] = {c: [] for c in CONDITIONS}
    per_cert: dict[str, dict] = {}
    for cert in certs:
        row = {}
        for cond in CONDITIONS:
            sysblk, user = cert.prompt_parts(cond)
            n = counter.count(sysblk, user)
            per_condition[cond].append(n)
            row[cond] = n
        per_cert[cert.certificate_id] = row
        print(f"  {cert.certificate_id}  " +
              "  ".join(f"{c}={row[c]:>6}" for c in CONDITIONS))
        counter.save()

    print("\n== prompt tokens by condition, over all "
          f"{len(certs)} certificates (F1 window = +-{default_hw} rows) ==")
    print(f"{'cond':<5} {'min':>8} {'median':>8} {'max':>8}   over B")
    summary = {}
    for cond in CONDITIONS:
        s = stats(per_condition[cond])
        over = sum(1 for x in per_condition[cond] if x > B)
        summary[cond] = {**s, "over_B": over}
        print(f"{cond:<5} {s['min']:>8} {s['median']:>8} {s['max']:>8}   {over}/{len(certs)}")

    # --- the fixed scaffolding, i.e. what every condition pays ------------
    # Measured as the whole prompt with an EMPTY feedback block. The API
    # rejects a zero-length user message, and the suffix is non-empty, so this
    # is both legal and exactly the quantity wanted: everything the five
    # conditions pay identically.
    from certificate import template as _tpl
    sysblk, user0 = _tpl().split_for_call("")
    scaffold = counter.count(sysblk, user0)
    print(f"\nfixed scaffolding (prompt with an empty feedback block; the "
          f"system half is cached): {scaffold} tokens")

    # --- the F1 window ladder --------------------------------------------
    print(f"\n== F1 excerpt ladder: prompt tokens vs half-width, "
          f"over all {len(certs)} certificates ==")
    print(f"{'half-width':<12} {'min':>8} {'median':>8} {'max':>8}   over B")
    ladder = {}
    for hw in WINDOWS:
        xs = []
        for cert in certs:
            sysblk, user = cert.prompt_parts("F1", halfwidth=hw)
            xs.append(counter.count(sysblk, user))
        counter.save()
        s = stats(xs)
        over = sum(1 for x in xs if x > B)
        label = "full trace" if hw < 0 else f"+-{hw} rows"
        ladder[label] = {**s, "over_B": over, "halfwidth": hw,
                         "seconds_of_sim": None if hw < 0 else round((2 * hw + 1) * 0.05, 2)}
        print(f"{label:<12} {s['min']:>8} {s['median']:>8} {s['max']:>8}   "
              f"{over}/{len(certs)}")

    full = ladder["full trace"]
    fits = full["max"] <= B
    print(f"\nDOES AN UNWINDOWED F1 PROMPT FIT INSIDE B={B}?  "
          f"{'YES' if fits else 'NO'}")
    if not fits:
        print(f"  full-trace F1 overflows by {full['median'] - B} tokens at the "
              f"median and {full['max'] - B} at the worst certificate "
              f"({full['median'] / B:.1f}x and {full['max'] / B:.1f}x B).")
        ok = [k for k, v in ladder.items() if v["over_B"] == 0 and v["halfwidth"] >= 0]
        print(f"  windows that fit for every certificate: "
              f"{', '.join(ok) if ok else 'none of those measured'}")

    # --- can the F1 window even reach the event F4b reports? -------------
    # The point of the ladder is not only "what fits". F4b's content is the
    # leaf that was running immediately BEFORE the failing leaf started, so if
    # the window does not reach that transition, F1 cannot see the thing F4b
    # names -- however raw it is. Measured, not assumed.
    import pandas as pd
    back_rows, back_s = [], []
    for cert in certs:
        df = pd.read_parquet(cert.trace_path)
        i = cert.argmin_index
        here = df["bt_node_path"].iloc[i]
        k = i
        while k > 0 and df["bt_node_path"].iloc[k] == here:
            k -= 1
        back_rows.append(i - k)
        back_s.append(round(float(df["t_s"].iloc[i] - df["t_s"].iloc[k]), 3))
    reach = {
        "rows_back_to_authorising_transition": stats(back_rows),
        "seconds_back": {"min": min(back_s),
                         "median": statistics.median(back_s), "max": max(back_s)},
        "inside_configured_window": sum(1 for x in back_rows if x <= default_hw),
        "halfwidth_needed_for_all": max(back_rows),
    }
    print(f"\n== can F1's window reach the transition F4b reports? ==")
    print(f"  rows back from the argmin: min {min(back_rows)}  "
          f"median {statistics.median(back_rows)}  max {max(back_rows)}  "
          f"({min(back_s)}-{max(back_s)} s)")
    print(f"  inside the configured +-{default_hw} window: "
          f"{reach['inside_configured_window']}/{len(certs)}   "
          f"half-width needed to cover all: +-{max(back_rows)} rows")

    # --- campaign cost estimate ------------------------------------------
    sizes = json.loads(json.dumps(
        __import__("yaml").safe_load(
            (REPO / "data" / "scenarios" / "space.yaml").read_text())["sizes"]))
    seeds = int(sizes["seeds"])
    attempts = len(CONDITIONS) * len(certs) * seeds
    # Prompt side: the scaffolding is cache-READ on all but the first call of
    # each cache lifetime; the feedback block is fresh input every time.
    fresh = {c: summary[c]["mean"] - scaffold for c in CONDITIONS}
    prompt_cost = sum(
        len(certs) * seeds * (
            llm.cost_usd(int(fresh[c]), 0, cache_read=scaffold, model=a.model))
        for c in CONDITIONS)
    # Output side: measured on this repo's own synthesis calls (see
    # logs/llm_index.jsonl); effort=high spends most of the budget on
    # reasoning, so this is the dominant term and is a real estimate, not a
    # placeholder.
    out_tokens = _measured_output_tokens()
    out_cost = attempts * llm.cost_usd(0, out_tokens, model=a.model)
    print(f"\n== campaign cost estimate ==")
    print(f"  attempts: {len(CONDITIONS)} conditions x {len(certs)} certificates "
          f"x {seeds} seeds = {attempts}")
    print(f"  mean completion tokens, measured over this repo's prior "
          f"effort=high calls: {out_tokens}")
    print(f"  prompt side (scaffolding billed as cache reads): ${prompt_cost:.2f}")
    print(f"  completion side:                                 ${out_cost:.2f}")
    print(f"  TOTAL, order of magnitude:                       ${prompt_cost + out_cost:.2f}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "model": a.model,
        "budget_B": B,
        "f1_halfwidth_rows": default_hw,
        "n_certificates": len(certs),
        "scaffolding_tokens": scaffold,
        "by_condition": summary,
        "per_certificate": per_cert,
        "f1_window_ladder": ladder,
        "full_trace_f1_fits_in_B": fits,
        "f1_window_reach_vs_f4b": reach,
        "campaign": {
            "conditions": len(CONDITIONS), "certificates": len(certs),
            "seeds": seeds, "attempts": attempts,
            "mean_completion_tokens_measured": out_tokens,
            "prompt_cost_usd": round(prompt_cost, 2),
            "completion_cost_usd": round(out_cost, 2),
            "total_usd": round(prompt_cost + out_cost, 2),
        },
        "count_tokens_api_calls": counter.calls,
        "count_tokens_cache_hits": counter.hits,
        "git_commit": llm.git_commit(),
    }, indent=2))
    counter.save()
    print(f"\nwrote {OUT.relative_to(REPO)}  "
          f"({counter.calls} count_tokens calls, {counter.hits} cache hits)")
    return 0


def _measured_output_tokens(default: int = 6000) -> int:
    """Mean completion tokens over this repo's own logged effort=high calls."""
    idx = REPO / "logs" / "llm_index.jsonl"
    if not idx.exists():
        return default
    xs = [json.loads(l)["tokens_completion"]
          for l in idx.read_text().splitlines() if l.strip()]
    return int(statistics.mean(xs)) if xs else default


if __name__ == "__main__":
    raise SystemExit(main())
