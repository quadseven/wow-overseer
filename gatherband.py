"""Which gathering skill value a node's lock actually demands.

infra#3789. `skillgoal` could not answer "is anything here within reach of this
skill value" because that number lives in `Lock.dbc` and `acore_world.lock_dbc`
is EMPTY on this realm - the same hole as `skillline_dbc` and
`skilllineability_dbc`. So the number is not readable from the world DB at all,
and the refusal that named this as hole 3 was correct about the cause.

It IS readable from the worldserver's own client data
(`/azerothcore/env/dist/data/dbc/Lock.dbc`), which is where this projection
comes from. `tools/gather_bands_from_dbc.py` regenerates it in one command, the
same way `tools/spell_focus_from_dbc.py` regenerates test_craft's MEASURED_FOCUS
and for the same reason: CI runs stdlib-only with no cluster access, so a
checked-in projection is the only form of the server's answer a pull request can
be gated on.

THE KEY IS THE LOCK ID, NOT THE NODE NAME. `gameobject_template.Data0` is the
lock id for a type-3 (chest) object, so the join from a live spawn to its band
is exact and survives renames. Names are deliberately NOT stored here - 144 node
templates share these 67 locks, and a name-keyed table would have to repeat a
band 144 times and could disagree with itself.

A BAND OF 0 MEANS "NO MINIMUM", NOT "MISSING". Copper Vein (lock 38) and
Peacebloom/Silverleaf (lock 29) both read 0, which is why a character with
Mining 1 can mine copper. Treat absent-from-this-table as unknown and refuse;
treat 0 as reachable by anyone with the skill at all.

MEASURED, NOT REMEMBERED. Truesilver Deposit (lock 380) reads **205** here, not
the 230 that is widely repeated for it. Anything typed from memory into this
file is a guess wearing a measurement's clothes.
"""

# LockType ids from LockType.dbc. Only the two gathering professions are
# projected - picklock, fishing poles and quest locks are not a skill this
# family can raise by walking somewhere.
LOCKTYPE_HERBALISM = 2
LOCKTYPE_MINING = 3

MINING_BANDS = {
    38: 0,
    1713: 0,
    1771: 0,
    1775: 0,
    1802: 0,
    18: 25,
    1860: 25,
    19: 50,
    39: 65,
    20: 75,
    40: 75,
    21: 100,
    22: 125,
    41: 125,
    25: 150,
    42: 155,
    379: 175,
    380: 205,
    400: 230,
    719: 230,
    939: 255,
    1649: 275,
    1632: 305,
    399: 310,
    1650: 325,
    1652: 350,
    1800: 350,
    1651: 375,
    1782: 375,
    1783: 400,
    1784: 425,
    1785: 450,
}

HERBALISM_BANDS = {
    29: 0,
    259: 0,
    1702: 0,
    1714: 0,
    30: 15,
    8: 25,
    9: 50,
    31: 70,
    10: 75,
    519: 85,
    11: 100,
    32: 115,
    33: 120,
    26: 125,
    45: 125,
    34: 130,
    35: 140,
    27: 150,
    47: 160,
    521: 170,
    49: 185,
    51: 195,
    50: 205,
    439: 210,
    48: 215,
    440: 220,
    441: 230,
    442: 235,
    443: 245,
    444: 250,
    1119: 260,
    1120: 270,
    1121: 280,
    1122: 285,
    1123: 290,
    1124: 300,
    1639: 315,
    1641: 325,
    1642: 335,
    1643: 340,
    1644: 350,
    1786: 360,
    1645: 365,
    1646: 375,
    1787: 385,
    1788: 400,
    1793: 415,
    1789: 425,
    1791: 430,
    1790: 435,
    1792: 450,
}

BANDS = {
    "mining": MINING_BANDS,
    "herbalism": HERBALISM_BANDS,
}


def band_for(lock_id, skill_name):
    """The skill value `lock_id` demands of `skill_name`, or None if unknown.

    None is not zero. Zero is a real answer meaning "no minimum"; None means
    this lock is not a node of that profession at all, and the caller must
    refuse rather than assume it is free.
    """
    table = BANDS.get(skill_name)
    if table is None:
        return None
    return table.get(int(lock_id))


def in_band(lock_id, skill_name, value):
    """Can a character with `value` in `skill_name` open this lock at all."""
    band = band_for(lock_id, skill_name)
    if band is None:
        return False
    try:
        return int(value) >= band
    except (TypeError, ValueError):
        return False


def reachable_locks(skill_name, value):
    """Every lock id of `skill_name` that `value` can open, lowest band first.

    Ordered so a caller choosing "somewhere this character can actually work"
    gets the most forgiving node first rather than an arbitrary dict order.
    """
    table = BANDS.get(skill_name)
    if table is None:
        return []
    try:
        have = int(value)
    except (TypeError, ValueError):
        return []
    return [
        lock
        for lock, band in sorted(table.items(), key=lambda kv: (kv[1], kv[0]))
        if have >= band
    ]
