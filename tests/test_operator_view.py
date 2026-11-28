"""The operator view (app/views/operator.js), rendered under node.

It is locked unless GET /api/v2/operator says the setting is on, and then
every form posts to a route map_server.py already serves, with the field
names that route's handler reads. Those names are checked against the
handlers' own source here, so a renamed field on either side fails a test
rather than a live order.
"""

import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from _stub_modules import PYMYSQL, stub_modules
import source_utils

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
with stub_modules(pymysql=PYMYSQL):
    import decree
    import map_server
    import priorities
    import travel

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
    "priorities": dict(priorities.view([]), section="priorities"),
}

AGENDA = {"headline": "The family is questing in Stranglethorn Vale."}

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
        "/api/agenda": {"data": AGENDA, "at": 1, "error": None},
    }


FORM_PARTS = ("<form", "<input", "<select", "<textarea", "data-op=")


def handler_source(path):
    return source_utils.function_source(map_server.Handler.POST_ROUTES[path])


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

    def test_every_operator_action_has_a_form_and_no_form_invents_one(self):
        routes = set(map_server.Handler.POST_ROUTES)
        used = {a["path"] for a in self.actions.values()}
        # Frame uploads come from the stream agent, and watch lifecycle calls
        # remain available to clients outside this operator page.
        # The cutter routes are called by the capture host, never by a form.
        # /api/spectate is the Guilds tab's Watch button, which posts a run id.
        cutter = {r for r in routes if r.startswith("/api/clips/")}
        self.assertEqual(
            used, routes - {"/api/frame", "/api/watch", "/api/spectate"} - cutter
        )
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
        decree_src = source_utils.function_source(decree)
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
        sections = {
            decree.JOB,
            decree.MUSTER,
            decree.CAMPAIGN,
            decree.QUEUE,
            decree.TRAVEL,
            decree.PRIORITIES,
            decree.GUILDRUN,
        }
        for aid, action in self.actions.items():
            fixed = action.get("fixed", {})
            if "section" in fixed:
                self.assertIn(fixed["section"], sections, aid)
            if "action" in fixed:
                self.assertIn('"%s"' % fixed["action"], handler_source("/api/watch"))
        self.assertIs(self.actions["restart"]["fixed"]["restart"], True)
        self.assertIs(self.actions["unqueue"]["fixed"]["clear"], True)
        self.assertIs(self.actions["unrank"]["fixed"]["reset"], True)
        self.assertEqual(self.actions["standdown"]["fixed"]["role"], travel.NONE)

    def test_on_demand_stream_controls_are_not_in_the_operator_view(self):
        source = (APP / "views" / "operator.js").read_text()
        for phrase in (
            "watchStart",
            "watchStop",
            "Start a stream",
            "Stop a stream",
            "STARTUP_SECONDS",
            "UNCLAIMED_AFTER_SECONDS",
            "MAX_CHANNELS",
        ):
            self.assertNotIn(phrase, source)

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
        self.assertIn("Send this to Grug", got["asked"])
        self.assertIn("&quot;hello&quot;", got["asked"])
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
            "listeners.input({target: field('job', 'family', 'Zug')});\n"
            "listeners.input({target: field('job', 'mode', 'quest')});\n"
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
            "listeners.input({target: field('job', 'family', 'Zug')});\n"
            "listeners.input({target: field('job', 'mode', 'quest')});\n"
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


DEFAULT = list(priorities.DEFAULT_ORDER)


