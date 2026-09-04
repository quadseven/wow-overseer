"""The Watch wall as the PAGE has it, which is where a wall breaks silently.

TWO OF THESE WERE WRITTEN AFTER BEING HIT, in the change that added the wall,
and both were invisible until a parser was pointed at the file:

  a duplicate id      `id="wheadline"` already belonged to the Wealth view, so
                      getElementById handed the wealth code the wall element
                      and the wealth headline rendered into the wall.
  a shadowed const    `wsection` was already the wealth section. Two `const`
                      declarations of one name in one script is a SyntaxError,
                      which does not break that view: it breaks the WHOLE
                      PAGE, because the script never runs at all.

Neither is reachable from Python and neither shows up in a diff. They show up
as a blank site. So they are asserted here, over the file, for every id and
every top-level const on the page rather than only the ones this view added.
"""
import os
import re
import unittest

LF = chr(10)
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(HERE, "index.html"), encoding="utf-8") as _fh:
    PAGE = _fh.read()
SCRIPTS = re.findall(r"<script(?:\s[^>]*)?>(.*?)</script>", PAGE, re.S)


def _wall_js():
    """Just the wall, and nothing after it.

    Every one of these assertions is about what the WALL does, and the first
    versions sliced to the end of the file: they counted the theme toggle's
    storage calls and the on-demand panel's copy as the wall's, which is a
    test that fails for something another view is doing.
    """
    js = APP[APP.index("// --- the Watch wall"):]
    return js[:js.index("function layoutBroadcasts")]


def _wall_code():
    """The wall with its comments stripped.

    Four assertions in the change that added this failed on their own
    explanations: a comment quoting the string it replaced is not that string
    coming back, and a test that cannot tell the difference punishes writing
    the comment at all. Anything asserting that a bad pattern is GONE reads
    this; anything asserting a good pattern is PRESENT can read the source.
    """
    return LF.join(l for l in _wall_js().splitlines()
                   if not l.strip().startswith("//"))


def absent(case, needle, haystack, where):
    """assertNotIn against a 200KB page prints the WHOLE page on failure, which
    buries the one line that matters. This prints the needle."""
    case.assertFalse(needle in haystack, "%r found in %s" % (needle, where))
# The last block is the application. The three before it are the pre-paint
# theme script and the map bootstraps, and they have their own scopes.
APP = max(SCRIPTS, key=len)


class TheDocumentIsWellFormedEnoughToRun(unittest.TestCase):

    def test_no_id_is_used_twice(self):
        """getElementById returns the FIRST match and reports no error, so a
        collision silently rewires one view into another."""
        ids = re.findall(r'\sid="([^"]+)"', PAGE)
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        self.assertEqual(dupes, [], "ids declared more than once: %s" % dupes)

    def test_no_top_level_const_is_declared_twice(self):
        """A duplicate `const` in one script is a SyntaxError, and a
        SyntaxError anywhere in this block means NOTHING on the page runs."""
        names = re.findall(r"^const ([A-Za-z_$][\w$]*)\s*=", APP, re.M)
        dupes = sorted({n for n in names if names.count(n) > 1})
        self.assertEqual(dupes, [], "const declared twice: %s" % dupes)

    def test_every_wall_element_the_script_reaches_for_exists(self):
        """getElementById on a missing id returns null, and the first property
        access on it throws where the whole script stops."""
        for name in ("watch", "wall", "wallmodes", "wallwarn", "wallhead",
                     "wallsound"):
            self.assertIn('id="%s"' % name, PAGE, name)


class TheWallIsItsOwnView(unittest.TestCase):

    def test_it_has_a_tab_that_names_its_view(self):
        self.assertIn('const WATCH_VIEW = "watch";', PAGE)
        self.assertIn("wb.dataset.view = WATCH_VIEW;", PAGE)

    def test_family_is_still_the_first_tab(self):
        """infra#2892 put Family first because "are my five all right" is the
        question asked from a phone. The wall is the headline of the redesign
        and still does not get to move it."""
        self.assertLess(PAGE.index("fb.dataset.view = FAMILY_VIEW;"),
                        PAGE.index("wb.dataset.view = WATCH_VIEW;"))

    def test_the_two_views_read_one_payload(self):
        """A second endpoint would let the wall and the cards disagree about
        who is dead, and only one of them is ever on screen to be checked."""
        self.assertIn("if (view !== FAMILY_VIEW && view !== WATCH_VIEW) return;",
                      PAGE)


