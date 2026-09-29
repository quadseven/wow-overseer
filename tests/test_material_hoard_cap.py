"""A crafter's material hoard cannot pin its bags at zero free slots.

MEASURED ON wow-dev, 2026-09-29. The Horde family's mage carried 0 free slots:
about forty stacks of Linen Cloth, twenty to a stack, spread over the pack and
four bags. `bridge._fetch_vendor_items` protected every stack of a material
NAME in `materials.REAGENTS` without limit, so the vendor pass found nothing to
sell ("sellable Oz 0"), and the bag gate that withholds a queued run at three
free slots or fewer never lifted. Ragefire Chasm stayed at 0 of 50 for hours
while the family's Jev chose a sell errand, over and over, that could not sell
anything. The module holds its door shut on the same floor, so no timeout on
the bridge's side could have let the run in.

The cap is per holder and per material, whole stacks, largest first, and one
stack is always kept. It reuses `disposition._stock_keeps`, which is the rule
`profession_keeps` already applies to the family's other stock.
"""

import pathlib
import sys
import types
import unittest
from unittest import mock

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import bag_pressure  # noqa: E402
import disposition  # noqa: E402
import materials  # noqa: E402


def row(guid, count, holder="Oz", entry=2589, name="Linen Cloth"):
    return {
        "holder": holder,
        "item_guid": guid,
        "count": count,
        "entry": entry,
        "name": name,
        "quality": 1,
        "sell_price": 13,
        "item_class": 7,
        "bag_family": 0,
        "quest_item": 0,
        "reagent": 0,
    }


def hoard(stacks, holder="Oz"):
    return [row(1000 + i, 20, holder=holder) for i in range(stacks)]


class TheCapKeepsWholeStacksAndSellsTheRest(unittest.TestCase):
    def test_a_hoard_past_the_cap_leaves_surplus_stacks(self):
        rows = hoard(40)
        kept = disposition.material_keeps(rows, materials.REAGENTS)
        self.assertEqual(len(kept) * 20, disposition.MATERIAL_KEEP)
        self.assertLess(len(kept), 40)

    def test_a_pile_inside_the_cap_is_kept_whole(self):
        rows = hoard(3)
        kept = disposition.material_keeps(rows, materials.REAGENTS)
        self.assertEqual(sorted(kept), [1000, 1001, 1002])

    def test_one_stack_is_always_kept_even_past_the_cap(self):
        rows = [row(7, disposition.MATERIAL_KEEP * 2)]
        self.assertEqual(
            sorted(disposition.material_keeps(rows, materials.REAGENTS)), [7]
        )

    def test_the_cap_is_per_holder(self):
        rows = hoard(10, "Oz") + [
            dict(r, holder="Uzza", item_guid=r["item_guid"] + 500)
            for r in hoard(10, "Uzza")
        ]
        kept = disposition.material_keeps(rows, materials.REAGENTS)
        by_holder = {"Oz": 0, "Uzza": 0}
        for r in rows:
            if r["item_guid"] in kept:
                by_holder[r["holder"]] += r["count"]
        self.assertEqual(by_holder["Oz"], disposition.MATERIAL_KEEP)
        self.assertEqual(by_holder["Uzza"], disposition.MATERIAL_KEEP)

    def test_a_name_that_is_no_material_is_not_this_rules_business(self):
        rows = [row(5, 20, entry=999, name="Wolf Meat")]
        self.assertEqual(disposition.material_keeps(rows, materials.REAGENTS), {})


class TheVendorReadOffersTheSurplus(unittest.TestCase):
    """Drives the real `_fetch_vendor_items` over a fake world."""

    def setUp(self):
        stub = types.ModuleType("discord")

        class Client:
            def __init__(self, *args, **kwargs):
                pass

        stub.Client = Client
        with mock.patch.dict(sys.modules, {"discord": stub}):
            sys.modules.pop("bridge", None)
            import bridge
        self.bridge = bridge

    def _read(self, rows):
        b = self.bridge
        conn = mock_conn(rows)
        with (
            unittest_mock_patch(b, "_connect", lambda: conn),
            unittest_mock_patch(b, "_worked_by", lambda names: {}),
            unittest_mock_patch(b.professions, "assigned", lambda name: ()),
        ):
            return b._fetch_vendor_items(["Oz"])

    def test_the_surplus_linen_is_flagged_for_clearance_and_never_offered_to_a_vendor(
        self,
    ):
        """The cap frees bag room, and the surplus goes to `clearance`, whose
        last stop is the vendor: the vendor read offers none of it itself."""
        out = self._read([dict(r) for r in hoard(40)])
        self.assertEqual(bag_pressure.vendor_candidates(out), ())
        over = [r for r in out if r["material_surplus"]]
        kept = [r for r in out if not r["material_surplus"]]
        self.assertEqual(sum(r["count"] for r in kept), disposition.MATERIAL_KEEP)
        self.assertEqual(len(over), 40 - len(kept))
        self.assertGreater(len(over), 30)

    def test_a_small_pile_is_still_never_sold(self):
        out = self._read([dict(r) for r in hoard(4)])
        self.assertEqual(bag_pressure.vendor_candidates(out), ())


def mock_conn(rows):
    class Cur:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, args=None):
            pass

        def fetchall(self):
            return rows

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def cursor(self):
            return Cur()

    return Conn()


def unittest_mock_patch(obj, name, value):
    return mock.patch.object(obj, name, value)


class TheSourceUsesTheCap(unittest.TestCase):
    def test_the_name_protection_is_no_longer_unconditional(self):
        src = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text()
        body = src[src.index("def _fetch_vendor_items(") :]
        self.assertIn("disposition.material_surplus(", body)


class TheCrafterKeepsRoomForARun(unittest.TestCase):
    """`materials.plan` stops handing a crafter stacks once its free slots
    reach the reserve, so the family's gate never sees the crafter at zero."""

    CRAFTERS = {"tailoring": "Oz"}

    def _holdings(self, stacks):
        return [
            materials.Holding("Zug", "Linen Cloth", 20, 100 + i) for i in range(stacks)
        ]

    def test_a_full_crafter_receives_nothing(self):
        plan = materials.plan(
            self._holdings(5), crafters=self.CRAFTERS, room={"Oz": 0}, reserve=8
        )
        self.assertEqual(plan.grants, ())
        self.assertEqual(len(plan.blocked), 1)
        self.assertIn("free", plan.blocked[0].said)

    def test_a_crafter_receives_only_what_leaves_the_reserve(self):
        plan = materials.plan(
            self._holdings(5), crafters=self.CRAFTERS, room={"Oz": 10}, reserve=8
        )
        self.assertEqual(len(plan.grants), 2)

    def test_no_room_reading_changes_nothing(self):
        plan = materials.plan(self._holdings(5), crafters=self.CRAFTERS)
        self.assertEqual(len(plan.grants), 5)

    def test_an_unread_receiver_is_not_blocked_on_a_missing_key(self):
        plan = materials.plan(
            self._holdings(2), crafters=self.CRAFTERS, room={"Zork": 0}, reserve=8
        )
        self.assertEqual(len(plan.grants), 2)


class TheBridgePassesTheRoom(unittest.TestCase):
    def test_both_give_passes_hand_plan_the_free_slots_and_the_reserve(self):
        src = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text()
        self.assertEqual(
            src.count("reserve=bag_pressure.CAMPAIGN_RESUME_FREE_SLOTS"), 2
        )


if __name__ == "__main__":
    unittest.main()