def ranked_in(html):
    """The priority ids in the order the list draws them."""
    chunk = html[html.index('<ol class="op-rank"') : html.index("</ol>")]
    return re.findall(
        r'<li class="op-rank-item" data-op-rank="priorities" data-pid="([a-z]+)"', chunk
    )


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class ThePrioritiesPanel(unittest.TestCase):
    """#1559: the ranked list beside what the family is doing now."""

    def reorder(self, steps):
        """Render, run `steps` (JS) against the bound listeners, then return
        the last redraw of the priorities form and every POST."""
        return run(
            "const c = ctx(%s);\nV.render(c); V.after(main, c);\n%s\n"
            "await new Promise((r) => setTimeout(r, 50));\n"
            "const last = swapped.filter((h) => h.includes('data-op=\"priorities\"')).pop() || '';\n"
            "console.log(JSON.stringify({last, posted: posted.filter((p) => p.method === 'POST')}));"
            % (json.dumps(on_reads()), steps)
        )

    def test_the_order_and_the_agenda_sentence_are_side_by_side(self):
        got = render_with(on_reads())
        self.assertIn("/api/agenda", got["reads"])
        html = got["html"]
        card = html[html.index('class="card op-card op-pri"') :]
        card = card[: card.index('<div class="op-grid">')]
        self.assertIn("The family is questing in Stranglethorn Vale.", card)
        self.assertIn("op-pri-side", card)
        self.assertIn("op-pri-main", card)
        self.assertEqual(ranked_in(card), DEFAULT)
        for p in priorities.PRIORITIES:
            self.assertIn(p.sentence.replace("'", "&#39;"), card)
        self.assertIn(priorities.TAKES_EFFECT, card)
        self.assertIn('data-op="unrank"', card)

    def test_an_unanswered_agenda_is_said_not_blank(self):
        reads = on_reads()
        reads["/api/agenda"] = {
            "at": 0,
            "error": {"message": "HTTP 503"},
            "failures": 1,
        }
        html = render_with(reads)["html"]
        self.assertIn("What the family is doing now did not answer (HTTP 503)", html)

    def test_move_to_shifts_rather_than_swaps(self):
        got = run(
            "console.log(JSON.stringify([M.moveTo(%s, 'dungeons', 1), M.moveTo(%s, 'alive', 4)]));"
            % (json.dumps(DEFAULT), json.dumps(DEFAULT))
        )
        self.assertEqual(got[0], list(priorities.move(DEFAULT, "dungeons", 1)))
        self.assertEqual(got[1], list(priorities.move(DEFAULT, "alive", 4)))

    def button(self, move, pid):
        return (
            "{closest: (sel) => sel.includes('data-op-move') ? {getAttribute: (a) => "
            "({'data-op-move': '%s', 'data-op-rank': 'priorities', 'data-pid': '%s'})[a]} : null}"
            % (move, pid)
        )

    def row(self, pid):
        return (
            "{closest: (sel) => sel.includes('li[data-op-rank]') ? {getAttribute: (a) => "
            "({'data-op-rank': 'priorities', 'data-pid': '%s'})[a]} : null}" % pid
        )

    def test_the_arrow_buttons_reorder(self):
        got = self.reorder(
            "listeners.click({target: %s, preventDefault() {}});\n"
            "listeners.click({target: %s, preventDefault() {}});"
            % (self.button("up", "dungeons"), self.button("down", "alive"))
        )
        expected = priorities.move(DEFAULT, "dungeons", 3)
        expected = priorities.move(expected, "alive", 2)
        self.assertEqual(ranked_in(got["last"]), list(expected))
        self.assertIn("Not saved yet", got["last"])
        self.assertEqual(got["posted"], [])

    def test_alt_arrow_on_a_focused_row_reorders(self):
        got = self.reorder(
            "listeners.keydown({altKey: true, key: 'ArrowUp', target: %s, preventDefault() {}});\n"
            "listeners.keydown({altKey: false, key: 'ArrowUp', target: %s, preventDefault() {}});"
            % (self.row("gold"), self.row("gold"))
        )
        self.assertEqual(
            ranked_in(got["last"]), list(priorities.move(DEFAULT, "gold", 5))
        )

    def test_dragging_a_row_onto_another_takes_its_place(self):
        got = self.reorder(
            "listeners.dragstart({target: %s});\n"
            "listeners.dragover({target: %s, preventDefault() {}});\n"
            "listeners.drop({target: %s, preventDefault() {}});"
            % (self.row("guild"), self.row("alive"), self.row("alive"))
        )
        self.assertEqual(
            ranked_in(got["last"]), list(priorities.move(DEFAULT, "guild", 1))
        )

    def test_saving_sends_the_order_on_screen_after_a_confirm(self):
        got = self.reorder(
            "listeners.keydown({altKey: true, key: 'ArrowUp', target: %s, preventDefault() {}});\n"
            "listeners.submit({target: target({'form[data-op]': 'priorities'}), preventDefault() {}});\n"
            "listeners.click({target: target({'data-op-confirm': 'priorities'}), preventDefault() {}});"
            % self.row("quest")
        )
        [sent] = got["posted"]
        self.assertTrue(sent["url"].endswith("/api/decree"))
        self.assertEqual(
            json.loads(sent["body"]),
            {
                "section": "priorities",
                "order": list(priorities.move(DEFAULT, "quest", 2)),
            },
        )

    def test_reset_sends_reset_and_no_order(self):
        got = self.reorder(
            "listeners.submit({target: target({'form[data-op]': 'unrank'}), preventDefault() {}});\n"
            "listeners.click({target: target({'data-op-confirm': 'unrank'}), preventDefault() {}});"
        )
        [sent] = got["posted"]
        self.assertEqual(
            json.loads(sent["body"]), {"section": "priorities", "reset": True}
        )


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


