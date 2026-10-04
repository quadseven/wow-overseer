"""A guild member sells the white gear it has outgrown, like grey loot.

wow-dev 2026-10-04: the first guild mail collections were refused "no room in
the bags" for 4 of 6 members. Their bags held replaced starter weapons and
armor (Cudgel, Practice Sword, Simple Dagger, Scout's Boots) and no grey, so
the sale that makes room never fired.
"""

import pathlib
import unittest

import guildjobs

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _member(carried, level=17):
    return guildjobs.Member(
        name="Achevar",
        guild="Cave",
        role=guildjobs.MAINTENANCE,
        level=level,
        class_id=1,
        online=True,
        map_id=0,
        x=-9000.0,
        y=100.0,
        money=5000,
        eligible=True,
        skills={
            guildjobs.FIRST_AID: (40, 75),
            guildjobs.HERBALISM: (40, 75),
            guildjobs.SKINNING: (1, 75),
        },
        carried=tuple(carried),
    )


def _white(guid, item_class=2, subclass=7, item_level=2, price=20):
    return guildjobs.Carried(
        guid=guid,
        entry=1000 + guid,
        item_class=item_class,
        subclass=subclass,
        quality=1,
        sell_price=price,
        item_level=item_level,
        name="white %d" % guid,
    )


class OutgrownWhiteGearSells(unittest.TestCase):
    def test_starter_weapons_and_armor_are_outgrown(self):
        self.assertTrue(_white(1).outgrown(17))
        self.assertTrue(_white(2, item_class=4, subclass=2, item_level=5).outgrown(17))
        self.assertTrue(_white(3, item_level=7).outgrown(17))

    def test_close_to_level_is_kept(self):
        self.assertFalse(_white(1, item_level=8).outgrown(17))
        self.assertFalse(_white(1, item_level=0).outgrown(17))

    def test_tools_and_trinkets_are_never_sold(self):
        self.assertFalse(_white(1, subclass=14).outgrown(40))  # mining pick
        self.assertFalse(_white(2, subclass=20).outgrown(40))  # fishing pole
        self.assertFalse(_white(3, item_class=4, subclass=0).outgrown(40))  # shirt
        self.assertFalse(_white(4, item_class=7, subclass=5).outgrown(40))  # cloth

    def test_green_and_unsellable_are_kept(self):
        green = guildjobs.Carried(
            guid=9,
            entry=9,
            item_class=2,
            subclass=7,
            quality=2,
            sell_price=50,
            item_level=2,
        )
        self.assertFalse(green.outgrown(40))
        self.assertFalse(_white(1, price=0).outgrown(40))

    def test_a_bag_of_outgrown_gear_gets_a_sale(self):
        bag = [_white(20 + i) for i in range(4)]
        # Its skinning knife, a tool it keeps.
        knife = guildjobs.Carried(guid=1, entry=7005, item_class=2, subclass=14)
        bag.append(knife)
        plan = guildjobs.plan([_member(bag)], masters={"Cave": "Grug"})
        step = [s for s in plan.steps if s.holder == "Achevar"][0]
        self.assertEqual("sell", step.action)
        self.assertEqual(
            ["guid:20", "guid:21", "guid:22", "guid:23"],
            sorted(r.command for r in step.rows),
        )

    def test_the_bridge_reads_white_gear_and_its_level(self):
        source = (ROOT / "bridge.py").read_text()
        sql = source[source.index("_JOB_ITEMS_SQL = (") :]
        sql = sql[: sql.index("\n)\n")]
        self.assertIn("it.ItemLevel AS item_level", sql)
        self.assertIn("it.class IN (2, 4) AND it.Quality = 1", sql)


if __name__ == "__main__":
    unittest.main()
