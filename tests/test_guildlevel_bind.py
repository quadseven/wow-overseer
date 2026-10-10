"""A member that reaches the zone it now levels in sets its hearth at that zone's
inn (2026-10-10).

Read on the dev realm on 2026-10-10: 140 of the two guilds' 142 members were
bound at their starting inn, 39 of them on map 530 (20 Draenei at Ammen Vale, 19
Blood Elves on Sunstrider Isle), and 14 of those 39 stood on the continents. A
hearth (the stood-still hearth, a gear walk's, a guild run's) puts a Draenei or
a Blood Elf back on its island, and the level step then has to take it off by
the boat or the orb again. A player rebinds at the inn of the zone it levels in.
This is that: once a member whose hearth is bound somewhere it has outgrown
stands in a zone whose band fits its level, it walks to that zone's innkeeper
(`walk-to-spawn creature:<spawn> near:3`, quadseven/mod-overseer: the walk ends
inside the innkeeper's reach) and binds there (`kind='bind'`, `here`), the
core's own HandleBinderActivateOpcode. Nothing is moved and nothing is granted.
"""

import unittest

import guildjobs
import guildlevel
import guildroute
from test_guildlevel import (
    ALL_HUBS,
    AZUREMYST,
    BLOODMYST,
    DARKSHORE,
    DRAENEI,
    EASTERN_KINGDOMS,
    ELWYNN,
    HUMAN,
    KALIMDOR,
    OUTLAND,
    QUESTS,
    WESTFALL,
    master_rows,
)
from test_guildlevel import member as level_member

AMMEN_VALE = 3526


def inn_rows():
    """One innkeeper 40 yards from every hub's taxi node, spawn id by hub
    order."""
    rows = []
    for i, hub in enumerate(ALL_HUBS):
        point = hub.point
        rows.append(
            {
                "guid": 70000 + i,
                "map_id": point[0],
                "x": point[1] + 40.0,
                "y": point[2],
                "name": "Innkeeper of %s" % hub.name,
                "enemy_group": 0,
            }
        )
    return rows


def inn_of(key):
    return 70000 + [h.key for h in ALL_HUBS].index(key)


def hub(key):
    return next(h for h in ALL_HUBS if h.key == key)


def world(inns=None):
    return guildlevel.world(
        QUESTS, master_rows(), (), inn_rows=inn_rows() if inns is None else inns
    )


def at(key, **over):
    """A level 14 human priest standing at a hub, bound in Elwynn Forest."""
    h = hub(key)
    base = dict(
        map_id=h.point[0],
        x=h.point[1] + 300.0,
        y=h.point[2],
        zone_id=h.zone_id,
        home_map=EASTERN_KINGDOMS,
        home_zone=ELWYNN,
    )
    base.update(over)
    return level_member(**base)


def plan(members, recent=(), leveling=None):
    return guildjobs.plan(
        members,
        masters={"Cave": "Grug"},
        leveling=leveling or world(),
        cap=guildroute.FAR_WALK_YARDS,
        recent=tuple(recent),
    )


def bind_steps(result, name="Cleric"):
    return [s for s in result.steps if s.holder == name and s.action == guildlevel.INN_ACTION]


class TheInns(unittest.TestCase):
    def test_each_hub_has_the_innkeeper_beside_it(self):
        inns = guildlevel.hub_inns(inn_rows())
        self.assertEqual(inns["westfall"].spawn, inn_of("westfall"))

    def test_an_innkeeper_too_far_from_the_hub_is_not_its_inn(self):
        far = [dict(r, x=r["x"] + guildlevel.INN_YARDS) for r in inn_rows()]
        self.assertNotIn("westfall", guildlevel.hub_inns(far))

    def test_the_other_sides_innkeeper_is_not_its_inn(self):
        hostile = [dict(r, enemy_group=2) for r in inn_rows()]  # attacks the Alliance
        self.assertNotIn("westfall", guildlevel.hub_inns(hostile))


