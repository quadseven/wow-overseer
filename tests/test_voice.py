"""Inner-voice tests: NL routing, prompt-as-data, LLM decision parsing.

No live LLM anywhere - the model's output is canned JSON, and the prompt is
asserted as a string. That is the seam the epic pinned (infra#2597).
"""

import json
import pathlib
import re
import unittest

import goals
import voice
from core import InsertCommand, NLDirective, parse_directive

ME = "1000"
ALLOWED = frozenset({ME})


class RoutingTest(unittest.TestCase):
    def test_raw_command_first_token_goes_straight_through(self):
        out = parse_directive("@Grug follow", ME, ALLOWED)
        self.assertEqual(out, [InsertCommand("Grug", "follow", "discord:1000")])

    def test_multiword_raw_command_still_raw(self):
        out = parse_directive("@Grug drop quest", ME, ALLOWED)
        self.assertEqual(out, [InsertCommand("Grug", "drop quest", "discord:1000")])

    def test_natural_language_becomes_an_nl_directive(self):
        out = parse_directive(
            "@Grug go kill boars until you feel stronger", ME, ALLOWED
        )
        self.assertEqual(
            out,
            [
                NLDirective(
                    "Grug", "go kill boars until you feel stronger", "discord:1000"
                )
            ],
        )

    def test_nl_directive_respects_caps_and_gates(self):
        self.assertEqual(parse_directive("@Grug do something", "9999", ALLOWED), [])


class PromptTest(unittest.TestCase):
    def test_prompt_contains_identity_situation_vocabulary_and_ask(self):
        p = voice.build_prompt(
            name="Grug",
            level=1,
            race_name="Orc",
            class_name="Warrior",
            zone="Durotar",
            personality=None,
            text="go kill boars until you feel stronger",
        )
        for needle in (
            "Grug",
            "level 1",
            "Orc",
            "Warrior",
            "Durotar",
            "go kill boars until you feel stronger",
            "grind",
            "JSON",
        ):
            self.assertIn(needle, p, needle)

    def test_personality_is_woven_in_when_present(self):
        p = voice.build_prompt(
            name="Gimli",
            level=40,
            race_name="Dwarf",
            class_name="Warrior",
            zone="Ironforge",
            personality="gruff axe-proud dwarf",
            text="say hello",
        )
        self.assertIn("gruff axe-proud dwarf", p)

    def test_a_whole_character_survives_being_woven_in(self):
        """persona.characterisation supplies several lines, not a label. It
        used to be squeezed into "Personality: ..." on the identity line,
        which was fine for the one-word mod_ollama_chat_personality strings
        and mangles a persona and a register into one run-on sentence."""
        import persona

        p = voice.build_prompt(
            name="Bork",
            level=8,
            race_name="Gnome",
            class_name="Rogue",
            zone="Elwynn Forest",
            personality=persona.characterisation("Bork"),
            text="lets go sell junk in town",
        )
        self.assertIn("Worships Grog", p)
        self.assertIn("Grug no like.", p)
        # The order still has to be legible under all of that.
        self.assertIn("lets go sell junk in town", p)
        self.assertIn("sell gray", p)


class DecisionTest(unittest.TestCase):
    def _decide(self, content):
        return voice.parse_decision(content)

    def test_valid_decision_yields_command_and_say(self):
        d = self._decide(
            json.dumps({"command": "grind", "say": "Grug smash boars now."})
        )
        self.assertEqual(d.command, "grind")
        self.assertEqual(d.say, "Grug smash boars now.")

    def test_none_command_is_an_in_character_refusal(self):
        d = self._decide(json.dumps({"command": "none", "say": "Grug not know how."}))
        self.assertIsNone(d.command)
        self.assertIn("not know", d.say)

    def test_json_wrapped_in_prose_still_parses(self):
        d = self._decide(
            'Here you go:\n```json\n{"command": "follow", "say": "Grug follow."}\n```'
        )
        self.assertEqual(d.command, "follow")

    def test_garbage_yields_no_command_and_a_fallback_say(self):
        d = self._decide("I am a language model and cannot")
        self.assertIsNone(d.command)
        self.assertTrue(d.say)

    def test_injection_shaped_commands_are_rejected(self):
        for evil in ("follow; DROP TABLE x", "follow\n.gm on", "a" * 300):
            d = self._decide(json.dumps({"command": evil, "say": "hm"}))
            self.assertIsNone(d.command, evil)

    def test_say_is_truncated_not_unbounded(self):
        d = self._decide(json.dumps({"command": "follow", "say": "x" * 5000}))
        self.assertLessEqual(len(d.say), voice.MAX_SAY)


