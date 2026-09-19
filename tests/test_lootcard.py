"""lootcard.py: which drops earn a card, for how long, and how they stack.

Pure module. The client half - turning LOOT_ITEM and friends into patterns and
calling GameTooltip:SetHyperlink - lives in LootCard.lua, because those globals
and that tooltip only exist inside a running game client. So the same guard the
status labels use applies here: the Lua is read as source text and this suite
fails when its constants or its ordered table drift from the module's.

THE FORMAT STRINGS BELOW ARE FIXTURES, copied verbatim out of 3.3.5a's
GlobalStrings.lua (build 12340). The module deliberately does not carry them -
the whole point of naming the globals instead is that the client owns the
wording, in whatever locale it is running. They are here so the argument
indices in MESSAGE_FORMS can be checked against the real strings rather than
against somebody's memory of them, which is where a mistake would actually
hide.
"""
import pathlib
import re
import unittest

import lootcard

ROOT = pathlib.Path(__file__).resolve().parents[1]
ADDON = ROOT / "wow-addons/PartyStatus"

GLOBALS_335A = {
    "LOOT_ITEM": "%s receives loot: %s.",
    "LOOT_ITEM_MULTIPLE": "%s receives loot: %sx%d.",
    "LOOT_ITEM_PUSHED_SELF": "You receive item: %s.",
    "LOOT_ITEM_PUSHED_SELF_MULTIPLE": "You receive item: %sx%d.",
    "LOOT_ITEM_SELF": "You receive loot: %s.",
    "LOOT_ITEM_SELF_MULTIPLE": "You receive loot: %sx%d.",
    "LOOT_ROLL_WON": "%s won: %s",
    "LOOT_ROLL_WON_NO_SPAM_DE": "%1$s won: %3$s |cff818181(Disenchant - %2$d)|r",
    "LOOT_ROLL_WON_NO_SPAM_GREED": "%1$s won: %3$s |cff818181(Greed - %2$d)|r",
    "LOOT_ROLL_WON_NO_SPAM_NEED": "%1$s won: %3$s |cff818181(Need - %2$d)|r",
    "LOOT_ROLL_YOU_WON": "You won: %s",
    "LOOT_ROLL_YOU_WON_NO_SPAM_DE": "You won: %2$s |cff818181(Disenchant - %1$d)|r",
    "LOOT_ROLL_YOU_WON_NO_SPAM_GREED": "You won: %2$s |cff818181(Greed - %1$d)|r",
    "LOOT_ROLL_YOU_WON_NO_SPAM_NEED": "You won: %2$s |cff818181(Need - %1$d)|r",
}

# Every specifier in a format string, as (argument index, kind). A bare "%s"
# takes the next argument; "%3$s" names one.
_SPEC = re.compile(r"%(\d?)\$?([sd])")


def specifiers(fmt):
    """{argument index: "s" or "d"} for one format string."""
    found, auto = {}, 0
    for idx, kind in _SPEC.findall(fmt):
        auto += 1
        found[int(idx) if idx else auto] = kind
    return found


def card(link="[robe]", winner="Og", verb=lootcard.WON, at=0.0):
    return {"link": link, "winner": winner, "verb": verb, "at": at}


class WhichDropsEarnACard(unittest.TestCase):

    def test_a_green_and_better_is_worth_showing(self):
        for quality in (2, 3, 4, 5, 6):
            self.assertTrue(lootcard.worth_showing(quality), quality)

    def test_wool_and_moss_agate_are_not(self):
        """The operator's complaint, in one test. A stream that announces
        every scrap of cloth is noise with a robe hidden in it."""
        for quality in (0, 1):
            self.assertFalse(lootcard.worth_showing(quality), quality)

    def test_an_unreadable_quality_is_not_shown(self):
        """Chosen direction, not an accident. The colour is in every link the
        server sends, so an unreadable one means the reader is broken - and a
        broken reader that shows everything puts every grey on a permanent
        stream, while one that shows nothing costs a card and is obvious."""
        self.assertFalse(lootcard.worth_showing(None))

    def test_the_bar_is_uncommon(self):
        self.assertEqual(lootcard.MIN_QUALITY, 2)


