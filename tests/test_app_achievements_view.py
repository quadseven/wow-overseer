"""The achievements views, drawn by app/views/_achievements.js: the profile
badges card, the Chronicle feed row and the toast on Now.

Run under node against small stand-ins for the browser, like the other app
view tests. The toast tests drive announce() with a fake document, a fake
localStorage and captured timers, because the seen rule is the behaviour:
what a toast marks seen, and when.
"""

import json
import unittest

from test_app_flagship import app_file, needs_node, run_node

API_STUB = (
    'export const u = (p) => "/m" + p;\n'
    "export const peek = () => ({ data: undefined });\n"
    "export const load = () => Promise.resolve();\n"
)
FAMILIES_STUB = (
    "export const guildSlug = (name) =>"
    ' ({ Cave: "cave", Bonkers: "bonkers" })[name] || "";\n'
)
FILES = {
    "views/_achievements.js": None,
    "models/achievements.js": None,
    "models/time.js": None,
    "ui.js": None,
    "api.js": API_STUB,
    "families.js": FAMILIES_STUB,
}

T = 1791576724


def ach(i, at, tier="bronze", member="Grug"):
    return {
        "id": "rule:%s:%d" % (member, i),
        "rule": "rule",
        "title": "T%d" % i,
        "line": "L%d" % i,
        "tier": tier,
        "member": member,
        "who": [member] if member else ["Grug", "Ugga"],
        "guild": "Cave",
        "earned_at": at,
        "source": {"table": "x", "id": i},
    }


# Three new since the visit: a dubious one newest, a gold one (the headline
# a toast leads with), then a bronze one.
NEWS = [ach(1, T + 300, "dubious"), ach(2, T + 200, "gold"), ach(3, T + 100)]
READ = {"data": {"items": NEWS, "count": 3}, "loading": False}

FAKES = """
const store = new Map();
const timers = [];
let appended = null;
const xBtn = { addEventListener(_t, f) { xBtn.click = f; } };
const links = [{ addEventListener(_t, f) { this.click = f; } }];
function fakeEl() {
  const el = { listeners: {}, removed: false,
    classList: { add() {} },
    setAttribute() {},
    addEventListener(t, f) { el.listeners[t] = f; },
    querySelector(_s) { return xBtn; },
    querySelectorAll(_s) { return links; },
    remove() { el.removed = true; } };
  return el;
}
globalThis.document = { createElement: () => fakeEl(),
  body: { appendChild(e) { appended = e; } } };
globalThis.window = {
  addEventListener() {},
  localStorage: { getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, v) },
  setTimeout: (fn, ms) => { timers.push({ fn, ms }); return timers.length; },
  clearTimeout: () => {},
  matchMedia: () => ({ matches: COARSE }),
};
const seen = () => JSON.parse(store.get("overseer.achievements.seen") || "[]");
"""


def toast_script(body, coarse=False):
    files = {k: (v if v is not None else app_file(k)) for k, v in FILES.items()}
    script = (
        "const COARSE = %s;\n" % ("true" if coarse else "false")
        + FAKES
        + 'const A = await import("./views/_achievements.js");\n'
        + body
    )
    return run_node(files, script)


