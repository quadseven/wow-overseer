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

import json
import pathlib
import unittest

import guildcorps
import guildjobs
import purse
import weaponskill

ROOT = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (ROOT / "bridge.py").read_text(encoding="utf-8")

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


# A WEAPON MASTER ACROSS THE WATER (#793). On the dev realm the guild passes
# noted 362 times in a day that no weapon master of the member's side on its
# map teaches the skill: the Horde's masters for axes and maces stand in
# Kalimdor, the Alliance's for staves and daggers in the Eastern Kingdoms. The
# member now crosses to the continent whose master teaches it, by the module's
# `cross-to-map` row, and the next pass on that map walks it to the master.
FAR_MASTER = dict(MASTER, map_id=0, spawn=8765, name="Far Master", yards=9000.0)


class TheFarMaster(unittest.TestCase):
    def test_a_master_on_the_other_continent_is_chosen(self):
        got = weaponskill.choose_far_master([FAR_MASTER], {201}, "horde", 1)
        self.assertEqual(8765, got["spawn"])
        self.assertEqual(0, got["map_id"])

    def test_a_master_on_its_own_map_is_not_far(self):
        self.assertEqual({}, weaponskill.choose_far_master([MASTER], {201}, "horde", 1))

    def test_the_other_side_master_is_not_chosen(self):
        self.assertEqual(
            {}, weaponskill.choose_far_master([FAR_MASTER], {201}, "alliance", 1)
        )

    def test_off_the_classic_continents_nothing_is_far(self):
        self.assertEqual(
            {}, weaponskill.choose_far_master([FAR_MASTER], {201}, "horde", 530)
        )
        far_off = dict(FAR_MASTER, map_id=530)
        self.assertEqual(
            {}, weaponskill.choose_far_master([far_off], {201}, "horde", 1)
        )

    def test_the_master_teaching_more_wins(self):
        other = dict(FAR_MASTER, entry=11871, spawn=999, spell=196, yards=10.0)
        both = dict(FAR_MASTER, spell=196)
        got = weaponskill.choose_far_master(
            [other, FAR_MASTER, both], {201, 196}, "horde", 1
        )
        self.assertEqual(11870, got["entry"])

    def test_the_far_maps_are_the_other_continent(self):
        self.assertEqual([1], weaponskill.far_maps(0))
        self.assertEqual([0], weaponskill.far_maps(1))
        self.assertEqual([], weaponskill.far_maps(530))
        self.assertEqual([], weaponskill.far_maps(None))


def far_offer(n=None):
    return weaponskill.offer(n or need(), FAR_MASTER)


class TheCrossing(unittest.TestCase):
    def test_a_member_crosses_to_the_master_continent(self):
        result = guildjobs.plan([member()], weapons={"Eggo": far_offer()})
        (step,) = weapon_steps(result)
        self.assertIsNone(step.walk)
        self.assertEqual(
            (
                guildcorps.Row(
                    "job", "cross-to-map map:0", "", "guildjobs:weapon-cross:Eggo"
                ),
            ),
            step.rows,
        )
        self.assertIn("Far Master", step.said)
        self.assertIn("Eastern Kingdoms", step.said)

    def test_the_weapon_crossing_shares_the_crossing_clock(self):
        self.assertIn(guildjobs.WEAPON_CROSS_ACTION, guildjobs.CROSS_ACTIONS)
        recent = (
            guildjobs.Recent(
                "Eggo",
                guildjobs.WEAPON_CROSS_ACTION,
                5,
                command="cross-to-map map:0",
                dest=0,
            ),
        )
        result = guildjobs.plan(
            [member()], weapons={"Eggo": far_offer()}, recent=recent
        )
        self.assertEqual([], weapon_steps(result))

    def test_a_crossing_the_module_refused_for_good_is_said_not_asked(self):
        wall = sorted(guildjobs.classquest.CROSS_WALLS)[0]
        recent = (
            guildjobs.Recent(
                "Eggo",
                guildjobs.classquest.CROSS_ACTION,
                60,
                command="cross-to-map map:0",
                dest=0,
                refusal=wall,
            ),
        )
        result = guildjobs.plan(
            [member()], weapons={"Eggo": far_offer()}, recent=recent
        )
        self.assertEqual([], weapon_steps(result))
        self.assertTrue(any(wall in n for n in result.notes), result.notes)

    def test_a_purse_short_of_the_price_does_not_cross(self):
        result = guildjobs.plan([member(money=400)], weapons={"Eggo": far_offer()})
        self.assertEqual([], weapon_steps(result))
        self.assertTrue(any("saves for skill 43" in n for n in result.notes))


# THE MASTER ACROSS THE WATER IS RANKED FROM THE LANDING (#1585). The rows'
# yards are from the member on its own continent, so they ranked nothing on
# the other one, and an Alliance member could be sent to Darnassus, which a
# walk from Auberdine never reaches.
ORGRIMMAR_MASTER = dict(
    MASTER, entry=11868, spawn=501, name="Orgrimmar Master",
    x=1700.0, y=-4300.0, yards=9000.0,
)  # fmt: skip
BLUFF_MASTER = dict(
    MASTER, entry=11869, spawn=502, name="Bluff Master",
    x=-1200.0, y=-50.0, yards=10.0,
)  # fmt: skip
# Darnassus, on Teldrassil, and an Alliance master on the Eastern Kingdoms.
DARNASSUS_MASTER = dict(
    MASTER, entry=11866, spawn=601, name="Darnassus Master", faction=80,
    map_id=1, x=9950.0, y=2300.0, yards=10.0,
)  # fmt: skip
STORMWIND_MASTER = dict(
    MASTER, entry=11867, spawn=602, name="Stormwind Master", faction=12,
    map_id=0, x=-8800.0, y=600.0, yards=10.0,
)  # fmt: skip


