"""Where a family levels next: levelroute.py, its Jev choice, and its wiring.

The Horde family (Zug 28, Oz 25, Uzza 23, Zork 24, Zrog 24) was scattered
across the Barrens, Ashenvale and Stonetalon and died over and over to
Sharptalon, to Astranaar's sentinels and to Kolkar and Grimtotem elites. These
tests hold the choice a group of players would make instead: one friendly hub
in level order that the weakest member can survive, quests they can all take,
and no enemy town and no zone far above the weakest member.
"""

import asyncio
import pathlib
import unittest
from unittest import mock

import jev
import jev_choices
import levelroute
import questbook
import questshare

ROOT = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (ROOT / "bridge.py").read_text(encoding="utf-8")
SERVER = (ROOT / "map_server.py").read_text(encoding="utf-8")
PAGE = (ROOT / "index.html").read_text(encoding="utf-8")

KALIMDOR = 1
ORGRIMMAR = (KALIMDOR, 1637, 1677.6, -4315.7)

# name, race, class, level: two orcs, two trolls and a tauren.
HORDE_FIVE = (
    ("Zug", 2, 1, 28),
    ("Oz", 8, 8, 25),
    ("Uzza", 8, 5, 23),
    ("Zork", 6, 11, 24),
    ("Zrog", 2, 7, 24),
)


def members(levels=None):
    return tuple(
        {
            "name": name,
            "race": race,
            "class": cls,
            "level": (levels or {}).get(name, level),
            "map_id": KALIMDOR,
        }
        for name, race, cls, level in HORDE_FIVE
    )


def quests_in(zone, low, high, start=0, races=0, classes=0):
    """One quest per level from `low` to `high` in `zone`, ids from `start`."""
    return [
        {
            "quest": start + i,
            "zone": zone,
            "level": level,
            "min_level": max(level - 4, 1),
            "races": races,
            "classes": classes,
        }
        for i, level in enumerate(range(low, high + 1))
    ]


BARRENS, STONETALON, ASHENVALE, NEEDLES, HILLSBRAD = 17, 406, 331, 400, 267
QUESTS = tuple(
    quests_in(BARRENS, 10, 25, 1000)
    + quests_in(BARRENS, 18, 25, 1100)
    + quests_in(STONETALON, 18, 27, 2000)
    + quests_in(ASHENVALE, 20, 32, 3000)
    + quests_in(NEEDLES, 26, 41, 4000)
    + quests_in(HILLSBRAD, 20, 30, 5000)
)

# Astranaar's flight point (taxi node 28) and a handful of its sentinels, level
# 40 and of the Alliance, which is what makes it a town the Horde must avoid.
ASTRANAAR = next(n for n in levelroute.flightlearn.NODES if n.id == 28)


def sentinels(count=8, x=ASTRANAAR.x, y=ASTRANAAR.y):
    return (
        levelroute.Cell(
            map_id=KALIMDOR, x=x, y=y, level=40, elite=False, side=2, n=count
        ),
    )


def facts(**kw):
    kw.setdefault("members", members())
    kw.setdefault("here", ORGRIMMAR)
    kw.setdefault("zones", {n: 1637 for n, *_ in HORDE_FIVE})
    kw.setdefault("quests", QUESTS)
    kw.setdefault("rewarded", {})
    kw.setdefault("held", {})
    kw.setdefault("spawns", sentinels())
    kw.setdefault("deaths", {})
    return levelroute.Facts(family="Zug", **kw)


