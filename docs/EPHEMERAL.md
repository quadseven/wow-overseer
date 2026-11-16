# Ephemeral worlds: decrees

An ephemeral (proving) world is a throwaway copy of the realm that bots can play
in without touching live progression. A decree is the one YAML file under
`data/decrees/` that says who is in that world, where, in what state, what to do, and
which SQL or log assertions decide the verdict. Tracking issue: #2343.

Last checked: 2026-11-15.

## What ships today, and what does not

Shipped in this repository now:

- the decree schema v1 and `python3 -m ephemeral lint`;
- `data/decrees/anchors.yaml`, the only place coordinates may live;
- `python3 -m ephemeral acts`, which prints a decree's `act` timeline as the
  command rows it becomes;
- `python3 -m ephemeral seed`, which compiles `cast` and `arrange` to SQL behind a
  loopback-only guard (see Seed below);
- `python3 -m ephemeral judge`, which runs a decree's `act` timeline, evaluates
  its `observe` assertions and writes a PASS, FAIL or INVALID verdict as a result
  ConfigMap (see Judge below);
- `python3 -m ephemeral submit`, `dispatch` and `collect`, the PC-side runner
  (see Runner below);
- three worked example decrees in `data/decrees/`.

Not shipped: the world itself. The cluster side and the world image live outside
this repository, and the whole chain from decree file to a posted verdict has not
been run end to end. The seed step, the judge and the runner have only been run
against fake connections, a fake `kubectl` and a fake `gh` in unit tests, never
against a real database, cluster or GitHub issue.

## Requesting a proving run

The runner is out of scope for the decree-writing steps below; its commands are
under Runner. The part that comes first is writing the decree:

1. Write the decree for the defect: a starting state, the action, and
   observations that fail on the broken image and hold on the fixed one.
2. Run `python3 -m ephemeral lint data/decrees/<name>.yaml` until it has no errors.
   Fill the issue number and fix commit (a `TODO` is only a warning).
3. Open a pull request with the decree. A fix pull request should carry its
   decree, so the red-then-green evidence exists before the fix merges.

A run is the decree executed against the image without the fix (control) and
with it (treatment), several times each. Request one with `submit`.

## What a run can and cannot prove

A proving run is a controlled experiment on a copy of the realm's data. A pass is evidence for the live realm only when all of these hold:

- the treatment image is the one the live realm runs or will run;
- the fix is present in the treatment image and absent from the control;
- the preconditions were observed in the same run, so "nothing bad happened"
  cannot mean "nothing happened";
- the same decree failed on the control, so the check can fail at all;
- the evidence is state the game core wrote (respawn rows, skill rows, money and
  slot changes), not a status flag.

It cannot prove, and a decree for these should be refused or downgraded:

- anything that lives in code the world does not run (bridge code with the bridge
  off, language-model choices, the map site and UI);
- behaviour that depends on a client-driven character, because every character
  in a proving world is headless;
- population effects such as the travel queue, dungeon-finder matching or the
  auction house, which need the full bot population;
- wall-clock effects over hours, unless the decree seeds timestamps, in which
  case it tests only the seeded path;
- a scenario made unreachable by over-granting, hand-placed state or config
  changes on the path under test.

Lint holds a few of these lines now (grants need a `ceiling`, no literal
coordinates, a bridge-repo fix needs the bridge on). It does not check whether a
decree can actually reach its scenario; only a run can.

## How it complements fidelity (#2281) and liveproof (#2125)

