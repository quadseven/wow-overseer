"""The item plan's GIVE route stops handing the same piece around (#2605 follow-up).

Measured on the dev realm on 2026-11-15 over three hours: 64 give rows, 14 of
them errors, and the same pieces moving between the same few members. Three
belts of one kind all went to one member in one pass, one sash was given to
the same member twice, and an axe went to one member, then another, then back.
A piece moved in the last few hours is left where it is, a member is not
handed a second copy of gear it already carries unless it can wear both, and
a give is held while the receiver's bags are full.
"""

from __future__ import annotations

import pathlib
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import guildshare  # noqa: E402
import itemplan  # noqa: E402
import itemplan_shadow as shadow  # noqa: E402
from test_itemplan_shadow import import_bridge  # noqa: E402

BELT, RING = 5001, 5002
TEMPLATES = {
    BELT: {"item_class": 4, "inventory_type": 6},
    RING: {"item_class": 4, "inventory_type": 11},
    7001: {"item_class": 7, "inventory_type": 0},
}


def gift(guid, holder="Zrog", taker="Zork", entry=BELT, count=1):
    return guildshare.Gift(
        holder=holder,
        taker=taker,
        item="Piece",
        entry=entry,
        count=count,
        guid=guid,
        need="r",
        reason="r",
    )


def vet(gifts, carried=(), recent=(), free=None):
    return shadow.vet_gifts(
        gifts,
        carried=list(carried),
        templates=TEMPLATES,
        recent=frozenset(recent),
        free_slots=free or {"Zork": 10, "Oz": 10},
    )


class ThePieceMovedRecently(unittest.TestCase):
    def test_a_guid_given_inside_the_window_is_held(self):
        kept, held = vet([gift(1)], recent={1})
        self.assertEqual(kept, [])
        self.assertEqual(len(held), 1)
        self.assertIn("recently", held[0][1])

    def test_a_guid_not_moved_goes(self):
        kept, held = vet([gift(1)], recent={2})
        self.assertEqual([g.guid for g in kept], [1])
        self.assertEqual(held, [])


class TheSecondCopy(unittest.TestCase):
    def test_gear_the_taker_already_carries_is_held(self):
        carried = [{"holder": "Zork", "entry": BELT}]
        kept, held = vet([gift(1)], carried=carried)
        self.assertEqual(kept, [])
        self.assertIn("already", held[0][1])

    def test_three_copies_in_one_pass_send_one(self):
        kept, held = vet([gift(1), gift(2), gift(3)])
        self.assertEqual([g.guid for g in kept], [1])
        self.assertEqual(len(held), 2)

    def test_a_ring_can_be_worn_twice_so_a_second_goes(self):
        carried = [{"holder": "Zork", "entry": RING}]
        kept, _ = vet([gift(1, entry=RING)], carried=carried)
        self.assertEqual(len(kept), 1)

    def test_a_material_the_taker_holds_still_goes(self):
        carried = [{"holder": "Zork", "entry": 7001}]
        kept, _ = vet([gift(1, entry=7001, count=5)], carried=carried)
        self.assertEqual(len(kept), 1)


class TheReceiversBags(unittest.TestCase):
    def test_a_full_receiver_is_held(self):
        kept, held = vet([gift(1)], free={"Zork": 0})
        self.assertEqual(kept, [])
        self.assertIn("no room", held[0][1])

    def test_room_is_spent_as_gifts_are_kept(self):
        gifts = [gift(1, entry=BELT), gift(2, entry=RING)]
        kept, held = vet(gifts, free={"Zork": 1})
        self.assertEqual([g.guid for g in kept], [1])
        self.assertEqual(len(held), 1)

    def test_a_guildmate_outside_the_family_is_not_judged_on_room(self):
        kept, _ = vet([gift(1, taker="Stranger")], free={"Zork": 0})
        self.assertEqual(len(kept), 1)


class TheExecutorUsesIt(unittest.IsolatedAsyncioTestCase):
    async def test_a_recently_moved_piece_is_not_written(self):
        bridge = import_bridge()
        rows = [
            {
                "holder": "Zrog",
                "item_guid": 11,
                "entry": BELT,
                "name": "Belt",
                "quality": 2,
                "count": 1,
                "sell_price": 10,
                "item_class": 4,
            }
        ]
        written = []
        executor = SimpleNamespace(
            _write_guild_gifts=mock.AsyncMock(
                side_effect=lambda gifts: written.extend(gifts)
            ),
        )
        plan = SimpleNamespace(
            decisions=[
                SimpleNamespace(
                    key=("Zrog", 1, BELT, 0),
                    route=itemplan.GIVE,
                    target="Zork",
                    holder="Zrog",
                    entry=BELT,
                    name="Belt",
                    count=1,
                    reason="r",
                )
            ]
        )
        extras = shadow.Extras(
            open_quest_items={},
            market={},
            templates=TEMPLATES,
            instance_soulbound={11: False},
            fire_gear=frozenset(),
            guild_free={},
            guild_crafters=(),
        )
        with (
            mock.patch.object(
                bridge.itemplan_shadow, "give_enabled", return_value=True
            ),
            mock.patch.object(bridge, "_itemplan_reads", return_value=extras),
            mock.patch.object(
                bridge.itemplan_shadow,
                "shadow",
                return_value=SimpleNamespace(plan=plan),
            ),
            mock.patch.object(bridge, "_recently_given_guids", return_value={11}),
        ):
            await bridge.Bridge._itemplan_give(
                executor, ["Zrog", "Zork"], "Zug", rows, {"Zork": 10}
            )
        self.assertEqual(written, [])
        executor._write_guild_gifts.assert_not_awaited()


class TheHistoryRead(unittest.TestCase):
    def test_a_give_and_a_letter_both_name_their_guid_and_errors_are_skipped(self):
        bridge = import_bridge()

        class Cursor:
            sql = ""

            def execute(self, sql, params=None):
                Cursor.sql = sql

            def fetchall(self):
                return [
                    {"command": "guid:204233877"},
                    {"command": "send item:203879679 subject:Warlord's Axe"},
                    {"command": "unrelated"},
                ]

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        conn = mock.MagicMock()
        conn.__enter__.return_value = conn
        conn.cursor.return_value = Cursor()
        with mock.patch.object(bridge, "_connect", return_value=conn):
            got = bridge._recently_given_guids(12)
        self.assertEqual(got, frozenset({204233877, 203879679}))
        self.assertIn("status <> 'error'", Cursor.sql)


if __name__ == "__main__":
    unittest.main()
