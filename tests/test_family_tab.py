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
    """The Twitch view (infra#2892): a focused player plus live thumbnails
    of the five broadcasts that are already running, independent of the
    on-demand watch/POV cards this class's siblings above already cover."""

    @classmethod
    def setUpClass(cls):
        import pathlib
        here = pathlib.Path(__file__).resolve().parent.parent
        cls.page = (here / "index.html").read_text()
        start = cls.page.index("// --- the Family tab (infra#2892)")
        cls.tab = cls.page[start:cls.page.index("loadZones().then(")]

    def test_the_grid_sits_beside_the_cards_in_the_family_section(self):
        self.assertIn('<section id="family">', self.page)
        section = self.page[self.page.index('<section id="family">'):
                             self.page.index("</section>")]
        self.assertIn('id="ftwitch"', section)
        self.assertIn('id="ffocus"', section)
        self.assertIn('id="fthumbs"', section)
        # The grid must render BEFORE the card list in markup order, since
        # it is the primary surface the Twitch-style request asked for.
        self.assertLess(section.index('id="ftwitch"'), section.index('id="fcards"'))

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
        cannot be tapped at all."""
        self.assertIn(".ftile .ffull { display:none; pointer-events:auto;",
                      self.page)
        self.assertIn("#ffocus .ftile .ffull { display:inline-block; }",
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
        grid = self.tab[self.tab.index("// --- the broadcast grid"):
                         self.tab.index("function renderFamily")]
        for name in family.roster():
            self.assertNotIn('"' + name + '"', grid)


class ThumbSizedBroadcastGrid(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import pathlib
        here = pathlib.Path(__file__).resolve().parent.parent
        page = (here / "index.html").read_text()
        cls.css = page[page.index("the Twitch-style broadcast grid"):
                        page.index("</style>")]

    def test_the_focused_player_reserves_its_shape(self):
        focus = self.css[self.css.index("#ffocus {"):]
        self.assertIn("aspect-ratio:16/9", focus[:focus.index("}")])

    def test_the_focused_player_letterboxes_rather_than_crops(self):
        """Same rule the panel's fullscreen view follows: a cropped POV
        hides the hotbars, half of why watching it is worth doing."""
        rule = self.css[self.css.index("#ffocus .ftile video"):]
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
