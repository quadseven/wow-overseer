"""The operator view (app/views/operator.js), rendered under node.

It is locked unless GET /api/v2/operator says the setting is on, and then
every form posts to a route map_server.py already serves, with the field
names that route's handler reads. Those names are checked against the
handlers' own source here, so a renamed field on either side fails a test
rather than a live order.
"""

import inspect
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import types
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import decree  # noqa: E402
import map_server  # noqa: E402
import stream  # noqa: E402
import travel  # noqa: E402

APP = HERE / "app"

DECREE = {
    "sections": [
        {"key": "job", "does": "Tells every member to switch to this job."},
        {"key": "campaign", "does": "Sets how many runs the family wants."},
    ],
    "job": {
        "line": "Set to quest.",
        "chips": [
            {"mode": "quest", "sendable": True},
            {"mode": "farm", "sendable": False},
        ],
    },
    "travel": {
        "line": "Nobody is walking anywhere.",
        "who": ["Grug", "Zug"],
        "chips": [{"role": "vendor"}, {"role": "banker"}],
        "caveat": "Travel, not transaction.",
    },
    "will": {"audience": ["Grug", "Bork"]},
    "queue": {"example": "ragefire 50, then wailing 50"},
    "families": [
        {
            "key": "Grug",
            "label": "Grug's family",
            "job": {"line": "Grug's family: Set to quest.", "split_line": ""},
            "campaign": {"line": "Grug's family: 0 of 9 runs done.", "means": ""},
            "queue": {"line": "Grug's family: nothing is queued."},
        },
        {
            "key": "Zug",
            "label": "Zug's family",
            "job": {"line": "Zug's family: Set to town run.", "split_line": ""},
            "campaign": {"line": "Zug's family: 4 of 10 runs done.", "means": ""},
            "queue": {"line": "Zug's family: nothing is queued."},
        },
    ],
    "orders": [],
}

DIRECTOR = {
    "watcher": "Watcher",
    "enabled": True,
    "active": False,
    "spec": "",
    "target": "",
    "note": "",
    "expires_in": 0,
    "usage": "watch <character> | off",
}

PRELUDE = """
const listeners = {};
const posted = [];
const swapped = [];
globalThis.window = {setTimeout: (f) => f(), setInterval: () => 1, clearInterval() {}};
globalThis.location = {hash: '#/operator'};
globalThis.document = {
  querySelector: (sel) => /^form\[data-op="[^"]+"\]$/.test(sel) ? {parentNode: {replaceChild: (n) => swapped.push(n.html)}, querySelector: () => null} : null,
  createElement: () => { const box = {}; Object.defineProperty(box, 'innerHTML', {set(v) { box.firstChild = {html: v}; }}); return box; },
  addEventListener() {},
};
globalThis.fetch = async (url, opts) => {
  posted.push({url, method: (opts && opts.method) || 'GET', headers: (opts && opts.headers) || {}, body: opts && opts.body});
  return {ok: true, status: 200, json: async () => ({ok: true}), text: async () => '{}'};
};
const main = {
  addEventListener: (kind, fn) => { listeners[kind] = fn; },
  querySelectorAll: () => [],
};
function target(attrs) {
  return {closest: (sel) => {
    for (const k of Object.keys(attrs)) if (sel.includes(k)) return {getAttribute: () => attrs[k]};
    return null;
  }};
}
// An input: closest() finds the input itself, as the DOM does.
function field(id, name, value) {
  const el = {name, value, getAttribute: () => id};
  el.closest = () => el;
  return el;
}
const V = (await import(%(view)s)).default;
const M = await import(%(view)s);
const A = await import(%(api)s);
function ctx(reads) {
  return {view: 'operator', section: '', params: {}, query: {}, hash: '#/operator', isPhone: false,
    get: (p) => (p in reads ? reads[p] : {data: undefined, at: 0, error: null, loading: true})};
}
const ok = (data) => ({data, at: 1, error: null});
const failed = (msg) => ({data: undefined, at: 0, error: {message: msg}, failures: 1});
"""


