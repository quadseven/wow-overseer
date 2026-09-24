"""Hand-overs happen the way a player's would (#189, #185).

mod-overseer#566 (PR #571) makes `kind='give'` refuse unless the two
characters stand on one map inside trade range. mod-overseer#569 (PR #570)
adds a `walk-to-mailbox` row that walks a guild bot off the roster to the
nearest mailbox. This suite pins the site's side of both:

  * every pass that wrote a give asks `handover.verdict` first, and writes a
    give only when the pair was last seen together; apart, a guild gift is
    posted from a mailbox or waits, and a family hand-over waits;
  * the module's distance refusal never marks a pair stuck;
  * a route held by a guild bot walks it by the module's row, posts the
    letter on 'applied', and backs off on a worldserver that does not know
    the row.

bridge.py imports discord and cannot be imported here, so its wiring is read
as text, the way test_bag_handover and test_guildroute read it.
"""

import json
import pathlib
import re
import unittest

import guildroute
import guildshare
import handover
import materials

HERE = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = HERE / "bridge.py"

KALIMDOR, EASTERN_KINGDOMS = 1, 0


def at(map_id, x, y):
    return {"map_id": map_id, "pos_x": float(x), "pos_y": float(y)}


NEAR = handover.spots({"Og": at(KALIMDOR, 0, 0), "Grug": at(KALIMDOR, 6, 4)})
FAR = handover.spots({"Og": at(KALIMDOR, 0, 0), "Grug": at(KALIMDOR, 240, 0)})
SPLIT = handover.spots({"Og": at(KALIMDOR, 0, 0), "Grug": at(EASTERN_KINGDOMS, 0, 0)})


def _block(signature: str) -> str:
    """One def's body, to the next def at the same or shallower indent."""
    src = BRIDGE.read_text(encoding="utf-8")
    start = src.index(signature)
    indent = len(signature) - len(signature.lstrip())
    rest = src[start:]
    match = re.search(r"\n {0,%d}(async def |def |class )" % indent, rest[1:])
    return rest[: match.start() + 1] if match else rest


class TheVerdict(unittest.TestCase):
    def test_a_near_pair_gives(self):
        self.assertEqual(handover.verdict("Og", "Grug", NEAR).verb, handover.GIVE)

    def test_a_far_pair_waits_and_says_how_far(self):
        got = handover.verdict("Og", "Grug", FAR)
        self.assertEqual(got.verb, "")
        self.assertIn("Og and Grug are 240 yards apart", got.why)
        self.assertIn("waits until they stand together", got.why)

    def test_two_maps_wait_and_say_so(self):
        got = handover.verdict("Og", "Grug", SPLIT)
        self.assertEqual(got.verb, "")
        self.assertIn("on different maps", got.why)

    def test_the_edge_of_trade_range(self):
        inside = handover.spots({"Og": at(1, 0, 0), "Grug": at(1, 11.0, 0)})
        outside = handover.spots({"Og": at(1, 0, 0), "Grug": at(1, 11.2, 0)})
        self.assertEqual(handover.verdict("Og", "Grug", inside).verb, handover.GIVE)
        self.assertEqual(handover.verdict("Og", "Grug", outside).verb, "")

    def test_an_unseen_character_is_never_given_to(self):
        alone = handover.spots({"Og": at(1, 0, 0)})
        got = handover.verdict("Og", "Grug", alone)
        self.assertEqual((got.verb, got.why[:26]), ("", "Grug is not in the world; "))
        got = handover.verdict("Grug", "Og", alone)
        self.assertEqual(got.why, "Grug is not in the world")

    def test_a_mailable_item_is_posted_from_a_mailbox(self):
        got = handover.verdict("Og", "Grug", FAR, posting={"Og"}, mailable=True)
        self.assertEqual(got.verb, handover.MAIL)

    def test_a_mailable_item_away_from_a_mailbox_waits_for_one(self):
        got = handover.verdict("Og", "Grug", FAR, posting=set(), mailable=True)
        self.assertEqual(got.verb, "")
        self.assertIn("goes by post when Og next stands at a mailbox", got.why)

    def test_together_beats_the_post(self):
        got = handover.verdict("Og", "Grug", NEAR, posting={"Og"}, mailable=True)
        self.assertEqual(got.verb, handover.GIVE)

    def test_an_unmailable_item_is_never_posted(self):
        got = handover.verdict("Og", "Grug", FAR, posting={"Og"}, mailable=False)
        self.assertEqual(got.verb, "")

    def test_the_log_line(self):
        self.assertEqual(
            handover.waiting("Linen Cloth", "Og", "Grug", "why"),
            "Linen Cloth from Og to Grug waits: why",
        )


