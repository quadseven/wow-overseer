"""Routing a bag the way a person would, and refusing the routes that are shut.

Written from the dev family as measured on 2026-09-04: Og enchanting at skill
ONE, seventy-nine Linen Cloth held for a tailor at skill one, no guild bank,
nothing ever listed on the auction house, and twenty-two uncommons on Grug
alone. The refusals below are not hypothetical - most of them are the state
that family is actually in.
"""

import unittest

from disposition import (
    AUCTION,
    BANK,
    BIND_NONE,
    BIND_ON_EQUIP,
    BIND_ON_PICKUP,
    EXECUTABLE_TODAY,
    DISENCHANT,
    GIVE,
    KEEP,
    VENDOR,
    Family,
    Item,
    decide,
    outgrown,
)

# A town with both services open, so a test about routing is not accidentally
# a test about being out in the field.
TOWN = Family(
    enchanting_skill=0,
    vendor_reachable=True,
    auction_reachable=True,
    professions={"tailoring": 1},
)

# The family as measured: Og can technically enchant, at skill one.
REAL = Family(
    enchanting_skill=1,
    vendor_reachable=True,
    auction_reachable=False,
    professions={"tailoring": 1, "alchemy": 1, "leatherworking": 1},
)


def green(name="Ivycloth Cloak", **kw):
    """An ordinary outgrown green, overridable per test."""
    base = dict(
        name=name,
        quality=2,
        known=True,
        binding=BIND_ON_EQUIP,
        quest_item=False,
        equipment=True,
        required_level=15,
        sell_price=100,
    )
    base.update(kw)
    return Item(**base)


class NothingUnknownIsEverRisked(unittest.TestCase):
    """The defect this module is written against: flags that defaulted to safe
    and therefore approved anything nobody had classified."""

    def test_an_unclassified_item_is_kept(self):
        self.assertEqual(decide(Item(name="???"), TOWN).route, KEEP)

    def test_the_defaults_themselves_are_the_cautious_ones(self):
        """Constructed with a name and nothing else, an item must look like the
        most dangerous thing it could be, not the most convenient."""
        blank = Item(name="???")
        self.assertFalse(blank.known)
        self.assertTrue(blank.quest_item)
        self.assertEqual(blank.binding, BIND_ON_PICKUP)

    def test_a_quest_item_is_never_routed_anywhere(self):
        it = green("Gold Pickup Schedule", quest_item=True)
        self.assertEqual(decide(it, TOWN, character_level=28).route, KEEP)


class SoulboundCannotBeListed(unittest.TestCase):
    """The rule that decides the option set, and the one a person states as
    'you cannot auction that, it is soulbound'."""

    def test_a_soulbound_green_is_never_auctioned(self):
        it = green(binding=BIND_ON_PICKUP, auction_value=100000)
        self.assertNotEqual(decide(it, TOWN, character_level=28).route, AUCTION)

    def test_a_soulbound_green_goes_to_the_vendor_when_it_cannot_be_dusted(self):
        it = green(binding=BIND_ON_PICKUP, auction_value=100000)
        self.assertEqual(decide(it, TOWN, character_level=28).route, VENDOR)

    def test_a_bind_on_equip_green_of_the_same_value_is_listed(self):
        """The only difference between this and the test above is binding."""
        it = green(binding=BIND_ON_EQUIP, auction_value=100000)
        self.assertEqual(decide(it, TOWN, character_level=28).route, AUCTION)


class TheAuctionHasToBeWorthTheWalk(unittest.TestCase):
    def test_a_green_worth_barely_more_than_vendor_is_not_listed(self):
        it = green(auction_value=110, sell_price=100)
        self.assertEqual(decide(it, TOWN, character_level=28).route, VENDOR)

    def test_a_green_worth_several_times_vendor_is_listed(self):
        it = green(auction_value=100 * 4, sell_price=100)
        self.assertEqual(decide(it, TOWN, character_level=28).route, AUCTION)

    def test_an_unknown_auction_price_takes_the_sure_thing(self):
        """An unpriced item is not a reason to gamble a listing slot."""
        it = green(auction_value=None)
        self.assertEqual(decide(it, TOWN, character_level=28).route, VENDOR)

    def test_no_auctioneer_in_reach_means_no_listing(self):
        it = green(auction_value=100000)
        away = Family(vendor_reachable=True, auction_reachable=False)
        self.assertEqual(decide(it, away, character_level=28).route, VENDOR)


