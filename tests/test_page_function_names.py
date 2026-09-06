"""No two top level functions in index.html may share a name.

WHY THIS EXISTS, and it is not style. On 2026-09-06 the Armory tab showed
exactly one of five family members. The data was fine: /api/armory returned
all five, each with 19 slots, and the page fetched all five successfully.
What went wrong is that index.html declared `renderStats` TWICE, once for the
Armory tab taking (c, stats) and once for the Wealth tab taking (list).

JavaScript function declarations hoist and the LAST one wins, so the Armory's
call reached the Wealth tab's function, `for (const s of list)` was handed a
profile object, and it threw `TypeError: list is not iterable` on the first
member after the first. The loop over p.members died there, so member one was
drawn and members two through five were never created at all. A page that
draws one member looks like a data problem or a filter, which is why this
went unnoticed: nothing was red, there was no console error a viewer would
see, and the one member on screen looked completely correct.

The whole file is one script, so a name is either unique in it or it is a
collision waiting for someone to call the wrong one. This test is cheap and
it fails loudly the moment a second declaration of an existing name lands.

Ticket: infra#3398.
"""
import collections
import pathlib
import re
import unittest

PAGE = pathlib.Path(__file__).resolve().parent.parent / "index.html"

# Top level only: a function declaration that starts at the beginning of a
# line. Anything indented is nested inside another function or a block, where
# shadowing is deliberate and scoped, and is none of this test's business.
DECLARATION = re.compile(r"^function\s+([A-Za-z_$][\w$]*)\s*\(", re.MULTILINE)


class EveryTopLevelFunctionHasItsOwnName(unittest.TestCase):
    def test_no_name_is_declared_twice(self):
        """Two declarations of one name means one of them is unreachable."""
        source = PAGE.read_text(encoding="utf-8")
        counts = collections.Counter(DECLARATION.findall(source))
        repeated = sorted(name for name, n in counts.items() if n > 1)
        self.assertEqual(
            [], repeated,
            "declared more than once at the top level of index.html, so the "
            "later declaration silently replaces the earlier one and every "
            "caller of the earlier reaches the wrong function: "
            + ", ".join(repeated))

    def test_it_can_see_the_functions_it_is_meant_to_guard(self):
        """A regex that matches nothing would pass the test above forever."""
        names = DECLARATION.findall(PAGE.read_text(encoding="utf-8"))
        self.assertGreater(len(names), 50)
        self.assertIn("renderArmoryStats", names)
        self.assertIn("renderStats", names)


if __name__ == "__main__":
    unittest.main()
