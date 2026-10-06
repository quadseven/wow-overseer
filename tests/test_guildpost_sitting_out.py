"""A family member sitting out to craft takes its own post (master tailor).

Measured on wow-dev 2026-10-06: the crew mailed the master tailor 20 Linen
Cloth, and it sat unclaimed for 90 minutes. The guild post pass skipped every
roster member (the family's mail pass collects, but only when the family
stands at a mailbox) and the walk row refused a roster member who does not
lead. A member sitting out its campaign is neither in the family's walk nor
walked by anyone else.
"""

import contextlib
import sys
import types
import unittest
from unittest import mock

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import guildpost  # noqa: E402
import guildroute  # noqa: E402
from test_guildsocial_bridge import bridge  # noqa: E402


def letter(receiver, mail_id, guid, **over):
    base = {
        "receiver": receiver,
        "mail_id": mail_id,
        "item_guid": guid,
        "name": "Linen Cloth",
        "delivered": 1,
        "cod": 0,
    }
    base.update(over)
    return guildpost.letter_from_row(base)


class _Cursor:
    def __init__(self, roster, snapshots):
        self.roster, self.snapshots, self.rows = roster, snapshots, []

    def execute(self, sql, args=()):
        # PyMySQL needs one bound value per placeholder.
        assert sql.count("%s") == len(args), (sql, args)
        if "overseer_roster" in sql:
            self.rows = [
                {"name": n, "travel_npc": t}
                for n, t in self.roster.items()
                if n in args
            ]
        else:
            self.rows = [{"map_id": m} for n, m in self.snapshots.items() if n in args]

    def fetchall(self):
        return self.rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Conn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def sitting(roster, snapshots, out=("Og",), names=("Grug", "Ugga", "Og")):
    cursor = _Cursor(roster, snapshots)

    @contextlib.contextmanager
    def connect():
        yield _Conn(cursor)

    with (
        mock.patch.object(bridge, "_connect", connect),
        mock.patch.object(bridge, "_STANDIN_OUT", frozenset(out)),
    ):
        return bridge._sitting_out_to_walk(list(names))


class TheSittingOutMemberIsWalked(unittest.TestCase):
    def test_visits_include_a_sitting_out_roster_member(self):
        plan, _ = guildpost.visits(
            [letter("Og", 33549, 70)],
            {"Og"},
            roster={"Grug", "Og"},
            sitting_out={"Og"},
        )
        self.assertEqual([v.receiver for v in plan], ["Og"])
        self.assertEqual(plan[0].takes[0].command, "take-item mail:33549 item:70")

    def test_a_roster_member_still_in_the_campaign_is_left_to_its_family(self):
        plan, _ = guildpost.visits(
            [letter("Grug", 1, 10)], {"Grug"}, roster={"Grug", "Og"}, sitting_out={"Og"}
        )
        self.assertEqual(plan, [])

    def test_the_walker_is_cleared_for_the_row_only_when_named(self):
        roster, leaders = {"Grug", "Og"}, {"Grug": "k"}
        state, spawn = {"map_id": 0, "in_combat": 0}, {"d2": 100.0}
        named = guildroute.walker_from(
            "Og", state, leaders, roster, spawn, row_walkers={"Og"}
        )
        self.assertTrue(named.by_row)
        self.assertEqual(named.unwalkable, "")
        plain = guildroute.walker_from("Og", state, leaders, roster, spawn)
        self.assertEqual(plain.unwalkable, guildroute.NOT_LEADING)

    def test_the_pickup_never_spends_the_outbound_mail_run_budget(self):
        self.assertFalse(guildpost.WALK_SOURCE.startswith("guildwalk"))
        self.assertNotEqual(guildpost.WALK_SOURCE, guildroute.SOURCE)
        self.assertEqual(bridge.MAIL_WALK_SOURCE, "guildwalk")


class TheBridgeClearsOnlyAFreeMember(unittest.TestCase):
    def test_a_member_sitting_out_with_a_quiet_family_is_cleared(self):
        got = sitting({"Og": ""}, {"Grug": 1, "Ugga": 1})
        self.assertEqual(got, frozenset({"Og"}))

    def test_a_member_with_its_own_errand_is_not_pulled_off_it(self):
        self.assertEqual(
            sitting({"Og": "profession trainer"}, {"Grug": 1}), frozenset()
        )

    def test_the_family_inside_a_dungeon_clears_nobody(self):
        self.assertEqual(sitting({"Og": ""}, {"Grug": 36, "Ugga": 36}), frozenset())

    def test_nobody_sitting_out_clears_nobody(self):
        self.assertEqual(sitting({"Og": ""}, {}, out=()), frozenset())

    def test_the_pass_passes_the_cleared_names_to_the_walker_read(self):
        with open(bridge.__file__) as source:
            text = source.read()
        self.assertIn(
            "guildpost.visits(letters, online, busy, free_slots, roster,", text
        )
        self.assertIn("None, sitting)", text)


if __name__ == "__main__":
    unittest.main()
