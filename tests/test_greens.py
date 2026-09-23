"""Old greens leave the bags, and only the ones nobody will ever wear.

MEASURED ON THE DEV FAMILY, 2026-09-08, and the numbers are the argument.

The five carry 207 uncommon items. That figure is what a naive count says and
it is not the pile: 46 of them are BEING WORN and 6 are the bags themselves.
Of the 155 that are genuinely loose, 54 are not gear at all - Gold Ore and
Silver Bars that feed Grug's mining and blacksmithing, Jade and Tigerseye,
four `Formula: Enchant ...` for Og, Plans, Patterns, and eleven Bronze
Lockboxes that Bork the rogue can open. Selling those is the disaster this
suite exists to prevent, and the quality<=1 rule in `sellable` is what
prevents it, so that rule is deliberately left exactly as it was.

That leaves 101 carried weapons and armour, and the family-fit gate splits
them: 34 are upgrades the HOLDER should be wearing, 35 are upgrades a SIBLING
should be handed, 3 are rings this codebase has no slot map for, and 25 are
what the owner actually asked about - old greens nobody will ever wear.

WHY THE GATE HAD TO EXIST BEFORE ANYTHING COULD BE SOLD. Without it the pass
sold four rows, and two of them were soulbound upgrades their holders should
have been wearing: Og's Buccaneer's Orb (item level 23 over an equipped 22)
and Ugga's Bright Cloak (23 over 22). `gear.is_upgrade_for` refuses anything
soulbound - correct for a hand-off, wrong for the holder's own bags - so the
holder is asked with `gear.would_wear` instead. That is the single most
important line in this change and the first test below is it.
"""

import pathlib
import unittest

import bag_pressure
import disposition
import gear

WARRIOR, PALADIN, ROGUE, PRIEST, MAGE = 1, 2, 4, 5, 8
ANY_CLASS = -1  # item_template.AllowableClass for "all"
MAGE_ONLY = 1 << (MAGE - 1)
WARRIOR_ONLY = 1 << (WARRIOR - 1)

# A vendor in reach and nothing else, which is the deployment: ECONOMY_ERRANDS
# is ("vendor", "banker", "repair"), so no pass can put anybody at an
# auctioneer or a mailbox however finished those executors are.
IN_TOWN = disposition.Family(vendor_reachable=True)
THE_FIVE = ["Bork", "Grog", "Grug", "Og", "Ugga"]


def worn(name, class_id, level, **slots):
    """Equipped rows for one character, as _FAMILY_EQUIPPED_SQL returns them.

    `slots` is inventory_type -> item level, keyed by the raw InventoryType
    the SQL hands over, because that is the shape the seam actually carries.
    """
    if not slots:
        return [
            dict(
                name=name,
                class_id=class_id,
                level=level,
                inventory_type=None,
                item_level=None,
            )
        ]
    return [
        dict(
            name=name,
            class_id=class_id,
            level=level,
            inventory_type=int(inv.lstrip("i")),
            item_level=int(ilvl),
        )
        for inv, ilvl in slots.items()
    ]


def carried(**kw):
    """One carried gear row, as _SURPLUS_GEAR_SQL returns it.

    Defaults describe Og's Rigid Cape: a tradable green cloak, item level 19,
    required level 14, on a level-28 mage who has long outgrown it.
    """
    base = dict(
        holder="Og",
        level=28,
        item_guid=5001,
        entry=9001,
        count=1,
        instance_flags=0,
        name="Rigid Cape",
        quality=2,
        sell_price=402,
        required_level=14,
        bonding=2,
        item_class=4,
        item_level=19,
        allowable_class=ANY_CLASS,
        inventory_type=16,
    )
    base.update(kw)
    return base


def sold(gear_rows, equipped_rows, keep_names=()):
    """Every guid the wired vendor pass would offer to a merchant."""
    fits = bag_pressure.family_fits(gear_rows, equipped_rows, THE_FIVE)
    return {
        c.item_guid
        for c in bag_pressure.gear_candidates(
            gear_rows,
            IN_TOWN,
            available=disposition.EXECUTABLE_TODAY,
            fits=fits,
            keep_names=keep_names,
        )
    }


