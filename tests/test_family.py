"""Family-tab builder tests: snapshot rows in, five cards out.

The tab exists because five characters were dying on a loop in a zone thirty
levels above them and the map - 500 dots on a phone - surfaced none of it. So
the cases that matter here are the ones that were invisible: dead, hurt, and
missing, each of which must read as itself and not as the other two.
"""
import ast
import re
import unittest
from pathlib import Path

import family
from transform import Geometry

GEO = Geometry.load(".")

# Grug in Elwynn, where the live family actually stands.
ELWYNN = {"guid": 1, "name": "Grug", "level": 19, "race": 1, "class": 1,
          "health": 583, "max_health": 583, "in_combat": 0, "is_bot": 1,
          "group_leader": 1, "map_id": 0, "pos_x": -9000.0, "pos_y": 400.0,
          "age_seconds": 4}


def row(**kw):
    d = dict(ELWYNN)
    d.update(kw)
    return d


def card(payload, name):
    return next(m for m in payload["members"] if m["name"] == name)


class RosterTest(unittest.TestCase):
    def test_roster_is_the_family_table_oldest_first(self):
        names = family.roster()
        self.assertEqual(set(names), set(("Grug", "Ugga", "Og", "Grog", "Bork")))
        # Seniority, which is the same fact head_of_family reads. The father
        # leads the party and must be the first card under the thumb.
        self.assertEqual(names[0], "Grug")
        self.assertEqual(names[-1], "Bork")

    def test_every_member_gets_a_card_even_with_no_rows_at_all(self):
        p = family.build_family([], GEO)
        self.assertEqual(len(p["members"]), 5)
        self.assertEqual(p["here"], 0)
        self.assertEqual(p["expected"], 5)
        self.assertIsNone(p["freshest_seconds"])


class ConditionTest(unittest.TestCase):
    def test_full_health_is_ok(self):
        c = card(family.build_family([row()], GEO), "Grug")
        self.assertEqual(c["condition"], family.OK)
        self.assertEqual(c["health_pct"], 100)
        self.assertTrue(c["present"])

    def test_zero_health_is_dead_and_says_so(self):
        c = card(family.build_family([row(health=0)], GEO), "Grug")
        self.assertEqual(c["condition"], family.DEAD)
        self.assertEqual(c["health_pct"], 0)
        # Dead is PRESENT. A corpse is still in the world, still in the zone
        # that killed it, and still the thing worth looking at - rendering it
        # as "gone" is how the loop stayed invisible.
        self.assertTrue(c["present"])

    def test_a_third_of_health_left_is_hurt(self):
        c = card(family.build_family([row(health=100, max_health=583)], GEO), "Grug")
        self.assertEqual(c["condition"], family.HURT)

    def test_just_above_the_threshold_is_not_cried_over(self):
        health = int(583 * family.HURT_BELOW) + 1
        c = card(family.build_family([row(health=health)], GEO), "Grug")
        self.assertEqual(c["condition"], family.OK)

    def test_missing_row_is_gone_not_dead(self):
        # The distinction the tab is built on: logged out is ordinary, dead
        # is news, and one must never render as the other.
        p = family.build_family([row()], GEO)
        self.assertEqual(card(p, "Bork")["condition"], family.GONE)
        self.assertFalse(card(p, "Bork")["present"])
        self.assertEqual(p["dead"], 0)

    def test_a_gone_member_still_carries_who_they_are(self):
        # A card with no name and no class is not a card; a person scanning
        # five of them needs to know WHICH one is missing.
        c = card(family.build_family([], GEO), "Ugga")
        self.assertEqual(c["role"], "mother")
        self.assertEqual(c["class"], "Priest")

    def test_mid_write_snapshot_is_not_a_corpse(self):
        # max_health 0 with health 0 happens between the module's writes.
        # Reading that as "dead" puts a red card over a healthy character.
        c = card(family.build_family([row(health=200, max_health=0)], GEO), "Grug")
        self.assertEqual(c["condition"], family.OK)

    def test_one_hit_point_never_rounds_away_to_nothing(self):
        c = card(family.build_family([row(health=1, max_health=583)], GEO), "Grug")
        self.assertEqual(c["health_pct"], 1)
        self.assertEqual(c["condition"], family.HURT)

    def test_all_but_one_hit_point_never_rounds_up_to_full(self):
        c = card(family.build_family([row(health=582, max_health=583)], GEO), "Grug")
        self.assertEqual(c["health_pct"], 99)


