# What Does Formal Structure in Counterexample Feedback Buy?

**Neel Mistry and Sreedath Panat.** NeurIPS 2026 Workshop on AI for Verifiable Coding (poster).

Paper: [`paper/main.pdf`](paper/main.pdf) (camera-ready). The anonymous version that was
reviewed is [`paper/submitted/main_v1.0-submission.pdf`](paper/submitted/main_v1.0-submission.pdf).

This repository holds the code, the frozen program, the twenty counterexample certificates,
the exact prompts and raw model responses for all 300 repair attempts, and the scripts and
saved outputs behind every table and figure in the paper.

## Summary

A large language model repairs an interpretable behaviour-tree policy for an unprotected left
turn in the CARLA simulator, given a description of a counterexample found by a falsifier. We
hold the falsifier, the program, the counterexample corpus, the token budget and the
evaluation suite fixed, vary only how the failure is rendered (five conditions, from a raw
trace excerpt to a certificate with a blamed program location), and run 300 one-step repair
attempts. The conditions differ sharply in the kind of repair attempted: structural edits in
59 of 60 attempts under the raw trace against 13 of 60 under a natural-language summary, a
difference of 76.7 points (95% interval [+61.7, +90.0]); because the raw trace also differs in
length and information content, this is a difference between feedback conditions, not an
effect of formal structure. Satisfying the safety contracts on the failing scenario is
trivially achievable by refusing to act: of the 18 attempts that satisfied them, 13 never
entered the junction's conflict zone; of the other 5, 3 completed the manoeuvre, and 1 of those
also left the regression suite intact. That one program satisfies the contracts and completes
the turn on all twenty counterexamples. Excluding refusals, we did not detect a reliable improvement in
repair success from any condition, and under stated assumptions only large improvements would
reliably have been detected.

## Authors

Neel Mistry designed the study, built the system, ran all experiments and analyses, and wrote
the paper. Sreedath Panat advised. This work received no external funding.

## Releases

| Tag | What it is |
|---|---|
| `v1.0-submission` | The version that was reviewed. `paper/main.pdf` is the anonymous submitted PDF. |
| `v1.1-camera-ready` | The final version. `paper/main.pdf` is the camera-ready PDF, and the submitted PDF is kept at `paper/submitted/main_v1.0-submission.pdf`. |

Both are clean snapshots of a private development repository whose history is not published.
[`PROVENANCE.md`](PROVENANCE.md) records the original commit hashes and dates, including when
the internal study plan was first committed.

## Repository map

```
paper/                 paper source, PDF and figures (see paper/README.md)
  submitted/           the anonymous PDF that was reviewed
src/                   experiment code: behaviour-tree DSL parser and validator, the five
                       contracts and their robustness, falsifier, certificates and the
                       five feedback renderers, patcher, evaluator, tree edit distance,
                       CARLA backend
scripts/               entry points: offline analysis, simulator runs, model calls
tests/                 unit tests, each run as a script
config/                simulator settings, contract thresholds, experiment settings,
                       local.yaml.example (machine-specific settings for simulator runs)
data/
  scenarios/           frozen baseline program, the 14 candidates it was selected from,
                       scenario space with a justification for each bound, junction,
                       regression and held-out suites, hand-written probe programs
  certificates/        the 20 counterexample certificates (JSON)
    traces/            the 20 trajectories the certificates point to (Parquet, 2.5 MB)
  prompts/             the patch-task template shared by every condition
  results/             every saved output; data/results/NOTES.md describes each file
  dsl_probe_traces/    trajectories behind Table 4 and the clean-repair validation (40 MB)
  calibration_traces/  the frozen baseline's 100 calibration trajectories (14 MB)
logs/
  campaign/            the exact prompt sent and raw response received, per attempt (300 + 300)
  llm_raw/             the 21 raw API records of baseline synthesis
  llm_index.jsonl      one line per model call (331 calls)
  e1_phase_a.log       campaign run log, model calls
  e1_phase_b.log       campaign run log, simulator evaluation
docs/                  design notes and measurements referred to by the code,
                       env_manifest.md (pinned environment), study_plan/ (the internal study plan)
REPRODUCE.md           every table, figure and appendix mapped to a script and a command
PROVENANCE.md          private-history commit hashes and dates
```

## Quick start: reproduce the paper offline

