"""Who the party follows when the family's own head is bound across an ocean.

Revival uses the GROUP LEADER'S bind and never the character's own: the module
reads group->GetLeaderGUID() and teleports to that player's homebind. So the
whole family gathers wherever the leader is bound, and a leader bound on the
wrong continent turns every death into a party split, which no drive in the
module can rejoin.

On 2026-09-07 that was exactly the state: the father was bound in Elwynn while
the family's hundred-run campaign was on Kalimdor. The campaign finished 0 of
100 and every death pulled the party further apart.

WHY THIS LIVES IN bridge AND NOT IN bonds. bonds.head_of_family() is the
family's answer, and other code reads it as story rather than logistics:
speaking_order puts the head first in every digest, and bonds.SUSPICION is
asserted to BE the head, because the jealousy belongs to the father. Overriding
there would have made the man he is suspicious of the head of his family and
changed who narrates the day. _head_now already exists as the seam where a
borrower leads for a while without anybody's standing changing.

Ticket: infra#3420.
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


class TheLeadCanBeMovedWithoutMovingTheFamily(unittest.TestCase):
    def test_the_override_is_consulted_before_seniority(self):
        """Otherwise it can never take effect."""
        body = _head_now_source()
        self.assertRegex(body, r"HOMEWARD_LEAD\s+or\s+bonds\.head_of_family\(\)")

    def test_a_borrower_still_outranks_it(self):
        """A character actually walking somewhere is a better leader for that
        moment than one merely bound well, and the train order a person just
        gave outranks both.

        Read from the RETURN expression rather than the whole function, because
        the docstring above it names all three and would satisfy a naive index
        search in the wrong order. This test failed that way once."""
        body = _head_now_source()
        expr = body[body.index("return "):]
        self.assertLess(expr.index("_train_traveller()"), expr.index("HOMEWARD_LEAD"))
        self.assertLess(expr.index("_errand_traveller()"), expr.index("HOMEWARD_LEAD"))
        self.assertLess(expr.index("HOMEWARD_LEAD"), expr.index("bonds.head_of_family()"))

    def test_it_names_somebody_in_the_family(self):
        """A typo would hand the party, and every revival with it, to a
        character that does not exist. Read as text rather than imported,
        because bridge.py opens a database connection at import time."""
        text = BRIDGE.read_text(encoding="utf-8")
        m = re.search(r'^HOMEWARD_LEAD: str \| None = (.+)$', text, re.M)
        self.assertIsNotNone(m, "HOMEWARD_LEAD must stay a module level literal")
        value = m.group(1).strip()
        if value != "None":
            self.assertIn(value.strip('"').strip("'"), bonds.FAMILY)

    def test_the_family_table_is_untouched(self):
        """The override is logistics. If this fails, somebody solved a routing
        problem by editing who these people are to each other."""
        self.assertEqual(bonds.head_of_family(), "Grug")
        senior = max(bonds.FAMILY, key=lambda n: bonds.FAMILY[n].seniority)
        self.assertEqual(senior, "Grug")

    def test_the_jealousy_still_belongs_to_the_father(self):
        """bonds.SUSPICION is the father's, and he is still the father whether
        or not the party is currently following him."""
        self.assertEqual(bonds.SUSPICION["who"], bonds.head_of_family())


if __name__ == "__main__":
    unittest.main()
