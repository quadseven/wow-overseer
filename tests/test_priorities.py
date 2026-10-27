"""The family's priorities: a fixed list the operator ranks on the site (#1559).

One pure module (priorities.py) owns the list, refuses any order that is not
a full permutation of it, moves an entry to a rank, and renders the prompt
line. The decree console stores the order through its own write path, every
Jev Choice request carries the ranked sentences word for word, and the goal
pass breaks a tie over the family's job with it.
"""

import asyncio
import logging
import pathlib
import sys
import types
import unittest
from unittest import mock

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))
if not hasattr(sys.modules["pymysql"], "err"):
    _err = types.ModuleType("pymysql.err")

    class _MySQLError(Exception):
        pass

    _err.MySQLError = _MySQLError
    sys.modules["pymysql"].err = _err

import campaignplan  # noqa: E402
import decree  # noqa: E402
import goals  # noqa: E402
import jev  # noqa: E402
import jev_choices  # noqa: E402
import map_server  # noqa: E402
import priorities  # noqa: E402
from test_decree_order import FakeConn, FakeCursor, order, roster  # noqa: E402
from test_jev_items import FakeJev  # noqa: E402

map_server.log.propagate = False
map_server.log.addHandler(logging.NullHandler())

HERE = pathlib.Path(__file__).resolve().parent.parent
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")
SERVER = (HERE / "map_server.py").read_text(encoding="utf-8")
MYSQL_ERROR = map_server.pymysql.err.MySQLError

NAMES = ("Grug", "Ugga", "Grog", "Bork", "Og")

# A ranking the operator might give: dungeons first, staying alive last but
# one. Every id once.
REORDERED = (
    priorities.DUNGEONS,
    priorities.GEAR,
    priorities.ALIVE,
    priorities.QUEST,
    priorities.PROFESSIONS,
    priorities.GOLD,
    priorities.GUILD,
)


def _import_bridge():
    """bridge.py with discord stubbed, as tests/test_activity_interlude_rest.py
    imports it: only the client class is needed to load the module."""
    stub = types.ModuleType("discord")

    class Client:
        def __init__(self, *args, **kwargs):
            pass

    stub.Client = Client
    with mock.patch.dict(sys.modules, {"discord": stub}):
        sys.modules.pop("bridge", None)
        import bridge  # noqa: PLC0415 - heavy; only one test needs it
    return bridge


def body_of(section_text: str, start: str) -> str:
    begin = section_text.index(start)
    return section_text[begin : section_text.index("\n    def ", begin + 10)]


class TheList(unittest.TestCase):
    def test_every_priority_has_a_stable_id_a_label_and_one_sentence(self):
        self.assertEqual(
            priorities.IDS,
            ("alive", "gear", "quest", "dungeons", "professions", "gold", "guild"),
        )
        for p in priorities.PRIORITIES:
            self.assertTrue(p.label, p.id)
            self.assertTrue(p.sentence.endswith("."), p.id)
            self.assertTrue(p.sentence.isascii(), p.id)
        self.assertEqual(len(set(priorities.IDS)), len(priorities.IDS))

    def test_the_default_is_the_list_in_its_own_order(self):
        self.assertEqual(priorities.DEFAULT_ORDER, priorities.IDS)

    def test_every_goal_kind_serves_a_priority_on_the_list(self):
        self.assertEqual(set(priorities.GOAL_PRIORITY), set(goals.GOAL_KINDS))
        for pid in priorities.GOAL_PRIORITY.values():
            self.assertIn(pid, priorities.IDS)