# Three characters wearing something better in EVERY slot these tests touch:
# back (16), chest (5), legs (7), feet (8) and off hand (23). Filling all of
# them is not tidiness, it is the fixture being honest - an empty slot is a
# real upgrade for whoever has it, so a half-dressed fixture would prove that
# gear is kept for the wrong reason and hide a rule that never ran.
FULLY_DRESSED = dict(i16=30, i5=30, i7=30, i8=30, i23=30)
OG_IS_DRESSED = (
    worn("Og", MAGE, 28, **FULLY_DRESSED)
    + worn("Grug", WARRIOR, 32, **FULLY_DRESSED)
    + worn("Ugga", PRIEST, 27, **FULLY_DRESSED)
)


class NothingTheFamilyWouldWearIsEverSold(unittest.TestCase):
    """The protections, one test each, in the order they are enumerated."""

    def test_a_soulbound_upgrade_for_its_holder_is_never_sold(self):
        """Og's Buccaneer's Orb, live on 2026-09-08. The shipped pass sold it.

        Soulbound and outgrown by the level margin, so every level-based test
        agrees it is disposable, and it is the best off-hand Og owns.
        """
        orb = carried(
            name="Buccaneer's Orb",
            item_guid=7001,
            instance_flags=1,
            required_level=18,
            item_level=23,
            inventory_type=23,
        )
        dressed = worn("Og", MAGE, 28, i23=22)
        self.assertEqual(sold([orb], dressed), set())
        # And prove the reason, not just the outcome: the holder wants it.
        fits = bag_pressure.family_fits([orb], dressed, THE_FIVE)
        self.assertEqual(fits[7001], disposition.FIT_HOLDER)

    def test_a_piece_a_sibling_would_wear_is_never_sold(self):
        """Ugga carries it, Ugga cannot use it, Og can. That is a hand-off."""
        robe = carried(
            holder="Ugga",
            level=27,
            item_guid=7002,
            name="Mystic's Woolies",
            required_level=14,
            item_level=19,
            inventory_type=7,
            allowable_class=MAGE_ONLY,
        )
        family = worn("Ugga", PRIEST, 27, i7=20) + worn("Og", MAGE, 28, i7=12)
        self.assertEqual(sold([robe], family), set())
        fits = bag_pressure.family_fits([robe], family, THE_FIVE)
        self.assertEqual(fits[7002], disposition.FIT_SIBLING)

    def test_a_ring_is_kept_because_nothing_here_can_judge_a_ring(self):
        """3 carried rings, InventoryType 11, which _SLOT_BY_INVTYPE omits.

        "No slot for it" must never read as "nobody wants it". The slot map is
        deliberately small; this keeps it a refusal rather than a licence.
        """
        ring = carried(
            name="Clay Ring", item_guid=7003, inventory_type=11, required_level=5
        )
        self.assertEqual(sold([ring], OG_IS_DRESSED), set())
        fits = bag_pressure.family_fits([ring], OG_IS_DRESSED, THE_FIVE)
        self.assertEqual(fits[7003], disposition.FIT_UNJUDGEABLE)

    def test_a_quest_item_is_refused_even_wearing_an_armour_class(self):
        quest = carried(item_class=12, item_guid=7004)
        self.assertEqual(sold([quest], OG_IS_DRESSED), set())

    def test_a_container_is_never_sold(self):
        """A bag is class 1, and an empty bag is slots - bag_upgrade's point.

        Refused twice over: _SURPLUS_GEAR_SQL selects only classes 2 and 4,
        and EQUIPMENT_CLASSES excludes class 1 if one ever arrived anyway.
        """
        bag = carried(name="Small Black Pouch", item_class=1, item_guid=7005, quality=1)
        self.assertNotIn(1, bag_pressure.EQUIPMENT_CLASSES)
        self.assertEqual(sold([bag], OG_IS_DRESSED), set())

    def test_a_profession_material_is_never_sold(self):
        """Gold Ore feeds Grug's mining and blacksmithing. Class 7, not gear.

        The family deliberately feeds one character's crafting from the
        others' gathering, so these are not junk however green they look.
        """
        ore = carried(
            name="Gold Ore",
            item_class=7,
            item_guid=7006,
            sell_price=500,
            required_level=0,
            inventory_type=0,
        )
        self.assertEqual(sold([ore], OG_IS_DRESSED), set())

    def test_the_junk_rule_still_refuses_every_uncommon(self):
        """`sellable` is untouched, and that is what protects the other 54.

        Gems, ore, bars, four enchanting formulas and eleven lockboxes all
        reach the junk half of the pass. Relaxing quality<=1 there would sweep
        up the lot, so the greens that ARE disposable are routed through the
        gear half instead, which is restricted to weapons and armour.
        """
        for name in (
            "Jade",
            "Gold Bar",
            "Ornate Bronze Lockbox",
            "Formula: Enchant Chest - Minor Mana",
        ):
            self.assertFalse(
                bag_pressure.sellable(
                    bag_pressure.ItemForSale(
                        quality=2,
                        quest_item=False,
                        reagent=False,
                        profession_needed=False,
                        sell_price=700,
                    )
                ),
                name,
            )

    def test_an_item_the_owner_marked_is_never_sold(self):
        """The owner's hand brake, by name, matched case and space blind."""
        keeper = carried(
            name="Journeyman's Pants",
            item_guid=7007,
            required_level=5,
            item_level=10,
            inventory_type=7,
        )
        self.assertEqual(sold([keeper], OG_IS_DRESSED), {7007})
        self.assertEqual(
            sold([keeper], OG_IS_DRESSED, keep_names=("  journeyman's PANTS ",)), set()
        )

    def test_the_owners_mark_also_covers_the_junk_half_of_the_pass(self):
        row = {
            "holder": "Og",
            "item_guid": 8001,
            "count": 1,
            "name": "Ornate Bronze Lockbox",
            "quality": 0,
            "sell_price": 50,
            "quest_item": False,
            "reagent": False,
            "profession_needed": False,
        }
        self.assertEqual(len(bag_pressure.vendor_candidates([row])), 1)
        self.assertEqual(
            bag_pressure.vendor_candidates(
                [row], keep_names=("Ornate Bronze Lockbox",)
            ),
            (),
        )

    def test_gear_still_close_to_level_is_kept_when_nobody_was_asked(self):
        """The `outgrown` margin, still doing its job wherever the gate has
        not answered. FIT_UNASKED is the default and is what every caller
        that has not been taught about `fits` gets."""
        recent = carried(item_guid=7008, required_level=25, item_level=30)
        self.assertEqual(
            bag_pressure.gear_candidates(
                [recent], IN_TOWN, available=disposition.EXECUTABLE_TODAY
            ),
            (),
        )

    def test_a_piece_nobody_has_grown_into_yet_is_kept(self):
        """`gear.is_upgrade_for` refuses a character below the required level
        with "requires level N", so a piece the family has not reached answers
        NOBODY for a reason that levelling retires. That is not an old green,
        it is a future one, and selling it is the irreversible half of a
        temporary fact (infra#3464).
        """
        early = carried(
            item_guid=7013,
            name="Feet of the Lynx",
            required_level=40,
            item_level=45,
            inventory_type=8,
        )
        self.assertEqual(sold([early], OG_IS_DRESSED), set())
        fits = bag_pressure.family_fits([early], OG_IS_DRESSED, THE_FIVE)
        self.assertEqual(fits[7013], disposition.FIT_NOBODY)

    def test_a_worthless_piece_is_not_walked_to_a_vendor(self):
        self.assertEqual(
            sold([carried(item_guid=7009, sell_price=0)], OG_IS_DRESSED), set()
        )


