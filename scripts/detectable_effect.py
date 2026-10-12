#!/usr/bin/env python3
"""Detectable-effect (power) analysis for the repair-success comparisons.

WHAT THIS IS, AND WHAT IT IS NOT.

This script answers a question about the DESIGN, not about the data. Suppose a
feedback condition truly differed from the reference condition, F3, by d
percentage points in repair success. How often would the decision rule the
paper uses have declared that difference detected? The answer depends on a
model of how the data were generated. The model is stated below, each part of
it is either varied or named as fixed, and every number this script writes is
conditional on it.

It is NOT a measured resolution of the experiment and it is NOT a noise floor.
An earlier draft argued from the F4a-F3 difference that 5.0 points was the
experiment's noise floor. That argument was wrong (see the
scripts/uncertainty.py docstring) and nothing here revives
it. A minimum detectable effect (MDE) moves when the assumptions move, and it
says nothing about whether smaller true effects exist.

THE DECISION RULE, taken from scripts/uncertainty.py rather than reinvented.

  * resample the 20 certificates with replacement, carrying every attempt of a
    resampled certificate in every condition;
  * recompute both rates on the resampled attempts and take the difference
    (condition - F3) within the same resample, which keeps the pairing;
  * 95% percentile interval over 10000 resamples;
  * 'detected' when the interval excludes 0 (uncertainty.py prints
    'CI includes 0' when lo <= 0 <= hi). No multiplicity adjustment.

EXACT FORM OF THE RULE. Every certificate carries exactly 3 attempts per
condition, so a resampled difference is (1/60) * sum of 20 draws from the
per-certificate differences D_j = s_cond,j - s_ref,j, with D_j in {-3..3}. The
bootstrap distribution therefore depends only on how many certificates take
each of the 7 values, and there are C(26,6) = 230,230 such configurations. For
each one the bootstrap distribution is computed EXACTLY, as a 20-fold
convolution of the empirical distribution of D. That is the B -> infinity limit
of the paper's rule:

    lower bound > 0  <=>  P*(resampled difference <= 0) < 0.025
    upper bound < 0  <=>  P*(resampled difference >= 0) < 0.025

It removes bootstrap Monte Carlo error from the power estimates. The paper's
finite-B rule is a Monte Carlo approximation of it, and the VALIDATION block
checks agreement three ways: (1) a literal reimplementation of the finite-B
rule reproduces data/results/uncertainty.json exactly from the same seed;
(2) the paper's own function, uncertainty.cluster_bootstrap, run on synthetic
datasets, agrees with the literal reimplementation; (3) the literal B = 10000
rule and the exact table agree on thousands of simulated datasets.

DATA-GENERATING MODEL (the assumptions).

  A1  20 certificates, 3 replicates per (condition, certificate) cell, as run.
  A2  Replicates are independent Bernoulli draws given the cell's success
      probability. (`seed` is a replicate index; 3.00 distinct programs per
      cell were measured.)
  A3  Certificate heterogeneity: the cell success probability is Beta with mean
      p and intra-cluster correlation ICC = 1/(a+b+1), the same ICC in both
      arms. ICC is the correlation between two replicate outcomes in the same
      cell. Grid: ICC in {0, 0.1, 0.3}, plus 0.5 as a sensitivity.
  A4  Pairing: a certificate's difficulty is coupled across the two conditions
      by a Gaussian copula on the Beta quantiles with correlation r. r = 1
      ('shared', the natural reference for a paired design) means a
      certificate is equally hard, in rank, for both conditions; r = 0
      ('independent') means difficulty is unrelated across conditions; r = 0.5
      is reported in between. Negative coupling (conditions succeeding on
      different certificates) is not simulated and would lower power further.
  A5  The reference rate p0 is treated as known. Values: the observed F3 rate
      (2/60 for both outcomes), 0.05, and 3/300 (all-condition pooled rate of
      resolved_and_completed) as a sensitivity.
  A6  The effect is a shift in mean success probability, p1 = p0 + d.
  A7  A single comparison against F3 at two-sided 95%, as in the paper.
      Bonferroni over the four comparisons against F3 on one outcome, and over
      all 17 paired differences the analysis computes, are reported as
      sensitivities, not as what the paper did.

Common random numbers: within one (p0, ICC, coupling) configuration every d
reuses the same latent draws, so detection is monotone in d per simulated
experiment and the power curve is monotone. Monte Carlo standard errors are
reported for every power value.

ADDED IN VERIFICATION (9 Oct 2026; main results unchanged; the paper's
Appendix E reports the result):

  * monte_carlo_replicate: every setting is re-simulated with a second,
    independent seed (--mc-seed, default 4242) and the change in each MDE is
    recorded. Pointwise power SEs do not by themselves bound the error of an
    interpolated MDE, and two runs with the SAME seed only show determinism.
  * beta_parametrisation_check: simulated mean and replicate-replicate
    correlation of the Beta-Bernoulli cells against their targets, so the
    check quoted in the evidence file is reproducible from this script.
  * success_pattern_likelihood: probability, under each (ICC, coupling)
    setting, of the pattern the success outcome itself shows (no cell with
    more than one success, no certificate on which both F1 and F3 succeed),
    given the observed totals. Indicative evidence on A3/A4 only.
  * shared_coupling_concentration: deterministic quadrature showing how the
    improvement is spread over certificates at each shared-coupling MDE.

    .venv/bin/python scripts/detectable_effect.py [--n-sim 20000] [--workers 24]

Writes data/results/detectable_effect.json. No CARLA, no LLM calls: reads only
data/results/attempts.jsonl and data/results/uncertainty.json.
"""
from __future__ import annotations

import argparse
import collections
import itertools
import json
import multiprocessing as mp
import pathlib
import subprocess
import sys
import time
from fractions import Fraction

import numpy as np
from scipy import optimize, special, stats

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import uncertainty  # noqa: E402  (the paper's own bootstrap; imported, never modified)

