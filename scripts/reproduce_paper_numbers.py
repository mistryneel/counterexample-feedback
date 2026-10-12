#!/usr/bin/env python3
"""Recompute every quantitative claim in the paper from committed data.

WHAT THIS IS
    A ledger: one row per quantitative claim in paper/main.tex, giving the tex
    line, the value printed in the paper, the value recomputed here, and a
    status. It exits non-zero if any claim is a MISMATCH, so it can gate a
    camera-ready build.

        .venv/bin/python scripts/reproduce_paper_numbers.py                 # paper/main.tex
        .venv/bin/python scripts/reproduce_paper_numbers.py path/to/main.tex
        .venv/bin/python scripts/reproduce_paper_numbers.py --markdown out.md --json out.json

STATUSES
    MATCH              recomputed value, rounded half-up to the precision the
                       paper prints, equals the paper's value
    MISMATCH           it does not (exit code 1)
    NOT-RECOMPUTABLE   no committed artefact supports the number; the reason
                       is given
    NOT-FOUND          the claim's anchoring text is absent from the tex given
                       (expected when a revised main.tex rewords or drops a
                       claim; it is listed, not failed, unless --strict)

BASIS
    "recomputed: X"        derived here from committed data X
    "from artefact X"      the number can only come from a CARLA run or an API
                           call; it is read from the committed artefact X that
                           recorded it, and any arithmetic on top of it is
                           redone here. It is NOT independently recomputed.
    "external"             a figure quoted from another paper

HOW VALUES ARE FOUND IN THE TEX
    Each claim carries a regular expression with named groups anchored on the
    surrounding words, so a revised main.tex is checked by pattern rather than
    by line number. A claim whose anchor no longer matches reports NOT-FOUND.
    A coverage scan then lists every digit string in the document body that no
    registered claim accounts for, so a NEW number added during revision is
    surfaced rather than silently unchecked.

ROUNDING
    Half-up, at the number of decimals the paper prints. Values that are exact
    ratios of counts are carried as fractions so no binary-float rounding can
    flip a half (e.g. 26.55 -> 26.6, 0.925 -> 0.93).

DATA
    Everything read is in the released repository, by path relative to its
    root. No CARLA, no API call.

      data/results/*.json[l], data/results/patched_programs/,
      data/results/rendered_prompts/, data/certificates/*.json,
      data/scenarios/, config/, data/prompts/, logs/llm_index.jsonl
                                  campaign records and committed results
      data/certificates/traces/   the 20 counterexample trajectories the
                                  certificates point at; every F1 prompt is
                                  regenerated from them
      data/dsl_probe_traces/      trajectories behind the expressiveness table
                                  and the clean repair's six repeats, re-scored
                                  here with src/stl.py (manifest.json holds a
                                  sha256 per file)
      data/calibration_traces/    the frozen baseline's 100 calibration
                                  episodes, re-scored here with src/stl.py
      logs/campaign/prompts/, logs/campaign/responses/
                                  the prompt sent and the response received for
                                  each of the 300 attempts
      logs/llm_raw/synth_*.json   the 21 baseline-synthesis API records
      logs/e1_phase_a.log, logs/e1_phase_b.log
                                  campaign run logs (wall-clock time)

    LOCAL means a source that is NOT in the released repository: the full
    trace store data/traces/ and the logs/llm_raw/ records other than
    synth_*. No claim depends on one. They are read only for an optional
    note (GEN-01, submitted text only) or as a fallback when a released
    directory above is missing, and --no-local skips them, so a run with
    --no-local is exactly what a fresh clone can do. The run takes about
    90 s, most of it re-scoring trajectories.

    Two claims (TAXC-08, TAXC-09) are about the order of commits in the
    development history. They are recomputed from git when that history is
    present (the attempts record the commit they ran from). A checkout
    without it, such as an export or a snapshot whose history starts after
    the campaign, reports them NOT-RECOMPUTABLE rather than MISMATCH.

TWO VERSIONS OF THE PAPER (camera-ready revision, 10 Oct 2026)
    The registry covers both the submitted text (git tag v1.0-submission) and
    the camera-ready revision. A claim tagged `only="v1.0"` exists only in the
    submitted text and one tagged `only="v1.1"` only in the camera-ready; the
    rest apply to both. The version is detected from the tex (the camera-ready
    loads the style with [final]) and can be forced with --version.

    The camera-ready \\input{}s paper/checklist.tex. Included files are read
    and checked too; their rows report `checklist.tex:<line>`. The coverage
    scan reads only the "Justification:" answers of the checklist, not the
    template's guideline text.

    Rows recomputed from released trajectories and logs (until the public
    release these sources were git-ignored and the rows were LOCAL only):
      * every cell of the expressiveness table (Table 4 in the camera-ready)
        and the clean repair's six repeats, re-scored from
        data/dsl_probe_traces/ with src/stl.py, each trace linked to its
        certificate by parameter hash and to a committed .bt program by
        sha256 of the program source; the committed artefacts
        (dsl_expressiveness.json, baseline_eval.json,
        clean_repair_validation.json) must agree;
      * the calibration-set entry and completion of the frozen baseline,
        from data/calibration_traces/;
      * all 300 prompts regenerated from the certificates (F1 from
        data/certificates/traces/) and compared with logs/campaign/prompts/;
        the F1 excerpt size (21 rows x 45 columns) for all 60 F1 prompts;
      * the checklist's wall-clock figures (logs/e1_phase_*.log).

SECOND CAMERA-READY PASS (10 Oct 2026, after the round-2 revision)
    * Claims reworded in round 2 were re-anchored; claims whose sentence was
      removed were dropped from the v1.1 registry (CRT-10, DSL-C4), and shared
      claims whose wording now exists only in the submitted text were tagged
      v1.0 (V10_ONLY), each with a v1.1 counterpart.
    * New v1.1 claims: the inline skeleton-edit counts (PT-13), the Section
      4.1 repeat of the 76.7-point interval (PT-02b/03b), the F1 range 51.7 to
      76.7 (PT-10c), F1-F4a / F1-F4b and the 19-contrast statement (APD-12 to
      APD-15), the clean repair's patch read from the program sources (DSL-P1
      to DSL-P4) and the hand-written path-check family (DSL-P5), Appendix A's
      feedback-block row and scaffolding (APA-04/05), the baseline's 95% suite
      completion (CRT-11), the power range 0.17 to 0.23 (APE-11), and others.
    * Integrity check I-20: uncertainty.json skeleton_edit_pairwise.
    * Coverage now counts only the match a claim evaluates (claim.occurrence),
      not every match of its pattern, and "$95\\%$" is masked only where it
      names an interval level.
    * A word-level scan (informational, not in the exit code) lists number
      words in the body that no claim evaluates.
    * The funnel figure's round-2 bar labels and title are read.

PUBLIC RELEASE PASS (10 Oct 2026)
    * Rows that read git-ignored trajectories and logs now read the released
      copies (see DATA), so a fresh clone recomputes them; --no-local is the
      fresh-clone mode. The expressiveness table's "fixed" cells, the clean
      repair's 20/20 and its six repeats are re-scored from trajectories, with
      the committed artefacts required to agree, instead of being read from
      those artefacts.
    * I-09 regenerates all 300 prompts, F1 included; I-10 also checks that
      every saved response contains the program logged for it.
    * New integrity checks: I-21 (probe trajectories match their manifest),
      I-22 (calibration re-score equals baseline_calibration_frozen.json),
      I-23 (probe re-score equals dsl_probe_rescore.json and
      clean_repair_rescore.json, episode by episode).
    * TAXC-08/09 report NOT-RECOMPUTABLE when the campaign's commit is not in
      the checkout's history, instead of a spurious MISMATCH.
    * The figure check saves with make_figures.SAVE_METADATA, so the
      regenerated PDFs are compared byte for byte with the included ones.

The script is importable: `run(tex_path)` returns (rows, integrity, coverage).
"""
from __future__ import annotations

import argparse
import collections
import dataclasses
import decimal
import functools
import glob
import hashlib
import json
import math
import pathlib
import re
import shutil
import statistics
import subprocess
import sys
from fractions import Fraction
from typing import Any, Callable

REPO = pathlib.Path(__file__).resolve().parent.parent
CONDS = ["F1", "F2", "F3", "F4a", "F4b"]
N_BOOT = 10000
BOOT_SEED = 0          # the seed scripts/uncertainty.py uses

decimal.getcontext().prec = 40


# =============================================================================
# Data access. Everything is loaded lazily and cached, relative to `repo`.
# =============================================================================
class NotRecomputable(Exception):
    """Raised by a compute function when no committed artefact supports it."""


class Ctx:
    def __init__(self, repo: pathlib.Path = REPO, local: bool = True):
        self.repo = repo
        self.local = local         # False: skip every LOCAL (unreleased) source, as on a fresh clone
        src = str(repo / "src")
        if src not in sys.path:
            sys.path.insert(0, src)

    # -- raw loaders --------------------------------------------------------
    def p(self, rel: str) -> pathlib.Path:
        return self.repo / rel

    def json(self, rel: str):
        return json.loads(self.p(rel).read_text())

    def jsonl(self, rel: str) -> list[dict]:
        return [json.loads(l) for l in self.p(rel).read_text().splitlines() if l.strip()]

    def yaml(self, rel: str):
        import yaml
        return yaml.safe_load(self.p(rel).read_text())

    @functools.cached_property
    def attempts(self) -> list[dict]:
        return self.jsonl("data/results/attempts.jsonl")

    @functools.cached_property
    def patches(self) -> list[dict]:
        return self.jsonl("data/results/patches.jsonl")

    @functools.cached_property
    def certs(self) -> list[dict]:
        return [json.loads(pathlib.Path(f).read_text())
                for f in sorted(glob.glob(str(self.p("data/certificates/CE*.json"))))]

    @functools.cached_property
    def baseline_eval(self) -> dict:
        return self.json("data/results/baseline_eval.json")

    @functools.cached_property
    def contracts_cfg(self) -> dict:
        return self.yaml("config/contracts.yaml")

    @functools.cached_property
    def sim_cfg(self) -> dict:
        return self.yaml("config/sim.yaml")

    @functools.cached_property
    def exp_cfg(self) -> dict:
        return self.yaml("config/experiment.yaml")

    # -- derived ------------------------------------------------------------
    def by_cond(self, cond: str) -> list[dict]:
        return [a for a in self.attempts if a["condition"] == cond]

    def count(self, pred: Callable[[dict], bool], cond: str | None = None) -> int:
        rows = self.attempts if cond is None else self.by_cond(cond)
        return sum(1 for a in rows if pred(a))

    @functools.cached_property
    def baseline_gap(self) -> float:
        gaps = {round(v["generalization_gap"], 6) for v in self.baseline_eval.values()}
        if len(gaps) != 1:
            raise NotRecomputable(f"baseline generalization gap not unique: {gaps}")
        return gaps.pop()

    @functools.cached_property
    def boot(self) -> "Boot":
        return Boot(self.attempts, seed=BOOT_SEED, n_boot=N_BOOT)


# =============================================================================
# Cluster bootstrap over certificates. Same resampling unit, seed, resample
# count and percentile rule as scripts/uncertainty.py, re-implemented here so
# the committed uncertainty.json can be checked against it, and extended to
# every pair of conditions (uncertainty.json stores only differences vs F3, so
# the paper's F1-F2 interval is not in any committed file).
# =============================================================================
PREDICATES: dict[str, Callable[[dict], bool]] = {
    "resolved": lambda r: bool(r.get("resolved")),
    "resolved_ex_refusal": lambda r: bool(r.get("resolved")) and not r.get("resolved_by_refusal"),
    "skeleton_edit": lambda r: r.get("patch_type") == "skeleton_edit",
    "regression": lambda r: (r.get("regression_failures") or 0) >= 1,
}


class Boot:
    def __init__(self, rows: list[dict], seed: int, n_boot: int):
        import numpy as np
        self.np = np
        by_cert = collections.defaultdict(list)
        for r in rows:
            by_cert[r["certificate_id"].split("_")[0]].append(r)
        self.certs = sorted(by_cert)
        k = len(self.certs)
        self.k, self.n_boot, self.seed = k, n_boot, seed
        # One generator, consumed exactly as uncertainty.py consumes it: one
        # rng.integers(0, k, k) call per resample. Each metric there re-seeds
        # with the same seed, so the picks are shared across metrics.
        rng = np.random.default_rng(seed)
        self.picks = np.stack([rng.integers(0, k, k) for _ in range(n_boot)])
        self.N = np.zeros((k, len(CONDS)), dtype=np.int64)
        self.S = {m: np.zeros((k, len(CONDS)), dtype=np.int64) for m in PREDICATES}
        for i, c in enumerate(self.certs):
            for r in by_cert[c]:
                j = CONDS.index(r["condition"])
                self.N[i, j] += 1
                for m, f in PREDICATES.items():
                    self.S[m][i, j] += int(f(r))
        self.rates = {}
        for m in PREDICATES:
            succ = self.S[m][self.picks].sum(axis=1)
            n = self.N[self.picks].sum(axis=1)
            self.rates[m] = 100.0 * succ / n

    def point(self, m: str, c: str) -> float:
        j = CONDS.index(c)
        return 100.0 * int(self.S[m][:, j].sum()) / int(self.N[:, j].sum())

    def _ci(self, a) -> tuple[float, float]:
        np = self.np
        a = a[np.isfinite(a)]
        return float(np.percentile(a, 2.5)), float(np.percentile(a, 97.5))

    def ci(self, m: str, c: str) -> tuple[float, float]:
        return self._ci(self.rates[m][:, CONDS.index(c)])

    def diff(self, m: str, a: str, b: str) -> tuple[float, tuple[float, float]]:
        d = self.rates[m][:, CONDS.index(a)] - self.rates[m][:, CONDS.index(b)]
        return self.point(m, a) - self.point(m, b), self._ci(d)

    def diff_alpha(self, m: str, a: str, b: str, alpha: float) -> tuple[float, float]:
        """Percentile interval at level 1 - alpha (Bonferroni sensitivity).

        Same resamples as `diff`; the same np.percentile call that
        scripts/uncertainty.py::pct_ci makes."""
        np = self.np
        d = self.rates[m][:, CONDS.index(a)] - self.rates[m][:, CONDS.index(b)]
        d = d[np.isfinite(d)]
        return float(np.percentile(d, 100 * alpha / 2)), float(np.percentile(d, 100 * (1 - alpha / 2)))

    def n_per_cond_in_resamples(self) -> set:
        """Every per-condition denominator that occurs in any resample."""
        return set(int(x) for x in self.N[self.picks].sum(axis=1).ravel())


# =============================================================================
# Value handling
# =============================================================================
WORDS = {
    "zero": 0, "none": 0, "one": 1, "once": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "three hundred": 300,
}
NUM = r"[-+]?\d+(?:\{,\}\d{3})*(?:\.\d+)?"


def W(name: str) -> str:
    """Named group for a number word (or digits)."""
    words = "|".join(sorted((w for w in WORDS), key=len, reverse=True))
    return rf"(?P<{name}>(?i:{words})|\d+)"


def G(name: str) -> str:
    return rf"(?P<{name}>{NUM})"


def parse_paper(s: str) -> decimal.Decimal:
    t = s.strip().replace("{,}", "").replace(",", "").replace("\\,", "")
    key = re.sub(r"\s+", " ", t.lower())
    if key in WORDS:
        return decimal.Decimal(WORDS[key])
    return decimal.Decimal(t.lstrip("+"))


def n_decimals(s: str) -> int:
    t = s.replace("{,}", "")
    return len(t.split(".")[1]) if "." in t else 0


def to_dec(x) -> decimal.Decimal:
    if isinstance(x, bool):
        return decimal.Decimal(int(x))
    if isinstance(x, Fraction):
        return decimal.Decimal(x.numerator) / decimal.Decimal(x.denominator)
    if isinstance(x, float):
        return decimal.Decimal(repr(x))
    return decimal.Decimal(x)


def round_like(x, paper_str: str) -> decimal.Decimal:
    q = decimal.Decimal(1).scaleb(-n_decimals(paper_str))
    return to_dec(x).quantize(q, rounding=decimal.ROUND_HALF_UP)


def show(x) -> str:
    if isinstance(x, bool):
        return str(x)
    if isinstance(x, Fraction):
        if x.denominator == 1:
            return str(x.numerator)
        return f"{float(x):.6f}".rstrip("0").rstrip(".") + f" (={x.numerator}/{x.denominator})"
    if isinstance(x, float):
        return f"{x:.6f}".rstrip("0").rstrip(".") if abs(x) < 1e6 else f"{x:.0f}"
    return str(x)


# =============================================================================
# Claims
# =============================================================================
@dataclasses.dataclass
class Claim:
    cid: str
    desc: str
    pattern: str                       # regex with named groups
    compute: Callable[[Ctx], Any]      # -> value, or tuple matching `groups`
    basis: str
    groups: tuple[str, ...] = ("v",)   # groups compared, in order
    kind: str = "num"                  # num | bool | approx | approx_abs
    occurrence: int = 0                # which match of `pattern` (0-based)
    tol: float = 0.0                   # relative tolerance (approx); absolute (approx_abs)
    note: str = ""
    only: str | None = None            # None: both versions; "v1.0" submitted; "v1.1" camera-ready

    def __post_init__(self):
        # Robust to reflow: a literal space left in a pattern (text concatenated
        # outside ws()) would fail when the editor rewraps that line.
        out, i, p = [], 0, self.pattern
        while i < len(p):
            ch = p[i]
            if ch == "\\" and i + 1 < len(p):
                out.append(r"\s+" if p[i + 1] == " " else p[i:i + 2])   # keep escapes intact
                i += 2
                continue
            out.append(r"\s+" if ch == " " else ch)
            i += 1
        self.pattern = "".join(out)


@dataclasses.dataclass
class Row:
    cid: str
    line: int | None
    desc: str
    paper: str
    recomputed: str
    status: str
    basis: str
    note: str = ""
    file: str = "main.tex"

    def where(self) -> str:
        if self.line is None:
            return "-"
        return str(self.line) if self.file == "main.tex" else f"{self.file}:{self.line}"


def ws(s: str) -> str:
    """Turn literal spaces in a pattern into flexible whitespace."""
    return s.replace(" ", r"\s+")


def NR(reason: str):
    def f(_ctx):
        raise NotRecomputable(reason)
    return f


# ---- recurring computations -------------------------------------------------
def pct(k: int, n: int) -> Fraction:
    return Fraction(100 * k, n)


def skel(ctx: Ctx, c: str) -> int:
    return ctx.count(lambda a: a["patch_type"] == "skeleton_edit", c)


def skel_recomputed(ctx: Ctx, c: str) -> int:
    """Patch type re-derived from program source, not read from the log."""
    from ted import classify_patch
    return sum(1 for a in ctx.by_cond(c)
               if classify_patch(a["bt_source_before"], a["bt_source_after"]) == "skeleton_edit")


def is_clean(a: dict) -> bool:
    return bool(a["resolved_and_completed"]) and (a["regression_failures"] or 0) == 0


def ci_contains_zero(lo: float, hi: float) -> bool:
    return lo <= 0.0 <= hi


def ex_refusal_vs_f3_all_contain_zero(ctx: Ctx):
    b = ctx.boot
    out = {c: b.diff("resolved_ex_refusal", c, "F3") for c in CONDS if c != "F3"}
    ok = all(ci_contains_zero(*ci) for _, ci in out.values())
    detail = "; ".join(f"{c}-F3 {p:+.1f} [{ci[0]:+.1f},{ci[1]:+.1f}]" for c, (p, ci) in out.items())
    return ok, detail


def median_prompt_tokens(ctx: Ctx, c: str) -> Fraction:
    xs = [a["tokens_prompt"] + a["cache_read"] + a["cache_write"] for a in ctx.by_cond(c)]
    return Fraction(statistics.median(xs)).limit_denominator(2)


def h_bits(counts) -> float:
    n = sum(counts)
    return -sum((k / n) * math.log2(k / n) for k in counts if k)


def cond_entropy(pairs) -> float:
    by = collections.defaultdict(collections.Counter)
    for c, node in pairs:
        by[c][node] += 1
    tot = len(pairs)
    return sum((sum(v.values()) / tot) * h_bits(list(v.values())) for v in by.values())


def dsl_variant(ctx: Ctx, needle: str) -> dict:
    d = ctx.json("data/results/dsl_expressiveness.json")
    hits = [v for v in d["variants_tested"] if needle in v["fix"]]
    if len(hits) != 1:
        raise NotRecomputable(f"dsl_expressiveness.json: {len(hits)} variants match {needle!r}")
    return hits[0]


def frac_str(s: str) -> tuple[int, int]:
    a, b = s.split("/")
    return int(a), int(b)


def llm_synth_counts(ctx: Ctx) -> dict:
    rows = ctx.jsonl("logs/llm_index.jsonl")
    syn = [r for r in rows if r["tag"].startswith("synth")]
    by_prompt = collections.Counter(r["call_id"].split("_")[2] for r in syn)
    return {"total": len(syn), "by_prompt": dict(by_prompt),
            "truncated": sum(1 for r in syn if r["stop_reason"] == "max_tokens")}


def baseline_decelerate_fallback(ctx: Ctx) -> float:
    """v_mps of the Decelerate that follows DistanceToStopLineBelow(30.0)."""
    from program_parser import parse
    root = parse(ctx.p("data/scenarios/baseline_program.bt").read_text())
    found = []

    def walk(n):
        kids = list(n.children)
        if n.name == "Sequence" and len(kids) == 2 and kids[0].name == "DistanceToStopLineBelow" \
                and kids[1].name == "Decelerate":
            found.append(float(kids[1].params["v_mps"]))
        for k in kids:
            walk(k)
    walk(root)
    if len(found) != 1:
        raise NotRecomputable(f"expected one stop-line fallback Decelerate, found {found}")
    return found[0]


def gap_thresholds(ctx: Ctx, rel: str) -> list[float]:
    from program_parser import parse
    root = parse(ctx.p(rel).read_text())
    out = []

    def walk(n):
        if n.name == "OncomingGapExceeds":
            out.append(float(n.params["gap_s"]))
        for k in n.children:
            walk(k)
    walk(root)
    return out


def gen_changes(ctx: Ctx) -> dict[str, float]:
    base = ctx.baseline_gap
    return {c: statistics.mean(a["generalization_gap"] for a in ctx.by_cond(c)) - base
            for c in CONDS}


def rho5_means(ctx: Ctx) -> dict[str, float]:
    out = {}
    for c in CONDS:
        xs = [a["rho5_after"] for a in ctx.by_cond(c)]
        if any(x >= 999.0 for x in xs):
            raise NotRecomputable("vacuity sentinel present in rho5_after")
        out[c] = Fraction(sum(Fraction(str(x)) for x in xs), len(xs))
    return out


# ---- the registry -----------------------------------------------------------
A_ATT = "recomputed: data/results/attempts.jsonl"
A_BOOT = ("recomputed: cluster bootstrap over the 20 certificates, 10,000 resamples, "
          "seed 0, percentile 95% (same procedure as scripts/uncertainty.py)")
A_CERT = "recomputed: data/certificates/*.json"
A_PROBE = "recomputed: data/dsl_probe_traces/ re-scored with src/stl.py"
A_CLEAN = ("recomputed: data/dsl_probe_traces/clean_repair/ (all K, including its own counterexample) re-scored "
           "with src/stl.py; attempts.jsonl (own counterexample) and artefact "
           "data/results/clean_repair_validation.json (other 19) must agree")
A_REPEATS = ("recomputed: data/dsl_probe_traces/repeats/ (rss_rep0..5) re-scored with src/stl.py; artefact "
             "data/results/clean_repair_validation.json test_2 must agree")
A_CALIB = ("recomputed: data/calibration_traces/ (100 episodes of the committed calibration run) re-scored "
           "with src/stl.py; they must reproduce baseline_calibration.json's violation count and argmin split")