class NotKnowingIsAlwaysAReasonToKeep(unittest.TestCase):
    """Every way the gate can come back short, and all of them keep."""

    def test_no_equipped_rows_at_all_sells_nothing(self):
        """An older world image, or a failed fetch. Refusing is the answer."""
        self.assertEqual(sold([carried()], []), set())

    def test_a_holder_nobody_described_is_not_assumed_to_want_nothing(self):
        orphan = carried(holder="Bork", item_guid=7010)
        self.assertEqual(sold([orphan], worn("Og", MAGE, 28, i16=26)), set())

    def test_a_caller_that_never_asked_behaves_exactly_as_before(self):
        """FIT_UNASKED is the default, and it is the pre-gate behaviour.

        This is what makes the change safe to land: a call site that has not
        been taught about `fits` cannot start selling things.
        """
        rows = [carried()]
        self.assertEqual(
            bag_pressure.gear_candidates(
                rows, IN_TOWN, available=disposition.EXECUTABLE_TODAY
            ),
            (),
        )

    def test_a_row_missing_a_gear_fact_is_dropped_not_guessed_at(self):
        broken = carried(item_guid=7011)
        del broken["item_level"]
        self.assertEqual(
            bag_pressure.family_fits([broken], OG_IS_DRESSED, THE_FIVE), {}
        )
        self.assertEqual(sold([broken], OG_IS_DRESSED), set())

    def test_a_character_wearing_nothing_is_still_described(self):
        """A LEFT JOIN row with no item. They must not vanish from the gate."""
        states = gear.characters_from_rows(worn("Bork", ROGUE, 28), THE_FIVE)
        self.assertEqual([c.name for c in states], ["Bork"])
        self.assertEqual(states[0].equipped, {})


