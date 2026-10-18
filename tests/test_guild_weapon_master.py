"""A guild member walks to a weapon master for a weapon it carries (#793).

Measured on the dev realm on 2026-10-18: every guild equip pass logged 10 to 11
carried weapon upgrades per guild that "wait on a weapon skill a weapon master
teaches" (a gladius with no Swords, a bow with no Bows), pass after pass, and
none of them ever moved. The weapon-master walk (#399, weaponskill.py) runs only
for the family, with its leader; nothing ever sent a guild member outside the
family to one. The guild jobs now do: a walk to the master's spawn, then
`train-weapon skill:<id>` paid from the member's own gold, and the guild equip
pass puts the weapon on once the skill reads learned.

Pure unit tests against weaponskill and guildjobs.plan, and a read of bridge.py
for the wiring.
"""

import pathlib
import unittest

import guildcorps
import guildjobs
import purse
import weaponskill

BRIDGE = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text(
    encoding="utf-8"
)

MAGE, PRIEST, HUNTER = 8, 5, 3
SWORDS, BOWS = 43, 45


def carried(entry=5191, subclass=7, inventory_type=13, required_level=20, **over):
    base = dict(
        guid=900 + entry,
        entry=entry,
        item_class=guildjobs.WEAPON,
        subclass=subclass,
        quality=2,
        sell_price=500,
        name="A Gladius",
        item_level=24,
        required_level=required_level,
        inventory_type=inventory_type,
    )
    base.update(over)
    return guildjobs.Carried(**base)


def member(name="Eggo", **over):
    base = dict(
        name=name,
        guild="Cave",
        role=guildjobs.RAIDER,
        level=25,
        class_id=MAGE,
        race=2,
        online=True,
        map_id=1,
        x=0.0,
        y=0.0,
        money=5000,
        eligible=True,
        carried=(carried(),),
    )
    base.update(over)
    return guildjobs.Member(**base)


def need(name="Eggo", why="its mainhand is empty", slot="mainhand"):
    return weaponskill.Need(name, SWORDS, 201, 5191, "A Gladius", slot, why)


MASTER = {
    "entry": 11870,
    "spawn": 4321,
    "name": "Archibald",
    "faction": 68,
    "map_id": 1,
    "x": 10.0,
    "y": 20.0,
    "yards": 300.0,
    "spell": 201,
    "cost": 1000,
}


def offer(n=None, master=MASTER):
    return weaponskill.offer(n or need(), master)


def weapon_steps(result, name="Eggo"):
    return [
        s
        for s in result.steps
        if s.holder == name and s.action == guildjobs.WEAPON_ACTION
    ]


class WhoIsRead(unittest.TestCase):
    def test_a_mage_carrying_a_sword_it_could_learn_is_read(self):
        self.assertTrue(guildjobs.weapon_candidate(member(), ()))

    def test_a_priest_cannot_learn_swords(self):
        self.assertFalse(guildjobs.weapon_candidate(member(class_id=PRIEST), ()))

    def test_a_weapon_above_its_level_waits(self):
        m = member(carried=(carried(required_level=40),))
        self.assertFalse(guildjobs.weapon_candidate(m, ()))

    def test_a_hunter_melee_weapon_is_never_a_reason(self):
        m = member(class_id=HUNTER, carried=(carried(),))
        self.assertFalse(guildjobs.weapon_candidate(m, ()))
        bow = carried(entry=2504, subclass=2, inventory_type=15)
        self.assertTrue(
            guildjobs.weapon_candidate(member(class_id=HUNTER, carried=(bow,)), ())
        )

    def test_armor_or_an_off_hand_is_not_read(self):
        shield = carried(item_class=guildjobs.ARMOR, subclass=6, inventory_type=14)
        self.assertFalse(guildjobs.weapon_candidate(member(carried=(shield,)), ()))

    def test_offline_dead_fighting_or_unplaced_members_are_not_read(self):
        for over in (
            {"online": False},
            {"alive": False},
            {"in_combat": True},
            {"x": None},
        ):
            with self.subTest(**over):
                self.assertFalse(guildjobs.weapon_candidate(member(**over), ()))


class TheOffer(unittest.TestCase):
    def test_the_master_spawn_and_price_ride_on_the_offer(self):
        got = offer()
        self.assertEqual(
            (4321, 1, 10.0, 20.0, "Archibald", 1000),
            (got.spawn, got.map_id, got.x, got.y, got.master, got.cost),
        )

    def test_no_master_is_an_offer_with_no_spawn(self):
        self.assertEqual(0, offer(master={}).spawn)
        self.assertEqual(0, offer(master=dict(MASTER, spawn=None)).spawn)

    def test_the_chosen_master_keeps_its_spawn(self):
        chosen = weaponskill.choose_master([MASTER], {201}, "horde", 1)
        self.assertEqual(4321, weaponskill.offer(need(), chosen).spawn)

    def test_fills_empty(self):
        self.assertTrue(need().fills_empty)
        self.assertFalse(need(why="item level 24 over 8 worn").fills_empty)


