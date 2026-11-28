"""The family board's new shape: a verdict that leads, member rows that carry
the roster truth, and an order that explains a wedge.

Rendered through the same Node seam as test_app_zone_danger: the real view
module, fed canned reads at its own paths. Every payload below is shaped like
the read it stands for; nothing here reaches inside the view.
"""

import json
import shutil
import unittest

from test_app_shell import node_module
from test_zone_danger import ANSWER

REALM = {
    "families": [{"key": k} for k in ("Grug", "Zug", "Tug", "Jug")],
    "guilds": [],
}

CHECKED_AT = 100000


def agenda(**over):
    base = {
        "headline": "Grug is walking to the vendor in Stormwind.",
        "queue": {"line": "", "entries": []},
        "detail": [],
        "activity": "travel",
        "stalled": False,
        "moved_seconds": 4 * 60,
        "stall_line": "",
        "stall_blocker": "",
        "leader": "Grug",
    }
    base.update(over)
    return base


STALLED = agenda(
    stalled=True,
    moved_seconds=53 * 60,
    stall_line="STALLED: no quest, level or gear change for 53 minutes.",
    stall_blocker="Grug is walking to the vendor in Stormwind.",
)


def family(members=None):
    return {
        "members": members
        or [
            {
                "name": "Grug",
                "role": "father",
                "present": True,
                "level": 60,
                "class": "Warrior",
                "condition": "ok",
                "health_pct": 100,
                "zone": "Stormwind",
                "leader": True,
                "combat": False,
            },
            {
                "name": "Bork",
                "role": "",
                "present": True,
                "level": 59,
                "class": "Rogue",
                "condition": "ok",
                "health_pct": 96,
                "zone": "Stormwind",
                "leader": False,
                "combat": False,
            },
            {
                "name": "Og",
                "role": "",
                "present": True,
                "level": 58,
                "class": "Mage",
                "condition": "hurt",
                "health_pct": 41,
                "zone": "Ironforge",
                "leader": False,
                "combat": False,
            },
        ]
    }


def roster(members=None):
    return {
        "checked_at": CHECKED_AT,
        "members": members
        or [
            {
                "name": "Grug",
                "doing": "Walking to the vendor",
                "waiting": "",
                "stuck": True,
                "since": CHECKED_AT - 53 * 60,
                "follows": "",
            },
            {
                "name": "Bork",
                "doing": "Following Grug",
                "waiting": "",
                "stuck": True,
                "since": CHECKED_AT - 53 * 60,
                "follows": "Grug",
            },
            {
                "name": "Og",
                "doing": "Questing",
                "waiting": "",
                "stuck": False,
                "since": None,
                "follows": "",
            },
        ],
    }


def reads(**over):
    base = {
        "/api/agenda": agenda(),
        "/api/family": family(),
        "/api/v2/roster": roster(),
        "/api/needs": {
            "moving": {
                "headline": "One trip is queued.",
                "rows": [
                    {
                        "title": "Vendor trip",
                        "word": "waiting",
                        "blocked": True,
                        "said": "Grug is walking to the vendor.",
                    }
                ],
                "notes": [],
                "rule": "",
            },
            "answering": {
                "headline": "Four follow the head.",
                "rows": [
                    {
                        "pair": "Bork and Grug",
                        "word": "COUNTING",
                        "progress": "3 of 5",
                        "pct": 60,
                        "note": "Bork answers Grug.",
                    }
                ],
                "rule": "",
            },
        },
        "/api/questlog": {
            "held": 3,
            "shared": 1,
            "alone": 2,
            "everyone": 0,
            "members": [
                {"name": "Grug", "class": "Warrior"},
                {"name": "Grog", "class": "Paladin"},
            ],
            "board": {
                "preview": 12,
                "rows": [
                    {
                        "title": "A Test Quest",
                        "level": 55,
                        "objectives": [{"what": "Boar ribs", "have": 2, "need": 5}],
                        "people": [
                            {"name": "Grug", "role": "on"},
                            {"name": "Grog", "role": "hand_in"},
                        ],
                    }
                ],
            },
        },
        "/api/auras": {"members": []},
        "/api/meter": {"families": []},
        "/api/v2/zone-danger": {"families": []},
        "/api/levelroute": {
            "where": "Where we are: Grug in Stormwind.",
            "queue": "",
            "now": "Leveling zone: Dun Morogh, levels 1-10.",
            "next": "Next: Loch Modan at about level 10.",
            "route": [
                {
                    "band": "1-10",
                    "zones": [{"zone": "Dun Morogh"}],
                    "dungeons": [],
                    "milestones": [],
                }
            ],
        },
    }
    base.update(over)
    return base