class WhoBinds(unittest.TestCase):
    def test_a_member_in_a_zone_that_fits_and_bound_where_it_has_outgrown_binds(self):
        steps = bind_steps(plan([at("westfall")]))
        self.assertEqual(len(steps), 1)
        step = steps[0]
        self.assertEqual(step.walk.kind, "job")
        self.assertEqual(
            step.walk.command,
            "walk-to-spawn creature:%d near:%d max:%d"
            % (inn_of("westfall"), guildlevel.INN_NEAR_YARDS, int(guildroute.FAR_WALK_YARDS)),
        )
        self.assertEqual([(r.kind, r.command) for r in step.rows], [("bind", "here")])
        self.assertEqual(step.rows[0].source, "guildjobs:level-bind:Cleric")
        self.assertIn("sets its hearth", step.said)
        self.assertIn("Sentinel Hill", step.said)

    def test_a_draenei_landed_on_kalimdor_binds_there(self):
        draenei = at(
            "darkshore",
            race=DRAENEI,
            home_map=OUTLAND,
            home_zone=AMMEN_VALE,
        )
        steps = bind_steps(plan([draenei]))
        self.assertEqual(len(steps), 1)
        self.assertIn("creature:%d " % inn_of("darkshore"), steps[0].walk.command)

    def test_bound_in_the_zone_already_it_does_not(self):
        self.assertEqual(bind_steps(plan([at("westfall", home_zone=WESTFALL)])), [])

    def test_bound_somewhere_that_still_fits_it_does_not(self):
        # Bound in Loch Modan, which still fits level 14.
        self.assertEqual(bind_steps(plan([at("westfall", home_zone=38)])), [])

    def test_a_member_in_a_zone_it_has_outgrown_does_not(self):
        self.assertEqual(bind_steps(plan([at("westfall", level=22)])), [])

    def test_a_member_still_in_its_starting_zone_does_not(self):
        home = level_member(home_map=EASTERN_KINGDOMS, home_zone=ELWYNN)
        self.assertEqual(bind_steps(plan([home])), [])

    def test_a_draenei_in_bloodmyst_at_its_level_binds_at_blood_watch(self):
        draenei = at(
            "bloodmyst", race=DRAENEI, home_map=OUTLAND, home_zone=AMMEN_VALE
        )
        steps = bind_steps(plan([draenei]))
        self.assertEqual(len(steps), 1)
        self.assertIn("creature:%d " % inn_of("bloodmyst"), steps[0].walk.command)

    def test_no_inn_for_the_zone_no_bind(self):
        self.assertEqual(bind_steps(plan([at("westfall")], leveling=world(inns=[]))), [])

    def test_an_unread_home_does_not(self):
        self.assertEqual(
            bind_steps(plan([at("westfall", home_map=None, home_zone=None)])), []
        )

    def test_not_while_fighting_dead_or_offline(self):
        for over in ({"in_combat": True}, {"alive": False}, {"online": False}):
            self.assertEqual(bind_steps(plan([at("westfall", **over)])), [], over)

    def test_a_roster_family_member_is_left_to_levelroute(self):
        leveling = guildlevel.world(
            QUESTS, master_rows(), ("Cleric",), inn_rows=inn_rows()
        )
        self.assertEqual(bind_steps(plan([at("westfall")], leveling=leveling)), [])

    def test_one_try_in_the_cooldown(self):
        row = guildjobs.Recent("Cleric", guildlevel.INN_ACTION, 30, status="error")
        self.assertEqual(bind_steps(plan([at("westfall")], recent=(row,))), [])
        old = guildjobs.Recent(
            "Cleric", guildlevel.INN_ACTION, guildlevel.INN_COOLDOWN_MINUTES, status="error"
        )
        self.assertEqual(len(bind_steps(plan([at("westfall")], recent=(old,)))), 1)

    def test_the_class_quest_still_comes_first(self):
        source = guildjobs._member_step.__code__.co_names
        self.assertLess(source.index("class_step"), source.index("_inn_first"))


class TheBridge(unittest.TestCase):
    def test_the_bridge_reads_the_homes_and_the_innkeepers(self):
        import pathlib

        source = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text()
        for needle in (
            "character_homebind hb ON hb.guid = c.guid",
            "home_map=_row_int(r, \"home_map\")",
            "_JOB_INNS_SQL",
            "inn_rows=facts.get(\"inns\", ())",
        ):
            self.assertTrue(needle in source, needle)


class TheSides(unittest.TestCase):
    def test_a_horde_member_binds_at_its_own_sides_inn(self):
        orc = at(
            "barrens",
            race=2,
            home_map=KALIMDOR,
            home_zone=14,  # Durotar
        )
        steps = bind_steps(plan([orc]))
        self.assertEqual(len(steps), 1)
        self.assertIn("creature:%d " % inn_of("barrens"), steps[0].walk.command)


if __name__ == "__main__":
    unittest.main()
