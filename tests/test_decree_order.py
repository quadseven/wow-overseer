"""What an order from the decree console becomes (infra#3345).

For the whole of infra#2597 this console could not write. Three of its four
cards were drawn disabled and said so honestly, and the honesty was the point:
`GET /api/decree` answered can_send=False for the job, the campaign and the
travel aim, because nothing but a hand on the database wrote those columns. It
took a hand on the database to get the family into a dungeon, and a second one
to get them out of a campaign that had quietly finished at 30 of 30.

This suite holds the half that replaced the refusals. Every judgement about a
write is a pure function of a dict and a roster - no database, no HTTP, no
browser - which is exactly what lets the only WRITE surface on the site be
tested at all.

THE THREE THINGS THAT MUST NOT REGRESS, each of which has cost somebody a
session already:

  * AN UNWIRED MODE IS REFUSED HERE. jobs.MODES names twelve modes and
    jobs.IMPLEMENTED names the two that change behaviour. Setting one of the
    other ten does not do nothing - it stands the quest drive DOWN and puts
    nothing in its place. The bridge warns and obeys, which is right for a
    typed sentence; a console obeying one tap is not.

  * AN AIM NEVER OVERWRITES AN AIM. overseer_roster.travel_npc is what the
    profession errand planner uses to send somebody to a trainer, and
    bridge._write_trade_errand guards its own vendor pass so the town run
    cannot erase one. A console aim gets the same guard on every role.

  * NOTHING IS SENT THAT NO STATEMENT EXISTS FOR. The adapter holds one
    statement per column, looked up by this module's own constants. A planner
    that could emit a column with no statement behind it would be a write that
    silently did nothing, which is the failure this whole view is named after.

The read side is tests/test_decree.py and the page contract is
tests/test_decree_tab.py.
"""
import io
import json
import logging
import pathlib
import sys
import types
import unittest
from unittest import mock

# STUBBED FOR IMPORT, exactly as tests/test_chat_endpoints.py does it: the
# module only touches pymysql inside _connect(), which nothing here reaches.
# `err.MySQLError` is added because this suite DOES reach the except clauses
# that name it - a bare stub would turn a degraded-schema test into an
# AttributeError that looked like the guard working.
sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))
if not hasattr(sys.modules["pymysql"], "err"):
    _err = types.ModuleType("pymysql.err")

    class _MySQLError(Exception):
        pass

    _err.MySQLError = _MySQLError
    sys.modules["pymysql"].err = _err

import decree  # noqa: E402
import jobs  # noqa: E402
import map_server  # noqa: E402  (must follow the pymysql stub)
import travel  # noqa: E402

# The degraded-write paths log on purpose; without a configured root handler
# those reach stderr and make a passing run look like a wall of failures.
map_server.log.propagate = False
map_server.log.addHandler(logging.NullHandler())

MYSQL_ERROR = map_server.pymysql.err.MySQLError

HERE = pathlib.Path(__file__).resolve().parent.parent
SERVER = (HERE / "map_server.py").read_text(encoding="utf-8")
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")

FAMILY = ("Og", "Bork", "Grog", "Grug", "Ugga")


def roster(overrides=None) -> list:
    """The five, all enabled, Og leading, everybody questing, 0 of 30 run."""
    overrides = overrides or {}
    rows = []
    for name in FAMILY:
        row = {
            "name": name,
            "enabled": 1,
            "lead": 1 if name == "Og" else 0,
            "job": "quest",
            "drive_quest": 0,
            "travel_npc": "",
            "learn_skill": 0,
            "dungeon_runs_wanted": 30,
            "dungeon_runs_done": 0,
        }
        row.update(overrides.get(name, {}))
        rows.append(row)
    return rows


class WhichCardGivesTheOrder(unittest.TestCase):

    def test_a_section_nobody_has_heard_of_is_refused_and_not_guessed(self):
        for body in ({"section": "muster"}, {"section": ""}, {}, {"section": 7}):
            order = decree.plan_order(body, roster())
            self.assertEqual(order.refusal, decree.ORDER_REFUSALS["section"])
            self.assertEqual(order.rows, ())
            self.assertEqual(order.updates, ())

    def test_the_will_is_refused_here_and_pointed_at_the_chat_path(self):
        """It is a real card and a reachable one, so a bare "not a card"
        would be a lie. The will is a conversation and it has its own road."""
        order = decree.plan_order({"section": decree.WILL}, roster())
        self.assertEqual(order.refusal, decree.ORDER_REFUSALS["will"])
        self.assertIn("chat path", order.refusal)

    def test_a_refusal_is_a_refusal_and_never_also_a_write(self):
        """The one invariant every planner shares. An Order that carried both
        would have the adapter running writes it had already refused."""
        refused = (
            {"section": "muster"},
            {"section": decree.WILL},
            {"section": decree.JOB, "mode": "not a mode"},
            {"section": decree.JOB, "mode": "farm"},
            {"section": decree.CAMPAIGN},
            {"section": decree.CAMPAIGN, "wanted": -1},
            {"section": decree.TRAVEL, "name": "Thrall", "role": "banker"},
            {"section": decree.TRAVEL, "name": "Og", "role": "the pub"},
        )
        for body in refused:
            order = decree.plan_order(body, roster())
            self.assertTrue(order.refusal, body)
            self.assertEqual(order.asked, 0, body)
            self.assertEqual(order.says, "", body)

    def test_the_roster_is_read_and_never_taken_from_the_request(self):
        """A stale page carrying its own idea of the family would fan an
        order out over characters the worldserver no longer drives."""
        order = decree.plan_order(
            {"section": decree.JOB, "mode": "dungeon",
             "roster": ["Thrall"], "names": ["Thrall"]},
            roster({"Ugga": {"enabled": 0}}),
        )
        self.assertEqual([r.target_name for r in order.rows],
                         ["Og", "Bork", "Grog", "Grug"])