class WhoGotIt(unittest.TestCase):

    def test_it_names_the_winner_and_what_happened(self):
        self.assertEqual(lootcard.headline("Og", lootcard.WON, "Grug"),
                         "Og won")

    def test_a_plain_pickup_is_said_differently_from_a_win(self):
        self.assertEqual(lootcard.headline("Grug", lootcard.LOOTED, "Grug"),
                         "Grug looted")

    def test_nobody_is_called_you_on_a_stream(self):
        """The self forms carry no name. A viewer watching a video has no way
        to know whose screen it is, and "You won" beside four other people's
        names could be about any of them."""
        self.assertEqual(lootcard.headline("", lootcard.WON, "Grug"),
                         "Grug won")

    def test_it_says_nothing_rather_than_something_empty(self):
        self.assertEqual(lootcard.headline("", lootcard.WON, ""), "")

    def test_the_item_is_not_in_the_headline(self):
        """Only the client can render a link. Composing the name here would
        mean re-deriving its colour and its brackets and getting one wrong."""
        self.assertNotIn("[", lootcard.headline("Og", lootcard.WON, "Grug"))


class HowTheStackBehaves(unittest.TestCase):

    def test_a_drop_opens_a_card_stamped_with_the_time(self):
        stack = lootcard.admit([], card(), 100.0)
        self.assertEqual(len(stack), 1)
        self.assertEqual(stack[0]["at"], 100.0)

    def test_a_card_lasts_a_couple_of_minutes(self):
        stack = lootcard.admit([], card(), 100.0)
        self.assertEqual(len(lootcard.expire(stack, 100.0 + 119)), 1)
        self.assertEqual(len(lootcard.expire(stack, 100.0 + 121)), 0)

    def test_timers_are_independent_and_a_new_drop_resets_nothing(self):
        """A version that restarted the clock on every drop would keep the
        first robe of a dungeon on screen until the run ended."""
        stack = lootcard.admit([], card(link="[a]"), 0.0)
        stack = lootcard.admit(stack, card(link="[b]"), 100.0)
        self.assertEqual([c["at"] for c in stack], [0.0, 100.0])
        self.assertEqual([c["link"] for c in lootcard.expire(stack, 121.0)],
                         ["[b]"])

    def test_group_loot_saying_one_drop_twice_is_one_card(self):
        """The roll result and then the loot itself, a fraction of a second
        apart."""
        stack = lootcard.admit([], card(verb=lootcard.WON), 10.0)
        stack = lootcard.admit(stack, card(verb=lootcard.LOOTED), 10.5)
        self.assertEqual(len(stack), 1)
        self.assertEqual(stack[0]["verb"], lootcard.WON)

    def test_the_better_wording_wins_whichever_order_they_arrive_in(self):
        stack = lootcard.admit([], card(verb=lootcard.LOOTED), 10.0)
        stack = lootcard.admit(stack, card(verb=lootcard.WON), 10.5)
        self.assertEqual(len(stack), 1)
        self.assertEqual(stack[0]["verb"], lootcard.WON)

    def test_a_collapsed_duplicate_does_not_buy_more_time(self):
        stack = lootcard.admit([], card(), 10.0)
        stack = lootcard.admit(stack, card(), 20.0)
        self.assertEqual(stack[0]["at"], 10.0)

    def test_looting_the_same_thing_much_later_is_a_new_card(self):
        stack = lootcard.admit([], card(), 10.0)
        stack = lootcard.admit(stack, card(), 10.0 + lootcard.DEDUPE_SECONDS + 1)
        self.assertEqual(len(stack), 2)

    def test_two_people_winning_the_same_item_are_two_cards(self):
        stack = lootcard.admit([], card(winner="Og"), 10.0)
        stack = lootcard.admit(stack, card(winner="Ugga"), 10.5)
        self.assertEqual(len(stack), 2)

    def test_a_busy_pull_never_refuses_the_newest_drop(self):
        stack = []
        for i in range(6):
            stack = lootcard.admit(stack, card(link="[%d]" % i), 10.0 + i)
        self.assertEqual([c["link"] for c in stack], ["[3]", "[4]", "[5]"])

    def test_the_newest_cards_are_the_ones_that_keep_their_stats(self):
        stack = []
        for i in range(3):
            stack = lootcard.admit(stack, card(link="[%d]" % i), 10.0 + i)
        shown = lootcard.layout(stack)
        self.assertEqual([c["expanded"] for c in shown], [False, True, True])

    def test_a_lone_card_keeps_its_stats(self):
        shown = lootcard.layout(lootcard.admit([], card(), 10.0))
        self.assertEqual([c["expanded"] for c in shown], [True])

    def test_the_stack_can_never_be_taller_than_the_free_column(self):
        """Two tooltips and a headline. A tooltip for a level-25 green is
        about 160 units with its headline and the measured free band on the
        right is about 470, so three tooltips do not fit and two do."""
        self.assertEqual(lootcard.MAX_CARDS, 3)
        self.assertEqual(lootcard.MAX_EXPANDED, 2)
        self.assertLess(lootcard.MAX_EXPANDED, lootcard.MAX_CARDS)

    def test_expiring_never_reorders_what_is_left(self):
        stack = []
        for i in range(3):
            stack = lootcard.admit(stack, card(link="[%d]" % i), 10.0 + i * 60)
        # 10, 70 and 130; at 180 the first is 170 seconds old and gone.
        kept = lootcard.expire(stack, 180.0)
        self.assertEqual([c["link"] for c in kept], ["[1]", "[2]"])


