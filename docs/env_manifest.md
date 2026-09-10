# Environment Manifest

**Recorded:** 2026-08-23
**Purpose:** this file is what makes the experiment reproducible and **will be cited in the
paper**. Every value was read from the running system, not from memory or documentation.

Determinism validation against this exact environment: [`determinism_report.md`](determinism_report.md).

---

## Host

| Field | Value |
|---|---|
| Hostname | (redacted) |
| OS | Ubuntu 24.04.4 LTS (Noble Numbat) |
| Kernel | 6.17.0-29-generic (`#29~24.04.1-Ubuntu SMP PREEMPT_DYNAMIC`) |
| Architecture | x86_64 |
| glibc | 2.39-0ubuntu8.7 |
| CPU | AMD Ryzen 9 9900X — 12 cores / 24 threads, boost 5.66 GHz |
| RAM | 30 GiB |
| Swap | 8 GiB (`/swap.img`) |
| Root filesystem | ext4 on `/dev/nvme0n1p2`, 1.8 TB |

### ⚠️ Ubuntu 24.04 is outside CARLA's stated support matrix

The CARLA 0.9.16 quickstart states verbatim:

> "CARLA is built for Windows 10 and 11 and Ubuntu **20.04** and **22.04**."

24.04 is neither endorsed nor explicitly excluded. **This is why the server runs in the
official container**, which supplies its own supported Ubuntu userland, making the host
distribution irrelevant to the simulator. The Python client runs natively on the host.

This is a *native Linux* CARLA build throughout. **No Wine. No Windows binaries.** A container
is packaging, not emulation.

---

## GPU

| Field | Value |
|---|---|
| GPUs | 3 × NVIDIA GeForce RTX 3090, 24576 MiB each |
| Driver | **580.159.04** |
| CUDA (driver-reported max) | 13.0 |
| CUDA toolkit installed | 12.6.85 (`/usr/local/cuda-12.6`) |
| Compute capability | 8.6 |
| Vulkan loader | `libvulkan.so.1.3.275` |
| NVIDIA Vulkan ICD | `/usr/share/vulkan/icd.d/nvidia_icd.json`, API 1.4.312 |

CUDA is **not used by this experiment**. CARLA renders through Vulkan; the toolkit is recorded
only because it is present on the machine.

Measured: **~3 GB VRAM per headless CARLA instance** (2.4 GiB container RSS).

---

## Simulator

| Field | Value |
|---|---|
| CARLA version | **0.9.16** |
| Release date | 2025-09-16 |
| Engine | Unreal Engine 4.26.2 (`ue4/0.9.16` branch) |
| Source commit | `294096eb1c38eabf246e4f3a9cdab704e33a7f4c` |
| Distribution | Docker image `carlasim/carla:0.9.16` |
| **Image digest** | `sha256:aaf1df22702780ece072069e23d03c4879b002ae028c79744b09c4c7ddbae953` |
| Image size | 8.64 GB content / 29.4 GB on disk |
| Docker Engine | 29.5.2 (build 79eb04c) |
| GPU passthrough | `nvidia-container-toolkit`, `--runtime=nvidia` |
| Launch flags | `-RenderOffScreen -nosound -quality-level=Low -carla-rpc-port=N` |
| Map | Town05 (**ships in the base image** — `AdditionalMaps` not required) |

Maps present in the image (13): `Town01`, `Town01_Opt`, `Town02`, `Town02_Opt`, `Town03`,
`Town03_Opt`, `Town04`, `Town04_Opt`, **`Town05`**, `Town05_Opt`, `Town10HD`, `Town10HD_Opt`,
`AnnotationColorLandscape`. `Town06`/`Town07` are absent, consistent with the documentation.

### Version match is verified, not assumed

`CarlaBackend.__enter__` compares `client.get_client_version()` against
`client.get_server_version()` on every connection and **refuses to start on mismatch**.
Confirmed at gate time: client `0.9.16`, server `0.9.16`.

---

## Python

| Field | Value |
|---|---|
| Interpreter | CPython **3.12.3** (`/usr/bin/python3.12`, Ubuntu system) |
| Virtualenv | `.venv/`, created with `uv venv` |
| `uv` | 0.11.7 |
| CARLA client wheel | `carla-0.9.16-cp312-cp312-manylinux_2_31_x86_64.whl` |

**Why 0.9.16 specifically.** It is the only CARLA release publishing a Python 3.12 Linux
wheel. 0.9.15's newest Linux wheel is `cp310`, and this machine has no interpreter below 3.12.
0.10.0 publishes no PyPI wheel at all. The `manylinux_2_31` tag requires glibc ≥ 2.31; the host
has 2.39.

**The pip wheel is the client library only.** It does **not** include the `agents` package, so
`GlobalRoutePlanner` is unavailable — route planning is implemented in `carla_backend.py`.

### Packages (exact, pinned)

