"""The decree console's guild finder run order.

An order {section: "guildrun", guild, keyword} asks the guild planner (guildrun)
to form one run for that guild now. Every judgement is the planner's own and
lives in decree.plan_order, so the suite holds it with no database and no
browser: the accepted order, the refusals, the rows it writes, and the
OVERSEER_OPERATOR_ACTIONS gate every decree section sits behind.
"""

import json
import os
import unittest
from unittest import mock

from _stub_modules import PYMYSQL, stub_modules

with stub_modules(pymysql=PYMYSQL):
    import decree
    import guildrun
    import map_server

map_server.log.propagate = False

WARRIOR, PRIEST, ROGUE, MAGE, WARLOCK = 1, 5, 4, 8, 9
PROTECTION, HOLY = "12301", "14913"
GUILD = "Cave"
FAMILY_ROSTER = [{"name": "Zugger", "enabled": 1}, {"name": "Grugger", "enabled": 1}]


def member_row(name, level, class_id, guild=GUILD, **kw):
    out = {
        "name": name,
        "level": level,
        "class_id": class_id,
        "map_id": 0,
        "race": 1,
        "in_combat": 0,
        "health": 300,
        "group_leader": 0,
        "guild_name": guild,
        "talent_spells": None,
        "target_tree": "",
    }
    out.update(kw)
    return out


def idle_five(guild=GUILD):
    return [
        member_row("Tanky", 20, WARRIOR, guild, talent_spells=PROTECTION),
        member_row("Healy", 20, PRIEST, guild, talent_spells=HOLY),
        member_row("Stabby", 19, ROGUE, guild),
        member_row("Zappy", 19, MAGE, guild),
        member_row("Locky", 19, WARLOCK, guild),
    ]


def facts(**over):
    out = {
        "guilds": (GUILD, "Bonkers"),
        "guild": GUILD,
        "rows": idle_five(),
        "family": set(),
        "busy": set(),
        "resting": set(),
        "benched": frozenset(),
        "active": {},
        "history": [],
        "finder_floors": {},
        "boss_levels": {},
    }
    out.update(over)
    return out


def ask(**over):
    body = {"section": decree.GUILDRUN, "guild": GUILD, "keyword": "deadmines"}
    body.update(over)
    return body


def plan(body=None, guild_facts=None, roster=None):
    return decree.plan_order(
        body or ask(),
        FAMILY_ROSTER if roster is None else roster,
        guild_facts=facts() if guild_facts is None else guild_facts,
    )


class FakeCursor:
    def __init__(self):
        self.calls = []
        self.lastrowid = 0

    def fetchone(self):
        return None

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        self.lastrowid += 40


class AnAcceptedOrder(unittest.TestCase):
    def test_the_planner_seats_the_idle_five_for_the_named_door(self):
        order = plan()
        self.assertEqual(order.refusal, "")
        self.assertEqual(order.section, decree.GUILDRUN)
        self.assertEqual(order.asked, 1)
        self.assertEqual(order.rows, ())
        decision = order.guild_run
        self.assertEqual(decision.door.keyword, "deadmines")
        self.assertEqual(decision.chosen.tank.name, "Tanky")
        self.assertEqual(decision.chosen.healer.name, "Healy")
        self.assertIn("Cave sends", order.says)
        self.assertIn("Deadmines", order.says)

    def test_the_guild_and_keyword_are_matched_without_regard_to_case(self):
        order = plan(ask(guild=" cave ", keyword=" Deadmines "))
        self.assertEqual(order.refusal, "")

    def test_it_writes_the_run_row_and_the_finder_command_and_links_them(self):
        order = plan()
        cursor = FakeCursor()
        with mock.patch.object(map_server, "_connect") as connect:
            conn = connect.return_value
            conn.cursor.return_value.__enter__.return_value = cursor
            changed = map_server._apply_order(order)
        self.assertEqual(changed, 1)
        run_sql, run_params = cursor.calls[1]
        self.assertIn("INSERT INTO overseer_guild_run", run_sql)
        self.assertEqual(run_params[0], "Cave")
        self.assertEqual(run_params[3], "deadmines")
        self.assertEqual(run_params[4], "Tanky")
        self.assertEqual(run_params[6], "heuristic")
        command_sql, command_params = cursor.calls[2]
        self.assertIn("INSERT INTO overseer_command", command_sql)
        self.assertIn("'guild'", command_sql)
        self.assertEqual(command_params[0], "Tanky")
        self.assertTrue(command_params[1].startswith("finder-run deadmines Healy "))
        self.assertEqual(command_params[2], guildrun.SOURCE)
        link_sql, link_params = cursor.calls[3]
        self.assertIn("UPDATE overseer_guild_run SET command_id", link_sql)
        self.assertEqual(link_params, (120, 80))
        self.assertEqual(len(cursor.calls), 4)

    def test_a_realm_without_the_run_table_reports_nothing_formed(self):
        order = plan()
        err = map_server.pymysql.err.MySQLError(1146, "no table")

        class Dead(FakeCursor):
            def execute(self, sql, params=None):
                raise err

        with mock.patch.object(map_server, "_connect") as connect:
            connect.return_value.cursor.return_value.__enter__.return_value = Dead()
            changed = map_server._apply_order(order)
        self.assertEqual(changed, 0)
        self.assertEqual(
            decree.order_result(order, 0)["note"], decree.ORDER_NOTHING[decree.GUILDRUN]
        )


