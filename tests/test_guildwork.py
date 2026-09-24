"""The maintenance members' job: guild dues by post (#234).

Pure unit tests against guildwork.py, plus source checks on the bridge pass,
the lineup endpoint and the page. The fixtures are the dev realm as measured
on 2026-09-23: two guilds of 71, ten maintenance members each, random
playerbots holding 296 to 3,254 gold, and a guild master on the family.
"""

import ast
import json
import pathlib
import unittest

import guildroute
import guildwork
import raidlineup

HERE = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")
SERVER = (HERE / "map_server.py").read_text(encoding="utf-8")
PAGE = (HERE / "index.html").read_text(encoding="utf-8")
DOCKERFILE = (HERE / "Dockerfile").read_text(encoding="utf-8")

GOLD = guildwork.COPPER_PER_GOLD


def walker(name, **over):
    base = dict(
        name=name,
        map_id=0,
        in_combat=False,
        unwalkable="",
        cohort="",
        yards=328.0,
        aim="at:0:-8826.4,630.1,94.1",
        by_row=True,
    )
    base.update(over)
    return guildroute.Walker(**base)


def member(name, gold=1704, online=True, guild="Cave"):
    return guildwork.Member(name=name, guild=guild, money=gold * GOLD, online=online)


class TheDuesAmount(unittest.TestCase):
    def test_a_purse_at_or_under_the_float_posts_nothing(self):
        self.assertEqual(guildwork.dues_for(guildwork.FLOAT_COPPER), 0)
        self.assertEqual(guildwork.dues_for(0), 0)

    def test_a_quarter_of_what_is_above_the_float(self):
        self.assertEqual(guildwork.dues_for(296 * GOLD), 49 * GOLD)

    def test_one_letter_never_carries_more_than_the_cap(self):
        self.assertEqual(guildwork.dues_for(3254 * GOLD), guildwork.LETTER_CAP_COPPER)

    def test_under_a_gold_is_not_worth_the_walk(self):
        self.assertEqual(guildwork.dues_for(guildwork.FLOAT_COPPER + 3 * GOLD), 0)

    def test_an_unreadable_purse_posts_nothing(self):
        for money in (None, "", "lots", -5):
            self.assertEqual(guildwork.dues_for(money), 0, money)


class TheLetter(unittest.TestCase):
    def setUp(self):
        self.run = guildwork.DuesRun(
            holder="Goraraa",
            taker="Grug",
            guild="Cave",
            copper=250 * GOLD,
            aim="at:0:1,2,3",
            yards=328.4,
        )

    def test_it_is_the_mail_verbs_own_grammar(self):
        self.assertEqual(self.run.command, "send money:2500000 subject:Guild dues")
        self.assertEqual(self.run.walk_command, "walk-to-mailbox max:600")

    def test_its_sources_are_not_the_gear_routes(self):
        """The gear route counts its daily walks by `guildwalk:` and its
        letters by `guildroute:`; a dues row counted there would spend them."""
        for source in (self.run.source, self.run.walk_source):
            self.assertFalse(source.startswith(guildroute.SOURCE + ":"), source)
            self.assertFalse(source.startswith("guildwalk:"), source)
        self.assertTrue(self.run.source.startswith(guildwork.SOURCE + ":"))
        self.assertFalse(self.run.walk_source.startswith(guildwork.SOURCE + ":"))

    def test_the_subject_fits_the_client(self):
        self.assertLessEqual(len(guildwork.SUBJECT), 64)

    def test_the_log_line_names_who_where_how_much_and_to_whom(self):
        self.assertEqual(
            self.run.said,
            "Goraraa (Cave) walks 328 yards to the mailbox at at:0:1,2,3 "
            "to post 250g of dues to Grug",
        )