def confirm_of(aid, fields=(), reads=None):
    """Render the on view, type `fields` into form `aid`, submit it, and
    return the markup the form was redrawn with: its confirm, or whatever
    stopped the confirm from opening."""
    steps = "".join(
        "listeners.input({target: field(%s, %s, %s)});\n"
        % (json.dumps(aid), json.dumps(name), json.dumps(value))
        for name, value in fields
    )
    return run(
        "const c = ctx(%s);\nV.render(c); V.after(main, c);\n%s"
        "listeners.submit({target: target({'form[data-op]': %s}), preventDefault() {}});\n"
        "console.log(JSON.stringify(swapped.length ? swapped[swapped.length - 1] : ''));"
        % (json.dumps(reads or on_reads()), steps, json.dumps(aid))
    )


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class PlainWordConfirms(unittest.TestCase):
    """#3366: a confirm names the action in plain words. No wire key, no
    fixed field, no "(empty)", no hidden header line."""

    CASES = (
        ("job", (("family", "Zug"), ("mode", "quest")), "Set the family&#39;s job"),
        ("muster", (("guild", "Cave"), ("command", "Form up")), "Send to the guild"),
        (
            "guildrun",
            (("guild", "Cave"), ("keyword", "scarlet-armory")),
            "Form the run",
        ),
        ("cap", (("family", "Zug"), ("wanted", "3")), "Set the run cap"),
        ("queue", (("family", "Grug"), ("entries", "ragefire 50")), "Set the queue"),
        ("aim", (("name", "Grug"), ("role", "vendor")), "Send them"),
        ("chat", (("name", "Grug"), ("text", "hello")), "Send this to Grug"),
        ("director", (("watch", "watch Grug"), ("token", "x")), "Point the Watcher"),
        ("priorities", (), "Save this order"),
        ("will", (("text", "Hold the bridge."),), "Let the family overhear it"),
    )

    def test_every_confirm_names_its_action_and_shows_no_wire(self):
        for aid, fields, heading in self.CASES:
            with self.subTest(action=aid):
                chunk = confirm_of(aid, fields)
                self.assertIn(heading, chunk)
                self.assertIn("data-op-confirm", chunk)
                for wire in (
                    "Send this to the realm?",
                    "(empty)",
                    "(hidden)",
                    "X-Director-Token",
                    '<span class="op-k">section</span>',
                    '<span class="op-k">family</span>',
                    '<span class="op-k">wanted</span>',
                    '<span class="op-k">restart</span>',
                    '<span class="op-k">clear</span>',
                    '<span class="op-k">reset</span>',
                ):
                    self.assertNotIn(wire, chunk, aid)

    def test_the_family_is_named_by_its_label_not_its_key(self):
        chunk = confirm_of("job", (("family", "Zug"), ("mode", "quest")))
        self.assertIn("Family</span> Zug&#39;s family", chunk)

    def test_the_words_sent_are_shown_in_quotes(self):
        chunk = confirm_of("muster", (("guild", "Cave"), ("command", "Form up")))
        self.assertIn("&quot;Form up&quot;", chunk)
        chunk = confirm_of("chat", (("name", "Grug"), ("text", "hello")))
        self.assertIn("&quot;hello&quot;", chunk)

    def test_the_priorities_confirm_names_entries_not_ids(self):
        chunk = confirm_of("priorities")
        self.assertIn("Highest first", chunk)
        first = next(p.label for p in priorities.PRIORITIES if p.id == DEFAULT[0])
        self.assertIn(first.replace("'", "&#39;"), chunk)


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class DangerConfirms(unittest.TestCase):
    """#3366: the five destructive actions carry the bad border, their own
    verb on the button, and a consequence line."""

    CASES = (
        (
            "cap",
            (("family", "Grug"), ("wanted", "0")),
            "Stop the campaign",
            "Yes, stop the campaign",
            "stops outright",
        ),
        (
            "restart",
            (("family", "Grug"),),
            "Start the count again",
            "Yes, start the count again",
            "goes back to the start",
        ),
        (
            "unqueue",
            (("family", "Grug"),),
            "Clear the queue",
            "Yes, clear the queue",
            "are wiped",
        ),
        (
            "unrank",
            (),
            "Reset the priorities",
            "Yes, reset the priorities",
            "default order",
        ),
        (
            "standdown",
            (("name", "Grug"),),
            "Stand them down",
            "Yes, stand them down",
            "cleared outright",
        ),
    )

    def test_each_destructive_confirm_carries_the_treatment(self):
        for aid, fields, heading, verb, consequence in self.CASES:
            with self.subTest(action=aid):
                chunk = confirm_of(aid, fields)
                self.assertIn(heading, chunk)
                self.assertIn('data-danger="1"', chunk)
                self.assertIn(verb, chunk)
                self.assertIn(consequence, chunk)

    def test_an_ordinary_confirm_has_no_danger_treatment(self):
        chunk = confirm_of("cap", (("family", "Grug"), ("wanted", "3")))
        self.assertIn("Set the run cap", chunk)
        self.assertNotIn("data-danger", chunk)
        self.assertIn("Yes, send it", chunk)
        chunk = confirm_of("chat", (("name", "Grug"), ("text", "hello")))
        self.assertNotIn("data-danger", chunk)
        self.assertIn("Yes, send it", chunk)


