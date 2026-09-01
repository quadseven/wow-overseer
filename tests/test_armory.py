"""The Armory builder: rows in, a readable gear-and-build column out.

The rules here are the ones that cost something to get wrong, and most of
them are rules about NOT lying: an empty slot has to say so, a slot that can
never hold anything useful must not read as a gap, a durability of zero on a
ring is not a broken ring, and a talent nobody can name must still be counted.
Every one of those, done the obvious way, produces a page that looks entirely
plausible and is wrong.

Run against the COMMITTED talents.json rather than a stub, deliberately: the
whole point of that file is that it resolves real spell ids into real talent
names, and a test that mocked it would pass just as happily with an empty one.

Ticket: infra#3096.
"""
import unittest

import armory
import family

BOOK = armory.TalentBook.load(".")

# Taken from bonds rather than retyped: WHO the family is belongs there, and
# a second list here is a second answer that can disagree with it.
ROSTER = family.roster()
FIRST, SECOND = ROSTER[0], ROSTER[1]

WARRIOR, PRIEST, DEATH_KNIGHT = 1, 5, 6
# Warrior trees, in the order TalentTab.dbc draws them.
ARMS, FURY, PROTECTION = 0, 1, 2

# Real ids out of the committed book. Puncture is a three-rank Warrior
# Protection talent, so spell 12810 IS rank 2 - which is the distinction
# between counting talents and counting POINTS.
PUNCTURE_R1, PUNCTURE_R2 = 12308, 12810
# Improved Heroic Strike, three ranks, Warrior ARMS - a different tree.
HEROIC_STRIKE_R1 = 12282


def char(**kw):
    row = {"name": FIRST, "level": 25, "race": 1, "class": WARRIOR,
           "online": 1, "activeTalentGroup": 0}
    row.update(kw)
    return row


def item(slot, **kw):
    row = {"name": FIRST, "slot": slot, "entry": 6552, "durability": 70,
           "item_name": "Bard's Tunic", "quality": 2, "item_level": 19,
           "required_level": 14, "max_durability": 70}
    row.update(kw)
    return row


def talent(spell, **kw):
    row = {"name": FIRST, "spell": spell, "specMask": 1}
    row.update(kw)
    return row


def build(char_rows=None, equipment_rows=None, talent_rows=None):
    return armory.build_armory(
        [char()] if char_rows is None else char_rows,
        equipment_rows or [], talent_rows or [], BOOK)


def col(payload, name):
    return next(m for m in payload["members"] if m["name"] == name)


def slot_of(member, slot_name):
    return next(s for s in member["slots"] if s["slot"] == slot_name)


class TheColumnsTest(unittest.TestCase):
    def test_every_member_gets_a_column_even_with_nothing_in_the_database(self):
        """The failure this tab exists to stop is a character going unnoticed.
        A member with no rows must be a visible empty column, never a column
        that quietly is not drawn - four columns look completely normal."""
        payload = build(char_rows=[])
        self.assertEqual([m["name"] for m in payload["members"]], ROSTER)
        for member in payload["members"]:
            self.assertFalse(member["present"])

    def test_the_columns_come_in_roster_order(self):
        """Same order as every other surface. Sorting these by a second rule
        would be a second opinion about the same family."""
        self.assertEqual([m["name"] for m in build()["members"]], ROSTER)

    def test_the_slot_order_is_sent_rather_than_left_to_the_page(self):
        """The grid reads ACROSS - row three is the same slot in all five
        columns - which only holds if one list decides the order. A second
        list in the page could disagree and misalign the whole thing."""
        self.assertEqual([s["slot"] for s in build()["slots"]],
                         list(armory.EQUIPPED_SLOTS))


