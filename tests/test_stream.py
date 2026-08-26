"""The stream lifecycle: who is watched, and when the client dies.

infra#2663's hardest acceptance criterion is not the video - it is "without
leaving a WoW client running idle when nobody is watching". A client held for
nobody costs a GPU and 300MB and is INVISIBLE, which is this project's
favourite kind of bug. Every test below is about that sentence.
"""
import unittest

import stream


class Staleness(unittest.TestCase):
    """Silence is the signal. Everything that can stop a viewer watching -
    closed tab, crashed browser, slept laptop, dropped tailnet - stops the
    heartbeat, so all of them end the stream."""

    def _row(self, **kw):
        base = {"state": "live", "character": "Grug", "last_seen_seconds": 1000.0}
        base.update(kw)
        return base

    def test_a_fresh_heartbeat_keeps_the_stream(self):
        self.assertFalse(stream.is_stale(self._row(), 1005.0))

    def test_silence_past_the_timeout_ends_it(self):
        self.assertTrue(
            stream.is_stale(self._row(), 1000.0 + stream.STALE_AFTER_SECONDS + 1))

    def test_the_timeout_is_bounded_in_absolute_seconds(self):
        """Pinned to REAL numbers, not to the constant itself. The first cut
        wrote every staleness assertion as `STALE_AFTER_SECONDS + 1`, so the
        whole class moved with the constant - setting it to 999999 kept the
        suite green, which a mutation run caught. A test derived entirely from
        the value it is checking cannot check it."""
        self.assertLessEqual(stream.STALE_AFTER_SECONDS, 120,
                             "a client held this long for nobody is the bug "
                             "infra#2663 exists to prevent")
        self.assertGreaterEqual(stream.STALE_AFTER_SECONDS, 30,
                                "too short and a throttled background tab "
                                "kills a stream somebody is watching")

    def test_two_minutes_of_silence_is_stale_at_any_setting(self):
        """Absolute, not relative: whatever the constant says, two minutes of
        no viewer must end the stream."""
        self.assertTrue(stream.is_stale(self._row(), 1000.0 + 120))

    def test_five_seconds_of_silence_is_never_stale(self):
        self.assertFalse(stream.is_stale(self._row(), 1005.0))

    def test_the_timeout_survives_a_dropped_heartbeat(self):
        """One lost request must not kill a stream somebody is watching, so
        the timeout is a multiple of the send cadence."""
        self.assertGreaterEqual(
            stream.STALE_AFTER_SECONDS, 3 * stream.HEARTBEAT_SECONDS)

    def test_an_ended_row_is_never_stale(self):
        """`ended` rows are history. History does not need tearing down, and
        a sweep that kept 'finding' them would act on the same row forever."""
        for state in ("ended", "stopping"):
            self.assertFalse(
                stream.is_stale(self._row(state=state), 9_999_999.0), state)

    def test_a_request_nobody_picked_up_goes_stale_on_its_own_clock(self):
        """No heartbeat yet, because no viewer has confirmed anything - so it
        is judged from when it was asked for. Otherwise a request the agent
        never takes sits in `requested` forever."""
        row = {"state": "requested", "character": "Grug",
               "requested_seconds": 500.0}
        self.assertFalse(stream.is_stale(row, 505.0))
        self.assertTrue(stream.is_stale(row, 500.0 + stream.STALE_AFTER_SECONDS + 1))

    def test_a_row_with_no_clock_at_all_is_not_guessed_at(self):
        """Refusing to act on absent data is the whole lesson of this epic:
        five times in one day something reported nothing and it was read as a
        measurement. A row with no timestamps has not been measured."""
        self.assertFalse(
            stream.is_stale({"state": "live", "character": "Grug"}, 9_999_999.0))


