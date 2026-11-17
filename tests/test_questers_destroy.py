"""A quester whose bags are full of quest leftovers destroys them (#1813).

The sale sends a quester to a vendor for what a vendor buys, but a quest
leftover has no price: a stack of an item whose quest was handed in or dropped
stays in the bags for ever and no sale reaches it, so a quester full of them
cannot make room for the next take. This mirrors the raid seats' rule (#2607,
guildjobs._seat_destroy_step): destroy a quest-class stack that no quest the
quester is on or could still take names, with no vendor price and common
quality. Never an epic, never an item a quest in its log or one it has not yet
done names (the quest-log hold), never a Darkmoon card, never a stack
reserved in overseer_keep. No walk and no vendor: the world's destroy verb
re-checks the quest log itself."""

import types
import unittest

import guildjobs
import keep
import questers
from test_questers import ELWYNN, giver, quest, world
from test_questers_sell import GREY, QUEST, kept, quester, stack

LEFTOVER = stack(10, 700, QUEST, price=0, quest_needed=False)
LEFTOVER_B = stack(11, 701, QUEST, price=0, count=3, quest_needed=False)
NEEDED = stack(12, 702, QUEST, price=0)  # quest_needed defaults to True
PRICED = stack(13, 703, QUEST, price=20, quest_needed=False)
EPIC = stack(14, 704, QUEST, quality=4, price=0, quest_needed=False)
CARD = guildjobs.Carried(
    guid=15,
    entry=705,
    item_class=QUEST,
    quality=1,
    sell_price=0,
    name="Ace of Beasts",
    quest_needed=False,
)
NAMED_BY_OPEN_QUEST = stack(16, 706, QUEST, price=0, quest_needed=False)
NAMED_BY_UNDONE_QUEST = stack(17, 707, QUEST, price=0, quest_needed=False)
DONE_QUEST_ITEM = stack(18, 708, QUEST, price=0, quest_needed=False)


def catalogue():
    open_quest = dict(quest(41, ELWYNN, 4, title="Open one"), item1=706, item_count1=1)
    undone = dict(quest(42, ELWYNN, 4, title="Not yet"), item1=707, item_count1=1)
    done = dict(quest(43, ELWYNN, 4, title="Handed in"), item1=708, item_count1=1)
    return world(
        extra_quests=[open_quest, undone, done],
        extra_givers=[
            giver(q, kind, 1040 + q, 140, 50, 0)
            for q in (41, 42, 43)
            for kind in ("start", "end")
        ],
    )


def member(**kw):
    base = dict(
        quest_log={41: questers.STATUS_INCOMPLETE},
        quests_done=frozenset({43}),
    )
    base.update(kw)
    return quester(**base)


def destroy(who, carried, recent=(), reservations=None, tried=()):
    return questers.destroy_step(
        who,
        carried,
        reservations if reservations is not None else kept(),
        catalogue(),
        recent,
        tried,
    )


def rows(step):
    return [r.command for r in step.rows]


