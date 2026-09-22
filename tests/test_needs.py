"""What the five need, judged with no database and no browser (infra#2597).

Every assertion here is about a DECISION - a threshold, a state word, which of
four problems is the problem, and the sentence that says so. All of it used to
be the kind of thing that ends up as a ternary in a template, and the reason it
must not is that a page and a module disagreeing about what 39% durability
means would render a perfectly plausible bar while being wrong.

The bars are also asserted to agree about which END is good. That reads like a
style rule and is not: "bags 100%" meaning full-and-bad beside "repair 100%"
meaning intact-and-fine is two charts sharing a grid, and a reader has to learn
each row separately.
"""

import json
import unittest

import bonds
import family
import materials
import needs
import wealth


def item(name, bag, slot, guid, count=1, item_name=None, cslots=0):
    """One character_inventory row in the shape the adapter selects."""
    return {
        "name": name,
        "bag": bag,
        "slot": slot,
        "item_guid": guid,
        "entry": 2589,
        "count": count,
        "item_name": item_name,
        "quality": 1,
        "item_level": 5,
        "sell_price": 10,
        "class": 7,
        "subclass": 5,
        "displayid": 1,
        "container_slots": cslots,
    }


def backpack(name, used, *, material=None, first_guid=1000):
    """`used` of the sixteen built-in backpack slots, filled."""
    return [
        item(name, 0, 23 + i, first_guid + i, count=19, item_name=material)
        for i in range(used)
    ]


def worn(name, durability, maximum=100, slots=5):
    return [
        {"name": name, "slot": s, "durability": durability, "max_durability": maximum}
        for s in range(slots)
    ]


def bars_for(members, key):
    return {
        m["name"]: next(b for b in m["needs"] if b["key"] == key)
        for m in members
        if m["present"]
    }


def build(char_rows=None, inventory=(), equipment=(), skills=(), gives=(), thoughts=()):
    roster = family.roster()
    if char_rows is None:
        char_rows = [{"name": n, "money": 15000000} for n in roster]
    return needs.build_needs(
        list(char_rows),
        list(inventory),
        list(equipment),
        list(skills),
        list(gives),
        list(thoughts),
    )


class TheCoinIsSaidTheWayTheGameWritesIt(unittest.TestCase):
    def test_the_three_units_in_order(self):
        self.assertEqual(needs.coin_words(wealth.coins(1420651)), "142g 6s 51c")

    def test_a_unit_with_nothing_in_it_is_dropped(self):
        self.assertEqual(needs.coin_words(wealth.coins(1500000)), "150g")

    def test_an_empty_purse_is_a_word_and_not_a_zero(self):
        """ "0c" reads as a rendering artefact. A character with an empty purse
        has nothing, and that is what a reader is looking for."""
        self.assertEqual(needs.coin_words(wealth.coins(0)), "nothing")


class EveryBarIsFullWhenTheNeedIsMet(unittest.TestCase):
    """The rule that makes four bars one panel rather than four charts."""

    def test_empty_bags_read_full_and_full_bags_read_empty(self):
        roomy = build(inventory=backpack("Grug", 0))
        packed = build(inventory=backpack("Grug", 16))
        self.assertEqual(bars_for(roomy["members"], needs.BAGS)["Grug"]["pct"], 100)
        self.assertEqual(bars_for(packed["members"], needs.BAGS)["Grug"]["pct"], 0)

    def test_intact_gear_reads_full_and_broken_gear_reads_empty(self):
        intact = build(equipment=worn("Grug", 100))
        broken = build(equipment=worn("Grug", 0))
        self.assertEqual(bars_for(intact["members"], needs.REPAIR)["Grug"]["pct"], 100)
        self.assertEqual(bars_for(broken["members"], needs.REPAIR)["Grug"]["pct"], 0)

    def test_a_purse_over_the_floor_reads_full_rather_than_off_the_end(self):
        """The family holds 140 to 170 gold each. A bar that ran to a wealth
        target would peg at 1400% and say nothing."""
        rich = build(
            char_rows=[
                {"name": n, "money": needs.THIN_COPPER * 40} for n in family.roster()
            ]
        )
        self.assertEqual(bars_for(rich["members"], needs.COIN)["Grug"]["pct"], 100)