class OutcomesReachTheScreen(unittest.TestCase):
    """Every way a watch ends carries a reason. A reason nobody renders is
    the same as no reason - the buttons just come back and the viewer is left
    guessing, which is the bug Evan hit the first time he pressed one."""

    def _row(self, **kw):
        base = {"state": "ended", "character": "Og",
                "detail": "cam needs a GM account that is not family",
                "last_seen_seconds": 1000.0}
        base.update(kw)
        return base

    def test_a_recent_refusal_is_reported_with_its_reason(self):
        got = stream.outcome_of(self._row(), 1005.0)
        self.assertIsNotNone(got)
        self.assertIn("GM account", got["detail"])
        self.assertEqual("ended", got["state"])

    def test_the_sweeps_own_teardown_is_reported_too(self):
        got = stream.outcome_of(
            self._row(state="stopping", detail="nobody was watching"), 1005.0)
        self.assertEqual("nobody was watching", got["detail"])

    def test_a_running_watch_has_no_outcome_yet(self):
        for state in stream.OCCUPIES_A_CLIENT:
            self.assertIsNone(stream.outcome_of(self._row(state=state), 1005.0), state)

    def test_an_old_teardown_does_not_greet_you_on_open(self):
        """Yesterday's "nobody was watching" is not news, and showing it as a
        warning on a panel you just opened reads as a live failure."""
        self.assertIsNone(stream.outcome_of(self._row(), 1000.0 + 3600))

    def test_the_window_is_bounded_in_absolute_seconds(self):
        """Pinned to real numbers rather than to the constant, the same
        lesson the staleness class learned from a mutation run."""
        self.assertLessEqual(stream.OUTCOME_RECENT_SECONDS, 600)
        self.assertGreaterEqual(stream.OUTCOME_RECENT_SECONDS,
                                stream.STALE_AFTER_SECONDS)

    def test_a_bare_ended_row_says_nothing_because_it_has_nothing_to_say(self):
        self.assertIsNone(stream.outcome_of(self._row(detail=""), 1005.0))
        self.assertIsNone(stream.outcome_of(self._row(detail=None), 1005.0))

    def test_a_reason_of_unknown_age_is_not_shown(self):
        """No clock is not a measurement - the same refusal is_stale makes."""
        self.assertIsNone(
            stream.outcome_of(self._row(last_seen_seconds=None), 1005.0))


