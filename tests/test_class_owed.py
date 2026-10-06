"""A class quest is owed before any dungeon (the operator, 2026-10-06).

Measured on the dev realm that day: Dreadlox, a warrior with quest 1498
incomplete, was picked for a Wailing Caverns run at 18:13 because the guild's
class hold only held a member ON a hunt, and he was in backoff at that moment;
nine tank warriors without Defensive Stance were seated as tanks (0 of 46
clears); Fleshless stands on Eastern Kingdoms and his chain starts in Kalimdor;
Ulag (quest 1819, creature 6390) has no spawn row. These tests hold every
formation path to the hold, the tank seat to its spell, the hold to its bound,
and the cross-continent quest to a named blocker.
"""

import asyncio
import dataclasses
import sys
import types
import unittest
from unittest import mock

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import classquest  # noqa: E402
import guildjobs  # noqa: E402
import guildpug as gp  # noqa: E402
import guildrun  # noqa: E402
import guildsocial as gs  # noqa: E402
import raidroles  # noqa: E402
import standin  # noqa: E402
from test_classquest import (  # noqa: E402
    EASTERN,
    KALIMDOR,
    UNDEAD,
    WARRIOR,
    book,
    class_plan,
    class_steps,
    qrow,
    who,
)
from test_guildpug import HOLY, PRIEST, four_yeses, pug_facts, yes  # noqa: E402
from test_guildsocial_bridge import _Self, bridge, facts, row  # noqa: E402
from test_standin import facts as standin_facts  # noqa: E402

DAY = 24 * 3600.0
PROTECTION = "12301"
DEFENSIVE_STANCE, BEAR_FORM = 71, 5487
DRUID = 11


def dreadlox(**over):
    """A warrior holding Path of Defense (1498) incomplete, level 19."""
    base = dict(
        name="Dreadlox",
        level=19,
        quest_log={1498: 3},
        quests_done=frozenset({1505}),
    )
    base.update(over)
    return who(**base)


# --- who owes ---------------------------------------------------------------------


class WhoOwes(unittest.TestCase):
    def test_a_quest_held_incomplete_is_owed(self):
        owed = classquest.owed(book(), dreadlox())
        self.assertEqual((owed.quest, owed.blocker), (1498, ""))

    def test_a_quest_not_yet_taken_is_owed_too(self):
        self.assertEqual(classquest.owed(book(), who()).quest, 1505)

    def test_nothing_is_owed_below_the_quest_level_or_once_rewarded(self):
        self.assertIsNone(classquest.owed(book(), who(level=9)))
        self.assertIsNone(
            classquest.owed(book(), who(quests_done=frozenset({1505, 1498})))
        )
        self.assertIsNone(classquest.owed(book(), who(known=frozenset({8121}))))

    def test_another_class_owes_nothing_of_the_warriors(self):
        self.assertIsNone(classquest.owed(book(), who(class_id=5)))

    def test_a_creature_no_spawn_names_is_permanent_and_owed_by_nobody(self):
        # Ulag alone: creature 6390 is summoned by a script, no spawn row.
        only_ulag = book(
            quest_rows=[
                qrow(1819, "Ulag the Cleaver", reward=8121, npc1=6390, npc_count1=1)
            ]
        )
        m = who(quest_log={1819: 3})
        self.assertIsNone(classquest.owed(only_ulag, m))
        self.assertIn("no verb", classquest.next_move(only_ulag, m)[1][0])

    def test_a_gameobject_nothing_uses_is_permanent_too(self):
        altar = book(
            quest_rows=[qrow(2002, "Altar Job", reward=8121, npc1=-4000, npc_count1=1)]
        )
        self.assertIsNone(classquest.owed(altar, who(quest_log={2002: 3})))

    def test_a_group_quest_is_owed_and_asked_for(self):
        grp = book(
            quest_rows=[
                qrow(2000, "Group Job", reward=8121, grp=3, npc1=3130, npc_count1=1)
            ]
        )
        owed = classquest.owed(grp, who(quest_log={2000: 3}))
        self.assertEqual(owed.blocker, classquest.GROUP)

    def test_a_permanent_variant_does_not_clear_a_group_whose_other_is_open(self):
        # Fleshless: Ulag (permanent) in the log, the other chain across the sea.
        owed = classquest.owed(book(), fleshless())
        self.assertIsNotNone(owed)
        self.assertEqual(owed.blocker, classquest.MAP)