class TheWorldData(unittest.TestCase):
    def test_a_zones_levels_come_from_its_quests(self):
        found = levelroute.bands(QUESTS, levelroute.HORDE)
        self.assertEqual(found[ASHENVALE][:2], (21, 31))
        self.assertEqual(found[BARRENS][2], 24)

    def test_the_other_sides_quests_and_class_quests_do_not_count(self):
        rows = quests_in(BARRENS, 50, 55, 1, races=1101) + quests_in(
            BARRENS, 50, 55, 100, classes=1
        )
        self.assertEqual(levelroute.bands(rows, levelroute.HORDE), {})
        self.assertIn(BARRENS, levelroute.bands(rows[:6], levelroute.ALLIANCE))

    def test_an_alliance_flight_point_with_its_guards_is_a_town(self):
        found = levelroute.towns(levelroute.HORDE, sentinels())
        self.assertIn("Astranaar", [t[0] for t in found])
        ashenvale = levelroute.BY_KEY["ashenvale"]
        self.assertIn("Astranaar", levelroute.towns_in(ashenvale, found))

    def test_a_lone_flight_master_is_not_a_town(self):
        found = levelroute.towns(levelroute.HORDE, sentinels(count=1))
        self.assertNotIn("Astranaar", [t[0] for t in found])

    def test_every_hub_is_a_flight_point_of_its_own_side_on_a_classic_continent(self):
        for hub in levelroute.HUBS:
            self.assertTrue(hub.friendly, hub.key)
            self.assertIn(hub.map_id, (0, 1), hub.key)


class WhatMayBeChosen(unittest.TestCase):
    def test_a_zone_far_above_the_weakest_is_refused(self):
        refused = levelroute.refusals(facts())
        self.assertIn("too high", refused["needles"])
        self.assertIn("Uzza is 23", refused["needles"])

    def test_the_other_continent_is_refused_while_the_crossing_cannot_be_made(self):
        refused = levelroute.refusals(facts())
        self.assertIn("another continent", refused["hillsbrad"])

    def test_an_outgrown_zone_is_refused(self):
        refused = levelroute.refusals(
            facts(
                members=members(
                    {"Uzza": 30, "Zrog": 30, "Zork": 30, "Oz": 30, "Zug": 30}
                )
            )
        )
        self.assertIn("outgrown", refused["barrens"])

    def test_a_hub_beside_an_enemy_town_is_refused(self):
        splintertree = levelroute.BY_KEY["ashenvale"]
        map_id, x, y, _z = splintertree.point
        town = (("Nowhere Keep", "Ashenvale", map_id, x + 100.0, y),)
        self.assertEqual(levelroute.towns_beside(splintertree, town), ("Nowhere Keep",))
        with mock.patch.object(levelroute, "towns", return_value=town):
            refused = levelroute.refusals(facts())
        self.assertIn("beside Nowhere Keep", refused["ashenvale"])
        self.assertNotIn("ashenvale", levelroute.refusals(facts()))

    def test_a_zone_with_nothing_left_for_the_weakest_is_done(self):
        done = frozenset(q["quest"] for q in QUESTS if q["zone"] == STONETALON)
        refused = levelroute.refusals(facts(rewarded={"Uzza": done}))
        self.assertIn("done", refused["stonetalon"])

    def test_the_weakest_member_sets_the_window(self):
        opened, done = levelroute.zone_work(facts(), BARRENS, 23)
        # Barrens quests 18..25 twice over, less nothing done: the window is
        # 23 - GREEN_BELOW to 23 + ABOVE.
        self.assertEqual(opened, 16)
        self.assertEqual(done, 0)

    def test_a_quest_one_member_cannot_take_is_not_a_family_quest(self):
        rows = QUESTS + tuple(quests_in(BARRENS, 20, 24, 9000, races=32))
        opened, _ = levelroute.zone_work(facts(quests=rows), BARRENS, 23)
        self.assertEqual(opened, 16)

    def test_a_family_at_the_cap_has_no_leveling_zone(self):
        capped = members({n: 60 for n, *_ in HORDE_FIVE})
        self.assertEqual(levelroute.options(facts(members=capped)), [])


