"""GET /api/v2/gear/changes reads recent loot and equips."""

import datetime
import pathlib
import sys
import types
import unittest

from _stub_modules import PYMYSQL, stub_modules

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
with stub_modules(pymysql=PYMYSQL):
    import apiv2
    import realmread
    from apiv2 import gear_changes

SINCE = datetime.datetime(2026, 10, 15, 12)
EVENTS = [
    {
        "member_name": "Durga",
        "guild": "Bonkers",
        "kind": "item_equip",
        "entry": 101,
        "item": "Worn Boots",
        "quality": 1,
        "item_level": 5,
        "prior_state": "unknown",
        "at": SINCE + datetime.timedelta(hours=4),
    },
    {
        "member_name": "Velo",
        "guild": "Bonkers",
        "kind": "item_equip",
        "entry": 102,
        "item": "Wool Gloves",
        "quality": 1,
        "item_level": 4,
        "prior_state": "empty",
        "at": SINCE + datetime.timedelta(hours=3),
    },
    {
        "member_name": "Mirra",
        "guild": "Cave",
        "kind": "item_equip",
        "entry": 103,
        "item": "Brightwood Staff",
        "quality": 3,
        "item_level": 30,
        "prior_state": "item",
        "prior_entry": 99,
        "prior_item": "Oak Staff",
        "prior_quality": 2,
        "prior_item_level": 20,
        "at": SINCE + datetime.timedelta(hours=2),
    },
    {
        "member_name": "Tharn",
        "guild": "Cave",
        "kind": "item_loot",
        "entry": 104,
        "item": "Ashwood Bow",
        "quality": 2,
        "item_level": 8,
        "prior_state": "",
        "at": SINCE + datetime.timedelta(hours=1),
    },
]


