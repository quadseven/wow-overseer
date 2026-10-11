"""A member wears its best usable piece in every slot, judged by gear score.

Measured on the dev realm on 2026-10-10: the equip pass (gear.equips, item
level) held back 42 carried pieces after three `e` commands each, and 31 of
them score lower by the member's own spec weights than what it wears. Each was
put on and taken off again by mod-playerbots' own stat-scored equip. The pass
also never looked at a ring, a neck or a trinket, and refused a one-hander
while a two-hander was worn. These pin the scored judge (equipscore.py) and
the bridge wiring that makes it the judge for every member it can score.
"""

import pathlib
import re
import unittest

import equipscore as es
import gear

BRIDGE = pathlib.Path(__file__).resolve().parents[1] / "bridge.py"

WARRIOR, PALADIN, ROGUE, MAGE = 1, 2, 4, 8
HUMAN, TROLL = 1, 8
# Talent spells of one tree each (raidroles' talent book).
PROTECTION = "12666,12753,12764,12803,12804,12809,12811,12818"
FROST = "12953,15047,16766,28332,55094"
# Skill lines: swords 43, two-hand swords 55, staves 136, daggers 173,
# wands 228, cloth 415, leather 414, mail 413, plate 293, shield 433,
# dual wield 118.
CASTER_SKILLS = "136,173,228,415"
ROGUE_SKILLS = "43,173,414,415,118"
WARRIOR_SKILLS = "43,44,54,55,413,414,415,433"

_GUID = [5000]


def piece(name, inv, item_class=4, subclass=1, level=20, req=15, stats=(), **kw):
    """One item row as _SCORED_GEAR_SQL returns it. `stats` is
    ((stat_type, value), ...); `slot` makes it worn."""
    _GUID[0] += 1
    row = dict(
        holder=kw.pop("holder", "Eggrok"),
        equipment_slot=kw.pop("slot", None),
        item_guid=kw.pop("guid", _GUID[0]),
        entry=kw.pop("entry", _GUID[0]),
        name=name,
        quality=2,
        item_level=level,
        required_level=req,
        item_class=item_class,
        item_subclass=subclass,
        inventory_type=inv,
        allowable_class=-1,
        allowable_race=-1,
        required_skill=0,
        required_skill_rank=0,
        required_spell=0,
        required_reputation=0,
        max_count=0,
        item_flags=0,
        armor=0,
        block=0,
        dmg_min1=0,
        dmg_max1=0,
        delay=0,
        random_property_id=0,
        enchantments="",
    )
    for n, (kind, amount) in enumerate(stats, start=1):
        row["stat_type%d" % n] = kind
        row["stat_value%d" % n] = amount
    row.update(kw)
    return row


AGI, STR, INT, SPI, STA, DEFENSE = 3, 4, 5, 6, 7, 12


def member(name, class_id, level, talents="", tree="", skills="", race=HUMAN):
    return dict(
        name=name,
        class_id=class_id,
        level=level,
        race=race,
        talent_spells=talents,
        target_tree=tree,
        skills=skills,
    )


def eggrok(skills=CASTER_SKILLS):
    return es.wearer_from_row(member("Eggrok", MAGE, 25, FROST, "Frost", skills, TROLL))


def walking_stick():
    return piece(
        "Walking Stick",
        17,
        2,
        10,
        level=8,
        req=3,
        slot=15,
        dmg_min1=10,
        dmg_max1=16,
        delay=3000,
    )


def thiefs_blade():
    return piece(
        "Thief's Blade",
        13,
        2,
        7,
        level=22,
        req=17,
        stats=((AGI, 7),),
        dmg_min1=18,
        dmg_max1=34,
        delay=1800,
    )


def runic_stave():
    return piece("Runic Stave", 23, 4, 0, level=18, req=13, stats=((STA, 2), (SPI, 2)))


