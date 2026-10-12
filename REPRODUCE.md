# Reproducing the paper

Every table and figure in the paper is either recomputed from files in this repository or,
where it needed the simulator or the API (Table 2's and Table 5's token counts, the Section 3
simulator figures), checked against the released saved output; Figure 1 is a static schematic.
None of this needs the simulator, an API key or network access (apart from installing packages
and Tectonic's first download). This file gives the environment, the full offline verification
sequence with the expected output of each command, and a map from every element of the paper
to the inputs and script behind it. Parts that need CARLA or the model API are listed at the
end; they were not re-run for this release.

All commands run from the repository root. Run times are from the authors' machine (AMD Ryzen 9
9900X, 24 threads).

## 1. Environment

The paper's environment is recorded in [`docs/env_manifest.md`](docs/env_manifest.md):
Linux x86_64, CPython 3.12.3, packages pinned in [`requirements.txt`](requirements.txt), with
the resolved dependency graph in [`requirements.lock.txt`](requirements.lock.txt).

```bash
uv venv --python 3.12 .venv
VIRTUAL_ENV=.venv uv pip install -r requirements.txt
```

For this release, fresh environments were created from `requirements.txt` with uv 0.11.7
(installing from uv's local cache): one complete, and one without `carla`, `anthropic` and the
packages only `anthropic` needs. Every offline command below ran in both on a copy of the
release tree and gave the output shown, including the ledger's MATCH=315 summary (2.13 reads
the `anthropic` version from the pin in `requirements.txt`). So if `carla` (the wheel used here
is CPython 3.12, `manylinux_2_31_x86_64`) does not install on your platform, remove it from
`requirements.txt`; the ledger then reports the rows that read the `carla` pin (CHK-16, CHK-27,
CHK-27b) as NOT-RECOMPUTABLE, and everything else is unchanged.

Other requirements:

- **pytest is not used.** Each test file runs as a script.
- **Fonts.** The figures are byte-identical to the committed files only when Liberation Serif
  is installed (Ubuntu package `fonts-liberation`).
- **Tectonic 0.17.0** builds the paper (section 2.14).

## 2. Offline verification sequence

| # | Command | Reproduces | Writes into the repository | Time |
|---|---|---|---|---|
| 2.1 | `scripts/uncertainty.py --out /tmp/uncertainty.json` | every interval; Table 6; data for Figure 3 | no (with `--out`) | 11 s |
| 2.2 | `scripts/analyze_e1.py --out /tmp/e1_analysis.json` | per-condition rates, Section 4.5, Appendix C | no (with `--out`) | < 1 s |
| 2.3 | inline recount | Table 3 | no | < 1 s |
| 2.4 | `paper/figures/make_figures.py` | Figures 2, 3, 4 | yes, byte-identical | 1 s |
| 2.5 | `scripts/diff_prompts.py` | Table 2 byte counts | no | 1 s |
| 2.6 | `scripts/check_attempts_schema.py` | the attempt log | no | < 1 s |
| 2.7 | `scripts/check_certificates.py` | the 20 certificates | no | < 1 s |
| 2.8 | `scripts/recompute_blame.py` | Section 4.6 entropies | yes, byte-identical | < 1 s |
| 2.9 | `scripts/rescore_dsl_probes.py --no-write` | Table 4, clean-repair validation | no (with `--no-write`) | 65 s |
| 2.10 | `scripts/rescore_calibration.py --check` | Section 3.2 calibration counts | no (with `--check`) | 21 s |
| 2.11 | `tests/test_*.py` | unit tests | no | 1 s |
| 2.12 | `scripts/detectable_effect.py --out /tmp/detectable_effect.json` | Table 7 | no (with `--out`) | 2.5 min |
| 2.13 | `scripts/reproduce_paper_numbers.py paper/main.tex --strict --no-local` | every number registered in the paper (7 not recomputable, listed below) | no | 95 s |
| 2.14 | `tectonic -X compile main.tex --outdir /tmp/paper-build` | the PDF | no (with `--outdir`) | 2 s |

