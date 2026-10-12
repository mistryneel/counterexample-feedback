#!/usr/bin/env python3
"""Re-score Table 4 (constructive test of expressiveness) and the clean-repair
validation from saved trajectories. Offline: no CARLA, no API call.

WHAT IT REPRODUCES
    Table 4 of the paper (label tab:dsl) and the six-repeat validation of the
    single clean repair (the one attempt of 300 that resolved its counterexample,
    completed the manoeuvre and caused no regression failure).

        .venv/bin/python scripts/rescore_dsl_probes.py             # score, compare, write JSON
        .venv/bin/python scripts/rescore_dsl_probes.py --no-write  # score and compare only

    Exit code 0 when every Table 4 cell, the validation and every numeric
    cross-check agree; 1 otherwise.

INPUTS (all committed)
    data/dsl_probe_traces/       one directory per Table 4 row (a row that is a
                                 family of programs has one sub-directory per
                                 variant), plus repeats/ for the six repeats.
                                 Each episode is a .parquet trajectory with a
                                 .json sidecar. manifest.json lists every file
                                 with its sha256 and its original name.
    data/scenarios/dsl_probe/    the program each variant ran. Every trace is
                                 tied to its program by sha256(program source)
                                 [:16], which must equal the hash of the
                                 committed .bt file; a mismatch is an error.
    data/certificates/*.json     the 20 counterexamples. Every trace is tied to
                                 its certificate by param_hash(evaluation_params).
    config/contracts.yaml, data/scenarios/junction.yaml,
    data/results/control_map.json (read by src/stl.py for C5)

SCORING (the campaign's own scorer and definitions, src/evaluate.py)
    rho        src/stl.compute_rho on the trajectory: the minimum over the five
               contracts, a vacuous contract keeping its 999.0 sentinel and
               being skipped in the argmin.
    resolved   rho >= 0.
    completed  "P4_settle" in the episode's phases_reached (sidecar
               result.meta). P4 is reached when the ego's route index passes the
               junction exit before the episode ends (src/carla_backend.py
               _phase_for), so "completed" means "cleared the junction exit
               within the time limit". Cross-checked here against the per-tick
               `phase` column of the trajectory.
    entered    not C2 vacuous, i.e. the ego was at some tick inside the conflict
               zone (a disc of conflict_zone_radius_m around the junction
               centre, config/contracts.yaml).

OUTPUTS
    data/results/dsl_probe_rescore.json      Table 4, per row and per variant,
                                             with per-episode values
    data/results/clean_repair_rescore.json   the clean repair on all 20
                                             counterexamples and its six repeats
    Neither file carries a timestamp or an absolute path, so a re-run on the
    same inputs rewrites them byte-identically.

CROSS-CHECKS (reported; a numeric disagreement makes the exit code 1)
    data/results/dsl_expressiveness.json      the earlier hand-written summary
    data/results/clean_repair_validation.json the earlier hand-written summary
    data/results/attempts.jsonl               the campaign's own record of the
                                              clean repair on its counterexample
    data/certificates/*.json                  the frozen baseline's recorded run
                                              on each counterexample
    paper/main.tex                            the Table 4 cells as printed

    Neither earlier summary had a producing script; this script is that script.
    Both are left unmodified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import sys

import pyarrow.parquet as pq
import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

import stl  # noqa: E402  (src/ on sys.path)
from config import param_hash  # noqa: E402

TRACES = REPO / "data" / "dsl_probe_traces"
PROBE = REPO / "data" / "scenarios" / "dsl_probe"
OUT_TABLE = REPO / "data" / "results" / "dsl_probe_rescore.json"
OUT_CLEAN = REPO / "data" / "results" / "clean_repair_rescore.json"
N_CE = 20
ROUND = 6                       # same rounding as the campaign's attempt records

# The clean repair: the single attempt that resolved, completed and broke nothing.
CLEAN_ATTEMPT = "F1__CE005_C1_5b773c94ec4bb251__s3"
CLEAN_CERT = "CE005_C1_5b773c94ec4bb251"

# Table 4 as printed in paper/main.tex (label tab:dsl), in order. `expect` is
# (resolved, completed) out of 20 and must hold for EVERY variant of the row;
# `entered` is checked where the paper states it ("never enters the junction").
ROWS = [
    {"key": "frozen_baseline", "label": "frozen baseline",
     "expect": (0, 2),
     "variants": [("frozen_baseline", "data/scenarios/baseline_program.bt",
                   "the frozen baseline, unmodified")]},
    {"key": "raise_gap_thresholds", "label": "raise gap thresholds (e.g. 5.5 -> 9.0)",
     "expect": (0, 3),
     "variants": [("raise_gap_thresholds", "data/scenarios/dsl_probe/fixA_bigger_gap.bt",
                   "OncomingGapExceeds 5.5 -> 9.0, 3.8 -> 6.0 and 6.5 -> 9.0 in the gap-guarded branches")]},
    {"key": "gap_guard_sweep", "label": "gap guard on committing branch, up to 15.0",
     "expect": (0, 2),
     "variants": [(f"gap_guard_sweep/gap_s_{v}", f"data/scenarios/dsl_probe/sweep_{v}.bt",
                   f"OncomingGapExceeds(gap_s={v}) added to the committing branch")
                  for v in ("5.5", "8.0", "10.0", "12.0", "15.0")]},
    {"key": "geometric_guard", "label": "geometric guard on committing branch",
     "expect": (0, 2),
     "variants": [
         ("geometric_guard/pathisclear_16m", "data/scenarios/dsl_probe/geometric_guard_16m.bt",
          "PathIsClear(dist_m=16.0) added to the committing branch"),
         ("geometric_guard/pathisclear_24m", "data/scenarios/dsl_probe/diag.bt",
          "PathIsClear(dist_m=24.0) added to the committing branch"),
         ("geometric_guard/pathisclear_32m", "data/scenarios/dsl_probe/geometric_guard_32m.bt",
          "PathIsClear(dist_m=32.0) added to the committing branch"),
         ("geometric_guard/green_and_pathisclear_24m", "data/scenarios/dsl_probe/pc.bt",
          "TrafficLightIsGreen and PathIsClear(dist_m=24.0) added to the committing branch"),
     ]},
    {"key": "geometric_guard_true_stop", "label": "geometric guard + true stop",
     "expect": (20, 0), "expect_entered": 0,
     "variants": [("geometric_guard_true_stop", "data/scenarios/dsl_probe/fixFULL.bt",
                   "PathIsClear(dist_m=24.0) on the committing branch and fallback "
                   "Decelerate(v_mps=0.0, decel_mps2=3.0)")]},
    {"key": "clean_repair", "label": "the model's clean repair, from F1",
     "expect": (20, 20),
     "variants": [("clean_repair", "data/scenarios/dsl_probe/clean_repair.bt",
                   f"the patched program of attempt {CLEAN_ATTEMPT}")]},
]
REPEATS = ("repeats", "data/scenarios/dsl_probe/clean_repair.bt")


def sha16(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def sha256_file(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def rel(p: pathlib.Path) -> str:
    return str(p.relative_to(REPO))


def r6(x):
    return None if x is None else round(float(x), ROUND)


class Fail(Exception):
    """Input inconsistency: the traces cannot be trusted to mean what they say."""


# ---------------------------------------------------------------------------
# loading and scoring
# ---------------------------------------------------------------------------
def load_certificates() -> dict[str, dict]:
    by_hash = {}
    for f in sorted((REPO / "data" / "certificates").glob("*.json")):
        c = json.loads(f.read_text())
        h = param_hash(c["evaluation_params"])
        if h in by_hash:
            raise Fail(f"two certificates share parameter hash {h}")
        by_hash[h] = c
    if len(by_hash) != N_CE:
        raise Fail(f"expected {N_CE} certificates, found {len(by_hash)}")
    return by_hash


def check_manifest() -> dict:
    """Every file in data/dsl_probe_traces/ is listed, present and unaltered."""
    mf = TRACES / "manifest.json"
    if not mf.exists():
        raise Fail(f"{rel(mf)} missing")
    m = json.loads(mf.read_text())
    listed = {e["path"]: e for e in m["files"]}
    present = {str(p.relative_to(TRACES)) for p in TRACES.rglob("*")
               if p.is_file() and p.name != "manifest.json"}
    if set(listed) != present:
        raise Fail(f"manifest mismatch: unlisted {sorted(present - set(listed))[:5]}, "
                   f"missing {sorted(set(listed) - present)[:5]}")
    bad = [p for p, e in listed.items() if sha256_file(TRACES / p) != e["sha256"]]
    if bad:
        raise Fail(f"sha256 mismatch against manifest: {bad[:5]}")
    return {"files": len(listed), "bytes": sum(e["bytes"] for e in listed.values()),
            "sha256_verified": len(listed)}


def score_episode(sidecar: pathlib.Path, want_sha: str, certs: dict, contracts: dict,
                  junction: dict) -> dict:
    side = json.loads(sidecar.read_text())
    pq_path = sidecar.with_suffix(".parquet")
    if not pq_path.exists():
        raise Fail(f"{rel(sidecar)}: no trajectory beside it")
    pmeta = {k.decode(): v.decode() for k, v in (pq.read_schema(pq_path).metadata or {}).items()}

    # Provenance: the program that drove this episode is the committed one.
    src = side.get("program_source") or ""
    if not (side.get("program_sha") == sha16(src) == want_sha == pmeta.get("program_sha")):
        raise Fail(f"{rel(sidecar)}: program {side.get('program_sha')} (source hash {sha16(src)}, "
                   f"parquet {pmeta.get('program_sha')}) is not the committed {want_sha}")
    if pmeta.get("param_hash") != side["param_hash"] or side["result"]["param_hash"] != side["param_hash"]:
        raise Fail(f"{rel(sidecar)}: parameter hash differs between sidecar and trajectory")
    cert = certs.get(side["param_hash"])
    if cert is None:
        raise Fail(f"{rel(sidecar)}: parameter hash {side['param_hash']} matches no certificate")
    if param_hash(side["result"]["scenario_params"]) != side["param_hash"]:
        raise Fail(f"{rel(sidecar)}: scenario_params do not hash to param_hash")

    df, _ = stl.load_trace(pq_path)
    r = stl.compute_rho(df, contracts, junction)
    phases = list(side["result"]["meta"].get("phases_reached") or [])
    phases_in_trace = sorted(set(df["phase"].dropna().astype(str)))
    if sorted(phases) != phases_in_trace:
        raise Fail(f"{rel(sidecar)}: phases_reached {phases} disagree with trace {phases_in_trace}")
    return {
        "file": str(sidecar.relative_to(TRACES)),
        "episode_id": side["episode_id"],
        "certificate_id": cert["certificate_id"],
        "status": side["result"]["status"],
        "rho": r6(r.rho),
        "argmin_contract": r.contract,
        "per_contract": {k: r6(v.rho) for k, v in r.per_contract.items()},
        "vacuous": sorted(k for k, v in r.per_contract.items() if v.vacuous),
        "phases_reached": phases,
        "resolved": bool(r.rho >= 0.0),
        "completed": "P4_settle" in phases,
        "entered": not r.per_contract["C2"].vacuous,
        "_rho_raw": float(r.rho),
        "_rho4_raw": float(r.per_contract["C4"].rho) if "C4" in r.per_contract else None,
    }


def score_dir(subdir: str, program: str, certs, contracts, junction, require_all_certs=True):
    d = TRACES / subdir
    prog = REPO / program
    want = sha16(prog.read_text())
    sidecars = sorted(d.glob("*.json"))
    if not sidecars:
        raise Fail(f"no episodes in {rel(d)}")
    eps = [score_episode(s, want, certs, contracts, junction) for s in sidecars]
    if require_all_certs:
        ids = [e["certificate_id"] for e in eps]
        if len(eps) != N_CE or len(set(ids)) != N_CE:
            raise Fail(f"{rel(d)}: {len(eps)} episodes on {len(set(ids))} distinct certificates, "
                       f"expected {N_CE} on {N_CE}")
    return {"directory": str(d.relative_to(REPO)), "program": program, "program_sha": want,
            "n": len(eps),
            "resolved": sum(e["resolved"] for e in eps),
            "completed": sum(e["completed"] for e in eps),
            "entered": sum(e["entered"] for e in eps),
            "resolved_and_completed": sum(e["resolved"] and e["completed"] for e in eps),
            "episodes": sorted(eps, key=lambda e: e["certificate_id"])}


def public(ep: dict) -> dict:
    return {k: v for k, v in ep.items() if not k.startswith("_")}


def frac(k: int, n: int = N_CE) -> str:
    return f"{k}/{n}"


# ---------------------------------------------------------------------------
# paper/main.tex: the Table 4 cells as printed
# ---------------------------------------------------------------------------
def paper_table4() -> list[tuple[int, int]] | str:
    tex = REPO / "paper" / "main.tex"
    if not tex.exists():
        return "paper/main.tex absent"
    t = tex.read_text()
    i = t.find(r"\label{tab:dsl}")
    if i < 0:
        return r"\label{tab:dsl} not found"
    j, k = t.find(r"\begin{tabular}", i), t.find(r"\end{tabular}", i)
    if j < 0 or k < 0:
        return "tabular for tab:dsl not found"
    cells = []
    for line in t[j:k].split(r"\\"):
        fr = re.findall(r"(\d+)/20", line)
        if len(fr) == 2:
            cells.append((int(fr[0]), int(fr[1])))
    return cells


# ---------------------------------------------------------------------------
# cross-checks against the earlier hand-written summaries
# ---------------------------------------------------------------------------
def xcheck_dsl_expressiveness(rows: dict) -> list[dict]:
    d = json.loads((REPO / "data" / "results" / "dsl_expressiveness.json").read_text())
    out = []
    # variant text in the JSON -> (row key, field, value recomputed here)
    pairs = [
        ("raise OncomingGapExceeds", "raise_gap_thresholds"),
        ("add OncomingGapExceeds guard", "gap_guard_sweep"),
        ("add PathIsClear to branch C", "geometric_guard"),
        ("true stop", "geometric_guard_true_stop"),
    ]
    for v in d["variants_tested"]:
        hit = [rk for needle, rk in pairs if needle in v["fix"]]
        if not hit:
            out.append({"variant": v["fix"], "committed": {k: v[k] for k in ("fixed", "completed") if k in v},
                        "status": "NOT RE-SCORED",
                        "why": "not a Table 4 row; its trajectories are not in data/dsl_probe_traces/"})
            continue
        row = rows[hit[0]]
        for field, here in (("fixed", "resolved"), ("completed", "completed")):
            if field not in v:
                continue
            got = sorted({frac(var[here]) for var in row["variants"]})
            ok = got == [v[field]]
            out.append({"variant": v["fix"], "field": field, "committed": v[field],
                        "recomputed_per_variant": {var["directory"]: frac(var[here])
                                                   for var in row["variants"]},
                        "status": "MATCH" if ok else "MISMATCH"})
    # The PathIsClear entry names three distances; the shipped family has four variants.
    out.append({"variant": "add PathIsClear to branch C, 16/24/32 m", "status": "NOTE",
                "why": "the row also includes a fourth variant, TrafficLightIsGreen plus "
                       "PathIsClear(24 m) (data/scenarios/dsl_probe/pc.bt); it gives the same "
                       "counts as the other three"})
    # The textual finding and implication, tested against the re-scored rows.
    hand = [k for k in rows if k != "clean_repair"]
    both = sum(var["resolved_and_completed"] for k in hand for var in rows[k]["variants"])
    clean = rows["clean_repair"]["variants"][0]
    out.append({"field": "finding",
                "committed": d["finding"],
                "recomputed": f"episodes of the hand-written programs that both resolved and "
                              f"completed: {both} of "
                              f"{sum(var['n'] for k in hand for var in rows[k]['variants'])}",
                "status": "MATCH" if both == 0 else "MISMATCH",
                "why": "true of the hand-written family the sentence refers to"})
    out.append({"field": "implication",
                "committed": d["implication"],
                "recomputed": f"the clean repair resolves {frac(clean['resolved'])} and completes "
                              f"{frac(clean['completed'])}",
                "status": "SUPERSEDED",
                "why": "the clean repair is a valid program in the same language that satisfies "
                       "the contracts and completes the manoeuvre, so refusal is not the only "
                       "expressible fix. Textual; does not affect the exit code"})
    return out


def xcheck_clean_validation(gen: dict, rep: dict) -> list[dict]:
    v = json.loads((REPO / "data" / "results" / "clean_repair_validation.json").read_text())
    t1, t2 = v["test_1_generalisation"], v["test_2_rss_stability"]
    own, oth = gen["own_counterexample"], gen["other_19"]
    checks = [
        ("test_1.own_counterexample.resolved", t1["own_counterexample"]["resolved"], own["resolved"]),
        ("test_1.own_counterexample.completed", t1["own_counterexample"]["completed"], own["completed"]),
        ("test_1.own_counterexample.rho", t1["own_counterexample"]["rho"], own["rho"]),
        ("test_1.own_counterexample.binding", t1["own_counterexample"]["binding"], own["argmin_contract"]),
        ("test_1.other_19_never_shown.resolved", t1["other_19_never_shown"]["resolved"], oth["resolved"]),
        ("test_1.other_19_never_shown.completed", t1["other_19_never_shown"]["completed"], oth["completed"]),
        ("test_1.other_19_never_shown.entered", t1["other_19_never_shown"]["entered"], oth["entered"]),
        ("test_1.other_19_never_shown.binding", t1["other_19_never_shown"]["binding"], oth["binding"]),
        ("test_1.all_20.resolved_and_completed", t1["all_20"]["resolved_and_completed"],
         gen["all_20"]["resolved_and_completed"]),
        ("test_2.repeats", t2["repeats"], rep["n"]),
        ("test_2.rho_spread", t2["rho_spread"], rep["rho_spread"]),
        ("test_2.C4_spread_m", t2["C4_spread_m"], rep["rho4_spread_m"]),
        ("test_2.C4_ever_binding", t2["C4_ever_binding"], rep["c4_ever_binding"]),
        ("test_2.resolved_all_repeats", t2["resolved_all_repeats"], rep["resolved_all"]),
        ("test_2.completed_all_repeats", t2["completed_all_repeats"], rep["completed_all"]),
    ]
    return [{"field": f, "committed": c, "recomputed": g, "status": "MATCH" if c == g else "MISMATCH"}
            for f, c, g in checks]


def xcheck_attempt_record(ep: dict) -> dict:
    """The campaign's own evaluation of the clean repair on its counterexample."""
    rec = None
    for line in (REPO / "data" / "results" / "attempts.jsonl").read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            if r["attempt_id"] == CLEAN_ATTEMPT:
                rec = r
                break
    if rec is None:
        return {"status": "MISMATCH", "why": f"{CLEAN_ATTEMPT} not in attempts.jsonl"}
    prog_ok = sha16(rec["bt_source_after"]) == sha16((PROBE / "clean_repair.bt").read_text())
    fields = {"rho": "rho_after", "C1": "rho1_after", "C2": "rho2_after", "C3": "rho3_after",
              "C4": "rho4_after", "C5": "rho5_after"}
    here = {"rho": ep["rho"], **ep["per_contract"]}
    deltas = {k: abs(here[k] - rec[f]) for k, f in fields.items()}
    tol = 1e-5
    same = (prog_ok and max(deltas.values()) <= tol
            and rec["resolved"] == ep["resolved"] and rec["ce_completed"] == ep["completed"]
            and rec["ce_entered_conflict_zone"] == ep["entered"]
            and rec["argmin_contract_after"] == ep["argmin_contract"])
    return {"attempt_id": CLEAN_ATTEMPT,
            "program_identical_to_bt_source_after": prog_ok,
            "campaign": {"rho": rec["rho_after"], **{k: rec[f] for k, f in fields.items() if k != "rho"},
                         "argmin": rec["argmin_contract_after"], "resolved": rec["resolved"],
                         "completed": rec["ce_completed"], "entered": rec["ce_entered_conflict_zone"]},
            "rescored": {"rho": ep["rho"], **ep["per_contract"], "argmin": ep["argmin_contract"],
                         "resolved": ep["resolved"], "completed": ep["completed"],
                         "entered": ep["entered"]},
            "max_abs_delta": r6(max(deltas.values())), "tolerance": tol,
            "status": "MATCH" if same else "MISMATCH"}


