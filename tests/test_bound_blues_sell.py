"""A member sells the soulbound blues it outgrew or cannot wear (#1592).

Read on the dev realm on 2026-11-03 (read-only SELECT on character_inventory,
item_instance and item_template): 128 of the 162 members of Cave and Bonkers
had one free bag slot or none, and their bags held 3,710 slots. 579 of them
(about 152g at a vendor) were rare weapons and armor at least ten item levels
under the holder, and 827 of the 1,007 rare pieces carried by every member were
soulbound (item_instance.flags & 1): Rhahk'Zor's Hammer alone 54 times. The
vendor's verdict kept every rare piece as "guild loot, for the loot council and
the bank", first, before the outgrown rule. A soulbound piece cannot be mailed,
traded or put in the guild bank, and the loot council decides a drop when it
drops, so a bound blue in the bags only ever waited there. Selling the bound
outgrown ones alone would take 72 of the 128 members above one free slot.

Only 56 members walked to a vendor to sell in the 24 hours before the read
(the bridge log archive), most with one or two stacks: a member whose bags
held nothing but kept stacks and bound blues got no sale step at all.

The rule now: a rare or better piece that is soulbound is judged as the
member's own gear (outgrown sells, an upgrade within the lookahead is kept,
anything else it will not wear sells). A piece that is not bound is still kept
for the loot council and the bank.
"""

import dataclasses
import unittest

import gear
import guildjobs
import vendorsale
from test_guildsocial_bridge import bridge
from test_member_income import BLUE, CRYSTAL, MOUNT, bonk

# Rhahk'Zor's Hammer and Serpent's Shoulders as item_template has them, in
# Ekka's bags (a level 35 priest in Cave, 0 free slots): both bind on pickup,
# and the copies read were all soulbound.
HAMMER = guildjobs.Carried(
    guid=7001,
    entry=5187,
    name="Rhahk'Zor's Hammer",
    item_class=2,
    subclass=5,
    quality=3,
    sell_price=2163,
    item_level=20,
    required_level=15,
    inventory_type=17,
    bound=True,
)
SHOULDERS = guildjobs.Carried(
    guid=7002,
    entry=5404,
    name="Serpent's Shoulders",
    item_class=4,
    subclass=2,
    quality=3,
    sell_price=938,
    item_level=23,
    required_level=18,
    inventory_type=3,
    bound=True,
)
# A bind-on-equip blue never worn: tradable, so the guild still wants it.
LOOSE = dataclasses.replace(SHOULDERS, guid=7003, bound=False)


def ekka(**over):
    """A level 35 member at 0 free slots whose bags hold only what the verdict
    kept before #1592: a quest item, a mount and two bound outgrown blues."""
    base = dict(
        name="Ekka",
        level=35,
        free_slots=0,
        bag_slots=16,
        carried=(CRYSTAL, MOUNT, HAMMER, SHOULDERS),
    )
    base.update(over)
    return bonk(**base)


def sold(member, kept=None):
    return {c.name for c in guildjobs.vendor_stacks(member, kept)}


class ABoundBlueItOutgrewSells(unittest.TestCase):
    def test_the_verdict_sells_a_bound_outgrown_blue(self):
        verdict = vendorsale.verdict(HAMMER, guildjobs.vendor_judge(ekka()))
        self.assertIs(vendorsale.SELL, verdict[0])
        self.assertIn("outgrown", verdict[1])

    def test_a_full_member_with_only_bound_blues_to_spare_walks_to_sell(self):
        step = guildjobs._full_bags_first(ekka(), None, (), 600.0)
        self.assertIsNotNone(step)
        self.assertEqual("sell", step.action)
        self.assertEqual(
            {"guid:%d" % HAMMER.guid, "guid:%d" % SHOULDERS.guid},
            {r.command for r in step.rows},
        )

    def test_the_quest_item_and_the_mount_stay(self):
        self.assertEqual({HAMMER.name, SHOULDERS.name}, sold(ekka()))


class ATradableBlueIsStillGuildLoot(unittest.TestCase):
    def test_an_unbound_outgrown_blue_is_kept(self):
        verdict = vendorsale.verdict(LOOSE, guildjobs.vendor_judge(ekka()))
        self.assertEqual(
            (vendorsale.KEEP, "guild loot, for the loot council and the bank"),
            verdict,
        )

    def test_a_carried_row_with_no_bound_column_is_not_bound(self):
        self.assertFalse(guildjobs.Carried(guid=1, entry=1).bound)


class ABoundBlueItWillWearIsKept(unittest.TestCase):
    def test_a_bound_upgrade_stays(self):
        # Sword of Zeal (item level 32) over Bonk's level 16 main hand.
        bound = dataclasses.replace(BLUE, bound=True)
        verdict = vendorsale.verdict(bound, guildjobs.vendor_judge(bonk()))
        self.assertIs(vendorsale.KEEP, verdict[0])
        self.assertIn("an upgrade", verdict[1])

    def test_a_bound_blue_is_kept_while_the_worn_gear_is_unread(self):
        bound = dataclasses.replace(BLUE, bound=True)
        verdict = vendorsale.verdict(bound, guildjobs.vendor_judge(bonk(worn=None)))
        self.assertEqual((vendorsale.KEEP, "its worn gear is unread"), verdict)

    def test_a_bound_blue_its_class_cannot_wear_sells(self):
        # A level 25 mage (Stakk's class) cannot wield a two-handed mace.
        mage = gear.CharacterState(
            name="Stakk", class_id=8, level=25, equipped={"main_hand": 10}
        )
        verdict = vendorsale.verdict(
            HAMMER, guildjobs.vendor_judge(bonk(class_id=8, worn=mage))
        )
        self.assertIs(vendorsale.SELL, verdict[0])


class TheBridgeReadsTheBinding(unittest.TestCase):
    def test_the_carried_read_selects_the_soulbound_flag(self):
        self.assertIn("ii.flags & 1", bridge._JOB_ITEMS_SQL)
        self.assertIn("AS bound", bridge._JOB_ITEMS_SQL)

    def test_a_row_flagged_soulbound_is_carried_bound(self):
        rows = [
            dict(owner=5, item_guid=7001, entry=5187, count=1, quality=3, bound=1),
            dict(owner=5, item_guid=7003, entry=5404, count=1, quality=3, bound=0),
        ]
        carried = guildjobs.carried_from_rows(rows)[5]
        self.assertEqual([True, False], [c.bound for c in carried])


if __name__ == "__main__":
    unittest.main()