Python commands are run as `.venv/bin/python <script>`. Where a command writes into the
repository, `git status --short` afterwards prints nothing, because the output is
byte-identical to the committed file. Without `--out`, `--no-write` or `--check`, scripts 2.1,
2.2, 2.9 and 2.10 rewrite their committed outputs instead, also byte-identically. Script 2.12
is different: without `--out` it rewrites `data/results/detectable_effect.json` with a new
`git_commit` and new timings, so always give it `--out`.

### 2.1 Bootstrap intervals

```bash
.venv/bin/python scripts/uncertainty.py --out /tmp/uncertainty.json
cmp /tmp/uncertainty.json data/results/uncertainty.json && echo identical
```

```
300 attempts, 20 certificates, 10000 bootstrap resamples clustered on certificate
...
REPAIR SUCCESS, refusals excluded
...
paired differences vs F3, same resampled certificates:
  F1   - F3 =   +1.7   [  -5.0,   +8.3]   CI includes 0
  F2   - F3 =   -3.3   [  -8.3,   +0.0]   CI includes 0
...
structural edit, F1 - F2 =  +76.7   [ +61.7,  +90.0]
...
17 paired differences computed; Bonferroni alpha = 0.05/17
...
identical
```

### 2.2 Per-condition analysis

```bash
.venv/bin/python scripts/analyze_e1.py --out /tmp/e1_analysis.json
cmp /tmp/e1_analysis.json data/results/e1_analysis.json && echo identical
```

```
attempts: 300   conditions: 5   certificates: 20   replicates: 3
...
cond      fix  ex-refus  fix/1k tot  fix/1k fb   malf  trunc  apierr  regfail    TED    ICR
F1      21.7%      5.0%       0.009      0.018   0.0%   0.0%    0.0%    0.700  5.933  94.1%
F2       1.7%      0.0%       0.002      0.237   0.0%   0.0%    0.0%    0.633  5.767  95.0%
F3       5.0%      3.3%       0.006      0.189   0.0%   0.0%    0.0%    1.000  6.950  93.2%
F4a      0.0%      0.0%       0.000      0.000   0.0%   0.0%    0.0%    1.117  7.383  94.9%
F4b      1.7%      0.0%       0.002      0.047   0.0%   0.0%    0.0%    0.883  4.267  95.0%
...
  13 of 18 resolutions across all conditions are refusals (72%)
...
    hole_fill       n=170  mean regression failures  0.812   resolved 3/170
    skeleton_edit   n=130  mean regression failures  0.939   resolved 15/130
...
identical
```

### 2.3 Table 3, counted directly

The three criteria are fields of each attempt record: S is `resolved`, a refusal is
`resolved_by_refusal`, entry is `ce_entered_conflict_zone`, C is `ce_completed`, and R is
`regression_failures == 0`.

```bash
.venv/bin/python - <<'EOF'
import json
rows = [json.loads(l) for l in open("data/results/attempts.jsonl")]
for c in ["F1", "F2", "F3", "F4a", "F4b"]:
    rs = [r for r in rows if r["condition"] == c]
    S = [r for r in rs if r["resolved"]]
    print(c, len(S), sum(r["resolved_by_refusal"] for r in S),
          sum(r["ce_entered_conflict_zone"] for r in S),
          sum(r["ce_completed"] for r in rs),
          sum(r["regression_failures"] == 0 for r in rs),
          sum(r["ce_completed"] for r in S),
          sum(r["ce_completed"] and r["regression_failures"] == 0 for r in S))
EOF
```

Columns: S all, refused, entered, C, R, S and C, S and C and R.

```
F1 13 10 3 7 18 1 1
F2 1 1 0 6 23 0 0
F3 3 1 2 7 16 2 0
F4a 0 0 0 7 6 0 0
F4b 1 1 0 6 13 0 0
```

### 2.4 Figures 2 to 4

```bash
.venv/bin/python paper/figures/make_figures.py
git status --short paper/figures
```

```
loaded 300 attempts
  wrote fig2_uncertainty.pdf / .png
  wrote fig3_patch_type.pdf / .png
  wrote fig4_funnel.pdf / .png
done. Figure 1 (fig1_pipeline.png) is a static schematic and is not generated here.
```

