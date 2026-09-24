"""The raiders a guild's healer shortfall asks to respec, in a raid leader's order.

The guilds are the dev realm's on 2026-09-24, read by class and talent tree:
each placed eight healers of the twelve a forty-raider lineup wants.
"""

import ast
import asyncio
import os
import sys
import time
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import guildcorps  # noqa: E402
import healerspec  # noqa: E402
import raidlineup  # noqa: E402
import raidroles  # noqa: E402
from raidlineup import (  # noqa: E402
    DEATH_KNIGHT,
    DRUID,
    HUNTER,
    MAGE,
    PALADIN,
    PRIEST,
    ROGUE,
    SHAMAN,
    WARLOCK,
    WARRIOR,
)


def _member(name, class_id, spec, level=60):
    return {"name": name, "class_id": class_id, "level": level, "spec": spec}


def _many(prefix, class_id, spec, count):
    return [_member("%s%02d" % (prefix, i), class_id, spec) for i in range(count)]


CAVE_FAMILY = ["Grug", "Og", "Bork", "Grog", "Ugga"]


def cave():
    """Cave by class and talent tree, the family among them."""
    members = [
        _member("Grug", WARRIOR, "Protection"),
        _member("Og", MAGE, "Frost"),
        _member("Bork", ROGUE, "Combat"),
        _member("Grog", PALADIN, "Retribution"),
        _member("Ugga", PRIEST, "Holy"),
        _member("Deathknight", DEATH_KNIGHT, ""),
        _member("Shadowa", PRIEST, "Shadow"),
        _member("Shadowb", PRIEST, "Shadow"),
        _member("Shadowc", PRIEST, "Shadow"),
        _member("Reta", PALADIN, "Retribution"),
        _member("Retb", PALADIN, "Retribution"),
        _member("Retc", PALADIN, "Retribution"),
        _member("Enha", SHAMAN, "Enhancement"),
        _member("Enhb", SHAMAN, "Enhancement"),
        _member("Enhc", SHAMAN, "Enhancement"),
        _member("Elea", SHAMAN, "Elemental"),
        _member("Eleb", SHAMAN, "Elemental"),
    ]
    members += _many("Feral", DRUID, "Feral Combat", 3)
    members += _many("Resto", DRUID, "Restoration", 1)
    members += _many("Hunter", HUNTER, "Marksmanship", 6)
    members += _many("Mage", MAGE, "Arcane", 6)
    members += _many("Holypal", PALADIN, "Holy", 1)
    members += _many("Protpal", PALADIN, "Protection", 3)
    members += _many("Priest", PRIEST, "Holy", 3)
    members += _many("Disc", PRIEST, "Discipline", 1)
    members += _many("Rogue", ROGUE, "Combat", 4)
    members += _many("Rshaman", SHAMAN, "Restoration", 1)
    members += _many("Warlock", WARLOCK, "Destruction", 21)
    members += _many("Warrior", WARRIOR, "Fury", 3)
    members += _many("Arms", WARRIOR, "Arms", 1)
    members += _many("Protwar", WARRIOR, "Protection", 2)
    return members


BONKERS_FAMILY = ["Zug", "Oz", "Uzza", "Zork", "Zrog"]


def bonkers():
    """Bonkers as measured: every hybrid but one paladin is family."""
    members = [
        _member("Zug", WARRIOR, "Protection", 29),
        _member("Oz", MAGE, "Fire", 27),
        _member("Uzza", PRIEST, "Holy", 26),
        _member("Zork", DRUID, "Feral Combat", 27),
        _member("Zrog", SHAMAN, "Enhancement", 27),
        _member("Velalenn", PALADIN, "Protection"),
        _member("Quelmin", PALADIN, "Holy"),
    ]
    members += _many("Priest", PRIEST, "Holy", 4)
    members += _many("Disc", PRIEST, "Discipline", 2)
    members += _many("Hunter", HUNTER, "Marksmanship", 9)
    members += _many("Mage", MAGE, "Frost", 12)
    members += _many("Rogue", ROGUE, "Assassination", 10)
    members += _many("Warlock", WARLOCK, "Demonology", 21)
    members += _many("Warrior", WARRIOR, "Fury", 3)
    members += _many("Protwar", WARRIOR, "Protection", 3)
    return members