- The fidelity suite (#2281) replays captured realm truth offline in CI. It is
  fast and needs no world, but it cannot show behaviour that only appears when
  bots actually play: movement, rendezvous, party formation, combat.
- Liveproof (#2125) probes the live realm on a schedule. It sees real play, but
  only when the live guilds happen to reach the same state again, and it has no
  control arm.
- A proving run plays bots in a throwaway copy from a chosen starting state, with
  a control arm. It complements both and replaces neither: use fidelity for
  logic that can be replayed, liveproof for what the live realm does, and a
  proving run for behaviour that needs bots playing from a known state.

## Lint a decree

    python3 -m ephemeral lint data/decrees/<name>.yaml        # warnings pass
    python3 -m ephemeral lint --strict data/decrees/<name>.yaml  # warnings fail

No cluster is needed. The reader is a strict YAML subset (`ephemeral/miniyaml.py`)
because the unit suite has no YAML parser. Table and column names in observation
SQL are checked against a snapshot of the game databases
(`ephemeral/data/acore_schema.json`), so a mistyped name is a lint error.

## Shape

    decree: v1
    id: <kebab-case>
    proves: [{repo: owner/name, issue: <n or TODO>, criterion: "<live-check box text>"}]
    fix: {repo: owner/name, commit: <sha or TODO>}
    world: {class: lean|full, image: follow-dev, bridge: "off"|"on", random_bots: 0, config: {}}
    runs: {control: 3, treatment: 3}
    duration: 20m
    cast:      # characters in the template, by name, family:<name> or guild:<Guild>:<role>
    arrange:   # instances, groups, creatures, before the world loads
    act:       # after load: roster or command steps, at a time or when an observation holds
    observe:   # preconditions and checks: SQL or a log pattern

## Rules lint enforces

- No literal coordinates. `at`, `corpse_at` and `homebind` name an anchor:
  `creature`, `gameobject`, `areatrigger`, `graveyard`, `with`, or `captured`
  (a key in `data/decrees/anchors.yaml`). A coordinate column compared to a number
  in observation SQL is also an error.
- `kind: gm` is rejected: bot sessions are SEC_PLAYER, so it silently does nothing.
- Auction rows and the auction house bot are refused unless the decree sets
  `family: auction-house`.
- A grant (level, money, skills, spells, items) needs a `ceiling`, and a grant
  above what the ceiling text allows is rejected.
- At least one precondition and one check. This only stops a decree with no
  observations of one kind; whether the scenario is reached is shown by a run.
- A fix in the bridge repo needs `world.bridge: "on"`.
- A `roster` step is shorthand for a `command` of kind `job`: it is written as an
  `overseer_command` row. Measured on a hand-made world, such a row was applied
  within seconds with no bridge, while a direct update of `overseer_roster`
  showed no effect. `ephemeral/acts.py` turns the timeline into those rows.
- Observation SQL is one read-only SELECT. Every table and column must exist, a
  derived table (`FROM (SELECT ...)`) is not supported, and a database qualifier
  must lead to a table and column (`db.table.column`).
- An observation must be able to fail: it has to read a known table or use a
  seeded-state variable. `SELECT 1` is refused.
- Variables are limited to a fixed vocabulary: `@t0`, `@cast`, `@cast<N>`,
  `@<Name>`, `@<instance alias>`, `@money_start`, `@seed_skill_value`,
  `@seed_skill_max`, `@skill_<name>`. The component that fills them is not built
  yet, so today this only fixes the names a decree may use.

`TODO` is allowed for an issue number or commit and is a warning, never an error.

## Anchors

`data/decrees/anchors.yaml` is the only file that may hold coordinates. Each entry is
a position a real character stood at, copied from a row the game wrote, with
`provenance: {source, ref, observed}`. Never type a position by hand. An entry
whose row has not been copied is `pending`: lint warns when a decree uses it, and
the seed compiler refuses it.

## Killing a creature whose death has a script

Seeding a creature dead skips its death script. Where the script is the point
(a bar that turns hostile when its owner dies), the kill belongs in `act`, and
the window continues `when:` an observation shows the creature dead.

## Where the decrees live

Decrees and `anchors.yaml` are under `data/decrees/`, a path `check.yml` already
watches (`data/**`), so a pull request that changes only a decree still runs the
unit tests that lint every shipped decree. Keep new decrees there; a decree
elsewhere would not start the tests.

## Seed: cast and arrange to SQL

    python3 -m ephemeral seed [--dry-run] data/decrees/<name>.yaml

Meant to run inside the world pod before the worldserver starts (no pod runs it yet).
It lints the decree, passes the guard, resolves every name and anchor in the world's own database
(zero or several matches is INVALID), compiles the statements and applies them
in one transaction. Settings come from the pod environment, never the decree:
`EPH_MYSQL_HOST`, `EPH_MYSQL_PORT`, `EPH_MYSQL_USER`, `EPH_MYSQL_PASSWORD`,
`EPH_WORLD_LABEL`, `EPH_HARNESS_GRANTS` (placeholders in
`data/ephemeral/config.example.env`). Exit 3 is INVALID. Exit 0 means the
plan compiled, and also that it was applied unless `--dry-run` was given, which
prints the SQL and applies nothing.

The guard (`ephemeral/guard.py`) makes the SQL unable to reach anything else:

- the MySQL host must be the literal loopback address (no DNS name, no
  `localhost`) on the world's own MySQL port (3306), and the connection is made
  to those constants, not to the caller's strings;
- the namespace's world label must be `ephemeral`, the harness must say grants
  are enabled, and the marker table must hold exactly one row (only a template
  build writes it);
- every statement is built by `ephemeral/sqlgen.py` (four shapes, one table of
  the world's own character database, literal values only, table and column
  names checked against the schema) and re-verified at execution time;
- `apply_plan` accepts only a connection that came out of the guard.

Table and column names are checked against the live schema inside the world
(the snapshot is the fallback for lint and tests). A character named on its own
in `cast` overrides the same character inside a `family:` entry.

What the seed writes follows how the core stores each thing. Whether the core
then plays the scenario as intended is shown by the first end-to-end run, and a
failed precondition makes that run INVALID, never a pass.

## Judge: act timeline, observations, verdict

    python3 -m ephemeral judge data/decrees/<name>.yaml --log <worldserver log>

Meant to run as the world pod's last step, after the seed. In the pod it needs no
flags: `seed` and `judge` both default `EPH_VARS_FILE` to `/tmp/eph-vars.json` (the
volume both containers mount), and the judge reads the worldserver log from
`EPH_LOG_FILE`, else `$EPH_LOGS_DIR/Server.log` (the stock worldserver file
appender); `--log` overrides both. With none of them it reports a log that
could not be read, which is INVALID.
It reads the variables and resolved cast the seed left in `EPH_VARS_FILE`, runs
the `act` steps (by time, or when a named observation first holds), samples the
`observe` entries and decides one of three verdicts:

- PASS: every precondition held and every check held.
- FAIL: every precondition held and at least one check was violated. A real
  defect sighting.
- INVALID: the scenario was never reached. This covers a precondition that did
  not hold, an act step that never fired (for example a `when:` observation that
  never came true), a query that timed out or errored, a log that could not be
  read, a guard refusal, a missing seed handoff and a decree that does not lint.
  INVALID beats FAIL, never counts as a pass and never closes an issue.

Observations are `when: start` (once, before any order; a failing precondition
ends the run early), `continuous` (every ten seconds) or `end` (after the
window). Log assertions count regex matches in the worldserver log and are
checked at the end. Across repeated looks the worst one wins and never improves:
a timeout or error is sticky and makes the run INVALID even if a later look
violates or passes; a violation outranks a later clean look.

What the judge may write, in total: `overseer_command` rows in the world's own
database (through the same guard as the seed, and never kind `gm`), and one
ConfigMap, `eph-result-<run-id>`, created in its own namespace. Every
observation is re-checked as a single SELECT against the live schema before it
runs. Settings come from the pod environment: the seed's variables plus
`EPH_RUN_ID`, `EPH_ARM` and `EPH_NAMESPACE`. The ConfigMap holds the verdict, the
reasons, the rendered SQL and observed values per assertion, sample rows and
matched log lines (cut to fit 256 KB, never the verdict). Exit 0 means a verdict
was written, whatever it was; exit 2 means the harness could not write one.

Two rules keep a PASS honest. A scalar expectation needs exactly one row and one
column; any other shape is INVALID, so row order can never hide a failing value.
And a decree that arranges an instance cannot PASS without a held precondition
that reads `log_encounter` (a real FROM or JOIN, not a name in a string), the
core's own credited-encounter record. That observation must reject zero credits
(an expectation like `>= 0` is refused) and be bounded to this run, with
`time >= @t0` and the arranged instance's map as conjuncts of a flat AND chain in
a single plain SELECT (no OR, NOT, XOR, BETWEEN, parentheses, UNION or subquery,
so no row from an earlier run can satisfy it). The observation reads
`log_encounter` exactly once (no self-join) and both bounds apply to that one
alias, or are unqualified when it is the only table; a run's
completion flag is never evidence, and a run with no credit is INVALID. The
judge finds the API server from the pod's `KUBERNETES_SERVICE_HOST` and
`KUBERNETES_SERVICE_PORT`; without them it prints an INVALID verdict and exits 2,
because there is nowhere to write the result.

## Runner: submit, dispatch, collect

All three read one settings file, never the repository: copy
`ephemeral/eph.config.example.json`, fill it in, and pass `--config` or set
`EPH_CONFIG`. It names the namespace, the nodes a world may use (each with its
client-data claim and a world cap), the nodes that are never used, and the
digest-pinned tools image. A missing or malformed file is an error.

    python3 -m ephemeral submit [--arm both] [--node N] --control-worldserver REF         --control-dbimport REF --control-pin SHA data/decrees/<name>.yaml
    python3 -m ephemeral dispatch [--once]
    python3 -m ephemeral collect [--dry-run]

`submit` lints the decree, reads the Job skeleton ConfigMap and the base realm's
running image digests and override files, merges the decree's config onto them
(every changed key becomes a fidelity delta), and creates one SUSPENDED Job per
run plus a ConfigMap of that run's inputs, owned by the Job. It starts nothing.
It refuses: a decree that does not lint, an image other than `follow-dev`, a
bridge-on decree (the skeleton has no bridge sidecar yet), a control arm without
control images, and a fix that is wrongly present or absent in an arm's image
(checked by asking GitHub whether the fix commit is an ancestor of the commit
each image was built from; a `TODO` commit is recorded as unchecked, and an
unchecked decree can never close or disprove anything). It saves a submission
record under the results directory.

`dispatch` is the only thing that starts worlds. One instance runs at a time,
enforced by a Kubernetes Lease. Each pass it unsuspends the oldest queued Job
that fits: the node is allowed and under its world cap, the namespace quota has
room, and the node would keep at least 20 percent of its disk free after the
Job's disk and every recently started world's disk are counted. If the node's
stats cannot be read it refuses. A small Job may skip a larger one that does not
fit, but nothing skips a head that has waited 30 minutes. Runs after the first
control and treatment pair start only if the pair was control FAIL then
treatment PASS; any other first pair stops the batch and removes its waiting
Jobs. A finished Job with no result gets an INVALID result recorded for it.

`collect` copies result ConfigMaps to the results directory, decides each batch
and posts. A decree with any run count other than 3 control and 3 treatment can
still post evidence (outcome `underpowered`, decided before any other outcome, so a
single FAIL or PASS in a small decree is never a disproof) but never changes a
label and never closes an issue. An issue closes only when the same decree FAILed on every control run
and PASSed on every treatment run, every run valid, the fix verified present in
the treatment image and absent from the control, the decree on the default
branch byte for byte, that decree's pull request approved by someone other than
its author or the posting App (each reviewer's latest formal review or approval marker decides, by time; a COMMENTED review changes nothing and any outstanding request for changes refuses), and no unticked box left in the issue body (the
live-check boxes are ticked first, then the label is removed, then the issue is
closed as completed). An epic is never closed. A disproven result comments,
removes the label and leaves the issue open. A treatment pass without a usable
control comments and leaves it open. A passing control and an INVALID run post
nothing to the issue. A decree not yet merged posts to its own pull request when
`--decree-pr` was given. The comment author is read back and must be the
configured App, and `collect` refuses to write unless `GH_TOKEN` and
`GH_CONFIG_DIR` are set.

Not built: requeueing an INVALID first pair (resubmit instead), PR-built images,
and the bridge sidecar.
