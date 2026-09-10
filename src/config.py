"""Configuration loading. Nothing in this project is hardcoded in Python.

`load_config()` reads config/sim.yaml, then deep-merges config/local.yaml over
it if that file exists. local.yaml is git-ignored and holds machine-specific
values (ports, container names, GPU index).
"""

from __future__ import annotations

import copy
import hashlib
import json
import pathlib
import subprocess
from typing import Any

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(name: str = "sim") -> dict:
    """Load config/<name>.yaml, deep-merged with config/local.yaml if present."""
    path = REPO_ROOT / "config" / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"missing config: {path}")
    cfg = yaml.safe_load(path.read_text()) or {}

    local = REPO_ROOT / "config" / "local.yaml"
    if local.exists():
        cfg = _deep_merge(cfg, yaml.safe_load(local.read_text()) or {})
    return cfg


def param_hash(params: dict) -> str:
    """Stable SHA-256 of a scenario parameter dict.

    This is the simulation cache key (project rule: "Cache simulations. Never
    re-run an identical parameter set."). sort_keys makes it independent of
    dict insertion order; separators strip whitespace so formatting changes
    do not invalidate the cache.
    """
    canon = json.dumps(params, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode()).hexdigest()[:16]


def git_commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        return out.stdout.strip() or None if out.returncode == 0 else None
    except Exception:
        return None


def check_substepping(cfg: dict) -> tuple[bool, str]:
    """Verify fixed_delta_seconds <= max_substep_delta_time * max_substeps.

    CARLA does not raise when this is violated -- physics silently becomes
    non-deterministic. Returns (ok, human-readable explanation).
    """
    fd = cfg["timing"]["fixed_delta_seconds"]
    p = cfg["physics"]
    prod = p["max_substep_delta_time"] * p["max_substeps"]
    ok = fd <= prod
    msg = (
        f"fixed_delta_seconds={fd} <= "
        f"max_substep_delta_time({p['max_substep_delta_time']}) * "
        f"max_substeps({p['max_substeps']}) = {prod} -> "
        f"{'HOLDS' if ok else 'VIOLATED'}"
    )
    if p["max_substep_delta_time"] >= 0.01666:
        msg += (
            f"  [WARNING: max_substep_delta_time="
            f"{p['max_substep_delta_time']} exceeds the documented ceiling "
            f"of 0.01666]"
        )
    return ok, msg
