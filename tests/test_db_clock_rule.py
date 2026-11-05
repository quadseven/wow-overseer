"""One clock for a database timestamp, whatever the container's TZ (#1843).

The rule (realmread's module docstring, THE CLOCK): a naive DATETIME read from
MySQL is on the database session's clock, so the "now" it is compared with is
the database's own NOW(), read in the same session. A pure function that takes
`now=` defaults to naive UTC, never the container-local clock.

On main the recap passed the pod's naive local datetime.now() as `now`, and
seven builders defaulted to it, while gear.py read the same rows as UTC. With
the image's TZ unset every clock is UTC and the split is invisible; this suite
sets a zone nine hours east of UTC, where on main every member of a live run
read stale and every run stalled.

"JST-9" is a POSIX TZ string (UTC+9), so it needs no tz database.
"""

import os
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from _stub_modules import PYMYSQL, stub_modules

with stub_modules(pymysql=PYMYSQL):
    import agenda
    import gear
    import map_server
    import partystatus
    import realmread

EAST = "JST-9"
FAMILY = ["Grug", "Bork", "Grog", "Og", "Ugga"]


def _utc_naive():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class _InZone:
    """Run the body with TZ set to `zone`, then put the old TZ back."""

    def __init__(self, zone):
        self.zone = zone

    def __enter__(self):
        self.old = os.environ.get("TZ")
        os.environ["TZ"] = self.zone
        time.tzset()
        return self

    def __exit__(self, *exc):
        if self.old is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = self.old
        time.tzset()
        return False


class TheZoneReallyMoves(unittest.TestCase):
    def test_the_east_zone_moves_the_local_clock(self):
        """Without this the suite below proves nothing."""
        with _InZone(EAST):
            gap = datetime.now() - _utc_naive()
        self.assertGreater(gap, timedelta(hours=8))


class _Cur:
    """A cursor whose database runs UTC: rows by table, NOW() on its clock."""

    def __init__(self, db_now, runs, snaps):
        self.db_now, self.runs, self.snaps = db_now, runs, snaps
        self.sql = ""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=()):
        self.sql = sql

    def fetchall(self):
        if self.sql == realmread.DB_NOW_SQL:
            return [{"db_now": self.db_now}]
        if "overseer_dungeon_run" in self.sql:
            return list(self.runs)
        if "FROM overseer_snapshot" in self.sql:
            return list(self.snaps)
        return []


class TheRecap(unittest.TestCase):
    def _recap(self):
        db_now = _utc_naive()
        started = db_now - timedelta(minutes=30)
        runs = [
            {
                "id": 7,
                "leader_name": "Grug",
                "map_id": 36,
                "state": "active",
                "started_at": started,
                "last_progress_at": db_now - timedelta(minutes=2),
                "ended_at": None,
                "ended_reason": "",
                "outcome": "",
            }
        ]
        snaps = [
            {
                "name": name,
                "level": 20,
                "map_id": 36,
                "health": 100,
                "max_health": 100,
                "in_combat": 0,
                "updated_at": db_now - timedelta(seconds=10),
            }
            for name in FAMILY
        ]
        conn = mock.MagicMock()
        conn.cursor.return_value = _Cur(db_now, runs, snaps)
        with mock.patch.object(map_server, "_connect", return_value=conn):
            payload = map_server.Handler._recap_for(None, FAMILY)
        return payload

    def _decisions(self, payload):
        stale = [m["name"] for m in payload["party"] if m.get("stale")]
        return payload["live"], payload["run"]["stalled"], stale

    def test_stale_and_stalled_decide_the_same_east_of_utc(self):
        with _InZone("UTC0"):
            utc = self._decisions(self._recap())
        with _InZone(EAST):
            east = self._decisions(self._recap())
        self.assertEqual(utc, (True, False, []))
        self.assertEqual(east, utc)

    def test_the_recap_read_returns_the_database_clock(self):
        db_now = datetime(2026, 1, 2, 3, 4, 5)
        conn = mock.MagicMock()
        conn.cursor.return_value = _Cur(db_now, [], [])
        with mock.patch.object(map_server, "_connect", return_value=conn):
            fetched = map_server._fetch_recap(None, FAMILY)
        self.assertEqual(fetched["now"], db_now)


