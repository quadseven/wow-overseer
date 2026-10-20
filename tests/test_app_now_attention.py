"""What needs the operator on Now: the chips and the Attention list agree.

The operator saw "6 ghosts" on the ghost chip and "4 ghosts" in the
Attention list on one Now page. These tests render the app's Now view under
node from fixed reads and pin why the two cannot disagree:

- both are drawn by one render() from one value: the view reads
  /api/v2/roster once per draw (app/models/roster.js ghosts(), a corpse or a
  released spirit, over every member of both family guilds, not only the
  families) and hands that one list to the chip and to the Attention row;
- the 5 s quick pace polls only /api/eye and /api/v2/roll, and any answer
  redraws the whole page from the api.js cache, so no timer refreshes one of
  the two without the other;
- a roster that has not answered, or that read nobody's life, is "not
  measured" in both places, never a number in one and not in the other.

And the stuck count takes a stalled family's leader (/api/v2/stuck kind
"stall", #1257) as one stuck member like the rest, the Members badge's
count, and the Attention list says how many of them lead a stalled family.
"""

import json
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
APP = HERE / "app"

NODE = shutil.which("node")
needs_node = unittest.skipIf(NODE is None, "node is not on PATH")

# Just enough of a browser for views/now.js and what it imports to load.
# `reads` maps a path to its payload; every other read is still loading.
RENDER = r"""
const noop = () => {};
globalThis.window = globalThis;
globalThis.addEventListener = noop;
globalThis.matchMedia = () => ({ matches: false, addEventListener: noop });
globalThis.localStorage = { getItem: () => null, setItem: noop };
globalThis.document = {
  addEventListener: noop, removeEventListener: noop,
  querySelector: () => null, querySelectorAll: () => [], getElementById: () => null,
  createElement: () => ({ style: {}, setAttribute: noop, appendChild: noop }),
  documentElement: { setAttribute: noop, getAttribute: () => null },
  head: { appendChild: noop }, body: { appendChild: noop },
};
const fixture = JSON.parse(process.argv[2]);
const { learn } = await import("./app/families.js");
learn({ families: fixture.families.map((key) => ({ key })), guilds: [] });
const now = (await import("./app/views/now.js")).default;
const waiting = { data: undefined, at: 0, error: null, loading: true };
const get = (path) => (path in fixture.reads ? { data: fixture.reads[path], at: 1, error: null, loading: false } : waiting);
const out = now.render({ get, isPhone: false, previousVisit: 0, params: {}, query: {} });
console.log(JSON.stringify({ markup: String(out && out.s !== undefined ? out.s : out), quick: now.quick, every: now.every }));
process.exit(0);
"""