K = 20                       # certificates
R = 3                        # replicates per (condition, certificate) cell
N_PER_ARM = K * R            # 60 attempts per condition
VALS = np.arange(-R, R + 1)  # possible per-certificate differences, -3..3
NV = len(VALS)               # 7
ALPHA = 0.05
N_COMPARISONS = 4            # F1, F2, F4a, F4b each against F3
N_COMPARISONS_ALL = 17       # every paired difference the paper's analysis computes
                             # (16 against F3 over four outcomes, plus F1 - F2 on
                             # structural edits; see data/results/uncertainty.json "multiplicity")
TARGET_POWER = 0.80
BOOT_B = 10000               # the paper's number of resamples
BASE = 21                    # count-vector encoding base (counts are 0..20)

OUTCOMES = {
    "resolved_ex_refusal": lambda r: bool(r.get("resolved"))
    and not r.get("resolved_by_refusal"),
    "resolved_and_completed": lambda r: bool(r.get("resolved_and_completed")),
}

TABLE: dict = {}  # filled in main() before workers fork


# ----------------------------------------------------------------------------
# The exact decision table
# ----------------------------------------------------------------------------
def enumerate_count_vectors(k: int = K, nv: int = NV) -> np.ndarray:
    """All ways to place k certificates into nv difference values (stars and bars)."""
    out = []
    for bars in itertools.combinations(range(k + nv - 1), nv - 1):
        prev, c = -1, []
        for b in bars:
            c.append(b - prev - 1)
            prev = b
        c.append(k + nv - 2 - prev)
        out.append(c)
    return np.asarray(out, dtype=np.int64)


def encode(counts: np.ndarray) -> np.ndarray:
    return counts @ (BASE ** np.arange(NV, dtype=np.int64))


def exact_tails_fraction(counts) -> tuple[Fraction, Fraction]:
    """P*(S<=0), P*(S>=0) in exact rational arithmetic, for borderline rows."""
    poly = [int(c) for c in counts]  # coefficient of x^(v+R)
    acc = [1]
    for _ in range(K):
        new = [0] * (len(acc) + len(poly) - 1)
        for i, a in enumerate(acc):
            if a:
                for j, b in enumerate(poly):
                    if b:
                        new[i + j] += a * b
        acc = new
    total = K ** K
    zero = K * R  # index of S = 0
    return Fraction(sum(acc[: zero + 1]), total), Fraction(sum(acc[zero:]), total)


def build_table() -> dict:
    """Exact bootstrap tail probabilities for every possible configuration."""
    counts = enumerate_count_vectors()
    keys = encode(counts)
    order = np.argsort(keys)
    counts, keys = counts[order], keys[order]
    p_le0 = np.empty(len(counts))
    p_ge0 = np.empty(len(counts))
    nfft = 128  # >= K*(NV-1)+1 = 121, so no wrap-around
    zero = K * R
    for s in range(0, len(counts), 40000):
        pmf1 = counts[s:s + 40000] / K
        f = np.fft.rfft(pmf1, n=nfft, axis=1) ** K
        pmf = np.fft.irfft(f, n=nfft, axis=1)[:, : K * (NV - 1) + 1]
        p_le0[s:s + 40000] = pmf[:, : zero + 1].sum(1)
        p_ge0[s:s + 40000] = pmf[:, zero:].sum(1)
    thresholds = [ALPHA / 2, ALPHA / 2 / N_COMPARISONS, ALPHA / 2 / N_COMPARISONS_ALL]
    n_exact = 0
    for thr in thresholds:
        for arr in (p_le0, p_ge0):
            for i in np.flatnonzero(np.abs(arr - thr) < 1e-9):
                le, ge = exact_tails_fraction(counts[i])
                p_le0[i], p_ge0[i] = float(le), float(ge)
                n_exact += 1
    # sanity: a few rows against exact rational arithmetic
    rng = np.random.default_rng(12345)
    max_err = 0.0
    for i in rng.choice(len(counts), 200, replace=False):
        le, ge = exact_tails_fraction(counts[i])
        max_err = max(max_err, abs(float(le) - p_le0[i]), abs(float(ge) - p_ge0[i]))
    sum_d = counts @ VALS
    det_pos = p_le0 < ALPHA / 2
    det_neg = p_ge0 < ALPHA / 2
    det_pos_b = p_le0 < ALPHA / 2 / N_COMPARISONS
    det_neg_b = p_ge0 < ALPHA / 2 / N_COMPARISONS
    det_pos_b17 = p_le0 < ALPHA / 2 / N_COMPARISONS_ALL
    det_neg_b17 = p_ge0 < ALPHA / 2 / N_COMPARISONS_ALL
    min_pos = int(sum_d[det_pos].min())
    n_favouring = counts[:, R + 1:].sum(1)  # certificates with D_j > 0
    n_against = counts[:, :R].sum(1)        # certificates with D_j < 0
    witness = counts[det_pos][np.argmin(sum_d[det_pos])]
    return {
        "counts": counts, "keys": keys, "p_le0": p_le0, "p_ge0": p_ge0,
        "det_pos": det_pos, "det_neg": det_neg,
        "det_pos_bonf": det_pos_b, "det_neg_bonf": det_neg_b,
        "det_pos_bonf17": det_pos_b17, "det_neg_bonf17": det_neg_b17,
        "summary": {
            "n_configurations": int(len(counts)),
            "fft_vs_exact_max_abs_error_200_rows": max_err,
            "rows_recomputed_exactly_near_threshold": n_exact,
            "min_detectable_observed_sum_D": min_pos,
            "min_detectable_observed_diff_pp": 100.0 * min_pos / N_PER_ARM,
            "witness_counts_for_D_-3..3": witness.tolist(),
            "min_certificates_with_D_gt_0_among_detected_increases":
                int(n_favouring[det_pos].min()),
            "min_certificates_with_D_lt_0_among_detected_decreases":
                int(n_against[det_neg].min()),
            "min_detectable_observed_sum_D_bonferroni":
                int(sum_d[det_pos_b].min()),
            "min_detectable_observed_diff_pp_bonferroni":
                100.0 * int(sum_d[det_pos_b].min()) / N_PER_ARM,
            "min_detectable_observed_sum_D_bonferroni17":
                int(sum_d[det_pos_b17].min()),
            "min_detectable_observed_diff_pp_bonferroni17":
                100.0 * int(sum_d[det_pos_b17].min()) / N_PER_ARM,
        },
    }


