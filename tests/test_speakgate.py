"""The send seam does not speak the same line twice (#2247)."""

import sys
import types
import unittest
from unittest import mock

import relay
import speakgate


def _load_bridge():
    """bridge imports discord, which CI does not install: stub the few names
    it touches at import, as the other bridge tests do."""
    for key in list(sys.modules):
        if key == "bridge" or key.startswith("discord"):
            sys.modules.pop(key, None)
    discord = types.ModuleType("discord")
    discord.Intents = type(
        "Intents",
        (),
        {"default": staticmethod(lambda: types.SimpleNamespace(message_content=False))},
    )
    discord.Client = object
    discord.app_commands = types.SimpleNamespace(
        CommandTree=lambda *_a, **_kw: object(),
        describe=lambda **_kw: lambda fn: fn,
    )
    discord.ext = types.ModuleType("discord.ext")
    discord.ext.commands = types.ModuleType("discord.ext.commands")
    sys.modules["discord"] = discord
    sys.modules["discord.ext"] = discord.ext
    sys.modules["discord.ext.commands"] = discord.ext.commands
    import bridge

    return bridge


bridge = _load_bridge()


def gate():
    return speakgate.SpeakGate(dedupe_seconds=30.0, standing_seconds=1800.0)


class AnIdenticalLineIsSentOnce(unittest.TestCase):
    def test_the_same_line_in_the_same_second_is_suppressed(self):
        g = gate()
        self.assertEqual(
            speakgate.SEND, g.check("Og", "guild", "", "LF cloth", "a", 100.0)
        )
        got = g.check("Og", "guild", "", "LF cloth", "a", 100.4)
        self.assertNotEqual(speakgate.SEND, got)
        self.assertEqual(1, g.suppressed[got])

    def test_spelling_of_the_same_line_is_one_line(self):
        g = gate()
        g.check("Og", "guild", "", "LF  Cloth", "a", 0.0)
        self.assertNotEqual(
            speakgate.SEND, g.check("og", "guild", "", "lf cloth ", "a", 1.0)
        )

    def test_after_the_window_it_is_sent_again(self):
        g = gate()
        g.check("Og", "guild", "", "hi", "a", 0.0)
        self.assertEqual(speakgate.SEND, g.check("Og", "guild", "", "hi", "a", 30.0))

    def test_another_speaker_another_channel_or_other_words_are_sent(self):
        g = gate()
        g.check("Og", "guild", "", "hi", "a", 0.0)
        for args in (
            ("Oz", "guild", "", "hi"),
            ("Og", "party", "", "hi"),
            ("Og", "guild", "", "hello"),
            ("Og", "whisper", "Oz", "hi"),
        ):
            self.assertEqual(speakgate.SEND, g.check(*args, "a", 1.0), args)


class AStandingRequestWaitsItsInterval(unittest.TestCase):
    def test_a_reagent_ask_repeats_only_after_the_standing_interval(self):
        g = gate()
        src = "overseer:craft:Grug"
        self.assertEqual(
            speakgate.SEND, g.check("Og", "party", "", "bring linen", src, 0.0)
        )
        self.assertNotEqual(
            speakgate.SEND, g.check("Og", "party", "", "bring linen", src, 600.0)
        )
        self.assertEqual(
            speakgate.SEND, g.check("Og", "party", "", "bring linen", src, 1800.0)
        )


class TheSeamCountsAndLogsWhatItHolds(unittest.TestCase):
    def test_the_second_identical_line_writes_no_row_and_is_logged(self):
        cmd = relay.SpeakCommand("Og", "guild", "LF cloth", "", "overseer:guildsocial")
        with (
            mock.patch.object(bridge, "_SPEAK_GATE", gate()),
            mock.patch.object(bridge.orders, "send", return_value=7) as send,
            mock.patch.object(bridge, "_orders_store"),
            self.assertLogs(bridge.log, "INFO") as logs,
        ):
            first = bridge._insert_speak(cmd)
            second = bridge._insert_speak(cmd)
        self.assertEqual((7, 0), (first, second))
        self.assertEqual(1, send.call_count)
        self.assertTrue(
            any("not speaking" in line and "Og" in line for line in logs.output)
        )


if __name__ == "__main__":
    unittest.main()