class TheGearTest(unittest.TestCase):
    def test_an_empty_slot_is_reported_not_omitted(self):
        """A missing row is the whole finding. If empty slots were simply left
        out, the one thing this view was asked for - who is missing a helmet -
        would be the one thing it could not show."""
        member = col(build(equipment_rows=[item(4)]), FIRST)
        self.assertEqual(len(member["slots"]), len(armory.EQUIPPED_SLOTS))
        self.assertTrue(slot_of(member, "head")["empty"])
        self.assertFalse(slot_of(member, "chest")["empty"])

    def test_a_cosmetic_slot_is_shown_but_never_counted_as_a_gap(self):
        """Shirt and tabard hold no stats in 3.3.5. Counting them would put
        every character on the server permanently two slots short, and a
        number that is always wrong by two is a number nobody reads."""
        member = col(build(), FIRST)
        self.assertTrue(slot_of(member, "tabard")["cosmetic"])
        self.assertTrue(slot_of(member, "tabard")["empty"])
        self.assertNotIn("tabard", member["gear"]["empty_slots"])
        self.assertNotIn("shirt", member["gear"]["empty_slots"])

    def test_the_average_item_level_is_over_what_is_worn(self):
        """Counting an empty slot as item level 0 folds two different
        complaints - his gear is old, and he has no helmet - into one number
        that answers neither. The empty slots are listed separately instead."""
        member = col(build(equipment_rows=[
            item(4, item_level=20), item(5, item_level=30)]), FIRST)
        self.assertEqual(member["gear"]["average_item_level"], 25)
        self.assertEqual(member["gear"]["worn"], 2)

    def test_a_character_wearing_nothing_has_no_average_rather_than_a_zero(self):
        """Zero is a claim about his gear. None is the truth: there is nothing
        to average."""
        self.assertIsNone(col(build(), FIRST)["gear"]["average_item_level"])

    def test_an_item_the_world_database_does_not_know_is_still_worn(self):
        """A LEFT JOIN miss is a custom or removed item, and it is genuinely
        equipped. Rendering it as an empty slot would invent a gap that is not
        there and send somebody looking for a helmet he already has."""
        member = col(build(equipment_rows=[
            item(0, entry=99999, item_name=None, quality=None,
                 item_level=None, max_durability=None)]), FIRST)
        head = slot_of(member, "head")
        self.assertFalse(head["empty"])
        self.assertEqual(head["name"], "Item #99999")
        self.assertEqual(head["quality_name"], armory.UNKNOWN_QUALITY)

    def test_an_item_that_cannot_break_is_not_reported_as_broken(self):
        """Rings, cloaks, necks and trinkets store durability 0 because they
        HAVE no durability. Reading that as broken would paint half the
        paper doll red permanently."""
        member = col(build(equipment_rows=[
            item(10, durability=0, max_durability=0)]), FIRST)
        self.assertFalse(slot_of(member, "finger 1")["broken"])
        self.assertEqual(member["gear"]["broken"], [])

    def test_an_item_that_can_break_and_has_is_called_out(self):
        member = col(build(equipment_rows=[
            item(4, durability=0, max_durability=70)]), FIRST)
        self.assertTrue(slot_of(member, "chest")["broken"])
        self.assertEqual(member["gear"]["broken"], ["chest"])

    def test_quality_is_named_as_well_as_numbered(self):
        """The page colours by the number; a person reads the word. Deciding
        here is what stops a render function growing its own switch."""
        member = col(build(equipment_rows=[item(4, quality=4)]), FIRST)
        self.assertEqual(slot_of(member, "chest")["quality_name"], "epic")


