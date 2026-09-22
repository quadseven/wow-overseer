"""The Watch wall composes five tiles, and none of it is allowed to lie.

WHY THESE ARE THE TESTS. The wall's failures are not exceptions, they are
confident sentences that are wrong: a logged-out character described as dead, a
player drawn over a URL that does not exist, a warning that names nobody, the
five reordering themselves under the cursor the moment a fight starts. Every
one of those renders fine and reads as a working feature. So these assert on
the WORDS and the ORDER, which is where a wall goes wrong.
"""
import unittest

import watchwall


def member(name, **kw):
    """A family member dict shaped like `family._member` returns.

    Deliberately minimal: the wall must cope with the absent-row shape, which
    carries no zone, no health and no combat flag at all.
    """
    row = {"name": name, "present": True, "condition": "ok"}
    row.update(kw)
    return row


class TheSentenceSaysTheMostUrgentTrueThing(unittest.TestCase):

    def test_logged_out_is_not_death(self):
        """The snapshot sweep drops the row of anyone not logged in, so an
        absent row is the ordinary way to be offline. Calling that dead is the
        wall's most alarming possible lie."""
        line = watchwall.status_line({"name": "Ugga", "present": False})
        self.assertEqual(line, "logged out")
        self.assertNotIn("dead", line)

    def test_death_outranks_a_fight(self):
        m = member("Og", condition="dead", combat=True, zone="Westfall")
        self.assertEqual(watchwall.status_line(m), "dead in Westfall")

    def test_a_fight_outranks_an_injury(self):
        m = member("Bork", condition="hurt", health_pct=20, combat=True,
                   zone="Westfall")
        self.assertEqual(watchwall.status_line(m), "fighting in Westfall")

    def test_an_injury_carries_the_percentage_the_family_module_rounded(self):
        """Not recomputed from health/max_health. Two surfaces rounding the
        same character differently is how a tile ends up arguing with the bar
        printed next to it."""
        m = member("Grog", condition="hurt", health_pct=7, zone="Westfall")
        self.assertEqual(watchwall.status_line(m), "hurt, 7% in Westfall")

    def test_an_instance_is_not_prefixed_with_in(self):
        """`family._member` composes "inside an instance" as a whole phrase.
        Prefixing it produces "fighting in inside an instance"."""
        m = member("Grug", combat=True, zone="inside an instance",
                   instance=True)
        self.assertEqual(watchwall.status_line(m), "fighting inside an instance")

    def test_a_placeless_character_still_gets_a_sentence(self):
        """Geography can fail to place someone. An empty caption under a live
        tile reads as a broken tile."""
        self.assertEqual(watchwall.status_line(member("Grug")), "in the world")

    def test_hurt_with_no_percentage_still_reads(self):
        m = member("Grug", condition="hurt", zone="Westfall")
        self.assertEqual(watchwall.status_line(m), "hurt in Westfall")


class TheCaptionSaysWhatTheyAreAndNotOnlyWhoTheyAre(unittest.TestCase):
    """infra#3482. The wall printed "Grug - L33 Warrior" over the picture and
    "Grug" again underneath it. Taking the duplicate off took the level and
    the class with it, and a wall of five characters that cannot say what any
    of them IS answers half the question it exists for."""

    def test_it_says_the_level_and_the_class(self):
        self.assertEqual(
            watchwall.standing(member("Grug", level=33, **{"class": "Warrior"})),
            "L33 Warrior")

    def test_a_missing_level_says_the_class_alone(self):
        """Never "L None Warrior", and never a bare "L" with nothing after
        it. An absent field is the ordinary case on this payload, not an
        error, so it has to read as a shorter sentence rather than as a
        broken one."""
        self.assertEqual(watchwall.standing(member("Grug", **{"class": "Warrior"})),
                         "Warrior")
        self.assertEqual(watchwall.standing(member("Grug", level=0,
                                                   **{"class": "Warrior"})),
                         "Warrior")

    def test_a_missing_class_still_says_the_level(self):
        self.assertEqual(watchwall.standing(member("Grug", level=33)), "L33")

    def test_a_member_with_neither_says_nothing_rather_than_a_stray_l(self):
        self.assertEqual(watchwall.standing(member("Grug")), "")

    def test_being_logged_out_does_not_take_their_class_away(self):
        """What they ARE does not change when they log off; what they are
        DOING is status_line's question and it says "logged out" there. A
        wall that blanked the class on absence would make four of five tiles
        anonymous every night."""
        row = member("Grug", present=False, level=33, **{"class": "Warrior"})
        self.assertEqual(watchwall.standing(row), "L33 Warrior")
        self.assertEqual(watchwall.status_line(row), "logged out")

    def test_it_rides_on_the_tile(self):
        tile = watchwall.build_wall(
            [member("Grug", level=33, **{"class": "Warrior"})])["tiles"][0]
        self.assertEqual(tile["standing"], "L33 Warrior")