def lookup(D: np.ndarray) -> np.ndarray:
    """Row index into TABLE for each simulated experiment (rows of D)."""
    counts = np.stack([(D == v).sum(1) for v in VALS], axis=1)
    keys = encode(counts)
    idx = np.searchsorted(TABLE["keys"], keys)
    assert np.array_equal(TABLE["keys"][idx], keys), "configuration missing from table"
    return idx


# ----------------------------------------------------------------------------
# The literal finite-B rule, for validation
# ----------------------------------------------------------------------------
def paper_picks(B: int = BOOT_B, seed: int = 0) -> np.ndarray:
    """Exactly the resample sequence uncertainty.cluster_bootstrap draws."""
    rng = np.random.default_rng(seed)
    return np.stack([rng.integers(0, K, K) for _ in range(B)])


def literal_ci(D: np.ndarray, picks: np.ndarray) -> tuple[float, float]:
    diff = 100.0 * D[picks].sum(1) / N_PER_ARM
    lo, hi = np.percentile(diff, [100 * ALPHA / 2, 100 * (1 - ALPHA / 2)])
    return float(lo), float(hi)


# ----------------------------------------------------------------------------
# The data-generating model
# ----------------------------------------------------------------------------
def beta_params(p: float, icc: float) -> tuple[float, float]:
    kappa = (1.0 - icc) / icc
    return p * kappa, (1.0 - p) * kappa


def cell_probs(u: np.ndarray, p: float, icc: float) -> np.ndarray:
    if p <= 0.0:
        return np.zeros_like(u)
    if p >= 1.0:
        return np.ones_like(u)
    if icc == 0.0:
        return np.full_like(u, p)
    a, b = beta_params(p, icc)
    return special.betaincinv(a, b, u)


def draw_world(p0, icc, r, n_sim, seed):
    ss = np.random.SeedSequence([seed, round(p0 * 1e6), round(icc * 1e3),
                                 round(r * 1e3)])
    rng = np.random.default_rng(ss)
    z_ref = rng.standard_normal((n_sim, K))
    z_ind = rng.standard_normal((n_sim, K))
    u_ref = special.ndtr(z_ref)
    u_cond = u_ref.copy() if r == 1.0 else special.ndtr(
        r * z_ref + np.sqrt(1.0 - r * r) * z_ind)
    v_ref = rng.random((n_sim, K, R))
    v_cond = rng.random((n_sim, K, R))
    s_ref = (v_ref < cell_probs(u_ref, p0, icc)[..., None]).sum(-1)
    return {"u_cond": u_cond, "v_cond": v_cond, "s_ref": s_ref}


def D_at(world, p0, icc, d):
    p_c = cell_probs(world["u_cond"], p0 + d, icc)
    s_c = (world["v_cond"] < p_c[..., None]).sum(-1)
    return s_c - world["s_ref"]


def d_grid(p0: float, step: float) -> list[float]:
    g = set(np.round(np.arange(0.0, 1.0 - p0 + 1e-12, step), 6).tolist())
    g |= {round(x / N_PER_ARM, 6) for x in (1, 2, 4, 13)}  # observed-size points
    g = {x for x in g if 0.0 <= x <= 1.0 - p0 + 1e-12}
    g |= {-p0, -p0 / 2}                                   # largest possible decreases
    return sorted(g)


def simulate_config(job):
    label, p0, icc, r, n_sim, seed, step = job
    t0 = time.time()
    world = draw_world(p0, icc, r, n_sim, seed)
    curve = []
    hit = 0
    for d in d_grid(p0, step):
        D = D_at(world, p0, icc, d)
        idx = lookup(D)
        obs = 100.0 * D.sum(1) / N_PER_ARM
        row = {"d_pp": round(100.0 * d, 4)}
        for name, key in (("pos", "det_pos"), ("neg", "det_neg"),
                          ("pos_bonf", "det_pos_bonf"), ("neg_bonf", "det_neg_bonf"),
                          ("pos_bonf17", "det_pos_bonf17")):
            pw = float(TABLE[key][idx].mean())
            row[f"power_{name}"] = pw
            row[f"se_{name}"] = float(np.sqrt(pw * (1 - pw) / n_sim))
        row["mean_observed_diff_pp"] = float(obs.mean())
        curve.append(row)
        if d > 0 and row["power_pos_bonf17"] >= 0.995:
            hit += 1
            if hit >= 3:
                break
    return {"label": label, "p0": p0, "icc": icc, "coupling_r": r,
            "n_sim": n_sim, "seed": seed, "curve": curve,
            "seconds": round(time.time() - t0, 1)}


def mde_from_curve(curve, key="pos", target=TARGET_POWER):
    pos = [c for c in curve if c["d_pp"] > 0]
    d = np.array([c["d_pp"] for c in pos])
    pw = np.array([c[f"power_{key}"] for c in pos])
    se = np.array([c[f"se_{key}"] for c in pos])

    def first(mask):
        i = np.flatnonzero(mask)
        return float(d[i[0]]) if len(i) else None

    grid = first(pw >= target)
    interp = None
    i = np.flatnonzero(pw >= target)
    if len(i):
        j = i[0]
        if j == 0:
            interp = float(d[0])
        else:
            interp = float(d[j - 1] + (target - pw[j - 1]) * (d[j] - d[j - 1])
                           / (pw[j] - pw[j - 1]))
    return {"mde_pp_grid": grid, "mde_pp_interp": interp,
            "mc_band_pp": [first(pw + 1.96 * se >= target),
                           first(pw - 1.96 * se >= target)]}


def power_at(curve, d_pp, key="pos"):
    best = min(curve, key=lambda c: abs(c["d_pp"] - d_pp))
    return {"d_pp": best["d_pp"], "power": best[f"power_{key}"],
            "se": best[f"se_{key}"]}


# ----------------------------------------------------------------------------
# Closed-form sanity checks, ignoring clustering
# ----------------------------------------------------------------------------
Z_A = float(stats.norm.ppf(1 - ALPHA / 2))
Z_B = float(stats.norm.ppf(TARGET_POWER))


