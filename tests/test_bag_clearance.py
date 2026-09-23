"""Clearing the bags that withhold both families' dungeon campaigns (#88).

Measured on wow-dev 2026-09-22 with both campaigns queued and withheld by
`bridge._drive_dungeon`: Grog at 0 free slots carrying a spare Red Leather
Bag (8) while wearing a Small Green Pouch (6) and a Reinforced Steel Lockbox;
Ugga at 0 carrying three lockboxes; Bork, the family rogue, at Lockpicking
300 with 6 free; Zug at 3 free with 2149 copper against a 2000 copper
reserve and a 500 copper pouch in reach.

Pinned here: the reserve yields only for a campaign-blocking buyer, a spare
bag larger than a worn one is put on by its own holder when the core can do
the swap, lockboxes reach a rogue who can pick them and are sold when none
can, and a tool is kept only for a holder whose own trades use it. The bridge
is read as text because it imports discord.
"""

import pathlib
import re
import unittest

import bag_pressure
import bag_upgrade
import disposition
import lockbox

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


def _sql(name: str) -> str:
    src = _source()
    start = src.index(name + " = (")
    return src[start : src.index("\n)\n", start)]


POUCH = bag_pressure.BagOffer(entry=4496, name="Small Brown Pouch", slots=6, price=500)


def zug(money=2149, free_slots=3):
    return bag_pressure.BagBuyer(
        name="Zug",
        level=20,
        money=money,
        open_positions=4,
        free_slots=free_slots,
        stocks=frozenset({4496}),
    )


class TheReserveYieldsOnlyToACampaign(unittest.TestCase):
    def test_without_a_campaign_zug_is_held_back_as_before(self):
        got, notes = bag_pressure.bag_purchases([zug()], [POUCH])
        self.assertEqual(got, ())
        self.assertIn("cannot spare 500", notes[0])

    def test_a_waiting_campaign_buys_zug_his_pouch(self):
        got, notes = bag_pressure.bag_purchases([zug()], [POUCH], campaign_waiting=True)
        self.assertEqual([p.buyer for p in got], ["Zug"])
        self.assertEqual(notes, ())
        self.assertIn("reserve yields", got[0].why)

    def test_a_buyer_above_the_trigger_keeps_the_reserve(self):
        got, _ = bag_pressure.bag_purchases(
            [zug(free_slots=bag_pressure.TOWN_RUN_FREE_SLOTS + 1)],
            [POUCH],
            campaign_waiting=True,
        )
        self.assertEqual(got, ())

    def test_the_price_itself_never_yields(self):
        got, _ = bag_pressure.bag_purchases(
            [zug(money=499)], [POUCH], campaign_waiting=True
        )
        self.assertEqual(got, ())

    def test_the_bridge_reads_the_queue_and_passes_it(self):
        body = _block("    async def _buy_bags_once(")
        self.assertIn("_campaign_waiting, names", body)
        self.assertIn("campaign_waiting=campaign", body)

    def test_the_queue_read_crosses_the_collation_split_explicitly(self):
        sql = _sql("_CAMPAIGN_WAITING_SQL")
        self.assertIn("COLLATE utf8mb4_unicode_ci", sql)
        self.assertIn("q.status IN ('queued', 'active')", sql)


def bag(name, slots, guid, used=0, entry=0, general=True, inside=0):
    return bag_upgrade.Bag(
        name, slots, used=used, guid=guid, entry=entry, general=general, inside=inside
    )


PACK = 1159012
GROG = bag_upgrade.Member(
    "Grog",
    4,
    worn=(
        bag("Small Green Pouch", 6, 368082, used=6),
        bag("Red Leather Bag", 8, 874793, used=8),
        bag("Large Brown Sack", 10, PACK, used=10),
        bag("Green Leather Bag", 8, 1246251, used=8),
    ),
    carried=(bag("Red Leather Bag", 8, 1322682, entry=2657, inside=PACK),),
)


