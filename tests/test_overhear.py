"""Evan talking to the family in game rather than through Discord.

He asked the same thing several ways - "how do i talk as grug suggesting to go
to a town and sell and upgrade gear", and then, having typed exactly that into
party chat: "i just asked for the sword that dropped with +4 stamina and they
arent listening". Nothing was listening. The only ear the overseer had was a
Discord channel.
"""
import unittest

import bonds
import overhear

FAMILY = bonds.FAMILY

# What the bridge itself caused them to say. Anything else from the family in a
# shared channel is somebody at a keyboard.
AUTHORED = {"Aye.", "Then it is settled.", "Og is still 4. We should not leave them behind."}


def _row(**over):
    row = {"sender_name": "Grug", "sender_is_bot": 0, "channel": "party",
           "text": "go to town and sell your junk"}
    row.update(over)
    return row


class AddressedTest(unittest.TestCase):
    def test_a_human_in_party_chat_is_giving_an_order(self):
        self.assertTrue(overhear.is_addressed(_row(), family=FAMILY, authored=AUTHORED))

    def test_the_family_talking_among_itself_is_not(self):
        """The bridge authored those lines, so they are its own echo."""
        self.assertFalse(overhear.is_addressed(
            _row(text="Then it is settled."), family=FAMILY, authored=AUTHORED))

    def test_selfbot_does_not_silence_evan(self):
        """The bug this replaced. With SelfBotLevel 3 the AI attaches to his
        character on login, so everything he types comes back flagged as bot
        speech - the live row read sender_is_bot=1 while he was sitting there
        typing it. Authorship is the test now, and the flag is not consulted."""
        row = _row(sender_is_bot=1, text="everyone go sell your junk and repair")
        self.assertTrue(overhear.is_addressed(row, family=FAMILY, authored=AUTHORED))

    def test_a_stranger_is_not_giving_evans_orders(self):
        self.assertFalse(overhear.is_addressed(_row(sender_name="Thrall"), family=FAMILY, authored=AUTHORED))

    def test_a_whisper_is_between_two_people(self):
        """Fanning a private word out to five characters is not obedience, it
        is eavesdropping."""
        self.assertFalse(overhear.is_addressed(_row(channel="whisper"), family=FAMILY, authored=AUTHORED))

    def test_a_single_word_is_an_exclamation_not_an_instruction(self):
        self.assertFalse(overhear.is_addressed(_row(text="ouch"), family=FAMILY, authored=AUTHORED))

    def test_an_empty_line_is_not_an_order(self):
        for text in ("", "   "):
            self.assertFalse(overhear.is_addressed(_row(text=text), family=FAMILY, authored=AUTHORED))


class HearTest(unittest.TestCase):
    def test_the_last_line_wins(self):
        """If he typed twice between ticks, the later line is the one he meant.
        Acting on the first obeys a sentence he had already replaced."""
        rows = [_row(text="everyone follow me"), _row(text="actually go sell your junk")]
        d = overhear.hear(rows, family=FAMILY, authored=AUTHORED, last_at=None, now=100.0)
        self.assertEqual(d.text, "actually go sell your junk")

    def test_bot_chatter_is_stepped_over_to_find_it(self):
        rows = [_row(text="go to town and sell"), _row(sender_is_bot=1, text="Aye.")]
        d = overhear.hear(rows, family=FAMILY, authored=AUTHORED, last_at=None, now=100.0)
        self.assertEqual(d.speaker, "Grug")

    def test_nothing_to_act_on_is_not_an_error(self):
        rows = [_row(sender_is_bot=1, text="Aye.")]
        self.assertIsNone(overhear.hear(rows, family=FAMILY, authored=AUTHORED, last_at=None, now=100.0))

    def test_a_burst_of_typing_is_one_order_not_three(self):
        """Somebody typing three sentences of thought is having a conversation.
        Turning each line into a command would have the family thrash."""
        rows = [_row(text="everyone come here please")]
        self.assertIsNone(
            overhear.hear(rows, family=FAMILY, authored=AUTHORED, last_at=100.0, now=100.0 + 1))

    def test_the_cooldown_does_expire(self):
        rows = [_row(text="everyone come here please")]
        d = overhear.hear(rows, family=FAMILY, authored=AUTHORED, last_at=100.0,
                          now=100.0 + overhear.COOLDOWN_SECONDS + 1)
        self.assertIsNotNone(d)


