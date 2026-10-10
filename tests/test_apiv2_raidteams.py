"""GET /api/v2/raidteams: the approved Molten Core seats per guild, open seats
left open, and the raid fields per member (attuned, fire resistance,
consumables), null when the realm cannot answer a read."""

import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import apiv2  # noqa: E402
import raidready  # noqa: E402
import raidsupply  # noqa: E402
import raidteams  # noqa: E402
from apiv2 import raidteams as v2  # noqa: E402

GUILD_ID = 7


class Unreadable(Exception):
    """Stands in for the driver's error on a missing table."""


Unreadable.__module__ = "pymysql.err"


def _rows(team, *, renamed=False, recruits=False, other_guild=()):
    """characters/guild_member rows for `team`: current names until the
    rename, and no recruit until one joins."""
    out = []
    for s in raidteams.seats(team):
        if not s.was and not recruits and s not in raidteams.GROUPS[team][0]:
            continue
        name = s.name if (renamed or not s.was) else s.was
        gid = 99 if name in other_guild else GUILD_ID
        out.append(
            {
                "name": name,
                "level": 30,
                "class_id": s.class_id,
                "online": 1,
                "guildid": gid,
            }
        )
    return out


class FakeCursor:
    """Answers the endpoint's four reads from canned rows, by SQL text."""

    def __init__(self, members, attuned=(), worn=(), carried=(), fail=()):
        self.answers = {
            v2.MEMBERS_SQL[:40]: members,
            v2.ATTUNED_SQL[:40]: list(attuned),
            v2.WORN_SQL[:40]: list(worn),
            v2.CONSUMABLES_SQL[:40]: list(carried),
        }
        self.fail = set(fail)
        self.last = None
        self.executed = []

    def execute(self, sql, params=()):
        self.executed.append((sql, params))
        key = sql[:40]
        if key in self.fail:
            raise Unreadable(1146, "Table doesn't exist")
        self.last = self.answers[key]

    def fetchall(self):
        return self.last

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConn:
    def __init__(self, cur):
        self.cur = cur
        self.closed = False

    def cursor(self):
        return self.cur

    def close(self):
        self.closed = True


def _ctx(cur):
    conn = FakeConn(cur)
    return types.SimpleNamespace(connect=lambda: conn, server=None), conn


class TheRoute(unittest.TestCase):
    def test_the_route_is_registered_under_v2(self):
        self.assertIn("/api/v2/raidteams", apiv2.ROUTES)

    def test_the_guild_is_matched_without_case(self):
        self.assertEqual(v2.guild_key({"guild": ["cave"]}), "Cave")
        self.assertEqual(v2.guild_key({"guild": ["BONKERS"]}), "Bonkers")
        self.assertEqual(v2.guild_key({"guild": ["nobody"]}), "")
        self.assertEqual(v2.guild_key({}), "")

    def test_an_unknown_guild_is_a_400_that_names_the_guilds(self):
        code, payload = v2.raidteams_read({"guild": ["x"]}, None)
        self.assertEqual(code, 400)
        self.assertEqual(payload["guilds"], ["cave", "bonkers"])


class TheSeats(unittest.TestCase):
    def test_eight_groups_of_five_in_the_approved_order(self):
        payload = v2.build("Cave", {"members": _rows("Cave", recruits=True)})
        self.assertEqual(len(payload["groups"]), 8)
        self.assertTrue(all(len(g) == 5 for g in payload["groups"]))
        self.assertEqual(
            payload["groups"][0], [s.name for s in raidteams.GROUPS["Cave"][0]]
        )
        self.assertEqual(payload["gaps"], {"tanks": 0, "healers": 0, "damage": 0})

    def test_a_seat_is_found_under_the_name_it_has_until_the_rename(self):
        payload = v2.build("Cave", {"members": _rows("Cave")})
        brug = raidteams.GROUPS["Cave"][1][0]
        self.assertEqual(payload["groups"][1][0], brug.was)
        self.assertEqual(payload["seats"][1][0]["approved"], brug.name)

    def test_a_recruit_not_yet_joined_is_an_open_seat_and_a_gap(self):
        payload = v2.build("Cave", {"members": _rows("Cave")})
        recruits = [
            s
            for s in raidteams.seats("Cave")
            if not s.was and s not in raidteams.GROUPS["Cave"][0]
        ]
        flat = [n for g in payload["groups"] for n in g]
        self.assertEqual(flat.count(None), len(recruits))
        want = {"tanks": 0, "healers": 0, "damage": 0}
        for s in recruits:
            want[v2._GAP_KEY[s.seat]] += 1
        self.assertEqual(payload["gaps"], want)
        self.assertEqual(payload["seated"], 40 - len(recruits))

    def test_nobody_found_leaves_every_seat_open_never_guessed(self):
        payload = v2.build("Bonkers", {"members": []})
        self.assertEqual([n for g in payload["groups"] for n in g], [None] * 40)
        self.assertEqual(sum(payload["gaps"].values()), 40)
        self.assertEqual(payload["members"], {})

    def test_a_character_in_another_guild_does_not_take_the_seat(self):
        grug = raidteams.GROUPS["Cave"][0][0].name
        payload = v2.build(
            "Cave", {"members": _rows("Cave", recruits=True, other_guild={grug})}
        )
        self.assertIsNone(payload["groups"][0][0])


