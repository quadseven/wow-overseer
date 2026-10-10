"""The Decree console's page contract, asserted against index.html as source,
the way test_family_tab.py, test_armory_tab.py and test_wealth_tab.py do:
map_server.py imports pymysql and the page has no other test seam.

TWO OF THESE ARE ABOUT WHERE THE CODE SITS, and they are the reason a file
like this exists at all. Seven suites slice this page by their own banners:
the Family tests take their banner to loadZones().then( (script) and to
</style> (CSS); the Armory's and the Bags view's take theirs to </script>; the
Chronicle's, the Council's and the Eye's each run to the next view's banner;
the current-goal banner's CSS window ends at the `nav` rule. Code dropped
inside any of those windows is swept into assertions about a feature it has
nothing to do with. So this view's CSS sits between the shared redesign
furniture and the Chronicle banner, its script sits between the map's
intervals and the realm banner, its handler sits BELOW the chat one, and its
fetch sits BELOW `_ask_llm`.

THE FURNITURE STAYS ABOVE IT. The section rule, the stat strip and the hue
vocabulary belong to no single view (infra#2597), so this block sits after
them and never wraps them.

THE REST ARE THE TWO HONESTY MECHANISMS, seen from the page's side. This is
the only view in the redesign that WRITES, and the failure it must not have is
the one the whole epic is named after: a control that reports success while
doing nothing. So every judgement is asserted to be ABSENT from the page - the
list of wired job modes, the vocabulary of travel roles, the meaning of a
status word - and every control that cannot reach the world is asserted to be
disabled with the reason beside it.

Ticket: infra#2597.
"""

import pathlib
import unittest


HERE = pathlib.Path(__file__).resolve().parent.parent
SERVER = (HERE / "map_server.py").read_text(encoding="utf-8")

JS_BANNER = "// --- the Decree console (infra#2597)"
CSS_BANNER = "/* --- the Decree console (infra#2597)"
CHRONICLE_CSS = "/* --- the Chronicle (infra#2597, mod-overseer#88, mod-overseer#152)"
FURNITURE_CSS = "/* --- the redesign furniture (infra#2597)"
REALM_JS = "// --- which world this is (quadseven/mod-overseer#184)"


class WhereTheCodeIsAllowedToSit(unittest.TestCase):
    def test_the_handler_sits_below_every_other_endpoints_window(self):
        """The Family, Armory and Wealth windows end at `def _thoughts` or
        `def do_POST`; the watch window starts at `def _watch_state`."""
        at = SERVER.index("    def _decree(self")
        self.assertGreater(at, SERVER.index("    def do_POST(self"))
        self.assertGreater(at, SERVER.index("    def _chat(self"))
        self.assertLess(at, SERVER.index("    def _watch_state(self"))

    def test_the_fetch_sits_below_every_other_fetch_window(self):
        """`def _fetch_armory`, `_fetch_achievements` and `_fetch_questlog`
        all run to `def _ensure_stream_store`, and `_fetch_agenda` runs to
        `_fetch_streams`."""
        at = SERVER.index("def _fetch_decree")
        self.assertGreater(at, SERVER.index("def _fetch_streams"))
        self.assertGreater(at, SERVER.index("def _ask_llm"))
        self.assertLess(at, SERVER.index("class Handler"))


class TheOnlyThingItSends(unittest.TestCase):
    def test_the_row_id_comes_back_from_the_endpoint(self):
        """Without it the console could say an order was sent and never say
        what became of it."""
        self.assertIn('"command_id": row_id,', SERVER)
        self.assertIn("row_id = None", SERVER)


class TheEndpointIsAnAdapter(unittest.TestCase):
    """THE ONE RULE at the other end: the HTTP adapter fetches rows and does
    nothing else."""

    def test_it_reads_what_the_read_back_needs(self):
        """The newest job row per character from any source, and the family
        each roster row belongs to, both read in the console's own fetch."""
        fetch = SERVER[SERVER.index("def _fetch_decree") :]
        fetch = fetch[: fetch.index("def _fetch_roster_rows")]
        self.assertIn("WHERE kind = 'job' GROUP BY target_name", fetch)
        self.assertIn('"newest_job_rows": newest_job_rows', fetch)
        self.assertIn("_with_family(rd, roster_rows)", fetch)
        self.assertIn("SELECT name, family FROM overseer_roster", fetch)

    def test_an_order_is_planned_against_the_same_families(self):
        plan = SERVER[SERVER.index("def _fetch_roster_rows") :]
        plan = plan[: plan.index("def _apply_order")]
        self.assertIn("return _with_family(rd, rows)", plan)

    def test_it_is_in_the_route_table(self):
        table = SERVER[SERVER.index("GET_ROUTES = {") :]
        self.assertIn('"/api/decree": _decree,', table[: table.index("}")])

    def test_the_write_endpoint_is_in_the_post_table(self):
        post = SERVER[SERVER.index("POST_ROUTES = {") :]
        self.assertIn('"/api/decree": _decree_post,', post[: post.index("}")])

    def test_the_handler_only_fetches_and_serves(self):
        handler = SERVER[SERVER.index("    def _decree(self") :]
        handler = handler[: handler.index("    def _watch_state(self")]
        self.assertIn("decree.build_console(**_fetch_decree())", handler)
        self.assertNotIn("query.get", handler)

    def test_a_failed_query_is_a_503_and_never_a_blank_console(self):
        handler = SERVER[SERVER.index("    def _decree(self") :]
        handler = handler[: handler.index("    def _watch_state(self")]
        self.assertIn("self._send(503", handler)
        self.assertIn("log.exception", handler)

    def test_a_degraded_schema_thins_the_console_rather_than_breaking_it(self):
        """A realm whose worldserver predates a table must get an empty list,
        not a 503 on every poll."""
        fetch = SERVER[SERVER.index("def _fetch_decree") :]
        fetch = fetch[: fetch.index("class Handler")]
        self.assertIn("rd.rows(", fetch)

    def test_the_orders_it_reads_back_are_its_own(self):
        """Scoped by `source`. A console showing the bridge's traffic would
        report somebody else's orders as if the operator had given them."""
        fetch = SERVER[SERVER.index("def _fetch_decree") :]
        fetch = fetch[: fetch.index("class Handler")]
        self.assertIn("WHERE source = %s", fetch)
        self.assertIn("WEB_SOURCE", fetch)
        self.assertIn("decree.OUTCOME_ROWS", fetch)

    def test_the_source_is_one_constant_and_not_two_literals(self):
        """A second spelling would hand the console an empty page while the
        orders themselves went through perfectly."""
        self.assertIn('WEB_SOURCE = "web:overseer"', SERVER)
        self.assertEqual(SERVER.count('"web:overseer"'), 1)


class TheHouseRules(unittest.TestCase):
    def test_no_em_dashes(self):
        for name in ("tests/test_decree_tab.py",):
            self.assertNotIn(
                chr(0x2014), (HERE / name).read_text(encoding="utf-8"), name
            )


if __name__ == "__main__":
    unittest.main()
