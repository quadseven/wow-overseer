"""Family bonds: who answers a plea depends on who they are to the caller.

Evan's brief, verbatim, because every rule below traces to a clause of it:

  "grug is the dad and should always help his family unless he is mad at ugga
   getting helped by og too much, and bork is gonna constantly need help he is
   a little dumb kid always getting in trouble lol the younger brother to grog"

So: Grug answers unconditionally, EXCEPT Ugga, and only once Og has answered
her more than Grug finds tolerable. Bork's pleas are expected rather than
exceptional, so he is exempt from the fatigue that would otherwise mute a
character who calls constantly.

The history these decisions read is not new state - it is the `reflection`
rows kin already writes ("Grog called for help. I regrouped."), counted back.
Nothing here is a separate memory the store could disagree with.
"""

import ast
import pathlib
import unittest

import bonds
import kin


def _row(name, level=5, *, is_bot=True, guild_id=7):
    return {"name": name, "level": level, "is_bot": is_bot, "guild_id": guild_id}


FAMILY_ROSTER = [
    _row("Grug", 8),
    _row("Ugga", 6),
    _row("Grog", 7),
    _row("Bork", 4),
    _row("Og", 6),
]

# kin scopes by an explicit name set; bonds is where that set is defined.
FAMILY = set(bonds.FAMILY)


class RolesTest(unittest.TestCase):
    def test_every_family_member_has_a_role(self):
        for who in ("Grug", "Ugga", "Grog", "Bork", "Og"):
            self.assertIn(who, bonds.FAMILY, who)

    def test_og_is_not_blood(self):
        """He lives by the river. It matters for exactly one rule."""
        self.assertFalse(bonds.FAMILY["Og"].blood)
        self.assertTrue(bonds.FAMILY["Grog"].blood)

    def test_bork_is_the_youngest(self):
        levels = {n: b.seniority for n, b in bonds.FAMILY.items() if b.blood}
        self.assertEqual(min(levels, key=levels.get), "Bork")

    def test_lookup_is_case_insensitive_because_chat_is(self):
        self.assertIs(bonds.member("grug"), bonds.member("Grug"))
        self.assertIsNone(bonds.member("Thrall"))


class GrugAlwaysHelpsTest(unittest.TestCase):
    def test_grug_answers_his_children(self):
        for child in ("Grog", "Bork"):
            d = bonds.decide("Grug", kin.Plea(child, "a quest"), history=[])
            self.assertTrue(d.will_answer, child)

    def test_grug_answers_ugga_when_nothing_is_wrong(self):
        d = bonds.decide("Grug", kin.Plea("Ugga", "a quest"), history=[])
        self.assertTrue(d.will_answer)

    def test_grug_answers_even_the_neighbour(self):
        d = bonds.decide("Grug", kin.Plea("Og", "a quest"), history=[])
        self.assertTrue(d.will_answer)


class GrugIsMadTest(unittest.TestCase):
    """'unless he is mad at ugga getting helped by og too much'"""

    def _og_helped_ugga(self, n):
        return [("Og", "Ugga")] * n

    def test_one_or_two_times_is_fine(self):
        for n in (1, 2):
            d = bonds.decide(
                "Grug", kin.Plea("Ugga", "a quest"), history=self._og_helped_ugga(n)
            )
            self.assertTrue(d.will_answer, n)

    def test_past_the_threshold_grug_sulks(self):
        # Same history as test_nobody_else_is_jealous. The pair is the point:
        # identical input, and only Grug refuses.
        d = bonds.decide(
            "Grug",
            kin.Plea("Ugga", "a quest"),
            history=self._og_helped_ugga(bonds.JEALOUSY_THRESHOLD),
        )
        self.assertFalse(d.will_answer)
        self.assertIn("Og", d.reason)

    def test_the_sulk_is_only_about_ugga(self):
        """Grug does not take it out on the children."""
        h = self._og_helped_ugga(bonds.JEALOUSY_THRESHOLD + 5)
        for other in ("Grog", "Bork", "Og"):
            d = bonds.decide("Grug", kin.Plea(other, "a quest"), history=h)
            self.assertTrue(d.will_answer, other)

    def test_og_helping_anyone_else_does_not_bother_him(self):
        h = [("Og", "Grog")] * (bonds.JEALOUSY_THRESHOLD + 5)
        d = bonds.decide("Grug", kin.Plea("Ugga", "a quest"), history=h)
        self.assertTrue(d.will_answer)

    def test_grug_helping_ugga_himself_does_not_make_him_jealous(self):
        h = [("Grug", "Ugga")] * (bonds.JEALOUSY_THRESHOLD + 5)
        d = bonds.decide("Grug", kin.Plea("Ugga", "a quest"), history=h)
        self.assertTrue(d.will_answer)

    def test_nobody_else_is_jealous(self):
        """Exactly at the jealousy threshold and below the fatigue one, so this
        isolates jealousy. The first version used threshold+5, which is 8
        answers to Ugga and therefore tripped FATIGUE instead - it would have
        passed for the wrong reason if the jealousy rule were deleted."""
        self.assertLess(bonds.JEALOUSY_THRESHOLD, bonds.FATIGUE_THRESHOLD)
        h = self._og_helped_ugga(bonds.JEALOUSY_THRESHOLD)
        for who in ("Grog", "Bork", "Og"):
            d = bonds.decide(who, kin.Plea("Ugga", "a quest"), history=h)
            self.assertTrue(d.will_answer, who)