def lineup(members, family):
    return raidlineup.build_lineup(members, guaranteed=family)


def everyone_online(members):
    return frozenset(m["name"] for m in members)


class CaveIsFourHealersShort(unittest.TestCase):
    def setUp(self):
        self.members = cave()
        self.lineup = lineup(self.members, CAVE_FAMILY)
        self.chosen, self.notes = healerspec.choose(
            "Cave", self.lineup, CAVE_FAMILY, everyone_online(self.members)
        )

    def test_the_lineup_measured_the_shortfall(self):
        self.assertEqual(self.lineup["shortfall"]["healers"], 4)

    def test_two_shadow_priests_and_two_retribution_paladins(self):
        self.assertEqual(
            [(p.name, p.tree) for p in self.chosen],
            [
                ("Shadowa", "Shadow"),
                ("Shadowb", "Shadow"),
                ("Reta", "Retribution"),
                ("Retb", "Retribution"),
            ],
        )

    def test_the_last_shadow_priest_stays(self):
        self.assertNotIn("Shadowc", [p.name for p in self.chosen])
        self.assertIn(
            "Shadowc stays Shadow: the guild keeps one Shadow priest", self.notes
        )

    def test_each_goes_to_its_class_healing_tree(self):
        self.assertEqual(
            {p.name: p.tab for p in self.chosen},
            {"Shadowa": 1, "Shadowb": 1, "Reta": 0, "Retb": 0},
        )
        self.assertEqual(self.chosen[0].healing_tree, "Holy")

    def test_never_the_family(self):
        self.assertNotIn("Grog", [p.name for p in self.chosen])

    def test_never_a_seated_tank(self):
        seated = [
            m["name"]
            for g in self.lineup["groups"]
            for m in g["members"]
            if m["duty"] in (raidlineup.MAIN_TANK, raidlineup.OFF_TANK)
        ]
        self.assertTrue(set(seated).isdisjoint(p.name for p in self.chosen))

    def test_after_the_respecs_the_lineup_is_whole(self):
        changed = {p.name: healerspec.HEALING_TREE[p.class_id] for p in self.chosen}
        after = [dict(m, spec=changed.get(m["name"], m["spec"])) for m in self.members]
        self.assertEqual(lineup(after, CAVE_FAMILY)["shortfall"]["healers"], 0)
        self.assertEqual(
            healerspec.choose("Cave", lineup(after, CAVE_FAMILY), CAVE_FAMILY)[0], []
        )


class BonkersNeedsRecruitsToo(unittest.TestCase):
    def setUp(self):
        members = bonkers()
        self.lineup = lineup(members, BONKERS_FAMILY)
        self.chosen, self.notes = healerspec.choose(
            "Bonkers", self.lineup, BONKERS_FAMILY, everyone_online(members)
        )

    def test_the_one_paladin_outside_the_family(self):
        self.assertEqual([(p.name, p.tab) for p in self.chosen], [("Velalenn", 0)])

    def test_the_rest_is_said_to_be_a_recruit(self):
        short = self.lineup["shortfall"]["healers"]
        self.assertGreater(short, 1)
        self.assertIn(
            "Bonkers is %d healer(s) short after these respecs, and no other raider outside "
            "the family can heal: that is a recruit, not a respec" % (short - 1),
            self.notes,
        )

    def test_the_familys_druid_and_shaman_are_not_asked(self):
        self.assertTrue({"Zork", "Zrog"}.isdisjoint(p.name for p in self.chosen))