class AShotIsAWatchThatEnds(unittest.TestCase):
    """One picture, riding the watch lifecycle rather than getting its own
    table and poller. Everything that makes a watch safe applies unchanged -
    the channel cap, the sweep, the refusal reasons, and above all the selfbot
    verification that stops a login wedging the family's loot (#2781). A
    screenshot costs a real client login; it should cost the same care."""

    def test_the_vocabulary_stays_machine_readable(self):
        """The Windows agent has no import from here - it reads this file with
        ast.literal_eval and asserts its own vocabulary matches. Writing MODES
        as a tuple of NAMES makes the constant vanish from that parser, so the
        agent sees KeyError rather than a mismatch. It caught `shot` that way."""
        import ast as _ast
        import pathlib as _pathlib
        src = (_pathlib.Path(stream.__file__)).read_text()
        found = {}
        for node in _ast.parse(src).body:
            if isinstance(node, _ast.Assign) and isinstance(node.targets[0], _ast.Name):
                try:
                    found[node.targets[0].id] = _ast.literal_eval(node.value)
                except ValueError:
                    pass
        for name in ("MODES", "STATES", "OCCUPIES_A_CLIENT", "STALE_AFTER_SECONDS",
                     "SHOT_TIMEOUT_SECONDS", "NEEDS_A_VIEWER"):
            self.assertIn(name, found, f"{name} is no longer literal-evaluable")
        self.assertEqual(tuple(stream.MODES), tuple(found["MODES"]))

    def test_the_named_constants_and_the_literal_tuple_agree(self):
        """MODES is spelled out literally so a parser can read it, which means
        the values exist twice. Gated here so they cannot drift apart."""
        self.assertEqual((stream.POV, stream.CAM, stream.SHOT), tuple(stream.MODES))
        self.assertEqual((stream.POV, stream.CAM), tuple(stream.NEEDS_A_VIEWER))

    def test_shot_is_a_real_mode(self):
        self.assertIn(stream.SHOT, stream.MODES)
        self.assertTrue(stream.can_start([], "Grug", stream.SHOT)[0])

    def test_a_shot_holds_a_channel_like_anything_else(self):
        """It is a logged-in client for a minute. Pretending otherwise is how
        three clients end up on a two-client GPU."""
        rows = [{"state": "live", "character": "Grug", "mode": "pov"},
                {"state": "starting", "character": "Og", "mode": "shot"}]
        self.assertEqual(2, stream.channels_in_use(rows))
        self.assertFalse(stream.can_start(rows, "Bork", stream.SHOT)[0])

    def test_a_shot_expects_no_viewer(self):
        self.assertFalse(stream.needs_a_viewer({"mode": stream.SHOT}))
        for mode in (stream.POV, stream.CAM):
            self.assertTrue(stream.needs_a_viewer({"mode": mode}), mode)

    def test_a_row_with_no_mode_is_treated_as_a_watch(self):
        """Older rows predate the column. Assuming `shot` for them would give
        a real watch a three-minute leash and leave a client up for nobody."""
        self.assertTrue(stream.needs_a_viewer({}))

    def test_a_shot_is_not_swept_while_its_client_is_still_logging_in(self):
        """WoW measured 45-60s to a logged-in client on that hardware. On the
        watch clock the timeout would reliably beat the thing it is timing,
        tearing down the very client midway through starting for it."""
        shot = {"state": "starting", "character": "Grug", "mode": stream.SHOT,
                "requested_seconds": 1000.0}
        self.assertFalse(stream.is_stale(shot, 1000.0 + 90))

    def test_a_shot_nobody_serves_still_ends(self):
        """The sweep is its timeout. Without one it would hold a channel
        forever and no second shot could ever start."""
        shot = {"state": "starting", "character": "Grug", "mode": stream.SHOT,
                "requested_seconds": 1000.0}
        self.assertTrue(stream.is_stale(shot, 1000.0 + stream.SHOT_TIMEOUT_SECONDS + 1))

    def test_a_watch_keeps_the_short_leash(self):
        """The point of two clocks is that neither drifts onto the other."""
        watch = {"state": "live", "character": "Grug", "mode": stream.POV,
                 "last_seen_seconds": 1000.0}
        self.assertTrue(stream.is_stale(watch, 1000.0 + 90))

    def test_the_two_timeouts_are_bounded_in_absolute_seconds(self):
        """Pinned to real numbers, not to each other - the lesson the
        staleness class learned from a mutation run."""
        self.assertGreater(stream.SHOT_TIMEOUT_SECONDS, stream.STALE_AFTER_SECONDS)
        self.assertGreaterEqual(stream.SHOT_TIMEOUT_SECONDS, 120)
        self.assertLessEqual(stream.SHOT_TIMEOUT_SECONDS, 600)


class Channels(unittest.TestCase):
    """One GPU. infra#2663: 'one or two channels is the realistic target'."""

    def test_two_channels_can_be_in_use(self):
        rows = [{"state": "live", "character": "Grug"},
                {"state": "starting", "character": "Ugga"}]
        self.assertEqual(2, stream.channels_in_use(rows))

    def test_a_third_is_refused_with_a_reason_a_person_can_read(self):
        rows = [{"state": "live", "character": "Grug"},
                {"state": "live", "character": "Ugga"}]
        ok, why = stream.can_start(rows, "Bork", "cam")
        self.assertFalse(ok)
        self.assertIn("channel", why.lower())

    def test_ended_rows_do_not_hold_a_channel(self):
        """Otherwise the cap would fill with history and nobody could watch
        anything after two sessions."""
        rows = [{"state": "ended", "character": "Grug"},
                {"state": "ended", "character": "Ugga"}]
        self.assertEqual(0, stream.channels_in_use(rows))
        self.assertTrue(stream.can_start(rows, "Bork", "cam")[0])

    def test_watching_the_same_character_twice_is_refused_not_duplicated(self):
        """Two clients on one character would be two GPU channels showing the
        same thing - the answer is 'you are already there'."""
        rows = [{"state": "live", "character": "Grug"}]
        ok, why = stream.can_start(rows, "Grug", "pov")
        self.assertFalse(ok)
        self.assertIn("already", why.lower())

    def test_an_unknown_mode_is_refused(self):
        self.assertFalse(stream.can_start([], "Grug", "hologram")[0])