class BorkTest(unittest.TestCase):
    """'bork is gonna constantly need help he is a little dumb kid always
    getting in trouble lol the younger brother to grog'

    Read as two clauses, not one: Bork calls constantly (so the rest of the
    family does eventually stop dropping everything), and he is Grog's little
    brother (so Grog does not). Bork was briefly exempt from fatigue outright,
    which made the little-brother rule decoration - it could not change an
    outcome, because the caller it applies to was already exempt.
    """

    def test_the_family_does_tire_of_a_caller_who_will_not_stop(self):
        h = [("Og", "Bork")] * bonds.FATIGUE_THRESHOLD
        d = bonds.decide("Og", kin.Plea("Bork", "a quest"), history=h)
        self.assertFalse(d.will_answer)
        self.assertIn("already", d.reason)

    def test_fatigue_is_per_pair_so_it_means_the_same_at_any_roster_size(self):
        """Og answering Grog says nothing about whether Ugga will. Counting
        every answer to a caller instead made the threshold fire after two
        pleas with five online and five pleas with two - the same number
        meaning different things depending on who was logged in."""
        h = [("Og", "Bork")] * (bonds.FATIGUE_THRESHOLD * 3)
        self.assertTrue(
            bonds.decide("Ugga", kin.Plea("Bork", "q"), history=h).will_answer
        )

    def test_grug_himself_never_tires(self):
        h = [("Grug", "Grog")] * (bonds.FATIGUE_THRESHOLD * 4)
        d = bonds.decide("Grug", kin.Plea("Grog", "a quest"), history=h)
        self.assertTrue(d.will_answer)

    def test_grog_never_tires_of_his_little_brother(self):
        """The rule now has teeth: it is the only thing that keeps someone
        turning up for Bork after everyone else has had enough."""
        h = [("Grog", "Bork")] * (bonds.FATIGUE_THRESHOLD * 3)
        d = bonds.decide("Grog", kin.Plea("Bork", "a quest"), history=h)
        self.assertTrue(d.will_answer)
        self.assertIn("brother", d.reason.lower())

    def test_the_little_brother_rule_is_grogs_and_not_everyones(self):
        """Ugga outranks Bork and shares his blood, so a rule keyed on
        seniority had her answering as his big BROTHER - she is his mother.
        It is the elder son's rule."""
        h = [("Ugga", "Bork")] * (bonds.FATIGUE_THRESHOLD * 3)
        d = bonds.decide("Ugga", kin.Plea("Bork", "a quest"), history=h)
        self.assertFalse(d.will_answer, d.reason)
        self.assertNotIn("brother", d.reason.lower())

    def test_bork_still_gets_help_from_the_two_who_owe_him_it(self):
        """The end state after the family has tired: dad and big brother."""
        h = [
            (n, "Bork")
            for n in ("Grug", "Ugga", "Grog", "Og")
            for _ in range(bonds.FATIGUE_THRESHOLD * 2)
        ]
        came = [
            n
            for n in ("Grug", "Ugga", "Grog", "Og")
            if bonds.decide(n, kin.Plea("Bork", "q"), history=h).will_answer
        ]
        self.assertEqual(came, ["Grug", "Grog"])


