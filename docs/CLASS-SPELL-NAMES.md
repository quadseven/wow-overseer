# Class spell names

The Standing card's learned, trainable and above-level spell lists share
`app/models/spellnames.js`. Its catalog is generated from the 3.3.5 client
DBCs, including ranks. Unknown IDs retain the `Spell N` label and spell link.

## Regeneration

Obtain `Spell.dbc`, `SkillLine.dbc` and `SkillLineAbility.dbc` from the
[client-data v20.0 archive](https://github.com/wowgaming/client-data/releases/tag/v20.0).
Place the three files in one directory, then run:

```sh
python3 tools/class_spell_names_from_dbc.py ./dbc > spellnames.js
```

Check the exit status before replacing `app/models/spellnames.js` with the
output. The generator refuses files whose checksums differ:

| File | MD5 |
| --- | --- |
| Spell.dbc | 543b9fe61355b6a77a01714d52fea2e5 |
| SkillLine.dbc | c4e4e914a868250dd087f37292d272d7 |
| SkillLineAbility.dbc | d8c11abfcfe70596cb9068c0e97a1d9a |

The Spell and SkillLineAbility checksums match the client data already used
by `taughtspells.py` and `racespells.py`. Checksums identify the input version;
they are not a security signature.

Selection includes all abilities in class skill lines (`CategoryID = 7`),
all class-restricted abilities (`ClassMask != 0`), and every spell that
teaches one of those through a learn-spell effect, recursively. This includes
trainer wrappers such as Summon Felsteed, not just the resulting learned spell.
There is no roster or level-cap filter. Deleted spell IDs still present in
SkillLineAbility are excluded because Spell.dbc has no corresponding record.

`tests/fixtures/class_trainer_spell_ids.json` contains 1,219 distinct spell IDs
from archived Standing responses covering all ten classes. It contains no
character data. It is a regression sample, not the generator's input or a claim
that the archived responses contain every trainer rank: Standing responses
exclude ranks above the realm's level cap. The generator selects those higher
ranks directly from the client taxonomy.

Run `tests/test_app_member_standing.py` and
`tests/test_class_spell_names_generator.py` to check coverage, unknown-ID
fallback, rank display, selection, and rejection of different input data.