class DisenchantingIsNotAvailableToThisFamily(unittest.TestCase):
    """Og is the enchanter at skill 1. A rule that assumed otherwise would emit
    orders the world refuses, which reads in the log as a stuck bot."""

    def test_skill_one_cannot_break_down_a_level_fifteen_green(self):
        it = green(binding=BIND_ON_PICKUP, disenchant_skill_required=25)
        self.assertEqual(decide(it, REAL, character_level=28).route, VENDOR)

    def test_the_same_item_is_dusted_once_the_skill_is_there(self):
        able = Family(enchanting_skill=50, vendor_reachable=True)
        it = green(binding=BIND_ON_PICKUP, disenchant_skill_required=25)
        self.assertEqual(decide(it, able, character_level=28).route, DISENCHANT)

    def test_an_unknown_threshold_is_never_guessed_at(self):
        able = Family(enchanting_skill=450, vendor_reachable=True)
        it = green(binding=BIND_ON_PICKUP, disenchant_skill_required=None)
        self.assertEqual(decide(it, able, character_level=28).route, VENDOR)

    def test_trade_goods_are_not_disenchantable_however_high_the_skill(self):
        able = Family(enchanting_skill=450, vendor_reachable=True, professions={})
        cloth = Item(
            name="Linen Cloth",
            quality=1,
            known=True,
            binding=BIND_NONE,
            quest_item=False,
            equipment=False,
            sell_price=10,
            disenchant_skill_required=1,
        )
        self.assertNotEqual(decide(cloth, able).route, DISENCHANT)

    def test_a_common_item_is_not_disenchantable(self):
        able = Family(enchanting_skill=450, vendor_reachable=True)
        it = green(quality=1, binding=BIND_ON_PICKUP, disenchant_skill_required=1)
        self.assertNotEqual(decide(it, able, character_level=28).route, DISENCHANT)

    def test_a_natural_guild_enchanter_can_break_down_bind_on_equip_green(self):
        it = green(
            binding=BIND_ON_EQUIP,
            disenchant_skill_required=25,
            holder="Og",
        )
        family = Family(
            vendor_reachable=True,
            guild_enchanters={"Guildmate": 50},
        )
        self.assertEqual(
            decide(it, family, character_level=28, available={DISENCHANT}).route,
            DISENCHANT,
        )

    def test_no_qualifying_guild_enchanter_does_not_disassemble(self):
        it = green(
            binding=BIND_ON_EQUIP,
            disenchant_skill_required=25,
            holder="Og",
        )
        family = Family(vendor_reachable=True, guild_enchanters={"Guildmate": 10})
        verdict = decide(
            it,
            family,
            character_level=28,
            available={DISENCHANT, VENDOR, AUCTION},
        )
        self.assertEqual(verdict.route, VENDOR)
        self.assertIn("no qualifying natural guild enchanter", verdict.why)

    def test_soulbound_green_requires_the_holders_natural_skill(self):
        it = green(
            binding=BIND_ON_PICKUP,
            disenchant_skill_required=25,
            holder="Og",
        )
        family = Family(
            enchanting_skill=450,
            guild_enchanters={"Guildmate": 50},
        )
        self.assertNotEqual(
            decide(it, family, character_level=28, available={DISENCHANT}).route,
            DISENCHANT,
        )


class OldMeansOutgrown(unittest.TestCase):
    def test_a_green_near_your_level_is_kept(self):
        self.assertEqual(
            decide(green(required_level=25), TOWN, character_level=28).route, KEEP
        )

    def test_a_green_far_below_your_level_is_cleared_out(self):
        self.assertNotEqual(
            decide(green(required_level=10), TOWN, character_level=28).route, KEEP
        )

    def test_the_margin_protects_an_item_a_sibling_might_still_want(self):
        self.assertFalse(outgrown(green(required_level=20), 28))
        self.assertTrue(outgrown(green(required_level=18), 28))

    def test_something_with_no_level_is_not_equipment_to_outgrow(self):
        cloth = Item(
            name="Linen Cloth", quality=1, known=True, quest_item=False, equipment=False
        )
        self.assertFalse(outgrown(cloth, 28))


class ProfessionMaterialsAreNotLoot(unittest.TestCase):
    """The seventy-nine Linen Cloth. Selling these is selling the family's
    tailoring and cooking economy, and it is the exact failure the sale rule
    was one unset flag away from."""

    def cloth(self, **kw):
        base = dict(
            name="Linen Cloth",
            quality=1,
            known=True,
            binding=BIND_NONE,
            quest_item=False,
            equipment=False,
            sell_price=10,
            reagent_for="tailoring",
        )
        base.update(kw)
        return Item(**base)

    def test_cloth_the_tailor_needs_is_kept(self):
        self.assertEqual(decide(self.cloth(), TOWN, reagent_held=39).route, KEEP)

    def test_cloth_for_a_profession_nobody_has_is_still_kept(self):
        nobody = Family(vendor_reachable=True, professions={})
        self.assertEqual(decide(self.cloth(), nobody, reagent_held=999).route, KEEP)

    def test_surplus_beyond_what_the_family_keeps_is_sold(self):
        self.assertEqual(decide(self.cloth(), TOWN, reagent_held=500).route, VENDOR)

    def test_surplus_is_listed_when_it_is_worth_more_that_way(self):
        it = self.cloth(auction_value=1000)
        self.assertEqual(decide(it, TOWN, reagent_held=500).route, AUCTION)

    def test_surplus_with_nowhere_to_go_is_kept_not_dropped(self):
        field = Family(
            vendor_reachable=False,
            auction_reachable=False,
            professions={"tailoring": 1},
        )
        self.assertEqual(decide(self.cloth(), field, reagent_held=500).route, KEEP)