class WhereAndWhatTest(unittest.TestCase):
    def test_card_carries_zone_level_class_and_combat(self):
        c = card(family.build_family([row(in_combat=1)], GEO), "Grug")
        self.assertEqual(c["level"], 19)
        self.assertEqual(c["class"], "Warrior")
        self.assertEqual(c["faction"], "alliance")
        self.assertTrue(c["combat"])
        self.assertTrue(c["zone"])
        self.assertFalse(c["instance"])

    def test_instance_dweller_says_instance_not_a_guessed_zone(self):
        c = card(family.build_family(
            [row(map_id=34, pos_x=0.0, pos_y=0.0)], GEO), "Grug")
        self.assertTrue(c["instance"])
        self.assertEqual(c["zone"], "inside an instance")

    def test_leader_is_the_world_s_leader_and_carries_the_pov_warning(self):
        # stream.pov_changes_the_family says in as many words that the UI
        # must not hide this: POV on the leader makes the other four follow.
        rows = [row(), row(guid=2, name="Bork", group_leader=1)]
        p = family.build_family(rows, GEO)
        self.assertTrue(card(p, "Grug")["leader"])
        self.assertTrue(card(p, "Grug")["pov_changes_the_family"])
        self.assertFalse(card(p, "Bork")["leader"])
        self.assertFalse(card(p, "Bork")["pov_changes_the_family"])

    def test_leader_outside_the_snapshot_marks_nobody(self):
        # A party led by someone the snapshot has not got must not silently
        # promote whoever happens to sort first.
        p = family.build_family([row(group_leader=999)], GEO)
        self.assertFalse(card(p, "Grug")["leader"])


class BroadcastPathTest(unittest.TestCase):
    """infra#2892 Twitch view: the always-on grid's path builder.

    Deliberately NOT the same convention as wow-stream-agent/video.py's
    stream_path() (which hyphenates prefix and name) - see the module
    docstring in family.py for why. These tests pin the convention that is
    actually live: devgrug, not dev-grug.
    """

    def test_matches_the_paths_verified_live_on_mediamtx(self):
        # http://127.0.0.1:9997/v3/paths/list on the gaming box, verified
        # while this feature was built, answered with exactly these five.
        live = {"devbork", "devgrog", "devgrug", "devog", "devugga"}
        self.assertEqual(
            {family.broadcast_path(n) for n in family.roster()}, live)

    def test_prefix_and_name_are_concatenated_not_hyphenated(self):
        self.assertEqual(family.broadcast_path("Grug", prefix="dev"), "devgrug")
        self.assertNotEqual(family.broadcast_path("Grug", prefix="dev"), "dev-grug")

    def test_case_and_whitespace_do_not_change_the_path(self):
        self.assertEqual(family.broadcast_path("  Grug  ", prefix="DEV"), "devgrug")

    def test_empty_prefix_is_the_bare_name(self):
        self.assertEqual(family.broadcast_path("Grug", prefix=""), "grug")

    def test_an_unusable_name_degrades_to_no_path_rather_than_raising(self):
        # A card that cannot resolve a path must still be drawable - this
        # module never gets to take the whole tab down over one bad name.
        self.assertEqual(family.broadcast_path("../etc/passwd"), "")
        self.assertEqual(family.broadcast_path(""), "")

    def test_an_unusable_prefix_also_degrades_rather_than_raising(self):
        self.assertEqual(family.broadcast_path("Grug", prefix="not a prefix"), "")

    def test_broadcast_url_is_the_path_under_the_stream_host(self):
        self.assertEqual(
            family.broadcast_url("Grug", base="https://example.test", prefix="dev"),
            "https://example.test/devgrug")

    def test_broadcast_url_strips_a_trailing_slash_on_the_base(self):
        self.assertEqual(
            family.broadcast_url("Grug", base="https://example.test/", prefix="dev"),
            "https://example.test/devgrug")

    def test_broadcast_url_is_none_when_the_path_cannot_be_built(self):
        self.assertIsNone(family.broadcast_url("", base="https://example.test"))

    def test_every_card_carries_a_broadcast_url_present_or_not(self):
        # The tile has to be drawable for a logged-out character too - the
        # WHEP handshake is what decides offline, not this module guessing
        # from an absent snapshot row.
        p = family.build_family([row()], GEO)
        self.assertTrue(card(p, "Grug")["broadcast_url"])
        self.assertTrue(card(p, "Bork")["broadcast_url"])  # not present at all


