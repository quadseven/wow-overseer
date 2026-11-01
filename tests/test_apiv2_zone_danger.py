"""Only the module's fresh canonical snapshot can become a measured list."""

import json
import types
import unittest

from apiv2 import zone_danger
from test_zone_danger import ANSWER


class Read:
    def __init__(self, rows):
        self.answer = rows
        self.calls = []

    def rows(self, sql, params, *, what):
        self.calls.append((sql, params, what))
        return self.answer


def context(rows):
    return types.SimpleNamespace(
        read=Read(rows),
        families=types.SimpleNamespace(
            families=lambda: {"First": ["Leader", "Sibling"], "Second": ["Other"]}
        ),
    )


class DangerRead(unittest.TestCase):
    def test_native_answer_is_preserved_and_missing_family_stays_unknown(self):
        ctx = context(
            [{"name": "Leader", "result": json.dumps(ANSWER), "now_at": 1001}]
        )
        code, payload = zone_danger.page({}, ctx)
        self.assertEqual(200, code)
        first, second = payload["families"]
        self.assertEqual(ANSWER, first["danger"])
        self.assertEqual("Leader", first["sampled_for"])
        self.assertEqual("online", first["status"])
        self.assertEqual("error", second["status"])
        self.assertNotIn("danger", second)
        sql, names, table = ctx.read.calls[0]
        self.assertTrue(sql.startswith("SELECT"))
        self.assertIn("INTERVAL 30 SECOND", sql)
        self.assertEqual(("Leader", "Other"), names)
        self.assertEqual("overseer_zone_danger", table)

    def test_empty_stale_and_malformed_have_different_meanings(self):
        for result, now_at, expected in (
            (dict(ANSWER, zones=[]), 1001, "online"),
            (ANSWER, 1031, "error"),
            ({}, 1001, "error"),
        ):
            ctx = context(
                [{"name": "Leader", "result": json.dumps(result), "now_at": now_at}]
            )
            with self.subTest(result=result, now_at=now_at):
                entry = zone_danger.page({}, ctx)[1]["families"][0]
                self.assertEqual(expected, entry["status"])

    def test_selector_refused_before_any_read(self):
        ctx = context([])
        self.assertEqual(400, zone_danger.page({"name": ["Unrelated"]}, ctx)[0])
        self.assertEqual([], ctx.read.calls)

    def test_database_failure_is_not_reported_as_empty_success(self):
        ctx = context([])

        def fail(*_args, **_kwargs):
            raise OSError("database unavailable")

        ctx.read.rows = fail
        with self.assertRaises(OSError):
            zone_danger.page({}, ctx)

    def test_endpoint_is_discovered_by_the_actual_v2_registry(self):
        import apiv2

        self.assertIs(zone_danger.page, apiv2.ROUTES["/api/v2/zone-danger"])