class EveryViewIsReachableByItsOwnHash(unittest.TestCase):
    """FOUND LIVE, on the deploy of the Watch wall. `#watch` opened the FAMILY
    tab: applyHash was a chain of ifs against three named views, the wall was a
    fourth, and an unrecognised name fell through to the final else. No error
    anywhere, just a deep link showing the wrong page.

    So the list is asserted against the view constants themselves, which is the
    only version of this test that survives somebody adding a fifth view."""

    def test_the_router_is_a_list_and_not_a_ladder(self):
        self.assertIn("const HASH_VIEWS = [", PAGE)

    def test_every_view_constant_is_routable(self):
        names = set(re.findall(r"^const ([A-Z]+_VIEW) = ", APP, re.M))
        listed = PAGE[PAGE.index("const HASH_VIEWS = ["):]
        listed = listed[:listed.index("]")]
        for name in sorted(names):
            if name == "MAP_VIEW":
                # The map is routed separately because its hash carries which
                # continent, so it needs more than a name.
                self.assertIn("if (name === MAP_VIEW)", PAGE)
                continue
            self.assertIn(name, listed, "%s is not reachable by hash" % name)

    def test_an_unknown_hash_falls_back_to_family(self):
        """An empty hash, a typo and a stale bookmark should all land on the
        page that answers "are my five all right"."""
        self.assertIn("HASH_VIEWS.indexOf(name) >= 0 ? name : FAMILY_VIEW",
                      PAGE)


class NoJudgementLivesInTheScript(unittest.TestCase):
    """infra#2597. Every sentence on the wall is composed by watchwall.py, and
    the page places nodes."""

    def test_the_tile_caption_is_not_composed_here(self):
        """It used to read `m.present ? m.zone : "not in the world"`, which is
        a decision about what absence MEANS made where no test can read it.

        ASSERTED ON THE ASSIGNMENT, not on the old expression. The first
        version of this grepped for `m.present ? m.zone` and failed on the
        comment above quoting it, which is a test that punishes the
        explanation rather than the code."""
        assign = "t.zone.textContent = "
        line = APP[APP.index(assign):APP.index(assign) + 80]
        absent(self, "m.present", line, "the zone caption")
        self.assertIn("wallLines.get(m.name)", line)

    def test_the_wall_prints_the_line_the_module_composed(self):
        self.assertIn("wallLines.set(t.name, t.line)", PAGE)

    def test_the_tone_class_is_the_modules_word(self):
        """Not re-derived from condition and combat. The colour and the words
        have to agree about what the urgent thing is."""
        self.assertIn('slot.classList.add("t-" + t.tone)', PAGE)

    def test_the_headline_is_printed_not_written(self):
        """It used to be built in the page out of `playable` and said
        "5 of 5 broadcasting" over a production realm with nobody logged in."""
        self.assertIn('wallhead.textContent = w.headline', PAGE)
        absent(self, "broadcasting", _wall_code(), "the wall view")

    def test_the_warning_is_printed_not_written(self):
        """Scoped to the wall, not the page. The on-demand panel says
        "selfbot" in a button title and has said it since infra#2887; that
        copy is correct where it is. The rule being pinned is that the WALL
        prints what watchwall composed instead of wording it again."""
        self.assertIn("wallwarn.textContent = w.warning", PAGE)
        absent(self, "selfbot", _wall_code(), "the wall view")
        absent(self, "follow", _wall_code(), "the wall view")

    def test_the_page_never_reorders_the_roster(self):
        """The module has tests pinning that the wall does not reorder. A sort
        here would move that guarantee somewhere no test can see it."""
        for banned in (".sort(", "sortBy", ".reverse("):
            absent(self, banned, _wall_code(), "the wall view")


class TheChannelBudgetIsNotOnThisWall(unittest.TestCase):
    """The budget belongs to the on-demand watch, which the wall does not use:
    these are continuous broadcasts, and nothing on this view starts, stops or
    queues one. "both channels busy" here would describe a mechanism that is
    not involved."""

    def test_the_wall_view_names_none_of_it(self):
        for word in ("max_channels", "channels_in_use", "startup_seconds",
                     "unclaimed", "heartbeat"):
            absent(self, word, _wall_code(), "the wall view")

    def test_the_wall_asks_for_no_stream(self):
        """It shows what is already broadcasting. A start button here would be
        a second way to spend a channel, from a view that cannot show the
        refusal."""
        absent(self, "/api/watch", _wall_code(), "the wall view")
        absent(self, '"start"', _wall_code(), "the wall view")