Every table and figure is either recomputed offline from the committed files or, where it
needed the simulator or the API (the token counts in Tables 2 and 5, the simulator figures in
Section 3), checked against the released saved output; Figure 1 is a static schematic. None of
this needs the simulator or an API key, and it takes a few minutes. The commands below were checked on a copy of the release tree on
Linux x86_64 with CPython 3.12.3 and uv 0.11.7:

```bash
git clone https://github.com/mistryneel/counterexample-feedback.git
cd counterexample-feedback
uv venv --python 3.12 .venv
VIRTUAL_ENV=.venv uv pip install -r requirements.txt

.venv/bin/python scripts/uncertainty.py --out /tmp/uncertainty.json   # intervals: Table 6, Figure 3
cmp /tmp/uncertainty.json data/results/uncertainty.json && echo identical
.venv/bin/python scripts/rescore_dsl_probes.py --no-write              # Table 4, about 65 s
.venv/bin/python paper/figures/make_figures.py                         # Figures 2 to 4
git status --short paper/figures                                       # empty: byte-identical
```

[`REPRODUCE.md`](REPRODUCE.md) gives the full sequence, the expected output of each command,
and which commands write into the repository.

Two platform notes. The `carla` client used here is the CPython 3.12 wheel for Linux x86_64
(`manylinux_2_31`); if `carla` does not install on your platform, remove that line from
`requirements.txt`, because no offline script imports `carla` (or `anthropic`); the numbers
ledger then reports the three rows that read the `carla` pin as not recomputable. The figures
are byte-identical only when the Liberation Serif font is installed (Ubuntu package
`fonts-liberation`); without it matplotlib falls back to DejaVu Serif and the bytes differ.

## What needs the simulator

Re-running any simulation needs CARLA 0.9.16 on Linux with an NVIDIA GPU. The server ran in
the official Docker image `carlasim/carla:0.9.16`, digest
`sha256:aaf1df22702780ece072069e23d03c4879b002ae028c79744b09c4c7ddbae953`; check that
`docker images --digests carlasim/carla` shows this digest before trusting a re-run. Copy
`config/local.yaml.example` to `config/local.yaml` and edit it, then follow
[`docs/RUNBOOK.md`](docs/RUNBOOK.md) and [`docs/env_manifest.md`](docs/env_manifest.md).
`scripts/determinism_gate.py` should report `GATE VERDICT: PASS` before any experimental run.

Simulator entry points: `start_carla.sh`, `stop_carla.sh`, `health_check.py`,
`determinism_gate.py`, `run_falsification.py` (the certificate corpus), `build_suites.py`,
`calibrate_baseline.py`, `run_e1.py --phase b` (evaluation of every patch),
`probe_c4_determinism.py`, `calibrate_control_map.py`, `run_campaign.py` and
`run_one_episode.py`. None of these was re-run for this release. Most of them write to the
released result paths, so run them in a separate clone or branch
([`REPRODUCE.md`](REPRODUCE.md), section 4).

On the simulator side, the released determinism gate (`data/results/determinism_gate.json`;
a placeholder controller on a fixed scenario without a lead vehicle or signal timing)
reproduced the ego trajectory bit-identically within a process and across restarts. With the
frozen baseline on three six-parameter scenarios repeated six times, four of the five
contracts reproduced exactly; the lead-distance contract C4 varies by up to 0.69 m (see
`docs/determinism_c4.md`).

## What needs an API key

Synthesizing baseline candidates (`scripts/synthesize_baseline.py`), drawing repair attempts
(`scripts/run_e1.py --phase a`), counting prompt tokens (`scripts/check_prompt_budget.py`) and
the renderer smoke test (`scripts/smoke_render.py`) call Anthropic's API. Set
`ANTHROPIC_API_KEY` in the environment or in a git-ignored `.env` file at the repository root.
Some keys are tied to a workspace and also need `ANTHROPIC_WORKSPACE_ID`, or every request
returns an error (see `src/llm.py`).

Every logged model call (331, listed in `logs/llm_index.jsonl`) used `claude-opus-5` at
effort `high`; the 300 repair calls used `max_tokens` 48,000. The model exposes no seed or
temperature, and its identifier names no snapshot, so new samples will not reproduce the
released ones sample for sample: the three replicates per cell are independent samples. The
released prompts and responses in `logs/campaign/` are the record of what was sent and
received. `run_e1.py` writes to `data/results/patches.jsonl`, `data/results/attempts.jsonl`
and `logs/campaign/`, and resumes by `attempt_id`, so in a clone that holds the released
campaign it skips every attempt already recorded; draw new samples in a separate clone or
branch.

