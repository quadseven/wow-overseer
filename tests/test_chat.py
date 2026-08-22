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


if __name__ == "__main__":
    unittest.main()