class TheTilesAreMovedAndNeverRebuilt(unittest.TestCase):
    """Rebuilding a tile tears down a live PeerConnection and re-establishes it
    across the tailnet, for a layout change nobody asked to pay for."""

    def test_the_layout_chooses_a_parent_rather_than_making_a_tile(self):
        fn = APP[APP.index("function layoutBroadcasts"):]
        fn = fn[:fn.index("\n}")]
        self.assertIn("view === WATCH_VIEW", fn)
        self.assertIn("appendChild(t.tile)", fn)
        absent(self, "broadcastTile(", fn, "layoutBroadcasts")

    def test_a_slot_is_built_once_and_cached(self):
        self.assertIn("let slot = wall.slots.get(name);", PAGE)
        self.assertIn("if (slot) return slot;", PAGE)

    def test_hero_is_promoted_by_span_not_by_order(self):
        """`order` would move tiles past each other visually, which is
        reordering the roster by another name."""
        self.assertIn("#wall.m-hero > .wslot.hero { grid-column:1 / -1; }", PAGE)
        wall_css = PAGE[PAGE.index("#wall { display:grid"):][:1400]
        # Anchored, because "order:" is a substring of "border:" and the
        # unanchored version could never pass.
        self.assertIsNone(re.search(r"[;{\s]order\s*:", wall_css),
                          "the wall CSS reorders tiles with `order`")


class HeroModeDoesNotWalkBackIntoTheTinyTwitchView(unittest.TestCase):
    """This page HAD one big player and four thumbnails. infra#88 removed it
    because on a phone the four were the smallest thing on screen, and the
    operator said so in as many words. It is back only as a choice."""

    def test_the_default_is_not_hero(self):
        self.assertIn('DEFAULT_MODE = FIVE_UP', _module_source())

    def test_hero_collapses_to_one_column_on_a_narrow_screen(self):
        self.assertIn("@media (max-width:760px) {", PAGE)
        narrow = PAGE[PAGE.index("@media (max-width:760px) {"):]
        self.assertIn("#wall.m-hero { grid-template-columns:1fr; }", narrow[:400])


class TheSoundIsOffUntilAskedFor(unittest.TestCase):

    def test_nothing_makes_a_noise_before_a_click(self):
        """A page that makes a noise on load is a page that gets closed."""
        self.assertIn('wall.sound = wallStored(WALL_SOUND_KEY) === "on";', PAGE)
        self.assertIn('aria-pressed="false"', PAGE)

    def test_it_cues_a_change_and_not_a_state(self):
        """Cueing the state would sound the alarm every five seconds for as
        long as a fight lasted, which is how a sound feature gets switched off
        and never switched back on."""
        self.assertIn("was && was !== t.tone", PAGE)

    def test_the_cue_is_synthesised_rather_than_fetched(self):
        """One HTML file, no build step. An audio asset would be a second
        thing to deploy and a second way to 404."""
        self.assertIn("createOscillator", PAGE)
        absent(self, "<audio", PAGE, "index.html")

    def test_a_browser_with_no_audio_does_not_take_the_wall_down(self):
        cue = PAGE[PAGE.index("function wallCue"):]
        cue = cue[:cue.index("\n}")]
        self.assertIn("try {", cue)
        self.assertIn("catch", cue)


class TheStoredPreferencesAreHandledLikeStorage(unittest.TestCase):

    def test_every_access_goes_through_the_wrapped_helpers(self):
        """localStorage THROWS rather than returning null in a private window,
        and an unwrapped read would stop the wall drawing at all."""
        for helper in ("function wallStored", "function wallStore"):
            body = PAGE[PAGE.index(helper):]
            self.assertIn("try {", body[:260])
            self.assertIn("catch", body[:260])
        # Counted over CODE, not comments: the block comment above the
        # helpers explains why localStorage is wrapped, and counting the word
        # there punishes the explanation instead of the thing explained.
        self.assertEqual(_wall_code().count("localStorage"), 2,
                         "raw localStorage use outside the two helpers")

    def test_a_stored_mode_is_validated_against_the_server(self):
        """It arrives from browser storage, which is to say from anywhere, and
        an unknown mode is a wall with no layout at all."""
        self.assertIn("w.modes.indexOf(stored) >= 0 ? stored : w.default_mode",
                      PAGE)

    def test_a_stored_hero_is_validated_against_the_five_on_the_wall(self):
        self.assertIn("names.indexOf(chosen) >= 0 ? chosen : w.hero", PAGE)


def _module_source():
    with open(os.path.join(HERE, "watchwall.py"), encoding="utf-8") as fh:
        return fh.read()


class TheHouseRules(unittest.TestCase):

    def test_no_em_dashes(self):
        for name in ("index.html", "tests/test_watch_wall_tab.py"):
            with open(os.path.join(HERE, name), encoding="utf-8") as fh:
                absent(self, chr(0x2014), fh.read(), name)

    def test_the_page_still_carries_no_framework(self):
        """The wall added a view, not a dependency."""
        absent(self, "<script src=", PAGE, "index.html")


if __name__ == "__main__":
    unittest.main()
