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


FAMILY_ROSTER = [_row("Grug", 8), _row("Ugga", 6), _row("Grog", 7),
                 _row("Bork", 4), _row("Og", 6)]

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
            d = bonds.decide("Grug", kin.Plea("Ugga", "a quest"),
                             history=self._og_helped_ugga(n))
            self.assertTrue(d.will_answer, n)

    def test_past_the_threshold_grug_sulks(self):
        # Same history as test_nobody_else_is_jealous. The pair is the point:
        # identical input, and only Grug refuses.
        d = bonds.decide("Grug", kin.Plea("Ugga", "a quest"),
                         history=self._og_helped_ugga(bonds.JEALOUSY_THRESHOLD))
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
        self.assertTrue(bonds.decide("Ugga", kin.Plea("Bork", "q"), history=h).will_answer)

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
        h = [(n, "Bork") for n in ("Grug", "Ugga", "Grog", "Og")
             for _ in range(bonds.FATIGUE_THRESHOLD * 2)]
        came = [n for n in ("Grug", "Ugga", "Grog", "Og")
                if bonds.decide(n, kin.Plea("Bork", "q"), history=h).will_answer]
        self.assertEqual(came, ["Grug", "Grog"])


class ApplyToMusterTest(unittest.TestCase):
    def test_bonds_filter_a_real_muster(self):
        m = kin.plan_muster(kin.Plea("Ugga", "a quest"), FAMILY_ROSTER,
                            family=FAMILY, last_muster_at=None, now=100.0)
        before = [a.character_name for a in m.actions]
        self.assertIn("Grug", before)

        filtered = bonds.apply(m, kin.Plea("Ugga", "a quest"),
                               history=[("Og", "Ugga")] * bonds.JEALOUSY_THRESHOLD)
        after = [a.character_name for a in filtered.actions]
        self.assertNotIn("Grug", after)
        self.assertIn("Og", after)

    def test_memories_follow_the_filter(self):
        """A responder who did not go must not remember going."""
        m = kin.plan_muster(kin.Plea("Ugga", ""), FAMILY_ROSTER,
                            family=FAMILY, last_muster_at=None, now=100.0)
        filtered = bonds.apply(m, kin.Plea("Ugga", ""),
                               history=[("Og", "Ugga")] * bonds.JEALOUSY_THRESHOLD)
        self.assertNotIn("Grug", filtered.responder_memories)
        for name in filtered.responder_memories:
            self.assertIn(name, [a.character_name for a in filtered.actions])

    def test_the_caller_memory_names_only_who_actually_came(self):
        m = kin.plan_muster(kin.Plea("Ugga", ""), FAMILY_ROSTER,
                            family=FAMILY, last_muster_at=None, now=100.0)
        filtered = bonds.apply(m, kin.Plea("Ugga", ""),
                               history=[("Og", "Ugga")] * bonds.JEALOUSY_THRESHOLD)
        self.assertNotIn("Grug", filtered.caller_memory)

    def test_everyone_refusing_leaves_no_actions_and_says_why(self):
        m = kin.plan_muster(kin.Plea("Ugga", ""), FAMILY_ROSTER,
                            family=FAMILY, last_muster_at=None, now=100.0)
        heavy = ([("Og", "Ugga")] * bonds.JEALOUSY_THRESHOLD
                 + [("Grog", "Ugga")] * bonds.FATIGUE_THRESHOLD
                 + [("Bork", "Ugga")] * bonds.FATIGUE_THRESHOLD
                 + [("Og", "Ugga")] * bonds.FATIGUE_THRESHOLD)
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
            reason="", caller_memory="I called for help and Thrall regrouped.",
            responder_memories={"Thrall": "Ugga called for help. I regrouped."},
        )
        heavy = [("Thrall", "Ugga")] * (bonds.FATIGUE_THRESHOLD * 4)
        filtered = bonds.apply(m, kin.Plea("Ugga", ""), history=heavy)
        self.assertEqual([a.character_name for a in filtered.actions], ["Thrall"])
        self.assertTrue(bonds.decide("Thrall", kin.Plea("Ugga", ""),
                                     history=heavy).will_answer)
        self.assertTrue(bonds.decide("Grug", kin.Plea("Thrall", ""),
                                     history=heavy).will_answer)


class HistoryTest(unittest.TestCase):
    def test_history_is_parsed_out_of_reflection_rows(self):
        rows = [
            {"character_name": "Og", "text": "Ugga called for help with a quest. I regrouped."},
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
            m = kin.plan_muster(plea, roster, family=FAMILY,
                                last_muster_at=None, now=0.0)
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
        self.assertFalse(bonds.decide("og", kin.Plea("Grog", "q"), history=h).will_answer)

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
        m = kin.plan_muster(plea, [_row(n) for n in bonds.FAMILY], family=FAMILY,
                            last_muster_at=None, now=0.0)
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
            n for n in ast.walk(tree)
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "_muster_for_pleas"
        )
        cls.calls = [n for n in ast.walk(cls.fn) if isinstance(n, ast.Call)]

    def _call(self, dotted: str):
        want = dotted.split(".")
        for c in self.calls:
            f = c.func
            if (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name)
                    and [f.value.id, f.attr] == want):
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
            "family", [k.arg for k in call.keywords],
            "plan_muster called without family= - kin would muster the realm",
        )

    def test_the_reflection_window_is_a_clock_not_a_row_count(self):
        """A row-count window only advances when rows are written, and a
        muster everyone refuses writes none - so a family that stopped helping
        each other could never start again, and said so only to the log."""
        src = (pathlib.Path(__file__).resolve().parent.parent / "bridge.py").read_text()
        fetch = src[src.index("def _fetch_reflections"):]
        fetch = fetch[:fetch.index("\ndef ")]
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
            hist, ast.List,
            "history= is a literal list - the bonds rules can never fire",
        )

if __name__ == "__main__":
    unittest.main()