class AnOrderIsAFullPermutationOrItIsRefused(unittest.TestCase):
    def test_a_full_permutation_is_taken_as_given(self):
        self.assertEqual(priorities.validate(list(REORDERED)), (REORDERED, ""))

    def test_anything_else_is_refused_and_never_repaired(self):
        cases = {
            "left out": list(REORDERED[:-1]),
            "named twice": list(REORDERED[:-1]) + [REORDERED[0]],
            "unknown": list(REORDERED[:-1]) + ["raiding"],
            "padded": list(REORDERED) + ["raiding"],
            "not a list": "dungeons,gear,alive,quest,professions,gold,guild",
            "not strings": [1, 2, 3, 4, 5, 6, 7],
            "empty": [],
            "missing": None,
        }
        for what, bad in cases.items():
            got, refusal = priorities.validate(bad)
            self.assertIsNone(got, what)
            self.assertTrue(refusal, what)

    def test_the_refusal_names_what_was_wrong(self):
        _, refusal = priorities.validate(list(REORDERED[:-1]))
        self.assertIn('"guild"', refusal)
        self.assertIn("left out", refusal)
        _, refusal = priorities.validate(list(REORDERED[:-1]) + ["gear"])
        self.assertIn('"gear"', refusal)
        self.assertIn("more than once", refusal)
        _, refusal = priorities.validate(list(REORDERED[:-1]) + ["raiding"])
        self.assertIn('"raiding"', refusal)

    def test_a_refused_order_writes_nothing_and_the_stored_order_stands(self):
        """Through the console's own plan and write: a refusal is never a
        write, so whatever the row held is what it still holds."""
        bad = {"section": decree.PRIORITIES, "order": list(REORDERED[:-1])}
        planned = decree.plan_order(bad, roster())
        self.assertTrue(planned.refusal)
        self.assertIsNone(planned.priorities)
        self.assertEqual(planned.asked, 0)
        cursor = FakeCursor()
        with mock.patch.object(map_server, "_connect", return_value=FakeConn(cursor)):
            changed = map_server._apply_order(planned)
        self.assertEqual(changed, 0)
        self.assertEqual(cursor.calls, [])

    def test_a_refused_order_is_a_400_and_never_reaches_a_write(self):
        with mock.patch.multiple(
            map_server,
            _fetch_roster_rows=mock.DEFAULT,
            _apply_order=mock.DEFAULT,
        ) as mocks:
            mocks["_fetch_roster_rows"].return_value = roster()
            handler = order(section=decree.PRIORITIES, order=["gear", "gear"])
        self.assertEqual(handler.code, 400)
        self.assertEqual(handler.payload["section"], decree.PRIORITIES)
        mocks["_apply_order"].assert_not_called()

    def test_a_stored_value_that_no_longer_matches_reads_as_the_default(self):
        order, state = priorities.read_stored([{"ranked": "gear,alive,quest"}])
        self.assertEqual(
            (order, state), (priorities.DEFAULT_ORDER, priorities.UNREADABLE)
        )
        self.assertEqual(
            priorities.read_stored([]), (priorities.DEFAULT_ORDER, priorities.UNSET)
        )
        stored = ",".join(REORDERED)
        self.assertEqual(
            priorities.read_stored([{"ranked": stored}]),
            (REORDERED, priorities.STORED),
        )


class MovingShiftsRatherThanSwaps(unittest.TestCase):
    def test_moving_to_the_top_shifts_everybody_above_it_down_one(self):
        moved = priorities.move(priorities.DEFAULT_ORDER, priorities.DUNGEONS, 1)
        self.assertEqual(
            moved,
            ("dungeons", "alive", "gear", "quest", "professions", "gold", "guild"),
        )
        # A swap would have put "alive" fourth.
        self.assertNotEqual(moved.index("alive"), 3)

    def test_moving_down_shifts_the_ones_it_passes_up_one(self):
        moved = priorities.move(priorities.DEFAULT_ORDER, priorities.ALIVE, 4)
        self.assertEqual(
            moved,
            ("gear", "quest", "dungeons", "alive", "professions", "gold", "guild"),
        )

    def test_the_prompt_line_lists_the_sentences_in_the_new_order(self):
        moved = priorities.move(priorities.DEFAULT_ORDER, priorities.GOLD, 2)
        line = priorities.prompt_line(moved)
        self.assertTrue(line.startswith("Priorities (highest first): 1. "))
        expected = [priorities.priority(i).sentence for i in moved]
        at = [line.index("%d. %s" % (n, s)) for n, s in enumerate(expected, 1)]
        self.assertEqual(at, sorted(at))
        self.assertIn("2. " + priorities.priority(priorities.GOLD).sentence, line)

    def test_a_rank_off_the_list_or_an_unknown_id_is_a_bug_not_a_guess(self):
        for pid, rank in (("dungeons", 0), ("dungeons", 8), ("raiding", 1)):
            with self.assertRaises(ValueError):
                priorities.move(priorities.DEFAULT_ORDER, pid, rank)
        with self.assertRaises(ValueError):
            priorities.move(("gear",), "gear", 1)


