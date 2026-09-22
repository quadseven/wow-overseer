"""The story of a notable item, as the Chronicle tells it (mod-overseer#567).

lootstory joins the module's item_loot, item_given and item_equip rows into
one sentence per item. These tests pin the three things that sentence has to
get right: which rows belong to one item, what each step is called
(including whether a hand-over was one a player could make), and that the
page is handed a finished sentence rather than parts to assemble.
"""

import unittest
from datetime import datetime, timedelta

import lootstory

T0 = datetime(2026, 9, 22, 12, 0, 0)
ZONES = {12: "Elwynn Forest", 1519: "Stormwind City", 618: "Winterspring"}


def row(kind, who, minutes, **extra):
    base = {
        "id": minutes,
        "character_name": who,
        "kind": kind,
        "subject_id": 647,
        "subject_name": "Destiny",
        "subject_quality": 4,
        "map": 0,
        "zone": 12,
        "item_guid": 9001,
        "counterpart": "",
        "via": "",
        "source": "",
        "first_seen": T0 + timedelta(minutes=minutes),
        "last_seen": T0 + timedelta(minutes=minutes),
        "guild": "Cave",
    }
    base.update(extra)
    return base


def destiny():
    return [
        row("item_loot", "Avenah", 0, via="loot", source="Defias Pillager"),
        row("item_given", "Avenah", 5, via="give", counterpart="Grog", zone=1519),
        row("item_equip", "Grog", 6),
    ]


class OneItemOneSentence(unittest.TestCase):
    def test_loot_hand_over_and_equip_are_one_story(self):
        payload = lootstory.build_loot(destiny(), ZONES)
        self.assertEqual(len(payload["stories"]), 1)
        story = payload["stories"][0]
        self.assertEqual(
            story["line"],
            "Avenah looted it from Defias Pillager in Elwynn Forest, then gave it to "
            "Grog by overseer command, then Grog equipped it.",
        )
        self.assertEqual(story["item"]["name"], "Destiny")
        self.assertEqual(story["item"]["quality"], 4)
        self.assertEqual(story["guild"], "Cave")
        self.assertEqual(story["at"], (T0 + timedelta(minutes=6)).isoformat())
        self.assertEqual(story["since"], T0.isoformat())

    def test_rows_arriving_newest_first_still_tell_it_in_order(self):
        payload = lootstory.build_loot(list(reversed(destiny())), ZONES)
        self.assertTrue(payload["stories"][0]["line"].startswith("Avenah looted it"))

    def test_two_copies_of_one_item_are_two_stories(self):
        rows = [
            row("item_loot", "Avenah", 0, via="loot"),
            row("item_loot", "Bork", 1, via="loot", item_guid=9002),
        ]
        self.assertEqual(len(lootstory.build_loot(rows, ZONES)["stories"]), 2)

    def test_newest_story_first(self):
        rows = [
            row("item_loot", "Avenah", 0, via="loot"),
            row("item_loot", "Bork", 30, via="loot", item_guid=9002),
        ]
        lines = [s["line"] for s in lootstory.build_loot(rows, ZONES)["stories"]]
        self.assertTrue(lines[0].startswith("Bork"))

    def test_repeated_equips_by_one_character_are_one_step(self):
        rows = [
            *destiny(),
            row("item_equip", "Grog", 70),
            row("item_equip", "Grog", 130),
        ]
        line = lootstory.build_loot(rows, ZONES)["stories"][0]["line"]
        self.assertEqual(line.count("equipped it"), 1)


