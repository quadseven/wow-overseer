"""Pick-up groups (#591): a guild group short a real tank or healer calls in
LookingForGroup, a random bot of the same side that plays the seat answers,
and the run forms with the guildmates and the pug, the tank leading.

These pin the pure decisions in guildpug.py and the social layer's seating of
a pug, and drive the bridge's half with its reads stubbed.
"""

import asyncio
import datetime
import os
import sys
import types
import unittest
from unittest import mock

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import guildpug as gp  # noqa: E402
import guildsocial as gs  # noqa: E402
from test_guildsocial import (  # noqa: E402
    DEADMINES,
    DOORS,
    ENTRANCES,
    HOLY,
    MAGE,
    NOW,
    PRIEST,
    PROTECTION,
    ROGUE,
    WARLOCK,
    WARRIOR,
    ask,
    mate,
    plan,
    yes,
)
from test_guildsocial_bridge import _Conn, _Self, bridge, facts, row  # noqa: E402

ORC = 2
SHADOW = "15392"  # Shadow Weaving: a priest who plays damage
DOORS_BY_KEY = {d.keyword: d for d in DOORS}


def pug(name, level=20, class_id=PRIEST, **kw):
    """A random bot outside the guild: by default a Holy priest by the door."""
    kw.setdefault("talent_spells", HOLY)
    kw.setdefault("guild", "")
    return mate(name, level, class_id, **kw)


def old_ask(minutes=6, **kw):
    return ask(
        7,
        "Auren",
        created_at=NOW - datetime.timedelta(minutes=minutes),
        expires_at=NOW + datetime.timedelta(minutes=10 - minutes),
        **kw,
    )


def guild_four():
    """The asker and three guildmates who said yes: a tank and two damage
    dealers. Nobody in the guild plays a healer at this band."""
    return [
        mate("Auren", 20, ROGUE),
        mate("Tanky", 21, WARRIOR, talent_spells=PROTECTION, has_shield=1),
        mate("Zappy", 19, MAGE),
        mate("Locky", 20, WARLOCK),
    ]


def four_yeses():
    return [
        yes(1, 7, "Tanky", "tank"),
        yes(3, 7, "Zappy", "dps"),
        yes(4, 7, "Locky", "dps"),
    ]


def call(minutes_ago=2, seats=("healer",)):
    return gp.Call(
        7,
        "Auren",
        tuple(seats),
        "LF healer",
        NOW - datetime.timedelta(minutes=minutes_ago),
    )


def pug_plan(mates, asks, answers, calls=None, pugs=(), social=None, **kw):
    social = social or gs.Pass()
    free = {m.name: m.member for m in mates}
    return gp.plan(
        social,
        list(asks),
        list(answers),
        dict(calls or {}),
        free,
        list(pugs),
        DOORS_BY_KEY,
        {"Cave": "Alliance"},
        ENTRANCES,
        NOW,
        **kw,
    )


class TheSwitch(unittest.TestCase):
    def test_on_unless_turned_off(self):
        self.assertTrue(gp.enabled({}))
        self.assertTrue(gp.enabled({"GUILD_PUGS": "on"}))
        for off in ("off", "0", "false", "no", "OFF"):
            self.assertFalse(gp.enabled({"GUILD_PUGS": off}))