class TestGearChanges(unittest.TestCase):
    def get(self, query, rows=EVENTS):
        ctx = types.SimpleNamespace(
            read=realmread.Memory({gear_changes.CHANGES_SQL: rows})
        )
        return apiv2.handle("/api/v2/gear/changes", query, ctx)

    def test_loot_and_equip_include_prior_state_and_delta(self):
        code, body = self.get({"since": [SINCE.isoformat()]})
        self.assertEqual(code, 200)
        self.assertEqual(
            [r["kind"] for r in body["changes"]], ["worn", "worn", "worn", "looted"]
        )
        self.assertEqual(body["changes"][2]["replaced"], "Oak Staff")
        self.assertEqual(body["changes"][2]["item_level_change"], 10)
        self.assertEqual(body["changes"][2]["entry"], 103)
        self.assertEqual(body["changes"][2]["prior_entry"], 99)
        self.assertEqual(body["changes"][1]["replaced"], "was empty")
        self.assertEqual(body["changes"][0]["replaced"], "not recorded")

    def test_filters_and_cap(self):
        many = [
            dict(EVENTS[-1], at=SINCE + datetime.timedelta(seconds=i))
            for i in range(510)
        ]
        code, body = self.get(
            {"since": [SINCE.isoformat()], "member": ["Tharn"], "guild": ["Cave"]}, many
        )
        self.assertEqual(code, 200)
        self.assertEqual(len(body["changes"]), 500)
        self.assertTrue(body["limited"])
        self.assertTrue(
            all(
                r["character"] == "Tharn" and r["guild"] == "Cave"
                for r in body["changes"]
            )
        )
        _, member_rows = self.get(
            {"since": [SINCE.isoformat()], "member": ["Mirra"], "guild": ["Cave"]}
        )
        self.assertEqual([r["character"] for r in member_rows["changes"]], ["Mirra"])
        _, no_rows = self.get(
            {"since": [SINCE.isoformat()], "member": ["Mirra"], "guild": ["Bonkers"]}
        )
        self.assertEqual(no_rows["changes"], [])

    def test_since_is_required_and_route_is_registered(self):
        self.assertIn("/api/v2/gear/changes", apiv2.ROUTES)
        self.assertEqual(self.get({})[0], 400)

    def test_opted_in_feed_can_read_revisions_at_the_same_timestamp(self):
        exact = dict(EVENTS[0], event_id=9007199254740993, occurrences=4, at=SINCE)
        inclusive = gear_changes.CHANGES_SQL.replace(
            "e.last_seen > %s", "e.last_seen >= %s"
        )
        ctx = types.SimpleNamespace(
            read=realmread.Memory({gear_changes.CHANGES_SQL: [], inclusive: [exact]})
        )
        route = "/api/v2/gear/changes"
        query = {"since": [SINCE.isoformat()]}
        self.assertEqual(apiv2.handle(route, query, ctx)[1]["changes"], [])
        status, body = apiv2.handle(route, {**query, "include_boundary": ["1"]}, ctx)
        self.assertEqual(status, 200)
        self.assertFalse(body["limited"])
        self.assertEqual(
            [(row["event_id"], row["occurrences"]) for row in body["changes"]],
            [("9007199254740993", 4)],
        )

    def test_exactly_five_hundred_rows_are_not_truncated(self):
        rows = [dict(EVENTS[0], event_id=i + 1) for i in range(500)]
        code, body = self.get({"since": [SINCE.isoformat()]}, rows)
        self.assertEqual(code, 200)
        self.assertEqual(len(body["changes"]), 500)
        self.assertFalse(body["limited"])

    def oldest(self, rows, *, inclusive=False):
        query = {"since": [SINCE.isoformat()], "oldest_first": ["1"]}
        if inclusive:
            query["include_boundary"] = ["1"]
        statement = (
            gear_changes.OLDEST_BOUNDARY_SQL if inclusive else gear_changes.OLDEST_SQL
        )
        reader = realmread.Memory({statement: rows})
        code, body = apiv2.handle(
            "/api/v2/gear/changes", query, types.SimpleNamespace(read=reader)
        )
        self.assertEqual(code, 200)
        params = (SINCE, "", "", "", "")
        self.assertEqual(reader.asked, [(statement, params * (2 if inclusive else 1))])
        return body

    def test_full_boundary_does_not_consume_forward_batch(self):
        boundary = [
            dict(EVENTS[0], at=SINCE, event_id=i + 1, boundary_row=1)
            for i in range(500)
        ]
        new = dict(EVENTS[1], event_id=501, boundary_row=0)
        body = self.oldest([*boundary, new], inclusive=True)
        self.assertFalse(body["limited"])
        self.assertEqual(len(body["changes"]), 501)
        self.assertEqual(body["changes"][-1]["event_id"], "501")

    def test_lookahead_protects_the_first_incomplete_timestamp(self):
        complete = SINCE + datetime.timedelta(seconds=1)
        split = SINCE + datetime.timedelta(seconds=2)
        rows = [dict(EVENTS[0], at=complete, event_id=1)] + [
            dict(EVENTS[0], at=split, event_id=i + 2) for i in range(500)
        ]
        body = self.oldest(rows)
        self.assertEqual(len(body["changes"]), 500)
        self.assertTrue(body["limited"])
        self.assertEqual(body["complete_through"], complete.isoformat(sep=" "))

    def test_oversized_boundary_blocks_advancing_to_a_later_timestamp(self):
        boundary = [
            dict(EVENTS[0], at=SINCE, event_id=i + 1, boundary_row=1)
            for i in range(501)
        ]
        body = self.oldest([*boundary, EVENTS[1]], inclusive=True)
        self.assertTrue(body["limited"])
        self.assertIsNone(body["complete_through"])
        self.assertEqual(len(body["changes"]), 500)
        self.assertTrue(
            all(row["at"] == SINCE.isoformat(sep=" ") for row in body["changes"])
        )


class TheSqlParsesOnMySql8(unittest.TestCase):
    """2026-10-15: the deployed read answered 503 because the query aliased a
    column as `character`, a MySQL 8 reserved word; the memory reader in the
    tests never parses SQL."""

    def test_no_reserved_word_is_used_as_a_bare_alias(self):
        import re

        aliases = re.findall(r"\bAS\s+([A-Za-z_]+)", gear_changes.CHANGES_SQL, re.I)
        reserved = {"character", "key", "order", "group", "rank", "range"}
        self.assertEqual(sorted(set(a.lower() for a in aliases) & reserved), [])

    def test_boundary_and_forward_lookaheads_share_one_bounded_statement(self):
        from sqlglot import exp, parse_one

        sql = gear_changes.OLDEST_BOUNDARY_SQL
        self.assertIn("e.last_seen = %s", sql)
        self.assertIn("e.last_seen > %s", sql)
        statement = parse_one(sql.replace("%s", "NULL"), read="mysql")
        self.assertIsInstance(statement, exp.Union)
        self.assertEqual(
            [row.expression.this for row in statement.find_all(exp.Limit)],
            ["501", "501"],
        )