class HeadlineTest(unittest.TestCase):
    def test_headline_counts_are_what_the_tab_shouts(self):
        rows = [
            row(),
            row(guid=2, name="Ugga", health=0),
            row(guid=3, name="Og", in_combat=1),
        ]
        p = family.build_family(rows, GEO)
        self.assertEqual(p["here"], 3)
        self.assertEqual(p["dead"], 1)
        self.assertEqual(p["in_combat"], 1)

    def test_freshness_is_the_freshest_present_member(self):
        rows = [row(age_seconds=40), row(guid=2, name="Og", age_seconds=6)]
        self.assertEqual(family.build_family(rows, GEO)["freshest_seconds"], 6)


class TheQualityLadder(unittest.TestCase):
    """WebRTC has no ladder of its own and MediaMTX does not transcode, so a
    second quality exists only because the gaming box publishes a second
    stream. This is the page's only way to find out that it does."""

    def test_the_ladder_lists_every_rendition_best_first(self):
        got = family.broadcast_renditions("Grug", base="https://x", prefix="dev")
        self.assertEqual([r["id"] for r in got], ["high", "low"])

    def test_each_rendition_carries_the_url_the_page_opens(self):
        got = family.broadcast_renditions("Grug", base="https://x", prefix="dev")
        by_id = {r["id"]: r["url"] for r in got}
        self.assertEqual(by_id["high"], "https://x/devgrug")
        self.assertEqual(by_id["low"], "https://x/devgruglow")

    def test_the_default_rendition_is_the_one_broadcast_url_already_meant(self):
        """The field predates the ladder. A player that never learns about
        renditions must keep working, byte for byte, off the old field."""
        self.assertEqual(
            family.broadcast_url("Grug", base="https://x", prefix="dev"),
            next(r["url"] for r
                 in family.broadcast_renditions("Grug", base="https://x",
                                                prefix="dev")
                 if r["default"]))

    def test_exactly_one_rendition_is_the_default(self):
        """The page starts on it and falls back TO it when another 404s. Two
        would make that ambiguous, none would make it impossible."""
        got = family.broadcast_renditions("Grug", base="https://x")
        self.assertEqual(sum(1 for r in got if r["default"]), 1)

    def test_the_renditions_carry_their_size_so_the_page_need_not_guess(self):
        got = {r["id"]: (r["width"], r["height"]) for r
               in family.broadcast_renditions("Grug", base="https://x")}
        self.assertEqual(got["high"], (1280, 720))
        self.assertEqual(got["low"], (640, 360))

    def test_the_low_rendition_is_actually_smaller(self):
        """A picker whose second entry is the same size is a fake picker, and
        this feature is explicitly not allowed to ship one."""
        got = {r["id"]: r for r in family.broadcast_renditions("Grug")}
        self.assertLess(got["low"]["width"], got["high"]["width"])
        self.assertLess(got["low"]["height"], got["high"]["height"])

    def test_a_name_that_cannot_be_a_path_gets_no_ladder(self):
        """Empty, not a 500. A tile that cannot resolve a path is drawn
        offline; it does not take the whole Family tab down with it."""
        for bad in ("", "../etc/passwd", "Gr0g", "A" * 13):
            with self.subTest(name=bad):
                self.assertEqual(family.broadcast_renditions(bad), [])

    def test_every_card_carries_the_ladder_present_or_not(self):
        """Same rule the url already follows: a logged-out character can still
        be mid-broadcast, and the tile learns the truth from the handshake."""
        p = family.build_family([row()], GEO)
        self.assertTrue(card(p, "Grug")["broadcast_renditions"])
        self.assertTrue(card(p, "Bork")["broadcast_renditions"])

    def test_the_ladder_and_the_url_never_disagree(self):
        """Two fields describing one stream is two chances to be wrong."""
        p = family.build_family([row()], GEO)
        for name in ("Grug", "Bork"):
            with self.subTest(name=name):
                c = card(p, name)
                default = [r for r in c["broadcast_renditions"] if r["default"]]
                self.assertEqual([c["broadcast_url"]],
                                 [r["url"] for r in default])


