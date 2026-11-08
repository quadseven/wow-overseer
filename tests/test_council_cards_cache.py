"""/api/council builds the Chronicle once per window, not once per poll (#2051).

The council reads only the run cards' loot off the Chronicle, and building the
whole Chronicle was the route's 4.7 s. These pin that repeated calls share one
build, and that the route goes through the shared helper.
"""

import pathlib
import sys
import unittest
from unittest import mock

from _stub_modules import PYMYSQL, stub_modules

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
with stub_modules(pymysql=PYMYSQL):
    import map_server
    import readcache


class CouncilCardsCache(unittest.TestCase):
    def setUp(self):
        self.clock = [100.0]
        self.cache = readcache.ReadCache(
            map_server.COUNCIL_CARDS_SECONDS, clock=lambda: self.clock[0]
        )
        patch = mock.patch.object(map_server, "COUNCIL_CARDS", self.cache)
        patch.start()
        self.addCleanup(patch.stop)

    def test_polls_inside_the_window_build_the_chronicle_once(self):
        with mock.patch.object(
            map_server, "_fetch_achievements", return_value={}
        ) as fetch, mock.patch.object(
            map_server.achievements,
            "build_achievements",
            return_value={"cards": [{"kind": "run"}]},
        ) as build:
            first = map_server._cards_for_council()
            self.clock[0] += map_server.COUNCIL_CARDS_SECONDS - 1
            second = map_server._cards_for_council()
            self.assertEqual(first, second)
            self.assertEqual((fetch.call_count, build.call_count), (1, 1))
            self.clock[0] += 2
            map_server._cards_for_council()
            self.assertEqual(build.call_count, 2)

    def test_the_council_route_reads_cards_through_the_shared_helper(self):
        src = pathlib.Path(map_server.__file__).read_text()
        start = src.index("def _council(query")
        body = src[start : src.index("def _eye(query", start)]
        self.assertIn("_cards_for_council()", body)
        self.assertNotIn("build_achievements", body)


if __name__ == "__main__":
    unittest.main()