class WhoseWalkStartsThisPass(unittest.TestCase):
    def setUp(self):
        self.members = cave()
        self.lineup = lineup(self.members, CAVE_FAMILY)

    def test_at_most_two_per_pass(self):
        picks, _ = healerspec.picks(
            "Cave", self.lineup, CAVE_FAMILY, everyone_online(self.members)
        )
        self.assertEqual([p.name for p in picks], ["Shadowa", "Shadowb"])

    def test_an_online_raider_goes_before_an_offline_one(self):
        online = everyone_online(self.members) - {"Shadowa"}
        chosen, notes = healerspec.choose("Cave", self.lineup, CAVE_FAMILY, online)
        self.assertEqual([p.name for p in chosen][:2], ["Shadowb", "Shadowc"])
        self.assertIn("Shadowa stays Shadow: the guild keeps one Shadow priest", notes)

    def test_a_chosen_raider_out_of_the_world_waits(self):
        members = bonkers()
        online = everyone_online(members) - {"Velalenn"}
        chosen, _ = healerspec.choose(
            "Bonkers", lineup(members, BONKERS_FAMILY), BONKERS_FAMILY, online
        )
        self.assertEqual([p.name for p in chosen], ["Velalenn"])
        picks, notes = healerspec.picks(
            "Bonkers", lineup(members, BONKERS_FAMILY), BONKERS_FAMILY, online
        )
        self.assertEqual(picks, [])
        self.assertIn("Velalenn is not in the world", notes)

    def test_a_recent_ask_is_left_alone(self):
        recent = {("Shadowa", "respec", 1): 30}
        picks, notes = healerspec.picks(
            "Cave", self.lineup, CAVE_FAMILY, everyone_online(self.members), recent
        )
        self.assertEqual([p.name for p in picks], ["Shadowb", "Reta"])
        self.assertIn(
            "Shadowa was asked 30 minute(s) ago and is left alone for 180", notes
        )
        recent = {("Shadowa", "respec", 1): healerspec.RETRY_MINUTES}
        picks, _ = healerspec.picks(
            "Cave", self.lineup, CAVE_FAMILY, everyone_online(self.members), recent
        )
        self.assertEqual(picks[0].name, "Shadowa")

    def test_a_raider_on_another_errand_waits(self):
        picks, notes = healerspec.picks(
            "Cave",
            self.lineup,
            CAVE_FAMILY,
            everyone_online(self.members),
            busy={"Shadowa"},
        )
        self.assertEqual([p.name for p in picks], ["Shadowb", "Reta"])
        self.assertIn("Shadowa is on another guild errand", notes)

    def test_nothing_when_nobody_is_short(self):
        full = cave() + _many("Extra", PRIEST, "Holy", 4)
        self.assertEqual(lineup(full, CAVE_FAMILY)["shortfall"]["healers"], 0)
        self.assertEqual(
            healerspec.picks(
                "Cave", lineup(full, CAVE_FAMILY), CAVE_FAMILY, everyone_online(full)
            ),
            ([], []),
        )

    def test_a_raider_below_the_raid_level_is_not_asked(self):
        young = [
            dict(m, level=58) if m["name"] == "Shadowa" else m for m in self.members
        ]
        chosen, _ = healerspec.choose(
            "Cave", lineup(young, CAVE_FAMILY), CAVE_FAMILY, everyone_online(young)
        )
        self.assertNotIn("Shadowa", [p.name for p in chosen])


class TheRow(unittest.TestCase):
    def test_the_module_verb(self):
        pick = healerspec.Pick("Shadowa", "Cave", PRIEST, "Shadow", 1, True)
        step = healerspec.step(pick, 20000)
        self.assertEqual(step.holder, "Shadowa")
        self.assertIsNone(step.walk)
        self.assertEqual(len(step.rows), 1)
        row = step.rows[0]
        self.assertEqual(
            (row.kind, row.command, row.source),
            ("cast", "walk-to-trainer talents:1 max:20000", "healerspec:respec:1"),
        )
        self.assertIn("respecs to Holy", step.said)

    def test_its_own_rows_are_read_back_as_its_cooldown(self):
        recent = guildcorps.recent_from_rows(
            [
                {"source": "healerspec:respec:1", "target_name": "Shadowa", "age": 12},
                {"source": "guildcorps:train:197", "target_name": "Shadowa", "age": 3},
            ],
            prefix=healerspec.SOURCE,
        )
        self.assertEqual(recent, {("Shadowa", "respec", 1): 12})


class TheLineupIsReadFromTalentSpells(unittest.TestCase):
    def test_one_shadow_talent_reads_as_the_shadow_tree(self):
        book = raidroles._book()
        shadow = next(
            s
            for s, (cid, tree, _rank) in book.items()
            if cid == PRIEST and tree == "Shadow"
        )
        rows = [
            {
                "guild_name": "Cave",
                "name": "Shadowa",
                "class_id": PRIEST,
                "level": 60,
                raidroles.KEY: str(shadow),
            }
        ]
        lineups = healerspec.lineups_from_rows(rows, [])
        placed = [m for g in lineups["Cave"]["groups"] for m in g["members"]]
        self.assertEqual(placed[0]["spec"], "Shadow")


