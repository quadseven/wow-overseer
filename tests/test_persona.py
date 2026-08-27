"""Saying the line in character, without ever changing what was decided.

Evan's brief for the family:

    bork should be an annoying young son, grog a more mature son still young
    but older than bork, ugga the ... mother of the sons, grug the dad, loves
    and protects his family, and og the neighbor who is probably secretly
    sleeping with ugga behind grugs back and grug is suspicion sometimes when
    ugga smiles at og

The last clause is not decoration. bonds.py already made Grug refuse to answer
Ugga once Og had answered her too often - the sulk was in the rules before it
had a reason, and this gives it one.
"""
import unittest

import bonds
import persona


class PersonaTest(unittest.TestCase):
    def test_every_family_member_has_a_voice(self):
        for name in bonds.FAMILY:
            with self.subTest(name=name):
                self.assertTrue(bonds.FAMILY[name].persona.strip(),
                                "%s has no persona, so the model gets nothing "
                                "to distinguish them from anyone else" % name)

    def test_the_personas_are_actually_different(self):
        """Five identical descriptions would voice five identical characters,
        and every test above would still pass."""
        texts = [b.persona for b in bonds.FAMILY.values()]
        self.assertEqual(len(set(texts)), len(texts))

    def test_a_stranger_gets_no_prompt_at_all(self):
        """This module has personas for five characters and no business
        putting words in anyone else's mouth."""
        self.assertIsNone(persona.build_prompt("Thrall", "hello"))

    def test_every_member_has_a_race_class_and_gender(self):
        """Verified against the live characters, not assumed: the two brothers
        are a dwarf and a gnome while their parents are human, which is exactly
        the sort of thing a persona invents wrongly if nobody writes it down."""
        for name, bond in bonds.FAMILY.items():
            with self.subTest(name=name):
                self.assertTrue(bond.race, name)
                self.assertTrue(bond.char_class, name)
                self.assertTrue(bond.gender, name)

    def test_the_family_is_who_evan_says_it_is(self):
        """Pinned against the live characters as of 2026-08-23."""
        self.assertEqual(
            {n: (b.gender, b.race, b.char_class) for n, b in bonds.FAMILY.items()},
            {
                "Grug": ("male", "human", "warrior"),
                "Ugga": ("female", "human", "priest"),
                "Grog": ("male", "dwarf", "paladin"),
                "Bork": ("male", "gnome", "rogue"),
                "Og": ("male", "human", "mage"),
            },
        )

    def test_the_speaker_is_told_their_class(self):
        p = persona.build_prompt("Bork", "help me")
        self.assertIn("rogue", p)

    def test_the_others_are_named_by_their_class_too(self):
        """Grug should know Ugga is the priest keeping him alive."""
        p = persona.build_prompt("Grug", "x")
        self.assertIn("priest", p)
        self.assertIn("paladin", p)

    def test_race_never_reaches_the_model(self):
        """The race is a sight gag - the boys are a dwarf and a gnome because
        those models are SHORT, so they read as children. Hand a model the word
        "dwarf" and it writes "aye, laddie" unprompted. This family has exactly
        one accent and it is Grug's."""
        for name in bonds.FAMILY:
            p = persona.build_prompt(name, "x")
            for word in ("dwarf", "gnome", "human"):
                self.assertNotIn(word, p.lower(),
                                 "%s's prompt mentions %s" % (name, word))

    def test_the_house_voice_is_in_every_prompt(self):
        """They are cavemen - that is why the parents are human. The register
        is shared and the personalities differ within it; five polite
        descriptions of a family produced five near-identical sentences when
        the voice was left ordinary."""
        for name in bonds.FAMILY:
            p = persona.build_prompt(name, "x")
            self.assertIn("caveman", p.lower(), name)
            self.assertIn("Grug know fire good.", p, name)

    def test_the_voice_rules_are_spelled_out_not_implied(self):
        """"Talk like a caveman" alone gets a model reaching for "ugg" and
        chest-beating. The rules are what produce the actual register."""
        p = persona.build_prompt("Bork", "x")
        for rule in ("instead of", "Short words"):
            self.assertIn(rule, p)

    def test_the_speakers_own_role_is_in_the_prompt(self):
        p = persona.build_prompt("Bork", "help me")
        self.assertIn("younger son", p)

    def test_the_plain_line_is_carried_through_as_the_meaning(self):
        p = persona.build_prompt("Grog", "Og is still 4.")
        self.assertIn("Og is still 4.", p)


