# Trace Provenance

Which banked traces may back a paper claim, and which may not.

---

## The problem

`src/config.py::git_commit()` stamps every Parquet trace and sidecar JSON with the repository
commit at run time. It returns `None` when the working directory is not a git repository.

**The repository was initialised on 24 August 2026.** Every trace banked before that carries
an empty `git_commit` field, so the exact code that produced it cannot be recovered from the
trace alone.

---

## Generation 0 — pre-repository (23 Aug 2026)

| | |
|---|---|
| Count | 300 Parquet + 300 sidecar JSON, 33 MB |
| Naming | `bank_<shard>_<index>_<param_hash>.parquet`, shards 0–2 |
| `git_commit` | **empty** |
| Manifests | `data/results/campaign_bank_{0,1,2}.jsonl` |
| ρ scores | `data/results/bank_rho.json` |
| Ego | **Hardcoded Python controller**, not a behaviour tree. `bt_node_*` columns are null throughout |
| Falsifier space | 4 parameters including `ped_phase_offset`, which was **a no-op** — no pedestrian was ever spawned |
| Schema | v1.0.0, 43 columns |
| CARLA | 0.9.16, image digest `sha256:aaf1df22702780ece072069e23d03c4879b002ae028c79744b09c4c7ddbae953` |
| Junction | Town05 id 1126 |

### What generation 0 is valid for

✅ **Pipeline validation.** They demonstrated end to end that the backend, schema, and ρ
computation work on real CARLA data.

✅ **The C5 threshold sweep** (`data/results/c5_threshold_sweep.json`). That analysis measures
a property of *CARLA's vehicle physics*, not of any program, so a hardcoded controller is an
acceptable — arguably preferable — probe: it produces harder braking than a tuned tree would.

✅ **Throughput and determinism figures** quoted in `docs/determinism_report.md`.

### What generation 0 is NOT valid for

❌ **Any F1–F4 result.** The ego was not a behaviour tree, so there is no `active_node` and no
blame localization.

❌ **Baseline violation-rate calibration.** The 19.3% figure describes the hardcoded
controller, not the frozen baseline program.

❌ **Parameter sensitivity claims.** `ped_phase_offset` was inert, and `aggressiveness` did not
exist. Superseded by generation 1 — see `docs/sensitivity_analysis.md`.

❌ **Anything printed in the paper without a commit hash.** Reproducibility requires the code
that produced the number.

---

## Generation 1 onward — post-repository

Every trace banked from 24 Aug carries a real `git_commit`. Traces intended to back a paper
claim must:

1. carry a non-empty `git_commit`
2. be produced by a behaviour tree, with `bt_node_*` populated
3. use the falsifier space defined in `data/scenarios/space.yaml`

`scripts/check_trace_provenance.py` asserts all three over a directory and exits non-zero on
violation. Run it before any analysis whose output reaches the paper.

---

## Why generation 0 was kept rather than deleted

Regenerating is cheap — 300 episodes took 74 seconds — so keeping them is not about cost. They
are retained because the determinism report and the C5 threshold sweep quote numbers derived
from them, and deleting the inputs to a published measurement would make that measurement
unreproducible. They are labelled, not trusted.
