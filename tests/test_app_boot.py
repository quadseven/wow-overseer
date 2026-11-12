"""The first route starts without waiting for the realm read, and the nav
badges wait for the first draw.

WHY. With no saved copy of the realm read, the first route waited for it,
then loaded its view module, then read the view's data; and the nav badges
fired about 26 KB of their own reads (chronicle, loot, stuck) alongside the
view's. On a phone profile the view's data started seconds after the first
byte and shared the line with the badges. boot.js holds the two decisions as
pure functions, run here under node.

Ticket: #2311 (epic #2309).
"""

import json
import shutil
import unittest

from test_app_shell import node_module

REALM = {
    "families": [{"key": "Grug", "names": ["Grug"]}, {"key": "Zug", "names": ["Zug"]}],
    "guilds": [{"name": "Cave", "family": "Grug"}],
}


def run(script, realm=None):
    return node_module("boot.js", script, realm=realm)


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class WhatStartsBeforeTheRealmAnswers(unittest.TestCase):
    def early(self, hash_, learned=False, last="", realm=None):
        return run(
            "console.log(JSON.stringify(M.earlyRoute(%s, {learned: %s, last: %s})));"
            % (json.dumps(hash_), "true" if learned else "false", json.dumps(last)),
            realm=realm,
        )

    def test_a_section_that_needs_no_realm_list_starts_at_once(self):
        for hash_, view in (
            ("#/quests", "quests"),
            ("#/members", "members"),
            ("#/economy", "economy"),
            ("#/now", "now"),
            ("#/m/Grug/gear", "member"),
            ("#/quests/42", "quests"),
        ):
            got = self.early(hash_)
            self.assertEqual(got["view"], view, hash_)
            self.assertEqual(got["hash"], hash_)

    def test_a_page_that_names_its_family_or_guild_starts_at_once_too(self):
        # Until the realm answers, the router keeps any slug it is given
        # (families.js), so the page is the one the route will draw.
        for hash_, view in (
            ("#/now/family/grug", "family"),
            ("#/guilds/cave", "guild"),
            ("#/guilds/cave/runs", "guild"),
            ("#/raid/mc/cave", "raid"),
        ):
            self.assertEqual(self.early(hash_)["view"], view, hash_)

    def test_a_page_that_needs_the_realm_list_to_pick_its_family_waits(self):
        for hash_ in ("#/raid/mc", "#/runs", "#/guilds", "#/now/family"):
            self.assertIsNone(self.early(hash_), hash_)

    def test_an_old_hash_waits_because_it_may_name_a_family(self):
        for hash_ in ("#armory", "#family/zug", "#aprof-Grug", "#dungeons/33"):
            self.assertIsNone(self.early(hash_), hash_)

    def test_nothing_starts_early_when_the_list_is_already_known(self):
        self.assertIsNone(self.early("#/quests", learned=True))

    def test_an_empty_hash_starts_the_page_the_route_will_restore(self):
        self.assertEqual(self.early("", last="#/economy")["view"], "economy")
        self.assertEqual(self.early("#/", last="")["view"], "now")
        self.assertEqual(self.early("", last="#/guilds/cave")["view"], "guild")
        self.assertIsNone(self.early("", last="#/runs"))

    def test_a_hash_that_redirects_waits(self):
        for hash_ in ("#/quests/1/2", "#/m", "#/now/unknown"):
            self.assertIsNone(self.early(hash_), hash_)

    def test_an_unknown_page_starts_nothing(self):
        got = self.early("#/nowhere")
        self.assertTrue(got is None or got["view"] == "notfound")


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class WhenTheBadgesStart(unittest.TestCase):
    def test_they_start_once_at_the_first_draw_and_not_before(self):
        out = run(
            """
            const calls = []; const timers = [];
            const b = M.afterFirstDraw(() => calls.push("start"), { setTimer: (fn, ms) => { timers.push([fn, ms]); return timers.length; }, clearTimer: () => {}, fallbackMs: 4000 });
            const before = calls.length;
            b.drawn(); b.drawn(); b.drawn();
            console.log(JSON.stringify({ before, after: calls.length, fallback: timers[0][1] }));
            """
        )
        self.assertEqual(out, {"before": 0, "after": 1, "fallback": 4000})

    def test_they_start_anyway_when_nothing_draws(self):
        out = run(
            """
            const calls = []; let fire = null;
            const b = M.afterFirstDraw(() => calls.push("start"), { setTimer: (fn) => { fire = fn; return 1; }, clearTimer: () => {}, fallbackMs: 4000 });
            fire(); fire(); b.drawn();
            console.log(JSON.stringify({ starts: calls.length }));
            """
        )
        self.assertEqual(out, {"starts": 1})

    def test_the_fallback_timer_is_cleared_when_the_draw_comes(self):
        out = run(
            """
            let cleared = 0;
            const b = M.afterFirstDraw(() => {}, { setTimer: () => 7, clearTimer: (id) => { if (id === 7) cleared++; }, fallbackMs: 4000 });
            b.drawn();
            console.log(JSON.stringify({ cleared }));
            """
        )
        self.assertEqual(out, {"cleared": 1})


class MainUsesThem(unittest.TestCase):
    def test_main_starts_the_early_route_and_defers_the_badges(self):
        import pathlib

        main = (
            pathlib.Path(__file__).resolve().parent.parent / "app" / "main.js"
        ).read_text(encoding="utf-8")
        self.assertIn('from "./boot.js"', main)
        self.assertIn("earlyRoute(", main)
        self.assertIn("afterFirstDraw(", main)
        # The badges are no longer started where the module loads.
        self.assertNotRegex(main, r"(?m)^refreshBadges\(\);")


if __name__ == "__main__":
    unittest.main()