def closed_form(p0: float, n: float = N_PER_ARM) -> dict:
    # Cohen's h (arcsine): power 0.8 when 2asin(sqrt p1) - 2asin(sqrt p0) = (za+zb)sqrt(2/n)
    h = (Z_A + Z_B) * np.sqrt(2.0 / n)
    arcs = np.sin(np.arcsin(np.sqrt(p0)) + h / 2) ** 2 - p0

    def n_req(p1, cc):
        dd = p1 - p0
        pb = (p0 + p1) / 2
        m = (Z_A * np.sqrt(2 * pb * (1 - pb)) + Z_B * np.sqrt(p0 * (1 - p0) + p1 * (1 - p1))) ** 2 / dd ** 2
        if cc:
            m = m / 4 * (1 + np.sqrt(1 + 4 / (m * dd))) ** 2
        return m

    fleiss = optimize.brentq(lambda p1: n_req(p1, False) - n, p0 + 1e-6, 1 - 1e-9) - p0
    fleiss_cc = optimize.brentq(lambda p1: n_req(p1, True) - n, p0 + 1e-6, 1 - 1e-9) - p0
    return {"arcsine_pp": 100 * float(arcs), "fleiss_pp": 100 * float(fleiss),
            "fleiss_continuity_corrected_pp": 100 * float(fleiss_cc)}


def fisher_exact_mde(p0: float, n: int = N_PER_ARM, step: float = 0.0025) -> dict:
    """Exact power of a two-sided Fisher test, n per arm, no clustering."""
    reject = np.zeros((n + 1, n + 1), dtype=bool)  # [x_ref, x_cond], cond > ref
    for x0 in range(n + 1):
        for x1 in range(x0 + 1, n + 1):
            _, p = stats.fisher_exact([[x1, n - x1], [x0, n - x0]])
            reject[x0, x1] = p < ALPHA
    pm0 = stats.binom.pmf(np.arange(n + 1), n, p0)
    for d in np.arange(step, 1 - p0, step):
        pm1 = stats.binom.pmf(np.arange(n + 1), n, p0 + d)
        pw = float(pm0 @ reject @ pm1)
        if pw >= TARGET_POWER:
            return {"fisher_exact_mde_pp_grid": round(100 * float(d), 4),
                    "power_at_mde": pw, "grid_step_pp": 100 * step}
    return {"fisher_exact_mde_pp_grid": None}


# ----------------------------------------------------------------------------
# Observed data
# ----------------------------------------------------------------------------
def per_cert_D(rows, pred, cond, ref="F3"):
    s = collections.defaultdict(lambda: [0, 0])
    for r in rows:
        if r["condition"] in (cond, ref):
            s[r["_cert"]][0 if r["condition"] == cond else 1] += int(pred(r))
    certs = sorted({r["_cert"] for r in rows})
    return np.array([s[c][0] - s[c][1] for c in certs])


def observed_block(rows, n_boot):
    out = {}
    ref_unc = json.loads((REPO / "data/results/uncertainty.json").read_text())
    picks = paper_picks(n_boot, 0)
    repro = []
    for name, pred in OUTCOMES.items():
        point, cis, dcis = uncertainty.cluster_bootstrap(rows, None, pred, n_boot, 0)
        counts = {c: int(sum(1 for r in rows if r["condition"] == c and pred(r)))
                  for c in uncertainty.CONDS}
        block = {"successes_of_60": counts, "rate_pct": point,
                 "diff_vs_F3": {}}
        for c in uncertainty.CONDS:
            if c == "F3":
                continue
            D = per_cert_D(rows, pred, c)
            lo, hi = literal_ci(D, picks)
            idx = lookup(D[None, :])[0]
            block["diff_vs_F3"][c] = {
                "point_pp": point[c] - point["F3"],
                "ci_paper_function": list(dcis[c]),
                "ci_literal_reimplementation": [lo, hi],
                "exact_rule_P_le0": float(TABLE["p_le0"][idx]),
                "exact_rule_P_ge0": float(TABLE["p_ge0"][idx]),
                "detected_paper_function": not (dcis[c][0] <= 0 <= dcis[c][1]),
                "detected_exact_rule": bool(TABLE["det_pos"][idx] or TABLE["det_neg"][idx]),
                "per_cert_D": D.tolist(),
            }
            repro.append(abs(lo - dcis[c][0]) < 1e-9 and abs(hi - dcis[c][1]) < 1e-9)
        out[name] = block
    # the existing uncertainty.json outcomes, reproduced by the literal rule
    preds = {"resolved": lambda r: bool(r.get("resolved")),
             "resolved_ex_refusal": OUTCOMES["resolved_ex_refusal"],
             "skeleton_edit": lambda r: r.get("patch_type") == "skeleton_edit",
             "regression": lambda r: (r.get("regression_failures") or 0) >= 1}
    match_json = {}
    for key, pred in preds.items():
        ok = True
        for c, v in ref_unc[key]["diff_vs_F3"].items():
            lo, hi = literal_ci(per_cert_D(rows, pred, c), picks)
            ok &= abs(lo - v["ci"][0]) < 1e-9 and abs(hi - v["ci"][1]) < 1e-9
        match_json[key] = bool(ok)
    out["validation"] = {
        "literal_rule_matches_paper_function_on_real_data": bool(all(repro)),
        "literal_rule_reproduces_uncertainty_json": match_json,
    }
    return out


def anova_icc(groups) -> float:
    """One-way ANOVA intra-cluster correlation for equal-size binary clusters."""
    y = np.asarray(groups, float)
    k, m = y.shape
    if y.std() == 0:
        return float("nan")
    gm = y.mean()
    msb = m * ((y.mean(1) - gm) ** 2).sum() / (k - 1)
    msw = ((y - y.mean(1, keepdims=True)) ** 2).sum() / (k * m - k)
    den = msb + (m - 1) * msw
    return float((msb - msw) / den) if den > 0 else float("nan")