class TheToneAgreesWithTheSentence(unittest.TestCase):
    """A tile coloured for calm under a caption saying "dead" is worse than
    either being wrong alone, so the two ladders are pinned together."""

    def test_every_case_matches_the_words(self):
        cases = [
            ({"present": False}, watchwall.TONE_GONE, "logged out"),
            (member("x", condition="dead"), watchwall.TONE_DEAD, "dead"),
            (member("x", combat=True), watchwall.TONE_COMBAT, "fighting"),
            (member("x", condition="hurt"), watchwall.TONE_HURT, "hurt"),
            (member("x"), watchwall.TONE_CALM, "in the world"),
        ]
        for row, tone, word in cases:
            self.assertEqual(watchwall.tone_of(row), tone, row)
            self.assertIn(word.split(",")[0], watchwall.status_line(row))

    def test_death_wins_the_tone_too(self):
        m = member("x", condition="dead", combat=True)
        self.assertEqual(watchwall.tone_of(m), watchwall.TONE_DEAD)


class APlayerIsDrawnOnlyOverARealUrl(unittest.TestCase):
    """`stream.delivery_of`'s rule, applied to the continuous broadcast. A
    player pointed at nothing is a black rectangle and a bug report."""

    def test_no_url_is_not_playable(self):
        self.assertFalse(watchwall.playable(member("x")))
        self.assertFalse(watchwall.playable(member("x", broadcast_url=None)))
        self.assertFalse(watchwall.playable(member("x", broadcast_url="")))
        self.assertFalse(watchwall.playable(member("x", broadcast_url="   ")))

    def test_a_url_is_playable_even_while_logged_out(self):
        """Deliberate, and `family._member` says why: the snapshot sweep and
        the encoder are not the same clock, so a character can be logged out
        and mid-broadcast for a beat. The tile learns the truth from the WHEP
        handshake rather than guessing offline from absence."""
        row = {"name": "Ugga", "present": False,
               "broadcast_url": "https://example.invalid/devugga"}
        self.assertTrue(watchwall.playable(row))

    def test_the_tile_carries_none_rather_than_an_empty_string(self):
        """An empty string is truthy enough in enough places to reach a
        <video src=""> , which reloads the page in some browsers."""
        wall = watchwall.build_wall([member("x", broadcast_url="")])
        self.assertIsNone(wall["tiles"][0]["url"])


class TheLeaderWarningIsAccurateOrAbsent(unittest.TestCase):

    def test_nobody_flagged_means_no_sentence(self):
        """The party can be led by someone the snapshot has not got, and
        `family._member` then flags nobody. A warning naming nobody is worse
        than no warning."""
        self.assertIsNone(watchwall.leader_warning(
            [member("Grug"), member("Ugga")]))

    def test_it_names_the_leader_and_what_changes(self):
        rows = [member("Grug", leader=True, pov_changes_the_family=True),
                member("Ugga")]
        warning = watchwall.leader_warning(rows)
        self.assertIn("Grug", warning["body"])
        self.assertIn("selfbot", warning["body"])
        self.assertIn("follow", warning["body"])

    def test_it_is_a_title_and_a_body(self):
        """Five sentences above the video on a phone is a warning that gets
        scrolled past unread. The title carries the whole claim, so the page
        can collapse to it on a narrow screen and still be honest."""
        rows = [member("Grug", pov_changes_the_family=True)]
        warning = watchwall.leader_warning(rows)
        self.assertEqual(warning["title"], "THE LEADER IS A SELFBOT")
        self.assertGreater(len(warning["body"]), len(warning["title"]))

    def test_it_does_not_promise_that_closing_the_tab_stops_it(self):
        """The on-demand watch stops when the viewer stops asking. These
        encoders were up before the page was opened and stay up after it is
        closed, so the tab-shaped wording would be false here."""
        rows = [member("Grug", pov_changes_the_family=True)]
        body = watchwall.leader_warning(rows)["body"].lower()
        self.assertNotIn("stop watching", body)
        self.assertNotIn("as long as", body)
        self.assertIn("never logs out", body)
        self.assertIn("whether or not you are looking", body)

    def test_it_reads_the_family_modules_answer_rather_than_the_leader_flag(self):
        """`leader` and `pov_changes_the_family` are different questions and
        `family._member` computes the second one. Deriving it here from the
        first would be a second opinion that can disagree."""
        rows = [member("Grug", leader=True, pov_changes_the_family=False)]
        self.assertIsNone(watchwall.leader_warning(rows))