class WhenToLook(unittest.TestCase):
    def test_short_only_a_healer_after_five_minutes_the_asker_calls(self):
        out = pug_plan(guild_four(), [old_ask()], four_yeses())
        self.assertEqual(len(out.calls), 1)
        c = out.calls[0]
        self.assertEqual((c.ask_id, c.asker, c.seats), (7, "Auren", ("healer",)))
        self.assertIn("healer", c.said)
        self.assertIn("Deadmines", c.said)
        self.assertIn("4/5", c.said)
        self.assertEqual(out.joins, ())

    def test_not_before_five_minutes(self):
        out = pug_plan(guild_four(), [old_ask(minutes=3)], four_yeses())
        self.assertEqual(out.calls, ())

    def test_not_while_a_damage_seat_is_still_open(self):
        out = pug_plan(guild_four(), [old_ask()], four_yeses()[:2])
        self.assertEqual(out.calls, ())

    def test_short_both_the_call_asks_for_both_tank_first(self):
        # The asker and two damage yeses fill the damage seats; no tank said yes.
        out = pug_plan(guild_four(), [old_ask()], four_yeses()[1:])
        self.assertEqual(out.calls[0].seats, ("tank", "healer"))
        self.assertIn("3/5", out.calls[0].said)
        self.assertIn("tank and healer", out.calls[0].said)

    def test_a_full_group_calls_for_nobody(self):
        crowd = guild_four() + [mate("Healy", 20, PRIEST, talent_spells=HOLY)]
        answers = four_yeses() + [yes(2, 7, "Healy", "healer")]
        out = pug_plan(crowd, [old_ask()], answers)
        self.assertEqual(out.calls, ())

    def test_a_healer_who_answered_this_pass_cancels_the_call(self):
        crowd = guild_four() + [mate("Healy", 20, PRIEST, talent_spells=HOLY)]
        social = gs.Pass(replies=(gs.Reply(7, "Healy", "healer", "need", "I'll heal"),))
        out = pug_plan(crowd, [old_ask()], four_yeses(), social=social)
        self.assertEqual(out.calls, ())

    def test_an_ask_the_social_pass_closes_is_left_alone(self):
        social = gs.Pass(expire=((7, "Auren", "Never mind"),))
        out = pug_plan(guild_four(), [old_ask()], four_yeses(), social=social)
        self.assertEqual(out.calls, ())

    def test_one_call_per_ask(self):
        out = pug_plan(
            guild_four(),
            [old_ask()],
            four_yeses(),
            calls={7: call(minutes_ago=0.5)},
            pugs=[pug("Mercy")],
        )
        self.assertEqual(out.calls, ())
        self.assertEqual(out.joins, ())  # a beat before anyone answers

    def test_watching_reads_pugs_only_for_asks_that_may_want_one(self):
        young = ask(8, "Bree", created_at=NOW - datetime.timedelta(minutes=1))
        held = ask(9, "Cole", state="filled", created_at=NOW)
        answers = [yes(20, 9, "Mercy", "healer", stance="pug")]
        watched = gp.watching([old_ask(), young, held], {}, answers, NOW)
        self.assertEqual([a.id for a in watched], [7, 9])
        self.assertEqual(gp.levels_to_read([young], DOORS_BY_KEY)[1], DEADMINES.ceiling)
        self.assertIsNone(gp.levels_to_read([], DOORS_BY_KEY))


class TheCallRow(unittest.TestCase):
    def test_a_call_read_back_names_its_asker_and_seats(self):
        c = gp.call_from_row(
            {"ask_id": 7, "asker": "Auren", "seats": "tank,healer", "said": "LF"}
        )
        self.assertEqual((c.ask_id, c.asker, c.seats), (7, "Auren", ("tank", "healer")))
        self.assertIn("c.asker", gp.CALLS_SQL)


class WhoAnswers(unittest.TestCase):
    def joins(self, pugs, **kw):
        return pug_plan(
            guild_four(),
            [old_ask()],
            four_yeses(),
            calls={7: call()},
            pugs=pugs,
            **kw,
        ).joins

    def test_a_free_holy_priest_of_the_side_answers_for_the_seat(self):
        joins = self.joins([pug("Mercy")])
        self.assertEqual(len(joins), 1)
        j = joins[0]
        self.assertEqual(
            (j.ask_id, j.member, j.role, j.asker), (7, "Mercy", "healer", "Auren")
        )
        self.assertIn("Deadmines", j.said)
        self.assertIn("Mercy", j.told_guild)
        self.assertIn("LFG", j.told_guild)

    def test_who_does_not_qualify(self):
        cases = {
            "the other side": pug("Grom", race=ORC),
            "plays damage": pug("Dark", talent_spells=SHADOW),
            "no talents spent": pug("Fresh", talent_spells=None),
            "grouped": pug("Party", group_leader=1),
            "in combat": pug("Busy", in_combat=1),
            "dead": pug("Ghost", health=1, has_corpse=1),
            "outside the band": pug("Old", level=DEADMINES.ceiling + 1),
            "far from the asker's level": pug("High", level=DEADMINES.ceiling),
            "another continent": pug("Away", map_id=1),
            "too far to walk": pug("Far", at=(-9000.0, 300.0)),
            "a guildmate": pug("Mate", guild="Cave"),
            "unarmored": pug("Bare", worn_slots=1),
        }
        for why, who in cases.items():
            with self.subTest(why):
                self.assertEqual(self.joins([who]), ())

    def test_a_family_member_or_a_member_in_a_run_does_not(self):
        self.assertEqual(self.joins([pug("Mercy")], family={"Mercy"}), ())
        self.assertEqual(self.joins([pug("Mercy")], busy={"Mercy"}), ())

    def test_the_nearest_level_wins_among_equals(self):
        joins = self.joins([pug("Aaa", level=23), pug("Zed", level=20)])
        self.assertEqual(joins[0].member, "Zed")

    def test_the_closer_one_wins(self):
        joins = self.joins([pug("Aaa", at=(-10200.0, 1200.0)), pug("Zed")])
        self.assertEqual(joins[0].member, "Zed")

    def test_a_pug_who_already_said_yes_is_not_asked_again(self):
        mates = guild_four() + [pug("Mercy")]
        answers = four_yeses() + [yes(9, 7, "Mercy", "healer", stance="pug")]
        out = pug_plan(
            mates, [old_ask()], answers, calls={7: call()}, pugs=[pug("Mercy")]
        )
        self.assertEqual(out.joins, ())


