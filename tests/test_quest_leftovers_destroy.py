"""Quest-class leftovers: finish the quest, or destroy what is certainly useless (#2607).

Measured on the dev realm on 2026-11-15 over the 2,126 quest-class stacks the
two guilds carry: 856 are named by a quest in the holder's log, 860 by a quest
the holder has not taken yet and could (180 quests), 15 by a quest it is too
low for, 79 only by quests already rewarded or closed to its race, and 316 by
no quest at all, of which 247 are Darkmoon cards. The old sale test counted
only the log, so the 860 looked like leftovers and could be sold or destroyed.

The rule now: an item a quest the holder could still take names stays (go and
finish it); an unpriced common leftover that no quest names, or whose quests
are all done or closed, is destroyed with its reason. A Darkmoon card stays
only when its holder or a family member has its deck's Ace or four other
cards; every other tradable card lists on the real auction house, then falls
back to the vendor after two failed listings. Decks and trinkets stay.
"""

from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import bag_pressure  # noqa: E402
import guildjobs  # noqa: E402
import itemplan  # noqa: E402
import itemplan_vendor  # noqa: E402
import itemplan_shadow as shadow  # noqa: E402
import seatbags  # noqa: E402
from itemplan import (  # noqa: E402
    AUCTION,
    BANK_PERSONAL,
    DESTROY,
    KEEP_CARRY,
    SELL_VENDOR,
    Context,
)
from test_guild_seat_bags import SEAT, extras_for, row, seat  # noqa: E402
from test_guildjobs import only_step, plan  # noqa: E402
from test_itemplan import member, one, stack  # noqa: E402

LOG_READ = Context(open_quest_items={"Ana": frozenset()}, fire_gear=frozenset())


def quest_stack(entry=700, name="Torn Page", quality=1, sell=0, needed=False, **kw):
    return stack(
        entry=entry,
        name=name,
        item_class=itemplan.C_QUEST,
        quality=quality,
        sell=sell,
        bind=0,
        quest_needed=needed,
        **kw,
    )


class TheNeededTestSeesQuestsNotYetTaken(unittest.TestCase):
    def test_the_shared_test_keeps_what_an_untaken_quest_names(self):
        sql = bag_pressure.STACK_QUEST_NEEDED_SQL
        self.assertIn("qt2.AllowableRaces", sql)
        self.assertIn("character_queststatus_rewarded", sql)
        self.assertIn("characters", sql)
        for column in ("RequiredItemId1", "RequiredItemId6", "ItemDrop4", "StartItem"):
            self.assertGreaterEqual(sql.count(column), 2, column)

    def test_it_still_reads_the_log(self):
        self.assertIn("character_queststatus qs", bag_pressure.STACK_QUEST_NEEDED_SQL)


