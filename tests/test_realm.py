"""The realm banner's decision table (quadseven/mod-overseer#184).

WHAT THIS SUITE IS ACTUALLY PROTECTING. Three realms run this site's module and
the hostnames that used to tell them apart are being collapsed into one. From
then on, this banner is the only thing standing between a reader and the belief
that the live family's positions are a disposable world's. There is exactly one
way for that to go wrong and it is not an exception: it is a banner that renders
calmly and says the wrong thing.

So most of the cases below are about the states where the page does NOT have
what it needs. Every one of them has to come out as an alarm, and none of them
may come out as NOT PRODUCTION. The reassuring answer has to be earned by a
realm that actually said so.

`realm` is a PURE module, rows in and one banner out, so each case here is a
dict literal rather than a database. The adapter's guard is what turns a missing
table into an empty list, and this is the half of that contract that has to say
less rather than raise.

The core banners are quoted from the three running worldservers rather than
invented, including the older one on the live realm. The gap between them is the
thing this feature was built to make visible, so a suite that used one made-up
revision everywhere would be testing a world that does not exist.
"""
import unittest
from datetime import datetime, timedelta

import realm

NOW = datetime(2026, 9, 3, 12, 0, 0)

# The live realm is twelve days and one commit behind the other two. Real.
LIVE_CORE = ("AzerothCore rev. efe123fab543+ 2026-08-14 08:34:16 -0700 "
             "(HEAD branch) (Unix, RelWithDebInfo, Static)")
NEWER_CORE = ("AzerothCore rev. 47960183bb03+ 2026-08-28 21:04:11 +0200 "
              "(HEAD branch) (Unix, RelWithDebInfo, Static)")

UPSTREAMS = (
    ("mod-playerbots", "2f7d9f774987d0157c6a0d0cc08c40bec3db3945"),
    ("mod-ollama-chat", "8ba5e791f0a84ee04636f0b19b62d3c4aff3dce1"),
    ("mod-dungeon-clear", "0ed117bb67148091b37541e19c1ae8e19a5260d3"),
    ("mod-ah-bot-plus", "f685832994c825f90aa5a3dc0e1620aa568e875b"),
)


def build_rows(name="wow-dev", kind="non-production", core=NEWER_CORE,
               pins="match", reported_at=NOW, upstreams=UPSTREAMS):
    """One realm's overseer_build, as the module writes it."""
    rows = [
        ("module", "0.1.0", "compiled"),
        ("core", core, "compiled"),
        ("realm", name, "declared"),
        ("realm_kind", kind, "derived"),
        ("pins", pins, "derived"),
    ]
    rows += [(component, sha, "declared") for component, sha in upstreams]
    return [{"name": n, "value": v, "source": s, "reported_at": reported_at}
            for n, v, s in rows]


def world(core=NEWER_CORE):
    return [{"core_version": core}]


def realmlist(name="Homelab-Dev"):
    return [{"name": name}]


def build(rows=None, version_rows=None, realmlist_rows=None, now=NOW):
    return realm.build_realm(
        list(rows if rows is not None else build_rows()),
        list(version_rows if version_rows is not None else world()),
        list(realmlist_rows if realmlist_rows is not None else realmlist()),
        now=now,
    )