def fleshless(**over):
    """An Undead warrior on Eastern Kingdoms holding Ulag the Cleaver."""
    base = dict(
        name="Fleshless",
        race=UNDEAD,
        map_id=EASTERN,
        x=-20.0,
        y=-996.0,
        level=19,
        quest_log={1819: 3},
        quests_done=frozenset({1818}),
    )
    base.update(over)
    return who(**base)


# --- owed whatever the member is doing --------------------------------------------


class OwedWhateverItIsDoing(unittest.TestCase):
    """class_held reads the plan line, which names a member only while it is on
    a hunt. The hold reads the book."""

    def refused(self, minutes_ago=2):
        row_ = guildjobs.Recent(
            "Dreadlox",
            classquest.ACTION,
            minutes_ago,
            status="error",
            refusal=classquest.REALM_FULL_REASON,
            retryable=True,
        )
        return (row_,)

    def test_a_member_in_backoff_is_held(self):
        result = class_plan([dreadlox()], recent=self.refused())
        self.assertEqual(set(result.owed), {"Dreadlox"})

    def test_a_member_the_pass_does_not_ready_has_no_line_and_is_still_held(self):
        # class_step plans nobody in combat, dead or offline: no line, so
        # class_held names nobody, and the old hold let the member be picked.
        for over in (dict(in_combat=True), dict(alive=False), dict(online=False)):
            result = class_plan([dreadlox(**over)])
            if over.get("alive") is not False:
                self.assertEqual(guildjobs.class_held(result.lines), set(), over)
            self.assertEqual(set(result.owed), {"Dreadlox"}, over)

    def test_a_member_waiting_for_a_far_walk_slot_is_held(self):
        far = dreadlox(x=-282.0, y=-6500.0)
        result = class_plan([far], far_slots=0)
        self.assertTrue(any("far walk slot" in n for n in result.notes))
        self.assertEqual(set(result.owed), {"Dreadlox"})

    def test_a_member_with_an_unread_position_is_held(self):
        m = dreadlox(map_id=None, x=None, y=None, online=False)
        self.assertIsNotNone(guildjobs.class_owed(m, book()))

    def test_a_member_whose_quest_is_permanently_blocked_is_not_held(self):
        only_ulag = book(
            quest_rows=[
                qrow(1819, "Ulag the Cleaver", reward=8121, npc1=6390, npc_count1=1)
            ]
        )
        result = class_plan([who(quest_log={1819: 3})], b=only_ulag)
        self.assertEqual(result.owed, {})

    def test_no_book_holds_nobody(self):
        self.assertEqual(guildjobs.plan([dreadlox()], masters={}).owed, {})


# --- the bound --------------------------------------------------------------------