class SuspicionTest(unittest.TestCase):
    """The engine behind the jealousy rule, finally written down."""

    def test_only_grug_carries_the_suspicion(self):
        carried = [n for n in bonds.FAMILY
                   if "suspects" in (persona.build_prompt(n, "x") or "")]
        self.assertEqual(carried, ["Grug"])

    def test_it_names_the_two_people_it_is_about(self):
        p = persona.build_prompt("Grug", "x")
        self.assertIn("Ugga", p)
        self.assertIn("Og", p)

    def test_the_model_is_never_told_the_affair_is_real(self):
        """A suspicion nobody can prove is a better engine than a confirmed
        fact, and it keeps the model from writing a confrontation the rules
        cannot deliver."""
        note = bonds.SUSPICION["note"].lower()
        self.assertIn("suspect", note)
        self.assertIn("no proof", note)
        self.assertIn("never accuses", note)

    def test_the_suspicion_matches_who_the_rules_actually_punish(self):
        """If these ever disagree, the story and the mechanics are about two
        different triangles."""
        self.assertEqual(bonds.SUSPICION["who"], bonds.head_of_family())
        d = bonds.decide(
            bonds.SUSPICION["who"],
            type("P", (), {"caller": bonds.SUSPICION["about"], "about": "q"})(),
            history=[(bonds.SUSPICION["with"], bonds.SUSPICION["about"])]
            * bonds.JEALOUSY_THRESHOLD,
        )
        self.assertFalse(d.will_answer, d.reason)
        self.assertIn(bonds.SUSPICION["with"], d.reason)


class CleanTest(unittest.TestCase):
    """Whatever the model returned, made safe to speak - or the plain line.

    Falls back rather than repairs. A mangled line is worse than the plain
    one: the plain one is at least true to the plan.
    """

    PLAIN = "Og is still 4. We should not leave them behind."

    def test_a_good_line_is_kept(self):
        self.assertEqual(persona.clean("Og lags. We do not leave him.", self.PLAIN),
                         "Og lags. We do not leave him.")

    def test_quotes_are_stripped(self):
        self.assertEqual(persona.clean('"Og lags."', self.PLAIN), "Og lags.")

    def test_stage_directions_are_stripped(self):
        self.assertEqual(persona.clean("(gruffly) Og lags.", self.PLAIN), "Og lags.")

    def test_a_reasoning_preamble_takes_the_last_line(self):
        """Reasoning models narrate first and answer last."""
        said = "Let me think about how Grug speaks.\nHe is gruff.\nOg lags. We go."
        self.assertEqual(persona.clean(said, self.PLAIN), "Og lags. We go.")

    def test_an_empty_answer_falls_back(self):
        for said in ("", "   ", "\n\n"):
            self.assertEqual(persona.clean(said, self.PLAIN), self.PLAIN)

    def test_an_enormous_answer_falls_back(self):
        self.assertEqual(persona.clean("x" * 500, self.PLAIN), self.PLAIN)

    def test_a_line_of_pure_narration_falls_back(self):
        self.assertEqual(persona.clean("(he says nothing)", self.PLAIN), self.PLAIN)

    def test_newlines_never_reach_the_game(self):
        """A newline in a chat command is a second line nobody decided to say."""
        out = persona.clean("Og lags.\tWe go.", self.PLAIN)
        self.assertNotIn("\\n", out)
        self.assertNotIn("\\t", out)