class DeliveryIsNotGuessed(unittest.TestCase):
    """Sunshine has NO browser player: 47990 is its config UI, video leaves
    over Moonlight (RTSP + UDP). Embedding a player for a Moonlight stream
    renders a black rectangle and a bug report."""

    def test_the_default_is_instructions_not_a_player(self):
        self.assertEqual(stream.DELIVERY_MOONLIGHT, stream.delivery_of({}))
        self.assertEqual(stream.DELIVERY_MOONLIGHT,
                         stream.delivery_of({"delivery": ""}))

    def test_an_embed_is_only_used_when_explicitly_claimed(self):
        self.assertEqual(stream.DELIVERY_EMBED,
                         stream.delivery_of({"delivery": "embed"}))

    def test_an_unrecognised_kind_falls_back_to_instructions(self):
        """Guessing wrong toward Moonlight prints a sentence; guessing wrong
        toward embed shows a dead player."""
        self.assertEqual(stream.DELIVERY_MOONLIGHT,
                         stream.delivery_of({"delivery": "webrtc-maybe"}))


class WatchingChangesTheWatched(unittest.TestCase):
    """Logging in as a character makes it a selfbot, which hands the followers
    a master - so watching the leader in POV makes his family follow him, for
    as long as the stream is up. The UI says so rather than hiding it."""

    def test_pov_on_the_leader_changes_the_family(self):
        self.assertTrue(stream.pov_changes_the_family("Grug", "Grug"))

    def test_pov_on_a_follower_does_not(self):
        self.assertFalse(stream.pov_changes_the_family("Ugga", "Grug"))

    def test_no_character_is_not_a_change(self):
        self.assertFalse(stream.pov_changes_the_family("", "Grug"))


class Migrations(unittest.TestCase):
    """CREATE TABLE IF NOT EXISTS is a no-op on an existing table, including
    every column inside it - the trap that made overseer_goal's kind-ENUM
    silently dead in production while CI stayed green."""

    def test_a_table_missing_everything_gets_every_alter(self):
        sql = stream.stream_migrations(["character", "requested_at"])
        self.assertEqual(4, len(sql))
        self.assertTrue(all(s.startswith("ALTER TABLE overseer_stream") for s in sql))

    def test_a_correct_table_needs_nothing(self):
        sql = stream.stream_migrations(
            ["character", "mode", "state", "detail", "last_seen"])
        self.assertEqual([], sql)

    def test_it_is_idempotent_by_construction(self):
        """Feeding it its own outcome twice is a no-op the second time."""
        first = stream.stream_migrations(["character"])
        after = ["character", "mode", "state", "detail", "last_seen"]
        self.assertEqual(4, len(first))
        self.assertEqual([], stream.stream_migrations(after))

    def test_case_does_not_defeat_it(self):
        self.assertEqual([], stream.stream_migrations(
            ["Character", "MODE", "State", "Detail", "LAST_SEEN"]))

    def test_state_is_not_an_enum(self):
        """VARCHAR on purpose: a new state word must never need a migration
        to be sayable, which is exactly what the goal-kind ENUM cost."""
        sql = " ".join(stream.stream_migrations(["character"]))
        self.assertIn("VARCHAR", sql.upper())
        self.assertNotIn("ENUM", sql.upper())


if __name__ == "__main__":
    unittest.main()