class TheHeroIsChosenNeverRanked(unittest.TestCase):

    def test_a_name_from_storage_is_validated_against_the_roster(self):
        """It arrives from the browser, which is to say from anywhere. An
        unknown name would empty the big slot and leave five in the rail."""
        rows = [member("Grug"), member("Ugga")]
        self.assertEqual(watchwall.hero_of(rows, "Ugga"), "Ugga")
        self.assertEqual(watchwall.hero_of(rows, "Deathwing"), "Grug")

    def test_the_default_skips_anyone_not_in_the_world(self):
        rows = [{"name": "Grug", "present": False}, member("Ugga")]
        self.assertEqual(watchwall.hero_of(rows), "Ugga")

    def test_an_all_absent_family_still_has_a_hero(self):
        """A hero mode with no hero has no layout at all."""
        rows = [{"name": "Grug", "present": False},
                {"name": "Ugga", "present": False}]
        self.assertEqual(watchwall.hero_of(rows), "Grug")

    def test_an_empty_roster_does_not_raise(self):
        self.assertIsNone(watchwall.hero_of([]))
        self.assertEqual(watchwall.build_wall([])["tiles"], [])

    def test_nothing_in_the_module_ranks_interestingness(self):
        """The RedZone auto-cut is a real feature and it needs a score this
        module has no inputs for. Promoting the wrong character with apparent
        confidence is worse than promoting the first.

        ASKED OF THE PARSE TREE, NOT OF THE TEXT. The first version of this
        grepped the source for "score" and failed on the paragraph explaining
        why there is no score, which is a test that punishes the comment
        rather than the code. `ast` sees calls and never sees prose.
        """
        import ast
        with open(watchwall.__file__, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        called = {node.func.id for node in ast.walk(tree)
                  if isinstance(node, ast.Call)
                  and isinstance(node.func, ast.Name)}
        for ranking in ("sorted", "max", "min"):
            self.assertNotIn(ranking, called, ranking)
        attrs = {node.func.attr for node in ast.walk(tree)
                 if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute)}
        self.assertNotIn("sort", attrs)


class TheRosterOrderIsNeverTouched(unittest.TestCase):
    """`family.roster` is seniority, and re-sorting by who is fighting would
    move a character out from under the viewer's cursor every time a fight
    started. The wall is a place; things stay where they were put."""

    def test_tiles_come_back_in_the_order_they_went_in(self):
        names = ["Grug", "Ugga", "Grog", "Bork", "Og"]
        rows = [member(n) for n in names]
        # Make the last one the loudest thing on the wall.
        rows[-1].update(condition="dead", combat=True)
        wall = watchwall.build_wall(rows)
        self.assertEqual([t["name"] for t in wall["tiles"]], names)

    def test_promoting_a_hero_does_not_reorder_the_rest(self):
        names = ["Grug", "Ugga", "Grog", "Bork", "Og"]
        wall = watchwall.build_wall([member(n) for n in names], chosen="Og")
        self.assertEqual(wall["hero"], "Og")
        self.assertEqual([t["name"] for t in wall["tiles"]], names)


class TheHeadlineClaimsOnlyWhatThePayloadKnows(unittest.TestCase):
    """WRITTEN AFTER SHIPPING THE WRONG ONE. The first headline counted
    `playable` and said "5 of 5 broadcasting"; on production that rendered over
    five characters the very same payload reported as logged out."""

    def test_it_does_not_claim_anything_is_broadcasting(self):
        """Nothing here can see whether an encoder is publishing. That is the
        WHEP handshake, it happens in the browser, and the tile reports it."""
        rows = [member("Grug", broadcast_url="u"), member("Ugga", broadcast_url="u")]
        line = watchwall.headline(rows).lower()
        for claim in ("broadcast", "streaming", "live"):
            self.assertNotIn(claim, line, claim)

    def test_an_empty_world_says_so_in_words(self):
        """Zero of five is a statistic; nobody being there is the thing worth
        reading, and it is the production case."""
        rows = [{"name": n, "present": False, "broadcast_url": "u"}
                for n in ("Grug", "Ugga", "Og")]
        self.assertEqual(watchwall.headline(rows), "nobody is in the world")

    def test_it_counts_presence_and_not_urls(self):
        rows = [member("Grug", broadcast_url="u"),
                {"name": "Ugga", "present": False, "broadcast_url": "u"}]
        self.assertEqual(watchwall.headline(rows), "1 of 2 in the world")

    def test_an_empty_roster_does_not_divide_by_anything(self):
        self.assertEqual(watchwall.headline([]), "no family")

    def test_the_wall_carries_it(self):
        wall = watchwall.build_wall([member("Grug")])
        self.assertEqual(wall["headline"], "1 of 1 in the world")


