"""Now on a phone: one pinned stage, one connected stream, a calm redraw.

The pure pieces run under node (the same harness as test_app_scrollanchor.py):
the redraw hold with a fake clock, the identical-body gate, the scroll write
rule, the staged choice and its persistence, and the one-stream plan. The Now
view is also rendered under node at a narrow and a wide width to check what
the markup holds.
"""

import json
import pathlib
import shutil
import subprocess
import tempfile
import unittest

from test_app_shell import node_module

HERE = pathlib.Path(__file__).resolve().parent.parent
APP = HERE / "app"
NODE = shutil.which("node")
needs_node = unittest.skipIf(NODE is None, "node is needed to run the app's modules")

CLOCK = """
let t = 0;
const timers = new Map();
let nextId = 1;
const clock = {
  now: () => t,
  setTimer: (fn, ms) => { const id = nextId++; timers.set(id, { fn, at: t + ms }); return id; },
  clearTimer: (id) => timers.delete(id),
  advance(ms) {
    const end = t + ms;
    for (;;) {
      const due = [...timers.entries()].filter(([, v]) => v.at <= end).sort((a, b) => a[1].at - b[1].at)[0];
      if (!due) break;
      timers.delete(due[0]);
      t = due[1].at;
      due[1].fn();
    }
    t = end;
  },
};
let applied = 0;
const hold = M.makeHold({ ...clock, apply: () => { applied++; }, quiet: 150 });
"""


def hold(body):
    return node_module(
        "redraw.js",
        "console.log(JSON.stringify((() => {\n" + CLOCK + body + "\n})()));",
    )


@needs_node
class HoldWhileScrolling(unittest.TestCase):
    def test_an_idle_page_redraws_at_once(self):
        self.assertEqual(hold("hold.request(); return applied;"), 1)

    def test_a_redraw_during_a_scroll_waits_for_it_to_settle(self):
        got = hold(
            """
            hold.scrolled();
            clock.advance(100);
            hold.request();
            const during = applied;
            clock.advance(40);
            const early = applied;
            clock.advance(20);
            return [during, early, applied];
            """
        )
        self.assertEqual(got, [0, 0, 1])

    def test_a_touch_in_progress_holds_the_redraw_however_long_it_lasts(self):
        got = hold(
            """
            hold.touchStart();
            hold.request();
            clock.advance(5000);
            const held = applied;
            hold.touchEnd();
            clock.advance(149);
            const settling = applied;
            clock.advance(2);
            return [held, settling, applied];
            """
        )
        self.assertEqual(got, [0, 0, 1])

    def test_only_the_latest_pending_redraw_is_applied(self):
        got = hold(
            """
            hold.scrolled();
            hold.request(); hold.request(); hold.request();
            clock.advance(400);
            return applied;
            """
        )
        self.assertEqual(got, 1)

    def test_scroll_end_applies_the_redraw_without_waiting_for_the_timer(self):
        got = hold(
            """
            hold.scrolled();
            hold.request();
            hold.scrollEnd();
            return applied;
            """
        )
        self.assertEqual(got, 1)

    def test_scroll_end_does_not_release_a_redraw_while_a_finger_is_down(self):
        got = hold(
            """
            hold.touchStart();
            hold.request();
            hold.scrollEnd();
            return applied;
            """
        )
        self.assertEqual(got, 0)

    def test_a_scroll_that_keeps_going_keeps_the_redraw_waiting(self):
        got = hold(
            """
            hold.request();
            const first = applied;
            hold.scrolled();
            hold.request();
            for (let i = 0; i < 10; i++) { clock.advance(100); hold.scrolled(); }
            const during = applied;
            clock.advance(200);
            return [first, during, applied];
            """
        )
        self.assertEqual(got, [1, 1, 2])


