"""Free-phrased Discord orders through the local model (#1501).

The model is faked with a canned reply. Each tool call must become exactly the
directive the typed fixed form produces, and anything unknown writes nothing.
"""

import asyncio
import types
import unittest

from test_campaign_queue import FakeWorld, _load, _Log

import campaignqueue  # noqa: E402
import core  # noqa: E402
import freeorders  # noqa: E402
import llmmode  # noqa: E402

FAMS = {
    "Zug": {"leader": {}, "names": ["Zug", "Ogg"]},
    "Grug": {"leader": {}, "names": ["Grug", "Bork"]},
}
SRC = "discord:7"


def decide(reply, said="x"):
    return freeorders.decisions(reply, said, SRC, FAMS)


class TheTools(unittest.TestCase):
    def test_run_a_dungeon_until_an_item_drops_is_the_typed_queue_order(self):
        out, heard = decide(
            '{"tool":"campaign","family":"zug","dungeon":"deadmines","runs":0,'
            '"item":"Red Defias Mask"}'
        )
        typed = core.parse_directive(
            "queue Zug: deadmines until Red Defias Mask drops",
            "7",
            {"7"},
            dedicated=True,
        )
        self.assertEqual(typed, out)
        self.assertEqual("queue Zug: deadmines until Red Defias Mask drops", heard)

    def test_run_a_dungeon_n_times_is_the_typed_queue_order(self):
        out, _ = decide(
            '{"tool":"campaign","family":"Grug","dungeon":"ragefire","runs":5}'
        )
        typed = core.parse_directive(
            "queue Grug: ragefire 5", "7", {"7"}, dedicated=True
        )
        self.assertEqual(typed, out)

    def test_go_level_a_member_is_the_typed_goal_order(self):
        out, heard = decide('{"tool":"level","member":"bork","level":40}')
        typed = core.parse_directive("@Bork reach level 40", "7", {"7"}, dedicated=True)
        self.assertEqual(typed, out)
        self.assertEqual("@Bork reach level 40", heard)

    def test_a_reply_after_thinking_aloud_uses_the_last_object(self):
        out, _ = decide('I think {"a":1} so {"tool":"level","member":"Ogg","level":30}')
        self.assertEqual([core.NLDirective("Ogg", "reach level 30", SRC)], out)


class TheRefusals(unittest.TestCase):
    def assertWritesNothing(self, out):
        self.assertTrue(out)
        self.assertTrue(all(isinstance(d, core.Reply) for d in out), out)

    def test_an_unknown_member_asks_and_writes_nothing(self):
        out, heard = decide('{"tool":"level","member":"Nobody","level":40}')
        self.assertWritesNothing(out)
        self.assertEqual("", heard)
        self.assertIn("Nobody", out[0].text)

    def test_an_unknown_family_asks_and_writes_nothing(self):
        out, _ = decide(
            '{"tool":"campaign","family":"Thrak","dungeon":"ragefire","runs":5}'
        )
        self.assertWritesNothing(out)
        self.assertIn("Thrak", out[0].text)

    def test_a_level_out_of_range_writes_nothing(self):
        out, _ = decide('{"tool":"level","member":"Ogg","level":99}')
        self.assertWritesNothing(out)

    def test_a_farm_phrasing_is_refused_in_words_before_and_after_the_model(self):
        out, _ = freeorders.decisions("{}", "farm linen cloth", SRC, FAMS)
        self.assertEqual([core.Reply(freeorders.FARM_REFUSAL)], out)
        out, _ = decide('{"tool":"farm","target":"linen"}')
        self.assertEqual([core.Reply(freeorders.FARM_REFUSAL)], out)

    def test_the_ask_tool_relays_the_question_and_writes_nothing(self):
        out, _ = decide('{"tool":"ask","question":"Which dungeon?"}')
        self.assertWritesNothing(out)
        self.assertIn("Which dungeon?", out[0].text)

    def test_an_unreadable_reply_or_an_unknown_tool_writes_nothing(self):
        for raw in ("no json here", '{"tool":"delete everything"}', ""):
            self.assertWritesNothing(decide(raw)[0])

    def test_chatter_is_not_sent_to_the_model(self):
        out = core.parse_directive("what a lovely evening", "7", {"7"}, dedicated=True)
        self.assertIsInstance(out[0], core.Reply)

    def test_an_order_shaped_sentence_becomes_a_free_order_only_in_the_channel(self):
        text = "run Deadmines until the mask drops"
        out = core.parse_directive(text, "7", {"7"}, dedicated=True)
        self.assertEqual([core.FreeOrder(text, SRC)], out)
        self.assertEqual([], core.parse_directive(text, "7", {"7"}, dedicated=False))


class TheBridgeMethod(unittest.TestCase):
    def run_order(self, text, reply, llm_off=False):
        sent, acted = [], []

        class Channel:
            async def send(self, line):
                sent.append(line)

        async def call(fn, prompt, system=""):
            if llm_off:
                raise llmmode.LLMOff("LLM_MODE=off")
            return reply

        async def act_on(decision, channel):
            acted.append(decision)

        world = FakeWorld([])
        ns = _load(
            ["_free_order"],
            {
                "asyncio": asyncio,
                "campaignqueue": campaignqueue,
                "core": core,
                "freeorders": freeorders,
                "log": _Log(),
                "llmpool": types.SimpleNamespace(call=call),
                "_ask_llm": lambda *a: "",
                "_fetch_queue_roster": world.fetch_roster,
            },
        )
        me = types.SimpleNamespace(_act_on=act_on)
        asyncio.run(ns["_free_order"](me, core.FreeOrder(text, SRC), Channel()))
        return sent, acted

    def test_a_campaign_reply_is_acted_on_as_the_queue_directive(self):
        sent, acted = self.run_order(
            "run ragefire 5 times",
            '{"tool":"campaign","family":"Zug","dungeon":"ragefire","runs":5}',
        )
        self.assertEqual([core.QueueDirective("Zug", "ragefire 5", SRC)], acted)
        self.assertIn("Understood as: queue Zug: ragefire 5", sent[0])

    def test_with_the_model_off_nothing_is_acted_on_and_the_channel_is_told(self):
        sent, acted = self.run_order("run ragefire 5 times", "", llm_off=True)
        self.assertEqual([], acted)
        self.assertEqual([freeorders.NOT_UNDERSTOOD[:1990]], sent)

    def test_a_farm_order_never_reaches_the_model(self):
        sent, acted = self.run_order("farm linen cloth", "boom", llm_off=True)
        self.assertEqual([], acted)
        self.assertEqual([freeorders.FARM_REFUSAL], sent)


if __name__ == "__main__":
    unittest.main()
