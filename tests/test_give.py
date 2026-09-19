"""The item handoff, and the four ways it could quietly lie.

A party rolls on everything, so loot lands on whoever won the roll rather than
on whoever can use it. Moving it afterwards is a module job because no chat
command can do it: mod-playerbots' `t <Hitem:>` targets the bot's master and,
between two selfbots, never completes - while the queue row still reads
`delivered`. That is the shape this whole file exists to stop being repeated.

So the failures worth pinning are the ones that would make the handoff look
like it worked:

  * a refusal that writes nothing back, leaving an 'error' row nobody outside
    the worldserver can diagnose;
  * a refusal reason that does not distinguish the five cases an operator
    actually has to tell apart;
  * a `detail` literal carrying a quote character, which is pasted straight
    into the UPDATE that reports the outcome;
  * a move that is not inside one transaction, which is how an item gets
    duplicated or lost across a worldserver crash;
  * an ENUM value added by editing CREATE TABLE IF NOT EXISTS, which does
    nothing at all to a table that already exists.
"""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE = ROOT / "mod-overseer/src/mod_overseer.cpp"
MIGRATION = (
    ROOT
    / "mod-overseer/data/sql/characters/base"
    / "2026_08_24_00_overseer_give.sql"
)


def _source() -> str:
    return MODULE.read_text(encoding="utf-8")


def _give_source() -> str:
    """Everything from the give banner to the end of DoGive."""
    src = _source()
    start = src.index("// ---------------------------------------------------------------- give --")
    end = src.index("    void WriteSnapshot()")
    assert end > start
    return src[start:end]


class TheGivePathIsReachable(unittest.TestCase):
    def test_the_command_loop_dispatches_it(self):
        """A DoGive nobody calls is a feature that exists only in the diff."""
        src = _source()
        self.assertIn('kind == "give"', src)
        self.assertIn("DoGive(player, targetArg, command, status, rowResult)", src)

    def test_it_is_exempt_from_the_bot_trigger_hold(self):
        """kind='give' shares no ChatCommandTrigger, so holding it would only
        delay it for no reason - the same exemption chat, gm and probe have."""
        src = _source()
        self.assertIn(
            'kind != "chat" && kind != "gm" && kind != "probe" && kind != "give"', src
        )

    def test_the_outcome_reaches_the_row(self):
        src = _source()
        self.assertIn("result = '{}'", src)
        self.assertIn("EscLong(rowResult)", src)


class EveryRefusalIsReported(unittest.TestCase):
    """`detail` alone is a short string; the JSON in `result` is the evidence."""

    def test_every_early_return_writes_the_result_column(self):
        """Each refusal writes `result`. Most go through refuse() or describe(),
        both of which set `out`; the backoff exit added in #170 builds its own
        JSON and assigns `out` directly, which satisfies the same invariant.
        A bare `return "something"` with none of the three in front of it would
        end the row as an error with an empty result - a failure nobody can
        diagnose from outside the worldserver."""
        body = _give_source()
        # DoGive lost its `static` in #170; match on the part that is stable.
        body = body[body.index("char const* DoGive("):]
        # AND IT STOPS AT DoGive'S OWN END, which it did not used to. The window
        # _give_source returns runs to WriteSnapshot, so slicing only at the
        # front left this scanning every function that happens to sit between
        # DoGive and there. That was harmless for as long as nothing did, and
        # stopped being harmless when quadseven/mod-overseer#349 lifted
        # BindAtInnkeeperInReach out of DoBind into that gap. That helper
        # returns a refusal literal FOR ITS CALLER to record, which is its
        # documented contract, and both callers honour it: DoBind wraps it in
        # refuse(), and the home errand logs it and holds the member. So the
        # invariant this test protects was never broken; the test was reading a
        # function it was never about.
        end = body.find("--------------------------------------------------------------- trade --")
        if end != -1:
            body = body[:end]
        lines = body.splitlines()
        for line_no, line in enumerate(lines):
            stripped = line.strip()
            if not stripped.startswith('return "') or stripped == 'return "";':
                continue
            # The refusal itself, or the describe() that recorded it, has to be
            # within the same short block. Six lines covers a wrapped call.
            window = "\n".join(lines[max(0, line_no - 6):line_no + 1])
            # `out = ` counts because it IS the result column being written.
            # The test names the mechanism in its title but the invariant it
            # protects is the column, so recognising only the two helpers would
            # fail a path that does the right thing by hand.
            self.assertTrue(
                "describe(" in window or "refuse(" in window or "out = " in window,
                f"DoGive line {line_no + 1} refuses without writing `result`: {stripped}",
            )

    def test_the_five_outcomes_an_operator_must_tell_apart(self):
        body = _give_source()
        for reason in (
            "no carried item with that guid on the giver",  # item not found
            "receiver bags are full",                       # no room
            "item is soulbound",                            # never movable
            "receiver not online",                          # offline
            "giver and receiver are the same character",    # same character
        ):
            self.assertIn(reason, body, f"give cannot report: {reason}")

    def test_no_detail_literal_carries_a_quote(self):
        """`detail` is pasted into the UPDATE unescaped - see the comment on
        that statement. An apostrophe in one of these literals would break the
        report, or worse."""
        body = _give_source()
        # DoGive lost its `static` in #170; match on the part that is stable.
        body = body[body.index("char const* DoGive("):]
        statements = re.findall(r"\breturn\b[^;]*;", body, re.S)
        self.assertGreater(len(statements), 5, "the refusal paths went missing")
        checked = 0
        for statement in statements:
            for literal in re.findall(r'"((?:[^"\\]|\\.)*)"', statement):
                checked += 1
                self.assertNotIn(
                    "'", literal, f"a detail literal carries a quote: {statement.strip()}"
                )
        self.assertGreater(checked, 5, "no literals were actually inspected")