@needs_node
class IdenticalBodyIsSkipped(unittest.TestCase):
    def test_the_same_body_on_the_same_page_is_not_drawn_again(self):
        got = node_module(
            "redraw.js",
            """
            const g = M.makeGate();
            console.log(JSON.stringify([
              g.changed("#/now", "a"), g.changed("#/now", "a"), g.changed("#/now", "b"),
              g.changed("#/now", "b"), g.changed("#/other", "b"),
            ]));
            """,
        )
        self.assertEqual(got, [True, False, True, False, True])

    def test_a_reset_forgets_the_last_body(self):
        got = node_module(
            "redraw.js",
            """
            const g = M.makeGate();
            g.changed("#/now", "a"); g.reset();
            console.log(JSON.stringify(g.changed("#/now", "a")));
            """,
        )
        self.assertTrue(got)


@needs_node
class NoScrollWriteWhenTheAnchorDidNotMove(unittest.TestCase):
    def run_target(self, args):
        return node_module(
            "scrollanchor.js",
            "console.log(JSON.stringify(M.restoreTarget(%s)));" % args,
        )

    def test_no_write_when_the_page_is_already_where_the_reader_was(self):
        self.assertIsNone(self.run_target("640, 0, 640"))

    def test_no_write_for_a_sub_pixel_difference(self):
        self.assertIsNone(self.run_target("640, 0.3, 640.2"))

    def test_the_anchor_moving_gives_the_new_target(self):
        self.assertEqual(self.run_target("640, 30, 640"), 670)

    def test_a_page_that_shifted_under_the_reader_is_put_back(self):
        self.assertEqual(self.run_target("640, 0, 0"), 640)

    def test_the_target_never_goes_above_the_top(self):
        self.assertEqual(self.run_target("10, -50, 10"), 0)


STORE = """
const mem = new Map();
globalThis.window = { localStorage: {
  getItem: (k) => (mem.has(k) ? mem.get(k) : null),
  setItem: (k, v) => mem.set(k, String(v)),
} };
"""


@needs_node
class StagedChoiceSurvivesAReload(unittest.TestCase):
    def test_a_saved_choice_is_read_back(self):
        got = node_module(
            "store.js",
            STORE
            + "M.saveStage('Zug'); console.log(JSON.stringify([M.savedStage(), [...mem.keys()].filter((k) => k.includes('stage'))]));",
        )
        self.assertEqual(got[0], "Zug")
        self.assertEqual(len(got[1]), 1)

    def test_nothing_saved_reads_as_no_choice(self):
        got = node_module(
            "store.js", STORE + "console.log(JSON.stringify(M.savedStage()));"
        )
        self.assertEqual(got, "")

    def test_the_saved_choice_stages_that_family_when_it_has_a_stream(self):
        got = node_module(
            "views/now/stagechoice.js",
            """
            const opts = [{ fam: "Grug", name: "a", url: "u1" }, { fam: "Zug", name: "b", url: "u2" }];
            console.log(JSON.stringify([M.pickStaged(opts, "Zug"), M.pickStaged(opts, "Mok"), M.pickStaged(opts, ""), M.pickStaged([], "Zug")]));
            """,
        )
        self.assertEqual(got, ["Zug", "Grug", "Grug", ""])

    def test_the_default_is_the_first_family_with_a_stream(self):
        got = node_module(
            "views/now/stagechoice.js",
            """
            const opts = [{ fam: "Grug", name: "a", url: "" }, { fam: "Zug", name: "b", url: "u2" }];
            console.log(JSON.stringify(M.pickStaged(opts, "")));
            """,
        )
        self.assertEqual(got, "Zug")


@needs_node
class OneStreamAtNarrowWidths(unittest.TestCase):
    OPTS = (
        'const opts = [{ fam: "Grug", name: "a", url: "u1" },'
        ' { fam: "Zug", name: "b", url: "u2" }, { fam: "Mok", name: "c", url: "" }];'
    )

    def plan(self, narrow, staged):
        return node_module(
            "views/now/stagechoice.js",
            self.OPTS
            + "console.log(JSON.stringify(M.connectPlan(opts, %s, %s)));"
            % (json.dumps(staged), "true" if narrow else "false"),
        )

    def test_narrow_connects_only_the_staged_stream_and_releases_the_rest(self):
        got = self.plan(True, "Zug")
        self.assertEqual(got["connect"], [{"name": "b", "url": "u2"}])
        self.assertEqual(sorted(got["release"]), ["a", "c"])

    def test_wide_connects_every_stream_and_releases_none(self):
        got = self.plan(False, "Zug")
        self.assertEqual(
            got["connect"],
            [
                {"name": "a", "url": "u1"},
                {"name": "b", "url": "u2"},
                {"name": "c", "url": ""},
            ],
        )
        self.assertEqual(got["release"], [])


