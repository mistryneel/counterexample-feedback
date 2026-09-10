# `.bt` DSL Reference

**Spec:** 01_TECHNICAL_SPEC_v2.md §4 · **Code:** `src/bt_vocabulary.py`, `src/program_parser.py`

The program representation the LLM writes and patches. Owning the AST is required for tree edit
distance, node-level blame, and pre-execution validation — all three are load-bearing for the
paper.

---

## Grammar

```
Selector()
  Sequence()
    TrafficLightIsGreen()
    OncomingGapExceeds(gap_s=3.0)
    CommitTurn(v_mps=5.0, accel_mps2=1.5)
  Sequence()
    DistanceToStopLineBelow(dist_m=12.0)
    HoldAtStopLine(decel_mps2=2.0)
  Cruise(v_mps=8.0, accel_mps2=1.2)
```

Rules, and there are only five:

1. One node per line.
2. **Two spaces** of indentation per level. Nothing else; tabs are rejected.
3. `NodeName(param=value, param=value)`. The `()` may be omitted when there are no parameters.
4. `#` starts a comment. Blank lines are ignored.
5. Exactly one root.

### Why this shape

**Parentheses rather than bare `name value` pairs** because the call form matches the ProgPrompt
import block the agent is shown, and matching forms cost fewer malformed samples.

**Indentation rather than nested brackets** because an unbalanced bracket is the commonest LLM
structural error and it invalidates the *whole* program, whereas a bad indent invalidates one
line and produces a precise error message. Since malformed output is a separately counted
outcome (project rule 3), the format should not manufacture failures unrelated to the
research question.

---

## Node vocabulary

Generated from `bt_vocabulary.py` — run `python src/bt_vocabulary.py` for the exact import
block presented to the agent, which cannot disagree with the validator because both read the
same specs.

### Composites

| Node | Behaviour |
|---|---|
| `Sequence()` | Children in order; fail at the first failure; succeed only if all succeed |
| `Selector()` | Children in order; succeed at the first success. The **last** child is the fallback |

Both compile with `memory=False`, so conditions are re-evaluated from the start every tick. With
`memory=True` a Sequence would resume after its last running child and skip the yield test —
the program would stop reacting to oncoming traffic after committing once.

### Conditions — return SUCCESS or FAILURE, never RUNNING

| Node | Parameters | Meaning |
|---|---|---|
| `OncomingGapExceeds` | `gap_s` [0, 15] | Nearest oncoming vehicle needs ≥ `gap_s` to reach the conflict zone. **This is the yield test** |
| `EgoSpeedBelow` | `v_mps` [0, 20] | Ego slower than `v_mps` |
| `DistanceToStopLineBelow` | `dist_m` [0, 60] | Ego within `dist_m` of the stop line (negative once past) |
| `InConflictZone` | — | Ego inside the conflict zone |
| `TrafficLightIsGreen` | — | Ego's signal is green |
| `PathIsClear` | `dist_m` [0, 60] | No actor within `dist_m` along the turn path |
| `WaitedLongerThan` | `t_s` [0, 30] | Ego stationary for `t_s` — the deadlock escape |

### Actions — issue a control command, return RUNNING

| Node | Parameters | Meaning |
|---|---|---|
| `Cruise` | `v_mps`, `accel_mps2` | Follow the route at `v_mps` |
| `Decelerate` | `v_mps`, `decel_mps2` | Slow to `v_mps` |
| `HoldAtStopLine` | `decel_mps2` | Stop at the line and hold |
| `CommitTurn` | `v_mps`, `accel_mps2` | Drive through the conflict zone; SUCCESS once clear |
| `Creep` | `v_mps`, `accel_mps2` | Edge forward for visibility |
| `EmergencyStop` | `decel_mps2` | Brake as hard as `decel_mps2` allows |

### Every speed-changing action takes an explicit `accel_mps2` / `decel_mps2`

This is deliberate and load-bearing. **C5 is computed from commanded acceleration**
(`docs/c5_decision.md`). If the tree only chose target speeds and a fixed PID converted them to
throttle and brake, C5 would score the PID and not the tree — measured, ρ₅ was a **constant**
across 300 traces and discriminated nothing.

With the ramp as a program parameter, ρ₅ separates programs:

| Program | `max\|a_cmd\|` | ρ₅ |
|---|---|---|
| gentle (`accel 0.8`, `decel 1.0`) | 1.00 | **+2.00** ✅ |
| reference (`accel 1.5`, `decel 2.0`) | 2.00 | **+1.00** ✅ |
| harsh (`accel 5.5`, `EmergencyStop 7.5`) | 7.50 | **−4.50** ❌ |