class WhichOne(unittest.TestCase):
    def test_level_order_the_barrens_first_for_a_weakest_of_23(self):
        opts = levelroute.options(facts())
        self.assertEqual([o.key for o in opts], ["barrens", "stonetalon", "ashenvale"])
        self.assertEqual(levelroute.heuristic(opts).key, "barrens")

    def test_a_zone_the_family_keeps_dying_in_is_put_last(self):
        dying = {BARRENS: levelroute.DEATHS_AVOID}
        pick = levelroute.heuristic(levelroute.options(facts(deaths=dying, spawns=())))
        self.assertEqual(pick.key, "stonetalon")
        once = {BARRENS: levelroute.DEATHS_AVOID - 1}
        pick = levelroute.heuristic(levelroute.options(facts(deaths=once, spawns=())))
        self.assertEqual(pick.key, "barrens")

    def test_a_zone_that_is_mostly_red_around_its_hub_is_put_last(self):
        crossroads = levelroute.BY_KEY["barrens"]
        map_id, x, y, _z = crossroads.point

        def cell(level, n):
            return levelroute.Cell(map_id, x, y, level, False, 0, n)

        red = (cell(23 + levelroute.DANGER_GAP, 6), cell(20, 4))
        pick = levelroute.heuristic(levelroute.options(facts(spawns=red)))
        self.assertEqual(pick.key, "stonetalon")
        mild = (cell(23 + levelroute.DANGER_GAP, 4), cell(20, 6))
        pick = levelroute.heuristic(levelroute.options(facts(spawns=mild)))
        self.assertEqual(pick.key, "barrens")

    def test_ashenvale_says_its_enemy_town_and_its_deaths(self):
        opts = levelroute.options(facts(deaths={ASHENVALE: 21}))
        ashenvale = next(o for o in opts if o.key == "ashenvale")
        self.assertEqual(ashenvale.towns, ("Astranaar",))
        self.assertTrue(ashenvale.heavy)

    def test_the_log_line_is_unique_and_says_why(self):
        pick = levelroute.heuristic(levelroute.options(facts()))
        line = levelroute.line("Zug", pick, "the heuristic", "first look")
        self.assertTrue(line.startswith("levelroute: family=Zug chose zone barrens"))


class WhatTheChoiceChanges(unittest.TestCase):
    def test_the_aim_is_the_zone_quest_most_of_them_hold(self):
        held = {
            "Zug": frozenset({1015, 1016, 3000}),
            "Oz": frozenset({1015, 3000}),
            "Zork": frozenset({1015}),
        }
        quest, holders = levelroute.zone_aim(facts(held=held), BARRENS)
        self.assertEqual((quest, holders), (1015, ("Oz", "Zork", "Zug")))

    def test_a_quest_over_the_window_or_put_aside_is_not_aimed(self):
        held = {n: frozenset({1015}) for n, *_ in HORDE_FIVE}
        held["Zug"] = frozenset({1015, 1106})
        self.assertEqual(
            levelroute.zone_aim(facts(held=held), BARRENS, skip={1015})[0], 1106
        )
        # Ashenvale's 3012 is level 32, nine over the weakest: never aimed.
        held = {"Zug": frozenset({3012}), "Oz": frozenset({3012})}
        self.assertEqual(levelroute.zone_aim(facts(held=held), ASHENVALE), (0, ()))

    def test_nobody_holding_a_zone_quest_is_no_aim(self):
        held = {"Zug": frozenset({3000})}
        self.assertEqual(levelroute.zone_aim(facts(held=held), BARRENS), (0, ()))

    def test_shares_keep_to_the_chosen_zone(self):
        catalog = {
            1015: questbook.Quest(id=1015, quest_level=20, flags=8, zone=BARRENS),
            784: questbook.Quest(id=784, quest_level=7, flags=8, zone=14),
        }
        family = [
            questbook.Member("Zug", 1, 2, 28, held=frozenset({1015, 784})),
            questbook.Member("Uzza", 5, 8, 23),
        ]
        plan = questshare.plan(levelroute.share_members(family, BARRENS), catalog)
        self.assertEqual([g.quest_id for g in plan.grants], [1015])
        refused = {r.quest_id: r.reasons for r in plan.refusals}
        self.assertIn(questbook.ELSEWHERE, refused[784])


