"""Restart-time pass dependencies, exercised without a database connection."""

import ast
import asyncio
import pathlib
import types
import unittest

SOURCE = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text()


def _function(name, namespace):
    tree = ast.parse(SOURCE)
    cls = next(node for node in tree.body
               if isinstance(node, ast.ClassDef) and node.name == "Bridge")
    method = next(node for node in cls.body
                  if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                  and node.name == name)
    module = ast.Module(body=[method], type_ignores=[])
    exec(compile(module, "bridge.py", "exec"), namespace)  # noqa: S102
    return namespace[name]


class _Log:
    def __init__(self):
        self.lines = []

    def info(self, message, *args):
        self.lines.append(message % args)


class _Reached(Exception):
    pass


class RestartPassGates(unittest.IsolatedAsyncioTestCase):
    def _bridge(self, completed):
        log = _Log()
        namespace = {
            "_pass_completed": lambda name: name in completed,
            "asyncio": asyncio,
            "log": log,
            "_family_of": lambda cohort: ([], None),
            "_PACE_QUESTING": {},
        }
        obj = types.SimpleNamespace(_waiting_for_passes=set())

        def waiting(message):
            if message not in obj._waiting_for_passes:
                log.info("%s", message)
                obj._waiting_for_passes.add(message)

        obj._log_waiting_for_pass = waiting
        return obj, namespace, log

    async def _assert_entry_gate(self, method, dependency, line):
        completed = set()
        obj, ns, log = self._bridge(completed)
        fn = _function(method, ns)
        await fn(obj)
        await fn(obj)
        self.assertEqual(log.lines, [line])
        completed.add(dependency)
        if method == "_guild_run_once":
            ns["guildrun"] = types.SimpleNamespace(limits=lambda: (_ for _ in ()).throw(_Reached()))
        else:
            ns["_family_of"] = lambda cohort: (["member"], "member")
            obj._mid_run = lambda names: asyncio.sleep(0, result=False)
            if method == "_town_errand_once":
                ns["_family_of"] = lambda cohort: (_ for _ in ()).throw(_Reached())
                with self.assertRaises(_Reached):
                    await fn(obj, _locked=True)
                return
            if method in ("_auction_once", "_bank_once", "_guild_bank_once"):
                # The lookup is the first operation after the gate; record it,
                # then stop before any planner or command writer is reached.
                ns["_family_of"] = lambda cohort: (_ for _ in ()).throw(_Reached())
        if method == "_guild_run_once":
            with self.assertRaises(_Reached):
                await fn(obj)
        else:
            with self.assertRaises(_Reached):
                await fn(obj)

    async def test_guild_run_waits_for_guild_jobs(self):
        await self._assert_entry_gate(
            "_guild_run_once", "guild_jobs",
            "guild run: waiting for the first guild jobs pass")

    async def test_bank_and_guild_bank_wait_for_guild_share(self):
        for method, line in (
            ("_bank_once", "bank: waiting for the first guild share pass"),
            ("_guild_bank_once", "guild bank: waiting for the first guild share pass"),
        ):
            await self._assert_entry_gate(method, "guild_share", line)

    async def test_auction_waits_for_guild_share(self):
        await self._assert_entry_gate(
            "_auction_once", "guild_share",
            "auction: waiting for the first guild share pass")

    async def test_town_errand_waits_for_queue_stall_read(self):
        await self._assert_entry_gate(
            "_town_errand_once", "campaign_queue",
            "town errand: waiting for the first queue pass")

    async def test_queue_preserves_quest_aims_until_dungeon_pace_runs(self):
        completed = set()
        obj, ns, log = self._bridge(completed)
        obj._family_lent_hold = lambda key, fam: asyncio.sleep(0, result=True)
        ns["campaignqueue"] = types.SimpleNamespace(
            _family=lambda key: key,
            step=lambda rows, leader: types.SimpleNamespace(writes=False, why="idle"),
        )
        aims = []

        def clear_aim(*args):
            aims.append(args)
            raise _Reached()

        ns["_aim_family_quest"] = clear_aim
        fn = _function("_campaign_queue_family_once", ns)
        family = {"names": ["member"], "leader": {"name": "member"}}
        await fn(obj, "group", [], {"group": family}, set())
        self.assertEqual(aims, [])
        self.assertEqual(log.lines, ["queue: waiting for the first dungeon pace pass"])
        completed.add("dungeon_pace")
        with self.assertRaises(_Reached):
            await fn(obj, "group", [], {"group": family}, set())
        self.assertEqual(len(aims), 1)


class GuildRunRestartClock(unittest.TestCase):
    def test_latest_persisted_formation_becomes_monotonic_time(self):
        tree = ast.parse(SOURCE)
        fn = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                  and node.name == "_guild_run_last_formed_at")
        queries = []

        class Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def execute(self, sql):
                self.sql = sql
                queries.append(sql)

            def fetchone(self):
                return {"formed": 990.0}

        class Connection:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def cursor(self):
                return Cursor()

        ns = {"_connect": Connection, "time": types.SimpleNamespace(
            monotonic=lambda: 500.0, time=lambda: 1000.0)}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), "bridge.py", "exec"), ns)  # noqa: S102
        self.assertEqual(ns["_guild_run_last_formed_at"](), 490.0)
        self.assertIn("MAX(created_at)", queries[0])


if __name__ == "__main__":
    unittest.main()