class MapServerWiring(unittest.TestCase):
    """The endpoints and the page, asserted against the source - map_server
    imports pymysql and cannot be imported by the tests."""

    @classmethod
    def setUpClass(cls):
        import pathlib
        here = pathlib.Path(__file__).resolve().parent.parent
        cls.server = (here / "map_server.py").read_text()
        cls.page = (here / "index.html").read_text()

    def test_the_watch_endpoints_exist_on_both_verbs(self):
        """Asserted against the routing tables rather than an if-chain: the
        contract is that each verb reaches the RIGHT half of the lifecycle.
        The form this replaced only proved the path string appeared somewhere,
        so a GET wired to _watch_post would have passed it."""
        get_table = self.server[self.server.index("GET_ROUTES = {"):]
        get_table = get_table[:get_table.index("}")]
        post_table = self.server[self.server.index("POST_ROUTES = {"):]
        post_table = post_table[:post_table.index("}")]
        self.assertIn('"/api/watch": _watch_state', get_table)
        self.assertIn('"/api/watch": _watch_post', post_table)

    def test_every_read_sweeps_stale_rows(self):
        """The sweep is the whole lifecycle: a viewer who closed the tab sends
        nothing again, so their silence cannot end anything by itself."""
        self.assertIn("stream_expire", self.server)
        state = self.server[self.server.index("def _watch_state"):]
        state = state[:state.index("def _watch_post")]
        self.assertIn("stream_expire", state)

    def test_the_table_is_migrated_not_merely_created(self):
        """CREATE TABLE IF NOT EXISTS is a no-op on an existing table."""
        self.assertIn("stream_migrations", self.server)
        self.assertIn("information_schema.COLUMNS", self.server)

    def test_clocks_come_from_the_database(self):
        """UNIX_TIMESTAMP in SQL, not datetime arithmetic in Python: the
        bridge and MySQL need not agree on timezone, and a stream torn down an
        hour early for that reason would be maddening to chase."""
        self.assertIn("UNIX_TIMESTAMP(last_seen)", self.server)

    def test_a_watch_request_checks_the_character_exists(self):
        self.assertIn("_character_exists_by_name", self.server)

    def test_the_endpoint_hands_the_reason_to_the_page(self):
        state = self.server[self.server.index("def _watch_state"):]
        state = state[:state.index("def _watch_post")]
        self.assertIn("outcome_of", state)
        self.assertIn('"outcome"', state)

    def test_the_page_offers_a_shot_and_does_not_beat_for_it(self):
        """A shot has no viewer to fall silent. Beating for it would keep
        alive a row whose entire point is to finish."""
        self.assertIn('id="pwshot"', self.page)
        self.assertIn('mode !== "shot"', self.page)

    def test_the_page_renders_it(self):
        self.assertIn("s.outcome", self.page)

    def test_a_live_detail_is_printed_verbatim(self):
        """The agent writes detail as prose meant to be read as-is. Labelling
        it produced "live on Moonlight - Open Moonlight on the Switch and
        launch..." - the sentence already says that, better."""
        self.assertNotIn('"live on Moonlight" + (w.detail', self.page)
        self.assertIn("watchNote(w.detail, \"live\")", self.page)

    def test_the_note_keeps_the_line_breaks_it_was_given(self):
        """detail is several sentences now; textContent collapses newlines
        without pre-wrap, running the instruction into one wall."""
        css = self.page[self.page.index("#pwnote {"):]
        self.assertIn("pre-wrap", css[:css.index("}")])

    def test_the_sweep_stamps_when_it_gave_up(self):
        """Without a clock on the teardown, outcome_of cannot tell a refusal
        that just happened from one that happened yesterday, and refuses to
        show either."""
        sweep = self.server[self.server.index("def stream_expire"):]
        sweep = sweep[:sweep.index("def _character_exists_by_name")]
        self.assertIn("last_seen = NOW()", sweep)

    def test_the_store_failing_does_not_take_the_map_down(self):
        main = self.server[self.server.index("def main()"):]
        self.assertIn("_ensure_stream_store", main)
        self.assertIn("except Exception", main)
        self.assertLess(main.index("logging.basicConfig"),
                        main.index("_ensure_stream_store"),
                        "the ensure must run AFTER basicConfig or its failure "
                        "is emitted through an unconfigured logger")

    def test_the_page_heartbeats_and_does_not_rely_on_unload(self):
        """Silence is the signal. An unload handler misses a crashed tab, a
        slept laptop and a dropped tailnet; a heartbeat misses none of them."""
        self.assertIn("setInterval", self.page)
        self.assertIn('"beat"', self.page)
        self.assertNotIn("onbeforeunload", self.page)

    def test_the_page_never_embeds_a_moonlight_stream(self):
        """Sunshine has no browser player - 47990 is its config UI. An iframe
        at any Sunshine port shows settings or nothing."""
        watch = self.page[self.page.index("async function refreshWatch"):]
        watch = watch[:watch.index("pwcam.onclick")]
        self.assertIn('w.delivery === "embed"', watch)
        self.assertIn("Moonlight", watch)
        self.assertNotIn("<iframe", watch)

    def test_closing_the_panel_does_not_stop_the_stream(self):
        """A viewer may close the map and keep watching on the Switch. Only
        the staleness sweep decides, because only it cannot be fooled by how
        the page was left."""
        close = self.page[self.page.index("function closePanel"):]
        close = close[:close.index("async function fetchPanel")]
        self.assertIn("clearInterval", close)
        self.assertNotIn('"stop"', close)

    def test_both_modes_are_offered_and_described(self):
        self.assertIn('id="pwcam"', self.page)
        self.assertIn('id="pwpov"', self.page)
        self.assertIn("observer", self.page)