def assumption_context(rows) -> dict:
    """Descriptive numbers bearing on A3 (ICC) and A4 (coupling), from the data.

    Repair success has 2-5 events per outcome, too few to estimate either. The
    edit-type and regression outcomes, from the same attempts, are reported as
    the only in-experiment evidence of how strongly attempts cluster.
    """
    preds = {"resolved_ex_refusal": OUTCOMES["resolved_ex_refusal"],
             "resolved_and_completed": OUTCOMES["resolved_and_completed"],
             "skeleton_edit": lambda r: r.get("patch_type") == "skeleton_edit",
             "regression": lambda r: (r.get("regression_failures") or 0) >= 1}
    certs = sorted({r["_cert"] for r in rows})
    out = {}
    for name, pred in preds.items():
        cells = collections.defaultdict(list)
        for r in rows:
            cells[(r["condition"], r["_cert"])].append(int(pred(r)))
        icc = {c: anova_icc([cells[(c, k)] for k in certs]) for c in uncertainty.CONDS}
        cnt = {c: np.array([sum(cells[(c, k)]) for k in certs]) for c in uncertainty.CONDS}
        corr = {}
        for c in uncertainty.CONDS:
            if c == "F3":
                continue
            a, b = cnt[c], cnt["F3"]
            corr[c] = (float(stats.spearmanr(a, b).statistic)
                       if a.std() > 0 and b.std() > 0 else float("nan"))
        out[name] = {"within_cell_icc_by_condition": icc,
                     "spearman_per_certificate_counts_vs_F3": corr,
                     "certificates_with_any_success": {
                         c: [k for k, v in zip(certs, cnt[c]) if v > 0]
                         for c in uncertainty.CONDS} if name.startswith("resolved") else None}
    return out


# ----------------------------------------------------------------------------
# Validation on simulated data
# ----------------------------------------------------------------------------
def validate_literal_vs_exact(configs, n_per, seed):
    rng = np.random.default_rng(seed)
    res = []
    for p0, icc, r, d in configs:
        world = draw_world(p0, icc, r, n_per, seed + 7)
        D = D_at(world, p0, icc, d)
        idx = lookup(D)
        exact = TABLE["det_pos"][idx] | TABLE["det_neg"][idx]
        lit = np.empty(n_per, dtype=bool)
        for i in range(n_per):
            picks = rng.integers(0, K, (BOOT_B, K))
            lo, hi = literal_ci(D[i], picks)
            lit[i] = not (lo <= 0 <= hi)
        p_le = TABLE["p_le0"][idx]
        res.append({"p0": p0, "icc": icc, "coupling_r": r, "d_pp": 100 * d,
                    "n": n_per, "agree": float((lit == exact).mean()),
                    "n_disagree": int((lit != exact).sum()),
                    "detect_rate_exact": float(exact.mean()),
                    "detect_rate_literal": float(lit.mean()),
                    "n_within_0.005_of_threshold":
                        int((np.abs(p_le - ALPHA / 2) < 0.005).sum())})
    return res


def validate_paper_function(n_datasets, seed):
    """Run uncertainty.cluster_bootstrap itself on synthetic rows."""
    picks = paper_picks(BOOT_B, 0)
    out = []
    # choose datasets whose exact tail sits near the threshold, to stress the rule
    world = draw_world(1 / 30, 0.0, 1.0, 4000, seed)
    D_all = D_at(world, 1 / 30, 0.0, 0.10)
    pl = TABLE["p_le0"][lookup(D_all)]
    cand = np.argsort(np.abs(pl - ALPHA / 2))[: n_datasets]
    for i in cand:
        D = D_all[i]
        # build rows: F1 = condition, F3 = reference, others copy F3.
        # Only D matters to the rule; the smallest consistent cell counts are used.
        s_ref = np.clip(-D, 0, R)
        s_c = s_ref + D
        rows = []
        for j in range(K):
            cert = f"CE{j + 1:03d}"
            for cond in uncertainty.CONDS:
                s = s_c[j] if cond == "F1" else s_ref[j]
                for rep in range(R):
                    rows.append({"_cert": cert, "condition": cond, "y": rep < s})
        _, _, dcis = uncertainty.cluster_bootstrap(rows, None, lambda r: r["y"], BOOT_B, 0)
        lo, hi = literal_ci(D, picks)
        out.append({"sum_D": int(D.sum()), "exact_P_le0": float(pl[i]),
                    "paper_ci": list(dcis["F1"]), "literal_ci": [lo, hi],
                    "match": abs(lo - dcis["F1"][0]) < 1e-9 and abs(hi - dcis["F1"][1]) < 1e-9})
    return out


def beta_parametrisation_check(seed, n_cells=400000):
    """Simulated mean and replicate-replicate correlation vs their targets.

    For a Beta(a, b) cell probability, two Bernoulli replicates in the same
    cell have correlation Var(p) / (mu (1 - mu)) = 1 / (a + b + 1). This draws
    cells exactly as the power simulation does (cell_probs on uniform
    quantiles) and measures both quantities directly.
    """
    rng = np.random.default_rng(np.random.SeedSequence([seed, 31337]))
    out = []
    for p, icc in ((1 / 30, 0.1), (1 / 30, 0.3), (1 / 30, 0.5), (0.05, 0.3), (0.25, 0.3)):
        a, b = beta_params(p, icc)
        q = cell_probs(rng.random(n_cells), p, icc)
        y = rng.random((n_cells, R)) < q[:, None]
        corr = float(np.mean([np.corrcoef(y[:, i], y[:, j])[0, 1]
                              for i, j in ((0, 1), (0, 2), (1, 2))]))
        out.append({"p": p, "icc_target": icc, "icc_from_a_b": 1.0 / (a + b + 1.0),
                    "simulated_mean": float(y.mean()),
                    "simulated_replicate_corr": corr, "n_cells": n_cells})
    return out


