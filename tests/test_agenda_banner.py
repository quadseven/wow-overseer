"""The current-goal banner's page contract (infra#3205).

Asserted against index.html as source, the way test_family_tab.py,
test_armory_tab.py and test_chronicle_tab.py do: map_server.py imports
pymysql and the page has no other test seam.

The first class here is about WHERE the code sits, and it is not bookkeeping.
Three tab suites slice this file by their own banners - the Family from its
banner to loadZones().then(, the Armory and the Wealth view from theirs to
</script>, the Chronicle from its to the Council's - and anything dropped
inside one of those windows silently becomes part of a contract about a
different tab. This banner is not a tab at all, so it has to sit in the one
gap none of them claim.
"""

import pathlib
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
BANNER = "// --- the current goal banner (infra#3205)"
CSS_BANNER = "/* --- the current goal banner (infra#3205)"
CHRONICLE = "// --- the Chronicle (infra#2597, mod-overseer#88, mod-overseer#152)"
CHRONICLE_CSS = "/* --- the Chronicle (infra#2597, mod-overseer#88, mod-overseer#152)"
FAMILY_CSS = "--- the Family tab (infra#2892)"


class WhereTheCodeIsAllowedToSit(unittest.TestCase):
    def test_the_handler_sits_outside_the_family_and_armory_windows(self):
        """Both suites slice map_server.py to `def _thoughts`."""
        server = (HERE / "map_server.py").read_text(encoding="utf-8")
        self.assertGreater(server.index("def _agenda"), server.index("def _thoughts"))