class AShotIsNotAWatch(unittest.TestCase):
    """The map's own sweep has to know that a still is on a different clock.

    `stream_expire` runs on every read of the watch endpoint, which the open
    map does constantly. If the map still believed a shot dies after sixty
    seconds of silence it would move the row to 'stopping' while the Windows
    agent was forty-five seconds into logging a character in for it - THE
    TIMEOUT BEATING THE THING IT IS TIMING, with the agent entirely innocent
    and the symptom being a still that never arrives.

    A shot has no heartbeat on purpose: the page does not beat for one,
    because beating would keep alive a row whose whole purpose is to finish.
    So the only honest question about a shot is "has this been sitting here
    longer than a login could take", asked of `requested_at`.
    """

    def shot(self, **over):
        row = {"character": "Ugga", "mode": "shot", "state": "requested",
               "requested_seconds": 1000.0, "last_seen_seconds": 1000.0}
        row.update(over)
        return row

    def test_a_shot_survives_the_watch_timeout(self):
        self.assertFalse(stream.is_stale(self.shot(), 1000.0 + 90))

    def test_a_shot_expires_on_its_own_leash(self):
        self.assertTrue(
            stream.is_stale(self.shot(),
                            1000.0 + stream.SHOT_TIMEOUT_SECONDS + 1))

    def test_a_shot_with_no_heartbeat_is_not_stale_for_that_reason(self):
        self.assertFalse(
            stream.is_stale(self.shot(last_seen_seconds=None), 1000.0 + 90))

    def test_a_watch_is_unchanged(self):
        self.assertTrue(stream.is_stale(self.shot(mode="pov"), 1000.0 + 61))

    def test_a_row_with_no_mode_is_a_watch(self):
        """Rows predate the mode column. A real watch handed three minutes is
        a client rendering for nobody for three minutes."""
        self.assertTrue(stream.is_stale(self.shot(mode=None), 1000.0 + 61))

    def test_an_unrecognised_mode_falls_to_the_shorter_leash(self):
        """A mode nobody has heard of is far more likely to be a mistyped
        watch than a new kind of still. Membership in NEEDS_A_VIEWER answers
        "no viewer" for it and hands it three minutes - a client rendering for
        nobody for three minutes. Asking "is this a shot?" instead puts every
        unknown on the short clock, where being wrong costs a second click."""
        self.assertTrue(stream.is_stale(self.shot(mode="hologram"),
                                        1000.0 + 61))
        self.assertTrue(stream.needs_a_viewer({"mode": "hologram"}))

    def test_a_shot_may_be_asked_for(self):
        allowed, why = stream.can_start([], "Ugga", stream.SHOT)
        self.assertTrue(allowed, why)

    def test_the_shot_leash_is_longer_than_the_watch_one(self):
        self.assertGreater(stream.SHOT_TIMEOUT_SECONDS,
                           stream.STALE_AFTER_SECONDS)
