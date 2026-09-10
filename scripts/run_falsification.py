#!/usr/bin/env python3
"""Drive the falsifier to K admitted counterexamples and bank the certificates.

    .venv/bin/python scripts/run_falsification.py --k 20 --port 2000

Engineering invariants, all load-bearing here:
  * ONE persistent CARLA client for the whole campaign.
  * Every episode wrapped so an exception returns a sentinel, never kills the
    campaign (this is inside CarlaBackend.run_episode and Falsifier.rollout).
  * CHECKPOINT AFTER EVERY ADMITTED COUNTEREXAMPLE -- a crash costs one
    certificate, not the batch. Certificates already on disk are picked up on
    restart and not re-derived.
  * Rollouts cached by (program, param_hash); never re-run an identical set.
  * The held-out region is never sampled, at any stage.

The campaign also settles the one genuinely open scientific question in the
project: H(node | contract) over the counterexamples the falsifier SELECTS.
If the violated contract determines the blamed node, F4 is information-
identical to F3 and the paper's headline comparison is vacuous by
construction. A result of zero is a real finding, not a failure. NOTHING here
selects counterexamples on `active_node` or on `violated_contract` -- doing so
would manufacture the entropy the campaign exists to measure.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
import os
import pathlib
import random
import sys
import time

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import stl  # noqa: E402
import yaml  # noqa: E402
from calibrate_baseline import conditional_entropy  # noqa: E402  (unit-tested)
from config import git_commit, load_config, param_hash  # noqa: E402
from falsifier import (  # noqa: E402
    Falsifier, budget_delta, narrate, render_boundary_report,
)
from run_campaign import in_held_out, sample  # noqa: E402

CONTRACT_KEYS = ("C1", "C2", "C3", "C4", "C5")

# Same tolerance the determinism gate applies (scripts/determinism_gate.py
# TOL_RHO). Using a tighter one here would report "non-deterministic" for
# float noise the project has already declared acceptable, and would bury the
# one contract that genuinely does drift under four that do not.
TOL_RHO = 1e-6


def utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def sha256_file(p) -> str:
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()[:16]


def write_json_atomic(path: pathlib.Path, obj: dict) -> None:
    """Write, flush and fsync. A crash on the next episode must not lose this."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w") as fh:
        json.dump(obj, fh, indent=2, default=str)
        fh.flush()
        os.fsync(fh.fileno())
    tmp.replace(path)


# ==========================================================================
# Certificate assembly
# ==========================================================================

