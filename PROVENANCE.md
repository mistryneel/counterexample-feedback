# Provenance

This public repository is a clean snapshot of a private development repository. The private
history (35 commits up to the camera-ready revision) is not published. The public repository
has two commits:

| Public tag | Contents |
|---|---|
| `v1.0-submission` | The tree of private commit `98b1caa` (the version submitted and reviewed; tagged `v1.0-submission` in the private repository), with private files removed |
| `v1.1-camera-ready` | The camera-ready revision (private commit `5b96b97`) and the release preparation that followed it, with the same files removed |

The removed files are private working notes and planning documents, correspondence, agent
instructions and stage reports written during development, an audit of the original machine,
an unfinished manual-review sheet and the script that generated it, a superseded script that
rewrites the certificates in place (`scripts/regen_narratives.py`), a figure the paper does not
use, a token-count cache, and the organizers' formatting-instructions PDF. Four files were
redacted in both commits, in comments, one documentation field and one example configuration
value (no code, data or paper text changed): the hostname in `docs/env_manifest.md`; a
home-directory path and a machine-specific comment in `config/local.yaml.example`; a
machine-specific comment in `config/sim.yaml`; and a development note in the header comment of
`paper/references.bib` (the built PDF is unchanged). In both commits, code comments and documentation that referred
to the authors' private working notes were reworded; no code, data or paper text changed. In both commits the plan was moved,
unmodified, from the repository root to `docs/study_plan/`. In the `v1.0-submission`
commit the original `README.md`, a development-stage overview, was replaced by a short note
pointing to `v1.1-camera-ready`, and the paper's pre-submission build notes
(`paper/README.md`) were removed. Large trajectory sets that were never
committed are not included, apart from the subsets in `data/certificates/traces/`,
`data/dsl_probe_traces/` and `data/calibration_traces/` that the offline re-scoring needs.

## What the hashes and dates are worth

The commit hashes below refer to the unpublished private history, and the dates are the
author and commit dates recorded by git on the authors' machine. Whoever makes a commit can
set its dates to any value, and nobody outside the authors can resolve the hashes. This table is therefore
a record of what the authors' history says, not proof of when anything happened. No plan was
registered with a third party.

## Key commits in the private history

Dates are as recorded; author date and commit date agree for every commit named in this file.

| Event | Private commit | Recorded date |
|---|---|---|
| Plan first committed (`01_TECHNICAL_SPEC_v2.md`) | `d73df5df4a93c2c3d0225e7ee1d91698442ebbeb` | 2026-08-29 17:14:11 -0700 |
| Baseline frozen (`data/scenarios/baseline_program.bt`) | `d09926137e237eceb710968e8e905cc0e0924c51` | 2026-08-31 00:31:35 -0700 |
| Falsifier and the 20 certificates first committed | `c164333e9ae4b97a1daf51ea4dd852ce0be38a86` | 2026-08-31 12:58:05 -0700 |
| Campaign code; the `git_commit` of every attempt | `47936183b86f17a56d7aa7de773d56c89190cc60` | 2026-08-31 16:07:25 -0700 |
| Campaign results (`attempts.jsonl`, `patches.jsonl`) | `29fd1a78981a65c967924d55cd6fd42e37e3860a` | 2026-08-31 21:14:40 -0700 |
| Submitted version | `98b1caa24219565f4068afc3c1e87a2e98490235` | 2026-09-09 21:57:57 -0700 |
| Camera-ready revision | `5b96b9732f51f8e2da5b0750786af0f60b73858f` | 2026-10-10 09:44:10 -0700 |

The 300 records in `data/results/attempts.jsonl` carry timestamps from 2026-08-31T23:07:30Z to
23:42:30Z (16:07:30 to 16:42:30 at -0700), after the recorded time of `4793618` and before
that of `29fd1a7`. The certificates were last changed in private commit `3d0fed1`
(2026-08-31 14:40:24 -0700), before the campaign commit.

Some released files are unchanged since a private commit, and their git blob ids can be
checked with `git hash-object <file>`:

| File | Unchanged since | Git blob id |
|---|---|---|
| `docs/study_plan/01_TECHNICAL_SPEC_v2.md` | `d73df5d` (first commit) | `bcb5951f4d2833a5d68b5f684f4f122246fa7e28` |
| `data/scenarios/baseline_program.bt` | `d099261` (freeze) | `3469f9ee3888812a3a1071a3a89e1f4ede7a0005` |
| `data/results/patches.jsonl` | `29fd1a7` (campaign) | `6e0d5f8ca5adbedfad9774dcfd3877d84a4323ed` |
| `data/results/attempts.jsonl` | `29fd1a7` (campaign) | `85adca18f7427df630a0100c92030a1368f93a7d` |

A matching blob id shows that the public file is byte-identical to the file the authors'
history records at that commit; it does not show when that commit was made.

## The internal study plan

The plan the paper calls pre-specified is `01_TECHNICAL_SPEC_v2.md`, published unmodified as
`docs/study_plan/01_TECHNICAL_SPEC_v2.md`. Code comments cite it as
`01_TECHNICAL_SPEC_v2.md` or as "spec v2". It was first committed in `d73df5d`, the root of the
private history, and never modified afterwards.

Three dates bear on it, and they do not agree:

- The plan states "Revision date: 23 August 2026".
- The message of `d73df5d` says the commit records "Work of 23 Aug 2026, committed
  retroactively on 24 Aug", because the repository did not exist while that work was done.
- The recorded date of `d73df5d` is 29 Aug 2026, and the three commits that follow it were
  recorded within 31 minutes of it.

We cannot establish from the repository which of these is right. What the record does show,
on any of the three dates, is that the plan's first commit precedes the commits that changed
the scope (`230a70f`, 2026-08-29, dropped the pedestrian-phase parameter and restored the
aggressiveness parameter; `12c0568`, `70caa30` and `b21159d`, 2026-08-30, re-enabled the
red-light and lead-distance contracts and moved to the six-parameter space), the baseline
freeze, and the campaign.

Appendix B of the paper describes the deviations from the plan in contracts, scenario
parameters, the blame field and the success criterion. The plan also sets the experiment's
scale differently from what was run: it gives K = 8 counterexamples with one seed and a
five-scenario regression suite as the initial scale, with K = 20 and three seeds planned for
September, whereas the campaign used K = 20, three replicates, and 30-scenario regression and
held-out suites. It specifies four conditions, F1 to F4; the campaign split F4 into F4a (the
planned `active_node` field) and F4b (`authorising_node`, defined later and labelled
exploratory in the paper).

## `git_commit` fields in data files

Many files record a `git_commit` field. Each names a commit in the private history: the commit
checked out (`git rev-parse HEAD`) when the record was written. The recorder did not note
uncommitted changes, so where code ran before it was committed, the field names an earlier
commit than the code that ran. The main values:

| Where | `git_commit` | Note |
|---|---|---|
| `data/results/attempts.jsonl` (300 of 300) | `4793618` | the earliest attempt timestamp is 5 s after this commit's recorded time |
| `logs/llm_index.jsonl` | `4793618` (300 campaign calls), `e86fe34` (5 dry-run calls), `890cd82` (5 smoke-test calls), `b21159d` (21 synthesis calls) | the synthesis harness was first committed in `e1ce410` |
| `data/certificates/*.json` and their trajectories | `4d5b761` | the falsifier code was first committed with the certificates in `c164333` |
| `data/calibration_traces/*.json` | `147e92e` | run with the re-phased `light_offset` code later committed in `d099261` (the freeze commit); they reproduce `d099261`'s committed calibration entry for the frozen candidate exactly, while the result recorded at `147e92e` differs (81 violations). See `scripts/rescore_calibration.py` for how the traces are tied to the frozen program |
| `data/dsl_probe_traces/` sidecars and `manifest.json` | `4bf1111` (240 episodes), `bc0ed1c` (26 episodes) | each trace is also tied to its program by the sha256 of the program source |
| `data/results/detectable_effect.json` | `98b1caa` | run on 9 Oct 2026 with the script first committed in `5b96b97` (the camera-ready revision); `98b1caa` was HEAD at the time and contains neither the script nor the output |

None of these hashes resolves in this repository. The results do not depend on resolving them:
every number in the paper is either recomputed from the released files or checked against a
released saved output, as described in [`REPRODUCE.md`](REPRODUCE.md).

## The edit classifier (TAXC-08, TAXC-09)

Two statements in the paper (Section 4.1, Appendix C) concern the order of development and are
checked against the private history, so `scripts/reproduce_paper_numbers.py` reports them as not
recomputable here. The facts behind them: `src/ted.py` and `tests/test_ted.py` were first
committed in private commit `4793618` (2026-08-31 16:07:25 -0700), which is the `git_commit`
recorded by all 300 attempts in `data/results/attempts.jsonl`; the earliest attempt is
timestamped 2026-08-31T23:07:30Z, 5 s after that commit. The two edit categories appear in the
plan at `docs/study_plan/01_TECHNICAL_SPEC_v2.md` line 392 ("Patch type | Hole fill vs
skeleton edit"), and the plan has not changed since it was first committed in `d73df5d`.

## Corrections since the submitted version

Running `scripts/reproduce_paper_numbers.py` on the submitted paper (tag `v1.0-submission`,
`paper/main.tex`) reports exactly these seven rows as MISMATCH and exits 1. All seven are
corrected in the camera-ready, and none changes a conclusion.

| Row | Submitted text | Corrected |
|---|---|---|
| INT-02 | the 76.7-point gap is "between the least and most processed conditions" | it is F1 against F2, the natural-language summary |
| PT-09 | "the most processed conditions produce among the fewest" structural edits | false for F4b (28 of 60); reworded |
| BAS-01 | baseline "sampled 20 times" | 18 samples under one fixed prompt |
| BAS-08 | completes the turn in 88.3% of the 100 calibration scenarios | 90 of 100 |
| GEN-01 | "All calls use ... `max_tokens` = 48,000" | true of the 300 repair calls; 15 of the 21 baseline-synthesis calls used 16,000 |
| SCO-03 | the parameter space "grew to six" by adding two parameters | one planned parameter was dropped and three were added (Appendix B) |
| TAB2-F1 | F1 median prompt 16,381 tokens | 16,382 (the median is 16,381.5) |

The camera-ready also corrects one statement the ledger does not register as a number: the
submitted Limitations said oncoming vehicles travel at constant velocity, but they brake for
the ego as it nears the conflict zone, depending on an aggressiveness parameter.