class JsonInTheMouthTest(unittest.TestCase):
    """A model asked for a sentence sometimes answers with an object anyway,
    and these were SPOKEN OUT LOUD in Evan's party chat before it was caught:

        [Party] Bork: {"response": "Bork no need do thing. Bork go fish!"}
        [Party] Og:   {"sentence": "Og help Grug."}
        [Party] Grug: }

    The last one is the worst. A pretty-printed object's final line is a lone
    brace, and clean() read the last line. Answering in JSON is not the
    failure - failing to notice is.
    """

    PLAIN = "Og is still 4. We should not leave them behind."

    def test_the_exact_lines_that_reached_the_channel(self):
        for said, want in (
            ('{"response": "Bork no need do thing. Bork go fish!"}',
             "Bork no need do thing. Bork go fish!"),
            ('{"sentence": "Og help Grug."}', "Og help Grug."),
        ):
            with self.subTest(said=said):
                self.assertEqual(persona.clean(said, self.PLAIN), want)

    def test_a_pretty_printed_object_is_not_read_line_by_line(self):
        said = '{\n  "say": "Grug go now."\n}'
        self.assertEqual(persona.clean(said, self.PLAIN), "Grug go now.")

    def test_a_lone_brace_is_never_spoken(self):
        for said in ("}", "{", "  }  ", "{}"):
            with self.subTest(said=said):
                self.assertEqual(persona.clean(said, self.PLAIN), self.PLAIN)

    def test_an_object_with_no_sentence_in_it_falls_back(self):
        """`{"grug_plan_carried_at":210}` was said out loud. Whatever that is,
        it is not speech."""
        self.assertEqual(persona.clean('{"grug_plan_carried_at":210}', self.PLAIN),
                         self.PLAIN)

    def test_json_wrapped_in_narration_is_still_found(self):
        said = 'Let me think.\nHere is the line:\n{"response": "Grug go now."}'
        self.assertEqual(persona.clean(said, self.PLAIN), "Grug go now.")

    def test_a_plain_sentence_is_untouched_by_any_of_this(self):
        self.assertEqual(persona.clean("Og lags. We go.", self.PLAIN), "Og lags. We go.")

    def test_a_sentence_that_merely_mentions_a_brace_survives(self):
        """Only text that actually PARSES as an object is treated as one."""
        said = "Grug no like { thing."
        self.assertEqual(persona.clean(said, self.PLAIN), said)


