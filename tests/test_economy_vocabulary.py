"""The economy errand vocabulary, compared across the two processes (#50).

`bridge.ECONOMY_ERRANDS` and mod-overseer's `CounterRoleForAim` are two copies
of one vocabulary. The C++ function's own comment says "a test compares them
rather than a comment asking somebody to remember", and until this file no
test did: the two drifted in both directions (`auctioneer` was C++ only,
`guild banker` Python only) and nothing noticed.

This compares them both ways, the way test_travel_npc.py compares
`travel.ROLES` against `TravelRoles()`. A difference is allowed only when it
is written down below with its reason, so a new keyword on either side fails
here until somebody decides which side it belongs on.

bridge.py imports discord and cannot be imported here, so both sides are read
as text.
"""

import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "bridge.py"
DECISIONS = ROOT / "mod-overseer/src/overseer_decisions.cpp"

# Keywords the bridge guards as economy errands that the C++ gives no counter
# role, each with the decision that keeps it one-sided.
PYTHON_ONLY = {
    # Nothing writes this keyword any more: the guild bank pass aims at the
    # vault's own spawn as a ground aim, and the npcflag the keyword names
    # matches no creature in this expansion (see travel.ROLES). It stays in
    # ECONOMY_ERRANDS as a guard, so a future writer of it takes the guarded
    # branch and cannot blank a learn errand (test_guildbank.py pins that).
    # A counter hold for a role no creature carries would hold nobody, so the
    # C++ side has no reason to gain it.
    "guild banker": "a guard for a keyword nothing writes; no creature to hold at",
}

# Keywords the C++ holds a character at that the bridge does not guard. None.
CPP_ONLY: dict = {}


def _python_keywords() -> set:
    match = re.search(
        r"^ECONOMY_ERRANDS = \((.*?)\)$", BRIDGE.read_text(encoding="utf-8"), re.M
    )
    if match is None:
        raise AssertionError("ECONOMY_ERRANDS is not a flat tuple any more")
    return set(re.findall(r'"([^"]+)"', match.group(1)))


def _cpp_keywords() -> set:
    source = DECISIONS.read_text(encoding="utf-8", errors="replace")
    start = source.index("CounterRole CounterRoleForAim(std::string const& aim)")
    end = source.index("\n}", start)
    body = "\n".join(line.split("//", 1)[0] for line in source[start:end].splitlines())
    return set(re.findall(r'aim == "([^"]+)"', body))


class EconomyErrandsMatchCounterRoleForAim(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not DECISIONS.exists():
            raise unittest.SkipTest(
                "mod-overseer submodule not checked out; "
                "check.yml passes submodules: true for this dir"
            )

    def test_the_cpp_side_is_read_at_all(self):
        """A parse that finds nothing would make both comparisons below pass
        for the wrong reason, so the four roles the C++ carries today are
        pinned by name."""
        self.assertLessEqual(
            {"vendor", "banker", "repair", "auctioneer"}, _cpp_keywords()
        )

    def test_every_python_economy_errand_has_a_counter_role_or_a_reason(self):
        self.assertEqual(set(PYTHON_ONLY), _python_keywords() - _cpp_keywords())

    def test_every_counter_role_is_a_python_economy_errand_or_has_a_reason(self):
        self.assertEqual(set(CPP_ONLY), _cpp_keywords() - _python_keywords())

    def test_every_stated_exception_is_still_a_real_difference(self):
        """An exception that stops being a difference is stale prose, the
        failure this file exists to end."""
        self.assertLessEqual(set(PYTHON_ONLY), _python_keywords())
        self.assertLessEqual(set(CPP_ONLY), _cpp_keywords())


if __name__ == "__main__":
    unittest.main()