if __name__ == "__main__":
    unittest.main()


class GateTest(unittest.TestCase):
    """The select-and-parameterize contract from infra#2600."""

    def test_parameterized_known_command_is_allowed(self):
        d = voice.parse_decision(
            json.dumps({"command": "co +grind,-loot", "say": "ok"})
        )
        self.assertEqual(d.command, "co +grind,-loot")

    def test_well_formed_but_unknown_command_is_rejected(self):
        # Charset-clean, yet no vocabulary entry and no known raw token:
        # the model may not invent commands the vocabulary never sanctioned.
        d = voice.parse_decision(json.dumps({"command": "gm on", "say": "hm"}))
        self.assertIsNone(d.command)

    def test_power_user_raw_tokens_bypass_the_voice(self):
        for raw in ("equip 1234", "talk", "q accept", "cast fireball"):
            out = parse_directive(f"@Grug {raw}", ME, ALLOWED)
            self.assertEqual(out, [InsertCommand("Grug", raw, "discord:1000")], raw)


class ReasoningPreambleTest(unittest.TestCase):
    """Live-found 2026-08-21: reasoning models narrate before answering."""

    def test_last_json_object_wins_over_think_aloud_with_braces(self):
        content = (
            "We need to pick one {command} from the list. The user said "
            "{go kill boars}. Grind fits. Final answer:\n"
            '{"command": "grind", "say": "Minarula hunts the boars of Azuremyst."}'
        )
        d = voice.parse_decision(content)
        self.assertEqual(d.command, "grind")
        self.assertIn("boars", d.say)

    def test_truncated_mid_thought_still_degrades_honestly(self):
        d = voice.parse_decision(
            "We need to answer the request. The list includes grind which"
        )
        self.assertIsNone(d.command)
        self.assertTrue(d.say)


class SellJunkTest(unittest.TestCase):
    """Live-found 2026-08-24 (infra#2597).

    The operator typed "lets go sell junk in town" in party chat. The model answered
    with the command `sell junk`, which is NOT a command: mod-playerbots'
    SellAction accepts gray/*/vendor/[item link], anything else falls through
    to an item-name lookup, matches nothing, sells nothing and RETURNS TRUE.
    Rows 856-859 went to four characters, every one status `delivered`, and
    not a single grey item left a bag.

    It passed the gate because RAW_STARTERS was built by splitting the
    vocabulary, turning "sell gray" into the bare token "sell". The comment
    warning that "sell junk" IS NOT A COMMAND sat twenty lines above the code
    that admitted it.
    """

    def test_sell_junk_is_refused(self):
        d = voice.parse_decision(
            json.dumps({"command": "sell junk", "say": "On my way."})
        )
        self.assertIsNone(d.command)
        self.assertEqual(d.say, "On my way.")

    def test_bare_sell_is_not_a_starter(self):
        self.assertNotIn("sell", voice.RAW_STARTERS)
        self.assertFalse(voice.is_raw_command("sell junk"))

    def test_the_real_sell_commands_still_pass(self):
        for good in ("sell gray", "sell vendor"):
            d = voice.parse_decision(json.dumps({"command": good, "say": "Aye."}))
            self.assertEqual(d.command, good, good)
            self.assertTrue(voice.is_raw_command(good), good)

    def test_multiword_entries_still_take_arguments(self):
        d = voice.parse_decision(json.dumps({"command": "drop quest", "say": "Fine."}))
        self.assertEqual(d.command, "drop quest")
        self.assertTrue(voice.is_raw_command("drop quest"))
        self.assertTrue(voice.is_raw_command("  DROP   QUEST  "))

    def test_explicitly_listed_starters_still_parameterize(self):
        d = voice.parse_decision(
            json.dumps({"command": "co +grind,-loot", "say": "Aye."})
        )
        self.assertEqual(d.command, "co +grind,-loot")

    def test_invented_second_word_on_a_multiword_verb_is_refused(self):
        # The general shape of the bug, not just the one string that bit us.
        for bad in ("sell everything", "drop everything", "reset everything"):
            d = voice.parse_decision(json.dumps({"command": bad, "say": "..."}))
            self.assertIsNone(d.command, bad)