class WiringTest(unittest.TestCase):
    """A voice nobody uses is a very well-tested monologue."""

    @classmethod
    def setUpClass(cls):
        import ast
        import pathlib

        cls.ast = ast
        cls.src = (pathlib.Path(__file__).resolve().parent.parent / "bridge.py").read_text()
        cls.tree = ast.parse(cls.src)

    def _names_in(self, fn_name):
        ast = self.ast
        fn = next(n for n in ast.walk(self.tree)
                  if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))
                  and n.name == fn_name)
        return {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)} | {
            n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)}

    def test_the_council_speaks_in_character(self):
        self.assertIn("_in_character", self._names_in("_council_once"))

    def test_the_voice_falls_back_rather_than_raising(self):
        """A council must not be lost because a model was slow. The fallback
        is the line that was going to be said anyway."""
        fn = next(n for n in self.ast.walk(self.tree)
                  if isinstance(n, self.ast.AsyncFunctionDef)
                  and n.name == "_in_character")
        handlers = [n for n in self.ast.walk(fn)
                    if isinstance(n, self.ast.ExceptHandler)]
        self.assertTrue(handlers, "no except: an LLM outage would drop the council")

    def test_the_voice_runs_after_the_decision_not_before(self):
        """The whole design rests on this order. If the model were asked
        before the plan existed it could change what was decided.

        Scoped to `_council_once`'s own source, not the whole file: other
        functions (materials.py's handoff pass, craftpleas.py's answers) call
        `self._in_character(` too, and a call site living earlier in
        bridge.py than `_council_once` says nothing about the order INSIDE
        the council function itself.
        """
        fn = next(n for n in self.ast.walk(self.tree)
                  if isinstance(n, self.ast.AsyncFunctionDef)
                  and n.name == "_council_once")
        body = self.ast.get_source_segment(self.src, fn)
        council_at = body.index("held = council.hold(")
        voice_at = body.index("self._in_character(")
        self.assertLess(council_at, voice_at)

    def test_the_asked_model_is_told_not_to_reason(self):
        """The first live run returned a reasoning monologue truncated at the
        token cap, with no answer in it at all."""
        names = self._names_in("_in_character")
        self.assertIn("_ask_llm", names)
        self.assertIn("No reasoning", self.src)

    def test_the_inner_voice_is_grounded_on_the_family_everywhere(self):
        """Not one voice.build_prompt may take the bots' table straight.

        This is the defect, stated where it can be caught again: every call
        site passed `personality=grounding["personality"]`, which for this
        family is ANCIENT_WISE_ONE for two of them and nothing at all for the
        other three. Checked per call rather than by a text search, so a new
        fourth call site cannot quietly reintroduce it.
        """
        ast = self.ast
        calls = [n for n in ast.walk(self.tree)
                 if isinstance(n, ast.Call)
                 and getattr(n.func, "attr", None) == "build_prompt"
                 and getattr(getattr(n.func, "value", None), "id", None) == "voice"]
        self.assertTrue(calls, "nothing asks the inner voice at all any more")
        for call in calls:
            arg = next((k.value for k in call.keywords if k.arg == "personality"), None)
            self.assertIsNotNone(arg, "a build_prompt call names no personality")
            reached = {n.id for n in ast.walk(arg) if isinstance(n, ast.Name)}
            self.assertIn(
                "_persona_for", reached,
                "line %d prompts on mod_ollama_chat_personality instead of the "
                "family Evan wrote" % call.lineno,
            )


class CharacterisationTest(unittest.TestCase):
    """The persona Evan wrote, for prompts persona.py does not build itself.

    Bork replied to "lets go sell junk in town" with "The cycle of commerce
    must flow. Let us trade these dull relics for coin, as the ancients did."
    He was flagged ANCIENT_WISE_ONE in mod_ollama_chat_personality, which was
    the only characterisation the inner voice was ever given.
    """

    def test_it_is_the_persona_from_bonds(self):
        text = persona.characterisation("Grog")
        self.assertIn("Copies his father's way of talking", text)
        self.assertIn("elder son", text)

    def test_the_register_comes_with_it(self):
        """The persona separates the five; the register is what makes them one
        family. Personas alone produced five polite strangers."""
        self.assertIn("caveman", persona.characterisation("Ugga"))
        self.assertIn("Grug no like.", persona.characterisation("Ugga"))

    def test_every_member_has_one_including_the_three_the_table_forgot(self):
        """The live table holds rows for Bork and Og and NOTHING for Grug,
        Ugga or Grog - who were therefore prompted with no character at all."""
        for name in ("Grug", "Ugga", "Grog", "Bork", "Og"):
            self.assertTrue(persona.characterisation(name), name)

    def test_chat_casing_still_finds_them(self):
        self.assertEqual(persona.characterisation("bORK"), persona.characterisation("Bork"))

    def test_a_stranger_gets_nothing_rather_than_a_borrowed_family(self):
        """Five hundred random bots share this realm. This module has personas
        for five characters and no business describing anyone else - the caller
        falls back to whatever the bots' own table says."""
        self.assertIsNone(persona.characterisation("Thrall"))
        self.assertIsNone(persona.characterisation(""))


if __name__ == "__main__":
    unittest.main()
