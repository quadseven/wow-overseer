"""Thought-timeline and web-chat tests: rows in, page/prompt/reply out.

Same seam rule as the rest of the service (infra#2597): the HTTP adapter
fetches rows and writes rows, and every decision the timeline and the chat
box make - how a page ends, what "3m ago" means, who spoke a line, what the
model is actually asked, what a garbled model reply degrades to - lives in
chat.py where this stdlib suite can reach it without MySQL or an LLM.

Ticket: infra#2604.
"""
import unittest
from datetime import datetime, timedelta

import chat
import jobs
import persona
import voice

NOW = datetime(2026, 8, 21, 12, 0, 0)


def rows(*specs) -> list[dict]:
    """Newest-first rows shaped like the SELECT the adapter runs."""
    out = []
    for row_id, source, text, ago_seconds in specs:
        out.append({
            "id": row_id,
            "source": source,
            "text": text,
            "created_at": NOW - timedelta(seconds=ago_seconds),
        })
    return out


class RelativeWhenTest(unittest.TestCase):
    def test_seconds_minutes_hours_days(self):
        cases = [(3, "just now"), (42, "42s ago"), (90, "1m ago"),
                 (60 * 75, "1h ago"), (86400 * 3 + 5, "3d ago")]
        for ago, expected in cases:
            with self.subTest(ago=ago):
                self.assertEqual(chat.relative_when(NOW - timedelta(seconds=ago), NOW), expected)

    def test_a_row_stamped_in_the_future_reads_as_just_now(self):
        # The label is computed on the database clock, but a row written
        # between the SELECT and the NOW() read is legitimately "ahead".
        # "in -2s" would read as breakage; "just now" is the truth.
        self.assertEqual(chat.relative_when(NOW + timedelta(seconds=2), NOW), "just now")


class TimelineTest(unittest.TestCase):
    def test_each_thought_carries_id_source_text_iso_and_label(self):
        page = chat.build_timeline("Odo", rows((9, "event", "Odo entered combat.", 120)), NOW, 50)
        self.assertEqual(page["name"], "Odo")
        thought = page["thoughts"][0]
        self.assertEqual(thought["id"], 9)
        self.assertEqual(thought["source"], "event")
        self.assertEqual(thought["text"], "Odo entered combat.")
        self.assertEqual(thought["created_at"], "2026-08-21T11:58:00")
        self.assertEqual(thought["when"], "2m ago")

    def test_newest_first_order_is_preserved(self):
        page = chat.build_timeline(
            "Odo", rows((9, "chat", "later", 10), (8, "chat", "earlier", 60)), NOW, 50
        )
        self.assertEqual([t["id"] for t in page["thoughts"]], [9, 8])

    def test_overseer_chat_lines_are_attributed_and_unprefixed(self):
        # Both sides of a web exchange persist as source 'chat' (one enum,
        # two speakers), so the marker is what tells the page who spoke.
        page = chat.build_timeline(
            "Odo",
            rows((9, "chat", "I go, Overseer.", 5),
                 (8, "chat", chat.overseer_line("go mine"), 6)),
            NOW, 50,
        )
        said, asked = page["thoughts"]
        self.assertEqual(said["speaker"], "character")
        self.assertEqual(asked["speaker"], "overseer")
        self.assertEqual(asked["text"], "go mine")

    def test_a_discord_command_thought_is_the_overseer_speaking(self):
        page = chat.build_timeline("Odo", rows((7, "command", "go mine", 5)), NOW, 50)
        self.assertEqual(page["thoughts"][0]["speaker"], "overseer")

    def test_a_full_page_offers_the_next_cursor(self):
        page = chat.build_timeline(
            "Odo", rows((9, "event", "a", 1), (8, "event", "b", 2)), NOW, 2
        )
        self.assertEqual(page["next_before"], 8)
        self.assertTrue(page["has_more"])

    def test_a_short_page_is_the_end_of_history(self):
        page = chat.build_timeline("Odo", rows((9, "event", "a", 1)), NOW, 2)
        self.assertIsNone(page["next_before"])
        self.assertFalse(page["has_more"])

    def test_a_character_with_no_thoughts_is_an_empty_page_not_an_error(self):
        page = chat.build_timeline("Odo", [], NOW, 50)
        self.assertEqual(page["thoughts"], [])
        self.assertIsNone(page["next_before"])