class TheStandingJob(unittest.TestCase):
    """One kind='job' row per enabled character, the shape the bridge writes."""

    def test_it_writes_one_row_per_enabled_character(self):
        order = decree.plan_order({"section": decree.JOB, "mode": "dungeon"},
                                  roster())
        self.assertEqual([r.target_name for r in order.rows], list(FAMILY))
        self.assertEqual({r.command for r in order.rows}, {"dungeon"})
        self.assertEqual({r.kind for r in order.rows}, {decree.JOB_KIND})
        self.assertEqual(order.updates, ())
        self.assertEqual(order.asked, 5)

    def test_the_kind_is_the_one_the_bridge_writes_and_not_bot(self):
        """'quest' is not a mod-playerbots chat command, so a kind='bot' row
        would be accepted by PlayerbotAI::HandleCommand and do nothing - the
        voice.py "sell junk" failure this codebase already paid for once."""
        self.assertEqual(decree.JOB_KIND, "job")
        self.assertIn("VALUES (%s, %s, 'job', %s)", BRIDGE)

    def test_a_disabled_row_is_nobody(self):
        order = decree.plan_order({"section": decree.JOB, "mode": "quest"},
                                  roster({"Grug": {"enabled": 0}}))
        self.assertNotIn("Grug", [r.target_name for r in order.rows])
        self.assertEqual(len(order.rows), 4)

    def test_an_empty_roster_is_said_rather_than_written_to_nobody(self):
        order = decree.plan_order({"section": decree.JOB, "mode": "quest"}, [])
        self.assertEqual(order.refusal, decree.ORDER_REFUSALS["roster"])

    def test_how_people_say_it_resolves_the_same_way_discord_does(self):
        """jobs.resolve, not a second recognizer. A console that took only the
        canonical noun would be a third vocabulary for the same column."""
        for said in ("dungeon", "dungeons", "Dungeon Run", "  DUNGEON  "):
            order = decree.plan_order({"section": decree.JOB, "mode": said},
                                      roster())
            self.assertEqual({r.command for r in order.rows}, {"dungeon"}, said)

    def test_named_dungeon_is_carried_to_every_roster_row(self):
        order = decree.plan_order({"section": decree.JOB,
                                   "mode": "dungeon shadowfang"}, roster())
        self.assertEqual({r.command for r in order.rows}, {"dungeon:shadowfang"})

    def test_unknown_named_dungeon_is_refused(self):
        order = decree.plan_order({"section": decree.JOB,
                                   "mode": "dungeon zulfarak"}, roster())
        self.assertEqual(order.refusal, decree.ORDER_REFUSALS["mode"])

    def test_a_mode_nobody_has_heard_of_is_refused_and_never_passed_through(self):
        """An unrecognised mode reaching overseer_roster.job stops the family
        doing anything at all: mod_overseer.cpp compares the string."""
        for said in ("dungon", "", "   ", None, 7, ["dungeon"]):
            order = decree.plan_order({"section": decree.JOB, "mode": said},
                                      roster())
            self.assertEqual(order.refusal, decree.ORDER_REFUSALS["mode"], said)

    def test_every_unwired_mode_is_refused_from_this_page(self):
        """The judgement, not validation. An unwired mode stands the quest
        drive down and puts nothing in its place, and one tap is too cheap for
        that. Read off jobs.IMPLEMENTED, never a second list here, so wiring a
        mode in mod-overseer opens this console in the same commit."""
        for mode in jobs.MODES:
            order = decree.plan_order({"section": decree.JOB, "mode": mode},
                                      roster())
            if mode in jobs.IMPLEMENTED:
                self.assertEqual(order.refusal, "", mode)
                self.assertEqual(len(order.rows), 5, mode)
            else:
                self.assertEqual(order.refusal, decree.unwired_refusal(mode), mode)
                self.assertEqual(order.rows, (), mode)

    def test_the_refusal_opens_with_the_modules_own_sentence(self):
        """jobs.describe has one author. A second copy here would be free to
        soften the stand-down warning it carries."""
        why = decree.unwired_refusal("farm")
        self.assertTrue(why.startswith(jobs.describe("farm")))
        self.assertIn("NOT BUILT YET", why)

    def test_the_refusal_names_the_way_it_is_done_anyway(self):
        """A refusal with no way forward is a dead end. The explicit form in
        the overseer's own channel still sets any mode in MODES."""
        why = decree.unwired_refusal("town run")
        self.assertIn('"job town run"', why)

    def test_what_it_says_is_what_the_bridge_says(self):
        order = decree.plan_order({"section": decree.JOB, "mode": "dungeon"},
                                  roster())
        self.assertEqual(order.says, jobs.describe("dungeon"))