class OnlyNobodyWantsItOpensTheVendor(unittest.TestCase):
    """The one sentence: a green nobody will wear is vendored, and only that.

    WHY NOT THE AUCTION, on the numbers rather than on principle. The house's
    own listings price a green weapon or armour piece in this family's item
    level band at 2.2 to 2.9 times its vendor value - below the multiple this
    module already picked as the bar - and the whole disposable pile is worth
    0.84 gold while the five carry about 800. Two of the five are at 100% of
    their bag slots. The slot is what is at stake, not the copper.

    WHY NOT DISENCHANT. `overseer_command.kind` is an 18-value ENUM with no
    'disenchant' in it, so the row cannot be inserted, and mod-overseer has no
    handler for one. Og is enchanting 1 of 75, which reaches 38 of 155 greens.

    WHY NOTHING IS DELETED. Nothing in the disposable pile is worth zero at a
    vendor, so deleting would only ever destroy something a merchant would pay
    for, and no executor in mod-overseer destroys an item in the first place.
    """

    def test_a_tradable_green_nobody_wants_reaches_the_vendor(self):
        self.assertEqual(sold([carried()], OG_IS_DRESSED), {5001})

    def test_and_the_gate_says_which_answer_opened_it(self):
        fits = bag_pressure.family_fits([carried()], OG_IS_DRESSED, THE_FIVE)
        self.assertEqual(fits[5001], disposition.FIT_NOBODY)

    def test_the_auction_is_not_claimed_to_be_available(self):
        """No writer here and no way to reach an auctioneer, so it is not on.

        DoAuction is finished and would list; this process still cannot ask
        it to. Saying otherwise in EXECUTABLE_TODAY would be the lie the set
        exists to prevent.
        """
        self.assertNotIn(disposition.AUCTION, disposition.EXECUTABLE_TODAY)
        self.assertNotIn(disposition.DISENCHANT, disposition.EXECUTABLE_TODAY)

    def test_turning_the_auction_on_later_takes_the_worthwhile_ones_back(self):
        """The premium is per item, so the rule survives an auctioneer leg."""
        rich = disposition.Item(
            name="Rigid Cape",
            quality=2,
            known=True,
            binding=disposition.BIND_ON_EQUIP,
            quest_item=False,
            equipment=True,
            required_level=14,
            sell_price=402,
            auction_value=402 * disposition.AUCTION_BEATS_VENDOR_BY,
        )
        at_the_house = disposition.Family(vendor_reachable=True, auction_reachable=True)
        both = disposition.EXECUTABLE_TODAY | {disposition.AUCTION}
        self.assertEqual(
            disposition.decide(
                rich,
                at_the_house,
                character_level=28,
                available=both,
                family_fit=disposition.FIT_NOBODY,
            ).route,
            disposition.AUCTION,
        )

    def test_a_green_nobody_wants_no_longer_waits_for_the_level_margin(self):
        """THE DEFECT THIS PR IS AGAINST, in one row (infra#3464).

        `outgrown` asks whether the holder has moved ten levels past the
        required level, which is a PROXY for "would anybody wear this". The
        family-fit gate asks that question directly, of all five, with the
        same opinion that decides hand-offs. Letting the proxy overrule the
        answer is why a green nobody can use sits in a bag until its holder
        out-levels it by ten - and this family farms one instance, so several
        of them never get there.

        Safe because gear only ever improves: item level is fixed on the item
        and nothing here takes gear off anybody, so a piece that beats
        nobody's slot today beats nobody's slot at any later level.
        """
        stuck = carried(
            item_guid=7014, name="Ridge Cloak", required_level=25, item_level=30
        )
        self.assertEqual(sold([stuck], OG_IS_DRESSED), {7014})
        fits = bag_pressure.family_fits([stuck], OG_IS_DRESSED, THE_FIVE)
        self.assertEqual(fits[7014], disposition.FIT_NOBODY)

    def test_the_margin_still_holds_every_answer_that_is_not_nobody(self):
        """One rule changed and only for one answer. A holder's own upgrade, a
        sibling's, and a piece nothing can judge are all still kept by the
        checks above this branch, and a piece nobody was asked about is kept
        by the margin itself."""
        item = disposition.Item(
            name="Ridge Cloak",
            quality=2,
            known=True,
            binding=disposition.BIND_ON_EQUIP,
            quest_item=False,
            equipment=True,
            required_level=25,
            sell_price=402,
        )
        for answer in (
            disposition.FIT_UNASKED,
            disposition.FIT_HOLDER,
            disposition.FIT_UNJUDGEABLE,
        ):
            with self.subTest(answer=answer):
                self.assertEqual(
                    disposition.decide(
                        item,
                        IN_TOWN,
                        character_level=28,
                        available=disposition.EXECUTABLE_TODAY,
                        family_fit=answer,
                    ).route,
                    disposition.KEEP,
                )

    def test_a_soulbound_green_nobody_wants_is_still_a_vendor_sale(self):
        """Unchanged behaviour, and the reason is unchanged: nobody can list
        or receive it, so no route loses out by taking the copper."""
        orb = carried(
            name="Bright Boots",
            item_guid=7012,
            instance_flags=1,
            required_level=18,
            item_level=23,
            inventory_type=8,
        )
        self.assertEqual(sold([orb], OG_IS_DRESSED), {7012})