`git status` prints nothing. File names predate the camera-ready numbering: `fig4_funnel` is
Figure 2, `fig2_uncertainty` is Figure 3 and `fig3_patch_type` is Figure 4.

### 2.5 Prompt scaffolding is byte-identical across conditions

Renders all 100 prompts (20 certificates by 5 conditions). F1 prompts read the trajectories in
`data/certificates/traces/`.

```bash
.venv/bin/python scripts/diff_prompts.py
```

```
CE001_C2_44b9f97d05fda474  C2  PASS  prefix=9410f2fde79da31e  feedback_bytes=F1:24480 F2:164 F3:592 F4a:840 F4b:827
...
CE020_C1_d3346d835dab0fd8  C1  PASS  prefix=9410f2fde79da31e  feedback_bytes=F1:21607 F2:190 F3:592 F4a:840 F4b:864

byte-identity of everything outside the feedback block: PASS over 20 certificates
fixed scaffolding: 10874 bytes before the feedback block, 102 bytes after
```

The ledger (2.13) goes further: check I-09 re-renders every prompt and matches it against the
hash logged for each of the 300 attempts, and check I-10 matches every prompt saved in
`logs/campaign/prompts/` against the same hashes.

### 2.6 and 2.7 Record checks

```bash
.venv/bin/python scripts/check_attempts_schema.py
.venv/bin/python scripts/check_certificates.py
```

```
data/results/attempts.jsonl: 300 records
  ok   all 51 schema fields present on every record
...
  outcomes: {'ok': 300}
...
  resolutions: 18/300 evaluated; 13 of those are RESOLUTION BY REFUSAL (rho >= 0 because the ego never entered the junction)
...
SCHEMA CHECK PASSED
checked 20 certificates
distinct scenarios: 20 of 20
ALL CERTIFICATES SCHEMA-COMPLETE AND CONSISTENT
```

### 2.8 Blame entropy

```bash
.venv/bin/python scripts/recompute_blame.py
```

```
certificates: 20
...
active_node                   0.0000 bits                1   <- pre-specified
authorising_node              0.5000 bits                2
...
for contrast, H(contract) = 1.2345 bits -- the corpus IS varied, just not in blame
...
boundary suppression: 7/20 certificates carry a headway boundary
...
written: data/results/blame_recompute.json   (certificates NOT modified)
```

It rewrites `data/results/blame_recompute.json` byte-identically. **Never pass `--write`**: it
rewrites the certificate files in `data/certificates/` in place.

### 2.9 Table 4 and the clean-repair validation

Re-scores the 266 saved trajectories in `data/dsl_probe_traces/` (532 files with their JSON
sidecars, sha256-checked against `manifest.json`): 13 program variants on all 20
counterexamples, and six repeats of the clean repair. Definitions used: resolved means rho >= 0 (the minimum over the five
contracts, vacuous contracts skipped in the argmin); completed means the vehicle reached the
junction exit before the episode ended (phase P4_settle); entered means C2 was not vacuous,
that is, the vehicle was inside the 12 m conflict-zone disc at some tick.

```bash
.venv/bin/python scripts/rescore_dsl_probes.py --no-write
```

```
traces: 532 files, 40.0 MB, sha256 verified against manifest
paper/main.tex Table 4 cells: read, 6 rows
...
frozen baseline                                                             0/20      2/20   20/20  0/20, 2/20
                                             -> MATCH
...
geometric guard + true stop                                                20/20      0/20    0/20  20/20, 0/20, entered 0/20
                                             -> MATCH
the model's clean repair, from F1                                          20/20     20/20   20/20  20/20, 20/20
                                             -> MATCH

clean repair, own counterexample CE005_C1_5b773c94ec4bb251: rho 0.5 (binding C5), resolved True, completed True
clean repair, other 19: resolved 19/19, completed 19/19, entered 19/19, binding {'C1': 3, 'C5': 16}
six repeats on CE005_C1_5b773c94ec4bb251: rho [0.5, 0.5, 0.5, 0.5, 0.5, 0.5]
...
RESULT: Table 4 and the six-repeat validation reproduce exactly; all numeric cross-checks agree
```