def decree_with_sections(sections):
    """The canned decree read with its sections replaced wholesale."""
    d = json.loads(json.dumps(DECREE))
    d["sections"] = sections
    d["refusal_tag"] = "this cannot be sent from here"
    return {"data": d, "at": 1, "error": None}


def form_chunk(html, aid):
    start = html.index('data-op="%s"' % aid)
    return html[start : html.index("</form>", start)]


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class CanSendIsHonoured(unittest.TestCase):
    """#3366: a section the read says cannot be sent renders its form
    disabled, with the read's why_not and instead where the submit was."""

    SECTIONS = (
        {
            "key": "job",
            "does": "Tells every member to switch to this job.",
            "can_send": True,
            "why_not": "",
            "instead": "",
        },
        {
            "key": "campaign",
            "does": "Sets how many runs the family wants.",
            "can_send": False,
            "why_not": "The bridge is holding the counter while a run is counted.",
            "instead": "Set the dungeon queue instead.",
        },
    )

    def reads(self):
        return on_reads(decree_with_sections(self.SECTIONS))

    def test_the_blocked_forms_are_disabled_and_say_why(self):
        html = render_with(self.reads())["html"]
        for aid in ("cap", "restart"):
            chunk = form_chunk(html, aid)
            self.assertNotIn('type="submit"', chunk, aid)
            self.assertIn("disabled", chunk, aid)
            self.assertIn("this cannot be sent from here", chunk, aid)
            self.assertIn(
                "The bridge is holding the counter while a run is counted.",
                chunk,
                aid,
            )
            self.assertIn("Set the dungeon queue instead.", chunk, aid)
        # A section that can be sent keeps its working submit.
        self.assertIn('type="submit"', form_chunk(html, "job"))

    def test_a_blocked_form_opens_no_confirm_and_sends_nothing(self):
        got = run(
            "const c = ctx(%s);\nV.render(c); V.after(main, c);\n"
            "listeners.input({target: field('cap', 'family', 'Grug')});\n"
            "listeners.input({target: field('cap', 'wanted', '0')});\n"
            "listeners.submit({target: target({'form[data-op]': 'cap'}), preventDefault() {}});\n"
            "listeners.click({target: target({'data-op-confirm': 'cap'}), preventDefault() {}});\n"
            "await new Promise((r) => setTimeout(r, 50));\n"
            "console.log(JSON.stringify({asked: swapped.some((h) => h.includes('data-op-confirm')),"
            " posted: posted.filter((p) => p.method === 'POST').length}));"
            % json.dumps(self.reads())
        )
        self.assertEqual(got, {"asked": False, "posted": 0})


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class RequiredFieldsBlockTheConfirm(unittest.TestCase):
    """#3366: a form with an empty required field opens no confirm; it
    names what is missing, in the form, and sends nothing."""

    def test_each_blank_field_names_itself(self):
        cases = (
            ("chat", (("name", "Grug"),), "Type what to say."),
            ("chat", (("text", "hello"),), "Pick who to talk to."),
            ("job", (("family", "Zug"),), "Pick a job mode."),
            ("job", (("mode", "quest"),), "Pick which family this is for."),
            ("muster", (("guild", "Cave"),), "Type the order."),
            ("cap", (("family", "Grug"),), "Type how many runs are wanted."),
            ("will", (), "Type the decree."),
            ("director", (("watch", "watch Grug"),), "Type the director token."),
        )
        for aid, fields, reason in cases:
            with self.subTest(action=aid, reason=reason):
                chunk = confirm_of(aid, fields)
                self.assertIn(reason, chunk)
                self.assertIn('role="alert"', chunk)
                self.assertNotIn("data-op-confirm", chunk)

    def test_zero_runs_wanted_is_a_value_not_a_blank(self):
        chunk = confirm_of("cap", (("family", "Grug"), ("wanted", "0")))
        self.assertIn("data-op-confirm", chunk)
        self.assertNotIn('role="alert"', chunk)

    def test_the_reason_goes_away_once_the_field_is_filled(self):
        got = run(
            "const c = ctx(%s);\nV.render(c); V.after(main, c);\n"
            "listeners.input({target: field('chat', 'name', 'Grug')});\n"
            "listeners.submit({target: target({'form[data-op]': 'chat'}), preventDefault() {}});\n"
            "const blocked = swapped[swapped.length - 1];\n"
            "listeners.input({target: field('chat', 'text', 'hello')});\n"
            "listeners.submit({target: target({'form[data-op]': 'chat'}), preventDefault() {}});\n"
            "const opened = swapped[swapped.length - 1];\n"
            "console.log(JSON.stringify({blocked, opened}));" % json.dumps(on_reads())
        )
        self.assertIn("Type what to say.", got["blocked"])
        self.assertIn("data-op-confirm", got["opened"])
        self.assertNotIn("Type what to say.", got["opened"])

    def test_an_unread_priorities_order_blocks_the_save(self):
        reads = on_reads()
        d = json.loads(json.dumps(DECREE))
        d["priorities"] = {
            "order": [],
            "entries": [],
            "state_says": "",
            "takes_effect": "",
        }
        reads["/api/decree"] = {"data": d, "at": 1, "error": None}
        chunk = confirm_of("priorities", (), reads)
        self.assertIn("The saved order is not read yet.", chunk)
        self.assertNotIn("data-op-confirm", chunk)


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class RankArrowsAndHints(unittest.TestCase):
    """#3366: priority arrows are 44px targets, and the drag hint is
    dropped where the pointer is a finger."""

    def test_the_arrows_are_44px(self):
        css = (APP / "views" / "operator.css").read_text(encoding="utf-8")
        rule = css[css.index(".op-rank-btn") :]
        rule = rule[: rule.index("}")]
        self.assertIn("min-width: 44px", rule)
        self.assertIn("min-height: 44px", rule)

    def test_the_drag_hint_drops_on_touch_pointers(self):
        css = (APP / "views" / "operator.css").read_text(encoding="utf-8")
        self.assertIn("@media (pointer: coarse)", css)
        coarse = css[css.index("@media (pointer: coarse)") :]
        self.assertIn(".op-hint-fine", coarse)
        self.assertIn("display: none", coarse)
        html = render_with(on_reads())["html"]
        self.assertIn("op-hint-fine", html)
        self.assertIn("Drag a row", html)
        self.assertNotIn("op-hint-coarse", html)


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class SectionOrderByPhoneUse(unittest.TestCase):
    """#3366: Talk and Travel lead the page, the Watcher comes last."""

    def test_the_sections_run_talk_travel_decree_watcher(self):
        html = render_with(on_reads())["html"]
        heads = [
            html.index('id="op-h-%s"' % name)
            for name in ("talk", "travel", "decree", "watcher")
        ]
        self.assertEqual(heads, sorted(heads))
        self.assertLess(html.index('data-op="chat"'), html.index('data-op="job"'))
        self.assertLess(html.index('data-op="aim"'), html.index('data-op="job"'))
        self.assertLess(html.index('data-op="job"'), html.index('data-op="director"'))


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class ThePollWaitsForTheOperator(unittest.TestCase):
    """#3366: the view's own swap (the seam main.js offers a view) holds
    the page while a form is being edited or a confirm is open, so the
    30 second poll never redraws over a draft, focus, caret or scroll."""

    FAKE = "{innerHTML: 'OLD', querySelector: () => ({}), contains: () => true}"

    def swap_after(self, steps):
        return run(
            "const c = ctx(%s);\nV.render(c); V.after(main, c);\n%s"
            "const m = %s;\nconst took = V.swap(m, 'NEW');\n"
            "console.log(JSON.stringify({took, html: m.innerHTML}));"
            % (json.dumps(on_reads()), steps, self.FAKE)
        )

    def test_a_redraw_swaps_when_nothing_is_being_edited(self):
        self.assertEqual(self.swap_after(""), {"took": True, "html": "NEW"})

    def test_a_redraw_waits_while_a_confirm_is_open(self):
        got = self.swap_after(
            "listeners.input({target: field('chat', 'name', 'Grug')});\n"
            "listeners.input({target: field('chat', 'text', 'hello')});\n"
            "listeners.submit({target: target({'form[data-op]': 'chat'}), preventDefault() {}});\n"
        )
        self.assertEqual(got, {"took": True, "html": "OLD"})

    def test_a_redraw_waits_while_a_field_has_focus(self):
        got = self.swap_after(
            "document.activeElement = {getAttribute: (a) => a === 'data-op-field' ? 'chat' : null};\n"
        )
        self.assertEqual(got, {"took": True, "html": "OLD"})

    def test_a_redraw_waits_while_a_form_holds_an_unsent_draft(self):
        # Typed and then left (no focus, no submit): the draft is an edit
        # in progress, and the poll must not draw over it.
        got = self.swap_after(
            "listeners.input({target: field('chat', 'text', 'half a thought')});\n"
        )
        self.assertEqual(got, {"took": True, "html": "OLD"})

    def test_a_redraw_resumes_once_the_send_completes(self):
        got = run(
            "const c = ctx(%s);\nV.render(c); V.after(main, c);\n"
            "listeners.input({target: field('chat', 'name', 'Grug')});\n"
            "listeners.input({target: field('chat', 'text', 'hello')});\n"
            "listeners.submit({target: target({'form[data-op]': 'chat'}), preventDefault() {}});\n"
            "listeners.click({target: target({'data-op-confirm': 'chat'}), preventDefault() {}});\n"
            "await new Promise((r) => setTimeout(r, 50));\n"
            "const m = %s;\nconst took = V.swap(m, 'NEW');\n"
            "console.log(JSON.stringify({took, html: m.innerHTML}));"
            % (json.dumps(on_reads()), self.FAKE)
        )
        self.assertEqual(got, {"took": True, "html": "NEW"})


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class TheWillFanout(unittest.TestCase):
    """#3366: the will's confirm counts its audience and says a sent line
    cannot be unsent; the send shows how many have gone."""

    def test_the_confirm_counts_the_audience(self):
        chunk = confirm_of("will", (("text", "Hold the bridge."),))
        self.assertIn("2 of them", chunk)
        self.assertIn("Grug, Bork", chunk)
        self.assertIn("one by one", chunk)
        self.assertIn("cannot be unsent", chunk)
        self.assertIn("&quot;Hold the bridge.&quot;", chunk)

    def test_the_send_shows_how_many_have_gone(self):
        got = run(
            "const gates = [];\n"
            "globalThis.fetch = async (url, opts) => { posted.push({url, method: 'POST', body: opts && opts.body});"
            " return new Promise((res) => gates.push(() => res({ok: true, status: 200,"
            " json: async () => ({say: 'Heard.'}), text: async () => '{}'}))); };\n"
            "const c = ctx(%s);\nV.render(c); V.after(main, c);\n"
            "listeners.input({target: field('will', 'text', 'Hold the bridge.')});\n"
            "listeners.submit({target: target({'form[data-op]': 'will'}), preventDefault() {}});\n"
            "listeners.click({target: target({'data-op-confirm': 'will'}), preventDefault() {}});\n"
            "await new Promise((r) => setTimeout(r, 20));\n"
            "gates[0]();\n"
            "await new Promise((r) => setTimeout(r, 20));\n"
            "const mid = swapped[swapped.length - 1];\n"
            "gates[1]();\n"
            "await new Promise((r) => setTimeout(r, 50));\n"
            "const done = swapped[swapped.length - 1];\n"
            "console.log(JSON.stringify({mid, done, sent: posted.length}));"
            % json.dumps(on_reads())
        )
        self.assertIn("Sent 1 of 2", got["mid"])
        self.assertIn("Answers, in the order they were asked", got["done"])
        self.assertEqual(got["sent"], 2)


if __name__ == "__main__":
    unittest.main()
