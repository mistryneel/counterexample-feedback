"""Trajectory log schema — the single source of truth.

Both `carla_backend` (writer) and `stl` (reader) import from here so the
schema cannot drift between them. Documented in `docs/log_schema.md`.

Layout: ONE ROW PER SIMULATION TIMESTEP.

Ego quantities are scalar columns. Other actors are stored as parallel list
columns -- `actor_id[i]`, `actor_x_m[i]`, `actor_vx_mps[i]` all refer to the
same actor at index i within a row. Actor count may differ between rows (an
actor can be destroyed mid-episode), so nothing may assume a fixed width.

Why wide-with-lists rather than one row per (timestep, actor): robustness is
computed as a min over timesteps, and every predicate (clearance, TTC) needs
the complete world state at a single instant. Wide means one row is one
complete world state, so rho computation is a single pass with no groupby.

NOTE ON DEVIATION FROM THE PLANNED REPO LAYOUT: this module is not in the
planned layout. It exists because the schema has two consumers and
duplicating it in both is exactly how a schema silently drifts.
"""

from __future__ import annotations

import pyarrow as pa

SCHEMA_VERSION = "1.2.0"

F64 = pa.float64()
LF64 = pa.list_(pa.float64())
LI64 = pa.list_(pa.int64())
LSTR = pa.list_(pa.string())

# --------------------------------------------------------------------------
# Sentinel returned by a failed episode. Never confuse with a real trajectory.
# --------------------------------------------------------------------------
STATUS_OK = "ok"
STATUS_TIMEOUT = "timeout"
STATUS_COLLISION = "collision"
STATUS_SPAWN_FAILED = "spawn_failed"
STATUS_EXCEPTION = "exception"
STATUS_SERVER_LOST = "server_lost"

TERMINAL_STATUSES = {
    STATUS_SPAWN_FAILED,
    STATUS_EXCEPTION,
    STATUS_SERVER_LOST,
}
"""Statuses meaning 'no usable trajectory'. rho is undefined for these and
they must NEVER be pooled with a run that produced a real trajectory --
same rule as project rule 3 for malformed vs unsafe program output."""


