"""The Watch control on a live dungeon group, drawn by app/views/_spectate.js.

Run under node against stand-ins for the browser, like the clips shelf. The
markup is checked as text; a fake document checks that a click sends the run
id and nothing else, and that a refusal is shown in words.
"""

import json
import unittest

from test_app_flagship import app_file, needs_node, run_node

# api.js: reads are canned, post and load are recorded on globalThis.
API_STUB = (
    'export const u = (p) => "/m" + p;\n'
    "export const peek = () => ({ data: undefined });\n"
    "export const load = (p) => { (globalThis.loads ||= []).push(p);"
    " return Promise.resolve(); };\n"
    "export const post = (p, b) => { (globalThis.posts ||= []).push([p, b]);"
    " return Promise.resolve(globalThis.answer); };\n"
)
WHEP_STUB = (
    "export function makePlayer(video, note) {"
    " const p = { starts: [], stops: 0,"
    " start(n, u) { p.starts.push([n, u]); }, stop() { p.stops += 1; } };"
    " (globalThis.players ||= []).push(p); return p; }\n"
)

FILES = {
    "views/_spectate.js": None,
    "views/now/whep.js": WHEP_STUB,
    "ui.js": None,
    "api.js": API_STUB,
}

STREAM = "https://stream.example.test/devwatcher"
RUN = {"id": 285, "guild": "Bonkers", "place": "Scarlet Monastery (the Library)"}


def run(script):
    files = {k: (v if v is not None else app_file(k)) for k, v in FILES.items()}
    return run_node(files, "globalThis.window = { addEventListener() {} };\n" + script)


def cam(**kw):
    base = {
        "active": False,
        "run": None,
        "spec": "",
        "target": "",
        "note": "",
        "expires_in": 0,
        "switch_in": 0,
        "stream": STREAM,
    }
    base.update(kw)
    return {"data": base, "loading": False}


ON = {"data": {"enabled": True}, "loading": False}
OFF = {"data": {"enabled": False}, "loading": False}


def markup(expr):
    out = run(
        'const S = await import("./views/_spectate.js");\n'
        "console.log(JSON.stringify({m: String(%s)}));\n" % expr
    )
    return out["m"]


def control(sp, op, run_=RUN):
    return markup(
        "S.control(%s, %s, %s)" % (json.dumps(run_), json.dumps(sp), json.dumps(op))
    )


def stage(sp, runs=(RUN,)):
    return markup("S.stage(%s, %s)" % (json.dumps(sp), json.dumps(list(runs))))


@needs_node
class TheButton(unittest.TestCase):
    def test_an_idle_camera_offers_watch_with_the_run_id(self):
        m = control(cam(), ON)
        self.assertIn('data-spectate-run="285"', m)
        self.assertIn("Watch", m)
        self.assertNotIn("Watch instead", m)
        self.assertNotIn("disabled", m)

    def test_the_group_on_screen_says_now_watching_and_has_no_button(self):
        m = control(cam(active=True, run=285, target="Tanky", switch_in=40), ON)
        self.assertIn("Now watching", m)
        self.assertNotIn("<button", m)

    def test_another_group_reads_watch_instead_with_the_wait(self):
        m = control(cam(active=True, run=286, switch_in=40), ON)
        self.assertIn("Watch instead", m)
        self.assertIn('data-spectate-run="285"', m)
        self.assertIn("switched in 40 seconds", m)

    def test_after_the_dwell_no_wait_is_promised(self):
        m = control(cam(active=True, run=286, switch_in=0), ON)
        self.assertIn("Watch instead", m)
        self.assertNotIn("seconds", m)

    def test_operator_actions_off_is_a_disabled_button_with_the_reason(self):
        m = control(cam(), OFF)
        self.assertIn("disabled", m)
        self.assertNotIn("data-spectate-run", m)
        self.assertIn("Operator actions are off", m)

    def test_an_unread_camera_is_disabled_and_says_so(self):
        m = control({"data": None, "loading": True}, ON)
        self.assertIn("disabled", m)
        self.assertIn("not been read", m)
        self.assertNotIn("data-spectate-run", m)


@needs_node
class TheCameraCard(unittest.TestCase):
    def test_an_idle_camera_draws_only_the_status_line(self):
        m = stage(cam())
        self.assertIn("data-spectate-msg", m)
        self.assertNotIn("Now watching", m)
        self.assertNotIn("data-spectate-slot", m)

    def test_it_names_the_group_the_target_and_the_picture_slot(self):
        m = stage(cam(active=True, run=285, target="Tanky"))
        self.assertIn("Now watching Bonkers in Scarlet Monastery (the Library)", m)
        self.assertIn("Following Tanky", m)
        self.assertIn('data-spectate-slot data-stream="%s"' % STREAM, m)

    def test_it_says_whose_interface_is_on_screen(self):
        m = stage(cam(active=True, run=285, target="Tanky"))
        self.assertIn("belongs to the camera", m)

    def test_with_no_target_yet_it_shows_the_directors_reason(self):
        m = stage(cam(active=True, run=285, note="the Watcher is not in the world"))
        self.assertIn("Waiting: the Watcher is not in the world", m)
        self.assertNotIn("Following", m)

    def test_a_run_that_is_not_listed_is_named_by_its_number(self):
        m = stage(cam(active=True, run=999, target="Tanky"), runs=())
        self.assertIn("Now watching run 999", m)

    def test_no_stream_address_is_said_in_words_not_an_empty_player(self):
        m = stage(cam(active=True, run=285, stream=""))
        self.assertIn("no stream address", m)
        self.assertNotIn("data-spectate-slot", m)

    def test_names_from_the_realm_are_escaped(self):
        bad = dict(RUN, guild="<img src=x onerror=alert(1)>")
        m = stage(cam(active=True, run=285), runs=(bad,))
        self.assertNotIn("<img", m)