class DarkmoonCardsFollowTheDeckThreshold(unittest.TestCase):
    NAMES = (
        "Two of Beasts",
        "Eight of Portals",
        "Ace of Warlords",
        "Four of Elementals",
        "Beasts Deck",
        "Warlords Deck",
        "Darkmoon Card: Heroism",
    )

    def test_the_names_are_recognised(self):
        for name in self.NAMES:
            self.assertTrue(bag_pressure.is_darkmoon(name), name)
        for name in ("Torn Page", "Two of Hearts", "Deck of Cards", ""):
            self.assertFalse(bag_pressure.is_darkmoon(name), name)

    def card(self, name, entry, holder="Ana", count=1, sell=12_500):
        return quest_stack(
            entry=entry,
            name=name,
            holder=holder,
            count=count,
            quality=2,
            sell=sell,
            needed=False,
        )

    def test_an_ace_is_kept(self):
        ace = self.card("Ace of Beasts", 800)
        d = one([ace], [member()], ace, LOG_READ)
        self.assertIn(d.route, (BANK_PERSONAL, KEEP_CARRY))

    def test_a_holder_keeps_a_card_when_they_hold_its_decks_ace(self):
        target = self.card("Two of Beasts", 801)
        ace = self.card("Ace of Beasts", 802)
        d = one([target, ace], [member()], target, LOG_READ)
        self.assertIn(d.route, (BANK_PERSONAL, KEEP_CARRY))

    def test_a_family_member_holding_the_ace_keeps_the_card(self):
        target = self.card("Two of Beasts", 803)
        ace = self.card("Ace of Beasts", 804, holder="Bo")
        d = one([target, ace], [member(), member("Bo")], target, LOG_READ)
        self.assertIn(d.route, (BANK_PERSONAL, KEEP_CARRY))

    def test_four_other_cards_of_the_same_deck_are_enough(self):
        target = self.card("Two of Beasts", 805)
        others = [
            self.card(name, 806 + n)
            for n, name in enumerate(
                ("Four of Beasts", "Five of Beasts", "Six of Beasts", "Seven of Beasts")
            )
        ]
        d = one([target, *others], [member()], target, LOG_READ)
        self.assertIn(d.route, (BANK_PERSONAL, KEEP_CARRY))

    def test_a_family_member_with_four_other_cards_keeps_the_card(self):
        target = self.card("Two of Beasts", 808)
        others = [
            self.card(name, 809 + n, holder="Bo")
            for n, name in enumerate(
                ("Four of Beasts", "Five of Beasts", "Six of Beasts", "Seven of Beasts")
            )
        ]
        d = one([target, *others], [member(), member("Bo")], target, LOG_READ)
        self.assertIn(d.route, (BANK_PERSONAL, KEEP_CARRY))

    def test_each_non_ace_card_without_a_family_set_is_listed_not_destroyed(self):
        for suit in ("Beasts", "Elementals", "Portals", "Warlords"):
            for rank in ("Two", "Three", "Four", "Five", "Six", "Seven", "Eight"):
                with self.subTest(card=f"{rank} of {suit}"):
                    card = self.card(f"{rank} of {suit}", 850)
                    d = one([card], [member()], card, LOG_READ)
                    self.assertEqual(d.route, AUCTION)
                    self.assertNotEqual(d.route, DESTROY)

    def test_copies_of_the_same_card_are_not_other_cards(self):
        target = self.card("Two of Beasts", 840, count=5)
        d = one([target], [member()], target, LOG_READ)
        self.assertEqual(d.route, AUCTION)

    def test_a_second_stack_of_the_same_card_is_not_another_card(self):
        target = self.card("Two of Beasts", 841, count=3)
        twin = self.card("Two of Beasts", 842, count=3)
        d = one([target, twin], [member()], target, LOG_READ)
        self.assertEqual(d.route, AUCTION)

    def test_cards_from_a_different_deck_do_not_count(self):
        target = self.card("Two of Beasts", 809)
        others = [
            self.card(name, 810 + n)
            for n, name in enumerate(
                (
                    "Ace of Portals",
                    "Four of Portals",
                    "Five of Portals",
                    "Six of Portals",
                    "Seven of Portals",
                )
            )
        ]
        d = one([target, *others], [member()], target, LOG_READ)
        self.assertEqual(d.route, AUCTION)

    def test_three_other_cards_are_listed_at_the_vendor_quote(self):
        target = self.card("Two of Beasts", 810)
        others = [
            self.card(name, 811 + n)
            for n, name in enumerate(
                ("Four of Beasts", "Five of Beasts", "Six of Beasts")
            )
        ]
        d = one([target, *others], [member()], target, LOG_READ)
        self.assertEqual((d.route, d.target), (AUCTION, itemplan.LIST_AT_VENDOR_QUOTE))

    def test_four_other_ranks_split_across_two_members_keep_the_card(self):
        target = self.card("Two of Beasts", 820)
        ana = [
            self.card(name, 821 + n)
            for n, name in enumerate(("Four of Beasts", "Five of Beasts"))
        ]
        bo = [
            self.card(name, 825 + n, holder="Bo")
            for n, name in enumerate(("Six of Beasts", "Seven of Beasts"))
        ]
        d = one([target, *ana, *bo], [member(), member("Bo")], target, LOG_READ)
        self.assertIn(d.route, (BANK_PERSONAL, KEEP_CARRY))

    def test_split_ranks_of_another_family_do_not_count(self):
        target = self.card("Two of Beasts", 830)
        ana = self.card("Four of Beasts", 831)
        bo = [
            self.card(name, 832 + n, holder="Bo")
            for n, name in enumerate(
                ("Five of Beasts", "Six of Beasts", "Seven of Beasts")
            )
        ]
        d = one(
            [target, ana, *bo],
            [member(), member("Bo", family="Other")],
            target,
            LOG_READ,
        )
        self.assertEqual(d.route, AUCTION)

    def test_an_emptied_stack_does_not_count_as_a_card(self):
        target = self.card("Two of Beasts", 835)
        held = [
            self.card(name, 836 + n)
            for n, name in enumerate(
                ("Four of Beasts", "Five of Beasts", "Six of Beasts")
            )
        ]
        empty = self.card("Seven of Beasts", 840, count=0)
        d = one([target, *held, empty], [member()], target, LOG_READ)
        self.assertEqual(d.route, AUCTION)

    def test_an_emptied_ace_stack_does_not_keep_the_card(self):
        target = self.card("Two of Beasts", 845)
        ace = self.card("Ace of Beasts", 846, count=0)
        d = one([target, ace], [member()], target, LOG_READ)
        self.assertEqual(d.route, AUCTION)

    def test_one_failed_listing_still_lists_but_two_choose_vendor_fallback(self):
        target = self.card("Two of Beasts", 830)
        rows = [target]
        members = [member()]
        once = Context(
            open_quest_items={"Ana": frozenset()},
            fire_gear=frozenset(),
            failed_listings={("Ana", target.entry): 1},
        )
        twice = Context(
            open_quest_items={"Ana": frozenset()},
            fire_gear=frozenset(),
            failed_listings={("Ana", target.entry): 2},
        )
        self.assertEqual(one(rows, members, target, once).route, AUCTION)
        self.assertEqual(one(rows, members, target, twice).route, SELL_VENDOR)

    def test_the_itemplan_vendor_route_carries_out_a_card_after_two_failures(self):
        target = self.card("Two of Beasts", 835, sell=1_000)
        ctx = Context(
            open_quest_items={"Ana": frozenset()},
            fire_gear=frozenset(),
            failed_listings={("Ana", target.entry): 2},
        )
        plan = itemplan.plan([target], [member()], ctx)
        row = {
            "holder": "Ana",
            "entry": target.entry,
            "item_guid": 835,
            "name": target.name,
            "quality": target.quality,
            "count": target.count,
            "sell_price": target.sell,
            "item_class": itemplan.C_QUEST,
            "quest_item": False,
            "reagent": False,
            "profession_needed": False,
        }
        sales = itemplan_vendor.sales_for(plan, [(target, row)])
        self.assertEqual([sale.candidate.item_guid for sale in sales], [835])

    def test_the_plan_never_sells_lists_or_destroys_one(self):
        # A deck or a finished card trinket: the threshold governs loose cards
        # only, so these are never sold, listed or destroyed.
        for name in ("Beasts Deck", "Warlords Deck", "Darkmoon Card: Heroism"):
            item = self.card(name, 840)
            d = one([item], [member()], item, LOG_READ)
            self.assertIn(d.route, (BANK_PERSONAL, KEEP_CARRY), name)
            self.assertNotIn(d.route, (SELL_VENDOR, AUCTION, DESTROY), name)

    def test_the_vendor_pass_refuses_one_even_when_no_quest_names_it(self):
        r = row(1, 800, "Three of Beasts", quality=3, sell=12_500, item_class=12)
        r["quest_item"] = False
        self.assertEqual(bag_pressure.vendor_candidates([r]), ())
        self.assertTrue(bag_pressure.vendor_refusal(r))

    def test_the_destroy_pass_skips_one_even_at_no_price(self):
        r = row(1, 800, "Three of Beasts", quality=1, sell=0, item_class=12)
        r["quest_item"] = False
        self.assertEqual(bag_pressure.destroy_candidates([r]), ())


