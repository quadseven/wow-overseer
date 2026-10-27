"""Every Discord order the bridge acted on is recorded (#1499).

quadseven/mod-overseer#150 asks that every order is queryable afterwards:
who gave it, what was said, what was written. The bridge's three Discord
writers (the campaign queue, a goal, a family job) each leave one
`overseer_order` row after their own rows land, and nothing else does.

The handlers run here out of bridge.py's own source against fake writers;
no test touches a database.
"""

import ast
import asyncio
import contextvars
import json
import pathlib
import types
import unittest

from test_decree_order import FakeConn, FakeCursor  # noqa: F401 - sets up the pymysql stub

import campaignqueue  # noqa: E402
import core  # noqa: E402
import craft  # noqa: E402
import goals  # noqa: E402
import jobs  # noqa: E402
import orderrecord  # noqa: E402
import raidprep  # noqa: E402
import standin  # noqa: E402
import trainjob  # noqa: E402
from test_campaign_queue import ORDER, FakeWorld, roster_rows  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent.parent
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")
DOCKERFILE = (HERE / "Dockerfile").read_text(encoding="utf-8")

TYPED = "queue Zug: ragefire 50 times, then wailing caverns 50 times"


def _function(name):
    for node in ast.walk(ast.parse(BRIDGE)):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == name
        ):
            return node
    raise AssertionError("%s not found in bridge.py" % name)


def _load(names, namespace):
    module = ast.Module(body=[_function(n) for n in names], type_ignores=[])
    exec(compile(module, "bridge.py", "exec"), namespace)  # noqa: S102 - bridge.py's own source
    return namespace


class _Log:
    def __init__(self):
        self.lines = []

    def info(self, msg, *a, **k):
        self.lines.append(msg % a if a else msg)

    warning = exception = info


class _Channel:
    id = 555

    def __init__(self):
        self.sent = []

    async def send(self, line):
        self.sent.append(line)


class _Store:
    """overseer_order as the bridge's _insert_order sees it."""

    def __init__(self, fail=False):
        self.records = []
        self.fail = fail

    def insert(self, record):
        if self.fail:
            raise RuntimeError("the database went away")
        self.records.append(record)
        return len(self.records)


def _namespace(store, log, **extra):
    return {
        "asyncio": asyncio,
        "core": core,
        "orderrecord": orderrecord,
        "log": log,
        "_HEARD": contextvars.ContextVar("heard_order_text", default=""),
        "_insert_order": store.insert,
        **extra,
    }


def _run(ns, typed, coro_factory):
    async def heard():
        ns["_HEARD"].set(typed)
        await coro_factory()

    asyncio.run(heard())


# --- the pure record ------------------------------------------------------------


class TheRecord(unittest.TestCase):
    def test_a_discord_order_that_wrote_rows_is_recorded(self):
        rec = orderrecord.build(
            orderrecord.QUEUE,
            "discord:7",
            "queue Zug: ragefire 50",
            555,
            orderrecord.ids("overseer_dungeon_queue", [41, 42]),
        )
        self.assertEqual("discord:7", rec.author)
        self.assertEqual("555", rec.channel_id)
        self.assertEqual(
            [
                {"table": "overseer_dungeon_queue", "key": "id=41"},
                {"table": "overseer_dungeon_queue", "key": "id=42"},
            ],
            json.loads(rec.rows_json()),
        )
        self.assertEqual(
            ("555", "discord:7", "queue Zug: ragefire 50", "queue", rec.rows_json()),
            rec.params(),
        )

    def test_an_order_that_wrote_nothing_is_not_recorded(self):
        self.assertIsNone(
            orderrecord.build(orderrecord.JOB, "discord:7", "job farm", 1, ())
        )

    def test_an_automatic_write_is_not_an_order(self):
        self.assertIsNone(
            orderrecord.build(
                orderrecord.JOB,
                "overseer:craft_rhythm",
                "",
                None,
                orderrecord.ids("overseer_command", [3]),
            )
        )

    def test_long_text_is_cut_to_the_column(self):
        rec = orderrecord.build(
            orderrecord.GOAL,
            "discord:7",
            "x" * 5000,
            "",
            (orderrecord.Written("overseer_goal", "id=1"),),
        )
        self.assertEqual(orderrecord.MAX_TEXT, len(rec.params()[2]))

    def test_a_missing_id_is_not_a_row(self):
        self.assertEqual(
            (orderrecord.Written("t", "id=4"),), orderrecord.ids("t", [0, None, 4])
        )

    def test_the_table_has_the_columns_the_insert_names(self):
        for column in (
            "channel_id",
            "author",
            "text",
            "kind",
            "rows_written",
            "created_at",
        ):
            self.assertIn(column + " ", orderrecord.CREATE_SQL)
        self.assertIn(
            "(channel_id, author, text, kind, rows_written)", orderrecord.INSERT_SQL
        )


