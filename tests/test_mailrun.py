"""What the family collects from its mailboxes, and what it leaves alone.

THE ROWS ARE THE MEASURED ONES. Every letter in `LIVE` below is a real row read
out of wow-dev's `mail` table on 2026-09-13, including the auction house
settlement carrying 4,100 copper and the four letters Ugga is holding. Made-up
rows would have let the LEFT JOIN case (a letter with money and no attachment)
pass a test built only from letters that carry things, which is the exact case
that letter is.

THE OTHER HALF OF THIS FILE IS A MIRROR. `mailrun.command` renders text a C++
parser has to accept, so the tests below read `ParseMailRequest` and
`MailRefusal` as source and fail when the two sides drift - the same discipline
`test_travel_npc.py` holds `travel.ROLES` to against `TravelRoles()`. A grammar
test that only checked our own constant would pass on the day the module renamed
the verb, which is the day it matters.
"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import mailrun  # noqa: E402
import travel  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[3]
DECISIONS = ROOT / "docker/azerothcore-playerbots/mod-overseer/src/overseer_decisions.cpp"
HEADER = ROOT / "docker/azerothcore-playerbots/mod-overseer/src/overseer_decisions.h"
MODULE = ROOT / "docker/azerothcore-playerbots/mod-overseer/src/mod_overseer.cpp"


def _row(holder, mail_id, *, money=0, cod=0, delivered=1, expire=0, item=None):
    return {"holder": holder, "mail_id": mail_id, "money": money, "cod": cod,
            "delivered": delivered, "expire_time": expire, "item_guid": item}


# wow-dev, 2026-09-13. Og's letter 41 is `messageType = 2` - an auction house
# settlement - and is the whole reason the fetch is a LEFT JOIN: it carries
# money and NOTHING ELSE, so an inner join onto `mail_items` would drop the most
# valuable thing in any of these mailboxes.
LIVE = [
    _row("Og", 41, money=4100, expire=1791006826),
    _row("Og", 39, expire=1796176470, item=555),
    _row("Og", 14, expire=1790728912, item=777),
    _row("Ugga", 22, expire=1790844250, item=901),
    _row("Ugga", 23, expire=1790845231, item=902),
    _row("Ugga", 366, expire=1791771841),
]

FAMILY = ["Bork", "Grog", "Grug", "Og", "Ugga"]


class LettersAreFoldedBackTogether(unittest.TestCase):

    def test_one_letter_per_id_however_many_attachment_rows(self):
        """The fetch is one row per attachment; a letter is one letter."""
        rows = [_row("Og", 14, item=777), _row("Og", 14, item=778),
                _row("Og", 14, item=779)]
        letters = mailrun.letters_from_rows(rows, ["Og"])
        self.assertEqual(len(letters), 1)
        self.assertEqual(letters[0].attachments, (777, 778, 779))

    def test_a_letter_carrying_only_money_survives(self):
        """THE LEFT JOIN CASE, and the one that pays. Og's letter 41 has no
        `mail_items` row at all, so a fold that keyed on the attachment would
        drop it - along with 4,100 copper."""
        letters = mailrun.letters_from_rows(LIVE, FAMILY)
        by_id = {letter.mail_id: letter for letter in letters}
        self.assertIn(41, by_id)
        self.assertEqual(by_id[41].money, 4100)
        self.assertEqual(by_id[41].attachments, ())

    def test_a_row_for_somebody_else_is_not_collected(self):
        """`names` is the family; the realm's other 535 letters are not ours."""
        letters = mailrun.letters_from_rows(
            LIVE + [_row("Auctioneer", 9001, item=1)], FAMILY)
        self.assertNotIn("Auctioneer", {letter.holder for letter in letters})

    def test_a_letter_with_no_usable_id_is_dropped_not_guessed_at(self):
        """The executor refuses a zero mail id without reaching the world, so a
        row this process cannot name a letter from is one it must not ask
        about."""
        letters = mailrun.letters_from_rows(
            [_row("Og", 0, item=5), _row("Og", None, item=6)], ["Og"])
        self.assertEqual(letters, ())

    def test_the_soonest_to_expire_comes_first(self):
        """Mail keeps thirty days and then the letter and everything on it are
        gone, so when the visit limit bites the nearest deadline wins."""
        letters = [one for one in mailrun.letters_from_rows(LIVE, FAMILY)
                   if one.holder == "Og"]
        self.assertEqual([one.mail_id for one in letters], [14, 41, 39])

    def test_a_duplicate_attachment_row_does_not_double_the_take(self):
        """A join can repeat a row; a bag slot cannot be spent twice."""
        letters = mailrun.letters_from_rows(
            [_row("Og", 14, item=777), _row("Og", 14, item=777)], ["Og"])
        self.assertEqual(letters[0].attachments, (777,))


