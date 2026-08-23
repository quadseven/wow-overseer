"""What the family is actually working on.

Evan: "they are killing murlocs right now they should talk about that and how
many more they need to do and whats next and talk about the gear drops and who
needs what".

Every number in these sentences comes from a database row. A character that
invents its own progress is a character the overseer can no longer be believed
about, which is worth more than a livelier line.
"""
import unittest

import council
import quests


def _row(**over):
    row = {"character_name": "Grug", "quest": 5545}
    row.update(over)
    return row


def _meta(**over):
    meta = {"LogTitle": "A Bundle of Trouble"}
    meta.update(over)
    return meta


class ReadTest(unittest.TestCase):
    def test_an_item_objective_counts_what_is_left(self):
        p = quests.read(_row(itemcount1=4),
                        _meta(RequiredItemCount1=8, item_name1="Bundle of Wood"))
        self.assertEqual(p.left, 4)
        self.assertEqual(quests.say_remaining(p),
                         "I need 4 more Bundle of Wood for A Bundle of Trouble.")

    def test_a_kill_objective_counts_the_same_way(self):
        p = quests.read(_row(mobcount1=8),
                        _meta(LogTitle="Protect the Frontier",
                              RequiredNpcOrGoCount1=10, npc_name1="Prowler"))
        self.assertEqual(quests.say_remaining(p),
                         "I need 2 more Prowler for Protect the Frontier.")

    def test_a_quest_with_nothing_to_count_is_not_reported(self):
        """Plenty are "go and speak to someone", which has nothing to say about
        how many more."""
        self.assertIsNone(quests.read(_row(), _meta()))

    def test_a_finished_quest_says_so(self):
        p = quests.read(_row(itemcount1=8),
                        _meta(RequiredItemCount1=8, item_name1="Bundle of Wood"))
        self.assertTrue(p.done)
        self.assertIn("hand it in", quests.say_remaining(p))

    def test_overshooting_never_goes_negative(self):
        p = quests.read(_row(itemcount1=99),
                        _meta(RequiredItemCount1=8, item_name1="Bundle of Wood"))
        self.assertEqual(p.left, 0)

    def test_a_missing_name_still_produces_a_sentence(self):
        """The name lookups are LEFT JOINs; a missing name must yield a vaguer
        line, never a dropped quest."""
        p = quests.read(_row(mobcount1=1), _meta(RequiredNpcOrGoCount1=5))
        self.assertIn("4 more", quests.say_remaining(p))

    def test_the_worst_objective_is_the_one_spoken_about(self):
        """One sentence, so it should be about the thing furthest from done.

        The kill objective is built FIRST, so this deliberately makes the ITEM
        the worse one - the first version put the worst one first by accident
        and passed against code that simply took objectives[0]."""
        p = quests.read(_row(mobcount1=9, itemcount1=1),
                        _meta(RequiredNpcOrGoCount1=10, npc_name1="Prowler",
                              RequiredItemCount1=8, item_name1="Wood"))
        self.assertIn("Wood", quests.say_remaining(p))
        self.assertIn("7 more", quests.say_remaining(p))


class FocusTest(unittest.TestCase):
    def _p(self, qid, have, need, character="Grug"):
        return quests.read(
            {"character_name": character, "quest": qid, "itemcount1": have},
            {"LogTitle": "Q%d" % qid, "RequiredItemCount1": need, "item_name1": "thing"})

    def test_the_closest_to_finishing_wins(self):
        """Clearing the thing in front of you is what a real group does."""
        chosen = quests.focus([self._p(1, 1, 10), self._p(2, 8, 10)])
        self.assertEqual(chosen.quest_id, 2)

    def test_an_untouched_quest_is_not_what_they_are_working_on(self):
        """It is what one of them happens to be carrying."""
        self.assertIsNone(quests.focus([self._p(1, 0, 10)]))

    def test_a_finished_quest_is_not_a_focus(self):
        self.assertIsNone(quests.focus([self._p(1, 10, 10)]))

    def test_the_same_state_always_picks_the_same_quest(self):
        """A council that changed its mind every hour on identical facts would
        be noise, not deliberation."""
        rows = [self._p(9, 5, 10), self._p(2, 5, 10)]
        self.assertEqual(quests.focus(rows).quest_id, 2)
        self.assertEqual(quests.focus(list(reversed(rows))).quest_id, 2)

    def test_it_knows_who_else_carries_it(self):
        """A quest several of them hold is the one worth doing together - the
        kills count for everyone at once."""
        rows = [self._p(5, 1, 10, "Grug"), self._p(5, 2, 10, "Bork"),
                self._p(7, 1, 10, "Og")]
        self.assertEqual(quests.shared_with(rows, 5), ["Bork", "Grug"])


class CouncilTalksAboutWorkTest(unittest.TestCase):
    """The council could talk about levels and nothing else, so five characters
    grinding murlocs held a conversation about levels."""

    def _m(self, name, **over):
        over.setdefault("level", 9)
        over.setdefault("gold", 999999)
        over.setdefault("trades", 5)
        return council.Member(name=name, class_name="Warrior", **over)

    def test_a_half_finished_quest_is_what_gets_raised(self):
        members = [self._m("Grug", quest="I need 4 more Wood for X.", quest_left=4),
                   self._m("Ugga"), self._m("Grog"), self._m("Bork"), self._m("Og")]
        c = council.hold(members, history=[])
        self.assertEqual(c.plan.kind, "quest")
        self.assertTrue(any("4 more Wood" in l for l in c.lines), c.lines)

    def test_it_outranks_trades_and_coin(self):
        """The most concrete thing anyone at the table has."""
        members = [self._m("Grug", quest="I need 1 more Wood for X.", quest_left=1, trades=0),
                   self._m("Ugga"), self._m("Grog")]
        self.assertEqual(council.hold(members, history=[]).plan.kind, "quest")

    def test_somebody_left_far_behind_still_outranks_it(self):
        """A family that finishes its errands past its youngest is not the
        family this is meant to be."""
        members = [self._m("Grug", quest="I need 1 more Wood for X.", quest_left=1),
                   self._m("Ugga"), self._m("Grog"), self._m("Bork"),
                   self._m("Og", level=2)]
        c = council.hold(members, history=[])
        self.assertEqual((c.plan.kind, c.plan.beneficiary), ("level", "Og"))


class WiringTest(unittest.TestCase):
    """A quest sentence nobody passes on is a very well-tested string."""

    def test_the_bridge_hands_the_quest_to_the_council(self):
        import ast
        import pathlib

        src = (pathlib.Path(__file__).resolve().parent.parent / "bridge.py").read_text()
        fn = next(n for n in ast.walk(ast.parse(src))
                  if isinstance(n, ast.FunctionDef) and n.name == "_fetch_council_members")
        call = next(
            n for n in ast.walk(fn)
            if isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "Member")
        quest = next((k.value for k in call.keywords if k.arg == "quest"), None)
        self.assertIsNotNone(quest, "Member is built without a quest at all")
        self.assertNotIsInstance(
            quest, ast.Constant,
            "quest= is a literal, so the council never hears what anyone is doing")

    def test_the_bridge_actually_reads_progress(self):
        import ast
        import pathlib

        src = (pathlib.Path(__file__).resolve().parent.parent / "bridge.py").read_text()
        fn = next(n for n in ast.walk(ast.parse(src))
                  if isinstance(n, ast.FunctionDef) and n.name == "_fetch_council_members")
        names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
        self.assertIn("_fetch_quest_progress", names)


if __name__ == "__main__":
    unittest.main()