class TheSpecScoreDecides(unittest.TestCase):
    def test_a_higher_item_level_that_scores_lower_is_left_in_the_bags(self):
        """Bork's case: a cloth sash of item level 42 over his leather belt of
        37. Item level asked for it three times; the rogue's weights do not."""
        rogue = es.wearer_from_row(member("Bork", ROGUE, 39, skills=ROGUE_SKILLS))
        worn = [
            piece(
                "Gem-studded Leather Belt",
                6,
                4,
                2,
                level=37,
                req=32,
                stats=((AGI, 9), (STA, 5)),
                slot=5,
                holder="Bork",
            )
        ]
        sash = piece(
            "Mistscape Sash",
            6,
            4,
            1,
            level=42,
            req=37,
            stats=((INT, 8), (SPI, 7)),
            holder="Bork",
        )
        self.assertEqual(es.choose(rogue, worn, [sash]), ())
        # The item-level judge asks for it: the defect this replaces.
        legacy = gear.equips(
            gear.holdings_from_rows([dict(sash, item_guid=sash["item_guid"])]),
            [gear.CharacterState("Bork", ROGUE, 39, {"waist": 37})],
        )
        self.assertEqual([e.name for e in legacy], ["Mistscape Sash"])

    def test_a_better_scoring_piece_is_put_on(self):
        tank = es.wearer_from_row(
            member("Grug", WARRIOR, 43, PROTECTION, skills=WARRIOR_SKILLS)
        )
        worn = [
            piece(
                "Old Breastplate",
                5,
                4,
                3,
                level=35,
                req=30,
                stats=((STA, 6),),
                armor=300,
                slot=4,
                holder="Grug",
            )
        ]
        chest = piece(
            "Symbolic Breastplate",
            5,
            4,
            3,
            level=43,
            req=38,
            stats=((STA, 14), (STR, 9)),
            armor=420,
            holder="Grug",
        )
        got = es.choose(tank, worn, [chest])
        self.assertEqual(
            [(e.name, e.slot) for e in got], [("Symbolic Breastplate", "chest")]
        )
        self.assertIn("gear score", got[0].reason)
        self.assertEqual(got[0].command, "e Hitem:%d:0" % chest["entry"])

    def test_a_sidegrade_inside_the_margin_is_not_asked_for(self):
        tank = es.wearer_from_row(
            member("Grug", WARRIOR, 43, PROTECTION, skills=WARRIOR_SKILLS)
        )
        worn = [
            piece(
                "Cloak A",
                16,
                4,
                1,
                level=38,
                stats=((STA, 10),),
                slot=14,
                holder="Grug",
            )
        ]
        carried = [
            piece(
                "Cloak B",
                16,
                4,
                1,
                level=45,
                stats=((STA, 10),),
                armor=5,
                holder="Grug",
            )
        ]
        self.assertEqual(es.choose(tank, worn, carried), ())


class NecksRingsAndTrinketsAreWorn(unittest.TestCase):
    def test_a_better_ring_is_put_on_which_item_level_never_judged(self):
        tank = es.wearer_from_row(
            member("Grug", WARRIOR, 43, PROTECTION, skills=WARRIOR_SKILLS)
        )
        worn = [
            piece(
                "Band A", 11, 4, 0, level=30, stats=((STA, 4),), slot=10, holder="Grug"
            ),
            piece(
                "Band B", 11, 4, 0, level=30, stats=((STA, 5),), slot=11, holder="Grug"
            ),
        ]
        ring = piece(
            "Engraved Truesilver Ring",
            11,
            4,
            0,
            level=40,
            req=35,
            stats=((STA, 12), (STR, 6)),
            holder="Grug",
        )
        got = es.choose(tank, worn, [ring])
        self.assertEqual(
            [(e.name, e.slot) for e in got], [("Engraved Truesilver Ring", "finger")]
        )
        legacy = gear.equips(
            gear.holdings_from_rows([ring]),
            [gear.CharacterState("Grug", WARRIOR, 43, {})],
        )
        self.assertEqual(legacy, ())

    def test_an_empty_neck_is_filled(self):
        tank = es.wearer_from_row(
            member("Grug", WARRIOR, 43, PROTECTION, skills=WARRIOR_SKILLS)
        )
        chain = piece(
            "Kaleidoscope Chain", 2, 4, 0, level=35, stats=((STA, 6),), holder="Grug"
        )
        self.assertEqual([e.slot for e in es.choose(tank, [], [chain])], ["neck"])

    def test_a_unique_ring_is_worn_once(self):
        tank = es.wearer_from_row(
            member("Grug", WARRIOR, 43, PROTECTION, skills=WARRIOR_SKILLS)
        )
        one = piece(
            "Seal",
            11,
            4,
            0,
            level=40,
            stats=((STA, 9),),
            entry=777,
            max_count=1,
            holder="Grug",
        )
        two = dict(one, item_guid=one["item_guid"] + 1)
        got = es.choose(tank, [], [one, two])
        self.assertEqual(len(got), 1)