class PageSizeTest(unittest.TestCase):
    def test_missing_or_unparseable_falls_back_to_the_default(self):
        for raw in (None, "", "lots", "-4", "0"):
            with self.subTest(raw=raw):
                self.assertEqual(chat.page_size(raw), chat.DEFAULT_PAGE)

    def test_a_huge_request_is_clamped(self):
        # Bounded on purpose: one page must never be a whole-table scan
        # serialized into a single response.
        self.assertEqual(chat.page_size("100000"), chat.MAX_PAGE)

    def test_a_sane_request_is_honored(self):
        self.assertEqual(chat.page_size("10"), 10)


class MessageTest(unittest.TestCase):
    def test_whitespace_only_is_not_a_message(self):
        self.assertEqual(chat.clean_message("   \n "), "")

    def test_a_long_message_is_bounded(self):
        self.assertEqual(len(chat.clean_message("x" * 5000)), chat.MAX_MESSAGE)

    def test_the_overseer_marker_survives_the_column_limit(self):
        line = chat.overseer_line("y" * 5000)
        self.assertTrue(line.startswith(chat.OVERSEER_PREFIX))
        self.assertLessEqual(len(line), chat.MAX_TEXT)


class PromptTest(unittest.TestCase):
    def build(self, **kw):
        args = {
            "name": "Odo", "level": 5, "race_name": "Orc", "class_name": "Warrior",
            "zone": "Durotar", "personality": "gruff and loyal",
            "health": 100, "max_health": 146, "in_combat": False,
            "recent": rows((9, "event", "Odo entered combat.", 60),
                           (8, "chat", "I am hungry.", 120)),
            "text": "go train your mining",
        }
        args.update(kw)
        return chat.build_chat_prompt(**args)

    def test_the_prompt_states_who_the_character_is(self):
        prompt = self.build()
        for fragment in ("Odo", "level 5", "Orc", "Warrior", "gruff and loyal"):
            self.assertIn(fragment, prompt)

    def test_the_prompt_states_the_situation(self):
        prompt = self.build(in_combat=True)
        self.assertIn("Durotar", prompt)
        self.assertIn("100/146", prompt)
        self.assertIn("fighting", prompt)

    def test_the_prompt_carries_recent_history_oldest_first(self):
        prompt = self.build()
        self.assertIn("Odo entered combat.", prompt)
        self.assertIn("I am hungry.", prompt)
        self.assertLess(prompt.index("I am hungry."), prompt.index("Odo entered combat."))

    def test_history_is_capped_so_one_chat_cannot_grow_unbounded(self):
        # Newest first in, newest kept: a character with months of event
        # thoughts must not build a prompt that grows with their history.
        many = rows(*[(i, "event", "line %d" % i, 61 - i) for i in range(60, 0, -1)])
        prompt = self.build(recent=many)
        self.assertIn("line 60", prompt)
        self.assertIn("line 53", prompt)
        self.assertNotIn("line 52", prompt)

    def test_the_prompt_asks_the_question_and_names_the_answer_shape(self):
        prompt = self.build()
        self.assertIn("go train your mining", prompt)
        self.assertIn('"say"', prompt)
        self.assertIn('"command"', prompt)
        self.assertIn("none", prompt)

    def test_the_prompt_offers_only_the_sanctioned_vocabulary(self):
        # Same select-and-parameterize rule as the Discord path: the model
        # picks from a list, it never invents a string for the game.
        prompt = self.build()
        for command in ("grind", "follow", "stay"):
            self.assertIn(command, prompt)

    def test_a_character_with_no_personality_row_still_gets_a_prompt(self):
        prompt = self.build(personality=None)
        self.assertIn("Odo", prompt)
        self.assertNotIn("Personality:", prompt)

    def test_an_empty_history_is_stated_not_faked(self):
        prompt = self.build(recent=[])
        self.assertIn("Odo", prompt)
        self.assertIn("nothing", prompt.lower())