class TheFamilyComesBeforeTheVendor(unittest.TestCase):
    def test_an_upgrade_for_a_sibling_is_handed_over_not_sold(self):
        it = green(auction_value=100000)
        v = decide(it, TOWN, character_level=28, upgrade_for_sibling=True)
        self.assertEqual(v.route, GIVE)

    def test_that_beats_even_a_valuable_auction(self):
        """Ranking check: the family gate is above every disposal, so a
        mis-ranked disposal can waste value but never lose a sibling's upgrade."""
        it = green(binding=BIND_ON_EQUIP, auction_value=10**9)
        self.assertEqual(
            decide(it, TOWN, character_level=28, upgrade_for_sibling=True).route, GIVE
        )


class EveryVerdictExplainsItself(unittest.TestCase):
    def test_no_verdict_is_silent(self):
        cases = [
            Item(name="???"),
            green(),
            green(binding=BIND_ON_PICKUP),
            green(required_level=27),
        ]
        for it in cases:
            v = decide(it, TOWN, character_level=28)
            self.assertTrue(
                v.why.strip(), "a route with no reason cannot be reviewed: %r" % it.name
            )
            self.assertIn(it.name, v.why)


class TheBankIsWhereThingsGoToWait(unittest.TestCase):
    """Measured 2026-09-04: every member had elsewhere=0, so the family has
    never banked anything while carrying seventy-nine Linen Cloth for a tailor
    at skill one. That pile is the case this route exists for.

    A guild bank would be the shared version and does not exist: there is no
    guild, and although travel to a petitioner and to a guild banker both work,
    buying a charter, collecting signatures, registering and depositing are all
    unwritten. So every test here is about the PERSONAL bank.
    """

    def cloth(self, **kw):
        base = dict(
            name="Linen Cloth",
            quality=1,
            known=True,
            binding=BIND_NONE,
            quest_item=False,
            equipment=False,
            sell_price=10,
            reagent_for="tailoring",
        )
        base.update(kw)
        return Item(**base)

    def test_mats_for_a_profession_nobody_has_are_banked_not_carried(self):
        nobody = Family(vendor_reachable=True, bank_reachable=True, professions={})
        self.assertEqual(decide(self.cloth(), nobody, reagent_held=999).route, BANK)

    def test_without_a_bank_those_mats_are_still_never_sold(self):
        """The bank is a convenience. Its absence must not turn into a sale of
        something the family was keeping on purpose."""
        nobody = Family(vendor_reachable=True, bank_reachable=False, professions={})
        self.assertEqual(decide(self.cloth(), nobody, reagent_held=999).route, KEEP)

    def test_surplus_with_no_buyer_in_reach_goes_to_the_bank(self):
        field = Family(
            vendor_reachable=False,
            auction_reachable=False,
            bank_reachable=True,
            professions={"tailoring": 1},
        )
        self.assertEqual(decide(self.cloth(), field, reagent_held=500).route, BANK)

    def test_a_buyer_in_reach_still_beats_the_bank_for_true_surplus(self):
        """Banking surplus is hoarding with extra steps. If somebody will pay
        for it and the family cannot use it, take the money."""
        town = Family(
            vendor_reachable=True,
            auction_reachable=True,
            bank_reachable=True,
            professions={"tailoring": 1},
        )
        self.assertEqual(decide(self.cloth(), town, reagent_held=500).route, VENDOR)

    def test_cloth_the_tailor_is_using_stays_in_the_bags(self):
        """Banking something needed today is worse than carrying it: it costs a
        walk to get back."""
        town = Family(
            vendor_reachable=True, bank_reachable=True, professions={"tailoring": 1}
        )
        self.assertEqual(decide(self.cloth(), town, reagent_held=39).route, KEEP)

    def test_the_bank_is_never_offered_for_a_quest_item(self):
        town = Family(vendor_reachable=True, bank_reachable=True)
        it = Item(
            name="Gold Pickup Schedule",
            quality=1,
            known=True,
            quest_item=True,
            binding=BIND_ON_PICKUP,
        )
        self.assertEqual(decide(it, town).route, KEEP)


