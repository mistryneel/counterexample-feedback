#!/usr/bin/env python3
"""Run the E1 campaign: 5 conditions x 20 certificates x 3 replicates.

TWO PHASES, DELIBERATELY SEPARATED.

  Phase A (LLM)    300 calls. Independent of each other, so they run
                   concurrently. ~1 minute each serially would be 5 hours;
                   threaded it is under one.
  Phase B (CARLA)  61 scenarios per `ok` patch. STRICTLY SERIAL -- one
                   persistent client per campaign (project engineering
                   invariants), and the determinism the whole project rests on
                   is a property of a single synchronous server stepping one
                   episode at a time.

Separating them means a CARLA failure never wastes LLM spend and an API
failure never wastes simulation. Both phases checkpoint after every unit of
work, flushed and fsynced, and both resume by `attempt_id` -- a crash at
attempt 250 costs one attempt, not $45.

PHASE A ORDERING NOTE. The first call is made ALONE, before the pool starts.
The 4513-token system prefix is byte-identical across all 300 calls and
`src/llm.py` marks it `cache_control`; if 8 threads start simultaneously they
all miss a cache that does not exist yet and each pays a cache WRITE. One
warm-up call creates the entry, and the remaining 299 read it.

    .venv/bin/python scripts/run_e1.py --dry-run          # 1 cert x 5 x 1
    .venv/bin/python scripts/run_e1.py --phase a
    .venv/bin/python scripts/run_e1.py --phase b --port 2000
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import pathlib
import sys
import threading
import time

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import llm  # noqa: E402
import patcher  # noqa: E402
import stl  # noqa: E402
from certificate import CONDITIONS, Certificate  # noqa: E402
from config import load_config  # noqa: E402
from evaluate import Evaluator, budget_delta, load_suites  # noqa: E402

PATCHES = REPO / "data" / "results" / "patches.jsonl"
ATTEMPTS = REPO / "data" / "results" / "attempts.jsonl"
BASELINE_EVAL = REPO / "data" / "results" / "baseline_eval.json"
SEEDS = (1, 2, 3)

_write_lock = threading.Lock()


def append_jsonl(path: pathlib.Path, rec: dict) -> None:
    """Checkpoint one record. Flushed and fsynced -- a crash costs one attempt."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with _write_lock:
        with path.open("a") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")
            fh.flush()
            os.fsync(fh.fileno())


def read_jsonl(path: pathlib.Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def plan(certs, conditions, seeds) -> list[tuple]:
    """Every (condition, certificate, replicate) in a fixed order."""
    return [(c, cert, s) for cert in certs for c in conditions for s in seeds]


# ==========================================================================
# Phase A -- the LLM calls
# ==========================================================================
def phase_a(certs, conditions, seeds, workers: int, effort: str,
            max_tokens: int) -> int:
    done = {r["attempt_id"] for r in read_jsonl(PATCHES)}
    todo = [t for t in plan(certs, conditions, seeds)
            if patcher.attempt_id(t[0], t[1].certificate_id, t[2]) not in done]
    print(f"PHASE A: {len(todo)} calls to make ({len(done)} already on disk)")
    if not todo:
        return 0

    counts = {o: 0 for o in patcher.OUTCOMES}
    t0 = time.perf_counter()

    def run(task):
        cond, cert, seed = task
        return patcher.generate(cert, cond, seed, effort=effort,
                                max_tokens=max_tokens)

    # Warm the prompt cache with ONE call before fanning out. See module docstring.
    first, rest = todo[0], todo[1:]
    rec = run(first)
    append_jsonl(PATCHES, rec)
    counts[rec["outcome"]] += 1
    print(f"  [warm-up] {rec['attempt_id']:<44} {rec['outcome']:<10} "
          f"cache_write={rec.get('cache_write')}")

    n = 1
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(run, t): t for t in rest}
        for fut in cf.as_completed(futs):
            rec = fut.result()
            append_jsonl(PATCHES, rec)
            counts[rec["outcome"]] += 1
            n += 1
            if n % 10 == 0 or rec["outcome"] != "ok":
                print(f"  [{n:>3}/{len(todo)}] {rec['attempt_id']:<44} "
                      f"{rec['outcome']:<10} "
                      f"ted={rec.get('ted_from_original')} "
                      f"{rec.get('patch_type') or ''}"
                      + (f"  {rec.get('validator_result', '')[:70]}"
                         if rec["outcome"] == "malformed" else "")
                      + (f"  {rec.get('api_error', '')[:70]}"
                         if rec["outcome"] == "api_error" else ""))

    dt = time.perf_counter() - t0
    print(f"\nPHASE A done in {dt/60:.1f} min: " +
          "  ".join(f"{k}={v}" for k, v in counts.items()))
    return 0


