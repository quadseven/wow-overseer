"""GET /api/guildseats answers the bench rows the bridge left in the memo store (#784)."""

import json
import types
import unittest
from unittest import mock

from _stub_modules import PYMYSQL, stub_modules

with stub_modules(pymysql=PYMYSQL):
    import map_server
    import realmread


class TheEndpoint(unittest.TestCase):
    def _call(self, answers):
        sent = []
        this = types.SimpleNamespace(
            _send=lambda code, ctype, body, *a: sent.append((code, body))
        )
        with mock.patch.object(
            realmread, "Session", lambda connect: realmread.Memory(answers)
        ):
            map_server.Handler._guild_seats(this, {})
        return sent[0]

    def test_it_is_routed(self):
        with open(map_server.__file__) as handle:
            src = handle.read()
        self.assertIn('"/api/guildseats": _guild_seats', src)

    def test_it_answers_the_memo_rows(self):
        rows = [
            {
                "subject": "Cave",
                "value": json.dumps([{"keyword": "deadmines", "tanks": 2}]),
                "since": 9.0,
            }
        ]
        code, body = self._call({map_server.seatmeter.BENCH_READ_SQL: rows})
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)["guilds"][0]["doors"][0]["tanks"], 2)


if __name__ == "__main__":
    unittest.main()