class JevReadsTheRankedSentencesVerbatim(unittest.TestCase):
    def dungeon_facts(self):
        return campaignplan.Facts(
            family="Grug",
            level_rows=tuple(
                {"name": n, "level": 60, "race": 1, "map_id": 1, "lead": 0}
                for n in NAMES
            ),
            done={},
            failed={},
            quests={2557: 4},
            gear={n: (44.0, 2) for n in NAMES},
            loot={429: 60},
            keys=frozenset({18249}),
        )

    def ask_dungeon(self, ranked):
        fake = FakeJev(confidence=0.9)
        facts = self.dungeon_facts()
        opts = campaignplan.options(facts)
        pick = campaignplan.heuristic(opts)
        rule = jev_choices.policy(jev_choices.KIND_DUNGEON, {})
        client = jev.Client("k", transport=fake)
        judgment = asyncio.run(
            jev_choices.dungeon_ask(
                client, facts, opts, pick, rule, "the queue is empty", ranked=ranked
            )
        )
        return fake.requests, judgment

    def test_a_dungeon_choice_carries_the_sentences_in_the_stored_order(self):
        [request], judgment = self.ask_dungeon(REORDERED)
        self.assertEqual(
            request["state"]["priorities"],
            [priorities.priority(i).sentence for i in REORDERED],
        )
        instructions = request["questions"]["dungeon"]["instructions"]
        self.assertIn(priorities.prompt_line(REORDERED), instructions)
        # The record says which ranking it was asked under.
        self.assertTrue(judgment.facts.startswith("priorities dungeons>gear>alive"))

    def test_the_sentence_the_page_shows_is_the_one_jev_reads(self):
        [request], _ = self.ask_dungeon(REORDERED)
        page = decree.build_console(
            roster(), [], priority_rows=[{"ranked": ",".join(REORDERED)}]
        )["priorities"]
        self.assertEqual(
            [e["sentence"] for e in page["entries"]], request["state"]["priorities"]
        )
        self.assertIn(page["line"], request["questions"]["dungeon"]["instructions"])

    def test_without_an_order_the_request_is_as_it_was(self):
        [request], judgment = self.ask_dungeon(None)
        self.assertNotIn("priorities", request["state"])
        self.assertNotIn(
            priorities.PROMPT_HEAD, request["questions"]["dungeon"]["instructions"]
        )
        self.assertFalse(judgment.facts.startswith("priorities"))

    def test_every_choice_kind_takes_the_order(self):
        state, questions = jev_choices.with_priorities(
            {"family": []},
            {"zone": jev.choice("Pick one.", {"a": "A", "b": "B"})},
            REORDERED,
        )
        self.assertEqual(state["priorities"], list(priorities.sentences(REORDERED)))
        self.assertTrue(
            questions["zone"]["instructions"].endswith(
                priorities.prompt_line(REORDERED)
            )
        )
        for ask in (
            jev_choices.dungeon_ask,
            jev_choices.zone_ask,
            jev_choices.quest_shadow,
        ):
            self.assertIn("ranked", ask.__code__.co_varnames, ask.__name__)

    def test_the_bridge_hands_every_ask_the_stored_order(self):
        plan = body_of(BRIDGE, "    async def _plan_campaign(")
        self.assertIn("ranked = await self._priority_order()", plan)
        self.assertIn("rule, ranked=ranked,", plan)
        self.assertIn("priorities.prompt_line(ranked)", plan)
        level = body_of(BRIDGE, "    async def _level_ask(")
        self.assertIn("ranked = await self._priority_order()", level)
        self.assertIn("why_now, ranked=ranked)", level)
        quest = body_of(BRIDGE, "    def _jev_quest_shadow(")
        self.assertIn("ranked=ranked)", quest)


