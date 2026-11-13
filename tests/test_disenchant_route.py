"""A stack a sale path lets go goes to the family enchanter first (#2411, #1978).

Both family enchanters read Enchanting 1 on 2026-11-13 with no dust in their
bags, while the sale paths walked disenchantable greens to vendors. The rule
is `bag_pressure.disenchant_route`; `bridge._insert_sell` asks it after the
keep marks and the epic gate, so it never widens what may leave the guild.
"""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import bag_pressure  # noqa: E402

BRIDGE = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text(
    encoding="utf-8"
)


def function_text(name: str) -> str:
    """One top-level bridge function, by its text: def to the next def."""
    start = BRIDGE.index("\ndef %s(" % name)
    return BRIDGE[start : BRIDGE.index("\ndef ", start + 1)]


def facts(**kw):
    base = dict(
        item_class=4, quality=2, disenchant_id=1, required_skill=1, soulbound=False
    )
    base.update(kw)
    return bag_pressure.DisenchantFacts(**base)


ENCHANTERS = {"Og": 30}


class TheRoute(unittest.TestCase):
    def test_the_enchanter_disenchants_what_it_would_have_sold(self):
        self.assertEqual(
            (bag_pressure.DISENCHANT, "Og"),
            bag_pressure.disenchant_route("Og", facts(soulbound=True), ENCHANTERS),
        )

    def test_a_sibling_gives_a_bind_on_equip_item_to_the_enchanter(self):
        self.assertEqual(
            (bag_pressure.GIVE_TO_ENCHANTER, "Og"),
            bag_pressure.disenchant_route("Grug", facts(), ENCHANTERS),
        )

    def test_a_soulbound_item_off_the_enchanter_is_still_sold(self):
        self.assertIsNone(
            bag_pressure.disenchant_route("Grug", facts(soulbound=True), ENCHANTERS)
        )

    def test_skill_gates_the_item_level(self):
        """RequiredDisenchantSkill above the enchanter's Enchanting: sold."""
        self.assertIsNone(
            bag_pressure.disenchant_route("Og", facts(required_skill=50), ENCHANTERS)
        )
        self.assertIsNone(
            bag_pressure.disenchant_route("Grug", facts(required_skill=50), ENCHANTERS)
        )

    def test_the_core_gate_is_copied_exactly(self):
        for why, f in (
            ("not gear", facts(item_class=7)),
            ("grey", facts(quality=0)),
            ("white", facts(quality=1)),
            ("legendary", facts(quality=5)),
            ("no DisenchantID", facts(disenchant_id=0)),
            ("never disenchantable", facts(required_skill=-1)),
        ):
            with self.subTest(why=why):
                self.assertIsNone(bag_pressure.disenchant_route("Og", f, ENCHANTERS))
        for quality in (2, 3, 4):
            with self.subTest(quality=quality):
                self.assertIsNotNone(
                    bag_pressure.disenchant_route(
                        "Og", facts(quality=quality), ENCHANTERS
                    )
                )

    def test_an_unread_item_is_sold_as_before(self):
        self.assertIsNone(bag_pressure.disenchant_route("Og", None, ENCHANTERS))

    def test_no_enchanter_no_route(self):
        self.assertIsNone(bag_pressure.disenchant_route("Grug", facts(), {}))

    def test_the_most_skilled_enchanter_takes_a_give_by_name_on_a_tie(self):
        self.assertEqual(
            (bag_pressure.GIVE_TO_ENCHANTER, "Ab"),
            bag_pressure.disenchant_route("Grug", facts(), {"Og": 5, "Ab": 5}),
        )
        self.assertEqual(
            (bag_pressure.GIVE_TO_ENCHANTER, "Og"),
            bag_pressure.disenchant_route("Grug", facts(), {"Og": 9, "Ab": 5}),
        )


class TheSaleAsksTheRouteLast(unittest.TestCase):
    def setUp(self):
        self.body = function_text("_insert_sell")

    def test_after_the_keep_marks_and_the_epic_gate(self):
        keep = self.body.index("_KEEP.blocks(")
        epic = self.body.index("_epic_blocks(")
        route = self.body.index("_disenchant_instead(")
        insert = self.body.index("INSERT INTO overseer_command")
        self.assertLess(keep, route)
        self.assertLess(epic, route)
        self.assertLess(route, insert)

    def test_the_route_has_its_own_switch_and_fails_open_to_the_sale(self):
        body = function_text("_disenchant_instead")
        self.assertIn("if not DISENCHANT_ROUTE:", body)
        # A database or connection fault falls back to the sale; a bug raises.
        self.assertIn("except (pymysql.err.MySQLError, OSError):", body)
        self.assertIn(
            'DISENCHANT_ROUTE = os.environ.get("DISENCHANT_ROUTE", "0") == "1"', BRIDGE
        )

    def test_a_routed_item_is_not_written_twice(self):
        body = function_text("_disenchant_instead")
        self.assertLess(body.index("_DISENCHANT_ROUTED_SQL"), body.index("INSERT INTO"))


if __name__ == "__main__":
    unittest.main()
