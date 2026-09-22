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
    js = APP[APP.index("// --- the Watch wall") :]
    return js[: js.index("function layoutBroadcasts")]


def _wall_code():
    """The wall with its comments stripped.

    Four assertions in the change that added this failed on their own
    explanations: a comment quoting the string it replaced is not that string
    coming back, and a test that cannot tell the difference punishes writing
    the comment at all. Anything asserting that a bad pattern is GONE reads
    this; anything asserting a good pattern is PRESENT can read the source.
    """
    return LF.join(
        line for line in _wall_js().splitlines() if not line.strip().startswith("//")
    )


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
        for name in ("watch", "wall", "wallmodes", "wallwarn", "wallhead", "wallsound"):
            self.assertIn('id="%s"' % name, PAGE, name)


class TheWallIsItsOwnView(unittest.TestCase):
    def test_it_has_a_tab_that_names_its_view(self):
        self.assertIn('const WATCH_VIEW = "watch";', PAGE)
        self.assertIn("wb.dataset.view = WATCH_VIEW;", PAGE)

    def test_watch_is_the_first_tab(self):
        """THIS REVERSES infra#2892 AND THE TEST THAT PINNED IT, deliberately.

        That decision put Family first because "are my five all right" is the
        question asked from a phone, and when the wall landed it took second
        place on exactly that reasoning. The design handoff makes Watch the
        default tab, and the operator asked for a Twitch-like experience for
        watching the family: the question asked from a phone turns out to be
        "what are they doing", and the wall answers it in pictures.

        Family is one tap away and still answers the health question better
        than five video tiles can, which is why it is second rather than
        moved down the row."""
        self.assertLess(
            PAGE.index("wb.dataset.view = WATCH_VIEW;"),
            PAGE.index("fb.dataset.view = FAMILY_VIEW;"),
        )

    def test_the_two_views_read_one_payload(self):
        """A second endpoint would let the wall and the cards disagree about
        who is dead, and only one of them is ever on screen to be checked."""
        self.assertIn("if (view !== FAMILY_VIEW && view !== WATCH_VIEW) return;", PAGE)


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
        listed = PAGE[PAGE.index("const HASH_VIEWS = [") :]
        listed = listed[: listed.index("]")]
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
        self.assertIn("HASH_VIEWS.indexOf(name) >= 0 ? name : FAMILY_VIEW", PAGE)


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
        line = APP[APP.index(assign) : APP.index(assign) + 80]
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
        self.assertIn("wallhead.textContent = w.headline", PAGE)
        absent(self, "broadcasting", _wall_code(), "the wall view")

    def test_the_warning_is_printed_not_written(self):
        """Scoped to the wall, not the page. The on-demand panel says
        "selfbot" in a button title and has said it since infra#2887; that
        copy is correct where it is. The rule being pinned is that the WALL
        prints what watchwall composed instead of wording it again."""
        self.assertIn("sum.textContent = w.warning.title", PAGE)
        self.assertIn("body.textContent = w.warning.body", PAGE)
        absent(self, "selfbot", _wall_code(), "the wall view")
        absent(self, "follow", _wall_code(), "the wall view")

    def test_the_warning_is_built_once_and_not_on_every_poll(self):
        """Rebuilding it every five seconds resets `open` under a reader
        mid-sentence, snapping the warning shut while they are in it. Same
        rule the quest board follows: a poll that changed nothing leaves the
        DOM alone."""
        self.assertIn("if (!wallwarn.firstChild) {", PAGE)
        absent(self, "wallwarn.replaceChildren", PAGE, "the wall view")

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
        for word in (
            "max_channels",
            "channels_in_use",
            "startup_seconds",
            "unclaimed",
            "heartbeat",
        ):
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
        fn = APP[APP.index("function layoutBroadcasts") :]
        fn = fn[: fn.index("\n}")]
        self.assertIn("view === WATCH_VIEW", fn)
        self.assertIn("appendChild(t.tile)", fn)
        absent(self, "broadcastTile(", fn, "layoutBroadcasts")

    def test_the_wall_does_not_use_the_wealth_tabs_class_name(self):
        """SHIPPED BROKEN AND WENT LIVE. `.wslot` was already the Wealth tab's
        bag slot: `.wslot img`, `.wslot .nm`, `.wslot.q0` through `.q7` and
        `.wslot.free` have been styled there since long before the wall
        existed. The wall taking the same name meant its slot rules landed on
        every bag, and the bags' item-quality colours landed on the wall.

        Renaming the newcomer, never the incumbent: the wall is `pov-`
        prefixed now, one point of view per tile.

        THE INCUMBENT HAS CHANGED SHAPE SINCE, and the check below moved with
        it rather than being deleted. A bag slot used to be a 44px icon in a
        quality-coloured border (`.wslot img`, `.wslot.q0`); the Bags redesign
        made it an 11px square, ink for full and a hairline for empty, and
        neither of those rules exists any more. What this test is actually
        for - the name still belongs to Bags and the wall still does not touch
        it - is unchanged, so it is asserted against the rules that are there
        now."""
        wall_css = PAGE[PAGE.index("/* --- THE WATCH WALL") :]
        wall_css = wall_css[: wall_css.index("</style>")]
        absent(self, ".wslot", wall_css, "the wall CSS")
        self.assertIn(".povslot", wall_css)
        # And the incumbent is still there, still Bags'.
        self.assertIn("  .wslot { width:11px;", PAGE)
        self.assertIn(".wslot.free {", PAGE)

    def test_no_class_the_wall_defines_is_defined_anywhere_else(self):
        """The general form of the .wslot collision, and the one that catches
        the NEXT one. Two views styling the same class name is invisible in a
        diff, produces no error, and renders as one view quietly wearing the
        other view's rules.

        Scoped to classes the WALL introduces, because plenty of shared
        utility classes legitimately appear in several places; what must not
        happen is a wall-specific name colliding with a view-specific one."""
        style = PAGE[PAGE.index("<style>") : PAGE.index("</style>")]
        block = style[style.index("/* --- THE WATCH WALL") :]
        block = block[: block.index("#wallhead {")]
        outside = style.replace(block, "")
        mine = set(re.findall(r"\.(pov[a-z-]+)", block))
        self.assertTrue(mine, "the wall defines no pov- classes at all")
        for name in sorted(mine):
            self.assertNotIn(
                "." + name, outside, ".%s is styled outside the wall too" % name
            )

    def test_promoting_a_tile_is_offered_and_not_just_possible(self):
        """The tiles were clickable from the day hero mode existed and nothing
        said so, which is the same as not being clickable: nobody tries what a
        page has not offered. A real BUTTON, not a clickable div, so it is
        reachable by keyboard and announces itself."""
        self.assertIn('el("button", "povbig", "BIG")', PAGE)
        self.assertIn("big.onclick", PAGE)
        self.assertIn("e.stopPropagation();", PAGE)

    def test_the_button_and_the_tile_share_one_promote_path(self):
        """Two copies of "make this the hero" is two places for the stored
        preference to be written differently."""
        self.assertIn("function promote(name) {", PAGE)
        self.assertIn("hit.onclick = () => promote(name);", PAGE)

    def test_the_click_target_stops_at_the_caption(self):
        """The handoff is explicit: the transparent button covers everything
        above the bottom bar, never under it, or the label eats the click.
        It also has to sit ABOVE the video, because a <video> with native
        controls swallows clicks that land on it, which is why the tile is
        INSERTED FIRST rather than appended."""
        self.assertIn('el("button", "povhit")', PAGE)
        self.assertIn("shot.append(hit, big);", PAGE)
        self.assertIn("target.insertBefore(t.tile, target.firstChild)", PAGE)
        css = PAGE[PAGE.index(".povhit {") :]
        self.assertIn("inset:0", css[: css.index("}")])

    def test_it_is_offered_only_where_it_means_something(self):
        """ "Make this the big one" says nothing when there is no big one, and
        nothing on the tile that already is it. FIVE UP and HERO both have a
        big tile; STACKED does not, so there the chip would be a promise the
        layout does not keep."""
        self.assertIn('s.big.hidden = wall.mode === "stacked" || isHero;', PAGE)

    def test_a_slot_is_built_once_and_cached(self):
        self.assertIn("let slot = wall.slots.get(name);", PAGE)
        self.assertIn('el("div", "povslot")', PAGE)
        self.assertIn("if (slot) return slot;", PAGE)

    def test_hero_is_promoted_by_span_not_by_order(self):
        """`order` would move tiles past each other visually, which is
        reordering the roster by another name."""
        self.assertIn("#wall.m-hero > .povslot.hero { grid-column:1 / -1; }", PAGE)
        wall_css = PAGE[PAGE.index("#wall { display:grid") :][:1400]
        # Anchored, because "order:" is a substring of "border:" and the
        # unanchored version could never pass.
        self.assertIsNone(
            re.search(r"[;{\s]order\s*:", wall_css),
            "the wall CSS reorders tiles with `order`",
        )