class ARealmThatHasSaidWhatItIs(unittest.TestCase):
    def test_a_declared_production_realm_says_production(self):
        out = build(build_rows(name="wow", kind="production", core=LIVE_CORE),
                    world(LIVE_CORE), realmlist("Homelab"))
        self.assertEqual(out["kind"], realm.PRODUCTION)
        self.assertEqual(out["label"], "PRODUCTION")

    def test_a_declared_disposable_realm_says_not_production(self):
        out = build()
        self.assertEqual(out["kind"], realm.NON_PRODUCTION)
        self.assertEqual(out["label"], "NOT PRODUCTION")

    def test_a_realm_that_reported_cleanly_raises_no_warning(self):
        self.assertEqual(build()["warnings"], [])

    def test_its_own_name_is_preferred_over_the_realm_list(self):
        """The module's report is what the deployment chose; the realm list is
        what a client sees. When both exist the deployment's name wins."""
        out = build()
        self.assertEqual(out["realm"], "wow-dev")
        self.assertEqual(out["realm_source"], "reported")
        self.assertEqual(out["realm_line"], "wow-dev")

    def test_the_build_line_names_the_module_the_core_and_every_upstream(self):
        line = build()["build_line"]
        self.assertIn("module 0.1.0", line)
        self.assertIn("core 47960183bb03", line)
        for component, sha in UPSTREAMS:
            self.assertIn(component, line)
            self.assertIn(sha[:12], line)

    def test_the_upstreams_come_back_in_a_fixed_order(self):
        """The rows arrive from a table with no ordering worth trusting, and a
        list that reshuffles between polls is unreadable."""
        shuffled = list(reversed(build_rows()))
        out = build(shuffled)
        self.assertEqual([u["name"] for u in out["upstreams"]],
                         list(realm.UPSTREAM_ORDER))


class ARealmThatHasSaidNothing(unittest.TestCase):
    """THE STATE EVERY REALM IS IN THE DAY THIS SHIPS, because the table is
    created by SQL the in-world module ships and no worldserver has been rolled
    onto it yet. This is the case that has to be right first, not last."""

    def test_a_missing_build_table_still_renders_a_banner(self):
        out = build([], world(LIVE_CORE), realmlist("Homelab"))
        self.assertEqual(out["kind"], realm.UNKNOWN)
        self.assertEqual(out["label"], "REALM NOT VERIFIED")
        self.assertFalse(out["reported"])

    def test_it_says_plainly_that_no_build_was_reported(self):
        """Not a blank, not a guess, and not an empty string where a version
        belongs. The reader has to be told why the page cannot vouch for this."""
        out = build([], world(LIVE_CORE), realmlist("Homelab"))
        self.assertIn("has not reported a build", out["warning_text"])
        self.assertIn("has not reported a build", out["build_line"])
        self.assertEqual(out["module_version"], "")
        self.assertEqual(out["upstreams"], [])

    def test_it_still_names_the_core_because_the_world_reports_that_itself(self):
        """acore_world.version is written by AzerothCore at startup with no
        module involved, so it is available on a realm that has never run this
        feature at all. On the day this ships it is the only real value the
        banner has, and the realms visibly disagree on it."""
        live = build([], world(LIVE_CORE), realmlist("Homelab"))
        newer = build([], world(NEWER_CORE), realmlist("Homelab-Dev"))
        self.assertEqual(live["core_revision"], "efe123fab543")
        self.assertEqual(newer["core_revision"], "47960183bb03")
        self.assertEqual(live["core_source"], "world")
        self.assertIn("efe123fab543", live["build_line"])

    def test_it_still_names_the_realm_from_the_realm_list(self):
        out = build([], world(LIVE_CORE), realmlist("Homelab"))
        self.assertEqual(out["realm"], "Homelab")
        self.assertEqual(out["realm_source"], "realmlist")
        self.assertIn("Homelab", out["realm_line"])
        self.assertIn("has not reported its own identity", out["realm_line"])

    def test_every_table_missing_is_a_banner_and_not_an_exception(self):
        """A realm mid-import, or a database this site has never seen before.
        There is no arrangement of empty inputs that may raise."""
        out = realm.build_realm([], [], [], now=NOW)
        self.assertEqual(out["kind"], realm.UNKNOWN)
        self.assertEqual(out["label"], "REALM NOT VERIFIED")
        self.assertTrue(out["realm_line"])
        self.assertTrue(out["build_line"])
        self.assertTrue(out["warning_text"])