class TheBound(unittest.TestCase):
    def plan_at(self, owing, now, **over):
        return class_plan([dreadlox(**over)], owing=owing, now=now)

    def test_six_hours_with_no_progress_releases_the_hold(self):
        owing = classquest.Owing()
        self.assertEqual(classquest.OWED_HOURS, 6)
        self.assertIn("Dreadlox", self.plan_at(owing, 1000.0).owed)
        held = self.plan_at(owing, 1000.0 + 5.9 * 3600)
        self.assertIn("Dreadlox", held.owed)
        late = self.plan_at(owing, 1000.0 + 6.1 * 3600)
        self.assertEqual(late.owed, {})
        self.assertIn("Dreadlox", late.released)

    def test_the_release_keeps_the_ask_and_names_the_blocker(self):
        grp = book(
            quest_rows=[
                qrow(2000, "Group Job", reward=8121, grp=3, npc1=3130, npc_count1=1)
            ]
        )
        owing = classquest.Owing()
        m = who(quest_log={2000: 3})
        class_plan([m], b=grp, owing=owing, now=0.0)
        late = class_plan([m], b=grp, owing=owing, now=7 * 3600.0)
        self.assertEqual(late.owed, {})
        self.assertEqual([h.move.quest for h in late.helps], [2000])
        note = next(n for n in late.notes if "released" in n)
        self.assertIn("Group Job", note)
        self.assertIn("group", note)

    def test_progress_starts_the_clock_over(self):
        owing = classquest.Owing()
        self.plan_at(owing, 0.0)
        later = self.plan_at(owing, 7 * 3600.0, quest_progress={1498: 2})
        self.assertIn("Dreadlox", later.owed)
        self.assertEqual(later.released, {})

    def test_a_member_that_owes_nothing_forgets_its_clock(self):
        owing = classquest.Owing()
        self.plan_at(owing, 0.0)
        class_plan([dreadlox(known=frozenset({8121}))], owing=owing, now=3600.0)
        again = self.plan_at(owing, 7 * 3600.0)
        self.assertIn("Dreadlox", again.owed)

    def test_another_guilds_pass_does_not_reset_this_ones_clock(self):
        owing = classquest.Owing()
        self.plan_at(owing, 0.0)
        class_plan([who("Other")], owing=owing, now=3 * 3600.0)
        late = self.plan_at(owing, 7 * 3600.0)
        self.assertIn("Dreadlox", late.released)


# --- every formation path ---------------------------------------------------------


class TheGuildRuns(unittest.TestCase):
    def test_why_not_names_the_class_quest(self):
        member_ = guildrun.member_from_row(row("Dreadlox", 19, WARRIOR))
        self.assertEqual(
            guildrun.why_not(
                member_, set(), set(), set(), frozenset(), frozenset({"Dreadlox"})
            ),
            guildrun.OWES_CLASS_QUEST,
        )
        self.assertEqual(guildrun.why_not(member_, set(), set(), set()), "")

    def test_free_members_leaves_the_owed_out(self):
        rows = [row("Dreadlox", 19, WARRIOR), row("Zappy", 19, 8)]
        free, held = guildrun.free_members(
            rows, set(), set(), set(), frozenset(), frozenset({"Dreadlox"})
        )
        self.assertEqual([m.name for m in free], ["Zappy"])
        self.assertEqual(held, {guildrun.OWES_CLASS_QUEST: 1})

    def test_the_coordinator_picks_nobody_that_owes(self):
        this = _Self()
        this._class_owed_by = {None: {"Dreadlox": classquest.Owed(1498, "x", 1)}}
        this._class_board = None
        seen = []
        the_facts = facts()
        the_facts.update(
            rows=[
                row("Dreadlox", 19, WARRIOR, talent_spells=PROTECTION),
                row("Zappy", 19, 8),
            ],
            finder_floors={},
            history=[],
            in_flight_by_guild={},
        )

        def pools(members, doors):
            seen.extend(m.name for m in members)
            return []

        with (
            mock.patch.multiple(
                bridge,
                _guild_run_gate=lambda: {"uptime": 99999, "latest": []},
                _guild_runs_in_flight=lambda: 0,
                _fetch_guild_run_facts=lambda bounds: the_facts,
            ),
            mock.patch.object(guildrun, "pools", pools),
        ):
            asyncio.run(bridge.Bridge._guild_run_once(this))
        self.assertEqual(seen, ["Zappy"])