class TheCampaignCounter(unittest.TestCase):
    """The number that had the family sitting at 30 of 30, doing nothing."""

    def test_a_new_cap_is_written_to_every_enabled_row(self):
        """Not the leader's alone. The coordinator reads the leader's row, the
        crown moves in world, and the count does not travel with it - so a cap
        on one row is a campaign that restarts when somebody else takes over."""
        order = decree.plan_order({"section": decree.CAMPAIGN, "wanted": 40},
                                  roster())
        self.assertEqual([u.name for u in order.updates], list(FAMILY))
        self.assertEqual({u.column for u in order.updates},
                         {decree.CAMPAIGN_WANTED})
        self.assertEqual({u.value for u in order.updates}, {40})
        self.assertEqual(order.rows, ())

    def test_a_restart_puts_the_count_back_to_zero_everywhere(self):
        """The operator's actual complaint: 30 of 30 and no way back without
        SQL. The migration's own comment says a campaign is started again by
        setting done to 0."""
        order = decree.plan_order(
            {"section": decree.CAMPAIGN, "restart": True},
            roster({"Og": {"dungeon_runs_done": 30}}))
        self.assertEqual({u.column for u in order.updates}, {decree.CAMPAIGN_DONE})
        self.assertEqual({u.value for u in order.updates}, {0})
        self.assertEqual(len(order.updates), 5)

    def test_both_at_once_is_one_order(self):
        order = decree.plan_order(
            {"section": decree.CAMPAIGN, "wanted": 60, "restart": True}, roster())
        self.assertEqual(order.asked, 10)
        columns = [u.column for u in order.updates]
        self.assertEqual(columns.count(decree.CAMPAIGN_WANTED), 5)
        self.assertEqual(columns.count(decree.CAMPAIGN_DONE), 5)

    def test_an_order_that_asks_for_nothing_is_refused(self):
        """A press that wrote nothing and reported success is the failure this
        view is named after."""
        for body in ({"section": decree.CAMPAIGN},
                     {"section": decree.CAMPAIGN, "restart": False}):
            order = decree.plan_order(body, roster())
            self.assertEqual(order.refusal, decree.ORDER_REFUSALS["campaign"])

    def test_a_cap_that_is_not_a_whole_number_of_runs_is_refused(self):
        """bool is an int in Python, so JSON `true` would otherwise arrive as
        a cap of 1 and pass every range check below it."""
        for wanted in (True, False, 3.5, "40", None if False else "", [40]):
            order = decree.plan_order(
                {"section": decree.CAMPAIGN, "wanted": wanted}, roster())
            self.assertEqual(order.refusal, decree.ORDER_REFUSALS["wanted"],
                             repr(wanted))

    def test_the_ceiling_is_the_columns_own_and_not_one_this_module_invented(self):
        """SMALLINT UNSIGNED, from mod-overseer's own migration. A cap above
        it is refused by the database, and an operator would read that as the
        console being broken."""
        self.assertEqual(decree.CAMPAIGN_CEILING, 65535)
        for wanted in (-1, decree.CAMPAIGN_CEILING + 1, 10 ** 9):
            order = decree.plan_order(
                {"section": decree.CAMPAIGN, "wanted": wanted}, roster())
            self.assertEqual(order.refusal, decree.ORDER_REFUSALS["ceiling"],
                             wanted)
        edge = decree.plan_order(
            {"section": decree.CAMPAIGN, "wanted": decree.CAMPAIGN_CEILING},
            roster())
        self.assertEqual(edge.refusal, "")

    def test_a_cap_of_zero_is_legal_and_is_said_to_be_a_full_stop(self):
        """Not a small campaign. mod_overseer.cpp asks whether done is at
        least wanted before it starts a run, so 0 is true on the first
        comparison and no run ever begins."""
        order = decree.plan_order(
            {"section": decree.CAMPAIGN, "wanted": decree.CAMPAIGN_STOP}, roster())
        self.assertEqual(order.refusal, "")
        self.assertIn("stopped outright", order.says)

    def test_a_restart_is_to_zero_and_to_no_other_number(self):
        """dungeon_runs_done is the coordinator's record of runs that closed.
        A console that let a person type into it would be forging that."""
        self.assertEqual(decree.CAMPAIGN_RESTART, 0)
        order = decree.plan_order(
            {"section": decree.CAMPAIGN, "restart": 12}, roster())
        self.assertEqual({u.value for u in order.updates}, {0})

    def test_an_empty_roster_is_said_rather_than_written_to_nobody(self):
        order = decree.plan_order({"section": decree.CAMPAIGN, "wanted": 5}, [])
        self.assertEqual(order.refusal, decree.ORDER_REFUSALS["roster"])

    def test_the_campaign_writes_are_unguarded(self):
        """A counter is a number to be set, not an intent that might already
        be held by somebody else's plan."""
        order = decree.plan_order(
            {"section": decree.CAMPAIGN, "wanted": 40, "restart": True}, roster())
        self.assertEqual({u.if_free for u in order.updates}, {False})


