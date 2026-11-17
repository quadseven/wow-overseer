"""The site shows each member's own job in individual mode (#2408).

Three seams, each driven: the pure rule (`individual.standing`), the family
view the decree console serves (`decree.family_views`), and the operator
page that draws it (app/views/operator.js, under node).
"""

import pathlib
import shutil
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tests"))

import decree  # noqa: E402
import individual  # noqa: E402

NAMED = {individual.ENV: "Grug"}
EMPTY = {individual.ENV: ""}
NOT_GIVEN = {}


def rows(jobs_by_name, family="Grug", lead=None):
    lead = lead or next(iter(jobs_by_name))
    return [
        {
            "name": name,
            "family": family,
            "enabled": 1,
            "lead": 1 if name == lead else 0,
            "job": job,
            "travel_npc": "",
            "dungeon_runs_wanted": 0,
            "dungeon_runs_done": 0,
        }
        for name, job in jobs_by_name.items()
    ]


def view(jobs_by_name, environ, family="Grug"):
    return decree.family_views(rows(jobs_by_name, family), [], environ)[0]["job"]


class TheRule(unittest.TestCase):
    def test_a_dungeon_or_raid_job_links_and_names_who_holds_it(self):
        got = individual.standing(
            {"Og": "dungeon:wailing", "Grug": "craft", "Bork": "raid:molten"},
            "Grug",
            NAMED,
        )
        self.assertEqual(got["state"], individual.LINKED)
        self.assertEqual(got["reason"], "job")
        self.assertEqual(got["by"], ("Bork", "Og"))

    def test_a_named_family_with_no_linking_job_is_individual(self):
        got = individual.standing({"Og": "quest", "Grug": "craft"}, "grug", NAMED)
        self.assertEqual(
            (got["state"], got["reason"]), (individual.INDIVIDUAL, "named")
        )

    def test_town_run_and_raid_prep_do_not_link(self):
        got = individual.standing(
            {"Og": "town run", "Grug": "raid prep"}, "Grug", NAMED
        )
        self.assertEqual(got["state"], individual.INDIVIDUAL)

    def test_a_family_the_setting_does_not_name_is_linked(self):
        for environ in (EMPTY, {individual.ENV: "Zug"}):
            got = individual.standing({"Og": "quest", "Grug": "craft"}, "Grug", environ)
            self.assertEqual(
                (got["state"], got["reason"]), (individual.LINKED, "unnamed"), environ
            )

    def test_a_process_never_handed_the_setting_does_not_guess(self):
        got = individual.standing({"Og": "quest", "Grug": "craft"}, "Grug", NOT_GIVEN)
        self.assertEqual((got["state"], got["reason"]), (individual.UNREAD, "setting"))

    def test_a_linking_job_is_known_without_the_setting(self):
        got = individual.standing({"Og": "dungeon"}, "Grug", NOT_GIVEN)
        self.assertEqual((got["state"], got["reason"]), (individual.LINKED, "job"))

    def test_an_empty_roster_says_nothing(self):
        self.assertEqual(individual.standing({}, "Grug", NAMED)["state"], "")

    def test_it_agrees_with_the_rule_the_drives_ask(self):
        """`active` is what the bridge acts on; the page must not disagree."""
        for jobs_by_name in (
            {"Og": "quest", "Grug": "craft"},
            {"Og": "dungeon", "Grug": "craft"},
            {"Og": "town run", "Grug": "town run"},
        ):
            for family in ("Grug", "Zug"):
                got = individual.standing(jobs_by_name, family, NAMED)
                self.assertEqual(
                    got["state"] == individual.INDIVIDUAL,
                    individual.active(jobs_by_name, family, NAMED),
                    (jobs_by_name, family),
                )