class TheHandsAreOneSet(unittest.TestCase):
    def test_a_weapon_without_its_skill_is_never_asked_for_and_is_named(self):
        """Eggrok's Thief's Blade: a sword, and Eggrok has no Swords skill."""
        w = eggrok()
        worn, carried = [walking_stick()], [thiefs_blade(), runic_stave()]
        self.assertEqual(es.choose(w, worn, carried), ())
        waiting = es.waiting_on_skill(w, worn, carried)
        self.assertEqual([(r["name"], s) for r, s in waiting], [("Thief's Blade", 43)])

    def test_a_one_hander_and_an_off_hand_replace_a_weaker_two_hander_main_first(self):
        """Once the skill is learned both go on, the main hand first: the core
        refuses an off-hand piece while the two-hander is worn. A mage's spec
        weighs neither piece, so the caster's role weights decide."""
        w = eggrok(CASTER_SKILLS + ",43")
        got = es.choose(w, [walking_stick()], [thiefs_blade(), runic_stave()])
        self.assertEqual(
            [(e.name, e.slot) for e in got],
            [("Thief's Blade", "main_hand"), ("Runic Stave", "off_hand")],
        )
        self.assertIn("role score", got[0].reason)
        legacy = gear.equips(
            gear.holdings_from_rows(
                [
                    dict(thiefs_blade(), holder="Eggrok"),
                    dict(runic_stave(), holder="Eggrok"),
                ]
            ),
            [gear.CharacterState("Eggrok", MAGE, 25, {"two_hand": 8})],
        )
        self.assertEqual(legacy, ())

    def test_an_off_hand_alone_is_never_asked_for_beside_a_two_hander(self):
        self.assertEqual(es.choose(eggrok(), [walking_stick()], [runic_stave()]), ())

    def test_an_off_hand_weapon_needs_dual_wield(self):
        tank = es.wearer_from_row(member("Grug", WARRIOR, 18, skills="43,413,414,415"))
        worn = [
            piece(
                "Shortsword",
                13,
                2,
                7,
                level=10,
                req=5,
                slot=15,
                holder="Grug",
                dmg_min1=5,
                dmg_max1=9,
                delay=2000,
            )
        ]
        # Weaker than the sword in the main hand, so it only fits the off hand.
        offhand = piece(
            "Second Sword",
            13,
            2,
            7,
            level=15,
            req=10,
            holder="Grug",
            dmg_min1=4,
            dmg_max1=7,
            delay=2000,
        )
        self.assertEqual(es.choose(tank, worn, [offhand]), ())
        dual = es.wearer_from_row(
            member("Grug", WARRIOR, 20, skills="43,118,413,414,415")
        )
        got = es.choose(dual, worn, [offhand])
        self.assertEqual([e.slot for e in got], ["off_hand"])

    def test_a_shield_tank_keeps_its_shield(self):
        tank = es.wearer_from_row(
            member("Grug", WARRIOR, 43, PROTECTION, skills=WARRIOR_SKILLS)
        )
        worn = [
            piece(
                "Sword",
                13,
                2,
                7,
                level=30,
                slot=15,
                holder="Grug",
                dmg_min1=20,
                dmg_max1=30,
                delay=2000,
            ),
            piece(
                "Buckler",
                14,
                4,
                6,
                level=30,
                slot=16,
                holder="Grug",
                stats=((STA, 4),),
                armor=600,
            ),
        ]
        big = piece(
            "Destiny",
            17,
            2,
            8,
            level=43,
            req=38,
            holder="Grug",
            stats=((STR, 30), (STA, 20)),
            dmg_min1=120,
            dmg_max1=180,
            delay=3800,
        )
        self.assertEqual(es.choose(tank, worn, [big]), ())


