"""A picture of a character's own screen, and the honesty around it.

The whole point of the status field is that three different things look
identical on a panel otherwise: a bot that is genuinely standing still, a
capture that came back black, and a capture that never happened.
"""
import pathlib
import unittest

import frames

JPEG = b"\xff\xd8\xff" + b"body"


class WhatIsAccepted(unittest.TestCase):
    def test_a_real_jpeg_is_taken(self):
        self.assertEqual("", frames.refusal("Grug", frames.OK, JPEG, ""))

    def test_a_png_posing_as_a_frame_is_refused(self):
        """Stored happily, it renders as a broken image with nothing anywhere
        saying why - the exact silent-failure shape this file exists against."""
        png = b"\x89PNG\r\n\x1a\n" + b"body"
        self.assertIn("jpeg", frames.refusal("Grug", frames.OK, png, ""))

    def test_an_ok_with_no_frame_is_refused(self):
        self.assertIn("needs a frame", frames.refusal("Grug", frames.OK, b"", ""))

    def test_an_unknown_status_is_refused(self):
        self.assertIn("status must be", frames.refusal("Grug", "fine", JPEG, ""))

    def test_an_oversized_frame_is_refused(self):
        big = b"\xff\xd8\xff" + b"x" * frames.MAX_FRAME_BYTES
        self.assertIn("larger than", frames.refusal("Grug", frames.OK, big, ""))

    def test_the_size_cap_is_bounded_in_absolute_bytes(self):
        """Pinned to real numbers rather than to the constant, so raising it to
        something absurd is a failing test and not a silent policy change."""
        self.assertLessEqual(frames.MAX_FRAME_BYTES, 2 * 1024 * 1024)
        self.assertGreaterEqual(frames.MAX_FRAME_BYTES, 128 * 1024)

    def test_a_failure_needs_no_frame(self):
        for status in (frames.BLACK, frames.FAILED):
            self.assertEqual("", frames.refusal("Grug", status, b"", "no client"), status)

    def test_an_overlong_reason_is_refused_rather_than_silently_cut(self):
        self.assertIn("longer than",
                      frames.refusal("Grug", frames.FAILED, b"", "x" * 500))


class AFailureKeepsTheLastGoodPicture(unittest.TestCase):
    """Throwing away the only picture because the newest capture went black
    replaces something useful with nothing. Its age already stops it passing
    as live."""

    def test_black_keeps_the_frame_and_records_why(self):
        first = frames.accept(None, frames.OK, JPEG, "", 1000.0)
        then = frames.accept(first, frames.BLACK, b"", "d3d returned black", 1100.0)
        self.assertEqual(JPEG, then["jpeg"])
        self.assertEqual(frames.BLACK, then["status"])
        self.assertEqual("d3d returned black", then["detail"])

    def test_the_picture_keeps_its_own_age_not_the_failures(self):
        """Two clocks on purpose: when the PICTURE was taken, and when anything
        last tried. A viewer looking at a stale image needs the second one -
        it is the difference between 'nobody is looking' and 'we are looking
        and it is failing'."""
        first = frames.accept(None, frames.OK, JPEG, "", 1000.0)
        then = frames.accept(first, frames.FAILED, b"", "client died", 1100.0)
        got = frames.describe(then, 1150.0)
        self.assertEqual(150, got["captured_seconds_ago"])
        self.assertEqual(50, got["tried_seconds_ago"])

    def test_a_new_good_frame_replaces_the_old_one(self):
        first = frames.accept(None, frames.OK, JPEG, "", 1000.0)
        fresh = b"\xff\xd8\xff" + b"newer"
        then = frames.accept(first, frames.OK, fresh, "", 1100.0)
        self.assertEqual(fresh, then["jpeg"])
        self.assertEqual(100, frames.describe(then, 1200.0)["captured_seconds_ago"])

    def test_nothing_ever_posted_says_so_plainly(self):
        got = frames.describe(None, 1000.0)
        self.assertFalse(got["has_frame"])
        self.assertIsNone(got["status"])
        self.assertIsNone(got["captured_seconds_ago"])


class ReasonsAreReadable(unittest.TestCase):
    def test_whitespace_is_collapsed_not_rendered(self):
        self.assertEqual("no client logged in",
                         frames.clean_detail("  no   client\nlogged in  "))

    def test_a_reason_is_capped(self):
        self.assertEqual(frames.MAX_DETAIL_CHARS, len(frames.clean_detail("x" * 900)))

    def test_a_non_string_reason_is_not_rendered_as_one(self):
        self.assertEqual("", frames.clean_detail(None))
        self.assertEqual("", frames.clean_detail(12))


class TheEndpointIsWired(unittest.TestCase):
    """map_server imports pymysql and index.html is a browser page, so both are
    asserted against their source."""

    @classmethod
    def setUpClass(cls):
        here = pathlib.Path(__file__).resolve().parent.parent
        cls.server = (here / "map_server.py").read_text()
        cls.page = (here / "index.html").read_text()

    def test_both_verbs_reach_the_right_half(self):
        get = self.server[self.server.index("GET_ROUTES = {"):]
        get = get[:get.index("}")]
        post = self.server[self.server.index("POST_ROUTES = {"):]
        post = post[:post.index("}")]
        self.assertIn('"/api/frame": _frame_get', get)
        self.assertIn('"/api/frame": _frame_post', post)

    def test_the_store_is_bounded_and_not_on_disk(self):
        """History would need a cleanup job, and base64 in a TEXT column is how
        a table becomes unqueryable."""
        self.assertIn("_FRAMES: dict = {}", self.server)
        self.assertIn("_FRAMES_LOCK", self.server)

    def test_the_page_shows_the_reason_and_not_just_the_word_failed(self):
        self.assertIn("m.detail", self.page)

    def test_the_page_forces_a_refetch_when_a_newer_frame_lands(self):
        """An <img> whose src never changes is never re-fetched, no-store or
        not - the panel would show one picture forever."""
        self.assertIn("frameSeen", self.page)
        self.assertIn("captured_seconds_ago < frameSeen.ago", self.page)