class TheRunFormsWithThePug(unittest.TestCase):
    def test_the_pug_is_seated_named_and_counted(self):
        mates = guild_four() + [pug("Mercy")]
        answers = four_yeses() + [yes(9, 7, "Mercy", "healer", stance="pug")]
        out = plan(mates, asks=[old_ask()], answers=answers)
        form = out.form
        self.assertIsNotNone(form)
        self.assertEqual(form.composition.healer.name, "Mercy")
        self.assertEqual(form.composition.tank.name, "Tanky")
        self.assertEqual(form.pugs, ("Mercy",))
        self.assertTrue(form.key.endswith("+1pug"))
        self.assertEqual(form.speaker, "Tanky")
        self.assertEqual(
            form.composition.command("deadmines") + gp.pug_tail(form.pugs),
            "finder-run deadmines Mercy Auren Zappy Locky pug Mercy",
        )

    def test_a_pug_tank_leads_and_the_asker_says_so_in_guild_chat(self):
        mates = [
            mate("Auren", 20, ROGUE),
            mate("Healy", 20, PRIEST, talent_spells=HOLY),
            mate("Zappy", 19, MAGE),
            mate("Locky", 20, WARLOCK),
            pug("Bulwark", 21, WARRIOR, talent_spells=PROTECTION, has_shield=1),
        ]
        answers = [
            yes(2, 7, "Healy", "healer"),
            yes(3, 7, "Zappy", "dps"),
            yes(4, 7, "Locky", "dps"),
            yes(9, 7, "Bulwark", "tank", stance="pug"),
        ]
        form = plan(mates, asks=[old_ask()], answers=answers).form
        self.assertEqual(form.composition.tank.name, "Bulwark")
        self.assertEqual(form.speaker, "Auren")
        self.assertNotIn("I'll lead", form.said)

    def test_a_pug_no_longer_free_is_withdrawn(self):
        answers = four_yeses() + [yes(9, 7, "Mercy", "healer", stance="pug")]
        out = plan(guild_four(), asks=[old_ask()], answers=answers)
        self.assertIsNone(out.form)
        self.assertEqual(out.withdraw, (9,))

    def test_without_a_pug_nothing_changes(self):
        out = plan(guild_four(), asks=[old_ask()], answers=four_yeses())
        self.assertIsNone(out.form)

    def test_pug_mates_holds_an_answered_pug_who_is_busy(self):
        rows = [
            row("Mercy", 20, PRIEST, guild_name="", talent_spells=HOLY, in_combat=1),
            row("Other", 20, PRIEST, guild_name="", talent_spells=HOLY),
        ]
        answers = [yes(9, 7, "Mercy", "healer", stance="pug")]
        everyone, answered, held = gp.pug_mates(rows, answers, set(), set())
        self.assertEqual([m.name for m in everyone], ["Mercy", "Other"])
        self.assertEqual([m.name for m in answered], ["Mercy"])
        self.assertEqual(held, {"Mercy": "in combat"})


def pug_facts(call_minutes=2):
    out = facts()
    out["rows"] = [r for r in out["rows"] if r["name"] != "Healy"]
    out["asks"] = [old_ask()]
    out["answers"] = four_yeses()
    out["pug_calls"] = {7: call(minutes_ago=call_minutes)}
    return out