class ThePage(unittest.TestCase):
    def test_where_we_are_and_where_next(self):
        view = levelroute.page_view(facts(zones={"Zug": 2437, "Uzza": 2437}))
        self.assertEqual(view["where"], "Where we are: Uzza, Zug in Ragefire Chasm.")
        self.assertIn("The Barrens (the Crossroads)", view["now"])
        self.assertIn("chosen by the heuristic", view["now"])
        self.assertTrue(view["next"].startswith("Next: "))

    def test_the_recorded_choice_is_shown_with_who_made_it(self):
        view = levelroute.page_view(facts(), "stonetalon", "Jev")
        self.assertIn("Stonetalon Mountains (Sun Rock Retreat)", view["now"])
        self.assertIn("chosen by Jev", view["now"])

    def test_the_route_holds_hubs_dungeons_class_quests_and_the_mount(self):
        bands = levelroute.route(facts())
        first = bands[0]
        self.assertEqual(first["band"], "23-29")
        self.assertIn("Wailing Caverns 17-24", first["dungeons"])
        self.assertIn("The Barrens", [z["zone"] for z in first["zones"]])
        milestones = [m for b in bands for m in b["milestones"]]
        self.assertIn("Zug at 30: Whirlwind Axe (class quest)", milestones)
        self.assertIn("Zug at 40: Shield Slam (protection talent)", milestones)
        self.assertIn("everyone at 40: riding and a mount", milestones)

    def test_at_the_cap_it_says_so(self):
        capped = members({n: 60 for n, *_ in HORDE_FIVE})
        view = levelroute.page_view(facts(members=capped))
        self.assertEqual(view["now"], "At the level cap: no leveling zone.")


class JevChoosesTheZone(unittest.TestCase):
    def ask(self, fake, key="k", environ=None, deaths=None):
        from test_jev_items import FakeJev  # noqa: F401 - the shared fake

        f = facts(deaths=deaths or {})
        opts = levelroute.options(f)
        pick = levelroute.heuristic(opts)
        rule = jev_choices.policy(jev_choices.KIND_ZONE, environ or {})
        client = jev.Client(key, transport=fake)
        judgment = asyncio.run(
            jev_choices.zone_ask(client, f, opts, pick, rule, "first look")
        )
        return judgment, opts, pick

    def fake(self, **kw):
        from test_jev_items import FakeJev

        return FakeJev(**kw)

    def test_the_question_carries_the_facts_a_group_would_weigh(self):
        fake = self.fake(picks={"zone": "stonetalon"}, confidence=0.9)
        judgment, opts, _pick = self.ask(fake, deaths={ASHENVALE: 21})
        [request] = fake.requests
        self.assertEqual(
            list(request["questions"]["zone"]["criteria"]), [o.key for o in opts]
        )
        zone = next(z for z in request["state"]["zones"] if z["zone"] == "Ashenvale")
        self.assertEqual(zone["enemy_faction_towns_in_the_zone"], ["Astranaar"])
        self.assertEqual(zone["family_deaths_there_in_the_last_day"], 21)
        for fact in (
            "open_quests_for_the_family",
            "quests_the_family_has_done_there",
            "hostile_elites_near_the_hub",
            "yards_from_the_leader",
        ):
            self.assertIn(fact, zone)
        self.assertEqual(
            request["state"]["weakest_member"], {"name": "Uzza", "level": 23}
        )
        self.assertIn("worn_item_level", request["state"]["family"][0])
        self.assertEqual(judgment.kind, "leveling_zone")

    def test_a_confident_answer_acts(self):
        fake = self.fake(picks={"zone": "stonetalon"}, confidence=0.9)
        judgment, opts, pick = self.ask(fake)
        self.assertEqual(judgment.acted, jev.JEV)
        self.assertEqual(
            jev_choices.zone_carried(opts, pick, judgment).key, "stonetalon"
        )
        self.assertTrue(
            judgment.line().startswith("levelroute: family=Zug chose stonetalon")
        )

    def test_below_the_floor_or_with_no_key_the_heuristic_acts(self):
        fake = self.fake(picks={"zone": "stonetalon"}, confidence=0.5)
        judgment, opts, pick = self.ask(fake)
        self.assertIs(jev_choices.zone_carried(opts, pick, judgment), pick)
        judgment, opts, pick = self.ask(self.fake(), key="")
        self.assertEqual(judgment.status, jev.NO_KEY)
        self.assertIs(jev_choices.zone_carried(opts, pick, judgment), pick)

    def test_it_acts_by_default_behind_its_floor(self):
        rule = jev_choices.policy(jev_choices.KIND_ZONE, {})
        self.assertEqual((rule.mode, rule.threshold), (jev.ACT, 0.7))
        off = jev_choices.policy(
            jev_choices.KIND_ZONE, {"JEV_MODE_LEVELING_ZONE": "off"}
        )
        self.assertEqual(off.mode, jev.OFF)

    def test_off_asks_nothing(self):
        fake = self.fake()
        judgment, _, _ = self.ask(fake, environ={"JEV_MODE_LEVELING_ZONE": "off"})
        self.assertIsNone(judgment)
        self.assertEqual(fake.requests, [])