class TheFormsMatchTheClientsRealStrings(unittest.TestCase):
    """MESSAGE_FORMS names arguments by index. Against the wrong index a card
    shows the roll number where the item should be, or a name that is really
    half a hyperlink, and nothing crashes to say so."""

    def test_every_form_names_a_string_that_exists_in_335a(self):
        for name, _, _, _ in lootcard.MESSAGE_FORMS:
            self.assertIn(name, GLOBALS_335A, name)

    def test_the_item_argument_is_always_a_string_specifier(self):
        for name, _, item, _ in lootcard.MESSAGE_FORMS:
            self.assertEqual(specifiers(GLOBALS_335A[name]).get(item), "s",
                             "%s argument %d" % (name, item))

    def test_the_winner_argument_is_a_string_when_there_is_one(self):
        for name, winner, _, _ in lootcard.MESSAGE_FORMS:
            if winner:
                self.assertEqual(specifiers(GLOBALS_335A[name]).get(winner),
                                 "s", "%s argument %d" % (name, winner))

    def test_a_form_with_no_winner_really_has_no_name_in_it(self):
        """Argument 0 means the client wrote the line about itself, so there
        is nobody to capture and the watched character is substituted."""
        for name, winner, _, _ in lootcard.MESSAGE_FORMS:
            if not winner:
                self.assertTrue(GLOBALS_335A[name].startswith("You"), name)

    def test_a_form_with_a_winner_does_not_start_with_you(self):
        for name, winner, _, _ in lootcard.MESSAGE_FORMS:
            if winner:
                self.assertFalse(GLOBALS_335A[name].startswith("You"), name)

    def test_no_form_is_listed_twice(self):
        names = [f[0] for f in lootcard.MESSAGE_FORMS]
        self.assertEqual(len(names), len(set(names)))

    def test_every_verb_is_one_of_the_two(self):
        for name, _, _, verb in lootcard.MESSAGE_FORMS:
            self.assertIn(verb, (lootcard.WON, lootcard.LOOTED), name)


class TheOrderIsLoadBearing(unittest.TestCase):
    """Each of these pairs is a message the GENERAL form also matches, with the
    wrong text captured and nothing to say so."""

    def index(self, name):
        for i, form in enumerate(lootcard.MESSAGE_FORMS):
            if form[0] == name:
                return i
        raise AssertionError(name + " is not in MESSAGE_FORMS")

    def before(self, first, second, why):
        self.assertLess(self.index(first), self.index(second), why)

    def test_the_no_spam_roll_forms_come_before_the_plain_one(self):
        for kind in ("NEED", "GREED", "DE"):
            self.before(
                "LOOT_ROLL_WON_NO_SPAM_" + kind, "LOOT_ROLL_WON",
                '"%s won: %s" also matches the (Need - 76) line, swallowing '
                "the whole suffix into the item")

    def test_the_self_roll_forms_come_before_the_third_person_one(self):
        self.before(
            "LOOT_ROLL_YOU_WON", "LOOT_ROLL_WON",
            '"%s won: %s" matches "You won: ..." with a winner called "You"')

    def test_the_multiple_forms_come_before_their_singulars(self):
        self.before("LOOT_ITEM_MULTIPLE", "LOOT_ITEM",
                    '"...loot: %s." would swallow the "x3" into the item')
        self.before("LOOT_ITEM_SELF_MULTIPLE", "LOOT_ITEM_SELF",
                    "same, for the self form")
        self.before("LOOT_ITEM_PUSHED_SELF_MULTIPLE", "LOOT_ITEM_PUSHED_SELF",
                    "same, for the pushed form")

    def test_rolls_in_progress_are_not_listed_at_all(self):
        """START_LOOT_ROLL already puts a roll frame on screen with its own
        timer. A card for the roll and another for its result would double
        every drop's screen time to say the same thing twice."""
        names = [f[0] for f in lootcard.MESSAGE_FORMS]
        for rolled in ("LOOT_ROLL_ROLLED_NEED", "LOOT_ROLL_ROLLED_GREED",
                       "LOOT_ROLL_ROLLED_DE"):
            self.assertNotIn(rolled, names)