class HeroModeDoesNotWalkBackIntoTheTinyTwitchView(unittest.TestCase):
    """This page HAD one big player and four thumbnails. infra#88 removed it
    because on a phone the four were the smallest thing on screen, and the
    operator said so in as many words. It is back only as a choice."""

    def test_the_default_is_not_hero(self):
        self.assertIn("DEFAULT_MODE = FIVE_UP", _module_source())

    def test_hero_collapses_to_one_column_on_a_narrow_screen(self):
        """ONE COLUMN, and that is what this test has been named all along.

        It used to assert TWO, which is what the block actually did, and two
        columns on a 390px screen is a 177px tile: infra#88's complaint about
        the tiny twitch view arriving again by a different route, asserted as
        if it were the fix. infra#3482 made every mode a single full-width
        column below the breakpoint and this assertion now says so.

        m-hero is named here too. It was never in this block at all, so its
        `minmax(150px, 1fr)` auto-fit ran at full strength on the narrowest
        screen the page has, which is the exact rail the class docstring above
        says the wall must never collapse into."""
        # 640px, which is the handoff's single breakpoint. The first version
        # of the wall invented 760 along with the rest of its geometry.
        self.assertIn("@media (max-width: 640px) {", PAGE)
        narrow = PAGE[PAGE.index("@media (max-width: 640px) {") :]
        head = narrow[:400]
        self.assertIn(
            "#wall.m-five-up, #wall.m-hero { grid-template-columns:1fr;", head
        )
        # No mode is left out: a mode with no rule here is a mode that keeps
        # its desktop column count on a phone, which is how m-hero was missed.
        for mode in ("m-five-up", "m-hero"):
            self.assertIn("#wall.%s > .povslot.hero" % mode, head, mode)

    def test_the_promoted_tile_leads_the_phone_column(self):
        """A hero that is only "the first row" of a four-column grid means
        nothing once there is one column: the promoted tile would sit wherever
        roster order put it, and promoting would do nothing visible. It leads
        with `order`, which is also why it is a grid property and not a DOM
        move - layoutBroadcasts re-parents live PeerConnections, and
        reordering the array would tear one down to change a layout."""
        narrow = PAGE[PAGE.index("@media (max-width: 640px) {") :][:400]
        self.assertIn("order:-1", narrow)


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
        cue = PAGE[PAGE.index("function wallCue") :]
        cue = cue[: cue.index("\n}")]
        self.assertIn("try {", cue)
        self.assertIn("catch", cue)