class TheFarWalk(unittest.TestCase):
    """quadseven/mod-overseer#633: dues walks may go far, and the nearest
    member is asked first."""

    masters = {"Cave": "Grug"}

    def test_the_far_cap_is_on_the_walk_row(self):
        plan = guildwork.plan_dues(
            [member("Velalenn")],
            self.masters,
            {"Velalenn": walker("Velalenn", yards=1953.0)},
            (),
            (),
            max_yards=guildroute.FAR_WALK_YARDS,
            eligible={"Velalenn"},
        )
        self.assertEqual(len(plan.runs), 1)
        self.assertEqual(plan.runs[0].walk_command, "walk-to-mailbox max:20000")

    def test_at_the_near_cap_1953_yards_still_waits(self):
        plan = guildwork.plan_dues(
            [member("Velalenn")],
            self.masters,
            {"Velalenn": walker("Velalenn", yards=1953.0)},
            (),
            (),
            eligible={"Velalenn"},
        )
        self.assertEqual(plan.runs, ())
        self.assertIn("1953 yards away, past the 600", plan.notes[0])

    def test_the_nearest_members_take_the_guilds_two_walks(self):
        crew = [member("Far"), member("Near"), member("Mid"), member("Unknown")]
        walkers = {
            "Far": walker("Far", yards=1953.0),
            "Near": walker("Near", yards=44.0),
            "Mid": walker("Mid", yards=516.0),
            "Unknown": walker("Unknown", yards=None),
        }
        plan = guildwork.plan_dues(
            crew, self.masters, walkers, (), (), max_yards=guildroute.FAR_WALK_YARDS,
            eligible={m.name for m in crew},
        )
        self.assertEqual([r.holder for r in plan.runs], ["Near", "Mid"])


class ThePlan(unittest.TestCase):
    masters = {"Cave": "Grug", "Bonkers": "Zug"}

    def plan(self, members, walkers=None, posted=(), busy=(), **kw):
        if walkers is None:
            walkers = {m.name: walker(m.name) for m in members}
        kw.setdefault("eligible", {m.name for m in members})
        return guildwork.plan_dues(members, self.masters, walkers, posted, busy, **kw)

    def test_a_due_member_near_a_mailbox_walks(self):
        plan = self.plan([member("Goraraa", 3254)])
        self.assertEqual(len(plan.runs), 1)
        run = plan.runs[0]
        self.assertEqual(
            (run.holder, run.taker, run.copper), ("Goraraa", "Grug", 250 * GOLD)
        )

    def test_each_guild_posts_to_its_own_master(self):
        plan = self.plan([member("Goraraa"), member("Quelmin", guild="Bonkers")])
        self.assertEqual(
            {r.holder: r.taker for r in plan.runs},
            {"Goraraa": "Grug", "Quelmin": "Zug"},
        )

    def test_a_member_who_posted_today_is_left_alone_quietly(self):
        plan = self.plan([member("Goraraa")], posted={"Goraraa"})
        self.assertEqual(plan.runs, ())
        self.assertEqual(plan.notes, ())

    def test_every_other_skip_says_why(self):
        members = [
            member("Becalin", online=False),
            member("Poor", gold=100),
            member("Busy"),
            member("Fighting"),
            member("Far"),
            member("Nowhere"),
        ]
        walkers = {
            "Busy": walker("Busy"),
            "Fighting": walker("Fighting", in_combat=True),
            "Far": walker("Far", yards=716.0),
        }
        plan = self.plan(members, walkers=walkers, busy={"Busy"})
        self.assertEqual(plan.runs, ())
        said = " | ".join(plan.notes)
        self.assertIn("Becalin is offline", said)
        self.assertIn("Poor carries 100g, not enough above the 100g float", said)
        self.assertIn("Busy is already walking to a mailbox", said)
        self.assertIn("Fighting waits: Fighting is in combat", said)
        self.assertIn("716 yards away, past the 600", said)
        self.assertIn("Nowhere waits: Nowhere is not in the world", said)
        self.assertEqual(len(plan.notes), 6)

    def test_a_worldserver_that_cannot_walk_a_bot_is_a_wait(self):
        plan = self.plan(
            [member("Goraraa")],
            walkers={
                "Goraraa": walker(
                    "Goraraa", by_row=False, unwalkable=guildroute.OFF_ROSTER
                )
            },
        )
        self.assertEqual(plan.runs, ())
        self.assertIn("cannot walk one to a mailbox yet", plan.notes[0])

    def test_a_member_in_outland_or_northrend_is_never_walked(self):
        # Measured on dev: a Bonkers member was walked 341 yards to a mailbox
        # on map 530. The classic ruleset leaves such a member where it is.
        plan = self.plan(
            [member("Zora", guild="Bonkers"), member("Frost", guild="Bonkers")],
            walkers={
                "Zora": walker("Zora", map_id=530, aim="at:530:-248.1,1017.4,54.3"),
                "Frost": walker("Frost", map_id=571, aim="at:571:5804.1,624.7,647.8"),
            },
        )
        self.assertEqual(plan.runs, ())
        said = " | ".join(plan.notes)
        self.assertIn("Zora stands in Outland, outside the classic world", said)
        self.assertIn("Frost stands in Northrend, outside the classic world", said)

    def test_a_roster_leader_is_never_walked_by_the_row(self):
        plan = self.plan(
            [member("Grog")],
            walkers={"Grog": walker("Grog", by_row=False, cohort="grug")},
        )
        self.assertEqual(plan.runs, ())
        self.assertIn("cannot be walked by the mailbox walk row", plan.notes[0])

    def test_no_more_than_two_walks_per_guild_per_pass(self):
        cave = [member("A%d" % i) for i in range(5)]
        bonkers = [member("B%d" % i, guild="Bonkers") for i in range(5)]
        plan = self.plan(cave + bonkers)
        self.assertEqual([r.holder for r in plan.runs], ["A0", "A1", "B0", "B1"])
        self.assertEqual(
            sum("2 dues walks per guild per pass" in n for n in plan.notes), 6
        )

    def test_the_guild_master_and_a_masterless_guild_post_nothing(self):
        plan = self.plan([member("Grug"), member("Orphan", guild="Nobody")])
        self.assertEqual(plan.runs, ())
        self.assertIn("Grug is the guild master and posts no dues", plan.notes)
        self.assertIn("Orphan: Nobody has no guild master to post to", plan.notes)