class ParseReplyTest(unittest.TestCase):
    def test_the_last_json_object_wins_over_the_narration(self):
        # Live-learned on 2026-08-21: reasoning models narrate first, and
        # the narration contains braces. The answer is the LAST object.
        content = ('First I consider {"command": "flee"} but no.\n'
                   '{"command": "grind", "say": "I will hunt, Overseer."}')
        decision = chat.parse_reply(content)
        self.assertEqual(decision.command, "grind")
        self.assertEqual(decision.say, "I will hunt, Overseer.")

    def test_an_invented_command_is_dropped_but_the_words_survive(self):
        decision = chat.parse_reply('{"command": "rm -rf azeroth", "say": "As you wish."}')
        self.assertIsNone(decision.command)
        self.assertEqual(decision.say, "As you wish.")

    def test_plain_prose_is_a_usable_reply(self):
        decision = chat.parse_reply("I am tired, Overseer.")
        self.assertIsNone(decision.command)
        self.assertEqual(decision.say, "I am tired, Overseer.")

    def test_reasoning_tags_are_stripped_and_the_answer_kept(self):
        decision = chat.parse_reply(
            "<think>the user wants mining, I should agree</think>\n\n"
            "As you wish, Overseer.\nI will swing the pick."
        )
        self.assertEqual(decision.say, "As you wish, Overseer. I will swing the pick.")

    def test_reasoning_that_never_finished_is_silence_not_a_leaked_monologue(self):
        # The model hit max_tokens mid-thought: there is no answer, and
        # pasting its private reasoning into the character's mouth is worse
        # than admitting nothing came back.
        decision = chat.parse_reply("<think>hmm, the overseer wants me to mine, and")
        self.assertEqual(decision.say, chat.SILENT_LINE)

    def test_nothing_at_all_degrades_to_an_honest_line(self):
        for content in ("", "   \n\n "):
            with self.subTest(content=content):
                self.assertEqual(chat.parse_reply(content).say, chat.SILENT_LINE)

    def test_a_broken_json_fragment_falls_back_to_the_prose_around_it(self):
        decision = chat.parse_reply('I will go.\n{"command": "grind", "say": ')
        self.assertEqual(decision.say, "I will go.")

    def test_a_reply_is_bounded_by_the_say_limit(self):
        decision = chat.parse_reply("z" * 5000)
        self.assertLessEqual(len(decision.say), voice.MAX_SAY)

    def test_a_json_reply_with_no_words_still_yields_something_sayable(self):
        self.assertTrue(chat.parse_reply('{"command": "grind", "say": ""}').say.strip())


class OutageTest(unittest.TestCase):
    def test_the_outage_line_names_the_character_and_admits_the_silence(self):
        # The human's message is already persisted by then; the reply row
        # must be honest rather than an invented in-character answer.
        line = chat.outage_line("Odo")
        self.assertIn("Odo", line)
        self.assertLessEqual(len(line), chat.MAX_TEXT)


# --- the rules for saying a thing out loud (infra#3197) --------------------
#
# Every case below is constructed. The three faults they pin were captured
# from Evan's own stream and confirmed against the live database on
# 2026-09-02: one sentence said 58 times in three minutes, a crafter
# answering itself, and a claim ("Og know tailoring") that `character_skills`
# has never supported.

# Og as the world actually has him: herbalism, and nothing else.
OG_LIVE = {"Og": {"herbalism": 30}}
# What the family has DECIDED he will end up with. Still 'planned' in
# overseer_trade since 2026-08-26 (mod-overseer#160, #167, #168).
OG_PLANNED = {"Og": ("tailoring", "enchanting")}


class SayKeyTest(unittest.TestCase):
    def test_the_key_is_speaker_subject_and_listener(self):
        self.assertEqual(
            chat.say_key(speaker="Og", subject="tailoring", listener="Grog"),
            ("og", "tailoring", "grog"),
        )

    def test_a_drifting_quantity_cannot_defeat_it(self):
        """20 Linen Cloth and 19 Linen Cloth are one thing to say."""
        self.assertEqual(
            chat.say_key(speaker="Grug", subject="Linen Cloth", listener="Og"),
            chat.say_key(speaker="Grug", subject="Linen Cloth", listener="Og"),
        )

    def test_names_are_matched_however_they_are_spelled(self):
        self.assertEqual(
            chat.say_key(speaker="OG", subject="Cloth", listener=" grog "),
            chat.say_key(speaker="og", subject="cloth", listener="Grog"),
        )

    def test_a_different_listener_is_a_different_line(self):
        self.assertNotEqual(
            chat.say_key(speaker="Og", subject="tailoring", listener="Grog"),
            chat.say_key(speaker="Og", subject="tailoring", listener="Grug"),
        )

    def test_a_missing_listener_is_still_a_key(self):
        self.assertEqual(
            chat.say_key(speaker="Og", subject="tailoring"),
            ("og", "tailoring", ""),
        )