class TheLadderMatchesWhatIsPublished(unittest.TestCase):
    """The agent PUBLISHES the renditions and this module ADVERTISES them, and
    the two processes never speak. A suffix that disagrees is a quality option
    that 404s - the fake picker this feature must not ship.

    Read with ast.literal_eval rather than imported: wow-stream-agent is a
    separate codebase that runs on a different machine and is not importable
    from here, which is the same reason broadcast_path duplicates its formula
    instead of borrowing it.
    """

    # _agent_constants, test_the_two_sides_agree_about_the_ladder and
    # test_the_gated_constant_survived_the_parse removed here: they read
    # quadseven/infra's production/scripts/wow-stream-agent/video.py (a
    # different service, on a different machine, not part of this
    # extraction) to cross-check its RENDITIONS ladder against this
    # module's. That comparison has no home in this repo now; an equivalent
    # check should live in infra or in wow-stream-agent's own repo instead -
    # see the tracking issue for this split.

    def test_the_advertised_path_is_one_the_encoder_would_accept(self):
        """This module returns "" for a name it cannot use, so it can never
        say no the way the agent does. The check that the two agree about
        what a usable path looks like has to happen here."""
        pattern = re.compile(r"^https://[^/]+/[a-z]{2,16}$")
        for name in family.roster():
            for r in family.broadcast_renditions(name, base="https://x",
                                                 prefix="dev"):
                with self.subTest(name=name, rendition=r["id"]):
                    self.assertRegex(r["url"], pattern)

class TheRollbackLever(unittest.TestCase):
    """WOW_STREAM_LADDER=0 stops the page offering a quality nobody publishes.

    IT IS NOT A FEATURE FLAG FOR THE LADDER. The WHEP 404 fallback already
    makes a mismatch harmless, so this exists for one narrow case: the
    encoders on the gaming box are pinned to a detached worktree and only
    pick up a new command line when an operator restarts them, so a rollback
    there would leave the API advertising a rendition that stopped existing.
    This makes the UI quiet during one instead of merely survivable.

    Tested by reloading the module because the value is read at import, which
    is deliberate - a per-request getenv would let the ladder change shape
    between two polls of the same page.
    """

    # RESTORED IN tearDown, NOT IN A finally AROUND THE RELOAD, and that is
    # not a style choice - it is the bug this helper was written with first.
    # reload() mutates the module IN PLACE, so a finally that reloads with the
    # original environment runs before the caller ever sees the value and
    # hands back a module already reset. Every assertion then reads the
    # default state and the test passes for a reason that is not true.
    def setUp(self):
        import os
        self._before = os.environ.get("WOW_STREAM_LADDER")

    def tearDown(self):
        import importlib
        import os
        if self._before is None:
            os.environ.pop("WOW_STREAM_LADDER", None)
        else:
            os.environ["WOW_STREAM_LADDER"] = self._before
        importlib.reload(family)

    def _reloaded(self, value):
        import importlib
        import os
        if value is None:
            os.environ.pop("WOW_STREAM_LADDER", None)
        else:
            os.environ["WOW_STREAM_LADDER"] = value
        return importlib.reload(family)

    def test_off_leaves_exactly_the_default_rendition(self):
        for off in ("0", "false", "no", "off", "OFF"):
            with self.subTest(value=off):
                mod = self._reloaded(off)
                got = mod.broadcast_renditions("Grug", base="https://x")
                self.assertEqual([r["id"] for r in got],
                                 [mod.RENDITION_DEFAULT])
                self.assertTrue(got[0]["default"])

    def test_off_still_leaves_a_watchable_stream(self):
        """Turning the ladder off must not turn the video off. One entry is
        the honest answer, not an empty list."""
        mod = self._reloaded("0")
        got = mod.broadcast_renditions("Grug", base="https://x", prefix="dev")
        self.assertEqual(got[0]["url"], "https://x/devgrug")
        self.assertEqual(mod.broadcast_url("Grug", base="https://x",
                                           prefix="dev"), got[0]["url"])

    def test_the_ladder_is_on_by_default(self):
        """An operator should not have to switch on the thing this change is
        for. Default-off is how a feature ships inert."""
        mod = self._reloaded(None)
        self.assertEqual(len(mod.broadcast_renditions("Grug")), 2)