def xcheck_baseline_vs_certificates(row: dict, certs: dict) -> dict:
    """The frozen baseline re-run against each certificate's own recorded run."""
    by_id = {c["certificate_id"]: c for c in certs.values()}
    per, worst, sign_ok, flags_ok = [], 0.0, 0, 0
    for ep in row["variants"][0]["episodes"]:
        c = by_id[ep["certificate_id"]]
        d = abs(ep["rho"] - c["rho"])
        worst = max(worst, d)
        s = (ep["rho"] >= 0) == (c["rho"] >= 0)
        f = (("P4_settle" in c["phases_reached"]) == ep["completed"]
             and ("C2" not in c["vacuous_contracts"]) == ep["entered"])
        sign_ok += s
        flags_ok += f
        if d > 1e-6 or not s or not f:
            per.append({"certificate_id": c["certificate_id"], "certificate_rho": c["rho"],
                        "rescored_rho": ep["rho"], "abs_delta": r6(d),
                        "certificate_argmin": c["rho_argmin_contract"],
                        "rescored_argmin": ep["argmin_contract"]})
    ok = sign_ok == N_CE and flags_ok == N_CE
    return {"what": "frozen-baseline trajectories here were re-simulated after the certificates "
                    "were banked; compares their rho, completion and entry with each certificate's "
                    "recorded run",
            "resolved_sign_agrees": frac(sign_ok), "completed_and_entered_agree": frac(flags_ok),
            "max_abs_rho_delta": r6(worst), "differences_above_1e-6": per,
            "status": "MATCH" if ok else "MISMATCH"}


# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--no-write", action="store_true", help="score and compare, write nothing")
    args = ap.parse_args()

    contracts_path = REPO / "config" / "contracts.yaml"
    junction_path = REPO / "data" / "scenarios" / "junction.yaml"
    contracts = yaml.safe_load(contracts_path.read_text())     # committed file only
    junction = stl.load_junction(junction_path)

    try:
        manifest = check_manifest()
        certs = load_certificates()
        rows = {}
        for row in ROWS:
            variants = []
            for subdir, program, desc in row["variants"]:
                v = score_dir(subdir, program, certs, contracts, junction)
                v["description"] = desc
                variants.append(v)
            rows[row["key"]] = {"label": row["label"], "variants": variants}
        rep_eps = score_dir(REPEATS[0], REPEATS[1], certs, contracts, junction,
                            require_all_certs=False)["episodes"]
    except Fail as e:
        print(f"FAIL: {e}")
        return 1

    # Failures are kept per output file, so each file's `status` reflects only
    # what that file reports.
    fail_table: list[str] = []
    fail_clean: list[str] = []

    # ---- Table 4 --------------------------------------------------------------
    table = []
    paper = paper_table4()
    for i, row in enumerate(ROWS):
        rr = rows[row["key"]]
        exp_r, exp_c = row["expect"]
        per_var = [(v["resolved"], v["completed"], v["entered"]) for v in rr["variants"]]
        ok = all((r, c) == (exp_r, exp_c) for r, c, _ in per_var)
        if "expect_entered" in row:
            ok = ok and all(e == row["expect_entered"] for _, _, e in per_var)
        paper_cell = paper[i] if isinstance(paper, list) and i < len(paper) else None
        if isinstance(paper, list) and paper_cell != (exp_r, exp_c):
            ok = False
        status = "MATCH" if ok else "MISMATCH"
        if not ok:
            fail_table.append(f"Table 4 row '{row['label']}'")
        table.append({
            "row": row["label"], "key": row["key"],
            "paper": {"resolved": frac(exp_r), "completed": frac(exp_c),
                      **({"entered": frac(row["expect_entered"])} if "expect_entered" in row else {})},
            "paper_tex_cells": (frac(paper_cell[0]) + ", " + frac(paper_cell[1])) if paper_cell else None,
            "recomputed_per_variant": [
                {"directory": v["directory"], "program": v["program"], "program_sha": v["program_sha"],
                 "description": v["description"], "resolved": frac(v["resolved"]),
                 "completed": frac(v["completed"]), "entered": frac(v["entered"])}
                for v in rr["variants"]],
            "status": status})
    if isinstance(paper, list) and len(paper) != len(ROWS):
        fail_table.append(f"paper/main.tex Table 4 has {len(paper)} rows, expected {len(ROWS)}")

    # ---- clean repair: all 20, own counterexample, the other 19 -------------
    clean = rows["clean_repair"]["variants"][0]
    own = next(e for e in clean["episodes"] if e["certificate_id"] == CLEAN_CERT)
    others = [e for e in clean["episodes"] if e["certificate_id"] != CLEAN_CERT]
    binding = {}
    for e in others:
        binding[e["argmin_contract"]] = binding.get(e["argmin_contract"], 0) + 1
    gen = {
        "own_counterexample": {k: own[k] for k in ("certificate_id", "rho", "argmin_contract",
                                                   "per_contract", "resolved", "completed", "entered")},
        "other_19": {"resolved": frac(sum(e["resolved"] for e in others), len(others)),
                     "completed": frac(sum(e["completed"] for e in others), len(others)),
                     "entered": frac(sum(e["entered"] for e in others), len(others)),
                     "binding": dict(sorted(binding.items())),
                     "c1_binding": {e["certificate_id"]: e["rho"] for e in others
                                    if e["argmin_contract"] == "C1"}},
        "all_20": {"resolved": frac(clean["resolved"]), "completed": frac(clean["completed"]),
                   "entered": frac(clean["entered"]),
                   "resolved_and_completed": frac(clean["resolved_and_completed"])},
    }

    # ---- six repeats on the clean repair's own counterexample -----------------
    rep_ids = {e["certificate_id"] for e in rep_eps}
    rhos = [e["_rho_raw"] for e in rep_eps]
    rho4s = [e["_rho4_raw"] for e in rep_eps]
    rep = {
        "n": len(rep_eps),
        "certificate_id": sorted(rep_ids),
        "rho": [e["rho"] for e in rep_eps],
        "rho4_m": [e["per_contract"]["C4"] for e in rep_eps],
        "argmin_contract": [e["argmin_contract"] for e in rep_eps],
        "rho_spread": max(rhos) - min(rhos),
        "rho4_spread_m": max(rho4s) - min(rho4s),
        "c4_ever_binding": any(e["argmin_contract"] == "C4" for e in rep_eps),
        "resolved_all": all(e["resolved"] for e in rep_eps),
        "completed_all": all(e["completed"] for e in rep_eps),
        "entered_all": all(e["entered"] for e in rep_eps),
        "equal_to_20_counterexample_run": all(abs(x - own["_rho_raw"]) == 0.0 for x in rhos),
    }
    val_ok = (rep["n"] == 6 and rep_ids == {CLEAN_CERT} and rep["rho_spread"] == 0.0
              and rep["rho4_spread_m"] == 0.0 and not rep["c4_ever_binding"]
              and rep["resolved_all"] and rep["completed_all"])
    if not val_ok:
        fail_clean.append("six-repeat validation")
    if not (clean["resolved"] == clean["completed"] == clean["entered"] == N_CE):
        fail_clean.append("clean repair on all 20 counterexamples")

    # ---- cross-checks ------------------------------------------------------------
    x_dsl = xcheck_dsl_expressiveness(rows)
    x_val = xcheck_clean_validation(gen, rep)
    x_att = xcheck_attempt_record(own)
    x_base = xcheck_baseline_vs_certificates(rows["frozen_baseline"], certs)
    for x in x_dsl:
        if x["status"] == "MISMATCH":
            fail_table.append(f"dsl_expressiveness.json: {x.get('variant') or x.get('field')}")
    if x_base["status"] == "MISMATCH":
        fail_table.append("frozen baseline vs certificates")
    for x in x_val:
        if x["status"] == "MISMATCH":
            fail_clean.append(f"clean_repair_validation.json: {x['field']}")
    if x_att["status"] == "MISMATCH":
        fail_clean.append("attempts.jsonl clean-repair record")
    failures = fail_table + fail_clean

    inputs = {rel(p): sha256_file(p) for p in
              [contracts_path, junction_path, REPO / "data" / "results" / "control_map.json"]
              + sorted({REPO / prog for row in ROWS for _, prog, _ in row["variants"]})}
    head = {"script": "scripts/rescore_dsl_probes.py",
            "scorer": "src/stl.py compute_rho; resolved = rho >= 0; completed = 'P4_settle' in "
                      "phases_reached; entered = C2 not vacuous (src/evaluate.py)",
            "inputs_sha256": inputs,
            "traces": {"directory": "data/dsl_probe_traces", **manifest}}

    out_table = {**head,
                 "table4": table,
                 "cross_check_dsl_expressiveness_json": x_dsl,
                 "cross_check_frozen_baseline_vs_certificates": x_base,
                 "rows": {k: {"label": v["label"],
                              "variants": [{**{kk: vv for kk, vv in var.items() if kk != "episodes"},
                                            "episodes": [public(e) for e in var["episodes"]]}
                                           for var in v["variants"]]}
                          for k, v in rows.items()},
                 "status": "MATCH" if not fail_table else "MISMATCH",
                 "failures": fail_table}
    out_clean = {**head,
                 "program": "data/scenarios/dsl_probe/clean_repair.bt",
                 "program_sha": clean["program_sha"],
                 "attempt_id": CLEAN_ATTEMPT,
                 "generalisation": gen,
                 "repeats": {**rep, "episodes": [public(e) for e in rep_eps]},
                 "cross_check_clean_repair_validation_json": x_val,
                 "cross_check_attempts_jsonl": x_att,
                 "episodes": [public(e) for e in clean["episodes"]],
                 "status": "MATCH" if not fail_clean else "MISMATCH",
                 "failures": fail_clean}

    # ---- report ------------------------------------------------------------------
    print(f"traces: {manifest['files']} files, {manifest['bytes'] / 1e6:.1f} MB, "
          f"sha256 verified against manifest")
    print(f"paper/main.tex Table 4 cells: {paper if isinstance(paper, str) else 'read, ' + str(len(paper)) + ' rows'}")
    print()
    print(f"{'Table 4 row':44} {'variant':26} {'resolved':>8} {'completed':>9} {'entered':>7}  paper")
    for t in table:
        for j, v in enumerate(t["recomputed_per_variant"]):
            name = v["directory"].split("/")[-1] if len(t["recomputed_per_variant"]) > 1 else ""
            lab = t["row"] if j == 0 else ""
            exp = f"{t['paper']['resolved']}, {t['paper']['completed']}"
            pp = ""
            if j == 0:
                # The cells as read from paper/main.tex when available, else the
                # transcription above; both are compared and must agree.
                pp = t["paper_tex_cells"] or exp
                if t["paper_tex_cells"] and t["paper_tex_cells"] != exp:
                    pp += f" (tex) vs {exp} (transcribed)"
                if "entered" in t["paper"]:
                    pp += f", entered {t['paper']['entered']}"
            print(f"{lab:44} {name:26} {v['resolved']:>8} {v['completed']:>9} {v['entered']:>7}  {pp}")
        print(f"{'':44} {'-> ' + t['status']}")
    print()
    print(f"clean repair, own counterexample {own['certificate_id']}: rho {own['rho']} "
          f"(binding {own['argmin_contract']}), resolved {own['resolved']}, completed {own['completed']}")
    print(f"clean repair, other 19: resolved {gen['other_19']['resolved']}, completed "
          f"{gen['other_19']['completed']}, entered {gen['other_19']['entered']}, binding "
          f"{gen['other_19']['binding']}")
    print(f"six repeats on {', '.join(rep['certificate_id'])}: rho {rep['rho']}")
    print(f"  rho4 (m) {rep['rho4_m']}")
    print(f"  spread rho {rep['rho_spread']}, spread rho4 {rep['rho4_spread_m']} m, "
          f"argmin {sorted(set(rep['argmin_contract']))}, C4 ever binding {rep['c4_ever_binding']}, "
          f"resolved all {rep['resolved_all']}, completed all {rep['completed_all']}  "
          f"-> {'MATCH' if val_ok else 'MISMATCH'}")
    print()
    print("cross-check data/results/clean_repair_validation.json:")
    for x in x_val:
        print(f"  {x['status']:9} {x['field']}: committed {x['committed']}, recomputed {x['recomputed']}")
    print(f"cross-check data/results/attempts.jsonl {CLEAN_ATTEMPT}: {x_att['status']} "
          f"(program identical {x_att['program_identical_to_bt_source_after']}, "
          f"max |delta| {x_att['max_abs_delta']})")
    print("cross-check data/results/dsl_expressiveness.json:")
    for x in x_dsl:
        if "recomputed_per_variant" in x:      # a numeric cell of one variant entry
            got = sorted(set(x["recomputed_per_variant"].values()))
            line = (f"{x['variant']} [{x['field']}]: committed {x['committed']}, "
                    f"recomputed {', '.join(got)} in every variant")
        elif "variant" in x:                   # an entry not re-scored, or a note
            line = x["variant"]
        else:                                  # the textual finding / implication
            line = f"{x['field']}: {x['recomputed']}"
        print(f"  {x['status']:13} {line}")
        if "why" in x and x["status"] != "MATCH":
            print(f"  {'':13} ({x['why']})")
    print(f"cross-check frozen baseline vs certificates: {x_base['status']} (resolved sign agrees "
          f"{x_base['resolved_sign_agrees']}, completion and entry agree "
          f"{x_base['completed_and_entered_agree']}, max |rho delta| {x_base['max_abs_rho_delta']})")
    for dd in x_base["differences_above_1e-6"]:
        print(f"  {dd['certificate_id']}: certificate rho {dd['certificate_rho']} ({dd['certificate_argmin']}), "
              f"re-run {dd['rescored_rho']} ({dd['rescored_argmin']}), |delta| {dd['abs_delta']}")

    if not args.no_write:
        OUT_TABLE.write_text(json.dumps(out_table, indent=1) + "\n")
        OUT_CLEAN.write_text(json.dumps(out_clean, indent=1) + "\n")
        print(f"\nwrote {rel(OUT_TABLE)} and {rel(OUT_CLEAN)}")
    print()
    if failures:
        print("RESULT: MISMATCH: " + "; ".join(failures))
        return 1
    print("RESULT: Table 4 and the six-repeat validation reproduce exactly; all numeric cross-checks agree")
    return 0


if __name__ == "__main__":
    sys.exit(main())