@needs_node
class TheToastSeenRule(unittest.TestCase):
    def test_display_marks_only_the_headline_seen(self):
        out = toast_script(
            "A.announce(%s, %d);\n"
            "console.log(JSON.stringify({seen: seen(), html: appended.innerHTML}));\n"
            % (json.dumps(READ), T * 1000)
        )
        self.assertEqual(out["seen"], [NEWS[1]["id"]])
        self.assertIn("T2", out["html"])
        self.assertIn("and 2 more", out["html"])

    def test_a_timeout_leaves_the_rest_to_be_offered_again(self):
        out = toast_script(
            "A.announce(%s, %d);\n"
            "timers[0].fn();\n"
            "const afterTimeout = seen();\n"
            "A.announce(%s, %d);\n"
            "console.log(JSON.stringify({afterTimeout, seen: seen(),"
            " html: appended.innerHTML}));\n"
            % (json.dumps(READ), T * 1000, json.dumps(READ), T * 1000)
        )
        self.assertEqual(out["afterTimeout"], [NEWS[1]["id"]])
        self.assertEqual(out["seen"], [NEWS[1]["id"], NEWS[0]["id"]])
        self.assertIn("T1", out["html"])
        self.assertIn("and 1 more", out["html"])

    def test_dismissing_marks_the_rest_seen(self):
        out = toast_script(
            "A.announce(%s, %d);\n"
            "xBtn.click();\n"
            "console.log(JSON.stringify({seen: seen()}));\n"
            % (json.dumps(READ), T * 1000)
        )
        self.assertEqual(sorted(out["seen"]), sorted(a["id"] for a in NEWS))

    def test_tapping_through_marks_the_rest_seen(self):
        out = toast_script(
            "A.announce(%s, %d);\n"
            "links[0].click();\n"
            "console.log(JSON.stringify({seen: seen()}));\n"
            % (json.dumps(READ), T * 1000)
        )
        self.assertEqual(sorted(out["seen"]), sorted(a["id"] for a in NEWS))

    def test_the_toast_runs_longer_on_touch(self):
        out = toast_script(
            "A.announce(%s, %d);\n"
            "console.log(JSON.stringify({ms: timers[0].ms}));\n"
            % (json.dumps(READ), T * 1000),
            coarse=True,
        )
        self.assertEqual(out["ms"], 14000)
        out = toast_script(
            "A.announce(%s, %d);\n"
            "console.log(JSON.stringify({ms: timers[0].ms}));\n"
            % (json.dumps(READ), T * 1000)
        )
        self.assertEqual(out["ms"], 9000)

    def test_a_dubious_toast_does_not_say_earned(self):
        one = {
            "data": {"items": [ach(7, T + 300, "dubious")], "count": 1},
            "loading": False,
        }
        out = toast_script(
            "A.announce(%s, %d);\n"
            "console.log(JSON.stringify({html: appended.innerHTML}));\n"
            % (json.dumps(one), T * 1000)
        )
        self.assertIn("picked up", out["html"])
        self.assertNotIn(" earned ", out["html"])


@needs_node
class TheProfileCard(unittest.TestCase):
    def draw(self, read):
        files = {k: (v if v is not None else app_file(k)) for k, v in FILES.items()}
        out = run_node(
            files,
            "globalThis.window = { addEventListener() {} };\n"
            'const A = await import("./views/_achievements.js");\n'
            "console.log(JSON.stringify({m: String(A.badgesCard(%s, 'Grug'))}));\n"
            % json.dumps(read),
        )
        return out["m"]

    def test_the_tally_leads_the_card_and_three_badges_show(self):
        items = [ach(i, T + i * 10, "silver") for i in range(8)]
        read = {
            "data": {
                "items": items,
                "count": 5,
                "of": 9,
                "tiers": {"gold": 1, "silver": 2, "bronze": 2},
                "basis": "Basis.",
            },
            "loading": False,
        }
        m = self.draw(read)
        self.assertIn('class="ach-tally"', m)
        self.assertLess(m.index("5 of 9"), m.index('class="ach-badge"'))
        before_fold = m[: m.index("ach-more")]
        self.assertEqual(before_fold.count('class="ach-badge"'), 3)
        self.assertIn("5 more achievements", m)


@needs_node
class TheFeedRow(unittest.TestCase):
    def test_the_feed_medal_is_the_profile_size_with_the_time_under(self):
        files = {k: (v if v is not None else app_file(k)) for k, v in FILES.items()}
        out = run_node(
            files,
            "globalThis.window = { addEventListener() {} };\n"
            'const A = await import("./views/_achievements.js");\n'
            "console.log(JSON.stringify({m: String(A.feedRow(%s, {}))}));\n"
            % json.dumps(ach(1, T, "gold")),
        )
        m = out["m"]
        self.assertIn("ach-medal ach-medal-lg", m)
        self.assertIn("ach-when", m)
        self.assertLess(m.index("ach-line"), m.index("ach-when"))


if __name__ == "__main__":
    unittest.main()
