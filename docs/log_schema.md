# Trajectory Log Schema

**Schema version:** `1.2.0`
**Defined in code:** [`src/trace_schema.py`](../src/trace_schema.py) — that module is the
single source of truth; this document describes it.
**Format:** Apache Parquet, Snappy compression, one file per episode.
**Stability:** Tomorrow's contract, certificate, and falsifier work reads these files.
Additive changes (new nullable columns) bump the minor version. Renaming, removing, or
changing the dtype of an existing column bumps the major version and requires re-banking
every trace.

---

## Layout: one row per simulation timestep

Ego quantities are **scalar columns**. Other actors are **parallel list columns** — within a
row, `actor_id[i]`, `actor_x_m[i]`, and `actor_vx_mps[i]` all describe the same actor.

Actor count may vary between rows (an actor can be destroyed mid-episode), so no consumer
may assume a fixed width. `trace_schema.validate_row` rejects ragged lists at write time.

**Why wide-with-lists rather than one row per (timestep, actor):** robustness is a min over
timesteps, and every predicate — clearance, TTC — needs the complete world state at one
instant. Wide means one row *is* one complete world state, so ρ is a single pass with no
groupby and no join.

**Why every actor field is duplicated per row rather than stored once:** so that ρ is
computable from the trace alone, with no CARLA import and no map access. That is what makes
the trace-store architecture work — traces banked on the 3090 stay analysable anywhere.

---

## Columns (45)

### Clock — 4 columns

| Column | Type | Null? | Meaning |
|---|---|---|---|
| `frame` | `int64` | no | CARLA server global frame counter. **Strictly monotonic.** Gaps mean dropped ticks. |
| `t_s` | `float64` | no | Seconds since episode start. First tick is exactly `0.0`. |
| `sim_elapsed_s` | `float64` | no | Raw `snapshot.timestamp.elapsed_seconds`, not reset per episode. Distinguishes "episode restarted" from "server restarted". |
| `delta_s` | `float64` | no | `snapshot.timestamp.delta_seconds` **as reported by the server**. Must equal `fixed_delta_seconds` on every tick. This is the field the clock-integrity gate checks. |

`delta_s` is logged rather than assumed because assuming it is exactly how a clock bug stays
invisible: if the server silently falls back to variable timestep, `t_s` computed as
`i * 0.05` would still look perfect while the physics underneath diverged.

### Ego pose — 6 columns