class TheDistanceWallIsNotStuck(unittest.TestCase):
    TOO_FAR = (
        "giver and receiver are too far apart to hand over; "
        "meet within trade range or mail it"
    )
    OTHER_MAP = (
        "giver and receiver are on different maps; meet within trade range or mail it"
    )

    def test_both_module_sentences_are_recognised(self):
        self.assertTrue(handover.is_range_refusal(self.TOO_FAR))
        self.assertTrue(handover.is_range_refusal(self.OTHER_MAP))
        self.assertFalse(handover.is_range_refusal("receiver bags are full"))
        self.assertFalse(handover.is_range_refusal(""))

    def test_range_refusals_never_mark_a_pair_stuck(self):
        attempts = [
            materials.Attempt(
                holder="Og", taker="Grug", status="error", detail=self.TOO_FAR
            )
            for _ in range(materials.GIVE_UP_AFTER + 2)
        ]
        self.assertEqual(materials.stuck(attempts), {})
        self.assertEqual(materials.refusal_counts(attempts), {})

    def test_a_real_refusal_still_counts_through_them(self):
        full = "receiver bags are full"
        attempts = []
        for _ in range(materials.GIVE_UP_AFTER):
            attempts.append(materials.Attempt("Og", "Grug", "error", full))
            attempts.append(materials.Attempt("Og", "Grug", "error", self.OTHER_MAP))
        self.assertEqual(materials.stuck(attempts), {("Og", "Grug"): full})


class EveryGiveWriterAsksFirst(unittest.TestCase):
    """Each of the five passes #189 names reads positions and asks the verdict
    before it writes, and logs the waits."""

    def test_bags(self):
        body = _block("    async def _hand_bags_once(")
        self.assertIn(
            "handover.spots(await asyncio.to_thread(_fetch_positions, names))", body
        )
        ask = body.index("handover.verdict(move.giver, move.receiver, where)")
        self.assertLess(ask, body.index("_insert_bag_give"))
        self.assertIn('_log_capped("bags", waits)', body)

    def test_materials(self):
        body = _block("    async def _move_materials_once(")
        ask = body.index("handover.verdict(grant.holder, grant.taker, where)")
        self.assertLess(ask, body.index("await asyncio.to_thread(_insert_give, grant)"))
        self.assertIn('_log_capped("materials", waits)', body)

    def test_guild_surplus_gives_together_posts_or_waits(self):
        self.assertIn(
            "await self._write_guild_gifts(share.gifts)",
            _block("    async def _guild_share_once("),
        )
        body = _block("    async def _write_guild_gifts(")
        ask = body.index("handover.verdict(")
        self.assertIn("posting=posting, mailable=True", body)
        self.assertLess(ask, body.index("_insert_guild_gift, gift, how.verb"))
        self.assertIn('_log_capped("guildshare", waits)', body)
        facts = _block("    async def _guild_gift_facts(")
        self.assertIn("_holders_at_mailbox", facts)

    def test_the_guild_gift_writer_writes_only_give_or_mail(self):
        body = _block("def _insert_guild_gift(")
        self.assertIn("if verb not in (handover.GIVE, handover.MAIL):", body)
        self.assertIn(
            "gift.post_command if verb == handover.MAIL else gift.command", body
        )
        self.assertNotIn("VALUES (%s, %s, 'give', %s, %s)", body)

    def test_guild_gear_is_offered_the_post(self):
        body = _block("    async def _guild_gear_share_once(")
        self.assertIn("_holders_at_mailbox, list(family_names), positions", body)
        self.assertIn("at_mailbox=at_mailbox", body)

    def test_the_town_trip(self):
        body = _block("    async def _towntrip_once(")
        self.assertIn("if errand.kind == towntrip.GIVE_KIND:", body)
        ask = body.index("handover.verdict(errand.member, errand.taker, where)")
        self.assertLess(ask, body.index("_insert_town_errand, errand"))
        self.assertIn('_log_capped("towntrip", waits)', body)

    def test_no_pass_but_these_writes_a_give(self):
        """The four literal give writers are the ones gated above; the gear
        writer's kind comes from gear.deliverable, which never answers give."""
        src = BRIDGE.read_text(encoding="utf-8")
        literal = sorted(
            chunk.split("(", 1)[0]
            for chunk in src.split("\ndef ")[1:]
            if "'give', %s" in chunk
        )
        self.assertEqual(literal, ["_insert_bag_give", "_insert_give"])