class TheHolderIsAskedSoulboundBlind(unittest.TestCase):
    """`would_wear` and `is_upgrade_for` differ by exactly one refusal."""

    def _orb(self, soulbound):
        return gear.Holding(
            holder="Og",
            guid=1,
            entry=1,
            name="Buccaneer's Orb",
            quality=2,
            item_level=23,
            required_level=18,
            allowable_class=ANY_CLASS,
            inventory_type=23,
            item_class=gear.ITEM_CLASS_ARMOR,
            soulbound=soulbound,
        )

    def _og(self):
        return gear.CharacterState(
            name="Og", class_id=MAGE, level=28, equipped={"off_hand": 22}
        )

    def test_would_wear_ignores_binding_and_is_upgrade_for_does_not(self):
        self.assertTrue(gear.would_wear(self._orb(True), self._og())[0])
        self.assertFalse(gear.is_upgrade_for(self._orb(True), self._og())[0])
        self.assertTrue(gear.is_upgrade_for(self._orb(False), self._og())[0])

    def test_they_agree_on_everything_else(self):
        for soulbound in (True, False):
            unusable = gear.Holding(
                holder="Og",
                guid=2,
                entry=2,
                name="Plate Helm",
                quality=2,
                item_level=40,
                required_level=1,
                allowable_class=WARRIOR_ONLY,
                inventory_type=1,
                item_class=gear.ITEM_CLASS_ARMOR,
                soulbound=soulbound,
            )
            self.assertFalse(gear.would_wear(unusable, self._og())[0])
            self.assertFalse(gear.is_upgrade_for(unusable, self._og())[0])

    def test_a_sibling_is_still_asked_with_the_binding_refusal(self):
        """Nine soulbound pieces would suit a sibling and can never reach one.

        Measured 2026-09-08. Their protection is the holder's own claim, asked
        first; a sibling's wish must not keep an item nobody can hand over.
        """
        self.assertEqual(
            gear.claimant(
                self._orb(True),
                [
                    gear.CharacterState(
                        name="Og", class_id=MAGE, level=28, equipped={"off_hand": 30}
                    ),
                    gear.CharacterState(
                        name="Ugga", class_id=PRIEST, level=27, equipped={}
                    ),
                ],
            ),
            gear.NOBODY,
        )

    def test_the_holder_is_asked_before_any_sibling(self):
        """Both would wear it; the one already carrying it keeps it."""
        self.assertEqual(
            gear.claimant(
                self._orb(False),
                [
                    self._og(),
                    gear.CharacterState(
                        name="Ugga", class_id=PRIEST, level=27, equipped={}
                    ),
                ],
            ),
            "Og",
        )