| Column | Type | Meaning |
|---|---|---|
| `ego_x_m`, `ego_y_m`, `ego_z_m` | `float64` | Position, CARLA world frame, metres |
| `ego_yaw_deg`, `ego_pitch_deg`, `ego_roll_deg` | `float64` | Rotation, degrees (CARLA's native unit — not converted, to avoid a needless lossy step) |

### Ego motion — 9 columns

| Column | Type | Null? | Meaning |
|---|---|---|---|
| `ego_vx_mps`, `ego_vy_mps`, `ego_vz_mps` | `float64` | no | Velocity vector, m/s |
| `ego_speed_mps` | `float64` | no | ‖v‖, m/s |
| `ego_ax_mps2`, `ego_ay_mps2`, `ego_az_mps2` | `float64` | no | Acceleration vector, m/s² |
| `ego_accel_long_mps2` | `float64` | no | **Signed longitudinal** acceleration: **a** projected onto the heading unit vector |
| `ego_jerk_long_mps3` | `float64` | **yes** | Finite difference of `ego_accel_long_mps2`. **NULL on the first row.** |

Two decisions worth stating, because both affect C5:

- **Longitudinal projection, not magnitude.** C5 bounds `|a|`. Using ‖**a**‖ would count
  centripetal acceleration during the left turn as if it were harsh braking, so a program
  that turns correctly would be scored as uncomfortable. Projecting onto heading measures
  what C5 is actually about.
- **Jerk is NULL, never 0.0, on the first row.** There is no previous sample, so there is no
  measurement. Writing `0.0` would fabricate one, and `min()` over a fabricated 0 silently
  changes ρ₅.

### Ego control — 3 columns

| Column | Type | Meaning |
|---|---|---|
| `ego_throttle`, `ego_brake` | `float64` | Applied control, [0, 1] |
| `ego_steer` | `float64` | Applied control, [−1, 1] |

Logged as *applied*, i.e. what the controller commanded this tick. Needed to distinguish
"the program asked for the brake and the physics did not deliver" from "the program never
asked".

### Ego bounding box — 3 columns

| Column | Type | Meaning |
|---|---|---|
| `ego_extent_x_m`, `ego_extent_y_m`, `ego_extent_z_m` | `float64` | Half-extents, metres |

Constant across an episode, logged per row anyway so clearance is computable from the trace
with no simulator.

### Traffic light — 2 columns

| Column | Type | Null? | Meaning |
|---|---|---|---|
| `tl_state` | `string` | yes | `Red` / `Yellow` / `Green` / `Off` / `Unknown`, for the light governing the ego approach. Read from the **resolved ego light actor**, so it is populated on every tick including while the ego is inside the junction. NULL only if that light could not be resolved. |
| `tl_elapsed_s` | `float64` | yes | Seconds the light has been in its current state |

### Behaviour-tree blame — 3 columns

| Column | Type | Null? | Meaning |
|---|---|---|---|
| `bt_node_id` | `string` | yes | ID of the leaf that was ticking |
| `bt_node_type` | `string` | yes | Node vocabulary type, e.g. `OncomingGapExceeds` |
| `bt_node_path` | `string` | yes | e.g. `root/Sequence/Fallback/OncomingGapExceeds` |

**All three are NULL for every trace banked on 23 August**, because today's ego is driven by
a hardcoded controller, not a tree. They are populated from 24 August when `py_trees` takes
over. They exist in v1.0.0 of the schema so that today's traces and tomorrow's traces share
one schema and can sit in the same table.

### Behaviour-tree tick path and commanded acceleration — 2 columns (added 1.1.0 / 1.2.0)

| Column | Type | Null? | Meaning |
|---|---|---|---|
| `bt_tick_path` | `string` | yes | Comma-joined `node_id`s of **every leaf evaluated this tick**, in order |
| `cmd_accel_mps2` | `float64` | yes | The acceleration the **program** asked for, m/s², signed |

`bt_tick_path` is what makes blame more than "which action ran". A tick reading
`n_2,n_6,n_7` instead of `n_2,n_3,n_4` says the gap test `n_3` was never reached because `n_2`
failed first — a different diagnosis and a different patch.

`cmd_accel_mps2` is read directly by C5. It is **not** derived from `ego_throttle`/`ego_brake`,
because those are the command *after* actuator slew limiting, so a harness constant would pin
`max|jerk_cmd|` identically for every program — measured, ρ₅ was −29.572 regardless of what the
tree asked for. Logging what the tree requested makes C5 a property of the program, which is
what C5 is for. NULL when no behaviour tree is driving.

### Manoeuvre phase — 1 column

| Column | Type | Null? | Meaning |
|---|---|---|---|
| `phase` | `string` | yes | `P1_approach` / `P2_yield_hold` / `P2_yield_clear` / `P3_commit` / `P4_settle` |

Recorded by the controller **as it happens**, never reconstructed from geometry afterwards.
The PCR metric (mean fraction of phases P1–P4 reached) reads this column directly. Deriving
it later from positions would create a second, silently different definition of "reached P3"
— the same failure mode `actor_role` avoids.

---

Returning to blame: `bt_node_*` is the column the certificate's `active_node` field is resolved from: take the argmin
timestep of ρ, read `bt_node_*` at that row. **Blame localization is a lookup, not an
inference** — which is only possible because the policy is a readable program.

### Other actors — 12 parallel list columns

| Column | Type | Meaning |
|---|---|---|
| `actor_id` | `list<int64>` | CARLA actor ID |
| `actor_type` | `list<string>` | Blueprint ID, e.g. `vehicle.tesla.model3` |
| `actor_role` | `list<string>` | `oncoming` / `lead` / `pedestrian` / `other` |
| `actor_x_m`, `actor_y_m`, `actor_z_m` | `list<float64>` | Position, metres |
| `actor_yaw_deg` | `list<float64>` | Heading, degrees |
| `actor_vx_mps`, `actor_vy_mps` | `list<float64>` | Velocity, m/s |
| `actor_speed_mps` | `list<float64>` | ‖v‖, m/s |
| `actor_extent_x_m`, `actor_extent_y_m` | `list<float64>` | Bounding box half-extents, metres |

> **Changed 30 Aug (schema-compatible, values only).** `tl_state` was previously read via
> `ego.get_traffic_light()`, which returns `None` once the ego leaves the light's trigger
> volume — i.e. throughout the junction traversal, which is exactly the interval C3 is about.
> Measured on the 24 Aug bank it was NULL on **92% of ticks**. Traces banked before 30 Aug
> carry that sparse column and **must not be scored for C3**; the column type is unchanged, so
> this is a value-semantics change rather than a schema break.
>
> `actor_role` now also takes the value **`lead`** — one vehicle spawned ahead of the ego in
> the ego's own lane, required for C4 to be non-vacuous. Traces banked before 30 Aug contain
> no `lead` actor and score C4 as vacuous.

`actor_role` is **assigned at spawn time by the scenario runner and logged**, never inferred
later from geometry. C2 needs to know which vehicles are oncoming; reconstructing that from
positions after the fact would be a second, silently different definition of "oncoming".

---

## Episode metadata

Written **twice**, deliberately:

1. **Parquet file-level key-value metadata** — travels with the data, survives file moves.
2. **A sidecar `<episode_id>.json`** — human-readable, greppable, survives tools that drop
   Parquet metadata.

Contents:

| Key | Meaning |
|---|---|
| `episode_id` | Unique run identifier |
| `schema_version` | `1.0.0` |
| `status` | `ok` / `timeout` / `collision` / `spawn_failed` / `exception` / `server_lost` |
| `scenario_params` | The falsifier parameter dict that produced this run, verbatim |
| `param_hash` | SHA-256 of the canonicalized parameter dict — the simulation cache key |
| `seeds` | `{python, numpy, traffic_manager}` actually applied |
| `carla_server_version`, `carla_client_version` | Both, so a mismatch is visible in the data |
| `map`, `fixed_delta_seconds`, `max_substep_delta_time`, `max_substeps` | Timing/physics settings in force |
| `n_ticks` | Rows written |
| `wall_clock_s` | Wall-clock duration of the episode |
| `real_time_factor` | `(n_ticks * fixed_delta_seconds) / wall_clock_s` |
| `git_commit` | Repo commit at run time, if available |

### `status` is not optional

A run with `status != "ok"` may have a partial trajectory or none. `trace_schema.TERMINAL_STATUSES`
lists the ones for which **ρ is undefined**. Those runs are counted separately and are never
pooled with runs that produced a real trajectory — the same rule that project rule 3 applies to
malformed vs unsafe program output, for the same reason: they are different results.

---

## Reading a trace

```python
import pyarrow.parquet as pq

tbl = pq.read_table("data/traces/ep_000123.parquet")
meta = {k.decode(): v.decode() for k, v in tbl.schema.metadata.items()}
df = tbl.to_pandas()
```

`float64` throughout. `float32` would round at ~1e-7 relative, which is the same order as the
determinism tolerance the gate is trying to measure — the storage format would corrupt the
measurement. Disk is not a constraint (1.4 TB free).