class TheGuildGiftPosts(unittest.TestCase):
    def test_the_post_command_is_a_mail_send_of_the_same_stack(self):
        gift = guildshare.Gift(
            holder="Og",
            taker="Avenah",
            item="Linen Cloth",
            entry=2589,
            count=20,
            guid=881,
            need="",
            reason="",
        )
        self.assertEqual(gift.command, "guid:881")
        self.assertEqual(gift.post_command, "send item:881 subject:Linen Cloth")


def _row(status, detail="", **result):
    return status, detail, json.dumps(result) if result else ""


class TheWalkRowIsReadForEveryAnswer(unittest.TestCase):
    """quadseven/mod-overseer#570's statuses, and an older module's answer."""

    def judge(self, status, detail="", **result):
        return guildroute.judge_walk("Avenah", *_row(status, detail, **result))

    def test_still_walking(self):
        for status in ("pending", "claimed", "verifying"):
            with self.subTest(status=status):
                self.assertEqual(self.judge(status).state, guildroute.WALKING)

    def test_arrived(self):
        got = self.judge(
            "applied",
            outcome="arrived",
            reached={"name": "Mailbox", "yards": 2.5, "held_seconds": 120},
        )
        self.assertEqual(got.state, guildroute.ARRIVED)
        self.assertEqual(got.mailbox, "Mailbox")
        self.assertEqual(got.said, "Avenah stands at Mailbox")

    def test_unchanged_ends_and_may_try_again(self):
        got = self.judge("unchanged", "did not reach the mailbox in time")
        self.assertEqual(got.state, guildroute.ENDED)
        self.assertTrue(got.retryable)
        self.assertIn("did not reach the mailbox in time", got.said)

    def test_a_refusal_carries_the_modules_retryable_flag(self):
        got = self.judge("error", "character is in combat", retryable=True)
        self.assertEqual((got.state, got.retryable), (guildroute.ENDED, True))
        got = self.judge("error", "nearest mailbox is beyond the cap", retryable=False)
        self.assertEqual((got.state, got.retryable), (guildroute.ENDED, False))
        self.assertIn("nearest mailbox is beyond the cap", got.said)

    def test_an_older_worldserver_is_read_as_unsupported(self):
        """Before #570 the row reaches DoMail, whose parser knows five verbs."""
        got = self.judge("error", "malformed mail command", retryable=False)
        self.assertEqual(got.state, guildroute.UNSUPPORTED)
        self.assertIn("60 minutes", got.said)

    def test_an_unreadable_result_is_not_a_crash_nor_an_arrival(self):
        got = guildroute.judge_walk("Avenah", "applied", "", "{not json")
        self.assertEqual((got.state, got.retryable), (guildroute.ENDED, False))
        self.assertIn("without an arrival", got.said)
        got = guildroute.judge_walk("Avenah", "error", "", None)
        self.assertEqual(got.state, guildroute.ENDED)

    def test_a_wrapped_unknown_verb_is_still_unsupported(self):
        got = self.judge("error", "refused: malformed mail command.")
        self.assertEqual(got.state, guildroute.UNSUPPORTED)

    def test_the_hold_and_the_follow_are_bounded(self):
        self.assertEqual(guildroute.MAIL_WALK_HOLD_SECONDS, 120)
        self.assertLessEqual(guildroute.MAIL_RUN_YARDS, 600)
        self.assertGreater(guildroute.WALK_FOLLOW_SECONDS, 300)
        self.assertLess(guildroute.WALK_FOLLOW_SECONDS, guildroute.MAIL_RUN_SECONDS)


