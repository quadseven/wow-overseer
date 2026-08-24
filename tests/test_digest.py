"""The digest must never invent history, and must volunteer the gap.

Two failure modes are worth a suite of their own, and both are silent:

  1. REPORTING A DELTA IT CANNOT SOURCE. Almost nothing in acore_characters
     is timestamped - characters.money is a balance, character_queststatus_
     rewarded is (guid, quest, active) - so "Grug gained 2 levels tonight"
     is a sentence the schema cannot support unless something was sampling.
     A zero where the answer is "I was not watching" reads as "nothing
     happened", which is a lie told confidently, every hour, forever.

  2. NOT SAYING THE THING EVAN ASKED FOR. The standing requirement is that
     nobody falls behind. Live tonight: Og on 17 quest turn-ins against Grog
     and Ugga on 3, and Grog with 0.3 gold - under the price of training. A
     digest that reports those only when asked is a digest that never reports
     them.

The numbers in the fixtures below are the ones measured live on 2026-08-23,
so a test that passes here is a test about the family that actually exists.
"""
import datetime
import unittest

import bonds
import core
import digest
import questbook
import voice

NOW = datetime.datetime(2026, 8, 24, 7, 40)


def standing(name, level, gold, quests, spells=17, talents=1, **kw):
    return digest.Standing(
        name=name, level=level, copper=int(gold * digest.COPPER_PER_GOLD),
        quests_done=quests, spells=spells, talents=talents, **kw,
    )


# Measured live 2026-08-23. Grug 14/2.4g/13, Bork 11/3.0g/13, Ugga 11/2.8g/3,
# Grog 10/0.3g/3, Og 10/2.8g/17.
def live_family():
    return [
        standing("Grug", 14, 2.4, 13, spells=25, talents=3, online=True),
        standing("Bork", 11, 3.0, 13, spells=17, talents=2, online=True),
        standing("Ugga", 11, 2.8, 3, spells=18, talents=2, online=True),
        standing("Grog", 10, 0.3, 3, spells=17, talents=1, online=True),
        standing("Og", 10, 2.8, 17, spells=19, talents=1, online=True),
    ]


def window(hours=6.0, now=NOW):
    return digest.window_for(digest.Ask(hours=hours), now)


def sample(name, minutes_ago, **kw):
    return digest.Sample(name=name, at=NOW - datetime.timedelta(minutes=minutes_ago), **kw)


class Asking(unittest.TestCase):
    """The natural-language ask, which is the whole point of the feature."""

    def test_how_are_they_is_the_default_window(self):
        self.assertEqual(digest.DEFAULT_HOURS, digest.parse_ask("how are they?").hours)

    def test_all_night_is_a_night(self):
        """"What did they do all night" is Evan's own sentence."""
        self.assertEqual(digest.NIGHT_HOURS,
                         digest.parse_ask("what did they do all night?").hours)
        self.assertEqual(digest.NIGHT_HOURS,
                         digest.parse_ask("how are they? anything overnight").hours)

    def test_an_explicit_number_of_hours_wins(self):
        self.assertEqual(3.0, digest.parse_ask("catch me up on the last 3 hours").hours)
        self.assertEqual(6.0, digest.parse_ask("what did they do in the past 6 hrs").hours)

    def test_days_become_hours(self):
        self.assertEqual(48.0, digest.parse_ask("how are they over the last 2 days").hours)

    def test_a_number_beats_the_night_phrase(self):
        """"all night, say the last 2 hours" means two hours."""
        self.assertEqual(
            2.0, digest.parse_ask("what did they do all night - last 2 hours").hours)

    def test_an_absurd_window_is_clamped_not_refused(self):
        self.assertEqual(digest.MAX_HOURS,
                         digest.parse_ask("how are they over the last 9999 days").hours)

    def test_zero_hours_falls_back_rather_than_reporting_an_empty_stretch(self):
        self.assertEqual(digest.DEFAULT_HOURS,
                         digest.parse_ask("how are they in the last 0 hours").hours)

    def test_it_does_not_swallow_the_roster_question(self):
        for text in ("who is online", "list the players", "roster"):
            self.assertIsNone(digest.parse_ask(text), text)

    def test_it_does_not_fire_on_an_ordinary_sentence(self):
        for text in ("", "hello", "@Grug follow", "sell gray"):
            self.assertIsNone(digest.parse_ask(text), text)

    def test_a_reporting_verb_is_not_a_playerbot_command(self):
        """The `sell junk` lesson, asserted rather than remembered.

        voice.VOCABULARY entries are delivered VERBATIM to a bot as
        mod-playerbots chat. A reporting verb there would be whispered into a
        grammar with no such command, and mod-playerbots' own action would
        report success having done nothing - which is exactly how `sell junk`
        got four characters to announce a trip to the vendor and sell not one
        grey item.
        """
        for word in ("digest", "how are they", "catch up", "report"):
            self.assertNotIn(word, voice.VOCABULARY)


