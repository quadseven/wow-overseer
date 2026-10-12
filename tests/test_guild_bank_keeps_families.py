"""Guild bank keeps are per family (#855): one family's share pass never
removes another family's keeps."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from test_guildsocial_bridge import bridge  # noqa: E402

FAMILY_A = ["Aone", "Atwo"]
FAMILY_B = ["Bone"]


class GuildBankKeepsPerFamilyTests(unittest.TestCase):
    def setUp(self):
        bridge._GUILD_BANK_KEEPS.clear()
        bridge._GUILD_BANK_KEEPS_BY_FAMILY.clear()
        self.addCleanup(bridge._GUILD_BANK_KEEPS.clear)
        self.addCleanup(bridge._GUILD_BANK_KEEPS_BY_FAMILY.clear)

    def test_a_keeps_survive_b_with_and_without_surplus_gear(self):
        bridge._set_guild_bank_keeps(FAMILY_A, {101: "for a guildmate"})
        bridge._set_guild_bank_keeps(FAMILY_B, {})
        self.assertIn(101, bridge._GUILD_BANK_KEEPS)
        bridge._set_guild_bank_keeps(FAMILY_B, {202: "other piece"})
        self.assertIn(101, bridge._GUILD_BANK_KEEPS)
        self.assertIn(202, bridge._GUILD_BANK_KEEPS)

    def test_a_own_pass_drops_its_stale_keeps(self):
        bridge._set_guild_bank_keeps(FAMILY_A, {101: "old"})
        bridge._set_guild_bank_keeps(FAMILY_B, {202: "b"})
        bridge._set_guild_bank_keeps(FAMILY_A, {303: "new"})
        self.assertEqual(set(bridge._GUILD_BANK_KEEPS), {202, 303})
        bridge._set_guild_bank_keeps(FAMILY_A, {})
        self.assertEqual(set(bridge._GUILD_BANK_KEEPS), {202})


if __name__ == "__main__":
    unittest.main()
