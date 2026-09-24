"""Items a character must keep (overseer_keep), the bridge's half.

The case is the dev realm's: a paladin keeps an epic sword through a lowering
of his level, and none of the bridge's disposal passes may write a row that
sells, destroys, gives, mails, auctions or guild-banks it. The module refuses
such a row too; these tests pin that the bridge never writes one, and that a
failed read of the reservations does not make the sword fair game.
"""

import pathlib
import re
import unittest

import keep

HERE = pathlib.Path(__file__).resolve().parent.parent
SWORD_GUID = 4909901
SWORD_ENTRY = 647


def rows(*extra):
    return [
        {"character_name": "Grog", "item_entry": SWORD_ENTRY, "item_guid": SWORD_GUID},
        *extra,
    ]


class ReservedTest(unittest.TestCase):
    def test_a_row_naming_the_instance_is_reserved(self):
        r = keep.from_rows(rows())
        self.assertTrue(keep.reserved(r, "Grog", "guid:%d count:1" % SWORD_GUID))
        self.assertTrue(keep.reserved(r, "grog", "bank deposit guid:%d" % SWORD_GUID))

    def test_another_character_or_item_is_not(self):
        r = keep.from_rows(rows())
        self.assertFalse(keep.reserved(r, "Grug", "guid:%d count:1" % SWORD_GUID))
        self.assertFalse(keep.reserved(r, "Grog", "guid:12345 count:1"))

    def test_a_guid_reservation_does_not_reserve_the_whole_entry(self):
        r = keep.from_rows(rows())
        self.assertFalse(keep.reserved(r, "Grog", "entry:%d" % SWORD_ENTRY))

    def test_an_entry_reservation_covers_rows_naming_the_entry(self):
        r = keep.from_rows(
            [{"character_name": "Grog", "item_entry": SWORD_ENTRY, "item_guid": 0}]
        )
        self.assertTrue(keep.reserved(r, "Grog", "entry:%d" % SWORD_ENTRY))
        self.assertFalse(keep.reserved(r, "Grog", "entry:2901"))

    def test_a_reservation_naming_nothing_covers_nothing(self):
        r = keep.from_rows(
            [{"character_name": "Grog", "item_entry": 0, "item_guid": 0}]
        )
        self.assertFalse(keep.reserved(r, "Grog", "guid:0 entry:0"))

    def test_only_whole_words_are_read(self):
        self.assertEqual(keep.items_named("walk-to-vendor item:647 max:600"), ((), ()))
        self.assertEqual(keep.items_named("send guid:5 subject:x"), ((5,), ()))
        self.assertEqual(keep.items_named("buy entry:647 count:1"), ((), (647,)))
        self.assertEqual(keep.items_named("itemguid:5"), ((), ()))


class ReloadTest(unittest.TestCase):
    def test_read_once_a_minute(self):
        calls = []
        clock = [0.0]

        def fetch():
            calls.append(clock[0])
            return rows()

        k = keep.Keep(fetch, clock=lambda: clock[0])
        self.assertTrue(k.blocks("Grog", "guid:%d" % SWORD_GUID))
        clock[0] = 30.0
        k.blocks("Grog", "guid:1")
        self.assertEqual(len(calls), 1)
        clock[0] = 61.0
        k.blocks("Grog", "guid:1")
        self.assertEqual(len(calls), 2)

    def test_a_failed_read_keeps_the_last_list(self):
        state = {"fail": False}
        clock = [0.0]

        def fetch():
            if state["fail"]:
                raise RuntimeError("database went away")
            return rows()

        k = keep.Keep(fetch, clock=lambda: clock[0])
        self.assertTrue(k.blocks("Grog", "guid:%d" % SWORD_GUID))
        state["fail"] = True
        clock[0] = 120.0
        self.assertTrue(k.blocks("Grog", "guid:%d" % SWORD_GUID))

    def test_an_empty_table_frees_everything(self):
        data = {"rows": rows()}
        clock = [0.0]
        k = keep.Keep(lambda: data["rows"], clock=lambda: clock[0])
        self.assertTrue(k.blocks("Grog", "guid:%d" % SWORD_GUID))
        data["rows"] = []
        clock[0] = 61.0
        self.assertFalse(k.blocks("Grog", "guid:%d" % SWORD_GUID))


class WritersTest(unittest.TestCase):
    """Every writer that moves an item off its holder asks keep first."""

    WRITERS = (
        "_insert_destroy",
        "_insert_sell",
        "_insert_give",
        "_insert_guild_gift",
        "_insert_gear_handoff",
        "_insert_bag_give",
        "_insert_auction",
        "_insert_route",
        "_insert_guild",
        "_insert_corps_row",
        "_insert_crafter_row",
        "_insert_lockbox_row",
    )

    def test_each_disposal_writer_asks_before_it_writes(self):
        source = (HERE / "bridge.py").read_text()
        for name in self.WRITERS:
            with self.subTest(writer=name):
                match = re.search(
                    r"^def %s\(.*?(?=^def |\Z)" % name, source, re.S | re.M
                )
                self.assertIsNotNone(match, name)
                body = match.group(0)
                ask = body.find("_KEEP.blocks(")
                write = body.find("INSERT INTO overseer_command")
                self.assertGreater(ask, 0, name)
                self.assertLess(ask, write, name)


class BankPolicyTest(unittest.TestCase):
    """The guild bank's policy reads the same reservations (bankpolicy rule 0)."""

    def test_the_policy_read_is_handed_the_reservations(self):
        source = (HERE / "bridge.py").read_text()
        self.assertIn("reservations=_keep_reservations(cur, key)", source)

    def test_an_entry_reservation_reaches_the_policy_by_entry(self):
        import bankpolicy

        rows = [
            {
                "character_name": "Grog",
                "item_entry": SWORD_ENTRY,
                "until_level": 52,
                "reason": "kept",
            }
        ]
        got = bankpolicy.reservations_from_rows(rows, ["Grog"])
        self.assertEqual(
            [(r.character, r.item, r.until_level) for r in got],
            [("Grog", SWORD_ENTRY, 52)],
        )


if __name__ == "__main__":
    unittest.main()