RENDER = r"""
const noop = () => {};
globalThis.window = globalThis;
globalThis.addEventListener = noop;
const fx = JSON.parse(process.argv[2]);
globalThis.matchMedia = () => ({ matches: fx.narrow, addEventListener: noop });
globalThis.localStorage = { getItem: (k) => (k === "overseer.stage" ? fx.saved : null), setItem: noop };
globalThis.document = {
  addEventListener: noop, removeEventListener: noop,
  querySelector: () => null, querySelectorAll: () => [], getElementById: () => null,
  createElement: () => ({ style: {}, setAttribute: noop, appendChild: noop }),
  documentElement: { setAttribute: noop, getAttribute: () => null },
  head: { appendChild: noop }, body: { appendChild: noop },
};
const { learn } = await import("./app/families.js");
learn({ families: fx.families.map((key) => ({ key })), guilds: [] });
const now = (await import("./app/views/now.js")).default;
const waiting = { data: null, at: 0, error: null, loading: true };
const wall = {
  data: {
    members: fx.families.map((f) => ({ name: f + "ling", family: f, class: "mage" })),
    wall: { tiles: fx.families.map((f) => ({ name: f + "ling", url: "https://stream.example/" + f })) },
  },
  at: 1, error: null, loading: false,
};
const get = (path) => (path === "/api/wall" ? wall : waiting);
const out = now.render({ get, isPhone: fx.narrow, previousVisit: 0, params: {}, query: {} });
console.log(JSON.stringify(String(out && out.s !== undefined ? out.s : out)));
process.exit(0);
"""


def render(narrow, saved=None, families=("Grug", "Zug", "Mok")):
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        shutil.copytree(APP, root / "app")
        (root / "package.json").write_text('{"type": "module"}', encoding="utf-8")
        (root / "run.js").write_text(RENDER, encoding="utf-8")
        out = subprocess.run(
            [
                NODE,
                str(root / "run.js"),
                json.dumps(
                    {"narrow": narrow, "saved": saved, "families": list(families)}
                ),
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    if out.returncode != 0:
        raise AssertionError(out.stderr)
    return json.loads(out.stdout.strip().splitlines()[-1])


@needs_node
class TheNowMarkup(unittest.TestCase):
    def test_wide_keeps_a_video_slot_in_every_family_unit(self):
        self.assertEqual(render(False).count("data-stream="), 3)

    def test_narrow_has_no_video_slot_in_the_redrawn_page(self):
        self.assertNotIn("data-stream=", render(True))

    def test_narrow_puts_the_staged_family_first_then_the_others(self):
        body = render(True, saved="Zug")
        order = [
            part.split('"')[0] for part in body.split('class="fam" data-family="')[1:]
        ]
        self.assertEqual(order, ["Zug", "Grug", "Mok"])

    def test_narrow_without_a_saved_choice_stages_the_first_streamed_family(self):
        body = render(True)
        self.assertIn('data-family="Grug" data-staged', body)
        self.assertEqual(body.count("data-staged"), 1)

    def test_narrow_leads_with_the_families_and_trails_with_the_chips(self):
        body = render(True)
        self.assertLess(body.index('class="fams"'), body.index('class="nchips"'))
        self.assertLess(body.index('class="fams"'), body.index("now-head"))

    def test_narrow_hears_only_the_staged_family(self):
        self.assertEqual(render(True, saved="Mok").count("data-hear="), 1)


if __name__ == "__main__":
    unittest.main()