Full pins in [`requirements.txt`](../requirements.txt); resolved graph with dependency
provenance in [`requirements.lock.txt`](../requirements.lock.txt).

| Package | Version | Role |
|---|---|---|
| `carla` | 0.9.16 | simulator client |
| `numpy` | 2.5.2 | numerics |
| `scipy` | 1.18.1 | numerics |
| `pandas` | 3.0.5 | trace handling |
| `pyarrow` | 25.0.1 | Parquet I/O |
| `pyyaml` | 6.0.3 | configuration |
| `py-trees` | 2.5.0 | behaviour-tree execution |
| `networkx` | 3.6.1 | tree edit distance |
| `matplotlib` | 3.11.1 | figures |
| `rtamt` | 0.3.5 | STL robustness (independent cross-check) |
| `antlr4-python3-runtime` | 4.7 | (rtamt dependency) |
| `contourpy` | 1.3.3 | (matplotlib) |
| `cycler` | 0.12.1 | (matplotlib) |
| `fonttools` | 4.63.0 | (matplotlib) |
| `kiwisolver` | 1.5.0 | (matplotlib) |
| `packaging` | 26.3 | (transitive) |
| `pillow` | 12.3.0 | (matplotlib) |
| `pydot` | 4.0.1 | (py-trees) |
| `pyparsing` | 3.3.2 | (matplotlib) |
| `python-dateutil` | 2.9.0.post0 | (pandas) |
| `six` | 1.17.0 | (transitive) |

**`rtamt` note:** the published wheel is `rtamt-0.3.5-py3-none-any.whl`, pure Python. The C++
backend module `rtamt_stl_library_wrapper` is **absent**, so `StlDiscreteTimeOnlineSpecificationCpp`
is unavailable. Only offline discrete-time evaluation is used, which the pure-Python
implementation provides. Functionally verified, not merely installed.

---

## Simulation settings (pinned)

From [`config/sim.yaml`](../config/sim.yaml). Changing any of these invalidates the
determinism report.

| Setting | Value |
|---|---|
| `synchronous_mode` | `true` |
| `fixed_delta_seconds` | **0.05** (20 Hz) |
| `no_rendering_mode` | `true` |
| `substepping` | `true` |
| `max_substep_delta_time` | **0.01** |
| `max_substeps` | **10** |
| Substepping condition | `0.05 ≤ 0.01 × 10 = 0.10` ✅ (2× headroom) |
| `reload_between_episodes` | **`false`** — see below |
| Weather | `ClearNoon`, fixed |
| Quality | `Low` |
| Episode horizon | 30.0 s (600 ticks max) |
| Trace format | Parquet, Snappy, float64 |

### `reload_between_episodes: false` deviates from the CARLA docs

The docs state that reproducible physics requires "world reloading between repetitions". It is
disabled here on measured evidence: `reload_world()` **segfaults CARLA 0.9.16** roughly 3–4 s
after the client disconnects (isolated by bisection), and cost ~70% of throughput. Determinism
without reload is therefore **verified empirically** — gate stages 3.4 and 3.5 produced
bit-identical trajectories and bit-identical ρ, within and across processes. Full detail in the
determinism report.

### Seeds

| Seed | Value |
|---|---|
| Python `random` | 20260823 |
| `numpy.random` | 20260823 |
| Traffic Manager `set_random_device_seed` | 20260823 |

The Traffic Manager **controls no actor in E1** — oncoming vehicles use
`enable_constant_velocity` and the ego is program-controlled. The TM is seeded for completeness;
it governs nothing in the experiment. Gate stage 3.6 could not demonstrate that the TM seed
controls TM behaviour (different seeds also produced identical traffic), and this is recorded
as inconclusive rather than claimed.

---

## Frozen artefacts

| File | Contents |
|---|---|
| `data/scenarios/junction.yaml` | Town05 junction **id 1126**, ego/oncoming approaches by OpenDRIVE identity, left-turn direction empirically verified |
| `docs/log_schema.md` | Trajectory schema v1.0.0, 43 columns |
| `src/trace_schema.py` | The schema in code — single source of truth |

---

## Reproducing this environment

```bash
git clone <repo> && cd cv_research
uv venv --python python3.12 .venv
VIRTUAL_ENV=.venv uv pip install -r requirements.txt
sudo usermod -aG docker "$USER"     # then log out and back in
docker pull carlasim/carla:0.9.16
cp config/local.yaml.example config/local.yaml
scripts/start_carla.sh --port 2000 --gpu 0
scripts/health_check.py
scripts/determinism_gate.py --port 2000 --n 5
```

The gate must print `GATE VERDICT: PASS` before any experimental run.

---

## Not recorded, and why

- **`git_commit` is empty in every trace written on 23 Aug** — this directory is not yet a git
  repository, so `config.git_commit()` returns `None`. Traces banked today carry an empty
  commit field. Initialising the repository is a prerequisite for any trace that will back a
  paper claim.