class WhoIsOnMaintenance(unittest.TestCase):
    def rows(self):
        rows = []
        for i in range(71):
            rows.append(
                dict(
                    guild_name="Cave",
                    name="M%02d" % i,
                    class_id=(1, 5, 8, 4, 3)[i % 5],
                    level=60 - (i % 3),
                    money=(500 + i) * GOLD,
                    online=1,
                    master="M00",
                )
            )
        return rows

    def test_it_is_the_lineup_pages_own_pick(self):
        rows = self.rows()
        members, masters = guildwork.maintenance_from_rows(rows, ["M00", "M01"])
        lineup = raidlineup.build_lineup(
            [
                dict(name=r["name"], class_id=r["class_id"], level=r["level"])
                for r in rows
            ],
            guaranteed=["M00", "M01"],
        )
        self.assertEqual(
            [m.name for m in members], [m["name"] for m in lineup["maintenance"]]
        )
        self.assertEqual(len(members), raidlineup.MAINTENANCE)
        self.assertEqual(masters, {"Cave": "M00"})
        picked = {r["name"]: r for r in rows}
        for m in members:
            self.assertEqual(m.money, picked[m.name]["money"])
            self.assertTrue(m.online)


def letter(name, status="delivered", money=2500000, outcome="sent", detail=""):
    return dict(
        target_name=name,
        command="send money:%d subject:Guild dues" % money,
        status=status,
        detail=detail,
        result=json.dumps({"outcome": outcome, "mail": {"money": money}}),
    )


class WhatWasPosted(unittest.TestCase):
    def test_only_a_letter_the_world_sent_counts(self):
        got = guildwork.contributions(
            [
                letter("Goraraa"),
                letter("Goraraa", money=490000),
                letter(
                    "Goraraa",
                    status="error",
                    outcome="refused",
                    detail="mailbox not in range",
                ),
                letter("Quelmin", status="pending", outcome=""),
            ]
        )
        self.assertEqual(got["Goraraa"]["letters"], 2)
        self.assertEqual(got["Goraraa"]["copper"], 2990000)
        self.assertEqual(got["Goraraa"]["last_refusal"], "mailbox not in range")
        self.assertEqual(got["Quelmin"]["letters"], 0)

    def test_a_later_letter_clears_an_old_refusal(self):
        got = guildwork.contributions(
            [
                letter(
                    "Goraraa",
                    status="error",
                    outcome="refused",
                    detail="character is in combat",
                ),
                letter("Goraraa"),
            ]
        )
        self.assertEqual(got["Goraraa"]["last_refusal"], "")

    def test_the_amount_falls_back_to_the_command(self):
        row = letter("Goraraa")
        row["result"] = json.dumps({"outcome": "sent"})
        self.assertEqual(guildwork.contributions([row])["Goraraa"]["copper"], 2500000)

    def test_the_page_says_the_job_and_the_total(self):
        lineup = {"maintenance": [{"name": "Goraraa"}, {"name": "Baleron"}]}
        guildwork.attach_work(
            lineup, "Grug", guildwork.contributions([letter("Goraraa")])
        )
        first, second = lineup["maintenance"]
        self.assertEqual(first["job"], "guild dues")
        self.assertEqual(
            first["work"],
            "guild dues: posts a quarter of its gold above 100g to Grug once a day"
            " - posted 250g in 1 letter",
        )
        self.assertTrue(second["work"].endswith("- nothing posted yet"))
        self.assertEqual(lineup["dues"]["copper"], 2500000)
        self.assertEqual(
            lineup["dues"]["said"], "maintenance dues posted to Grug: 250g in 1 letter"
        )


