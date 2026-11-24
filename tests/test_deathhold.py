"""The flag that holds a death-looping member off its own wandering (#2152).

The pure plan (deathhold.plan) and the wiring of its writer into the guild
jobs pass. The module's half reads exactly KIND and the value's map and zone.
"""

import pathlib
import sys
import unittest

from _stub_modules import PYMYSQL, stub_modules

with stub_modules(pymysql=PYMYSQL):
    HERE = pathlib.Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(HERE))

    import deathhold
    import deathloop

BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")
NOW = 1_800_000_000.0
NAME = "Member"


def function_source(name):
    start = BRIDGE.index("def %s(" % name)
    end = BRIDGE.index("\ndef ", start + 1)
    return BRIDGE[start:end]


def loop(zone=1377, map_id=1, level=60, run=0):
    return deathloop.Loop(
        name=NAME,
        zone=zone,
        map_id=map_id,
        deaths=14,
        killer="Twilight Geolord",
        level=level,
        first_age=3600,
        last_age=60,
        slow=True,
        run=run,
    )


class APlanForOnePass(unittest.TestCase):
    def test_a_new_loop_is_flagged_from_now(self):
        out = deathhold.plan({NAME: loop()}, {NAME: 60}, {}, NOW)
        self.assertEqual(1, len(out.writes))
        w = out.writes[0]
        self.assertEqual(NAME, w.name)
        self.assertEqual({"map": 1, "zone": 1377, "level": 60}, w.value)
        self.assertEqual(NOW, w.since)
        self.assertEqual(
            NOW + deathhold.HOLD_SECONDS + deathhold.REST_SECONDS, w.expires
        )
        self.assertEqual((), out.drops)

    def test_a_standing_row_for_the_same_zone_is_never_rewritten(self):
        memos = {NAME: ({"map": 1, "zone": 1377, "level": 60}, NOW - 7200)}
        out = deathhold.plan({NAME: loop()}, {NAME: 60}, memos, NOW)
        self.assertEqual(
            (), out.writes, "a rewrite would move `since` and renew the hold"
        )
        self.assertEqual((), out.drops)

    def test_a_standing_row_outlives_the_loop_clearing(self):
        memos = {NAME: ({"map": 1, "zone": 1377, "level": 60}, NOW - 7200)}
        out = deathhold.plan({}, {NAME: 60}, memos, NOW)
        self.assertEqual((), out.writes)
        self.assertEqual((), out.drops, "the rest after the hold is the row's own")

    def test_a_loop_in_another_zone_replaces_the_row(self):
        memos = {NAME: ({"map": 1, "zone": 440, "level": 60}, NOW - 7200)}
        out = deathhold.plan({NAME: loop()}, {NAME: 60}, memos, NOW)
        self.assertEqual([1377], [w.value["zone"] for w in out.writes])
        self.assertEqual(NOW, out.writes[0].since)
        self.assertEqual((), out.drops)

    def test_a_level_gained_drops_the_row(self):
        memos = {NAME: ({"map": 0, "zone": 44, "level": 24}, NOW - 600)}
        out = deathhold.plan({}, {NAME: 25}, memos, NOW)
        self.assertEqual((), out.writes)
        self.assertEqual((NAME,), out.drops)

    def test_a_roster_member_is_never_flagged_and_its_row_is_dropped(self):
        out = deathhold.plan({NAME: loop()}, {NAME: 60}, {}, NOW, roster={NAME})
        self.assertEqual((), out.writes)
        memos = {NAME: ({"map": 1, "zone": 1377, "level": 60}, NOW - 60)}
        out = deathhold.plan({NAME: loop()}, {NAME: 60}, memos, NOW, roster={NAME})
        self.assertEqual((NAME,), out.drops)

    def test_a_member_this_pass_did_not_read_is_left_alone(self):
        memos = {"Other": ({"map": 1, "zone": 1377, "level": 60}, NOW - 60)}
        out = deathhold.plan({}, {NAME: 60}, memos, NOW)
        self.assertEqual((), out.writes)
        self.assertEqual((), out.drops)

    def test_a_run_wipe_is_not_flagged(self):
        out = deathhold.plan({NAME: loop(run=6)}, {NAME: 60}, {}, NOW)
        self.assertEqual((), out.writes)

    def test_zone_zero_is_not_flagged(self):
        out = deathhold.plan({NAME: loop(zone=0)}, {NAME: 60}, {}, NOW)
        self.assertEqual((), out.writes)

    def test_no_loops_writes_nothing(self):
        self.assertEqual(deathhold.Plan(), deathhold.plan(None, {NAME: 60}, None, NOW))