class OnlyWhatItCanWearNow(unittest.TestCase):
    def test_level_class_race_and_armour_skill_are_the_characters_own(self):
        tank = es.wearer_from_row(
            member("Grug", WARRIOR, 30, PROTECTION, skills=WARRIOR_SKILLS)
        )
        too_high = piece(
            "Helm", 1, 4, 3, level=40, req=35, stats=((STA, 9),), holder="Grug"
        )
        plate = piece(
            "Plate Helm", 1, 4, 4, level=30, req=25, stats=((STA, 9),), holder="Grug"
        )
        not_mine = piece(
            "Libram",
            1,
            4,
            3,
            level=30,
            req=25,
            stats=((STA, 9),),
            holder="Grug",
            allowable_class=1 << (PALADIN - 1),
        )
        wrong_race = piece(
            "Troll Mask",
            1,
            4,
            3,
            level=30,
            req=25,
            stats=((STA, 9),),
            holder="Grug",
            allowable_race=1 << (TROLL - 1),
        )
        self.assertEqual(
            es.choose(tank, [], [too_high, plate, not_mine, wrong_race]), ()
        )
        ok = piece(
            "Mail Helm", 1, 4, 3, level=30, req=25, stats=((STA, 9),), holder="Grug"
        )
        self.assertEqual([e.name for e in es.choose(tank, [], [ok])], ["Mail Helm"])


class ThePass(unittest.TestCase):
    def test_a_member_it_can_score_is_judged_by_score_and_the_rest_by_item_level(self):
        legacy = (
            gear.Equip(
                "Bork", 1, 4736, "Mistscape Sash", "waist", 42, 37, "item level"
            ),
            gear.Equip("Nobody", 2, 99, "Old Hat", "head", 10, 5, "item level"),
        )
        rows = [member("Bork", ROGUE, 39, skills=ROGUE_SKILLS)]
        gear_rows = [
            piece(
                "Gem-studded Leather Belt",
                6,
                4,
                2,
                level=37,
                req=32,
                stats=((AGI, 9),),
                slot=5,
                holder="Bork",
            ),
            piece(
                "Mistscape Sash",
                6,
                4,
                1,
                level=42,
                req=37,
                stats=((INT, 8),),
                holder="Bork",
            ),
            piece(
                "Thug Ring",
                11,
                4,
                0,
                level=38,
                req=33,
                stats=((AGI, 8),),
                holder="Bork",
            ),
        ]
        got = es.plan(legacy, rows, gear_rows, ["Bork", "Nobody"])
        self.assertEqual(
            [(e.holder, e.name) for e in got.equips],
            [("Bork", "Thug Ring"), ("Nobody", "Old Hat")],
        )
        self.assertEqual(got.scored, frozenset({"Bork"}))

    def test_the_owners_mark_keeps_a_piece_in_the_bags(self):
        rows = [member("Bork", ROGUE, 39, skills=ROGUE_SKILLS)]
        ring = piece(
            "Thug Ring", 11, 4, 0, level=38, req=33, stats=((AGI, 8),), holder="Bork"
        )
        got = es.plan((), rows, [ring], ["Bork"], keep_names=("Thug Ring",))
        self.assertEqual(got.equips, ())


def _block(signature: str) -> str:
    src = BRIDGE.read_text()
    start = src.index(signature)
    indent = len(signature) - len(signature.lstrip())
    rest = src[start:]
    match = re.search(r"\n {0,%d}(async def |def |class )" % indent, rest[1:])
    return rest[: match.start() + 1] if match else rest


