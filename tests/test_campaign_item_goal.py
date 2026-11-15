"""Item-goal queue orders resolve before writing and stop on owned loot."""

import unittest

import campaignqueue as queue


class ItemGoalParsing(unittest.TestCase):
    def test_named_item_keeps_punctuation_and_defaults_to_ceiling(self):
        entries, refusal = queue.parse_entries(
            "deadmines until Cookie's Stirring Rod drops"
        )
        self.assertEqual("", refusal)
        self.assertEqual("deadmines", entries[0].keyword)
        self.assertEqual(queue.RUNS_CEILING, entries[0].runs)
        self.assertEqual("Cookie's Stirring Rod", entries[0].item_name)

    def test_optional_ceiling_and_item_with_and_do_not_split_the_item(self):
        entries, refusal = queue.parse_entries(
            "deadmines 5 until Band of Fire and Ice drops"
        )
        self.assertEqual("", refusal)
        self.assertEqual(5, entries[0].runs)
        self.assertEqual("Band of Fire and Ice", entries[0].item_name)

    def test_resolution_prefers_exact_case_insensitive_match(self):
        entry = queue.parse_entries("deadmines until blue ring drops")[0][0]
        resolved, refusal = queue.resolve_items(
            (entry,),
            {
                "blue ring": [
                    {"entry": 123, "name": "Blue Ring"},
                    {"entry": 124, "name": "Large Blue Ring"},
                ]
            },
        )
        self.assertEqual("", refusal)
        self.assertEqual(123, resolved[0].goal_item)

    def test_ambiguous_or_unknown_items_produce_no_partial_plan(self):
        entry = queue.parse_entries("deadmines until ring drops")[0][0]
        for candidates in (
            [],
            [{"entry": 123, "name": "Blue Ring"}, {"entry": 124, "name": "Red Ring"}],
        ):
            with self.subTest(candidates=candidates):
                resolved, refusal = queue.resolve_items((entry,), {"ring": candidates})
                self.assertEqual((), resolved)
                self.assertTrue(refusal)
                if candidates:
                    self.assertIn("123", refusal)
                    self.assertIn("124", refusal)


class ItemGoalCompletion(unittest.TestCase):
    def test_owned_target_completes_active_entry_before_run_ceiling(self):
        rows = [
            {
                "id": 7,
                "keyword": "deadmines",
                "runs_wanted": 50,
                "status": "active",
                "goal_item": 123,
            }
        ]
        leader = {"job": "dungeon:deadmines", "dungeon_runs_done": 1}
        self.assertFalse(queue.step(rows, leader, owned_items=set()).writes)
        move = queue.step(rows, leader, owned_items={123})
        self.assertEqual(7, move.finish)
        self.assertTrue(move.quest)
        self.assertIn("123", move.why)

    def test_no_item_read_does_not_finish_early_but_run_cap_still_applies(self):
        rows = [
            {
                "id": 7,
                "keyword": "deadmines",
                "runs_wanted": 5,
                "status": "active",
                "goal_item": 123,
            }
        ]
        self.assertFalse(
            queue.step(
                rows, {"job": "dungeon:deadmines", "dungeon_runs_done": 1}
            ).writes
        )
        self.assertEqual(7, queue.step(rows, {"dungeon_runs_done": 5}).finish)