class OnlyStreamedCharactersHaveAVideo(unittest.TestCase):
    """Two game clients are streamed and the other eight characters are headless
    bots with nothing publishing, but every character HAS a stream path (it is a
    pure function of the name), so the page drew a video tile for all ten: eight
    black rectangles beside the two that work.

    `WOW_STREAMED_CHARACTERS` names who is streamed. Unset or empty means
    EVERYONE, which is what every deployment did before it existed, so nothing
    changes anywhere that does not set it. A character not on it has no URL, and
    `watchwall.playable` already means "a URL exists to try", so the wall and the
    cards follow without a second rule.
    """

    STREAMED = ("Grug", "Zug")

    def test_a_listed_character_is_streamed(self):
        self.assertTrue(family.is_streamed("Grug", self.STREAMED))
        self.assertTrue(family.is_streamed("Zug", self.STREAMED))

    def test_an_unlisted_character_is_not(self):
        for name in ("Bork", "Grog", "Og", "Ugga", "Oz", "Uzza", "Zork", "Zrog"):
            self.assertFalse(family.is_streamed(name, self.STREAMED), name)

    def test_unset_means_everyone(self):
        """The floor. A deployment that never set this must not lose a picture."""
        self.assertTrue(family.is_streamed("Bork", ()))
        from unittest import mock
        with mock.patch.object(family, "_STREAMED", frozenset()):
            self.assertTrue(family.is_streamed("Bork"))
            self.assertTrue(family.broadcast_url("Bork"))

    def test_a_near_miss_does_not_match_somebody_else(self):
        """A character name IS its spelling."""
        self.assertFalse(family.is_streamed("grug", self.STREAMED))
        self.assertFalse(family.is_streamed("Gru", self.STREAMED))
        self.assertFalse(family.is_streamed("", self.STREAMED))

    def test_an_unstreamed_character_gets_no_url_and_no_renditions(self):
        """Through the real public functions, with the list patched in: a tile
        with no URL is what the page keys off, so this is the seam that matters."""
        from unittest import mock
        with mock.patch.object(family, "_STREAMED", frozenset(self.STREAMED)):
            self.assertIsNone(family.broadcast_url("Bork"))
            self.assertEqual(family.broadcast_renditions("Bork"), [])
            self.assertTrue(family.broadcast_url("Grug"))
            self.assertTrue(family.broadcast_renditions("Grug"))

    def test_the_wall_calls_an_unstreamed_tile_unplayable(self):
        from unittest import mock
        import watchwall
        with mock.patch.object(family, "_STREAMED", frozenset(self.STREAMED)):
            self.assertFalse(watchwall.playable({"broadcast_url": family.broadcast_url("Bork")}))
            self.assertTrue(watchwall.playable({"broadcast_url": family.broadcast_url("Grug")}))


if __name__ == "__main__":
    unittest.main()