class SendingThemSomewhere(unittest.TestCase):
    """One character, one role, and never over the top of an errand."""

    def test_an_aim_is_one_character_and_one_column(self):
        order = decree.plan_order(
            {"section": decree.TRAVEL, "name": "Og", "role": "banker"}, roster())
        self.assertEqual(len(order.updates), 1)
        up = order.updates[0]
        self.assertEqual((up.name, up.column, up.value), ("Og", "travel_npc", "banker"))
        self.assertEqual(order.rows, ())

    def test_the_column_is_the_one_the_bridge_writes(self):
        self.assertEqual(decree.TRAVEL_COLUMN, "travel_npc")

    def test_an_aim_is_guarded_and_will_not_erase_an_errand(self):
        """bridge._write_trade_errand guards its vendor pass with the same
        rule so the town run cannot erase a profession trainer errand. A
        console aim gets it on every role, because the errand planner at least
        knows what it is replacing and a person tapping a chip does not.

        The bridge's half of that guard became a value list rather than a
        two-way OR in infra#3692, when a bare creature entry joined the role
        keywords as something an economy pass may aim at; the invariant this
        checks - the bridge never writes a town aim over a column it has not
        been told it may - is unchanged, and map_server's own copy above is
        untouched."""
        order = decree.plan_order(
            {"section": decree.TRAVEL, "name": "Og", "role": "vendor"}, roster())
        self.assertTrue(order.updates[0].if_free)
        self.assertIn("WHERE name = %%s AND travel_npc IN (", BRIDGE)
        self.assertIn("def _retaskable_from(", BRIDGE)

    def test_standing_somebody_down_clears_the_column_unguarded(self):
        """The one write on this page that removes an intent rather than
        substituting one, and the operator's only way out of a character stuck
        walking somewhere. Guarding it would make it a no-op exactly when it
        is needed."""
        order = decree.plan_order(
            {"section": decree.TRAVEL, "name": "Og", "role": travel.NONE},
            roster({"Og": {"travel_npc": "profession trainer"}}))
        up = order.updates[0]
        self.assertEqual(up.value, travel.NONE)
        self.assertFalse(up.if_free)

    def test_only_an_enabled_character_can_be_sent(self):
        for name in ("Thrall", "", "  ", None, 7, "Grug"):
            order = decree.plan_order(
                {"section": decree.TRAVEL, "name": name, "role": "banker"},
                roster({"Grug": {"enabled": 0}}))
            self.assertEqual(order.refusal, decree.ORDER_REFUSALS["name"], name)

    def test_a_role_nobody_has_heard_of_is_refused(self):
        for role in ("the pub", "somewhere", "0", None, 7, ["banker"]):
            order = decree.plan_order(
                {"section": decree.TRAVEL, "name": "Og", "role": role}, roster())
            self.assertEqual(order.refusal, decree.ORDER_REFUSALS["role"], role)

    def test_the_vocabulary_is_travels_own_and_not_a_third_copy(self):
        """The keywords are already duplicated in C++ and checked line for
        line by tests/test_travel_npc.py. A third copy is the one nobody would
        think to check."""
        for role in travel.ROLES:
            order = decree.plan_order(
                {"section": decree.TRAVEL, "name": "Og", "role": role}, roster())
            self.assertEqual(order.refusal, "", role)
            self.assertEqual(order.updates[0].value, role)

    def test_an_alias_and_a_creature_entry_both_resolve(self):
        for said, stored in (("auction house", "auctioneer"), ("inn", "innkeeper"),
                             ("1234", "1234")):
            order = decree.plan_order(
                {"section": decree.TRAVEL, "name": "Og", "role": said}, roster())
            self.assertEqual(order.updates[0].value, stored, said)

    def test_nothing_wider_than_the_column_is_ever_planned(self):
        """A keyword that does not fit is one the module can never read back.
        Enforced here rather than discovered as a silently truncated row."""
        for role in travel.ROLES:
            self.assertLessEqual(len(role), travel.COLUMN_WIDTH)
        long_entry = "9" * (travel.COLUMN_WIDTH + 1)
        order = decree.plan_order(
            {"section": decree.TRAVEL, "name": "Og", "role": long_entry}, roster())
        self.assertEqual(order.refusal, decree.ORDER_REFUSALS["role"])

    def test_what_it_says_repeats_the_caveat_where_it_is_read(self):
        """Travel is not transaction. An aimed character walks there and
        stands in front of it, and the sentence says so at the moment somebody
        has just pressed send."""
        order = decree.plan_order(
            {"section": decree.TRAVEL, "name": "Og", "role": "vendor"}, roster())
        self.assertIn("is not using it", order.says)