class ASpareLargerBagGoesOn(unittest.TestCase):
    def test_grog_swaps_the_red_bag_for_the_pouch(self):
        (move,) = bag_upgrade.self_equips([GROG])
        self.assertEqual(move.holder, "Grog")
        self.assertEqual(move.guid, 1322682)
        self.assertEqual(move.replaces, "Small Green Pouch")
        self.assertEqual(move.slots_gained, 2)
        self.assertEqual(move.command, "e Hitem:2657:0")

    def test_the_old_swap_test_would_have_refused_it(self):
        """_swap_is_safe counts free slots; the core empties the bag into the
        new one instead, so at 0 free the swap is still possible."""
        self.assertEqual(bag_upgrade.plan_bag_moves(4, GROG.worn, GROG.carried, 0), [])

    def test_a_spare_no_larger_is_left_alone(self):
        small = bag_upgrade.Member(
            "Grog", 4, worn=GROG.worn, carried=(bag("Pouch", 6, 9, entry=5572),)
        )
        self.assertEqual(bag_upgrade.self_equips([small]), [])

    def test_a_spare_inside_the_bag_it_replaces_is_left_alone(self):
        inner = bag_upgrade.Member(
            "Grog",
            4,
            worn=GROG.worn,
            carried=(bag("Red Leather Bag", 8, 7, entry=2657, inside=368082),),
        )
        self.assertEqual(bag_upgrade.self_equips([inner]), [])

    def test_the_spare_must_hold_every_item_of_the_worn_bag(self):
        worn = (bag("Big", 10, 1, used=10), bag("Also", 10, 2, used=10))
        carried = (bag("Satchel", 12, 3, entry=4498),)
        member = bag_upgrade.Member("Og", 2, worn=worn, carried=carried)
        self.assertEqual(len(bag_upgrade.self_equips([member])), 1)
        tight = (bag("Big", 10, 1, used=10),)
        member = bag_upgrade.Member(
            "Og", 1, worn=tight, carried=(bag("Small", 12, 3, entry=1, used=0),)
        )
        self.assertEqual(len(bag_upgrade.self_equips([member])), 1)
        over = (bag("Big", 10, 1, used=10),)
        member = bag_upgrade.Member(
            "Og", 1, worn=over, carried=(bag("Tiny", 9, 3, entry=1),)
        )
        self.assertEqual(bag_upgrade.self_equips([member]), [])

    def test_a_profession_bag_is_never_the_spare(self):
        herb = bag_upgrade.Member(
            "Ugga",
            4,
            worn=GROG.worn,
            carried=(bag("Herb Pouch", 12, 5, entry=22250, general=False),),
        )
        self.assertEqual(bag_upgrade.self_equips([herb]), [])

    def test_an_empty_position_is_filled_first(self):
        member = bag_upgrade.Member(
            "Zug", 4, worn=(), carried=(bag("Small Brown Pouch", 6, 11, entry=4496),)
        )
        (move,) = bag_upgrade.self_equips([member])
        self.assertIsNone(move.replaces)
        self.assertEqual(move.slots_gained, 7)

    def test_a_bag_put_on_is_not_also_handed_to_a_sibling(self):
        members = bag_upgrade.without_bags([GROG], {1322682})
        self.assertEqual(members[0].carried, ())

    def test_rows_carry_entry_subclass_and_the_bag_it_sits_in(self):
        rows = [
            dict(
                holder="Grog",
                guid=PACK,
                name="Large Brown Sack",
                slots=10,
                bag=0,
                slot=21,
                used=10,
                entry=5576,
                subclass=0,
            ),
            dict(
                holder="Grog",
                guid=1322682,
                name="Red Leather Bag",
                slots=8,
                bag=PACK,
                slot=6,
                used=0,
                entry=2657,
                subclass=0,
            ),
        ]
        (member,) = bag_upgrade.members_from_rows(rows, ["Grog"])
        (spare,) = member.carried
        self.assertEqual((spare.entry, spare.general, spare.inside), (2657, True, PACK))

    def test_the_bag_sql_reads_what_self_equips_needs(self):
        sql = _sql("_BAG_STATE_SQL")
        self.assertIn("ii.itemEntry AS entry", sql)
        self.assertIn("it.subclass AS subclass", sql)

    def test_the_bridge_puts_own_bags_on_before_the_family_plan(self):
        body = _block("    async def _hand_bags_once(")
        self.assertIn("await self._equip_own_bags(members)", body)
        self.assertIn("bag_upgrade.without_bags(members, own)", body)
        self.assertLess(
            body.index("_equip_own_bags"), body.index("bag_upgrade.plan_family_bags(")
        )
        writer = _block("    async def _equip_own_bags(")
        self.assertIn("bag_upgrade.self_equips(members)", writer)
        self.assertIn("_recent_bag_equip_keys, GIVE_RETRY_MINUTES", writer)


def box(holder, guid, lock_id=62, unlocked=False, price=200):
    return lockbox.Box(
        holder=holder,
        guid=guid,
        entry=4638,
        name="Reinforced Steel Lockbox",
        lock_id=lock_id,
        unlocked=unlocked,
        quality=2,
        sell_price=price,
    )


BORK = lockbox.Picker("Bork", lockbox.ROGUE, lockpicking=300, free_slots=6)
GROGP = lockbox.Picker("Grog", 2, free_slots=0)
UGGA = lockbox.Picker("Ugga", 5, free_slots=0)
TRIGGER = bag_pressure.TOWN_RUN_FREE_SLOTS