class TheSocialPass(unittest.TestCase):
    def run_once(self, owed, the_facts=None, **patches):
        written = []
        this = _Self()
        this._class_owed_by = {
            None: {n: classquest.Owed(1498, "Path of Defense", 1) for n in owed}
        }
        stubs = {
            "_guild_run_gate": lambda: {"uptime": 99999, "latest": []},
            "_guild_runs_in_flight": lambda: 0,
            "_fetch_guild_social_facts": lambda bounds: the_facts or facts(),
            "_write_guild_social": lambda social: written.append(social) or 0,
            "_guild_social_names": lambda: set(),
        }
        stubs.update(patches)
        with mock.patch.multiple(bridge, **stubs):
            asyncio.run(bridge.Bridge._guild_social_once(this))
        return written

    def test_a_yes_from_a_member_that_owes_a_class_quest_is_not_seated(self):
        written = self.run_once({"Zappy"})
        self.assertIsNone(written[0].form)
        self.assertEqual(written[0].withdraw, (3,))

    def test_the_same_pass_forms_the_group_when_nobody_owes(self):
        self.assertIsNotNone(self.run_once(set())[0].form)

    def test_a_member_that_owes_is_not_the_asker_of_a_dungeon(self):
        the_facts = facts()
        the_facts["asks"] = []
        the_facts["answers"] = []
        owed_all = {r["name"] for r in the_facts["rows"]}
        written = self.run_once(owed_all, the_facts)
        self.assertEqual(written[0].posts, ())

    def test_the_hold_costs_no_need(self):
        held, needs = bridge._hold_owed(
            {"A": "offline"}, {"A": 1, "B": 2, "C": 3}, {"A", "B"}
        )
        self.assertEqual(held, {"A": "offline", "B": guildrun.OWES_CLASS_QUEST})
        self.assertEqual(needs, {"C": 3})

    def test_the_hold_reads_every_cohort(self):
        this = types.SimpleNamespace(_class_owed_by={"a": {"X": 1}, "b": {"Y": 2}})
        self.assertEqual(bridge._class_owed_names(this), {"X", "Y"})
        self.assertEqual(bridge._class_owed_names(types.SimpleNamespace()), set())


class ThePickUpGroups(unittest.TestCase):
    def test_a_pug_that_owes_a_class_quest_is_not_seated(self):
        the_facts = pug_facts()
        the_facts["answers"] = four_yeses() + [
            yes(9, 7, "Mercy", "healer", stance="pug")
        ]
        rows = [row("Mercy", 20, PRIEST, guild_name="", talent_spells=HOLY)]
        written = []
        this = _Self()
        this._class_owed_by = {None: {"Mercy": classquest.Owed(1, "x", 1)}}
        with mock.patch.multiple(
            bridge,
            _guild_run_gate=lambda: {"uptime": 99999, "latest": []},
            _guild_runs_in_flight=lambda: 0,
            _fetch_guild_social_facts=lambda bounds: the_facts,
            _fetch_guild_pugs=lambda span, bounds: rows,
            _write_guild_social=lambda social: written.append(social) or 0,
            _write_guild_pugs=lambda pp: None,
            _guild_social_names=lambda: set(),
        ):
            asyncio.run(bridge.Bridge._guild_social_once(this))
        self.assertIsNone(written[0].form)

    def test_the_pug_read_holds_the_owed_as_busy(self):
        mates = [
            gs.mate_from_row(
                row("Mercy", 20, PRIEST, guild_name="", talent_spells=HOLY)
            ),
        ]
        _all, answered, held = gp.pug_mates(
            [row("Mercy", 20, PRIEST, guild_name="", talent_spells=HOLY)],
            [yes(9, 7, "Mercy", "healer", stance="pug")],
            {"Mercy"},
            set(),
        )
        self.assertEqual([m.name for m in answered], ["Mercy"])
        self.assertIn("Mercy", held)
        self.assertTrue(mates)