class WhatCameOfIt(unittest.TestCase):
    """`changed` is rows CHANGED, not matched. pymysql does not set
    CLIENT_FOUND_ROWS, so the same order pressed twice reports zero."""

    def setUp(self):
        self.order = decree.plan_order(
            {"section": decree.JOB, "mode": "dungeon"}, roster())

    def test_everything_landing_is_counted_and_said(self):
        out = decree.order_result(self.order, 5)
        self.assertTrue(out["ok"])
        self.assertEqual((out["changed"], out["asked"]), (5, 5))
        self.assertEqual(out["says"], self.order.says)
        self.assertIn("5 of 5", out["note"])

    def test_a_short_count_says_what_the_rest_means(self):
        out = decree.order_result(self.order, 3)
        self.assertTrue(out["ok"])
        self.assertIn("3 of 5", out["note"])
        self.assertIn("already carried the value", out["note"])

    def test_nothing_changing_is_not_reported_as_success(self):
        """The alternative is a console reporting success for a write the
        database declined, which is the failure this view is named after."""
        out = decree.order_result(self.order, 0)
        self.assertFalse(out["ok"])
        self.assertEqual(out["note"], decree.ORDER_NOTHING[decree.JOB])

    def test_every_section_that_can_order_has_a_nothing_happened_sentence(self):
        """Composed here or a KeyError reaches the operator as a 503 on the
        one press that most needs an explanation."""
        for section in decree.PLANNERS:
            self.assertIn(section, decree.ORDER_NOTHING)
            self.assertTrue(decree.ORDER_NOTHING[section])

    def test_the_travel_sentence_names_both_reasons_it_could_be_zero(self):
        """A guarded update reports zero for "already walking there" and for
        "carries an errand" alike, and the difference matters."""
        note = decree.ORDER_NOTHING[decree.TRAVEL]
        self.assertIn("already walking there", note)
        self.assertIn("will not erase one", note)

    def test_the_job_sentence_names_the_schema_that_would_refuse_it(self):
        note = decree.ORDER_NOTHING[decree.JOB]
        self.assertIn("overseer_command.kind", note)