class LockboxesReachTheRogue(unittest.TestCase):
    def test_the_rogue_unlocks_his_own_then_opens_it(self):
        got = lockbox.plan([box("Bork", 1)], [BORK], TRIGGER)
        self.assertEqual(got.unlock, ("Bork",))
        got = lockbox.plan([box("Bork", 1, unlocked=True)], [BORK], TRIGGER)
        self.assertEqual(got.open, ("Bork",))

    def test_a_siblings_box_goes_to_the_rogue(self):
        got = lockbox.plan([box("Grog", 2)], [BORK, GROGP], TRIGGER)
        (hand,) = got.hands
        self.assertEqual((hand.holder, hand.taker), ("Grog", "Bork"))
        self.assertEqual(hand.command, "guid:2")
        self.assertTrue(hand.post_command.startswith("send item:2 "))

    def test_the_rogue_is_never_filled_to_the_trigger(self):
        boxes = [box("Ugga", 3), box("Ugga", 4), box("Ugga", 5), box("Grog", 2)]
        got = lockbox.plan(boxes, [BORK, GROGP, UGGA], TRIGGER)
        self.assertEqual(len(got.hands), 2)
        self.assertEqual(len(got.notes), 2)

    def test_no_rogue_sells_it(self):
        got = lockbox.plan([box("Grog", 2)], [GROGP], TRIGGER)
        self.assertEqual([b.guid for b in got.sell], [2])
        (sale,) = lockbox.sale_candidates(got.sell)
        self.assertEqual((sale.holder, sale.item_guid, sale.count), ("Grog", 2, 1))

    def test_a_rogue_below_the_lock_sells_it(self):
        novice = lockbox.Picker("Bork", lockbox.ROGUE, lockpicking=100, free_slots=9)
        got = lockbox.plan([box("Grog", 2)], [novice], TRIGGER)
        self.assertEqual(len(got.sell), 1)

    def test_an_unknown_lock_needs_the_skill_cap(self):
        self.assertEqual(box("Grog", 2, lock_id=999).skill_needed, 300)

    def test_a_box_with_no_price_is_not_sold(self):
        self.assertEqual(lockbox.sale_candidates([box("Grog", 2, price=0)]), ())

    def test_rows_read_the_unlocked_bit(self):
        rows = [
            dict(
                holder="Ugga",
                item_guid=9,
                entry=5758,
                name="Mithril Lockbox",
                item_class=15,
                lock_id=62,
                instance_flags=4,
                quality=2,
                sell_price=250,
            ),
            dict(
                holder="Ugga",
                item_guid=10,
                entry=1,
                name="Not a box",
                item_class=12,
                lock_id=62,
                instance_flags=0,
            ),
        ]
        (got,) = lockbox.boxes_from_rows(rows)
        self.assertTrue(got.unlocked)

    def test_the_vendor_pass_routes_and_sells_them(self):
        body = _block("    async def _vendor_once(")
        self.assertIn("locks = await self._lockbox_plan(names, free_slots)", body)
        self.assertIn("await self._route_lockboxes(names, locks)", body)
        self.assertIn(") + lock_sales", body)
        self.assertLess(
            body.index("_route_lockboxes"),
            body.index("if not bag_pressure.family_town_run_needed("),
        )

    def test_a_box_moves_only_by_a_near_give_or_a_letter(self):
        body = _block("    async def _hand_lockboxes(")
        self.assertIn("handover.verdict(", body)
        self.assertIn("mailable=True", body)
        writer = _block("def _insert_lockbox_row(")
        self.assertIn('if kind not in ("bot", handover.GIVE, handover.MAIL)', writer)

    def test_lockbox_is_in_the_image(self):
        self.assertIn("lockbox.py", DOCKERFILE.read_text(encoding="utf-8"))


def tool(entry, name, bag_family, guid, holder):
    return {
        "holder": holder,
        "item_guid": guid,
        "count": 1,
        "entry": entry,
        "name": name,
        "quality": 1,
        "sell_price": 16,
        "item_class": 2,
        "bag_family": bag_family,
    }


HAMMER = tool(5956, "Blacksmith Hammer", 1152, 1, "Grog")
PICK = tool(2901, "Mining Pick", 1024, 2, "Ugga")


class AToolIsKeptForTheHolderWhoUsesIt(unittest.TestCase):
    def test_every_tool_is_kept_without_a_plan_as_before(self):
        keeps = disposition.profession_keeps([HAMMER, PICK])
        self.assertEqual(sorted(keeps), [1, 2])

    def test_a_tool_of_the_holders_own_trade_is_kept(self):
        keeps = disposition.profession_keeps(
            [HAMMER], worked_by={"Grog": ("mining", "engineering")}
        )
        self.assertIn(1, keeps)

    def test_a_tool_the_holder_has_no_trade_for_is_left_to_the_vendor(self):
        keeps = disposition.profession_keeps(
            [PICK], worked_by={"Ugga": ("alchemy", "herbalism")}
        )
        self.assertNotIn(2, keeps)

    def test_a_holder_with_no_known_plan_keeps_the_tool(self):
        keeps = disposition.profession_keeps([PICK], worked_by={"Grog": ("mining",)})
        self.assertIn(2, keeps)

    def test_the_hammer_serves_blacksmithing_too(self):
        self.assertIn("blacksmithing", disposition.tool_trades(5956, 1152))
        self.assertEqual(disposition.tool_trades(1, 128), ("engineering",))

    def test_the_vendor_read_passes_each_holders_plan(self):
        body = _block("def _fetch_vendor_items(")
        self.assertIn("worked_by = _worked_by(names)", body)
        self.assertIn("worked_by=worked_by", body)
        plan = _block("def _worked_by(")
        self.assertIn("professions.assigned(name)", plan)
        self.assertIn("_fetch_declared_trades(names)", plan)


if __name__ == "__main__":
    unittest.main()