## Figure and table numbering

Figure file names predate the camera-ready numbering.

| Paper | File | Made by |
|---|---|---|
| Figure 1 | `paper/figures/fig1_pipeline.png` | drawn with an AI image-generation tool from a schematic the authors specified; carries no data |
| Figure 2 | `paper/figures/fig4_funnel.pdf` | `paper/figures/make_figures.py` |
| Figure 3 | `paper/figures/fig2_uncertainty.pdf` | `paper/figures/make_figures.py` |
| Figure 4 (Appendix C) | `paper/figures/fig3_patch_type.pdf` | `paper/figures/make_figures.py` |

Tables 1 to 4 are in the main text and Tables 5 to 7 in Appendices A, D and E.
[`REPRODUCE.md`](REPRODUCE.md) maps each one to its inputs and script.

## Known caveats

[`data/results/NOTES.md`](data/results/NOTES.md) lists them in full. In brief:

- **C4 is not deterministic** (up to 0.69 m over identical parameters). It was never the
  binding contract after any of the 300 patches.
- **Some raw API records were overwritten.** Parallel calls could share a `call_id`, so for
  14 attempts the raw API record held a sibling's response. Those records are not released;
  `logs/llm_raw/` holds only the 21 baseline-synthesis records. The per-attempt files in
  `logs/campaign/` are complete, and every prompt matches its hash in `attempts.jsonl`.
- **Evaluation trajectories were not kept per attempt.** The 18,300 per-attempt evaluation
  rollouts are recorded as fields of `data/results/attempts.jsonl`, not as trajectories.
- **The vacuity sentinel.** A contract that never applies is scored 999.0 so that it never
  wins the minimum. Exclude it before averaging any per-contract robustness.
- **The frozen baseline's header predates the corrected counts.** `baseline_program.bt` is
  frozen, so its comment still says "sampled 1 of 20" and "ICR 88.3%". The paper's figures
  are 18 samples and completion on 90 of the 100 calibration scenarios. 88.3% cannot be a count
  out of 100; it equals 53 of 60, matching the header's separate 60-scenario draw, whose results
  were not kept. Programs derived from the baseline (the 300
  patched programs and those in `data/scenarios/dsl_probe/`) keep its header, including
  "FROZEN BASELINE PROGRAM -- DO NOT EDIT"; it stays because each program and trajectory is
  tied to the sha256 of the program's source.
- **`data/results/dsl_expressiveness.json` is partly superseded** by the clean repair; see
  NOTES caveat 1.
- **Absolute paths are historical.** Certificates and several result files store
  `/home/npk/Projects/cv_research/...` paths from the machine that ran the experiment. They need no editing:
  `src/certificate.py` resolves certificate trajectories by file name under
  `data/certificates/traces/`.
- **`git_commit` fields refer to unpublished history.** See [`PROVENANCE.md`](PROVENANCE.md).
- **Two claims need the unpublished history.** The paper's statements that the edit
  classifier was committed before the campaign, and that its categories were in the plan before
  any attempt, are checked against private commit order; in this snapshot the numbers script
  reports them as not recomputable (TAXC-08, TAXC-09; see `PROVENANCE.md`).

## Licence

Code is released under the MIT License ([`LICENSE`](LICENSE)). Data (`data/`), logs (`logs/`)
and the paper's text and figures are released under CC BY 4.0
([`DATA_LICENSE`](DATA_LICENSE)). The model outputs in `logs/` and the programs the model
wrote are released by Neel Mistry, who as the API customer owns them under Anthropic's
Commercial Terms (the customer owns its outputs; checked 10 Oct 2026). No CARLA code, binaries or assets are
redistributed, only trajectories logged from the simulator. `paper/neurips_2026_vericode.sty`
is the workshop's style file, distributed by the organizers for building papers, and is not
covered by either licence.

## Citation

```bibtex
@inproceedings{mistry2026formal,
  title     = {What Does Formal Structure in Counterexample Feedback Buy?},
  author    = {Mistry, Neel and Panat, Sreedath},
  booktitle = {NeurIPS 2026 Workshop on AI for Verifiable Coding},
  year      = {2026},
  note      = {Poster},
  url       = {https://github.com/mistryneel/counterexample-feedback}
}
```

[`CITATION.cff`](CITATION.cff) carries the same information.