class TheDurabilityThresholds(unittest.TestCase):
    """Red under 40, amber under 75. The design's numbers, and the game's."""

    def state(self, durability):
        payload = build(equipment=worn("Grug", durability))
        return bars_for(payload["members"], needs.REPAIR)["Grug"]["state"]

    def test_below_forty_is_the_warning(self):
        self.assertEqual(self.state(needs.REPAIR_BROKEN_PCT - 1), needs.WARN)

    def test_exactly_forty_is_a_caution_and_not_a_warning(self):
        """An off-by-one here is the difference between a card that shouts at
        a perfectly ordinary set of gear and one that never shouts at all."""
        self.assertEqual(self.state(needs.REPAIR_BROKEN_PCT), needs.CAUTION)

    def test_below_seventy_five_is_the_caution(self):
        self.assertEqual(self.state(needs.REPAIR_WORN_PCT - 1), needs.CAUTION)

    def test_at_seventy_five_it_stops_saying_anything(self):
        self.assertEqual(self.state(needs.REPAIR_WORN_PCT), needs.FINE)

    def test_it_is_the_repair_bill_and_not_the_average_item(self):
        """One item at 5% among fifteen at 100% is a cheap trip; averaging per
        item would report the same number as fifteen at 94%, which is not the
        same trip at all."""
        gear = [{"name": "Grug", "slot": 0, "durability": 5, "max_durability": 1000}]
        gear += [
            {"name": "Grug", "slot": s, "durability": 100, "max_durability": 100}
            for s in range(1, 16)
        ]
        self.assertEqual(needs._repair_pct(gear), 60)

    def test_an_item_that_cannot_break_is_not_an_item_at_zero(self):
        """Rings, cloaks, necks and trinkets have no durability at all, so a
        stored 0 there is not damage. Counting them would report a family in
        rags forever."""
        rings = [
            {"name": "Og", "slot": s, "durability": 0, "max_durability": 0}
            for s in range(4)
        ]
        self.assertIsNone(needs._repair_pct(rings))
        bar = bars_for(build(equipment=rings)["members"], needs.REPAIR)["Og"]
        self.assertIsNone(bar["pct"])
        self.assertEqual(bar["state"], needs.FINE)
        self.assertNotIn("%", bar["value"])


class TheBagThresholds(unittest.TestCase):
    def bar(self, used, key=None):
        payload = build(inventory=backpack("Grug", used))
        return bars_for(payload["members"], key or needs.BAGS)["Grug"]

    def test_no_room_at_all_is_the_warning(self):
        self.assertEqual(self.bar(16)["state"], needs.WARN)

    def test_a_loot_or_two_from_none_is_the_caution(self):
        self.assertEqual(self.bar(16 - needs.ROOM_TIGHT_SLOTS)["state"], needs.CAUTION)

    def test_room_to_spare_says_nothing(self):
        self.assertEqual(self.bar(0)["state"], needs.FINE)

    def test_no_inventory_rows_is_an_empty_backpack_and_never_a_full_one(self):
        """Every character is born with the sixteen-slot backpack, so a member
        with no rows has an EMPTY one. Reading that as full would be the worst
        available lie about somebody nobody has data for - a card shouting
        "no room left" at a character who has all of it."""
        bar = bars_for(build()["members"], needs.BAGS)["Grug"]
        self.assertEqual(bar["pct"], 100)
        self.assertEqual(bar["state"], needs.FINE)
        self.assertIn(str(wealth.BACKPACK_SLOTS), bar["value"])