class Routing(unittest.TestCase):
    """core.parse_directive must hand the ask to the digest, not the roster."""

    ALLOWED = frozenset({"7"})

    def parse(self, text, dedicated=True):
        return core.parse_directive(text, "7", self.ALLOWED, dedicated=dedicated)

    def test_the_overseers_own_channel_answers_how_are_they(self):
        out = self.parse("how are they?")
        self.assertEqual(1, len(out))
        self.assertIsInstance(out[0], core.DigestQuery)
        self.assertEqual(digest.DEFAULT_HOURS, out[0].hours)

    def test_the_digest_beats_the_roster_on_the_word_playing(self):
        """_ROSTER_RE matches "playing"; the family question must still win.

        Without the ordering this returns a census of 500 bots to somebody who
        asked how five characters are - and it looks like a working feature.
        """
        out = self.parse("what have they been playing for the last 6 hours")
        self.assertIsInstance(out[0], core.DigestQuery)

    def test_the_roster_question_still_reaches_the_roster(self):
        out = self.parse("who is online?")
        self.assertIsInstance(out[0], core.RosterQuery)

    def test_a_shared_channel_stays_silent(self):
        self.assertEqual([], self.parse("how are they?", dedicated=False))

    def test_an_addressed_order_is_untouched(self):
        out = self.parse("@Grug follow")
        self.assertFalse(any(isinstance(d, core.DigestQuery) for d in out))


class Changes(unittest.TestCase):
    """Deltas, and the three genuinely different reasons there may be none."""

    def test_the_baseline_is_the_last_sample_before_the_window(self):
        """Not the first sample INSIDE it.

        Using the first inside silently shortens a six-hour question to
        whatever the sampler happened to cover, and reports a night as the
        twenty minutes since the last restart. The number looks reasonable and
        is wrong.
        """
        rows = [
            sample("Grug", 400, level=12, quests_done=9),   # before the window
            sample("Grug", 300, level=13, quests_done=11),  # inside it
            sample("Grug", 5, level=14, quests_done=13),
        ]
        change = digest.changes(window(6.0), rows)["Grug"]
        self.assertEqual(digest.BASIS_SAMPLED, change.basis)
        self.assertEqual(2, change.levels)
        self.assertEqual(4, change.quests)

    def test_a_window_older_than_the_sampling_says_so(self):
        rows = [sample("Grug", 60, level=14), sample("Grug", 5, level=14)]
        change = digest.changes(window(6.0), rows)["Grug"]
        self.assertEqual(digest.BASIS_NO_BASELINE, change.basis)
        self.assertFalse(change.measured)
        self.assertEqual(NOW - datetime.timedelta(minutes=60), change.since)

    def test_nothing_sampled_is_not_the_same_as_nothing_happened(self):
        change = digest.Change(name="Grog")
        self.assertEqual(digest.BASIS_NO_SAMPLES, change.basis)
        self.assertFalse(change.measured)
        self.assertFalse(change.moved)

    def test_spent_gold_is_a_negative_delta_not_a_wrap(self):
        """money only ever goes up in SQL's mind; repairs say otherwise."""
        rows = [sample("Ugga", 400, copper=30000), sample("Ugga", 5, copper=28000)]
        change = digest.changes(window(6.0), rows)["Ugga"]
        self.assertEqual(-2000, change.copper)
        self.assertTrue(change.moved)

    def test_a_flat_window_is_measured_and_empty(self):
        rows = [sample("Grog", 400, level=10, copper=3000),
                sample("Grog", 5, level=10, copper=3000)]
        change = digest.changes(window(6.0), rows)["Grog"]
        self.assertTrue(change.measured)
        self.assertFalse(change.moved)


