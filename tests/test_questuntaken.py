"""Quests a holder could take for the quest items it carries (#2648)."""

import unittest

import questbook
import questuntaken as qu

HOLDER = questbook.Member(name="Grug", class_id=1, race_id=1, level=20)


def quest(quest_id: int, **kw) -> questbook.Quest:
    return questbook.Quest(id=quest_id, title=f"Quest {quest_id}", **kw)


def catalog(*quests) -> dict:
    return {q.id: q for q in quests}


class ItemQuests(unittest.TestCase):
    def test_required_drop_and_start_items_all_name_their_quest(self) -> None:
        rows = [
            {"ID": 10, "RequiredItemId1": 100, "RequiredItemId6": 106},
            {"ID": 11, "ItemDrop4": 200, "StartItem": 300},
            {"ID": 12, "RequiredItemId1": 100},
        ]
        got = qu.item_quests(rows)
        self.assertEqual(got[100], frozenset({10, 12}))
        self.assertEqual(got[106], frozenset({10}))
        self.assertEqual(got[200], frozenset({11}))
        self.assertEqual(got[300], frozenset({11}))

    def test_zero_and_missing_columns_name_nothing(self) -> None:
        got = qu.item_quests([{"ID": 10, "RequiredItemId1": 0, "ItemDrop1": None}])
        self.assertEqual(got, {})

    def test_a_row_without_an_id_is_ignored(self) -> None:
        self.assertEqual(qu.item_quests([{"RequiredItemId1": 5}]), {})


class UntakenFor(unittest.TestCase):
    naming = {100: frozenset({10}), 101: frozenset({10, 11}), 102: frozenset({12})}

    def run_for(self, member, carried, *quests) -> qu.Cover:
        return qu.untaken_for(member, carried, self.naming, catalog(*quests))

    def test_a_takable_quest_is_listed_with_the_items_that_name_it(self) -> None:
        cover = self.run_for(HOLDER, {100, 101}, quest(10), quest(11))
        self.assertEqual([u.quest_id for u in cover.quests], [10, 11])
        self.assertEqual(cover.quests[0].items, (100, 101))
        self.assertEqual(cover.quests[1].items, (101,))
        self.assertEqual(cover.items, frozenset({100, 101}))

    def test_a_quest_already_in_the_log_is_not_untaken(self) -> None:
        held = questbook.Member("Grug", 1, 1, 20, held=frozenset({10}))
        cover = self.run_for(held, {100}, quest(10))
        self.assertEqual(cover.quests, ())
        self.assertEqual(cover.refused, ())

    def test_a_rewarded_quest_is_dropped_not_refused(self) -> None:
        done = questbook.Member("Grug", 1, 1, 20, rewarded=frozenset({10}))
        cover = self.run_for(done, {100}, quest(10))
        self.assertEqual((cover.quests, cover.refused), ((), ()))

    def test_race_and_class_masks_close_a_quest_and_it_is_refused(self) -> None:
        # A human warrior against an orc-only and a mage-only quest.
        orc_only = quest(10, allowable_races=questbook.RACE_BIT[2])
        mage_only = quest(12, allowable_classes=questbook.CLASS_BIT[8])
        cover = self.run_for(HOLDER, {100, 102}, orc_only, mage_only)
        self.assertEqual(cover.quests, ())
        self.assertEqual(
            cover.refused,
            ((10, (questbook.RACE,)), (12, (questbook.CLASS,))),
        )
        self.assertEqual(cover.items, frozenset())

    def test_a_holder_below_the_level_window_is_not_sent(self) -> None:
        low = questbook.Member("Grug", 1, 1, 12)
        cover = self.run_for(low, {100}, quest(10, min_level=15))
        self.assertEqual(cover.quests, ())
        self.assertEqual(cover.refused, ((10, (questbook.TOO_LOW,)),))

    def test_a_holder_above_the_max_level_is_not_sent(self) -> None:
        cover = self.run_for(HOLDER, {100}, quest(10, max_level=19))
        self.assertEqual(cover.refused, ((10, (questbook.TOO_HIGH,)),))

    def test_an_unmet_prerequisite_is_refused(self) -> None:
        cover = self.run_for(HOLDER, {100}, quest(10, prev_quest_id=5))
        self.assertEqual(cover.refused, ((10, (questbook.PREREQUISITE,)),))

    def test_a_met_prerequisite_lets_the_quest_through(self) -> None:
        member = questbook.Member("Grug", 1, 1, 20, rewarded=frozenset({5}))
        cover = self.run_for(member, {100}, quest(10, prev_quest_id=5))
        self.assertEqual([u.quest_id for u in cover.quests], [10])

    def test_a_named_quest_missing_from_the_catalogue_is_skipped(self) -> None:
        cover = self.run_for(HOLDER, {100})
        self.assertEqual((cover.quests, cover.refused), ((), ()))

    def test_an_item_no_quest_names_covers_nothing(self) -> None:
        cover = self.run_for(HOLDER, {999}, quest(10))
        self.assertEqual(cover.quests, ())
        self.assertEqual(cover.items, frozenset())

    def test_an_item_stays_covered_when_one_of_its_quests_is_closed(self) -> None:
        closed = quest(10, allowable_races=questbook.RACE_BIT[2])
        cover = self.run_for(HOLDER, {101}, closed, quest(11))
        self.assertEqual(cover.items, frozenset({101}))
        self.assertEqual([u.quest_id for u in cover.quests], [11])

    def test_the_log_line_counts_items_takable_and_closed(self) -> None:
        closed = quest(12, allowable_races=questbook.RACE_BIT[2])
        cover = self.run_for(HOLDER, {100, 102}, quest(10), closed)
        self.assertEqual(
            qu.say(cover), "untaken quests: Grug 1 items covered, 1 takable, 1 closed"
        )


if __name__ == "__main__":
    unittest.main()