class ApplyToMusterTest(unittest.TestCase):
    def test_bonds_filter_a_real_muster(self):
        m = kin.plan_muster(
            kin.Plea("Ugga", "a quest"),
            FAMILY_ROSTER,
            family=FAMILY,
            last_muster_at=None,
            now=100.0,
        )
        before = [a.character_name for a in m.actions]
        self.assertIn("Grug", before)

        filtered = bonds.apply(
            m,
            kin.Plea("Ugga", "a quest"),
            history=[("Og", "Ugga")] * bonds.JEALOUSY_THRESHOLD,
        )
        after = [a.character_name for a in filtered.actions]
        self.assertNotIn("Grug", after)
        self.assertIn("Og", after)

    def test_memories_follow_the_filter(self):
        """A responder who did not go must not remember going."""
        m = kin.plan_muster(
            kin.Plea("Ugga", ""),
            FAMILY_ROSTER,
            family=FAMILY,
            last_muster_at=None,
            now=100.0,
        )
        filtered = bonds.apply(
            m, kin.Plea("Ugga", ""), history=[("Og", "Ugga")] * bonds.JEALOUSY_THRESHOLD
        )
        self.assertNotIn("Grug", filtered.responder_memories)
        for name in filtered.responder_memories:
            self.assertIn(name, [a.character_name for a in filtered.actions])

    def test_the_caller_memory_names_only_who_actually_came(self):
        m = kin.plan_muster(
            kin.Plea("Ugga", ""),
            FAMILY_ROSTER,
            family=FAMILY,
            last_muster_at=None,
            now=100.0,
        )
        filtered = bonds.apply(
            m, kin.Plea("Ugga", ""), history=[("Og", "Ugga")] * bonds.JEALOUSY_THRESHOLD
        )
        self.assertNotIn("Grug", filtered.caller_memory)

    def test_everyone_refusing_leaves_no_actions_and_says_why(self):
        m = kin.plan_muster(
            kin.Plea("Ugga", ""),
            FAMILY_ROSTER,
            family=FAMILY,
            last_muster_at=None,
            now=100.0,
        )
        heavy = (
            [("Og", "Ugga")] * bonds.JEALOUSY_THRESHOLD
            + [("Grog", "Ugga")] * bonds.FATIGUE_THRESHOLD
            + [("Bork", "Ugga")] * bonds.FATIGUE_THRESHOLD
            + [("Og", "Ugga")] * bonds.FATIGUE_THRESHOLD
        )
        filtered = bonds.apply(m, kin.Plea("Ugga", ""), history=heavy)
        # Unconditional. Guarded by `if not filtered.actions` this passed the
        # moment anyone came - a green light that stays green precisely when
        # the rule it guards stops firing.
        self.assertEqual(filtered.actions, [])
        self.assertIn("nobody came", filtered.reason)
        for who in ("Grug", "Grog", "Bork", "Og"):
            self.assertIn(who, filtered.reason)

    def test_a_stranger_outside_the_family_is_untouched(self):
        """bonds only has opinions about the family. Anyone else passes.

        Built by hand, not through plan_muster: scoped by `family` it refuses
        Thrall outright, so routing through it compared [] to [] and never
        reached decide() at all.
        """
        m = kin.Muster(
            actions=[kin.KinAction("Thrall", ["follow"])],
            reason="",
            caller_memory="I called for help and Thrall regrouped.",
            responder_memories={"Thrall": "Ugga called for help. I regrouped."},
        )
        heavy = [("Thrall", "Ugga")] * (bonds.FATIGUE_THRESHOLD * 4)
        filtered = bonds.apply(m, kin.Plea("Ugga", ""), history=heavy)
        self.assertEqual([a.character_name for a in filtered.actions], ["Thrall"])
        self.assertTrue(
            bonds.decide("Thrall", kin.Plea("Ugga", ""), history=heavy).will_answer
        )
        self.assertTrue(
            bonds.decide("Grug", kin.Plea("Thrall", ""), history=heavy).will_answer
        )