class TheFamilyStandIn(unittest.TestCase):
    def test_a_guildmate_that_owes_is_not_picked_to_stand_in(self):
        step = standin.step(standin_facts(owed=frozenset({"Locky"})))
        self.assertEqual(step.action, standin.SEAT)
        self.assertEqual(step.seat.in_name, "Zappy")

    def test_nobody_stands_in_when_every_guildmate_owes(self):
        step = standin.step(standin_facts(owed=frozenset({"Locky", "Zappy", "Arrow"})))
        self.assertEqual(step.seat.in_name, "")

    def test_a_seated_guest_that_comes_to_owe_is_released_between_runs(self):
        seat = standin.Seat("Grug", "Og", "Locky", "dps", "Og crafts")
        kept = standin.step(standin_facts(current=seat))
        self.assertEqual(kept.action, standin.KEEP)
        cleared = standin.step(standin_facts(current=seat, owed=frozenset({"Locky"})))
        self.assertEqual(cleared.action, standin.CLEAR)
        self.assertIn(guildrun.OWES_CLASS_QUEST, cleared.why)

    def test_the_bridge_reads_the_owed_into_the_facts(self):
        this = types.SimpleNamespace(_class_owed_by={None: {"Locky": 1}}, _mid_run=None)
        gfacts = {"busy": set(), "resting": set(), "benched": set(), "family": set()}
        got = asyncio.run(
            bridge.Bridge._standin_facts(
                this, "Grug", "", None, [], None, gfacts, {}, ()
            )
        )
        self.assertEqual(got.owed, frozenset({"Locky"}))


# --- the tank seat needs its spell ------------------------------------------------


def tank(name="Tanky", level=21, **over):
    base = dict(talent_spells=PROTECTION, has_shield=1, has_tank_kit=1)
    base.update(over)
    return guildrun.member_from_row(row(name, level, WARRIOR, **base))


class TheTankKit(unittest.TestCase):
    def test_the_spells_are_defensive_stance_and_bear_form(self):
        self.assertEqual(raidroles.TANK_KIT, {1: DEFENSIVE_STANCE, 11: BEAR_FORM})
        self.assertEqual(raidroles.tank_kit(WARRIOR), DEFENSIVE_STANCE)
        self.assertEqual(raidroles.tank_kit(2), 0)

    def test_a_warrior_without_defensive_stance_is_not_tank_ready(self):
        self.assertFalse(guildrun.tank_ready(tank(has_tank_kit=0)))
        self.assertTrue(guildrun.tank_ready(tank()))

    def test_a_druid_without_bear_form_is_not_tank_ready(self):
        def bear(kit):
            return guildrun.member_from_row(
                row("Bear", 20, DRUID, talent_spells=None, has_tank_kit=kit)
            )

        druid = dataclasses.replace(bear(0), tree="Feral Combat")
        self.assertFalse(guildrun.tank_ready(druid))
        self.assertTrue(
            guildrun.tank_ready(dataclasses.replace(druid, has_tank_kit=True))
        )

    def test_a_paladin_needs_no_quest_spell(self):
        pal = guildrun.member_from_row(
            row("Pal", 20, 2, talent_spells=None, has_shield=1, has_tank_kit=0)
        )
        self.assertTrue(guildrun.has_kit(pal))

    def test_an_unread_spell_list_is_not_held(self):
        unread = guildrun.member_from_row(
            row("Tanky", 21, WARRIOR, talent_spells=PROTECTION, has_shield=1)
        )
        self.assertIsNone(unread.has_tank_kit)
        self.assertTrue(guildrun.tank_ready(unread))

    def test_the_seat_checks_agree(self):
        kitless = tank(has_tank_kit=0)
        self.assertFalse(gs.can_take(kitless, gs.TANK))
        self.assertEqual(gs.role_of(kitless), gs.DPS)
        self.assertFalse(gs.seatable(kitless))
        self.assertTrue(gs.can_take(tank(), gs.TANK))

    def test_a_group_with_only_a_kitless_tank_does_not_form(self):
        healer = guildrun.member_from_row(row("Healy", 20, PRIEST, talent_spells=HOLY))
        dps = [
            guildrun.member_from_row(row(n, 20, c))
            for n, c in (("Zappy", 8), ("Locky", 9), ("Stab", 4))
        ]
        self.assertEqual(
            guildrun.compositions([tank(has_tank_kit=0), healer] + dps), []
        )
        formed = guildrun.compositions([tank(), healer] + dps)
        self.assertEqual(formed[0].tank.name, "Tanky")

    def test_the_social_pass_seats_no_kitless_tank(self):
        def run(kit):
            the_facts = facts()
            for r in the_facts["rows"]:
                if r["name"] == "Tanky":
                    r["has_tank_kit"] = kit
            written = []
            with mock.patch.multiple(
                bridge,
                _guild_run_gate=lambda: {"uptime": 99999, "latest": []},
                _guild_runs_in_flight=lambda: 0,
                _fetch_guild_social_facts=lambda bounds: the_facts,
                _write_guild_social=lambda social: written.append(social) or 0,
                _guild_social_names=lambda: set(),
            ):
                asyncio.run(bridge.Bridge._guild_social_once(_Self()))
            return written[0]

        self.assertIsNotNone(run(1).form)
        self.assertIsNone(run(0).form)

    def test_the_column_holds_every_kit_entry(self):
        for klass, spell in raidroles.TANK_KIT.items():
            self.assertIn(
                "(s.class = %d AND cs.spell = %d)" % (klass, spell),
                raidroles.TANK_KIT_COLUMN,
            )
        self.assertEqual(
            raidroles.TANK_KIT_COLUMN.count("(s.class"), len(raidroles.TANK_KIT)
        )

    def test_the_member_read_asks_the_world_for_the_spell(self):
        self.assertIn("has_tank_kit", bridge._GUILD_RUN_MEMBERS_SQL)
        self.assertIn("character_spell", bridge._GUILD_RUN_MEMBERS_SQL)
        self.assertIn("s.class = 1 AND cs.spell = 71", bridge._GUILD_PUGS_SQL)
        self.assertIn("s.class = 11 AND cs.spell = 5487", bridge._GUILD_PUGS_SQL)