class TheBridgeMakesItTheJudge(unittest.TestCase):
    def test_both_passes_ask_the_scorer(self):
        self.assertIn(
            "self._scored_equips(", _block("    async def _equip_upgrades(self")
        )
        guild = _block("    async def _guild_equip_once(self")
        self.assertIn("self._scored_equips(", guild)
        # An empty uncommon-or-better read no longer ends the guild pass: the
        # scorer reads every quality.
        self.assertNotIn("if not gear_rows:\n            return", guild)
        body = _block("    async def _scored_equips(self")
        self.assertIn("equipscore.plan(", body)
        self.assertIn("_fetch_scored_gear", body)
        self.assertIn("_fetch_wearers", body)
        self.assertIn("judged %d %smember(s) by gear score", body)

    def test_the_scored_read_covers_jewellery_every_quality_and_the_bags_only(self):
        src = BRIDGE.read_text()
        sql = src[src.index("_SCORED_GEAR_SQL = (") : src.index("_WEARERS_SQL = (")]
        self.assertNotIn("Quality >=", sql)
        for inv in ("1, 2, 3", "11, 12", "28"):
            self.assertIn(inv, sql)
        self.assertIn("ci.slot BETWEEN 19 AND 38", sql)
        self.assertNotIn("BETWEEN 39", sql)
        self.assertIn("ii.randomPropertyId AS random_property_id", sql)
        wearers = src[
            src.index("_WEARERS_SQL = (") : src.index("def _fetch_scored_gear")
        ]
        self.assertIn("character_skills", wearers)
        self.assertIn("raidroles.TALENTS_COLUMN", wearers)


if __name__ == "__main__":
    unittest.main()


class AHuntersBotNeverWearsAMeleeWeapon(unittest.TestCase):
    """Measured on the dev realm over two days: mod-playerbots' equip put on
    0 of 11 melee weapons asked of hunters (and 8 of 10 asked of warriors).
    Six hunters held a Gladius or a Stiletto, held the skill line for it, and
    were told `e` three times each; the pieces stayed in the bags."""

    HUNTER = 3

    def dug(self):
        return es.wearer_from_row(
            member("Dug", self.HUNTER, 16, skills="43,44,45,172,173")
        )

    def gladius(self):
        return piece(
            "Gladius",
            13,
            2,
            7,
            level=9,
            req=4,
            dmg_min1=5,
            dmg_max1=11,
            delay=2100,
        )

    def battleaxe(self):
        return piece(
            "Worn Battleaxe",
            17,
            2,
            1,
            level=2,
            req=0,
            slot=15,
            dmg_min1=3,
            dmg_max1=5,
            delay=2900,
        )

    def test_a_melee_upgrade_is_not_asked_for(self):
        self.assertEqual(
            es.choose(self.dug(), [self.battleaxe()], [self.gladius()]), ()
        )

    def test_the_refusal_names_the_reason(self):
        self.assertIn("melee", es.refusal(self.gladius(), self.dug()))

    def test_a_ranged_weapon_is_still_worn(self):
        bow = piece(
            "Short Bow", 15, 2, 2, level=9, req=4, dmg_min1=5, dmg_max1=11, delay=2100
        )
        got = es.choose(self.dug(), [], [bow])
        self.assertEqual([e.name for e in got], ["Short Bow"])

    def test_a_melee_weapon_is_not_a_skill_wait_either(self):
        w = es.wearer_from_row(member("Dug", self.HUNTER, 16, skills="44,45,172"))
        self.assertEqual(
            es.waiting_on_skill(w, [self.battleaxe()], [self.gladius()]), ()
        )

    def test_a_warrior_still_wears_the_same_sword(self):
        w = es.wearer_from_row(member("Durg", 1, 25, skills=WARRIOR_SKILLS))
        self.assertEqual(es.refusal(self.gladius(), w), "")
