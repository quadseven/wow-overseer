"""The Family tab's page contract: the rules that cost something to learn.

Asserted against index.html as source, the same way test_stream.py guards the
player - map_server.py imports pymysql and the page has no other test seam.
These are deliberately not "does it render": they are the handful of rules
that were each paid for by a real failure, and that a refactor could quietly
undo while leaving five cards on screen looking perfectly fine.

Ticket: infra#2892.
"""
import re
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
        """A caller may choose a FAMILY. It may never supply a NAME.

        This used to forbid `query.get` outright, which was the simplest way
        to say "no roster from the request" while there was one family. There
        are two now - an Alliance five and a Horde five - so the tab has to be
        able to ask for one of them, and a flat ban on reading the query would
        have meant hard-coding a second roster in the page instead. That is
        the very thing test_the_roster_is_not_retyped_into_the_page forbids.

        So the invariant is enforced where it actually lives: whatever the
        caller sends is matched against the set of families the DATABASE
        reports, and the names handed to _fetch_family come from that lookup.
        A request cannot name a character, which is what this has always been
        about.
        """
        handler = self.server[self.server.index("def _family"):]
        handler = handler[:handler.index("def _thoughts")]
        # the roster reaching the query comes from the lookup, not the request
        self.assertIn("_fetch_family_names(", handler)
        # Every reader here is handed `names`, the list that lookup produced.
        # Matched as a call ARGUMENT rather than as one exact line, because
        # pinning the whole spelling makes this fail on any rewording of the
        # call - which it did, the first time the call gained an argument.
        for reader in ("_fetch_family(", "_fetch_profiles("):
            self.assertIn(reader + "names)", handler,
                          reader + " must be given the looked-up roster")
        self.assertIn("family.build_family(", handler)
        # the only thing taken from the request is the family key
        self.assertIn('query.get("family"', handler)
        self.assertNotIn("query.get(\"name", handler)
        # and nothing from the request is passed to a reader
        self.assertNotIn("_fetch_family(query", handler)
        self.assertNotIn("build_family(query", handler)

        lookup = self.server[self.server.index("def _fetch_family_names"):]
        lookup = lookup[:lookup.index("def _default_family")]
        # an unrecognised key falls back rather than reaching SQL
        self.assertIn("which if which in by_family else", lookup)

    def test_one_tab_per_family_comes_from_the_server(self):
        """The page must not be edited the day a third family exists.

        The families are read off the payload and the buttons built from
        them, so a world with one family still shows a single "Family" tab
        and a world with three shows three - without this file naming any of
        them, which is the same rule that keeps the roster out of the page.
        """
        sync = self.tab[self.tab.index("function syncFamilyTabs"):]
        sync = sync[:sync.index("function markTabs")]
        self.assertIn("payload.families", sync)
        self.assertIn("known.length < 2", sync,
                      "one family must still render the plain Family tab")
        for name in family.roster():
            self.assertNotIn('"' + name + '"', sync,
                             "a family name spelled here is a second answer "
                             "to who the families are")

    def test_the_tabs_are_not_rebuilt_under_a_thumb(self):
        """Rebuilding the row every poll would destroy the button a person is
        tapping. The set is compared first and usually nothing happens."""
        sync = self.tab[self.tab.index("function syncFamilyTabs"):]
        sync = sync[:sync.index("function markTabs")]
        self.assertIn("familiesKnown.join", sync)
        self.assertIn("return", sync)

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
        layout = layout[:layout.index("function renderBroadcasts")]
        self.assertIn("familyCard(name).stream", layout)

    def test_the_stream_is_the_first_thing_on_the_card(self):
        """infra#88: "the twitch view is so tiny". The picture is the product,
        so it is the top of the card and edge to edge, with the name and the
        state in one strip underneath it. A tile appended after the watch
        button would be back to being a video near a name."""
        card = self.tab[self.tab.index("function familyCard"):]
        card = card[:card.index("// --- the broadcasts")]
        order = card[card.index("card.append("):]
        order = order[:order.index(")")]
        self.assertLess(order.index("stream"), order.index("strip"))
        strip = card[card.index("strip.append("):]
        strip = strip[:strip.index(")")]
        self.assertLess(strip.index("head"), strip.index("slots"))
        self.assertLess(strip.index("slots"), strip.index("btn"))

    def test_the_quest_list_is_not_on_the_card_any_more(self):
        """infra#3110 put a quest list inside every card; infra#88 moved
        them to one board under all five feeds. Only the slot count (the
        #73 number, a fact about ONE character) stays with the card."""
        card = self.tab[self.tab.index("function familyCard"):]
        card = card[:card.index("// --- the broadcasts")]
        self.assertNotIn('el("div", "fquests")', card)
        self.assertNotIn("qlist", card)
        self.assertIn('el("div", "fslots")', card)

    def test_tiles_are_built_once_and_moved_not_rebuilt(self):
        """Same rule as familyCard: rebuilding a tile mid-stream would
        replace its <video> and tear down a live PeerConnection to redraw a
        picture that was already fine."""
        self.assertIn(
            "let t = broadcasts.tiles.get(name);\n  if (t) return t;", self.tab)

    def test_laying_out_moves_the_node_rather_than_reconnecting(self):
        layout = self.tab[self.tab.index("function layoutBroadcasts"):]
        layout = layout[:layout.index("function renderBroadcasts")]
        self.assertIn("appendChild", layout)
        self.assertNotIn("makePlayer(", layout)
        self.assertNotIn("player.start(", layout)

    def test_there_is_no_focused_tile_and_no_thumbnail_to_promote(self):
        """infra#88: one big player and four 170px thumbnails was the
        "so tiny" the operator complained about. Every tile is now the full
        width of its column, so there is nothing to promote and no tap that
        does it - a tap on a picture belongs to the native controls."""
        self.assertNotIn("function promoteBroadcast", self.tab)
        self.assertNotIn("broadcasts.focus", self.tab)
        self.assertNotIn('"focused"', self.tab)
        tile = self.tab[self.tab.index("function broadcastTile"):]
        tile = tile[:tile.index("function layoutBroadcasts")]
        self.assertNotIn("tile.onclick", tile)

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

    def test_the_fullscreen_tap_stays_on_the_button(self):
        """The overlay is pointer-events:none and the video underneath has
        native controls; the button's tap must not fall through to them."""
        tile = self.tab[self.tab.index("function broadcastTile"):]
        tile = tile[:tile.index("function layoutBroadcasts")]
        onclick = tile[tile.index("full.onclick"):]
        self.assertIn("e.stopPropagation();",
                      onclick[:onclick.index("goFullscreen(")])

    def test_fullscreen_is_offered_on_every_tile(self):
        """Every tile is a real player now (infra#88), so every tile gets the
        button. The overlay is pointer-events:none, so the button must opt
        back in for itself or it cannot be tapped at all."""
        rule = self.page[self.page.index(".ftile .ffull {"):]
        rule = rule[:rule.index("}")]
        self.assertIn("display:inline-block", rule)
        self.assertIn("pointer-events:auto", rule)
        self.assertNotIn(".ftile.focused", self.page)

    def test_a_refused_fullscreen_is_shown_to_the_person(self):
        """goFullscreen insists a refusal is said out loud, which is only true
        if the caller renders the sentence it is handed."""
        tile = self.tab[self.tab.index("function broadcastTile"):]
        tile = tile[:tile.index("function layoutBroadcasts")]
        self.assertIn("fsnote.textContent = text;", tile)


    def test_every_tile_gets_native_video_controls(self):
        """The scripted fullscreen button is not what a thumb reaches for. iOS
        Safari gives a <video> its own fullscreen affordance through the native
        control bar, which is the control people already know from YouTube.
        With no thumbnails left to protect from a control bar (infra#88),
        every tile carries it."""
        tile = self.tab[self.tab.index("function broadcastTile"):]
        tile = tile[:tile.index("function layoutBroadcasts")]
        self.assertIn("video.controls = true;", tile)

    def test_the_overlay_stays_out_of_the_control_bar(self):
        """Native controls own the bottom edge of a video whenever they are
        showing, so the name, the health bar and the zone all sit at the top
        of the overlay where the controls never are."""
        rule = self.page[self.page.index(".ftile .fov {"):]
        rule = rule[:rule.index("}")]
        self.assertNotIn("justify-content:space-between", rule)
        self.assertIn("pointer-events:none", rule)

    def test_the_name_on_the_picture_is_in_its_class_colour(self):
        render = self.tab[self.tab.index("function renderBroadcasts"):]
        render = render[:render.index("function startBroadcasts")]
        self.assertIn("m.class_colour", render)

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
        cls.page = (here / "index.html").read_text()
        cls.css = cls.page[cls.page.index("the broadcast tile, inside its own"):
                           cls.page.index("</style>")]

    def test_the_empty_slot_reserves_the_shape_not_the_tile(self):
        """makePlayer owns the tile's `display` - none until start(), none
        again after stop() - so a reservation hung on the tile is worth
        nothing in the exact window it is needed. The card must hold the
        space while there is no picture in it, or the strip underneath gets
        shoved down half a second later under a thumb already reaching for
        it. FULL WIDTH (infra#88): 170px was the "so tiny"."""
        slot = self.css[self.css.index(".fstream {"):]
        slot = slot[:slot.index("}")]
        self.assertIn("aspect-ratio:16/9", slot)
        self.assertIn("width:100%", slot)
        self.assertNotIn("170px", self.css)

    def test_every_player_letterboxes_rather_than_crops(self):
        """Same rule the panel's fullscreen view follows: a cropped POV
        hides the hotbars, half of why watching it is worth doing. It used
        to apply to the focused tile only; every tile is that tile now."""
        rule = self.css[self.css.index(".ftile video {"):]
        self.assertIn("object-fit:contain", rule[:rule.index("}")])

    def test_the_feeds_fill_the_width_and_wrap_to_five(self):
        """One column on a phone, then two, then three (3+2), then all five
        in a row. Explicit stops, so the shape is the same on every visit."""
        page = self.page
        grid = page[page.index("#ffeeds {"):page.index(".fcard {")]
        self.assertIn("grid-template-columns:1fr", grid)
        self.assertIn("repeat(2,minmax(0,1fr))", grid)
        self.assertIn("repeat(3,minmax(0,1fr))", grid)
        self.assertIn("repeat(5,minmax(0,1fr))", grid)

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