class TheEndpointIsWiredUp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = (HERE / "map_server.py").read_text(encoding="utf-8")

    def test_the_route_exists(self):
        self.assertIn('"/api/agenda": _agenda,', self.server)

    def test_the_endpoint_takes_a_family_and_never_a_roster(self):
        """The family key, through the same _family_scope the quest board
        uses, and nothing else from the request. Unscoped, the banner read
        both families' rows as one family."""
        handler = self.server[self.server.index("def _agenda") :]
        handler = handler[: handler.index("def do_POST")]
        self.assertIn("self._family_scope(query)", handler)
        self.assertIn(
            "agenda.build_agenda(**_fetch_agenda(names), members=names)", handler
        )
        self.assertNotIn("query.get", handler)

    def test_a_failed_query_is_a_503_and_not_an_empty_banner(self):
        handler = self.server[self.server.index("def _agenda") :]
        handler = handler[: handler.index("def do_POST")]
        self.assertIn("503", handler)

    def test_the_module_ships_in_the_image(self):
        dockerfile = (HERE / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("agenda.py", dockerfile)


class EveryOverseerTableReadIsGuarded(unittest.TestCase):
    """infra#3172 cost a whole tab on production because one read of a table
    the module creates was not guarded. infra#2846 cost the family their quest
    drive because one COLUMN was missing. Both classes are guarded here, and
    this is the test that says so out loud."""

    @classmethod
    def setUpClass(cls):
        cls.server = (HERE / "map_server.py").read_text(encoding="utf-8")
        start = cls.server.index("def _fetch_agenda")
        cls.fetch = cls.server[start : cls.server.index("def _fetch_streams", start)]

    def test_every_overseer_table_goes_through_the_guard(self):
        for table in (
            "overseer_roster",
            "overseer_dungeon_run",
            "overseer_goal",
            "overseer_trade",
            "overseer_event",
        ):
            self.assertIn('"%s")' % table, self.fetch, table)

    def test_the_guard_swallows_a_missing_column_as_well_as_a_missing_table(self):
        guard = self.server[
            self.server.index("def _guarded") : self.server.index("def _fetch_agenda")
        ]
        self.assertIn("(1054, 1146)", guard)

    def test_the_guard_swallows_nothing_else(self):
        """Anything but those two is a real fault and must still reach the
        handler's 503, rather than being rendered as an empty banner."""
        guard = self.server[
            self.server.index("def _guarded") : self.server.index("def _fetch_agenda")
        ]
        self.assertIn("raise", guard)

    def test_the_newest_columns_have_an_older_fallback(self):
        """dungeon_runs_*, campaign_id, run_number, outcome and members all
        landed on 2026-09-02. A world predating them must get a thinner
        banner, not a 503."""
        self.assertIn("_ROSTER_OLD", self.fetch)
        self.assertIn("_RUNS_OLD", self.fetch)
        self.assertNotIn(
            "dungeon_runs_done",
            self.server[
                self.server.index("_ROSTER_OLD =") : self.server.index("_RUNS_FULL =")
            ],
        )

    def test_the_reserved_word_lead_is_escaped_in_both_roster_reads(self):
        """`lead` is reserved in MySQL 8. An unquoted one is a syntax error,
        which no schema fallback would catch."""
        block = self.server[
            self.server.index("_ROSTER_FULL =") : self.server.index("_RUNS_FULL =")
        ]
        self.assertEqual(block.count("`lead`"), 2)
        self.assertNotIn(" lead,", block)

    def test_the_agenda_roster_read_carries_family(self):
        block = self.server[
            self.server.index("_ROSTER_FULL =") : self.server.index("_RUNS_FULL =")
        ]
        self.assertIn("family", block)


if __name__ == "__main__":
    unittest.main()


# A stand-in for the few DOM calls the banner makes. Enough to hold a tree and
# say where every node ended up; nothing that could pass for a browser.
FAKE_DOM = r"""
class El {
  constructor(tag, id) { this.tag = tag; this.id = id || ""; this.children = [];
    this.parentElement = null; this._text = ""; this.className = "";
    const self = this;
    this.classList = {
      add(...c) { const s = new Set(self.className.split(" ").filter(Boolean)); c.forEach((x) => s.add(x)); self.className = [...s].join(" "); },
      remove(...c) { self.className = self.className.split(" ").filter((x) => x && !c.includes(x)).join(" "); },
    };
  }
  set textContent(v) { this._text = String(v); this.children = []; }
  get textContent() { return this.children.length ? this.children.map((c) => c.textContent).join("") : this._text; }
  appendChild(c) { if (c.parentElement) c.parentElement.children = c.parentElement.children.filter((x) => x !== c);
    c.parentElement = this; this.children.push(c); return c; }
  append(...cs) { cs.forEach((c) => this.appendChild(c)); }
  replaceChildren(...cs) { this.children.forEach((c) => { c.parentElement = null; }); this.children = []; this.append(...cs); }
  querySelector(sel) { const cls = sel.slice(1); for (const c of this.all()) if (c.className.split(" ").includes(cls)) return c; return null; }
  all() { return this.children.flatMap((c) => [c, ...c.all()]); }
}
const ids = {};
const stack = new El("div", "agstack");
const agenda = new El("div", "agenda");
for (const i of ["agfam", "agline", "agdetail", "agwhen"]) { ids[i] = new El("div", i); agenda.appendChild(ids[i]); }
ids.agenda = agenda; ids.agother = new El("div", "agother");
stack.append(agenda, ids.agother);
const document = { getElementById: (i) => ids[i], createElement: (t) => new El(t) };
"""

DRAW_THREE = r"""
const fams = ["Aldren", "Morka", "Tovi"];
renderAgenda({ family: "Tovi", families: fams, activity: "job", headline: "Gathering",
  detail: [], stalled: true, stall_line: "nobody has moved", moved_seconds: 3000,
  changed_seconds: 60 });
placeAgendaRows([
  renderAgendaRow({ family: "Aldren", activity: "dungeon", headline: "Deadmines, 0 of 10",
    queue: { line: "" }, stalled: false, moved_seconds: 30 }),
  renderAgendaRow({ family: "Morka", activity: "quest", headline: "Questing, 2 of 6 steps",
    queue: { line: "Queue: Wailing Caverns 0 of 50." }, stalled: true, moved_seconds: 2700 }),
]);
const isRow = (e) => e.className.split(" ").includes("agrow");
process.stdout.write(JSON.stringify({
  agenda_rows: agenda.all().filter(isRow).length,
  other: ids.agother.children.map((c) => c.className),
  other_nested: ids.agother.children.flatMap((c) => c.all()).filter(isRow).length,
  texts: ids.agother.children.map((c) => c.all().filter((x) => !x.children.length && x.textContent).map((x) => x.textContent)),
  big_when: ids.agwhen.children.map((c) => c.textContent),
}));
"""
