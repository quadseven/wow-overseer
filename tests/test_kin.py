"""Kin muster: one character calls for help, the family answers.

No live LLM, no SQL, no Discord - a chat line and a roster go in, typed actions
come out. Same seam every other pure module here pins (infra#2597).

The rule that shapes all of it: a plea is only ever answered with commands
already in voice.VOCABULARY. mod-playerbots resolves `follow` against the bot's
MASTER (FollowMasterStrategy), not an arbitrary name - there is no
`follow <player>` - so "everyone go to Grog" is not expressible as a command and
is not attempted. What IS expressible is "stop what you are doing and regroup",
which combined with WoW's native party assist is the behaviour that shows up on
screen.
"""

import unittest

import kin
import voice


def _row(name, level=5, *, is_bot=True, guild_id=7):
    return {"name": name, "level": level, "is_bot": is_bot, "guild_id": guild_id}


FAMILY = {"Grug", "Ugga", "Grog", "Bork", "Og"}

# The family: all bots, all guild 7 (guild is now incidental).
ROSTER = [
    _row("Grug", 6),
    _row("Ugga", 5),
    _row("Grog", 6),
    _row("Bork", 4),
    _row("Og", 5),
]


class ParsePleaTest(unittest.TestCase):
    def test_a_plain_request_for_help_is_a_plea(self):
        p = kin.parse_plea("Grog", "I need help with my paladin quest")
        self.assertIsNotNone(p)
        self.assertEqual(p.caller, "Grog")
        self.assertEqual(p.about, "my paladin quest")

    def test_help_without_an_about_still_counts(self):
        p = kin.parse_plea("Bork", "help!")
        self.assertIsNotNone(p)
        self.assertEqual(p.about, "")

    def test_ordinary_chatter_is_not_a_plea(self):
        for line in (
            "Grug smash boars",
            "nice loot",
            "I helped Ugga earlier",
            "no help needed",
            "helpful little gnome",
        ):
            self.assertIsNone(kin.parse_plea("Grug", line), line)

    def test_help_as_a_mere_prefix_is_not_a_plea(self):
        """Fails without the trailing \\b on every `help` alternative."""
        for line in (
            "I need helpful directions to Orgrimmar",
            "I want helpful advice",
            "can anyone helpfully explain this quest",
        ):
            self.assertIsNone(kin.parse_plea("Grug", line), line)

    def test_negated_help_is_not_a_plea(self):
        """Fails without _NEGATIVE_RE - the guard the review found inert."""
        for line in (
            "you can't help me now",
            "nobody can help me",
            "no one can help me",
            "the innkeeper wouldn't help me",
            "I don't think I need help",
            "I never said I need help",
        ):
            self.assertIsNone(kin.parse_plea("Grug", line), line)

    def test_being_told_to_stop_helping_is_not_a_plea(self):
        """Fails without _DISMISS_RE."""
        for line in (
            "stop trying to help me",
            "quit trying to help me",
            "enough, you don't need to help me",
        ):
            self.assertIsNone(kin.parse_plea("Grug", line), line)

    def test_offering_to_help_a_lowercased_name_is_not_a_plea(self):
        """Fails without the case-insensitive offer-exclusion; it used to
        become the SPEAKER's plea with about='ugga'."""
        for line in ("can someone help ugga", "can anyone help bork with this"):
            self.assertIsNone(kin.parse_plea("Ugga", line), line)

    def test_the_commonest_plea_survives_the_offer_exclusion(self):
        """Guards the regression the exclusion caused when first widened:
        `help with` looked exactly like `help <name>`."""
        p = kin.parse_plea("Grog", "I need help with my paladin quest")
        self.assertIsNotNone(p)
        self.assertEqual(p.about, "my paladin quest")

    def test_a_question_about_helping_someone_else_is_not_a_plea(self):
        self.assertIsNone(kin.parse_plea("Ugga", "should I help Bork?"))

    def test_speaker_is_required(self):
        self.assertIsNone(kin.parse_plea("", "I need help"))

    def test_case_and_punctuation_do_not_matter(self):
        self.assertIsNone(kin.parse_plea("Og", ""))
        self.assertIsNotNone(kin.parse_plea("Og", "  HELP ME PLEASE!!  "))