class TheStep(unittest.TestCase):
    def test_a_member_walks_to_the_master_and_buys_the_skill(self):
        result = guildjobs.plan([member()], weapons={"Eggo": offer()})
        (step,) = weapon_steps(result)
        self.assertEqual(SWORDS, step.key)
        self.assertEqual(
            guildcorps.Row(
                "job",
                "walk-to-spawn creature:4321 near:%d%s"
                % (
                    guildjobs.WEAPON_MASTER_NEAR_YARDS,
                    guildjobs._cap_word(guildjobs.guildroute.MAIL_RUN_YARDS),
                ),
                "",
                "guildjobs:weapon-walk:Eggo",
            ),
            step.walk,
        )
        self.assertEqual(
            (
                guildcorps.Row(
                    "cast", "train-weapon skill:43", "5191", "guildjobs:weapon:Eggo"
                ),
            ),
            step.rows,
        )
        self.assertIn("Archibald", step.said)
        self.assertIn("A Gladius", step.said)

    def test_no_offer_no_step(self):
        self.assertEqual([], weapon_steps(guildjobs.plan([member()])))

    def test_no_master_on_its_map_is_said(self):
        result = guildjobs.plan([member()], weapons={"Eggo": offer(master={})})
        self.assertEqual([], weapon_steps(result))
        self.assertTrue(
            any("no weapon master of its side" in note for note in result.notes),
            result.notes,
        )

    def test_a_purse_short_of_the_price_saves(self):
        result = guildjobs.plan([member(money=400)], weapons={"Eggo": offer()})
        self.assertEqual([], weapon_steps(result))
        self.assertTrue(
            any("saves for skill 43" in n for n in result.notes), result.notes
        )

    def test_class_spells_owed_hold_the_gold_for_an_upgrade(self):
        order = purse.Order(
            "Eggo", 25, 5000, wants=(purse.Want(purse.SPELLS, 4800, "class spells"),)
        )
        better = offer(need(why="item level 24 over 8 worn"))
        result = guildjobs.plan([member(purse=order)], weapons={"Eggo": better})
        self.assertEqual([], weapon_steps(result))

    def test_an_empty_main_hand_spends_from_the_whole_purse(self):
        order = purse.Order(
            "Eggo", 25, 5000, wants=(purse.Want(purse.SPELLS, 4800, "class spells"),)
        )
        result = guildjobs.plan([member(purse=order)], weapons={"Eggo": offer()})
        self.assertEqual(1, len(weapon_steps(result)))

    def test_a_recent_trip_cools_down(self):
        recent = (guildjobs.Recent("Eggo", guildjobs.WEAPON_ACTION, 30, walk=True),)
        result = guildjobs.plan([member()], weapons={"Eggo": offer()}, recent=recent)
        self.assertEqual([], weapon_steps(result))
        old = (guildjobs.Recent("Eggo", guildjobs.WEAPON_ACTION, 130, walk=True),)
        result = guildjobs.plan([member()], weapons={"Eggo": offer()}, recent=old)
        self.assertEqual(1, len(weapon_steps(result)))

    def test_weapon_steps_share_the_gear_allowance(self):
        names = ["M%02d" % i for i in range(guildjobs.GEAR_STEPS_PER_GUILD + 2)]
        members = [member(name=n) for n in names]
        weapons = {n: offer(need(name=n)) for n in names}
        result = guildjobs.plan(members, weapons=weapons)
        self.assertEqual(
            guildjobs.GEAR_STEPS_PER_GUILD,
            sum(1 for s in result.steps if s.action == guildjobs.WEAPON_ACTION),
        )


class TheBridgeReadsAndPasses(unittest.TestCase):
    def test_the_plan_is_given_the_weapon_offers(self):
        body = BRIDGE.split("async def _plan_guild_jobs", 1)[1].split(
            "\n    async def ", 1
        )[0]
        self.assertIn("weapons = await self._job_weapon_offers(", body)
        self.assertIn("weapons=weapons", body)

    def test_the_master_read_names_the_spawn_and_the_price(self):
        sql = BRIDGE.split("_WEAPON_MASTERS_SQL = (", 1)[1].split("\n)", 1)[0]
        self.assertIn("cr.guid AS spawn", sql)
        self.assertIn("ts.MoneyCost AS cost", sql)
        self.assertIn("ORDER BY yards", sql)


if __name__ == "__main__":
    unittest.main()