BRIDGE = open(
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bridge.py"
    ),
    encoding="utf-8",
).read()


class _Log:
    def __init__(self):
        self.lines = []

    def info(self, msg, *a, **k):
        self.lines.append(msg % a if a else msg)

    warning = exception = debug = info


class TheBridgePass(unittest.TestCase):
    """The corps pass starts the respec walks through the corps' own runner."""

    def body(self, name):
        start = BRIDGE.index("    async def %s(" % name)
        end = BRIDGE.index("\n    async def ", start + 10)
        return BRIDGE[start:end]

    def test_every_familys_guild_is_asked_after_the_corps_and_the_raid_supply(self):
        corps = self.body("_guild_corps_once")
        ask = (
            "self._healer_respec_once(facts, names, busy | set(self._corps_steps), cap)"
        )
        self.assertEqual(corps.count(ask), 2)
        other = corps.index("if cohort is not None:")
        self.assertLess(
            corps.index("busy |= {step.holder for step in plan.steps}"), other
        )
        self.assertLess(other, corps.index(ask))
        self.assertLess(corps.index(ask), corps.index("return", other))
        self.assertLess(
            corps.index("self._raid_supply_once(facts, plan.corps, busy, cap)"),
            corps.rindex(ask),
        )

    def test_the_facts_carry_the_lineups_and_the_pass_own_rows(self):
        start = BRIDGE.index("def _fetch_corps_facts(")
        facts = BRIDGE[start : BRIDGE.index("\ndef ", start + 10)]
        self.assertIn(
            '"lineups": healerspec.lineups_from_rows(rows, family_names)', facts
        )
        self.assertIn('(healerspec.SOURCE + ":%",)', facts)
        self.assertIn("prefix=healerspec.SOURCE", facts)

    def run_pass(self, online):
        tree = ast.parse(BRIDGE)
        found = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "_healer_respec_once"
        ]
        log = _Log()
        ns = {
            "healerspec": healerspec,
            "asyncio": asyncio,
            "time": time,
            "log": log,
            "_log_capped": lambda prefix, notes: [
                log.info("%s: %s", prefix, n) for n in notes
            ],
        }
        exec(compile(ast.Module(body=found, type_ignores=[]), "bridge.py", "exec"), ns)  # noqa: S102
        steps = []

        class Self:
            _corps_steps = {}
            _mail_walk_tasks = set()

            def _mail_walk_task_done(self, task):
                return None

            async def _run_corps_step(self, step, cap):
                steps.append((step, cap))

        me = Self()
        me._healer_respec_once = types.MethodType(ns["_healer_respec_once"], me)
        members = cave()
        facts = {
            "lineups": {"Cave": lineup(members, CAVE_FAMILY)},
            "online": online(members),
            "healer_recent": {},
        }

        async def go():
            await me._healer_respec_once(facts, CAVE_FAMILY, set(), 20000.0)
            await asyncio.sleep(0)

        asyncio.run(go())
        return steps, log, me

    def test_two_walks_start_and_hold_their_raiders(self):
        steps, log, me = self.run_pass(everyone_online)
        self.assertEqual([s.holder for s, _ in steps], ["Shadowa", "Shadowb"])
        self.assertEqual(
            steps[0][0].rows[0].command, "walk-to-trainer talents:1 max:20000"
        )
        self.assertEqual(set(me._corps_steps), {"Shadowa", "Shadowb"})
        self.assertIn("healer respec: started 2 walk(s)", log.lines)
        self.assertIn(
            "healer respec: Shadowc stays Shadow: the guild keeps one Shadow priest",
            log.lines,
        )

    def test_nobody_in_the_world_starts_nothing(self):
        steps, log, _ = self.run_pass(lambda members: frozenset())
        self.assertEqual(steps, [])
        self.assertIn("healer respec: started 0 walk(s)", log.lines)


if __name__ == "__main__":
    unittest.main()