# --- the queue order --------------------------------------------------------------


class AQueueOrder(unittest.TestCase):
    def run_order(self, family, text, store=None):
        world = FakeWorld([])
        store = store or _Store()
        log = _Log()
        channel = _Channel()

        def write_queue(plan, source, new_ids=None):
            new_ids.extend(range(41, 41 + len(plan.entries)))
            return len(plan.entries)

        async def queue_once():
            return None

        ns = _load(
            ["_set_queue", "_note_order"],
            _namespace(
                store,
                log,
                campaignqueue=campaignqueue,
                _fetch_queue_roster=world.fetch_roster,
                _fetch_queue_rows=world.fetch_queue,
                _queue_level_rows=lambda fam: [
                    dict(r, lead=int(r["name"] == fam["leader"]["name"]))
                    for r in roster_rows()
                    if r["name"] in fam["names"]
                ],
                _write_queue=write_queue,
            ),
        )
        me = types.SimpleNamespace(_campaign_queue_once=queue_once)
        _run(
            ns,
            TYPED,
            lambda: ns["_set_queue"](
                me, core.QueueDirective(family, text, "discord:7"), channel
            ),
        )
        return store.records, channel.sent, log.lines

    def test_who_what_and_which_rows(self):
        records, sent, _ = self.run_order("Zug", ORDER)
        self.assertEqual(1, len(records))
        rec = records[0]
        self.assertEqual(
            ("discord:7", TYPED, "queue", "555"),
            (rec.author, rec.text, rec.kind, rec.channel_id),
        )
        self.assertEqual(
            [
                {"table": "overseer_dungeon_queue", "key": "id=41"},
                {"table": "overseer_dungeon_queue", "key": "id=42"},
            ],
            json.loads(rec.rows_json()),
        )
        self.assertIn("Ragefire Chasm 50, then Wailing Caverns 50", sent[0])

    def test_a_refused_order_leaves_no_record(self):
        records, sent, _ = self.run_order("Zug", "ragefire 50, stockades 5")
        self.assertEqual([], records)
        self.assertIn("other faction's capital", sent[0])

    def test_a_record_that_cannot_be_written_does_not_stop_the_order(self):
        records, sent, lines = self.run_order("Zug", ORDER, _Store(fail=True))
        self.assertEqual([], records)
        self.assertIn("Ragefire Chasm 50, then Wailing Caverns 50", sent[0])
        self.assertTrue(
            any("carried out but not recorded" in ln for ln in lines), lines
        )


# --- the goal order ----------------------------------------------------------------