Without `--no-write` it also rewrites `data/results/dsl_probe_rescore.json` and
`clean_repair_rescore.json`, byte-identically. The script reports `dsl_expressiveness.json`'s
`implication` field as SUPERSEDED (see `data/results/NOTES.md`, caveat 1), and the CE004
baseline re-run as differing from its certificate by 0.0048 in rho, with the sign unchanged.

### 2.10 Calibration counts (Section 3.2)

```bash
.venv/bin/python scripts/rescore_calibration.py --check
```

```
program
  [PASS] frozen baseline = comment-only header + candidate, byte for byte  ...
...
agreement with paper/main.tex, Section 3.2
  [PASS] n_scored  (re-scored 100, paper 100)
  [PASS] violations  (re-scored 20, paper 20)
  [PASS] entered  (re-scored 100, paper 100)
  [PASS] completed  (re-scored 90, paper 90)

totals: scored 100, entered 100, completed 90, violations 20 {'C3': 4, 'C2': 14, 'C1': 2}, status {'collision': 10, 'ok': 90}
--check: data/results/baseline_calibration_frozen.json is byte-identical
```

### 2.11 Unit tests

```bash
.venv/bin/python tests/test_certificate.py    # last line: 91/91 pass
.venv/bin/python tests/test_falsifier.py      # 45 passed, 0 failed
.venv/bin/python tests/test_ted.py            # last line: 30/30 pass
```

Each exits 0 on success.

### 2.12 Detectable effect (Table 7, Appendix E)

Simulation, parallel over all cores (about 35 CPU-minutes).

```bash
.venv/bin/python scripts/detectable_effect.py --out /tmp/detectable_effect.json
.venv/bin/python - /tmp/detectable_effect.json <<'EOF'
import json, sys
a = json.load(open("data/results/detectable_effect.json"))
b = json.load(open(sys.argv[1]))
def strip(d):
    d = {k: v for k, v in d.items() if k not in ("git_commit", "runtime_s")}
    d["simulations"] = [{k: v for k, v in s.items() if k != "seconds"} for s in d["simulations"]]
    return d
print("identical apart from git_commit and timings:", strip(a) == strip(b))
EOF
```

```
...
  p0=0.0333|icc=0.0|r=1.0                  MDE80 = 15.2 pp (grid 15.5, MC band [15.5, 15.5]) ...
  p0=0.0333|icc=0.1|r=1.0                  MDE80 = 14.2 pp ...
  p0=0.0333|icc=0.1|r=0.0                  MDE80 = 17.0 pp ...
  p0=0.0333|icc=0.3|r=1.0                  MDE80 = 13.0 pp ...
  p0=0.0333|icc=0.3|r=0.0                  MDE80 = 19.8 pp ...
...
identical apart from git_commit and timings: True
```

Table 7 reports these values rounded to whole points (`r=1.0` is "shared", `r=0.0` is
"independent"). The output file records the commit it ran at and how long each setting took;
everything else is identical.

### 2.13 Every number in the paper

`reproduce_paper_numbers.py` holds one row per quantitative claim in `paper/main.tex` and
`paper/checklist.tex`, recomputes each from the released files, and runs integrity checks
across them.

```bash
.venv/bin/python scripts/reproduce_paper_numbers.py paper/main.tex --strict --no-local
```

`--no-local` restricts the script to the released files. Without it, the script also uses
unreleased local files where present (`data/traces/`, raw API records), which only exist on the
machine that ran the experiment or after you re-run the simulator or the API in your clone.

On a fresh clone of the release:

```
registry: v1.1  (LOCAL sources skipped: fresh-clone mode)
id                        line  claim                                          paper                  recomputed                     status
ABS-01                      69  number of feedback conditions                  five                   5                              MATCH
...
INTEGRITY
  I-01   PASS  TED and patch type re-derived from program source equal the logged values
...
  I-09   PASS  all prompts regenerated from committed certificates + template (F1 from data/certificates/traces/) hash-match the prompts actually sent
  I-10   PASS  logs/campaign: every saved prompt shares the prefix and suffix and hash-matches attempts.jsonl; every saved response contains the program logged as bt_source_after
...
  I-22   PASS  calibration trajectories (data/calibration_traces/) re-scored here agree with data/results/baseline_calibration_frozen.json, episode by episode and in total
  I-19   PASS  release hygiene: sources of the numbers committed; released inputs tracked and not git-ignored
...
SUMMARY [v1.1]  MATCH=315  NOT-RECOMPUTABLE=7  integrity_fail=0  integrity_warn=0  unregistered_numbers=0
```

Exit code 0. The seven NOT-RECOMPUTABLE rows, each printed with its reason, are four figures
quoted from other papers (REL-06, REL-01b, REL-04b, TAB1-RSSb); one historical measurement
recorded only in documentation (APB-03); and two statements about the order of development
commits, which need the unpublished history (TAXC-08, TAXC-09; see
[`PROVENANCE.md`](PROVENANCE.md)). The counts read from the internal study plan (SCO-01,
SCO-01b, APB-01) are recomputed from `docs/study_plan/01_TECHNICAL_SPEC_v2.md`. Any MISMATCH,
any failed integrity check, or under `--strict` any claim it cannot find or any number in the
paper that no row accounts for, makes it exit 1. Check I-19 reports WARN, without failing, if one
of the scripts and saved outputs it lists, or a released input directory, is untracked or has
uncommitted changes; it does not check every file the ledger reads.

### 2.14 The paper

```bash
cd paper
tectonic -X compile main.tex --outdir /tmp/paper-build
```

```
note: Running TeX ...
note: Running BibTeX on main.aux ...
...
warning: main.tex:460: Underfull \vbox (badness 2269) has occurred while \output is active
warning: main.tex:644: Underfull \vbox (badness 3568) has occurred while \output is active
...
note: Running xdvipdfmx ...
note: Writing `/tmp/paper-build/main.pdf` (464.5... KiB)
```

The PDF has 22 pages and its text (`pdftotext`) is identical to `paper/main.pdf`. Without
`--outdir`, the build overwrites `paper/main.pdf`. See [`paper/README.md`](paper/README.md).

## 3. Paper element to source

"Offline" means the element is recomputed by the command given. "Saved" means the number
comes from a run that needed the simulator or the API; the saved output is released and the
ledger (2.13) checks the paper against it, but it is not recomputed.

### Main text