class AUselessLeftoverIsDestroyed(unittest.TestCase):
    def test_an_unpriced_common_leftover_no_quest_names_is_destroyed(self):
        s = quest_stack()
        d = one([s], [member()], s, LOG_READ)
        self.assertEqual(d.route, DESTROY)
        self.assertIn("no quest", d.reason)

    def test_an_item_a_quest_could_still_take_is_kept(self):
        s = quest_stack(needed=True)
        d = one([s], [member()], s, LOG_READ)
        self.assertNotIn(d.route, (DESTROY, SELL_VENDOR))

    def test_a_priced_leftover_is_not_destroyed(self):
        s = quest_stack(sell=40)
        d = one([s], [member()], s, LOG_READ)
        self.assertNotEqual(d.route, DESTROY)

    def test_nothing_above_common_is_destroyed(self):
        s = quest_stack(quality=2)
        d = one([s], [member()], s, LOG_READ)
        self.assertNotEqual(d.route, DESTROY)

    def test_an_unread_quest_log_destroys_nothing(self):
        s = quest_stack()
        d = one([s], [member()], s, Context(fire_gear=frozenset()))
        self.assertNotEqual(d.route, DESTROY)

    def test_a_key_is_never_destroyed(self):
        k = stack(entry=950, name="Skeleton Key", item_class=itemplan.C_KEY, sell=0)
        d = one([k], [member()], k, LOG_READ)
        self.assertNotEqual(d.route, DESTROY)

    def test_an_open_quest_item_is_kept(self):
        s = quest_stack(entry=701)
        ctx = Context(open_quest_items={"Ana": frozenset({701})}, fire_gear=frozenset())
        d = one([s], [member()], s, ctx)
        self.assertEqual(d.route, KEEP_CARRY)

    def test_the_row_flag_reaches_the_stack(self):
        r = row(5, 710, "Torn Page", sell=0, item_class=12)
        r["quest_item"] = False
        (built,) = shadow.build_stacks([r])
        self.assertFalse(built.quest_needed)
        r2 = dict(r, quest_item=True)
        (built2,) = shadow.build_stacks([r2])
        self.assertTrue(built2.quest_needed)
        (unknown,) = shadow.build_stacks(
            [{k: v for k, v in r.items() if k != "quest_item"}]
        )
        self.assertIsNone(unknown.quest_needed)