def render(reads, families=("Grug",)):
    """The Now view's markup (and its paces) for these reads."""
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        shutil.copytree(APP, root / "app")
        (root / "package.json").write_text('{"type": "module"}', encoding="utf-8")
        (root / "run.js").write_text(RENDER, encoding="utf-8")
        out = subprocess.run(
            [
                NODE,
                str(root / "run.js"),
                json.dumps({"families": list(families), "reads": reads}),
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    if out.returncode != 0:
        raise AssertionError(out.stderr)
    return json.loads(out.stdout.strip().splitlines()[-1])


def chip_text(markup, tone):
    m = re.search(
        r'<a class="nchip" href="[^"]*" data-tone="'
        + tone
        + r'"[^>]*>.*?</i>(.*?)</a>',
        markup,
        re.S,
    )
    assert m, "no %s chip" % tone
    return re.sub(r"<[^>]+>", "", m.group(1))


def attention_text(markup, query):
    m = re.search(
        r'<a class="arow" href="#/members\?'
        + query
        + r'=1">.*?<span class="grow">(.*?)</span>',
        markup,
        re.S,
    )
    assert m, "no %s row in Attention" % query
    return re.sub(r"<[^>]+>", "", m.group(1))


def count(text, noun):
    m = re.match(r"(\d+) " + noun, text)
    return None if m is None else int(m.group(1))


def member(name, life, guild="Cave"):
    return {"name": name, "guild": guild, "life": life, "online": True, "stuck": False}


# Two family members and two guildmates down, one alive, one never read.
ROSTER = {
    "checked_at": 1000,
    "members": [
        member("Grug", "ghost"),
        member("Og", "dead"),
        member("Pogg", "alive"),
        member("Mate", "ghost", guild="Bonkers"),
        member("Corpse", "dead", guild="Bonkers"),
        member("Unread", None, guild="Bonkers"),
    ],
}


@needs_node
class GhostsAreOneCount(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.markup = render({"/api/v2/roster": ROSTER})["markup"]

    def test_the_chip_and_the_attention_list_say_the_same_number(self):
        on_chip = count(chip_text(self.markup, "ghost"), "ghost")
        in_list = count(attention_text(self.markup, "ghost"), "ghost")
        self.assertEqual(on_chip, in_list)

    def test_it_is_every_corpse_and_spirit_of_both_guilds(self):
        # Not the families only, and a corpse counts with a released spirit.
        self.assertEqual(chip_text(self.markup, "ghost"), "4 ghosts")
        self.assertEqual(
            attention_text(self.markup, "ghost"), "4 ghosts: Grug, Og, Mate, Corpse"
        )

    def test_a_roster_not_answered_is_not_measured_in_both(self):
        markup = render({})["markup"]
        self.assertEqual(chip_text(markup, "ghost"), "Ghosts not measured")
        self.assertIn("not measured", attention_text(markup, "ghost"))
        self.assertIsNone(count(attention_text(markup, "ghost"), "ghost"))

    def test_a_roster_with_no_life_read_is_not_measured_in_both(self):
        unread = {
            "checked_at": 1000,
            "members": [member("Grug", None), member("Og", None)],
        }
        markup = render({"/api/v2/roster": unread})["markup"]
        self.assertEqual(chip_text(markup, "ghost"), "Ghosts not measured")
        self.assertIsNone(count(attention_text(markup, "ghost"), "ghost"))

    def test_no_quick_timer_refreshes_the_roster_alone(self):
        # The 5 s pace reads the realm strip only; the roster and the stuck
        # list keep the view's own pace, and every answer redraws the page.
        got = render({})
        self.assertEqual(sorted(got["quick"]["reads"]), ["/api/eye", "/api/v2/roll"])
        self.assertNotIn("/api/v2/roster", got["quick"]["reads"])
        self.assertNotIn("/api/v2/stuck", got["quick"]["reads"])

    def test_the_view_reads_the_roster_once_per_draw(self):
        # One read model per draw, shared by the chip and the list: a second
        # roster read in the view could be handed a different answer.
        src = (APP / "views" / "now.js").read_text(encoding="utf-8")
        self.assertEqual(
            src.count('rosterModel(ctx.get("/api/v2/roster")).ghosts()'), 1
        )
        self.assertEqual(src.count('D.stuck(ctx.get("/api/v2/stuck"))'), 1)


def stuck_row(name, kind, since=400):
    return {
        "name": name,
        "step": "walking",
        "blocker": "a hold",
        "since": since,
        "kind": kind,
        "follows": "",
    }


@needs_node
class AStallIsAStuckMemberAndSaysSo(unittest.TestCase):
    def test_the_stall_counts_and_the_list_says_it_leads_a_stalled_family(self):
        stuck = {
            "checked_at": 1000,
            "members": [
                stuck_row("Grug", "stall", since=100),
                stuck_row("Og", "hold"),
                stuck_row("Pogg", "class quest"),
            ],
        }
        markup = render({"/api/v2/stuck": stuck})["markup"]
        # The Members badge counts every /api/v2/stuck row; the chip does too.
        self.assertEqual(count(chip_text(markup, "stuck"), "stuck"), 3)
        self.assertEqual(
            attention_text(markup, "stuck"),
            "3 members stuck (1 leads a stalled family)",
        )

    def test_two_stalls_are_said_as_two(self):
        stuck = {
            "checked_at": 1000,
            "members": [stuck_row("Grug", "stall"), stuck_row("Zug", "stall")],
        }
        markup = render({"/api/v2/stuck": stuck})["markup"]
        self.assertEqual(
            attention_text(markup, "stuck"),
            "2 members stuck (2 lead stalled families)",
        )

    def test_no_stall_adds_nothing(self):
        stuck = {"checked_at": 1000, "members": [stuck_row("Og", "hold")]}
        markup = render({"/api/v2/stuck": stuck})["markup"]
        self.assertEqual(attention_text(markup, "stuck"), "1 member stuck")


if __name__ == "__main__":
    unittest.main()