class TheBridgeFollowsTheWalk(unittest.TestCase):
    def test_the_walk_row_is_kind_mail_with_its_own_source(self):
        body = _block("def _insert_mail_walk(")
        self.assertIn("VALUES (%s, %s, 'mail', %s, %s)", body)
        self.assertIn("run.walk_command", body)
        self.assertIn("MAIL_WALK_SOURCE", body)

    def test_the_follow_is_bounded_and_reads_the_row(self):
        """The read loop is shared with the guild dues walks (#234), so it
        lives in `_await_mail_walk` and the follow calls it."""
        loop = _block("    async def _await_mail_walk(")
        # Bounded by the row's own cap since quadseven/mod-overseer#633: the
        # near cap is still WALK_FOLLOW_SECONDS, the far one the far ceiling.
        self.assertIn("guildroute.follow_seconds(cap)", loop)
        self.assertEqual(
            guildroute.follow_seconds(guildroute.MAIL_RUN_YARDS),
            guildroute.WALK_FOLLOW_SECONDS,
        )
        self.assertIn("await asyncio.sleep(MAIL_WALK_POLL_SECONDS)", loop)
        self.assertIn("_command_answer, row_id", loop)
        self.assertIn("guildroute.judge_walk(", loop)
        self.assertNotIn("except Exception", loop)
        body = _block("    async def _follow_mail_walk(")
        self.assertIn("await self._await_mail_walk(run.holder, row_id)", body)
        self.assertIn("except pymysql.err.MySQLError:", body)
        self.assertNotIn("except Exception", body)

    def test_arrival_posts_through_the_route_writer_once(self):
        body = _block("    async def _end_mail_walk(")
        arrived = body.index("guildroute.ARRIVED")
        self.assertLess(arrived, body.index("_recent_route_keys"))
        self.assertLess(
            body.index("_recent_route_keys"), body.index("_insert_route, run")
        )

    def test_an_older_worldserver_backs_off(self):
        body = _block("    async def _end_mail_walk(")
        self.assertIn("guildroute.UNSUPPORTED", body)
        self.assertIn("guildroute.WALK_UNSUPPORTED_SECONDS", body)
        walk = _block("    async def _walk_route_holders(")
        self.assertIn("row_walks = now >= self._mail_walk_unsupported_until", walk)
        self.assertIn("_route_walks_today", walk)

    def test_the_follow_task_is_held(self):
        body = _block("    async def _start_mail_walk(")
        self.assertIn("self._mail_walk_tasks.add(task)", body)
        self.assertIn("task.add_done_callback(self._mail_walk_task_done)", body)
        done = _block("    def _mail_walk_task_done(")
        self.assertIn("log.error(", done)
        self.assertIn("self._guild_mail_runs.pop(run.holder, None)", body)

    def test_handover_ships(self):
        self.assertIn(
            " handover.py ", (HERE / "Dockerfile").read_text(encoding="utf-8")
        )


if __name__ == "__main__":
    unittest.main()