| Element | Inputs | Script | Status |
|---|---|---|---|
| Figure 1 (the ablation) | `paper/figures/fig1_pipeline.png` | none: drawn with an AI image-generation tool from a schematic the authors specified; carries no data | static |
| Table 1 (contracts) | `config/contracts.yaml`, `src/stl.py` | definitions | n/a |
| Section 3.1, reproducibility (4 of 5 contracts exact; rho4 up to 0.69 m; rho4 binding in 0 of 300) | `data/results/determinism_gate.json`, `determinism_c4.json`; `attempts.jsonl` (`c4_binding_after`, `argmin_contract_after`) | `determinism_gate.py`, `probe_c4_determinism.py` (CARLA); ledger | saved; the 0 of 300 is offline |
| Section 3.2, baseline (18 samples, 2 truncated, 14 of 16 valid) | `logs/llm_index.jsonl`, `logs/llm_raw/synth_*.json`, `data/scenarios/candidates/` | `synthesize_baseline.py` (API); ledger | saved |
| Section 3.2, calibration (20 of 100 violate, entry in 100, completion in 90; all 14 candidates' rates) | `data/calibration_traces/`, `data/results/baseline_calibration.json`, `baseline_calibration_frozen.json` | `rescore_calibration.py` (2.10); `calibrate_baseline.py` (CARLA) for the 14 candidates | frozen baseline offline; other candidates saved |
| Section 3.3, corpus (K = 20, 26.6 simulations each; 7 boundaries withheld) | `data/results/falsification_summary.json`, `data/certificates/` | `run_falsification.py` (CARLA); `recompute_blame.py` (2.8) for the 7 | saved; 7 offline |
| Table 2 (conditions): byte counts | certificates, `data/certificates/traces/`, `data/prompts/patch_task.md`, `data/scenarios/baseline_program.bt` | `diff_prompts.py` (2.5) | offline |
| Table 2: median prompt tokens | `data/results/prompt_budget.json` | `check_prompt_budget.py` (API token counting); ledger check I-08 against the token counts logged per attempt | saved |
| Section 3.3, F1 window (202,812 tokens unwindowed, 10.1 times the budget; transition 28 to 47 rows back) | `data/results/prompt_budget.json` | `check_prompt_budget.py` (API); ledger | saved |
| Section 3.3, generation settings (model, effort, `max_tokens`; 3.00 distinct programs per cell) | `attempts.jsonl`, `logs/llm_index.jsonl` | `analyze_e1.py` (2.2); ledger | offline |
| Section 4 opening (no malformed or truncated output) | `attempts.jsonl` (`outcome`) | `check_attempts_schema.py` (2.6) | offline |
| Section 4.1, structural edits (59, 13, 15, 15, 28 of 60; F1 minus F2 +76.7 [+61.7, +90.0]; 51.7 to 76.7) | `attempts.jsonl` (`bt_source_before`, `bt_source_after`, `patch_type`) | `src/ted.py` (`classify_patch`), `uncertainty.py` (2.1); ledger check I-01 re-derives all 300 labels | offline |
| Table 3 (three criteria) | `attempts.jsonl` | inline recount (2.3); ledger | offline |
| Figure 2 (funnel) | `attempts.jsonl` | `make_figures.py` (2.4), file `fig4_funnel.pdf` | offline |
| Section 4.2, suite completion of refusals (93 to 95%) | `attempts.jsonl` (`icr`) | ledger | offline |
| Table 4 (expressiveness) | `data/dsl_probe_traces/`, `data/scenarios/dsl_probe/*.bt`, `data/scenarios/baseline_program.bt`, certificates | `rescore_dsl_probes.py` (2.9) | offline from saved trajectories |
| Section 4.3, clean repair (20 of 20; six repeats with zero spread) | as Table 4, `data/results/patched_programs/F1__CE005_C1_5b773c94ec4bb251__s3.bt` | `rescore_dsl_probes.py` (2.9) | offline from saved trajectories |
| Figure 3 (paired differences against F3) | `attempts.jsonl`, `data/results/uncertainty.json` | `uncertainty.py` (2.1), `make_figures.py` (2.4), file `fig2_uncertainty.pdf` | offline |
| Section 4.4, detectable effect (13 to 20 points; a 5-point improvement detected at most a quarter of the time) | `data/results/detectable_effect.json` | `detectable_effect.py` (2.12) | offline |
| Section 4.5 (224 of 300 broke a regression; F4a minus F3 +16.7 [+3.3, +30.0]; mean rho5 falls from 1.000 to between 0.59 and 0.93) | `attempts.jsonl`, `data/results/baseline_eval.json` | `analyze_e1.py` (2.2), `uncertainty.py` (2.1); ledger | offline |
| Section 4.6, blame (0.000, 1.234 and 0.500 bits; five contracts with one node each still give zero) | certificates, `data/certificates/traces/` | `recompute_blame.py` (2.8); ledger for the constructed case | offline |
| Section 5, limitations (7 of 20 certificates without a boundary) | certificates | `recompute_blame.py` (2.8) | offline |

### Appendices and checklist

| Element | Inputs | Script | Status |
|---|---|---|---|
| Appendix A, Table 5 (information per condition; feedback-block tokens) | `data/results/prompt_budget.json` (median prompt tokens minus the 4,513 shared), `src/certificate.py` (the renderers), `logs/campaign/prompts/` | `check_prompt_budget.py` (API) for tokens; `diff_prompts.py` (2.5) | tokens saved; content offline |
| Appendix B (deviations from the plan) | `docs/study_plan/01_TECHNICAL_SPEC_v2.md`, `data/scenarios/space.yaml`, `config/contracts.yaml` | none; see [`PROVENANCE.md`](PROVENANCE.md) | documentation |
| Appendix C, edit taxonomy and Figure 4 (170 hole fills, 130 skeleton edits; median TED 8 against 5; 140 and 30; mean TED by condition; 0.94 against 0.81) | `attempts.jsonl` | `src/ted.py`, `tests/test_ted.py`, `analyze_e1.py` (2.2), `make_figures.py` (2.4), file `fig3_patch_type.pdf`; ledger | offline |
| Appendix D, Table 6 (17 paired differences, Bonferroni) | `attempts.jsonl` | `uncertainty.py` (2.1) | offline |
| Appendix E, Table 7 (detectable effect) | `attempts.jsonl`, `data/results/uncertainty.json` | `detectable_effect.py` (2.12) | offline |
| Checklist, compute and token totals | `logs/e1_phase_a.log`, `logs/e1_phase_b.log`, `attempts.jsonl`, `falsification_summary.json`, `docs/env_manifest.md` | ledger | saved run logs |
| Checklist, package versions | `requirements.txt`, the installed environment | ledger | offline |

## 4. Steps that need the simulator or the API

None of these was re-run for this release. They are the commands the experiment used, in
order, and what each writes. Most write to the released result paths, and several resume from
what is already on disk, so run them in a separate clone or branch. Run every Python script as
`.venv/bin/python scripts/<name>.py ...` (or `source .venv/bin/activate` first): some scripts
are not executable and the others use `#!/usr/bin/env python3`. API steps also append to
`logs/llm_index.jsonl` and write `logs/llm_raw/`. See [`README.md`](README.md) for setup and
[`docs/RUNBOOK.md`](docs/RUNBOOK.md) for operation.

| Step | Command | Needs | Writes |
|---|---|---|---|
| Start the server | `scripts/start_carla.sh --port 2000 --gpu 0`, then `scripts/health_check.py` | CARLA | |
| Determinism gate | `scripts/determinism_gate.py --port 2000 --n 5` | CARLA | `data/results/determinism_gate.json` |
| Baseline candidates | `scripts/synthesize_baseline.py --n 12` (the paper's 18 samples were drawn in two batches) | API | `data/scenarios/candidates/cand_NN.bt` (overwriting files of the same name), `data/results/synthesis.json`, `logs/` |
| Calibration and freeze gates | `scripts/calibrate_baseline.py --programs <candidates> --n 100` | CARLA | `data/results/baseline_calibration.json`, trajectories |
| Counterexample corpus | `scripts/run_falsification.py --k 20 --port 2000` | CARLA | `data/certificates/`, `data/results/falsification_summary.json` |
| Evaluation suites | `scripts/build_suites.py --port 2000` | CARLA | `data/scenarios/regression_suite.json`, `held_out_suite.json` |
| Prompt token counts | `scripts/check_prompt_budget.py` | API (token counting) | `data/results/prompt_budget.json` |
| Repair attempts | `scripts/run_e1.py --phase a` | API | `data/results/patches.jsonl`, `logs/campaign/` |
| Evaluation of every patch | `scripts/run_e1.py --phase b --port 2000` | CARLA | `data/results/attempts.jsonl`, `baseline_eval.json` |
| C4 reproducibility | `scripts/probe_c4_determinism.py --repeats 6` | CARLA | `data/results/determinism_c4.json` |

`run_e1.py` resumes by `attempt_id`, so in a clone that holds the released campaign it skips
every attempt already recorded; draw new samples in a separate clone or branch. New samples
will not reproduce the released ones sample for sample: `claude-opus-5` exposes no seed or
temperature, and its identifier names no snapshot.

The expressiveness probes (Table 4) and the calibration trajectories were produced on the
simulator during development. The probe episodes were run with driver code that is not in this
repository; every released trajectory has a sidecar recording its scenario parameters and the
full source of the program it ran, and `scripts/run_one_episode.py --params <json>
--program <file.bt> --episode-id <id> --result-json <file>` runs a single episode of that
kind. We have not used it to re-run the probes.
