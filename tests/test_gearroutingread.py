"""The routing pass's reads (gearroutingread.py), moved out of map_server.py
so the site and the bridge read the report's inputs the same way.

Pinned as a pure move: the SQL each read sends is fingerprinted against what
map_server.py sent before the move, and the read is driven through a fake
session to pin the order, parameters and fallback.
"""

import hashlib
import unittest

import gearroutingread as grr


def _h(sql):
    return hashlib.sha256(sql.encode()).hexdigest()[:16]


HOLES = "%s, %s"


class TheSqlIsUnchanged(unittest.TestCase):
    def test_wearers_with_the_raid_tree(self):
        sql = grr.WEARERS.format(holes=HOLES, target=grr.RAID_TREE)
        self.assertEqual(_h(sql), "47d105cacc7fea51")

    def test_wearers_without_the_raid_tree(self):
        sql = grr.WEARERS.format(holes=HOLES, target="''")
        self.assertEqual(_h(sql), "a2b07cd374c4a213")

    def test_gear(self):
        self.assertEqual(_h(grr.GEAR.format(holes=HOLES)), "e1ec7bacc0c2795b")

    def test_bank(self):
        self.assertEqual(_h(grr.BANK.format(holes=HOLES)), "76da056fc8509f81")

    def test_the_read_carries_the_binding_facts(self):
        """A routing read without the template's bonding and the instance's
        flags cannot tell a movable copy from a bound one, which is the whole
        safety of the pass."""
        self.assertIn("it.bonding AS bonding", grr.GEAR)
        self.assertIn("ii.flags AS instance_flags", grr.GEAR)
        self.assertIn("it.bonding AS bonding", grr.BANK)
        self.assertIn("ii.flags AS instance_flags", grr.BANK)

    def test_the_read_covers_every_guild_member_not_only_the_families(self):
        self.assertIn("guild_member", grr.WEARERS)
        self.assertIn("guild_member", grr.GEAR)


class FakeSession:
    def __init__(self):
        self.calls = []

    def rows(self, sql, params, fallback=None, what=""):
        self.calls.append((_h(sql), tuple(params), fallback is not None, what))
        return [{"what": what}]


class TheReadOrder(unittest.TestCase):
    def test_read_asks_wearers_gear_bank_in_order(self):
        rd = FakeSession()
        wearers, gear, bank = grr.read(rd, ["Grug", "Zug"])
        self.assertEqual(
            [c[3] for c in rd.calls],
            ["routing wearers", "routing gear", "guild_bank_item routing"],
        )
        self.assertEqual(rd.calls[0][1], ("Grug", "Zug"))
        self.assertTrue(rd.calls[0][2])  # wearers carry a fallback
        self.assertFalse(rd.calls[1][2])
        self.assertEqual(rd.calls[0][0], "47d105cacc7fea51")
        self.assertEqual(rd.calls[1][0], "e1ec7bacc0c2795b")
        self.assertEqual(rd.calls[2][0], "76da056fc8509f81")
        self.assertEqual(wearers, [{"what": "routing wearers"}])
        self.assertEqual(bank, [{"what": "guild_bank_item routing"}])


class TheSiteUsesIt(unittest.TestCase):
    def test_map_server_reads_through_the_shared_module(self):
        import pathlib

        src = (pathlib.Path(__file__).resolve().parents[1] / "map_server.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("gearroutingread.read(", src)
        self.assertNotIn("_ROUTING_WEARERS", src)
        self.assertEqual(src.count("import gearroutingread"), 1)


class ThePayloadShapeIsUnchanged(unittest.TestCase):
    """/api/guildrouting answers the same keys, in the same order, as it did
    when the reads lived in map_server.py."""

    KEYS = [
        "min_gain",
        "members",
        "judged",
        "unjudged",
        "candidates",
        "notes",
        "routes",
        "headline",
        "lines",
        "execution",
    ]

    def _fetch(self, names):
        import map_server

        class Fam:
            @staticmethod
            def names():
                return names

        class Sess:
            def __init__(self, _connect):
                pass

            def __enter__(self):
                return FakeEmpty()

            def __exit__(self, *a):
                return False

        saved = (map_server.FAMILIES, map_server.realmread.Session)
        map_server.FAMILIES, map_server.realmread.Session = Fam, Sess
        try:
            return map_server._fetch_guild_routing()
        finally:
            map_server.FAMILIES, map_server.realmread.Session = saved

    def test_a_guild_with_rows_answers_the_full_shape(self):
        payload = self._fetch(["Grug"])
        self.assertEqual(list(payload), self.KEYS)

    def test_no_families_answers_the_bare_build(self):
        payload = self._fetch([])
        self.assertEqual(list(payload), self.KEYS[:7])


class FakeEmpty:
    def rows(self, sql, params, fallback=None, what=""):
        return []


if __name__ == "__main__":
    unittest.main()