class AudienceTest(unittest.TestCase):
    def test_the_speaker_is_not_ordered_to_obey_himself(self):
        """Evan is playing one of them. Telling his own character to follow
        itself looks fine in a test and reads as a bug in game."""
        d = overhear.Directive(speaker="Grug", text="follow me")
        self.assertEqual(overhear.audience(d, family=FAMILY),
                         ["Bork", "Grog", "Og", "Ugga"])

    def test_casing_does_not_smuggle_the_speaker_back_in(self):
        d = overhear.Directive(speaker="grug", text="follow me")
        self.assertNotIn("Grug", overhear.audience(d, family=FAMILY))


class WiringTest(unittest.TestCase):
    """A listener nobody calls hears nothing."""

    @classmethod
    def setUpClass(cls):
        import ast
        import pathlib

        cls.ast = ast
        cls.src = (pathlib.Path(__file__).resolve().parent.parent / "bridge.py").read_text()
        cls.tree = ast.parse(cls.src)

    def _names(self, fn_name):
        ast = self.ast
        fn = next(n for n in ast.walk(self.tree)
                  if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))
                  and n.name == fn_name)
        return {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)} | {
            n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)}

    def test_the_relay_listens(self):
        self.assertIn("_obey_evan_in_game", self._names("_relay_chat"))

    def test_the_bridge_supplies_what_it_authored(self):
        """authored=set() means the bridge claims to have said nothing, and its
        own council lines become a stream of orders. A literal empty set is
        indistinguishable from a working call at the name level, so this checks
        the argument is a CALL."""
        import ast

        fn = next(n for n in self.ast.walk(self.tree)
                  if isinstance(n, self.ast.AsyncFunctionDef) and n.name == "_obey_once")
        call = next(n for n in self.ast.walk(fn)
                    if isinstance(n, ast.Call)
                    and getattr(n.func, "attr", None) == "hear")
        authored = next(k.value for k in call.keywords if k.arg == "authored")
        # Not a type check: `set()` parses as a Call and sailed through one.
        # The argument has to actually reach for the reader.
        inner = {n.id for n in ast.walk(authored) if isinstance(n, ast.Name)}
        self.assertIn("_authored_lines", inner,
                      "authored= does not read what the bridge said, so the "
                      "family's own speech will be obeyed as orders")

    def test_it_hears_and_it_acts(self):
        names = self._names("_obey_once")
        self.assertIn("hear", names)
        self.assertIn("audience", names)
        self.assertIn("_insert_command", names)

    def test_an_order_it_cannot_express_issues_no_command(self):
        """Inventing an approximation of an order nobody gave is worse than
        admitting it was not understood, when the order moves five characters
        around a world."""
        fn = next(n for n in self.ast.walk(self.tree)
                  if isinstance(n, self.ast.AsyncFunctionDef)
                  and n.name == "_obey_once")
        src = self.ast.unparse(fn)
        self.assertIn("decision.command is None", src)

    def test_a_dead_voice_does_not_take_the_relay_with_it(self):
        """The relay is the product; obeying is a bonus on top of it. The
        guard lives in the listener rather than the relay because _relay_chat
        is at Elder's complexity cap."""
        fn = next(n for n in self.ast.walk(self.tree)
                  if isinstance(n, self.ast.AsyncFunctionDef)
                  and n.name == "_obey_evan_in_game")
        handlers = [n for n in self.ast.walk(fn)
                    if isinstance(n, self.ast.ExceptHandler)]
        self.assertTrue(handlers)


if __name__ == "__main__":
    unittest.main()