class TheWallCarriesNoneOfTheChannelBudget(unittest.TestCase):
    """The budget belongs to the on-demand watch, which the wall does not use.
    "both channels busy" on a wall of continuous broadcasts would be a sentence
    about a mechanism that is not involved."""

    def test_the_payload_mentions_no_budget(self):
        wall = watchwall.build_wall([member("Grug", broadcast_url="u")])
        flat = repr(wall).lower()
        for word in ("channel", "unclaimed", "startup", "heartbeat", "queue"):
            self.assertNotIn(word, flat, word)

    def test_the_module_does_not_import_the_on_demand_lifecycle(self):
        """Not hostility to `stream`: the wall genuinely needs nothing from
        it, and an import is how the budget creeps back in."""
        source = open(watchwall.__file__, encoding="utf-8").read()
        self.assertNotIn("\nimport stream", source)
        self.assertNotIn("\nfrom stream", source)


class TheShapeTheFamilyPayloadPromises(unittest.TestCase):

    def test_the_three_modes_are_all_there(self):
        wall = watchwall.build_wall([member("Grug")])
        self.assertEqual(len(wall["modes"]), 3)
        self.assertIn(wall["default_mode"], wall["modes"])
        for mode in wall["modes"]:
            self.assertIn(mode, wall["mode_labels"])

    def test_every_tile_carries_what_a_tile_needs_to_draw(self):
        wall = watchwall.build_wall([member("Grug", role="father",
                                            class_colour="#C79C6E")])
        tile = wall["tiles"][0]
        for key in ("name", "role", "class", "class_colour", "leader",
                    "playable", "url", "standing", "line", "tone"):
            self.assertIn(key, tile, key)

    def test_it_is_json_serialisable(self):
        """It rides on /api/family, so anything that is not JSON here is a 500
        on the tab that is the page's homepage."""
        import json
        json.dumps(watchwall.build_wall([member("Grug", broadcast_url="u")]))


class TheHouseRules(unittest.TestCase):

    def test_no_em_dashes(self):
        import os
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for name in ("watchwall.py", "tests/test_watchwall.py"):
            with open(os.path.join(here, name), encoding="utf-8") as fh:
                self.assertNotIn(chr(0x2014), fh.read(), name)


if __name__ == "__main__":
    unittest.main()


class TheWallIsEveryFamilysHeads(unittest.TestCase):
    """The Watch tab showed one family's head, whichever family the Family tab
    had last looked at. It is every family's streamed characters now: on a
    realm with two game clients, the two heads, side by side."""

    def families(self):
        alliance = {"members": [
            member("Grug", broadcast_url="https://streams.example/grug",
                   leader=True, pov_changes_the_family=True),
            member("Ugga", broadcast_url=None),
            member("Og", broadcast_url=None)]}
        horde = {"members": [
            member("Zug", broadcast_url="https://streams.example/zug",
                   leader=True, pov_changes_the_family=True),
            member("Oz", broadcast_url=None)]}
        return [("Grug", alliance), ("Zug", horde)]

    def test_both_heads_and_only_the_heads(self):
        heads = watchwall.build_heads(self.families())
        self.assertEqual([m["name"] for m in heads["members"]], ["Grug", "Zug"])
        self.assertEqual([t["name"] for t in heads["wall"]["tiles"]], ["Grug", "Zug"])

    def test_each_head_says_which_family_it_leads(self):
        heads = watchwall.build_heads(self.families())
        self.assertEqual({m["name"]: m["family"] for m in heads["members"]},
                         {"Grug": "Grug", "Zug": "Zug"})
        self.assertEqual(heads["families"], ["Grug", "Zug"])

    def test_the_headline_counts_the_heads_not_the_families(self):
        heads = watchwall.build_heads(self.families())
        self.assertEqual(heads["wall"]["headline"], "2 of 2 in the world")

    def test_the_warning_names_both_selfbots(self):
        warning = watchwall.build_heads(self.families())["wall"]["warning"]
        self.assertIn("Grug", warning["body"])
        self.assertIn("Zug", warning["body"])
        self.assertIn("never log", warning["body"])
        self.assertIn("whether or not you are looking", warning["body"])

    def test_nobody_streamed_is_an_empty_wall_not_an_error(self):
        heads = watchwall.build_heads([("Grug", {"members": [member("Ugga")]})])
        self.assertEqual(heads["members"], [])
        self.assertEqual(heads["wall"]["headline"], "no family")
