"""Watch on any character, Stop, the Watcher tile and the Live now list.

Drawn by app/views/_spectate.js and app/views/now/live.js, run under node like
test_app_spectate. Markup is checked as text; a fake document checks that a
click sends the name or the stop and nothing else.
"""

import json
import unittest

from test_app_flagship import app_file, needs_node, run_node
from test_app_spectate import CLICK, FILES, OFF, ON, cam, markup, run

OK = {"ok": True, "status": 200, "body": {"ok": True}, "failed": ""}


def click(answer, value, attr):
    return run(CLICK % (json.dumps(value), json.dumps(attr), json.dumps(answer)))


@needs_node
class TheCharacterButton(unittest.TestCase):
    def mk(self, sp, op, name="Ugga"):
        return markup(
            "S.charButton(%s, %s, %s)"
            % (json.dumps(name), json.dumps(sp), json.dumps(op))
        )

    def test_an_idle_camera_offers_watch_with_the_name(self):
        m = self.mk(cam(), ON)
        self.assertIn('data-spectate-char="Ugga"', m)
        self.assertNotIn("disabled", m)
        self.assertNotIn("Watch instead", m)

    def test_the_character_on_screen_says_now_watching_with_no_button(self):
        m = self.mk(cam(active=True, character="Ugga", spec="character Ugga"), ON)
        self.assertIn("Now watching", m)
        self.assertNotIn("<button", m)

    def test_another_target_reads_watch_instead_with_the_wait_in_the_title(self):
        m = self.mk(cam(active=True, character="Grug", switch_in=40), ON)
        self.assertIn("Watch instead", m)
        self.assertIn("switched in 40 seconds", m)

    def test_operator_off_is_disabled_with_the_reason(self):
        m = self.mk(cam(), OFF)
        self.assertIn("disabled", m)
        self.assertNotIn("data-spectate-char", m)
        self.assertIn("Operator actions are off", m)

    def test_an_unread_camera_is_disabled(self):
        m = self.mk({"data": None, "loading": True}, ON)
        self.assertIn("disabled", m)
        self.assertNotIn("data-spectate-char", m)

    def test_a_hostile_name_is_escaped(self):
        m = self.mk(cam(), ON, name='"><img src=x>')
        self.assertNotIn("<img", m)


@needs_node
class TheJumpButton(unittest.TestCase):
    def mk(self, order, sp, op):
        return markup(
            "S.jumpButton(%s, %s, %s)"
            % (json.dumps(order), json.dumps(sp), json.dumps(op))
        )

    def test_a_run_order_carries_the_run_id(self):
        m = self.mk({"run": 285}, cam(), ON)
        self.assertIn('data-spectate-run="285"', m)
        self.assertIn("Jump in", m)

    def test_a_character_order_carries_the_name(self):
        m = self.mk({"character": "Tanky"}, cam(), ON)
        self.assertIn('data-spectate-char="Tanky"', m)

    def test_the_group_the_camera_is_on_says_now_watching(self):
        self.assertIn(
            "Now watching", self.mk({"run": 285}, cam(active=True, run=285), ON)
        )
        on = cam(active=True, character="Tanky")
        self.assertIn("Now watching", self.mk({"character": "Tanky"}, on, ON))

    def test_operator_off_disables_it(self):
        m = self.mk({"run": 285}, cam(), OFF)
        self.assertIn("disabled", m)
        self.assertNotIn("data-spectate-run", m)


@needs_node
class TheStopAndTheTile(unittest.TestCase):
    def mk(self, sp, op, idle=False):
        return markup(
            "S.stage(%s, [], %s, %s)"
            % (json.dumps(sp), json.dumps(op), json.dumps(idle))
        )

    def test_a_character_order_reads_now_watching_the_name_with_a_stop_button(self):
        sp = cam(active=True, character="Ugga", target="Ugga", spec="character Ugga")
        m = self.mk(sp, ON)
        self.assertIn("Now watching Ugga", m)
        self.assertIn("data-spectate-stop", m)
        self.assertIn("data-spectate-slot", m)

    def test_no_stop_button_while_operator_actions_are_off(self):
        m = self.mk(cam(active=True, character="Ugga", target="Ugga"), OFF)
        self.assertNotIn("data-spectate-stop", m)

    def test_an_idle_tile_says_so_and_draws_no_picture(self):
        m = self.mk(cam(), ON, idle=True)
        self.assertIn("not watching anyone", m)
        self.assertNotIn("data-spectate-slot", m)
        self.assertNotIn("data-spectate-stop", m)

    def test_an_idle_card_is_not_drawn_unless_asked_for(self):
        self.assertNotIn("not watching anyone", self.mk(cam(), ON, idle=False))


