"""Dark Iron Legacy: a guild member earns the Shadowforge Key (#811).

Blackrock Depths' keyed doors open only for a member carrying the Shadowforge
Key (11000), and its one source is the quest Dark Iron Legacy. These are the
bridge's two decisions over it, asserted on rows without a database:

* a ghost guild member of level 48 or over beside Franclorn Forgewright (8888)
  takes 3801 from him, then 3802 once 3801 is rewarded;
* a member of a `blackrock-depths` guild run whose 3802 is complete (Ironfel,
  10999, carried) hands it in at the Shrine of Thaurissan (gameobject 164689).

Fixture rows. The world rows are a read-only live read of the dev realm,
2026-10-28: creature_queststarter names 8888 for 3801 and 3802,
creature_questender 8888 for 3801, gameobject_questender 164689 for 3802;
quest_template gives both MinLevel 48, 3802 PrevQuestID 3801 and RequiredItemId1
10999; creature 8888 spawns on map 0 at (-7596, -1115, 252.791) and gameobject
164689 on map 230 at (525.063, -238.897, -41.0423). The member rows carry the
columns mod-overseer writes to overseer_snapshot (health and max_health; a
released spirit's health is 1, apiv2/presence.py) and the core writes to
character_queststatus (status 1 complete, 3 incomplete) and
character_queststatus_rewarded. A guild run's members are the
`name:seat:class:level` list overseer_guild_run.members holds
(guildrun._member_list).
"""

import asyncio
import sqlite3
import types
import unittest
from unittest import mock

from _stub_modules import PYMYSQL, fresh_import, stub_modules

with stub_modules(pymysql=PYMYSQL):
    import dungeonquests as dq

FRANCLORN_ROW = {
    "kind": "creature",
    "map_id": 0,
    "pos_x": -7596.0,
    "pos_y": -1115.0,
    "pos_z": 252.791,
}
SHRINE_ROW = {
    "kind": "object",
    "map_id": 230,
    "pos_x": 525.063,
    "pos_y": -238.897,
    "pos_z": -41.0423,
}


def _snap(name, level=50, health=1, max_health=3200, at=FRANCLORN_ROW, dx=5.0):
    return {
        "name": name,
        "level": level,
        "health": health,
        "max_health": max_health,
        "map_id": at["map_id"],
        "pos_x": at["pos_x"] + dx,
        "pos_y": at["pos_y"],
        "pos_z": at["pos_z"],
    }


def _facts(snaps, log=(), rewarded=(), runs=(), recent=()):
    return dq.legacy_facts_from_rows(
        snaps,
        list(log),
        list(rewarded),
        [FRANCLORN_ROW, SHRINE_ROW],
        list(runs),
        list(recent),
    )


def _brd_run(*names):
    return {
        "keyword": "blackrock-depths",
        "members": ",".join("%s:dps:4:52" % n for n in names),
    }


