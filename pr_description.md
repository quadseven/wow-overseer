## Why
The bridge Standing card counts armor proficiency spells as owed forever because the `skilllineability_dbc` table in the world DB is empty, making it impossible to determine which skills grant which spells dynamically. A character holding the skill that grants a proficiency spell should not be listed as owing that spell.

## Summary
Updated `classtrain.py` to use a hardcoded mapping of skill IDs to spell IDs for proficiency spells. Changed `due()` and `spell_state()` to accept the `skills` set as an argument, and mapped spell 750 to skill 293 and spell 8737 to skill 413, so they are not listed as owed when the character possesses the skill. `bridge.py` and `apiv2/training.py` were also updated to pass `skills` appropriately.

## Acceptance
- A test covers spell 750 Plate Mail with skill 293 and spell 8737 Mail with skill 413, neither listed as owed
- A test shows a spell with no skill grant that the character has not learned is still owed
- A test shows 750 is still owed when skill 293 is absent

## Test plan
- Run tests in `test_class_owed.py` to assert that proficiency spells are correctly filtered when the skill is held
- Run tests in `test_class_owed.py` to assert that a normal spell is still owed
- Run tests in `test_class_owed.py` to assert that proficiency spells are still owed when the character does not hold the relevant skill

## Size
Small.

## Out of scope
Granting or teaching any spell; the module training stop.

Refs quadseven/wow-overseer#1482.
