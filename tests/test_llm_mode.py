"""LLM_MODE=off stops every language model call, and nothing breaks.

Both `_ask_llm` implementations are driven for real with the network patched
out: the assertion is that no request is ever opened, not that some wrapper
chose not to call a function. The callers are then driven through their own
fallbacks, because a switch that stops the calls but crashes the narrator or
500s the web chat is not an off switch.

bridge.py imports discord, which the unit suite does not install. It is
imported here under a stub that supplies only `discord.Client`, the one name
the module touches at import time, and sys.modules is restored afterwards so
no other test sees the stub.
"""

import asyncio
import logging
import os
import sys
import types
import unittest
from unittest import mock

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import events  # noqa: E402
import llmmode  # noqa: E402
import map_server  # noqa: E402
from test_chat_endpoints import SNAPSHOT, post  # noqa: E402


def _import_bridge():
    stub = types.ModuleType("discord")

    class Client:
        def __init__(self, *args, **kwargs):
            pass

    stub.Client = Client
    with mock.patch.dict(sys.modules, {"discord": stub}):
        sys.modules.pop("bridge", None)
        import bridge
    return bridge


bridge = _import_bridge()

OFF = {"LLM_MODE": "off"}


def _reset_announcement():
    llmmode._announced = False


class SwitchTest(unittest.TestCase):
    def setUp(self):
        _reset_announcement()

    def test_only_off_turns_it_off(self):
        self.assertFalse(llmmode.enabled({"LLM_MODE": "off"}))
        self.assertFalse(llmmode.enabled({"LLM_MODE": " OFF "}))
        for value in ("", "on", "0", "false", "disabled"):
            with self.subTest(value=value):
                self.assertTrue(llmmode.enabled({"LLM_MODE": value}))
        self.assertTrue(llmmode.enabled({}))

    def test_off_is_announced_once_per_process(self):
        with self.assertLogs("wow-overseer.llm", level="WARNING") as logs:
            for _ in range(3):
                with self.assertRaises(llmmode.LLMOff):
                    llmmode.check(OFF)
        self.assertEqual(len(logs.records), 1)
        self.assertIn("LLM_MODE=off", logs.output[0])


class AskLlmTest(unittest.TestCase):
    """Neither implementation opens a request while the switch is off."""

    def setUp(self):
        _reset_announcement()
        env = mock.patch.dict(os.environ, OFF)
        env.start()
        self.addCleanup(env.stop)
        logging.getLogger("wow-overseer.llm").disabled = True
        self.addCleanup(
            setattr, logging.getLogger("wow-overseer.llm"), "disabled", False
        )

    def test_the_bridge_sends_nothing(self):
        with mock.patch.object(bridge.urllib.request, "urlopen") as urlopen:
            with self.assertRaises(llmmode.LLMOff):
                bridge._ask_llm("say something")
        urlopen.assert_not_called()

    def test_the_map_server_sends_nothing(self):
        with mock.patch.object(map_server.urllib.request, "urlopen") as urlopen:
            with self.assertRaises(llmmode.LLMOff):
                map_server._ask_llm("say something")
        urlopen.assert_not_called()


class CallersDegradeTest(unittest.TestCase):
    """Each caller falls back to its plain behavior; nothing crashes."""

    def setUp(self):
        _reset_announcement()
        env = mock.patch.dict(os.environ, OFF)
        env.start()
        self.addCleanup(env.stop)
        net = mock.patch("urllib.request.urlopen")
        self.urlopen = net.start()
        self.addCleanup(net.stop)
        for name in ("wow-overseer", "wow-overseer.llm", "wow-map"):
            logger = logging.getLogger(name)
            self.addCleanup(setattr, logger, "disabled", logger.disabled)
            logger.disabled = True

    def test_a_character_speaks_its_plain_line(self):
        client = object.__new__(bridge.Bridge)
        with mock.patch.object(bridge.persona, "build_prompt", return_value="prompt"):
            said = asyncio.run(client._in_character("Grug", "We ride at dawn.", ""))
        self.assertEqual(said, "We ride at dawn.")
        self.urlopen.assert_not_called()

    def test_the_web_chat_answers_degraded_instead_of_failing(self):
        with mock.patch.multiple(
            map_server,
            _fetch_chat_grounding=mock.Mock(
                return_value={"snapshot_row": dict(SNAPSHOT), "recent": []}
            ),
            _insert_thought=mock.Mock(),
            _insert_command=mock.Mock(),
        ):
            handler = post()
        self.assertEqual(handler.code, 200)
        self.assertTrue(handler.payload["degraded"])
        self.urlopen.assert_not_called()

    def test_the_event_narrator_writes_templated_lines_without_asking(self):
        """One full cycle: every event becomes a thought, no request, no
        per-cycle traceback from a voiced path that can only raise."""
        detected = [
            events.Event("level_up", "Grug", {"level": 12}),
            events.Event("death", "Ugga", {}),
        ]
        written = []
        client = object.__new__(bridge.Bridge)
        closed = iter([False, True])

        async def ready():
            return None

        async def no_sleep(_seconds):
            return None

        client.wait_until_ready = ready
        client.is_closed = lambda: next(closed)
        with (
            mock.patch.multiple(
                bridge,
                _fetch_event_snapshot=mock.Mock(return_value=[]),
                _fetch_notable_names=mock.Mock(return_value=set()),
                _insert_thought=lambda name, kind, text: written.append(
                    (name, kind, text)
                ),
            ),
            mock.patch.object(bridge.events, "detect_events", return_value=detected),
            mock.patch.object(
                bridge.events, "filter_for_story", side_effect=lambda found, _n: found
            ),
            mock.patch.object(bridge.asyncio, "sleep", no_sleep),
            mock.patch.object(bridge.log, "exception") as logged_exception,
        ):
            asyncio.run(client._narrate_events())
        self.urlopen.assert_not_called()
        logged_exception.assert_not_called()
        self.assertEqual(
            written,
            [(e.name, "event", events.template_line(e)) for e in detected],
        )


if __name__ == "__main__":
    unittest.main()