class HowItMovedIsNamed(unittest.TestCase):
    def one(self, **given):
        rows = [
            row("item_loot", "Avenah", 0, via="loot", source="Defias Pillager"),
            row("item_given", "Avenah", 5, counterpart="Grog", **given),
        ]
        return lootstory.build_loot(rows, ZONES)["stories"][0]["line"]

    def test_a_trade_says_where(self):
        self.assertIn(
            "then traded it to Grog in Winterspring", self.one(via="trade", zone=618)
        )

    def test_a_letter_says_where_it_was_posted_from(self):
        self.assertIn(
            "then mailed it to Grog from Stormwind City",
            self.one(via="mail", zone=1519),
        )

    def test_a_module_give_is_not_dressed_as_a_trade(self):
        line = self.one(via="give")
        self.assertIn("gave it to Grog by overseer command", line)
        self.assertNotIn("traded", line)

    def test_a_roll_is_named_as_a_roll(self):
        rows = [
            row("item_loot", "Avenah", 0, via="need", source="Edwin VanCleef", map=36)
        ]
        line = lootstory.build_loot(rows, ZONES)["stories"][0]["line"]
        self.assertEqual(
            line, "Avenah won it on a need roll from Edwin VanCleef in The Deadmines."
        )

    def test_no_place_says_nothing_rather_than_map_zero(self):
        rows = [row("item_loot", "Avenah", 0, via="loot", zone=0, map=0)]
        line = lootstory.build_loot(rows, ZONES)["stories"][0]["line"]
        self.assertEqual(line, "Avenah looted it.")


class WithoutAGuid(unittest.TestCase):
    """Rows written before the module recorded guids, or from a database that
    has not applied the migration, join by entry and the current holder."""

    def test_an_equip_without_a_guid_joins_the_holders_story(self):
        rows = [*destiny()[:2], row("item_equip", "Grog", 6, item_guid=0)]
        payload = lootstory.build_loot(rows, ZONES)
        self.assertEqual(len(payload["stories"]), 1)
        self.assertTrue(
            payload["stories"][0]["line"].endswith("then Grog equipped it.")
        )

    def test_it_never_joins_somebody_elses_copy(self):
        rows = [*destiny()[:2], row("item_equip", "Bork", 6, item_guid=0)]
        self.assertEqual(len(lootstory.build_loot(rows, ZONES)["stories"]), 2)

    def test_the_fallback_read_without_story_columns_still_renders(self):
        bare = [
            {
                k: v
                for k, v in r.items()
                if k not in ("item_guid", "counterpart", "via", "source")
            }
            for r in destiny()
        ]
        payload = lootstory.build_loot(bare, ZONES)
        self.assertTrue(payload["stories"])


class WhatIsLeftOut(unittest.TestCase):
    def test_below_rare_is_not_a_story(self):
        rows = [row("item_equip", "Grog", 0, subject_quality=2)]
        self.assertEqual(lootstory.build_loot(rows, ZONES)["stories"], [])

    def test_other_kinds_are_ignored(self):
        rows = [row("quest_reward", "Grog", 0)]
        self.assertEqual(lootstory.build_loot(rows, ZONES)["stories"], [])

    def test_the_list_is_bounded_and_says_how_many_more(self):
        rows = [
            row("item_loot", "Avenah", i, via="loot", item_guid=100 + i)
            for i in range(5)
        ]
        payload = lootstory.build_loot(rows, ZONES, limit=3)
        self.assertEqual(len(payload["stories"]), 3)
        self.assertEqual(payload["more"], 2)

    def test_the_empty_and_basis_sentences_are_the_modules(self):
        payload = lootstory.build_loot([], ZONES)
        self.assertEqual(payload["empty"], lootstory.EMPTY)
        self.assertEqual(payload["basis"], lootstory.BASIS)

    def test_the_world_databases_name_wins_when_it_answers(self):
        items = {647: {"entry": 647, "name": "Destiny", "quality": 4, "item_level": 57}}
        payload = lootstory.build_loot(destiny(), ZONES, items=items)
        self.assertEqual(payload["stories"][0]["item"]["quality_name"], "epic")

    def test_the_wanted_entries_are_the_story_items(self):
        self.assertEqual(lootstory.wanted_entries(destiny()), [647])


if __name__ == "__main__":
    unittest.main()