def build_certificate(idx, viol, minimal_ro, contract, dropped, kept,
                      boundaries, boundary_report, avoid, repro,
                      spent, program_path, probe_path) -> dict:
    """All four certificate properties in one record (spec §7).

    MINIMAL     -> minimal_params / dropped_parameters
    GENERALIZED -> boundary / boundary_report
    ACTIONABLE  -> avoidable (and the probe evidence behind it)
    VERBALIZED  -> narrative

    ⚠️ WHICH SCENARIO THE CERTIFICATE IS *ABOUT*. rho, the per-contract vector,
    the argmin and `active_node` all describe the ORIGINAL scenario the
    falsifier found -- not the delta-debugged one. Minimization and boundary
    search are how the failure is DESCRIBED (compactly, and as a region rather
    than a point); they are not a replacement for the counterexample itself.

    This distinction is load-bearing and was found by measurement, not
    foreseen. Reverting to nominal collapses many distinct violations onto the
    same corner of the space -- with `aggressiveness` nominal at 0.0 the
    oncoming vehicle always yields, so nearly every C2 violation minimizes to
    the single fact "aggressiveness >= 0.44". Scoring the certificate on the
    minimized configuration would therefore have produced a corpus of near
    duplicates, and would have measured H(node | contract) over collapsed
    configurations rather than over the counterexamples the falsifier actually
    selected -- which is the population the experiment is about.
    """
    pc = viol.per_contract
    cid = f"CE{idx:03d}_{contract}_{viol.param_hash}"
    return {
        "certificate_id": cid,
        "param_hash": viol.param_hash,
        "git_commit": git_commit(),
        "timestamp": utcnow(),
        "schema_version": "1.0.0",

        # --- the program this counterexample is against ------------------
        "program": str(pathlib.Path(program_path).relative_to(REPO)),
        "program_sha256_16": sha256_file(program_path),
        "probe_program": str(pathlib.Path(probe_path).relative_to(REPO)),

        # --- MINIMAL (7.1) -----------------------------------------------
        # `minimal_params` is the certificate's scenario: it is what the
        # boundary is anchored on, what the narrative describes, and what a
        # repair should be evaluated against.
        "scenario_params": viol.params,
        "minimal_params": minimal_ro.params,
        # What a repair is scored against: the counterexample as found.
        "evaluation_params": viol.params,
        "dropped_parameters": dropped,
        "kept_parameters": kept,
        "rho_minimal": round(float(minimal_ro.rho), 6),
        "per_contract_minimal": {k: round(v, 6)
                                 for k, v in minimal_ro.per_contract.items()},
        "minimal_param_hash": minimal_ro.param_hash,
        "active_node_minimal": minimal_ro.active_node,

        # --- the violation ------------------------------------------------
        "violated_contract": contract,
        "rho": round(float(viol.rho), 6),
        **{f"rho{i}": (round(float(pc[k]), 6) if k in pc else None)
           for i, k in enumerate(CONTRACT_KEYS, start=1)},
        "rho_argmin_contract": viol.contract,
        "vacuous_contracts": [k for k, v in viol.vacuous.items() if v],
        "argmin_t_s": viol.t_s,
        "argmin_frame": viol.frame,
        "argmin_index": viol.argmin_index,

        # --- blame localization (7.5) -- a LOOKUP, not an inference ------
        "active_node": viol.active_node,
        "bt_node_type": viol.node_type,
        "bt_node_path": viol.node_path,
        "bt_tick_path": viol.tick_path,

        # --- GENERALIZED (7.2) -------------------------------------------
        "boundary": [
            {"parameter": b.parameter, "direction": b.direction,
             "threshold": b.threshold, "resolved": b.resolved,
             "violating_value": b.violating_value,
             "nominal_value": b.nominal_value,
             "bracket": [b.bracket[0], b.bracket[1]],
             "n_evals": b.n_evals, "note": b.note,
             "rendered": b.render()}
            for b in boundaries
        ],
        "boundary_report": boundary_report,

        # --- ACTIONABLE (7.3) --------------------------------------------
        **avoid,

        # --- VERBALIZED (7.4) --------------------------------------------
        "narrative": narrate(
            contract, viol.rho, viol.t_s, viol.node_type,
            viol.params, boundary_report, viol.achieved_gap_s),

        # --- episode provenance -------------------------------------------
        "episode_status": viol.status,
        "trace_path": viol.trace_path,
        "phases_reached": viol.phases_reached,
        "achieved_gap_s": viol.achieved_gap_s,

        "original_param_hash": viol.param_hash,

        # --- determinism spot-check ---------------------------------------
        "reproducibility": repro,

        # --- cost, broken out by purpose ----------------------------------
        **spent,
    }