class Ding(unittest.TestCase):
    """characters.leveltime is the one backwards-pointing time in the schema."""

    def test_a_logged_in_character_with_a_young_level_dinged_in_the_window(self):
        s = standing("Grug", 14, 2.4, 13, online=True, level_time_seconds=9000)
        self.assertTrue(digest.dinged_recently(s, window(6.0)))

    def test_an_older_level_did_not(self):
        s = standing("Grog", 10, 0.3, 3, online=True, level_time_seconds=90000)
        self.assertFalse(digest.dinged_recently(s, window(6.0)))

    def test_an_offline_character_proves_nothing(self):
        """leveltime counts PLAYED seconds. Offline, a small value is equally
        consistent with a ding a week ago followed by a logout."""
        s = standing("Grog", 10, 0.3, 3, online=False, level_time_seconds=60)
        self.assertFalse(digest.dinged_recently(s, window(6.0)))

    def test_an_unknown_leveltime_is_not_a_claim(self):
        s = standing("Og", 10, 2.8, 17, online=True, level_time_seconds=0)
        self.assertFalse(digest.dinged_recently(s, window(6.0)))


class Gaps(unittest.TestCase):
    """The inequality, volunteered."""

    def test_the_live_family_reports_the_turn_in_gap_first(self):
        found = digest.gaps(live_family())
        self.assertTrue(found)
        self.assertEqual("quest turn-ins", found[0].metric)
        self.assertEqual("Og", found[0].leader)
        self.assertEqual(17, found[0].leader_value)
        self.assertEqual(("Grog", "Ugga"), found[0].laggards)
        self.assertEqual(3, found[0].laggard_value)

    def test_grog_being_broke_is_reported(self):
        found = {g.metric: g for g in digest.gaps(live_family())}
        self.assertIn("gold", found)
        self.assertEqual(("Grog",), found["gold"].laggards)

    def test_the_level_spread_is_reported(self):
        found = {g.metric: g for g in digest.gaps(live_family())}
        self.assertIn("level", found)
        self.assertEqual("Grug", found["level"].leader)

    def test_an_even_family_has_nothing_to_report(self):
        even = [standing(n, 12, 5.0, 12) for n in ("Grug", "Ugga", "Grog", "Bork", "Og")]
        self.assertEqual((), digest.gaps(even))

    def test_one_character_alone_is_not_an_inequality(self):
        self.assertEqual((), digest.gaps([standing("Grug", 14, 0.0, 13)]))


def small_ledger():
    """Grug has turned in quest 100; Grog has not, and can.

    A real questbook.Ledger, built by questbook.build, so the digest is tested
    against the object the council actually acts on rather than a stand-in.
    """
    members = [
        questbook.Member(name="Grug", class_id=1, race_id=1, level=14,
                         rewarded=frozenset({100})),
        questbook.Member(name="Grog", class_id=2, race_id=1, level=10),
    ]
    catalog = {100: questbook.Quest(id=100, title="Kobold Candles", min_level=1)}
    return questbook.build(members, catalog)


class Building(unittest.TestCase):
    def test_the_family_comes_out_oldest_first(self):
        """bonds.speaking_order, not the alphabet.

        Alphabetical puts the seven-year-old first and the mother last in a
        report about how the family is.
        """
        built = digest.build(window(), live_family(), [], [])
        self.assertEqual(("Grug", "Ugga", "Og", "Grog", "Bork"), built.names)

    def test_moments_outside_the_window_are_dropped(self):
        inside = digest.Moment(NOW - datetime.timedelta(hours=1), "Bork", "said", "hi")
        outside = digest.Moment(NOW - datetime.timedelta(hours=30), "Bork", "said", "old")
        built = digest.build(window(6.0), live_family(), [], [inside, outside])
        self.assertEqual((inside,), built.moments)

    def test_a_digest_with_no_samples_is_not_measured(self):
        self.assertFalse(digest.build(window(), live_family(), [], []).measured)