class SayOnceTest(unittest.TestCase):
    def setUp(self):
        self.said: dict = {}
        self.key = chat.say_key(speaker="Og", subject="tailoring", listener="Grog")

    def test_a_thing_never_said_may_be_said(self):
        self.assertTrue(chat.should_say(self.said, self.key, now=100.0))

    def test_the_same_thing_is_not_said_twice_in_a_screenful(self):
        chat.remember_said(self.said, self.key, now=100.0)
        self.assertFalse(chat.should_say(self.said, self.key, now=160.0))

    def test_the_58_repeats_become_one(self):
        """The captured loop, replayed: 58 attempts three seconds apart."""
        spoken = 0
        for tick in range(58):
            now = 100.0 + tick * 3.0
            if chat.should_say(self.said, self.key, now=now):
                spoken += 1
                chat.remember_said(self.said, self.key, now=now)
        self.assertEqual(spoken, 1)

    def test_it_may_be_said_again_once_the_cooldown_has_passed(self):
        chat.remember_said(self.said, self.key, now=100.0)
        self.assertTrue(chat.should_say(
            self.said, self.key, now=100.0 + chat.SAY_ONCE_SECONDS
        ))

    def test_a_different_intent_is_not_silenced_by_this_one(self):
        chat.remember_said(self.said, self.key, now=100.0)
        other = chat.say_key(speaker="Grug", subject="Linen Cloth", listener="Og")
        self.assertTrue(chat.should_say(self.said, other, now=101.0))

    def test_expired_entries_are_forgotten_rather_than_accumulating(self):
        for tick in range(5):
            chat.remember_said(
                self.said, chat.say_key(speaker="Og", subject=str(tick)),
                now=100.0 + tick,
            )
        chat.remember_said(self.said, self.key, now=100.0 + chat.SAY_ONCE_SECONDS * 2)
        self.assertEqual(list(self.said), [self.key])

    def test_a_caller_may_ask_for_a_shorter_cooldown(self):
        chat.remember_said(self.said, self.key, now=100.0, cooldown=10.0)
        self.assertTrue(chat.should_say(self.said, self.key, now=111.0, cooldown=10.0))

    def test_the_cooldown_is_long_enough_to_outlast_a_screenful(self):
        """Not an arbitrary number: a screenful of party chat during a fight
        is a couple of minutes, and kin's 90s answer-a-plea cooldown is the
        shortest thing in the service."""
        self.assertGreaterEqual(chat.SAY_ONCE_SECONDS, 600.0)


class AddressedToSelfTest(unittest.TestCase):
    def test_a_character_talking_to_itself_is_caught(self):
        self.assertTrue(chat.addressed_to_self("Og", "Og"))

    def test_case_does_not_rescue_it(self):
        self.assertTrue(chat.addressed_to_self("og", " OG "))

    def test_two_different_characters_are_not_self_address(self):
        self.assertFalse(chat.addressed_to_self("Og", "Grog"))

    def test_nobody_is_not_yourself(self):
        """An empty listener is a line said to the room, which is fine."""
        self.assertFalse(chat.addressed_to_self("Og", ""))
        self.assertFalse(chat.addressed_to_self("", ""))