class TheRaidFields(unittest.TestCase):
    def setUp(self):
        self.grug = raidteams.GROUPS["Cave"][0][0].name
        self.ugga = raidteams.GROUPS["Cave"][0][1].name
        self.potion = raidsupply.SUPPLIES[0].entry

    def _payload(self, **reads):
        fetched = {
            "members": _rows("Cave"),
            "attuned": [],
            "worn": [],
            "consumables": [],
        }
        fetched.update(reads)
        return v2.build("Cave", fetched)

    def test_fields_are_read_per_member(self):
        payload = self._payload(
            attuned=[{"name": self.grug}],
            worn=[
                {"name": self.grug, "fire_res": 7},
                {"name": self.grug, "fire_res": 10},
            ],
            consumables=[{"name": self.grug, "entry": self.potion, "count": 3}],
        )
        grug = payload["members"][self.grug]
        self.assertIs(grug["attuned"], True)
        self.assertEqual(grug["fire_resistance"], 17)
        self.assertEqual(grug["consumables"], {str(self.potion): 3})

    def test_a_measured_nothing_is_false_zero_and_empty(self):
        ugga = self._payload()["members"][self.ugga]
        self.assertIs(ugga["attuned"], False)
        self.assertEqual(ugga["fire_resistance"], 0)
        self.assertEqual(ugga["consumables"], {})

    def test_an_unreadable_read_is_null_for_every_member(self):
        payload = self._payload(attuned=None, worn=None, consumables=None)
        for m in payload["members"].values():
            self.assertIsNone(m["attuned"])
            self.assertIsNone(m["fire_resistance"])
            self.assertIsNone(m["consumables"])

    def test_fire_resistance_is_counted_as_the_raid_card_counts_it(self):
        worn = [{"name": self.grug, "fire_res": 5}, {"name": self.ugga, "fire_res": 9}]
        payload = self._payload(worn=worn)
        fire = raidready.fire_resistance(worn)
        self.assertEqual(
            payload["members"][self.grug]["fire_resistance"], fire[self.grug]
        )

    def test_the_consumables_named_are_the_nights_supplies(self):
        payload = self._payload()
        entries = [i["entry"] for i in payload["consumable_items"]]
        self.assertEqual(
            entries, list(dict.fromkeys(s.entry for s in raidsupply.SUPPLIES))
        )


class TheReads(unittest.TestCase):
    def test_the_handler_reads_and_closes_its_connection(self):
        cur = FakeCursor(_rows("Cave"), attuned=[{"name": "Grug"}])
        ctx, conn = _ctx(cur)
        code, payload = v2.raidteams_read({"guild": ["cave"]}, ctx)
        self.assertEqual(code, 200)
        self.assertTrue(conn.closed)
        self.assertIs(payload["members"]["Grug"]["attuned"], True)
        self.assertEqual(len(cur.executed), 4)

    def test_every_value_is_bound(self):
        cur = FakeCursor(_rows("Cave"))
        v2.fetch(cur, "Cave")
        for sql, params in cur.executed:
            self.assertEqual(sql.count("%s"), len(params), sql)

    def test_a_missing_table_thins_that_field_only(self):
        cur = FakeCursor(_rows("Cave"), fail={v2.ATTUNED_SQL[:40]})
        ctx, _ = _ctx(cur)
        code, payload = v2.raidteams_read({"guild": ["cave"]}, ctx)
        self.assertEqual(code, 200)
        self.assertIsNone(payload["members"]["Grug"]["attuned"])
        self.assertEqual(payload["members"]["Grug"]["fire_resistance"], 0)

    def test_any_other_error_still_rises_to_the_503(self):
        class Broken:
            def execute(self, *a):
                raise OSError("connection reset")

        with self.assertRaises(OSError):
            v2.fetch(Broken(), "Cave")

    def test_nobody_found_reads_nothing_more(self):
        cur = FakeCursor([])
        v2.fetch(cur, "Cave")
        self.assertEqual(len(cur.executed), 1)


if __name__ == "__main__":
    unittest.main()
