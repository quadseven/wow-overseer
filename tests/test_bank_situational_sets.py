"""Members keep situational sets in the bank, chosen by gearscore (#540).

Decision #532: alternative and situational pieces (tank, healing, fire
resistance, PvP) stay in the member's bank, scored by the same per-spec
weights as the upgrade tracker, and no sale pass sells what the policy keeps.
"""

from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import bag_pressure  # noqa: E402
import bankpolicy  # noqa: E402
import gearscore  # noqa: E402
import guildjobs  # noqa: E402
import keep  # noqa: E402

PALADIN = 2
SPELL_POWER, INTELLECT, STRENGTH, STAMINA = 45, 5, 4, 7


def reach(bucket="chest"):
    return bag_pressure.GearReach(
        bucket=bucket,
        holder_role="damage",
        holder_class=PALADIN,
        holder_level=60,
        holder_wears=True,
        later_wearers=(),
    )


def keeper(role="damage"):
    return bankpolicy.Keeper("Grog", PALADIN, 60, role, frozenset())


def piece(guid, scored=(), **kw):
    base = dict(
        holder="Grog",
        guid=guid,
        entry=90000 + guid,
        name=kw.pop("name", "Piece %d" % guid),
        quality=kw.pop("quality", 3),
        item_class=bankpolicy.ARMOR,
        required_level=kw.pop("required_level", 55),
        item_level=kw.pop("item_level", 60),
        bound=True,
        scored=tuple(sorted(dict(scored).items())),
    )
    base.update(kw)
    return bankpolicy.Piece(**base)


# Spell power and intellect: a healing piece. No statweights `stats` are given,
# so only gearscore can see what it is for.
HEALING = (("spell_power", 60), ("intellect", 20))


class TheSetIsChosenByGearscore(unittest.TestCase):
    def test_a_healing_piece_is_kept_by_a_damage_paladin(self):
        plate = piece(1, HEALING)
        facts = bankpolicy.Facts(
            pieces=(plate,), family=(keeper(),), reach={1: reach()}
        )
        placed = bankpolicy.place(facts)[1]
        self.assertEqual("healing set", placed.kind)
        self.assertEqual(bankpolicy.PERSONAL, placed.to)

    def test_a_piece_for_the_holders_own_role_is_nobodys_second_set(self):
        facts = bankpolicy.Facts(
            pieces=(piece(2, HEALING),), family=(keeper("healer"),), reach={2: reach()}
        )
        self.assertEqual({}, bankpolicy.place(facts))

    def test_the_better_scoring_piece_wins_the_slot_over_item_level(self):
        weak_but_high_level = piece(3, (("spell_power", 20),), item_level=70)
        strong = piece(4, HEALING, item_level=55)
        facts = bankpolicy.Facts(
            pieces=(weak_but_high_level, strong),
            family=(keeper(),),
            reach={3: reach(), 4: reach()},
        )
        self.assertEqual([4], sorted(bankpolicy.place(facts)))

    def test_the_score_is_the_upgrade_trackers(self):
        stats = dict(HEALING)
        expected = gearscore.score(stats, "paladin-holy", 60)
        self.assertAlmostEqual(
            expected,
            bankpolicy.situational_score(piece(5, HEALING), PALADIN, 60, "healer"),
        )
        self.assertGreater(expected, 0)

    def test_rows_carry_gearscores_stats_into_the_piece(self):
        row = {
            "holder": "Grog",
            "item_guid": 9,
            "entry": 1234,
            "name": "Robe",
            "quality": 3,
            "item_class": bankpolicy.ARMOR,
            "container_slots": 0,
            "stat_type1": SPELL_POWER,
            "stat_value1": 40,
            "stat_type2": INTELLECT,
            "stat_value2": 12,
            "fire_res": 5,
        }
        got = dict(bankpolicy.pieces_from_rows([row])[0].scored)
        self.assertEqual(40, got["spell_power"])
        self.assertEqual(12, got["intellect"])
        self.assertEqual(5, got["fire_resistance"])

    def test_the_item_read_selects_the_columns_gearscore_needs(self):
        for column in ("it.block", "it.delay", "it.dmg_min1", "it.frost_res"):
            self.assertIn(column, bankpolicy.ITEMS_SQL)


class NoSalePassSellsWhatThePolicyKeeps(unittest.TestCase):
    """guildjobs sells grey and outgrown white gear. A white fire resistance
    piece is both outgrown and a kept second set: the sale must skip it."""

    def setUp(self):
        self.fire = guildjobs.Carried(
            guid=77,
            entry=5500,
            item_class=bankpolicy.ARMOR,
            subclass=2,
            quality=1,
            sell_price=40,
            name="Scorched Boots",
            item_level=10,
        )
        self.member = guildjobs.Member(
            name="Grog", guild="Cave", role="raider", level=60, carried=(self.fire,)
        )
        self.piece = piece(
            77,
            (("fire_resistance", 8),),
            quality=1,
            fire_res=8,
            item_level=10,
            required_level=5,
            name="Scorched Boots",
        )
        facts = bankpolicy.Facts(
            pieces=(self.piece,), family=(keeper(),), reach={77: reach("feet")}
        )
        self.placed = bankpolicy.place(facts)

    def test_the_piece_is_outgrown_and_kept(self):
        self.assertTrue(self.fire.sellable(60))
        self.assertEqual("fire resistance set", self.placed[77].kind)

    def test_without_the_policy_the_junk_sale_would_sell_it(self):
        rows = guildjobs.junk_sales(self.member, keep.Reservations())
        self.assertEqual(["guid:77"], [r.command for r in rows])

    def test_with_the_policys_keeps_neither_sale_sells_it(self):
        kept = keep.with_guids(keep.Reservations(), bankpolicy.kept_pairs(self.placed))
        self.assertEqual((), guildjobs.junk_sales(self.member, kept))
        self.assertIsNone(guildjobs._sell_step(self.member, kept, 1))

    def test_a_kept_pair_is_per_holder(self):
        kept = keep.with_guids(keep.Reservations(), [("Grog", 77)])
        other = guildjobs.Member(
            name="Zug", guild="Cave", role="raider", level=60, carried=(self.fire,)
        )
        self.assertEqual(1, len(guildjobs.junk_sales(other, kept)))


class TheGuildJobsPassReadsThePolicy(unittest.TestCase):
    def test_the_pass_plans_with_the_policys_keeps_not_the_bare_reservations(self):
        src = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text()
        start = src.index("async def _plan_guild_jobs")
        body = src[start : src.index("async def _job_gear_offers")]
        self.assertIn("_kept_with_bank_policy", body)
        self.assertNotIn("_KEEP.now", body)


if __name__ == "__main__":
    unittest.main()
