"""app/models/achievements.js: the read model over /api/v2/achievements.

What the Chronicle, the profile badges and the Now toast decide from the
payload: which achievements are new since a visit and not yet shown, which
are notable enough for the Chronicle's All list, and how each tier is drawn.
Run under node through test_app_shell's runner, from canned payloads.
"""

import json
import shutil
import unittest

from test_app_shell import node_module

NODE = unittest.skipUnless(
    shutil.which("node"), "node is needed to run the app's modules"
)

T = 1791576724


def ach(i, at, tier="bronze", member="Grug", rule="drowned"):
    return {
        "id": "%s:%s:%d" % (rule, member, i),
        "rule": rule,
        "title": "T%d" % i,
        "line": "L%d" % i,
        "tier": tier,
        "member": member,
        "who": [member] if member else ["Grug", "Ugga"],
        "guild": "Cave",
        "earned_at": at,
        "source": {"table": "overseer_death", "id": i},
    }


ITEMS = [
    ach(1, T + 300, "gold"),
    ach(2, T + 200, "dubious"),
    ach(3, T + 100, "gold", member=""),
    ach(4, T - 100, "silver"),
]
READ = {"data": {"items": ITEMS, "guilds": ["Cave"]}, "loading": False}


def run(script):
    return node_module(
        "models/achievements.js", "console.log(JSON.stringify(" + script + "));"
    )


@NODE
class Fresh(unittest.TestCase):
    def test_new_since_the_visit_and_not_yet_shown_newest_first(self):
        got = run(
            "M.fresh(%s, %d, new Set([%s])).map((a) => a.id)"
            % (json.dumps(ITEMS), T, json.dumps(ITEMS[1]["id"]))
        )
        self.assertEqual(got, [ITEMS[0]["id"], ITEMS[2]["id"]])

    def test_a_first_visit_has_nothing_new(self):
        self.assertEqual(run("M.fresh(%s, null, new Set())" % json.dumps(ITEMS)), [])
        self.assertEqual(run("M.fresh(%s, 0, new Set())" % json.dumps(ITEMS)), [])

    def test_a_read_that_is_not_ready_has_no_items(self):
        self.assertEqual(run("M.items({loading: true})"), [])
        self.assertEqual(run('M.items({error: "503"})'), [])
        self.assertEqual(len(run("M.items(%s)" % json.dumps(READ))), 4)


@NODE
class Tiers(unittest.TestCase):
    def test_each_tier_has_its_own_label_and_icon(self):
        got = run('["bronze", "silver", "gold", "dubious"].map((t) => M.tier(t))')
        self.assertEqual(
            [t["label"] for t in got], ["Bronze", "Silver", "Gold", "Dubious"]
        )
        self.assertEqual(len({t["icon"] for t in got}), 4)

    def test_a_tier_the_app_does_not_know_is_drawn_as_its_own_word(self):
        got = run('M.tier("plaid")')
        self.assertEqual(got["key"], "bronze")
        self.assertEqual(got["label"], "plaid")

    def test_the_toast_leads_with_a_notable_one_over_a_newer_one(self):
        news = [
            ach(9, T + 900, "dubious"),
            ach(8, T + 800, "gold"),
            ach(7, T + 700, "gold"),
        ]
        got = run("M.headline(%s).id" % json.dumps(news))
        self.assertEqual(got, news[1]["id"])
        plain = [ach(9, T + 900, "dubious"), ach(8, T + 800, "bronze")]
        self.assertEqual(run("M.headline(%s).id" % json.dumps(plain)), plain[0]["id"])
        self.assertIsNone(run("M.headline([])"))

    def test_notable_is_gold_or_a_guild_first(self):
        got = run("%s.map((a) => M.notable(a))" % json.dumps(ITEMS))
        self.assertEqual(got, [True, False, True, False])


if __name__ == "__main__":
    unittest.main()