class StrategyEngineTest(unittest.TestCase):
    """A strategy command must name the engine that HOLDS the strategy.

    mod-playerbots runs two engines and `co` and `nc` address one each.
    `co +grind` parses, delivers, reports success and changes nothing,
    because `grind` is registered on the non-combat engine - goals.py's
    `strategy_for` documents the live measurement ("not one unit") and
    switched its own copy to `nc`. The vocabulary shown to the model kept
    saying `co` for another three entries, which is a line the model is
    INVITED to pick that cannot work: the same shape as the "sell junk"
    entry voice.py's own comment warns about, twenty lines above it.

    Nothing pinned the engine choice, which is why the two modules were
    free to disagree. These two tests are that pin. Verified against the
    live engines the day they were written: a `kind='probe'` read of
    `strategies` on characters of four different classes put `grind`,
    `loot`, `stay`, `follow` and `new rpg` in `non_combat` every time and
    in `combat` never.
    """

    # A strategy command, split into engine, sign and strategy name.
    _STRATEGY = re.compile(r"^(nc|co) ([+-])([a-z][a-z ]*)$")

    @classmethod
    def _strategy_commands(cls, text: str):
        """Every "<engine> <sign><strategy>" string in a blob of source."""
        found = {}
        for line in re.findall(r'"((?:nc|co) [+-][a-z][a-z ]*)"', text):
            engine, _, strategy = cls._STRATEGY.match(line).groups()
            found.setdefault(strategy.strip(), set()).add(engine)
        return found

    def test_the_vocabulary_and_the_life_pass_agree_on_every_engine(self):
        """The real invariant: two copies of one fact must not disagree.

        goals.py's engine choices are measured against the running world, so
        they are the repository's own answer. Read out of its source rather
        than restated here, because a restated constant is a third copy.
        """
        driven = self._strategy_commands(
            pathlib.Path(goals.__file__).read_text(encoding="utf-8")
        )
        spoken = self._strategy_commands(
            "".join(f'"{entry}"' for entry in voice.VOCABULARY)
        )
        self.assertTrue(driven, "no strategy commands found in goals.py")
        shared = sorted(set(driven) & set(spoken))
        self.assertIn("grind", shared, "the entry this test was written for")
        for strategy in shared:
            self.assertEqual(
                driven[strategy],
                spoken[strategy],
                f"goals.py drives '{strategy}' on {sorted(driven[strategy])} and "
                f"the vocabulary offers it on {sorted(spoken[strategy])}",
            )

    def test_no_non_combat_strategy_is_offered_on_the_combat_engine(self):
        """Covers the entries goals.py happens not to drive, `loot` among them.

        The set is mod-playerbots' own, from AiFactory's non-combat defaults
        at the pinned module revision: `nc`, `food`, `chat`, `follow`,
        `default`, `force rebuff`, `quest`, `loot`, `gather`, `duel`, `pvp`,
        `buff`, `mount` and `emote` in the common block, and `grind`, `lfg`,
        `new rpg` and `bg` in the random-bot one. Only the ones a person
        would plausibly ask for are listed; a strategy genuinely on both
        engines (`flee`) is deliberately absent, which is what keeps
        goals.FLEE_STRATEGY's `co +flee` correct.
        """
        non_combat_only = frozenset(
            {
                "grind",
                "loot",
                "gather",
                "quest",
                "follow",
                "stay",
                "new rpg",
                "mount",
                "food",
                "lfg",
            }
        )
        for entry in voice.VOCABULARY:
            match = self._STRATEGY.match(entry)
            if not match:
                continue
            engine, _, strategy = match.groups()
            if strategy.strip() in non_combat_only:
                self.assertEqual(
                    engine,
                    "nc",
                    f"'{entry}' aims a non-combat strategy at the combat engine; "
                    "it will deliver, report success and do nothing",
                )
