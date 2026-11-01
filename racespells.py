"""Class trainer spells a character's race can never learn (#792).

The core teaches a spell only if one of its SkillLineAbility rows allows the
character's race and class (Player::IsSpellFitByClassAndRace). The bridge reads
every class trainer spell by class, so a faction pair such as Bloodlust and
Heroism, or Seal of Corruption and Seal of Vengeance, counted as owed forever
for the side that cannot learn it; the member was walked to a trainer that
refuses it, and tried again each cooldown.

Frozen from the worldserver's SkillLineAbility.dbc (md5
d8c11abfcfe70596cb9068c0e97a1d9a) by tools/race_spells_from_dbc.py, because
the `*_dbc` tables on the realm are empty. A spell absent from ROWS has no row
that names a race, so it fits every race.

PURE MODULE: a table and one question. No MySQL, no clock.
"""

from __future__ import annotations

# spell id -> ((RaceMask, ClassMask), ...), one pair per SkillLineAbility row.
# A mask of 0 means any.
ROWS = {
    668: ((1101, 0),),
    669: ((690, 0),),
    670: ((32, 0),),
    671: ((8, 0),),
    672: ((4, 0),),
    813: ((512, 0),),
    2481: ((4, 0),),
    2825: ((162, 64),),
    3561: ((1101, 128),),
    3562: ((1101, 128),),
    3563: ((690, 128),),
    3565: ((1101, 128),),
    3566: ((690, 128),),
    3567: ((690, 128),),
    5227: ((16, 0),),
    6562: ((1024, 39),),
    7340: ((64, 0),),
    7341: ((128, 0),),
    7744: ((16, 0),),
    10059: ((1101, 128),),
    11416: ((1101, 128),),
    11417: ((690, 128),),
    11418: ((690, 128),),
    11419: ((1101, 128),),
    11420: ((690, 128),),
    13819: ((1029, 2),),
    17737: ((16, 0),),
    20549: ((32, 0),),
    20550: ((32, 0),),
    20551: ((32, 0),),
    20552: ((32, 0),),
    20555: ((128, 0),),
    20557: ((128, 0),),
    20558: ((128, 0),),
    20572: ((2, 45),),
    20573: ((2, 0),),
    20574: ((2, 0),),
    20575: ((2, 256),),
    20576: ((2, 4),),
    20577: ((16, 0),),
    20579: ((16, 0),),
    20582: ((8, 0),),
    20583: ((8, 0),),
    20585: ((8, 0),),
    20589: ((64, 0),),
    20591: ((64, 0),),
    20592: ((64, 0),),
    20593: ((64, 0),),
    20594: ((4, 0),),
    20595: ((4, 0),),
    20596: ((4, 0),),
    20597: ((1, 0),),
    20598: ((1, 0),),
    20599: ((1, 0),),
    20864: ((1, 0),),
    21009: ((8, 1085),),
    21563: ((2, 1179),),
    23214: ((1029, 2),),
    25046: ((512, 8),),
    26290: ((128, 0),),
    26297: ((128, 0),),
    28878: ((1024, 208),),
    28880: ((1024, 1),),
    29932: ((1024, 0),),
    31801: ((1029, 2),),
    31803: ((1029, 2),),
    31804: ((1029, 2),),
    31898: ((512, 2),),
    32182: ((1024, 64),),
    32266: ((1101, 128),),
    32267: ((690, 128),),
    32271: ((1101, 128),),
    32272: ((690, 128),),
    33690: ((1101, 128),),
    33691: ((1101, 128),),
    33697: ((2, 64),),
    33702: ((2, 256),),
    34767: ((512, 2),),
    34769: ((512, 2),),
    35715: ((690, 128),),
    35717: ((690, 128),),
    49358: ((690, 128),),
    49359: ((1101, 128),),
    49360: ((1101, 128),),
    49361: ((690, 128),),
    53726: ((1029, 2),),
    53733: ((512, 2),),
    53736: ((512, 2),),
    53742: ((512, 2),),
    54562: ((2, 32),),
    55531: ((690, 0),),
    58943: ((128, 0),),
    58984: ((8, 0),),
    58985: ((1, 0),),
    59221: ((1024, 1),),
    59224: ((4, 0),),
    59535: ((1024, 2),),
    59536: ((1024, 4),),
    59538: ((1024, 16),),
    59540: ((1024, 64),),
    59541: ((1024, 128),),
    59542: ((1024, 2),),
    59543: ((1024, 4),),
    59544: ((1024, 16),),
    59545: ((1024, 32),),
    59547: ((1024, 64),),
    59548: ((1024, 128),),
    59752: ((1, 0),),
    60424: ((1101, 0),),
    60866: ((690, 0),),
    60867: ((1101, 0),),
    63644: ((4095, 1535),),
    63645: ((4095, 1535),),
    65222: ((2, 64),),
    75460: ((1791, 8),),
    75461: ((1791, 64),),
}


def fits(spell, race_id, class_id) -> bool:
    """Whether a character of this race and class can ever learn `spell`.

    True when the race or class is unknown: the bridge then falls back to the
    old behaviour of counting the spell.
    """
    rows = ROWS.get(_int(spell))
    race_id, class_id = _int(race_id), _int(class_id)
    if not rows or not race_id or not class_id:
        return True
    race_bit, class_bit = 1 << (race_id - 1), 1 << (class_id - 1)
    return any(
        (not race_mask or race_mask & race_bit)
        and (not class_mask or class_mask & class_bit)
        for race_mask, class_mask in rows
    )


def _int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