class OnlyRoutesSomethingCanActuallyCarryOut(unittest.TestCase):
    """A verdict nothing can execute is not a plan, it is a bag that never
    empties (infra#3330).

    Measured 2026-09-05: `overseer_command` has never held a single kind
    'auction' or kind 'bank' row, and there is no disenchant kind at all. So
    every AUCTION verdict this module has ever produced would have been a
    decision to keep the item forever, said in a way that looked like action.
    """

    def test_the_default_is_still_the_theoretical_answer(self):
        """Availability is the caller's fact, not this module's. Asked with no
        opinion about deployment, it answers as it always did."""
        it = green(auction_value=100000)
        self.assertEqual(decide(it, TOWN, character_level=28).route, AUCTION)

    def test_a_listing_verdict_is_withheld_when_nothing_can_list(self):
        it = green(auction_value=100000)
        verdict = decide(it, TOWN, character_level=28, available=EXECUTABLE_TODAY)
        self.assertNotEqual(verdict.route, AUCTION)

    def test_a_tradable_green_is_kept_rather_than_dumped_at_a_vendor(self):
        """The 111 bind-on-equip greens the family is carrying. Vendoring them
        because the auction executor is unfinished spends value that cannot be
        recovered, and several of them are the sibling-upgrade question
        (mod-overseer#189) rather than surplus at all."""
        it = green(binding=BIND_ON_EQUIP, auction_value=100000)
        self.assertEqual(
            decide(it, TOWN, character_level=28, available=EXECUTABLE_TODAY).route, KEEP
        )

    def test_an_outgrown_soulbound_piece_is_sold(self):
        """Nobody can ever wear, trade or list it, and Og cannot dust it. The
        vendor is the only truthful answer, and it is a real one."""
        it = green(binding=BIND_ON_PICKUP, required_level=15)
        self.assertEqual(
            decide(it, REAL, character_level=28, available=EXECUTABLE_TODAY).route,
            VENDOR,
        )

    def test_reaching_a_route_and_owning_a_route_are_different_facts(self):
        """An auctioneer out of walking range is a transient fact about today.
        A missing executor is a fact about the deployment. Only the second one
        may be answered by permanently giving the item away cheaply."""
        away = Family(vendor_reachable=True, auction_reachable=False)
        it = green(binding=BIND_ON_EQUIP, auction_value=100000)
        self.assertEqual(decide(it, away, character_level=28).route, VENDOR)
        self.assertEqual(
            decide(it, away, character_level=28, available=EXECUTABLE_TODAY).route, KEEP
        )

    def test_junk_is_still_sold_because_vendor_is_available(self):
        it = green(quality=0, binding=BIND_ON_PICKUP, sell_price=12)
        self.assertEqual(
            decide(it, REAL, character_level=28, available=EXECUTABLE_TODAY).route,
            VENDOR,
        )

    def test_with_no_routes_at_all_everything_is_kept(self):
        """Fail closed: an availability set nobody filled in must not become a
        licence to sell, and must not throw either."""
        for it in (
            green(quality=0, sell_price=12),
            green(binding=BIND_ON_PICKUP),
            green(auction_value=100000),
        ):
            self.assertEqual(
                decide(it, TOWN, character_level=28, available=frozenset()).route, KEEP
            )

    def test_the_bank_is_not_offered_until_something_writes_bank_rows(self):
        nobody = Family(vendor_reachable=True, bank_reachable=True, professions={})
        cloth = Item(
            name="Linen Cloth",
            quality=1,
            known=True,
            binding=BIND_NONE,
            quest_item=False,
            equipment=False,
            sell_price=10,
            reagent_for="tailoring",
        )
        self.assertEqual(decide(cloth, nobody, reagent_held=999).route, BANK)
        self.assertEqual(
            decide(cloth, nobody, reagent_held=999, available=EXECUTABLE_TODAY).route,
            KEEP,
        )

    def test_a_disenchant_verdict_is_withheld_while_no_executor_exists(self):
        able = Family(enchanting_skill=450, vendor_reachable=True)
        it = green(binding=BIND_ON_PICKUP, disenchant_skill_required=25)
        self.assertEqual(decide(it, able, character_level=28).route, DISENCHANT)
        self.assertEqual(
            decide(it, able, character_level=28, available=EXECUTABLE_TODAY).route,
            VENDOR,
        )

    def test_a_sibling_upgrade_is_kept_when_no_handover_route_is_open(self):
        it = green()
        self.assertEqual(
            decide(
                it,
                TOWN,
                character_level=28,
                upgrade_for_sibling=True,
                available=frozenset({VENDOR}),
            ).route,
            KEEP,
        )

    def test_turning_the_auction_on_is_one_name(self):
        """The point of a set rather than five more booleans."""
        it = green(auction_value=100000)
        self.assertEqual(
            decide(
                it, TOWN, character_level=28, available=EXECUTABLE_TODAY | {AUCTION}
            ).route,
            AUCTION,
        )


if __name__ == "__main__":
    unittest.main()