class TheAdapterRunsAndDoesNotDecide(unittest.TestCase):
    """THE ONE RULE at the other end: map_server.py fetches rows, runs what it
    was handed, and serialises the answer."""

    def handler(self) -> str:
        body = SERVER[SERVER.index("    def _decree_post(self)"):]
        return body[:body.index("    def _watch_state(self")]

    def applier(self) -> str:
        body = SERVER[SERVER.index("def _apply_order("):]
        return body[:body.index("class Handler")]

    def test_the_handler_asks_the_module_and_runs_what_it_gets_back(self):
        handler = self.handler()
        self.assertIn("decree.plan_order(request, _fetch_roster_rows())", handler)
        self.assertIn("_apply_order(order)", handler)
        self.assertIn("decree.order_result(order, changed)", handler)

    def test_the_handler_holds_no_vocabulary_of_its_own(self):
        """Not one comparison against a mode, a role, a name or a bound. Every
        one of those is a judgement, and they all live in the pure module."""
        handler = self.handler()
        for forbidden in ("jobs.", "travel.", "IMPLEMENTED", "int(", "strip()",
                          "CEILING", '"mode"', '"role"', '"wanted"'):
            self.assertNotIn(forbidden, handler, forbidden)

    def test_a_refusal_is_a_400_carrying_the_modules_own_sentence(self):
        """A status code alone would have the browser composing an
        explanation of a system it knows nothing about."""
        handler = self.handler()
        self.assertIn("self._send(400", handler)
        self.assertIn('"error": order.refusal', handler)

    def test_a_failed_write_is_a_503_and_is_logged(self):
        handler = self.handler()
        self.assertIn("self._send(503", handler)
        self.assertIn("log.exception", handler)

    def test_the_same_order_twice_cannot_interleave(self):
        """ThreadingHTTPServer runs a thread per request and a job order is
        one INSERT per character. Two taps a second apart would otherwise
        leave half the family on one mode and half on another - the split
        agenda.job_split exists to REPORT, and this page must not cause it.
        The lock covers the plan as well as the writes, so an order is planned
        against the roster it is about to be applied to."""
        self.assertIn("_DECREE_LOCK = threading.Lock()", SERVER)
        handler = self.handler()
        self.assertIn("with _DECREE_LOCK:", handler)
        # The CODE line, not the docstring above it that names the same call.
        plan = handler.index("decree.plan_order(request")
        self.assertLess(handler.index("with _DECREE_LOCK:"), plan)
        self.assertLess(plan, handler.index("_apply_order(order)"))

    def test_every_column_a_planner_can_emit_has_a_statement_behind_it(self):
        """A planned column with no statement is a write that silently does
        nothing. Checked by PLANNING every order this console offers and
        looking each column up in the adapter's own tables."""
        plans = (
            {"section": decree.CAMPAIGN, "wanted": 7, "restart": True},
            {"section": decree.TRAVEL, "name": "Og", "role": "banker"},
            {"section": decree.TRAVEL, "name": "Og", "role": travel.NONE},
        )
        plain = SERVER[SERVER.index("_ROSTER_SET = {"):]
        plain = plain[:plain.index("}")]
        guarded = SERVER[SERVER.index("_ROSTER_SET_IF_FREE = {"):]
        guarded = guarded[:guarded.index("}")]
        # The constant a planned column was named by, so the assertion reads
        # the adapter the way the adapter reads the module.
        named = {value: key for key, value in vars(decree).items()
                 if key.isupper() and isinstance(value, str)}
        for body in plans:
            order = decree.plan_order(body, roster())
            self.assertEqual(order.refusal, "", body)
            for up in order.updates:
                where = guarded if up.if_free else plain
                self.assertIn("decree." + named[up.column], where, up.column)
                self.assertIn(up.column, where, up.column)

    def test_the_statement_tables_are_keyed_by_the_modules_constants(self):
        """Never by a literal. A column renamed in decree.py and not here
        would be a lookup miss, which is loud, rather than a statement that
        writes the wrong column."""
        tables = SERVER[SERVER.index("_ROSTER_SET = {"):SERVER.index("_DECREE_LOCK")]
        for constant in ("decree.CAMPAIGN_WANTED", "decree.CAMPAIGN_DONE",
                         "decree.TRAVEL_COLUMN"):
            self.assertIn(constant, tables)

    def test_the_guarded_statement_is_the_bridges_own_where_clause(self):
        guarded = SERVER[SERVER.index("_ROSTER_SET_IF_FREE = {"):]
        guarded = guarded[:guarded.index("}")]
        self.assertIn("AND (travel_npc = '' OR travel_npc = %s)", guarded)

    def test_every_value_is_bound_and_no_name_is_interpolated(self):
        """The column name comes from a fixed table and nothing else reaches
        the SQL text. Names, roles and numbers are always parameters."""
        applier = self.applier()
        self.assertIn("_ROSTER_SET_IF_FREE if up.if_free else _ROSTER_SET", applier)
        self.assertIn("cur.execute(sql, params)", applier)
        for assembled in ("%%", ".format(", 'f"UPDATE', "+ up.column"):
            self.assertNotIn(assembled, applier, assembled)

    def test_the_orders_are_attributable_to_this_surface(self):
        """source='web:overseer' is what lets the console read its own orders
        back, and what lets anybody reading overseer_command tell a press on
        this page from the bridge's own traffic."""
        applier = self.applier()
        self.assertIn("WEB_SOURCE", applier)
        self.assertEqual(SERVER.count('"web:overseer"'), 1)

    def test_a_degraded_schema_is_guarded_on_every_write(self):
        """1146 missing table, 1054 missing column, 1265 an ENUM value this
        realm has never heard of. The last is not hypothetical: kind='job'
        arrives with mod-overseer's SQL and this process deploys separately,
        so a worldserver that predates it rejects the row under strict mode."""
        self.assertIn("_DEGRADED = (1054, 1146, 1265)", SERVER)
        applier = self.applier()
        self.assertEqual(applier.count("exc.args[0] in _DEGRADED"), 2)
        self.assertEqual(applier.count("raise"), 2)
        self.assertEqual(applier.count("log.warning"), 2)

    def test_a_degraded_write_does_not_cost_the_rest_of_the_family(self):
        """bridge._set_job keeps the identical rule on the identical fan-out:
        one failed insert must not stop the other four."""
        applier = self.applier()
        self.assertEqual(applier.count("continue"), 3)

    def test_the_roster_read_uses_the_same_statements_the_console_does(self):
        """A plan and the page must agree about who is enabled, so the order
        is planned off the statements the console was drawn from."""
        fetch = SERVER[SERVER.index("def _fetch_roster_rows"):]
        fetch = fetch[:fetch.index("def _apply_order")]
        self.assertIn("for attempt in (_ROSTER_FULL, _ROSTER_OLD):", fetch)

    def test_the_roster_read_does_not_inherit_the_1054_gap(self):
        """_guarded catches ProgrammingError, and 1054 is absent from
        pymysql's error_map so a missing COLUMN arrives as an
        OperationalError. On the read side that gap costs a banner; here it
        would 503 every order on the realm most likely to need the fallback."""
        fetch = SERVER[SERVER.index("def _fetch_roster_rows"):]
        fetch = fetch[:fetch.index("def _apply_order")]
        self.assertNotIn("_guarded(", fetch)
        self.assertIn("exc.args[0] in _DEGRADED", fetch)


class FakeCursor:
    """Records every statement, and can be told to fail or change no rows.

    `script` maps a fragment of SQL to what happens when it is run: an
    exception to raise, or the rowcount to report.
    """

    def __init__(self, script=None, rows=()):
        self.calls = []
        self.rowcount = 1
        self.rows = rows
        self.script = script or {}

    def execute(self, sql, params=()):
        self.calls.append((" ".join(sql.split()), params))
        for fragment, outcome in self.script.items():
            if fragment in " ".join(sql.split()):
                if isinstance(outcome, Exception):
                    raise outcome
                self.rowcount = outcome
                return
        self.rowcount = 1

    def fetchall(self):
        return list(self.rows)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.closed = False

    def cursor(self):
        return self._cursor

    def close(self):
        self.closed = True