class GhostAtFranclorn(unittest.TestCase):
    def test_a_ghost_of_48_or_over_takes_3801_by_name(self):
        rows = dq.legacy_rows(_facts([_snap("Brakk", level=48)]))
        self.assertIn(("Brakk", "take quest:3801"), rows)

    def test_the_tale_is_handed_back_and_the_legacy_taken_in_one_visit(self):
        """3801 has no objectives, so it is complete once taken; the rows go
        out in the order mod-overseer runs them (id order in one poll)."""
        rows = dq.legacy_rows(_facts([_snap("Brakk")]))
        self.assertEqual(
            rows,
            (
                ("Brakk", "take quest:3801"),
                ("Brakk", "turnin quest:3801"),
                ("Brakk", "take quest:3802"),
            ),
        )

    def test_a_living_member_gets_none(self):
        rows = dq.legacy_rows(_facts([_snap("Brakk", health=3200)]))
        self.assertEqual(rows, ())

    def test_a_corpse_not_yet_released_gets_none(self):
        rows = dq.legacy_rows(_facts([_snap("Brakk", health=0)]))
        self.assertEqual(rows, ())

    def test_a_member_under_48_gets_none(self):
        rows = dq.legacy_rows(_facts([_snap("Brakk", level=47)]))
        self.assertEqual(rows, ())

    def test_a_ghost_out_of_reach_gets_none(self):
        rows = dq.legacy_rows(_facts([_snap("Brakk", dx=60.0)]))
        self.assertEqual(rows, ())

    def test_a_member_with_3801_in_the_log_takes_no_3801(self):
        rows = dq.legacy_rows(
            _facts(
                [_snap("Brakk")],
                log=[{"name": "Brakk", "quest": 3801, "status": 1}],
            )
        )
        self.assertNotIn(("Brakk", "take quest:3801"), rows)
        self.assertEqual(
            rows, (("Brakk", "turnin quest:3801"), ("Brakk", "take quest:3802"))
        )

    def test_a_member_with_3802_gets_none(self):
        for log, rewarded in (
            ([{"name": "Brakk", "quest": 3802, "status": 3}], []),
            ([], [{"name": "Brakk", "quest": 3802}]),
        ):
            rows = dq.legacy_rows(
                _facts(
                    [_snap("Brakk")],
                    log=log,
                    rewarded=[{"name": "Brakk", "quest": 3801}] + rewarded,
                )
            )
            self.assertEqual(rows, ())

    def test_3802_is_taken_once_3801_is_rewarded(self):
        rows = dq.legacy_rows(
            _facts([_snap("Brakk")], rewarded=[{"name": "Brakk", "quest": 3801}])
        )
        self.assertEqual(rows, (("Brakk", "take quest:3802"),))

    def test_a_row_already_written_is_not_written_again(self):
        rows = dq.legacy_rows(
            _facts(
                [_snap("Brakk")],
                recent=[{"target_name": "Brakk", "command": "take quest:3801"}],
            )
        )
        self.assertNotIn(("Brakk", "take quest:3801"), rows)


class IronfelAtTheShrine(unittest.TestCase):
    def _at_shrine(self, name="Brakk"):
        return _snap(name, health=3200, at=SHRINE_ROW)

    def test_a_brd_run_with_ironfel_carried_hands_3802_in_at_the_shrine(self):
        rows = dq.legacy_rows(
            _facts(
                [self._at_shrine()],
                log=[{"name": "Brakk", "quest": 3802, "status": 1}],
                runs=[_brd_run("Brakk", "Ogg")],
            )
        )
        self.assertEqual(rows, (("Brakk", "turnin quest:3802"),))

    def test_a_run_without_3802_in_anyones_log_gets_none(self):
        rows = dq.legacy_rows(
            _facts([self._at_shrine()], runs=[_brd_run("Brakk", "Ogg")])
        )
        self.assertEqual(rows, ())

    def test_3802_without_ironfel_is_not_handed_in(self):
        rows = dq.legacy_rows(
            _facts(
                [self._at_shrine()],
                log=[{"name": "Brakk", "quest": 3802, "status": 3}],
                runs=[_brd_run("Brakk")],
            )
        )
        self.assertEqual(rows, ())

    def test_a_member_of_no_brd_run_hands_nothing_in(self):
        other = {"keyword": "scholomance", "members": "Brakk:dps:4:58"}
        rows = dq.legacy_rows(
            _facts(
                [self._at_shrine()],
                log=[{"name": "Brakk", "quest": 3802, "status": 1}],
                runs=[other],
            )
        )
        self.assertEqual(rows, ())

    def test_a_carrier_away_from_the_shrine_waits(self):
        rows = dq.legacy_rows(
            _facts(
                [_snap("Brakk", health=3200, at=SHRINE_ROW, dx=300.0)],
                log=[{"name": "Brakk", "quest": 3802, "status": 1}],
                runs=[_brd_run("Brakk")],
            )
        )
        self.assertEqual(rows, ())