def claims() -> list[Claim]:
    C: list[Claim] = []
    add = C.append

    # ------------------------------------------------------------------ abstract
    add(Claim("ABS-01", "number of feedback conditions",
              ws(r"vary only the rendering of the failure across ") + W("v") + r"\s+conditions",
              lambda c: len({a["condition"] for a in c.attempts}), A_ATT))
    add(Claim("ABS-02", "repair attempts run",
              ws(r"and run ") + G("v") + r"\s+repair",
              lambda c: len(c.attempts), A_ATT))
    add(Claim("ABS-03", "F1 structural edits / attempts",
              ws(r"edits account for \$") + r"(?P<a>\d+)/(?P<b>\d+)\$" + ws(" attempts under a raw"),
              lambda c: (skel_recomputed(c, "F1"), len(c.by_cond("F1"))),
              "recomputed: patch type re-derived from bt_source_before/after with src/ted.py",
              groups=("a", "b")))
    add(Claim("ABS-04", "F2 structural edits / attempts",
              ws(r"against \$") + r"(?P<a>\d+)/(?P<b>\d+)\$" + ws(" under a natural-language"),
              lambda c: (skel_recomputed(c, "F2"), len(c.by_cond("F2"))),
              "recomputed: patch type re-derived from program source", groups=("a", "b")))
    add(Claim("ABS-05", "F1 minus F2 structural-edit rate, points",
              ws(r"a difference of \$") + G("v") + r"\$" + ws(" points whose"),
              lambda c: pct(skel(c, "F1") - skel(c, "F2"), 60), A_ATT))
    add(Claim("ABS-06", "95% interval of F1 minus F2 structural-edit rate",
              ws(r"whose \$95\\%\$ interval is \$\[") + G("a") + "," + G("b") + r"\]\$",
              lambda c: c.boot.diff("skeleton_edit", "F1", "F2")[1], A_BOOT, groups=("a", "b"),
              note="not stored in any committed file: uncertainty.json holds only differences vs F3"))
    add(Claim("ABS-07", "no reliable ex-refusal improvement (every CI vs F3 contains 0)",
              r"(?P<v>" + ws(r"After excluding refusals we did not detect a reliable") + r")",
              ex_refusal_vs_f3_all_contain_zero, A_BOOT, kind="bool", occurrence=0))
    add(Claim("ABS-08", "share of apparent repairs that were refusals, %",
              r"\$" + G("v") + r"\\%\$" + ws(" of apparent repairs were"),
              lambda c: pct(c.count(lambda a: a["resolved_by_refusal"]), c.count(lambda a: a["resolved"])),
              A_ATT))
    add(Claim("ABS-09", "clean repairs (resolved, completed, no regression) / attempts",
              ws(r"and exactly ") + W("a") + ws(" of ") + G("b") + ws(" attempts repaired"),
              lambda c: (c.count(is_clean), len(c.attempts)), A_ATT, groups=("a", "b")))
    add(Claim("ABS-10", "clean repair re-evaluated on all K / on the unseen remainder",
              ws(r"re-evaluated across all ") + W("a") + ws(r" counterexamples, including the ") + W("b"),
              lambda c: (len(c.certs), frac_str(c.json("data/results/clean_repair_validation.json")
                                                ["test_1_generalisation"]["other_19_never_shown"]["resolved"])[1]),
              "K recomputed from data/certificates; unseen count from artefact "
              "data/results/clean_repair_validation.json (CARLA run)", groups=("a", "b")))
    add(Claim("ABS-11", "clean repair resolves and completes all 20",
              r"(?P<v>" + ws(r"it resolves and completes every one") + r")",
              lambda c: (c.json("data/results/clean_repair_validation.json")["test_1_generalisation"]
                         ["all_20"]["resolved_and_completed"] == "20/20", "all_20.resolved_and_completed = 20/20"),
              "from artefact data/results/clean_repair_validation.json (CARLA run)", kind="bool"))
    add(Claim("ABS-12", "safe and completing program found once in 300",
              ws(r"was found ") + W("a") + ws(" in ") + r"(?P<b>three\s+hundred)" + ws(" attempts"),
              lambda c: (c.count(is_clean), len(c.attempts)), A_ATT, groups=("a", "b")))

    # ------------------------------------------------------------- introduction
    add(Claim("INT-01", "largest and most robust effect is on edit kind",
              r"(?P<v>" + ws(r"Our largest and most robust effect is on the") + r")",
              lambda c: largest_effect_is_skeleton(c), A_BOOT, kind="bool"))
    add(Claim("INT-02", "76.7-point difference 'between the least and most processed conditions'",
              r"\$" + G("v") + r"\$-point difference in structural-edit rate between the least and\s+most\s+processed",
              lambda c: least_vs_most_processed(c), A_ATT,
              note="76.7 is F1 vs F2; F2 (narrative only) is not the most processed condition"))
    add(Claim("INT-03", "contribution 4: no detected improvement in repair success",
              r"(?P<v>" + ws(r"An absence of any detected improvement in repair success") + r")",
              ex_refusal_vs_f3_all_contain_zero, A_BOOT, kind="bool"))

    # ---------------------------------------------------------------- related
    add(Claim("REL-01", "Reflexion ablation: pass@1 without reflection",
              ws(r"exactly to baseline, \$") + G("v") + r"\$",
              NR("external citation (Reflexion, Table 3); checked by hand against the cited paper during revision"),
              "external"))
    add(Claim("REL-02", "Reflexion: base model pass@1",
              ws(r"pass@1 against \$") + G("v") + r"\$",
              NR("external citation (Reflexion, Table 3)"), "external"))
    add(Claim("REL-03", "Reflexion: full method pass@1",
              ws(r"where full Reflexion reaches \$") + G("v") + r"\$",
              NR("external citation (Reflexion, Table 3)"), "external"))
    add(Claim("REL-04", "Self-Debugging TransCoder with trace, %",
              ws(r"on TransCoder, \$") + G("v") + r"\\%\$",
              NR("external citation (Self-Debugging, Table 2b); checked by hand against the cited paper during revision"), "external"))
    add(Claim("REL-05", "Self-Debugging TransCoder unit-test only, %",
              ws(r"against \$") + G("v") + r"\\%\$" + ws(" for unit-test"),
              NR("external citation (Self-Debugging, Table 2b)"), "external"))
    # Added in verification (9 Oct): a number word the digit-only coverage scan
    # cannot see, so it was silently unregistered.
    add(Claim("REL-06", "Orvalho et al.: number of models evaluated",
              ws(r"improves repair across ") + W("v") + ws(" models"),
              NR("external citation (orvalho2025cegis); not checked here (no network)"), "external"))
    # Added in verification: RSS lemma and rule numbers were masked out of the
    # coverage scan rather than registered like the other external citations.
    add(Claim("TAB1-RSS", "RSS citation: lemma for the safe distance / rule numbers for C2 and avoidability",
              ws(r"& RSS Lemma ") + r"(?P<a>\d+)" + r"[\s\S]*?" + ws(r"is that work's rule~") + r"(?P<b>\d+)"
              + ws(r" and the avoidability filter is its rule~") + r"(?P<c>\d+)",
              NR("external citation (shalevshwartz2017rss); not checked here (no network)"), "external",
              groups=("a", "b", "c")))

    # ----------------------------------------------------------------- method
    add(Claim("MET-01", "junction approaches ('four-way')",
              ws(r"fixed signalised ") + W("v") + r"-way",
              lambda c: c.json("data/results/determinism_gate.json")["junction"]["n_traffic_lights"],
              "from artefact data/results/determinism_gate.json (junction.n_traffic_lights, read from CARLA)"))
    add(Claim("MET-02", "simulation rate, Hz",
              ws(r"runs synchronously at \\mbox{") + G("v") + r"\\,Hz",
              lambda c: sim_rate(c),
              "recomputed: 1 / fixed_delta_seconds, config/sim.yaml"))
    add(Claim("MET-03", "contracts that reproduce exactly / total",
              ws(r"and ") + W("a") + ws(" of the ") + W("b") + ws(" contracts reproduce exactly"),
              lambda c: contracts_reproducing(c),
              "from artefact data/results/determinism_c4.json (6 CARLA repeats x 3 scenarios)",
              groups=("a", "b")))
    add(Claim("MET-04", "max rho_4 spread over identical parameters, m (first mention)",
              ws(r"varies by up to \\mbox{") + G("v") + r"\\,m",
              lambda c: max_c4_spread(c),
              "from artefact data/results/determinism_c4.json"))
    add(Claim("MET-05", "attempts in which rho_4 was binding / attempts",
              ws(r"was the binding contract in \$") + G("a") + ws(r"\$ of \$") + G("b") + r"\$",
              lambda c: (c.count(lambda a: a["argmin_contract_after"] == "C4" or a["c4_binding_after"]),
                         len(c.attempts)), A_ATT, groups=("a", "b")))
    add(Claim("TAB1-01", "tau_yield, s",
              r"\$\\tau_\{\\text\{yield\}\}\$\s*&\s*" + G("v") + r"\\,s",
              lambda c: c.contracts_cfg["C2_yield"]["tau_yield_s"], "recomputed: config/contracts.yaml"))
    add(Claim("TAB1-02", "a_comfort, m/s^2",
              ws(r"of headroom &") + r"\s*" + G("v") + r"\\,m/s",
              lambda c: c.contracts_cfg["C5_comfort"]["a_comfort_mps2"], "recomputed: config/contracts.yaml"))

    # --------------------------------------------------------------- baseline
    add(Claim("BAS-01", "baseline synthesis: number of samples",
              ws(r"from one fixed prompt, sampled ") + G("v") + ws(" times"),
              lambda c: synth_samples(c),
              "recomputed: logs/llm_index.jsonl (committed index of every LLM call)"))
    add(Claim("BAS-02", "baseline synthesis: syntactically valid candidates",
              ws(r"of which ") + G("v") + ws(" were syntactically valid"),
              lambda c: len(c.json("data/results/baseline_calibration.json")["candidates"]),
              "recomputed: data/results/baseline_calibration.json (candidates scored) and "
              "data/scenarios/candidates/*.bt",
              note=""))
    add(Claim("BAS-03", "calibration set size",
              ws(r"measured on a shared ") + G("v") + r"-scenario",
              lambda c: calib_n(c), "recomputed: data/results/baseline_calibration.json"))
    add(Claim("BAS-04", "violation-rate band",
              ws(r"a violation rate in \$\[") + G("a") + "," + G("b") + r"\]\$",
              lambda c: tuple(c.json("data/results/baseline_calibration.json")["band"]),
              "recomputed: data/results/baseline_calibration.json", groups=("a", "b")))
    add(Claim("BAS-05", "completion gate floor, %",
              ws(r"task completion above \$") + G("v") + r"\\%\$",
              lambda c: icr_floor(c),
              "recomputed: ICR_FLOOR in scripts/calibrate_baseline.py",
              note="the gate's outcome per candidate is NOT in the committed baseline_calibration.json "
                   "(no ICR/PCR fields; file predates gate 1b)"))
    add(Claim("BAS-06", "frozen baseline violation rate on calibration set, %",
              ws(r"The frozen baseline violates on \$") + G("v") + r"\\%\$",
              lambda c: frozen_violation_rate(c),
              "recomputed: baseline_calibration.json (cand_01) + TED(frozen, cand_01) = 0"))
    add(Claim("BAS-07", "frozen baseline junction entry on calibration set, %",
              ws(r"enters the junction in \$") + G("v") + r"\\%\$",
              lambda c: calib_local_rate(
                  c, "entered", "no committed artefact records junction entry for the calibration run: "
                  "baseline_calibration.json has no entry/ICR field"),
              A_CALIB))
    add(Claim("BAS-08", "frozen baseline completion on calibration set, %",
              ws(r"completes\s+the turn in \$") + G("v") + r"\\%\$",
              lambda c: calib_local_rate(
                  c, "settled", "no committed artefact records ICR for the calibration run "
                  "(baseline_calibration.json has no ICR field). 88.3% is also not k/100 for any k, so it "
                  "cannot be a rate over the stated 100-scenario set; it fits 53/60 or 106/120. The frozen "
                  "program's header attributes the same 88.3% to an uncommitted 'independent 60-scenario draw'"),
              A_CALIB,
              note="88.3% matches the header's 'independent 60-scenario draw' (53/60), not the calibration set"))
    add(Claim("BAS-09", "candidates whose distribution is reported",
              ws(r"distribution of all ") + G("v") + ws(" candidates"),
              lambda c: len(c.json("data/results/baseline_calibration.json")["candidates"]),
              "recomputed: data/results/baseline_calibration.json"))

    # ------------------------------------------------------------ falsification
    add(Claim("FAL-01", "scenario-space dimension",
              ws(r"samples a ") + W("v") + r"-parameter",
              lambda c: len(c.yaml("data/scenarios/space.yaml")["parameters"]),
              "recomputed: data/scenarios/space.yaml"))
    add(Claim("FAL-02", "banked counterexamples K",
              ws(r"We banked\s*\$K\{=\}") + G("v") + r"\$",
              lambda c: len(c.certs), A_CERT))
    add(Claim("FAL-03", "mean simulations per banked counterexample",
              ws(r"at a mean cost of \$") + G("v") + r"\$",
              lambda c: falsif_cost(c),
              "from artefact data/results/falsification_summary.json (rollouts_total / K_admitted)",
              note="531 rollouts / 20; excludes 20 verification re-runs (27.55 with them) and 67 cache "
                   "hits; certificate-attributed rollouts sum to 411 (20.55 each)"))

    # ---------------------------------------------------------------- table 2
    for cond, label in [("F1", r"raw trajectory excerpt around the violation"),
                        ("F2", r"natural-language narrative only"),
                        ("F3", r"contract, \$\\rho\$, per-contract \$\\rhoc\{i\}\$, minimal params, boundary, narrative"),
                        ("F4a", r"F3 plus \\texttt\{active\\_node\}"),
                        ("F4b", r"F3 plus \\texttt\{authorising\\_node\}")]:
        add(Claim(f"TAB2-{cond}", f"median prompt tokens, {cond}",
                  rf"{cond}\s*&\s*" + ws(label) + r"\s*&\s*" + G("v"),
                  functools.partial(lambda c, cond: median_prompt_tokens(c, cond), cond=cond),
                  "recomputed: attempts.jsonl served usage (tokens_prompt + cache_read + cache_write), "
                  "median over the 60 attempts; equals prompt_budget.json per-certificate counts"))
    add(Claim("TAB2-cap1", "scaffolding prefix bytes",
              r"the\s+" + G("v") + ws(r" bytes of prefix"),
              lambda c: len(template(c).prefix.encode()),
              "recomputed: data/prompts/patch_task.md filled with the frozen program, vocabulary and "
              "config/contracts.yaml, split at {feedback}"))
    add(Claim("TAB2-cap2", "scaffolding suffix bytes",
              ws(r"bytes of prefix and ") + G("v") + ws(" bytes of suffix"),
              lambda c: len(template(c).suffix.encode()), "recomputed: same template split"))
    add(Claim("TAB2-cap3", "prefix and suffix byte-identical across 5 conditions x 20 certificates",
              ws(r"are byte-identical across all ") + W("a") + ws(r" conditions and all") + r"\s+" + W("b")
              + r"\s+certificates",
              lambda c: (len(CONDS), len(c.certs)),
              "recomputed: counts; the identity itself is checked in INTEGRITY I-09/I-10", groups=("a", "b"),
              note="I-09 regenerates all 300 prompts (F1 from data/certificates/traces/) and hash-matches them; "
                   "I-10 checks the 300 saved prompts in logs/campaign/prompts/"))
    add(Claim("CON-01", "unwindowed F1 prompt, median tokens",
              ws(r"F1 prompt measures ") + G("v") + ws(" tokens at the median"),
              lambda c: c.json("data/results/prompt_budget.json")["f1_window_ladder"]["full trace"]["median"],
              "from artefact data/results/prompt_budget.json (count_tokens API call; not recomputable offline)",
              note="check_prompt_budget.py stores int(median); a .5 median would be truncated"))
    add(Claim("CON-02", "unwindowed F1 / B",
              r"\$" + G("v") + r"\\times\$" + ws(" the per-attempt"),
              lambda c: Fraction(c.json("data/results/prompt_budget.json")["f1_window_ladder"]["full trace"]["median"],
                                 c.exp_cfg["token_budget_B"]),
              "recomputed from artefact prompt_budget.json and config/experiment.yaml"))
    add(Claim("CON-03", "per-attempt prompt budget B (first mention)",
              ws(r"budget of ") + G("v") + ws(r", so it must be windowed"),
              lambda c: c.exp_cfg["token_budget_B"], "recomputed: config/experiment.yaml"))
    add(Claim("CON-04", "F1 window half-width, rows",
              ws(r"fitting every\s*certificate \(\$\\pm ") + G("v") + r"\$",
              lambda c: f1_window(c),
              "config/experiment.yaml (f1_excerpt_halfwidth_rows) + artefact prompt_budget.json "
              "(largest ladder rung with over_B = 0)",
              note="verification (9 Oct): 'largest' holds only on the tested ladder (5, 10, 15, 20, 25, 50, 100); "
                   "half-widths 11-14 were never measured. The ladder maximum is linear (11,867 / 18,319 / "
                   "24,772 at 5 / 10 / 15), about 1,290 tokens per unit of half-width, so +-11 would be about "
                   "19,610 < 20,000 and probably fits. Unverified: needs the count_tokens API"))
    add(Claim("CON-05", "rows back to the F4b transition: min, max",
              ws(r"which lies ") + G("a") + ws(" to ") + G("b") + ws(r" rows back in all"),
              lambda c: rows_back(c),
              "from artefact data/results/prompt_budget.json (f1_window_reach_vs_f4b)",
              groups=("a", "b")))
    add(Claim("CON-06", "certificates for which the transition is outside the window",
              ws(r"rows back in all ") + W("v") + ws(" cases"),
              lambda c: rows_back_all(c),
              "from artefact data/results/prompt_budget.json (n - inside_configured_window)"))

    # ------------------------------------------------------------------ scope
    add(Claim("SCO-01", "pre-specified contracts / parameters",
              ws(r"Our internal study plan pre-specified ") + W("a") + ws(" contracts and ") + W("b")
              + ws(" scenario parameters"),
              lambda c: prereg_scope(c),
              "from artefact 01_TECHNICAL_SPEC_v2.md (spec v2 change table and section 6.1)",
              groups=("a", "b")))
    add(Claim("SCO-03", "parameter space 'grew to six because two of those parameters' make the new contracts bind",
              r"(?P<v>" + ws(r"the parameter space grew to six because") + r"\s+"
              + ws(r"two of those parameters are what make the new contracts bind") + r")",
              lambda c: param_composition(c),
              "recomputed: 01_TECHNICAL_SPEC_v2.md section 6.1 table vs data/scenarios/space.yaml "
              "(parameters and dropped)", kind="bool",
              note="added in verification (9 Oct)"))
    add(Claim("SCO-02", "contracts / parameters actually run",
              ws(r"We ran ") + W("a") + ws(" and ") + W("b"),
              lambda c: (len(c.json("data/results/falsification_summary.json")["active_contracts"]),
                         len(c.yaml("data/scenarios/space.yaml")["parameters"])),
              "recomputed: falsification_summary.json active_contracts, data/scenarios/space.yaml",
              groups=("a", "b")))

    # ------------------------------------------------------------- generation
    add(Claim("GEN-01", "max_tokens (first mention), stated for 'All calls'",
              ws(r"with \\texttt{max\\_tokens} \$=") + G("v") + r"\$ and prompt caching",
              lambda c: max_tokens_all_calls(c),
              A_ATT + " and logs/llm_index.jsonl (every logged call)",
              note="changed in verification (9 Oct): the sentence opens 'All calls use', so the check now "
                   "covers every logged call, not only the 300 repair attempts"))
    add(Claim("GEN-02", "distinct programs per (condition, certificate) cell",
              r"We measured \$" + G("v") + r"\$" + ws(" distinct programs"),
              lambda c: distinct_programs(c), A_ATT))
    add(Claim("GEN-03", "replicates per cell",
              ws(r"\(condition, certificate\) cell out of \$") + G("v") + r"\$",
              lambda c: len({a["seed"] for a in c.attempts}), A_ATT))
    add(Claim("GEN-04", "prompt budget B (second mention)",
              r"\$B = " + G("v") + r"\$",
              lambda c: c.exp_cfg["token_budget_B"], "recomputed: config/experiment.yaml"))
    add(Claim("GEN-05", "max_tokens (second mention)",
              r"\\texttt\{max\\_tokens\} \$=" + G("v") + r"\$ is a",
              lambda c: single(c, "max_tokens"), A_ATT))
    add(Claim("GEN-06", "attempts none of which hit max_tokens",
              ws(r"across all ") + G("v") + ws(" attempts none hit it"),
              lambda c: c.count(lambda a: a["stop_reason"] != "max_tokens" and a["tokens_completion"] < a["max_tokens"]),
              A_ATT))

    # ---------------------------------------------------------------- results
    add(Claim("RES-01", "conditions x certificates x replicates = attempts",
              W("a") + ws(r" conditions, ") + W("b") + ws(r" certificates and ") + W("c")
              + ws(" replicates give ") + G("d"),
              lambda c: (len(CONDS), len({a["certificate_id"] for a in c.attempts}),
                         len({a["seed"] for a in c.attempts}), len(c.attempts)),
              A_ATT, groups=("a", "b", "c", "d")))
    add(Claim("RES-02", "scenarios per patched-program evaluation",
              ws(r"evaluated on ") + G("v") + ws(" scenarios"),
              lambda c: single_val({a["rollouts_counterexample"] + a["rollouts_regression"]
                                    + a["rollouts_evaluation"] for a in c.attempts}),
              A_ATT))
    add(Claim("RES-03", "regression suite size (baseline passes all)",
              ws(r"the counterexample, a ") + G("v") + "-scenario regression",
              lambda c: regression_suite_n(c),
              "recomputed: data/scenarios/regression_suite.json (n, baseline_scvr = 0) and "
              "baseline_eval.json (0 regression failures)"))
    add(Claim("RES-04", "held-out suite size",
              ws(r"and a ") + G("v") + "-scenario held-out",
              lambda c: c.json("data/scenarios/held_out_suite.json")["n"],
              "recomputed: data/scenarios/held_out_suite.json"))
    add(Claim("RES-05", "attempts with no malformed and no truncated output",
              ws(r"Across all ") + G("v") + ws(r" attempts we observed no malformed"),
              lambda c: c.count(lambda a: a["outcome"] == "ok" and a["validator_ok"]
                                and a["stop_reason"] != "max_tokens"), A_ATT))

    # ------------------------------------------------------------- 4.1 table 3
    rowpat = (ws(r"skeleton edits \(of ") + r"(?P<n>\d+)\)\s*&\s*\\textbf\{(?P<a>\d+)\}\s*&\s*(?P<b>\d+)"
              r"\s*&\s*(?P<c>\d+)\s*&\s*(?P<d>\d+)\s*&\s*(?P<e>\d+)")
    for g, cond in zip("abcde", CONDS):
        add(Claim(f"TAB3-{cond}", f"structural edits, {cond} (of 60)", rowpat,
                  functools.partial(lambda c, cond: skel_recomputed(c, cond), cond=cond),
                  "recomputed: patch type re-derived from program source with src/ted.py",
                  groups=(g,)))
    add(Claim("TAB3-n", "attempts per condition in table 3", rowpat,
              lambda c: single_val({len(c.by_cond(x)) for x in CONDS}), A_ATT, groups=("n",)))
    add(Claim("PT-01", "largest and most robust condition-dependent effect",
              r"(?P<v>" + ws(r"This is the largest and most robust") + r")",
              lambda c: largest_effect_is_skeleton(c), A_BOOT, kind="bool"))
    add(Claim("PT-02", "F1 minus F2 structural-edit rate (table 3 caption)",
              ws(r"F1 versus F2 is a \$") + G("v") + r"\$-point",
              lambda c: pct(skel(c, "F1") - skel(c, "F2"), 60), A_ATT))
    add(Claim("PT-03", "95% interval, F1 minus F2 structural (table 3 caption)",
              ws(r"difference, \$95\\%\$ interval \$\[") + G("a") + "," + G("b") + r"\]\$",
              lambda c: c.boot.diff("skeleton_edit", "F1", "F2")[1], A_BOOT, groups=("a", "b")))
    add(Claim("PT-04", "attempts per condition (figure 3 caption)",
              ws(r"by condition, out of ") + G("v") + ws(" attempts each"),
              lambda c: single_val({len(c.by_cond(x)) for x in CONDS}), A_ATT))
    add(Claim("PT-05", "F1 structural-edit rate, %",
              ws(r"restructuring in \$") + G("v") + r"\\%\$",
              lambda c: pct(skel(c, "F1"), 60), A_ATT))
    add(Claim("PT-06", "F2 structural-edit rate, %",
              ws(r"summary does so in \$") + G("v") + r"\\%\$",
              lambda c: pct(skel(c, "F2"), 60), A_ATT))
    add(Claim("PT-07", "F4b structural-edit rate, %",
              ws(r"between the others at\s*\$") + G("v") + r"\\%\$",
              lambda c: pct(skel(c, "F4b"), 60), A_ATT))
    add(Claim("PT-08", "95% interval, F4b minus F3 structural",
              ws(r"its interval against F3 is\s*\$\[") + G("a") + "," + G("b") + r"\]\$",
              lambda c: c.boot.diff("skeleton_edit", "F4b", "F3")[1], A_BOOT, groups=("a", "b")))
    add(Claim("PT-09", "least processed gives most edits AND most processed give among the fewest",
              r"(?P<v>" + ws(r"the least processed\s*condition produces the most structural edits, and the most processed\s*conditions produce among the fewest") + r")",
              lambda c: ordering_claim(c), A_ATT, kind="bool"))
    add(Claim("PT-10", "raw trace resolvably different from every processed condition (structural)",
              r"(?P<v>" + ws(r"raw-trace condition is qualitatively different from every processed condition") + r")",
              lambda c: f1_differs_from_all(c), A_BOOT, kind="bool"))

    # ------------------------------------------------------------ 4.2 refusal
    add(Claim("REF-01", "baseline entered the junction on counterexamples",
              ws(r"entered\s*the junction in ") + W("a") + ws(" of ") + W("b") + ws(" counterexample scenarios"),
              lambda c: (sum(1 for v in c.baseline_eval.values() if v["ce_entered_conflict_zone"]),
                         len(c.baseline_eval)),
              "from artefact data/results/baseline_eval.json (CARLA run of the frozen baseline)",
              groups=("a", "b")))
    add(Claim("REF-02", "refusals / apparent repairs",
              W("a") + ws(" of the ") + W("b") + ws(r" apparent repairs, "),
              lambda c: (c.count(lambda a: a["resolved_by_refusal"]), c.count(lambda a: a["resolved"])),
              A_ATT, groups=("a", "b")))
    add(Claim("REF-03", "refusal share, % (section 4.2)",
              ws(r"apparent repairs, \$") + G("v") + r"\\%\$",
              lambda c: pct(c.count(lambda a: a["resolved_by_refusal"]), c.count(lambda a: a["resolved"])), A_ATT))
    add(Claim("REF-04", "resolved and completed",
              W("v") + ws(r"\s*attempts both satisfied the contract and completed"),
              lambda c: c.count(lambda a: a["resolved_and_completed"]), A_ATT))
    add(Claim("REF-05", "of those, also no regression",
              ws(r"three, only ") + W("v") + ws(" also left the regression suite intact"),
              lambda c: c.count(is_clean), A_ATT))
    add(Claim("REF-06", "clean repairs across all attempts",
              ws(r"Across ") + G("a") + ws(r" attempts there\s*is exactly ") + W("b") + ws(" clean repair"),
              lambda c: (len(c.attempts), c.count(is_clean)), A_ATT, groups=("a", "b")))
    add(Claim("REF-07", "evaluation-suite size used for completion metrics",
              ws(r"computed over the\s*") + G("v") + "-scenario evaluation suite",
              lambda c: c.json("data/scenarios/regression_suite.json")["n"]
              + c.json("data/scenarios/held_out_suite.json")["n"],
              "recomputed: regression_suite.json n + held_out_suite.json n"))
    add(Claim("REF-08", "pilot: suite completion while the counterexample timed out",
              ws(r"suite completion read \$") + G("v") + r"\$",
              lambda c: pilot_icr(c), "recomputed: data/results/dryrun_attempts.jsonl"))

    # ---------------------------------------------------------------- 4.3 DSL
    add(Claim("DSL-01", "candidate repairs run on all K counterexamples",
              ws(r"running them on all ") + W("v") + ws(" counterexamples"),
              lambda c: len(c.certs), A_CERT))
    T = r"\s*&\s*"
    K20 = lambda c: len(c.certs)
    add(Claim("DSL-T1", "frozen baseline: fixed / completed of K",
              ws(r"frozen baseline") + T + r"(?P<a>\d+)/(?P<an>\d+)" + T + r"(?P<b>\d+)/(?P<bn>\d+)",
              lambda c: probe_cells(c, "baseline", ("fixed", "completed"), art_baseline_eval),
              A_PROBE + " (frozen_baseline/); artefact data/results/baseline_eval.json must agree",
              groups=("a", "an", "b", "bn")))
    # Camera-ready (10 Oct): the row reads "raise gap thresholds (e.g.\ $5.5
    # \rightarrow 9.0$)", so the patterns accept both wordings and the ")".
    add(Claim("DSL-T2a", "gap requirement raised from / to",
              r"raise\s+gap\s+(?:requirement|thresholds\s+\(e\.g\.\\\s*)\s*\$" + G("a")
              + r"\s*\\rightarrow\s*" + G("b") + r"\$",
              lambda c: (gap_thresholds(c, "data/scenarios/baseline_program.bt")[0],
                         gap_thresholds(c, "data/scenarios/dsl_probe/fixA_bigger_gap.bt")[0]),
              "recomputed: data/scenarios/baseline_program.bt vs dsl_probe/fixA_bigger_gap.bt",
              groups=("a", "b")))
    add(Claim("DSL-T2b", "raise gap: fixed of K",
              r"rightarrow\s*9\.0\$\)?" + T + r"(?P<v>\d+)/(?P<vn>\d+)",
              lambda c: probe_cells(c, "fixA", ("fixed",), art_dsl("raise OncomingGapExceeds", "fixed")),
              A_PROBE + " (raise_gap_thresholds/); artefact data/results/dsl_expressiveness.json must agree",
              groups=("v", "vn")))
    add(Claim("DSL-T2c", "raise gap: completed of K",
              r"rightarrow\s*9\.0\$\)?" + T + r"\d+/\d+" + T + r"(?P<v>\d+)/(?P<vn>\d+)",
              lambda c: probe_cells(c, "fixA", ("completed",)),
              A_PROBE + " (raise_gap_thresholds/; dsl_expressiveness.json stores only 'fixed')",
              groups=("v", "vn")))
    add(Claim("DSL-T3a", "gap guard swept up to (validator maximum)",
              ws(r"gap guard on committing branch, up to ") + G("v"),
              lambda c: gap_guard_max(c),
              "recomputed: src/bt_vocabulary.py gap_s upper bound, dsl_probe/sweep_*.bt, "
              "dsl_expressiveness.json"))
    add(Claim("DSL-T3b", "gap guard: fixed of K",
              r"up to 15\.0" + T + r"(?P<v>\d+)/(?P<vn>\d+)",
              lambda c: probe_cells(c, "sweep", ("fixed",), art_dsl("add OncomingGapExceeds guard", "fixed")),
              A_PROBE + " (gap_guard_sweep/, one directory per committed sweep_*.bt); artefact "
              "data/results/dsl_expressiveness.json must agree", groups=("v", "vn")))
    add(Claim("DSL-T3c", "gap guard: completed of K",
              r"up to 15\.0" + T + r"\d+/\d+" + T + r"(?P<v>\d+)/(?P<vn>\d+)",
              lambda c: probe_cells(c, "sweep", ("completed",)),
              A_PROBE + " (gap_guard_sweep/, one directory per committed sweep_*.bt)",
              groups=("v", "vn")))
    add(Claim("DSL-T4b", "geometric guard: fixed of K",
              ws(r"geometric guard on committing branch") + T + r"(?P<v>\d+)/(?P<vn>\d+)",
              lambda c: probe_cells(c, "geometric", ("fixed",), art_dsl("add PathIsClear to branch C", "fixed")),
              A_PROBE + " (geometric_guard/, every variant); artefact data/results/dsl_expressiveness.json "
              "must agree", groups=("v", "vn")))
    add(Claim("DSL-T4c", "geometric guard: completed of K",
              ws(r"geometric guard on committing branch") + T + r"\d+/\d+" + T + r"(?P<v>\d+)/(?P<vn>\d+)",
              lambda c: probe_cells(c, "geometric", ("completed",)),
              A_PROBE + " (geometric_guard/, every variant; each program adds a PathIsClear guard to the "
              "baseline and is a committed data/scenarios/dsl_probe/*.bt)", groups=("v", "vn")))
    add(Claim("DSL-T5", "geometric guard + true stop: fixed / completed of K",
              ws(r"geometric guard \$\+\$ true stop") + T + r"(?P<a>\d+)/(?P<an>\d+)" + T + r"(?P<b>\d+)/(?P<bn>\d+)",
              lambda c: probe_cells(c, "truestop", ("fixed", "completed"), art_dsl("true stop", "fixed", "completed")),
              A_PROBE + " (geometric_guard_true_stop/); artefact data/results/dsl_expressiveness.json must agree",
              groups=("a", "an", "b", "bn")))
    add(Claim("DSL-T6", "model's clean repair: fixed / completed of K",
              ws(r"the model's clean repair, from F1\}") + T + r"\\textbf\{(?P<a>\d+)/(?P<an>\d+)\}" + T
              + r"\\textbf\{(?P<b>\d+)/(?P<bn>\d+)\}",
              lambda c: clean_repair_20(c), A_CLEAN, groups=("a", "an", "b", "bn")))
    add(Claim("DSL-cap", "table 4 caption: the single clean attempt of 300",
              ws(r"The final row is the single attempt\s*of ") + G("v"),
              lambda c: len(c.attempts) if c.count(is_clean) == 1 else f"{c.count(is_clean)} clean",
              A_ATT))
    add(Claim("DSL-M1", "yield predicate speed floor, m/s",
              ws(r"excludes any vehicle slower than \\mbox{") + G("v") + r"\\,m/s",
              lambda c: c.contracts_cfg["C2_yield"]["min_speed_for_ttc_mps"],
              "recomputed: config/contracts.yaml (C2_yield.min_speed_for_ttc_mps, read by the predicate "
              "in src/carla_backend.py)"))
    add(Claim("DSL-M2", "distance of the discarded vehicle, m",
              ws(r"scenario a vehicle \\mbox{") + G("v") + r"\\,m",
              lambda c: dsl_mech_number(c, r"vehicle ([\d.]+) m away"),
              "from artefact data/results/dsl_expressiveness.json (mechanism, measured on CE003)"))
    add(Claim("DSL-M3", "speed of the discarded vehicle, m/s",
              ws(r"away at \\mbox{") + G("v") + r"\\,m/s",
              lambda c: dsl_mech_number(c, r"at ([\d.]+) m/s is"),
              "from artefact data/results/dsl_expressiveness.json"))
    add(Claim("DSL-M4", "predicate cap, s",
              ws(r"the\s*predicate returns its ") + G("v") + r"\\,s\s+cap",
              lambda c: c.contracts_cfg["C2_yield"]["ttc_cap_s"], "recomputed: config/contracts.yaml"))
    add(Claim("DSL-M5", "gap demanded by the guard, s",
              ws(r"a guard demanding ") + G("v") + r"\\,s",
              lambda c: gap_guard_max(c), "recomputed: src/bt_vocabulary.py gap_s upper bound"))
    add(Claim("DSL-M6", "fallback deceleration target, m/s",
              ws(r"decelerates to \\mbox{") + G("v") + r"\\,m/s",
              lambda c: baseline_decelerate_fallback(c), "recomputed: data/scenarios/baseline_program.bt"))
    add(Claim("DSL-M7", "entry delay of the creeping ego, s",
              ws(r"the boundary ") + W("v") + ws(" seconds later"),
              lambda c: dsl_mech_number(c, r"Entry is delayed (\d+) s"),
              "from artefact data/results/dsl_expressiveness.json"))
    add(Claim("DSL-M8", "true stop: resolves all K, completes none",
              ws(r"true stop resolves all ") + W("a") + ws(r" counterexamples and completes ") + W("b"),
              lambda c: probe_cells(c, "truestop", ("fixed", "completed"),
                                    art_dsl("true stop", "fixed", "completed"), with_n=False),
              A_PROBE + " (geometric_guard_true_stop/); artefact data/results/dsl_expressiveness.json must agree",
              groups=("a", "b")))
    add(Claim("DSL-C1", "clean repair: one attempt in 300, under F1",
              ws(r"\\paragraph{A safe and completing repair is nonetheless expressible.}") + r"\s*"
              + W("a") + ws(" attempt in ") + G("b") + ws(r", under the raw-trace condition F1"),
              lambda c: clean_under_f1(c), A_ATT, groups=("a", "b")))
    add(Claim("DSL-C2", "clean repair re-evaluated on K / unseen",
              ws(r"Re-evaluated across all ") + W("a") + r"\s+counterexamples,\s+including\s+the\s+" + W("b"),
              lambda c: (len(c.certs), frac_str(c.json("data/results/clean_repair_validation.json")
                                                ["test_1_generalisation"]["other_19_never_shown"]["completed"])[1]),
              "K recomputed; unseen count from artefact clean_repair_validation.json", groups=("a", "b")))
    add(Claim("DSL-C3", "found once in three hundred; refusal share %",
              ws(r"was found ") + W("a") + ws(r" in\s*") + r"(?P<b>three\s+hundred)" + ws(r" attempts, while \$")
              + G("c") + r"\\%\$",
              lambda c: (c.count(is_clean), len(c.attempts),
                         pct(c.count(lambda a: a["resolved_by_refusal"]), c.count(lambda a: a["resolved"]))),
              A_ATT, groups=("a", "b", "c")))
    add(Claim("DSL-V1", "rho_4 spread (validation paragraph), m",
              ws(r"vary by up to\s*\\mbox{") + G("v") + r"\\,m",
              lambda c: max_c4_spread(c), "from artefact data/results/determinism_c4.json"))
    add(Claim("DSL-V2", "clean repair repeated on its own counterexample",
              ws(r"on its own counterexample ") + W("v") + ws(" times"),
              clean_repeats_n, A_REPEATS))
    add(Claim("DSL-V3", "zero spread in rho and rho_4; rho_4 never binding",
              r"(?P<v>" + ws(r"with zero spread in \$\\rho\$ and zero spread in \$\\rhoc\{4\}\$") + r")",
              lambda c: clean_rss(c), A_REPEATS, kind="bool"))

    # ---------------------------------------------------------------- 4.4 null
    add(Claim("FIG2-01", "only the raw-trace condition separates from zero (figure 2)",
              r"(?P<v>" + ws(r"Only the raw-trace condition separates\s*from zero") + r")",
              lambda c: fig2_only_f1(c), A_BOOT, kind="bool"))
    for cond in CONDS:
        pat = (rf"\n{cond}\s*&\s*" + G("a") + r"\\%\s*&\s*" + G("b") + r"\\%\s*&\s*(?P<c>\d+)/(?P<cn>\d+)"
               r"\s*&\s*(?P<d>\d+)/(?P<dn>\d+)\s*&\s*" + G("e") + r"\s*\\\\")
        add(Claim(f"TAB5-{cond}-fix", f"fix rate, {cond}, %", pat,
                  functools.partial(lambda c, cond: pct(c.count(lambda a: a["resolved"], cond), 60), cond=cond),
                  A_ATT, groups=("a",)))
        add(Claim(f"TAB5-{cond}-exref", f"fix rate excluding refusals, {cond}, %", pat,
                  functools.partial(lambda c, cond: pct(c.count(
                      lambda a: a["resolved"] and not a["resolved_by_refusal"], cond), 60), cond=cond),
                  A_ATT, groups=("b",)))
        add(Claim(f"TAB5-{cond}-drove", f"fixed and completed / attempts, {cond}", pat,
                  functools.partial(lambda c, cond: (c.count(lambda a: a["resolved_and_completed"], cond),
                                                     len(c.by_cond(cond))), cond=cond),
                  A_ATT, groups=("c", "cn")))
        add(Claim(f"TAB5-{cond}-broke", f"caused >= 1 regression failure / attempts, {cond}", pat,
                  functools.partial(lambda c, cond: (c.count(lambda a: (a["regression_failures"] or 0) >= 1, cond),
                                                     len(c.by_cond(cond))), cond=cond),
                  A_ATT, groups=("d", "dn")))
        add(Claim(f"TAB5-{cond}-ted", f"mean TED from original, {cond}", pat,
                  functools.partial(lambda c, cond: mean_ted(c, cond), cond=cond),
                  "recomputed: TED re-derived from bt_source_before/after with src/ted.py", groups=("e",)))
    add(Claim("TAB5-cap", "every ex-refusal difference vs F3 has a CI containing 0 (table 5 caption)",
              r"(?P<v>" + ws(r"Every paired difference against F3\s*has a \$95\\%\$ interval containing zero once refusals are excluded") + r")",
              ex_refusal_vs_f3_all_contain_zero, A_BOOT, kind="bool"))
    add(Claim("NUL-01", "no reliable ex-refusal improvement; every comparison vs F3 contains 0",
              r"(?P<v>" + ws(r"After excluding refusals we did not detect a reliable improvement in repair\s*success from any feedback format. Every paired comparison against F3 has an\s*interval containing zero") + r")",
              ex_refusal_vs_f3_all_contain_zero, A_BOOT, kind="bool"))
    add(Claim("NUL-02", "raw trace clears zero on the pre-specified rate",
              r"(?P<v>" + ws(r"The raw-trace condition clears zero on the\s*pre-specified rate") + r")",
              lambda c: f1_clears_zero_resolved(c), A_BOOT, kind="bool"))
    add(Claim("NUL-03", "F1 refusals / F1 resolutions",
              ws(r"but ") + W("a") + ws(" of its ") + W("b") + ws(" resolutions are refusals"),
              lambda c: (c.count(lambda a: a["resolved_by_refusal"], "F1"), c.count(lambda a: a["resolved"], "F1")),
              A_ATT, groups=("a", "b")))
    add(Claim("NUL-04", "F1 minus F3 excluding refusals, points",
              ws(r"excluding those the difference is \$") + G("v") + r"\$",
              lambda c: pct(c.count(lambda a: a["resolved"] and not a["resolved_by_refusal"], "F1")
                            - c.count(lambda a: a["resolved"] and not a["resolved_by_refusal"], "F3"), 60),
              A_ATT))
    add(Claim("NUL-05", "95% interval, F1 minus F3 excluding refusals",
              ws(r"with an interval of \$\[") + G("a") + "," + G("b") + r"\]\$",
              lambda c: c.boot.diff("resolved_ex_refusal", "F1", "F3")[1], A_BOOT, groups=("a", "b")))
    add(Claim("NUL-06", "K, replicates (section 4.4)",
              ws(r"With \$K\{=\}") + G("a") + ws(r"\$\s*counterexamples, ") + W("b") + ws(" replicates"),
              lambda c: (len(c.certs), len({a["seed"] for a in c.attempts})), A_ATT, groups=("a", "b")))
    add(Claim("NUL-07", "range of successes per condition",
              ws(r"between ") + W("a") + ws(" and ") + W("b") + ws(r" successes per\s*condition"),
              lambda c: (min(c.count(lambda a: a["resolved"], x) for x in CONDS),
                         max(c.count(lambda a: a["resolved"], x) for x in CONDS)), A_ATT, groups=("a", "b")))

    # ---------------------------------------------------------- 4.5 regression
    add(Claim("REG-01", "attempts / attempts with >= 1 regression failure",
              ws(r"Across all ") + G("n") + ws(" attempts, ") + G("v") + r"\s+\(",
              lambda c: (len(c.attempts), c.count(lambda a: (a["regression_failures"] or 0) >= 1)), A_ATT,
              groups=("n", "v")))
    add(Claim("REG-02", "share with >= 1 regression failure, %",
              ws(r"attempts, \d+ \(\$") + G("v") + r"\\%\$\)",
              lambda c: pct(c.count(lambda a: (a["regression_failures"] or 0) >= 1), len(c.attempts)), A_ATT))
    add(Claim("REG-03", "apparent fixes",
              ws(r"regression scenario to fail, against ") + G("v") + ws(" apparent fixes"),
              lambda c: c.count(lambda a: a["resolved"]), A_ATT))
    add(Claim("REG-04", "modal outcome is 'not fixed and broke >= 1', in every condition",
              r"(?P<v>" + ws(r"This holds in every condition") + r")",
              lambda c: modal_outcome(c), A_ATT, kind="bool",
              note="checked under the '>= 1 regression' reading; the text says 'broke one thing'"))
    add(Claim("REG-05", "rho_5 before the patch (all attempts)",
              ws(r"without exception, from \$") + G("v") + r"\$",
              lambda c: Fraction(sum(Fraction(str(a["rho5_before"])) for a in c.attempts), len(c.attempts)),
              A_ATT))
    add(Claim("REG-06", "range of per-condition mean rho_5 after the patch",
              ws(r"to between\s*\$") + G("a") + ws(r"\$ and \$") + G("b") + r"\$",
              lambda c: (min(rho5_means(c).values()), max(rho5_means(c).values())), A_ATT,
              groups=("a", "b")))
    add(Claim("REG-07", "rho_5 degrades in every condition",
              r"(?P<v>" + ws(r"\$\\rhoc\{5\}\$ degrades in every condition without exception") + r")",
              lambda c: (all(v < 1 for v in rho5_means(c).values()),
                         ", ".join(f"{k} {float(v):.4f}" for k, v in rho5_means(c).items())),
              A_ATT, kind="bool"))
    add(Claim("REG-08", "range of generalization-gap change vs baseline",
              ws(r"Generalization changes span \$") + G("a") + ws(r"\$ to \$") + G("b") + r"\$",
              lambda c: (min(gen_changes(c).values()), max(gen_changes(c).values())),
              "recomputed: mean generalization_gap per condition (attempts.jsonl) minus the baseline's "
              "(baseline_eval.json)", groups=("a", "b")))
    add(Claim("REG-09", "spread of generalization changes, points",
              r"a \$" + G("v") + r"\$-point\s+spread",
              lambda c: 100 * (max(gen_changes(c).values()) - min(gen_changes(c).values())),
              "recomputed: as REG-08"))
    add(Claim("REG-10", "spread 'well inside the intervals' of section 4.4",
              r"(?P<v>" + ws(r"spread well inside the intervals of") + r")",
              NR("comparison is between different quantities: no bootstrap interval exists for the "
                 "generalization gap in committed data, and the 4.4 intervals are on repair success"),
              "none"))

    # ------------------------------------------------- captions and settings
    add(Claim("GEN-00", "model and effort used for every call",
              r"(?P<v>" + ws(r"All calls use \\texttt\{claude-opus-5\} at effort \\texttt\{high\}") + r")",
              lambda c: (all(a["model_id"] == a["model_id_requested"] == "claude-opus-5" and a["effort"] == "high"
                             for a in c.attempts),
                         "served model_id, requested model and effort, all 300 attempts"),
              A_ATT, kind="bool"))
    add(Claim("FIG4-cap", "figure 4 caption: attempts / clean repairs",
              ws(r"From ") + G("a") + ws(" attempts to ") + W("b") + ws(" clean repair"),
              lambda c: (len(c.attempts), c.count(is_clean)), A_ATT, groups=("a", "b")))
    add(Claim("TAB5-cap0", "table 5 caption: attempts",
              ws(r"Repair success over ") + G("v") + ws(" attempts"),
              lambda c: len(c.attempts), A_ATT))

    # --------------------------------------------------------------- 4.6 blame
    add(Claim("BLM-01", "H(active_node | contract), bits",
              ws(r"H\(\\texttt{active\\_node} \\mid \\text{contract}\) =\s*") + G("v"),
              lambda c: cond_entropy([(x["violated_contract"], x["active_node"]) for x in c.certs]), A_CERT))
    add(Claim("BLM-02", "H(contract), bits",
              ws(r"against \$H\(\\text{contract}\) = ") + G("v"),
              lambda c: h_bits(list(collections.Counter(x["violated_contract"] for x in c.certs).values())),
              A_CERT, note="exact 1.234498; blame_recompute.json stores 1.2345, which would double-round to 1.235"))
    add(Claim("BLM-03", "contracts each blaming one node / resulting H(node | contract)",
              ws(r"we verified by construction that\s*") + W("k")
              + ws(r" contracts each blaming one node still yields \$\\Hnc = ") + G("h") + r"\$",
              lambda c: by_construction_zero(c),
              "recomputed by construction with src/blame.conditional_entropy", groups=("k", "h"),
              note="no unit test under tests/ asserts this; it is checked here by construction"))
    add(Claim("BLM-04", "H(authorising_node | contract), bits",
              ws(r"raises this to \$") + G("v") + r"\$",
              lambda c: cond_entropy([(x["violated_contract"], x["authorising_node"]) for x in c.certs]), A_CERT))

    # ----------------------------------------------------------- limitations
    add(Claim("LIM-01", "K and replicates (limitations)",
              ws(r"The remaining limitations are ordinary. \$K\{=\}") + G("a") + ws(r"\$ with ") + W("b")
              + ws(" replicates"),
              lambda c: (len(c.certs), len({a["seed"] for a in c.attempts})), A_ATT, groups=("a", "b")))
    add(Claim("LIM-02", "one repair step per counterexample",
              ws(r"We\s*measure ") + W("v") + ws(" repair step per counterexample"),
              lambda c: one_step(c), A_ATT))
    add(Claim("LIM-03", "F1 prompt tokens ('roughly')",
              ws(r"roughly ") + G("v") + ws(" prompt tokens"),
              lambda c: median_prompt_tokens(c, "F1"), A_ATT, kind="approx", tol=0.01))
    add(Claim("LIM-04", "other conditions' prompt tokens ('about')",
              ws(r"against about ") + G("v") + ws(" for every other"),
              lambda c: about_other(c), A_ATT, kind="approx", tol=0.05,
              note="checked as within 5% of every non-F1 median; their pooled mean is 4,775.5"))
    add(Claim("LIM-05", "certificates with no rendered boundary / K",
              W("a") + ws(" of ") + W("b") + ws(" certificates report no boundary"),
              lambda c: no_boundary(c), A_CERT, groups=("a", "b")))

    # ------------------------------------------------------------ conclusion
    add(Claim("CON-C1", "conclusion: no reliable ex-refusal improvement",
              r"(?P<v>" + ws(r"adjustments. After excluding refusals we\s*did not detect a reliable improvement") + r")",
              ex_refusal_vs_f3_all_contain_zero, A_BOOT, kind="bool"))
    add(Claim("CON-C2", "conclusion: one attempt in three hundred found it",
              ws(r"and ") + W("a") + ws(" attempt in ") + r"(?P<b>three\s+hundred)" + ws(" found it"),
              lambda c: (c.count(is_clean), len(c.attempts)), A_ATT, groups=("a", "b")))

    # Claims whose wording exists only in the submitted text (v1.0-submission).
    # Their camera-ready counterparts, where the claim survived, are registered
    # in claims_v11() under new ids.
    for cl in C:
        if cl.cid in V10_ONLY or cl.cid.startswith("TAB5-"):
            cl.only = "v1.0"
    C.extend(claims_v11())
    return C


