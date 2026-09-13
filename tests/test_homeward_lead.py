"""The father leads again: the bind override is retired, and stays retired.

HISTORY, KEPT BECAUSE THE FACT UNDER IT IS STILL TRUE. Revival uses the GROUP
LEADER'S bind and never the character's own: the module reads
group->GetLeaderGUID() and teleports to that player's homebind. So the whole
family gathers wherever the leader is bound, and a leader bound on the wrong
continent turns every death into a party split, which no drive in the module
can rejoin.

On 2026-09-07 that was exactly the state: the father was bound in Elwynn while
the family's hundred-run campaign was on Kalimdor. The campaign finished 0 of
100 and every death pulled the party further apart. bridge.HOMEWARD_LEAD was
added (infra#3420) to pin the lead to the one character bound at the port town
on the working continent, and its own comment named the condition for removing
it: the resting head bound on the family's own continent, and able to walk out
of where it stands.

Read live on 2026-09-13, `character_homebind` puts all five in Ratchet (map 1,
zone 392) within four yards of each other, beside Innkeeper Wiley - so the
father is bound at that same port town, and the override was choosing one
character for a property all five now share. The routing blocker its comment
named last, quadseven/mod-overseer#316, closed COMPLETED on 2026-09-08.

WHAT THESE TESTS GUARD NOW. That the override is gone rather than merely
inert, that the father is the resting answer, and that the three borrowers
still outrank him in the right order. The precedence tests EVALUATE THE REAL
EXPRESSION against stubs rather than reading it as text, because the realm
almost always has some borrower active - a live check answers "Grog" for a
vendor errand and proves nothing about the resting path underneath it.

Ticket: infra#3420 (added), infra#3715 (retired).
"""
import pathlib
import re
import unittest

import bonds

BRIDGE = pathlib.Path(__file__).resolve().parent.parent / "bridge.py"


def _head_now_source() -> str:
    text = BRIDGE.read_text(encoding="utf-8")
    start = text.index("def _head_now(")
    rest = text[start:]
    nxt = re.search(r"\ndef ", rest)
    return rest[: nxt.start()] if nxt else rest


def _resolve(train="", errand="", derived=""):
    """Run _head_now's ACTUAL return expression with the borrowers stubbed.

    bridge.py opens a database connection at import time, so the module cannot
    be imported here - the expression is lifted out of the source and
    evaluated against fakes instead. That keeps this a test of the shipped
    precedence rather than of a copy of it: edit the chain in bridge.py and
    these tests move with it, which is the failure mode a text assertion has.
    """
    body = _head_now_source()
    expr = body[body.index("return ") + len("return "):].strip()
    return eval(expr, {  # noqa: S307 - the source under test, not input
        "_train_traveller": lambda: train,
        "_errand_traveller": lambda: errand,
        "_derived_errand_traveller": lambda: derived,
        "bonds": bonds,
    })


class TheOverrideIsGone(unittest.TestCase):
    def test_no_module_level_constant_survives(self):
        """Including `= None`. An override that cannot change the answer is a
        third state for the next reader to rule out, and the point of removing
        it was to stop anybody having to."""
        text = BRIDGE.read_text(encoding="utf-8")
        self.assertIsNone(
            re.search(r"^HOMEWARD_LEAD\b", text, re.M),
            "HOMEWARD_LEAD is retired; do not reintroduce it as a constant",
        )

    def test_nothing_in_the_chain_still_consults_it(self):
        """Scoped to the RETURN EXPRESSION, not the whole function. The
        docstring above it names HOMEWARD_LEAD on purpose - why the override
        existed and why it stopped being needed is the history worth keeping -
        and asserting on the prose would force that history to be deleted to
        keep the test green."""
        body = _head_now_source()
        self.assertNotIn("HOMEWARD_LEAD", body[body.index("return "):])

    def test_no_character_name_is_hardcoded_into_the_decision(self):
        """The next bind emergency must not be solved by pinning a name here
        again. The seam for it is the `or` chain, where a borrower leads for
        as long as it has somewhere to be and hands the lead back after."""
        expr = _head_now_source()
        expr = expr[expr.index("return "):]
        for name in bonds.FAMILY:
            self.assertNotIn(
                '"%s"' % name, expr, "%s is hardcoded into _head_now" % name
            )
            self.assertNotIn("'%s'" % name, expr)


class TheRestingAnswerIsTheFather(unittest.TestCase):
    def test_with_no_borrower_the_father_leads(self):
        """THE STATE THE REALM IS USUALLY NOT IN. This is the whole change:
        before it, this case answered Grog."""
        self.assertEqual(_resolve(), "Grug")
        self.assertEqual(_resolve(), bonds.head_of_family())

    def test_the_family_table_is_untouched(self):
        """The override was logistics. If this fails, somebody solved a
        routing problem by editing who these people are to each other."""
        self.assertEqual(bonds.head_of_family(), "Grug")
        senior = max(bonds.FAMILY, key=lambda n: bonds.FAMILY[n].seniority)
        self.assertEqual(senior, "Grug")

    def test_the_jealousy_still_belongs_to_the_father(self):
        """bonds.SUSPICION is the father's, and he is still the father whether
        or not the party is currently following him. With the override gone
        the narrator and the leader are the same man again."""
        self.assertEqual(bonds.SUSPICION["who"], bonds.head_of_family())


class ABorrowerStillOutranksSeniority(unittest.TestCase):
    """A character actually walking somewhere is a better leader for that
    moment than one merely senior - removing the bind override must not have
    cost the family its travellers."""

    def test_a_train_order_takes_the_lead(self):
        self.assertEqual(_resolve(train="Ugga"), "Ugga")

    def test_a_trade_errand_takes_the_lead(self):
        self.assertEqual(_resolve(errand="Grog"), "Grog")

    def test_a_derived_errand_takes_the_lead(self):
        self.assertEqual(_resolve(derived="Og"), "Og")

    def test_an_order_a_person_gave_outranks_a_plan_the_family_drifted_into(self):
        self.assertEqual(_resolve(train="Ugga", errand="Grog"), "Ugga")

    def test_a_trade_outranks_an_errand_the_worldserver_wrote_itself(self):
        """infra#3686: nobody outside the worldserver asked for the derived
        one, so it is the weakest of the three."""
        self.assertEqual(_resolve(errand="Grog", derived="Og"), "Grog")

    def test_the_derived_errand_is_the_weakest_of_the_three(self):
        self.assertEqual(_resolve(train="Ugga", derived="Og"), "Ugga")
        self.assertEqual(
            _resolve(train="Ugga", errand="Grog", derived="Og"), "Ugga"
        )

    def test_a_borrower_that_answers_nobody_is_skipped(self):
        """Each borrower answers '' rather than raising when its lookup fails,
        so an empty answer must fall through to the next claim and not strand
        the family leaderless."""
        self.assertEqual(_resolve(train="", errand="", derived="Og"), "Og")
        self.assertEqual(_resolve(train="", errand="Grog", derived=""), "Grog")


if __name__ == "__main__":
    unittest.main()