class HistoryTest(unittest.TestCase):
    def test_history_is_parsed_out_of_reflection_rows(self):
        rows = [
            {
                "character_name": "Og",
                "text": "Ugga called for help with a quest. I regrouped.",
            },
            {"character_name": "Grug", "text": "I called for help and Og regrouped."},
            {"character_name": "Bork", "text": "Grog called for help. I regrouped."},
        ]
        pairs = bonds.history_from_thoughts(rows)
        self.assertIn(("Og", "Ugga"), pairs)
        self.assertIn(("Bork", "Grog"), pairs)
        # The caller's own first-person memory is not a helping event.
        self.assertNotIn(("Grug", "Og"), pairs)

    def test_unparseable_rows_are_skipped_not_guessed(self):
        rows = [{"character_name": "Og", "text": "the boars are angry today"}]
        self.assertEqual(bonds.history_from_thoughts(rows), [])


class InertRuleTest(unittest.TestCase):
    """Each test here killed a mutant that the rest of the suite let live.

    Written after mutating every branch in decide(): three survived, meaning
    three of the five family rules were decoration. Same failure the kin.py
    plea guards had earlier - green, and doing nothing.
    """

    def test_the_jealousy_rule_can_be_reached_from_a_real_history(self):
        """The counters are fed by rows the bridge writes, and one plea writes
        one row per responder. Under a per-caller tally Og fatigued out after
        two pleas, capping his answers to Ugga at two against a threshold of
        three - so Grug could never get jealous with the family online. This
        drives the real loop rather than a hand-built history."""
        roster = [_row(n) for n in bonds.FAMILY]
        rows, jealous = [], False
        for _ in range(6):
            plea = kin.Plea("Ugga", "a quest")
            m = kin.plan_muster(
                plea, roster, family=FAMILY, last_muster_at=None, now=0.0
            )
            m = bonds.apply(m, plea, history=bonds.history_from_thoughts(rows))
            came = [a.character_name for a in m.actions]
            if "Og" in came and "Grug" not in came:
                jealous = True
                break
            for n in came:
                rows.append({"character_name": n, "text": m.responder_memories[n]})
        self.assertTrue(jealous, "Grug never got jealous over a real history")


class CasingTest(unittest.TestCase):
    """The history is parsed out of free text an LLM wrote, so the casing of a
    name is not guaranteed. Every count goes through canon() for that reason;
    comparing raw let a lowercase "og" silently zero the tally, which looks
    exactly like a rule that was never going to fire."""

    def test_a_lowercase_helper_still_counts_against_grug(self):
        h = [("og", "ugga")] * bonds.JEALOUSY_THRESHOLD
        d = bonds.decide("grug", kin.Plea("UGGA", "q"), history=h)
        self.assertFalse(d.will_answer, d.reason)

    def test_a_lowercase_pair_still_tires_the_family(self):
        h = [("OG", "grog")] * bonds.FATIGUE_THRESHOLD
        self.assertFalse(
            bonds.decide("og", kin.Plea("Grog", "q"), history=h).will_answer
        )

    def test_history_from_thoughts_keeps_whatever_casing_it_read(self):
        """Proves the counters cannot rely on the store being canonical."""
        pairs = bonds.history_from_thoughts(
            [{"character_name": "og", "text": "ugga called for help. I regrouped."}]
        )
        self.assertEqual(pairs, [("og", "ugga")])


class MemoryTest(unittest.TestCase):
    def test_a_narrowed_muster_keeps_everything_the_caller_said(self):
        """apply used to recover the subject by splitting kin's rendered
        sentence on " and ", which cannot tell the separator kin inserted from
        one the speaker said. "my warrior quest and the boars" came back as
        "my warrior quest" - a memory of something that did not happen, in the
        one store these characters treat as true."""
        plea = kin.parse_plea("Grog", "I need help with my warrior quest and the boars")
        self.assertIsNotNone(plea)
        m = kin.plan_muster(
            plea,
            [_row(n) for n in bonds.FAMILY],
            family=FAMILY,
            last_muster_at=None,
            now=0.0,
        )
        heavy = [("Og", "Grog")] * (bonds.FATIGUE_THRESHOLD * 2)
        filtered = bonds.apply(m, plea, history=heavy)
        self.assertNotEqual(filtered.actions, m.actions)
        self.assertIn("the boars", filtered.caller_memory)
        self.assertIn("the boars", m.caller_memory)