# ==========================================================================
# main
# ==========================================================================

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=20)
    ap.add_argument("--port", type=int, default=2000)
    ap.add_argument("--gpu", type=int, default=0)
    ap.add_argument("--seed", type=int, default=20260831)
    ap.add_argument("--batch", type=int, default=40,
                    help="uniform samples per search round")
    ap.add_argument("--refine-top", type=int, default=2,
                    help="seeds taken from EACH contract's own ranking")
    ap.add_argument("--refine-steps", type=int, default=4,
                    help="local resamples per seed")
    ap.add_argument("--max-rounds", type=int, default=30)
    ap.add_argument("--max-rollouts", type=int, default=6000)
    ap.add_argument("--program", default=str(REPO / "data/scenarios/baseline_program.bt"))
    ap.add_argument("--probe", default=str(REPO / "data/scenarios/conservative_probe.bt"))
    ap.add_argument("--out-dir", default=str(REPO / "data/certificates"))
    ap.add_argument("--summary", default=str(REPO / "data/results/falsification_summary.json"))
    a = ap.parse_args()

    t_start = time.perf_counter()
    cfg = load_config("sim")
    cfg["server"]["port"] = a.port
    contracts_cfg = load_config("contracts")
    junction = stl.load_junction()

    space_yaml = yaml.safe_load((REPO / "data/scenarios/space.yaml").read_text())
    space = {k: tuple(v["range"]) for k, v in space_yaml["parameters"].items()}
    types = {k: v.get("type", "float") for k, v in space_yaml["parameters"].items()}
    nominal = {k: (int(v["nominal"]) if v.get("type") == "integer"
                   else float(v["nominal"]))
               for k, v in space_yaml["parameters"].items()}

    out_dir = pathlib.Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 78)
    print("FALSIFICATION CAMPAIGN")
    print("=" * 78)
    print(f"  program        {a.program}  sha={sha256_file(a.program)}")
    print(f"  probe          {a.probe}  sha={sha256_file(a.probe)}")
    print(f"  contracts      {contracts_cfg['combined']['active']}")
    print(f"  parameters     {list(space)}")
    print(f"  nominal        {nominal}")
    print(f"  target K       {a.k}   seed {a.seed}")
    print(f"  held-out       never sampled: {space_yaml['held_out']['v_oncoming']} "
          f"x {space_yaml['held_out']['headway']}")

    # --- resume ---------------------------------------------------------
    # RECOVERY DESIGN. Individual episodes cannot kill the campaign:
    # CarlaBackend.run_episode returns a sentinel on any exception and
    # Falsifier.rollout turns an unscoreable sentinel into a skipped candidate.
    # A dead SERVER is not recovered from in-process, unlike run_campaign.py --
    # deliberately. Every admitted certificate is fsynced to disk the moment it
    # is built, and the block below reloads them, so re-invoking this script
    # after a server restart resumes from the certificates already banked and
    # costs nothing but the rollouts of the round in flight. Rebuilding the
    # backend mid-campaign would add an untestable recovery path to buy back
    # only that partial round.
    existing = sorted(out_dir.glob("CE*.json"))
    admitted = [json.loads(p.read_text()) for p in existing]
    if admitted:
        print(f"  RESUMING: {len(admitted)} certificates already on disk")
    processed: set = {c.get("original_param_hash") for c in admitted}
    # Rebuilt on resume as well, or a certificate banked before a restart would
    # not be recognised as the original of a duplicate banked after it.
    info_index: dict = {}
    for c in admitted:
        if c.get("information_key"):
            info_index.setdefault(c["information_key"], c["certificate_id"])

    rng = random.Random(a.seed)
    from carla_backend import CarlaBackend

    be = CarlaBackend(cfg=cfg)
    be.__enter__()
    fz = Falsifier(be, contracts_cfg, junction, space, types, nominal,
                   in_held_out, a.program, a.probe, rng)

    rejected: list = []
    unscoreable = 0
    n_verification_rollouts = 0
    nominal_check: dict = {}
    last_fals_mark = 0

    try:
        # --- delta-debugging soundness check, MEASURED not assumed -------
        # If the all-nominal configuration violates, reverting a parameter to
        # nominal can CREATE a violation and delta debugging's conclusions are
        # unsound. Cheap (one rollout) and it invalidates everything downstream
        # if wrong, so it runs first and stops the campaign on failure.
        print("\n--- delta-debugging reference check (all-nominal) ---")
        ro_nom = fz.rollout(dict(nominal), "falsification")
        if ro_nom is None or not ro_nom.scoreable:
            print("  FATAL: the all-nominal configuration is not scoreable.")
            return 2
        nominal_check = {
            "params": dict(nominal), "rho": round(float(ro_nom.rho), 6),
            "argmin_contract": ro_nom.contract,
            "per_contract": {k: round(v, 6) for k, v in ro_nom.per_contract.items()},
            "violation_free": bool(ro_nom.rho >= 0),
            "status": ro_nom.status,
        }
        print(f"  rho = {ro_nom.rho:+.4f}  argmin {ro_nom.contract}  "
              f"{nominal_check['per_contract']}")
        if ro_nom.rho < 0:
            print("  FATAL: the all-nominal configuration VIOLATES. Delta "
                  "debugging would be unsound against it -- reverting a "
                  "parameter could create a violation rather than remove one. "
                  "Stopping rather than emitting certificates built on it.")
            write_json_atomic(pathlib.Path(a.summary),
                              {"status": "BLOCKED", "reason": "nominal violates",
                               "nominal_check": nominal_check})
            return 3
        print("  OK -- nominal is violation-free, delta debugging is sound here.")

        pool: list = []
        rnd = 0
        while len(admitted) < a.k and rnd < a.max_rounds:
            rnd += 1
            if fz.budget.total > a.max_rollouts:
                print(f"\nrollout budget {a.max_rollouts} exhausted")
                break

            # ---- 1. SEARCH: uniform, then per-contract ranked refinement --
            batch = fz.uniform_batch(lambda: sample(rng), a.batch)
            pool.extend(batch)
            refined = fz.refine(pool, a.refine_top, a.refine_steps,
                                float(space_yaml["sampling"]["refinement_radius_frac"]))
            pool.extend(refined)
            unscoreable += sum(1 for r in batch + refined if not r.scoreable)

            # DEDUPE WITHIN THE ROUND TOO, not just against previous rounds.
            # `processed` is only added to as violations are consumed, so a
            # param_hash appearing twice in one round passed this filter twice
            # and was certified twice. It does appear twice routinely: the
            # cache returns the SAME Rollout object for a repeated parameter
            # set, and refine() re-appends its running best each iteration.
            # Measured on the first campaign: 4 duplicated pairs, so 20
            # certificates covered only 16 distinct scenarios.
            fresh, _seen_round = [], set()
            for r in batch + refined:
                if not r.violated or r.param_hash in processed:
                    continue
                if r.param_hash in _seen_round:
                    continue
                _seen_round.add(r.param_hash)
                fresh.append(r)
            # Discovery order only. NOT sorted by contract or by node: any
            # selection on either would manufacture the entropy this campaign
            # exists to measure.
            print(f"\n[round {rnd}] rollouts={fz.budget.total} "
                  f"pool={len(pool)} new violations={len(fresh)} "
                  f"admitted={len(admitted)}/{a.k}")

            for viol in fresh:
                if len(admitted) >= a.k:
                    break
                processed.add(viol.param_hash)
                contract = viol.contract
                mark = fz.budget.snapshot()

                # ---- 2. DELTA DEBUGGING (7.1) ------------------------
                minimal, dropped, kept = fz.minimize(viol, contract)
                minimal_ro = fz.rollout(minimal, "minimization")
                if minimal_ro is None or not minimal_ro.scoreable:
                    rejected.append({"param_hash": viol.param_hash,
                                     "reason": "minimized config unscoreable"})
                    continue
                # The minimized configuration must STILL violate the contract
                # the certificate is about. If it does not, delta debugging
                # produced something that is not a counterexample and it must
                # never be banked as one.
                if not (minimal_ro.rho_of(contract) < 0):
                    rejected.append({"param_hash": viol.param_hash,
                                     "reason": "minimized config no longer violates",
                                     "contract": contract})
                    continue

                # ---- 3. BOUNDARY SEARCH (7.2) ------------------------
                bnds = fz.boundaries(minimal, kept, contract)
                report = render_boundary_report(bnds, contract)

                # ---- 4. AVOIDABILITY FILTER (7.3) --------------------
                # On the ORIGINAL scenario: the question is whether THIS
                # violation was avoidable, not whether its minimized shadow was.
                avoid = fz.avoidability(viol.params, contract)
                if not avoid["avoidable"]:
                    rejected.append({
                        "param_hash": viol.param_hash,
                        "minimal_param_hash": minimal_ro.param_hash,
                        "reason": "unavoidable", "contract": contract,
                        "probe_rho_on_contract": avoid["probe_rho_on_contract"],
                        "probe_rho": avoid["probe_rho"]})
                    print(f"    REJECTED (unavoidable) {contract} "
                          f"rho={minimal_ro.rho:+.3f} "
                          f"probe_rho_on_{contract}={avoid['probe_rho_on_contract']}")
                    continue

                # ---- determinism spot-check --------------------------
                # Determinism is load-bearing, so every admitted
                # counterexample is re-simulated once with the cache BYPASSED
                # and its rho compared. This turns a determinism risk into a
                # recorded number per certificate instead of an assumption.
                again = fz.reproduce(viol.params, contract)
                n_verification_rollouts += 1
                repro = {"checked": again is not None and again.scoreable,
                         "tolerance": TOL_RHO}
                if repro["checked"]:
                    repro.update({
                        "rho_repeat": round(float(again.rho), 6),
                        "rho_delta": round(float(again.rho - viol.rho), 9),
                        "per_contract_repeat": {k: round(v, 6)
                                                for k, v in again.per_contract.items()},
                        "per_contract_delta": {
                            k: round(float(again.per_contract.get(k, float("nan"))
                                           - v), 9)
                            for k, v in viol.per_contract.items()},
                        "active_node_repeat": again.active_node,
                        "rho_reproduces": abs(again.rho - viol.rho) <= TOL_RHO,
                        "node_reproduces": again.active_node == viol.active_node,
                    })
                    # Which contracts reproduce, individually. rho = min(.)
                    # hides a contract that drifts while a different one is the
                    # argmin, and C4 is measurably such a contract on this
                    # build -- see docs/determinism_c4.md.
                    pcd = repro["per_contract_delta"]
                    repro["per_contract_reproduces"] = {
                        k: abs(v) <= TOL_RHO for k, v in pcd.items()}
                    repro["max_abs_per_contract_delta"] = (
                        max((abs(v) for v in pcd.values()), default=0.0))
                    repro["contracts_not_reproducing"] = [
                        k for k, v in pcd.items() if abs(v) > TOL_RHO]

                # ---- bank it -----------------------------------------
                spent = budget_delta(mark, fz.budget.snapshot())
                # Search cost is not attributable to one counterexample, so
                # `rollouts_falsification` is the search spent SINCE THE LAST
                # ADMISSION -- an amortized share, labelled as such.
                spent["rollouts_falsification"] = (
                    fz.budget.counts["falsification"] - last_fals_mark)
                last_fals_mark = fz.budget.counts["falsification"]

                cert = build_certificate(
                    len(admitted) + 1, viol, minimal_ro, contract, dropped,
                    kept, bnds, report, avoid, repro, spent, a.program, a.probe)
                # Two certificates carry the same INFORMATION when they name
                # the same contract, the same surviving parameters and the same
                # boundary. That is flagged, not filtered: dropping them would
                # shrink the corpus on a criterion the experiment never agreed
                # to, and the redundancy rate is itself a property of the
                # falsifier worth reporting.
                info_key = str((contract, tuple(sorted(kept)),
                                tuple(round(b.threshold, 2) if b.threshold is not None
                                      else None for b in bnds)))
                cert["information_key"] = info_key
                cert["information_duplicate_of"] = info_index.get(info_key)
                info_index.setdefault(info_key, cert["certificate_id"])
                # CHECKPOINT: on disk, fsynced, before anything else happens.
                write_json_atomic(out_dir / f"{cert['certificate_id']}.json", cert)
                admitted.append(cert)
                dup = (" [information duplicate of "
                       f"{cert['information_duplicate_of']}]"
                       if cert["information_duplicate_of"] else "")
                print(f"    ADMITTED {cert['certificate_id']}  "
                      f"rho={viol.rho:+.3f}  node={viol.active_node}{dup}")
                print(f"      {report}")
                if repro.get("checked") and not repro.get("rho_reproduces"):
                    print(f"      ⚠ rho did NOT reproduce on re-simulation: "
                          f"delta={repro['rho_delta']:+.3e}")
    finally:
        try:
            be.__exit__(None, None, None)
        except Exception:
            pass

    # ======================================================================
    # The measurement this campaign exists to settle
    # ======================================================================
    wall = time.perf_counter() - t_start
    pairs = [(c["violated_contract"], c["active_node"]) for c in admitted
             if c.get("active_node")]
    H, detail = conditional_entropy(pairs) if pairs else (0.0, {})
    by_contract = collections.Counter(c["violated_contract"] for c in admitted)
    nodes = collections.Counter(c["active_node"] for c in admitted)

    n_rej_unavoidable = sum(1 for r in rejected if r["reason"] == "unavoidable")
    n_considered = len(admitted) + n_rej_unavoidable

    summary = {
        "status": "DONE" if len(admitted) >= a.k else "PARTIAL",
        "timestamp": utcnow(), "git_commit": git_commit(),
        "wall_clock_s": round(wall, 1),
        "K_target": a.k, "K_admitted": len(admitted),
        "seed": a.seed,
        "program": a.program, "program_sha256_16": sha256_file(a.program),
        "probe": a.probe, "probe_sha256_16": sha256_file(a.probe),
        "active_contracts": contracts_cfg["combined"]["active"],
        "nominal_check": nominal_check,
        "violated_contracts": {k: by_contract.get(k, 0) for k in CONTRACT_KEYS},
        "distinct_blamed_nodes": len(nodes),
        "blamed_nodes": dict(nodes.most_common()),
        "H_node_given_contract_bits": round(H, 4),
        "blame_detail": detail,
        "rollouts": fz.budget.as_dict(),
        "rollouts_verification": n_verification_rollouts,
        "rollouts_per_admitted": (round(fz.budget.total / len(admitted), 1)
                                  if admitted else None),
        "held_out_refusals": fz.refusals,
        "unscoreable_episodes": unscoreable,
        "rejected": rejected,
        "n_rejected_unavoidable": n_rej_unavoidable,
        "unavoidable_rate": (round(n_rej_unavoidable / n_considered, 4)
                             if n_considered else None),
        "information_duplicates": sum(
            1 for c in admitted if c.get("information_duplicate_of")),
        "distinct_information_keys": len({c.get("information_key")
                                          for c in admitted}),
        "contracts_failing_reproducibility": sorted({
            k for c in admitted
            for k in c.get("reproducibility", {}).get("contracts_not_reproducing", [])}),
        "reproducibility_failures": [
            c["certificate_id"] for c in admitted
            if c.get("reproducibility", {}).get("checked")
            and not c["reproducibility"].get("rho_reproduces")],
    }
    write_json_atomic(pathlib.Path(a.summary), summary)

    print("\n" + "=" * 78)
    print(f"admitted {len(admitted)}/{a.k} in {wall:.1f}s")
    print(f"contracts        {summary['violated_contracts']}")
    print(f"distinct nodes   {summary['distinct_blamed_nodes']}  {summary['blamed_nodes']}")
    print(f"H(node|contract) {H:.4f} bits")
    print(f"rollouts         {fz.budget.as_dict()}")
    print(f"unavoidable rate {summary['unavoidable_rate']}")
    print(f"repro failures   {summary['reproducibility_failures']}")
    print(f"summary written  {a.summary}")
    print("=" * 78)
    return 0 if len(admitted) >= a.k else 1


if __name__ == "__main__":
    raise SystemExit(main())