class TheBridgeAsksBeforeItSells(unittest.TestCase):
    """The seam, read as text: bridge.py imports discord and cannot import."""

    def setUp(self):
        self.src = (
            pathlib.Path(__file__).resolve().parents[1] / "bridge.py"
        ).read_text(encoding="utf-8")

    def _gear_sql(self):
        return self.src[
            self.src.index("_SURPLUS_GEAR_SQL = (") : self.src.index(
                "def _fetch_surplus_gear("
            )
        ]

    def test_the_gear_query_carries_what_the_gate_needs(self):
        block = self._gear_sql()
        for column in (
            "it.ItemLevel AS item_level",
            "it.AllowableClass AS allowable_class",
            "it.InventoryType AS inventory_type",
        ):
            self.assertIn(column, block)

    def test_the_two_queries_cover_disjoint_halves_of_the_character(self):
        """Worn is slot < 19; carried is 19..38 and inside a worn bag.

        Nothing equipped can appear in the sale query, which is the first
        protection on the owner's list and the one enforced by geometry
        rather than by a rule anybody has to remember.
        """
        worn_sql = self.src[
            self.src.index("_FAMILY_EQUIPPED_SQL = (") : self.src.index(
                "def _fetch_family_equipped("
            )
        ]
        self.assertIn("ci.bag = 0 AND ci.slot < 19", worn_sql)
        self.assertIn("ci.bag = 0 AND ci.slot BETWEEN 19 AND 38", self._gear_sql())

    def test_the_gear_query_still_refuses_everything_but_weapons_and_armour(self):
        self.assertIn("it.class IN (2, 4)", self._gear_sql())

    def test_the_pass_asks_the_gate_and_passes_the_owners_mark(self):
        start = self.src.index("    async def _vendor_once(self")
        block = self.src[start : self.src.index("    async def _vendor_loop(")]
        self.assertIn("bag_pressure.family_fits(gear_rows, worn, names)", block)
        self.assertIn("fits=fits", block)
        self.assertIn("keep_names=OWNER_KEEPS", block)

    def _vendor_pass(self):
        start = self.src.index("    async def _vendor_once(self")
        return self.src[start : self.src.index("    async def _vendor_loop(")]

    def test_the_vendor_errand_is_written_once_and_to_the_leader(self):
        """infra#3553. One aim, on the character that carries `new rpg`.

        mod-overseer refuses to walk anybody else - "Followers travel by
        following the leader; aim the leader instead" - so a per-holder aim
        moved nobody while still being billed against that character's
        ErrandBudgetLimits bucket on every travel poll, which refused the
        whole family's vendor errand for fifteen minutes at a time.
        """
        block = self._vendor_pass()
        self.assertIn("self._claim_town_slot(", block)
        self.assertIn('"economy", leader, "vendor", urgent=True', block)
        self.assertNotIn('self._claim_town_slot("economy", holder', block)
        self.assertEqual(1, block.count("_claim_town_slot"))

    def test_the_aim_is_taken_outside_the_per_holder_loop(self):
        """A second aim per holder is the defect, so geometry forbids it.

        Counting the write is not enough on its own: the same single call
        placed inside `for holder in sorted(by_holder)` would be five writes
        again with one line of source.
        """
        block = self._vendor_pass()
        self.assertLess(
            block.index("_write_trade_errand"),
            block.index("for holder in sorted(by_holder):"),
        )

    def test_the_leader_is_the_one_that_carries_the_strategy(self):
        """`_head_now`, not bonds.head_of_family().

        `_mark_party_leader` writes `_head_now()` into `lead` and
        `_give_them_a_life` reads it to decide who gets `nc +new rpg`, so it
        is the only answer that names a character able to walk.
        """
        self.assertIn(
            "leader = await asyncio.to_thread(_head_now)", self._vendor_pass()
        )

    def test_whether_the_aim_was_taken_is_read_and_not_assumed(self):
        """The economy guard only retasks an idle traveller, so this write
        legitimately does nothing while the town trip owns the column. The
        caller used to hardcode `aimed = True` and log that instead."""
        block = self._vendor_pass()
        self.assertIn("aimed = await self._claim_town_slot(", block)
        # Asked of CODE and not of prose: the comment above the call quotes
        # the old line, so a substring search over the whole block would be
        # answered by the explanation of the bug rather than by the bug.
        code = [ln.split("#", 1)[0].strip() for ln in block.splitlines()]
        self.assertNotIn("aimed = True", code)

    def test_the_sale_rows_are_still_grouped_by_holder(self):
        """The errand is the leader's; the ROWS stay the holder's, because
        DoSell answers on the range of whoever is selling (infra#3464)."""
        block = self._vendor_pass()
        self.assertIn("by_holder.setdefault(candidate.holder, [])", block)
        self.assertIn("town = await asyncio.to_thread(_fetch_town, holder)", block)

    def test_the_pass_writes_a_sale_and_never_a_destruction(self):
        """The sale writer never destroys. Destroying an unpriced released
        quest item has its own writer, `_insert_destroy`, and its own gate
        (mod-overseer#614); nothing in the disposable pile reaches it."""
        start = self.src.index("def _insert_sell(")
        block = self.src[start : start + 1200]
        self.assertIn("'sell'", block)
        for never in ("destroy", "DestroyItem"):
            self.assertNotIn(never, block)


if __name__ == "__main__":
    unittest.main()