class WiringTest(unittest.TestCase):
    """bonds.py can be perfect and never called.

    bridge.py cannot be imported here - it needs pymysql, discord and a live
    MySQL - so this walks its AST instead. An AST walk and not a grep on
    purpose: `bonds.apply` written in a comment or a docstring satisfies a
    grep, and a comment musters nobody.
    """

    @classmethod
    def setUpClass(cls):
        src = (pathlib.Path(__file__).resolve().parent.parent / "bridge.py").read_text()
        tree = ast.parse(src)
        cls.fn = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "_muster_for_pleas"
        )
        cls.calls = [n for n in ast.walk(cls.fn) if isinstance(n, ast.Call)]

    def _call(self, dotted: str):
        want = dotted.split(".")
        for c in self.calls:
            f = c.func
            if (
                isinstance(f, ast.Attribute)
                and isinstance(f.value, ast.Name)
                and [f.value.id, f.attr] == want
            ):
                return c
        return None

    def test_the_bridge_narrows_every_muster_through_bonds(self):
        self.assertIsNotNone(
            self._call("bonds.apply"),
            "_muster_for_pleas never calls bonds.apply - the family rules are "
            "dead code and every kin member answers every plea",
        )

    def test_the_bridge_scopes_the_muster_to_the_family(self):
        call = self._call("kin.plan_muster")
        self.assertIsNotNone(call, "_muster_for_pleas no longer plans a muster")
        self.assertIn(
            "family",
            [k.arg for k in call.keywords],
            "plan_muster called without family= - kin would muster the realm",
        )

    def test_the_reflection_window_is_a_clock_not_a_row_count(self):
        """A row-count window only advances when rows are written, and a
        muster everyone refuses writes none - so a family that stopped helping
        each other could never start again, and said so only to the log."""
        src = (pathlib.Path(__file__).resolve().parent.parent / "bridge.py").read_text()
        fetch = src[src.index("def _fetch_reflections") :]
        fetch = fetch[: fetch.index("\ndef ")]
        self.assertIn("INTERVAL", fetch)
        self.assertIn("created_at", fetch)

    def test_bonds_judges_on_real_memories_not_an_empty_history(self):
        """Passing history=[] would keep every test green and every rule inert:
        jealousy and fatigue are both counts over past helping."""
        call = self._call("bonds.apply")
        self.assertIsNotNone(call)
        hist = next((k.value for k in call.keywords if k.arg == "history"), None)
        self.assertIsNotNone(hist, "bonds.apply called without history=")
        self.assertNotIsInstance(
            hist,
            ast.List,
            "history= is a literal list - the bonds rules can never fire",
        )


class HeadOfFamilyTest(unittest.TestCase):
    """mod-overseer forms the party from whoever is online, in name order, so
    the leader landed on whoever sorts first - which put Bork, the youngest,
    in charge. The module has no idea who these characters are to each other;
    this is where that is written down."""

    def test_the_father_leads(self):
        self.assertEqual(bonds.head_of_family(), "Grug")

    def test_it_is_read_from_the_family_table_not_hardcoded(self):
        """A second answer here could disagree with FAMILY, which is the one
        place the relationships are written."""
        senior = max(bonds.FAMILY, key=lambda n: bonds.FAMILY[n].seniority)
        self.assertEqual(bonds.head_of_family(), senior)

    def test_it_is_not_simply_the_first_name_alphabetically(self):
        """The exact bug being corrected."""
        self.assertNotEqual(bonds.head_of_family(), sorted(bonds.FAMILY)[0])