class NothingUNCERTAINEverRendersAsSafe(unittest.TestCase):
    """The one rule under all of this. Every way of being unsure has to reach
    REALM NOT VERIFIED, and none of them may reach NOT PRODUCTION - a quiet
    banner over the live family is the accident this whole feature exists to
    prevent, and it is the only outcome here that is actually dangerous."""

    def _kinds_that_are_not_a_kind(self):
        return ["", "   ", "prod", "PROD", "prd", "live", "dev", "canary",
                "nonproduction", "Production!", "staging", "0", "null"]

    def test_no_mistyped_realm_kind_reads_as_a_real_answer(self):
        for kind in self._kinds_that_are_not_a_kind():
            out = build(build_rows(name="wow", kind=kind, core=LIVE_CORE),
                        world(LIVE_CORE), realmlist("Homelab"))
            self.assertEqual(out["kind"], realm.UNKNOWN, kind)
            self.assertNotEqual(out["kind"], realm.NON_PRODUCTION, kind)
            self.assertEqual(out["label"], "REALM NOT VERIFIED", kind)

    def test_a_reported_realm_with_no_kind_is_told_apart_from_one_that_never_reported(self):
        """Both are unknown, and both are alarms, but they are different
        problems and the sentence has to say which one it is: a realm that never
        reported needs a worldserver, a realm that reported without a kind needs
        a manifest."""
        silent = build([], world(LIVE_CORE), realmlist("Homelab"))
        partial = build(build_rows(kind=""), world(), realmlist())
        self.assertFalse(silent["reported"])
        self.assertTrue(partial["reported"])
        self.assertIn("has not reported a build", silent["warning_text"])
        self.assertIn("did not say whether it is production",
                      partial["warning_text"])

    def test_a_kind_this_page_has_never_heard_of_is_unknown_not_passed_through(self):
        """A worldserver newer than this file, reporting a fourth kind. The page
        has no styling for a word it has never seen and would draw it as though
        it were safe."""
        out = build(build_rows(kind="pre-production"))
        self.assertEqual(out["kind"], realm.UNKNOWN)
        self.assertIn(out["label"], realm.LABELS.values())

    def test_every_kind_the_page_can_render_has_a_label(self):
        """The page styles on kind and prints label. A kind with no label would
        be a KeyError in the one banner that may never fail."""
        for kind in (realm.PRODUCTION, realm.NON_PRODUCTION, realm.UNKNOWN):
            self.assertIn(kind, realm.LABELS)


class ADeclarationThatDescribesAnotherBuild(unittest.TestCase):
    """The upstream commits cannot be read out of the binary, so they are
    declared by the deployment. A manifest naming the default branch's pins in
    front of an older image declares four wrong commits with total confidence,
    and that is the live realm's situation today."""

    def test_stale_pins_are_called_out_rather_than_printed_as_fact(self):
        out = build(build_rows(name="wow", kind="production", core=LIVE_CORE,
                               pins="stale"),
                    world(LIVE_CORE), realmlist("Homelab"))
        self.assertEqual(out["pins"], realm.PINS_STALE)
        self.assertIn("describe another image", out["warning_text"])
        self.assertIn("pins STALE", out["build_line"])

    def test_stale_pins_do_not_change_the_realm_label(self):
        """A production realm with a stale declaration is still production.
        Downgrading the label because a secondary fact is suspect would be the
        banner making the reader's most important answer less reliable."""
        out = build(build_rows(name="wow", kind="production", core=LIVE_CORE,
                               pins="stale"),
                    world(LIVE_CORE), realmlist("Homelab"))
        self.assertEqual(out["kind"], realm.PRODUCTION)

    def test_the_commits_are_still_shown_so_the_reader_can_see_the_evidence(self):
        out = build(build_rows(pins="stale"))
        self.assertEqual(len(out["upstreams"]), len(UPSTREAMS))

    def test_a_report_naming_a_different_core_than_the_world_is_flagged(self):
        """Both are written at startup by the same process, so this should be
        impossible. If it happens, the report is left over from an earlier
        binary and everything derived from it is suspect."""
        out = build(build_rows(core=LIVE_CORE), world(NEWER_CORE), realmlist())
        self.assertIn("left over from an earlier worldserver",
                      out["warning_text"])

    def test_the_world_is_believed_over_the_report_about_the_core(self):
        """acore_world.version needs less to go right: the core writes it with
        no module involved, and it cannot be left behind by a module that failed
        to rewrite its own row."""
        out = build(build_rows(core=LIVE_CORE), world(NEWER_CORE), realmlist())
        self.assertEqual(out["core"], NEWER_CORE)
        self.assertEqual(out["core_source"], "world")