class TheBridgePass(unittest.TestCase):
    def run_once(self, environ, the_facts, pug_rows):
        written, pugs, read = [], [], []

        def fetch(span, bounds):
            read.append(span)
            return pug_rows

        with (
            mock.patch.dict(os.environ, environ),
            mock.patch.multiple(
                bridge,
                _guild_run_gate=lambda: {"uptime": 99999, "latest": []},
                _guild_runs_in_flight=lambda: 0,
                _fetch_guild_social_facts=lambda bounds: the_facts,
                _fetch_guild_pugs=fetch,
                _write_guild_social=lambda social: written.append(social) or 0,
                _write_guild_pugs=pugs.append,
                _guild_social_names=lambda: set(),
            ),
        ):
            asyncio.run(bridge.Bridge._guild_social_once(_Self()))
        return written, pugs, read

    def test_a_called_ask_draws_a_pug(self):
        rows = [row("Mercy", 20, PRIEST, guild_name="", talent_spells=HOLY)]
        _w, pugs, read = self.run_once({}, pug_facts(), rows)
        self.assertEqual(len(read), 1)
        self.assertEqual([j.member for j in pugs[0].joins], ["Mercy"])

    def test_a_pug_who_said_yes_is_seated_through_the_finder_row(self):
        the_facts = pug_facts()
        the_facts["answers"] = four_yeses() + [
            yes(9, 7, "Mercy", "healer", stance="pug")
        ]
        rows = [row("Mercy", 20, PRIEST, guild_name="", talent_spells=HOLY)]
        written, _p, _r = self.run_once({}, the_facts, rows)
        self.assertEqual(written[0].form.pugs, ("Mercy",))

    def test_off_reads_and_writes_nothing_of_pugs(self):
        rows = [row("Mercy", 20, PRIEST, guild_name="", talent_spells=HOLY)]
        written, pugs, read = self.run_once({"GUILD_PUGS": "off"}, pug_facts(), rows)
        self.assertEqual((pugs, read), ([], []))
        self.assertIsNone(written[0].form)


class TheBridgeWrites(unittest.TestCase):
    def test_the_call_the_answer_and_the_lines_from_their_speakers(self):
        sql, said = [], []
        pp = gp.PugPass(
            calls=(gp.Call(7, "Auren", ("healer",), "LF healer for Deadmines, 4/5"),),
            joins=(
                gp.Join(
                    8, "Mercy", "healer", "I can heal, inv", "Bree", "Got a healer"
                ),
            ),
        )
        with mock.patch.multiple(
            bridge,
            _connect=lambda: _Conn(sql),
            _insert_speak=lambda cmd: said.append(
                (cmd.target_name, cmd.channel, cmd.text, cmd.whisper_to)
            ),
        ):
            bridge._write_guild_pugs(pp)
        self.assertEqual(
            sql[0],
            (
                gp.INSERT_CALL_SQL,
                (7, "Auren", "healer", "lfg", "LF healer for Deadmines, 4/5"),
            ),
        )
        self.assertEqual(
            sql[1],
            (gs.INSERT_ANSWER_SQL, (8, "Mercy", "healer", "pug", "I can heal, inv")),
        )
        self.assertEqual(
            said,
            [
                ("Auren", "lfg", "LF healer for Deadmines, 4/5", ""),
                ("Mercy", "whisper", "I can heal, inv", "Bree"),
                ("Bree", "guild", "Got a healer", ""),
            ],
        )

    def test_the_run_row_records_the_pug_and_the_finder_row_names_it(self):
        mates = guild_four() + [pug("Mercy")]
        answers = four_yeses() + [yes(9, 7, "Mercy", "healer", stance="pug")]
        form = plan(mates, asks=[old_ask()], answers=answers).form
        sql = []
        with mock.patch.object(bridge, "_connect", lambda: _Conn(sql)):
            run_id = bridge._start_social_run(form)
        self.assertIn((gp.RUN_PUGS_SQL, ("Mercy", run_id)), sql)
        finder = next(a for s, a in sql if "INSERT INTO overseer_command" in s)
        self.assertEqual(finder[0], "Tanky")
        self.assertTrue(finder[1].endswith(" pug Mercy"))

    def test_a_run_without_a_pug_is_written_as_before(self):
        form = plan(
            guild_four() + [mate("Healy", 20, PRIEST, talent_spells=HOLY)],
            asks=[old_ask()],
            answers=four_yeses() + [yes(2, 7, "Healy", "healer")],
        ).form
        sql = []
        with mock.patch.object(bridge, "_connect", lambda: _Conn(sql)):
            bridge._start_social_run(form)
        self.assertNotIn(gp.RUN_PUGS_SQL, [s for s, _a in sql])
        finder = next(a for s, a in sql if "INSERT INTO overseer_command" in s)
        self.assertNotIn(" pug ", finder[1])

    def test_the_pug_read_takes_random_bots_outside_the_guilds(self):
        sql = bridge._GUILD_PUGS_SQL
        self.assertIn("LEFT JOIN guild g", sql)
        self.assertIn("g.name IS NULL OR g.name NOT IN ({holes})", sql)
        self.assertIn("s.is_bot = 1", sql)
        self.assertIn("AS talent_spells", sql)
        self.assertIn("AS has_shield", sql)


if __name__ == "__main__":
    unittest.main()