class SwitchingFamilyDropsTheOtherFamilysTiles(unittest.TestCase):
    """The second family's tab opened with the FIRST family's head on top.

    The page keeps three things per character, all keyed by name alone: the live
    stream tile, the wall tile and the family card. Each was only ever added to.
    With one family the names never changed so nothing showed; with two, a tab
    switch rendered the new family's five and left the previous five where they
    were - first, since they were created first. The operator opened the Horde
    family's tab to watch its head and found the Alliance head paused at 00:00
    above it.
    """

    @classmethod
    def setUpClass(cls):
        import pathlib
        here = pathlib.Path(__file__).resolve().parent.parent
        cls.page = (here / "index.html").read_text(encoding="utf-8")
        start = cls.page.index("function retainOnlyThese(")
        cls.prune = cls.page[start:cls.page.index("function renderFamily(")]
        cls.render = cls.page[cls.page.index("function renderFamily("):][:600]

    def test_all_three_per_character_stores_are_pruned(self):
        for store in ("broadcasts.tiles", "wall.slots", "fam.cards"):
            self.assertIn("of " + store, self.prune, store + " is never pruned")
            self.assertIn(store + ".delete(name)", self.prune)

    def test_a_removed_stream_is_stopped_not_merely_detached(self):
        """A tile owns a live PeerConnection to the encoder. Removing the node
        with the player still running leaves a stream nobody can see being
        pulled across the tailnet."""
        self.assertIn("t.player.stop()", self.prune)
        self.assertIn("c.player.stop()", self.prune)

    def test_the_nodes_leave_the_page(self):
        for node in ("t.tile.remove()", "s.slot.remove()", "c.card.remove()"):
            self.assertIn(node, self.prune)

    def test_a_character_in_the_new_payload_is_left_alone(self):
        """Pruning must be by absence. Rebuilding a tile that is staying would
        drop and re-establish its connection for a change nobody asked to pay
        for."""
        self.assertIn("if (keep.has(name)) continue;", self.prune)

    def test_it_runs_before_anything_is_drawn(self):
        """Pruning after the render would draw the new family beside the old
        one for a frame, and the old one is what a thumbnail catches."""
        self.assertIn("retainOnlyThese(", self.render)
        self.assertLess(self.render.index("retainOnlyThese("),
                        self.render.index("renderBroadcasts(p)"))