class TheReaderClock(unittest.TestCase):
    def test_db_now_is_the_database_value(self):
        at = datetime(2026, 1, 2, 3, 4, 5)
        rd = realmread.Memory({realmread.DB_NOW_SQL: [{"db_now": at}]})
        self.assertEqual(rd.db_now(), at)

    def test_db_now_with_no_answer_is_naive_utc(self):
        rd = realmread.Memory({realmread.DB_NOW_SQL: []})
        with _InZone(EAST):
            got = rd.db_now()
        self.assertIsNone(got.tzinfo)
        self.assertLess(abs(got - _utc_naive()), timedelta(minutes=1))


class TheBuilderDefaults(unittest.TestCase):
    """A builder called with no `now` reads naive UTC, not the local clock."""

    def _agenda(self):
        moved = _utc_naive() - timedelta(minutes=1)
        roster = [
            {"name": n, "family": "Grug", "enabled": 1, "lead": int(n == "Grug")}
            for n in FAMILY
        ]
        events = [{"kind": "quest_accept", "last_seen": moved}]
        return agenda.build_agenda(roster, [], [], [], [], events, {})

    def test_agenda_is_not_stalled_east_of_utc(self):
        with _InZone("UTC0"):
            utc = self._agenda()["stalled"]
        with _InZone(EAST):
            east = self._agenda()["stalled"]
        self.assertFalse(utc)
        self.assertEqual(east, utc)

    def test_party_status_is_not_stalled_east_of_utc(self):
        moved = _utc_naive() - timedelta(minutes=1)
        roster = [
            {"name": n, "family": "Grug", "enabled": 1, "lead": int(n == "Grug")}
            for n in FAMILY
        ]
        events = [{"kind": "quest_accept", "last_seen": moved}]
        with _InZone(EAST):
            push = partystatus.build_push(roster, [], events)
        self.assertNotIn("stalled", str(push).lower())

    def test_no_builder_defaults_to_the_local_clock(self):
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for name in (
            "achievements",
            "agenda",
            "council",
            "decree",
            "eye",
            "realm",
            "partystatus",
        ):
            with self.subTest(module=name):
                with open(os.path.join(here, name + ".py"), encoding="utf-8") as f:
                    text = f.read()
                self.assertNotIn("now or datetime.now()", text)


STAFF = gear.Equip(
    holder="Cronk",
    guid=7001,
    entry=7757,
    name="Odo's Ley Staff",
    slot="two_hand",
    item_level=30,
    worn_level=24,
    reason="a two-hander beats the main hand and shield",
)
KEY = ("Cronk", STAFF.command)
WORN = {"Cronk": {15: (5197, "Cookie's Tenderizer"), 16: (15524, "War Paint Shield")}}


def _gear_pass(created, holds, now=None):
    """One equip pass over a passing refusal (a 15 minute hold) stamped
    `created` by the database, naive, as a real row arrives."""
    answers = {
        KEY: {
            "id": 41,
            "target_name": "Cronk",
            "command": STAFF.command,
            "status": "error",
            "detail": "InventoryResult 36",
            "created_at": created,
        }
    }
    queued, _notes = gear.equips_to_queue(
        (STAFF,),
        set(),
        {KEY: 3},
        answers=answers,
        worn=WORN,
        holds=holds,
        now=now,
        online={"Cronk"},
        free_slots={"Cronk": 4},
    )
    return queued


class TheGearCooldown(unittest.TestCase):
    def _held(self):
        holds = {}
        return _gear_pass(_utc_naive() - timedelta(minutes=2), holds) == ()

    def test_the_cooldown_decides_the_same_east_of_utc(self):
        with _InZone("UTC0"):
            utc = self._held()
        with _InZone(EAST):
            east = self._held()
        self.assertTrue(utc)
        self.assertEqual(east, utc)

    def test_a_naive_database_now_is_taken(self):
        """A caller that read NOW() hands it over naive, as the row is."""
        db_now = datetime(2026, 1, 2, 3, 4, 5)
        created = db_now - timedelta(minutes=2)
        holds = {}
        self.assertEqual(_gear_pass(created, holds, now=db_now), ())
        later = db_now + timedelta(minutes=10)
        self.assertEqual(_gear_pass(created, holds, now=later), ())
        after = db_now + timedelta(minutes=20)
        self.assertEqual(_gear_pass(created, holds, now=after), (STAFF,))
        room = gear.equip_room((STAFF,), WORN, {"Cronk": 0}, now=after)
        self.assertEqual(room["Cronk"][2], 0)


if __name__ == "__main__":
    unittest.main()