class TheSchedulersTieBreakFollowsTheStoredOrder(unittest.TestCase):
    def test_the_higher_ranked_priority_sets_the_job(self):
        candidates = [(11, "skill"), (12, "dungeon")]
        default = priorities.job_contest(candidates, priorities.DEFAULT_ORDER)
        # Default: dungeons rank above professions.
        self.assertEqual((default.winner, default.waiting), (12, (11,)))
        reordered = priorities.move(priorities.DEFAULT_ORDER, priorities.PROFESSIONS, 1)
        flipped = priorities.job_contest(candidates, reordered)
        self.assertEqual((flipped.winner, flipped.waiting), (11, (12,)))
        self.assertIn("Professions ranks highest", flipped.line)

    def test_two_goals_serving_one_priority_keep_their_order(self):
        got = priorities.job_contest(
            [(3, "dungeon"), (4, "dungeon")], priorities.DEFAULT_ORDER
        )
        self.assertEqual((got.winner, got.waiting), (3, (4,)))

    def test_one_goal_or_none_is_not_a_contest(self):
        self.assertEqual(
            priorities.job_contest([(5, "skill")], REORDERED),
            priorities.Contest(5, (), ""),
        )
        self.assertEqual(
            priorities.job_contest([], REORDERED), priorities.Contest(None, (), "")
        )

    def test_the_goal_pass_holds_back_the_waiting_goals_job_actions(self):
        loop = body_of(BRIDGE, "    async def _supervise_goals(")
        self.assertIn("contest = priorities.job_contest(", loop)
        self.assertIn("await self._priority_order())", loop)
        self.assertIn("type(action) in _JOB_GOAL_ACTIONS", loop)
        self.assertIn('row.get("id") in contest.waiting', loop)
        self.assertIn(
            "_JOB_GOAL_ACTIONS = (goals.DriveDungeon, goals.DriveSkill)", BRIDGE
        )

    def test_a_failed_read_keeps_the_last_order(self):
        bridge = _import_bridge()

        class Holder:
            _priority_order = bridge.Bridge._priority_order

        held = Holder()
        held._priorities = REORDERED
        with (
            mock.patch.object(
                bridge, "_fetch_priority_order", side_effect=OSError("gone")
            ),
            mock.patch.object(bridge.log, "exception"),
        ):
            got = asyncio.run(held._priority_order())
        self.assertEqual(got, REORDERED)
        with mock.patch.object(
            bridge,
            "_fetch_priority_order",
            return_value=(priorities.DEFAULT_ORDER, priorities.STORED),
        ):
            got = asyncio.run(held._priority_order())
        self.assertEqual(got, priorities.DEFAULT_ORDER)
        self.assertEqual(held._priorities, priorities.DEFAULT_ORDER)