class WhatIsWorthAskingFor(unittest.TestCase):

    def test_money_is_collected_before_items(self):
        """A take-money costs no bag slot. Putting it second would let a full
        bag swallow the coins as well as the goods."""
        letters = mailrun.letters_from_rows(LIVE, FAMILY)
        takes = mailrun.plan(letters, {"Og": 8, "Ugga": 8}).takes
        og = [t for t in takes if t.character == "Og"]
        self.assertEqual(og[0].verb, mailrun.TAKE_MONEY)
        self.assertEqual(og[0].mail_id, 41)
        self.assertTrue(all(t.verb == mailrun.TAKE_ITEM for t in og[1:]))

    def test_a_full_bag_still_collects_the_money(self):
        """The case the ordering exists for: zero free slots, 4,100 copper."""
        letters = mailrun.letters_from_rows(LIVE, FAMILY)
        takes = mailrun.plan(letters, {"Og": 0, "Ugga": 0}).takes
        self.assertEqual([mailrun.command(t) for t in takes],
                         ["take-money mail:41"])

    def test_bag_room_stops_the_items_and_says_so(self):
        letters = mailrun.letters_from_rows(LIVE, FAMILY)
        plan = mailrun.plan(letters, {"Og": 1, "Ugga": 1})
        items = [t for t in plan.takes if t.verb == mailrun.TAKE_ITEM]
        self.assertEqual(len(items), 2)          # one each, not one apiece per letter
        self.assertEqual({t.character for t in items}, {"Og", "Ugga"})
        self.assertTrue(any("no room in the bags" in note for note in plan.notes))

    def test_what_was_already_asked_for_is_spent_budget(self):
        """`character_inventory` is written on PlayerSaveInterval for everything
        EXCEPT a mail take, so a loot five minutes ago still reads as free
        space. Without this the pass would re-ask the same optimistic question
        every cycle for as long as the window held."""
        letters = mailrun.letters_from_rows(LIVE, FAMILY)
        plan = mailrun.plan(letters, {"Og": 2, "Ugga": 2}, {"Og": 2, "Ugga": 1})
        items = [t for t in plan.takes if t.verb == mailrun.TAKE_ITEM]
        self.assertEqual([t.character for t in items], ["Ugga"])

    def test_an_undelivered_letter_is_left_where_it_is(self):
        """`mail has not been delivered yet` is the executor's answer, and a
        cross-account item waits the realm's configured hour."""
        letters = mailrun.letters_from_rows(
            [_row("Og", 50, money=10, delivered=0, item=1)], ["Og"])
        plan = mailrun.plan(letters, {"Og": 8})
        self.assertEqual(plan.takes, ())
        self.assertIn("has not been delivered yet", " ".join(plan.notes))

    def test_a_cash_on_delivery_letter_keeps_its_attachment(self):
        """`mail is cash on delivery` is a PERMANENT refusal of take-item: the
        core would charge the COD out of this character's purse. A row for one
        can only ever fail."""
        letters = mailrun.letters_from_rows(
            [_row("Og", 51, cod=5000, item=1)], ["Og"])
        plan = mailrun.plan(letters, {"Og": 8})
        self.assertEqual(plan.takes, ())
        self.assertIn("cash on delivery", " ".join(plan.notes))

    def test_money_is_still_taken_off_a_cash_on_delivery_letter(self):
        """Mirrors the executor rather than being tidier than it: `take-item`
        checks COD and `take-money` does not, so refusing both here would
        invent a rule the world does not have and strand the coins."""
        letters = mailrun.letters_from_rows(
            [_row("Og", 52, money=77, cod=5000, item=1)], ["Og"])
        takes = mailrun.plan(letters, {"Og": 8}).takes
        self.assertEqual([mailrun.command(t) for t in takes],
                         ["take-money mail:52"])

    def test_one_visit_is_bounded_and_the_rest_waits(self):
        """The family reaches a mailbox by one leader walking there. Forty rows
        against that one arrival spend the whole retry window on a journey that
        may not have finished."""
        rows = [_row("Og", 100 + n, item=n + 1) for n in range(20)]
        plan = mailrun.plan(mailrun.letters_from_rows(rows, ["Og"]), {"Og": 40})
        self.assertEqual(len(plan.takes), mailrun.VISIT_LIMIT)
        self.assertIn("one visit carries", " ".join(plan.notes))

    def test_a_character_nobody_could_measure_gets_nothing(self):
        """A name missing from `free_slots` is unknown room, not empty room -
        and unknown room plans no takes rather than takes that are refused."""
        letters = mailrun.letters_from_rows([_row("Bork", 16, item=4)], ["Bork"])
        self.assertEqual(mailrun.plan(letters, {}).takes, ())
        self.assertEqual(mailrun.room_for("Bork", {}, {}), 0)

    def test_room_never_goes_negative(self):
        self.assertEqual(mailrun.room_for("Og", {"Og": 2}, {"Og": 9}), 0)

    def test_an_empty_mailbox_plans_nothing_and_claims_nothing(self):
        plan = mailrun.plan((), {"Og": 8})
        self.assertEqual(plan.takes, ())
        self.assertEqual(plan.notes, ())

    def test_the_destructive_verbs_are_never_emitted(self):
        """`delete` DESTROYS every attachment on the letter (`Player::_SaveMail`
        issues CHAR_DEL_ITEM_INSTANCE for a mail left in MAIL_STATE_DELETED), so
        this module has no path that can reach it however the rows read."""
        rows = LIVE + [_row("Bork", 16, money=1, cod=1, delivered=0, item=9)]
        plan = mailrun.plan(mailrun.letters_from_rows(rows, FAMILY),
                            {name: 8 for name in FAMILY},
                            {name: 0 for name in FAMILY})
        rendered = [mailrun.command(t) for t in plan.takes]
        self.assertTrue(rendered)
        for text in rendered:
            self.assertFalse(text.startswith("delete"), text)
            self.assertFalse(text.startswith("return"), text)
            self.assertFalse(text.startswith("send"), text)


