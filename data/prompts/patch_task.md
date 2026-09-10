You patch behaviour-tree programs for an autonomous vehicle in a driving simulator. You output ONLY a program in the .bt DSL described below, inside a single ``` fenced block, with no prose before or after it.

{vocab}

GRAMMAR -- there are only five rules:
1. One node per line.
2. Two spaces of indentation per level. Tabs are rejected.
3. NodeName(param=value, param=value). The () may be omitted when there are no
   parameters.
4. # starts a comment. Blank lines are ignored.
5. Exactly one root.

Composite semantics, which matter:
- Sequence runs children in order, fails at the first failure, succeeds only if
  all succeed.
- Selector runs children in order and succeeds at the first success; its LAST
  child is the fallback.
- Both re-evaluate every condition from the top on EVERY tick (20 Hz). There is
  no memory of which child was running last tick. A Sequence will therefore
  abandon a running action the moment one of its earlier conditions stops
  holding.

THE MANOEUVRE
The program performs an UNPROTECTED LEFT TURN at a signalised four-way junction.
"Unprotected" means the ego has a circular green ball, not a green arrow: the
turn is legally permitted but oncoming traffic has right of way, and the ego
must find its own gap.

- The ego approaches the junction, must yield to oncoming traffic, turn left
  across their path, and settle into the target lane.
- Between one and three oncoming vehicles travel straight through at a constant
  6 to 16 m/s. They do not always slow down for the ego.
- One LEAD VEHICLE travels ahead of the ego in the ego's own lane at 6 m/s. It
  decelerates to a stop at the stop line, waits, then drives on and clears.
- The ego's signal is green on approach, then turns yellow for 3 s, then red for
  6 s, then returns to green.

THE FIVE SAFETY CONTRACTS
Each is a signed margin: positive means satisfied, negative means violated.

  C1  no collision -- minimum bounding-box clearance to any actor, in metres.
  C2  yield -- while inside the conflict zone, the nearest oncoming vehicle
      must need at least {tau_yield} s to reach it. Margin in seconds.
  C3  do not ENTER the intersection on red. Margin in seconds: positive is the
      green time remaining at the moment of entry, negative is how long the
      light had already been red. Being caught inside when the light changes is
      NOT penalised -- once you have lawfully entered you are expected to clear.
  C4  keep an RSS-safe longitudinal distance to the LEAD vehicle. The required
      distance grows with your speed and shrinks with the lead's. At 8 m/s
      behind a lead doing 6 m/s it is about 20 metres. Margin in metres.
  C5  comfort -- commanded longitudinal acceleration must stay within
      {a_comfort} m/s^2.

The overall score rho is the MINIMUM of the five, so the weakest one decides.

AND ON COMPLETING THE TASK
A program that never enters the junction violates nothing and still fails. It
must actually complete the turn and settle into the target lane. Waiting
forever is not a solution; there is a deadlock-escape condition in the
vocabulary for the case where no acceptable gap ever appears.

THE PROGRAM YOU ARE PATCHING

```
{program}
```

WHAT YOU ARE ASKED TO DO
This program was run on one traffic situation and violated a safety contract.
Patch it so that it no longer violates a contract in that situation, while still
completing the turn in general.

PATCH, DO NOT REWRITE. Make the smallest edit that fixes the failure -- change a
threshold, add a guard condition, insert a node, or reorder branches. Do not
restructure the program, do not rename anything, and do not change parts that
are unrelated to the failure. A rewrite that happens to pass is not a repair.

Also bear in mind:
- The failure below is one situation, not the whole space. A patch tuned so
  tightly that it only fixes this situation will fail the regression suite, and
  a patch so conservative that the ego stops turning fails the task.
- Conditions are re-checked every tick. If you gate the turn on a condition that
  stops holding halfway through, the ego will abandon the turn inside the
  junction, which is far more dangerous than completing it.

REPORT ON THE OBSERVED FAILURE

{feedback}

Output the complete patched program in a single ``` fenced block, with no prose
before or after it.