class Rendering(unittest.TestCase):
    def account(self, samples=(), moments=(), ledger=None, hours=8.0):
        return digest.render(digest.build(
            window(hours), live_family(), list(samples), list(moments), ledger=ledger))

    def test_an_unsampled_window_never_claims_a_delta(self):
        """The central honesty test.

        With no samples there is no baseline, so no sentence may say anyone
        gained, turned in, learned or spent anything across the window.
        """
        text = self.account()
        for invented in ("gained", "turned in", "learned", "spent"):
            self.assertNotIn(invented, text, invented)
        self.assertIn("I cannot tell you what changed", text)

    def test_it_says_since_when_it_has_been_counting(self):
        rows = [sample("Grug", 60, level=14), sample("Grug", 5, level=14)]
        self.assertIn("only been keeping count since", self.account(samples=rows))

    def test_a_sampled_window_reports_the_real_movement(self):
        rows = [
            sample("Grug", 500, level=12, copper=11000, quests_done=9, spells=21),
            sample("Grug", 5, level=14, copper=24000, quests_done=13, spells=25),
        ]
        text = self.account(samples=rows)
        self.assertIn("gained 2 levels", text)
        self.assertIn("turned in 4 quests", text)
        self.assertIn("learned 4 spells", text)
        self.assertIn("made 1.3g", text)

    def test_the_gap_is_in_the_report_without_being_asked(self):
        text = self.account()
        self.assertIn("Og has 17 quest turn-ins", text)
        self.assertIn("Grog and Ugga are on 3", text)
        self.assertIn("0.3g", text)

    def test_grog_being_broke_is_explained_not_just_printed(self):
        self.assertIn("under a gold buys no training", self.account())

    def test_catching_up_is_questbooks_own_sentence(self):
        """Verbatim from questbook.say.

        Restating it here would be a second answer to "who is behind", given
        to Evan, that could disagree with the one the council acts on.
        """
        ledger = small_ledger()
        text = self.account(ledger=ledger)
        self.assertIn(questbook.say(ledger, "Grog"), text)
        self.assertIn("Kobold Candles", text)

    def test_nobody_behind_adds_no_catching_up_section(self):
        self.assertNotIn("Catching up:", self.account())

    def test_every_figure_carries_where_it_came_from(self):
        text = self.account()
        self.assertIn("Sources:", text)
        self.assertIn("PlayerSaveInterval", text)
        self.assertIn(digest.SOURCE_SNAPSHOT, text)

    def test_the_sample_table_is_only_credited_when_it_was_used(self):
        self.assertNotIn(digest.SOURCE_SAMPLE, self.account())
        rows = [sample("Grug", 500, level=12), sample("Grug", 5, level=14)]
        self.assertIn(digest.SOURCE_SAMPLE, self.account(samples=rows))

    def test_the_event_log_is_an_enrichment_and_never_a_requirement(self):
        """Same family, same window, with and without the sibling table."""
        plain = self.account()
        enriched = self.account(moments=[digest.Moment(
            NOW - datetime.timedelta(hours=2), "Og", "quest_complete",
            'finished "Kobold Candles"', digest.SOURCE_EVENT)])
        self.assertIn("Og has 17 quest turn-ins", plain)
        self.assertIn("Og has 17 quest turn-ins", enriched)
        self.assertIn("Kobold Candles", enriched)

    def test_chat_is_quoted_from_the_window(self):
        moments = [digest.Moment(NOW - datetime.timedelta(hours=1), "Bork", "said",
                                 "grog i am stuck in the well again",
                                 digest.SOURCE_CHAT)]
        text = self.account(moments=moments)
        self.assertIn("stuck in the well", text)
        self.assertIn(digest.SOURCE_CHAT, text)

    def test_the_women_are_not_called_he(self):
        rows = [sample("Ugga", 500, copper=30000), sample("Ugga", 5, copper=28000)]
        self.assertIn("Since then she spent", self.account(samples=rows))

    def test_an_empty_world_says_so_rather_than_rendering_nothing(self):
        text = digest.render(digest.build(window(), [], [], []))
        self.assertIn("nothing to tell you", text)