class KeyHolder(unittest.TestCase):
    def test_a_member_handed_in_and_rewarded_carries_the_key(self):
        facts = _facts(
            [_snap("Brakk", health=3200, at=SHRINE_ROW)],
            rewarded=[{"name": "Brakk", "quest": 3802}],
        )
        self.assertEqual(dq.key_holders(facts, {"Brakk", "Ogg"}), ("Brakk",))

    def test_a_reward_this_bridge_did_not_hand_in_is_not_claimed(self):
        facts = _facts(
            [_snap("Brakk", health=3200)],
            rewarded=[{"name": "Brakk", "quest": 3802}],
        )
        self.assertEqual(dq.key_holders(facts, set()), ())


def _import_bridge():
    stub = types.ModuleType("discord")

    class Client:
        def __init__(self, *args, **kwargs):
            pass

    stub.Client = Client
    bridge = fresh_import("bridge", discord=stub, pymysql=PYMYSQL)
    return bridge


class _Pass:
    """The bridge instance the pass runs on: only its own attributes."""


class BridgePass(unittest.TestCase):
    """The pass writes the decided rows under its own source and says whose
    they are; the key line comes only once the Shrine hand-in is rewarded."""

    @classmethod
    def setUpClass(cls):
        cls.bridge = _import_bridge()

    def _run(self, host, facts):
        written = []

        def insert(name, said, source):
            written.append((name, said, source))
            return len(written)

        with (
            mock.patch.object(self.bridge, "_legacy_facts", lambda guilds: facts),
            mock.patch.object(self.bridge, "_insert_dungeonquest_row", insert),
            mock.patch.object(self.bridge.log, "info") as info,
        ):
            asyncio.run(self.bridge.Bridge._dark_iron_legacy_pass(host))
        return written, [c.args[0] % c.args[1:] for c in info.call_args_list]

    def test_the_ghost_take_and_the_key_holder_are_logged_by_name(self):
        host = _Pass()
        written, said = self._run(host, _facts([_snap("Brakk")]))
        self.assertIn(("Brakk", "take quest:3801", dq.LEGACY_SOURCE), written)
        self.assertTrue(any("Brakk" in s and "take quest:3801" in s for s in said))

        carrying = _facts(
            [_snap("Brakk", health=3200, at=SHRINE_ROW)],
            log=[{"name": "Brakk", "quest": 3802, "status": 1}],
            rewarded=[{"name": "Brakk", "quest": 3801}],
            runs=[_brd_run("Brakk")],
        )
        written, said = self._run(host, carrying)
        self.assertEqual(written, [("Brakk", "turnin quest:3802", dq.LEGACY_SOURCE)])
        self.assertFalse(any("Shadowforge Key" in s for s in said))

        rewarded = _facts(
            [_snap("Brakk", health=3200, at=SHRINE_ROW)],
            rewarded=[
                {"name": "Brakk", "quest": 3801},
                {"name": "Brakk", "quest": 3802},
            ],
        )
        written, said = self._run(host, rewarded)
        self.assertEqual(written, [])
        self.assertIn("dark iron legacy: Brakk now carries the Shadowforge Key", said)


FAMILY_SCHEMA = """
CREATE TABLE overseer_roster(name TEXT PRIMARY KEY, family TEXT, enabled INTEGER);
INSERT INTO overseer_roster VALUES
 ('Zug','Zug',1),('Zork','Zug',1),('Oz','Zug',1),('Benched','Zug',0),
 ('Grug','Grug',1),('Og','Grug',1);
CREATE TABLE overseer_dungeon_queue(
 id INTEGER PRIMARY KEY, family TEXT, keyword TEXT, status TEXT);
CREATE TABLE overseer_dungeon_run(
 id INTEGER PRIMARY KEY, leader_name TEXT, map_id INTEGER, state TEXT,
 members TEXT);
"""