class SkillStateTest(unittest.TestCase):
    def test_a_trade_in_character_skills_is_held(self):
        self.assertEqual(
            chat.skill_state("Og", "tailoring",
                             held={"Og": {"tailoring": 1}}, planned=OG_PLANNED),
            chat.HELD,
        )

    def test_the_live_family_is_learning_and_not_holding(self):
        """The fact the whole ticket turns on: Og does not know tailoring."""
        self.assertEqual(
            chat.skill_state("Og", "tailoring", held=OG_LIVE, planned=OG_PLANNED),
            chat.LEARNING,
        )

    def test_a_trade_neither_held_nor_planned_is_neither(self):
        self.assertEqual(
            chat.skill_state("Og", "blacksmithing", held=OG_LIVE, planned=OG_PLANNED),
            chat.UNSKILLED,
        )

    def test_the_world_outranks_the_queue(self):
        """A trade that is both held and still queued reads as held."""
        self.assertEqual(
            chat.skill_state("Og", "tailoring",
                             held={"Og": {"tailoring": 1}}, planned=OG_PLANNED),
            chat.HELD,
        )

    def test_a_character_nobody_has_read_holds_nothing(self):
        self.assertEqual(
            chat.skill_state("Og", "tailoring", held={}, planned={}),
            chat.UNSKILLED,
        )

    def test_names_and_skills_are_matched_however_they_are_spelled(self):
        self.assertEqual(
            chat.skill_state(" og ", "Tailoring",
                             held={"OG": {"TAILORING": 1}}, planned={}),
            chat.HELD,
        )

    def test_an_empty_question_is_never_a_claim(self):
        self.assertEqual(
            chat.skill_state("", "tailoring", held=OG_LIVE, planned=OG_PLANNED),
            chat.UNSKILLED,
        )
        self.assertEqual(
            chat.skill_state("Og", "", held=OG_LIVE, planned=OG_PLANNED),
            chat.UNSKILLED,
        )

    def test_a_skills_row_that_is_a_bare_list_works_too(self):
        """`held` is a mapping of name to skills; whether the skills arrive
        as a dict of values or a plain list is the caller's business."""
        self.assertEqual(
            chat.skill_state("Og", "tailoring",
                             held={"Og": ["tailoring"]}, planned={}),
            chat.HELD,
        )


class HonestClaimTest(unittest.TestCase):
    """The last gate, after the voice layer has reworded the line."""

    def test_a_held_trade_may_be_claimed_in_any_words(self):
        self.assertTrue(chat.honest_claim(
            "Og know tailoring. Og make it.", skill="tailoring", state=chat.HELD
        ))

    def test_the_captured_lie_is_refused(self):
        self.assertFalse(chat.honest_claim(
            "Og need cloth? Og know tailoring. Og make it, family just bring "
            "the stuff.",
            skill="tailoring", state=chat.LEARNING,
        ))

    def test_a_hedged_line_about_a_planned_trade_is_honest(self):
        self.assertTrue(chat.honest_claim(
            "Og no know tailoring yet. Og learning it.",
            skill="tailoring", state=chat.LEARNING,
        ))

    def test_a_line_that_never_names_the_trade_claims_nothing(self):
        self.assertTrue(chat.honest_claim(
            "Grug give Og 39 Linen Cloth.", skill="tailoring", state=chat.LEARNING
        ))

    def test_an_unlearned_trade_may_not_be_named_even_with_a_hedge(self):
        """There is nothing true to say about a trade nobody is getting."""
        self.assertFalse(chat.honest_claim(
            "Og learning blacksmithing.", skill="blacksmithing",
            state=chat.UNSKILLED,
        ))

    def test_the_trade_is_matched_as_a_whole_word(self):
        self.assertTrue(chat.honest_claim(
            "Og know tailoringcraft.", skill="tailoring", state=chat.LEARNING
        ))

    def test_no_trade_named_is_nothing_to_check(self):
        self.assertTrue(chat.honest_claim("Og hungry.", skill="", state=chat.UNSKILLED))

    def test_an_empty_line_is_honest_by_saying_nothing(self):
        self.assertTrue(chat.honest_claim("", skill="tailoring", state=chat.UNSKILLED))


