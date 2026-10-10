"""A guild vault aim is never a vault in the other side's capital.

Measured on the dev realm 2026-10-10 (read-only): the 22 Guild Vaults on
the two old continents carry three faction templates
(`gameobject_template_addon.faction`): 1732 in Stormwind, Ironforge and
Darnassus, 1735 in Undercity, Orgrimmar and Thunder Bluff, and 35 in Booty
Bay, Gadgetzan, Ratchet and Everlook. `_nearest_vault` ranked them by
distance alone. From Southshore or the Hinterlands an Alliance leader's
nearest vault is Undercity's; from Desolace or Feralas it is Thunder Bluff's.
The core lets anybody open any vault it stands at
(`Player::GetGameObjectIfCanInteractWith` has no faction check), so nothing
downstream stops the walk into the other side's guards.

Until #750 the guild bank pass never walked (no gold deposits, a full tab).
With withdrawals it walks Cave's guild master to the nearest vault on every
cycle while the vault has stacks to list.

Pinned here: the reader returns the nearest spawns with their faction and the
character's race, and the pure pick skips a vault of the other side's
faction. A neutral vault, or one with no faction row, is anybody's.
"""

import pathlib
import sys
import types
import unittest

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import travel  # noqa: E402

BRIDGE = pathlib.Path(__file__).resolve().parents[1] / "bridge.py"
HUMAN, NIGHT_ELF, ORC, TAUREN = 1, 4, 2, 6


def vault(name, faction, d2, race):
    return {
        "map_id": 0,
        "x": 0.0,
        "y": 0.0,
        "z": 0.0,
        "d2": d2,
        "faction": faction,
        "race": race,
        "where": name,
    }


class TheOwnSidesVault(unittest.TestCase):
    def test_an_alliance_leader_in_the_hinterlands_skips_undercity(self):
        rows = [
            vault("Undercity", 1735, 5.2e6, HUMAN),
            vault("Undercity", 1735, 5.3e6, HUMAN),
            vault("Ironforge", 1732, 2.7e7, HUMAN),
        ]
        self.assertEqual("Ironforge", travel.own_side_vault(rows)["where"])

    def test_an_alliance_leader_in_desolace_skips_thunder_bluff(self):
        rows = [
            vault("Thunder Bluff", 1735, 3.6e6, NIGHT_ELF),
            vault("Ratchet", 35, 2.6e7, NIGHT_ELF),
        ]
        self.assertEqual("Ratchet", travel.own_side_vault(rows)["where"])

    def test_a_horde_leader_skips_stormwind(self):
        rows = [
            vault("Stormwind", 1732, 1.0e6, ORC),
            vault("Booty Bay", 35, 2.0e7, ORC),
        ]
        self.assertEqual("Booty Bay", travel.own_side_vault(rows)["where"])

    def test_the_nearest_own_or_neutral_vault_is_kept(self):
        rows = [
            vault("Orgrimmar", 1735, 1.0e6, TAUREN),
            vault("Thunder Bluff", 1735, 2.0e6, TAUREN),
        ]
        self.assertEqual("Orgrimmar", travel.own_side_vault(rows)["where"])
        rows = [vault("a vault with no faction row", None, 1.0, HUMAN)]
        self.assertEqual(
            "a vault with no faction row", travel.own_side_vault(rows)["where"]
        )

    def test_only_the_other_sides_vaults_is_no_vault(self):
        rows = [vault("Undercity", 1735, 1.0, HUMAN)]
        self.assertIsNone(travel.own_side_vault(rows))
        self.assertIsNone(travel.own_side_vault([]))


class TheReaderWiring(unittest.TestCase):
    def setUp(self):
        src = BRIDGE.read_text(encoding="utf-8")
        self.sql = src[src.index("_VAULT_SQL = (") : src.index("def _nearest_vault")]
        reader = src[src.index("def _nearest_vault") :]
        self.reader = reader[: reader.index("\ndef ")]

    def test_the_reader_reads_each_vaults_faction_and_the_race(self):
        self.assertIn("acore_world.gameobject_template_addon", self.sql)
        self.assertIn("AS faction", self.sql)
        self.assertIn("s.race AS race", self.sql)
        self.assertNotIn('LIMIT 1"', self.sql)

    def test_the_reader_picks_through_the_pure_rule(self):
        self.assertIn("travel.own_side_vault(", self.reader)


if __name__ == "__main__":
    unittest.main()