class TheWindowIsCountedInAttachments(unittest.TestCase):

    def test_only_take_item_spends_a_bag_slot(self):
        asked = mailrun.attachments_asked({
            ("Og", "take-item mail:14 item:777"),
            ("Og", "take-item mail:39 item:555"),
            ("Og", "take-money mail:41"),
            ("Ugga", "take-item mail:22 item:901"),
        })
        self.assertEqual(asked, {"Og": 2, "Ugga": 1})

    def test_an_empty_window_spends_nothing(self):
        self.assertEqual(mailrun.attachments_asked(set()), {})


class TheCommandIsWhatTheDeployedParserAccepts(unittest.TestCase):
    """The mirror. These read mod-overseer's own source at the pinned SHA."""

    def test_the_rendered_shapes(self):
        take = mailrun.Take(character="Og", verb=mailrun.TAKE_ITEM,
                            mail_id=14, item_guid=777, why="")
        money = mailrun.Take(character="Og", verb=mailrun.TAKE_MONEY,
                             mail_id=41, item_guid=0, why="")
        self.assertEqual(mailrun.command(take), "take-item mail:14 item:777")
        self.assertEqual(mailrun.command(money), "take-money mail:41")

    def test_the_verbs_are_the_ones_ParseMailRequest_matches(self):
        source = DECISIONS.read_text(encoding="utf-8")
        self.assertIn('words[0] == "%s"' % mailrun.TAKE_ITEM, source)
        self.assertIn('words[0] == "%s"' % mailrun.TAKE_MONEY, source)

    def test_the_keys_are_the_ones_ParseMailRequest_binds(self):
        """`mail:` and `item:` are the parser's own key names, and anything
        else is answered `malformed mail command` without reaching the world."""
        source = DECISIONS.read_text(encoding="utf-8")
        self.assertIn('key == "mail"', source)
        self.assertIn('key == "item"', source)

    def test_the_grammar_line_in_the_header_still_says_this(self):
        header = HEADER.read_text(encoding="utf-8")
        self.assertIn("take-item mail:<mail.id> item:<item_instance.guid>", header)
        self.assertIn("take-money mail:<mail.id>", header)

    def test_the_refusals_this_module_plans_around_are_still_spelled_that_way(self):
        """Each of these is a wall `mailrun.plan` steers around by name. A
        renamed literal on the C++ side would make the steering silently wrong,
        so it fails here instead."""
        header = HEADER.read_text(encoding="utf-8")
        for literal in ('"mail is cash on delivery"',
                        '"mail has not been delivered yet"',
                        '"no room in the bags"',
                        '"mailbox not in range"',
                        '"no mail with that id"'):
            self.assertIn(literal, header)

    def test_a_mailbox_is_still_a_gameobject_to_the_executor(self):
        """travel.MAILBOX_GO_TYPE is 19 because `FindMailboxInReach` sweeps for
        GAMEOBJECT_TYPE_MAILBOX. If the module ever stopped looking for one, the
        ground aim this package writes would be aiming at nothing."""
        self.assertEqual(travel.MAILBOX_GO_TYPE, 19)
        self.assertIn("GetGoType() == GAMEOBJECT_TYPE_MAILBOX",
                      MODULE.read_text(encoding="utf-8"))

    def test_no_role_keyword_can_reach_a_mailbox(self):
        """The reason the aim is a ground aim at all. `travel.ROLES` mirrors
        `TravelRoles()` exactly, so inventing a `mailbox` keyword here would
        fail test_travel_npc rather than reach anything."""
        self.assertNotIn("mailbox", travel.ROLES)
        self.assertIsNone(travel.resolve("mailbox"))