class MidRunTest(unittest.TestCase):
    """Reading the room (mod-overseer#169, and Evan watching a pull stop).

    The live row, 2026-09-03: run 35864, map 36 (The Deadmines), state
    'active', members "Bork,Grog,Grug,Og,Ugga".
    """

    RUN = {
        "leader_name": "Bork", "map_id": 36, "state": "active",
        "members": "Bork,Grog,Grug,Og,Ugga",
    }
    JOBS = {"Bork": "dungeon", "Grog": "dungeon", "Grug": "dungeon",
            "Og": "dungeon", "Ugga": "dungeon"}

    def test_a_member_of_an_active_run_is_mid_run(self):
        self.assertTrue(chat.mid_run("Og", run=self.RUN, jobs=self.JOBS))

    def test_no_run_at_all_is_not_mid_run(self):
        self.assertFalse(chat.mid_run("Og", run=None, jobs=self.JOBS))

    def test_an_ended_run_is_not_mid_run(self):
        ended = dict(self.RUN, state="ended")
        self.assertFalse(chat.mid_run("Og", run=ended, jobs=self.JOBS))

    def test_somebody_outside_the_run_is_not_mid_run(self):
        self.assertFalse(chat.mid_run("Evan", run=self.RUN, jobs=self.JOBS))

    def test_the_member_list_is_read_however_it_is_spelled(self):
        spaced = dict(self.RUN, members=" bork , og ")
        self.assertTrue(chat.mid_run("Og", run=spaced, jobs={}))

    def test_a_run_row_with_no_members_falls_back_to_the_job(self):
        """Rows written before the members column was filled carry ''."""
        bare = dict(self.RUN, members="")
        self.assertTrue(chat.mid_run("Og", run=bare, jobs=self.JOBS))
        self.assertFalse(chat.mid_run("Og", run=bare, jobs={"Og": "quest"}))

    def test_the_job_alone_is_never_enough(self):
        """All five sit at job='dungeon' between runs as well, and that is
        not a reason to go quiet forever."""
        self.assertFalse(chat.mid_run("Og", run=None, jobs=self.JOBS))

    def test_a_member_list_beats_a_job(self):
        outside = dict(self.RUN, members="Bork,Grog")
        self.assertFalse(chat.mid_run("Og", run=outside, jobs=self.JOBS))

    def test_a_nameless_question_is_answered_no(self):
        self.assertFalse(chat.mid_run("", run=self.RUN, jobs=self.JOBS))

    def test_present_member_on_run_map_keeps_row_busy(self):
        self.assertTrue(chat.run_has_present_member(
            self.RUN, {"Og": 36, "Evan": 0}
        ))

    def test_members_elsewhere_release_stale_row(self):
        self.assertFalse(chat.run_has_present_member(
            self.RUN, {"Og": 0, "Bork": 0}
        ))

    def test_snapshot_read_failure_fails_closed(self):
        self.assertTrue(chat.run_has_present_member(self.RUN, None))

    def test_ended_or_missing_run_is_not_present(self):
        self.assertFalse(chat.run_has_present_member(None, {"Og": 36}))
        self.assertFalse(chat.run_has_present_member(
            dict(self.RUN, state="ended"), {"Og": 36}
        ))

    def test_legacy_run_without_members_uses_any_live_snapshot(self):
        bare = dict(self.RUN, members="")
        self.assertTrue(chat.run_has_present_member(bare, {"Og": 36}))
        self.assertFalse(chat.run_has_present_member(bare, {}))

    def test_the_busy_jobs_are_real_job_modes(self):
        """A typo here would silence nothing forever, in silence."""
        for mode in chat.BUSY_JOBS:
            with self.subTest(mode=mode):
                self.assertIn(mode, jobs.MODES)


class StandDownTest(unittest.TestCase):
    def test_it_says_not_now_and_where_they_are(self):
        said = chat.stand_down("Og", subject="cloth", place="The Deadmines")
        self.assertIn("not now", said)
        self.assertIn("The Deadmines", said)
        self.assertIn("Cloth wait", said)

    def test_it_names_the_speaker_so_the_line_reads_as_theirs(self):
        self.assertTrue(chat.stand_down("Og", subject="cloth").startswith("Og"))

    def test_an_unknown_place_still_reads_as_a_sentence(self):
        said = chat.stand_down("Og", subject="cloth")
        self.assertIn("deep place", said)

    def test_it_is_short_enough_to_survive_the_voice_layer(self):
        said = chat.stand_down("Og", subject="Bolt of Linen Cloth",
                               place="The Deadmines")
        self.assertLessEqual(len(said), persona.MAX_SPOKEN)

    def test_it_claims_no_trade(self):
        said = chat.stand_down("Og", subject="cloth", place="The Deadmines")
        self.assertTrue(
            chat.honest_claim(said, skill="tailoring", state=chat.UNSKILLED)
        )


if __name__ == "__main__":
    unittest.main()