class TheFamilyView(unittest.TestCase):
    def test_members_who_differ_are_each_shown_with_their_own_job(self):
        job = view({"Og": "quest", "Grug": "craft", "Ugga": "farm"}, NAMED)
        self.assertEqual(
            [(m["name"], m["job"]) for m in job["members"]],
            [("Og", "quest"), ("Grug", "craft"), ("Ugga", "farm")],
        )
        self.assertEqual(
            job["members_line"], "Og on quest, Grug on craft, Ugga on farm"
        )

    def test_members_who_agree_are_shown_as_one_job(self):
        job = view({"Og": "town run", "Grug": "town run"}, NAMED)
        self.assertEqual(job["members_line"], "")
        self.assertEqual(job["standing"], "town run")
        self.assertEqual({m["job"] for m in job["members"]}, {"town run"})

    def test_a_blank_job_reads_as_the_default_and_is_no_difference(self):
        job = view({"Og": "quest", "Grug": ""}, NAMED)
        self.assertEqual(job["members_line"], "")

    def test_a_dungeon_job_is_said_in_words(self):
        job = view({"Og": "dungeon", "Grug": "craft"}, NAMED)
        self.assertIn("Og on dungeon runs", job["members_line"])

    def test_an_individual_family_says_so_and_why(self):
        link = view({"Og": "quest", "Grug": "craft"}, NAMED)["link"]
        self.assertEqual(link["state"], "individual")
        self.assertTrue(link["line"].startswith("Individual:"), link["line"])
        self.assertIn(individual.ENV, link["line"])
        self.assertIn("summon", link["line"])

    def test_a_linked_family_says_which_job_links_it(self):
        link = view({"Og": "dungeon", "Grug": "craft"}, NAMED)["link"]
        self.assertEqual(link["state"], "linked")
        self.assertEqual(link["by"], ["Og"])
        self.assertTrue(link["line"].startswith("Linked: Og is on dungeon runs"))

    def test_an_unnamed_family_is_linked_by_the_setting(self):
        link = view({"Og": "quest", "Grug": "craft"}, NAMED, family="Zug")["link"]
        self.assertEqual((link["state"], link["reason"]), ("linked", "unnamed"))
        self.assertIn("does not name this family", link["line"])

    def test_a_page_without_the_setting_says_it_does_not_know(self):
        link = view({"Og": "quest", "Grug": "craft"}, NOT_GIVEN)["link"]
        self.assertEqual(link["state"], "unread")
        self.assertTrue(link["line"].startswith("Not known:"), link["line"])

    def test_a_disabled_member_is_nobody(self):
        roster = rows({"Og": "quest", "Grug": "craft"})
        roster[1]["enabled"] = 0
        job = decree.family_views(roster, [], NAMED)[0]["job"]
        self.assertEqual([m["name"] for m in job["members"]], ["Og"])
        self.assertEqual(job["members_line"], "")

    def test_a_roster_read_without_the_job_column_claims_no_jobs(self):
        roster = rows({"Og": "quest", "Grug": "craft"})
        for row in roster:
            del row["job"]
        job = decree.family_views(roster, [], NAMED)[0]["job"]
        self.assertEqual(job["members"], [])
        self.assertEqual(job["link"]["line"], "")

    def test_the_console_carries_the_view(self):
        payload = decree.build_console(rows({"Og": "quest", "Grug": "craft"}), [])
        job = payload["families"][0]["job"]
        self.assertEqual(job["members_line"], "Og on quest, Grug on craft")
        self.assertIn(job["link"]["state"], ("linked", "individual", "unread"))


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class TheOperatorPage(unittest.TestCase):
    """The page draws what the view says, and nothing when there is nothing."""

    @classmethod
    def setUpClass(cls):
        import test_operator_view as page

        cls.page = page

    def render(self, job):
        page = self.page
        data = dict(page.DECREE)
        data["families"] = [dict(page.DECREE["families"][0], job=job)]
        return page.render_with(page.on_reads({"data": data, "at": 1, "error": None}))[
            "html"
        ]

    def test_a_family_whose_members_differ_lists_each_and_says_why(self):
        job = view({"Og": "quest", "Grug": "craft"}, NAMED)
        html = self.render(job)
        self.assertIn("Each member", html)
        self.assertIn("Og on quest, Grug on craft", html)
        self.assertIn("Individual: no member is on a dungeon or raid job", html)

    def test_a_family_that_agrees_shows_one_job_and_no_member_list(self):
        job = view({"Og": "town run", "Grug": "town run"}, EMPTY)
        html = self.render(job)
        self.assertNotIn("Each member", html)
        self.assertIn("Linked: no dungeon or raid job is set", html)

    def test_a_payload_without_the_new_fields_still_draws(self):
        html = self.render({"line": "Grug's family: Set to quest.", "split_line": ""})
        self.assertNotIn("Each member", html)
        self.assertNotIn("Linked", html)


if __name__ == "__main__":
    unittest.main()