class TheBagPositionsAreADifferentComplaint(unittest.TestCase):
    """wealth.build_capacity says it in one line: three empty bag slots on a
    character with nothing to put in them is a different problem from four full
    bags, and the two want different answers."""

    def positions(self, inventory):
        payload = build(inventory=inventory)
        return bars_for(payload["members"], needs.BAG_POSITIONS)["Grug"]

    def test_an_empty_position_with_full_bags_is_the_actionable_one(self):
        self.assertEqual(self.positions(backpack("Grug", 16))["state"], needs.WARN)

    def test_an_empty_position_with_room_left_is_only_a_caution(self):
        self.assertEqual(self.positions(backpack("Grug", 0))["state"], needs.CAUTION)

    def test_four_bags_carried_says_nothing(self):
        full = [
            item("Grug", 0, 19 + i, 900 + i, item_name="Pouch", cslots=6)
            for i in range(wealth.BAG_POSITIONS)
        ]
        bar = self.positions(full)
        self.assertEqual(bar["state"], needs.FINE)
        self.assertEqual(bar["pct"], 100)


class TheWorstThingIsOneThing(unittest.TestCase):
    def worst(self, **kwargs):
        return {m["name"]: m["worst"] for m in build(**kwargs)["members"]}

    def test_a_warning_beats_a_caution_however_many_cautions_there_are(self):
        line = self.worst(inventory=backpack("Grug", 16), equipment=worn("Grug", 90))[
            "Grug"
        ]
        self.assertEqual(line["state"], needs.WARN)
        self.assertIn("no room left", line["text"])

    def test_nothing_wrong_is_said_rather_than_left_blank(self):
        """A blank line under four green bars reads as a failed read."""
        four = [
            item("Grug", 0, 19 + i, 900 + i, item_name="Pouch", cslots=6)
            for i in range(wealth.BAG_POSITIONS)
        ]
        line = self.worst(inventory=four, equipment=worn("Grug", 100))["Grug"]
        self.assertEqual(line["state"], needs.FINE)
        self.assertIn("Grug", line["text"])

    def test_it_names_the_character_so_a_card_can_be_read_alone(self):
        for name, line in self.worst(equipment=worn("Grug", 10)).items():
            self.assertIn(name, line["text"], name)

    def test_a_member_with_no_saved_row_says_so_instead_of_reading_empty_bags(self):
        """A card that vanishes is how somebody stops being noticed, which is
        the whole complaint the Family view answers - so an absent member gets
        a sentence rather than four bars at zero."""
        payload = build(
            char_rows=[
                {"name": n, "money": 500000} for n in family.roster() if n != "Og"
            ]
        )
        og = next(m for m in payload["members"] if m["name"] == "Og")
        self.assertFalse(og["present"])
        self.assertEqual(og["needs"], [])
        self.assertIn("no saved character row", og["worst"]["text"])
        self.assertEqual(og["worst"]["state"], needs.FINE)


class TheLabelGoesInkWhenItIsTheProblem(unittest.TestCase):
    def test_problem_is_decided_here_and_not_by_the_page(self):
        """The page reads `problem` and hangs a class on it. Working out for
        itself that "warn" and "caution" are problems and "fine" is not would
        be a second copy of the state list."""
        payload = build(inventory=backpack("Grug", 16))
        for member in payload["members"]:
            for bar in member["needs"]:
                self.assertEqual(bar["problem"], bar["state"] != needs.FINE, bar["key"])