class WindowContaminationTest(unittest.TestCase):
    """The bond rules count helping. Anything else in their window is noise
    that can evict the thing being counted.

    Measured on the live table before the fix: of 71 rows in the window,
    66 were council speech and 5 were real muster memories. The window is
    bounded, so a busier council evicts the memories entirely and the
    jealousy and fatigue rules stop being able to fire - silently, because
    an empty history is indistinguishable from a peaceful family.
    """

    def test_council_speech_contributes_no_pairs(self):
        """Which is exactly why it must not be stored where bonds looks."""
        council_rows = [
            {
                "character_name": "Grug",
                "text": "Og is still 4. We should not leave them behind.",
            },
            {"character_name": "Ugga", "text": "Aye."},
            {"character_name": "Grug", "text": "Then it is settled."},
        ]
        self.assertEqual(bonds.history_from_thoughts(council_rows), [])

    def test_a_window_of_council_speech_starves_the_rules(self):
        """The failure, reproduced: real memories crowded out by chatter that
        parses to nothing."""
        real = [
            {"character_name": "Og", "text": "Ugga called for help. I regrouped."}
        ] * 3
        chatter = [{"character_name": "Ugga", "text": "Aye."}] * 60

        healthy = bonds.history_from_thoughts(real)
        self.assertGreaterEqual(len(healthy), bonds.JEALOUSY_THRESHOLD)
        self.assertFalse(
            bonds.decide("Grug", kin.Plea("Ugga", "q"), history=healthy).will_answer
        )

        # Same window size, but the memories have been pushed out of it.
        starved = bonds.history_from_thoughts(chatter[:60] + real[:0])
        self.assertEqual(starved, [])
        self.assertTrue(
            bonds.decide("Grug", kin.Plea("Ugga", "q"), history=starved).will_answer,
            "with the memories evicted Grug can never get jealous, and nothing says so",
        )

    def test_the_bridge_does_not_write_council_speech_where_bonds_reads(self):
        """bridge.py needs pymysql and discord, so this walks its AST."""
        import ast
        import pathlib

        src = (pathlib.Path(__file__).resolve().parent.parent / "bridge.py").read_text()
        fn = next(
            n
            for n in ast.walk(ast.parse(src))
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "_council_once"
        )
        tags = [
            n.value
            for n in ast.walk(fn)
            if isinstance(n, ast.Constant) and n.value in ("reflection", "council")
        ]
        self.assertIn("council", tags)
        self.assertNotIn(
            "reflection",
            tags,
            "council speech tagged 'reflection' lands in the window "
            "the bond rules count, and crowds out the memories",
        )

    def test_every_declaration_of_the_source_column_admits_the_new_tag(self):
        """A tag the ENUM rejects is an insert that fails, every council.

        Checks the ENUM LISTS themselves, not merely that the word 'council'
        appears somewhere in the file - the first version of this test did the
        latter and passed happily against an enum that had been stripped of it,
        because the word still occurred in the insert two lines away.
        """
        import pathlib
        import re

        src = (pathlib.Path(__file__).resolve().parent.parent / "bridge.py").read_text()
        # Only the ones that describe `source`. The file also declares enums
        # for goal kind and status, and matching those made this fail for the
        # wrong reason.
        enums = [b for b in re.findall(r"ENUM\(([^)]*)\)", src) if "'reflection'" in b]
        self.assertEqual(
            len(enums), 2, "expected the CREATE and the MODIFY, found %d" % len(enums)
        )
        for body in enums:
            self.assertIn(
                "'council'", body, "this enum rejects the council tag: %s" % body
            )

    def test_the_live_table_is_widened_not_just_the_create(self):
        """overseer_thought already exists, so CREATE TABLE IF NOT EXISTS is a
        no-op against it and cannot add a value to the enum on its own."""
        import pathlib

        src = (pathlib.Path(__file__).resolve().parent.parent / "bridge.py").read_text()
        self.assertIn("MODIFY source", src)


class SpeakingOrderTest(unittest.TestCase):
    """Who speaks first when the whole family answers one order at once.

    overhear.audience sorts alphabetically, which is the right answer for who
    ACTS and the wrong one for who speaks: it put the seven-year-old at the
    head of every exchange and his mother at the end of it.
    """

    def test_the_family_answers_oldest_first(self):
        self.assertEqual(
            bonds.speaking_order(["Bork", "Grog", "Og", "Ugga"]),
            ["Ugga", "Og", "Grog", "Bork"],
        )

    def test_it_does_not_depend_on_what_order_it_was_handed(self):
        for given in (["Og", "Ugga", "Bork", "Grog"], ["Grog", "Bork", "Ugga", "Og"]):
            self.assertEqual(
                bonds.speaking_order(given), ["Ugga", "Og", "Grog", "Bork"]
            )

    def test_it_agrees_with_who_leads(self):
        """Seniority is the family table's one answer to who comes first. A
        second answer here could disagree with head_of_family."""
        self.assertEqual(bonds.speaking_order(bonds.FAMILY)[0], bonds.head_of_family())

    def test_chat_casing_does_not_demote_anyone(self):
        """Names arrive from chat rows, which are whatever was typed."""
        self.assertEqual(bonds.speaking_order(["bork", "ugga"]), ["ugga", "bork"])

    def test_strangers_sort_after_the_family_not_among_it(self):
        """This module has no opinion about a stranger's standing, and
        inventing one would put an outsider ahead of the father."""
        self.assertEqual(
            bonds.speaking_order(["Thrall", "Bork", "Ugga", "Arthas"]),
            ["Ugga", "Bork", "Arthas", "Thrall"],
        )

    def test_nobody_is_added_or_lost(self):
        """It orders an audience; it never changes who is in it."""
        given = ["Bork", "Grog", "Og", "Ugga"]
        self.assertCountEqual(bonds.speaking_order(given), given)
        self.assertEqual(bonds.speaking_order([]), [])


