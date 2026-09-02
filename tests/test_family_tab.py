"""The Family tab's page contract: the rules that cost something to learn.

Asserted against index.html as source, the same way test_stream.py guards the
player - map_server.py imports pymysql and the page has no other test seam.
These are deliberately not "does it render": they are the handful of rules
that were each paid for by a real failure, and that a refactor could quietly
undo while leaving five cards on screen looking perfectly fine.

Ticket: infra#2892.
"""
import unittest

import family


class TheFamilyTab(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import pathlib
        here = pathlib.Path(__file__).resolve().parent.parent
        cls.page = (here / "index.html").read_text()
        cls.server = (here / "map_server.py").read_text()
        start = cls.page.index("// --- the Family tab (infra#2892)")
        cls.tab = cls.page[start:cls.page.index("loadZones().then(")]

    def test_the_tab_exists_beside_the_continents(self):
        self.assertIn('<section id="family">', self.page)
        self.assertIn('fb.dataset.view = FAMILY_VIEW', self.page)

    def test_only_pov_is_offered(self):
        """infra#2887: follow-cam is NOT implemented and answers with a
        refusal after about forty seconds of pointless client bring-up. A
        button whose only possible outcome is a wasted minute of somebody
        else's GPU is worse than no button, so this tab does not have one."""
        self.assertIn('requestWatch(name, "pov")', self.tab)
        self.assertNotIn('"cam"', self.tab)
        self.assertNotIn('"shot"', self.tab)

    def test_a_full_gpu_is_said_on_the_button_not_discovered_by_waiting(self):
        """One GPU, two clients. A third tap CANNOT succeed, and the honest
        place to say so is the control the person is already looking at -
        not a refusal forty seconds later."""
        self.assertIn("both channels busy (", self.tab)
        self.assertIn("channels_in_use", self.tab)
        self.assertIn("max_channels", self.tab)

    def test_the_cards_are_built_once_and_updated_in_place(self):
        """Rebuilding the cards on the 5s poll would replace the <video>
        element mid-stream every five seconds - a black rectangle and a torn
        down PeerConnection, dressed up as a refresh."""
        self.assertIn("let c = fam.cards.get(name);\n  if (c) return c;", self.tab)
        card_render = self.tab[self.tab.index("function renderFamily"):]
        card_render = card_render[:card_render.index("function updateFamilyButtons")]
        self.assertNotIn("replaceChildren", card_render)
        self.assertNotIn("innerHTML", card_render)

    def test_nothing_reaches_the_page_as_markup(self):
        """Names and zones come from the database and must render inert -
        the same rule the character panel has followed since infra#2603."""
        self.assertNotIn("innerHTML", self.tab)

    def test_leaving_the_tab_stops_the_video_but_not_the_stream(self):
        """The same rule closePanel follows: a viewer may switch to the map or
        put the phone down and keep watching on the Switch. Only the server's
        staleness sweep decides, because only it cannot be fooled by how the
        page was left."""
        show = self.tab[self.tab.index("function showView"):]
        show = show[:show.index("setInterval(pollFamily")]
        self.assertIn("player.stop()", show)
        self.assertIn("clearInterval", show)
        self.assertNotIn('watchPost(', show,
                         "telling the server to stop is what the stop button "
                         "is for; a tab switch must not end somebody's stream")

    def test_the_stop_button_does_tell_the_server(self):
        stop = self.tab[self.tab.index("async function familyStop"):]
        stop = stop[:stop.index("async function refreshFamilyWatch")]
        self.assertIn('watchPost(name, "stop")', stop)
        self.assertIn("watch.timer", stop)

    def test_switching_characters_tears_the_first_one_down_first(self):
        """Or the switch leaves the first character's video playing under the
        second character's name - the exact confusion this feature removes."""
        watch = self.tab[self.tab.index("async function familyWatch"):]
        watch = watch[:watch.index("async function familyStop")]
        self.assertLess(watch.index("familyStop()"), watch.index("requestWatch("))

    def test_the_watch_is_heartbeaten_through_the_one_shared_helper(self):
        """A surface that asks for a client without beating leaves it
        rendering the game for nobody, which is the precise cost infra#2663
        exists to avoid. One helper, so there is one answer."""
        self.assertIn('requestWatch(name, "pov")', self.tab)
        self.assertNotIn('"beat"', self.tab,
                         "the tab must not grow its own heartbeat - two beats "
                         "for one page is two answers to who is still here")

    def test_the_roster_is_not_retyped_into_the_page(self):
        """WHO the family is belongs to bonds.FAMILY. A second list in the
        HTML is a second answer that can disagree with it - and it would
        disagree silently, by drawing four cards."""
        for name in family.roster():
            self.assertNotIn('"' + name + '"', self.tab)

    def test_the_endpoint_takes_no_roster_from_the_caller(self):
        handler = self.server[self.server.index("def _family"):]
        handler = handler[:handler.index("def _thoughts")]
        self.assertIn("family.build_family(_fetch_family(), GEO)", handler)
        self.assertNotIn("query.get", handler)

    def test_a_failed_poll_keeps_the_cards_it_has(self):
        """A Family tab that blanks on a failed poll is indistinguishable
        from a family who all logged out at once."""
        poll = self.tab[self.tab.index("async function pollFamily"):]
        poll = poll[:poll.index("function markTabs")]
        self.assertIn("unreachable", poll)
        self.assertNotIn("replaceChildren", poll)


class TheBroadcastGrid(unittest.TestCase):
    """The five always-on broadcasts (infra#2892), independent of the
    on-demand watch/POV cards this class's siblings above already cover.

    infra#3110 MOVED THEM. They shipped as a Twitch-style grid of their own -
    one focused player, a strip of five thumbnails, and the character list
    underneath - and the operator's complaint was that this is a wall of
    video over a wall of names, leaving a viewer to match one to the other by
    position. Each tile now lives in the card of the character it is showing.
    Everything else about them is unchanged, and most of this class exists to
    say so: the handshake, the retry, the offline message, the build-once
    rule and the focused-tile-only fullscreen all still hold."""

    @classmethod
    def setUpClass(cls):
        import pathlib
        here = pathlib.Path(__file__).resolve().parent.parent
        cls.page = (here / "index.html").read_text()
        start = cls.page.index("// --- the Family tab (infra#2892)")
        cls.tab = cls.page[start:cls.page.index("loadZones().then(")]

    def test_a_stream_is_parented_into_its_own_character_card(self):
        """infra#3110, requirement 2, and the whole of it: a tile's home is
        the card of the character it shows. Not a shared focus slot, not a
        thumbnail strip beside the names - there is nothing left on this page
        that holds video for more than one person."""
        self.assertIn('<section id="family">', self.page)
        section = self.page[self.page.index('<section id="family">'):
                             self.page.index("</section>")]
        self.assertNotIn('id="ftwitch"', section)
        self.assertNotIn('id="ffocus"', section)
        self.assertNotIn('id="fthumbs"', section)
        card = self.tab[self.tab.index("function familyCard"):]
        card = card[:card.index("// --- the broadcasts")]
        self.assertIn('el("div", "fstream")', card)
        layout = self.tab[self.tab.index("function layoutBroadcasts"):]
        layout = layout[:layout.index("function promoteBroadcast")]
        self.assertIn("familyCard(name).stream", layout)

    def test_the_stream_sits_under_the_name_and_above_the_state(self):
        """"This is Grug, this is Grug's stream" has to be one unit read top
        to bottom, or the move has bought nothing: a tile appended after the
        watch button would be back to being a video near a name."""
        card = self.tab[self.tab.index("function familyCard"):]
        card = card[:card.index("// --- the broadcasts")]
        order = card[card.index("card.append("):]
        order = order[:order.index(")")]
        self.assertLess(order.index("head"), order.index("stream"))
        self.assertLess(order.index("stream"), order.index("quests"))
        self.assertLess(order.index("quests"), order.index("btn"))

    def test_tiles_are_built_once_and_moved_not_rebuilt(self):
        """Same rule as familyCard: rebuilding a tile mid-stream would
        replace its <video> and tear down a live PeerConnection to redraw a
        picture that was already fine."""
        self.assertIn(
            "let t = broadcasts.tiles.get(name);\n  if (t) return t;", self.tab)

    def test_promoting_a_thumbnail_moves_the_node_rather_than_reconnecting(self):
        layout = self.tab[self.tab.index("function layoutBroadcasts"):]
        layout = layout[:layout.index("function promoteBroadcast")]
        self.assertIn("appendChild", layout)
        self.assertNotIn("makePlayer(", layout)
        self.assertNotIn("player.start(", layout)

    def test_the_grid_reuses_the_one_shared_whep_player(self):
        """makePlayer's own comment calls itself shared across 'TWO
        SURFACES' (the panel and the watch cards); this is the third, not a
        fourth reimplementation of the handshake."""
        self.assertEqual(self.tab.count("makePlayer(video,"), 2)

    def test_the_grid_starts_and_stops_with_the_tab(self):
        show = self.tab[self.tab.index("function showView"):]
        show = show[:show.index("setInterval(pollFamily")]
        fam_branch = show[show.index("if (isFam)"):show.index("stopBroadcasts();")]
        self.assertIn("startBroadcasts();", fam_branch)
        self.assertIn("stopBroadcasts();", show)

    def test_the_focused_tile_offers_fullscreen(self):
        """The grid shipped with no fullscreen affordance at all: goFullscreen()
        existed but ONLY the panel's card player called it, so on a phone - the
        device this tab was built for - there was nothing to tap. The button
        must be built into the tile and wired to the shared helper, not to a
        fourth reimplementation of the fullscreen dance."""
        tile = self.tab[self.tab.index("function broadcastTile"):]
        tile = tile[:tile.index("function layoutBroadcasts")]
        self.assertIn('el("button", "ffull"', tile)
        self.assertIn("goFullscreen(tile, video,", tile)

    def test_the_fullscreen_tap_does_not_also_promote_the_tile(self):
        """The tile's own click promotes it. Without stopPropagation the one
        tap runs both, which is a no-op on the focused tile today and becomes a
        second silent action the day promoteBroadcast stops returning early."""
        tile = self.tab[self.tab.index("function broadcastTile"):]
        tile = tile[:tile.index("function layoutBroadcasts")]
        onclick = tile[tile.index("full.onclick"):]
        self.assertIn("e.stopPropagation();",
                      onclick[:onclick.index("goFullscreen(")])

    def test_fullscreen_is_offered_only_on_the_focused_tile(self):
        """A tap on a thumbnail already means "make this the big one". Offering
        fullscreen there would give one tap two meanings. The overlay is
        pointer-events:none, so the button must opt back in for itself or it
        cannot be tapped at all.

        The selector moved with the tile (infra#3110) - focused is a class on
        the tile now rather than the slot it was moved into - but the rule is
        the same rule."""
        self.assertIn(".ftile .ffull { display:none; pointer-events:auto;",
                      self.page)
        self.assertIn(".ftile.focused .ffull { display:inline-block; }",
                      self.page)

    def test_a_refused_fullscreen_is_shown_to_the_person(self):
        """goFullscreen insists a refusal is said out loud, which is only true
        if the caller renders the sentence it is handed."""
        tile = self.tab[self.tab.index("function broadcastTile"):]
        tile = tile[:tile.index("function layoutBroadcasts")]
        self.assertIn("fsnote.textContent = text;", tile)


    def test_the_focused_tile_gets_native_video_controls(self):
        """The scripted fullscreen button is not what a thumb reaches for. iOS
        Safari gives a <video> its own fullscreen affordance through the native
        control bar, which is the control people already know from YouTube, so
        the focused tile carries it. Thumbnails must NOT, or the control bar
        covers a 150px picture and swallows the tap that promotes it."""
        layout = self.tab[self.tab.index("function layoutBroadcasts"):]
        layout = layout[:layout.index("function promoteBroadcast")]
        self.assertIn("t.video.controls = big;", layout)

    def test_thumbnails_do_not_carry_controls(self):
        """Guards the half that is easy to regress: controls must be bound to
        the focused flag, never set unconditionally at tile construction."""
        tile = self.tab[self.tab.index("function broadcastTile"):]
        tile = tile[:tile.index("function layoutBroadcasts")]
        self.assertNotIn("video.controls = true", tile)

    def test_leaving_the_tab_does_not_ask_the_encoders_to_stop(self):
        """These five broadcasts are not this page's to end - it never
        asked them to start, so leaving the tab must only drop the
        picture, never call out to stop anything running on the gaming
        box."""
        stop_fn = self.tab[self.tab.index("function stopBroadcasts"):]
        stop_fn = stop_fn[:stop_fn.index("function renderFamily")]
        self.assertIn("player.stop()", stop_fn)
        self.assertNotIn("fetch(", stop_fn)
        self.assertNotIn("watchPost(", stop_fn)

    def test_a_dark_path_reads_as_offline_with_its_own_reason(self):
        """Requirement #3: an absent or not-ready broadcast must say so,
        not sit there as a dead black rectangle. The reason shown is
        whatever the WHEP handshake actually said, not a bare 'OFFLINE'."""
        tile_fn = self.tab[self.tab.index("function broadcastTile"):]
        tile_fn = tile_fn[:tile_fn.index("function layoutBroadcasts")]
        self.assertIn('tile.classList.add("offline")', tile_fn)
        self.assertIn("off.textContent = name +", tile_fn)

    def test_no_roster_name_is_retyped_into_the_broadcast_code(self):
        """Same rule test_the_roster_is_not_retyped_into_the_page enforces
        for the cards: WHO the family is belongs to bonds.FAMILY by way of
        /api/family, never a second list somebody could disagree with."""
        grid = self.tab[self.tab.index("// --- the broadcasts"):
                         self.tab.index("function renderFamily")]
        for name in family.roster():
            self.assertNotIn('"' + name + '"', grid)


class ThumbSizedBroadcastGrid(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import pathlib
        here = pathlib.Path(__file__).resolve().parent.parent
        page = (here / "index.html").read_text()
        cls.css = page[page.index("the broadcast tile, inside its own"):
                        page.index("</style>")]

    def test_the_empty_slot_reserves_the_shape_not_the_tile(self):
        """makePlayer owns the tile's `display` - none until start(), none
        again after stop() - so a reservation hung on the tile is worth
        nothing in the exact window it is needed. The card must hold the
        space while there is no picture in it, or the quest log underneath
        gets shoved down half a second later under a thumb already reaching
        for it."""
        slot = self.css[self.css.index(".fstream {"):]
        slot = slot[:slot.index("}")]
        self.assertIn("aspect-ratio:16/9", slot)
        self.assertIn("width:170px", slot)
        self.assertIn(".fstream.big { width:100%; }", self.css)

    def test_the_focused_player_letterboxes_rather_than_crops(self):
        """Same rule the panel's fullscreen view follows: a cropped POV
        hides the hotbars, half of why watching it is worth doing."""
        rule = self.css[self.css.index(".ftile.focused video"):]
        self.assertIn("object-fit:contain", rule[:rule.index("}")])

    def test_offline_hides_the_frozen_frame_rather_than_the_message(self):
        video_rule = self.css[self.css.index(".ftile.offline video"):]
        self.assertIn("visibility:hidden", video_rule[:video_rule.index("}")])
        message_rule = self.css[self.css.index(".ftile.offline .foffline"):]
        self.assertIn("display:flex", message_rule[:message_rule.index("}")])


class ThumbSized(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import pathlib
        here = pathlib.Path(__file__).resolve().parent.parent
        page = (here / "index.html").read_text()
        cls.css = page[page.index("--- the Family tab (infra#2892)"):page.index("</style>")]

    def test_every_control_is_at_least_a_finger_wide(self):
        """44px is the floor a thumb can reliably hit. The page's own nav
        buttons were 28px, which is why they are bumped on touch too."""
        self.assertIn("min-height:44px", self.css)
        self.assertIn("pointer:coarse", self.css)

    def test_the_player_reserves_its_shape_before_the_first_frame(self):
        """A box that grows when video arrives makes the card jump under a
        thumb that is already reaching for it."""
        vid = self.css[self.css.index(".fvid {"):]
        self.assertIn("aspect-ratio:16/9", vid[:vid.index("}")])

    def test_a_dead_card_is_loud_rather_than_dim(self):
        """The whole complaint was that a family dying on a loop looked like
        nothing at all. Greying a dead card out would repeat the bug."""
        dead = self.css[self.css.index(".fcard.c-dead {"):]
        dead = dead[:dead.index("}")]
        self.assertIn("--horde", dead)
        self.assertNotIn("opacity", dead)

    def test_one_column_until_there_is_honestly_room(self):
        self.assertIn("grid-template-columns:1fr", self.css)
        self.assertIn("min-width:820px", self.css)


if __name__ == "__main__":
    unittest.main()


class TheBrokenButtonMustNotBeSpendable(unittest.TestCase):
    """infra#2887, found the way it should never be found - by Evan.

    `watch them` (follow-cam) sat FIRST in the character panel, read as the
    primary action, and is not implemented: it spends ~40 seconds bringing a
    client up and then answers with a refusal about needing a GM account that
    is not one of the family. He tapped it on his phone, waited, got nothing,
    and reasonably concluded streaming was broken - on the day it had been
    proven working end to end.

    The Family tab never offered it. The older panel did, and reordering alone
    would not have been enough: the panel re-enabled every button on each state
    change, so a merely-demoted control goes straight back to being spendable
    on the next poll.
    """

    @classmethod
    def setUpClass(cls):
        import pathlib
        cls.page = (pathlib.Path(__file__).resolve().parent.parent / "index.html").read_text()

    def test_the_working_mode_comes_first(self):
        self.assertLess(self.page.index('id="pwpov"'), self.page.index('id="pwcam"'),
                        "the button that works must precede the one that cannot")

    def test_follow_cam_ships_disabled(self):
        tag = self.page[self.page.index('id="pwcam"'):]
        self.assertIn("disabled", tag[:tag.index(">") + 1])

    def test_nothing_re_enables_follow_cam(self):
        # The part that actually matters - see the class docstring.
        self.assertNotIn("pwcam.disabled = pwpov.disabled = pwshot.disabled = false", self.page)
        self.assertNotIn("pwcam.disabled = false", self.page)

    def test_it_says_why_rather_than_just_being_dead(self):
        tag = self.page[self.page.index('id="pwcam"'):]
        self.assertIn("2887", tag[:tag.index("</button>")],
                      "a disabled control must carry its reason")


class TheQuestLogOnTheCard(unittest.TestCase):
    """infra#3110 requirement 1: what each of the five is actually working on,
    under their own name.

    The judgements all live in questlog.py, with their own suite. These are
    the page rules - the ones a refactor could undo while leaving five
    perfectly plausible quest lists on screen."""

    @classmethod
    def setUpClass(cls):
        import pathlib
        here = pathlib.Path(__file__).resolve().parent.parent
        cls.page = (here / "index.html").read_text()
        cls.server = (here / "map_server.py").read_text()
        start = cls.page.index("// --- the Family tab (infra#2892)")
        cls.tab = cls.page[start:cls.page.index("loadZones().then(")]
        cls.block = cls.tab[cls.tab.index("// --- the quest log (infra#3110)"):
                             cls.tab.index("// POV AND ONLY POV")]
        # The block without its opening essay, for the assertions that are
        # about what the CODE says rather than what the comments explain.
        cls.code = cls.block[cls.block.index("const fquesthead"):]

    def test_the_log_is_drawn_inside_the_character_own_card(self):
        """Not a sixth panel below the five cards. A quest log belongs to a
        character, and the whole point of putting it here is that it is read
        beside that character's name, health and stream."""
        section = self.page[self.page.index('<section id="family">'):
                             self.page.index("</section>")]
        self.assertIn('id="fquesthead"', section)
        self.assertIn('el("div", "fquests")', self.tab)
        self.assertIn("familyCard(m.name)", self.block)
        self.assertIn("c.qlist", self.block)

    def test_the_slot_count_is_said_even_when_it_is_fine(self):
        """mod-overseer#73 hid for a month because nothing counted the slots.
        A number that only appears once it is already bad is a number nobody
        has learned to read by the time it matters."""
        head = self.block[self.block.index("function questHeadline"):]
        head = head[:head.index("function questRow")]
        first = head.index('m.used + " of " + m.slots')
        # Unconditional: before any of the `if` lines that add the rest.
        self.assertLess(first, head.index("if (m.ready)"))

    def test_the_page_does_not_decide_what_a_full_log_is(self):
        """questlog.py owns the cap and how near it counts as full. A 25 typed
        into this file is a second answer that can disagree with the first,
        and it would disagree silently."""
        self.assertNotIn("25", self.code)
        self.assertIn("m.slots", self.code)
        self.assertIn("m.full", self.code)

    def test_every_quest_says_who_else_is_carrying_it(self):
        """mod-overseer#28 in the only place it can be seen: on the quest
        itself. Four names means the fight pays four of them; no names means
        it pays one, and that is the sentence that has to be on screen."""
        row = self.block[self.block.index("function questRow"):]
        row = row[:row.index("function renderQuestLog")]
        self.assertIn("q.held_by.filter", row)
        self.assertIn("nobody else holds this", row)

    def test_the_quest_list_is_the_only_thing_rebuilt(self):
        """replaceChildren anywhere near a card is how a live <video> gets
        thrown away mid-stream. It is allowed here and ONLY here, because
        this list is text the server just recomputed."""
        self.assertEqual(self.tab.count(".replaceChildren("), 1)
        render = self.block[self.block.index("function renderQuestLog"):]
        render = render[:render.index("function renderQuests")]
        self.assertIn("c.qlist.replaceChildren", render)

    def test_a_poll_that_changed_nothing_leaves_the_list_alone(self):
        """Thirty seconds apart, most polls are identical. Rebuilding anyway
        would throw away a half-read list under somebody's thumb for no
        change at all."""
        render = self.block[self.block.index("function renderQuestLog"):]
        render = render[:render.index("function renderQuests")]
        self.assertIn("quested.get(m.name) === sig", render)
        self.assertLess(render.index("return;"), render.index("replaceChildren"))

    def test_a_long_log_folds_but_its_totals_do_not(self):
        """Sixty-five quests across five characters is nine thousand pixels of
        phone scrolling, and a twenty-two row log buries the next character's
        stream under it. Folding the LIST is only safe because the header line
        above it already carries every number the two defects are made of -
        so the fold must sit below that line, never replace it."""
        render = self.code[self.code.index("function renderQuestLog"):]
        render = render[:render.index("function renderQuests")]
        self.assertIn("QUEST_PREVIEW", render)
        self.assertLess(render.index("questHeadline(m)"), render.index("QUEST_PREVIEW"))
        # Says how many are hidden and where they are, because the order is
        # meaningful: what folds away is the oldest end of the log.
        self.assertIn('" more, oldest last"', render)

    def test_expanding_a_log_is_not_swallowed_by_the_no_change_guard(self):
        """Nothing about the DATA changes when somebody taps "show more",
        which is exactly what that guard skips on."""
        render = self.code[self.code.index("function renderQuestLog"):]
        render = render[:render.index("function renderQuests")]
        toggle = render[render.index("more.onclick"):]
        self.assertIn("quested.delete(m.name)", toggle)

    def test_a_failed_poll_keeps_the_logs_it_has(self):
        """An empty quest log means "they have nothing to do", which is the
        opposite of what a failed read actually found out."""
        poll = self.block[self.block.index("async function pollQuests"):]
        self.assertIn("unreachable", poll)
        self.assertNotIn("replaceChildren", poll)

    def test_the_log_rides_its_own_slower_cadence(self):
        """Quest rows are SAVED state on the core's own player-save timer, so
        the 5s cadence would re-fetch an identical payload several times per
        actual change. Entering the tab still reads immediately, or the tab
        would be blank for half a minute on arrival."""
        self.assertIn("setInterval(pollQuests, 30000)", self.tab)
        show = self.tab[self.tab.index("function showView"):]
        show = show[:show.index("setInterval(pollFamily")]
        self.assertIn("pollQuests();", show[show.index("if (isFam)"):])

    def test_the_endpoint_takes_no_roster_from_the_caller(self):
        """Same rule /api/family and /api/armory follow: WHO the family is
        belongs to bonds, and a roster parameter would make this a general
        character query wearing a friendly name."""
        handler = self.server[self.server.index("def _questlog"):]
        handler = handler[:handler.index("def _thoughts")]
        self.assertIn("questlog.build_questlog(**_fetch_questlog())", handler)
        self.assertNotIn("query.get", handler)

    def test_the_endpoint_is_wired_into_the_route_table(self):
        """do_GET is a lookup and nothing else, so a handler that is never
        named in the table is a 404 with a docstring."""
        self.assertIn('"/api/questlog": _questlog,', self.server)

    def test_the_query_reads_the_statuses_the_module_named(self):
        """The status filter is the difference between a slot count that fits
        in 25 and one that does not (see questlog.IN_LOG). Spelling it into
        the SQL by hand is how it drifts from the module that explains it."""
        fetch = self.server[self.server.index("def _fetch_questlog"):]
        fetch = fetch[:fetch.index("def _ensure_stream_store")]
        self.assertIn("questlog.IN_LOG", fetch)
        self.assertIn("questlog.objective_entries", fetch)


class TheFamilyIsTheFrontDoor(unittest.TestCase):
    """infra#3110 requirement 3. Opening the site landed on the map, which
    answers "who is in the world" - five hundred dots on a phone - when the
    question actually being asked is "are my five all right". And there was no
    routing at all, so no view could be linked to."""

    @classmethod
    def setUpClass(cls):
        import pathlib
        here = pathlib.Path(__file__).resolve().parent.parent
        cls.page = (here / "index.html").read_text()
        cls.route = cls.page[cls.page.index("// --- the front door (infra#3110)"):]

    def test_the_view_is_chosen_on_load(self):
        """A routing function nothing calls is decoration. It has to run at
        the foot of the script - showView touches the Armory tab's own consts,
        so calling it any earlier is a temporal-dead-zone ReferenceError."""
        self.assertIn("\napplyHash();", self.route)
        self.assertLess(self.page.index("setInterval(pollArmory, 30000)"),
                        self.page.index("\napplyHash();"))

    def test_an_unknown_or_missing_hash_lands_on_the_family(self):
        fn = self.route[self.route.index("function applyHash"):]
        fn = fn[:fn.index('window.addEventListener("hashchange"')]
        self.assertIn("FAMILY_VIEW", fn)
        # The map branch returns first; everything else falls through to the
        # family, including a hash that names nothing at all.
        self.assertLess(fn.index("MAP_VIEW"), fn.index("ARMORY_VIEW"))

    def test_the_other_views_are_still_reachable_by_link(self):
        """The half that is easy to lose: making one view the default is only
        half of routing, and the other half is what makes "send me the Armory"
        a thing somebody can do."""
        fn = self.page[self.page.index("function hashFor"):]
        fn = fn[:fn.index("function showView")]
        self.assertIn("MAP_VIEW", fn)
        self.assertIn("ARMORY_VIEW", self.route)
        # The map carries its continent, or a link to it forgets the one piece
        # of state that view actually has.
        self.assertIn('"#" + MAP_VIEW + "/" + current', fn)

    def test_a_deep_linked_continent_waits_for_the_map_data(self):
        """The hash is read before zones.json arrives, so there is nothing to
        check the id against yet. Adopting it unchecked draws an empty map."""
        self.assertIn("adoptContinent();", self.page[:self.page.index("markTabs();")])
        adopt = self.route[self.route.index("function adoptContinent"):]
        adopt = adopt[:adopt.index("function applyHash")]
        self.assertIn("zones && zones[wantedContinent]", adopt)

    def test_switching_tabs_does_not_pile_up_history(self):
        """Five taps must not mean five presses of Back to leave the site -
        and assigning location.hash would also re-enter applyHash through the
        hashchange it fires."""
        self.assertIn("history.replaceState(null, \"\", want)", self.page)
        self.assertNotIn("location.hash =", self.page)

    def test_a_typed_or_pasted_hash_still_changes_the_view(self):
        self.assertIn('window.addEventListener("hashchange", applyHash)', self.route)