class OnlyStreamedCharactersHaveAVideo(unittest.TestCase):
    """The page half: nobody without a stream gets a tile, a wall slot or an open
    video box. See the server-side class of the same name in test_family.py."""

    @classmethod
    def setUpClass(cls):
        import pathlib
        here = pathlib.Path(__file__).resolve().parent.parent
        cls.page = (here / "index.html").read_text(encoding="utf-8")
        start = cls.page.index("function renderBroadcasts(")
        cls.broadcasts = cls.page[start:cls.page.index("function retainOnlyThese(")
                                  if cls.page.index("function retainOnlyThese(") > start
                                  else start + 3000]
        cls.wall = cls.page[cls.page.index("function renderWall(p)"):][:3000]

    def test_no_stream_tile_is_built_for_a_member_without_a_url(self):
        body = self.broadcasts[:900]
        self.assertIn("if (!m.broadcast_url) continue;", body)
        self.assertLess(body.index("if (!m.broadcast_url) continue;"),
                        body.index("broadcastTile(m.name)"))

    def test_the_wall_draws_only_the_tiles_that_can_play(self):
        self.assertIn("w.tiles.filter((t) => t.playable)", self.wall)
        self.assertIn("for (const t of shown) {", self.wall)
        self.assertNotIn("for (const t of w.tiles) {", self.wall)

    def test_an_empty_video_box_on_a_card_closes(self):
        self.assertIn(".fstream:empty { display:none; }", self.page)

    def test_a_wall_of_one_or_two_is_not_laid_out_as_five_up(self):
        for count in ("1", "2"):
            self.assertIn('#wall.m-five-up[data-count="%s"]' % count, self.page)
        self.assertIn("wallEl.dataset.count = String(shown.length);", self.wall)

    def test_the_narrow_layout_is_left_alone(self):
        """The few-tiles grid is wide-screens only. On a phone the wall is already
        one column, and an attribute selector outranks the rule that makes it so."""
        start = self.page.index('#wall.m-five-up[data-count="1"]')
        before = self.page[:start]
        self.assertIn("@media (min-width:641px) {", before[before.rindex("@media"):])


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