class AGoalOrder(unittest.TestCase):
    def run_order(self, text, cancelled=0):
        store, log, channel = _Store(), _Log(), _Channel()
        ns = _load(
            ["_maybe_handle_goal", "_note_order"],
            _namespace(
                store,
                log,
                goals=goals,
                _insert_goal=lambda name, goal, channel_id: 77,
                _cancel_goals=lambda name: cancelled,
                _insert_thought=lambda *a: None,
            ),
        )
        _run(
            ns,
            "Ugga, " + text,
            lambda: ns["_maybe_handle_goal"](
                types.SimpleNamespace(),
                core.NLDirective("Ugga", text, "discord:7"),
                channel,
            ),
        )
        return store.records, channel.sent

    def test_a_goal_is_recorded_with_its_row(self):
        records, _ = self.run_order("reach level 20")
        self.assertEqual(1, len(records))
        self.assertEqual(
            ("goal", "Ugga, reach level 20"), (records[0].kind, records[0].text)
        )
        self.assertEqual(
            [{"table": "overseer_goal", "key": "id=77"}],
            json.loads(records[0].rows_json()),
        )

    def test_a_cancel_is_recorded_with_what_it_cancelled(self):
        records, _ = self.run_order("forget your goals", cancelled=2)
        self.assertEqual(
            [{"table": "overseer_goal", "key": "character=Ugga cancelled=2"}],
            json.loads(records[0].rows_json()),
        )

    def test_a_cancel_that_found_nothing_is_not_recorded(self):
        records, sent = self.run_order("forget your goals", cancelled=0)
        self.assertEqual([], records)
        self.assertEqual(1, len(sent))


# --- the job order -----------------------------------------------------------------


class AJobOrder(unittest.TestCase):
    def run_order(self, source):
        store, log, channel = _Store(), _Log(), _Channel()
        names = ["Zug", "Oz", "Uzza"]
        ids = iter([301, 302, 303])
        ns = _load(
            ["_set_job", "_note_order"],
            _namespace(
                store,
                log,
                jobs=jobs,
                trainjob=trainjob,
                craft=craft,
                raidprep=raidprep,
                standin=standin,
                _fetch_enabled_names=lambda: list(names),
                _standin_running=lambda ns_: list(ns_),
                _insert_job=lambda name, mode, src: next(ids),
            ),
        )

        async def no(*a):
            return False

        async def ready(*a):
            return ""

        me = types.SimpleNamespace(_queue_holds_job=no, _job_not_ready=ready)
        _run(
            ns,
            "job quest",
            lambda: ns["_set_job"](
                me, core.JobDirective(jobs.DEFAULT, source), channel
            ),
        )
        return store.records, channel.sent

    def test_a_job_order_records_one_row_per_member_told(self):
        records, sent = self.run_order("discord:7")
        self.assertEqual(1, len(records))
        self.assertEqual(("job", "job quest"), (records[0].kind, records[0].text))
        self.assertEqual(
            ["id=301", "id=302", "id=303"],
            [r["key"] for r in json.loads(records[0].rows_json())],
        )
        self.assertIn("(3/3 of the family told)", sent[-1])

    def test_an_automatic_job_write_is_not_recorded(self):
        records, _ = self.run_order("overseer:craft_rhythm")
        self.assertEqual([], records)


# --- the wiring --------------------------------------------------------------------


class TheWiring(unittest.TestCase):
    def test_the_words_are_kept_before_the_message_is_parsed(self):
        body = ast.get_source_segment(BRIDGE, _function("on_message"))
        self.assertIn('_HEARD.set(message.content or "")', body)
        self.assertLess(body.index("_HEARD.set("), body.index("core.parse_directive("))

    def test_the_store_is_created_at_start_up(self):
        body = ast.get_source_segment(BRIDGE, _function("_ensure_stores"))
        self.assertIn("_ensure_order_store,", body)

    def test_each_discord_writer_records(self):
        for name, kind in (
            ("_set_queue", "QUEUE"),
            ("_maybe_handle_goal", "GOAL"),
            ("_set_job", "JOB"),
        ):
            body = ast.get_source_segment(BRIDGE, _function(name))
            self.assertIn("orderrecord.%s" % kind, body, name)

    def test_the_module_ships_in_the_image(self):
        self.assertIn(" orderrecord.py", DOCKERFILE)


if __name__ == "__main__":
    unittest.main()