class TheStoredPreferencesAreHandledLikeStorage(unittest.TestCase):
    def test_every_access_goes_through_the_wrapped_helpers(self):
        """localStorage THROWS rather than returning null in a private window,
        and an unwrapped read would stop the wall drawing at all."""
        for helper in ("function wallStored", "function wallStore"):
            body = PAGE[PAGE.index(helper) :]
            self.assertIn("try {", body[:260])
            self.assertIn("catch", body[:260])
        # Counted over CODE, not comments: the block comment above the
        # helpers explains why localStorage is wrapped, and counting the word
        # there punishes the explanation instead of the thing explained.
        self.assertEqual(
            _wall_code().count("localStorage"),
            2,
            "raw localStorage use outside the two helpers",
        )

    def test_a_stored_mode_is_validated_against_the_server(self):
        """It arrives from browser storage, which is to say from anywhere, and
        an unknown mode is a wall with no layout at all."""
        self.assertIn("w.modes.indexOf(stored) >= 0 ? stored : w.default_mode", PAGE)

    def test_a_stored_hero_is_validated_against_the_tiles_on_the_wall(self):
        """The stored name is honoured ONLY when it is one of the tiles actually
        on the wall, and the module's own hero is the fallback. The wall is the
        tiles that can play - a character with no stream has no tile - so
        "the five" became "whoever is shown", and the validation is against that
        list. The stored value must never reach the wall unchecked."""
        self.assertIn("const shown = w.tiles.filter((t) => t.playable);", PAGE)
        self.assertIn("const names = shown.map((t) => t.name);", PAGE)
        self.assertIn("names.indexOf(chosen) >= 0 ? chosen", PAGE)
        # The module's hero is still the fallback, and only if it is shown.
        self.assertIn("names.indexOf(w.hero) >= 0 ? w.hero", PAGE)


