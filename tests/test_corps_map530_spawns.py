"""Map 530 trainer/vendor spawns resolve starting-land zones from coordinates (#2446)."""

import pathlib
import sqlite3
import sys
import types
import unittest

from _stub_modules import PYMYSQL, fresh_import, stub_modules

HERE = pathlib.Path(__file__).resolve().parent.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))


def _import_bridge():
    stub = types.ModuleType("discord")
    stub.Intents = types.SimpleNamespace(default=lambda: None)

    class Client:
        def __init__(self, *args, **kwargs):
            pass

    stub.Client = Client
    return fresh_import("bridge", discord=stub, pymysql=PYMYSQL)


bridge = _import_bridge()

with stub_modules(pymysql=PYMYSQL):
    import classic
    import guildcorps
    import transform


# Real acore_world.creature spawns on map 530, all carrying zoneId = 0 in DB
# on wow-dev (read 2026-11-15), paired with Map::GetZoneId ground truth from
# AreaTable.dbc + worldserver 530*.map tiles.
STARTING_TRAINERS = (
    # Eversong Woods (3430): Julia Sunstriker
    {
        "map_id": 530,
        "zone_id": 0,
        "x": 10337.2,
        "y": -6419.45,
        "spell": 116,
        "expected_zone": classic.EVERSONG_WOODS,
    },
    # Silvermoon City (3487): Sedana
    {
        "map_id": 530,
        "zone_id": 0,
        "x": 9962.51,
        "y": -7247.43,
        "spell": 7414,
        "expected_zone": classic.SILVERMOON_CITY,
    },
    # Azuremyst Isle (3524): Aurelon
    {
        "map_id": 530,
        "zone_id": 0,
        "x": -4103.19,
        "y": -13744.2,
        "spell": 465,
        "expected_zone": classic.AZUREMYST_ISLE,
    },
    # The Exodar (3557): Miall
    {
        "map_id": 530,
        "zone_id": 0,
        "x": -4243.9,
        "y": -11706.7,
        "spell": 2020,
        "expected_zone": classic.THE_EXODAR,
    },
    # Bloodmyst Isle (3525): Anchorite Paetheus
    {
        "map_id": 530,
        "zone_id": 0,
        "x": -1931.62,
        "y": -11858.3,
        "spell": 3276,
        "expected_zone": classic.BLOODMYST_ISLE,
    },
)

OUTLAND_TRAINERS = (
    # Hellfire Peninsula (3483): Michael Schwan
    {
        "map_id": 530,
        "zone_id": 0,
        "x": -773.806,
        "y": 2751.21,
        "spell": 45375,
        "expected_zone": 3483,
    },
)

STARTING_VENDORS = (
    # Silvermoon City (3487): Melaris
    {
        "map_id": 530,
        "zone_id": 0,
        "x": 9996.41,
        "y": -7214.27,
        "item": 765,
        "expected_zone": classic.SILVERMOON_CITY,
    },
    # Ghostlands (3433): Provisioner Vredigar
    {
        "map_id": 530,
        "zone_id": 0,
        "x": 7555.68,
        "y": -6857.73,
        "item": 22985,
        "expected_zone": classic.GHOSTLANDS,
    },
    # The Exodar (3557): Oss
    {
        "map_id": 530,
        "zone_id": 0,
        "x": -4051.54,
        "y": -11552.8,
        "item": 5208,
        "expected_zone": classic.THE_EXODAR,
    },
)

OUTLAND_VENDORS = (
    # Hellfire Peninsula (3483): Cookie One-Eye
    {
        "map_id": 530,
        "zone_id": 0,
        "x": 62.0795,
        "y": 2719.01,
        "item": 8766,
        "expected_zone": 3483,
    },
    # Shattrath City (3703): Brendan Turner
    {
        "map_id": 530,
        "zone_id": 0,
        "x": -2076.77,
        "y": 5343.28,
        "item": 117,
        "expected_zone": 3703,
    },
    # Isle of Quel'Danas / Sunwell (4080): Kaalif (level-70 zone, not starting land)
    {
        "map_id": 530,
        "zone_id": 0,
        "x": 12845.9,
        "y": -7005.7,
        "item": 5565,
        "expected_zone": 4080,
    },
)


