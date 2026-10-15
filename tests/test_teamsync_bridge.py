"""The bridge's team sync pass writes a quester's reset as a naturalize row
(#927), with the reads stubbed."""

import asyncio
import types
import unittest
from unittest import mock

import raidteams
import teamsync
from test_guildsocial_bridge import bridge


def _bonkers_with_grakk():
    out = [
        {
            "name": s.name,
            "class_id": s.class_id,
            "race": teamsync.RACE_IDS[s.race],
            "level": 20,
        }
        for s in raidteams.seats("Bonkers")
    ]
    for _old, new in raidteams.SUMMONERS["Bonkers"] + raidteams.MAINTENANCE["Bonkers"]:
        out.append({"name": new, "class_id": 9, "race": 5, "level": 20})
    out.append({"name": "Grakk", "class_id": 9, "race": 2, "level": 6})
    return out


class TheResetRow(unittest.TestCase):
    def _run(self, reset_done):
        written = []
        members = {"Bonkers": _bonkers_with_grakk(), "Cave": []}
        with (
            mock.patch.multiple(
                bridge,
                _team_pending=lambda: set(),
                _team_reset_done=lambda: reset_done,
                _team_actor=lambda guild: "",
                _team_members=lambda guild: members[guild],
                _team_candidates=lambda guild: [],
                _team_refusal_rows=lambda: [],
                _insert_naturalize=lambda *a: written.append(("naturalize", *a)) or 1,
                _insert_job=lambda *a: written.append(("job", *a)) or 1,
                _insert_guild=lambda *a: written.append(("guild", *a)) or 1,
            ),
            mock.patch.dict("os.environ", {"TEAM_RENAMES": "on"}),
        ):
            asyncio.run(bridge.Bridge._team_sync_once(types.SimpleNamespace()))
        return written

    def test_a_named_quester_not_yet_reset_gets_a_naturalize_row(self):
        # With the family head out of the world: the reset runs on the quester
        # itself, offline, and no guild verb needs the head.
        self.assertEqual(
            self._run(set()),
            [("naturalize", "Grakk", "reset-level-1", bridge.TEAM_SYNC_SOURCE)],
        )

    def test_a_quester_the_ledger_reset_gets_none(self):
        self.assertEqual(self._run({"Grakk"}), [])

    def test_an_unread_ledger_writes_none(self):
        self.assertEqual(self._run(None), [])


class ThePendingInviteWindow(unittest.TestCase):
    def test_unanswered_rows_expire_after_a_bounded_window(self):
        calls = []

        class Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, sql, params):
                calls.append((sql, params))

            def fetchall(self):
                return [{"target_name": "GuildHead", "target_arg": "Firstlock"}]

        class Connection:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def cursor(self):
                return Cursor()

        with mock.patch.object(bridge, "_connect", return_value=Connection()):
            self.assertEqual(bridge._team_pending(), {"Firstlock"})
        sql, params = calls[0]
        self.assertIn("status IN ('pending', 'claimed')", sql)
        self.assertIn("created_at > NOW() - INTERVAL %s MINUTE", sql)
        self.assertEqual(params, (bridge.TEAM_SYNC_SOURCE, 30))


if __name__ == "__main__":
    unittest.main()


class TheRefusedInvite(unittest.TestCase):
    """#1015: the pass reads the module's refusal and does not re-invite."""

    def test_a_candidate_refused_ten_minutes_ago_is_not_invited(self):
        written = []
        members = {"Bonkers": _bonkers_with_grakk()[:-1], "Cave": []}
        lock = {
            "name": "Randomlock",
            "class_id": 9,
            "race": 2,
            "level": 4,
            "account_type": teamsync.ROTATING_ACCOUNT_TYPE,
        }
        refused = [
            {
                "target_arg": "Randomlock",
                "status": "unchanged",
                "detail": "",
                "age": 10,
                "result": '{"outcome":"refused","reason":"too far above the guild"}',
            }
        ]
        with (
            mock.patch.multiple(
                bridge,
                _team_pending=lambda: set(),
                _team_reset_done=lambda: set(),
                _team_actor=lambda guild: "Zug",
                _team_members=lambda guild: members[guild],
                _team_candidates=lambda guild: [lock] if guild == "Bonkers" else [],
                _team_refusal_rows=lambda: refused,
                _insert_naturalize=lambda *a: written.append(("naturalize", *a)) or 1,
                _insert_job=lambda *a: written.append(("job", *a)) or 1,
                _insert_guild=lambda *a: written.append(("guild", *a)) or 1,
            ),
        ):
            asyncio.run(bridge.Bridge._team_sync_once(types.SimpleNamespace()))
        self.assertEqual([w for w in written if w[0] == "guild"], [])