def render(reads_map, family_name="Grug", query=None):
    script = """
const reads = %s;
const waiting = {data: null, error: null, loading: true, at: 0};
const get = (path) => {
  for (const key of Object.keys(reads)) {
    if (path.startsWith(key)) return {data: reads[key], error: null, loading: false, at: 1};
  }
  return waiting;
};
const out = M.default.render({get, params: {family: %s}, query: %s});
console.log(JSON.stringify(out.s));
""" % (
        json.dumps(reads_map),
        json.dumps(family_name.lower()),
        json.dumps(query or {}),
    )
    return node_module("views/family.js", script, realm=REALM)


@unittest.skipUnless(shutil.which("node"), "node is needed for the actual view")
class FamilyVerdict(unittest.TestCase):
    def test_a_stalled_family_reads_as_stalled_at_the_top(self):
        text = render(reads(**{"/api/agenda": STALLED}))
        self.assertIn("Stalled 53 min", text)
        # The blocker, in plain words, and when the family last moved.
        self.assertIn("No quest, level or gear change for 53 minutes", text)
        self.assertIn("Grug is walking to the vendor in Stormwind", text)
        self.assertIn("Last progress 53m ago", text)
        # The warn treatment: a ring on the strip and a bar under the word.
        self.assertIn("fam-verdict is-stalled", text)
        self.assertIn("fv-bar", text)

    def test_the_verdict_sits_above_the_members(self):
        text = render(reads(**{"/api/agenda": STALLED}))
        self.assertLess(text.index("Stalled 53 min"), text.index("fam-member"))

    def test_a_moving_family_gets_one_quiet_line(self):
        text = render(reads())
        self.assertIn("Moving", text)
        self.assertIn("Last progress 4m ago", text)
        self.assertNotIn("is-stalled", text)
        self.assertNotIn("fv-bar", text)

    def test_the_state_word_names_a_dungeon_and_a_split(self):
        dungeon = render(reads(**{"/api/agenda": agenda(activity="dungeon")}))
        self.assertIn("In a dungeon", dungeon)
        split = render(reads(**{"/api/agenda": agenda(activity="split")}))
        self.assertIn("Split, moving", split)

    def test_an_unmeasured_agenda_draws_no_verdict(self):
        text = render(reads(**{"/api/agenda": None}))
        self.assertNotIn("fam-verdict", text)


def member_rows(text):
    return text.split('class="fam-member stretch-card')[1:]


@unittest.skipUnless(shutil.which("node"), "node is needed for the actual view")
class FamilyMembers(unittest.TestCase):
    def test_the_head_is_marked_and_only_the_head(self):
        rows = member_rows(render(reads()))
        self.assertEqual(len(rows), 3)
        self.assertIn("Head", rows[0])
        self.assertNotIn("Head", rows[1])
        self.assertNotIn("Head", rows[2])

    def test_a_follower_of_a_stuck_head_reads_waiting_on_him(self):
        rows = member_rows(render(reads()))
        self.assertIn("waiting on Grug", rows[1])
        # The head's own row carries what he is doing, and where.
        self.assertIn("Walking to the vendor", rows[0])
        self.assertIn("Stormwind", rows[0])

    def test_stuck_members_wear_the_stuck_tag_and_ring(self):
        text = render(reads())
        self.assertEqual(text.count("Stuck 53m"), 2)
        self.assertEqual(text.count("is-stuck"), 2)
        rows = member_rows(text)
        self.assertNotIn("Stuck", rows[2])

    def test_health_bars_come_from_health_pct(self):
        rows = member_rows(render(reads()))
        self.assertIn("width:96%", rows[1])
        self.assertIn("width:41%", rows[2])
        self.assertIn("Ironforge", rows[2])
        self.assertIn("Questing", rows[2])

    def test_a_follower_of_a_moving_head_keeps_his_doing_line(self):
        moving = roster(
            members=[
                {
                    "name": "Grug",
                    "doing": "Walking to the vendor",
                    "waiting": "",
                    "stuck": False,
                    "since": None,
                    "follows": "",
                },
                {
                    "name": "Bork",
                    "doing": "Following Grug",
                    "waiting": "",
                    "stuck": False,
                    "since": None,
                    "follows": "Grug",
                },
                {
                    "name": "Og",
                    "doing": "Questing",
                    "waiting": "",
                    "stuck": False,
                    "since": None,
                    "follows": "",
                },
            ]
        )
        rows = member_rows(render(reads(**{"/api/v2/roster": moving})))
        self.assertIn("Following Grug", rows[1])
        self.assertNotIn("waiting on", rows[1])