def shared_coupling_concentration(results, n_q=200000):
    """How the improvement is spread over certificates under shared coupling.

    Deterministic (midpoint quadrature over the Beta quantile). At the MDE of
    each shared setting with p0 = F3's observed rate: the share of the mean
    improvement carried by the 20% of certificates in the upper tail, the
    spread of the per-certificate improvement, and the mean within-cell
    binomial variance in the reference arm. Explains why the shared-column MDE
    is not monotone in ICC.
    """
    u = (np.arange(n_q) + 0.5) / n_q
    out = []
    for e in results:
        if e["coupling_r"] != 1.0 or e["label"].startswith("SUPP") or e["p0"] > 0.04:
            continue
        p0, icc, d = e["p0"], e["icc"], e["mde_80"]["mde_pp_interp"] / 100
        q0, q1 = cell_probs(u, p0, icc), cell_probs(u, p0 + d, icc)
        g = q1 - q0
        out.append({"p0": p0, "icc": icc, "d_pp": 100 * d,
                    "share_of_improvement_in_top_20pct": float(g[u > 0.8].sum() / g.sum()),
                    "sd_per_certificate_improvement": float(g.std()),
                    "mean_within_cell_var_ref": float(np.mean(R * q0 * (1 - q0)))})
    return out


def pattern_job(job):
    """P(observed success pattern | totals) under one (ICC, coupling) setting."""
    p_ref, p_cond, tot_ref, tot_cond, icc, r, n, seed = job
    world = draw_world(p_ref, icc, r, n, seed)
    s_ref = world["s_ref"]
    s_cond = (world["v_cond"] < cell_probs(world["u_cond"], p_cond, icc)[..., None]).sum(-1)
    keep = (s_ref.sum(1) == tot_ref) & (s_cond.sum(1) == tot_cond)
    a, b = s_ref[keep], s_cond[keep]
    singletons = (a <= 1).all(1) & (b <= 1).all(1)
    disjoint = ~((a > 0) & (b > 0)).any(1)
    m = int(keep.sum())

    def pr(x):
        v = float(x.mean())
        return {"p": v, "se": float(np.sqrt(v * (1 - v) / m))}
    return {"icc": icc, "coupling_r": r, "n_conditioned": m,
            "P_all_singletons": pr(singletons), "P_no_shared_certificate": pr(disjoint),
            "P_both": pr(singletons & disjoint)}


def success_pattern_likelihood(rows, pool, seed, n=200000):
    """Outcome A (resolved, refusals counted as failures), F1 against F3."""
    pred = OUTCOMES["resolved_ex_refusal"]
    certs = sorted({r["_cert"] for r in rows})
    cells = collections.Counter((r["condition"], r["_cert"]) for r in rows if pred(r))
    s3 = np.array([cells[("F3", c)] for c in certs])
    s1 = np.array([cells[("F1", c)] for c in certs])
    observed = {"F3_successes": int(s3.sum()), "F1_successes": int(s1.sum()),
                "all_singletons": bool((s3 <= 1).all() and (s1 <= 1).all()),
                "no_shared_certificate": bool(not ((s3 > 0) & (s1 > 0)).any())}
    jobs = [(s3.sum() / N_PER_ARM, s1.sum() / N_PER_ARM, int(s3.sum()), int(s1.sum()),
             icc, r, n, seed)
            for icc in (0.0, 0.1, 0.3, 0.5)
            for r in ((1.0,) if icc == 0.0 else (1.0, 0.5, 0.0))]
    return {"outcome": "resolved_ex_refusal, F1 vs F3",
            "model": "p_F3 = observed F3 rate, p_F1 = observed F1 rate, conditioned on "
                     "the observed totals; indicative, not an estimate of ICC or r",
            "observed": observed, "settings": pool.map(pattern_job, jobs)}


