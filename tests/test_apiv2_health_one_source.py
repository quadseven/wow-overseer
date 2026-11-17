"""The health read names what the stuck read lists (#2246).

On 2026-11-17 the stuck read listed 29 members and the health read named 14 of
them: a member waiting under two hours, or with no start on record, was in the
one list and not in the other, and a stalled family was in neither unless its
leader had nothing else to say. Both reads now start from one roster build, and
this pins that they cannot disagree on a fixture.
"""

import unittest

from _stub_modules import PYMYSQL, stub_modules

with stub_modules(pymysql=PYMYSQL):
    from apiv2 import health, members
    from test_members_v2 import NOW, family_roster

QUIET = {"Zug": NOW - 1500, "Oz": NOW - 1320, "Grug": NOW - 600}
STALLED_GRUG = {"Zug": NOW - 600, "Grug": NOW - 2 * 3600, "Og": NOW - 3 * 3600}


def payload_for(moved):
    view = members.stuck_view(family_roster(moved=moved))
    return view, health.build(NOW, view, [], {}, [], [], {})


def spoken(payload):
    return " ".join(f["title"] + " " + f["evidence"] for f in payload["findings"])


class TheHealthReadNamesEveryStuckMember(unittest.TestCase):
    def test_no_member_of_the_stuck_list_is_left_out(self):
        view, payload = payload_for(QUIET)
        self.assertTrue(view["members"])
        text = spoken(payload)
        missing = [m["name"] for m in view["members"] if m["name"] not in text]
        self.assertEqual(missing, [])

    def test_a_member_waiting_under_two_hours_has_its_own_finding(self):
        stuck = {
            "members": [
                {"name": "Cronk", "step": "wear", "blocker": "", "since": NOW - 600},
                {"name": "Ghosty", "step": "wear", "blocker": "", "since": None},
            ]
        }
        (f,) = health.short_stuck_findings(stuck, NOW)
        self.assertEqual("stuck-short:wear", f["key"])
        self.assertEqual(2, f["affected"])
        self.assertIn("Cronk", f["evidence"])
        self.assertIn("Ghosty", f["evidence"])

    def test_a_member_stuck_two_hours_is_not_listed_twice(self):
        stuck = {
            "members": [
                {
                    "name": "Cronk",
                    "step": "wear",
                    "blocker": "",
                    "since": NOW - 3 * 3600,
                }
            ]
        }
        self.assertEqual([], health.short_stuck_findings(stuck, NOW))
        self.assertEqual(1, len(health.stuck_findings(stuck, NOW)))


class TheHealthReadNamesAStalledFamily(unittest.TestCase):
    def test_a_stalled_family_is_a_finding(self):
        _, payload = payload_for(QUIET)
        keys = [f["key"] for f in payload["findings"]]
        self.assertIn("family-stalled:Zug", keys)

    def test_a_family_whose_leader_has_a_hold_of_its_own_is_still_named(self):
        # Grug is held on a vendor already (a stuck record of its own), so the
        # stuck list names the hold and not the stall; the family still stalls.
        _, payload = payload_for(STALLED_GRUG)
        keys = [f["key"] for f in payload["findings"]]
        self.assertIn("family-stalled:Grug", keys)

    def test_a_family_that_moved_lately_is_not_stalled(self):
        fresh = {"Zug": NOW - 60, "Grug": NOW - 60}
        _, payload = payload_for(fresh)
        keys = [f["key"] for f in payload["findings"]]
        self.assertEqual([], [k for k in keys if k.startswith("family-stalled")])

    def test_a_family_whose_progress_is_unknown_is_not_stalled(self):
        _, payload = payload_for(None)
        keys = [f["key"] for f in payload["findings"]]
        self.assertEqual([], [k for k in keys if k.startswith("family-stalled")])

    def test_the_finding_says_how_long_and_why(self):
        _, payload = payload_for(QUIET)
        (f,) = [f for f in payload["findings"] if f["key"] == "family-stalled:Zug"]
        self.assertEqual(5, f["affected"])
        self.assertIn("22 minutes", f["evidence"])
        self.assertTrue(f["since"].endswith("Z"))


if __name__ == "__main__":
    unittest.main()
