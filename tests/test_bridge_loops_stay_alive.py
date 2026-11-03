"""A forever-loop in the bridge keeps running, or says why it stopped.

Three ways a pass went quiet with nothing in the log, and the model's
system line, which was asked for and dropped:

- setup_hook holds every task so it is never collected, which also means
  asyncio never reports an exception that escapes one; `_pass_done` logs it.
- `_poll_outcomes` sent each reply outside its try, so one channel gone or
  one line Discord refused ended outcome reporting for every later order.
- Two async handlers called a reader that opens the database inline, which
  froze the event loop (heartbeats, the chat relay, every other pass) for as
  long as the query took; both go through `asyncio.to_thread` now.
- `_ask_llm` took a `system` line and sent its JSON-only default instead, so
  the persona lines were asked for as a JSON object (persona.clean unwraps
  the result, which is how it stayed unnoticed).

bridge.py imports discord, which the suite does not install; it is imported
under a stub the way test_llm_mode does it.
"""

import ast
import asyncio
import json
import pathlib
import types
import unittest
from unittest import mock

from _stub_modules import PYMYSQL, fresh_import

HERE = pathlib.Path(__file__).resolve().parent.parent
SOURCE = (HERE / "bridge.py").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def _import_bridge():
    stub = types.ModuleType("discord")

    class Client:
        def __init__(self, *args, **kwargs):
            pass

    stub.Client = Client
    return fresh_import("bridge", discord=stub, pymysql=PYMYSQL)


bridge = _import_bridge()


def _function(name):
    for node in ast.walk(TREE):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == name
        ):
            return node
    raise AssertionError(f"{name} not found in bridge.py")


def _calls_to(fn, callee):
    """Every Call node in `fn` whose callee is the plain name `callee`, with
    whether it sits inside `asyncio.to_thread(...)` as its first argument."""
    found = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Name) and f.id == callee:
            found.append((node.lineno, False))
        elif (
            isinstance(f, ast.Attribute)
            and f.attr == "to_thread"
            and node.args
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == callee
        ):
            found.append((node.lineno, True))
    return found


class ADeadPassIsLogged(unittest.TestCase):
    def test_an_exception_that_escapes_a_pass_is_an_error_line(self):
        async def pass_that_dies():
            raise RuntimeError("the read raised on the first cycle")

        async def run():
            task = asyncio.create_task(pass_that_dies())
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            return task

        task = asyncio.run(run())
        with self.assertLogs(bridge.log, "ERROR") as logged:
            bridge.Bridge._pass_done(None, task)
        self.assertEqual(len(logged.records), 1)
        self.assertIn("pass_that_dies", logged.output[0])
        self.assertIn("will not run again", logged.output[0])
        self.assertIsInstance(logged.records[0].exc_info[1], RuntimeError)

    def test_a_cancelled_pass_is_not_an_error(self):
        async def run():
            task = asyncio.create_task(asyncio.sleep(60))
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.sleep(0)
            return task

        task = asyncio.run(run())
        with mock.patch.object(bridge.log, "error") as error:
            bridge.Bridge._pass_done(None, task)
        error.assert_not_called()


class TheOutcomeReplyIsSentUnderTry(unittest.TestCase):
    def test_channel_send_sits_inside_a_try_that_logs(self):
        fn = _function("_poll_outcomes")
        sends = [
            node
            for node in ast.walk(fn)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "send"
        ]
        self.assertEqual(len(sends), 1)
        guarded = [
            t
            for t in ast.walk(fn)
            if isinstance(t, ast.Try)
            and any(sends[0] is n for b in t.body for n in ast.walk(b))
        ]
        self.assertTrue(guarded, "channel.send in _poll_outcomes is not under a try")
        handlers = [h for t in guarded for h in t.handlers]
        self.assertTrue(
            any("log.exception" in ast.unparse(h) for h in handlers),
            "the except around channel.send does not log",
        )


class DatabaseReadsLeaveTheLoop(unittest.TestCase):
    """The module's own rule (its docstring): nothing calls the database from
    an async handler. These two readers open a connection inline."""

    def test_the_town_errand_reads_bag_room_off_the_loop(self):
        for handler in ("_town_errand_once", "_town_errand_start"):
            with self.subTest(handler=handler):
                calls = _calls_to(_function(handler), "_bag_errand_needed")
                self.assertTrue(calls, f"{handler} no longer asks _bag_errand_needed")
                self.assertTrue(all(off for _, off in calls), calls)

    def test_the_clearance_plan_reads_declared_trades_off_the_loop(self):
        calls = _calls_to(_function("_clearance_plan"), "_clearance_kept")
        self.assertTrue(calls)
        self.assertTrue(all(off for _, off in calls), calls)


class TheSystemLineIsSent(unittest.TestCase):
    def _sent(self, *args):
        bodies = []

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return b'{"choices": [{"message": {"content": "ok"}}]}'

        def urlopen(req, timeout=None):
            bodies.append(json.loads(req.data))
            return Response()

        with (
            mock.patch.dict(bridge.os.environ, {"LLM_MODE": "on"}),
            mock.patch.object(bridge.urllib.request, "urlopen", urlopen),
        ):
            self.assertEqual(bridge._ask_llm(*args), "ok")
        return bodies[0]["messages"]

    def test_a_caller_with_its_own_system_line_gets_it(self):
        messages = self._sent("a prompt", "Answer with the sentence only.")
        self.assertEqual(
            messages[0], {"role": "system", "content": "Answer with the sentence only."}
        )
        self.assertEqual(messages[1], {"role": "user", "content": "a prompt"})

    def test_the_default_still_asks_for_json(self):
        messages = self._sent("a prompt")
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("JSON object only", messages[0]["content"])


if __name__ == "__main__":
    unittest.main()
