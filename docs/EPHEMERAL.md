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
- A fix in the bridge repo needs `world.bridge: "on"`, and with the bridge on
  the roster is the bridge's: order a job with a `command` of kind `job`.
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