# --- the quest across the sea -----------------------------------------------------


class TheCrossing(unittest.TestCase):
    def test_a_quest_on_the_other_continent_names_it_and_the_missing_verb(self):
        move, blocked = classquest.next_move(book(), fleshless(quest_log={}))
        # Take Veteran Uzzek's chain at Kalimdor, or Dillinger's here.
        self.assertTrue(move is not None or blocked)
        far = fleshless(quest_log={}, quests_done=frozenset({1818}), race=2)
        move, blocked = classquest.next_move(book(), far)
        text = " ".join(blocked)
        self.assertIn("Kalimdor", text)
        self.assertIn(classquest.CROSSING_VERB, text)

    def test_the_owed_row_carries_the_continent_to_reach(self):
        owed = classquest.owed(book(), fleshless())
        self.assertEqual(owed.to_map, KALIMDOR)
        self.assertIn(classquest.CROSSING_VERB, owed.said)

    def test_far_map_is_only_for_the_two_continents(self):
        m = fleshless()
        spot = classquest.Spawn(1, 2, KALIMDOR, 0.0, 0.0)
        self.assertEqual(classquest.far_map(m, [spot]), KALIMDOR)
        self.assertEqual(classquest.far_map(fleshless(map_id=KALIMDOR), [spot]), -1)
        outland = classquest.Spawn(1, 2, 530, 0.0, 0.0)
        self.assertEqual(classquest.far_map(m, [outland]), -1)
        self.assertEqual(classquest.far_map(fleshless(map_id=None), [spot]), -1)

    def test_the_member_stays_held_while_it_waits_for_the_verb(self):
        result = class_plan([fleshless()])
        self.assertEqual(class_steps(result), [])
        self.assertIn("Fleshless", result.owed)
        self.assertTrue(any(classquest.CROSSING_VERB in n for n in result.notes))


class TheWiring(unittest.TestCase):
    def test_every_formation_path_reads_the_hold(self):
        with open(bridge.__file__, encoding="utf-8") as f:
            text = f.read()
        for needle in (
            "owing=self._class_owing",
            "self._class_owed_by[_cohort_key(cohort)] = dict(plan.owed)",
            'facts["family"], facts["benched"], owed=frozenset(_class_owed_names(self))',
            "held, needs = _hold_owed(held, needs, owed)",
            "owed=frozenset(_class_owed_names(self))",
        ):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