class WhatCountsAsSaidOutLoud(unittest.TestCase):
    """`overseer_thought` holds the family's inner life as well as its speech.
    Quoting a reflection on a card would put words in somebody's mouth."""

    def test_a_spoken_row_is_quoted(self):
        rows = [
            {
                "character_name": "Bork",
                "source": "council",
                "text": "BORK FOUND SHINY ROCK",
            }
        ]
        said = {m["name"]: m["said"] for m in build(thoughts=rows)["members"]}
        self.assertTrue(said["Bork"]["spoken"])
        self.assertEqual(said["Bork"]["text"], "BORK FOUND SHINY ROCK")

    def test_an_inner_row_is_not(self):
        for source in ("reflection", "goal", "command", "event"):
            rows = [
                {
                    "character_name": "Bork",
                    "source": source,
                    "text": "never said out loud",
                }
            ]
            said = {m["name"]: m["said"] for m in build(thoughts=rows)["members"]}
            self.assertFalse(said["Bork"]["spoken"], source)
            self.assertNotIn("never said out loud", said["Bork"]["text"], source)

    def test_silence_is_a_sentence_and_not_an_empty_box(self):
        said = {m["name"]: m["said"] for m in build()["members"]}
        self.assertIn("Bork", said["Bork"]["text"])
        self.assertFalse(said["Bork"]["spoken"])

    def test_the_newest_spoken_row_wins(self):
        rows = [
            {"character_name": "Grug", "source": "council", "text": "newest"},
            {"character_name": "Grug", "source": "council", "text": "older"},
        ]
        said = {m["name"]: m["said"] for m in build(thoughts=rows)["members"]}
        self.assertEqual(said["Grug"]["text"], "newest")


class TheRowsAreSievedHereAndNotInSql(unittest.TestCase):
    def test_only_professions_come_out_of_character_skills(self):
        """The table also holds languages, Defence and every weapon skill, and
        handing those to code that reasons about profession slots is exactly
        how `trades` came to mean nothing in the bridge."""
        rows = [
            {"name": "Og", "skill": 197, "value": 40},
            {"name": "Og", "skill": 95, "value": 60},
            {"name": "Og", "skill": 98, "value": 300},
        ]
        held = needs.held_skills(rows)
        self.assertEqual(held["Og"], {"tailoring": 40})

    def test_an_equipped_reagent_is_not_a_stack_that_can_move(self):
        """A reagent is never worn, so this only ever excludes gear - but a
        stack counted from a paper-doll slot would be a give the world refuses
        forever."""
        rows = [
            item("Grug", 0, 3, 1, count=19, item_name="Linen Cloth"),
            item("Grug", 0, 25, 2, count=19, item_name="Linen Cloth"),
        ]
        held = needs.holdings(rows)
        self.assertEqual([h.guid for h in held], [2])

    def test_an_item_no_reagent_table_names_is_left_alone(self):
        rows = [item("Grug", 0, 25, 7, item_name="Tough Jerky")]
        self.assertEqual(needs.holdings(rows), [])

    def test_a_give_row_keeps_holder_and_taker_the_right_way_round(self):
        """`target_name` is the holder and `target_arg` the taker, which is
        what bridge._insert_give writes. Swapped, every refusal would be
        counted against the wrong pair and nobody would ever give up."""
        rows = [
            {
                "target_name": "Grug",
                "target_arg": "Og",
                "status": "error",
                "detail": "receiver bags are full",
            }
        ]
        tried = needs.attempts(rows)
        self.assertEqual((tried[0].holder, tried[0].taker), ("Grug", "Og"))
        self.assertEqual(tried[0].detail, "receiver bags are full")


class TheThreeSectionsAreOnePayload(unittest.TestCase):
    def test_every_member_of_the_roster_gets_a_card_in_roster_order(self):
        payload = build()
        self.assertEqual([m["name"] for m in payload["members"]], family.roster())
        self.assertEqual(payload["expected"], len(family.roster()))

    def test_the_handovers_are_the_plan_the_bridge_is_already_acting_on(self):
        """Read a second time, never recomputed with different inputs. A view
        that could change what the family does by being looked at is a view
        nobody can trust."""
        inventory = backpack("Grug", 5, material="Linen Cloth")
        payload = build(inventory=inventory)
        direct = materials.board(needs.holdings(inventory), attempts=[], held={})
        self.assertEqual(
            [r["said"] for r in payload["moving"]["rows"]],
            [r.said for r in direct["rows"]],
        )

    def test_the_bonds_are_judged_on_reflection_rows_and_nothing_else(self):
        """A spoken line that happened to read like a memory must not become a
        helping event that never happened."""
        rows = [
            {
                "character_name": "Og",
                "source": "chat",
                "text": "Ugga called for help with boars. I regrouped.",
            }
        ]
        payload = build(thoughts=rows)
        for row in payload["answering"]["rows"]:
            self.assertEqual(row["count"], 0, row["key"])

    def test_the_whole_payload_survives_json(self):
        """The modules hand back dataclasses, which json.dumps cannot hold. A
        payload that only works in a unit test is an endpoint that 500s."""
        json.dumps(
            build(
                inventory=backpack("Grug", 4, material="Linen Cloth"),
                thoughts=[
                    {
                        "character_name": "Og",
                        "source": "reflection",
                        "text": "Ugga called for help. I regrouped.",
                    }
                ],
            )
        )

    def test_the_page_is_handed_a_state_word_it_never_has_to_lower_case(self):
        payload = build()
        for row in payload["answering"]["rows"]:
            self.assertEqual(row["state"], row["word"].lower())


