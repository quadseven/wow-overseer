# Ephemeral worlds: decrees

A decree is one YAML file under `decrees/` that says who is in a throwaway
world, where, in what state, what to do, and what SQL or log assertions decide
the verdict. This page covers the parts that exist so far: the schema, `eph
lint`, and `decrees/anchors.yaml`. Tracking issue: #2343.

Last checked: 2026-11-15.

## Lint a decree

    python3 -m ephemeral lint decrees/<name>.yaml        # warnings pass
    python3 -m ephemeral lint --strict decrees/<name>.yaml  # warnings fail

No cluster is needed. The reader is a strict YAML subset (`ephemeral/miniyaml.py`)
because the unit suite has no YAML parser. Observation SQL is checked against a
snapshot of the game databases' table and column names
(`ephemeral/data/acore_schema.json`), so a mistyped column is a lint error.

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
  (a key in `decrees/anchors.yaml`). A coordinate column compared to a number
  in observation SQL is also an error.
- `kind: gm` is rejected: bot sessions are SEC_PLAYER, so it silently does nothing.
- Auction rows and the auction house bot are refused unless the decree sets
  `family: auction-house`.
- A grant (level, money, skills, spells, items) needs a `ceiling`, and a grant
  above what the ceiling text allows is rejected.
- At least one precondition and one check, so a vacuous pass is impossible.
- A fix in the bridge repo needs `world.bridge: "on"`.
- A `roster` step is shorthand for a `command` of kind `job`: it is written as an
  `overseer_command` row, which the module applies within seconds with or
  without the bridge. Nothing in a decree writes `overseer_roster` directly (a
  direct update was measured to have no effect). `ephemeral/acts.py` turns the
  timeline into those rows.
- Observation SQL is one read-only SELECT over known tables and columns, using
  only variables the judge defines: `@t0`, `@cast`, `@cast<N>`, `@<Name>`,
  `@<instance alias>`, `@money_start`, `@seed_skill_value`, `@seed_skill_max`,
  `@skill_<name>`.

`TODO` is allowed for an issue number or commit and is a warning, never an error.

## Anchors

`decrees/anchors.yaml` is the only file that may hold coordinates. Each entry is
a position a real character stood at, copied from a row the game wrote, with
`provenance: {source, ref, observed}`. Never type a position by hand. An entry
whose row has not been copied is `pending`: lint warns, and a world refuses it.

## Killing a creature whose death has a script

Seeding a creature dead skips its death script. Where the script is the point
(a bar that turns hostile when its owner dies), the kill belongs in `act`, and
the window continues `when:` an observation shows the creature dead.

## A decree-only change

`check.yml` filters on Python and JSON, so a pull request that touches only a
`.yaml` file under `decrees/` does not start the unit tests. Run
`python3 -m ephemeral lint decrees/*.yaml` yourself, or touch a test.

## Seed: cast and arrange to SQL

    python3 -m ephemeral seed [--dry-run] decrees/<name>.yaml

Runs inside the world pod, before the worldserver starts. It lints the decree,
passes the guard, resolves every name and anchor in the world's own database
(zero or several matches is INVALID), compiles the statements and applies them
in one transaction. Settings come from the pod environment, never the decree:
`EPH_MYSQL_HOST`, `EPH_MYSQL_PORT`, `EPH_MYSQL_USER`, `EPH_MYSQL_PASSWORD`,
`EPH_WORLD_LABEL`, `EPH_HARNESS_GRANTS`. Exit 0 is applied, 3 is INVALID.

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