V10_ONLY = {
    "REF-01",
    "ABS-02", "ABS-05", "ABS-06", "ABS-08", "ABS-09", "ABS-10", "ABS-12",
    "INT-01", "INT-02", "INT-03",
    "REL-01", "REL-02", "REL-03", "REL-04", "REL-05", "TAB1-RSS",
    "BAS-02", "BAS-06", "BAS-07", "BAS-08", "BAS-09",
    "TAB2-cap3", "CON-04", "SCO-03",
    "GEN-00", "GEN-01", "GEN-05", "GEN-06",
    "PT-01", "PT-05", "PT-06", "PT-09", "PT-10",
    "REF-02", "REF-03", "REF-04", "REF-05", "REF-08",
    "DSL-C1", "DSL-C3", "DSL-V1", "DSL-V3",
    "NUL-01", "REG-08", "REG-09", "REG-10", "BLM-03", "LIM-03", "LIM-04",
    "CON-C1", "CON-C2",
    # second camera-ready pass (10 Oct): reworded in the round-2 revision;
    # counterparts registered in claims_v11() as <id>b / new ids
    "ABS-07", "MET-01", "MET-05", "PT-02", "PT-03", "PT-08", "DSL-M8", "DSL-V2",
    "NUL-03", "REG-03", "REG-05", "REG-07",
    "TAB3-F1", "TAB3-F2", "TAB3-F3", "TAB3-F4a", "TAB3-F4b", "TAB3-n",
}


# ---- helpers used by the registry -------------------------------------------
def sim_rate(c: Ctx) -> Fraction:
    txt = c.p("config/sim.yaml").read_text()
    m = re.search(r"fixed_delta_seconds:\s*([\d.]+)", txt)
    return Fraction(1) / Fraction(m.group(1))


def single(c: Ctx, key: str):
    return single_val({a[key] for a in c.attempts})


def single_val(s: set):
    if len(s) != 1:
        return f"not constant: {sorted(s)}"
    return next(iter(s))


def contracts_reproducing(c: Ctx) -> tuple[int, int]:
    d = c.json("data/results/determinism_c4.json")
    contracts = list(d["scenarios"][0]["per_contract"])
    exact = [k for k in contracts
             if all(s["per_contract"][k]["spread"] == 0.0 for s in d["scenarios"])]
    return len(exact), len(contracts)


def max_c4_spread(c: Ctx) -> float:
    d = c.json("data/results/determinism_c4.json")
    return max(s["per_contract"]["C4"]["spread"] for s in d["scenarios"])


def template(c: Ctx):
    from certificate import template as t
    return t()


def synth_samples(c: Ctx) -> int:
    s = llm_synth_counts(c)
    # The paper says "one fixed prompt": the call_id embeds a prompt hash.
    # The prompt used for every scored candidate is the most frequent one.
    fixed = max(s["by_prompt"], key=s["by_prompt"].get)
    return MultiValue(s["by_prompt"][fixed],
                      f"{s['by_prompt'][fixed]} calls under the scored candidates' prompt hash {fixed} "
                      f"({s['truncated']} stopped at max_tokens); {s['total']} synthesis calls in all "
                      f"(by prompt hash {s['by_prompt']})")


def max_tokens_all_calls(c: Ctx):
    """max_tokens over EVERY logged call, because the paper says 'All calls use'.

    Added in verification (9 Oct). attempts.jsonl records max_tokens for the 300
    repair calls only. logs/llm_index.jsonl (committed) does not record the cap,
    but a call that stopped at max_tokens reveals it: its completion length IS
    the cap. The request caps are also read from the released
    logs/llm_raw/synth_*.json and, LOCAL only, from the other logs/llm_raw/
    records (not released: some of their call_ids collide, so a record can hold
    a sibling attempt's response).
    """
    att = single(c, "max_tokens")
    caps = collections.Counter()
    for r in c.jsonl("logs/llm_index.jsonl"):
        if r["stop_reason"] == "max_tokens":
            caps[(r["tag"].split("_")[0], r["tokens_completion"])] += 1
    other = {k: v for k, v in caps.items() if k[1] != att}
    local = ""
    raw = c.p("logs/llm_raw")
    if raw.is_dir():
        req = collections.Counter()
        files = sorted(raw.glob("synth_*.json"))
        if c.local:
            files = sorted(raw.glob("*.json"))
        for f in files:
            try:
                d = json.loads(f.read_text())
            except Exception:
                continue
            if "max_tokens" in d:
                req[(f.name.split("_")[0], d["max_tokens"])] += 1
        lab = "logs/llm_raw (synth_* released; others LOCAL)" if c.local else "logs/llm_raw/synth_*.json"
        local = f"; {lab} request caps by call type: {dict(sorted(req.items()))}"
    if other:
        return (f"not constant across all calls: {att} for the 300 repair attempts, but "
                + ", ".join(f"{n} {k[0]} call(s) truncated at {k[1]}" for k, n in sorted(other.items()))
                + " (committed logs/llm_index.jsonl)" + local)
    return att


def calib_n(c: Ctx):
    d = c.json("data/results/baseline_calibration.json")
    ns = {x["n_scored"] for x in d["candidates"]}
    if ns != {d["n_calibration_scenarios"]}:
        return f"inconsistent: {ns}"
    return d["n_calibration_scenarios"]


_CALIB_LOCAL: dict = {}


def calib_trace_dir(c: Ctx) -> pathlib.Path:
    """data/calibration_traces/ (released); the full trace store data/traces/
    only as a LOCAL fallback when the released directory is absent."""
    d = c.p(CALIB_DIR)
    if d.is_dir():
        return d
    if c.local and c.p("data/traces").is_dir():
        return c.p("data/traces")
    raise NotRecomputable(f"{CALIB_DIR}/ absent" + ("" if c.local else " (LOCAL fallback skipped: --no-local)"))


def calib_local(c: Ctx) -> dict:
    """Entry and completion of the frozen baseline on the committed
    100-scenario calibration set, re-scored from the released calibration
    trajectories in data/calibration_traces/.

    Added in verification (9 Oct); the trajectories were released 10 Oct. The
    committed baseline_calibration.json has no entry or ICR field. The link is
    exact, not heuristic: the calibration parameter vectors are regenerated
    from the committed seed and n with the same sampler calibrate_baseline.py
    uses, and each trace is located by its episode id
    `cal_<stem>_<i:05d>_<param_hash>`. The result is accepted only if it
    reproduces the committed violation count and argmin split for that
    candidate; otherwise this raises NotRecomputable. Definitions follow the
    code: entered = C2 not vacuous (src/evaluate.py); completed = phase
    P4_settle reached (ICR in scripts/calibrate_baseline.py).
    """
    key = (str(c.repo), c.local)
    if key in _CALIB_LOCAL:
        if isinstance(_CALIB_LOCAL[key], Exception):
            raise _CALIB_LOCAL[key]
        return _CALIB_LOCAL[key]
    try:
        import random
        from ted import ted_from_source
        d = c.json("data/results/baseline_calibration.json")
        base = c.p("data/scenarios/baseline_program.bt").read_text()
        cand = None
        for x in d["candidates"]:
            if ted_from_source(base, c.p(x["program"]).read_text()) == 0:
                cand = x
                break
        if cand is None:
            raise NotRecomputable("no calibrated candidate is TED-identical to the frozen baseline")
        stem = pathlib.Path(cand["program"]).stem
        cand_src = c.p(cand["program"]).read_text()
        tdir = calib_trace_dir(c)
        stl, contracts, junction, param_hash = _scorer(c)
        from run_campaign import sample
        rng = random.Random(d["seed"])
        params = [sample(rng) for _ in range(d["n_calibration_scenarios"])]
        n = entered = settled = viol = 0
        argmin = collections.Counter()
        per = []
        for i, p in enumerate(params):
            stem_i = tdir / f"cal_{stem}_{i:05d}_{param_hash(p)}"
            js, pq = stem_i.with_suffix(".json"), stem_i.with_suffix(".parquet")
            if not (js.exists() and pq.exists()):
                raise NotRecomputable(f"calibration trace {stem_i.name} absent from {tdir.relative_to(c.repo)}/")
            meta = json.loads(js.read_text())
            if meta.get("program_source") != cand_src:
                raise NotRecomputable(f"{stem_i.name} was run under a different program")
            df, _ = stl.load_trace(str(pq))
            r = stl.compute_rho(df, contracts, junction)
            n += 1
            e = not r.per_contract["C2"].vacuous
            s4 = "P4_settle" in (meta["result"]["meta"].get("phases_reached") or [])
            entered += int(e)
            settled += int(s4)
            if r.rho < 0:
                viol += 1
                argmin[r.contract] += 1
            per.append({"index": i, "param_hash": param_hash(p), "rho": float(r.rho), "contract": r.contract,
                        "entered": e, "settled": s4})
        if viol != cand["violations"] or dict(argmin) != cand["argmin_contract"]:
            raise NotRecomputable(f"local traces give {viol} violations {dict(argmin)}, committed "
                                  f"{cand['violations']} {cand['argmin_contract']}: not the committed run")
        out = {"n": n, "entered": entered, "settled": settled, "violations": viol,
               "argmin": dict(argmin), "stem": stem, "dir": str(tdir.relative_to(c.repo)), "per": per}
        _CALIB_LOCAL[key] = out
        return out
    except NotRecomputable as e:
        _CALIB_LOCAL[key] = e
        raise
    except Exception as e:  # a missing or unreadable trajectory is not a paper mismatch
        err = NotRecomputable(f"re-scoring the calibration trajectories raised {type(e).__name__}: {e}")
        _CALIB_LOCAL[key] = err
        raise err


def calib_local_rate(c: Ctx, field: str, why_nr: str):
    try:
        x = calib_local(c)
    except NotRecomputable as e:
        raise NotRecomputable(f"{why_nr} [trajectories unavailable: {e}]")
    return MultiValue(pct(x[field], x["n"]),
                      f"{x[field]}/{x['n']} on {x['stem']}'s calibration trajectories in {x['dir']}/, linked by "
                      f"regenerated param hashes; they reproduce the committed {x['violations']} violations "
                      f"{x['argmin']}")


def icr_floor(c: Ctx) -> Fraction:
    txt = c.p("scripts/calibrate_baseline.py").read_text()
    m = re.search(r"^ICR_FLOOR\s*=\s*([\d.]+)", txt, re.M)
    return Fraction(m.group(1)) * 100


def frozen_violation_rate(c: Ctx) -> Fraction:
    from ted import ted_from_source
    base = c.p("data/scenarios/baseline_program.bt").read_text()
    d = c.json("data/results/baseline_calibration.json")
    for cand in d["candidates"]:
        src = c.p(cand["program"]).read_text()
        if ted_from_source(base, src) == 0:
            return pct(cand["violations"], cand["n_scored"])
    raise NotRecomputable("no calibrated candidate is TED-identical to the frozen baseline")


def falsif_cost(c: Ctx) -> Fraction:
    d = c.json("data/results/falsification_summary.json")
    return Fraction(d["rollouts"]["rollouts_total"], d["K_admitted"])


def f1_window(c: Ctx) -> int:
    hw = c.exp_cfg["f1_excerpt_halfwidth_rows"]
    lad = c.json("data/results/prompt_budget.json")["f1_window_ladder"]
    fitting = [v["halfwidth"] for v in lad.values() if v["over_B"] == 0 and v["halfwidth"] > 0]
    if max(fitting) != hw:
        return f"config {hw} but largest fitting rung {max(fitting)}"
    return hw


def rows_back(c: Ctx) -> tuple[int, int]:
    r = c.json("data/results/prompt_budget.json")["f1_window_reach_vs_f4b"]["rows_back_to_authorising_transition"]
    return r["min"], r["max"]


def rows_back_all(c: Ctx) -> int:
    r = c.json("data/results/prompt_budget.json")["f1_window_reach_vs_f4b"]
    return r["rows_back_to_authorising_transition"]["n"] - r["inside_configured_window"]


def prereg_scope(c: Ctx) -> tuple[int, int]:
    txt = spec_v2_text(c)
    m1 = re.search(r"\*\*(\w+) contracts\*\* \(C1, C2, C5\)", txt)
    m2 = re.search(r"Search space — (\w+) parameters", txt)
    if not (m1 and m2):
        raise NotRecomputable("plan wording not found in 01_TECHNICAL_SPEC_v2.md")
    return WORDS[m1.group(1).lower()], WORDS[m2.group(1).lower()]


def param_composition(c: Ctx):
    """Is the run's parameter set the pre-specified four plus two new ones?

    Added in verification (9 Oct). The sentence explains 4 -> 6 as two added
    parameters that make C3 and C4 bind. The counts match (SCO-01/02); this
    checks the composition the sentence implies.
    """
    txt = spec_v2_text(c)
    # The FIRST table under the heading only: section 6.1 also has a table of
    # the v1 parameters it dropped, which must not be read as pre-specified.
    sec = re.search(r"### §6\.1 Search space[^\n]*\n\s*\n((?:\|[^\n]*\n)+)", txt)
    if not sec:
        raise NotRecomputable("section 6.1 table not found in 01_TECHNICAL_SPEC_v2.md")
    pre = set(re.findall(r"^\|\s*`(\w+)`\s*\|", sec.group(1), re.M))
    if len(pre) != prereg_scope(c)[1]:
        raise NotRecomputable(f"section 6.1 table lists {sorted(pre)}, heading says {prereg_scope(c)[1]}")
    sp = c.yaml("data/scenarios/space.yaml")
    run = set(sp["parameters"])
    dropped = sorted(pre - run)
    added = sorted(run - pre)
    ok = not dropped and len(added) == 2
    return ok, (f"pre-specified {sorted(pre)}; run {sorted(run)}; dropped {dropped} "
                f"(space.yaml 'dropped': {sorted(sp.get('dropped') or {})}); added {added}")


def distinct_programs(c: Ctx) -> Fraction:
    cells = collections.defaultdict(set)
    for a in c.attempts:
        cells[(a["condition"], a["certificate_id"])].add(
            hashlib.sha256(a["bt_source_after"].encode()).hexdigest())
    return Fraction(sum(len(v) for v in cells.values()), len(cells))


def regression_suite_n(c: Ctx):
    d = c.json("data/scenarios/regression_suite.json")
    base_fail = sum(v["regression_failures"] for v in c.baseline_eval.values())
    if d["baseline_scvr"] != 0.0 or base_fail != 0:
        return f"baseline does not pass: scvr={d['baseline_scvr']}, failures={base_fail}"
    return d["n"]


def pilot_icr(c: Ctx) -> float:
    rows = c.jsonl("data/results/dryrun_attempts.jsonl")
    hits = [r for r in rows if r["resolved"] and r["counterexample_status"] == "timeout"
            and not r["ce_entered_conflict_zone"] and r["condition"] == "F1"]
    if len(hits) != 1:
        raise NotRecomputable(f"{len(hits)} F1 dry-run attempts timed out unentered")
    return hits[0]["icr"]


def gap_guard_max(c: Ctx) -> float:
    from bt_vocabulary import ALL_NODES
    hi = ALL_NODES["OncomingGapExceeds"].params[0].hi
    sweep = max(float(pathlib.Path(p).stem.split("_")[1])
                for p in glob.glob(str(c.p("data/scenarios/dsl_probe/sweep_*.bt"))))
    if sweep != hi:
        return f"validator max {hi} but sweep max {sweep}"
    return hi


def dsl_mech_number(c: Ctx, rx: str) -> float:
    d = c.json("data/results/dsl_expressiveness.json")
    for s in d["mechanism"]:
        m = re.search(rx, s)
        if m:
            return float(m.group(1))
    raise NotRecomputable(f"pattern {rx!r} not in dsl_expressiveness.json mechanism text")


def clean_repair_20(c: Ctx):
    """The clean repair on all K counterexamples: (fixed, K, completed, K).

    Re-scored from data/dsl_probe_traces/clean_repair/, whose program is
    byte-identical to the clean attempt's bt_source_after. Its own
    counterexample must agree with attempts.jsonl and the other K-1 with the
    committed clean_repair_validation.json."""
    clean = [a for a in c.attempts if is_clean(a)]
    if len(clean) != 1:
        raise NotRecomputable(f"{len(clean)} clean attempts")
    att = clean[0]
    (v,) = probe_scores(c)["clean"]
    own_id = att["certificate_id"].split("_")[0]
    own = [e for e in v["episodes"] if e["cert"] == own_id]
    others = [e for e in v["episodes"] if e["cert"] != own_id]
    art = c.json("data/results/clean_repair_validation.json")["test_1_generalisation"]["other_19_never_shown"]
    bad = []
    if sha16(att["bt_source_after"]) != v["program_sha"]:
        bad.append(f"trajectories ran program {v['program_sha']}, the clean attempt's is {sha16(att['bt_source_after'])}")
    if len(own) != 1 or (own[0]["fixed"], own[0]["completed"]) != (bool(att["resolved"]), bool(att["ce_completed"])):
        bad.append(f"own counterexample {own_id} disagrees with attempts.jsonl")
    o = ((sum(e["fixed"] for e in others), len(others)), (sum(e["completed"] for e in others), len(others)))
    if o != (frac_str(art["resolved"]), frac_str(art["completed"])):
        bad.append(f"other {len(others)}: re-scored {o}, clean_repair_validation.json {art['resolved']}, "
                   f"{art['completed']}")
    if bad:
        return "; ".join(bad)
    return MultiValue((v["fixed"], v["n"], v["completed"], v["n"]),
                      _variant_line(v) + f"; own counterexample {own_id} agrees with attempts.jsonl; the other "
                      f"{len(others)} agree with clean_repair_validation.json ({art['resolved']}, {art['completed']})")


def clean_under_f1(c: Ctx):
    clean = [a for a in c.attempts if is_clean(a)]
    if len(clean) != 1 or clean[0]["condition"] != "F1":
        return f"{len(clean)} clean, conditions {[a['condition'] for a in clean]}"
    return 1, len(c.attempts)


def _repeats(c: Ctx) -> tuple[list[dict], dict, str]:
    clean = [a for a in c.attempts if is_clean(a)]
    if len(clean) != 1:
        raise NotRecomputable(f"{len(clean)} clean attempts")
    return (probe_scores(c)["repeats"],
            c.json("data/results/clean_repair_validation.json")["test_2_rss_stability"],
            clean[0]["certificate_id"].split("_")[0])


def clean_repeats_n(c: Ctx):
    reps, t, own = _repeats(c)
    on = {e["cert"] for e in reps}
    if on != {own} or len(reps) != t["repeats"]:
        return (f"{len(reps)} repeats on {sorted(on)}; clean_repair_validation.json records {t['repeats']} "
                f"on the clean attempt's {own}")
    return MultiValue(len(reps), f"{len(reps)} trajectories in repeats/, all on {own}; "
                                 f"clean_repair_validation.json repeats = {t['repeats']}")


def clean_rss(c: Ctx):
    """Zero spread in rho and rho_4 over the six repeats; C4 never binding."""
    reps, t, own = _repeats(c)
    rho = [e["rho"] for e in reps]
    r4 = [e["rho4"] for e in reps]
    sp, sp4 = max(rho) - min(rho), max(r4) - min(r4)
    binding = sorted({e["contract"] for e in reps})
    traces_ok = (sp == 0.0 and sp4 == 0.0 and "C4" not in binding and {e["cert"] for e in reps} == {own}
                 and all(e["fixed"] and e["completed"] for e in reps))
    art_ok = (t["rho_spread"] == 0.0 and t["C4_spread_m"] == 0.0 and not t["C4_ever_binding"]
              and t["repeats"] == len(reps))
    return traces_ok and art_ok, (
        f"re-scored {len(reps)} repeats on {own}: rho {sorted(set(rho))}, rho_4 {sorted(set(r4))} m, spread "
        f"{sp} and {sp4} m, binding {binding}, all fixed and completed {all(e['fixed'] and e['completed'] for e in reps)}; "
        f"clean_repair_validation.json: rho_spread={t['rho_spread']}, C4_spread_m={t['C4_spread_m']}, "
        f"C4_ever_binding={t['C4_ever_binding']}")


def mean_ted(c: Ctx, cond: str) -> Fraction:
    from ted import ted_from_source
    xs = [ted_from_source(a["bt_source_before"], a["bt_source_after"]) for a in c.by_cond(cond)]
    return Fraction(sum(xs), len(xs))


def largest_effect_is_skeleton(c: Ctx):
    b = c.boot
    best = None
    for m in PREDICATES:
        for i, x in enumerate(CONDS):
            for y in CONDS[i + 1:]:
                p, (lo, hi) = b.diff(m, x, y)
                dist = max(lo, -hi, 0.0)       # how far the CI sits from zero
                cand = (abs(p), dist, m, x, y)
                if best is None or cand[:2] > best[:2]:
                    best = cand
    # also find the contrast whose CI is farthest from zero
    far = max(((max(b.diff(m, x, y)[1][0], -b.diff(m, x, y)[1][1], 0.0), m, x, y)
               for m in PREDICATES for i, x in enumerate(CONDS) for y in CONDS[i + 1:]))
    ok = best[2] == "skeleton_edit" and far[1] == "skeleton_edit"
    return ok, (f"largest |diff| {best[0]:.1f} pts = {best[2]} {best[3]}-{best[4]}; "
                f"CI farthest from 0 = {far[1]} {far[2]}-{far[3]} ({far[0]:.1f} pts)")


def least_vs_most_processed(c: Ctx):
    f1 = skel(c, "F1")
    d4a = pct(f1 - skel(c, "F4a"), 60)
    d4b = pct(f1 - skel(c, "F4b"), 60)
    d2 = pct(f1 - skel(c, "F2"), 60)
    # Report the F1 vs F4b contrast (the most processed condition) as the value
    # the sentence describes; the note carries the others.
    return MultiValue(d4b, f"F1-F4b {float(d4b):.1f}, F1-F4a {float(d4a):.1f}; F1-F2 (narrative) {float(d2):.1f}")


@dataclasses.dataclass
class MultiValue:
    value: Any
    detail: str


def ordering_claim(c: Ctx):
    k = {x: skel(c, x) for x in CONDS}
    med = statistics.median(k.values())
    least_most = k["F1"] == max(k.values())
    most_fewest = {x: k[x] <= med for x in ("F4a", "F4b")}
    ok = least_most and all(most_fewest.values())
    return ok, (f"counts {k}; F1 is max: {least_most}; at or below the median ({med}): "
                f"F4a {most_fewest['F4a']}, F4b {most_fewest['F4b']}")


def f1_differs_from_all(c: Ctx):
    b = c.boot
    out = {y: b.diff("skeleton_edit", "F1", y) for y in CONDS if y != "F1"}
    ok = all(lo > 0 for _, (lo, hi) in out.values())
    return ok, "; ".join(f"F1-{y} {p:+.1f} [{lo:+.1f},{hi:+.1f}]" for y, (p, (lo, hi)) in out.items())


def fig2_only_f1(c: Ctx):
    b = c.boot
    sep = set()
    for m in ("resolved", "resolved_ex_refusal", "skeleton_edit"):
        for x in CONDS:
            if x == "F3":
                continue
            lo, hi = b.diff(m, x, "F3")[1]
            if not ci_contains_zero(lo, hi):
                sep.add((m, x))
    f1_ex = b.diff("resolved_ex_refusal", "F1", "F3")[1]
    ok = {x for _, x in sep} == {"F1"} and ci_contains_zero(*f1_ex)
    return ok, f"CIs excluding 0: {sorted(sep)}; F1 ex-refusal CI {f1_ex[0]:+.1f},{f1_ex[1]:+.1f}"


def f1_clears_zero_resolved(c: Ctx):
    p, (lo, hi) = c.boot.diff("resolved", "F1", "F3")
    return lo > 0, f"F1-F3 resolved {p:+.1f} [{lo:+.1f},{hi:+.1f}]"


def modal_outcome(c: Ctx):
    res = {}
    ok = True
    for x in CONDS:
        cells = collections.Counter(
            (bool(a["resolved"]), (a["regression_failures"] or 0) >= 1) for a in c.by_cond(x))
        mode = max(cells, key=cells.get)
        res[x] = cells[(False, True)]
        ok &= mode == (False, True)
    return ok, "not-fixed-and-broke counts per 60: " + ", ".join(f"{k} {v}" for k, v in res.items())


def by_construction_zero(c: Ctx):
    from blame import conditional_entropy
    pairs = [(f"C{i}", f"node{i}") for i in range(1, 6) for _ in range(4)]
    h, _ = conditional_entropy(pairs)
    return len({k for k, _ in pairs}), abs(h)


def one_step(c: Ctx):
    base = c.p("data/scenarios/baseline_program.bt").read_text()
    single_round = all(a["bt_source_before"] == base and a["ted_from_previous"] == a["ted_from_original"]
                       for a in c.attempts)
    per_cell = collections.Counter((a["condition"], a["certificate_id"], a["seed"]) for a in c.attempts)
    if single_round and set(per_cell.values()) == {1}:
        return 1
    return "not single-round"


def about_other(c: Ctx):
    meds = {x: median_prompt_tokens(c, x) for x in CONDS if x != "F1"}
    return MultiValue(meds, ", ".join(f"{k} {float(v):g}" for k, v in meds.items()))


def no_boundary(c: Ctx):
    none = [x for x in c.certs if not x.get("boundary_report_rendered")]
    sole = all(len(x.get("kept_parameters", [])) == 1 and x["kept_parameters"] == x["boundary_suppressed"]
               for x in none)
    if not sole:
        return "some no-boundary certificate does not have a single suppressed parameter"
    return len(none), len(c.certs)


# =============================================================================
# Camera-ready (v1.1) registry. Added 10 Oct 2026 for the revised main.tex and
# the checklist it \input{}s. Every claim here is tagged only="v1.1".
# =============================================================================
A_BOOT_F12 = A_BOOT + "; equals data/results/uncertainty.json skeleton_edit_F1_minus_F2 (I-15)"
A_BOOT_MULT = A_BOOT + "; Bonferroni at alpha = 0.05/17; equals data/results/uncertainty.json multiplicity (I-15)"
A_BOOT_PAIR = A_BOOT + "; equals data/results/uncertainty.json skeleton_edit_pairwise (I-20)"
A_DE = ("from artefact data/results/detectable_effect.json (scripts/detectable_effect.py simulation, "
        "20,000 experiments per setting; NOT re-simulated here)")
A_TAX = "recomputed: program sources in attempts.jsonl, parsed with src/program_parser.py, classified with src/ted.py"
A_DOC_ENV = "from documentation docs/env_manifest.md (hardware is not data)"
A_REQ = "recomputed: requirements.txt pin and the installed .venv package metadata"

# The 17 paired differences the paper computes: four outcomes x {F1, F2, F4a,
# F4b} against F3, plus F1 against F2 on structural edits.
CONTRASTS17 = ([(m, x, "F3") for m in ("resolved", "resolved_ex_refusal", "skeleton_edit", "regression")
                for x in ("F1", "F2", "F4a", "F4b")] + [("skeleton_edit", "F1", "F2")])
METRIC_LABEL = {"resolved": "Success (pre-specified)", "resolved_ex_refusal": "Success, refusals excl.",
                "skeleton_edit": "Structural edit", "regression": r"Broke $\geq 1$ regression"}


def V(name: str) -> str:
    """Named group for a dotted version string such as 0.9.16."""
    return rf"(?P<{name}>\d+\.\d+(?:\.\d+)?)"


# ---- outcome criteria (Table 4) ---------------------------------------------
def tab4_row(c: Ctx, cond: str | None):
    rows = c.attempts if cond is None else c.by_cond(cond)
    S = sum(1 for a in rows if a["resolved"])
    ref = sum(1 for a in rows if a["resolved_by_refusal"])
    ent = sum(1 for a in rows if a["resolved"] and a["ce_entered_conflict_zone"])
    C = sum(1 for a in rows if a["ce_completed"])
    R = sum(1 for a in rows if (a["regression_failures"] or 0) == 0)
    SC = sum(1 for a in rows if a["resolved_and_completed"])
    SCR = sum(1 for a in rows if is_clean(a))
    # consistency of the derived fields with their definitions
    if any(bool(a["resolved_and_completed"]) != (bool(a["resolved"]) and bool(a["ce_completed"])) for a in rows):
        return "resolved_and_completed != resolved and ce_completed"
    if any(bool(a["resolved_by_refusal"]) != (bool(a["resolved"]) and not a["ce_entered_conflict_zone"]) for a in rows):
        return "resolved_by_refusal != resolved and not entered"
    return S, ref, ent, C, R, SC, SCR


def counts_SCR(c: Ctx):
    t = tab4_row(c, None)
    return t[1], t[0], t[5], t[6]          # refused, S, S&C, S&C&R


def refusal_mechanism(c: Ctx):
    ref = [a for a in c.attempts if a["resolved_by_refusal"]]
    bad = [a["attempt_id"] for a in ref
           if not ({"C2", "C3"} <= set(a["ce_vacuous_contracts"] or [])
                   and a["argmin_contract_after"] == "C5" and a["rho5_after"] >= 0 and a["rho1_after"] >= 0)]
    r5 = collections.Counter(round(a["rho5_after"], 3) for a in ref)
    return not bad, (f"{len(ref)} refusals: C2 and C3 vacuous, argmin C5, rho1 >= 0 and rho5 >= 0 in "
                     f"{len(ref) - len(bad)}; rho5_after values {dict(r5)} (the unpatched baseline's is 1.0)")


def entered_not_completed(c: Ctx):
    xs = [a for a in c.attempts if a["resolved"] and a["ce_entered_conflict_zone"] and not a["ce_completed"]]
    st = collections.Counter(a["counterexample_status"] for a in xs)
    if set(st) - {"timeout"}:
        return f"{len(xs)}, but statuses {dict(st)} (not all ended by the time limit)"
    return MultiValue(len(xs), f"{[a['attempt_id'] for a in xs]}; status {dict(st)}")


def r_passes_refusal(c: Ctx):
    xs = [a for a in c.attempts if a["icr"] == 0 and (a["regression_failures"] or 0) == 0]
    suite = c.json("data/scenarios/regression_suite.json")["n"] + c.json("data/scenarios/held_out_suite.json")["n"]
    det = "; ".join(f"{a['attempt_id']} icr {a['icr']} refusal {a['resolved_by_refusal']} "
                    f"held-out violations {a['held_out_violations']}" for a in xs)
    return MultiValue((len(xs), 0, suite), det)


def c_inherited(c: Ctx):
    base_done = {k.split("_")[0] for k, v in c.baseline_eval.items() if v["ce_completed"]}
    comp = [a for a in c.attempts if a["ce_completed"]]
    inh = sum(1 for a in comp if a["certificate_id"].split("_")[0] in base_done)
    return MultiValue((inh, len(comp), len(base_done)), f"baseline completes {sorted(base_done)}")


def other_refusals_icr(c: Ctx):
    ref = [a for a in c.attempts if a["resolved_by_refusal"] and a["icr"] > 0]
    lo, hi = min(Fraction(str(a["icr"])) for a in ref), max(Fraction(str(a["icr"])) for a in ref)
    base = {v["icr"] for v in c.baseline_eval.values()}
    return MultiValue((len(ref), 100 * lo, 100 * hi),
                      f"ICR values {dict(collections.Counter(a['icr'] for a in ref))}; unpatched baseline ICR {base}")


def refused_only_own(c: Ctx):
    ref = [a for a in c.attempts if a["resolved_by_refusal"] and a["icr"] > 0]
    base = {v["icr"] for v in c.baseline_eval.values()}
    below = [a["attempt_id"] for a in ref if a["icr"] < min(base)]
    raise NotRecomputable(
        "no committed field records entry or completion per suite scenario, so 'refused only on their own "
        f"counterexample' cannot be checked. ICR only bounds it: {len(ref) - len(below)} of {len(ref)} complete "
        f"as many suite scenarios as the unpatched baseline (ICR {sorted(base)}); {len(below)} complete one "
        f"fewer (ICR 0.933), so they may have refused or failed elsewhere too: {below}")


# ---- generation, synthesis --------------------------------------------------
def synth_trunc(c: Ctx):
    s = llm_synth_counts(c)
    fixed = max(s["by_prompt"], key=s["by_prompt"].get)
    rows = [r for r in c.jsonl("logs/llm_index.jsonl")
            if r["tag"].startswith("synth") and r["call_id"].split("_")[2] == fixed and r["stop_reason"] == "max_tokens"]
    caps = {r["tokens_completion"] for r in rows}
    if len(caps) != 1:
        return f"truncated calls have completion lengths {caps}"
    local = ""
    raw = c.p("logs/llm_raw")
    if raw.is_dir():
        req = collections.Counter()
        for f in sorted(raw.glob("synth_*.json")):
            d = json.loads(f.read_text())
            req[(d["call_id"].split("_")[2], d.get("max_tokens"))] += 1
        local = f"; logs/llm_raw/synth_*.json request caps by prompt hash: {dict(req)}"
    return MultiValue((len(rows), caps.pop()),
                      f"{len(rows)} of the {s['by_prompt'][fixed]} calls under {fixed} stopped at max_tokens; "
                      f"committed evidence: their completion length equals the cap" + local)


def synth_valid(c: Ctx):
    s = llm_synth_counts(c)
    fixed = max(s["by_prompt"], key=s["by_prompt"].get)
    n_valid = len(c.json("data/results/baseline_calibration.json")["candidates"])
    trunc = sum(1 for r in c.jsonl("logs/llm_index.jsonl")
                if r["tag"].startswith("synth") and r["call_id"].split("_")[2] == fixed and r["stop_reason"] == "max_tokens")
    return MultiValue((n_valid, s["by_prompt"][fixed] - trunc),
                      f"{n_valid} candidates scored in baseline_calibration.json; {s['by_prompt'][fixed]} calls "
                      f"minus {trunc} truncated; the other {s['by_prompt'][fixed] - trunc - n_valid} failed validation "
                      f"(no candidate file for them; their raw responses are in logs/llm_raw/synth_*.json)")


def frozen_violations(c: Ctx):
    from ted import ted_from_source
    base = c.p("data/scenarios/baseline_program.bt").read_text()
    for cand in c.json("data/results/baseline_calibration.json")["candidates"]:
        if ted_from_source(base, c.p(cand["program"]).read_text()) == 0:
            return cand["violations"], cand["n_scored"]
    raise NotRecomputable("no calibrated candidate is TED-identical to the frozen baseline")


def calib_local_bool_entered(c: Ctx):
    try:
        x = calib_local(c)
    except NotRecomputable as e:
        raise NotRecomputable("baseline_calibration.json has no entry field and the calibration trajectories "
                              f"could not be re-scored [{e}]")
    return x["entered"] == x["n"], (f"entered {x['entered']}/{x['n']} on {x['stem']}'s calibration trajectories in "
                                    f"{x['dir']}/; they reproduce the committed {x['violations']} violations "
                                    f"{x['argmin']}")


def calib_local_count(c: Ctx, field: str):
    try:
        x = calib_local(c)
    except NotRecomputable as e:
        raise NotRecomputable("baseline_calibration.json has no completion field and the calibration trajectories "
                              f"could not be re-scored [{e}]")
    return MultiValue(x[field], f"{x[field]}/{x['n']} on {x['stem']}'s calibration trajectories in {x['dir']}/, "
                                f"linked by regenerated param hashes; they reproduce the committed "
                                f"{x['violations']} violations")


def model_served_all(c: Ctx):
    n = sum(1 for a in c.attempts
            if a["model_id"] == a["model_id_requested"] == "claude-opus-5" and a["effort"] == "high")
    idx = c.jsonl("logs/llm_index.jsonl")
    served = collections.Counter(r["model_served"] for r in idx)
    if n != len(c.attempts):
        return f"{n} of {len(c.attempts)}"
    return MultiValue(n, f"all attempts served = requested = claude-opus-5, effort high; "
                         f"logs/llm_index.jsonl model_served over all {len(idx)} calls: {dict(served)}")


def no_truncation(c: Ctx):
    hit = [a for a in c.attempts if a["stop_reason"] == "max_tokens" or a["tokens_completion"] >= a["max_tokens"]]
    return not hit, (f"stop reasons {dict(collections.Counter(a['stop_reason'] for a in c.attempts))}; "
                     f"largest completion {max(a['tokens_completion'] for a in c.attempts)} of "
                     f"{single(c, 'max_tokens')}")