class TheBound(unittest.TestCase):
    def test_the_hold_is_a_few_hours(self):
        self.assertGreaterEqual(deathhold.HOLD_SECONDS, 2 * 3600)
        self.assertLessEqual(deathhold.HOLD_SECONDS, 6 * 3600)

    def test_the_row_expires(self):
        self.assertLess(deathhold.HOLD_SECONDS + deathhold.REST_SECONDS, 24 * 3600)

    def test_the_kind_is_the_modules(self):
        self.assertEqual("death_loop_zone", deathhold.KIND)
        self.assertLessEqual(
            len(deathhold.KIND), 32, "overseer_bridge_memo.kind is VARCHAR(32)"
        )


def deaths(zone, n, level=50, newest=60):
    return [
        {
            "name": NAME,
            "zone": zone,
            "map": 1,
            "level": level,
            "killer": "Boar",
            "age": newest + 300 * i,
        }
        for i in range(n)
    ]


def forming_plan(rows, memos=None, roster=()):
    found = deathhold.flagged(
        deathloop.loops(rows, {NAME: 50}), deathloop.forming(rows, {NAME: 50})
    )
    return deathhold.plan(found, {NAME: 50}, memos, NOW, roster=roster)


class TheFormingLoop(unittest.TestCase):
    def test_three_deaths_write_two_do_not(self):
        out = forming_plan(deaths(14, 3))
        self.assertEqual(1, len(out.writes))
        self.assertEqual(14, out.writes[0].value["zone"])
        self.assertEqual((), forming_plan(deaths(14, 2)).writes)

    def test_the_escape_rule_still_needs_five(self):
        self.assertEqual({}, deathloop.loops(deaths(14, 4), {NAME: 50}))

    def test_a_roster_member_is_never_flagged(self):
        self.assertEqual((), forming_plan(deaths(14, 3), roster={NAME}).writes)

    def test_a_second_zone_is_flagged_and_the_first_row_kept(self):
        rows = deaths(14, 3, newest=1200) + deaths(15, 3, newest=60)
        memos = {NAME: ({"map": 1, "zone": 14, "level": 50}, NOW - 1000)}
        out = forming_plan(rows, memos)
        self.assertEqual(1, len(out.writes))
        self.assertEqual(15, out.writes[0].value["zone"])
        self.assertEqual(NOW, out.writes[0].since)
        # The same zone again rewrites nothing.
        same = {NAME: ({"map": 1, "zone": 15, "level": 50}, NOW - 100)}
        self.assertEqual((), forming_plan(rows, same).writes)


class TheWiring(unittest.TestCase):
    def test_the_guild_jobs_pass_writes_the_flags(self):
        start = BRIDGE.index("async def _start_guild_job_pass(")
        body = BRIDGE[start : BRIDGE.index("\n    def ", start)]
        self.assertIn("asyncio.to_thread(_flag_death_loop_holds, members, facts)", body)

    def test_the_writer_plans_from_the_judged_loops(self):
        body = function_source("_flag_death_loop_holds")
        self.assertIn("deathhold.plan(", body)
        self.assertIn('facts.get("death_loops")', body)
        self.assertIn("_memo_upsert(deathhold.KIND", body)
        self.assertIn("_memo_delete(deathhold.KIND", body)

    def test_an_unread_memo_store_writes_nothing(self):
        body = function_source("_flag_death_loop_holds")
        self.assertIn("if memos is None:\n        return", body)
        self.assertIn("return None", function_source("_death_hold_memos"))


if __name__ == "__main__":
    unittest.main()
