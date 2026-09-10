# RUNBOOK

Operations for the CARLA experiment rig. **Run the health check at the start of every session.**

---

## Quick reference

```bash
scripts/start_carla.sh --port 2000 --gpu 0     # start (blocks until connectable)
scripts/health_check.py                         # verify; exits non-zero on mismatch
scripts/stop_carla.sh --port 2000               # stop one instance
scripts/stop_carla.sh --all                     # stop every instance
scripts/determinism_gate.py --port 2000 --n 5   # full Phase 3 gate
scripts/run_campaign.py --n 100 --port 2000 --tag bank --shard 0
```

All scripts are **idempotent and safe to re-run**.

---

## Start of session

```bash
scripts/start_carla.sh --port 2000 --gpu 0
```

Blocks until CARLA **actually accepts a client connection** — not until the container is up,
and not for a fixed sleep. Typical time to ready: **~5 s**. Prints the server version, client
version, and current map.

Refuses to start twice on one port: if the port is already listening, or a container named
`carla_<port>` is already running, it exits 1 rather than creating a second server.

```bash
scripts/health_check.py
```

Checks, and **exits non-zero on any mismatch**:

- client/server version identical
- map matches `config/sim.yaml`
- synchronous mode, `fixed_delta_seconds`
- substepping parameters **as the live server has them**, and the condition
  `fixed_delta ≤ max_substep_delta_time × max_substeps`
- stale actors from a crashed run (warning)
- junction cache present

---

## Running a campaign

```bash
scripts/run_campaign.py --n 300 --port 2000 --tm-port 8000 --gpu 0 --seed 1 --tag bank --shard 0
```

- One persistent client for the whole campaign
- Every episode wrapped: an exception returns a sentinel, never kills the run
- **Checkpoints after every episode** (append + flush + `fsync`) — a crash costs one run
- **Resumable**: re-running skips episodes already in the manifest
- Simulation cache: an identical parameter set is never re-run
- Watches the server; if it dies, restarts it and continues

Manifest: `data/results/campaign_<tag>_<shard>.jsonl`, one JSON record per episode.

### Parallel campaign — use 3 instances, not more

```bash
for i in 0 1 2; do
  scripts/start_carla.sh --port $((2000+i*10)) --gpu $i
done
for i in 0 1 2; do
  scripts/run_campaign.py --n 100 --port $((2000+i*10)) --tm-port $((8000+i*10)) \
      --gpu $i --tag bank --shard $i &
done
wait
```

**Each instance needs its own `--tm-port`.** Two instances sharing a Traffic Manager port
collide on bind and the second fails.

Measured throughput:

| Instances | Aggregate |
|---|---|
| 1 | 1.07 ep/s |
| **3** | **3.28–4.05 ep/s** |
| 6 | 3.32 ep/s (**no gain**) |

**CPU is the binding resource, not VRAM.** Each instance draws ~350% CPU (≈3.5 of 24 threads).
At 6 instances the machine saturates (load average 15.4) while VRAM sits at 5.8 GB of 24 GB per
GPU. Three instances is the operating point.

---

## Shutdown

```bash
scripts/stop_carla.sh --port 2000     # one instance
scripts/stop_carla.sh --all           # everything
```

Stops and removes the container, then terminates orphaned `CarlaUE4-Linux-Shipping` /
`CarlaUE4.sh` processes **carrying that rpc port**, escalating to SIGKILL only for the PIDs it
actually signalled. Verifies the port is free and exits non-zero if not.

> The orphan is the thing to care about: `CarlaUE4.sh` spawns
> `CarlaUE4-Linux-Shipping`, and killing the wrapper alone leaves the child holding the RPC
> port, so the next `start_carla.sh` fails with "already listening".

---

## Troubleshooting

Every entry below was hit on 23 Aug 2026 and is recorded with the fix that worked.