class ARefusedOrder(unittest.TestCase):
    def refused(self, order, *needles):
        self.assertTrue(order.refusal)
        self.assertIsNone(order.guild_run)
        self.assertEqual(order.asked, 0)
        for needle in needles:
            self.assertIn(needle, order.refusal)

    def test_an_unknown_guild(self):
        self.refused(plan(ask(guild="Nowhere")), "not a guild", "Cave, Bonkers")
        self.refused(plan(ask(guild=7)), "not a guild")

    def test_an_unreadable_finder(self):
        self.refused(plan(guild_facts={}), "could not be read")

    def test_a_missing_or_unknown_keyword(self):
        self.refused(plan(ask(keyword="")), "Say which dungeon")
        self.refused(plan(ask(keyword="no-such-door")), "no-such-door", "deadmines")

    def test_an_active_run_is_never_overridden(self):
        self.refused(plan(guild_facts=facts(active={"Cave": 1})), "already has a run")

    def test_another_guilds_run_does_not_block_this_one(self):
        self.assertEqual(plan(guild_facts=facts(active={"Bonkers": 1})).refusal, "")

    def test_family_members_are_never_in_the_pick(self):
        family = {"Tanky", "Healy"}
        self.refused(
            plan(guild_facts=facts(family=family)),
            "no five idle members",
            "a family member",
        )

    def test_the_request_roster_also_holds_the_family_out(self):
        roster = FAMILY_ROSTER + [{"name": "Tanky", "enabled": 1}]
        self.refused(plan(roster=roster), "no five idle members")

    def test_members_in_a_run_or_resting_are_not_idle(self):
        self.refused(
            plan(guild_facts=facts(busy={"Stabby"})),
            "no five idle members",
            "in a guild run",
        )
        self.refused(plan(guild_facts=facts(resting={"Stabby"})), "resting after a run")

    def test_too_few_members(self):
        self.refused(
            plan(guild_facts=facts(rows=idle_five()[:4])), "no five idle members"
        )

    def test_members_who_do_not_fit_the_door(self):
        self.refused(plan(ask(keyword="scholomance")), "do not fit", "levels 58 to 60")

    def test_a_keyed_door_without_the_key_is_refused(self):
        rows = [dict(r, level=r["level"] + 17) for r in idle_five()]
        self.refused(
            plan(ask(keyword="scarlet-armory"), facts(rows=rows)), "do not fit"
        )

    def test_a_pick_that_reaches_a_family_member_is_refused(self):
        """The planner leaves them out, so only a planner that stopped doing
        so could pick one; the check stands behind it."""
        with mock.patch.object(guildrun, "free_members") as free:
            free.return_value = (
                [guildrun.member_from_row(r) for r in idle_five()],
                {},
            )
            order = plan(guild_facts=facts(family={"Tanky"}))
        self.refused(order, "Tanky", "family")