class TheBridgePass(unittest.TestCase):
    tree = ast.parse(BRIDGE)

    def body(self, name):
        fn = next(
            n
            for n in ast.walk(self.tree)
            if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == name
        )
        return ast.get_source_segment(BRIDGE, fn)

    def test_the_loop_is_registered_in_both_lists(self):
        """setup_hook and the headless driver; wow-dev runs headless."""
        self.assertEqual(BRIDGE.count("self._guild_dues_loop,"), 2)

    def test_the_pass_asks_the_pure_planner_for_the_pages_lineup(self):
        body = self.body("_guild_dues_once")
        self.assertIn("guildwork.maintenance_from_rows", body)
        self.assertIn("guildwork.plan_dues", body)
        self.assertIn("_dues_recent_holders", body)

    def test_it_writes_mail_rows_and_nothing_else(self):
        """Never a give across a continent, never a GM command."""
        insert = self.body("_insert_dues_row")
        self.assertIn("VALUES (%s, %s, 'mail', %s, %s)", insert)
        for name in ("_guild_dues_once", "_follow_dues_walk"):
            body = self.body(name)
            self.assertNotIn("_insert_gm", body)
            self.assertNotIn("_insert_give", body)
            self.assertNotIn("'give'", body)

    def test_the_letter_is_written_only_on_arrival(self):
        body = self.body("_follow_dues_walk")
        arrived = body.index("guildroute.ARRIVED")
        self.assertLess(arrived, body.index("run.command"))

    def test_both_walk_passes_read_a_walk_row_the_same_way(self):
        self.assertIn("_await_mail_walk", self.body("_follow_mail_walk"))
        # Through the guild passes' shared follow since #633, which is the one
        # that writes a walk a fight ended once more.
        self.assertIn("_follow_guild_walk", self.body("_follow_dues_walk"))
        self.assertIn("_await_mail_walk", self.body("_follow_guild_walk"))

    def test_the_dues_pass_asks_the_far_cap_and_follows_it(self):
        """quadseven/mod-overseer#633: the pass asks the far cap while the
        worldserver carries it, follows the row for the far ceiling, and walks a
        walk a fight ended once more."""
        self.assertIn("max_yards=self._guild_walk_cap()", self.body("_guild_dues_once"))
        follow = self.body("_follow_dues_walk")
        self.assertIn("self._follow_guild_walk(", follow)
        self.assertIn("run.cap", follow)
        self.assertLess(
            follow.index("_follow_guild_walk("), follow.index("guildroute.ARRIVED")
        )
        await_walk = self.body("_await_mail_walk")
        self.assertIn("guildroute.follow_seconds(cap)", await_walk)
        self.assertIn("guildroute.FAR_UNSUPPORTED", await_walk)
        self.assertIn("guildroute.GUILD_STEP_SECONDS", self.body("_guild_dues_once"))

    def test_the_recent_read_uses_the_modules_own_prefixes(self):
        body = self.body("_dues_recent_holders")
        self.assertIn("guildwork.SOURCE", body)
        self.assertIn("guildwork.WALK_SOURCE", body)


class ThePage(unittest.TestCase):
    def test_the_lineup_endpoint_attaches_the_work(self):
        lineup = SERVER[SERVER.index("    def _lineup(") :]
        lineup = lineup[: lineup.index("    def _raidgoals(")]
        self.assertIn("guildwork.attach_work(", lineup)
        self.assertIn("guildwork.contributions(", lineup)

    def test_the_dues_read_rides_the_kind_index(self):
        self.assertIn("WHERE kind = 'mail' AND source LIKE %s", SERVER)

    def test_the_page_draws_the_work_line_and_the_total(self):
        self.assertIn("if (m.work) {", PAGE)
        self.assertIn('w.className = "ln-work";', PAGE)
        self.assertIn("g.dues ? g.dues.said", PAGE)
        self.assertIn(".ln-work {", PAGE)

    def test_the_module_ships_in_the_image(self):
        self.assertIn("guildwork.py", DOCKERFILE)


if __name__ == "__main__":
    unittest.main()