class PlanMusterTest(unittest.TestCase):
    def _plea(self, caller="Grog", about="my paladin quest"):
        return kin.Plea(caller=caller, about=about)

    def test_the_family_answers_and_the_caller_does_not_answer_itself(self):
        m = kin.plan_muster(
            self._plea(), ROSTER, family=FAMILY, last_muster_at=None, now=100.0
        )
        self.assertNotIn("Grog", [a.character_name for a in m.actions])
        self.assertEqual(
            sorted(a.character_name for a in m.actions),
            ["Bork", "Grug", "Og", "Ugga"],
        )

    def test_every_issued_command_is_in_the_allowlist(self):
        m = kin.plan_muster(
            self._plea(), ROSTER, family=FAMILY, last_muster_at=None, now=100.0
        )
        self.assertTrue(m.actions)
        for a in m.actions:
            self.assertIn(a.command, voice.VOCABULARY, a.command)

    def test_a_caller_nobody_knows_musters_nobody(self):
        m = kin.plan_muster(
            self._plea(caller="Stranger"),
            ROSTER,
            family=FAMILY,
            last_muster_at=None,
            now=100.0,
        )
        self.assertEqual(m.actions, [])
        self.assertIn("not one of", m.reason)

    def test_a_second_plea_inside_the_cooldown_is_refused(self):
        m = kin.plan_muster(
            self._plea(), ROSTER, family=FAMILY, last_muster_at=90.0, now=100.0
        )
        self.assertEqual(m.actions, [])
        self.assertIn("cooldown", m.reason)

    def test_the_cooldown_expires(self):
        m = kin.plan_muster(
            self._plea(),
            ROSTER,
            family=FAMILY,
            last_muster_at=100.0 - kin.COOLDOWN_SECONDS - 1,
            now=100.0,
        )
        self.assertTrue(m.actions)

    def test_a_lone_character_musters_nobody_rather_than_erroring(self):
        m = kin.plan_muster(
            self._plea(caller="Grug"),
            [_row("Grug", 6)],
            family=FAMILY,
            last_muster_at=None,
            now=100.0,
        )
        self.assertEqual(m.actions, [])
        self.assertIn("alone", m.reason)

    def test_responders_are_capped(self):
        big = [_row(f"Kin{i:02d}") for i in range(40)] + [_row("Grog", 6)]
        m = kin.plan_muster(
            self._plea(), big, family=FAMILY, last_muster_at=None, now=100.0
        )
        self.assertLessEqual(len(m.actions), kin.MAX_RESPONDERS)

    # --- the review's critical finding, as tests -----------------------
    def test_a_human_player_is_never_mustered(self):
        """_fetch_roster returns EVERY online character. Before the fix the
        responders were the six alphabetically first names on the realm, so a
        player called Ahuman was ordered every time - and mod_overseer writes
        status='error', detail='target has no bot AI' for them."""
        roster = ROSTER + [
            _row("Aaanon", is_bot=False),
            _row("Ahuman", 60, is_bot=False),
        ]
        m = kin.plan_muster(
            self._plea(), roster, family=FAMILY, last_muster_at=None, now=100.0
        )
        names = [a.character_name for a in m.actions]
        self.assertNotIn("Ahuman", names)
        self.assertNotIn("Aaanon", names)
        self.assertEqual(sorted(names), ["Bork", "Grug", "Og", "Ugga"])

    def test_a_stranger_is_never_mustered(self):
        roster = ROSTER + [_row("Aardvark", guild_id=99), _row("Zzz", guild_id=0)]
        m = kin.plan_muster(
            self._plea(), roster, family=FAMILY, last_muster_at=None, now=100.0
        )
        names = [a.character_name for a in m.actions]
        self.assertNotIn("Aardvark", names)
        self.assertNotIn("Zzz", names)

    def test_a_caller_outside_the_family_musters_nobody_rather_than_the_realm(self):
        """Replaced a guild-membership test. The five characters turned out to
        have no guild - at level 1 one needs signatures - so scoping the family
        by one made the feature wait on an unrelated in-game chore."""
        roster = ROSTER + [_row("Thrall", 9)]
        m = kin.plan_muster(
            kin.Plea("Thrall", ""),
            roster,
            family=FAMILY,
            last_muster_at=None,
            now=100.0,
        )
        self.assertEqual(m.actions, [])
        self.assertIn("not family", m.reason)

    def test_an_empty_family_musters_nobody_rather_than_everyone(self):
        m = kin.plan_muster(
            kin.Plea("Grog", ""), ROSTER, family=set(), last_muster_at=None, now=100.0
        )
        self.assertEqual(m.actions, [])

    def test_responders_are_returned_in_sorted_order(self):
        """The old determinism test was vacuous - two calls with the same dict
        could not differ. This one fails if the sort is dropped."""
        roster = [_row("Ugga"), _row("Bork"), _row("Og"), _row("Grug"), _row("Grog", 6)]
        m = kin.plan_muster(
            self._plea(), roster, family=FAMILY, last_muster_at=None, now=100.0
        )
        names = [a.character_name for a in m.actions]
        self.assertEqual(names, sorted(names))