class TheFactsRead(unittest.TestCase):
    def test_one_active_run_holds_its_members_and_its_guild(self):
        script = [
            [{"guild": "Cave", "members": "Tanky:tank:1:20,Healy:healer:5:20"}],
            [],
            [],
            [],
        ]

        class Cur(FakeCursor):
            def fetchall(self):
                return script.pop(0)

        found = guildrun.order_facts(Cur(), 40)
        self.assertEqual(found["active"], {"Cave": 1})
        self.assertTrue({"Tanky", "Healy"} <= found["busy"])
        self.assertEqual(found["history"], [])


class TheWriteChecksAgain(unittest.TestCase):
    def test_a_run_that_began_since_the_read_is_not_started_over(self):
        order = plan()

        class Busy(FakeCursor):
            def fetchone(self):
                return {"id": 9}

        cursor = Busy()
        with mock.patch.object(map_server, "_connect") as connect:
            connect.return_value.cursor.return_value.__enter__.return_value = cursor
            changed = map_server._apply_order(order)
        self.assertEqual(changed, 0)
        self.assertEqual(len(cursor.calls), 1)
        self.assertIn("FOR UPDATE", cursor.calls[0][0])
        self.assertIn("overseer_guild_run", cursor.calls[0][0])

    def test_a_clear_guild_is_written_after_the_locked_check(self):
        order = plan()

        class Free(FakeCursor):
            def fetchone(self):
                return None

        cursor = Free()
        with mock.patch.object(map_server, "_connect") as connect:
            connect.return_value.cursor.return_value.__enter__.return_value = cursor
            changed = map_server._apply_order(order)
        self.assertEqual(changed, 1)
        self.assertIn("FOR UPDATE", cursor.calls[0][0])
        self.assertIn("INSERT INTO overseer_guild_run", cursor.calls[1][0])


class TheGate(unittest.TestCase):
    def test_the_section_is_listed_and_names_its_road(self):
        section = next(s for s in decree.SECTIONS if s.key == decree.GUILDRUN)
        self.assertEqual(section.writes, decree.GUILD_RUN_STORE)
        self.assertTrue(decree.can_send(decree.GUILDRUN))
        self.assertNotIn("overseer_", section.does)

    def post(self):
        class Handler(map_server.Handler):
            def __init__(self, body):
                self.rfile = __import__("io").BytesIO(body)
                self.wfile = __import__("io").BytesIO()
                self.headers = {
                    "Content-Length": str(len(body)),
                    "Content-Type": "application/json",
                }
                self.path = "/api/decree"
                self.client_address = ("127.0.0.1", 0)
                self.code = None

            def _send(self, code, ctype, body, *a, **k):
                self.code, self.payload = code, json.loads(body)

        handler = Handler(json.dumps(ask()).encode())
        handler.do_POST()
        return handler

    def test_off_it_is_a_403_and_nothing_is_read_or_written(self):
        with mock.patch.dict(os.environ, {"OVERSEER_OPERATOR_ACTIONS": ""}):
            with mock.patch.multiple(
                map_server,
                _fetch_roster_rows=mock.DEFAULT,
                _fetch_guildrun_facts=mock.DEFAULT,
                _apply_order=mock.DEFAULT,
            ) as mocks:
                handler = self.post()
        self.assertEqual(handler.code, 403)
        for mocked in mocks.values():
            mocked.assert_not_called()

    def test_on_a_good_order_is_a_200_and_a_refusal_is_a_400(self):
        with mock.patch.dict(os.environ, {"OVERSEER_OPERATOR_ACTIONS": "1"}):
            with mock.patch.multiple(
                map_server,
                _fetch_roster_rows=mock.DEFAULT,
                _fetch_guildrun_facts=mock.DEFAULT,
                _apply_order=mock.DEFAULT,
            ) as mocks:
                mocks["_fetch_roster_rows"].return_value = FAMILY_ROSTER
                mocks["_fetch_guildrun_facts"].return_value = facts()
                mocks["_apply_order"].return_value = 1
                good = self.post()
                self.assertEqual(good.code, 200)
                self.assertEqual(good.payload["asked"], 1)
                self.assertTrue(good.payload["ok"])
                mocks["_fetch_guildrun_facts"].return_value = facts(active={"Cave": 1})
                refused = self.post()
        self.assertEqual(refused.code, 400)
        self.assertIn("already has a run", refused.payload["error"])
        mocks["_apply_order"].assert_called_once()


if __name__ == "__main__":
    unittest.main()