_PROMPTS: dict = {}
PROMPT_SEP = "\n\n===== USER =====\n\n"   # how logs/campaign/prompts/*.txt join system and user


def regen_prompts(c: Ctx) -> dict:
    """Every prompt of the campaign regenerated from the committed certificates
    and template, with the hashes attempts.jsonl logged for the prompt and the
    feedback block actually sent.

    F1 renders a window of the counterexample trajectory, read through
    certificate.resolve_trace_path from data/certificates/traces/. If a
    certificate's trajectory resolves anywhere else (the absolute path stored
    at banking time, which is LOCAL), F1 is regenerated only when LOCAL
    sources are allowed and is labelled LOCAL; otherwise F1 is reported as
    not regenerated."""
    key = (str(c.repo), c.local)
    if key in _PROMPTS:
        return _PROMPTS[key]
    from certificate import Certificate, template as tpl
    t = tpl()
    certs = {x.certificate_id: x for x in Certificate.load_all(c.p("data/certificates"))}
    shipped = c.p("data/certificates/traces").resolve()
    where = {}
    for cid, x in certs.items():
        try:
            tp = pathlib.Path(x.trace_path).resolve()
        except FileNotFoundError:
            where[cid] = "absent"
            continue
        where[cid] = "released" if tp.parent == shipped else "LOCAL"
    f1_ok = all(w == "released" for w in where.values()) or (
        c.local and all(w in ("released", "LOCAL") for w in where.values()))
    fb_cache: dict = {}
    res: dict = {}
    for a in c.attempts:
        if a["condition"] == "F1" and not f1_ok:
            res[a["attempt_id"]] = None
            continue
        k = (a["certificate_id"], a["condition"])
        if k not in fb_cache:
            fb_cache[k] = certs[a["certificate_id"]].feedback(a["condition"])
        fb = fb_cache[k]
        res[a["attempt_id"]] = (sha16(fb) == a["feedback_sha256_16"],
                                sha16(t.prefix.rstrip("\n") + fb + t.suffix) == a["prompt_sha256_16"])
    out = {"res": res, "where": collections.Counter(where.values()), "f1": f1_ok, "fb": fb_cache,
           "prefix": len(t.prefix), "suffix": len(t.suffix)}
    _PROMPTS[key] = out
    return out


def campaign_prompts(c: Ctx) -> dict | None:
    """logs/campaign/prompts/: the prompt actually sent for each attempt.
    Returns None if the directory is absent."""
    d = c.p("logs/campaign/prompts")
    if not d.is_dir():
        return None
    from certificate import template as tpl
    t = tpl()
    good = present = 0
    for a in c.attempts:
        f = c.p(a["prompt_path"])
        if not f.exists():
            continue
        present += 1
        system, user = f.read_text().split(PROMPT_SEP, 1)
        good += (system == t.prefix.rstrip("\n") and user.endswith(t.suffix)
                 and sha16(system + user) == a["prompt_sha256_16"])
    return {"good": good, "present": present, "n": len(c.attempts)}


def prompt_identity_all(c: Ctx):
    """Template prefix and suffix byte-identical in every prompt actually sent:
    all 300 prompts are regenerated as prefix + feedback + suffix and must
    hash-match the prompt logged as sent; the saved prompts must agree."""
    g = regen_prompts(c)
    done = [v for v in g["res"].values() if v is not None]
    ok_fb, ok_pr = sum(v[0] for v in done), sum(v[1] for v in done)
    f1c = c.p("data/results/rendered_prompts/CE003_C1_969f15c8657c8fa6_F1.txt").read_text()
    from certificate import template as tpl
    t = tpl()
    ce003 = f1c[:len(t.prefix)] == t.prefix and f1c.endswith(t.suffix)
    cp = campaign_prompts(c)
    trace_src = ", ".join(f"{v} {k}" for k, v in sorted(g["where"].items()))
    det = (f"regenerated from certificates + template: {ok_pr}/{len(done)} prompts and {ok_fb}/{len(done)} feedback "
           f"blocks hash-match attempts.jsonl (certificate trajectories: {trace_src}); CE003 F1 committed copy {ce003}; "
           + (f"logs/campaign/prompts {cp['good']}/{cp['n']} share prefix and suffix and hash-match"
              if cp else "logs/campaign/prompts absent"))
    if len(done) < len(c.attempts) and not (cp and cp["good"] == cp["n"]):
        raise NotRecomputable(f"F1 prompts not regenerated (certificate trajectories: {trace_src}) and "
                              f"logs/campaign/prompts incomplete or absent: {det}")
    ok = (ok_fb == ok_pr == len(done) and ce003 and (cp is None or cp["good"] == cp["n"]))
    return ok, det


# ---- bootstrap, multiplicity --------------------------------------------------
def allci_row(c: Ctx, m: str, a: str, b: str):
    p, (lo, hi) = c.boot.diff(m, a, b)
    blo, bhi = c.boot.diff_alpha(m, a, b, 0.05 / len(CONTRASTS17))
    return p, lo, hi, blo, bhi


def excl_sets(c: Ctx):
    un, bf = set(), set()
    for m, a, b in CONTRASTS17:
        _, lo, hi, blo, bhi = allci_row(c, m, a, b)
        if not ci_contains_zero(lo, hi):
            un.add((m, a, b))
        if not ci_contains_zero(blo, bhi):
            bf.add((m, a, b))
    return un, bf


def fmt_set(s) -> str:
    return ", ".join(f"{m} {a}-{b}" for m, a, b in sorted(s))


def bonf_only_f1_skel(c: Ctx):
    un, bf = excl_sets(c)
    want = {("skeleton_edit", "F1", "F2"), ("skeleton_edit", "F1", "F3")}
    return bf == want, f"Bonferroni-excluding: {fmt_set(bf)}; unadjusted-excluding: {fmt_set(un)}"


def unadj_and_bonf_sets(c: Ctx):
    un, bf = excl_sets(c)
    want_un = {("resolved", "F1", "F3"), ("skeleton_edit", "F1", "F3"), ("skeleton_edit", "F1", "F2"),
               ("regression", "F4a", "F3")}
    want_bf = {("skeleton_edit", "F1", "F2"), ("skeleton_edit", "F1", "F3")}
    return un == want_un and bf == want_bf, f"unadjusted-excluding: {fmt_set(un)}; Bonferroni: {fmt_set(bf)}"


def n_contrasts(c: Ctx):
    js = c.json("data/results/uncertainty.json").get("multiplicity", {}).get("n_contrasts_computed")
    if js is not None and js != len(CONTRASTS17):
        return f"script registry {len(CONTRASTS17)} but uncertainty.json says {js}"
    return MultiValue(len(CONTRASTS17), f"uncertainty.json multiplicity.n_contrasts_computed = {js}")


def f4a_reg_bonf_contains_zero(c: Ctx):
    blo, bhi = c.boot.diff_alpha("regression", "F4a", "F3", 0.05 / len(CONTRASTS17))
    return ci_contains_zero(blo, bhi), f"Bonferroni [{blo:+.1f},{bhi:+.1f}]"


def zero_endpoint_only_zero_successes(c: Ctx):
    b = c.boot
    hits, bad = [], []
    for m in ("resolved", "resolved_ex_refusal", "skeleton_edit"):
        for x in CONDS:
            if x == "F3":
                continue
            lo, hi = b.diff(m, x, "F3")[1]
            if lo == 0.0 or hi == 0.0:
                k = int(b.S[m][:, CONDS.index(x)].sum())
                hits.append(f"{m} {x}-F3 [{lo:+.1f},{hi:+.1f}] successes {k}")
                if k != 0:
                    bad.append(hits[-1])
    return not bad and bool(hits), "; ".join(hits)


def zero_upper_for_zero_success(c: Ctx):
    b = c.boot
    out, ok = [], True
    for x in ("F2", "F4a", "F4b"):
        k = int(b.S["resolved_ex_refusal"][:, CONDS.index(x)].sum())
        lo, hi = b.diff("resolved_ex_refusal", x, "F3")[1]
        ok &= k == 0 and hi == 0.0
        out.append(f"{x}: successes {k}, [{lo:+.1f},{hi:+.1f}]")
    return ok, "; ".join(out)


def balanced_equivalence(c: Ctx) -> float:
    """max |rate difference - mean of per-certificate differences| over all resamples."""
    np = c.boot.np
    b = c.boot
    worst = 0.0
    for m, x, y in CONTRASTS17:
        i, j = CONDS.index(x), CONDS.index(y)
        d_cert = 100.0 * (b.S[m][:, i] - b.S[m][:, j]) / 3.0
        via_mean = d_cert[b.picks].mean(axis=1)
        via_rate = b.rates[m][:, i] - b.rates[m][:, j]
        worst = max(worst, float(np.max(np.abs(via_mean - via_rate))))
    return worst


def cert_level_formula(c: Ctx):
    reps = {n for n in collections.Counter((a["condition"], a["certificate_id"]) for a in c.attempts).values()}
    if reps != {3}:
        return f"cells not balanced: {reps}"
    w = balanced_equivalence(c)
    if w > 1e-9:
        return f"not equivalent: max deviation {w}"
    return MultiValue((len(c.certs), 100, 3), f"max |rate diff - mean of certificate-level diffs| = {w:.1e} "
                                              "over all 10,000 resamples and 17 contrasts")


def uncert_source(c: Ctx) -> str:
    return c.p("scripts/uncertainty.py").read_text()


def uncert_percentiles(c: Ctx):
    src = uncert_source(c)
    m = re.search(r"np\.percentile\(a,\s*([\d.]+)\)\),\s*float\(np\.percentile\(a,\s*([\d.]+)\)", src)
    if not m:
        raise NotRecomputable("percentile call not found in scripts/uncertainty.py")
    return Fraction(m.group(1)), Fraction(m.group(2))


def uncert_seed(c: Ctx):
    import numpy as np
    src = uncert_source(c)
    seeds = set(re.findall(r"def (?:cluster_bootstrap|paired_diff_draws)\([^)]*seed=(\d+)\)", src))
    gen = type(np.random.default_rng(0).bit_generator).__name__
    if len(seeds) != 1 or gen != "PCG64" or int(next(iter(seeds))) != BOOT_SEED:
        return f"seeds {seeds}, generator {gen}"
    return MultiValue(int(seeds.pop()), f"default seed of cluster_bootstrap and paired_diff_draws; "
                                        f"numpy.random.default_rng bit generator {gen}")


def n_boot_both(c: Ctx):
    js = c.json("data/results/uncertainty.json")["n_boot"]
    if js != N_BOOT:
        return f"uncertainty.json n_boot {js}"
    return N_BOOT


def denominators_always(c: Ctx):
    s = c.boot.n_per_cond_in_resamples()
    if len(s) != 1:
        return f"denominators {sorted(s)}"
    return s.pop()


def attempts_per_cert(c: Ctx):
    s = set(collections.Counter(a["certificate_id"] for a in c.attempts).values())
    return s.pop() if len(s) == 1 else f"not constant: {s}"


def bonf_alpha(c: Ctx):
    a = c.json("data/results/uncertainty.json")["multiplicity"]["bonferroni_alpha"]
    if abs(a - 0.05 / len(CONTRASTS17)) > 1e-15:
        return f"uncertainty.json bonferroni_alpha {a}"
    return Fraction(5, 100), len(CONTRASTS17)


# ---- detectable effect (Appendix E) -----------------------------------------
def de(c: Ctx) -> dict:
    p = c.p("data/results/detectable_effect.json")
    if not p.exists():
        raise NotRecomputable("data/results/detectable_effect.json absent")
    return c.json("data/results/detectable_effect.json")


def de_sim(c: Ctx, p0: float, icc: float, r: float) -> dict:
    hits = [s for s in de(c)["simulations"] if not s["label"].startswith("SUPP")
            and abs(s["p0"] - p0) < 1e-9 and s["icc"] == icc and s["coupling_r"] == r]
    if len(hits) != 1:
        raise NotRecomputable(f"{len(hits)} simulations for p0={p0}, icc={icc}, r={r}")
    return hits[0]


# The settings Table 7 reports: ICC 0 (no certificate effect), and ICC 0.1 and
# 0.3 under shared (r = 1) and independent (r = 0) difficulty.
TABLE7_SETTINGS = [(0.0, 1.0), (0.1, 1.0), (0.1, 0.0), (0.3, 1.0), (0.3, 0.0)]
P0_33 = 1 / 30


def mde(c: Ctx, p0: float, icc: float, r: float, key: str = "mde_80") -> float:
    return de_sim(c, p0, icc, r)[key]["mde_pp_interp"]


def mde_range(c: Ctx, p0: float = P0_33):
    xs = [mde(c, p0, i, r) for i, r in TABLE7_SETTINGS]
    return min(xs), max(xs)


def mde_main(c: Ctx):
    lo, hi = mde_range(c)
    f3 = pct(c.count(lambda a: a["resolved"] and not a["resolved_by_refusal"], "F3"), 60)
    tp = de(c)["settings"]["target_power"]
    if abs(float(f3) / 100 - P0_33) > 1e-12:
        return f"F3 ex-refusal rate {float(f3):.4f}% is not the simulated p0 {100 * P0_33:.4f}%"
    return MultiValue((f3, tp, lo, hi), f"MDE80 over the Table 7 settings at p0 = 2/60: {lo:.2f} to {hi:.2f} points")


def mde_large_bool(c: Ctx):
    lo, hi = mde_range(c)
    return lo >= 10.0, f"MDE80 {lo:.1f} to {hi:.1f} points against F3's 3.3% (Table 7 settings)"


def power_at5_quarter(c: Ctx):
    ps = [de_sim(c, P0_33, i, r)["power_at"]["5pp"]["power"] for i, r in TABLE7_SETTINGS]
    return max(ps) <= 0.25, f"power at +5 points over the Table 7 settings: {', '.join(f'{p:.3f}' for p in ps)}"


def bonf_increments(c: Ctx):
    d4, d17 = [], []
    for p0 in (P0_33, 0.05):
        for i, r in TABLE7_SETTINGS:
            base = mde(c, p0, i, r)
            d4.append(mde(c, p0, i, r, "mde_80_bonferroni") - base)
            d17.append(mde(c, p0, i, r, "mde_80_bonferroni17") - base)
    return MultiValue((4, min(d4), max(d4), len(CONTRASTS17), min(d17), max(d17)),
                      f"increase over the 10 Table 7 entries: x4 {min(d4):.2f} to {max(d4):.2f}, "
                      f"x17 {min(d17):.2f} to {max(d17):.2f} points")


def literal_vs_exact(c: Ctx):
    v = de(c)["validation"]["literal_vs_exact_on_simulated"]
    n = sum(x["n"] for x in v)
    agree = n - sum(x["n_disagree"] for x in v)
    return len(c.certs), de(c)["settings"]["boot_B_literal_rule"], agree, n


def icc_grid(c: Ctx):
    sims = [s for s in de(c)["simulations"] if not s["label"].startswith("SUPP")]
    for p0 in (P0_33, 0.05):
        for i, r in TABLE7_SETTINGS:
            de_sim(c, p0, i, r)
    return 0.0, 0.1, 0.3


def arcsine_mde(p0: float, n: int = 60, alpha: float = 0.05, power: float = 0.8) -> float:
    from statistics import NormalDist
    z = NormalDist().inv_cdf
    h = (z(1 - alpha / 2) + z(power)) * math.sqrt(2 / n)
    return 100 * (math.sin(math.asin(math.sqrt(p0)) + h / 2) ** 2 - p0)


@functools.lru_cache(maxsize=None)
def fisher_rejects(n: int = 60, alpha: float = 0.05):
    import numpy as np
    from scipy import stats
    P = np.ones((n + 1, n + 1))
    for x0 in range(n + 1):
        for x1 in range(n + 1):
            P[x0, x1] = stats.fisher_exact([[x0, n - x0], [x1, n - x1]])[1]
    return P < alpha


def fisher_mde(p0: float, n: int = 60, step_pp: float = 0.25, power: float = 0.8) -> float:
    import numpy as np
    from scipy import stats
    rej = fisher_rejects(n)
    b0 = stats.binom.pmf(np.arange(n + 1), n, p0)
    for k in range(1, 4 * 100):
        p1 = p0 + step_pp * k / 100
        b1 = stats.binom.pmf(np.arange(n + 1), n, p1)
        if float((b0[:, None] * b1[None, :] * rej).sum()) >= power:
            return step_pp * k
    raise NotRecomputable("Fisher MDE not reached")


def closed_forms(c: Ctx):
    cf = de(c)["closed_form_no_clustering"]["0.0333"]
    a, f = arcsine_mde(P0_33), fisher_mde(P0_33)
    f3 = pct(c.count(lambda x: x["resolved"] and not x["resolved_by_refusal"], "F3"), 60)
    if abs(a - cf["arcsine_pp"]) > 1e-6 or abs(f - cf["fisher_exact_mde_pp_grid"]) > 1e-9:
        return f"independent {a:.3f} / {f} vs artefact {cf['arcsine_pp']:.3f} / {cf['fisher_exact_mde_pp_grid']}"
    return MultiValue((60, a, f, f3), f"recomputed here (normal quantiles; scipy fisher_exact two-sided on a "
                                      f"0.25-point grid) and equal to the artefact: arcsine {a:.3f}, Fisher {f}")


def min_certs_to_exclude(c: Ctx):
    K = len(c.certs)
    k = next(k for k in range(1, K + 1) if ((K - k) / K) ** K < 0.025)
    js = de(c)["decision_table"]["min_certificates_with_D_gt_0_among_detected_increases"]
    if js != k:
        return f"arithmetic {k} but artefact decision table {js}"
    return MultiValue((k, K), f"((K-{k - 1})/K)^K = {((K - k + 1) / K) ** K:.4f} >= 0.025 > ((K-{k})/K)^K = "
                              f"{((K - k) / K) ** K:.4f}; equals the artefact's exhaustive decision table")


def f3_success_certs(c: Ctx):
    preds = {"S": lambda a: a["resolved"],
             "S excl. refusals": lambda a: a["resolved"] and not a["resolved_by_refusal"],
             "S,C": lambda a: a["resolved_and_completed"], "S,C,R": is_clean}
    out = {k: sorted({a["certificate_id"].split("_")[0] for a in c.by_cond("F3") if f(a)}) for k, f in preds.items()}
    return MultiValue(max(len(v) for v in out.values()), str(out))


def exref_pattern(c: Ctx):
    xs = [a for a in c.attempts if a["resolved"] and not a["resolved_by_refusal"]]
    per_cell = collections.Counter((a["condition"], a["certificate_id"]) for a in xs)
    certs = {a["certificate_id"].split("_")[0] for a in xs}
    return MultiValue((len(xs), max(per_cell.values()), len(certs)),
                      ", ".join(sorted(f"{a['condition']} {a['certificate_id'].split('_')[0]}" for a in xs)))


def tab7_entry(c: Ctx, icc: float, which: str):
    p0s = [P0_33, 0.05]
    if which == "zero":
        return (icc, mde(c, p0s[0], 0.0, 1.0), mde(c, p0s[1], 0.0, 1.0))
    return (icc, mde(c, p0s[0], icc, 1.0), mde(c, p0s[0], icc, 0.0),
            mde(c, p0s[1], icc, 1.0), mde(c, p0s[1], icc, 0.0))


def tab7_p0s(c: Ctx):
    return Fraction(100, 30), Fraction(5)


def tab7_caption_rates(c: Ctx):
    ex = c.count(lambda a: a["resolved"] and not a["resolved_by_refusal"], "F3")
    sc = c.count(lambda a: a["resolved_and_completed"], "F3")
    pre = c.count(lambda a: a["resolved"], "F3")
    if ex != sc:
        return f"F3 excluding refusals {ex}/60 but fixed and completed {sc}/60"
    return pct(ex, 60), pct(pre, 60)


def n_sim_all(c: Ctx):
    s = {de_sim(c, p0, i, r)["n_sim"] for p0 in (P0_33, 0.05) for i, r in TABLE7_SETTINGS}
    return s.pop() if len(s) == 1 else f"n_sim varies: {s}"


def second_seed_ok(c: Ctx):
    per = {x["label"]: x for x in de(c)["monte_carlo_replicate"]["per_setting"]}
    diffs, flips = [], []
    for p0 in (P0_33, 0.05):
        for i, r in TABLE7_SETTINGS:
            lab = de_sim(c, p0, i, r)["label"]
            m = per[lab]["mde_80"]
            diffs.append(m["abs_diff"])
            r1, r2 = (to_dec(m[k]).quantize(decimal.Decimal(1), rounding=decimal.ROUND_HALF_UP)
                      for k in ("seed_main", "seed_2"))
            if r1 != r2:
                flips.append(f"{lab}: {r1} vs {r2}")
    allmax = de(c)["monte_carlo_replicate"]["max_abs_diff_mde_80_pp"]
    return max(diffs) <= 0.5, (f"max |seed 1 - seed 2| over the Table 7 entries {max(diffs):.3f} "
                               f"(over all 33 settings {allmax:.3f}); whole-point entries that change with the "
                               f"second seed: {flips or 'none'}")


def target_power(c: Ctx):
    return de(c)["settings"]["target_power"]


# ---- taxonomy (Appendix C) --------------------------------------------------
def taxonomy(c: Ctx) -> dict:
    if hasattr(c, "_tax"):
        return c._tax
    from program_parser import parse
    from ted import classify_patch, ted_from_source
    from bt_vocabulary import ALL_NODES

    def nodes(n):
        out = [n]
        for k in n.children:
            out += nodes(k)
        return out

    lab = collections.Counter()
    grew = shrank_or_same = 0
    hole_kind = collections.Counter()
    hole_kind_by = collections.defaultdict(collections.Counter)
    ted = collections.defaultdict(list)
    reg = collections.defaultdict(list)
    for a in c.attempts:
        t = classify_patch(a["bt_source_before"], a["bt_source_after"])
        lab[t] += 1
        ted[t].append(ted_from_source(a["bt_source_before"], a["bt_source_after"]))
        reg[t].append(a["regression_failures"] or 0)
        if t not in ("skeleton_edit", "hole_fill"):
            continue
        nb, nf = nodes(parse(a["bt_source_before"])), nodes(parse(a["bt_source_after"]))
        if t == "skeleton_edit":
            if len(nf) > len(nb):
                grew += 1
            else:
                shrank_or_same += 1
            continue
        kinds = set()
        for x, y in zip(nb, nf):
            if x.name != y.name:
                raise NotRecomputable(f"hole fill with differing node names in {a['attempt_id']}")
            if {k: round(float(v), 6) for k, v in x.params.items()} != \
                    {k: round(float(v), 6) for k, v in y.params.items()}:
                kinds.add(ALL_NODES[x.name].kind)
        hole_kind["action" if "action" in kinds else ("condition only" if kinds == {"condition"} else str(kinds))] += 1
        hole_kind_by[a["condition"]][tuple(sorted(kinds))] += 1
    c._tax = {"lab": lab, "grew": grew, "not_grew": shrank_or_same, "hole_kind": hole_kind,
              "hole_kind_by": hole_kind_by, "ted": ted, "reg": reg}
    return c._tax


def tax_counts(c: Ctx):
    t = taxonomy(c)["lab"]
    other = {k: v for k, v in t.items() if k not in ("hole_fill", "skeleton_edit")}
    if other:
        return f"also {other}"
    return t["hole_fill"], t["skeleton_edit"]


def tax_grew(c: Ctx):
    t = taxonomy(c)
    return t["not_grew"] == 0 and t["grew"] > 0, f"{t['grew']} of {t['grew'] + t['not_grew']} skeleton edits add nodes"


def tax_hole_kinds(c: Ctx):
    k = taxonomy(c)["hole_kind"]
    extra = {x: v for x, v in k.items() if x not in ("action", "condition only")}
    if extra:
        return f"unexpected kinds {extra}"
    return k["action"], k["condition only"]


def tax_medians(c: Ctx):
    t = taxonomy(c)["ted"]
    return Fraction(statistics.median(t["hole_fill"])), Fraction(statistics.median(t["skeleton_edit"]))


def tax_reg_means(c: Ctx):
    r = taxonomy(c)["reg"]
    return (Fraction(sum(r["skeleton_edit"]), len(r["skeleton_edit"])),
            Fraction(sum(r["hole_fill"]), len(r["hole_fill"])))


def tax_reproduces(c: Ctx):
    from ted import classify_patch
    return sum(1 for a in c.attempts if classify_patch(a["bt_source_before"], a["bt_source_after"]) == a["patch_type"])


def f2_threshold(c: Ctx):
    by = taxonomy(c)["hole_kind_by"]["F2"]
    n_hole = sum(by.values())
    with_cond = sum(v for k, v in by.items() if "condition" in k)
    also_action = sum(v for k, v in by.items() if "action" in k)
    return (n_hole > 30 and with_cond == n_hole,
            f"F2: {n_hole}/60 hole fills, {with_cond} of them change a predicate threshold, {also_action} also "
            f"change an action set-point")