# ----------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-sim", type=int, default=20000)
    ap.add_argument("--step", type=float, default=0.005)
    ap.add_argument("--seed", type=int, default=20261009)
    ap.add_argument("--workers", type=int, default=min(24, mp.cpu_count()))
    ap.add_argument("--validate-n", type=int, default=1500)
    ap.add_argument("--paper-fn-checks", type=int, default=6)
    ap.add_argument("--mc-seed", type=int, default=4242,
                    help="second seed for the Monte Carlo replicate; negative to skip")
    ap.add_argument("--out", default=str(REPO / "data/results/detectable_effect.json"))
    a = ap.parse_args()
    t_start = time.time()

    print("building exact decision table ...", flush=True)
    TABLE.update(build_table())
    print(json.dumps(TABLE["summary"], indent=2))

    rows = uncertainty.load()
    print(f"\n{len(rows)} attempts, {len({r['_cert'] for r in rows})} certificates")
    print("observed outcomes (paper's own bootstrap, seed 0, B=10000) ...", flush=True)
    observed = observed_block(rows, BOOT_B)
    for name in OUTCOMES:
        b = observed[name]
        print(f"\n  {name}: successes/60 {b['successes_of_60']}")
        for c, v in b["diff_vs_F3"].items():
            print(f"    {c:<4}-F3 = {v['point_pp']:+5.1f}  paper CI "
                  f"[{v['ci_paper_function'][0]:+5.1f}, {v['ci_paper_function'][1]:+5.1f}]"
                  f"  exact P*(<=0)={v['exact_rule_P_le0']:.3f} P*(>=0)={v['exact_rule_P_ge0']:.3f}"
                  f"  detected={v['detected_paper_function']}/{v['detected_exact_rule']}")
    print("  validation:", observed["validation"])

    context = assumption_context(rows)
    print("\ncontext for A3/A4 (within-cell ICC by condition; Spearman of per-cert counts vs F3):")
    for k, v in context.items():
        print(f"  {k}: ICC {({c: round(x, 3) for c, x in v['within_cell_icc_by_condition'].items()})}")
        print(f"  {' ' * len(k)}  rho vs F3 {({c: round(x, 3) for c, x in v['spearman_per_certificate_counts_vs_F3'].items()})}")

    p0_obs = observed["resolved_ex_refusal"]["successes_of_60"]["F3"] / N_PER_ARM
    p0_obs_b = observed["resolved_and_completed"]["successes_of_60"]["F3"] / N_PER_ARM
    pooled_b = sum(observed["resolved_and_completed"]["successes_of_60"].values()) / (5 * N_PER_ARM)
    p0_values = sorted({p0_obs, p0_obs_b, 0.05, pooled_b})  # exact floats, deduplicated
    print(f"\np0 values: {p0_values}  (A observed {p0_obs:.4f}, B observed {p0_obs_b:.4f}, "
          f"B pooled {pooled_b:.4f})")

    jobs = []
    for p0 in p0_values:
        for icc in (0.0, 0.1, 0.3, 0.5):
            for r in ((1.0,) if icc == 0.0 else (1.0, 0.5, 0.0)):
                jobs.append((f"p0={p0:.4f}|icc={icc}|r={r}", p0, icc, r,
                             a.n_sim, a.seed, a.step))
    # supplementary: the edit-type outcome, F3 = 15/60 skeleton edits
    for icc in (0.0, 0.3):
        for r in ((1.0,) if icc == 0.0 else (1.0, 0.0)):
            jobs.append((f"SUPP_skeleton|p0=0.25|icc={icc}|r={r}", 0.25, icc, r,
                         a.n_sim, a.seed, a.step))
    print(f"running {len(jobs)} configurations x {a.n_sim} simulated experiments "
          f"on {a.workers} workers ...", flush=True)
    ctx = mp.get_context("fork")
    with ctx.Pool(a.workers) as pool:
        sims = pool.map(simulate_config, jobs)
        # Monte Carlo replicate: identical jobs, independent second seed (index 5).
        sims2 = (pool.map(simulate_config, [j[:5] + (a.mc_seed,) + j[6:] for j in jobs])
                 if a.mc_seed >= 0 else [])
        print("success-pattern likelihood (indicative evidence on A3/A4) ...", flush=True)
        pattern = success_pattern_likelihood(rows, pool, a.seed + 3)
    print(f"  observed: {pattern['observed']}")
    for s in pattern["settings"]:
        print(f"  icc={s['icc']} r={s['coupling_r']}: n={s['n_conditioned']}  "
              f"P(singletons)={s['P_all_singletons']['p']:.3f}  "
              f"P(no shared cert)={s['P_no_shared_certificate']['p']:.3f}  "
              f"P(both)={s['P_both']['p']:.3f}")

    results = []
    for s in sims:
        curve = s["curve"]
        entry = {k: s[k] for k in ("label", "p0", "icc", "coupling_r", "n_sim", "seed", "seconds")}
        entry["coupling"] = "shared" if s["coupling_r"] == 1.0 else (
            "independent" if s["coupling_r"] == 0.0 else f"r={s['coupling_r']}")
        if s["icc"] == 0.0:
            entry["coupling"] = "n/a (no certificate effect)"
        entry["mde_80"] = mde_from_curve(curve, "pos")
        entry["mde_80_bonferroni"] = mde_from_curve(curve, "pos_bonf")
        entry["mde_80_bonferroni17"] = mde_from_curve(curve, "pos_bonf17")
        zero = next(c for c in curve if c["d_pp"] == 0.0)
        entry["false_detection_rate_at_d0"] = {
            "any_direction": zero["power_pos"] + zero["power_neg"],
            "se": float(np.sqrt((zero["power_pos"] + zero["power_neg"]) *
                                (1 - zero["power_pos"] - zero["power_neg"]) / s["n_sim"]))}
        entry["power_at"] = {f"{x:g}pp": power_at(curve, x) for x in
                             (100 / 60, 200 / 60, 5, 10, 15, 20, 21.7, 25, 30, 40)}
        neg = min(curve, key=lambda c: c["d_pp"])
        entry["largest_possible_decrease"] = {
            "d_pp": neg["d_pp"], "power_detect_decrease": neg["power_neg"],
            "se": neg["se_neg"]}
        entry["max_wrong_sign_rate_for_d_gt_0"] = max(
            c["power_neg"] for c in curve if c["d_pp"] > 0)
        entry["curve"] = curve
        results.append(entry)
        m = entry["mde_80"]
        print(f"  {s['label']:<40} MDE80 = {m['mde_pp_interp'] if m['mde_pp_interp'] is None else round(m['mde_pp_interp'],1)} pp "
              f"(grid {m['mde_pp_grid']}, MC band {m['mc_band_pp']})  "
              f"Bonf {entry['mde_80_bonferroni']['mde_pp_interp'] and round(entry['mde_80_bonferroni']['mde_pp_interp'],1)}  "
              f"size@0 {entry['false_detection_rate_at_d0']['any_direction']:.4f}  "
              f"P(detect decrease to 0) {entry['largest_possible_decrease']['power_detect_decrease']:.3f}  "
              f"[{s['seconds']}s]")

    mc = None
    if sims2:
        per = []
        for s1, s2 in zip(sims, sims2):
            assert s1["label"] == s2["label"]
            row = {"label": s1["label"]}
            for key, name in (("pos", "mde_80"), ("pos_bonf", "mde_80_bonferroni"),
                              ("pos_bonf17", "mde_80_bonferroni17")):
                m1 = mde_from_curve(s1["curve"], key)["mde_pp_interp"]
                m2 = mde_from_curve(s2["curve"], key)["mde_pp_interp"]
                row[name] = {"seed_main": m1, "seed_2": m2, "abs_diff": abs(m1 - m2)}
            per.append(row)
        d80 = [r["mde_80"]["abs_diff"] for r in per]
        dall = [r[k]["abs_diff"] for r in per
                for k in ("mde_80", "mde_80_bonferroni", "mde_80_bonferroni17")]
        mc = {"seed_main": a.seed, "seed_2": a.mc_seed, "n_sim_each": a.n_sim,
              "max_abs_diff_mde_80_pp": max(d80),
              "rms_diff_mde_80_pp": float(np.sqrt(np.mean(np.square(d80)))),
              "implied_se_single_mde_pp": float(np.sqrt(np.mean(np.square(d80)) / 2)),
              "max_abs_diff_any_mde_pp": max(dall),
              "n_settings": len(per),
              "n_mde_80_changing_at_first_decimal": sum(
                  round(r["mde_80"]["seed_main"], 1) != round(r["mde_80"]["seed_2"], 1)
                  for r in per),
              "n_mde_80_changing_at_whole_point": sum(
                  round(r["mde_80"]["seed_main"]) != round(r["mde_80"]["seed_2"])
                  for r in per),
              "per_setting": per}
        print(f"\nMonte Carlo replicate (seed {a.seed} vs {a.mc_seed}): max |dMDE80| "
              f"{mc['max_abs_diff_mde_80_pp']:.2f} pp, implied SE of one MDE "
              f"{mc['implied_se_single_mde_pp']:.2f} pp, max over all MDEs "
              f"{mc['max_abs_diff_any_mde_pp']:.2f} pp; first decimal changes in "
              f"{mc['n_mde_80_changing_at_first_decimal']}/{len(per)}, whole point in "
              f"{mc['n_mde_80_changing_at_whole_point']}/{len(per)}")

    conc = shared_coupling_concentration(results)
    print("\nshared coupling: how the improvement is spread at the MDE (deterministic):")
    for c in conc:
        print(f"  p0={c['p0']:.4f} icc={c['icc']} d={c['d_pp']:.1f}: top-20% share "
              f"{c['share_of_improvement_in_top_20pct']:.2f}, SD per-cert improvement "
              f"{c['sd_per_certificate_improvement']:.3f}, ref within-cell var "
              f"{c['mean_within_cell_var_ref']:.3f}")

    beta_chk = beta_parametrisation_check(a.seed)
    print("\nBeta parametrisation check (target ICC = 1/(a+b+1)):")
    for b in beta_chk:
        print(f"  p={b['p']:.4f} icc={b['icc_target']}: 1/(a+b+1)={b['icc_from_a_b']:.4f}  "
              f"mean {b['simulated_mean']:.4f}  replicate corr {b['simulated_replicate_corr']:.3f}")

    closed = {f"{p0:.4f}": {**closed_form(p0), **fisher_exact_mde(p0),
                             "design_effect_arcsine_pp": {
                                 f"icc={icc}": closed_form(p0, N_PER_ARM / (1 + (R - 1) * icc))["arcsine_pp"]
                                 for icc in (0.1, 0.3, 0.5)}}
              for p0 in p0_values + [0.25]}
    print("\nclosed form (no clustering, n=60 per arm, two-sided 0.05, power 0.8):")
    for k, v in closed.items():
        print(f"  p0={k}: arcsine {v['arcsine_pp']:.1f} pp, Fleiss {v['fleiss_pp']:.1f}, "
              f"Fleiss+cc {v['fleiss_continuity_corrected_pp']:.1f}, "
              f"Fisher exact {v['fisher_exact_mde_pp_grid']}, design-effect arcsine {v['design_effect_arcsine_pp']}")

    print("\nvalidation: literal B=10000 rule vs exact table on simulated data ...", flush=True)
    vcfg = []
    for p0, icc, r in ((p0_obs, 0.0, 1.0), (p0_obs, 0.3, 1.0), (p0_obs, 0.3, 0.0), (0.05, 0.1, 1.0)):
        e = next(x for x in results if abs(x["p0"] - p0) < 1e-9 and x["icc"] == icc and x["coupling_r"] == r)
        vcfg.append((p0, icc, r, round(e["mde_80"]["mde_pp_grid"] / 100, 6)))
    val_sim = validate_literal_vs_exact(vcfg, a.validate_n, a.seed + 1)
    for v in val_sim:
        print("  ", v)
    print("validation: paper's own cluster_bootstrap on synthetic rows ...", flush=True)
    val_fn = validate_paper_function(a.paper_fn_checks, a.seed + 2)
    for v in val_fn:
        print("  ", v)

    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True,
                            text=True).stdout.strip()
    out = {
        "what_this_is": ("Power of the paper's decision rule under a stated data-generating "
                         "model. A property of the design under assumptions A1-A7, not a "
                         "measured resolution and not a noise floor."),
        "git_commit": commit,
        "script": "scripts/detectable_effect.py",
        "decision_rule": {
            "source": "scripts/uncertainty.py cluster_bootstrap",
            "unit": "certificate (20), resampled with replacement, all attempts carried",
            "interval": "95% percentile, paired difference condition - F3",
            "detected_when": "interval excludes 0",
            "multiplicity": "none in the paper; Bonferroni over 4 (per outcome) and over 17 "
                            "(all paired differences) reported as sensitivities",
            "implementation_here": "exact bootstrap distribution (B -> infinity) over all "
                                   "230,230 per-certificate difference configurations",
        },
        "assumptions": {
            "A1": "K=20 certificates, R=3 replicates per (condition, certificate) cell",
            "A2": "replicates independent Bernoulli given the cell success probability",
            "A3": "cell probability ~ Beta(mean p, ICC), ICC = 1/(a+b+1), same ICC in both arms",
            "A4": "certificate difficulty coupled across conditions by a Gaussian copula with r "
                  "(r=1 shared, the paired-design reference; r=0.5; r=0 independent). Negative "
                  "coupling not simulated; it would lower power further",
            "A5": "reference rate p0 known",
            "A6": "effect is a shift in mean success probability p1 = p0 + d",
            "A7": "single two-sided 95% comparison, as in the paper",
        },
        "settings": {"n_sim": a.n_sim, "grid_step_pp": 100 * a.step, "seed": a.seed,
                     "target_power": TARGET_POWER, "boot_B_literal_rule": BOOT_B},
        "decision_table": TABLE["summary"],
        "observed": observed,
        "context_for_assumptions": context,
        "p0_values": {"A_resolved_ex_refusal_observed_F3": p0_obs,
                      "B_resolved_and_completed_observed_F3": p0_obs_b,
                      "B_pooled_all_conditions": pooled_b, "A_alternative": 0.05,
                      "note": ("A and B have the same observed F3 rate (2/60), so under this "
                               "model their simulations are identical; they are computed once.")},
        "simulations": results,
        "closed_form_no_clustering": closed,
        "validation": {"literal_vs_exact_on_simulated": val_sim,
                       "paper_function_vs_literal_on_synthetic": val_fn,
                       "beta_parametrisation": beta_chk},
        "monte_carlo_replicate": mc,
        "success_pattern_likelihood": pattern,
        "shared_coupling_concentration": conc,
        "runtime_s": round(time.time() - t_start, 1),
    }
    path = pathlib.Path(a.out)
    path.write_text(json.dumps(out, indent=1))
    print(f"\nwritten: {path}  ({out['runtime_s']} s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