class TheAddonMirrorsTheModule(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.lua = (ADDON / "LootCard.lua").read_text()
        cls.toc = (ADDON / "PartyStatus.toc").read_text()
        # Comments stripped: the invariants below are about what the addon
        # DOES. The header quotes a format string to explain why it must not
        # hardcode one, and a test that could not tell prose from code would
        # fail on the sentence saying it does the right thing.
        cls.code = "".join(
            line for line in cls.lua.splitlines(True)
            if not line.strip().startswith("--"))

    def test_the_addon_tries_the_forms_in_the_modules_order(self):
        block = self.lua[self.lua.index("local MESSAGE_FORMS = {"):]
        block = block[:block.index("\n}")]
        found = re.findall(r'\{ "(\w+)", (\d+), (\d+), (\w+) \}', block)
        self.assertEqual(
            [(n, int(w), int(i), v) for n, w, i, v in found],
            [(n, w, i, "WON" if verb == lootcard.WON else "LOOTED")
             for n, w, i, verb in lootcard.MESSAGE_FORMS])

    def test_every_number_the_module_decided_is_the_number_the_addon_uses(self):
        for name, value in (("MIN_QUALITY", lootcard.MIN_QUALITY),
                            ("DWELL_SECONDS", lootcard.DWELL_SECONDS),
                            ("MAX_CARDS", lootcard.MAX_CARDS),
                            ("MAX_EXPANDED", lootcard.MAX_EXPANDED),
                            ("DEDUPE_SECONDS", lootcard.DEDUPE_SECONDS),
                            ("HEADLINE_SIZE", lootcard.HEADLINE_SIZE),
                            ("ANCHOR_X", lootcard.ANCHOR_X),
                            ("ANCHOR_Y", lootcard.ANCHOR_Y)):
            self.assertIn("local %s = %d" % (name, value), self.lua, name)

    def test_the_two_verbs_are_spelled_the_same_on_both_sides(self):
        self.assertIn('local WON = "%s"' % lootcard.WON, self.lua)
        self.assertIn('local LOOTED = "%s"' % lootcard.LOOTED, self.lua)

    def test_the_addon_reads_the_clients_globals_rather_than_english(self):
        """The whole reason MESSAGE_FORMS holds names and not sentences."""
        self.assertIn("_G[spec[1]]", self.code)
        self.assertNotIn("receives loot", self.code)
        self.assertNotIn("won: ", self.code)

    def test_the_stats_come_from_the_game(self):
        """SetHyperlink on the link that arrived. Anything that composed its
        own stat lines would be wrong the first time an item had a suffix."""
        self.assertIn("SetHyperlink", self.lua)

    def test_it_grows_up_from_the_bottom_right(self):
        """Measured against a live capture: that column is empty from the
        quest tracker down to the action bar art, and growing upward puts a
        busy stack in empty sky rather than over the bar."""
        self.assertIn(
            'anchor:SetPoint("BOTTOMRIGHT", UIParent, "BOTTOMRIGHT", ANCHOR_X, ANCHOR_Y)',
            self.lua)
        self.assertIn(
            'card:SetPoint("BOTTOMRIGHT", cards[slot - 1], "TOPRIGHT", 0, CARD_GAP)',
            self.lua)

    def test_a_card_never_takes_a_click_off_the_world(self):
        self.assertIn("card:EnableMouse(false)", self.lua)

    def test_a_card_does_not_outrank_a_tooltip_somebody_hovered(self):
        self.assertIn('tip:SetFrameStrata("MEDIUM")', self.lua)

    def test_the_toc_loads_it(self):
        self.assertIn("LootCard.lua", self.toc)
        self.assertIn("## Interface: 30300", self.toc)


if __name__ == "__main__":
    unittest.main()