# ==========================================================================
# Phase B -- simulation
# ==========================================================================
def phase_b(certs, port: int) -> int:
    patches = {r["attempt_id"]: r for r in read_jsonl(PATCHES)}
    done = {r["attempt_id"] for r in read_jsonl(ATTEMPTS)}
    by_id = {c.certificate_id: c for c in certs}

    reg, held, reg_meta, held_meta = load_suites()
    print(f"suites: regression {len(reg)} (baseline SCVR "
          f"{reg_meta['baseline_scvr']:.3f}), held-out {len(held)} "
          f"(baseline SCVR {held_meta['baseline_scvr']:.3f})")

    todo = [a for a in patches if a not in done]
    print(f"PHASE B: {len(todo)} attempts to evaluate ({len(done)} already done)")
    if not todo:
        return 0

    cfg = load_config("sim")
    cfg["server"]["port"] = port
    contracts = load_config("contracts")
    junction = stl.load_junction()

    from carla_backend import CarlaBackend
    be = CarlaBackend(cfg=cfg)
    be.__enter__()
    t0 = time.perf_counter()
    n_res = n_c4 = 0
    try:
        ev = Evaluator(be, contracts, junction)

        # The unpatched baseline on the same 61 -- spec §9.4 requires it as a
        # comparator, and every generalization gap is read against it.
        if not BASELINE_EVAL.exists():
            print("  evaluating the UNPATCHED BASELINE on all 20 counterexamples "
                  "and both suites...")
            base = {}
            for cert in certs:
                base[cert.certificate_id] = ev.evaluate(
                    str(patcher.BASELINE), cert, reg, held)
            BASELINE_EVAL.write_text(json.dumps(base, indent=2, default=str))
            print(f"  wrote {BASELINE_EVAL.relative_to(REPO)}")

        for i, aid in enumerate(sorted(todo), 1):
            p = patches[aid]
            cert = by_id[p["certificate_id"]]
            rec = dict(p)
            rec.update(patcher.certificate_fields(cert))

            if p["outcome"] != "ok":
                # Not evaluated, and NOT counted as unresolved-after-evaluation.
                # A malformed or truncated attempt has no program to simulate;
                # pooling it with an evaluated failure would make the fix rate
                # answer a different question.
                rec.update({"resolved": False, "evaluated": False,
                            "rho_after": None, "regression_failures": None,
                            "held_out_scvr": None, "generalization_gap": None,
                            "rollouts_counterexample": 0,
                            "rollouts_regression": 0, "rollouts_evaluation": 0})
                append_jsonl(ATTEMPTS, rec)
                print(f"  [{i:>3}/{len(todo)}] {aid:<44} {p['outcome']} -- not evaluated")
                continue

            before = ev.snapshot()
            # Absolute: the record stores a repo-relative path, and the backend
            # loads by filesystem path from whatever cwd the campaign runs in.
            prog = str(REPO / p["patched_program_path"])
            res = ev.evaluate(prog, cert, reg, held)
            rec.update(res)
            rec["evaluated"] = True
            rec.update(budget_delta(before, ev.snapshot()))
            append_jsonl(ATTEMPTS, rec)

            n_res += bool(res.get("resolved"))
            n_c4 += bool(res.get("c4_binding_after"))
            el = time.perf_counter() - t0
            print(f"  [{i:>3}/{len(todo)}] {aid:<44} "
                  f"resolved={str(res.get('resolved')):<5} "
                  f"rho={res.get('rho_after')} "
                  f"reg_fail={res.get('regression_failures')} "
                  f"ho_scvr={res.get('held_out_scvr')} "
                  f"icr={res.get('icr')} "
                  f"[{el/60:.1f}m, {i/max(el,1e-9)*3600:.0f}/h]"
                  + ("  ** C4 BINDING **" if res.get("c4_binding_after") else ""))

        el = time.perf_counter() - t0
        print(f"\nPHASE B done in {el/60:.1f} min. resolved {n_res}/{len(todo)}. "
              f"C4 binding after patch in {n_c4} attempts.")
        print("rollouts: " + json.dumps(ev.snapshot()) +
              f"  cache_hits={ev.cache_hits}")
    finally:
        be.__exit__(None, None, None)
    return 0


# ==========================================================================
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["a", "b", "ab"], default="ab")
    ap.add_argument("--port", type=int, default=2000)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--effort", default=llm.EFFORT)
    ap.add_argument("--max-tokens", type=int, default=48000)
    ap.add_argument("--dry-run", action="store_true",
                    help="1 certificate x 5 conditions x 1 replicate, "
                         "end to end, into separate files")
    ap.add_argument("--dry-cert", default="CE003")
    a = ap.parse_args()

    certs = Certificate.load_all()
    conditions, seeds = list(CONDITIONS), list(SEEDS)

    if a.dry_run:
        certs = [c for c in certs if c.certificate_id.startswith(a.dry_cert)]
        seeds = [1]
        global PATCHES, ATTEMPTS, BASELINE_EVAL
        PATCHES = REPO / "data" / "results" / "dryrun_patches.jsonl"
        ATTEMPTS = REPO / "data" / "results" / "dryrun_attempts.jsonl"
        BASELINE_EVAL = REPO / "data" / "results" / "dryrun_baseline_eval.json"
        print(f"DRY RUN: {len(certs)} certificate x {len(conditions)} conditions "
              f"x {len(seeds)} replicate = "
              f"{len(certs)*len(conditions)*len(seeds)} attempts")

    print(f"conditions {conditions}  certificates {len(certs)}  seeds {seeds}  "
          f"= {len(certs)*len(conditions)*len(seeds)} attempts")

    if a.phase in ("a", "ab"):
        rc = phase_a(certs, conditions, seeds, a.workers, a.effort, a.max_tokens)
        if rc:
            return rc
    if a.phase in ("b", "ab"):
        return phase_b(certs, a.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