class ReportTest(unittest.TestCase):
    """muster_report had no coverage at all; fanout.muster_report has five."""

    def test_a_report_names_who_regrouped(self):
        m = kin.plan_muster(
            kin.Plea("Grog", "my paladin quest"),
            ROSTER,
            family=FAMILY,
            last_muster_at=None,
            now=100.0,
        )
        line = kin.muster_report(m, kin.Plea("Grog", "my paladin quest"))
        self.assertIn("Grog", line)
        for who in ("Grug", "Ugga", "Bork", "Og"):
            self.assertIn(who, line)

    def test_a_report_never_claims_help_reached_the_caller(self):
        """`follow` resolves against the bot's MASTER, so "answered" or "came"
        would assert something the command cannot deliver."""
        m = kin.plan_muster(
            kin.Plea("Grog", ""), ROSTER, family=FAMILY, last_muster_at=None, now=100.0
        )
        line = kin.muster_report(m, kin.Plea("Grog", ""))
        for claim in ("came", "answered", "went to", "arrived"):
            self.assertNotIn(claim, line.lower(), claim)
        self.assertIn("regrouped", line)

    def test_a_refusal_reports_the_reason_and_no_names(self):
        m = kin.plan_muster(
            kin.Plea("Grog", ""), ROSTER, family=FAMILY, last_muster_at=99.0, now=100.0
        )
        line = kin.muster_report(m, kin.Plea("Grog", ""))
        self.assertIn("cooldown", line)
        self.assertNotIn("regrouped", line)


class MemoryTest(unittest.TestCase):
    """'Growing memories' - the schema's `reflection` source, unused until now."""

    def test_the_caller_remembers_who_came(self):
        """First person, so it names the HELPERS and not itself - a memory that
        said "Grog called for help" in Grog's own head would read as someone
        else's story the next time it is shown back to him."""
        m = kin.plan_muster(
            kin.Plea("Grog", "my paladin quest"),
            ROSTER,
            family=FAMILY,
            last_muster_at=None,
            now=100.0,
        )
        self.assertNotIn("Grog", m.caller_memory)
        for who in ("Grug", "Ugga", "Bork", "Og"):
            self.assertIn(who, m.caller_memory)

    def test_each_responder_remembers_who_it_answered(self):
        m = kin.plan_muster(
            kin.Plea("Grog", "my paladin quest"),
            ROSTER,
            family=FAMILY,
            last_muster_at=None,
            now=100.0,
        )
        self.assertTrue(m.responder_memories)
        for name, text in m.responder_memories.items():
            self.assertIn("Grog", text, name)

    def test_a_refused_muster_records_no_memory(self):
        m = kin.plan_muster(
            kin.Plea("Grog", ""), ROSTER, family=FAMILY, last_muster_at=99.0, now=100.0
        )
        self.assertEqual(m.caller_memory, "")
        self.assertEqual(m.responder_memories, {})

    def test_memory_mentions_what_the_help_was_about(self):
        m = kin.plan_muster(
            kin.Plea("Grog", "my paladin quest"),
            ROSTER,
            family=FAMILY,
            last_muster_at=None,
            now=100.0,
        )
        self.assertIn("paladin quest", m.caller_memory)

    def test_memory_survives_an_empty_about(self):
        m = kin.plan_muster(
            kin.Plea("Bork", ""), ROSTER, family=FAMILY, last_muster_at=None, now=100.0
        )
        self.assertTrue(m.caller_memory)
        self.assertNotIn("  ", m.caller_memory)


if __name__ == "__main__":
    unittest.main()