class TheMoveIsAtomic(unittest.TestCase):
    """Half an applied move is a duplicated or a vanished item."""

    def test_it_is_wrapped_in_one_character_database_transaction(self):
        body = _give_source()
        self.assertIn("CharacterDatabase.BeginTransaction()", body)
        self.assertIn("CharacterDatabase.CommitTransaction(trans)", body)

    def test_it_uses_the_send_mail_shape_and_not_the_give_item_shape(self):
        """GiveItemAction moves the item with no DB writes at all and lets the
        next periodic save catch up. SendMailAction deletes the old inventory
        row and re-saves the item inside the transaction. This is the second."""
        body = _give_source()
        self.assertIn("item->DeleteFromInventoryDB(trans)", body)
        self.assertIn("item->SaveToDB(trans)", body)

    def test_the_receivers_placement_is_written_in_the_same_transaction(self):
        """Without this the item is owned by the receiver and in no container
        until the receiver's next save, which is up to PlayerSaveInterval
        (900000ms) away."""
        body = _give_source()
        self.assertIn("REPLACE INTO character_inventory", body)

    def test_the_item_is_marked_changed_before_it_is_saved(self):
        """Player::RemoveItem does not change the item's state, and
        Item::SaveToDB writes nothing at all for ITEM_UNCHANGED. Without the
        SetState the owner change never reaches item_instance."""
        body = _give_source()
        save = body.index("item->SaveToDB(trans)")
        mark = body.index("item->SetState(ITEM_CHANGED)")
        self.assertLess(mark, save)

    def test_the_owner_is_reassigned_before_the_save(self):
        body = _give_source()
        self.assertLess(
            body.index("item->SetOwnerGUID(receiver->GetGUID())"),
            body.index("item->SaveToDB(trans)"),
        )

    def test_room_is_checked_before_anything_leaves_the_giver(self):
        """Asking after the item is already out of the giver's bags is how an
        item ends up owned by nobody."""
        body = _give_source()
        # #170 moved the hand-over into PlaceItemOn, which is DEFINED ABOVE
        # DoGive. A whole-file index comparison therefore now reads backwards
        # and would pass or fail on layout rather than on order of execution.
        # The invariant has not changed, so assert it where it actually lives:
        # inside DoGive, room is established before the item is placed.
        give = body[body.index("char const* DoGive("):]
        room = min(i for i in (give.find("receiver->CanStoreItem("),
                               give.find("CanWearContainer(receiver"))
                   if i >= 0)
        self.assertLess(room, give.index("PlaceItemOn(giver, receiver"))
        # And there is exactly ONE place the item can leave the giver, inside
        # that helper, so no other path can take it out of his bags first.
        # This is stronger than the original ordering check, which only
        # constrained the first of several possible move sites.
        self.assertEqual(1, body.count("giver->MoveItemFromInventory("))
        helper = body[body.index("PlaceItemOn(Player* giver"):]
        self.assertIn("giver->MoveItemFromInventory(", helper)


class TheEnumIsWidenedByAnExplicitAlter(unittest.TestCase):
    def test_the_migration_alters_rather_than_recreating(self):
        """CREATE TABLE IF NOT EXISTS is a no-op against an existing table, so
        an ENUM value added there never reaches a live database. This trap is
        already documented for overseer_goal.kind."""
        sql = MIGRATION.read_text(encoding="utf-8")
        self.assertIn("ALTER TABLE `overseer_command`", sql)
        self.assertIn("MODIFY COLUMN `kind`", sql)
        self.assertIn("'give'", sql)

    def test_it_keeps_every_kind_that_already_existed(self):
        """A MODIFY COLUMN that drops a value silently rewrites existing rows."""
        sql = MIGRATION.read_text(encoding="utf-8")
        for kind in ("'bot'", "'chat'", "'gm'", "'probe'"):
            self.assertIn(kind, sql)

    def test_the_default_is_unchanged(self):
        sql = MIGRATION.read_text(encoding="utf-8")
        self.assertIn("NOT NULL DEFAULT 'bot'", sql)


if __name__ == "__main__":
    unittest.main()