class TheReorderGoesThroughTheDecreeWritePath(unittest.TestCase):
    def run_order(self, body, script=None):
        cursor = FakeCursor(script)
        conn = FakeConn(cursor)
        planned = decree.plan_order(body, roster())
        self.assertEqual(planned.refusal, "", body)
        with mock.patch.object(map_server, "_connect", return_value=conn):
            changed = map_server._apply_order(planned)
        self.assertTrue(conn.closed)
        return planned, cursor, changed

    def test_the_card_is_a_decree_section_that_names_its_road(self):
        section = next(s for s in decree.SECTIONS if s.key == decree.PRIORITIES)
        self.assertEqual(section.writes, decree.PRIORITY_STORE)
        self.assertTrue(decree.can_send(decree.PRIORITIES))
        self.assertIn(decree.PRIORITIES, decree.PLANNERS)

    def test_a_reorder_is_one_upsert_attributed_to_the_console(self):
        planned, cursor, changed = self.run_order(
            {"section": decree.PRIORITIES, "order": list(REORDERED)}
        )
        self.assertEqual(planned.priorities, REORDERED)
        self.assertEqual(changed, 1)
        [(sql, params)] = cursor.calls
        self.assertEqual(sql, " ".join(priorities.UPSERT_SQL.split()))
        self.assertEqual(params, (",".join(REORDERED), map_server.WEB_SOURCE))

    def test_reset_writes_the_default_through_the_same_statement(self):
        planned, cursor, _ = self.run_order(
            {"section": decree.PRIORITIES, "reset": True}
        )
        self.assertEqual(planned.priorities, priorities.DEFAULT_ORDER)
        [(_sql, params)] = cursor.calls
        self.assertEqual(params[0], ",".join(priorities.DEFAULT_ORDER))

    def test_the_status_is_reported_the_way_every_decree_reports_it(self):
        planned = decree.plan_order(
            {"section": decree.PRIORITIES, "order": list(REORDERED)}, roster()
        )
        landed = decree.order_result(planned, 1)
        self.assertEqual(
            set(landed), {"section", "ok", "changed", "asked", "says", "note"}
        )
        self.assertTrue(landed["ok"])
        self.assertEqual(landed["asked"], 1)
        self.assertEqual(landed["note"], decree.ORDER_ALL % (1, 1))
        # Saved is not applied: the sentence says nothing in the world moved.
        self.assertIn("Nothing in the world has changed yet", landed["says"])
        self.assertIn("Dungeons, Gear up, Stay alive", landed["says"])
        same = decree.order_result(planned, 0)
        self.assertFalse(same["ok"])
        self.assertEqual(same["note"], decree.ORDER_NOTHING[decree.PRIORITIES])

    def test_the_same_order_twice_changes_nothing_and_says_so(self):
        _, _, changed = self.run_order(
            {"section": decree.PRIORITIES, "order": list(REORDERED)},
            script={"overseer_family_priorities": 0},
        )
        self.assertEqual(changed, 0)

    def test_a_realm_with_no_table_yet_changes_nothing_and_does_not_503(self):
        _, _, changed = self.run_order(
            {"section": decree.PRIORITIES, "order": list(REORDERED)},
            script={"overseer_family_priorities": MYSQL_ERROR(1146, "no table")},
        )
        self.assertEqual(changed, 0)

    def test_any_other_database_error_still_raises(self):
        planned = decree.plan_order(
            {"section": decree.PRIORITIES, "order": list(REORDERED)}, roster()
        )
        cursor = FakeCursor({"overseer_family_priorities": MYSQL_ERROR(2013, "lost")})
        with (
            mock.patch.object(map_server, "_connect", return_value=FakeConn(cursor)),
            self.assertRaises(MYSQL_ERROR),
        ):
            map_server._apply_order(planned)

    def test_the_endpoint_answers_like_every_other_decree(self):
        with mock.patch.multiple(
            map_server,
            _fetch_roster_rows=mock.DEFAULT,
            _apply_order=mock.DEFAULT,
        ) as mocks:
            mocks["_fetch_roster_rows"].return_value = roster()
            mocks["_apply_order"].return_value = 1
            handler = order(section=decree.PRIORITIES, order=list(REORDERED))
        self.assertEqual(handler.code, 200)
        self.assertEqual(handler.payload["section"], decree.PRIORITIES)
        self.assertTrue(handler.payload["ok"])
        planned = mocks["_apply_order"].call_args[0][0]
        self.assertEqual(planned.priorities, REORDERED)

    def test_the_console_reads_the_stored_order_back(self):
        fetch = SERVER[SERVER.index("def _fetch_decree") :]
        fetch = fetch[: fetch.index("def _with_family")]
        self.assertIn("rd.rows(priorities.SELECT_SQL", fetch)
        self.assertIn('"priority_rows": priority_rows', fetch)
        page = decree.build_console(roster(), [], priority_rows=[])
        self.assertEqual(page["priorities"]["order"], list(priorities.DEFAULT_ORDER))
        self.assertEqual(page["priorities"]["state"], priorities.UNSET)
        self.assertEqual(page["priorities"]["section"], decree.PRIORITIES)
        self.assertTrue(page["priorities"]["takes_effect"])

    def test_the_bridge_creates_the_table(self):
        ensure = BRIDGE[BRIDGE.index("def _ensure_queue_store") :]
        ensure = ensure[: ensure.index("def _fetch_priority_order")]
        self.assertIn("cur.execute(priorities.CREATE_SQL)", ensure)


if __name__ == "__main__":
    unittest.main()