class TheWritesThatActuallyRun(unittest.TestCase):
    """_apply_order driven against a recording cursor.

    Everything above this class reads source text or plans orders. These are
    the only tests that watch a statement and its parameters go past together,
    which is where a guarded UPDATE with two placeholders and three values
    would be caught - a mistake no source-text assertion sees.
    """

    def run_order(self, body, script=None):
        cursor = FakeCursor(script)
        conn = FakeConn(cursor)
        order = decree.plan_order(body, roster())
        self.assertEqual(order.refusal, "", body)
        with mock.patch.object(map_server, "_connect", return_value=conn):
            changed = map_server._apply_order(order)
        self.assertTrue(conn.closed, "the connection was not closed")
        return order, cursor, changed

    def test_a_job_order_inserts_one_attributable_row_per_character(self):
        order, cursor, changed = self.run_order(
            {"section": decree.JOB, "mode": "dungeon"})
        self.assertEqual(changed, 5)
        self.assertEqual(len(cursor.calls), 5)
        for (sql, params), name in zip(cursor.calls, FAMILY):
            self.assertIn("INSERT INTO overseer_command", sql)
            self.assertEqual(params, (name, "dungeon", "job", "web:overseer"))

    def test_the_source_is_what_the_console_reads_its_own_orders_back_by(self):
        """_fetch_decree scopes the outcome card by source. A row written
        under any other spelling is an order that happened and that this page
        would never show."""
        _, cursor, _ = self.run_order({"section": decree.JOB, "mode": "quest"})
        for _sql, params in cursor.calls:
            self.assertEqual(params[-1], map_server.WEB_SOURCE)

    def test_a_campaign_order_runs_the_plain_statement_per_row(self):
        order, cursor, changed = self.run_order(
            {"section": decree.CAMPAIGN, "wanted": 40, "restart": True})
        self.assertEqual(changed, 10)
        self.assertEqual(len(cursor.calls), 10)
        wanted = [c for c in cursor.calls if "dungeon_runs_wanted" in c[0]]
        done = [c for c in cursor.calls if "dungeon_runs_done" in c[0]]
        self.assertEqual(len(wanted), 5)
        self.assertEqual(len(done), 5)
        self.assertEqual(wanted[0][1], (40, "Og"))
        self.assertEqual(done[0][1], (0, "Og"))
        for sql, _params in cursor.calls:
            self.assertNotIn("travel_npc", sql)

    def test_a_travel_aim_runs_the_guarded_statement_with_three_values(self):
        """Two placeholders and three values, or three and two, is a
        ProgrammingError on a live realm and nothing here would have caught it
        without watching the pair go past."""
        order, cursor, changed = self.run_order(
            {"section": decree.TRAVEL, "name": "Grug", "role": "banker"})
        self.assertEqual(changed, 1)
        sql, params = cursor.calls[0]
        self.assertIn("AND (travel_npc = '' OR travel_npc = %s)", sql)
        self.assertEqual(sql.count("%s"), len(params))
        self.assertEqual(params, ("banker", "Grug", "banker"))

    def test_standing_somebody_down_runs_the_unguarded_statement(self):
        order, cursor, changed = self.run_order(
            {"section": decree.TRAVEL, "name": "Grug", "role": travel.NONE})
        sql, params = cursor.calls[0]
        self.assertNotIn("AND (", sql)
        self.assertEqual(sql.count("%s"), len(params))
        self.assertEqual(params, ("", "Grug"))

    def test_a_guarded_update_that_changes_nothing_is_counted_honestly(self):
        """The column already carries an errand, so the WHERE matches no row.
        Reporting that as a success is the failure this view is named after."""
        order, cursor, changed = self.run_order(
            {"section": decree.TRAVEL, "name": "Grug", "role": "banker"},
            {"travel_npc": 0})
        self.assertEqual(changed, 0)
        out = decree.order_result(order, changed)
        self.assertFalse(out["ok"])
        self.assertEqual(out["note"], decree.ORDER_NOTHING[decree.TRAVEL])

    def test_a_schema_that_has_never_heard_of_kind_job_costs_only_that_row(self):
        """1265 under strict mode is what an unknown ENUM value raises, and
        kind='job' arrives with mod-overseer's SQL while this process deploys
        separately. The order comes back short rather than as a 503."""
        order, cursor, changed = self.run_order(
            {"section": decree.JOB, "mode": "dungeon"},
            {"INSERT INTO overseer_command": MYSQL_ERROR(1265, "truncated")})
        self.assertEqual(changed, 0)
        self.assertEqual(len(cursor.calls), 5, "it stopped at the first refusal")

    def test_a_missing_campaign_column_is_survived_the_same_way(self):
        order, cursor, changed = self.run_order(
            {"section": decree.CAMPAIGN, "wanted": 40},
            {"dungeon_runs_wanted": MYSQL_ERROR(1054, "unknown column")})
        self.assertEqual(changed, 0)
        self.assertEqual(len(cursor.calls), 5)

    def test_a_missing_table_is_survived_the_same_way(self):
        order, cursor, changed = self.run_order(
            {"section": decree.TRAVEL, "name": "Og", "role": "vendor"},
            {"UPDATE overseer_roster": MYSQL_ERROR(1146, "no such table")})
        self.assertEqual(changed, 0)

    def test_a_thin_roster_falls_back_instead_of_failing_every_order(self):
        """The realm whose overseer_roster predates the campaign columns is
        the one that most needs an order to go through."""
        cursor = FakeCursor({"dungeon_runs_wanted":
                             MYSQL_ERROR(1054, "unknown column")})
        conn = FakeConn(cursor)
        with mock.patch.object(map_server, "_connect", return_value=conn):
            rows = map_server._fetch_roster_rows()
        # The full read, the thin read, then the family stamp (decree.py
        # plans a job or a campaign per family).
        self.assertEqual(len(cursor.calls), 3)
        self.assertIn("`lead` FROM overseer_roster", cursor.calls[1][0])
        self.assertIn("SELECT name, family FROM overseer_roster", cursor.calls[2][0])
        self.assertEqual(rows, [])
        self.assertTrue(conn.closed)

    def test_a_roster_read_that_is_not_a_schema_problem_still_raises(self):
        cursor = FakeCursor({"FROM overseer_roster":
                             MYSQL_ERROR(2013, "lost connection")})
        conn = FakeConn(cursor)
        with mock.patch.object(map_server, "_connect", return_value=conn):
            with self.assertRaises(MYSQL_ERROR):
                map_server._fetch_roster_rows()
        self.assertTrue(conn.closed)

    def test_any_other_database_error_still_reaches_the_handler(self):
        """A syntax error or a dead socket must not be rendered as an order
        that quietly wrote nothing. Only the three degraded codes are
        swallowed."""
        cursor = FakeCursor({"INSERT INTO overseer_command":
                             MYSQL_ERROR(1064, "you have an error in your SQL")})
        conn = FakeConn(cursor)
        order = decree.plan_order({"section": decree.JOB, "mode": "quest"}, roster())
        with mock.patch.object(map_server, "_connect", return_value=conn):
            with self.assertRaises(MYSQL_ERROR):
                map_server._apply_order(order)
        self.assertTrue(conn.closed, "the connection leaked on the error path")