class TheQuestBoard(unittest.TestCase):
    """infra#88: one shared quest board under all five feeds, in place of
    the five per-character lists infra#3110 put inside the cards.

    The judgements - who is on it, helping, done, leading; how the rows
    sort; where the fold is - all live in questlog.py, with their own suite.
    These are the page rules: the ones a refactor could undo while leaving a
    perfectly plausible list on screen."""

    @classmethod
    def setUpClass(cls):
        import pathlib
        here = pathlib.Path(__file__).resolve().parent.parent
        cls.page = (here / "index.html").read_text()
        cls.server = (here / "map_server.py").read_text()
        start = cls.page.index("// --- the Family tab (infra#2892)")
        cls.tab = cls.page[start:cls.page.index("loadZones().then(")]
        cls.block = cls.tab[cls.tab.index("// --- the quest board (infra#3110"):
                             cls.tab.index("// POV AND ONLY POV")]
        # The block without its opening essay, for the assertions that are
        # about what the CODE says rather than what the comments explain.
        cls.code = cls.block[cls.block.index("const fquesthead"):]

    def test_the_board_is_one_list_under_all_the_feeds(self):
        """Not five lists in five cards. The whole point of one list is that
        "who else is on this" is a row you look at, not five titles you
        match up by eye."""
        section = self.page[self.page.index('<section id="family">'):
                             self.page.index("</section>")]
        self.assertLess(section.index('id="ffeeds"'), section.index('id="fboard"'))
        self.assertIn('id="fquesthead"', section)
        self.assertIn('id="fqlist"', section)
        self.assertNotIn('el("div", "fquests")', self.tab)

    def test_one_row_per_quest_with_the_people_on_the_right(self):
        row = self.code[self.code.index("function boardRow"):]
        row = row[:row.index("function renderBoard")]
        self.assertIn("r.people", row)
        self.assertIn('el("div", "qbwho")', row)
        # main first, people second: the portraits are the right-hand column.
        self.assertIn("row.append(main, who)", row)

    def test_every_role_the_module_names_is_drawn(self):
        """questlog.HAND_IN/ON/HELPING/DONE are the vocabulary; the page must
        have a word and a ring for each, or a role the server decided would
        render as nothing."""
        import questlog
        words = self.code[self.code.index("const ROLE_WORDS"):]
        words = words[:words.index("}")]
        for role in (questlog.HAND_IN, questlog.ON, questlog.HELPING, questlog.DONE):
            self.assertIn(role + ":", words)
            self.assertIn(".pt." + role, self.page)

    def test_done_is_dimmed_so_everyone_else_did_it_can_be_seen(self):
        rule = self.page[self.page.index(".pt.done {"):]
        self.assertIn("opacity", rule[:rule.index("}")])

    def test_the_leader_wears_a_drawn_crown(self):
        """Drawn, not typed: the page is ASCII-only, and a glyph that one
        phone renders and another does not is not a marker."""
        portrait = self.code[self.code.index("function portrait"):]
        portrait = portrait[:portrait.index("function boardRow")]
        self.assertIn("if (p.leader) box.appendChild(crown())", portrait)
        self.assertIn("function crown()", self.code)
        self.assertIn('setAttribute("d"', self.code[self.code.index("function crown()"):])

    def test_the_portrait_is_the_armory_silhouette_in_the_class_colour(self):
        """One face everywhere: the Armory already draws a class-coloured
        silhouette, and a second drawing of the same person is a second
        opinion about what they look like."""
        portrait = self.code[self.code.index("function portrait"):]
        portrait = portrait[:portrait.index("function boardRow")]
        self.assertIn("silhouette(p.class_colour)", portrait)

    def test_the_slot_count_stays_on_the_card_and_is_said_even_when_fine(self):
        """mod-overseer#73 hid for a month because nothing counted the slots.
        A number that only appears once it is already bad is a number nobody
        has learned to read by the time it matters - and it is a fact about
        one character, so it stays beside that character's name."""
        head = self.block[self.block.index("function questHeadline"):]
        head = head[:head.index("function boardSignature")]
        first = head.index('m.used + " of " + m.slots')
        # Unconditional: before any of the `if` lines that add the rest.
        self.assertLess(first, head.index("if (m.ready)"))
        render = self.code[self.code.index("function renderQuests"):]
        self.assertIn("c.slots.textContent = questHeadline(m)", render)

    def test_the_page_does_not_decide_what_a_full_log_or_a_fold_is(self):
        """questlog.py owns the cap, how near it counts as full, and how many
        rows show before the fold. A 25 or a 12 typed into this file is a
        second answer that can disagree with the first, silently."""
        self.assertNotIn("25", self.code)
        self.assertNotIn("slice(0, 1", self.code)
        self.assertIn("m.slots", self.code)
        self.assertIn("m.full", self.code)
        self.assertIn("b.preview", self.code)

    def test_the_board_is_the_only_thing_rebuilt(self):
        """replaceChildren anywhere near a card is how a live <video> gets
        thrown away mid-stream. It is allowed here and ONLY here, because
        this list is text the server just recomputed."""
        self.assertEqual(self.tab.count(".replaceChildren("), 1)
        render = self.block[self.block.index("function renderBoard"):]
        render = render[:render.index("function renderQuests")]
        self.assertIn("fqlist.replaceChildren", render)

    def test_a_poll_that_changed_nothing_leaves_the_list_alone(self):
        """Thirty seconds apart, most polls are identical. Rebuilding anyway
        would throw away a half-read list under somebody's thumb for no
        change at all."""
        render = self.block[self.block.index("function renderBoard"):]
        render = render[:render.index("function renderQuests")]
        self.assertIn("board.sig === sig", render)
        self.assertLess(render.index("return;"), render.index("replaceChildren"))

    def test_a_long_board_folds_and_says_how_many_it_is_hiding(self):
        render = self.code[self.code.index("function renderBoard"):]
        render = render[:render.index("function renderQuests")]
        self.assertIn("b.rows.slice(0, b.preview)", render)
        self.assertIn('"show all " + b.rows.length', render)

    def test_expanding_the_board_is_not_swallowed_by_the_no_change_guard(self):
        """Nothing about the DATA changes when somebody taps "show all",
        which is exactly what that guard skips on - so the fold state is
        part of the signature."""
        render = self.code[self.code.index("function renderBoard"):]
        render = render[:render.index("function renderQuests")]
        self.assertIn('(board.open ? "|open" : "")', render)

    def test_the_server_reads_turn_ins_and_the_party_for_the_board(self):
        """DONE needs character_queststatus_rewarded per quest, and HELPING
        needs the snapshot's group_leader; a board built without either
        would draw every row as "on it" and nothing else."""
        fetch = self.server[self.server.index("def _fetch_questlog"):]
        fetch = fetch[:fetch.index("def _ensure_stream_store")]
        self.assertIn("character_queststatus_rewarded", fetch)
        self.assertIn("group_leader", fetch)
        self.assertIn('"done_rows": done_rows', fetch)
        self.assertIn('"party_rows": party_rows', fetch)

    def test_a_failed_poll_keeps_the_board_it_has(self):
        """An empty board means "they have nothing to do", which is the
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
        """The fallback, which is the half of routing that gets a stale
        bookmark to somewhere useful.

        The ordering assertion this used to make (MAP_VIEW named before
        ARMORY_VIEW inside applyHash) was really a description of the old
        if-ladder, and it broke when that ladder became a list, which it had
        to, because the ladder had just swallowed #watch. What it was actually
        protecting is below: the map still returns first, and anything the
        table does not name still lands on the family."""
        fn = self.route[self.route.index("function applyHash"):]
        fn = fn[:fn.index('window.addEventListener("hashchange"')]
        # The map returns before the table is consulted, because its hash
        # carries which continent and so needs more than a name.
        self.assertLess(fn.index("if (name === MAP_VIEW)"),
                        fn.index("HASH_VIEWS.indexOf(name)"))
        self.assertIn("HASH_VIEWS.indexOf(name) >= 0 ? name : FAMILY_VIEW", fn)

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


class TheNeedsTheHandoversAndTheBonds(unittest.TestCase):
    """infra#2597 on the Family view. The card answered "is my family alive"
    and nothing under it, and alive has never been the interesting question:
    they have spent whole sessions alive, standing still, with full bags, gear
    at a quarter durability, and a stack of linen four of them keep trying to
    hand to the fifth whose bags are full. Every one of those facts already
    existed in a module and none of them was on a surface.

    THE RULES THAT COST SOMETHING. These are not "does it render" - they are
    the handful that a refactor could undo while leaving three perfectly
    plausible panels on screen. The load-bearing one is
    test_the_page_decides_nothing: the moment a threshold or a status word is
    spelled in this file, the page has an opinion about the family that can
    disagree with the module, and both will render."""

    @classmethod
    def setUpClass(cls):
        import pathlib
        here = pathlib.Path(__file__).resolve().parent.parent
        cls.page = (here / "index.html").read_text(encoding="utf-8")
        cls.server = (here / "map_server.py").read_text(encoding="utf-8")
        cls.dockerfile = (here / "Dockerfile").read_text(encoding="utf-8")
        start = cls.page.index("// --- the Family tab (infra#2892)")
        cls.tab = cls.page[start:cls.page.index("loadZones().then(")]
        cls.block = cls.tab[
            cls.tab.index("// --- what they need, what wants to move"):
            cls.tab.index("// --- the quest board (infra#3110")]
        cls.section = cls.page[cls.page.index('<section id="family">'):
                               cls.page.index("</section>")]
        cls.css = cls.page[cls.page.index("--- the needs, the handovers"):
                           cls.page.index("--- THE WATCH WALL")]

    # --- the page decides nothing -----------------------------------------

    def test_the_page_decides_nothing(self):
        """THE WHOLE POINT. Not one status word, threshold or verdict is
        spelled in this block: every one arrives on the payload from needs.py,
        materials.py and bonds.py. A page that worked out for itself that 39%
        durability is red would be a second opinion about the family, and it
        would render a perfectly plausible bar while being wrong."""
        import bonds
        import materials
        for word in (materials.MOVING, "GAVE UP AFTER", bonds.STOPPED,
                     bonds.COUNTING, bonds.EXEMPT, bonds.ALWAYS):
            self.assertNotIn(word, self.block, word)

    def test_no_threshold_is_compared_in_javascript(self):
        """A comparison against a number IS a threshold, whatever it is called.
        There is not one in this block, and this fails the moment somebody
        adds the first - which is the edit that starts the drift."""
        self.assertNotIn(" < ", self.block)
        self.assertNotIn(" > ", self.block)
        self.assertNotIn(" <= ", self.block)
        self.assertNotIn(" >= ", self.block)

    def test_no_sentence_is_composed_in_a_template(self):
        """Every line of prose on these three panels is a field. Joining a name
        to a verb here would be writing dialogue in a renderer."""
        for field in (".said", ".note", ".title", ".headline", ".rule",
                      ".refusal_line", ".progress", ".pair"):
            self.assertIn(field, self.block, field)
        self.assertNotIn('" + row.holder + " to " + row.taker', self.block)

    def test_the_worst_line_takes_its_colour_from_the_module(self):
        """Rust when it is a warning, amber when it is a caution, muted when
        there is nothing to say - and which of those it is, is a judgement."""
        self.assertIn('"fworst s-" + m.worst.state', self.block)
        self.assertIn(".fworst.s-warn { color:var(--warn-text); }", self.page)
        self.assertIn(".fworst.s-caution { color:var(--caution-text); }", self.page)

    def test_the_label_goes_ink_when_it_is_the_problem(self):
        """The reading trick this panel is made of: four grey labels and one
        black one answers "what is wrong with him" before it is asked. Which
        one is the problem is needs.py's decision, carried as a flag."""
        self.assertIn("b.problem", self.block)
        rule = self.css[self.css.index(".fneed.problem .fneedl {"):]
        self.assertIn("color:var(--on-card)", rule[:rule.index("}")])
        rule = self.css[self.css.index(".fneedl {"):]
        self.assertIn("color:var(--on-card-dim)", rule[:rule.index("}")])

    # --- nothing near a card is ever rebuilt -------------------------------

    def test_the_new_rows_are_built_once_and_moved_rather_than_rebuilt(self):
        """A card holds a live <video>. There is exactly ONE replaceChildren on
        this page - the quest board's, which holds no player - and these three
        panels do not add a second: rows are keyed by the id the module sends
        and re-ordered with appendChild, which MOVES a node."""
        self.assertEqual(self.tab.count(".replaceChildren("), 1)
        self.assertNotIn(".replaceChildren(", self.block)
        self.assertNotIn("innerHTML", self.block)
        for builder, reuse in (("function needBar", "if (n) return n;"),
                               ("function moveRow", "if (r) return r;"),
                               ("function bondRow", "if (r) return r;")):
            fn = self.block[self.block.index(builder):]
            self.assertIn(reuse, fn[:400],
                          builder + " rebuilds its row instead of reusing it")

    def test_a_motive_that_stops_applying_is_hidden_and_not_removed(self):
        """A character wearing nothing that can break has no repair question,
        and gets one again the moment they put a helmet on. A node kept is a
        node that never has to be rebuilt under somebody's thumb."""
        render = self.block[self.block.index("function renderNeeds"):]
        render = render[:render.index("function renderMoves")]
        self.assertIn("n.row.hidden = true", render)
        self.assertIn("c.needbox.appendChild(n.row)", render)

    def test_a_bar_with_no_percentage_draws_no_bar(self):
        """None is not zero. "Nothing that can break" drawn as an empty bar
        reads as gear at zero durability, which is the opposite claim."""
        self.assertIn('b.pct === null ? "none" : ""', self.block)
        self.assertIn('row.pct === null ? "none" : ""', self.block)

    # --- what is on the page ----------------------------------------------

    def test_the_three_blocks_sit_under_the_board_in_the_order_they_are_read(self):
        """Who they are, what they are doing, what they need moved, and who
        will still turn up. Each one is the context for the next."""
        self.assertLess(self.section.index('id="fboard"'),
                        self.section.index('id="fmove"'))
        self.assertLess(self.section.index('id="fmove"'),
                        self.section.index('id="fbonds"'))
        for node in ("fmovehead", "fmovelist", "fmoverule",
                     "fbondhead", "fbondlist", "fbondrule"):
            self.assertIn('id="%s"' % node, self.section, node)

    def test_every_block_wears_the_same_three_part_rule(self):
        """A mono index, a 2px line and the label right-aligned in muted, four
        times. One of the four shouting in an <h2> while the others whisper is
        what this replaced."""
        self.assertEqual(self.section.count('class="fsec"'), 4)
        for index in ("01", "02", "03", "04"):
            self.assertIn('<span class="fsecn">%s</span>' % index, self.section)
        self.assertEqual(self.section.count('class="fsecline"'), 4)
        rule = self.page[self.page.index(".fsecline {"):]
        self.assertIn("height:2px", rule[:rule.index("}")])

    def test_the_ink_line_is_themed_rather_than_literally_ink(self):
        """--ink is a fixed near-black and this line sits on the page ground,
        not on a card. A literal --ink would be an invisible rule for anybody
        reading in the dark."""
        rule = self.page[self.page.index(".fsecline {"):]
        rule = rule[:rule.index("}")]
        self.assertIn("background:var(--shell-text)", rule)
        self.assertNotIn("var(--ink)", rule)

    def test_the_glyph_tile_is_a_mark_and_not_a_photo_slot(self):
        """64px cannot hold a picture plus any chrome round it, and the only
        likeness of these characters on the page is the live broadcast a
        couple of centimetres above. So it is initials over a two-letter race
        mark, and both come off the payload - working out what to call a race
        is a decision, and family.race_mark owns it."""
        card = self.tab[self.tab.index("function familyCard"):]
        card = card[:card.index("// --- the broadcasts")]
        self.assertIn('el("div", "fglyph")', card)
        self.assertNotIn('createElement("img")', card)
        self.assertNotIn("<img", card)
        self.assertIn("c.ginit.textContent = m.initials", self.tab)
        self.assertIn("c.gmark.textContent = m.mark", self.tab)

    def test_the_glyph_takes_its_colour_from_the_cards_state_and_not_from_js(self):
        """"How is he" is decided once, by family._condition, and lands as the
        card's class. A second assignment in JavaScript is how a priest came to
        be painted invisible on a white card."""
        self.assertNotIn("ginit.style.color", self.page)
        for state in ("c-hurt", "c-dead", "c-gone"):
            self.assertIn(".fcard.%s .fginit" % state, self.page)

    def test_the_quotation_is_speech_and_never_an_inner_thought(self):
        """overseer_thought holds the family's inner life as well as its
        speech. Quoting a reflection on a card would put words in somebody's
        mouth; needs.SPOKEN_SOURCES is where that line is drawn."""
        import needs
        self.assertIn('el("div", "fsaidl", "said out loud")', self.tab)
        self.assertIn("c.said.textContent = m.said.text", self.block)
        self.assertIn('m.said.spoken ? "" : " quiet"', self.block)
        # And the sieve stays in the module. A source name spelled in this file
        # is that decision made a second time, in the one place it cannot be
        # tested - and the failure mode is a card quoting a thought nobody
        # said, which reads exactly like a card quoting speech.
        self.assertTrue(needs.SPOKEN_SOURCES)
        for source in tuple(needs.SPOKEN_SOURCES) + ("reflection", "goal",
                                                     "command", "event"):
            self.assertNotIn('"%s"' % source, self.block, source)

    def test_the_card_carries_the_needs_the_worst_line_and_the_bond(self):
        """In that order, and above the watch button: what is wrong with them
        is read before deciding whether to go and look."""
        card = self.tab[self.tab.index("function familyCard"):]
        card = card[:card.index("// --- the broadcasts")]
        strip = card[card.index("strip.append("):]
        strip = strip[:strip.index(")")]
        for node in ("saidbox", "needbox", "worst", "bond"):
            self.assertIn(node, strip, node)
        self.assertLess(strip.index("needbox"), strip.index("worst"))
        self.assertLess(strip.index("bond"), strip.index("btn"))

    def test_the_two_lists_use_the_grid_the_handoff_draws(self):
        """auto-fit at 290px, unlike the feed grid above it. These hold text,
        so there is no <video> to protect from a column count that changes as
        a window is dragged - which is the only reason that grid has explicit
        stops.

        THE 290 IS WRAPPED IN min() SINCE infra#3482, and that is not a
        loosening of this assertion. auto-fit's floor is a hard one: on a
        320px screen this tab's content box is 292px, the track held out for
        290 plus its gap, and the two cards stood wider than the tab that held
        them - which mobile Safari answers by zooming the WHOLE PAGE out to
        fit. `min(100%, 290px)` asks for the identical 290 wherever 290 exists
        and takes the full width where it does not, so what the handoff draws
        is unchanged on every screen wide enough to draw it."""
        rule = self.css[self.css.index("#fmovelist, #fbondlist {"):]
        rule = rule[:rule.index("}")]
        self.assertIn("repeat(auto-fit,minmax(min(100%,290px),1fr))", rule)
        self.assertIn("gap:14px", rule)

    def test_no_track_in_this_block_has_a_bare_pixel_floor(self):
        """The general form of the rule above, and the one that catches the
        NEXT one. auto-fit's minimum is a hard floor: a track that asks for
        290px keeps asking on a 320px screen, and the row it is in ends up
        wider than the page. That does not show up as a scrollbar on the
        device this page is read on - mobile Safari zooms the whole document
        out until it fits, so the symptom is every word on the page rendering
        at half size, which is a bug nobody thinks to blame on a grid."""
        bare = re.findall(r"minmax\(\s*(\d+)px", self.css)
        self.assertEqual(bare, [], "bare px track floors in this block: %s; "
                                   "wrap each in min(100%%, Npx)" % bare)

    # --- the poll ----------------------------------------------------------

    def test_it_rides_the_slow_cadence_and_still_reads_on_arrival(self):
        """Bags, durability, money, give rows and thoughts are all SAVED state
        written on the core's own timer, so a 5s poll would re-fetch an
        identical payload six times per actual change. Entering the tab reads
        immediately, or these panels are blank for half a minute on arrival."""
        self.assertIn("setInterval(pollNeeds, 30000)", self.tab)
        show = self.tab[self.tab.index("function showView"):]
        show = show[:show.index("setInterval(pollFamily")]
        self.assertIn("pollNeeds();", show[show.index("if (isFam)"):])

    def test_a_failed_poll_keeps_the_panels_it_has(self):
        """An empty needs panel reads as "there is nothing wrong with any of
        them", which is the one claim this view exists to be able to disprove."""
        poll = self.block[self.block.index("async function pollNeeds"):]
        self.assertIn("unreachable", poll)
        self.assertNotIn("replaceChildren", poll)

    # --- the endpoint ------------------------------------------------------

    def test_the_endpoint_is_wired_into_the_route_table(self):
        """do_GET is a lookup and nothing else, so a handler that is never
        named in the table is a 404 with a docstring."""
        self.assertIn('"/api/needs": _needs,', self.server)
        self.assertIn('fetch(u("/api/needs"))', self.tab)

    def test_the_endpoint_takes_no_roster_from_the_caller(self):
        handler = self.server[self.server.index("def _needs"):]
        handler = handler[:handler.index("def _agenda")]
        self.assertIn("needs.build_needs(**_fetch_needs())", handler)
        self.assertNotIn("query.get", handler)
        self.assertIn("self._send(503", handler)

    def test_the_handler_sits_outside_every_other_suites_window(self):
        """The Armory suite reads `def _armory` to `def _thoughts` as its own
        contract; the Wealth handler is below _thoughts for exactly that
        reason and so is this one."""
        self.assertGreater(self.server.index("def _needs"),
                           self.server.index("def _thoughts"))

    def test_the_fetch_sits_outside_the_wealth_suites_window(self):
        """That window is read as the Wealth view's SQL, and it asserts the
        inventory query is NOT bounded by slot. The durability read here IS
        bounded by slot, because a paper doll is exactly what it wants."""
        self.assertGreater(self.server.index("def _fetch_needs"),
                           self.server.index("# Everything a tooltip draws"))
        self.assertLess(self.server.index("def _fetch_needs"),
                        self.server.index("def _ensure_stream_store"))

    def test_the_window_is_the_modules_number_and_not_one_typed_into_sql(self):
        """A window is a decision about what counts as recent, and a 24 in a
        query nothing tests is a decision nobody can find."""
        fetch = self.server[self.server.index("def _fetch_needs"):]
        fetch = fetch[:fetch.index("def _ensure_stream_store")]
        # BOTH reads, counted rather than merely present. Two queries take the
        # window and one of them going back to a literal would leave the other
        # holding the name - the assertion would pass and the two reads would
        # be looking at different amounts of history.
        self.assertEqual(fetch.count("needs.HISTORY_HOURS"), 2)
        self.assertIn("needs.HISTORY_MAX", fetch)

    def test_the_two_reads_that_can_be_missing_are_guarded(self):
        """A world whose image predates the give machinery has refused nothing.
        infra#3172 cost a whole tab on production because one read of a table
        the module creates was not guarded."""
        fetch = self.server[self.server.index("def _fetch_needs"):]
        fetch = fetch[:fetch.index("def _ensure_stream_store")]
        self.assertEqual(fetch.count("1054, 1146"), 2)
        self.assertIn("give_rows = []", fetch)
        self.assertIn("thought_rows = []", fetch)

    def test_the_inventory_read_is_the_same_columns_the_bag_view_uses(self):
        """Two views counting the same bags off two column lists is two
        answers to how full a bag is, and one of them drifts."""
        fetch = self.server[self.server.index("def _fetch_needs"):]
        fetch = fetch[:fetch.index("def _ensure_stream_store")]
        self.assertIn("_WEALTH_ITEM_COLUMNS", fetch)

    def test_the_gear_read_is_bounded_by_the_module_and_not_by_a_typed_19(self):
        fetch = self.server[self.server.index("def _fetch_needs"):]
        fetch = fetch[:fetch.index("def _ensure_stream_store")]
        self.assertIn("len(armory.EQUIPPED_SLOTS)", fetch)
        self.assertIn("it.MaxDurability AS max_durability", fetch)

    def test_the_skills_are_sieved_in_python_and_not_in_sql(self):
        """character_skills also holds languages, Defence and every weapon
        skill. Which of them is a profession is needs.held_skills' decision,
        and an IN list of ids here would be that decision in SQL nothing
        tests."""
        fetch = self.server[self.server.index("def _fetch_needs"):]
        fetch = fetch[:fetch.index("def _ensure_stream_store")]
        self.assertIn("JOIN character_skills k ON k.guid = c.guid", fetch)
        self.assertNotIn("k.skill IN", fetch)

    def test_the_module_ships_in_the_image(self):
        """The build's shared-dir copy takes top-level files only and the
        Dockerfile names them explicitly, so a new module is one forgotten line
        away from a pod that crashes at start, long after CI went green."""
        self.assertIn("needs.py", self.dockerfile)