class TheBuildTest(unittest.TestCase):
    def test_a_learned_spell_becomes_a_named_talent(self):
        """The entire reason talents.json exists. `character_talent` holds
        spell 12308 and nothing else; without the book this tab shows a
        number, which is the state the ticket was filed about."""
        spec = col(build(talent_rows=[talent(PUNCTURE_R1)]), FIRST)["spec"]
        names = [t["name"] for tree in spec["trees"] for t in tree["talents"]]
        self.assertEqual(names, ["Puncture"])

    def test_a_point_is_the_rank_held_not_the_talent_taken(self):
        """Rank 2 of a three-rank talent is TWO points spent. Counting rows
        would report a level 25 warrior as having spent one."""
        spec = col(build(talent_rows=[talent(PUNCTURE_R2)]), FIRST)["spec"]
        self.assertEqual(spec["spent"], 2)
        talents = [t for tree in spec["trees"] for t in tree["talents"]]
        self.assertEqual((talents[0]["rank"], talents[0]["max_rank"]), (2, 3))

    def test_the_distribution_reads_in_the_order_the_game_draws_the_trees(self):
        """0/0/16 is a sentence every WoW player already knows how to read,
        but only if the three numbers are in the client's own tab order."""
        spec = col(build(talent_rows=[
            talent(PUNCTURE_R2), talent(HEROIC_STRIKE_R1)]), FIRST)["spec"]
        self.assertEqual(spec["distribution"], "1/0/2")
        self.assertEqual(spec["trees"][ARMS]["name"], "Arms")
        self.assertEqual(spec["trees"][FURY]["name"], "Fury")
        self.assertEqual(spec["trees"][PROTECTION]["name"], "Protection")
        self.assertEqual(spec["primary"], "Protection")

    def test_only_the_active_spec_is_counted(self):
        """character_talent holds BOTH dual-spec builds, told apart by
        specMask. Summing them reports a level 25 warrior with 32 points and
        a build he is not playing."""
        rows = [talent(PUNCTURE_R2, specMask=1),
                talent(HEROIC_STRIKE_R1, specMask=2)]
        spec = col(build(talent_rows=rows), FIRST)["spec"]
        self.assertEqual(spec["spent"], 2)
        self.assertEqual(spec["distribution"], "0/0/2")

    def test_the_other_spec_is_what_shows_when_it_is_the_active_one(self):
        rows = [talent(PUNCTURE_R2, specMask=1),
                talent(HEROIC_STRIKE_R1, specMask=2)]
        spec = col(build([char(activeTalentGroup=1)], None, rows), FIRST)["spec"]
        self.assertEqual(spec["distribution"], "1/0/0")

    def test_an_unspent_point_is_reported(self):
        """The signal that a character has been levelling and nobody has been
        specc'ing him. It is invisible in the game unless you open his talent
        pane, and invisible here unless the budget is worked out."""
        spec = col(build([char(level=25)], None,
                         [talent(PUNCTURE_R1)]), FIRST)["spec"]
        self.assertEqual(spec["available"], 16)
        self.assertEqual(spec["spent"], 1)
        self.assertEqual(spec["unspent"], 15)

    def test_below_level_ten_there_is_no_budget_to_be_short_of(self):
        spec = col(build([char(level=9)], None, []), FIRST)["spec"]
        self.assertEqual(spec["available"], 0)
        self.assertEqual(spec["unspent"], 0)

    def test_a_death_knight_budget_is_unknown_rather_than_guessed(self):
        """A DK's points count quest rewards the core tracks in memory and
        does not expose here. An 'unspent points' figure that is quietly wrong
        is worse than one that admits it does not know."""
        spec = col(build([char(**{"class": DEATH_KNIGHT})], None, []),
                   FIRST)["spec"]
        self.assertIsNone(spec["available"])
        self.assertIsNone(spec["unspent"])

    def test_a_talent_the_book_does_not_know_is_counted_and_named(self):
        """A custom talent, or a client newer than the committed file. It is
        still a real point the character has spent, so dropping it would
        understate the build without anything on screen saying so."""
        spec = col(build(talent_rows=[talent(4242424)]), FIRST)["spec"]
        self.assertEqual(spec["spent"], 1)
        self.assertEqual([t["name"] for t in spec["unplaced"]],
                         ["Spell #4242424"])

    def test_a_character_with_no_talents_says_so_without_a_primary_tree(self):
        spec = col(build(), FIRST)["spec"]
        self.assertIsNone(spec["primary"])
        self.assertEqual(spec["distribution"], "0/0/0")

    def test_talents_are_listed_down_the_tree_the_way_the_trainer_draws_it(self):
        """Tier then column. Sorted by spell id - the order the rows arrive
        in - the list reads as a shuffle of a build rather than as a build."""
        spec = col(build(talent_rows=[
            talent(PUNCTURE_R1), talent(HEROIC_STRIKE_R1)]), FIRST)["spec"]
        for tree in spec["trees"]:
            rows = [(t["row"], t["col"]) for t in tree["talents"]]
            self.assertEqual(rows, sorted(rows))


class TheTalentBookTest(unittest.TestCase):
    """Guards the committed file itself. If these fail, talents.json is wrong
    or was regenerated from different client data - and every test above would
    otherwise fail in a way that pointed at the builder instead."""

    def test_the_book_knows_the_talent_the_other_tests_are_written_around(self):
        talent_row, rank = BOOK.by_spell[PUNCTURE_R2]
        self.assertEqual(talent_row["name"], "Puncture")
        self.assertEqual(rank, 2)

    def test_every_class_has_exactly_three_trees(self):
        """Pet trees are excluded on purpose - they have no class and never
        appear in character_talent - so every class left must have three."""
        for class_id in sorted({t["class"] for t in BOOK.trees.values()}):
            self.assertEqual(len(BOOK.trees_for(class_id)), 3, class_id)

    def test_a_rank_spell_names_exactly_one_talent(self):
        """The reverse index is a dict, so a spell that is a rank of two
        different talents would not collide loudly - the second would simply
        overwrite the first, and those points would be attributed to the wrong
        tree for as long as anybody looked at it."""
        import json
        with open("talents.json") as f:
            ranks = [s for t in json.load(f)["talents"] for s in t["ranks"]]
        self.assertEqual(len(ranks), len(set(ranks)))
        self.assertEqual(len(ranks), len(BOOK.by_spell))

    def test_the_book_covers_the_talents_the_family_have_actually_learned(self):
        """The file is generated, and a generator that silently produced an
        EMPTY book would pass every test above that uses a hard-coded id.
        This is the coverage check: a real class's real tree, fully named."""
        arms = BOOK.trees_for(WARRIOR)[ARMS][1]
        self.assertEqual(arms["name"], "Arms")
        named = [t for t in BOOK.by_spell.values() if t[0]["name"].startswith("Spell #")]
        self.assertEqual(named, [], "talents with no name in the book")


if __name__ == "__main__":
    unittest.main()