class WhoAnswersWhoTest(unittest.TestCase):
    """`answers` is the same rules asked about every pair instead of about one
    plea, and the failure it can have is not "wrong" but "plausible": a row
    that says COUNTING while `decide` would refuse renders perfectly and lies.

    The class that catches that is TheViewAgreesWithTheWorld below. These are
    the readable half - what a person is actually shown.
    """

    def rows(self, history):
        return {r.key: r for r in bonds.answers(history)}

    def test_the_two_written_exceptions_are_always_shown(self):
        """They are the rules a reader has come to check. A section that only
        appeared once somebody had already answered somebody would be empty on
        exactly the day you wanted to know what the rules were."""
        rows = self.rows([])
        self.assertIn("Grug>Ugga", rows)
        self.assertIn("Grog>Bork", rows)

    def test_an_ordinary_pair_nobody_has_answered_is_not_a_row(self):
        """Twenty rows of "nothing has happened" would drown the two or three
        that are asking for something - the same reason materials.plan does not
        note a stack already in the right bags."""
        self.assertNotIn("Bork>Grog", self.rows([]))

    def test_it_appears_the_moment_somebody_has_actually_answered(self):
        self.assertIn("Bork>Grog", self.rows([("Bork", "Grog")]))

    def test_the_fathers_counter_counts_somebody_elses_answers(self):
        """THE RULE THAT IS EASIEST TO GET WRONG. What stops Grug going to Ugga
        is not how often GRUG has answered her - it is how often Og has. A row
        labelled with the responder's own tally would be a different number,
        moving at a different speed, under the right words."""
        row = self.rows([("Og", "Ugga"), ("Og", "Ugga")])["Grug>Ugga"]
        self.assertEqual(row.counted, bonds.SUSPICION["with"])
        self.assertEqual(row.count, 2)
        self.assertEqual(row.threshold, bonds.JEALOUSY_THRESHOLD)
        self.assertIn(bonds.SUSPICION["with"], row.progress)

    def test_the_fathers_own_answers_do_not_move_that_counter(self):
        row = self.rows([("Grug", "Ugga")] * 9)["Grug>Ugga"]
        self.assertEqual(row.count, 0)

    def test_it_says_stopped_once_the_rule_has_fired(self):
        row = self.rows([("Og", "Ugga")] * bonds.JEALOUSY_THRESHOLD)["Grug>Ugga"]
        self.assertEqual(row.word, bonds.STOPPED)
        self.assertFalse(row.will_answer)

    def test_the_little_brother_is_exempt_rather_than_merely_ahead(self):
        """Bork calls constantly and that is characterisation. The row must say
        EXEMPT however many times Grog has been - a counter here would read as
        a big brother about to run out, which is the opposite of the rule."""
        row = self.rows([("Grog", "Bork")] * 50)["Grog>Bork"]
        self.assertEqual(row.word, bonds.EXEMPT)
        self.assertIsNone(row.threshold)
        self.assertIsNone(row.pct)
        self.assertEqual(row.progress, "")

    def test_a_refusal_sorts_above_a_counter_and_a_counter_above_an_exemption(self):
        """A refusal is the news. An exemption is the background it is read
        against, and putting the background first buries the finding."""
        words = [
            r.word
            for r in bonds.answers(
                [("Og", "Ugga")] * bonds.JEALOUSY_THRESHOLD + [("Bork", "Grog")]
            )
        ]
        self.assertEqual(words[0], bonds.STOPPED)
        self.assertLess(words.index(bonds.COUNTING), words.index(bonds.EXEMPT))

    def test_the_bar_never_runs_past_the_end(self):
        """A pair can be answered past its threshold - the rule stops the NEXT
        answer, it does not erase the last one - and a bar at 140% is a
        rendering bug wearing a fact."""
        row = self.rows([("Og", "Ugga")] * 20)["Grug>Ugga"]
        self.assertEqual(row.pct, 100)

    def test_the_sentence_agrees_with_the_number_it_carries(self):
        """ "answered Bork 1 times" makes a reader distrust the count as well as
        the grammar."""
        row = self.rows([("Bork", "Grog")])["Bork>Grog"]
        self.assertIn("1 time ", row.note + " ")
        self.assertNotIn("1 times", row.note)

    def test_no_note_reaches_for_a_pronoun_it_cannot_know(self):
        """This family is a mother, a father and three boys. A sentence that
        says "her" has to know which of them it is about; naming both sides
        costs a few characters and cannot be wrong."""
        for row in bonds.answers([("Og", "Ugga")] * 2 + [("Ugga", "Bork")]):
            for pronoun in (" he ", " she ", " him ", " her ", " his "):
                self.assertNotIn(pronoun, " " + row.note + " ", row.note)