def _module_source():
    with open(os.path.join(HERE, "watchwall.py"), encoding="utf-8") as fh:
        return fh.read()


class ThePageFitsThePhoneItIsReadOn(unittest.TestCase):
    """infra#3482. Two declarations, each missing, each invisible in a diff,
    and between them the page could not be used on a phone at all.

    Neither produced an error, a warning or a scrollbar. The first wrapped the
    tab row into four ragged lines above every view; the second made the wall
    wider than the screen, which mobile Safari answers by zooming the entire
    document out until it fits - so the report that arrived was "all the text
    is about 7px", which points at a font size and is caused by a grid."""

    def test_the_tab_row_says_it_does_not_wrap(self):
        """#tabs is a <nav>, and the shell's generic `nav` rule is the only
        rule on this page that declares flex-wrap at all. An ID selector does
        not beat a type selector on a property it never sets, so the generic
        `flex-wrap:wrap` won by default and `overflow-x:auto` had nothing left
        to scroll. The row has to say nowrap itself."""
        # Anchored on the declaration rather than on "#tabs {", because the
        # phone block sets a mask on the same id and comes first in the file.
        rule = PAGE[PAGE.index("#tabs { display:flex") :]
        rule = rule[: rule.index("}")]
        self.assertIn("flex-wrap:nowrap", rule)
        self.assertIn("overflow-x:auto", rule)

    def test_the_generic_nav_rule_still_wraps_for_everyone_else(self):
        """The fix is stated on #tabs rather than taken off `nav`, because
        #realmnav and #ajump are both still dressed by that rule and both
        want to wrap. This asserts the fix did not become a deletion."""
        self.assertIn("flex-wrap:wrap; }", PAGE[PAGE.index("  nav {") :][:120])

    def test_a_tab_never_breaks_across_two_lines(self):
        """ "Eastern Kingdoms" in a scrolling row with nowhere to wrap to."""
        rule = PAGE[PAGE.index("  #tabs button {") :]
        self.assertIn("white-space:nowrap", rule[: rule.index("}")])

    def test_the_selected_tab_is_scrolled_back_into_its_own_row(self):
        """Fourteen tabs on a row narrower than half of them. Opening the
        Armory from a link used to leave the lit tab off-screen, which reads
        as no tab being lit at all."""
        self.assertIn("function revealTab(b) {", PAGE)
        self.assertIn("if (on) revealTab(b);", PAGE)

    def test_revealing_a_tab_can_scroll_nothing_but_the_row(self):
        """scrollIntoView walks EVERY scrollable ancestor including the
        document, and block:"nearest" does not stop it: on first paint the
        row is below the fold, so the first version of this scrolled the page
        430px down and left it there, every load landing halfway through the
        header. scrollLeft touches one axis of one element."""
        fn = PAGE[PAGE.index("function revealTab(b) {") :]
        fn = fn[: fn.index("\n}")]
        self.assertIn("row.scrollLeft", fn)
        absent(self, "scrollIntoView", fn, "revealTab")
        absent(self, "scrollTop", fn, "revealTab")

    def test_the_caption_carries_the_identity_the_overlay_used_to(self):
        """The tile's overlay comes off on this view, so the caption has to
        say what the overlay said: what this character is, not only who. The
        phrase is the module's, like every other word on this wall."""
        self.assertIn('el("span", "povstanding")', PAGE)
        # `|| ""` and not a bare assignment: textContent of undefined prints
        # the word "undefined" into the caption, and empty is what
        # .povstanding:empty keys off to take its gap out of the row.
        self.assertIn('s.standing.textContent = t.standing || "";', PAGE)
        # Composed in watchwall, never assembled out of two fields here.
        # Scoped to the wall's own render loop: `.level` is read legitimately
        # elsewhere on the page, and an unscoped search finds those instead.
        loop = PAGE[PAGE.index("for (const t of shown) {") :]
        loop = loop[: loop.index("\n  }")]
        # ("t.class" is not checked here: it is a substring of
        # "slot.classList", which the same loop uses legitimately.)
        absent(self, "t.level", loop, "the wall render loop")

    def test_the_tile_wears_no_second_caption(self):
        """The Family tab's overlay travels with the tile when it is
        re-parented, so without this the name and the sentence are printed
        twice - once over the game and once beneath it - and the overlay's
        `fullscreen` button lands on top of the BIG chip."""
        block = PAGE[PAGE.index("/* --- THE WATCH WALL") :]
        block = block[: block.index("#wallhead {")]
        for hidden in (".povshot .fovname", ".povshot .fovzone", ".povshot .ffull"):
            self.assertIn(hidden, block, hidden)

    def test_health_survives_the_overlay_coming_off(self):
        """It is the one thing the overlay carried that the caption does not,
        and five bars in the same place on five tiles is the whole reason to
        look at a wall rather than five cards."""
        block = PAGE[PAGE.index("/* --- THE WATCH WALL") :]
        block = block[: block.index("#wallhead {")]
        self.assertIn(".povshot .fovbar", block)

    def test_a_tile_can_be_narrower_than_its_own_contents(self):
        """A grid item's automatic minimum size is its min-content width, and
        a tile's min-content is a <video> inside two nested aspect-ratio
        boxes: 360px, measured, whatever column it was handed. Without this
        the wall could not shrink to a 320px screen and stood 72px wider than
        the element containing it."""
        rule = PAGE[PAGE.index("  .povslot {") :]
        self.assertIn("min-width:0", rule[: rule.index("}")])

    def test_the_wall_declares_no_track_it_cannot_honour(self):
        """The general form of the rule above. Every track floor on the wall
        has to be reachable on the narrowest screen the page has."""
        block = PAGE[PAGE.index("/* --- THE WATCH WALL") :]
        block = block[: block.index("#wallhead {")]
        for floor in re.findall(r"minmax\(\s*(\d+)px", block):
            self.assertLessEqual(
                int(floor),
                320,
                "a %spx track floor cannot be met on a 320px screen" % floor,
            )


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