@needs_node
class TheClicks(unittest.TestCase):
    def test_a_character_click_posts_the_name_only(self):
        got = click(OK, "Ugga", "data-spectate-char")
        self.assertEqual(got["posts"], [["/api/spectate", {"character": "Ugga"}]])

    def test_a_stop_click_posts_stop_true_only(self):
        got = click(OK, "", "data-spectate-stop")
        self.assertEqual(got["posts"], [["/api/spectate", {"stop": True}]])

    def test_a_refused_character_shows_the_servers_sentence(self):
        body = {"error": "The camera is on run 7. It can be switched in 70 seconds."}
        got = click(
            {"ok": False, "status": 409, "body": body, "failed": ""},
            "Ugga",
            "data-spectate-char",
        )
        self.assertIn("switched in 70 seconds", got["text"])


LIVE = {
    "dungeons": [
        {
            "kind": "dungeon",
            "run": 285,
            "title": "Bonkers - Scarlet Monastery",
            "place": "Scarlet Monastery",
            "progress": "1 of 4 bosses down, 0 deaths",
            "seats": [
                {"name": "Tanky", "seat": "tank"},
                {"name": "Heely", "seat": "healer"},
            ],
            "order": {"run": 285},
        }
    ],
    "raids": [
        {
            "kind": "raid",
            "place": "Molten Core",
            "count": 36,
            "fighting": 20,
            "tanks": 3,
            "healers": 8,
            "members": ["Aa", "Bb"],
            "progress": "36 inside, 20 fighting",
            "order": {"character": "Aa"},
        }
    ],
    "battlegrounds": [
        {
            "kind": "battleground",
            "place": "Warsong Gulch",
            "count": 10,
            "fighting": 4,
            "tanks": 0,
            "healers": 0,
            "members": ["Cc"],
            "progress": "10 inside, 4 fighting",
            "order": {"character": "Cc"},
        }
    ],
}


def live_section(read, sp=None, op=ON):
    files = {k: (v if v is not None else app_file(k)) for k, v in FILES.items()}
    files["views/now/live.js"] = app_file("views/now/live.js")
    out = run_node(
        files,
        "globalThis.window = { addEventListener() {} };\n"
        'const L = await import("./views/now/live.js");\n'
        "console.log(JSON.stringify({m: String(L.section(%s, %s, %s))}));\n"
        % (json.dumps(read), json.dumps(sp or cam()), json.dumps(op)),
    )
    return out["m"]


@needs_node
class TheLiveList(unittest.TestCase):
    def test_each_kind_is_listed_with_progress_and_a_jump_in_button(self):
        m = live_section({"data": LIVE})
        self.assertIn("Dungeon: Bonkers - Scarlet Monastery", m)
        self.assertIn("Raid: Molten Core", m)
        self.assertIn("Battleground: Warsong Gulch", m)
        self.assertIn("1 of 4 bosses down", m)
        self.assertIn("Tanky (tank)", m)
        self.assertIn("3 tanks, 8 healers", m)
        self.assertEqual(m.count("Jump in"), 3)
        self.assertIn('data-spectate-run="285"', m)
        self.assertIn('data-spectate-char="Aa"', m)
        self.assertIn('data-spectate-char="Cc"', m)

    def test_nothing_live_is_said_in_words(self):
        empty = {"data": {"dungeons": [], "raids": [], "battlegrounds": []}}
        self.assertIn("No dungeon, raid or battleground is live", live_section(empty))

    def test_a_failed_read_does_not_claim_nothing_is_live(self):
        m = live_section({"data": None, "error": "x"})
        self.assertIn("did not answer", m)
        self.assertNotIn("is live right now", m)

    def test_the_group_on_screen_is_marked_not_offered_again(self):
        m = live_section({"data": LIVE}, sp=cam(active=True, run=285))
        self.assertEqual(m.count("Jump in"), 2)
        self.assertIn("Now watching", m)


class TheWiring(unittest.TestCase):
    def test_now_reads_draws_and_binds_the_watcher_and_the_live_list(self):
        src = app_file("views/now.js")
        for needle in (
            "LIVE_READ",
            "liveSection(",
            "watchStage(",
            "bindWatch(main)",
            "WATCH_CSS",
        ):
            self.assertIn(needle, src, needle)

    def test_the_character_lists_carry_the_button_and_bind_it(self):
        for view in ("members", "family", "map", "member"):
            src = app_file("views/%s.js" % view)
            for needle in ("charButton(", "bindWatch(", "WATCH_READ"):
                self.assertIn(needle, src, view + " " + needle)


if __name__ == "__main__":
    unittest.main()