class FamilyRun(unittest.TestCase):
    """A family's own Blackrock Depths run hands Ironfel in at the Shrine just
    as a guild run does (#1965). The family rows come from executing the
    bridge's real statement against the queue, roster and run tables."""

    @classmethod
    def setUpClass(cls):
        cls.bridge = _import_bridge()

    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(FAMILY_SCHEMA)
        self.carrier = _snap("Zork", health=3200, at=SHRINE_ROW)
        self.log = [{"name": "Zork", "quest": 3802, "status": 1}]
        self.guild_runs = []

    def _connect(self):
        """A connection whose family statement runs on sqlite; the other
        statements of the pass answer from the fixture rows."""
        subject = self

        class Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def execute(self, sql, params=()):
                if "overseer_dungeon_queue" in sql:
                    try:
                        rows = subject.db.execute(sql.replace("%s", "?"), params)
                    except sqlite3.OperationalError as error:
                        code = 1146 if "no such table" in str(error) else 1054
                        raise PYMYSQL.err.MySQLError(code, str(error)) from error
                    self.rows = [dict(r) for r in rows]
                elif "overseer_snapshot" in sql:
                    self.rows = [subject.carrier]
                elif "character_queststatus_rewarded" in sql:
                    self.rows = []
                elif "character_queststatus" in sql:
                    self.rows = list(subject.log)
                elif "acore_world.creature" in sql:
                    self.rows = [FRANCLORN_ROW, SHRINE_ROW]
                elif "overseer_guild_run" in sql:
                    self.rows = list(subject.guild_runs)
                else:
                    self.rows = []

            def fetchall(self):
                return self.rows

        class Connection:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def cursor(self):
                return Cursor()

        return Connection()

    def _rows(self):
        with mock.patch.object(self.bridge, "_connect", self._connect):
            facts = self.bridge._legacy_facts(["Bonkers"])
        return dq.legacy_rows(facts)

    def test_a_family_member_in_an_active_brd_queue_run_hands_3802_in(self):
        self.db.execute(
            "INSERT INTO overseer_dungeon_queue VALUES "
            "(129, 'Zug', 'blackrock-depths', 'active')"
        )
        self.assertEqual(self._rows(), (("Zork", "turnin quest:3802"),))

    def test_a_family_member_in_an_active_run_on_the_map_hands_3802_in(self):
        self.db.execute(
            "INSERT INTO overseer_dungeon_run VALUES "
            "(7, 'Zug', 230, 'active', 'Zug,Zork,Oz')"
        )
        self.assertEqual(self._rows(), (("Zork", "turnin quest:3802"),))

    def test_no_active_brd_run_of_any_kind_hands_nothing_in(self):
        self.db.executescript(
            "INSERT INTO overseer_dungeon_queue VALUES "
            "(129, 'Zug', 'blackrock-depths', 'queued'),"
            "(131, 'Zug', 'sunken-temple', 'active'),"
            "(130, 'Grug', 'blackrock-depths', 'active');"
            "INSERT INTO overseer_dungeon_run VALUES "
            "(7, 'Zug', 109, 'active', 'Zug,Zork,Oz'),"
            "(8, 'Zug', 230, 'ended', 'Zug,Zork,Oz');"
        )
        self.assertEqual(self._rows(), ())

    def test_the_guild_run_path_still_hands_in(self):
        self.guild_runs = [_brd_run("Zork", "Funky")]
        self.assertEqual(self._rows(), (("Zork", "turnin quest:3802"),))

    def test_an_older_ledger_without_the_columns_reads_no_family_run(self):
        self.db.execute("ALTER TABLE overseer_dungeon_run DROP COLUMN members")
        self.guild_runs = [_brd_run("Zork")]
        self.assertEqual(self._rows(), (("Zork", "turnin quest:3802"),))


if __name__ == "__main__":
    unittest.main()