class BridgeItemGoal(unittest.TestCase):
    def test_discord_resolves_before_write_and_echoes_ids(self):
        from test_campaign_queue import TheDiscordOrder
        from unittest.mock import patch
        import test_campaign_queue

        original = test_campaign_queue._load

        def load(names, namespace):
            namespace["_queue_item_candidates"] = lambda entries: {
                "Blue Ring": [{"entry": 123, "name": "Blue Ring"}]
            }
            return original(names, namespace)

        with patch.object(test_campaign_queue, "_load", load):
            written, sent, _ = TheDiscordOrder().run_order(
                "Grug", "deadmines until Blue Ring drops"
            )
        self.assertEqual(123, written[0][0].entries[0].goal_item)
        self.assertIn("item 123", sent[0])
        self.assertIn("deadmines", sent[0])

    def test_unknown_item_preserves_existing_queue(self):
        from test_campaign_queue import TheDiscordOrder
        from unittest.mock import patch
        import test_campaign_queue

        original = test_campaign_queue._load

        def load(names, namespace):
            namespace["_queue_item_candidates"] = lambda entries: {"Missing": []}
            return original(names, namespace)

        with patch.object(test_campaign_queue, "_load", load):
            written, sent, passes = TheDiscordOrder().run_order(
                "Grug", "deadmines until Missing drops"
            )
        self.assertEqual([], written)
        self.assertEqual([], passes)
        self.assertIn("Which item", sent[0])

    def test_queue_pass_finishes_owned_item_only_once(self):
        from test_campaign_queue import FakeWorld, _queue_pass

        sent = []

        class Channel:
            async def send(self, text):
                sent.append(text)

        world = FakeWorld(
            [
                {
                    "id": 7,
                    "family": "Zug",
                    "position": 0,
                    "keyword": "ragefire",
                    "runs_wanted": 50,
                    "status": "active",
                    "goal_item": 123,
                }
            ]
        )
        calls = []

        def holdings(family, target):
            calls.append((family, target))
            return {123}

        for _ in range(2):
            _queue_pass(
                world,
                extra={"_queue_owned_items": holdings},
                _rhythm_channel=lambda: Channel(),
            )
        self.assertEqual([("Zug", 123)], calls)
        self.assertEqual("done", world.queue[0]["status"])
        self.assertEqual([], sent)  # The durable notice drain owns delivery.
        self.assertEqual({"quest"}, {r["job"] for r in world.family("Zug")})

    def test_reader_includes_personal_bank_but_excludes_other_owners(self):
        from test_campaign_queue import _load

        calls = []

        class Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def execute(self, sql, params):
                calls.append((sql, params))

            def fetchall(self):
                return [{"entry": 123}]

            def cursor(self):
                return self

        ns = _load(["_queue_owned_items"], {"_connect": Cursor})
        self.assertEqual({123}, ns["_queue_owned_items"]("Family", 123))
        sql, params = calls[0]
        self.assertEqual(("Family", 123), params)
        self.assertIn("r.enabled = 1", sql)
        self.assertIn("ii.owner_guid = c.guid", sql)
        self.assertIn("ci.guid = c.guid", sql)
        self.assertNotIn("ci.slot", sql)

    def test_goal_writer_persists_item_in_queue_row(self):
        from test_campaign_queue import _load

        calls = []

        class Cursor:
            rowcount = 1
            lastrowid = 9

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def execute(self, sql, params):
                calls.append((sql, params))

            def cursor(self):
                return self

        ns = _load(["_write_queue"], {"_connect": Cursor, "campaignqueue": queue})
        entry = queue.Entry("deadmines", 5, goal_item=123, item_name="Blue Ring")
        plan = queue.Plan("Family", "", (entry,), False, "")
        ids = []
        ns["_write_queue"](plan, "discord:7", ids)
        self.assertEqual([9], ids)
        self.assertEqual(queue.ITEM_INSERT_SQL, calls[-1][0])
        self.assertEqual(("Family", 0, "deadmines", 5, "discord:7", 123), calls[-1][1])

    def test_store_migrates_old_table_once(self):
        from test_campaign_queue import _load, _Log
        import types

        calls = []

        class Cursor:
            migrated = set()
            column = ""

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def execute(self, sql, params=()):
                calls.append(sql)
                if params:
                    self.column = params[0]
                if sql.startswith("ALTER TABLE"):
                    self.migrated.add(self.column)

            def fetchone(self):
                return {"n": int(self.column in self.migrated)}

            def cursor(self):
                return self

        cursor = Cursor()
        ns = _load(
            ["_ensure_queue_store"],
            {
                "_connect": lambda: cursor,
                "campaignqueue": queue,
                "log": _Log(),
                "pymysql": types.SimpleNamespace(
                    err=types.SimpleNamespace(MySQLError=RuntimeError)
                ),
                "dungeonpace": types.SimpleNamespace(CREATE_SQL="pace"),
                "priorities": types.SimpleNamespace(CREATE_SQL="priorities"),
                "operatorhold": types.SimpleNamespace(CREATE_SQL="operatorhold"),
            },
        )
        ns["_ensure_queue_store"]()
        ns["_ensure_queue_store"]()
        # Two queue columns and the three the trade turn table gained.
        self.assertEqual(5, sum(sql.startswith("ALTER TABLE") for sql in calls))
        self.assertIn("goal_item", queue.CREATE_SQL)
        self.assertIn("goal_item", queue.SELECT_PENDING_SQL)

    def test_failed_inventory_read_does_not_stop_the_other_family(self):
        from test_campaign_queue import FakeWorld, _queue_pass

        world = FakeWorld(
            [
                {
                    "id": 7,
                    "family": "Grug",
                    "position": 0,
                    "keyword": "deadmines",
                    "runs_wanted": 50,
                    "status": "active",
                    "goal_item": 123,
                },
                {
                    "id": 8,
                    "family": "Zug",
                    "position": 0,
                    "keyword": "ragefire",
                    "runs_wanted": 5,
                    "status": "queued",
                },
            ]
        )

        from _stub_modules import PYMYSQL as pymysql

        def broken_read(*args):
            raise pymysql.err.OperationalError(2003, "database unavailable")

        _queue_pass(
            world, extra={"_queue_owned_items": broken_read, "pymysql": pymysql}
        )
        self.assertEqual("active", world.queue[0]["status"])
        self.assertEqual("active", world.queue[1]["status"])

    def test_cancelled_item_goal_cannot_change_family_jobs(self):
        from test_campaign_queue import _load, _Log
        import jobs

        jobs_written = []
        ns = _load(
            ["_apply_queue_move"],
            {
                "campaignqueue": queue,
                "jobs": jobs,
                "log": _Log(),
                "_mark_queue": lambda *args: 0,
                "_insert_job": lambda *args: jobs_written.append(args),
            },
        )
        move = queue.step(
            [
                {
                    "id": 7,
                    "keyword": "deadmines",
                    "runs_wanted": 50,
                    "status": "active",
                    "goal_item": 123,
                }
            ],
            {"dungeon_runs_done": 1},
            owned_items={123},
        )
        self.assertIn("withheld", ns["_apply_queue_move"](move, ["Member"], "Family"))
        self.assertEqual([], jobs_written)

    def test_notice_retries_failure_and_never_acks_a_missing_channel(self):
        from test_campaign_queue import _load, _Log
        import asyncio
        import types

        sent, ack = [], []
        notice = {"id": 7, "family": "Family", "keyword": "deadmines", "goal_item": 123}

        class Channel:
            fails = True

            async def send(self, text):
                if self.fails:
                    raise RuntimeError("channel unavailable")
                sent.append(text)

        channel = Channel()
        me = types.SimpleNamespace(get_channel=lambda _: channel)
        ns = _load(
            ["_send_queue_item_notices"],
            {
                "asyncio": asyncio,
                "campaignqueue": queue,
                "OVERSEER_CHANNEL_ID": "7",
                "log": _Log(),
                "_queue_item_notices": lambda: [notice],
                "_mark_queue": lambda sql, qid: ack.append((sql, qid)),
                "pymysql": types.SimpleNamespace(
                    err=types.SimpleNamespace(MySQLError=RuntimeError)
                ),
            },
        )
        asyncio.run(ns["_send_queue_item_notices"](me))
        self.assertEqual([], ack)
        me.get_channel = lambda _: None
        asyncio.run(ns["_send_queue_item_notices"](me))
        self.assertEqual([], ack)
        me.get_channel = lambda _: channel
        channel.fails = False
        asyncio.run(ns["_send_queue_item_notices"](me))
        self.assertEqual([(queue.ACK_ITEM_NOTICE_SQL, 7)], ack)
        self.assertIn("item 123", sent[0])

    def test_already_owned_item_does_not_start_an_extra_run(self):
        row = {
            "id": 7,
            "keyword": "deadmines",
            "runs_wanted": 50,
            "status": "queued",
            "goal_item": 123,
        }
        move = queue.step([row], None, owned_items={123})
        self.assertEqual(7, move.finish)
        self.assertEqual(0, move.start)
        self.assertTrue(move.quest)
        self.assertEqual(123, move.acquired_item)

    def test_programming_fault_in_ownership_reader_is_not_a_transient_hold(self):
        from test_campaign_queue import FakeWorld, _queue_pass
        from _stub_modules import PYMYSQL as pymysql

        world = FakeWorld(
            [
                {
                    "id": 7,
                    "family": "Grug",
                    "position": 0,
                    "keyword": "deadmines",
                    "runs_wanted": 50,
                    "status": "active",
                    "goal_item": 123,
                }
            ]
        )

        def broken_read(*args):
            raise NameError("reader defect")

        with self.assertRaisesRegex(NameError, "reader defect"):
            _queue_pass(
                world, extra={"_queue_owned_items": broken_read, "pymysql": pymysql}
            )
