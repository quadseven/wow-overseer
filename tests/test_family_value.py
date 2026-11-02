"""One Family value and one reading of cohort=None (#737).

Pinned here: families() groups roster rows into immutable Family values in
council.families_of's order (leader first inside a family, bonds' family
first, then by key); a roster naming no family degrades to bonds' own family
marked at large; resolve_legacy_family reads None as this bridge's own family
(the protected names), never every enrolled member; and bridge._names_of
answers through that helper with exactly the result it gave before.
"""

import ast
import dataclasses
import pathlib
import types
import unittest

import bonds
import family_value
from family_value import Family

HERE = pathlib.Path(__file__).resolve().parent.parent
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")


def _row(family, name, lead=0):
    return {"family": family, "name": name, "lead": lead}


def _bridge_function(name, namespace):
    for node in ast.walk(ast.parse(BRIDGE)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            module = ast.Module(body=[node], type_ignores=[])
            exec(compile(module, "bridge.py", "exec"), namespace)  # noqa: S102 - bridge.py's own source
            return namespace[name]
    raise AssertionError("%s not found in bridge.py" % name)


class FamiliesTest(unittest.TestCase):
    def test_rows_group_into_one_family_each_leader_first(self):
        rows = [
            _row("Zeta", "Yorr"),
            _row("Alpha", "Brak"),
            _row("Zeta", "Zug", lead=1),
            _row("Alpha", "Aka", lead=1),
            _row("Alpha", "Cro"),
        ]

        result = family_value.families(rows)

        self.assertEqual(
            result,
            (
                Family("Alpha", ("Aka", "Brak", "Cro"), at_large=False),
                Family("Zeta", ("Zug", "Yorr"), at_large=False),
            ),
        )

    def test_order_matches_council_families_of(self):
        rows = [_row("B", "Bee", 1), _row("A", "Ay", 1), _row("C", "Cee", 1)]

        self.assertEqual(
            [(f.name, list(f.members)) for f in family_value.families(rows)],
            [(name, names) for name, names in family_value.council.families_of(rows)],
        )

    def test_rows_without_family_or_name_are_ignored(self):
        rows = [_row("", "Loner"), _row("Kin", ""), _row("Kin", "Ugg", 1)]

        self.assertEqual(
            family_value.families(rows), (Family("Kin", ("Ugg",), at_large=False),)
        )

    def test_a_roster_naming_no_family_is_bonds_family_at_large(self):
        for rows in (None, [], [_row("", "Loner")]):
            with self.subTest(rows=rows):
                result = family_value.families(rows)
                self.assertEqual(len(result), 1)
                self.assertTrue(result[0].at_large)
                self.assertEqual(
                    sorted(result[0].members),
                    sorted(bonds.speaking_order(list(bonds.FAMILY))),
                )

    def test_a_family_is_immutable_and_states_at_large(self):
        fam = Family("Kin", ("Ugg",), at_large=False)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            fam.name = "Other"
        with self.assertRaises(TypeError):
            Family("Kin", ("Ugg",))  # the flag has no default


class LegacyCohortTest(unittest.TestCase):
    def test_none_is_this_bridges_own_family_sorted(self):
        self.assertEqual(
            family_value.resolve_legacy_family(None, ["Og", "Bork", "Grug"]),
            Family("", ("Bork", "Grug", "Og"), at_large=False),
        )

    def test_none_is_not_every_enrolled_member(self):
        # Another family's members never leak into the None reading: it is
        # only what the caller passes as its own.
        resolved = family_value.resolve_legacy_family(None, ["Grug"])
        self.assertEqual(resolved.members, ("Grug",))

    def test_a_cohort_keeps_its_key_and_names(self):
        cohort = types.SimpleNamespace(key="Zug", leader="Zug", names=("Zug", "Oz"))
        self.assertEqual(
            family_value.resolve_legacy_family(cohort, ["ignored"]),
            Family("Zug", ("Oz", "Zug"), at_large=False),
        )


class BridgeNamesOfTest(unittest.TestCase):
    """bridge._names_of routes through the helper and answers as before."""

    def _names_of(self, protected):
        calls = []

        def protected_guids():
            calls.append(1)
            return protected

        fn = _bridge_function("_names_of", {"_protected_guids": protected_guids})
        return fn, calls

    def test_none_reads_the_protected_names_sorted(self):
        fn, calls = self._names_of({1: "Og", 2: "Bork", 3: "Grug"})
        self.assertEqual(fn(None), ["Bork", "Grug", "Og"])
        self.assertEqual(fn(), ["Bork", "Grug", "Og"])
        self.assertEqual(len(calls), 2)

    def test_a_cohort_reads_its_own_names_without_the_database(self):
        fn, calls = self._names_of({1: "Grug"})
        cohort = types.SimpleNamespace(key="Zug", leader="Zug", names=("Zug", "Oz"))
        self.assertEqual(fn(cohort), ["Oz", "Zug"])
        self.assertEqual(calls, [])

    def test_names_of_answers_through_resolve_legacy_family(self):
        source = ast.get_source_segment(
            BRIDGE,
            next(
                n
                for n in ast.walk(ast.parse(BRIDGE))
                if isinstance(n, ast.FunctionDef) and n.name == "_names_of"
            ),
        )
        self.assertIn("family_value.resolve_legacy_family(", source)
        self.assertNotIn("sorted(", source)


if __name__ == "__main__":
    unittest.main()