class TheWindowIsANamedDecision(unittest.TestCase):
    """The adapter reads these rather than typing 24 into a query, the same way
    the quest log's SQL reads questlog.IN_LOG: a window is a decision about
    what counts as recent, and a number in SQL nothing tests cannot be found."""

    def test_the_window_is_wide_enough_for_the_refusals_that_were_measured(self):
        """Seven identical errors spread over six hours (mod-overseer#169). An
        hour-wide window sees one or two and reports a family that has given up
        as one that is still trying."""
        self.assertGreaterEqual(needs.HISTORY_HOURS, 6)

    def test_there_is_a_backstop_on_a_busy_stream(self):
        self.assertGreater(needs.HISTORY_MAX, 0)


class TheStatesAreNamedRatherThanSpelled(unittest.TestCase):
    def test_the_bar_states_are_constants(self):
        self.assertEqual(len({needs.FINE, needs.CAUTION, needs.WARN}), 3)

    def test_the_bonds_it_reports_are_the_bonds_module_s(self):
        payload = build(
            thoughts=[
                {
                    "character_name": "Og",
                    "source": "reflection",
                    "text": "Ugga called for help. I regrouped.",
                }
            ]
        )
        self.assertEqual(payload["answering"]["rule"], bonds.answering_rule())


if __name__ == "__main__":
    unittest.main()


class TheNeedsAreTheFamilyAsked(unittest.TestCase):
    """The same bug the quest board had: the Horde tab drew the Alliance's
    bags, handovers and bonds."""

    HORDE = ["Zug", "Oz"]

    def build(self, gives=()):
        return needs.build_needs(
            [{"name": n, "money": 100} for n in self.HORDE],
            [],
            [],
            [],
            list(gives),
            [],
            roster=self.HORDE,
        )

    def test_the_members_are_the_roster_given(self):
        p = self.build()
        self.assertEqual([m["name"] for m in p["members"]], self.HORDE)
        self.assertEqual(p["members"][0]["role"], "")

    def test_another_familys_bonds_are_not_drawn_on_this_one(self):
        p = self.build()
        self.assertEqual(p["answering"]["rows"], [])
        self.assertIn("no family rules", p["answering"]["headline"])
        for name in family.roster():
            self.assertNotIn(name, json.dumps(p["answering"]))

    def test_only_this_familys_give_attempts_are_counted(self):
        from unittest import mock

        other = {
            "target_name": family.roster()[0],
            "target_arg": "Ugga",
            "status": "failed",
            "detail": "bags full",
        }
        ours = {
            "target_name": "Oz",
            "target_arg": "Zug",
            "status": "failed",
            "detail": "bags full",
        }
        real = needs.materials.board
        seen = {}

        def spy(*args, **kw):
            seen["attempts"] = kw.get("attempts")
            return real(*args, **kw)

        with mock.patch.object(needs.materials, "board", spy):
            self.build(gives=[other, ours])
        self.assertEqual([a.holder for a in seen["attempts"]], ["Oz"])