class FakeHandler(map_server.Handler):
    """A Handler with the socket amputated: a body in, (code, payload) out."""

    def __init__(self, body=b""):
        self.path = "/api/decree"
        self.rfile = io.BytesIO(body)
        self.headers = {"Content-Length": str(len(body))} if body else {}
        self.sent = []

    def _send(self, code, ctype, body):
        self.sent.append((code, ctype, body))

    @property
    def code(self):
        return self.sent[-1][0]

    @property
    def payload(self):
        return json.loads(self.sent[-1][2])


def order(**body):
    handler = FakeHandler(json.dumps(body).encode())
    handler.do_POST()
    return handler


class TheEndpointFromTheOutside(unittest.TestCase):
    """POST /api/decree driven through do_POST, which is how the page hits it."""

    def setUp(self):
        patches = {"_fetch_roster_rows": mock.DEFAULT, "_apply_order": mock.DEFAULT}
        self.patcher = mock.patch.multiple(map_server, **patches)
        self.mocks = self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.mocks["_fetch_roster_rows"].return_value = roster()
        self.mocks["_apply_order"].return_value = 5

    def test_the_route_is_reachable_and_a_good_order_is_a_200(self):
        handler = order(section=decree.JOB, mode="dungeon")
        self.assertEqual(handler.code, 200)
        self.assertEqual(handler.payload["section"], decree.JOB)
        self.assertEqual(handler.payload["asked"], 5)
        self.assertTrue(handler.payload["ok"])
        self.assertEqual(handler.payload["says"], jobs.describe("dungeon"))

    def test_a_refused_order_is_a_400_and_never_reaches_a_write(self):
        handler = order(section=decree.JOB, mode="farm")
        self.assertEqual(handler.code, 400)
        self.assertEqual(handler.payload["error"], decree.unwired_refusal("farm"))
        self.mocks["_apply_order"].assert_not_called()

    def test_an_unknown_section_is_refused_before_the_roster_is_even_read(self):
        handler = order(section="muster")
        self.assertEqual(handler.code, 400)
        self.mocks["_apply_order"].assert_not_called()

    def test_a_body_that_is_not_json_is_refused_before_anything_else(self):
        handler = FakeHandler(b"section=job")
        handler.do_POST()
        self.assertEqual(handler.code, 400)
        self.mocks["_apply_order"].assert_not_called()

    def test_an_empty_body_is_refused(self):
        handler = FakeHandler()
        handler.do_POST()
        self.assertEqual(handler.code, 400)

    def test_a_dead_database_is_a_503_and_not_a_reported_order(self):
        """A console that reported an order it could not place is the exact
        failure this whole view is named after."""
        self.mocks["_apply_order"].side_effect = OSError("gone")
        handler = order(section=decree.CAMPAIGN, restart=True)
        self.assertEqual(handler.code, 503)

    def test_the_order_is_planned_against_the_roster_that_was_read(self):
        self.mocks["_fetch_roster_rows"].return_value = roster(
            {"Ugga": {"enabled": 0}})
        order(section=decree.JOB, mode="quest")
        planned = self.mocks["_apply_order"].call_args[0][0]
        self.assertEqual([r.target_name for r in planned.rows],
                         ["Og", "Bork", "Grog", "Grug"])

    def test_the_same_order_twice_is_reported_as_the_no_op_it_is(self):
        """Two taps a second apart. The second changes nothing because every
        row already carries the value, and the note says so rather than
        claiming a second campaign was set."""
        self.mocks["_apply_order"].return_value = 0
        handler = order(section=decree.CAMPAIGN, wanted=40)
        self.assertEqual(handler.code, 200)
        self.assertFalse(handler.payload["ok"])
        self.assertEqual(handler.payload["note"],
                         decree.ORDER_NOTHING[decree.CAMPAIGN])


if __name__ == "__main__":
    unittest.main()