def run(script):
    """Run `script` with the app copied to a module package (see PRELUDE)."""
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp) / "app"
        shutil.copytree(APP, root)
        (root / "package.json").write_text('{"type": "module"}', encoding="utf-8")
        code = PRELUDE % {
            "view": json.dumps((root / "views" / "operator.js").as_uri()),
            "api": json.dumps((root / "api.js").as_uri()),
        }
        out = subprocess.run(
            [shutil.which("node"), "--input-type=module", "-e", code + script],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    if out.returncode != 0:
        raise AssertionError(out.stderr)
    return json.loads(out.stdout)


def render_with(reads):
    """The view's reads and markup for these canned reads."""
    return run(
        "const c = ctx(%s);\n"
        "console.log(JSON.stringify({reads: V.reads(c), html: V.render(c).s}));"
        % json.dumps(reads)
    )


def on_reads(decree_read=None):
    return {
        "/api/v2/operator": {"data": {"enabled": True}, "at": 1, "error": None},
        "/api/decree": decree_read or {"data": DECREE, "at": 1, "error": None},
        "/api/director": {"data": DIRECTOR, "at": 1, "error": None},
    }


FORM_PARTS = ("<form", "<input", "<select", "<textarea", "data-op=")


def handler_source(path):
    return inspect.getsource(map_server.Handler.POST_ROUTES[path])


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class LockedUnlessTheServerSaysSo(unittest.TestCase):
    def test_off_draws_the_lock_and_no_form(self):
        got = render_with(
            {
                "/api/v2/operator": {
                    "data": {"enabled": False},
                    "at": 1,
                    "error": None,
                },
                "/api/decree": {"data": DECREE, "at": 1, "error": None},
            }
        )
        self.assertIn("/api/v2/operator", got["reads"])
        self.assertNotIn("/api/director", got["reads"])
        self.assertIn("Off on this deployment", got["html"])
        for part in FORM_PARTS:
            self.assertNotIn(part, got["html"])
        # The console state is still shown, read-only.
        self.assertIn("Grug&#39;s family: Set to quest.", got["html"])

    def test_an_unanswered_or_failed_setting_stays_locked(self):
        failed = {"at": 0, "error": {"message": "HTTP 503"}, "failures": 1}
        for op in (None, failed):
            reads = {"/api/decree": {"data": DECREE, "at": 1, "error": None}}
            if op is not None:
                reads["/api/v2/operator"] = op
            got = render_with(reads)
            for part in FORM_PARTS:
                self.assertNotIn(part, got["html"])

    def test_on_draws_the_forms_and_reads_the_watcher(self):
        got = render_with(on_reads())
        self.assertIn("/api/director", got["reads"])
        self.assertIn("On for this deployment", got["html"])
        self.assertNotIn("Off on this deployment", got["html"])
        self.assertIn("<form", got["html"])


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class FormsPostWhereTheHandlersRead(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.actions = run("console.log(JSON.stringify(M.ACTIONS));")
        cls.html = render_with(on_reads())["html"]

    def test_every_operator_route_has_a_form_and_no_form_invents_one(self):
        routes = set(map_server.Handler.POST_ROUTES)
        used = {a["path"] for a in self.actions.values()}
        # /api/frame is the stream agent's picture upload, not an action.
        self.assertEqual(used, routes - {"/api/frame"})
        self.assertIn("/api/frame", self.html)

    def test_each_form_posts_its_own_path_with_its_own_names(self):
        for aid, action in self.actions.items():
            tag = re.search(r'<form[^>]*data-op="%s"[^>]*>' % aid, self.html)
            self.assertIsNotNone(tag, aid)
            self.assertIn('data-path="%s"' % action["path"], tag.group(0))
            chunk = self.html[tag.start() : self.html.index("</form>", tag.start())]
            for field in action["fields"]:
                self.assertIn('name="%s"' % field["name"], chunk, aid)
            self.assertEqual(chunk.count('type="submit"'), 1, aid)

    def test_body_names_are_the_ones_the_handler_reads(self):
        decree_src = inspect.getsource(decree)
        for aid, action in self.actions.items():
            src = handler_source(action["path"])
            if action["path"] == "/api/decree":
                # map_server hands the whole body to decree.plan_order.
                self.assertIn("decree.plan_order(request", src)
                src = decree_src
            names = [f["name"] for f in action["fields"] if not f.get("header")]
            names += list(action.get("fixed", {}))
            if action.get("fanout"):
                names.append("name")
            for name in names:
                self.assertIn('request.get("%s")' % name, src, (aid, name))
            for field in action["fields"]:
                if field.get("header"):
                    self.assertIn('self.headers.get("%s")' % field["header"], src)

    def test_fixed_values_are_ones_the_server_takes(self):
        sections = {decree.JOB, decree.CAMPAIGN, decree.QUEUE, decree.TRAVEL}
        for aid, action in self.actions.items():
            fixed = action.get("fixed", {})
            if "section" in fixed:
                self.assertIn(fixed["section"], sections, aid)
            if "action" in fixed:
                self.assertIn('"%s"' % fixed["action"], handler_source("/api/watch"))
        self.assertIs(self.actions["restart"]["fixed"]["restart"], True)
        self.assertIs(self.actions["unqueue"]["fixed"]["clear"], True)
        self.assertEqual(self.actions["standdown"]["fixed"]["role"], travel.NONE)

    def test_watch_modes_and_heartbeat_are_streams_own(self):
        got = run(
            "console.log(JSON.stringify([M.WATCH_MODES, M.NEEDS_A_VIEWER, M.BEAT_MS]));"
        )
        self.assertEqual(sorted(got[0]), sorted(stream.MODES))
        self.assertEqual(sorted(got[1]), sorted(stream.NEEDS_A_VIEWER))
        self.assertEqual(got[2], stream.HEARTBEAT_SECONDS * 1000)

    def test_a_cap_goes_as_a_number_and_the_token_as_a_header(self):
        got = run(
            "console.log(JSON.stringify(["
            "M.bodyOf('cap', {family: 'Zug', wanted: '12'}),"
            "M.bodyOf('cap', {family: 'Zug', wanted: 'lots'}),"
            "M.bodyOf('director', {watch: 'watch Grug', token: 'x'})]));"
        )
        self.assertEqual(
            got[0]["body"], {"section": "campaign", "family": "Zug", "wanted": 12}
        )
        # Not a number: sent as typed, so the server's refusal says why.
        self.assertEqual(got[1]["body"]["wanted"], "lots")
        self.assertEqual(got[2]["body"], {"watch": "watch Grug"})
        self.assertEqual(got[2]["headers"], {"X-Director-Token": "x"})


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class ConfirmBeforeSending(unittest.TestCase):
    def test_submit_asks_first_and_only_yes_sends(self):
        got = run(
            "const c = ctx(%s);\nV.render(c); V.after(main, c);\n"
            "listeners.input({target: field('chat', 'name', 'Grug')});\n"
            "listeners.input({target: field('chat', 'text', 'hello')});\n"
            "listeners.submit({target: target({'form[data-op]': 'chat'}), preventDefault() {}});\n"
            "const afterSubmit = posted.length;\n"
            "const asked = swapped[swapped.length - 1];\n"
            "listeners.click({target: target({'data-op-confirm': 'chat'}), preventDefault() {}});\n"
            "await new Promise((r) => setTimeout(r, 50));\n"
            "console.log(JSON.stringify({afterSubmit, asked, posted}));"
            % json.dumps(on_reads())
        )
        self.assertEqual(got["afterSubmit"], 0)
        self.assertIn("Send this to the realm?", got["asked"])
        self.assertIn("data-op-confirm", got["asked"])
        writes = [p for p in got["posted"] if p["method"] == "POST"]
        self.assertEqual(len(writes), 1)
        self.assertTrue(writes[0]["url"].endswith("/api/chat"))
        self.assertEqual(
            json.loads(writes[0]["body"]), {"name": "Grug", "text": "hello"}
        )

    def test_cancel_sends_nothing(self):
        got = run(
            "const c = ctx(%s);\nV.render(c); V.after(main, c);\n"
            "listeners.submit({target: target({'form[data-op]': 'job'}), preventDefault() {}});\n"
            "listeners.click({target: target({'data-op-cancel': 'job'}), preventDefault() {}});\n"
            "listeners.click({target: target({'data-op-confirm': 'job'}), preventDefault() {}});\n"
            "await new Promise((r) => setTimeout(r, 50));\n"
            "console.log(JSON.stringify(posted.filter((p) => p.method === 'POST').length));"
            % json.dumps(on_reads())
        )
        self.assertEqual(got, 0)

    def test_a_refusal_is_the_servers_sentence_verbatim(self):
        got = run(
            "globalThis.fetch = async (url, opts) => ({ok: false, status: 400,"
            " json: async () => ({error: 'Pick which family this is for.', section: 'job'})});\n"
            "const c = ctx(%s);\nV.render(c); V.after(main, c);\n"
            "listeners.submit({target: target({'form[data-op]': 'job'}), preventDefault() {}});\n"
            "listeners.click({target: target({'data-op-confirm': 'job'}), preventDefault() {}});\n"
            "await new Promise((r) => setTimeout(r, 50));\n"
            "console.log(JSON.stringify(swapped[swapped.length - 1]));"
            % json.dumps(on_reads())
        )
        self.assertIn("Refused", got)
        self.assertIn("Pick which family this is for.", got)

    def test_nothing_sends_while_the_setting_is_off(self):
        got = run(
            "const c = ctx({'/api/v2/operator': ok({enabled: false})});\n"
            "V.render(c); V.after(main, c);\n"
            "console.log(JSON.stringify(Object.keys(listeners)));"
        )
        self.assertEqual(got, [])


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class TheDecreeRead(unittest.TestCase):
    def test_a_failed_console_read_says_so_and_the_forms_still_draw(self):
        got = render_with(
            on_reads({"at": 0, "error": {"message": "HTTP 503"}, "failures": 1})
        )
        html = got["html"]
        self.assertIn("The decree console did not answer", html)
        self.assertIn("HTTP 503", html)
        self.assertIn('data-action="retry"', html)
        # Choices fall back to text boxes; the server still checks the value.
        self.assertIn('data-op="job"', html)
        self.assertRegex(html, r'<input[^>]*name="mode"')
        self.assertIn("Waiting for the console", html)

    def test_the_console_state_comes_from_the_read(self):
        html = render_with(on_reads())["html"]
        self.assertIn("Zug&#39;s family: 4 of 10 runs done.", html)
        self.assertIn('<option value="Zug"', html)
        self.assertIn('<option value="quest"', html)


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class ThePostHelper(unittest.TestCase):
    def test_it_posts_json_under_the_mount_and_never_rejects(self):
        got = run(
            "const a = await A.post('/api/chat', {name: 'Grug', text: 'hi'}, {'X-Director-Token': 't'});\n"
            "globalThis.fetch = async () => { throw new Error('offline'); };\n"
            "const b = await A.post('/api/chat', {});\n"
            "console.log(JSON.stringify({a, b, posted}));"
        )
        sent = got["posted"][0]
        self.assertEqual(sent["method"], "POST")
        self.assertEqual(sent["url"], "/api/chat")
        self.assertEqual(sent["headers"]["Content-Type"], "application/json")
        self.assertEqual(sent["headers"]["X-Director-Token"], "t")
        self.assertEqual(json.loads(sent["body"]), {"name": "Grug", "text": "hi"})
        self.assertTrue(got["a"]["ok"])
        self.assertFalse(got["b"]["ok"])
        self.assertEqual(got["b"]["failed"], "offline")


if __name__ == "__main__":
    unittest.main()