class ASchemaOrARowThatIsNotTHEShapeExpected(unittest.TestCase):
    """Rows are name/value pairs precisely so a newer worldserver can report
    something this file has never heard of. That only helps if the odd shapes
    degrade rather than raise."""

    def test_a_fact_this_file_does_not_know_is_shown_rather_than_dropped(self):
        rows = build_rows() + [{"name": "mod-something-new", "value": "abc123def456",
                                "source": "declared", "reported_at": NOW}]
        names = [u["name"] for u in build(rows)["upstreams"]]
        self.assertIn("mod-something-new", names)
        self.assertEqual(names[:len(realm.UPSTREAM_ORDER)],
                         list(realm.UPSTREAM_ORDER))

    def test_a_row_with_no_name_is_skipped_and_not_an_exception(self):
        rows = build_rows() + [{"name": "", "value": "x", "source": "declared",
                                "reported_at": NOW}]
        self.assertEqual(build(rows)["kind"], realm.NON_PRODUCTION)

    def test_a_null_value_reads_as_absent_rather_than_as_the_word_none(self):
        rows = [r for r in build_rows() if r["name"] != "module"]
        rows.append({"name": "module", "value": None, "source": "compiled",
                     "reported_at": NOW})
        out = build(rows)
        self.assertEqual(out["module_version"], "")
        self.assertNotIn("None", out["build_line"])

    def test_a_timestamp_that_is_not_a_datetime_does_not_raise(self):
        """A realm mid-upgrade can hand back a string, and a zero timestamp
        arrives as None."""
        for stamp in ("2026-09-03 12:00:00", None, 0):
            out = build(build_rows(reported_at=stamp))
            self.assertEqual(out["kind"], realm.NON_PRODUCTION, repr(stamp))
            self.assertIsNone(out["reported_at"], repr(stamp))

    def test_an_unparseable_core_banner_shows_the_sentence_rather_than_nothing(self):
        out = build([], [{"core_version": "some future banner format"}],
                    realmlist("Homelab"))
        self.assertEqual(out["core_revision"], "")
        self.assertIn("some future banner format", out["build_line"])

    def test_a_realm_list_row_with_a_blank_name_falls_through(self):
        out = build([], world(LIVE_CORE), [{"name": ""}, {"name": "Homelab"}])
        self.assertEqual(out["realm"], "Homelab")


class TheClocks(unittest.TestCase):
    def test_the_age_of_the_report_is_measured_from_the_injected_clock(self):
        out = build(build_rows(reported_at=NOW - timedelta(minutes=5)))
        self.assertEqual(out["reported_seconds"], 300)

    def test_a_report_from_the_future_is_zero_rather_than_negative(self):
        out = build(build_rows(reported_at=NOW + timedelta(minutes=5)))
        self.assertEqual(out["reported_seconds"], 0)


class TheRevisionReaderAgreesWithTheModule(unittest.TestCase):
    """The same extraction happens in C++, in OverseerDecisions::CoreRevision.
    If the two disagree, a realm can show a commit here that its own build
    report considers unreadable, or the other way round."""

    def test_the_dirty_tree_marker_is_not_part_of_the_commit(self):
        self.assertEqual(realm._revision(NEWER_CORE), "47960183bb03")
        self.assertNotIn("+", realm._revision(NEWER_CORE))

    def test_a_banner_in_an_unknown_shape_yields_nothing(self):
        self.assertEqual(realm._revision("no revision here"), "")
        self.assertEqual(realm._revision(""), "")

    def test_two_hex_characters_are_a_coincidence_and_not_a_commit(self):
        """Seven is the floor on both sides. A shorter prefix would compare
        equal to a great many commits."""
        self.assertEqual(realm._revision("AzerothCore rev. de+ 2026-08-14"), "")
        self.assertEqual(realm._revision("AzerothCore rev. abcdef1+ x"), "abcdef1")


if __name__ == "__main__":
    unittest.main()