class AFullQuesterDestroysItsLeftovers(unittest.TestCase):
    def test_zero_price_leftovers_no_quest_names_are_destroyed_and_free_slots(self):
        step = destroy(member(), (LEFTOVER, LEFTOVER_B, GREY))
        self.assertIsNotNone(step)
        self.assertEqual(step.action, questers.DESTROY_ACTION)
        self.assertEqual(
            rows(step), ["destroy guid:10 count:1", "destroy guid:11 count:3"]
        )
        self.assertTrue(all(r.kind == "sell" for r in step.rows))
        self.assertIsNone(step.walk)
        self.assertEqual(
            {guildjobs.action_of(r.source) for r in step.rows},
            {questers.DESTROY_ACTION},
        )

    def test_a_done_quests_item_is_a_leftover(self):
        self.assertEqual(
            rows(destroy(member(), (DONE_QUEST_ITEM,))), ["destroy guid:18 count:1"]
        )

    def test_a_quester_with_room_destroys_nothing(self):
        self.assertIsNone(
            destroy(member(free_slots=questers.SELL_FLOOR + 1), (LEFTOVER,))
        )

    def test_unread_bags_destroy_nothing(self):
        self.assertIsNone(destroy(member(free_slots=None), (LEFTOVER,)))

    def test_an_offline_dead_or_unplaced_quester_destroys_nothing(self):
        for who in (member(online=False), member(alive=False), member(map_id=None)):
            self.assertIsNone(destroy(who, (LEFTOVER,)), who)

    def test_a_destroy_just_asked_is_not_asked_again(self):
        source = guildjobs.source_for(questers.DESTROY_ACTION, "Mirra")
        young = types.SimpleNamespace(
            name="Mirra",
            action=questers.DESTROY_ACTION,
            age_minutes=5,
            source=source,
        )
        self.assertIsNone(destroy(member(), (LEFTOVER,), recent=(young,)))
        old = types.SimpleNamespace(
            name="Mirra",
            action=questers.DESTROY_ACTION,
            age_minutes=questers.SELL_COOLDOWN_MINUTES,
            source=source,
        )
        self.assertIsNotNone(destroy(member(), (LEFTOVER,), recent=(old,)))


class WhatItNeverDestroys(unittest.TestCase):
    def test_needed_priced_epic_card_open_undone_and_reserved_stay(self):
        reserved = stack(19, 709, QUEST, price=0, quest_needed=False)
        reservations = keep.from_rows(
            [{"character_name": "Mirra", "item_guid": 19, "item_entry": 709}]
        )
        step = destroy(
            member(),
            (
                LEFTOVER,
                NEEDED,
                PRICED,
                EPIC,
                CARD,
                NAMED_BY_OPEN_QUEST,
                NAMED_BY_UNDONE_QUEST,
                reserved,
            ),
            reservations=reservations,
        )
        self.assertEqual(rows(step), ["destroy guid:10 count:1"])

    def test_nothing_to_destroy_sends_nobody(self):
        self.assertIsNone(destroy(member(), (NEEDED, PRICED, EPIC, CARD, GREY)))

    def test_unread_reservations_destroy_nothing(self):
        self.assertIsNone(
            questers.destroy_step(member(), (LEFTOVER,), None, catalogue(), (), ())
        )

    def test_at_most_the_sale_limit_goes_at_once(self):
        many = tuple(
            stack(100 + i, 800 + i, QUEST, price=0, quest_needed=False)
            for i in range(guildjobs.MAX_SALES + 5)
        )
        self.assertEqual(len(destroy(member(), many).rows), guildjobs.MAX_SALES)


class TheBridgeDestroysBeforeItSells(unittest.TestCase):
    def test_a_full_quester_with_leftovers_destroys_in_place_of_its_take(self):
        from test_questers_sell import run_pass

        run, asked = run_pass(quester(level=2, x=0.0, free_slots=0), (LEFTOVER, GREY))
        self.assertEqual(asked, [["Mirra"]])
        (step,) = run.started
        self.assertEqual(step.action, questers.DESTROY_ACTION)
        self.assertEqual(rows(step), ["destroy guid:10 count:1"])

    def test_with_no_leftover_the_sale_still_goes(self):
        from test_questers_sell import run_pass

        run, _asked = run_pass(quester(level=2, x=0.0, free_slots=0), (GREY,))
        (step,) = run.started
        self.assertEqual(step.action, questers.SELL_ACTION)


class TheLeftoverRead(unittest.TestCase):
    def test_the_read_is_zero_price_common_quest_class_with_the_quest_test(self):
        from test_guildsocial_bridge import bridge

        sql = bridge._QUESTER_LEFTOVERS_SQL
        self.assertIn("it.class = 12", sql)
        self.assertIn("it.SellPrice = 0", sql)
        self.assertIn("it.Quality <= 1", sql)
        self.assertIn("AS quest_needed", sql)
        self.assertIn("{guids}", sql)
        self.assertIn("ci.slot BETWEEN 23 AND 38", sql)
        self.assertNotIn("{goods}", sql)


if __name__ == "__main__":
    unittest.main()
