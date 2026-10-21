"""A leased guild member leaving the world is logged with its probable cause (#874).

The bridge only noticed afterwards ("waits for gear: it is offline"). The watch
reads the characters table, so these pin the pure decisions over plain rows and
the wiring in the bridge as source.
"""

import pathlib
import unittest

import guildjobs

HERE = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")

NOW = 1_000_000


def _row(name, logout=NOW - 30, online=0, account=1, guild="Cave"):
    return {
        "guid": hash(name) % 10_000,
        "name": name,
        "account": account,
        "online": online,
        "logout_time": logout,
        "guild": guild,
    }


class DeparturesTest(unittest.TestCase):
    def test_a_fresh_logout_is_reported_once(self):
        rows = [_row("Tugga")]
        first, seen = guildjobs.new_departures(rows, set(), NOW)
        self.assertEqual([r["name"] for r in first], ["Tugga"])
        again, _ = guildjobs.new_departures(rows, seen, NOW)
        self.assertEqual(again, [])

    def test_online_and_long_gone_members_are_not_departures(self):
        rows = [
            _row("Here", online=1),
            _row("Old", logout=NOW - guildjobs.LEAVE_LOOKBACK_SECONDS - 1),
        ]
        found, _ = guildjobs.new_departures(rows, set(), NOW)
        self.assertEqual(found, [])


class CauseTest(unittest.TestCase):
    def test_same_second_logouts_name_the_batch(self):
        batch = [_row("Tugga", logout=5), _row("Elfabulous", logout=5, guild="Bonkers")]
        line = guildjobs.leave_line(batch[0], batch, {})
        self.assertIn("Tugga", line)
        self.assertIn("same second as Elfabulous", line)
        self.assertIn("server-side pass", line)

    def test_a_busy_account_names_the_sibling_session(self):
        lone = _row("Bonk", account=7)
        line = guildjobs.leave_line(lone, [lone], {7: 2})
        self.assertIn("2 other characters on its account are online", line)

    def test_nothing_to_go_on_says_so(self):
        lone = _row("Oot", account=8)
        line = guildjobs.leave_line(lone, [lone], {})
        self.assertIn("no other session on its account and no batch", line)

    def test_every_line_names_the_member_and_guild(self):
        lone = _row("Lugg", guild="Bonkers")
        line = guildjobs.leave_line(lone, [lone], {})
        self.assertIn("Lugg", line)
        self.assertIn("Bonkers", line)


class WiringTest(unittest.TestCase):
    def test_the_watch_is_a_declared_headless_pass(self):
        self.assertIn('_Pass("_guild_logout_watch_loop")', BRIDGE)

    def test_the_watched_guilds_come_from_the_environment(self):
        self.assertIn("ALWAYS_ONLINE_GUILDS", BRIDGE)

    def test_the_watch_logs_at_warning(self):
        self.assertIn(
            "log.warning(", BRIDGE.split("def _guild_logout_watch_once")[1][:1500]
        )


if __name__ == "__main__":
    unittest.main()