class Voicing(unittest.TestCase):
    """The LLM garnishes the account; it never supplies it."""

    def built(self):
        return digest.build(window(), live_family(), [], [])

    def test_the_prompt_hands_the_model_the_finished_account(self):
        prompt = digest.build_prompt(self.built())
        self.assertIn("Og has 17 quest turn-ins", prompt)
        self.assertIn("Invent no numbers", prompt)

    def test_the_prompt_speaks_as_the_head_of_the_family(self):
        prompt = digest.build_prompt(self.built())
        self.assertTrue(prompt.startswith("You are %s," % bonds.head_of_family()))

    def test_an_outage_still_produces_an_opening_line(self):
        line = digest.opening_line(self.built(), "")
        self.assertTrue(line)
        self.assertIn("Grug", line)

    def test_a_model_line_is_used_and_bounded(self):
        line = digest.opening_line(self.built(), "  Evan.  You are back.  ")
        self.assertEqual("Evan. You are back.", line)
        self.assertLessEqual(len(digest.opening_line(self.built(), "x" * 900)), 200)


class Purity(unittest.TestCase):
    """Same seam as questbook and bonds: facts in, judgements out.

    Logic that reaches for a connection, an HTTP client or Discord here
    escapes the test suite, which cannot import bridge.py at all (see
    test_specs). Asserted on the IMPORT GRAPH rather than on the text: the
    module docstring names pymysql in the course of promising not to use it,
    and a substring match would fail on the promise itself.
    """

    ALLOWED = {"__future__", "re", "dataclasses", "datetime", "bonds", "questbook"}

    def _imports(self):
        import ast
        import pathlib
        tree = ast.parse(pathlib.Path(digest.__file__).read_text(encoding="utf-8"))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module.split(".")[0])
        return names

    def test_it_imports_nothing_that_does_io(self):
        self.assertEqual(set(), self._imports() - self.ALLOWED)

    def test_it_reuses_questbook_rather_than_re_deciding_who_is_behind(self):
        self.assertIn("questbook", self._imports())


class BridgeWiring(unittest.TestCase):
    """Two things in bridge.py that fail silently if they are wrong.

    bridge.py imports discord and cannot be imported here - the tested seam is
    the pure modules by design - so these read the source, the same technique
    test_specs uses for the except-handler guards. Structural assertions, not
    text matches: they find the function and look at what it actually does.
    """

    @staticmethod
    def _tree():
        import ast
        import pathlib
        bridge = pathlib.Path(__file__).resolve().parents[1] / "bridge.py"
        return ast.parse(bridge.read_text(encoding="utf-8"))

    def _function(self, name):
        import ast
        for node in ast.walk(self._tree()):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
                return node
        raise AssertionError("%s not found in bridge.py" % name)

    def test_the_sampler_is_registered_as_a_loop(self):
        """A forever-loop nobody starts is a feature that silently never runs.

        setup_hook's own comment records the shape: an unheld task is garbage
        collected mid-flight and its loop simply stops, with nothing in the
        log. Here the cost is worse than a stopped loop - without the sampler
        there is never a baseline, so every digest forever reports
        BASIS_NO_BASELINE and the feature looks merely honest rather than
        broken.
        """
        import ast
        names = {
            n.attr for n in ast.walk(self._function("setup_hook"))
            if isinstance(n, ast.Attribute)
        }
        self.assertIn("_sample_family", names)

    def test_the_optional_event_table_can_never_take_the_report_down(self):
        """overseer_event belongs to a concurrent ticket.

        Absent, half-built or renamed, none of that may cost the digest the
        rest of its facts - so the read must sit inside a handler, and the
        chat read (which is what makes an unsampled night worth reading) must
        be its own.
        """
        import ast
        fetch = self._function("_fetch_moments")
        guarded = {
            node.func.id
            for try_ in ast.walk(fetch) if isinstance(try_, ast.Try)
            for node in ast.walk(try_)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertIn("_fetch_event_moments", guarded)
        self.assertIn("_fetch_chat_moments", guarded)

    def test_the_window_is_anchored_on_database_time(self):
        """Not on the pod's clock.

        Every timestamp the digest filters on is a MySQL TIMESTAMP read back
        as a naive datetime in the DATABASE's timezone, and the bridge is a
        separate pod. datetime.now() here passes every test and then, on a pod
        an hour off the database, drops every moment in the window and reports
        a quiet night.
        """
        import ast
        build = self._function("_build_digest")
        called = {
            n.func.id for n in ast.walk(build)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }
        self.assertIn("_db_now", called)
        attrs = {n.attr for n in ast.walk(build) if isinstance(n, ast.Attribute)}
        self.assertNotIn("now", attrs, "_build_digest reads a clock that is not the database's")


if __name__ == "__main__":
    unittest.main()