class TheViewAgreesWithTheWorld(unittest.TestCase):
    """The one failure that would look fine on screen.

    `_counter` mirrors `decide` branch for branch so a row can say WHOSE
    answers it is counting. Two copies of one rule start identical and drift
    the first time either is edited - which is exactly how the little-brother
    rule spent a release being decoration. So every row is checked against
    `decide` itself rather than against a second reading of the docstring."""

    def histories(self):
        return [
            [],
            [("Og", "Ugga")] * 2,
            [("Og", "Ugga")] * bonds.JEALOUSY_THRESHOLD,
            [("Grog", "Bork")] * (bonds.FATIGUE_THRESHOLD + 2),
            [("Ugga", "Bork")] * bonds.FATIGUE_THRESHOLD,
            [(h, c) for h in bonds.FAMILY for c in bonds.FAMILY if h != c] * 3,
        ]

    def test_every_verdict_is_the_one_decide_would_give(self):
        for history in self.histories():
            for row in bonds.answers(history):
                verdict = bonds.decide(
                    row.responder, bonds._Call(row.caller), history=history
                )
                self.assertEqual(
                    row.will_answer, verdict.will_answer, (row.key, len(history))
                )
                self.assertEqual(row.reason, verdict.reason, row.key)

    def test_stopped_and_will_answer_can_never_disagree(self):
        for history in self.histories():
            for row in bonds.answers(history):
                self.assertEqual(
                    row.word == bonds.STOPPED, not row.will_answer, (row.key, row.word)
                )

    def test_a_counter_that_has_reached_its_threshold_has_stopped(self):
        """The whole promise of the bar: when it fills, something changes."""
        for history in self.histories():
            for row in bonds.answers(history):
                if row.threshold and row.count >= row.threshold:
                    self.assertEqual(row.word, bonds.STOPPED, row.key)


class TheCardNoteTest(unittest.TestCase):
    def test_it_prefers_what_this_character_does(self):
        """A card is about that character. Where they are the responder comes
        first; where they are the caller is still their business, because
        somebody having stopped coming when you ask is a fact about you."""
        note = bonds.note_for("Grog", history=[])
        self.assertIn("Grog", note)
        self.assertIn("Bork", note)

    def test_a_caller_only_row_still_says_something_about_them(self):
        note = bonds.note_for("Ugga", history=[("Og", "Ugga")] * 2)
        self.assertIn("Ugga", note)
        self.assertIn(bonds.SUSPICION["with"], note)

    def test_nobody_gets_a_blank(self):
        """A card with no bond note reads as a family with no bonds."""
        for name in bonds.FAMILY:
            self.assertTrue(bonds.note_for(name, history=[]).strip(), name)

    def test_somebody_outside_the_family_gets_nothing_rather_than_a_guess(self):
        self.assertEqual(bonds.note_for("Thrall", history=[]), "")


class TheStandingRuleIsBuiltFromTheThresholds(unittest.TestCase):
    def test_it_quotes_the_numbers_rather_than_repeating_them(self):
        """A sentence with a 5 typed into it goes on claiming five the day
        somebody changes FATIGUE_THRESHOLD, and reads exactly as convincingly."""
        rule = bonds.answering_rule()
        self.assertIn(str(bonds.FATIGUE_THRESHOLD), rule)
        self.assertIn(str(bonds.JEALOUSY_THRESHOLD), rule)
        self.assertIn(bonds.SUSPICION["with"], rule)


if __name__ == "__main__":
    unittest.main()
