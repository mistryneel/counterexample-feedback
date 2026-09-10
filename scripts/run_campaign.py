#!/usr/bin/env python3
"""Run a campaign of scenarios and bank every trajectory to Parquet.

Engineering invariants:
  * ONE persistent CARLA client for the whole campaign.
  * Every episode wrapped so an exception returns a sentinel, never kills
    the campaign.
  * CHECKPOINT AFTER EVERY EPISODE -- a crash costs one run, not the batch.
  * Identical parameter sets are never re-simulated (cache by param_hash).
  * The server is watched; if it dies the campaign restarts it and carries on.

    scripts/run_campaign.py --n 300 --port 2000 --seed 1
"""
from __future__ import annotations

import argparse
import json
import pathlib
import random
import subprocess
import sys
import time
from dataclasses import asdict

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from config import REPO_ROOT, load_config, param_hash  # noqa: E402

SPACE = {
    "n_oncoming": (1, 3),
    "v_oncoming": (6.0, 16.0),
    "headway": (1.5, 8.0),
    "aggressiveness": (0.0, 1.0),
}
# ped_phase_offset DROPPED 24 Aug: no pedestrian was ever spawned, so it was a
# no-op with measured correlation -0.031 against rho.
# aggressiveness RESTORED 24 Aug: a space in which only v_oncoming carries
# signal makes boundary search degenerate.
# Authoritative bounds and their justification: data/scenarios/space.yaml

# Held-out region reserved for evaluation; the sampler must never enter it.
# An interior hole, so the held-out test is interpolation not extrapolation.
# Authoritative definition: data/scenarios/space.yaml
def _load_space():
    import yaml
    p = REPO_ROOT / "data" / "scenarios" / "space.yaml"
    if not p.exists():
        return None
    return yaml.safe_load(p.read_text())


_SPACE_YAML = _load_space()
if _SPACE_YAML:
    SPACE = {k: tuple(v["range"]) for k, v in _SPACE_YAML["parameters"].items()}
    HELD_OUT = {k: tuple(v) for k, v in _SPACE_YAML["held_out"].items()
                if k != "justification"}
else:
    HELD_OUT = {"v_oncoming": (11.0, 13.0), "headway": (3.0, 4.5)}


def in_held_out(p: dict) -> bool:
    return (HELD_OUT["v_oncoming"][0] <= p["v_oncoming"] <= HELD_OUT["v_oncoming"][1]
            and HELD_OUT["headway"][0] <= p["headway"] <= HELD_OUT["headway"][1])


# Parameter TYPES come from space.yaml alongside the ranges, so a parameter
# added there is sampled automatically. The previous version hardcoded the four
# parameter names: when light_offset and lead_gap_s were added on 30 Aug the
# ranges were picked up but the names were not, so every sampled scenario
# silently omitted both and the two new contracts they drive would have been
# vacuous in the entire campaign without anything erroring.
PARAM_TYPES = ({k: v.get("type", "float") for k, v in _SPACE_YAML["parameters"].items()}
               if _SPACE_YAML else
               {"n_oncoming": "integer", "v_oncoming": "float",
                "headway": "float", "aggressiveness": "float"})


def sample(rng: random.Random, allow_held_out: bool = False) -> dict:
    for _ in range(1000):
        p = {}
        for name, (lo, hi) in SPACE.items():
            if PARAM_TYPES.get(name) == "integer":
                p[name] = rng.randint(int(lo), int(hi))
            else:
                p[name] = round(rng.uniform(float(lo), float(hi)), 4)
        if allow_held_out or not in_held_out(p):
            return p
    raise RuntimeError("rejection sampling failed to leave the held-out region")


def server_alive(port: int, timeout_s: float = 5.0) -> bool:
    r = subprocess.run(
        [str(REPO_ROOT / ".venv/bin/python"), "-c",
         f"import carla,sys;c=carla.Client('127.0.0.1',{port});"
         f"c.set_timeout({timeout_s});c.get_server_version()"],
        capture_output=True, timeout=timeout_s + 20)
    return r.returncode == 0


