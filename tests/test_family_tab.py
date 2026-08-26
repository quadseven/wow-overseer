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