class _DictCursor:
    def __init__(self, cur):
        self._cur = cur

    def execute(self, sql, params=()):
        self._cur.execute(sql.replace("%s", "?"), params)

    def fetchall(self):
        cols = [d[0] for d in (self._cur.description or ())]
        return [dict(zip(cols, row)) for row in self._cur.fetchall()]


def _world_db() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.execute("ATTACH DATABASE ':memory:' AS acore_world")
    db.execute(
        "CREATE TABLE acore_world.creature ("
        "guid INTEGER, id INTEGER, map INTEGER, zoneId INTEGER, "
        "position_x REAL, position_y REAL)"
    )
    db.execute(
        "CREATE TABLE acore_world.creature_default_trainer ("
        "CreatureId INTEGER, TrainerId INTEGER)"
    )
    db.execute(
        "CREATE TABLE acore_world.trainer_spell (TrainerId INTEGER, SpellId INTEGER)"
    )
    db.execute("CREATE TABLE acore_world.npc_vendor (entry INTEGER, item INTEGER)")
    return db


class Map530ZoneResolution(unittest.TestCase):
    def test_zone_id_at_matches_dbc_ground_truth_for_spawns(self):
        for row in (
            STARTING_TRAINERS + OUTLAND_TRAINERS + STARTING_VENDORS + OUTLAND_VENDORS
        ):
            got = transform.zone_id_at(530, row["x"], row["y"])
            self.assertEqual(got, row["expected_zone"], row)

    def test_places_keep_starting_land_trainers_with_zero_zone(self):
        rows = list(STARTING_TRAINERS) + list(OUTLAND_TRAINERS)
        got = guildcorps.places_from_rows(rows, "spell")
        self.assertEqual(
            got,
            {530: frozenset(r["spell"] for r in STARTING_TRAINERS)},
        )

    def test_places_keep_starting_land_vendors_with_zero_zone_and_drop_outland(self):
        rows = list(STARTING_VENDORS) + list(OUTLAND_VENDORS)
        got = guildcorps.places_from_rows(rows, "item")
        self.assertEqual(
            got,
            {530: frozenset(r["item"] for r in STARTING_VENDORS)},
        )

    def test_corps_sql_carries_coords_and_feeds_places_end_to_end(self):
        db = _world_db()
        try:
            db.executemany(
                "INSERT INTO acore_world.creature VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (1, 16633, 530, 0, 9962.51, -7247.43),  # Silvermoon trainer
                    (2, 16501, 530, 0, -4103.19, -13744.2),  # Azuremyst trainer
                    (3, 30721, 530, 0, -773.806, 2751.21),  # Hellfire trainer
                    (4, 16641, 530, 0, 9996.41, -7214.27),  # Silvermoon vendor
                    (5, 16632, 530, 0, -4051.54, -11552.8),  # Exodar vendor
                    (6, 23263, 530, 0, -2076.77, 5343.28),  # Shattrath vendor
                    (7, 25039, 530, 0, 12845.9, -7005.7),  # Quel'Danas vendor
                ],
            )
            db.executemany(
                "INSERT INTO acore_world.creature_default_trainer VALUES (?, ?)",
                [(16633, 1), (16501, 2), (30721, 3)],
            )
            db.executemany(
                "INSERT INTO acore_world.trainer_spell VALUES (?, ?)",
                [(1, 7414), (2, 465), (3, 45375)],
            )
            db.executemany(
                "INSERT INTO acore_world.npc_vendor VALUES (?, ?)",
                [(16641, 765), (16632, 5208), (23263, 117), (25039, 5565)],
            )
            cur = _DictCursor(db.cursor())
            trainable = bridge._corps_read(
                cur,
                "trainers",
                bridge._CORPS_TRAINABLE_SQL.format(spells="7414,465,45375"),
            )
            vendors = bridge._corps_read(
                cur,
                "vendors",
                bridge._CORPS_VENDORS_SQL.format(entries="765,5208,117,5565"),
            )
        finally:
            db.close()
        self.assertEqual(
            guildcorps.places_from_rows(trainable, "spell"),
            {530: frozenset({7414, 465})},
        )
        self.assertEqual(
            guildcorps.places_from_rows(vendors, "item"),
            {530: frozenset({765, 5208})},
        )


if __name__ == "__main__":
    unittest.main()