class TheAimComesOutOfTheSpawnTable(unittest.TestCase):

    def test_a_spawn_becomes_a_ground_aim_that_fits_the_column(self):
        aim = travel.mailbox_aim(
            {"map_id": 1, "x": -3200.57, "y": -2800.21, "z": 35.19}, 1)
        self.assertEqual(aim.aim, "at:1:-3200.6,-2800.2,35.2")
        self.assertLessEqual(len(aim.aim), travel.COLUMN_WIDTH)
        self.assertTrue(travel.is_ground_aim(aim.aim))

    def test_another_map_is_refused_with_a_sentence(self):
        aim = travel.mailbox_aim({"map_id": 0, "x": 1.0, "y": 2.0, "z": 3.0}, 1)
        self.assertEqual(aim.aim, "")
        self.assertIn("no navmesh", aim.refused)

    def test_nothing_found_is_refused_with_a_sentence(self):
        aim = travel.mailbox_aim(None, 1)
        self.assertEqual(aim.aim, "")
        self.assertIn("no mailbox is spawned on map 1", aim.refused)

    def test_no_fresh_snapshot_is_its_own_sentence(self):
        """A mailbox nobody can see is a snapshot problem, not a travel one,
        and a person reading the log has a different thing to do about it."""
        aim = travel.mailbox_aim({"map_id": 1, "x": 1.0, "y": 2.0, "z": 3.0}, None)
        self.assertEqual(aim.aim, "")
        self.assertIn("overseer_snapshot", aim.refused)

    def test_an_aim_that_would_truncate_is_refused_rather_than_written(self):
        """MySQL truncates outside strict mode, and a truncated aim is not a
        failed aim - it is a different, plausible coordinate nobody surveyed."""
        aim = travel.mailbox_aim(
            {"map_id": 530, "x": -39091111.75, "y": -11548.9, "z": -149.957}, 530)
        self.assertEqual(aim.aim, "")
        self.assertIn("truncate", aim.refused)


class TheLogSaysWhatWasAsked(unittest.TestCase):

    def test_every_take_gets_a_line_carrying_its_command(self):
        letters = mailrun.letters_from_rows(LIVE, FAMILY)
        takes = mailrun.plan(letters, {"Og": 8, "Ugga": 8}).takes
        lines = mailrun.lines(takes)
        self.assertEqual(len(lines), len(takes))
        self.assertIn("take-money mail:41", lines[0])
        self.assertIn("4100 copper", lines[0])


if __name__ == "__main__":
    unittest.main()