class ASecondFamilyIsNotTheFirstOneRenamed(unittest.TestCase):
    """The Family tab could only ever draw the family `bonds` holds.

    THE BUG, EXACTLY. `build_family` enumerated `roster()` - which is
    `bonds.speaking_order(bonds.FAMILY)`, one family, five keys - no matter
    whose snapshot rows it was handed. Asking for the Horde family returned
    `family: "Zug"` in the payload and then listed GRUG, UGGA, OG, GROG and
    BORK as its tiles, every one of them "logged out", because not one of
    those names appeared in the rows it had been given. The header said one
    family and the wall showed another, which is worse than either failing:
    it is a page confidently mislabelling five characters.

    And it could not have been caught by asking for the default family, which
    is the only thing every earlier test did.
    """

    HORDE = ["Zug", "Uzza", "Zrog", "Zork", "Oz"]
    # class/race ids as the characters table spells them: orc warrior,
    # troll priest, orc shaman, tauren druid, troll mage.
    PROFILES = {
        "Zug": {"class": 1, "race": 2}, "Uzza": {"class": 5, "race": 8},
        "Zrog": {"class": 7, "race": 2}, "Zork": {"class": 11, "race": 6},
        "Oz": {"class": 8, "race": 8},
    }

    def test_the_cards_are_the_family_that_was_asked_for(self):
        payload = family.build_family([], GEO, self.HORDE, self.PROFILES)
        self.assertEqual([m["name"] for m in payload["members"]], self.HORDE)
        for name in family.roster():
            self.assertNotIn(name, [m["name"] for m in payload["members"]],
                             f"{name} belongs to the other family")

    def test_the_wall_follows_the_cards(self):
        """The wall is composed from the same members list, so a wall that
        disagreed with the cards would mean two rosters in one payload."""
        payload = family.build_family([], GEO, self.HORDE, self.PROFILES)
        self.assertEqual([t["name"] for t in payload["wall"]["tiles"]],
                         [m["name"] for m in payload["members"]])

    def test_a_logged_out_member_still_has_a_class_and_a_race(self):
        """This is what `profiles` is for. These five have no persona, and
        a family that is deliberately not being driven yet is logged out on
        EVERY card - so a persona-only answer left the whole tab blank."""
        payload = family.build_family([], GEO, self.HORDE, self.PROFILES)
        oz = card(payload, "Oz")
        self.assertFalse(oz["present"])
        self.assertEqual(oz["class"], "Mage")
        self.assertNotEqual(oz["class_colour"], "#ffffff")
        self.assertTrue(oz["mark"], "a troll should still get a race mark")

    def test_a_present_member_is_described_by_the_world_not_the_persona(self):
        """Everything but `role` comes off the snapshot row, so a character
        bonds has never heard of renders completely when it is online."""
        payload = family.build_family(
            [row(name="Zug", race=2, **{"class": 1})], GEO,
            self.HORDE, self.PROFILES)
        zug = card(payload, "Zug")
        self.assertTrue(zug["present"])
        self.assertEqual(zug["class"], "Warrior")
        self.assertEqual(zug["race"], "Orc")
        self.assertEqual(zug["faction"], "horde")

    def test_the_default_is_still_the_family_bonds_holds(self):
        """Every existing caller passes no names and must be unaffected."""
        payload = family.build_family([], GEO)
        self.assertEqual([m["name"] for m in payload["members"]],
                         family.roster())


class TheZoneIsTheWorldsAnswerFirst(unittest.TestCase):
    """The Watch tile read "in Felwood" while the client on the same screen was
    in Winterspring. The zone came from bounding rectangles, and Felwood's box
    is smaller than Winterspring's and covers the west of it. The snapshot row
    carries the core's own zone id, which is the world's answer."""

    # A point both rectangles contain: west Winterspring by the world's
    # reckoning, Felwood by the smallest-box guess.
    OVERLAP = dict(map_id=1, pos_x=6000.0, pos_y=-2000.0)

    def test_the_guess_alone_says_felwood_which_is_the_bug(self):
        self.assertEqual(GEO.zone_name(1, 6000.0, -2000.0), "Felwood")

    def test_the_live_zone_id_wins_over_the_rectangle_guess(self):
        c = card(family.build_family([row(zone_id=618, **self.OVERLAP)], GEO), "Grug")
        self.assertEqual(c["zone"], "Winterspring")

    def test_no_zone_id_still_falls_back_to_the_guess(self):
        c = card(family.build_family([row(**self.OVERLAP)], GEO), "Grug")
        self.assertEqual(c["zone"], "Felwood")

    def test_an_unknown_zone_id_falls_back_rather_than_printing_nothing(self):
        c = card(family.build_family([row(zone_id=999999, **self.OVERLAP)], GEO), "Grug")
        self.assertEqual(c["zone"], "Felwood")

    def test_the_wall_caption_says_the_same_zone(self):
        p = family.build_family([row(zone_id=618, **self.OVERLAP)], GEO)
        tile = next(t for t in p["wall"]["tiles"] if t["name"] == "Grug")
        self.assertEqual(tile["line"], "in Winterspring")

    def test_the_adapter_selects_the_zone_id(self):
        server = Path(__file__).resolve().parent.parent.joinpath("map_server.py").read_text()
        fetch = server[server.index("def _fetch_family(names=None)"):]
        fetch = fetch[:fetch.index("# --- the Wealth and Bags view")]
        self.assertIn("zone_id", fetch)
