"""The bag handover reaches the give queue, and only through the pure planner.

bridge.py imports discord and cannot be imported here, so this reads it as
text the way test_digest and test_party_chat do. What is pinned is the seam
(infra#2597): the bridge fetches container rows and writes give rows; every
decision about which bag goes where is bag_upgrade's, and the pass runs
BEFORE reagents move because a give into full bags is what kept failing.
"""

import pathlib
import re
import unittest

BRIDGE = pathlib.Path(__file__).resolve().parents[1] / "bridge.py"
DOCKERFILE = pathlib.Path(__file__).resolve().parents[1] / "Dockerfile"


def _source() -> str:
    return BRIDGE.read_text(encoding="utf-8")


def _block(signature: str) -> str:
    """One def's body, to the next def at the same or shallower indent."""
    src = _source()
    start = src.index(signature)
    indent = len(signature) - len(signature.lstrip())
    rest = src[start:]
    match = re.search(r"\n {0,%d}(async def |def |class )" % indent, rest[1:])
    return rest[: match.start() + 1] if match else rest


class BagsMoveBeforeReagents(unittest.TestCase):
    def test_the_materials_pass_hands_bags_over_first(self):
        body = _block("    async def _move_materials_once(")
        self.assertIn("await self._hand_bags_once(names)", body)
        self.assertLess(body.index("_hand_bags_once"), body.index("_fetch_holdings"))

    def test_but_not_in_the_middle_of_a_dungeon_run(self):
        """The mid-run stand-down guards the whole pass, bags included."""
        body = _block("    async def _move_materials_once(")
        self.assertLess(body.index("self._mid_run("), body.index("_hand_bags_once"))


class TheBridgeDecidesNothingAboutBags(unittest.TestCase):
    def test_the_plan_comes_from_the_pure_module(self):
        body = _block("    async def _hand_bags_once(")
        self.assertIn("bag_upgrade.plan_family_bags(", body)
        self.assertIn("bag_upgrade.members_from_rows(rows, names)", body)
        self.assertIn("bag_upgrade.give_command(move)", body)

    def test_no_slot_arithmetic_in_the_bridge(self):
        """Slot ranges and 'is this bag worn' live in bag_upgrade. A literal
        19 or 23 here would be a second copy of that rule."""
        body = _block("    async def _hand_bags_once(")
        self.assertNotRegex(body, r"\b(19|22|23|38|39|67)\b")
        self.assertNotRegex(body, r"\[\"(bag|slot)\"\]")
        self.assertNotIn("ContainerSlots", body)

    def test_the_fetch_is_only_a_fetch(self):
        body = _block("def _fetch_bag_state(")
        self.assertIn("_BAG_STATE_SQL", body)
        self.assertIn("return [dict(row) for row in cur.fetchall()]", body)
        self.assertNotRegex(body, r"\b(19|22|23|38|39|67)\b")


class TheRowsCarryWhatThePlannerReads(unittest.TestCase):
    def test_the_sql_names_every_column_members_from_rows_uses(self):
        src = _source()
        sql = src[src.index("_BAG_STATE_SQL = (") : src.index("def _fetch_bag_state(")]
        for column in (
            "AS holder",
            "AS guid",
            "AS name",
            "AS slots",
            "AS bag",
            "AS slot",
            "AS used",
        ):
            self.assertIn(column, sql)

    def test_only_real_bags(self):
        """ITEM_CLASS_CONTAINER is 1. Quivers and ammo pouches also have
        ContainerSlots and would be handed to a warrior as loot room."""
        src = _source()
        sql = src[src.index("_BAG_STATE_SQL = (") : src.index("def _fetch_bag_state(")]
        self.assertIn("it.class = 1", sql)
        self.assertIn("it.ContainerSlots > 0", sql)

    def test_fill_counts_what_is_inside_each_bag(self):
        src = _source()
        sql = src[src.index("_BAG_STATE_SQL = (") : src.index("def _fetch_bag_state(")]
        self.assertIn("COUNT(*) AS n FROM character_inventory", sql)
        self.assertIn("fill.bag = ii.guid", sql)


class TheGiveRowIsTheGiveRowDoGiveReads(unittest.TestCase):
    """Same column meaning as _insert_give: giver in target_name, receiver in
    target_arg, `guid:N` in command. A row with these swapped would be a
    delivered command that moves nothing."""

    def test_columns(self):
        body = _block("def _insert_bag_give(")
        self.assertIn("(target_name, command, kind, target_arg, source)", body)
        self.assertIn("'give'", body)
        self.assertIn('(move.giver, command, move.receiver, "bags")', body)

    def test_a_world_without_the_enum_warns_instead_of_raising(self):
        body = _block("def _insert_bag_give(")
        self.assertIn("1265", body)
        self.assertIn("return 0", body)

    def test_the_same_handover_is_not_queued_twice_inside_the_window(self):
        body = _block("    async def _hand_bags_once(")
        self.assertIn("_recent_give_keys, GIVE_RETRY_MINUTES", body)
        self.assertIn("(move.giver, move.receiver, command) in seen", body)


class TheModuleShips(unittest.TestCase):
    def test_bag_upgrade_is_in_the_image(self):
        self.assertIn("bag_upgrade.py", DOCKERFILE.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