def git(c: Ctx, *args) -> str:
    r = subprocess.run(["git", "-C", str(c.repo), *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise NotRecomputable(f"git {' '.join(args)} failed: {r.stderr.strip()[:200]}")
    return r.stdout


def campaign_history(c: Ctx) -> set:
    """The commits the attempts record, which must be in this checkout's git
    history for a claim about commit order to be checkable. A checkout without
    them (an export, or a snapshot whose history starts after the campaign)
    raises NotRecomputable: the claim is about history it does not contain."""
    if not shutil.which("git") or not c.p(".git").exists():
        raise NotRecomputable("not a git checkout: the claim is about the development history")
    commits = {a["git_commit"] for a in c.attempts}
    missing = sorted(x[:7] for x in commits
                     if subprocess.run(["git", "-C", str(c.repo), "cat-file", "-e", f"{x}^{{commit}}"],
                                       capture_output=True).returncode != 0)
    if missing:
        raise NotRecomputable(f"the campaign's commit {', '.join(missing)} (attempts.jsonl git_commit) is not in "
                              "this repository's history, so the order of development commits cannot be checked "
                              "here")
    return commits


def _code_only(src: str) -> str:
    """AST of a Python source with docstrings removed (comments are not in the AST)."""
    import ast
    tree = ast.parse(src)
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr) \
                and isinstance(getattr(body[0], "value", None), ast.Constant) \
                and isinstance(body[0].value.value, str):
            node.body = body[1:] or [ast.Pass()]
    return ast.dump(tree, include_attributes=False)


def classifier_provenance(c: Ctx):
    campaign_history(c)
    first = git(c, "log", "--format=%H %cI", "--diff-filter=A", "--", "src/ted.py").split()
    commits = {a["git_commit"] for a in c.attempts}
    tests = git(c, "ls-tree", "--name-only", first[0], "tests/test_ted.py").strip()
    files = ["src/ted.py", "src/program_parser.py", "src/bt_vocabulary.py"]
    # "Apart from comments": compare the code, not the bytes. Comments and
    # docstrings were reworded for the public release; the logic was not.
    changed = [f for f in files
               if _code_only(git(c, "show", f"{first[0]}:{f}")) != _code_only(c.p(f).read_text())]
    dirty = []
    t0 = min(a["timestamp"] for a in c.attempts)
    import datetime as dt
    before = dt.datetime.fromisoformat(first[1]) < dt.datetime.fromisoformat(t0)
    ok = commits == {first[0]} and bool(tests) and not changed and not dirty and before
    return ok, (f"src/ted.py added in {first[0][:7]} at {first[1]}, with tests/test_ted.py: {bool(tests)}; all 300 "
                f"attempts record that commit: {commits == {first[0]}}; first attempt {t0}; classifier, parser, "
                f"vocabulary changed since: {changed or 'no'}; uncommitted changes: {dirty or 'no'}")


def taxonomy_predefined(c: Ctx):
    campaign_history(c)
    out = git(c, "log", "--reverse", "--format=%H %cI", "-S", "Hole fill vs skeleton edit", "--",
              "01_TECHNICAL_SPEC.md", "01_TECHNICAL_SPEC_v2.md").split("\n")
    first = out[0].split()
    t0 = min(a["timestamp"] for a in c.attempts)
    import datetime as dt
    ok = bool(first) and dt.datetime.fromisoformat(first[1]) < dt.datetime.fromisoformat(t0)
    return ok, f"'Hole fill vs skeleton edit' first committed in {first[0][:7]} at {first[1]}; first attempt {t0}"


# ---- F1 excerpt (Appendix A) -------------------------------------------------
def f1_window_dims(c: Ctx):
    """Rows x columns of the F1 trajectory excerpt, in every F1 prompt: the
    committed CE003 copy, the 20 F1 feedback blocks regenerated from the
    certificates (data/certificates/traces/), and the 60 F1 prompts sent
    (logs/campaign/prompts/). The header row must have that many columns."""
    rx = re.compile(r"trace: logged trajectory, rows (\d+)-(\d+) of (\d+), all (\d+) columns")

    def dims_of(text: str):
        m = rx.search(text)
        if not m:
            return ("no excerpt header",)
        hdr = text[m.end():].split("\n")[1].split(",")
        if len(hdr) != int(m.group(4)):
            return ("header has", len(hdr), "columns, not", int(m.group(4)))
        return (int(m.group(2)) - int(m.group(1)) + 1, int(m.group(4)))

    seen = {"committed CE003": collections.Counter([dims_of(
        c.p("data/results/rendered_prompts/CE003_C1_969f15c8657c8fa6_F1.txt").read_text())])}
    g = regen_prompts(c)
    if g["f1"]:
        seen["regenerated F1 feedback"] = collections.Counter(
            dims_of(fb) for (cid, cond), fb in g["fb"].items() if cond == "F1")
    d = c.p("logs/campaign/prompts")
    if d.is_dir():
        seen["logs/campaign/prompts F1"] = collections.Counter(
            dims_of(f.read_text()) for f in sorted(d.glob("F1__*.txt")))
    note = "; ".join(f"{k}: {dict(v)}" for k, v in seen.items())
    dims = {x for v in seen.values() for x in v}
    if len(dims) != 1:
        return f"not constant: {note}"
    hw = c.exp_cfg["f1_excerpt_halfwidth_rows"]
    dd = dims.pop()
    if len(dd) != 2:
        return f"{dd}: {note}"
    r, k = dd
    if r != 2 * hw + 1:
        return f"{r} rows, but 2 x half-width {hw} + 1 = {2 * hw + 1}"
    return MultiValue((r, k), note)


def outside_window(c: Ctx):
    lo, hi = rows_back(c)
    hw = c.exp_cfg["f1_excerpt_halfwidth_rows"]
    if lo <= hw:
        return f"min rows back {lo} <= half-width {hw}: inside the window"
    return lo, hi, 2 * hw + 1


def with_boundary(c: Ctx):
    k, n = no_boundary(c)
    return n - k, n


# ---- deviations (Appendix B) ---------------------------------------------------
SPEC_V2 = ("01_TECHNICAL_SPEC_v2.md", "docs/study_plan/01_TECHNICAL_SPEC_v2.md",
           "docs/preregistration/01_TECHNICAL_SPEC_v2.md",
           "docs/preregistered_plan_v2.md")


def spec_v2_text(c: Ctx) -> str:
    """The internal study plan (spec v2), at either of the names it may carry."""
    for rel in SPEC_V2:
        if c.p(rel).exists():
            return c.p(rel).read_text()
    raise NotRecomputable(f"internal study plan absent (looked for {', '.join(SPEC_V2)})")


def prereg_dropped_added(c: Ctx):
    txt = spec_v2_text(c)
    sec = re.search(r"### §6\.1 Search space[^\n]*\n\s*\n((?:\|[^\n]*\n)+)", txt)
    if not sec:
        raise NotRecomputable("section 6.1 table not found in 01_TECHNICAL_SPEC_v2.md")
    pre = set(re.findall(r"^\|\s*`(\w+)`\s*\|", sec.group(1), re.M))
    sp = c.yaml("data/scenarios/space.yaml")
    run = set(sp["parameters"])
    dropped, added = sorted(pre - run), sorted(run - pre)
    ok = dropped == ["ped_phase_offset"] and added == ["aggressiveness", "lead_gap_s", "light_offset"]
    if not ok:
        return f"pre-specified {sorted(pre)}; dropped {dropped}; added {added}"
    return MultiValue(len(pre), f"pre-specified {sorted(pre)}; dropped {dropped} (space.yaml 'dropped': "
                                f"{sorted(sp.get('dropped') or {})}); added {added}")


def aggressiveness_reason(c: Ctx):
    j = c.yaml("data/scenarios/space.yaml")["parameters"]["aggressiveness"]["justification"]
    if not re.search(r"only\s+parameter\s+carrying\s+signal", j):
        return "space.yaml justification does not say so"
    return MultiValue(1, "space.yaml aggressiveness.justification: '" + re.sub(r"\s+", " ", j)[:200] + "...'")


# ---- trajectories re-scored with src/stl.py (Table 4, validation, Sec. 3.2) ----
PROBE_DIR = "data/dsl_probe_traces"
CALIB_DIR = "data/calibration_traces"
_PROBES: dict = {}


def sha16(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def _scorer(c: Ctx):
    """src/stl.py and the campaign's contracts, junction and parameter hash."""
    for sub in ("src", "scripts"):
        if str(c.p(sub)) not in sys.path:
            sys.path.insert(0, str(c.p(sub)))
    import stl
    from config import load_config, param_hash
    return stl, load_config("contracts"), stl.load_junction(), param_hash


def _score_episode(env, sidecar: pathlib.Path) -> dict:
    """One episode: the sidecar's metadata plus rho from the trajectory.

    Definitions as in src/evaluate.py and scripts/rescore_dsl_probes.py:
    fixed = rho >= 0 (rho = min over the contracts, a vacuous contract kept
    out of the argmin by its 999.0 sentinel); completed = P4_settle in the
    episode's phases_reached; entered = C2 not vacuous (the ego was inside
    the conflict zone on at least one tick)."""
    stl, contracts, junction, _ = env
    m = json.loads(sidecar.read_text())
    df, _ = stl.load_trace(str(sidecar.with_suffix(".parquet")))
    r = stl.compute_rho(df, contracts, junction)
    src = m.get("program_source") or ""
    return {"file": sidecar.name, "param_hash": m["param_hash"], "program_sha": m.get("program_sha"),
            "source_sha": sha16(src), "source": src,
            "rho": float(r.rho), "contract": r.contract,
            "rho4": float(r.per_contract["C4"].rho) if "C4" in r.per_contract else None,
            "fixed": bool(r.rho >= 0), "entered": not r.per_contract["C2"].vacuous,
            "completed": "P4_settle" in (m["result"]["meta"].get("phases_reached") or [])}


def probe_scores(c: Ctx) -> dict:
    """Every hand-written repair of the expressiveness table, the model's clean
    repair and its six repeats, re-scored from the released trajectories in
    data/dsl_probe_traces/ with the campaign scorer.

    Released layout (scripts/rescore_dsl_probes.py documents the same map):
      frozen_baseline/            data/scenarios/baseline_program.bt
      raise_gap_thresholds/       dsl_probe/fixA_bigger_gap.bt
      gap_guard_sweep/gap_s_<g>/  dsl_probe/sweep_<g>.bt, one per committed sweep
      geometric_guard/<variant>/  a committed dsl_probe/*.bt adding PathIsClear
      geometric_guard_true_stop/  dsl_probe/fixFULL.bt
      clean_repair/               dsl_probe/clean_repair.bt
      repeats/                    clean_repair.bt, six runs on one counterexample

    Each episode is linked to its certificate by parameter hash and to its
    program by sha256(program source)[:16], which must equal the sidecar's
    program_sha and the hash of the committed .bt file named above. Every
    variant must cover all K certificates exactly once. Any break in these
    links raises NotRecomputable rather than producing a count.
    """
    key = str(c.repo)
    if key in _PROBES:
        if isinstance(_PROBES[key], Exception):
            raise _PROBES[key]
        return _PROBES[key]
    try:
        root = c.p(PROBE_DIR)
        if not root.is_dir():
            raise NotRecomputable(f"{PROBE_DIR}/ absent")
        env = _scorer(c)
        param_hash = env[3]
        by_hash = {param_hash(x["evaluation_params"]): x["certificate_id"].split("_")[0] for x in c.certs}
        rel = lambda p: str(pathlib.Path(p).relative_to(c.repo))
        probe = c.p("data/scenarios/dsl_probe")
        committed = {sha16(p.read_text()): rel(p) for p in sorted(probe.glob("*.bt"))}
        base_rel = "data/scenarios/baseline_program.bt"
        base_src = c.p(base_rel).read_text()
        sweeps = sorted(probe.glob("sweep_*.bt"), key=lambda p: float(p.stem.split("_", 1)[1]))
        geo_root = root / "geometric_guard"
        groups: dict[str, list[tuple[str, str | None]]] = {
            "baseline": [("frozen_baseline", base_rel)],
            "fixA": [("raise_gap_thresholds", "data/scenarios/dsl_probe/fixA_bigger_gap.bt")],
            "sweep": [(f"gap_guard_sweep/gap_s_{p.stem.split('_', 1)[1]}", rel(p)) for p in sweeps],
            "geometric": [(f"geometric_guard/{d.name}", None)
                          for d in (sorted(geo_root.iterdir()) if geo_root.is_dir() else []) if d.is_dir()],
            "truestop": [("geometric_guard_true_stop", "data/scenarios/dsl_probe/fixFULL.bt")],
            "clean": [("clean_repair", "data/scenarios/dsl_probe/clean_repair.bt")],
        }
        if not groups["geometric"]:
            raise NotRecomputable(f"{PROBE_DIR}/geometric_guard/ has no variant directories")
        n_pic = base_src.count("PathIsClear(")
        out: dict = {}
        for g, variants in groups.items():
            out[g] = []
            for sub, prog in variants:
                d = root / sub
                files = sorted(d.glob("*_CE[0-9][0-9][0-9].json")) if d.is_dir() else []
                if not files:
                    raise NotRecomputable(f"no trajectories in {PROBE_DIR}/{sub}/")
                eps = [_score_episode(env, f) for f in files]
                shas = {(e["program_sha"], e["source_sha"]) for e in eps}
                if len(shas) != 1 or eps[0]["program_sha"] != eps[0]["source_sha"]:
                    raise NotRecomputable(f"{PROBE_DIR}/{sub}/: episodes disagree on the program, or a sidecar's "
                                          "program_sha is not the hash of its program_source")
                psha = eps[0]["program_sha"]
                if prog is None:            # geometric family: any committed program adding a path check
                    prog = committed.get(psha)
                    if prog is None:
                        raise NotRecomputable(f"{PROBE_DIR}/{sub}/: program {psha} matches no committed "
                                              "data/scenarios/dsl_probe/*.bt")
                    if eps[0]["source"].count("PathIsClear(") <= n_pic:
                        raise NotRecomputable(f"{PROBE_DIR}/{sub}/: {prog} adds no PathIsClear guard")
                elif psha != sha16(c.p(prog).read_text()):
                    raise NotRecomputable(f"{PROBE_DIR}/{sub}/: program {psha} is not the committed {prog}")
                certs = [by_hash.get(e["param_hash"]) for e in eps]
                if None in certs or sorted(certs) != sorted(by_hash.values()):
                    raise NotRecomputable(f"{PROBE_DIR}/{sub}/: {len(eps)} episodes do not cover the {len(by_hash)} "
                                          "certificates once each (linked by parameter hash)")
                for e, ce in zip(eps, certs):
                    e["cert"] = ce
                    e.pop("source")
                out[g].append({"dir": sub, "program": prog, "program_sha": psha, "n": len(eps),
                               "fixed": sum(e["fixed"] for e in eps),
                               "completed": sum(e["completed"] for e in eps),
                               "entered": sum(e["entered"] for e in eps), "episodes": eps})
        # the clean repair's six repeats on its own counterexample
        rep = sorted((root / "repeats").glob("*.json")) if (root / "repeats").is_dir() else []
        if not rep:
            raise NotRecomputable(f"no trajectories in {PROBE_DIR}/repeats/")
        want = out["clean"][0]["program_sha"]
        reps = [_score_episode(env, f) for f in rep]
        for e in reps:
            if not (e["program_sha"] == e["source_sha"] == want):
                raise NotRecomputable(f"{PROBE_DIR}/repeats/{e['file']}: program {e['program_sha']} is not "
                                      f"clean_repair.bt ({want})")
            e["cert"] = by_hash.get(e["param_hash"])
            e.pop("source")
            if e["cert"] is None:
                raise NotRecomputable(f"{PROBE_DIR}/repeats/{e['file']}: parameter hash matches no certificate")
        out["repeats"] = reps
        _PROBES[key] = out
        return out
    except NotRecomputable as e:
        _PROBES[key] = e
        raise
    except Exception as e:  # a missing or unreadable trajectory is not a paper mismatch
        err = NotRecomputable(f"re-scoring {PROBE_DIR}/ raised {type(e).__name__}: {e}")
        _PROBES[key] = err
        raise err


def _variant_line(r: dict) -> str:
    return (f"{r['dir']} ({pathlib.Path(r['program']).name}): fixed {r['fixed']}/{r['n']}, "
            f"completed {r['completed']}/{r['n']}, entered {r['entered']}/{r['n']}")


def art_dsl(needle: str, *fields: str):
    """Artefact check: the dsl_expressiveness.json variant's counts."""
    def f(c: Ctx):
        v = dsl_variant(c, needle)
        return tuple(x for k in fields for x in frac_str(v[k])), f"dsl_expressiveness.json {needle!r}"
    return f


def art_baseline_eval(c: Ctx):
    be = c.baseline_eval
    return ((sum(1 for v in be.values() if v["resolved"]), len(be),
             sum(1 for v in be.values() if v["ce_completed"]), len(be)), "baseline_eval.json")


def probe_cells(c: Ctx, group: str, fields: tuple[str, ...], artefact: Callable | None = None,
                with_n: bool = True):
    """One row of the expressiveness table, re-scored: (count, K) per field,
    which must be the same for every variant in the group, and must equal the
    committed artefact's counts where one records them."""
    res = probe_scores(c)[group]
    det = "; ".join(_variant_line(r) for r in res)
    vals = {tuple(x for f in fields for x in ((r[f], r["n"]) if with_n else (r[f],))) for r in res}
    if len(vals) != 1:
        return f"varies across variants: {det}"
    val = vals.pop()
    if artefact is not None:
        want, name = artefact(c)
        if not with_n:
            want = want[::2]
        if tuple(want) != val:
            return f"re-scored {val} but {name} records {tuple(want)} ({det})"
        det += f"; {name} agrees"
    return MultiValue(val if len(val) > 1 else val[0], det)


# ---- checklist ------------------------------------------------------------------
def env_doc(c: Ctx, rx: str, n: int = 1):
    t = c.p("docs/env_manifest.md").read_text()
    m = re.search(rx, t)
    if not m:
        raise NotRecomputable(f"pattern {rx!r} not in docs/env_manifest.md")
    vals = tuple(decimal.Decimal(m.group(i + 1)) for i in range(n))
    return vals if n > 1 else vals[0]


def pkg_version(c: Ctx, req_name: str | None, dist: str):
    import importlib.metadata as md
    pin = None
    if req_name:
        for line in c.p("requirements.txt").read_text().splitlines():
            if line.strip().lower().startswith(req_name.lower() + "=="):
                pin = line.split("==", 1)[1].strip()
    try:
        inst = md.version(dist)
    except Exception:
        inst = None
    if pin and inst and pin != inst:
        return f"requirements.txt pins {pin} but {inst} is installed"
    v = pin or inst
    if v is None:
        raise NotRecomputable(f"{dist}: not pinned in requirements.txt and not installed")
    return MultiValue(v, f"requirements.txt: {pin or 'NOT PINNED'}; installed: {inst}")


def falsif_wall(c: Ctx):
    d = c.json("data/results/falsification_summary.json")
    return Fraction(str(d["wall_clock_s"])), d["rollouts"]["rollouts_total"]


def token_sums(c: Ctx):
    A = c.attempts
    inp = sum(a["tokens_prompt"] + a["cache_read"] + a["cache_write"] for a in A)
    return inp, sum(a["cache_read"] for a in A), sum(a["tokens_completion"] for a in A)


def rollouts_eval_total(c: Ctx):
    A = c.attempts
    att = sum(a["rollouts_counterexample"] + a["rollouts_regression"] + a["rollouts_evaluation"] for a in A)
    base = (len(c.baseline_eval) + c.json("data/scenarios/regression_suite.json")["n"]
            + c.json("data/scenarios/held_out_suite.json")["n"])
    note = (f"attempts {att} + unpatched baseline {base} (20 counterexamples, 30 regression, 30 held-out; "
            "the suites are cached across certificates)")
    log = c.p("logs/e1_phase_b.log")
    if log.exists():
        m = re.search(r"rollouts: (\{[^}]*\})", log.read_text())
        if m:
            logged = sum(json.loads(m.group(1)).values())
            note += f"; logs/e1_phase_b.log: {m.group(1)} = {logged}"
            if logged != att + base:
                return f"recomputed {att + base}, but logs/e1_phase_b.log records {logged} ({note})"
    return MultiValue(att + base, note)


def phase_minutes(c: Ctx, phase: str):
    log = c.p(f"logs/e1_phase_{phase.lower()}.log")
    if not log.exists():
        raise NotRecomputable(f"{log.relative_to(c.repo)} absent: no other artefact records campaign "
                              "wall-clock time")
    m = re.search(rf"PHASE {phase} done in ([\d.]+) min", log.read_text())
    if not m:
        raise NotRecomputable(f"no 'PHASE {phase} done' line in {log.name}")
    return MultiValue(Fraction(m.group(1)), f"{log.relative_to(c.repo)}: {m.group(0)!r}")


def claims_v11() -> list[Claim]:
    C: list[Claim] = []

    def add(cl: Claim):
        if cl.only is None:      # an explicit tag (a retired claim) is kept
            cl.only = "v1.1"
        C.append(cl)

    T = r"\s*&\s*"

    # ------------------------------------------------------------------ abstract
    add(Claim("ABS-02b", "repair attempts run; one repair step each",
              ws(r"and run ") + G("v") + r"\s+(?P<s>one)-step\s+repair",
              lambda c: (len(c.attempts), one_step(c)), A_ATT, groups=("v", "s")))
    add(Claim("ABS-05b", "F1 minus F2 structural-edit rate, points",
              ws(r"a difference of \$") + G("v") + ws(r"\$ points with"),
              lambda c: pct(skel(c, "F1") - skel(c, "F2"), 60), A_ATT))
    add(Claim("ABS-06b", "95% interval of F1 minus F2 structural-edit rate",
              ws(r"points with \$95\\%\$ interval \$\[") + G("a") + "," + G("b") + r"\]\$",
              lambda c: c.boot.diff("skeleton_edit", "F1", "F2")[1], A_BOOT_F12, groups=("a", "b")))
    add(Claim("ABS-13", "under stated assumptions only large improvements would reliably have been detected",
              r"(?P<v>" + ws(r"under stated assumptions only large improvements would reliably have been detected")
              + r")",
              mde_large_bool, A_DE, kind="bool"))
    add(Claim("ABS-07b", "excluding refusals, no reliable improvement in repair success from any condition",
              r"(?P<v>" + ws(r"Excluding refusals, we did not detect a reliable improvement in repair success "
                             r"from any condition") + r")",
              ex_refusal_vs_f3_all_contain_zero, A_BOOT, kind="bool"))
    add(Claim("ABS-14", "satisfied S / of those never entered / other (entered) / completed / also regression-intact",
              ws(r"of the ") + G("s") + ws(r" attempts that satisfied the contracts, ") + G("r")
              + ws(r" never entered the junction's conflict zone; of the other ") + G("e") + ws(r", ") + G("c")
              + ws(r" completed the manoeuvre, and ") + G("d") + ws(r" of those also left the regression suite intact"),
              abstract_funnel, A_ATT, groups=("s", "r", "e", "c", "d")))
    add(Claim("ABS-15", "the clean program satisfies the contracts and completes the turn on all K",
              ws(r"That one program satisfies the contracts and completes the turn on all ") + W("v")
              + ws(r" counterexamples"),
              lambda c: clean_all(c), A_CLEAN))
    add(Claim("ABS-16", "found only once",
              ws(r"Why it was found only ") + W("v"), lambda c: c.count(is_clean), A_ATT))

    # ------------------------------------------------------------- introduction
    add(Claim("INT-01b", "introduction: could not detect any condition improving repair success",
              r"(?P<v>" + ws(r"that, excluding refusals, we could not detect any of them improving repair success") + r")",
              ex_refusal_vs_f3_all_contain_zero, A_BOOT, kind="bool",
              note="read as success excluding refusals; the pre-specified F1-F3 interval excludes zero, "
                   "driven by refusals (Section 4.4)"))
    add(Claim("INT-02b", "76.7-point structural-edit difference, raw trace vs natural-language summary",
              r"\$" + G("v") + r"\$-point\s+difference\s+in\s+structural-edit\s+rate\s+between\s+the\s+raw-trace\s+"
              r"and\s+natural-language\s+conditions",
              lambda c: pct(skel(c, "F1") - skel(c, "F2"), 60), A_ATT))
    add(Claim("INT-03b", "contribution 4: no detected improvement in repair success",
              r"(?P<v>" + ws(r"No detected improvement in repair success once refusals are excluded") + r")",
              ex_refusal_vs_f3_all_contain_zero, A_BOOT, kind="bool",
              note="read as success excluding refusals; the pre-specified F1-F3 interval excludes zero, "
                   "driven by refusals (Section 4.4)"))
    add(Claim("INT-04", "contribution 3: the clean repair resolves and completes all K",
              ws(r"language can express a program that resolves and completes all ") + W("v")
              + r"\s+counterexamples\s+\(\\S",
              lambda c: clean_all(c), "as ABS-15"))

    # ---------------------------------------------------------------- related
    add(Claim("REL-01b", "Reflexion: base-model pass@1 / full Reflexion pass@1",
              ws(r"exactly to the base model's \$") + G("a") + ws(r"\$, against \$") + G("b")
              + ws(r"\$ for full Reflexion"),
              NR("external citation (Reflexion, Table 3); checked by hand against the cited paper during revision; "
                 "not re-checked here (no network)"), "external", groups=("a", "b")))
    add(Claim("REL-04b", "Self-Debugging TransCoder: with trace / unit test only, %",
              ws(r"accuracy on TransCoder \(\$") + G("a") + ws(r"\\%\$ against \$") + G("b") + r"\\%\$\)",
              NR("external citation (Self-Debugging, Table 2b); checked by hand against the cited paper during revision; "
                 "not re-checked here (no network)"),
              "external", groups=("a", "b")))
    add(Claim("TAB1-RSSb", "RSS citation: lemma for the safe distance / rule numbers for C2 and avoidability",
              ws(r"is that work's rule~") + r"(?P<b>\d+)" + ws(r" and the avoidability filter its rule~")
              + r"(?P<c>\d+)" + r"[\s\S]*?" + ws(r"& RSS Lemma ") + r"(?P<a>\d+)",
              NR("external citation (shalevshwartz2017rss); not checked here (no network)"), "external",
              groups=("a", "b", "c")))

    # ----------------------------------------------------------------- baseline
    add(Claim("BAS-10", "synthesis responses truncated / output cap then in use",
              W("a") + ws(r" responses were truncated at the \$") + G("b") + r"\$-token\s+output\s+cap",
              synth_trunc, "recomputed: logs/llm_index.jsonl (committed); cap read from the truncated calls' "
              "completion length", groups=("a", "b")))
    add(Claim("BAS-11", "valid candidates / non-truncated responses",
              G("a") + ws(r" of the other ") + G("b") + ws(r" were valid programs"),
              synth_valid, "recomputed: logs/llm_index.jsonl and data/results/baseline_calibration.json",
              groups=("a", "b")))
    add(Claim("BAS-06b", "frozen baseline: violations / calibration scenarios",
              ws(r"The frozen baseline violates on \$") + G("a") + ws(r"\$ of the \$") + G("b")
              + ws(r"\$ calibration scenarios"),
              frozen_violations, "recomputed: baseline_calibration.json (cand_01) + TED(frozen, cand_01) = 0",
              groups=("a", "b")))
    add(Claim("BAS-07b", "frozen baseline enters the junction in all calibration scenarios",
              r"(?P<v>" + ws(r"enters the junction in all of them") + r")",
              calib_local_bool_entered, A_CALIB, kind="bool"))
    add(Claim("BAS-08b", "frozen baseline completes the turn, of the 100 calibration scenarios",
              ws(r"completes the turn in \$") + G("v") + r"\$\.",
              lambda c: calib_local_count(c, "settled"), A_CALIB,
              note="baseline_calibration.json has no completion field; baseline_calibration_frozen.json records "
                   "it for the frozen baseline only (I-22), so the completion gate's outcome for the other 13 "
                   "candidates is not in the released data"))
    add(Claim("BAS-09b", "candidates whose violation rates are in the released data",
              ws(r"Violation rates for all ") + G("v") + ws(" candidates are in the released data"),
              calib_candidates_released, "recomputed: data/results/baseline_calibration.json (git-tracked)"))

    # --------------------------------------- number words (word scan, 10 Oct)
    n_conds = lambda c: len({a["condition"] for a in c.attempts})
    add(Claim("FIG1-cap", "figure 1 caption: conditions sharing the fixed pipeline",
              ws(r"are identical across all ") + W("v") + ws(r" conditions \(grey band\)"), n_conds, A_ATT))
    add(Claim("TAB1-cap", "Table 1 caption: number of contracts",
              ws(r"\\caption\{The ") + W("v") + ws(r" contracts, in signal temporal logic"),
              lambda c: len(c.json("data/results/falsification_summary.json")["active_contracts"]),
              "recomputed: falsification_summary.json active_contracts"))
    add(Claim("TAB2-cap4", "Table 2 caption: conditions sharing one template",
              ws(r"All ") + W("v") + ws(r" share one template with a single feedback placeholder"), n_conds, A_ATT))
    add(Claim("UNC-05", "conditions run on the same counterexamples",
              ws(r"All ") + W("v") + ws(r" conditions are run on the same"), n_conds, A_ATT))
    add(Claim("FAL-06", "certificates for which boundary search yielded no boundary (Section 3.3)",
              ws(r"crosses zero; ") + W("v") + ws(r" of these boundaries are withheld"),
              lambda c: no_boundary(c)[0] if isinstance(no_boundary(c), tuple) else no_boundary(c), A_CERT))
    add(Claim("ACK-01", "acknowledgements: certificates released",
              ws(r"the frozen program, the ") + W("v") + ws(r" counterexample certificates"),
              lambda c: len(c.certs), A_CERT))
    add(Claim("TAXC-10", "parameters compared after rounding to N decimals",
              ws(r"differs after rounding to ") + W("v") + ws(" decimals"),
              lambda c: (lambda m: int(m.group(1)) if m else "round(float(v), N) not found in Node.to_tuple")(
                  re.search(r"def to_tuple[\s\S]*?round\(float\(v\),\s*(\d+)\)",
                            c.p("src/program_parser.py").read_text())),
              "recomputed: src/program_parser.py Node.to_tuple (used by src/ted.classify_patch)"))

    # ------------------------------------------------------- method (3.1)
    add(Claim("MET-01b", "junction approaches ('four-way')",
              ws(r"fixed signalized ") + W("v") + r"-way",
              lambda c: c.json("data/results/determinism_gate.json")["junction"]["n_traffic_lights"],
              "from artefact data/results/determinism_gate.json (junction.n_traffic_lights, read from CARLA)"))
    add(Claim("MET-05b", "attempts in which rho_4 was binding on the counterexample / attempts",
              ws(r"was the binding contract on the counterexample in \$") + G("a") + ws(r"\$ of \$") + G("b") + r"\$",
              lambda c: (c.count(lambda a: a["argmin_contract_after"] == "C4" or a["c4_binding_after"]),
                         len(c.attempts)), A_ATT + " (argmin_contract_after, c4_binding_after)", groups=("a", "b")))

    # ------------------------------------------------------- conditions, scope
    add(Claim("TAB2-cap3b", "prefix and suffix verified byte-identical across all conditions and certificates",
              r"(?P<v>" + ws(r"verified byte-identical across all conditions and certificates") + r")",
              prompt_identity_all,
              "recomputed: all 300 prompts regenerated from data/certificates/ (F1 from data/certificates/traces/) "
              "+ data/prompts/patch_task.md, hash-matched to attempts.jsonl; logs/campaign/prompts/ must agree",
              kind="bool"))
    add(Claim("CON-04b", "F1 window half-width, rows",
              ws(r"fits every certificate \(\$\\pm ") + G("v") + r"\$",
              lambda c: f1_window(c),
              "config/experiment.yaml (f1_excerpt_halfwidth_rows) + artefact prompt_budget.json "
              "(largest ladder rung with over_B = 0)",
              note="'the largest window we tested': the ladder is 5, 10, 15, 20, 25, 50, 100, so 11-14 were never "
                   "tried; the wording is now accurate"))
    add(Claim("SCO-01b", "pre-specified contracts / parameters (Appendix B)",
              r"docs/study_plan\},\s+pre-specified\s+" + W("a") + ws(" contracts and ") + W("b")
              + ws(" scenario parameters"),
              lambda c: prereg_scope(c), "from artefact 01_TECHNICAL_SPEC_v2.md (spec v2 change table and section 6.1)",
              groups=("a", "b")))
    add(Claim("SCO-02b", "contracts / parameters actually run (Section 3.3)",
              ws(r"we ran ") + W("a") + ws(" and ") + W("b") + ws(", a change made before"),
              lambda c: (len(c.json("data/results/falsification_summary.json")["active_contracts"]),
                         len(c.yaml("data/scenarios/space.yaml")["parameters"])),
              "recomputed: falsification_summary.json active_contracts, data/scenarios/space.yaml",
              groups=("a", "b")))
    add(Claim("FAL-04", "one parameter moves rho_1 and rho_2 in opposite directions",
              ws(r"because ") + W("v") + ws(r" parameter moves \$\\rhoc\{1\}\$ and \$\\rhoc\{2\}\$ in opposite directions"),
              NR("no results artefact: the per-contract correlations (+0.555 / -0.435 for headway) exist only in "
                 "docs/sensitivity_analysis.md, measured 24 Aug on a 4-parameter bank under an earlier program and "
                 "the pre-fix headway semantics; data/results/sensitivity.json stores overall-rho correlations "
                 "only. On the frozen baseline's own falsification traces (LOCAL, 203 traces, uniform plus "
                 "refinement samples) no parameter moves rho_1 and rho_2 in clearly opposite directions: headway "
                 "Spearman -0.34 / -0.47 (same sign); the only opposite-sign pair is lead_gap_s +0.16 / -0.21 "
                 "(re-checked 10 Oct with src/stl.py over the 203 fals_fals_* traces of program 59218be8676bd5e5)"),
              "none (documentation only)", only="v1.0"))
    add(Claim("FAL-05", "every admitted counterexample is actionable (avoidable)",
              r"(?P<v>actionable\s+\(a\s+violation-free\s+response\s+existed\))",
              lambda c: (all(x["avoidable"] and x["avoidable_strict"] for x in c.certs),
                         f"avoidable and avoidable_strict in {sum(1 for x in c.certs if x['avoidable'] and x['avoidable_strict'])}/{len(c.certs)}"),
              A_CERT, kind="bool"))

    # --------------------------------------------------------------- generation
    add(Claim("GEN-00b", "repair calls using claude-opus-5 at effort high",
              ws(r"All ") + G("v") + ws(r" repair calls use \\texttt{claude-opus-5} at effort \\texttt{high}"),
              model_served_all, A_ATT + " and logs/llm_index.jsonl"))
    add(Claim("GEN-01b", "max_tokens for the repair calls",
              ws(r"with \\texttt{max\\_tokens} \$=") + G("v") + ws(r"\$ and prompt caching"),
              lambda c: single(c, "max_tokens"), A_ATT,
              note="the sentence now opens 'All 300 repair calls'; the synthesis calls' 16,000 cap is stated in "
                   "Section 3.2 (BAS-10)"))
    add(Claim("GEN-07", "served = requested model identifier on all repair calls",
              ws(r"both were \\texttt{claude-opus-5} on all ") + G("v") + ws(" calls"),
              model_served_all, A_ATT))
    add(Claim("GEN-06b", "no response reached max_tokens",
              r"(?P<v>" + ws(r"and no response reached it") + r")", no_truncation, A_ATT, kind="bool"))

    # ------------------------------------------------------- results, uncertainty
    add(Claim("UNC-01", "same K counterexamples, replicates each",
              ws(r"run on the same ") + W("a") + ws(r" counterexamples, ") + W("b") + ws(" times each"),
              lambda c: (len(c.certs), len({a["seed"] for a in c.attempts})), A_ATT, groups=("a", "b")))
    add(Claim("UNC-02", "resamples / certificates drawn / attempts kept per certificate",
              ws(r"each of \$") + G("a") + ws(r"\$ resamples draws ") + W("b")
              + ws(r" counterexamples with replacement, keeps all ") + W("c") + ws(" attempts on each"),
              lambda c: (n_boot_both(c), c.boot.k, attempts_per_cert(c)),
              "recomputed: data/results/attempts.jsonl; N_BOOT = uncertainty.json n_boot", groups=("a", "b", "c")))
    add(Claim("UNC-05", "under Bonferroni over every computed difference only F1's structural contrasts survive",
              r"(?P<v>" + ws(r"under a Bonferroni correction over every difference we compute, only the "
                             r"structural-edit differences of F1 from each other condition still exclude zero") + r")",
              bonf22_only_f1_skel, A_BOOT_MULT, kind="bool"))

    # --------------------------------------------------------------- 4.1 edits
    add(Claim("PT-01b", "edit kind is the largest and most robust condition-dependent effect",
              r"(?P<v>" + ws(r"It is the largest and most robust condition-dependent effect we measure") + r")",
              lambda c: largest_effect_is_skeleton(c), A_BOOT, kind="bool"))
    add(Claim("PT-05b", "F1 structural-edit rate, %",
              ws(r"restructured the program in \$") + G("v") + r"\\%\$",
              lambda c: pct(skel(c, "F1"), 60), A_ATT))
    add(Claim("PT-06b", "F2 structural-edit rate, %",
              ws(r"and in \$") + G("v") + ws(r"\\%\$ under the natural-language summary"),
              lambda c: pct(skel(c, "F2"), 60), A_ATT))
    add(Claim("PT-13", "skeleton edits per condition F1..F4b / attempts per condition (Section 4.1)",
              ws(r"Skeleton edits numbered ") + G("a") + r",\s+" + G("b") + r",\s+" + G("c") + r",\s+" + G("d")
              + ws(" and ") + G("e") + ws(" of ") + G("n") + ws(" under F1 to F4b"),
              skel_counts_all, A_TAX + " (re-derived from source; equals the logged patch_type)",
              groups=("a", "b", "c", "d", "e", "n")))
    add(Claim("PT-02b", "F1 minus F2 structural-edit rate, points (Section 4.1)",
              ws(r"a difference of \$") + G("v") + ws(r"\$ points with"),
              lambda c: pct(skel(c, "F1") - skel(c, "F2"), 60), A_ATT, occurrence=1))
    add(Claim("PT-03b", "95% interval of F1 minus F2 structural-edit rate (Section 4.1)",
              ws(r"points with \$95\\%\$ interval \$\[") + G("a") + "," + G("b") + r"\]\$",
              lambda c: c.boot.diff("skeleton_edit", "F1", "F2")[1], A_BOOT_F12, groups=("a", "b"), occurrence=1))
    add(Claim("PT-08b", "95% interval, F4b minus F3 structural (includes zero)",
              ws(r"its interval against F3, \$\[") + G("a") + "," + G("b") + ws(r"\]\$, includes zero"),
              lambda c: (lambda ci: ci if ci_contains_zero(*ci) else f"excludes zero: {ci}")(
                  c.boot.diff("skeleton_edit", "F4b", "F3")[1]), A_BOOT, groups=("a", "b")))
    add(Claim("PT-11", "F4b sits between F1 and the other processed conditions",
              r"(?P<v>" + ws(r"F4b sits between the others") + r")",
              lambda c: (max(skel(c, x) for x in ("F2", "F3", "F4a")) < skel(c, "F4b") < skel(c, "F1"),
                         str({x: skel(c, x) for x in CONDS})), A_ATT, kind="bool"))
    add(Claim("PT-09b", "F1 most by far; F2, F3, F4a differ by at most",
              ws(r"the least processed condition produces by far the most structural edits, while F2, F3 and F4a, "
                 r"which add structure step by step, differ by at most ") + W("v"),
              lambda c: (MultiValue(max(skel(c, x) for x in ("F2", "F3", "F4a"))
                                    - min(skel(c, x) for x in ("F2", "F3", "F4a")),
                                    str({x: skel(c, x) for x in CONDS}))
                         if skel(c, "F1") == max(skel(c, x) for x in CONDS) else "F1 is not the maximum"),
              A_ATT))
    add(Claim("PT-12a", "F1 prompt is 'roughly 3.5 times as long'",
              ws(r"it is roughly ") + G("v") + ws(" times as long"),
              lambda c: MultiValue({x: median_prompt_tokens(c, "F1") / median_prompt_tokens(c, x)
                                    for x in CONDS if x != "F1"}, "F1 median / each other median"),
              A_ATT, kind="approx", tol=0.05,
              note="ratios 3.36 (F4a) to 3.57 (F2)"))
    add(Claim("PT-12b", "F1 median / range of the other medians, prompt tokens",
              ws(r"times as long \(\$") + G("a") + ws(r"\$ against \$") + G("b")
              + ws(r"\$ to \$") + G("c") + r"\$",
              lambda c: (median_prompt_tokens(c, "F1"),
                         min(median_prompt_tokens(c, x) for x in CONDS if x != "F1"),
                         max(median_prompt_tokens(c, x) for x in CONDS if x != "F1")),
              A_ATT, groups=("a", "b", "c")))
    add(Claim("PT-10b", "raw trace differs from every processed condition (structural), every CI excluding 0",
              r"(?P<v>" + ws(r"What this design can establish is that the raw-trace condition differs from every "
                             r"processed condition") + r")",
              lambda c: f1_differs_from_all(c), A_BOOT, kind="bool"))
    add(Claim("PT-10c", "range of F1-minus-processed structural-edit differences, points",
              ws(r"differs from every processed condition, by \$") + G("a") + ws(r"\$ to \$") + G("b")
              + ws(r"\$ points with every interval excluding zero"),
              f1_vs_processed_range, A_BOOT_PAIR,
              groups=("a", "b")))

    # ------------------------------------------------------------- 4.2 criteria
    add(Claim("CRT-02", "refusal mechanism: C2, C3 vacuous; rho falls through to rho_5, which every refusal passed",
              r"(?P<v>" + ws(r"and \$\\rho\$ falls through to \$\\rhoc\{5\}\$, which every such program passed") + r")",
              refusal_mechanism, A_ATT, kind="bool"))
    labels = {"F1": "F1", "F2": "F2", "F3": "F3", "F4a": "F4a", "F4b": "F4b", None: "All"}
    for cond, lab in labels.items():
        add(Claim(f"TAB4-{lab}", f"criteria table (printed Table 3) row {lab}: S, refused, entered, C, R, S&C, S&C&R",
                  r"(?:\n|\\\\)\s*" + lab + r"\s*&\s*(?P<a>\d+)\s*&\s*(?P<b>\d+)\s*&\s*(?P<c>\d+)\s*&\s*(?P<d>\d+)"
                  r"\s*&\s*(?P<e>\d+)\s*&\s*(?P<f>\d+)\s*&\s*(?P<g>\d+)\s*\\\\",
                  functools.partial(lambda c, cond: tab4_row(c, cond), cond=cond), A_ATT,
                  groups=("a", "b", "c", "d", "e", "f", "g")))
    add(Claim("TAB4-cap1", "criteria table (printed Table 3): counts out of N per condition",
              ws(r"counts out of ") + G("v") + ws(" per condition"),
              lambda c: single_val({len(c.by_cond(x)) for x in CONDS}), A_ATT))
    add(Claim("TAB4-cap2", "conflict-zone disc radius, m",
              ws(r"conflict zone, a ") + G("v") + r"\\,m\s+disc",
              lambda c: MultiValue(c.contracts_cfg["C2_yield"]["conflict_zone_radius_m"],
                                   "src/stl.rho_c2 uses a disc of this radius about the junction centre"),
              "recomputed: config/contracts.yaml (C2_yield.conflict_zone_radius_m)"))
    add(Claim("TAB4-cap3", "regression scenarios, all passed by the unpatched baseline",
              ws(r"none of the ") + G("v") + ws(r" regression scenarios, all passed by the unpatched baseline"),
              lambda c: regression_suite_n(c),
              "recomputed: data/scenarios/regression_suite.json and baseline_eval.json"))
    for occ, where in ((0, "Section 4.2"), (1, "Conclusion")):
        add(Claim(f"CRT-03{'ab'[occ]}", f"criteria applied in turn select S, S&C, S&C&R of N ({where})",
                  ws(r"select ") + G("a") + ws(", then ") + G("b") + ws(", then ") + G("c") + ws(" of ") + G("d")
                  + ws(" attempts"),
                  lambda c: (tab4_row(c, None)[0], tab4_row(c, None)[5], tab4_row(c, None)[6], len(c.attempts)),
                  A_ATT, groups=("a", "b", "c", "d"), occurrence=occ))
    add(Claim("CRT-04", "refusals of the satisfied, and their share",
              W("a") + ws(r" of the ") + G("b") + ws(r" that satisfied the contracts, \$") + G("c") + r"\\%\$",
              lambda c: (tab4_row(c, None)[1], tab4_row(c, None)[0], pct(tab4_row(c, None)[1], tab4_row(c, None)[0])),
              A_ATT, groups=("a", "b", "c")))
    add(Claim("CRT-05", "entered but had not completed when the episode ended",
              ws(r"conflict zone; ") + W("v") + ws(r" more entered but had not completed the turn when the episode "
                                                  r"ended"),
              entered_not_completed, A_ATT))
    add(Claim("VAC-01", "satisfied the contracts by making them inapplicable (refusals) / satisfied",
              ws(r"on this corpus ") + G("a") + ws(r" of the ") + G("b") + ws(r" that satisfied them did"),
              lambda c: (tab4_row(c, None)[1], tab4_row(c, None)[0]), A_ATT, groups=("a", "b")))
    add(Claim("CRT-11", "unpatched baseline's suite completion, %",
              ws(r"against \$") + G("v") + ws(r"\\%\$ for the unpatched baseline"),
              baseline_suite_icr, "recomputed: data/results/baseline_eval.json (icr)"))
    add(Claim("CRT-06", "completed / of those, regression-intact",
              W("a") + ws(r" completed it, and of those ") + W("b") + ws(" only ") + W("c")
              + ws(" also left the regression suite intact"),
              lambda c: (tab4_row(c, None)[5], tab4_row(c, None)[5], tab4_row(c, None)[6]), A_ATT,
              groups=("a", "b", "c")))
    add(Claim("CRT-07", "a program completing none of the suite yet causing no regression failure",
              W("a") + ws(r" patched program completed ") + W("b") + ws(r" of the ") + G("c")
              + ws(r" suite scenarios and caused no regression failure"),
              r_passes_refusal, A_ATT + " (icr, regression_failures)", groups=("a", "b", "c")))
    add(Claim("CRT-08", "completions inherited from the baseline / all completions / baseline-completed CEs",
              G("a") + ws(r" of its ") + G("b") + ws(r" successes are on the ") + W("c")
              + ws(r" counterexamples the unpatched baseline already completed"),
              c_inherited, A_ATT + " and data/results/baseline_eval.json", groups=("a", "b", "c")))
    add(Claim("CRT-09", "other refusals / their suite completion range, %",
              ws(r"the other ") + W("a") + ws(r" refusals completed \$") + G("b") + ws(r"\$ to \$") + G("c") + r"\\%\$",
              other_refusals_icr, A_ATT + " (icr over the 60 suite scenarios)", groups=("a", "b", "c")))

    # ------------------------------------------------------------------- 4.3
    add(Claim("DSL-T2d", "'raise gap thresholds': more than one threshold raised",
              r"(?P<v>" + ws(r"raise gap thresholds") + r")",
              lambda c: (sum(1 for x, y in zip(gap_thresholds(c, "data/scenarios/baseline_program.bt"),
                                               gap_thresholds(c, "data/scenarios/dsl_probe/fixA_bigger_gap.bt"))
                             if y > x) >= 2,
                         f"{gap_thresholds(c, 'data/scenarios/baseline_program.bt')} -> "
                         f"{gap_thresholds(c, 'data/scenarios/dsl_probe/fixA_bigger_gap.bt')}"),
              "recomputed: baseline_program.bt vs dsl_probe/fixA_bigger_gap.bt", kind="bool"))
    add(Claim("DSL-capb", "each row a valid program, run on all K counterexamples",
              ws(r"Each row is a valid program, or a family of them, in the same DSL run on all ") + W("v")
              + ws(" counterexamples"),
              lambda c: probes_valid(c), "recomputed: src/program_parser.parse_and_validate on every probe .bt; "
              "K from data/certificates"))
    add(Claim("DSL-C1b", "clean repair: one attempt in 300, under F1",
              W("a") + ws(r" attempt in ") + G("b") + ws(r", under the raw-trace condition F1"),
              lambda c: clean_under_f1(c), A_ATT, groups=("a", "b")))
    add(Claim("DSL-C5", "a single success in N attempts",
              ws(r"a single success in ") + G("v") + ws(" attempts"),
              lambda c: len(c.attempts) if c.count(is_clean) == 1 else f"{c.count(is_clean)} clean", A_ATT))
    add(Claim("DSL-V2b", "clean repair repeated on its own counterexample (expressiveness table caption)",
              W("v") + ws(r" repeats on its own counterexample reproduced"),
              clean_repeats_n, A_REPEATS))
    add(Claim("DSL-V3b", "rho and rho_4 reproduced with zero spread",
              r"(?P<v>" + ws(r"reproduced \$\\rho\$ and \$\\rhoc\{4\}\$ with zero spread") + r")",
              lambda c: clean_rss(c), A_REPEATS, kind="bool"))
    add(Claim("DSL-M8b", "true stop: resolves all K, completes none",
              ws(r"Adding a true stop to the geometric guard resolves all ") + W("a")
              + ws(r" counterexamples and completes ") + W("b"),
              lambda c: probe_cells(c, "truestop", ("fixed", "completed"),
                                    art_dsl("true stop", "fixed", "completed"), with_n=False),
              A_PROBE + " (geometric_guard_true_stop/); artefact data/results/dsl_expressiveness.json must agree",
              groups=("a", "b")))
    add(Claim("DSL-P1", "clean repair: path check added to the committing branch, m",
              ws(r"Its patch adds a ") + G("v") + r"\\,m\s+path\s+check\s+to\s+the\s+committing\s+branch",
              clean_patch_commit, "recomputed: baseline_program.bt vs the clean attempt's bt_source_after "
              "(= data/results/patched_programs/F1__CE005_C1_5b773c94ec4bb251__s3.bt), parsed with src/program_parser.py"))
    add(Claim("DSL-P2", "clean repair: number of stop-line path checks lengthened / new length, m",
              ws(r"lengthens the ") + W("n") + ws(r" path checks at the stop line to ") + G("v") + r"\\,m",
              clean_patch_stopline, "recomputed: as DSL-P1", groups=("n", "v")))
    add(Claim("DSL-P3", "clean repair: fallback deceleration after / before, m/s^2",
              ws(r"brakes the fallback harder \(") + G("a") + ws(r" against ") + G("b") + r"\\,m/s",
              clean_patch_fallback, "recomputed: as DSL-P1", groups=("a", "b")))
    add(Claim("DSL-P4", "clean repair: fallback still creeps, and the patch changes nothing else",
              r"(?P<v>" + ws(r"while leaving it able to creep") + r")",
              clean_patch_creep, "recomputed: as DSL-P1", kind="bool"))
    add(Claim("DSL-P5", "hand-written path checks on the committing branch: shortest / longest, m; fixed of K",
              ws(r"hand-written path checks on the same branch \(") + G("a") + ws(" to ") + G("b")
              + ws(r"\\,m, fallback unchanged\) fixed ") + W("c") + ws(r" of the ") + W("d"),
              geometric_family,
              "recomputed: the committed programs of every data/dsl_probe_traces/geometric_guard/ variant, parsed "
              "with src/program_parser.py, and their trajectories re-scored with src/stl.py; artefact "
              "dsl_expressiveness.json ('add PathIsClear to branch C, 16/24/32 m', 0/20) must agree",
              groups=("a", "b", "c", "d")))

    # ------------------------------------------------------------------- 4.4
    add(Claim("FIG2-02", "intervals ending exactly at zero belong to conditions with no successes",
              r"(?P<v>" + ws(r"an interval ending exactly at zero, where a condition has no successes, does not") + r")",
              zero_endpoint_only_zero_successes, A_BOOT, kind="bool"))
    add(Claim("FIG2-03", "repeated attempts per cell (figure caption)",
              ws(r"the ") + W("v") + ws(r" repeated attempts per cell"),
              lambda c: len({a["seed"] for a in c.attempts}), A_ATT))
    add(Claim("NUL-01b", "no reliable ex-refusal improvement from any condition",
              r"(?P<v>" + ws(r"we did not detect a reliable improvement in repair success from any feedback "
                             r"condition") + r")",
              ex_refusal_vs_f3_all_contain_zero, A_BOOT, kind="bool"))
    add(Claim("NUL-03b", "F1 refusals / F1 resolutions",
              ws(r"but ") + G("a") + ws(r" of its ") + G("b") + ws(r" resolved attempts are refusals"),
              lambda c: (c.count(lambda a: a["resolved_by_refusal"], "F1"), c.count(lambda a: a["resolved"], "F1")),
              A_ATT, groups=("a", "b")))
    add(Claim("NUL-01c", "every ex-refusal comparison against F3 contains zero",
              r"(?P<v>" + ws(r"Every paired comparison against F3 has an interval containing zero") + r")",
              ex_refusal_vs_f3_all_contain_zero, A_BOOT, kind="bool"))
    add(Claim("NUL-08", "F2, F4a, F4b: no ex-refusal successes, upper endpoint exactly zero",
              r"(?P<v>" + ws(r"for F2, F4a and F4b, which have no such successes, zero is the upper endpoint") + r")",
              zero_upper_for_zero_success, A_BOOT, kind="bool"))
    add(Claim("MDE-01", "F3 rate / power / MDE range (Section 4.4)",
              ws(r"an improvement over F3's \$") + G("p") + ws(r"\\%\$ is detected with probability \$") + G("w")
              + ws(r"\$ only once it reaches \$") + G("a") + ws(r"\$ to \$") + G("b") + r"\$",
              mde_main, A_DE + "; F3 rate recomputed from attempts.jsonl", groups=("p", "w", "a", "b")))
    add(Claim("MDE-02", "an improvement of 5 points is detected at most a quarter of the time",
              r"(?P<v>" + ws(r"and one of \$5\$ points at most a quarter of the time") + r")",
              power_at5_quarter, A_DE, kind="bool"))

    # ------------------------------------------------------------------- 4.5
    add(Claim("REG-11", "F4a minus F3, broke >= 1 regression: point and 95% interval",
              ws(r"more often than F3, by \$") + G("p") + ws(r"\$ points \$\[") + G("a") + "," + G("b") + r"\]\$",
              lambda c: (c.boot.diff("regression", "F4a", "F3")[0], *c.boot.diff("regression", "F4a", "F3")[1]),
              A_BOOT, groups=("p", "a", "b")))
    add(Claim("REG-03b", "attempts that satisfied the contracts (Section 4.5)",
              ws(r"regression scenario to fail, against ") + G("v") + ws(r" that satisfied the contracts"),
              lambda c: c.count(lambda a: a["resolved"]), A_ATT))
    add(Claim("REG-12", "the F4a regression contrast does not survive Bonferroni",
              r"(?P<v>" + ws(r"this one does not survive the Bonferroni correction") + r")",
              f4a_reg_bonf_contains_zero, A_BOOT_MULT, kind="bool"))
    add(Claim("REG-13", "besides the F1 contrasts, exactly one interval (F4a regression) excludes zero unadjusted",
              r"(?P<v>" + ws(r"Besides the F1 contrasts, one other interval excludes zero without adjustment") + r")",
              unadj_and_bonf_sets, A_BOOT_MULT, kind="bool"))
    add(Claim("REG-14", "unadjusted intervals / expected chance exclusions ('about one')",
              ws(r"Among ") + G("n") + ws(r" unadjusted intervals about ") + W("e") + ws(" would exclude zero by chance"),
              about_one_by_chance, "recomputed: 22 distinct contrasts x 0.05", groups=("n", "e"), kind="approx_abs", tol=0.5,
              note="'about one': 1.1 checked to within 0.5"))
    add(Claim("REG-05b", "mean rho_5 on the counterexample before the patch",
              ws(r"falls in every condition, from \$") + G("v") + r"\$",
              rho5_before_all, A_ATT + " (rho5_before)"))
    add(Claim("REG-07b", "mean rho_5 on the counterexample falls in every condition",
              r"(?P<v>" + ws(r"mean \$\\rhoc\{5\}\$ on the counterexample falls in every condition") + r")",
              rho5_falls_everywhere, A_ATT + " (rho5_before, rho5_after)", kind="bool"))

    # ------------------------------------------------------------------- 4.6
    add(Claim("BLM-03b", "contracts each blaming one node / resulting H(node | contract)",
              ws(r"we verified by construction that ") + W("k") + ws(r" contracts each blaming one node still give ")
              + W("h"),
              lambda c: by_construction_zero(c), "recomputed by construction with src/blame.conditional_entropy",
              groups=("k", "h"),
              note="no unit test under tests/ asserts this; it is checked here by construction"))

    # ----------------------------------------------------- limitations, impact
    add(Claim("LIM-06", "one model, one repair step",
              r"(?P<a>one)\s+model\s+\(\\texttt\{claude-opus-5\}\)\s+and\s+(?P<b>one)\s+repair\s+step",
              lambda c: (len({a["model_id"] for a in c.attempts}), one_step(c)), A_ATT, groups=("a", "b")))
    add(Claim("LIM-07", "corpus construction amortized across all conditions",
              ws(r"amortized across all ") + W("v") + ws(" conditions"),
              lambda c: len({a["condition"] for a in c.attempts}), A_ATT))
    add(Claim("BI-01", "patches broke previously passing scenarios in three quarters of attempts",
              r"(?P<v>" + ws(r"broke previously passing scenarios in three quarters of attempts") + r")",
              lambda c: (abs(Fraction(c.count(lambda a: (a["regression_failures"] or 0) >= 1), len(c.attempts))
                             - Fraction(3, 4)) <= Fraction(1, 100),
                         f"{c.count(lambda a: (a['regression_failures'] or 0) >= 1)}/{len(c.attempts)} = 74.7%"),
              A_ATT, kind="bool"))
    add(Claim("CON-C3", "conclusion: no condition detected improving repair success",
              r"(?P<v>" + ws(r"Excluding refusals, we detected no condition improving repair success") + r")",
              ex_refusal_vs_f3_all_contain_zero, A_BOOT, kind="bool",
              note="true of success excluding refusals; the pre-specified F1-F3 interval excludes zero (refusals)"))

    # ------------------------------------------------------------- Appendix A
    add(Claim("APA-01", "F1 excerpt: rows x columns",
              ws(r"raw trajectory, ") + G("a") + ws(r" rows \$\\times\$ ") + G("b") + ws(" columns around the violation"),
              f1_window_dims, "recomputed: F1 feedback regenerated for all 20 certificates "
              "(data/certificates/traces/), the 60 F1 prompts in logs/campaign/prompts/ and the committed CE003 copy; "
              "config f1_excerpt_halfwidth_rows", groups=("a", "b")))
    add(Claim("APA-02", "certificates with a rendered boundary / K",
              ws(r"boundary of the failing region \(") + G("a") + ws(" of ") + G("b") + ws(r" certificates\)"),
              with_boundary, A_CERT, groups=("a", "b")))
    add(Claim("APA-04", "scaffolding tokens shared by every prompt",
              ws(r"Median prompt length minus the \$") + G("v") + ws(r"\$ tokens of scaffolding"),
              scaffold_tokens, "from artefact data/results/prompt_budget.json (scaffolding_tokens, count_tokens API)"))
    add(Claim("APA-05", "feedback block, median tokens, F1..F4b (= median prompt minus scaffolding)",
              ws(r"feedback block, median tokens\$\^\{\*\}\$") + T + r"\$" + G("a") + r"\$" + T + r"\$" + G("b")
              + r"\$" + T + r"\$" + G("c") + r"\$" + T + r"\$" + G("d") + r"\$" + T + r"\$" + G("e") + r"\$",
              feedback_block_tokens, A_ATT + " (median of tokens_prompt + cache_read + cache_write) minus artefact "
              "prompt_budget.json scaffolding_tokens", groups=("a", "b", "c", "d", "e")))
    add(Claim("APA-03", "rows back to the F4b transition, and the F1 window length",
              ws(r"lies ") + G("a") + ws(" to ") + G("b") + ws(r" rows before the violation, outside F1's ") + G("c")
              + r"-row",
              outside_window, "from artefact data/results/prompt_budget.json + config/experiment.yaml",
              groups=("a", "b", "c")))

    # ------------------------------------------------------------- Appendix B
    add(Claim("APB-01", "planned parameters; one dropped (pedestrian offset), three added",
              ws(r"Of the ") + W("v") + ws(r" planned parameters, the pedestrian-phase offset was dropped"),
              prereg_dropped_added, "recomputed: 01_TECHNICAL_SPEC_v2.md section 6.1 vs data/scenarios/space.yaml"))
    add(Claim("APB-02", "without aggressiveness only one parameter carried signal",
              ws(r"without it only ") + W("v") + ws(r" parameter carried signal"),
              aggressiveness_reason, "from documentation data/scenarios/space.yaml (aggressiveness.justification, "
              "24 Aug); the measurement is in docs/sensitivity_analysis.md, not in a results file"))
    add(Claim("APB-03", "three-contract reference program: contract determined the blamed leaf exactly",
              ws(r"on the reference program under ") + W("v")
              + ws(r" contracts, the violated contract determined the blamed leaf exactly"),
              NR("documentation only: config/contracts.yaml comments and docs/ (C2 -> HoldAtStopLine 90/90, "
                 "C1 -> CommitTurn 11/11); no results artefact records the three-contract blame distribution"),
              "none (documentation only)"))

    # ------------------------------------------------------------- Appendix C
    add(Claim("TAXC-01", "hole fills / skeleton edits (and no no-change or unparseable)",
              ws(r"There were ") + G("a") + ws(r" hole fills, ") + G("b")
              + ws(r" skeleton edits, and no no-change or unparseable outputs"),
              tax_counts, A_TAX, groups=("a", "b")))
    add(Claim("TAXC-02", "every skeleton edit increased the number of nodes",
              r"(?P<v>" + ws(r"Every skeleton edit increased the number of nodes") + r")", tax_grew, A_TAX, kind="bool"))
    add(Claim("TAXC-03", "hole fills changing an action parameter / only predicate thresholds",
              ws(r"Of the hole fills, ") + G("a") + ws(r" changed at least one action parameter, such as a target "
                                                    r"speed, and ") + G("b")
              + ws(r" changed only predicate thresholds"),
              tax_hole_kinds, A_TAX + " and src/bt_vocabulary.py node kinds", groups=("a", "b")))
    add(Claim("TAXC-04", "median TED: hole fills / skeleton edits",
              ws(r"median tree edit distance is ") + G("a") + ws(r" against ") + G("b") + ws(" for skeleton edits"),
              tax_medians, A_TAX, groups=("a", "b")))
    add(Claim("TAXC-05", "mean TED per patch, F1 to F4b",
              ws(r"Mean tree edit distance per patch was ") + G("a") + r",\s+" + G("b") + r",\s+" + G("c") + r",\s+"
              + G("d") + ws(" and ") + G("e") + ws(" for F1 to F4b"),
              lambda c: tuple(mean_ted(c, x) for x in CONDS),
              "recomputed: TED re-derived from bt_source_before/after with src/ted.py",
              groups=("a", "b", "c", "d", "e")))
    add(Claim("TAXC-06", "mean regression failures: skeleton edits / hole fills",
              ws(r"Skeleton edits averaged ") + G("a") + ws(r" regression failures against ") + G("b")
              + ws(" for hole fills"),
              tax_reg_means, A_TAX + " and regression_failures", groups=("a", "b")))
    add(Claim("TAXC-07", "re-running the classifier reproduces all labels",
              ws(r"reproduces all ") + G("v") + ws(" labels"), tax_reproduces, A_TAX))
    add(Claim("TAXC-08", "classifier unit tested, committed before the campaign, campaign ran from it, unchanged",
              r"(?P<v>" + ws(r"The classifier was unit tested and committed before the campaign, which ran from that "
                             r"commit; apart from comments, it has not changed since") + r")",
              classifier_provenance, "recomputed: git history (git log, git diff) and attempts.jsonl git_commit",
              kind="bool"))
    add(Claim("TAXC-09", "categories were in the design specification before any repair attempt",
              r"(?P<v>" + ws(r"were in the design specification before any repair attempt") + r")",
              taxonomy_predefined, "recomputed: git history of 01_TECHNICAL_SPEC*.md (git log -S)", kind="bool"))
    add(Claim("FIG3-cap2", "under a natural-language summary the model mostly changed parameter values",
              r"(?P<v>" + ws(r"natural-language summary it mostly changed parameter values") + r")",
              lambda c: (lambda n: (n > len(c.by_cond("F2")) / 2, f"F2: {n} of {len(c.by_cond('F2'))} hole fills"))(
                  sum(1 for a in c.by_cond("F2") if a["patch_type"] == "hole_fill")),
              A_TAX, kind="bool"))

    # ------------------------------------------------------------- Appendix D
    add(Claim("APD-01", "K / replicates / conditions / attempts per certificate",
              ws(r"There are \$K=") + G("a") + ws(r"\$, each attempted ") + W("b") + ws(r" times under each of the ")
              + W("c") + ws(r" conditions, so every certificate carries ") + G("d") + ws(" attempts"),
              lambda c: (len(c.certs), len({a["seed"] for a in c.attempts}), len(CONDS), attempts_per_cert(c)),
              A_ATT, groups=("a", "b", "c", "d")))
    add(Claim("APD-02", "resamples / certificates drawn",
              ws(r"Each of \$") + G("a") + ws(r"\$ resamples draws ") + G("b") + ws(" certificates uniformly"),
              lambda c: (n_boot_both(c), c.boot.k), A_BOOT, groups=("a", "b")))
    add(Claim("APD-02b", "number of bootstrap differences the percentiles are taken over",
              ws(r"percentile of the \$") + G("v") + ws(r"\$ differences"),
              n_boot_both, "recomputed: uncertainty.json n_boot = N_BOOT"))
    add(Claim("APD-12", "F1-F4a and F1-F4b structural edits: point and 95% interval",
              ws(r"F1 also differs from F4a and F4b on structural edits, by \$") + G("p1") + r"\$\s*\$\[" + G("l1")
              + "," + G("h1") + ws(r"\]\$ and \$") + G("p2") + r"\$\s*\$\[" + G("l2") + "," + G("h2") + r"\]\$",
              lambda c: (*ab_skel_diff(c, "F1", "F4a"), *ab_skel_diff(c, "F1", "F4b")), A_BOOT_PAIR,
              groups=("p1", "l1", "h1", "p2", "l2", "h2")))
    add(Claim("APD-13", "further pairs / distinct differences / Bonferroni family / F1 survivors",
              ws(r"Counting the ") + W("p") + ws(r" further structural-edit pairs, we computed ") + G("n")
              + ws(r" distinct differences; under a Bonferroni correction over all ") + G("m")
              + ws(r", exactly the ") + W("k") + ws(r" F1 structural-edit contrasts exclude zero"),
              bonf22_counts, A_BOOT_MULT + " (recomputed at 0.05/22)", groups=("p", "n", "m", "k")))
    add(Claim("TAB6-cap0", "Table 6 caption: number of tabulated differences",
              ws(r"\\caption\{The ") + G("v") + ws(r" tabulated paired differences"),
              n_contrasts, "registry of the 17 tabulated contrasts"))
    add(Claim("REF-01b", "baseline entered the conflict zone on every counterexample (Figure 2 caption)",
              ws(r"The unpatched baseline entered it on all ") + W("v") + ws(r" counterexamples"),
              lambda c: (lambda e, n: e if e == n else f"{e} of {n} entered")(
                  sum(1 for v in c.baseline_eval.values() if v["ce_entered_conflict_zone"]), len(c.baseline_eval)),
              "from artefact data/results/baseline_eval.json (CARLA run of the frozen baseline)"))
    add(Claim("FIG2-cap", "Figure 2 caption: refusals / resolutions",
              ws(r"one clean repair: ") + W("a") + ws(r" of the ") + W("b") + ws(r" that satisfied the contracts never entered"),
              lambda c: (c.count(lambda a: a["resolved_by_refusal"]), c.count(lambda a: a["resolved"])),
              A_ATT, groups=("a", "b")))
    add(Claim("APD-14", "F1-F2 is the largest of the ten pairwise structural-edit differences",
              r"(?P<v>" + ws(r"is the largest of the ten pairwise structural-edit differences") + r")",
              f1f2_largest_bool, A_BOOT_PAIR, kind="bool"))
    add(Claim("APD-15", "number of pairwise structural-edit differences",
              ws(r"is the largest of the ") + W("v") + ws(r" pairwise structural-edit differences"),
              f1f2_n_pairs, "recomputed: C(5, 2) over the five conditions"))
    add(Claim("APD-03", "per-condition denominator in every resample",
              ws(r"the denominator is always ") + G("v"), denominators_always, A_BOOT))
    add(Claim("APD-04", "percentiles of the interval",
              ws(r"runs from the \$") + G("a") + ws(r"\$th to the \$") + G("b") + ws(r"\$th percentile"),
              uncert_percentiles, "recomputed: scripts/uncertainty.py source (ci)", groups=("a", "b")))
    add(Claim("APD-05", "bootstrap seed (NumPy PCG64)",
              ws(r"NumPy PCG64, seed ") + G("v"), uncert_seed, "recomputed: scripts/uncertainty.py source, numpy"))
    add(Claim("APD-06", "equivalent form: K certificate-level differences 100 (s_a - s_b) / 3",
              ws(r"mean of the ") + G("a") + ws(r" certificate-level differences \$") + G("p")
              + r"\\,\(s_\{i,a\}-s_\{i,b\}\)/" + G("r") + r"\$",
              cert_level_formula, A_BOOT + "; equivalence checked numerically over every resample",
              groups=("a", "p", "r")))
    add(Claim("APD-07", "paired differences computed / outcomes",
              ws(r"We tabulate ") + G("a") + ws(r" paired differences: each condition against F3 on ") + W("b")
              + ws(" outcomes"),
              lambda c: (n_contrasts(c).value if isinstance(n_contrasts(c), MultiValue) else n_contrasts(c),
                         len({m for m, _, _ in CONTRASTS17})),
              "recomputed: registry of contrasts; equals uncertainty.json multiplicity", groups=("a", "b")))
    add(Claim("APD-08", "Bonferroni family size",
              ws(r"Bonferroni adjustment over these ") + G("v"), n_contrasts, "registry of the 17 tabulated contrasts"))
    add(Claim("APD-09", "Bonferroni survivors (F1-F2, F1-F3 structural) and casualties (F1-F3 success, F4a-F3 regression)",
              r"(?P<v>" + ws(r"the structural-edit differences of F1 from F2 and from F3 still exclude zero; the two "
                             r"others that exclude zero unadjusted, F1 against F3 on pre-specified success and F4a "
                             r"against F3 on regressions, do not") + r")",
              unadj_and_bonf_sets, A_BOOT_MULT, kind="bool"))
    add(Claim("APD-10", "clusters (Limits paragraph)",
              ws(r"With ") + G("v") + ws(" clusters, percentile intervals"), lambda c: c.boot.k, A_BOOT))
    add(Claim("APD-11", "successes per condition under the joint criteria: min / max",
              ws(r"with ") + W("a") + ws(" to ") + W("b") + ws(r" successes per condition, we report counts"),
              lambda c: (min(min(tab4_row(c, x)[5], tab4_row(c, x)[6]) for x in CONDS),
                         max(max(tab4_row(c, x)[5], tab4_row(c, x)[6]) for x in CONDS)),
              A_ATT + " (S&C and S&C&R per condition)", groups=("a", "b")))
    for m, a, b in CONTRASTS17:
        lab = METRIC_LABEL[m]
        pat = (r"(?:\n|\\\\|\\addlinespace)\s*" + re.escape(lab) + r"(?:(?!\\addlinespace)[\s\S])*?&\s*" + a + r"\$-\$" + b + r"\s*&\s*\$" + G("p")
               + r"\$\s*&\s*\$\[" + G("lo") + "," + G("hi") + r"\]\$\s*&\s*\$\[" + G("blo") + "," + G("bhi") + r"\]\$")
        add(Claim(f"TAB6-{m}-{a}{b}", f"Table 6: {m} {a}-{b}: diff, 95% CI, Bonferroni CI",
                  pat, functools.partial(lambda c, m, a, b: allci_row(c, m, a, b), m=m, a=a, b=b),
                  A_BOOT_MULT, groups=("p", "lo", "hi", "blo", "bhi")))
    add(Claim("TAB6-hdr", "Table 6 header: Bonferroni family size",
              r"Bonferroni\s+\(\$\\times\s+" + G("v") + r"\$\)", n_contrasts, "as UNC-03"))
    add(Claim("TAB6-cap1", "Table 6 caption: resamples / seed",
              ws(r"from one set of \$") + G("a") + ws(r"\$ certificate resamples \(seed ") + G("b"),
              lambda c: (n_boot_both(c), uncert_seed(c).value if isinstance(uncert_seed(c), MultiValue) else -1),
              "recomputed: uncertainty.json n_boot; scripts/uncertainty.py seed", groups=("a", "b")))
    add(Claim("TAB6-cap2", "Table 6 caption: Bonferroni alpha = 0.05 / 17",
              ws(r"Bonferroni intervals use ") + r"\$\\alpha\s*=\s*" + G("a") + "/" + G("b") + r"\$", bonf_alpha,
              "recomputed: registry; equals uncertainty.json multiplicity.bonferroni_alpha", groups=("a", "b")))

    # ------------------------------------------------------------- Appendix E
    add(Claim("APE-01", "each rate is out of N attempts",
              ws(r"so each rate is out of \$") + G("v") + r"\$",
              lambda c: single_val({len(c.by_cond(x)) for x in CONDS}), A_ATT))
    add(Claim("APE-03", "per-certificate differences / literal B / literal-vs-exact agreement",
              ws(r"depends only on the ") + W("a")
              + ws(r" per-certificate differences, so we computed it exactly rather than from \$") + G("b")
              + ws(r"\$ resamples; the two agreed on \$") + G("c") + ws(r"\$ of \$") + G("d") + r"\$",
              literal_vs_exact, A_DE + " (validation.literal_vs_exact_on_simulated)", groups=("a", "b", "c", "d")))
    add(Claim("APE-04", "ICC values simulated",
              r"outcomes\s+in\s+\$\\\{" + G("a") + r",\s*" + G("b") + r",\s*" + G("c") + r"\\\}\$",
              icc_grid, A_DE, groups=("a", "b", "c")))
    add(Claim("APE-05", "target detection probability",
              ws(r"gives the smallest \$d\$ detected with probability \$") + G("v") + r"\$", target_power, A_DE))
    add(Claim("APE-06", "closed forms at 60 per arm: arcsine / Fisher exact MDE at p0",
              ws(r"calculation for \$") + G("n") + ws(r"\$ attempts per arm gives \$") + G("a")
              + ws(r"\$ points \(arcsine approximation\) to \$") + G("b")
              + ws(r"\$ points \(Fisher's exact test\) at \$p_0=") + G("p") + r"\\%\$",
              closed_forms, "recomputed: closed forms (statistics.NormalDist; scipy.stats.fisher_exact); equal to "
              "detectable_effect.json closed_form_no_clustering", groups=("n", "a", "b", "p")))
    add(Claim("APE-07", "minimum certificates favouring a condition before the interval can exclude zero",
              ws(r"cannot exclude zero unless at least ") + W("a") + ws(r" of the ") + W("b") + ws(" certificates favour"),
              min_certs_to_exclude, "recomputed: arithmetic on the resampling rule; equals detectable_effect.json "
              "decision_table", groups=("a", "b")))
    add(Claim("APE-08", "F3 successful on at most N certificates under S, S excl. refusals, S with C",
              ws(r"with F3 successful on at most ") + W("v") + ws(r" certificates under each repair-success outcome "
                                                                  r"\(S, S excluding refusals, and S with C\)"),
              f3_success_certs_named, A_ATT))
    add(Claim("APE-11", "p0 / improvement / power range at +5 points over the Table 7 settings",
              ws(r"At \$p_0=") + G("p") + ws(r"\\%\$, a true improvement of \$") + G("d")
              + ws(r"\$ points is detected with probability \$") + G("a") + ws(r"\$ to \$") + G("b")
              + ws(r"\$ across these settings"),
              power_at_5_range, A_DE + " (power_at.5pp.power); F3 rate recomputed from attempts.jsonl",
              groups=("p", "d", "a", "b")))
    add(Claim("APE-09", "Bonferroni raises each MDE entry by about (x4) and (x17)",
              ws(r"over the ") + W("n4") + ws(r" comparisons against F3 raises each entry by about \$") + G("a")
              + ws(r"\$ to \$") + G("b") + ws(r"\$ points, and over all ") + G("n17")
              + ws(r" comparisons by about \$") + G("c") + ws(r"\$ to \$") + G("d") + r"\$",
              bonf_increments, A_DE, groups=("n4", "a", "b", "n17", "c", "d"), kind="approx_abs", tol=0.5,
              note="'about': each endpoint checked to within 0.5 points"))
    add(Claim("APE-10", "ex-refusal successes / max per cell / distinct certificates",
              ws(r"the ") + W("a") + ws(r" successes excluding refusals fell ") + W("b") + ws(r" per cell and on ")
              + W("c") + ws(" different certificates"),
              exref_pattern, A_ATT, groups=("a", "b", "c")))
    add(Claim("TAB7-hdr", "Table 7 header: the two p0 values, %",
              r"\\multicolumn\{2\}\{c\}\{\$p_0\s*=\s*" + G("a") + r"\\%\$\}\s*&\s*\\multicolumn\{2\}\{c\}\{\$p_0\s*=\s*"
              + G("b") + r"\\%\$\}",
              tab7_p0s, A_DE + " (simulated p0 = 1/30 and 0.05)", groups=("a", "b")))
    add(Claim("TAB7-icc0", "Table 7 row ICC 0: MDE at p0 3.3% / 5.0%",
              r"\$" + r"(?P<i>0)" + r"\$\s*&\s*\\multicolumn\{2\}\{c\}\{\$" + G("a")
              + r"\$\}\s*&\s*\\multicolumn\{2\}\{c\}\{\$" + G("b") + r"\$\}",
              lambda c: tab7_entry(c, 0, "zero"), A_DE + " (mde_80.mde_pp_interp, rounded half-up)",
              groups=("i", "a", "b")))
    for icc in ("0.1", "0.3"):
        add(Claim(f"TAB7-icc{icc}", f"Table 7 row ICC {icc}: shared / independent at p0 3.3%, then 5.0%",
                  r"\$(?P<i>" + re.escape(icc) + r")\$\s*&\s*\$" + G("a") + r"\$\s*&\s*\$" + G("b") + r"\$\s*&\s*\$"
                  + G("c") + r"\$\s*&\s*\$" + G("d") + r"\$\s*\\\\",
                  functools.partial(lambda c, icc: tab7_entry(c, float(icc), "pair"), icc=icc),
                  A_DE + " (mde_80.mde_pp_interp, rounded half-up)", groups=("i", "a", "b", "c", "d")))
    add(Claim("TAB7-cap1", "Table 7 caption: detection probability",
              ws(r"detected with probability \$") + G("v") + ws(r"\$ by the paired cluster bootstrap"),
              target_power, A_DE))
    add(Claim("TAB7-cap2", "Table 7 caption: certificates / replicates",
              ws(r"by the paired cluster bootstrap over ") + W("a") + ws(r" certificates and ") + W("b")
              + ws(" replicates"),
              lambda c: (len(c.certs), len({a["seed"] for a in c.attempts})), A_ATT, groups=("a", "b")))
    add(Claim("TAB7-cap3", "Table 7 caption: F3 rate excluding refusals (= S and C jointly) / F3 rate on S",
              ws(r"\$p_0=") + G("a") + ws(r"\\%\$ is F3's observed rate both excluding refusals and for S and C "
                                         r"jointly; \$") + G("b") + ws(r"\\%\$ is its rate on the pre-specified "
                                                                      r"criterion S"),
              tab7_caption_rates, A_ATT, groups=("a", "b")))
    add(Claim("TAB7-cap4", "Table 7 caption: simulated experiments per setting",
              ws(r"Each setting used \$") + G("v") + ws(r"\$ simulated experiments"), n_sim_all, A_DE))
    add(Claim("TAB7-cap5", "Table 7 caption: a second seed moved no entry by more than 0.5 points",
              ws(r"moved no entry by more than \$") + r"(?P<v>0\.5)" + ws(r"\$ points"),
              second_seed_ok, A_DE + " (monte_carlo_replicate)", kind="bool"))

    # --------------------------------------------------------------- checklist
    for occ in (0, 1):
        add(Claim(f"CHK-01{'ab'[occ]}", "checklist: certificates / attempts released",
                  ws(r"the ") + G("a") + ws(r" counterexample certificates, the prompts and raw model responses for all ")
                  + G("b") + ws(" attempts"),
                  lambda c: (len(c.certs), len(c.attempts)), A_ATT, groups=("a", "b"), occurrence=occ))
    add(Claim("CHK-02", "checklist: K",
              ws(r"the falsifier and \$K\{=\}") + G("v") + r"\$", lambda c: len(c.certs), A_CERT))
    add(Claim("CHK-03", "checklist: evaluation / regression / held-out scenario counts",
              ws(r"defines the ") + G("a") + ws(r"-scenario evaluation \(the counterexample, a ") + G("b")
              + ws(r"-scenario regression suite and a ") + G("c") + r"-scenario\s+held-out",
              lambda c: (1 + c.json("data/scenarios/regression_suite.json")["n"]
                         + c.json("data/scenarios/held_out_suite.json")["n"],
                         c.json("data/scenarios/regression_suite.json")["n"],
                         c.json("data/scenarios/held_out_suite.json")["n"]),
              "recomputed: data/scenarios/*_suite.json", groups=("a", "b", "c")))
    add(Claim("CHK-04", "checklist: scenario parameters",
              ws(r"The bounds of the ") + W("v") + ws(" scenario parameters"),
              lambda c: len(c.yaml("data/scenarios/space.yaml")["parameters"]), "recomputed: data/scenarios/space.yaml"))
    add(Claim("CHK-05", "checklist: certificates / resamples / seed",
              ws(r"a paired cluster bootstrap over the ") + G("a") + ws(r" counterexample certificates \(") + G("b")
              + ws(r" resamples, NumPy PCG64 with seed ") + G("c"),
              lambda c: (c.boot.k, n_boot_both(c), uncert_seed(c).value if isinstance(uncert_seed(c), MultiValue) else -1),
              A_BOOT, groups=("a", "b", "c")))
    add(Claim("CHK-06", "checklist: Bonferroni-adjusted intervals for all N differences",
              ws(r"Bonferroni-adjusted intervals for all ") + G("v") + ws(" differences"), n_contrasts, "as UNC-03"))
    add(Claim("CHK-07", "checklist: replicates per condition and certificate",
              ws(r"with the ") + W("v") + ws(" independent replicate samples per condition"),
              lambda c: len({a["seed"] for a in c.attempts}), A_ATT))
    add(Claim("CHK-08", "checklist: clusters",
              ws(r"notes that with ") + G("v") + ws(" clusters"), lambda c: c.boot.k, A_BOOT))
    add(Claim("CHK-09", "checklist: CPU model numbers / cores / RAM GiB",
              ws(r"AMD Ryzen ") + r"(?P<r1>\d+)\s+(?P<r2>\d+)X" + ws(r" with ") + G("a") + ws(r" cores, ") + G("b")
              + r"\\,GiB",
              lambda c: env_doc(c, r"AMD Ryzen (\d+) (\d+)X\s*—\s*(\d+) cores.*?\n\|\s*RAM\s*\|\s*(\d+) GiB", 4),
              A_DOC_ENV, groups=("r1", "r2", "a", "b")))
    add(Claim("CHK-10", "checklist: GPU model",
              ws(r"NVIDIA RTX ") + G("v") + ws(" GPUs"),
              lambda c: env_doc(c, r"NVIDIA GeForce RTX (\d+)"), A_DOC_ENV))
    add(Claim("CHK-11", "checklist: GPU memory per CARLA server, GB",
              ws(r"at about ") + G("v") + r"\\,GB\s+of\s+GPU\s+memory",
              lambda c: env_doc(c, r"~(\d+) GB VRAM per headless CARLA instance"), A_DOC_ENV))
    add(Claim("CHK-12", "checklist: corpus wall clock, s / simulations",
              ws(r"building the corpus took ") + G("a") + r"\\,s\s+for\s+" + G("b") + ws(" simulations"),
              falsif_wall, "from artefact data/results/falsification_summary.json (wall_clock_s, rollouts_total)",
              groups=("a", "b")))
    add(Claim("CHK-13", "checklist: repair calls / phase A wall clock, minutes",
              ws(r"the ") + G("a") + ws(r" repair calls took ") + G("b") + ws(" minutes run concurrently"),
              lambda c: (lambda m: MultiValue((len(c.attempts), m.value), m.detail))(phase_minutes(c, "A")),
              A_ATT + "; minutes from artefact logs/e1_phase_a.log (campaign run log)",
              groups=("a", "b")))
    add(Claim("CHK-14", "checklist: input tokens / cache reads / output tokens",
              r"\(" + G("a") + ws(r" input tokens, ") + G("b") + ws(r" of them read from the prompt cache, and ")
              + G("c") + ws(r" output tokens\)"),
              token_sums, A_ATT + " (tokens_prompt + cache_read + cache_write; cache_read; tokens_completion)",
              groups=("a", "b", "c")))
    add(Claim("CHK-15", "checklist: phase B wall clock, minutes / evaluation rollouts",
              ws(r"evaluation took ") + G("a") + ws(r" minutes on one serial simulator over ") + G("b")
              + ws(" rollouts"),
              lambda c: (lambda m, r: MultiValue((m.value, r if isinstance(r, str) else r.value),
                                                 m.detail + "; " + (r if isinstance(r, str) else r.detail)))(
                  phase_minutes(c, "B"), rollouts_eval_total(c)),
              "minutes from artefact logs/e1_phase_b.log (campaign run log); rollouts recomputed from "
              "attempts.jsonl + baseline_eval.json and the suites, and the run log must agree", groups=("a", "b")))
    for cid, rx, req, dist in [
        ("CHK-16", ws(r"used version ") + V("v"), "carla", "carla"),
        ("CHK-17", ws(r"py\\_trees ") + V("v"), "py-trees", "py-trees"),
        ("CHK-18", ws(r"rtamt ") + V("v"), "rtamt", "rtamt"),
        ("CHK-19", ws(r"NumPy ") + V("v"), "numpy", "numpy"),
        ("CHK-20", ws(r"SciPy ") + V("v"), "scipy", "scipy"),
        ("CHK-21", ws(r"pandas ") + V("v"), "pandas", "pandas"),
        ("CHK-22", ws(r"networkx ") + V("v"), "networkx", "networkx"),
        ("CHK-23", ws(r"pyarrow ") + V("v"), "pyarrow", "pyarrow"),
        ("CHK-24", ws(r"PyYAML ") + V("v"), "pyyaml", "PyYAML"),
        ("CHK-25", ws(r"matplotlib ") + V("v"), "matplotlib", "matplotlib"),
        ("CHK-26", ws(r"Anthropic Python SDK ") + V("v"), "anthropic", "anthropic"),
    ]:
        add(Claim(cid, f"checklist: {dist} version", rx,
                  functools.partial(lambda c, req, dist: pkg_version(c, req, dist), req=req, dist=dist),
                  A_REQ, kind="str"))
    add(Claim("CHK-27", "checklist: CARLA version (hardware sentence)",
              ws(r"GPUs, CARLA ") + V("v"), lambda c: pkg_version(c, "carla", "carla"), A_REQ, kind="str"))
    add(Claim("CHK-27b", "checklist: CARLA version (reproducibility answer)",
              ws(r"simulations requires CARLA ") + V("v"), lambda c: pkg_version(c, "carla", "carla"), A_REQ,
              kind="str"))
    add(Claim("CHK-28", "checklist: constructed N-contract case",
              ws(r"checked on a constructed ") + W("v") + r"-contract\s+case",
              lambda c: by_construction_zero(c)[0], "recomputed by construction with src/blame.conditional_entropy"))
    add(Claim("CHK-29", "checklist: repair attempts produced",
              ws(r"produced all ") + G("v") + ws(" repair attempts"), lambda c: len(c.attempts), A_ATT))
    return C


def clean_all(c: Ctx):
    v = clean_repair_20(c)
    if isinstance(v, str):
        return v
    r, n, comp, n2 = v.value
    if not (r == comp == n == n2):
        return f"resolved {r}/{n}, completed {comp}/{n2}"
    return MultiValue(n, v.detail)


def probes_valid(c: Ctx):
    from program_parser import parse_and_validate
    files = ["data/scenarios/baseline_program.bt"] + sorted(
        str(pathlib.Path(p).relative_to(c.repo)) for p in glob.glob(str(c.p("data/scenarios/dsl_probe/*.bt"))))
    bad = []
    for f in files:
        try:
            _root, vr = parse_and_validate(c.p(f).read_text())
            if not vr.ok:
                bad.append(f"{f}: {vr.errors[:1]}")
        except Exception as e:
            bad.append(f"{f}: {type(e).__name__}")
    if bad:
        return f"invalid: {bad}"
    return MultiValue(len(c.certs), f"{len(files)} programs validate")


# ---- second camera-ready pass (10 Oct 2026): helpers for claims added after
# the round-2 revision of main.tex ------------------------------------------------
def abstract_funnel(c: Ctx):
    """Abstract: of the S attempts, R never entered; of the other E, C completed, 1 also intact."""
    S, ref, ent, _C, _R, SC, SCR = tab4_row(c, None)
    if ent != S - ref:
        return f"entered {ent} != S {S} - refused {ref}"
    return S, ref, ent, SC, SCR


def skel_counts_all(c: Ctx):
    """Skeleton edits per condition, re-derived from source (not read from the log)."""
    vals = tuple(skel_recomputed(c, x) for x in CONDS)
    logged = tuple(skel(c, x) for x in CONDS)
    if vals != logged:
        return f"from source {vals} but logged {logged}"
    n = single_val({len(c.by_cond(x)) for x in CONDS})
    return (*vals, n)


def f1_vs_processed_range(c: Ctx):
    """Smallest and largest F1-minus-X structural-edit difference, X processed; every CI must exclude 0."""
    b = c.boot
    out = {y: b.diff("skeleton_edit", "F1", y) for y in CONDS if y != "F1"}
    bad = [y for y, (_, (lo, hi)) in out.items() if ci_contains_zero(lo, hi)]
    det = "; ".join(f"F1-{y} {p:+.1f} [{lo:+.1f},{hi:+.1f}]" for y, (p, (lo, hi)) in out.items())
    if bad:
        return f"intervals containing zero: {bad} ({det})"
    pts = [p for p, _ in out.values()]
    return MultiValue((min(pts), max(pts)), det)


def ab_skel_diff(c: Ctx, a: str, b_: str):
    p, (lo, hi) = c.boot.diff("skeleton_edit", a, b_)
    return p, lo, hi


def f1_skel_19(c: Ctx):
    """The 17 contrasts of Table 6 plus F1-F4a and F1-F4b; all four F1 structural contrasts exclude 0 at 0.05/19."""
    n = len(CONTRASTS17) + 2
    alpha = 0.05 / n
    res = {y: c.boot.diff_alpha("skeleton_edit", "F1", y, alpha) for y in ("F2", "F3", "F4a", "F4b")}
    det = "; ".join(f"F1-{y} [{lo:+.1f},{hi:+.1f}]" for y, (lo, hi) in res.items())
    bad = [y for y, ci in res.items() if ci_contains_zero(*ci)]
    if bad:
        return f"contain zero at alpha=0.05/{n}: {bad} ({det})"
    return MultiValue((n, len(res), Fraction(5, 100), n), f"intervals at alpha = 0.05/{n}: {det}")


def f1f2_largest_pairwise(c: Ctx):
    """(F1-F2 is strictly the largest |difference|?, number of pairs, detail)."""
    b = c.boot
    pairs = [(abs(b.diff("skeleton_edit", x, y)[0]), x, y) for i, x in enumerate(CONDS) for y in CONDS[i + 1:]]
    pairs.sort(reverse=True)
    ok = (pairs[0][1], pairs[0][2]) == ("F1", "F2") and pairs[0][0] > pairs[1][0]
    return ok, len(pairs), "top three |differences|: " + ", ".join(f"{x}-{y} {d:.1f}" for d, x, y in pairs[:3])


def f1f2_largest_bool(c: Ctx):
    ok, n, det = f1f2_largest_pairwise(c)
    return ok, f"{det}; {n} pairs"


def f1f2_n_pairs(c: Ctx):
    _ok, n, det = f1f2_largest_pairwise(c)
    return MultiValue(n, det)


def contrasts_all22():
    """The 17 tabulated contrasts plus the five structural-edit pairs that involve neither F3 nor F1-F2."""
    done = {frozenset((x, y)) for m, x, y in CONTRASTS17 if m == "skeleton_edit"}
    extra = [("skeleton_edit", x, y) for i, x in enumerate(CONDS) for y in CONDS[i + 1:]
             if frozenset((x, y)) not in done]
    return list(CONTRASTS17) + extra


def bonf22_survivors(c: Ctx):
    allc = contrasts_all22()
    alpha = 0.05 / len(allc)
    surv = set()
    for m, x, y in allc:
        lo, hi = c.boot.diff_alpha(m, x, y, alpha)
        if not ci_contains_zero(lo, hi):
            surv.add((m, x, y))
    return allc, surv


def bonf22_only_f1_skel(c: Ctx):
    allc, surv = bonf22_survivors(c)
    want = {("skeleton_edit", "F1", y) for y in ("F2", "F3", "F4a", "F4b")}
    return surv == want, f"{len(allc)} contrasts; Bonferroni-excluding: {fmt_set(surv)}"


def bonf22_counts(c: Ctx):
    allc, surv = bonf22_survivors(c)
    want = {("skeleton_edit", "F1", y) for y in ("F2", "F3", "F4a", "F4b")}
    if surv != want:
        return f"survivors at 0.05/{len(allc)} are {fmt_set(surv)}, not exactly the four F1 structural contrasts"
    extra = len(allc) - len(CONTRASTS17)
    js = c.json("data/results/uncertainty.json").get("multiplicity_all_computed", {}).get("n_distinct_differences")
    return MultiValue((extra, len(allc), len(allc), len(surv)),
                      f"recomputed survivors {fmt_set(surv)}; uncertainty.json n_distinct_differences = {js}")


def about_one_by_chance(c: Ctx):
    n = len(contrasts_all22())
    return MultiValue((n, Fraction(n * 5, 100)), f"{n} x 0.05 = {n * 0.05:.2f} expected exclusions if every effect were null")


def scaffold_tokens(c: Ctx):
    js = c.json("data/results/prompt_budget.json")["scaffolding_tokens"]
    sysblk = {a["cache_read"] + a["cache_write"] for a in c.attempts}
    return MultiValue(js, f"prompt_budget.json scaffolding_tokens (count_tokens API, not re-counted here); "
                          f"the cached system block alone is {sorted(sysblk)} tokens in every attempt, so the "
                          f"other {js - min(sysblk)} are the user-side prefix and suffix")


def feedback_block_tokens(c: Ctx):
    """Appendix A: median prompt tokens per condition minus the shared scaffolding."""
    sc = c.json("data/results/prompt_budget.json")["scaffolding_tokens"]
    vals = tuple(median_prompt_tokens(c, x) - sc for x in CONDS)
    pb = c.json("data/results/prompt_budget.json")["by_condition"]
    return MultiValue(vals, "median prompt (attempts.jsonl, = prompt_budget.json per certificate) minus "
                            f"scaffolding {sc}: " + ", ".join(f"{x} {float(v):g}" for x, v in zip(CONDS, vals))
                      + f"; prompt_budget.json stores int(median) for F1 = {pb['F1']['median']}")


def baseline_suite_icr(c: Ctx):
    s = {v["icr"] for v in c.baseline_eval.values()}
    if len(s) != 1:
        return f"baseline ICR not unique: {s}"
    return MultiValue(100 * Fraction(str(s.pop())), "baseline_eval.json icr (60 suite scenarios), identical "
                                                     "for all 20 certificates")


def rho5_before_all(c: Ctx):
    xs = {a["rho5_before"] for a in c.attempts}
    base = {v.get("rho5_after", v.get("rho5")) for v in c.baseline_eval.values()} - {None}
    return MultiValue(Fraction(sum(Fraction(str(a["rho5_before"])) for a in c.attempts), len(c.attempts)),
                      f"rho5_before values {sorted(xs)} (300 attempts)" + (f"; baseline_eval {sorted(base)}" if base else ""))


def rho5_falls_everywhere(c: Ctx):
    before = {x: Fraction(sum(Fraction(str(a["rho5_before"])) for a in c.by_cond(x)), len(c.by_cond(x)))
              for x in CONDS}
    after = rho5_means(c)
    ok = all(after[x] < before[x] for x in CONDS)
    return ok, ", ".join(f"{x} {float(before[x]):.3f} -> {float(after[x]):.4f}" for x in CONDS)


def f3_success_certs_named(c: Ctx):
    """F3's certificates with a success under S, S excluding refusals, and S with C (the three named)."""
    preds = {"S": lambda a: a["resolved"],
             "S excl. refusals": lambda a: a["resolved"] and not a["resolved_by_refusal"],
             "S and C": lambda a: a["resolved_and_completed"]}
    out = {k: sorted({a["certificate_id"].split("_")[0] for a in c.by_cond("F3") if f(a)}) for k, f in preds.items()}
    return MultiValue(max(len(v) for v in out.values()), str(out))


def power_at_5_range(c: Ctx):
    ps = [de_sim(c, P0_33, i, r)["power_at"]["5pp"]["power"] for i, r in TABLE7_SETTINGS]
    f3 = pct(c.count(lambda a: a["resolved"] and not a["resolved_by_refusal"], "F3"), 60)
    return MultiValue((f3, 5, min(ps), max(ps)),
                      f"power at +5 points, p0 = 2/60, Table 7 settings (ICC, r) {TABLE7_SETTINGS}: "
                      + ", ".join(f"{p:.4f}" for p in ps))


def calib_candidates_released(c: Ctx):
    d = c.json("data/results/baseline_calibration.json")
    cands = [x for x in d["candidates"] if "violations" in x and "n_scored" in x]
    tracked = ""
    if shutil.which("git") and c.p(".git").exists():
        r = subprocess.run(["git", "-C", str(c.repo), "ls-files", "--error-unmatch",
                            "data/results/baseline_calibration.json"], capture_output=True)
        if r.returncode != 0:
            return "data/results/baseline_calibration.json is not tracked by git, so not 'released'"
        tracked = "; the file is tracked by git"
    return MultiValue(len(cands), f"{len(cands)} candidates with violations / n_scored in "
                                  f"baseline_calibration.json{tracked}; it has no completion (gate 1b) field")


# ---- the clean repair's patch (Section 4.3) ---------------------------------------
def _branches(src: str):
    from program_parser import parse
    root = parse(src)
    return root, list(root.children)


def _find_branch(branches, first: str, first_param: tuple | None = None):
    hits = []
    for i, br in enumerate(branches):
        kids = list(br.children)
        if br.name == "Sequence" and kids and kids[0].name == first and (
                first_param is None or float(kids[0].params.get(first_param[0], -1)) == first_param[1]):
            hits.append(i)
    if len(hits) != 1:
        raise NotRecomputable(f"{len(hits)} top-level branches start with {first}{first_param or ''}")
    return hits[0]


def _subtree(n, name: str):
    out = [n] if n.name == name else []
    for k in n.children:
        out += _subtree(k, name)
    return out


def clean_patch(c: Ctx) -> dict:
    """What the single clean repair changed, read from the program sources.

    Branches are identified structurally in the frozen baseline: the committing
    branch is the Sequence that opens with DistanceToStopLineBelow(dist_m=0.0)
    ("past the stop line, still rolling"), the stop-line decision branch opens
    with EgoSpeedBelow, and the fallback is the Sequence
    DistanceToStopLineBelow(30.0) -> Decelerate. Every other parameter change
    in the program is collected so that 'adds / lengthens / brakes' can be
    checked as the whole patch."""
    clean = [a for a in c.attempts if is_clean(a)]
    if len(clean) != 1:
        raise NotRecomputable(f"{len(clean)} clean attempts")
    a = clean[0]
    probe = c.p("data/scenarios/dsl_probe/clean_repair.bt").read_text()
    if probe != a["bt_source_after"]:
        raise NotRecomputable("dsl_probe/clean_repair.bt is not byte-identical to the clean attempt's program")
    _, B = _branches(c.p("data/scenarios/baseline_program.bt").read_text())
    _, N = _branches(a["bt_source_after"])
    if len(B) != len(N):
        raise NotRecomputable(f"top-level branch count changed {len(B)} -> {len(N)}")
    ic = _find_branch(B, "DistanceToStopLineBelow", ("dist_m", 0.0))
    isl = _find_branch(B, "EgoSpeedBelow")
    ifb = _find_branch(B, "DistanceToStopLineBelow", ("dist_m", 30.0))
    pc = lambda n: [float(x.params["dist_m"]) for x in _subtree(n, "PathIsClear")]
    fb = lambda n: [x for x in _subtree(n, "Decelerate")]
    # every node, paired by preorder position inside each branch where the
    # skeleton is unchanged; branch C is compared as a multiset (insertion)
    other = []
    for i, (x, y) in enumerate(zip(B, N)):
        if i == ic:
            continue
        def flat(n):
            out = [(n.name, {k: round(float(v), 6) for k, v in n.params.items()})]
            for k in n.children:
                out += flat(k)
            return out
        fx, fy = flat(x), flat(y)
        if [n for n, _ in fx] != [n for n, _ in fy]:
            other.append(f"branch {i}: skeleton changed")
            continue
        for (n1, p1), (_n2, p2) in zip(fx, fy):
            if p1 != p2 and not (i == isl and n1 == "PathIsClear") and not (i == ifb and n1 == "Decelerate"):
                other.append(f"branch {i} {n1} {p1} -> {p2}")
    added_c = [n for n in [k.name for k in N[ic].children] if n not in [k.name for k in B[ic].children]]
    db, dn = fb(B[ifb]), fb(N[ifb])
    return {
        "attempt": a["attempt_id"],
        "commit_added": [d for d in pc(N[ic])] if added_c == ["PathIsClear"] and not pc(B[ic]) else None,
        "commit_added_nodes": added_c,
        "stopline_before": pc(B[isl]), "stopline_after": pc(N[isl]),
        "fallback_before": [dict(x.params) for x in db], "fallback_after": [dict(x.params) for x in dn],
        "other": other,
    }


def clean_patch_commit(c: Ctx):
    p = clean_patch(c)
    if not p["commit_added"] or len(p["commit_added"]) != 1:
        return f"committing branch gained {p['commit_added_nodes']}"
    return MultiValue(p["commit_added"][0], f"{p['attempt']}: committing branch (DistanceToStopLineBelow(0.0) "
                                            f"-> CommitTurn) gained {p['commit_added_nodes']}")


def clean_patch_stopline(c: Ctx):
    p = clean_patch(c)
    b, a = p["stopline_before"], p["stopline_after"]
    if len(b) != len(a) or len(set(a)) != 1 or not all(y > x for x, y in zip(b, a)):
        return f"stop-line path checks {b} -> {a}"
    return MultiValue((len(a), a[0]), f"stop-line branch PathIsClear dist_m {b} -> {a}")


def clean_patch_fallback(c: Ctx):
    p = clean_patch(c)
    b, a = p["fallback_before"], p["fallback_after"]
    if len(b) != 1 or len(a) != 1:
        return f"fallback Decelerate nodes {b} -> {a}"
    return MultiValue((Fraction(str(a[0]["decel_mps2"])), Fraction(str(b[0]["decel_mps2"]))),
                      f"fallback Decelerate {b[0]} -> {a[0]}")


def clean_patch_creep(c: Ctx):
    p = clean_patch(c)
    b, a = p["fallback_before"][0], p["fallback_after"][0]
    ok = float(a["v_mps"]) == float(b["v_mps"]) > 0 and not p["other"]
    return ok, (f"fallback target speed {b['v_mps']} -> {a['v_mps']} m/s (creeps if > 0); parameter changes "
                f"outside the three described: {p['other'] or 'none'}")


def geometric_family(c: Ctx):
    """'Our hand-written path checks on the same branch (16 to 32 m, fallback unchanged) fixed none of the twenty.'

    Recomputed from the released geometric-guard variants: each directory in
    data/dsl_probe_traces/geometric_guard/ ran a committed
    data/scenarios/dsl_probe/*.bt (linked by sha256 of the program source).
    The added guard's branch and distance and the untouched fallback are read
    from those programs, and 'fixed' from their re-scored trajectories. The
    committed dsl_expressiveness.json ('add PathIsClear to branch C,
    16/24/32 m', 0/20) must agree on the distances and the count."""
    v = dsl_variant(c, "add PathIsClear to branch C")
    m = re.search(r"([\d.]+(?:/[\d.]+)+)\s*m", v["fix"])
    if not m:
        raise NotRecomputable(f"no distance list in {v['fix']!r}")
    ds = sorted(float(x) for x in m.group(1).split("/"))
    res = probe_scores(c)["geometric"]
    base_src = c.p("data/scenarios/baseline_program.bt").read_text()
    _, B = _branches(base_src)
    ic = _find_branch(B, "DistanceToStopLineBelow", ("dist_m", 0.0))
    ifb = _find_branch(B, "DistanceToStopLineBelow", ("dist_m", 30.0))
    fb0 = [dict(x.params) for x in _subtree(B[ifb], "Decelerate")]
    seen = {}
    for r in res:
        _, P = _branches(c.p(r["program"]).read_text())
        added = [float(x.params["dist_m"]) for x in _subtree(P[ic], "PathIsClear")]
        fbx = [dict(x.params) for x in _subtree(P[ifb], "Decelerate")]
        seen[r["dir"]] = (pathlib.Path(r["program"]).name, added, fbx == fb0, r["fixed"], r["n"])
    det = (f"dsl_expressiveness.json: {v['fix']!r}, fixed {v['fixed']}; "
           + "; ".join(f"{k} ({p}): guard {a} m on the committing branch, fallback unchanged {u}, fixed {f}/{n}"
                       for k, (p, a, u, f, n) in seen.items()))
    bad = {k: x for k, x in seen.items() if not x[1] or not x[2]}
    if bad:
        return f"not a path check on the committing branch with the fallback unchanged: {sorted(bad)} ({det})"
    got = sorted({d for x in seen.values() for d in x[1]})
    if got != ds:
        return f"artefact says {ds} m, the programs give {got} m ({det})"
    fixed = {(x[3], x[4]) for x in seen.values()}
    if len(fixed) != 1 or fixed != {frac_str(v["fixed"])}:
        return f"fixed varies or disagrees with the artefact: {sorted(fixed)} ({det})"
    f, n = fixed.pop()
    return MultiValue((min(got), max(got), f, n), det)


# =============================================================================
# Evaluation
# =============================================================================
@dataclasses.dataclass
class Src:
    """The tex as checked: main.tex followed by the files it \\input{}s.

    Included files are appended after main.tex rather than spliced in, so
    main.tex line numbers stay exact; `where` maps an offset back to
    (file, line) in either."""
    text: str
    parts: list[tuple[int, str, str]]        # (start offset, label, original text)

    def where(self, off: int) -> tuple[str, int]:
        start, label, _ = max((p for p in self.parts if p[0] <= off), key=lambda p: p[0])
        return label, self.text.count("\n", start, off) + 1

    def main_len(self) -> int:
        return len(self.parts[0][2])


def load_src(tex_path: pathlib.Path) -> Src:
    main = tex_path.read_text()
    text, parts = main, [(0, "main.tex", main)]
    body = re.sub(r"(?<!\\)%.*", "", main)
    for name in re.findall(r"\\input\{([^}]+)\}", body):
        f = tex_path.parent / (name if name.endswith(".tex") else name + ".tex")
        if not f.exists():
            continue
        sep = f"\n%%%%%%%% INPUT {f.name} %%%%%%%%\n"
        text += sep
        parts.append((len(text), f.name, f.read_text()))
        text += parts[-1][2]
    return Src(text, parts)


def evaluate(claim: Claim, tex: str | Src, ctx: Ctx) -> Row:
    src = tex if isinstance(tex, Src) else Src(tex, [(0, "main.tex", tex)])
    matches = list(re.finditer(claim.pattern, src.text, re.S))
    if len(matches) <= claim.occurrence:
        return Row(claim.cid, None, claim.desc, "", "", "NOT-FOUND", claim.basis,
                   "anchor text absent from this tex (reworded or removed)")
    m = matches[claim.occurrence]
    g0 = claim.groups[0] if claim.kind != "bool" else "v"
    fname, line = src.where(m.start(g0))
    paper_strs = [m.group(g) for g in (claim.groups if claim.kind != "bool" else ("v",))]
    paper_disp = " | ".join(re.sub(r"\s+", " ", s) for s in paper_strs)
    if claim.kind == "bool":
        paper_disp = '"' + (paper_disp[:70] + ("..." if len(paper_disp) > 70 else "")) + '"'

    def row(rec, status, note):
        return Row(claim.cid, line, claim.desc, paper_disp, rec, status, claim.basis, note, fname)

    try:
        val = claim.compute(ctx)
    except NotRecomputable as e:
        return row("-", "NOT-RECOMPUTABLE", str(e) + ("; " + claim.note if claim.note else ""))
    except Exception as e:  # a crash is a finding, not a pass
        return row(f"ERROR {type(e).__name__}: {e}", "MISMATCH", "compute function raised")

    note = claim.note
    if isinstance(val, MultiValue):
        note = (val.detail + ("; " + note if note else ""))
        val = val.value

    if claim.kind == "bool":
        ok, detail = val if isinstance(val, tuple) else (val, "")
        return row(f"{bool(ok)} ({detail})" if detail else str(ok), "MATCH" if ok else "MISMATCH", note)

    if claim.kind == "str":
        if isinstance(val, MultiValue):
            val = val.value
        ok = str(val) == paper_strs[0]
        return row(str(val), "MATCH" if ok else "MISMATCH", note)

    if claim.kind == "approx":
        target = parse_paper(paper_strs[0])
        vals = list(val.values()) if isinstance(val, dict) else [val]
        rels = [abs(float(target) - float(to_dec(v))) / float(to_dec(v)) for v in vals]
        ok = max(rels) <= claim.tol
        rec = ", ".join(show(v) for v in vals)
        return row(f"{rec} (max rel. dev {max(rels):.1%})", "MATCH" if ok else "MISMATCH",
                   f"approximate claim, tolerance {claim.tol:.0%}" + ("; " + note if note else ""))

    vals = val if isinstance(val, tuple) else (val,)
    if len(vals) != len(paper_strs):
        return row(show(val), "MISMATCH", "recomputed value has a different shape: " + note)
    if claim.kind == "approx_abs":
        oks, recs = [], []
        for ps, v in zip(paper_strs, vals):
            if isinstance(v, str):
                oks.append(False)
                recs.append(v)
                continue
            oks.append(abs(float(parse_paper(ps)) - float(to_dec(v))) <= claim.tol)
            recs.append(show(v))
        return row(" | ".join(recs), "MATCH" if all(oks) else "MISMATCH",
                   f"approximate claim, absolute tolerance {claim.tol:g}" + ("; " + note if note else ""))
    oks, recs = [], []
    for ps, v in zip(paper_strs, vals):
        if isinstance(v, str):
            oks.append(False)
            recs.append(v)
            continue
        r = round_like(v, ps)
        oks.append(r == parse_paper(ps))
        raw = show(v)
        recs.append(raw if raw == str(r) else f"{raw} -> {r}")
    return row(" | ".join(recs), "MATCH" if all(oks) else "MISMATCH", note)


# =============================================================================
# Integrity checks: not paper numbers, but the things the numbers rest on.
# =============================================================================
@dataclasses.dataclass
class Check:
    cid: str
    desc: str
    status: str          # PASS | FAIL | SKIP | INFO
    detail: str


def integrity(ctx: Ctx) -> list[Check]:
    out: list[Check] = []
    A = ctx.attempts

    # I-01 TED and patch type from source vs logged
    from ted import ted_from_source, classify_patch
    bad = [a["attempt_id"] for a in A
           if ted_from_source(a["bt_source_before"], a["bt_source_after"]) != a["ted_from_original"]
           or classify_patch(a["bt_source_before"], a["bt_source_after"]) != a["patch_type"]]
    out.append(Check("I-01", "TED and patch type re-derived from program source equal the logged values",
                     "PASS" if not bad else "FAIL", f"{len(A) - len(bad)}/{len(A)} agree"
                     + (f"; first disagreements {bad[:3]}" if bad else "")))

    # I-02 patched_programs on disk == bt_source_after
    neq = [a["attempt_id"] for a in A if ctx.p(a["patched_program_path"]).read_text() != a["bt_source_after"]]
    out.append(Check("I-02", "data/results/patched_programs/*.bt equal bt_source_after",
                     "PASS" if not neq else "FAIL", f"{len(A) - len(neq)}/{len(A)} identical"))

    # I-03 every attempt patched the frozen baseline; frozen == cand_01
    base = ctx.p("data/scenarios/baseline_program.bt").read_text()
    n_base = sum(1 for a in A if a["bt_source_before"] == base)
    t01 = ted_from_source(base, ctx.p("data/scenarios/candidates/cand_01.bt").read_text())
    out.append(Check("I-03", "every attempt starts from the frozen baseline; frozen baseline is cand_01",
                     "PASS" if n_base == len(A) and t01 == 0 else "FAIL",
                     f"{n_base}/{len(A)} start from baseline_program.bt; TED(baseline, cand_01) = {t01}"))

    # I-04 clean repair probe file is the clean attempt's program
    clean = [a for a in A if is_clean(a)]
    t_cr = ted_from_source(ctx.p("data/scenarios/dsl_probe/clean_repair.bt").read_text(),
                           clean[0]["bt_source_after"]) if len(clean) == 1 else None
    out.append(Check("I-04", "dsl_probe/clean_repair.bt is the program of the single clean attempt",
                     "PASS" if t_cr == 0 else "FAIL",
                     f"clean attempts {[a['attempt_id'] for a in clean]}; TED = {t_cr}"))

    # I-05 bootstrap reproduces uncertainty.json exactly
    u = ctx.json("data/results/uncertainty.json")
    b = ctx.boot
    diffs = []
    for m in PREDICATES:
        for x in CONDS:
            if abs(b.point(m, x) - u[m]["point"][x]) > 1e-9:
                diffs.append(f"{m}.point.{x}")
            if any(abs(p - q) > 1e-9 for p, q in zip(b.ci(m, x), u[m]["ci"][x])):
                diffs.append(f"{m}.ci.{x}")
            if x != "F3":
                p, ci = b.diff(m, x, "F3")
                if abs(p - u[m]["diff_vs_F3"][x]["point"]) > 1e-9 or \
                        any(abs(s - t) > 1e-9 for s, t in zip(ci, u[m]["diff_vs_F3"][x]["ci"])):
                    diffs.append(f"{m}.diff.{x}")
    out.append(Check("I-05", "independent bootstrap reproduces data/results/uncertainty.json exactly",
                     "PASS" if not diffs else "FAIL",
                     "all points, CIs and diffs vs F3 equal to 1e-9" if not diffs else f"differ: {diffs}"))

    # I-06 e1_analysis.json summary agrees with recomputation
    e1 = ctx.json("data/results/e1_analysis.json")["summary"]
    dis = []
    for x in CONDS:
        rows = ctx.by_cond(x)
        rec = {
            "n_resolved": sum(1 for a in rows if a["resolved"]),
            "n_resolved_by_refusal": sum(1 for a in rows if a["resolved_by_refusal"]),
            "n_resolved_and_completed": sum(1 for a in rows if a["resolved_and_completed"]),
            "mean_ted": round(statistics.mean(a["ted_from_original"] for a in rows), 4),
            "mean_rho5_after": round(statistics.mean(a["rho5_after"] for a in rows), 4),
            "generalization_gap": round(statistics.mean(a["generalization_gap"] for a in rows), 4),
        }
        for k, v in rec.items():
            if abs(float(e1[x][k]) - float(v)) > 1e-4:
                dis.append(f"{x}.{k}: json {e1[x][k]} vs {v}")
    out.append(Check("I-06", "e1_analysis.json per-condition summary agrees with attempts.jsonl",
                     "PASS" if not dis else "FAIL", "agree" if not dis else "; ".join(dis)))

    # I-07 attempts.jsonl and patches.jsonl agree on shared fields
    P = {p["attempt_id"]: p for p in ctx.patches}
    dis = [a["attempt_id"] for a in A
           if a["attempt_id"] not in P or any(a[k] != P[a["attempt_id"]][k] for k in P[a["attempt_id"]] if k in a)]
    out.append(Check("I-07", "attempts.jsonl and patches.jsonl agree on every shared field",
                     "PASS" if not dis else "FAIL", f"{len(A) - len(dis)}/{len(A)} agree"))

    # I-08 served prompt usage equals the count_tokens artefact
    pb = ctx.json("data/results/prompt_budget.json")["per_certificate"]
    dis = [a["attempt_id"] for a in A
           if a["tokens_prompt"] + a["cache_read"] + a["cache_write"] != pb[a["certificate_id"]][a["condition"]]]
    cache = collections.Counter(a["cache_read"] + a["cache_write"] for a in A)
    out.append(Check("I-08", "served prompt tokens per attempt equal prompt_budget.json counts; "
                     "cached system block constant",
                     "PASS" if not dis and len(cache) == 1 else "FAIL",
                     f"{len(A) - len(dis)}/{len(A)} equal; cached system-block tokens {dict(cache)}"))

    # I-09 every prompt regenerated from committed certificates (F1 from the
    # released certificate trajectories) hash-matches the prompt sent
    try:
        g = regen_prompts(ctx)
        done = [v for v in g["res"].values() if v is not None]
        ok_fb, ok_pr = sum(v[0] for v in done), sum(v[1] for v in done)
        by_c = collections.Counter(a["condition"] for a in A if g["res"][a["attempt_id"]] is not None)
        out.append(Check("I-09", "all prompts regenerated from committed certificates + template (F1 from "
                         "data/certificates/traces/) hash-match the prompts actually sent",
                         "PASS" if ok_fb == ok_pr == len(done) == len(A) else "FAIL",
                         f"feedback {ok_fb}/{len(A)}, full prompt {ok_pr}/{len(A)} by condition {dict(by_c)} "
                         f"(prefix {g['prefix']} B, suffix {g['suffix']} B); certificate trajectories "
                         f"{dict(g['where'])}" + ("" if g["f1"] else "; F1 NOT regenerated")))
        from certificate import template as tpl
        t = tpl()
        f1 = ctx.p("data/results/rendered_prompts/CE003_C1_969f15c8657c8fa6_F1.txt").read_text()
        out.append(Check("I-09b", "committed CE003 F1 prompt carries the same prefix and suffix by index",
                         "PASS" if f1[:len(t.prefix)] == t.prefix and f1.endswith(t.suffix) else "FAIL",
                         "data/results/rendered_prompts/CE003_C1_969f15c8657c8fa6_F1.txt"))
    except Exception as e:
        out.append(Check("I-09", "prompt regeneration", "FAIL", f"{type(e).__name__}: {e}"))

    # I-10 the saved prompts and responses of all 300 attempts (logs/campaign/)
    cp = campaign_prompts(ctx)
    if cp is None:
        out.append(Check("I-10", "logs/campaign/prompts (released)", "FAIL", "logs/campaign/prompts/ absent"))
    else:
        resp = [ctx.p(a["response_path"]) for a in A]
        has = sum(1 for f in resp if f.exists())
        holds = sum(1 for a, f in zip(A, resp) if f.exists() and a["bt_source_after"] in f.read_text())
        ok = cp["good"] == cp["n"] and has == holds == len(A)
        out.append(Check("I-10", "logs/campaign: every saved prompt shares the prefix and suffix and hash-matches "
                         "attempts.jsonl; every saved response contains the program logged as bt_source_after",
                         "PASS" if ok else "FAIL",
                         f"prompts {cp['good']}/{cp['n']} ({cp['present']} present); responses {holds}/{len(A)} "
                         f"contain bt_source_after ({has} present)"))

    # I-11 INFO: bootstrap Monte-Carlo sensitivity of the headline intervals
    import numpy as np  # noqa: F401
    spans = collections.defaultdict(list)
    # Seeds 1-20 (verification, 9 Oct: was 1-10, which missed seed 16 moving the
    # F1-F3 ex-refusal lower bound to -6.7).
    for s in range(1, 21):
        bb = Boot(A, seed=s, n_boot=N_BOOT)
        spans["F1-F2 structural"].append(bb.diff("skeleton_edit", "F1", "F2")[1])
        spans["F1-F3 ex-refusal"].append(bb.diff("resolved_ex_refusal", "F1", "F3")[1])
        spans["F4b-F3 structural"].append(bb.diff("skeleton_edit", "F4b", "F3")[1])
    det = "; ".join(f"{k}: lo {min(x[0] for x in v):+.1f}..{max(x[0] for x in v):+.1f}, "
                    f"hi {min(x[1] for x in v):+.1f}..{max(x[1] for x in v):+.1f}"
                    for k, v in spans.items())
    out.append(Check("I-11", "INFO: CI endpoints across bootstrap seeds 1-20 (10,000 resamples each)",
                     "INFO", det))

    # I-12 INFO: every pairwise contrast whose CI excludes zero (multiplicity context)
    excl = []
    n_int = 0
    for m in PREDICATES:
        for i, x in enumerate(CONDS):
            for y in CONDS[i + 1:]:
                n_int += 1
                p, (lo, hi) = b.diff(m, x, y)
                if not ci_contains_zero(lo, hi):
                    excl.append(f"{m} {x}-{y} {p:+.1f} [{lo:+.1f},{hi:+.1f}]")
    out.append(Check("I-12", f"INFO: pairwise contrasts whose 95% CI excludes 0, of {n_int} computed "
                     "(no multiplicity adjustment)", "INFO", "; ".join(excl)))

    # I-13 INFO: ex-refusal intervals that contain zero only at an endpoint
    # Verification (9 Oct): also the pre-specified `resolved` panel of Figure 2,
    # where F4a-F3 is [-10.0, 0.0] because F4a had no resolutions at all.
    edge = []
    for m in ("resolved", "resolved_ex_refusal"):
        for x in CONDS:
            if x == "F3":
                continue
            p, (lo, hi) = b.diff(m, x, "F3")
            if lo == 0.0 or hi == 0.0:
                edge.append(f"{m} {x}-F3 [{lo:+.1f},{hi:+.1f}]")
    out.append(Check("I-13", "INFO: CIs vs F3 (Figure 3 success panels) that touch zero only at an endpoint "
                     "(a condition with 0 successes)", "INFO", "; ".join(edge) or "none"))

    # I-14 baseline synthesis log breakdown
    s = llm_synth_counts(ctx)
    out.append(Check("I-14", "INFO: baseline-synthesis calls in logs/llm_index.jsonl", "INFO",
                     f"{s['total']} synth calls; by prompt hash {s['by_prompt']}; "
                     f"{s['truncated']} stopped at max_tokens; 14 candidates scored"))

    # ---- added for the camera-ready (10 Oct 2026) ----------------------------
    # I-15 the multiplicity block and the F1-F2 interval in uncertainty.json
    mult = u.get("multiplicity")
    if mult is None:
        out.append(Check("I-15", "uncertainty.json multiplicity block", "FAIL",
                         "absent: the 17-contrast table (Appendix D) has no saved source"))
    else:
        dif = []
        alpha = 0.05 / len(CONTRASTS17)
        for m, x, y in CONTRASTS17:
            js = mult["contrasts"][m][f"{x}-{y}"]
            ci = b.diff(m, x, y)[1]
            bc = b.diff_alpha(m, x, y, alpha)
            if any(abs(p - q) > 1e-9 for p, q in zip(ci + bc, js["ci_95"] + js["ci_bonferroni"])):
                dif.append(f"{m} {x}-{y}")
        f12 = u.get("skeleton_edit_F1_minus_F2", {})
        p12, ci12 = b.diff("skeleton_edit", "F1", "F2")
        if not f12 or abs(f12["point"] - p12) > 1e-9 or any(abs(p - q) > 1e-9 for p, q in zip(ci12, f12["ci"])):
            dif.append("skeleton_edit_F1_minus_F2")
        if mult["n_contrasts_computed"] != len(CONTRASTS17) or abs(mult["bonferroni_alpha"] - alpha) > 1e-15:
            dif.append("n_contrasts / alpha")
        out.append(Check("I-15", "independent bootstrap reproduces uncertainty.json multiplicity block (17 contrasts, "
                         "95% and Bonferroni) and skeleton_edit_F1_minus_F2",
                         "PASS" if not dif else "FAIL",
                         "all 17 x (95%, Bonferroni) and the F1-F2 block equal to 1e-9" if not dif else f"differ: {dif}"))

    # I-16 the balanced-design equivalence stated in Appendix D
    w = balanced_equivalence(ctx)
    out.append(Check("I-16", "percentile bootstrap of rate differences = bootstrap of the mean of the 20 "
                     "certificate-level differences (Appendix D)", "PASS" if w < 1e-9 else "FAIL",
                     f"max deviation {w:.1e} over 10,000 resamples x 17 contrasts"))

    # I-20 (10 Oct, round 2) the ten pairwise structural-edit contrasts in
    # uncertainty.json, 95% and Bonferroni over 19 (Appendix D, F1-F4a / F1-F4b)
    pw = u.get("skeleton_edit_pairwise")
    if pw is None:
        out.append(Check("I-20", "uncertainty.json skeleton_edit_pairwise", "FAIL",
                         "absent: the F1-F4a / F1-F4b intervals of Appendix D have no saved source"))
    else:
        dif, n19 = [], len(CONTRASTS17) + 2
        for i, x in enumerate(CONDS):
            for y in CONDS[i + 1:]:
                js = pw.get(f"{x}-{y}")
                p, ci = b.diff("skeleton_edit", x, y)
                bc = b.diff_alpha("skeleton_edit", x, y, 0.05 / n19)
                if js is None or abs(js["point"] - p) > 1e-9 or any(
                        abs(q - r) > 1e-9 for q, r in zip(ci + bc, js["ci"] + js["ci_bonferroni_19"])):
                    dif.append(f"{x}-{y}")
        out.append(Check("I-20", "independent bootstrap reproduces uncertainty.json skeleton_edit_pairwise "
                         "(10 pairs: point, 95%, Bonferroni over 19)", "PASS" if not dif else "FAIL",
                         f"all {len(pw)} pairs equal to 1e-9" if not dif else f"differ: {dif}"))

    # I-17 detectable_effect.json self-checks and its link to the real data
    try:
        d = de(ctx)
        obs = d["observed"]["resolved_ex_refusal"]["successes_of_60"]
        rec = {x: ctx.count(lambda a: a["resolved"] and not a["resolved_by_refusal"], x) for x in CONDS}
        flags = d["observed"]["validation"]
        ok = (obs == rec and flags["literal_rule_matches_paper_function_on_real_data"]
              and all(flags["literal_rule_reproduces_uncertainty_json"].values()))
        out.append(Check("I-17", "detectable_effect.json: observed successes equal attempts.jsonl; its literal "
                         "rule reproduces uncertainty.json and the paper's cluster_bootstrap",
                         "PASS" if ok else "FAIL",
                         f"observed {obs} vs recomputed {rec}; flags {flags}; git commit {d.get('git_commit', '?')[:7]}"))
    except NotRecomputable as e:
        out.append(Check("I-17", "detectable_effect.json", "FAIL", str(e)))

    # I-18 hand-written probes and the clean repair, re-scored from the released
    # trajectories, agree with the committed artefacts (dsl_expressiveness.json
    # fixed counts, baseline_eval.json, clean_repair_validation.json)
    try:
        L = probe_scores(ctx)
        crv = ctx.json("data/results/clean_repair_validation.json")
        all20 = crv["test_1_generalisation"]["all_20"]
        t2 = crv["test_2_rss_stability"]
        reps = L["repeats"]
        chk = {
            "baseline fixed/completed vs baseline_eval": (
                {(r["fixed"], r["completed"]) for r in L["baseline"]}
                == {(sum(1 for v in ctx.baseline_eval.values() if v["resolved"]),
                     sum(1 for v in ctx.baseline_eval.values() if v["ce_completed"]))}),
            "fixA fixed vs dsl_expressiveness": {r["fixed"] for r in L["fixA"]}
            == {frac_str(dsl_variant(ctx, "raise OncomingGapExceeds")["fixed"])[0]},
            "sweeps fixed": {r["fixed"] for r in L["sweep"]}
            == {frac_str(dsl_variant(ctx, "add OncomingGapExceeds guard")["fixed"])[0]},
            "geometric fixed": {r["fixed"] for r in L["geometric"]}
            == {frac_str(dsl_variant(ctx, "add PathIsClear to branch C")["fixed"])[0]},
            "true stop fixed/completed": {(r["fixed"], r["completed"]) for r in L["truestop"]}
            == {(frac_str(dsl_variant(ctx, "true stop")["fixed"])[0],
                 frac_str(dsl_variant(ctx, "true stop")["completed"])[0])},
            "clean repair 20/20 vs clean_repair_validation": {(r["fixed"], r["completed"]) for r in L["clean"]}
            == {(frac_str(all20["resolved_and_completed"])[0], frac_str(all20["resolved_and_completed"])[0])},
            "six repeats vs clean_repair_validation": (
                len(reps) == t2["repeats"] and len({e["rho"] for e in reps}) == 1
                and len({e["rho4"] for e in reps}) == 1 and all(e["contract"] != "C4" for e in reps)
                and t2["rho_spread"] == 0.0 and t2["C4_spread_m"] == 0.0 and not t2["C4_ever_binding"]),
        }
        out.append(Check("I-18", f"probe trajectories ({PROBE_DIR}/) re-scored with src/stl.py reproduce the "
                         "committed probe artefacts (expressiveness table, clean-repair validation)",
                         "PASS" if all(chk.values()) else "FAIL",
                         "; ".join(f"{k}: {v}" for k, v in chk.items())
                         + f"; geometric variants scored: {[r['dir'] for r in L['geometric']]}"))
    except NotRecomputable as e:
        out.append(Check("I-18", "probe trajectories", "FAIL", f"released trajectories not re-scorable: {e}"))

    # I-21 the released probe trajectories are the files their manifest lists
    try:
        man = ctx.json(f"{PROBE_DIR}/manifest.json")
        root = ctx.p(PROBE_DIR)
        bad, nbytes = [], 0
        for f in man["files"]:
            q = root / f["path"]
            if not q.is_file():
                bad.append(f"missing {f['path']}")
                continue
            b = q.read_bytes()
            nbytes += len(b)
            if len(b) != f["bytes"] or hashlib.sha256(b).hexdigest() != f["sha256"]:
                bad.append(f"differs {f['path']}")
        listed = {f["path"] for f in man["files"]} | {"manifest.json"}
        extra = sorted(str(q.relative_to(root)) for q in root.rglob("*") if q.is_file()
                       and str(q.relative_to(root)) not in listed)
        ok = not bad and not extra and len(man["files"]) == man["n_files"] and nbytes == man["total_bytes"]
        out.append(Check("I-21", f"{PROBE_DIR}/manifest.json: every listed file present with its size and sha256, "
                         "and nothing unlisted", "PASS" if ok else "FAIL",
                         f"{len(man['files']) - len(bad)}/{man['n_files']} verified, {nbytes} bytes"
                         + (f"; problems {bad[:5]}" if bad else "") + (f"; unlisted {extra[:5]}" if extra else "")))
    except Exception as e:
        out.append(Check("I-21", f"{PROBE_DIR}/manifest.json", "FAIL", f"{type(e).__name__}: {e}"))

    # I-23 the committed outputs of scripts/rescore_dsl_probes.py agree, episode
    # by episode, with the independent re-score here
    try:
        L = probe_scores(ctx)
        mine = {f"{r['dir']}/{e['file']}": e for g in L if g != "repeats" for r in L[g] for e in r["episodes"]}
        mine.update({f"repeats/{e['file']}": e for e in L["repeats"]})
        theirs = {}
        for row in ctx.json("data/results/dsl_probe_rescore.json")["rows"].values():
            for v in row["variants"]:
                for e in v["episodes"]:
                    theirs[e["file"]] = e
        cr = ctx.json("data/results/clean_repair_rescore.json")
        for e in cr["episodes"] + cr["repeats"]["episodes"]:
            theirs.setdefault(e["file"], e)
        diff = []
        for k, e in theirs.items():
            m = mine.get(k)
            if m is None:
                diff.append(f"{k}: not re-scored here")
                continue
            same = (abs(m["rho"] - e["rho"]) <= 5e-7 and m["contract"] == e["argmin_contract"]
                    and (m["fixed"], m["completed"], m["entered"]) == (e["resolved"], e["completed"], e["entered"])
                    and (m["rho4"] is None or abs(m["rho4"] - e["per_contract"]["C4"]) <= 5e-7))
            if not same:
                diff.append(k)
        unmatched = sorted(set(mine) - set(theirs))
        out.append(Check("I-23", "data/results/dsl_probe_rescore.json and clean_repair_rescore.json agree episode by "
                         "episode with the re-score here (rho and rho_4 to 6 decimals, argmin, fixed, completed, "
                         "entered)", "PASS" if not diff and not unmatched else "FAIL",
                         f"{len(theirs) - len(diff)}/{len(theirs)} episodes agree"
                         + (f"; differ {diff[:5]}" if diff else "")
                         + (f"; re-scored here but absent from the outputs {unmatched[:5]}" if unmatched else "")))
    except Exception as e:
        out.append(Check("I-23", "rescore outputs", "FAIL", f"{type(e).__name__}: {e}"))

    # I-22 the frozen baseline's calibration episodes, re-scored here, agree with
    # baseline_calibration_frozen.json (scripts/rescore_calibration.py) episode by episode
    try:
        x = calib_local(ctx)
        bf = ctx.json("data/results/baseline_calibration_frozen.json")
        tot = bf["totals"]
        sc = {s_["index"]: s_ for s_ in bf["scenarios"]}
        diff = [p_["index"] for p_ in x["per"] if p_["index"] not in sc
                or sc[p_["index"]]["param_hash"] != p_["param_hash"]
                or abs(sc[p_["index"]]["rho"] - p_["rho"]) > 5e-7
                or sc[p_["index"]]["argmin_contract"] != p_["contract"]
                or sc[p_["index"]]["entered"] != p_["entered"]
                or sc[p_["index"]]["reached_P4_settle"] != p_["settled"]
                or sc[p_["index"]]["violated"] != (p_["rho"] < 0)]
        tots = (tot["n_scored"], tot["violations"], tot["entered"], tot["completed"], tot["argmin_contract"])
        here = (x["n"], x["violations"], x["entered"], x["settled"], x["argmin"])
        ok = not diff and len(sc) == x["n"] and tots == here and bf.get("all_checks_pass") is True
        out.append(Check("I-22", f"calibration trajectories ({x['dir']}/) re-scored here agree with "
                         "data/results/baseline_calibration_frozen.json, episode by episode and in total",
                         "PASS" if ok else "FAIL",
                         f"{x['n'] - len(diff)}/{x['n']} episodes agree; totals here (n, violations, entered, "
                         f"completed, argmin) {here}, file {tots}" + (f"; differ at {diff[:5]}" if diff else "")))
    except NotRecomputable as e:
        out.append(Check("I-22", "calibration trajectories", "FAIL", f"not re-scorable: {e}"))
    except Exception as e:
        out.append(Check("I-22", "calibration trajectories", "FAIL", f"{type(e).__name__}: {e}"))

    # I-19 release hygiene: the sources the numbers rest on are committed, and
    # no released input is git-ignored. Not a numerical failure, so WARN.
    if shutil.which("git") and ctx.p(".git").exists():
        gl = lambda *a: [x for x in subprocess.run(["git", "-C", str(ctx.repo), "ls-files", *a],
                                                   capture_output=True, text=True).stdout.splitlines() if x]
        need = ["data/results/uncertainty.json", "data/results/detectable_effect.json",
                "scripts/uncertainty.py", "scripts/detectable_effect.py", "scripts/reproduce_paper_numbers.py",
                "paper/figures/make_figures.py", "paper/checklist.tex", "src/certificate.py",
                "scripts/rescore_dsl_probes.py", "scripts/rescore_calibration.py",
                "data/results/dsl_probe_rescore.json", "data/results/clean_repair_rescore.json",
                "data/results/baseline_calibration_frozen.json",
                "data/scenarios/dsl_probe/geometric_guard_16m.bt", "data/scenarios/dsl_probe/geometric_guard_32m.bt"]
        st = {}
        for f in need:
            tracked = bool(gl("--", f))
            dirty = tracked and subprocess.run(["git", "-C", str(ctx.repo), "diff", "--quiet", "HEAD", "--", f],
                                               capture_output=True).returncode != 0
            st[f] = "untracked" if not tracked else ("modified, uncommitted" if dirty else "committed")
        bad = {k: v for k, v in st.items() if v != "committed"}
        inputs = ["data/certificates/traces", PROBE_DIR, CALIB_DIR, "logs/campaign/prompts",
                  "logs/campaign/responses", "logs/llm_raw/synth_*.json", "logs/e1_phase_a.log", "logs/e1_phase_b.log"]
        inp, lost = {}, {}
        for pth in inputs:
            tr, un, ig = (len(gl("--", pth)), len(gl("-o", "--exclude-standard", "--", pth)),
                          len(gl("-o", "-i", "--exclude-standard", "--", pth)))
            inp[pth] = f"{tr} tracked" + (f", {un} untracked" if un else "")
            if ig:
                lost[pth] = ig
        inp_bad = {k: v for k, v in inp.items() if "untracked" in v or v.startswith("0 tracked")}
        out.append(Check("I-19", "release hygiene: sources of the numbers committed; released inputs tracked and "
                         "not git-ignored", "WARN" if bad or inp_bad or lost else "PASS",
                         (f"sources not committed: {bad}" if bad else "sources all committed")
                         + (f"; released inputs not (all) committed: {inp_bad}" if inp_bad
                            else f"; released inputs all tracked: {inp}")
                         + (f"; git-ignored files under released inputs (missing from a clone): {lost}" if lost else "")
                         + "; LOCAL (unreleased) sources present here: data/traces/ "
                         + ("yes" if ctx.p("data/traces").is_dir() else "no") + ", logs/llm_raw/ other than synth_*: "
                         + str(len([q for q in ctx.p("logs/llm_raw").glob("*.json") if not q.name.startswith("synth_")])
                               if ctx.p("logs/llm_raw").is_dir() else 0)))
    return out


# =============================================================================
# Coverage scan: numbers in the body that no claim accounts for
# =============================================================================
MASKS = [
    r"CC BY 4\.0",                       # licence name, not a measurement
    r"\\(?:ref|label|cite[tp]?|includegraphics|bibliography|bibliographystyle|usepackage|documentclass)"
    r"(?:\[[^\]]*\])?\{[^}]*\}",
    r"\\includegraphics\[[^\]]*\]", r"\\itemsep\d+pt", r"\\rhoc\{[^}]*\}", r"rule~\d", r"Lemma~?\s*\d",
    # "$95\%$" only where it names the interval level (until 10 Oct every
    # "$95\%$" was masked, which hid "$95\%$ for the unpatched baseline").
    r"\\begin\{tabular\}\{[^}]*\}", r"\$95\\%\$(?=\s+(?:percentile\s+)?intervals?\b)", r"m/s\$\^2\$",
    r"\\citet\{[^}]*\}", r"pass@1",
    # Definitions, not measurements: the sign convention of robustness (>= 0 is
    # satisfied), the precondition H(node | contract) > 0, and a column header.
    r"\\geq\s*[01]\b", r"\\Hnc\s*>\s*0",
    # Camera-ready additions (10 Oct): layout arguments, the model's name,
    # licence names, the precondition written out in the checklist, and the
    # "Broke >= 1 regression" row label of Table 6 (a definition).
    r"\\multicolumn\{\d+\}", r"\\cmidrule\(lr\)\{\d+-\d+\}", r"claude-opus-5",
    r"0BSD|CC0-1\.0|Apache-2\.0|BSD-3-Clause|BSD\s+3-clause|CC-BY\s+4\.0",
    r"\\mid\\mathrm\{contract\}\)\s*>\s*0", r"95\\%\s+percentile", r"Town05", r"\\ge\s*0\b",
]


def coverage(tex: str | Src, claim_list: list[Claim]) -> list[tuple[str, str, str]]:
    src = tex if isinstance(tex, Src) else Src(tex, [(0, "main.tex", tex)])
    text = src.text
    start = text.find(r"\begin{document}")
    end = text.find(r"\end{document}")
    # Scanned: the body of main.tex, and in an \input checklist only the
    # "Justification:" answers (the question and guideline text is the
    # template's, not the paper's).
    spans = [(max(start, 0), end if 0 < end < src.main_len() else src.main_len())]
    for off, label, body in src.parts[1:]:
        for m in re.finditer(r"\\item\[\]\s*Justification:(.*?)(?=\\item\[\]|\\item\s*\{\\bf|\\end\{enumerate\}|\Z)",
                             body, re.S):
            spans.append((off + m.start(1), off + m.end(1)))
    masked = list(text)
    for rx in MASKS:
        for m in re.finditer(rx, text):
            for i in range(m.start(), m.end()):
                masked[i] = " "
    for m in re.finditer(r"(?<!\\)%.*", text):           # comments
        for i in range(m.start(), m.end()):
            masked[i] = " "
    mtext = "".join(masked)
    covered = []
    for cl in claim_list:
        # Only the match the claim actually evaluates counts as coverage. (Until
        # 10 Oct every match counted, so a sentence repeated verbatim, such as
        # the abstract's 76.7-point interval in Section 4.1, was reported as
        # covered although only its first occurrence was ever checked.)
        ms = list(re.finditer(cl.pattern, text, re.S))
        if len(ms) <= cl.occurrence:
            continue
        m = ms[cl.occurrence]
        for g in m.groupdict():
            if m.group(g) is not None:
                covered.append((m.start(g), m.end(g)))
    out = []
    for m in re.finditer(r"(?<![\\\w^.])\d+(?:\{,\}\d{3})*(?:\.\d+)*", mtext):
        if not any(s <= m.start() < e for s, e in spans):
            continue
        if any(s <= m.start() < e for s, e in covered):
            continue
        fname, line = src.where(m.start())
        ctx_txt = re.sub(r"\s+", " ", text[max(0, m.start() - 40): m.end() + 30])
        out.append((line if fname == "main.tex" else f"{fname}:{line}", m.group(0), ctx_txt))
    return out


NUMBER_WORDS = (r"\b(?:zero|one|once|two|twice|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|"
                r"fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|hundred|half|quarters?)\b")


def word_coverage(tex: str | Src, claim_list: list[Claim]) -> list[tuple[str, str, str]]:
    """INFORMATIONAL (10 Oct, round 2). Number WORDS in the body of main.tex
    that no claim evaluates. The digit scan above cannot see them. Most are
    enumerations or definitions ('three criteria', 'at least one', 'Second,'),
    so this list does not affect the exit code; it is printed so that a
    quantitative claim written in words is noticed and registered."""
    src = tex if isinstance(tex, Src) else Src(tex, [(0, "main.tex", tex)])
    text = src.text
    start, end = text.find(r"\begin{document}"), min(text.find(r"\end{document}"), src.main_len())
    masked = re.sub(r"(?<!\\)%.*", lambda m: " " * len(m.group(0)), text)
    covered = []
    for cl in claim_list:
        ms = list(re.finditer(cl.pattern, text, re.S))
        if len(ms) > cl.occurrence:
            m = ms[cl.occurrence]
            covered += [(m.start(g), m.end(g)) for g in m.groupdict() if m.group(g) is not None]
    out = []
    for m in re.finditer(NUMBER_WORDS, masked, re.I):
        if not (start <= m.start() < end) or any(s <= m.start() < e for s, e in covered):
            continue
        _f, line = src.where(m.start())
        out.append((line, m.group(0), re.sub(r"\s+", " ", text[max(0, m.start() - 40): m.end() + 30])))
    return out


# =============================================================================
# Figures (numbers printed inside the data figures, via pdftotext if present)
# =============================================================================
def figure_rows(ctx: Ctx, tex_path: pathlib.Path, version: str = "v1.1") -> list[Row]:
    rows: list[Row] = []
    figdir = tex_path.parent / "figures"
    if not (figdir / "fig4_funnel.pdf").exists():      # tex copied elsewhere: use the repo's figures
        figdir = ctx.repo / "paper" / "figures"
    if not figdir.is_dir():
        return [Row("FIG", None, "figure text", "", "", "NOT-FOUND", "-", f"no figures directory at {figdir}")]
    if not shutil.which("pdftotext"):
        return [Row("FIG", None, "figure text", "", "", "NOT-RECOMPUTABLE", "-", "pdftotext not installed")]

    def text(name):
        f = figdir / name
        if not f.exists():
            return None
        return subprocess.run(["pdftotext", "-layout", str(f), "-"], capture_output=True, text=True).stdout

    t3 = text("fig3_patch_type.pdf")
    if t3:
        for cond in CONDS:
            m = re.search(rf"^\s*{cond}\s+(\d+)\s*$", t3, re.M)
            want = skel_recomputed(ctx, cond)
            if m:
                rows.append(Row(f"FIG3-{cond}", None, f"structural-edit bars, fig3_patch_type.pdf (printed Figure 4): {cond}", m.group(1), str(want),
                                "MATCH" if int(m.group(1)) == want else "MISMATCH",
                                "recomputed: patch type from source", "figures/fig3_patch_type.pdf"))
    t4 = text("fig4_funnel.pdf")
    if t4:
        A = ctx.attempts
        want = {
            "attempts": len(A),
            "satisfied the contract": sum(1 for a in A if a["resolved"]),
            "not by refusing to drive": sum(1 for a in A if a["resolved"] and not a["resolved_by_refusal"]),
            "and completed the turn": sum(1 for a in A if a["resolved_and_completed"]),
            "and broke nothing": sum(1 for a in A if is_clean(a)),
        }
        # Camera-ready (round 2) labels: S, then entered, then C, then R.
        want.update({
            "satisfied the contracts": sum(1 for a in A if a["resolved"]),
            "and entered the conflict zone": sum(1 for a in A if a["resolved"] and not a["resolved_by_refusal"]),
            "and regression suite intact": sum(1 for a in A if is_clean(a)),
        })
        fig4_ids = {"attempts": "attempts", "satisfied the contract": "satisfied-v10",
                    "not by refusing to drive": "drive-v10", "and completed the turn": "turn",
                    "and broke nothing": "nothing-v10", "satisfied the contracts": "satisfied",
                    "and entered the conflict zone": "entered", "and regression suite intact": "intact"}
        found = 0
        for label, w in want.items():
            # one bar label per line in pdftotext -layout output: "<label>   <n>"
            m = re.search(rf"^\s*{re.escape(label)}\s+(\d+)\s*$", t4, re.M)
            if m:
                found += 1
                rows.append(Row(f"FIG4-{fig4_ids[label]}", None, f"funnel, fig4_funnel.pdf (printed Figure 2): {label}", m.group(1), str(w),
                                "MATCH" if int(m.group(1)) == w else "MISMATCH", A_ATT,
                                "figures/fig4_funnel.pdf"))
        if found < 5:
            rows.append(Row("FIG4-bars", None, "funnel, fig4_funnel.pdf (printed Figure 2): five bar labels read", str(found), "5",
                            "MISMATCH", "pdftotext", "a funnel bar label was not recognized; update the labels here"))
        k, n = sum(1 for a in A if a["resolved_by_refusal"]), sum(1 for a in A if a["resolved"])
        p = round_like(pct(k, n), "72")
        for rx, lab in ((r"(\d+) of (\d+) apparent repairs \((\d+)%\)", "refusals of apparent repairs"),
                        (r"(\d+) of the (\d+) that satisfied the contracts \((\d+)%\) never entered",
                         "refusals of those satisfying the contracts")):
            m = re.search(rx, t4)
            if m:
                ok = (int(m.group(1)), int(m.group(2)), decimal.Decimal(m.group(3))) == (k, n, p)
                rows.append(Row("FIG4-title", None, f"funnel title, fig4_funnel.pdf (printed Figure 2): {lab}",
                                f"{m.group(1)} of {m.group(2)} ({m.group(3)}%)", f"{k} of {n} ({p}%)",
                                "MATCH" if ok else "MISMATCH", A_ATT, "figures/fig4_funnel.pdf"))
    # Camera-ready (10 Oct): the x-axis label of the structural-edit figure.
    if t3:
        m = re.search(r"of\s+(\d+)\s+attempts", t3)
        if m:
            want = single_val({len(ctx.by_cond(x)) for x in CONDS})
            rows.append(Row("FIG3-xlabel", None, "structural-edit bars, fig3_patch_type.pdf (printed Figure 4): x label, of N attempts", m.group(1),
                            str(want), "MATCH" if int(m.group(1)) == want else "MISMATCH", A_ATT,
                            "figures/fig3_patch_type.pdf"))
    # The regeneration and plotted-coordinate checks test the CURRENT
    # make_figures.py against the included PDFs, so they apply to the
    # camera-ready only (the submitted figures came from an earlier version of
    # the script, with its own 4,000-resample bootstrap for Figure 2).
    if version == "v1.1":
        rows += fig2_rows(ctx, figdir)
    return rows


def regenerate_figures(ctx: Ctx, figdir: pathlib.Path):
    """Run paper/figures/make_figures.py's three data-figure functions without
    touching the repository: `save` is redirected to a temporary directory and
    the figure objects are kept, so the plotted coordinates can be read back.
    Returns ({name: Figure}, {name: identical-to-the-included-PDF?})."""
    import importlib.util
    import tempfile
    mf_path = ctx.p("paper/figures/make_figures.py")
    spec = importlib.util.spec_from_file_location("_make_figures_check", mf_path)
    mf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mf)
    figs, same = {}, {}
    # make_figures.py saves with SAVE_METADATA (no /CreationDate), so a rerun is
    # byte-identical to the included PDF; the strip only matters for an older
    # make_figures.py that still stamps the date.
    meta = getattr(mf, "SAVE_METADATA", {}).get("pdf")
    strip = lambda b: re.sub(rb"/CreationDate \([^)]*\)\s*", b"", b)
    with tempfile.TemporaryDirectory() as td:
        tdp = pathlib.Path(td)

        def save(fig, name):
            fig.savefig(tdp / f"{name}.pdf", bbox_inches="tight", metadata=meta)
            figs[name] = fig

        mf.save = save
        rows = mf.load()
        for fn in (mf.fig_uncertainty, mf.fig_patch_type, mf.fig_funnel):
            fn(rows)
        for name in figs:
            inc = figdir / f"{name}.pdf"
            same[name] = inc.exists() and strip((tdp / f"{name}.pdf").read_bytes()) == strip(inc.read_bytes())
    return figs, same


def fig2_rows(ctx: Ctx, figdir: pathlib.Path) -> list[Row]:
    """Every interval plotted in the uncertainty figure, read back from the
    figure object that make_figures.py builds, against the bootstrap here."""
    try:
        figs, same = regenerate_figures(ctx, figdir)
    except Exception as e:
        return [Row("FIG2", None, "uncertainty figure", "", "", "NOT-RECOMPUTABLE", "-",
                    f"could not regenerate the figure: {type(e).__name__}: {e}")]
    out = [Row(f"FIG-regen-{n.split('_')[0]}", None, f"{n}.pdf is what make_figures.py draws from the data",
               "included PDF", "identical" if ok else "DIFFERS",
               "MATCH" if ok else "MISMATCH", "recomputed: make_figures.py run in a temporary directory",
               f"figures/{n}.pdf") for n, ok in sorted(same.items())]
    fig = figs.get("fig2_uncertainty")
    if fig is None:
        return out
    b = ctx.boot
    keys = {"pre-specified": "resolved", "refusals excluded": "resolved_ex_refusal", "structural": "skeleton_edit"}
    others = ["F1", "F2", "F4a", "F4b"]
    highlighted, excluding = set(), set()
    for ax in fig.axes:
        title = ax.get_title().replace("\n", " ")
        m = next((v for k, v in keys.items() if k in title), None)
        if m is None:
            continue
        segs = {}
        for ln in ax.get_lines():
            x, y = list(ln.get_xdata()), list(ln.get_ydata())
            if len(y) == 2 and y[0] == y[1] and x[0] != x[1]:
                segs[int(round(y[0]))] = (min(x), max(x), ln.get_color())
        pts = {int(round(yy)): xx for coll in ax.collections for xx, yy in coll.get_offsets()}
        for i, cond in enumerate(others):
            lo, hi, col = segs[i]
            pt = pts[i]
            p, (blo, bhi) = b.diff(m, cond, "F3")
            ok = max(abs(lo - blo), abs(hi - bhi), abs(pt - p)) < 1e-9
            if col.lower() != "#151a16":
                highlighted.add((m, cond))
            if not ci_contains_zero(blo, bhi):
                excluding.add((m, cond))
            out.append(Row(f"FIG2-{m}-{cond}", None, f"uncertainty, fig2_uncertainty.pdf (printed Figure 3): {m}, {cond} - F3 (point, 95% CI)",
                           f"{pt:+.1f} [{lo:+.1f},{hi:+.1f}]", f"{p:+.1f} [{blo:+.1f},{bhi:+.1f}]",
                           "MATCH" if ok else "MISMATCH", A_BOOT,
                           "plotted coordinates read from the figure object (to 1e-9)"))
    out.append(Row("FIG2-highlight", None, "uncertainty, fig2_uncertainty.pdf (printed Figure 3): highlighted intervals = those excluding zero",
                   str(sorted(highlighted)), str(sorted(excluding)),
                   "MATCH" if highlighted == excluding else "MISMATCH", A_BOOT, "figures/fig2_uncertainty.pdf"))
    return out


# =============================================================================
# Driver
# =============================================================================
def detect_version(tex: str) -> str:
    """v1.1 (camera-ready) loads the style with [final]; v1.0 (submitted) did not."""
    return "v1.1" if re.search(r"\\usepackage\[final\]\{neurips", tex) else "v1.0"


def run(tex_path: str | pathlib.Path = REPO / "paper/main.tex", repo: pathlib.Path = REPO,
        version: str | None = None, local: bool = True):
    tex_path = pathlib.Path(tex_path)
    src = load_src(tex_path)
    version = version or detect_version(src.parts[0][2])
    ctx = Ctx(repo, local=local)
    cl = [c for c in claims() if c.only in (None, version)]
    rows = [evaluate(c, src, ctx) for c in cl]
    order = {p[1]: k for k, p in enumerate(src.parts)}
    rows.sort(key=lambda r: (r.line is None, order.get(r.file, 99), r.line or 0, r.cid))
    rows += figure_rows(ctx, tex_path, version)
    checks = integrity(ctx)
    cov = coverage(src, cl)
    run.version = version
    run.word_coverage = word_coverage(src, cl)
    return rows, checks, cov


def md_escape(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")


def to_markdown(rows: list[Row], checks: list[Check], cov, tex_path) -> str:
    out = []
    counts = collections.Counter(r.status for r in rows)
    out.append(f"Tex: `{tex_path}`. Claims: {len(rows)}. " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    out.append("")
    out.append("| id | tex line | claim | paper | recomputed | status | basis | note |")
    out.append("|---|---|---|---|---|---|---|---|")
    for r in rows:
        out.append("| " + " | ".join(md_escape(x) for x in [
            r.cid, r.where(), r.desc, r.paper, r.recomputed, r.status, r.basis, r.note]) + " |")
    out.append("")
    out.append("| check | description | status | detail |")
    out.append("|---|---|---|---|")
    for c in checks:
        out.append(f"| {c.cid} | {md_escape(c.desc)} | {c.status} | {md_escape(c.detail)} |")
    out.append("")
    if cov:
        out.append("Unregistered numbers in the document body:")
        out.append("")
        for line, num, ctx_txt in cov:
            out.append(f"- line {line}: `{num}` in \"{md_escape(ctx_txt)}\"")
    else:
        out.append("Unregistered numbers in the document body: none.")
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("tex", nargs="?", default=str(REPO / "paper/main.tex"))
    ap.add_argument("--markdown", help="write the ledger as a markdown table to this path")
    ap.add_argument("--json", help="write the ledger as JSON to this path")
    ap.add_argument("--strict", action="store_true",
                    help="also fail on NOT-FOUND claims and unregistered numbers")
    ap.add_argument("--version", choices=["v1.0", "v1.1"],
                    help="which registry to apply (default: detected from the tex; v1.1 = camera-ready)")
    ap.add_argument("--no-local", action="store_true",
                    help="skip every LOCAL (unreleased) source: data/traces/ and logs/llm_raw/ other than synth_*; the result is what a fresh clone of the released repository computes")
    a = ap.parse_args(argv)

    rows, checks, cov = run(a.tex, version=a.version, local=not a.no_local)
    print(f"registry: {run.version}  ({'LOCAL (unreleased) sources used where present' if not a.no_local else 'LOCAL sources skipped: fresh-clone mode'})")
    w = [11, 18, 46, 22, 30, 16]
    print(f"{'id':<{w[0]}} {'line':>{w[1]}}  {'claim':<{w[2]}} {'paper':<{w[3]}} {'recomputed':<{w[4]}} status")
    print("-" * 150)
    for r in rows:
        print(f"{r.cid:<{w[0]}} {r.where():>{w[1]}}  {r.desc[:w[2]]:<{w[2]}} "
              f"{r.paper[:w[3]]:<{w[3]}} {r.recomputed[:w[4]]:<{w[4]}} {r.status}"
              + (f"\n{'':>{w[0] + w[1] + 3}}basis: {r.basis}" if r.status != "MATCH" else "")
              + (f"\n{'':>{w[0] + w[1] + 3}}note: {r.note}" if r.note and r.status != "MATCH" else ""))
    print("\nINTEGRITY")
    for c in checks:
        print(f"  {c.cid:<6} {c.status:<5} {c.desc}\n         {c.detail}")
    print("\nCOVERAGE: numbers in the body not accounted for by any claim")
    for line, num, ctx_txt in cov:
        print(f"  line {line:>4}: {num:<10} ...{ctx_txt}...")
    if not cov:
        print("  none")
    wc = getattr(run, "word_coverage", [])
    print(f"\nWORD COVERAGE (informational, not in the exit code): {len(wc)} number words in the body that no "
          "claim evaluates; most are enumerations or definitions")
    for line, w_, ctx_txt in wc:
        print(f"  line {line:>4}: {w_:<9} ...{ctx_txt}...")

    counts = collections.Counter(r.status for r in rows)
    print(f"\nSUMMARY [{run.version}]  " + "  ".join(f"{k}={v}" for k, v in sorted(counts.items()))
          + f"  integrity_fail={sum(1 for c in checks if c.status == 'FAIL')}"
          + f"  integrity_warn={sum(1 for c in checks if c.status == 'WARN')}"
          + f"  unregistered_numbers={len(cov)}")

    if a.markdown:
        pathlib.Path(a.markdown).write_text(to_markdown(rows, checks, cov, a.tex))
    if a.json:
        pathlib.Path(a.json).write_text(json.dumps({
            "tex": a.tex,
            "version": run.version,
            "rows": [dataclasses.asdict(r) for r in rows],
            "integrity": [dataclasses.asdict(c) for c in checks],
            "unregistered_numbers": [{"line": l, "number": n, "context": t} for l, n, t in cov],
            "unregistered_number_words_info": [{"line": l, "word": n, "context": t}
                                               for l, n, t in getattr(run, "word_coverage", [])],
        }, indent=2))

    fail = counts.get("MISMATCH", 0) > 0 or any(c.status == "FAIL" for c in checks)
    if a.strict:
        fail |= counts.get("NOT-FOUND", 0) > 0 or bool(cov)
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