TRAJECTORY_SCHEMA = pa.schema(
    [
        # --- clock -------------------------------------------------------
        # frame is the CARLA server's global frame counter. Strictly
        # monotonic. Gaps mean dropped ticks -> determinism is broken.
        pa.field("frame", pa.int64(), nullable=False),
        # t_s: seconds since episode start (first tick == 0.0).
        pa.field("t_s", F64, nullable=False),
        # sim_elapsed_s: raw snapshot.timestamp.elapsed_seconds. Not reset per
        # episode. Kept because it distinguishes "the episode restarted" from
        # "the server restarted".
        pa.field("sim_elapsed_s", F64, nullable=False),
        # delta_s: snapshot.timestamp.delta_seconds, as reported by the SERVER.
        # This is the field the clock-integrity gate checks. It must equal
        # fixed_delta_seconds exactly on every tick.
        pa.field("delta_s", F64, nullable=False),

        # --- ego pose ----------------------------------------------------
        pa.field("ego_x_m", F64, nullable=False),
        pa.field("ego_y_m", F64, nullable=False),
        pa.field("ego_z_m", F64, nullable=False),
        pa.field("ego_yaw_deg", F64, nullable=False),
        pa.field("ego_pitch_deg", F64, nullable=False),
        pa.field("ego_roll_deg", F64, nullable=False),

        # --- ego motion --------------------------------------------------
        pa.field("ego_vx_mps", F64, nullable=False),
        pa.field("ego_vy_mps", F64, nullable=False),
        pa.field("ego_vz_mps", F64, nullable=False),
        pa.field("ego_speed_mps", F64, nullable=False),
        pa.field("ego_ax_mps2", F64, nullable=False),
        pa.field("ego_ay_mps2", F64, nullable=False),
        pa.field("ego_az_mps2", F64, nullable=False),
        # Signed longitudinal acceleration: ego_accel projected onto heading.
        # This is the quantity C5 bounds, not the raw magnitude -- |a| would
        # make centripetal acceleration during the turn look like harsh
        # braking.
        pa.field("ego_accel_long_mps2", F64, nullable=False),
        # Finite-difference jerk of ego_accel_long_mps2. NULL on the first
        # row (no previous sample). Nullable on purpose: a 0.0 here would be
        # a fabricated measurement.
        pa.field("ego_jerk_long_mps3", F64, nullable=True),

        # --- ego control applied this tick --------------------------------
        pa.field("ego_throttle", F64, nullable=False),
        pa.field("ego_brake", F64, nullable=False),
        pa.field("ego_steer", F64, nullable=False),

        # --- ego bounding box half-extents (metres) ------------------------
        # Constant across an episode, but logged per row so that clearance is
        # computable from the trace ALONE, with no CARLA import. This is what
        # lets rho be recomputed on a machine with no simulator.
        pa.field("ego_extent_x_m", F64, nullable=False),
        pa.field("ego_extent_y_m", F64, nullable=False),
        pa.field("ego_extent_z_m", F64, nullable=False),

        # --- traffic light governing the ego approach ----------------------
        pa.field("tl_state", pa.string(), nullable=True),
        pa.field("tl_elapsed_s", F64, nullable=True),

        # --- behaviour-tree blame placeholder ------------------------------
        # NULL for the whole of today: the hardcoded controller is not a tree.
        # Populated from 24 Aug when py_trees drives the ego. The certificate's
        # `active_node` field resolves the argmin timestep against these.
        pa.field("bt_node_id", pa.string(), nullable=True),
        pa.field("bt_node_type", pa.string(), nullable=True),
        pa.field("bt_node_path", pa.string(), nullable=True),
        # Comma-joined node_ids of every LEAF evaluated on this tick, in order.
        # Added in schema 1.1.0. This is what makes blame more than "which
        # action ran": it shows which CONDITIONS gated the branch. A tick that
        # reads "n_2,n_6,n_7" instead of "n_2,n_3,n_4" says the gap test n_3
        # was never reached because n_2 failed first -- a different diagnosis,
        # and a different patch.
        pa.field("bt_tick_path", pa.string(), nullable=True),

        # The acceleration the PROGRAM asked for this tick, m/s^2, signed.
        # Added in schema 1.2.0 and read directly by C5.
        #
        # Why not derive it from ego_throttle/ego_brake: those are the command
        # AFTER actuator slew limiting, so the limit -- a harness constant --
        # pins max|jerk| to the same value for every program, giving C5 zero
        # variance. Measured: rho_5 was identically -29.572 across programs.
        # Logging what the tree ASKED FOR makes C5 a property of the program,
        # which is what contract C5 is for.
        # NULL when no behaviour tree is driving.
        pa.field("cmd_accel_mps2", F64, nullable=True),

        # --- manoeuvre phase ----------------------------------------------
        # P1_approach | P2_yield_hold | P2_yield_clear | P3_commit | P4_settle
        # Recorded by the controller as it happens, NOT reconstructed from
        # geometry afterwards. The PCR metric (mean fraction of phases
        # reached) reads this column; reconstructing it later would create a
        # second, silently different definition of "reached P3".
        pa.field("phase", pa.string(), nullable=True),

        # --- other actors, parallel lists ----------------------------------
        pa.field("actor_id", LI64, nullable=False),
        pa.field("actor_type", LSTR, nullable=False),
        # role: "oncoming" | "lead" | "pedestrian" | "other"
        # Assigned at spawn time by the scenario runner, not inferred later.
        pa.field("actor_role", LSTR, nullable=False),
        pa.field("actor_x_m", LF64, nullable=False),
        pa.field("actor_y_m", LF64, nullable=False),
        pa.field("actor_z_m", LF64, nullable=False),
        pa.field("actor_yaw_deg", LF64, nullable=False),
        pa.field("actor_vx_mps", LF64, nullable=False),
        pa.field("actor_vy_mps", LF64, nullable=False),
        pa.field("actor_speed_mps", LF64, nullable=False),
        pa.field("actor_extent_x_m", LF64, nullable=False),
        pa.field("actor_extent_y_m", LF64, nullable=False),
    ]
)

COLUMNS = [f.name for f in TRAJECTORY_SCHEMA]

SCALAR_COLUMNS = [
    f.name for f in TRAJECTORY_SCHEMA if not pa.types.is_list(f.type)
]
LIST_COLUMNS = [f.name for f in TRAJECTORY_SCHEMA if pa.types.is_list(f.type)]


def empty_row() -> dict:
    """A row dict with every column present and empty lists for list columns.

    Used so a writer can never accidentally omit a column -- an omitted
    column becomes an all-null column in Parquet, which reads back as
    plausible data.
    """
    row = {name: None for name in SCALAR_COLUMNS}
    for name in LIST_COLUMNS:
        row[name] = []
    return row


def validate_row(row: dict) -> None:
    """Raise if a row is missing columns or has ragged actor lists."""
    missing = set(COLUMNS) - set(row)
    if missing:
        raise ValueError(f"trace row missing columns: {sorted(missing)}")
    extra = set(row) - set(COLUMNS)
    if extra:
        raise ValueError(f"trace row has unknown columns: {sorted(extra)}")
    lengths = {name: len(row[name]) for name in LIST_COLUMNS}
    if len(set(lengths.values())) > 1:
        raise ValueError(f"ragged actor list columns: {lengths}")