| Symptom | Cause | Fix |
|---|---|---|
| `time-out of 30000ms while waiting for the simulator` | Server not up, or died | `scripts/stop_carla.sh --port N && scripts/start_carla.sh --port N` |
| Container shows `Exited (139)` a few seconds after a run | **`reload_world()` segfaults CARLA 0.9.16** ~3–4 s after client disconnect | Keep `reload_between_episodes: false` in `config/sim.yaml`. Do not call `reload_world()` anywhere |
| `terminate called after throwing 'carla::client::TimeoutException'` + core dump, uncatchable | A live `carla.Client` outlived its server. libcarla's background thread throws from a non-Python context → `std::terminate` | Never restart the server from a process that has held a client. Do restarts from a process that never imports `carla` (see `scripts/seed_sensitivity.py`) |
| Script hangs forever at startup, no output | `sg docker -c ...` **prompting for a password on stdin** because the user is not in `/etc/group` for docker | `sudo usermod -aG docker $USER`, log out and back in. Scripts now check `/etc/group` first and redirect stdin from `/dev/null` |
| `permission denied ... /var/run/docker.sock` | Not in the docker group | `sudo usermod -aG docker $USER`; in an existing shell use `sg docker -c "..."` |
| `trying to create rpc server for traffic manager; but ... bind error` | TM port still in `TIME_WAIT` from a previous process, or two instances sharing a TM port | Give each instance its own `--tm-port`. `scripts/tm_probe.py` retries the same port for up to 120 s |
| Stopping one instance kills all of them | **Fixed 23 Aug.** SIGKILL escalation in `stop_carla.sh` was not port-filtered | Ensure `stop_carla.sh` escalates only to `TARGET_PIDS`. Regression test: start 2000 + 2010, stop 2010, confirm 2000 survives |
| `WARNING: sensor object went out of the scope but the sensor is still alive` | Sensor destroyed while still listening | `sensor.stop()` before destroying. Handled in `CarlaBackend._destroy_spawned` |
| `ImportError: cannot import name ... (most likely due to a circular import)` from `random` | A local file named `bisect.py` shadowing the stdlib module that `random` imports | Never name a script after a stdlib module |
| ρ₂ looks plausible but the "oncoming" car is in the ego's lane | Oncoming corridor derived from the turn-**exit** waypoint, which is inside the junction where `get_left_lane()` returns `None` | Resolve the oncoming approach as the controlled approach ~180° opposed to the ego's. Verified in `junction.yaml` |
| Ego drives through on **Red** although the spec requires permissive green | Cached traffic-light **actor ids** are reassigned on every world reload | Resolve lights by geometry each episode (`CarlaBackend.resolve_traffic_lights`) |
| Determinism check fails with deviation exactly equal to the vehicle spacing | Actor list columns **permuted** — `world.get_actors()` order is not stable | Sort by the `(role rank, spawn index)` key assigned at spawn |
| Determinism check fails only in the last few rows | Oncoming vehicles wrecking at the map boundary long after leaving the scenario | `oncoming_retire_past_cz_m: 80.0` retires them once they are clear |
| `delta_s` "not exactly 0.05" | **CARLA stores `delta_seconds` as float32.** It reports `0.05000000074505806` | Compare against `float32(0.05)`, not the float64 literal. Deviation is then exactly 0 |
| Subprocess prints nothing before aborting | stdout buffered when redirected; buffer lost on SIGABRT | Run with `python -u` |
| Deceleration of −27 m/s² below 5 m/s | Intrinsic CARLA low-speed braking regime, not brake torque and not the accelerometer | Not fixable. See the determinism report; affects C5 scoping |

---

## Recovery

**Server died mid-campaign.** Nothing is lost — the campaign checkpoints after every episode
and `run_campaign.py` detects a dead server and restarts it. To resume manually, re-run the
same command with the same `--tag` and `--shard`; already-banked episodes are skipped.

**Everything is wedged.**

```bash
scripts/stop_carla.sh --all
```

then confirm nothing survives:

```bash
pgrep -af CarlaUE4 ; ss -ltn | grep -E ':20[0-9]0 '
```

**Suspected determinism regression.** Re-run the gate. It must print `GATE VERDICT: PASS`:

```bash
scripts/determinism_gate.py --port 2000 --n 5
```

If any stage fails, **stop**. Do not run experiments against a rig that fails the gate.

---

## Gotchas that are not errors

- **`tl_state` is null for most rows.** `Actor.get_traffic_light()` returns `None` unless the
  ego is inside a light's trigger volume. Null means "no light governing the ego right now",
  not a logging failure.
- **`bt_node_*` columns are null in every trace banked on 23 Aug.** The ego was a hardcoded
  controller, not a behaviour tree. They populate from 24 Aug.
- **`frame` and `sim_elapsed_s` differ between otherwise-identical episodes.** They are
  absolute server counters and keep advancing on a persistent server. Only their *internal*
  consistency is meaningful.
- **The first `ego_jerk_long_mps3` is null, not 0.0.** There is no previous sample, so there is
  no measurement; a fabricated 0.0 would enter `min()` when C5 lands.