class TheWiring(unittest.TestCase):
    def pass_body(self):
        start = BRIDGE.index("async def _level_route_loop")
        return BRIDGE[start : BRIDGE.index("async def _goal_thought")]

    def test_the_pass_is_scheduled_in_both_loop_lists(self):
        self.assertEqual(BRIDGE.count("self._level_route_loop,"), 2)

    def test_jev_is_asked_and_the_answer_recorded(self):
        body = self.pass_body()
        self.assertIn("jev_choices.zone_ask(", body)
        self.assertIn("_insert_jev_judgment, judgment", body)
        self.assertIn("jev_choices.zone_carried(opts, pick, judgment)", body)

    def test_it_only_acts_while_the_family_quests_and_never_mid_run(self):
        body = self.pass_body()
        carry = body[body.index("async def _level_carry_out") :]
        self.assertIn('if job not in ("", jobs.DEFAULT):', carry)
        self.assertIn("await self._mid_run(names)", carry)
        self.assertLess(carry.index("jobs.DEFAULT"), carry.index("_claim_town_slot"))

    def test_the_walk_goes_through_the_town_slot_to_the_hub(self):
        body = self.pass_body()
        self.assertIn("LEVEL_CLAIMANT, leader, aim", body)
        self.assertIn("travel.ground_aim(*point)", body)

    def test_no_queue_is_written_and_the_own_family_is_not_aimed(self):
        body = self.pass_body()
        self.assertNotIn("campaignqueue.INSERT_SQL", body)
        self.assertNotIn("CANCEL_SQL", body)
        carry = body[body.index("async def _level_carry_out") :]
        self.assertLess(
            carry.index("if own:\n            return"), carry.index("self._level_aim(")
        )

    def test_the_aim_is_held_to_the_familys_own_rows(self):
        aim = BRIDGE[BRIDGE.index("def _aim_family_quest") :]
        aim = aim[: aim.index("\n\n\n")]
        self.assertEqual(aim.count("UPDATE overseer_roster"), 3)
        self.assertEqual(aim.count("WHERE family = %"), 3)

    def test_the_shares_are_held_to_the_zone(self):
        self.assertIn("members = levelroute.share_members(members, zone)", BRIDGE)
        self.assertIn("_share_family_quests, names, hub.zone_id", self.pass_body())

    def test_the_page_reads_it_and_draws_it(self):
        self.assertIn('"/api/levelroute": _levelroute,', SERVER)
        handler = SERVER[SERVER.index("def _levelroute(") :]
        handler = handler[: handler.index("def _armory_guild")]
        self.assertIn("self._family_scope(query)", handler)
        self.assertNotIn("query.get", handler)
        self.assertIn('u("/api/levelroute" + familyQuery(asked))', PAGE)
        self.assertIn('<span class="fsecl">leveling route</span>', PAGE)

    def test_the_module_ships_in_the_image(self):
        self.assertIn(
            "levelroute.py", (ROOT / "Dockerfile").read_text(encoding="utf-8")
        )


if __name__ == "__main__":
    unittest.main()