def restart_server(port: int, gpu: int) -> None:
    subprocess.run([str(REPO_ROOT / "scripts/stop_carla.sh"), "--port", str(port)],
                   capture_output=True, timeout=240)
    subprocess.run([str(REPO_ROOT / "scripts/start_carla.sh"),
                    "--port", str(port), "--gpu", str(gpu)],
                   capture_output=True, timeout=900)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, required=True)
    ap.add_argument("--port", type=int, default=2000)
    ap.add_argument("--tm-port", type=int, default=None)
    ap.add_argument("--gpu", type=int, default=0)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--tag", type=str, default="bank")
    ap.add_argument("--manifest", type=str, default=None)
    ap.add_argument("--program", type=str, default=None,
                    help="path to a .bt program; omit to use the placeholder controller")
    a = ap.parse_args()

    cfg = load_config("sim")
    cfg["server"]["port"] = a.port
    if a.tm_port:
        cfg["seeds"]["tm_port"] = a.tm_port

    manifest_path = pathlib.Path(
        a.manifest or REPO_ROOT / "data" / "results" / f"campaign_{a.tag}_{a.shard}.jsonl")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    # Resume: anything already recorded is skipped, so a restart costs nothing.
    done: set[str] = set()
    if manifest_path.exists():
        for line in manifest_path.read_text().splitlines():
            if line.strip():
                with_ = json.loads(line)
                done.add(with_["episode_id"])
        print(f"resuming: {len(done)} episodes already banked")

    rng = random.Random(a.seed * 100003 + a.shard)
    params_list = [sample(rng) for _ in range(a.n)]

    from carla_backend import CarlaBackend

    t0 = time.perf_counter()
    n_ok = n_fail = n_skip = 0
    seen_hashes: set[str] = set()

    be = CarlaBackend(cfg=cfg)
    be.__enter__()
    if a.program:
        prog = be.load_program(a.program)
        print(f"program {a.program}: depth={prog.ast.depth()} "
              f"size={prog.ast.size()} warnings={prog.validation.warnings}")
    try:
        for i, params in enumerate(params_list):
            ph = param_hash(params)
            eid = f"{a.tag}_{a.shard}_{i:05d}_{ph}"
            if eid in done:
                n_skip += 1
                continue
            if ph in seen_hashes:
                # Cache: never re-run an identical parameter set.
                n_skip += 1
                continue
            seen_hashes.add(ph)

            res = be.run_episode(params, episode_id=eid)

            if not res.usable and res.status in ("exception", "server_lost"):
                # Is the SERVER gone, or was this one bad episode?
                if not server_alive(a.port):
                    print(f"  [{i}] server lost -- restarting", flush=True)
                    try:
                        be.__exit__(None, None, None)
                    except Exception:
                        pass
                    restart_server(a.port, a.gpu)
                    be = CarlaBackend(cfg=cfg)
                    be.__enter__()
                    if a.program:
                        be.load_program(a.program)
                    res = be.run_episode(params, episode_id=eid)

            # CHECKPOINT: append immediately, flush, fsync. A crash on the next
            # episode must not lose this one.
            rec = {**asdict(res), "index": i}
            with manifest_path.open("a") as fh:
                fh.write(json.dumps(rec, default=str) + "\n")
                fh.flush()
                import os
                os.fsync(fh.fileno())

            if res.usable:
                n_ok += 1
            else:
                n_fail += 1
            if (i + 1) % 10 == 0 or i == 0:
                el = time.perf_counter() - t0
                rate = (n_ok + n_fail) / el if el > 0 else 0
                print(f"  [{i+1}/{a.n}] ok={n_ok} fail={n_fail} skip={n_skip} "
                      f"{rate:.2f} ep/s  eta={(a.n-i-1)/rate/60:.1f} min", flush=True)
    finally:
        try:
            be.__exit__(None, None, None)
        except Exception:
            pass

    el = time.perf_counter() - t0
    print(f"\ncampaign {a.tag} shard {a.shard}: ok={n_ok} fail={n_fail} "
          f"skip={n_skip} in {el:.1f}s ({(n_ok+n_fail)/el if el else 0:.2f} ep/s)")
    print(f"manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