class TheLanding(unittest.TestCase):
    def test_the_far_master_nearest_the_landing_wins(self):
        got = weaponskill.choose_far_master(
            [BLUFF_MASTER, ORGRIMMAR_MASTER], {201}, "horde", 0
        )
        self.assertEqual(501, got["spawn"])
        self.assertLess(got["yards"], 100.0)

    def test_an_entry_keeps_its_spawn_nearest_the_landing(self):
        near = dict(ORGRIMMAR_MASTER, spawn=503, yards=9500.0)
        far = dict(ORGRIMMAR_MASTER, x=-1200.0, y=-50.0, yards=5.0)
        got = weaponskill.choose_far_master([far, near], {201}, "horde", 0)
        self.assertEqual(503, got["spawn"])

    def test_every_landing_is_a_flight_point_of_the_world(self):
        nodes = {
            n["id"]: n
            for n in json.loads((ROOT / "taxinodes.json").read_text(encoding="utf-8"))[
                "nodes"
            ]
        }
        for (_team, map_id), points in weaponskill.LANDINGS.items():
            for node, x, y in points:
                with self.subTest(node=node):
                    self.assertEqual(map_id, nodes[node]["map"])
                    self.assertAlmostEqual(x, nodes[node]["x"], places=3)
                    self.assertAlmostEqual(y, nodes[node]["y"], places=3)
                    self.assertEqual(
                        weaponskill.MAINLAND, weaponskill.ground_of(map_id, x, y)
                    )


class TheIsland(unittest.TestCase):
    def test_darnassus_is_never_the_master_across_the_water(self):
        self.assertEqual(
            {},
            weaponskill.choose_far_master([DARNASSUS_MASTER], {201}, "alliance", 0),
        )

    def test_a_walk_from_auberdine_is_not_sent_to_darnassus(self):
        auberdine = {"map_id": 1, "pos_x": 6341.0, "pos_y": 557.0}
        self.assertEqual(
            {},
            weaponskill.choose_master(
                [DARNASSUS_MASTER], {201}, "alliance", 1, auberdine
            ),
        )

    def test_a_member_on_teldrassil_walks_to_darnassus(self):
        rut_theran = {"map_id": 1, "pos_x": 8643.0, "pos_y": 841.0}
        got = weaponskill.choose_master(
            [DARNASSUS_MASTER], {201}, "alliance", 1, rut_theran
        )
        self.assertEqual(601, got["spawn"])

    def test_the_island_is_the_zone_box_of_teldrassil(self):
        zones = json.loads((ROOT / "zones.json").read_text(encoding="utf-8"))
        (box,) = [
            z for z in zones["continents"]["1"]["zones"] if z["name"] == "Teldrassil"
        ]
        self.assertEqual(
            (("Teldrassil", box["bottom"], box["top"], box["right"], box["left"]),),
            weaponskill.ISLANDS[1],
        )

    def test_the_bridge_reads_the_ground_of_every_walker(self):
        self.assertEqual(
            3,
            BRIDGE.count('int(at["map_id"]), at)') + BRIDGE.count("int(m.map_id), at)"),
        )


def cross_row(action, dest, age, **over):
    return guildjobs.Recent(
        "Eggo", action, age, command="cross-to-map map:%d" % dest, dest=dest, **over
    )


class NoBackAndForth(unittest.TestCase):
    """THE LEVEL CROSSING COMES FIRST (#1585): past the shared crossing clock, a
    weapon crossing never undoes a level crossing, and is asked once a day."""

    def plan(self, recent):
        return guildjobs.plan([member()], weapons={"Eggo": far_offer()}, recent=recent)

    def test_a_level_crossing_here_holds_the_weapon_crossing(self):
        old = guildjobs.classquest.CROSS_COOLDOWN_MINUTES + 30
        result = self.plan((cross_row(guildjobs.guildlevel.CROSS_ACTION, 1, old),))
        self.assertEqual([], weapon_steps(result))
        self.assertTrue(
            any("its level crossing brought it here" in n for n in result.notes),
            result.notes,
        )

    def test_a_weapon_crossing_there_and_back_is_not_asked_again(self):
        old = guildjobs.classquest.CROSS_COOLDOWN_MINUTES + 90
        result = self.plan((cross_row(guildjobs.WEAPON_CROSS_ACTION, 0, old),))
        self.assertEqual([], weapon_steps(result))
        self.assertTrue(any("and is back" in n for n in result.notes), result.notes)

    def test_a_level_crossing_elsewhere_or_refused_does_not_hold(self):
        old = guildjobs.classquest.CROSS_COOLDOWN_MINUTES + 30
        for row in (
            cross_row(guildjobs.guildlevel.CROSS_ACTION, 0, old),
            cross_row(guildjobs.guildlevel.CROSS_ACTION, 1, old, refusal="no"),
        ):
            with self.subTest(row=row):
                self.assertEqual(1, len(weapon_steps(self.plan((row,)))))


class TheBridgeReadsTheFarMaster(unittest.TestCase):
    def test_the_guild_offer_falls_back_to_the_far_master(self):
        body = BRIDGE.split("async def _job_weapon_offers", 1)[1].split(
            "\n    def ", 1
        )[0]
        self.assertIn("weaponskill.choose_far_master(", body)
        self.assertIn("weaponskill.far_maps(", body)

    def test_the_master_read_takes_a_list_of_maps(self):
        sql = BRIDGE.split("_WEAPON_MASTERS_SQL = (", 1)[1].split("\n)", 1)[0]
        self.assertIn("cr.map IN ({maps})", sql)


if __name__ == "__main__":
    unittest.main()
