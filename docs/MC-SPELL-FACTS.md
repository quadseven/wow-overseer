# Molten Core capability facts

`data/mc-spells.json` records the first trainer ranks used by `mcencounters.py`
and the dispel types of its seven cited boss spells. These are learn-level
requirements, not a claim that a member has purchased or currently can cast
a spell. Talent-only capabilities are excluded. Seats and encounter needs
are unchanged.

The projection was inspected and regenerated on 2026-11-05 from an archived
Standing training export. Its capture time was not recorded; no fresh live
realm verification is claimed. The export contains all twenty-one required first
trainer ranks across ten classes, including Cleanse at 42, Mind Freeze at 57
and Tranquilizing Shot at 60. It does not contain the full above-cap trainer
catalog, which is unnecessary for these explicitly enumerated first ranks.

The Standing reader (`apiv2/training.py`, TRAINER_SQL) joins `trainer_spell`
to class trainers (`trainer.Type = 0`, `trainer.Requirement = class`) and
reads each SpellId's minimum ReqLevel. The export retains that level across
learned, trainable, prerequisite-missing and above-level states. Generation
rejects missing first ranks and contradictory levels. The committed file
contains no character identities, guilds, money or other member facts.

Spell names and boss dispel types were read from the matching 3.3.5a
Spell.dbc: ID field 0, Dispel field 2, English name field 136. Its MD5 is
`543b9fe61355b6a77a01714d52fea2e5`, matching the data fingerprint already
recorded by `tools/raid_consumables_from_dbc.py`. MD5 identifies that published
data version; it is not a security verification.

| Spell | Dispel | Answer |
| --- | --- | --- |
| 19703 Lucifron's Curse | Curse (2) | Curse dispel |
| 19702 Impending Doom | Magic (1) | Friendly magic dispel |
| 19716 Gehennas' Curse | Curse (2) | Curse dispel |
| 19713 Shazzrah's Curse | Curse (2) | Curse dispel |
| 19714 Magic Grounding | Magic (1) | Offensive dispel |
| 19659 Ignite Mana | Magic (1) | Friendly magic dispel |
| 19776 Shadow Word: Pain | Magic (1) | Friendly magic dispel |

Regenerate using a name-keyed collection of Standing training responses and
the matching Spell.dbc, keeping the raw export outside the repository:

```sh
python3 tools/mc_spell_facts.py TRAINING_EXPORT Spell.dbc > mc-spells.next.json &&
  diff -u data/mc-spells.json mc-spells.next.json
# After inspecting a successful generation, copy mc-spells.next.json into data/.
```

Compare the generated diff before committing. A missing, malformed or
incomplete source must fail generation; it must not imply the capability is
available. Missing member levels count as unavailable in the composer. The
Raid line distinguishes a class present below the required learn level from
a class absent from the lineup.