class ASeatDestroysItsLeftovers(unittest.TestCase):
    def rows(self):
        gone = row(2, 200, "Torn Page", sell=0, item_class=12)
        gone["quest_item"] = False
        kept = row(3, 201, "Folded Map", sell=0, item_class=12)
        kept["quest_item"] = True
        card = row(4, 202, "Two of Beasts", quality=3, sell=12_500, item_class=12)
        card["quest_item"] = False
        return [gone, kept, card]

    def test_the_plan_names_the_destroys_for_the_seat(self):
        rows = self.rows()
        got = seatbags.plan_for([SEAT], "Cave", rows, {SEAT: 2}, extras_for(rows))
        self.assertEqual([c.guid for c in got.destroys[SEAT]], [2])
        self.assertIn("destroys 1", got.lines[0])

    def test_the_step_destroys_through_the_world_verb_with_its_reason(self):
        m = seat(
            plan_destroy=(
                guildjobs.Carried(
                    guid=2, entry=200, count=3, item_class=12, name="Torn Page"
                ),
            )
        )
        step = only_step(plan([m]), SEAT)
        self.assertEqual(step.action, guildjobs.SEAT_DESTROY_ACTION)
        self.assertEqual(
            [(r.kind, r.command) for r in step.rows],
            [("sell", "destroy guid:2 count:3")],
        )
        self.assertIsNone(step.walk)
        self.assertIn("Torn Page", step.said)
        self.assertIn("no quest", step.said)

    def test_a_seat_with_room_destroys_nothing(self):
        m = seat(
            free_slots=30,
            plan_destroy=(guildjobs.Carried(guid=2, entry=200, item_class=12),),
        )
        step = only_step(plan([m]), SEAT)
        self.assertNotEqual(getattr(step, "action", ""), guildjobs.SEAT_DESTROY_ACTION)


if __name__ == "__main__":
    unittest.main()


class ANeededQuestItemIsNeverASaleWhenTheBankIsFull(unittest.TestCase):
    """Measured on the dev realm on 2026-11-15: with the personal bank full, a
    stack a quest could still take fell through to the vendor as a fallback
    ("quest-class leftover with a price"), and the pressure release sold the
    cheapest first. The owner's rule is that a quest item is never sold."""

    FULL_BANK = dict(bank_slots=itemplan.BANK_RESERVE)

    def test_a_priced_needed_stack_is_not_sold_listed_or_destroyed(self):
        s = quest_stack(entry=702, name="Scrap", sell=200, needed=True)
        d = one([s], [member(**self.FULL_BANK)], s, LOG_READ)
        self.assertNotIn(d.route, (SELL_VENDOR, AUCTION, DESTROY))
        self.assertNotIn(SELL_VENDOR, d.options)

    def test_a_leftover_no_quest_names_may_still_go_to_the_vendor(self):
        s = quest_stack(entry=703, name="Dead Page", sell=200, needed=False)
        d = one([s], [member(**self.FULL_BANK)], s, LOG_READ)
        self.assertEqual(d.route, SELL_VENDOR)