@unittest.skipUnless(shutil.which("node"), "node is needed for the actual view")
class FamilyOrder(unittest.TestCase):
    def test_sections_come_in_the_order_that_explains_a_wedge(self):
        text = render(reads(**{"/api/agenda": STALLED}))
        marks = [
            "fam-verdict",
            "fam-member",
            "What wants to move",
            "Quest board",
            "Damage, healing and threat",
            "Live buffs",
            "Travel danger",
            "Leveling route",
        ]
        idx = [text.index(m) for m in marks]
        self.assertEqual(idx, sorted(idx))

    def test_moves_and_bonds_share_one_card(self):
        text = render(reads())
        self.assertEqual(text.count('class="card fam-needs"'), 1)
        card = text.index('class="card fam-needs"')
        self.assertLess(card, text.index("What wants to move"))
        self.assertLess(text.index("Who answers who"), text.index("Quest board"))

    def test_an_unmeasured_needs_read_stays_one_card(self):
        text = render(reads(**{"/api/needs": None}))
        self.assertEqual(text.count('class="card fam-needs"'), 1)
        self.assertIn("What wants to move, who answers who", text)


def aura_member(name, held):
    return {
        "name": name,
        "family": "Grug",
        "status": "online",
        "auras": [{"name": b, "positive": True} for b in held],
    }


@unittest.skipUnless(shutil.which("node"), "node is needed for the actual view")
class FamilySwitcherAndBuffs(unittest.TestCase):
    def test_the_switcher_uses_bare_family_names(self):
        text = render(reads())
        self.assertIn(">Grug</a>", text)
        self.assertNotIn("Grug's family</a>", text)
        self.assertIn("fam-pick", text)

    def test_buffs_name_who_is_missing_a_buff(self):
        five = ["Grug", "Bork", "Og", "Grog", "Pell"]
        members = [
            aura_member(n, ["Power Word: Fortitude", "Arcane Intellect"]) for n in five
        ]
        members[3] = aura_member("Grog", ["Arcane Intellect"])
        text = render(reads(**{"/api/auras": {"members": members}}))
        seg = text[text.index("Live buffs") : text.index("Travel danger")]
        self.assertIn("4 of 5", seg)
        self.assertIn("missing Grog", seg)
        # Arcane Intellect is held by all five: it gets no missing line.
        self.assertEqual(seg.count(">missing"), 1)
        self.assertNotIn("ph-sparkle", seg)


@unittest.skipUnless(shutil.which("node"), "node is needed for the actual view")
class FamilyDangerRouteChips(unittest.TestCase):
    def test_travel_danger_leads_with_zones_and_folds_the_rule(self):
        danger = {
            "families": [
                {
                    "family": "Grug",
                    "sampled_for": "Grug",
                    "status": "online",
                    "danger": ANSWER,
                }
            ]
        }
        text = render(reads(**{"/api/v2/zone-danger": danger}))
        seg = text[text.index("Travel danger") :]
        self.assertLess(
            seg.index("Burning Steppes"), seg.index("How this is worked out")
        )
        fold = seg[seg.index("How this is worked out") :]
        self.assertIn("current map", fold)

    def test_the_route_is_suppressed_at_the_level_cap(self):
        cap = dict(reads()["/api/levelroute"])
        cap.update(now="At the level cap: no leveling zone.", route=[])
        text = render(reads(**{"/api/levelroute": cap}))
        self.assertNotIn("Leveling route", text)

    def test_the_route_shows_below_the_cap(self):
        self.assertIn("Leveling route", render(reads()))

    def test_quest_chips_use_initials_and_a_class_dot(self):
        text = render(reads())
        self.assertIn("qdot", text)
        self.assertIn("var(--cls-warrior", text)
        self.assertIn("var(--cls-paladin", text)
        self.assertIn(">G</a>", text)
        self.assertNotIn(">Gr</a>", text)


if __name__ == "__main__":
    unittest.main()