That is decision D4 working: "brake hard and never turn" is now a *measurably* worse program.

### Field names carry their type

`v_mps`, `gap_s`, `dist_m`, `t_s`, `accel_mps2`, `decel_mps2` (project conventions). `gap`
alone gets read as metres by one sample and seconds by the next.

---

## Validator (spec §4.4)

`validate()` checks, in order:

| Check | Example message |
|---|---|
| Grammar conformance | `line 2: indentation of 3 spaces is not a multiple of 2` |
| Node is in the vocabulary | `line 2: unknown node 'Teleport'. Permitted: ...` |
| Composite arity | `line 1: Sequence needs at least 1 child(ren), has 0` |
| Leaves take no children | `line 2: OncomingGapExceeds is a condition and cannot have children` |
| Parameter names | `line 2: OncomingGapExceeds has no parameter 'gap'` |
| Required parameters present | `line 2: ... is missing required parameter 'gap_s'` |
| Parameter type and range | `line 2: gap_s=99.0 is outside the permitted range [0.0, 15.0]` |
| **No unreachable subtrees** | `line 3: unreachable. HoldAtStopLine always returns RUNNING, so the 1 sibling(s) after it can never be reached` |
| Depth ≤ 8 | `tree depth 10 exceeds the maximum of 8` |

**Unreachability** is a real static property here, not a heuristic: every action returns
RUNNING, and RUNNING halts sibling evaluation in both Sequence and Selector, so any sibling
after an action is dead code. Dead code would also inflate tree edit distance, corrupting the
interpretability metric.

The validator's behaviour is exercised by the parser tests run during development; the released
tests are in `tests/`.

### Grammar-only fallback

`validate(root, grammar_only=True)` runs only what a successful parse already implies, and
returns a warning naming everything it skipped. This is the documented degraded mode from the
build plan — it was **not needed**; the full validator was finished well before the 15:30
checkpoint.

---

## Blame localization

Four columns are written every tick (`docs/log_schema.md`, schema ≥ 1.1.0):

| Column | Contents |
|---|---|
| `bt_node_id` | The **action leaf** that issued the control command |
| `bt_node_type` | Its vocabulary type |
| `bt_node_path` | e.g. `Selector/Sequence/HoldAtStopLine` |
| `bt_tick_path` | Comma-joined ids of **every leaf evaluated this tick, in order** |

`bt_tick_path` is what makes blame more than "which action ran". A tick reading
`n_2,n_6,n_7` instead of `n_2,n_3,n_4` says the gap test `n_3` was **never reached** because
`n_2` failed first — a different diagnosis and a different patch.

This is a **lookup, not an inference**: each leaf appends itself as it is ticked. It is possible
only because the policy is a readable program, which is why the interpretability claim and the
blame mechanism are the same property.

Worked example, from a real episode. ρ argmin at t = 11.15 s:

```
bt_node_id   = n_7
bt_node_type = HoldAtStopLine
bt_node_path = Selector/Sequence/HoldAtStopLine
bt_tick_path = n_2,n_3,n_6,n_7
```

Read: `n_2` (TrafficLightIsGreen) passed, `n_3` (OncomingGapExceeds) **failed**, so the first
Sequence failed and the Selector fell through to `n_6`/`n_7`. The certificate's `active_node`
is `n_7`; the actionable fact is that `n_3`'s threshold is what gated it.

---

## AST and tree edit distance

`BTNode` carries `name`, `params`, `children`, `line`, `node_id`, `path`.

- `node_id` is positional (`n_0`, `n_1`, … pre-order) and therefore **changes when the tree is
  edited**.
- `path` is the stable-ish handle quoted in certificates.
- Both are recorded so a reader can cross-check them.

`to_tuple()` gives a canonical hashable form (name, sorted rounded params, children) — the label
space for tree edit distance. `to_source()` round-trips: parse → source → parse is identical and
`to_tuple()` is stable across the round trip.

---

## Reference program

`data/scenarios/reference_program.bt` — hand-written, used to validate the pipeline.
**Not** the frozen baseline; that is LLM-synthesized on 25 Aug into `baseline_program.bt`.

It is deliberately imperfect so the falsifier has something to find: the gap test sits exactly
on `tau_yield` with no margin, nothing re-checks the path once committed, and there is no
escape from a deadlock if no acceptable gap ever appears.