CLICK = (
    'const S = await import("./views/_spectate.js");\n'
    "const messages = { text: '' };\n"
    "Object.defineProperty(messages, 'textContent', { set(v) { this.text = v; },"
    " get() { return this.text; } });\n"
    "globalThis.document = { querySelectorAll: () => [messages],"
    " createElement(tag) { return { tag, setAttribute() {}, append() {} }; } };\n"
    "let click;\n"
    "const button = { disabled: false, getAttribute: () => '285',"
    " addEventListener(_t, f) { click = f; } };\n"
    "const main = { querySelectorAll: (q) => (q.startsWith('button') ? [button] : []),"
    " querySelector: () => null };\n"
    "S.bind(main);\n"
    "globalThis.answer = %s;\n"
    "click();\n"
    "await new Promise((r) => setTimeout(r, 0));\n"
    "console.log(JSON.stringify({posts: globalThis.posts, loads: globalThis.loads,"
    " text: messages.text, disabled: button.disabled}));\n"
)


@needs_node
class TheClick(unittest.TestCase):
    def click(self, answer):
        return run(CLICK % json.dumps(answer))

    def test_a_click_posts_the_run_id_and_only_that_then_rereads_the_camera(self):
        got = self.click(
            {"ok": True, "status": 200, "body": {"ok": True}, "failed": ""}
        )
        self.assertEqual(got["posts"], [["/api/spectate", {"run": 285}]])
        self.assertEqual(got["loads"], ["/api/spectate"])
        self.assertEqual(got["text"], "")
        self.assertFalse(got["disabled"])

    def test_a_second_group_inside_the_dwell_shows_the_servers_sentence(self):
        body = {"error": "The camera is on run 7. It can be switched in 70 seconds."}
        got = self.click({"ok": False, "status": 409, "body": body, "failed": ""})
        self.assertIn("switched in 70 seconds", got["text"])
        self.assertFalse(got["disabled"])

    def test_the_operator_switch_being_off_is_said_plainly(self):
        got = self.click({"ok": False, "status": 403, "body": None, "failed": ""})
        self.assertIn("Operator actions are off", got["text"])

    def test_an_unreachable_world_is_said_and_the_button_comes_back(self):
        got = self.click({"ok": False, "status": 503, "body": None, "failed": ""})
        self.assertIn("did not answer", got["text"])
        self.assertFalse(got["disabled"])

    def test_no_answer_at_all_names_the_failure(self):
        got = self.click({"ok": False, "status": 0, "body": None, "failed": "timeout"})
        self.assertIn("did not go through", got["text"])
        self.assertIn("timeout", got["text"])


PLAY = (
    'const S = await import("./views/_spectate.js");\n'
    "const made = [];\n"
    "globalThis.document = { createElement(tag) { const e = { tag, setAttribute() {},"
    " append() {} }; made.push(e); return e; } };\n"
    "const slot = (url) => ({ getAttribute: () => url, append(...n) { this.got = n; } });\n"
    "const mainWith = (s) => ({ querySelectorAll: () => [], querySelector: () => s });\n"
)


@needs_node
class ThePicture(unittest.TestCase):
    def test_the_stream_starts_once_and_the_same_video_survives_a_redraw(self):
        out = run(
            PLAY
            + "const a = slot('%s'), b = slot('%s');\n" % (STREAM, STREAM)
            + "S.bind(mainWith(a)); S.bind(mainWith(b));\n"
            "console.log(JSON.stringify({starts: globalThis.players[0].starts,"
            " players: globalThis.players.length, same: a.got[0] === b.got[0],"
            " video: made.filter((e) => e.tag === 'video').length}));\n"
        )
        self.assertEqual(out["starts"], [["the camera", STREAM]])
        self.assertEqual((out["players"], out["same"], out["video"]), (1, True, 1))

    def test_a_card_that_goes_away_stops_the_picture(self):
        out = run(
            PLAY
            + "S.bind(mainWith(slot('%s'))); S.bind(mainWith(null));\n" % STREAM
            + "console.log(JSON.stringify({stops: globalThis.players[0].stops}));\n"
        )
        self.assertEqual(out["stops"], 1)


class TheWiring(unittest.TestCase):
    def test_the_guilds_view_draws_it_on_each_live_group_and_binds_it(self):
        src = app_file("views/guild.js")
        self.assertIn('from "./_spectate.js"', src)
        self.assertIn("watchControl(r, sp, op)", src)
        self.assertIn("bindWatch(main)", src)
        self.assertIn("WATCH_CSS", src)
        self.assertIn('"camera", "operator"', src)

    def test_a_queued_group_has_no_watch_button(self):
        src = app_file("views/guild.js")
        self.assertIn('r.state === "queued" ? "" : watchControl', src)


if __name__ == "__main__":
    unittest.main()
