"""Behavioral tests for group targeting: an expression plus a roster in,
the exact set of characters that will get command rows out.

No Discord, no MySQL, no LLM - resolution is pure, which is what makes the
cap, the ordering and the muster arithmetic provable (infra#2605).
"""
import unittest

from fanout import (
    MAX_FANOUT_TARGETS,
    describe_expression,
    muster_report,
    resolve_targets,
    split_group_order,
    thought_text,
)

# guildid -> name, exactly the shape acore_characters.guild yields.
GUILDS = {3: "Argentum", 12: "Rangers of Vengeance"}

ORC = 2
HUMAN = 1


def _row(name, level=60, race=ORC, guild_id=0, bot=1):
    """One overseer_snapshot row, trimmed to what resolution reads."""
    return {
        "name": name,
        "level": level,
        "race": race,
        "map_id": 1,
        "in_combat": 0,
        "is_bot": bot,
        "guild_id": guild_id,
    }


class GuildTargetingTest(unittest.TestCase):
    def test_guild_members_answer_and_outsiders_do_not(self):
        roster = [_row("Grug", guild_id=3), _row("Bork", guild_id=3), _row("Vely")]
        names, reason = resolve_targets("guild Argentum", roster, GUILDS)
        self.assertEqual(sorted(names), ["Bork", "Grug"])
        self.assertIn("Argentum", reason)

    def test_guild_name_is_matched_case_insensitively(self):
        roster = [_row("Grug", guild_id=3)]
        names, _ = resolve_targets("guild aRgEnTuM", roster, GUILDS)
        self.assertEqual(names, ["Grug"])

    def test_reason_uses_the_realms_spelling_not_the_typists(self):
        roster = [_row("Grug", guild_id=3)]
        _, reason = resolve_targets("guild argentum", roster, GUILDS)
        self.assertIn("Argentum", reason)

    def test_multi_word_guild_name_resolves(self):
        roster = [_row("Grug", guild_id=12)]
        names, _ = resolve_targets("guild Rangers of Vengeance", roster, GUILDS)
        self.assertEqual(names, ["Grug"])

    def test_unknown_guild_refuses_and_hints_at_quoting(self):
        names, reason = resolve_targets("guild Rangers", [_row("Grug")], GUILDS)
        self.assertEqual(names, [])
        self.assertIn("Rangers", reason)
        self.assertIn("quote", reason.lower())

    def test_guild_with_nobody_in_the_world_refuses(self):
        names, reason = resolve_targets("guild Argentum", [_row("Vely")], GUILDS)
        self.assertEqual(names, [])
        self.assertIn("Argentum", reason)

    def test_missing_guild_name_refuses(self):
        names, reason = resolve_targets("guild", [_row("Grug", guild_id=3)], GUILDS)
        self.assertEqual(names, [])
        self.assertIn("guild", reason.lower())

    def test_a_guild_name_never_reaches_resolution_as_a_pattern(self):
        # The typed name only ever selects from the map handed in; nothing
        # about it can widen the match.
        names, reason = resolve_targets("guild %", [_row("Grug", guild_id=3)], GUILDS)
        self.assertEqual(names, [])
        self.assertIn("no guild", reason.lower())


class FactionTargetingTest(unittest.TestCase):
    def test_horde_takes_horde_races_only(self):
        roster = [_row("Grug", race=2), _row("Vely", race=5), _row("Aldo", race=HUMAN)]
        names, reason = resolve_targets("horde", roster, GUILDS)
        self.assertEqual(sorted(names), ["Grug", "Vely"])
        self.assertIn("Horde", reason)

    def test_alliance_takes_alliance_races_only(self):
        roster = [_row("Aldo", race=HUMAN), _row("Nimi", race=4), _row("Grug", race=2)]
        names, reason = resolve_targets("alliance", roster, GUILDS)
        self.assertEqual(sorted(names), ["Aldo", "Nimi"])
        self.assertIn("Alliance", reason)

    def test_a_faction_with_nobody_in_the_world_refuses(self):
        names, reason = resolve_targets("alliance", [_row("Grug", race=2)], GUILDS)
        self.assertEqual(names, [])
        self.assertIn("Alliance", reason)

    def test_unknown_race_ids_belong_to_neither_faction(self):
        roster = [_row("Thing", race=99)]
        self.assertEqual(resolve_targets("horde", roster, GUILDS)[0], [])
        self.assertEqual(resolve_targets("alliance", roster, GUILDS)[0], [])


class EveryoneTest(unittest.TestCase):
    def test_everyone_takes_the_whole_world(self):
        roster = [_row("Grug", race=2), _row("Aldo", race=HUMAN), _row("Thing", race=99)]
        names, _ = resolve_targets("everyone", roster, GUILDS)
        self.assertEqual(sorted(names), ["Aldo", "Grug", "Thing"])

    def test_all_is_a_synonym_for_everyone(self):
        # Typing "@everyone" in Discord pings the whole server; "@all" is
        # the same order without the siren.
        roster = [_row("Grug")]
        self.assertEqual(resolve_targets("all", roster, GUILDS)[0], ["Grug"])

    def test_an_empty_world_refuses(self):
        names, reason = resolve_targets("everyone", [], GUILDS)
        self.assertEqual(names, [])
        self.assertIn("world", reason.lower())


class CommandableTest(unittest.TestCase):
    def test_characters_without_bot_ai_are_never_mustered(self):
        # mod-overseer can only whisper to a character that has a
        # PlayerbotAI; a row for a mortal is a guaranteed error row, and it
        # would make the muster count lie.
        roster = [_row("Grug"), _row("Evan", bot=0)]
        names, _ = resolve_targets("everyone", roster, GUILDS)
        self.assertEqual(names, ["Grug"])

    def test_a_world_of_only_mortals_refuses(self):
        names, reason = resolve_targets("everyone", [_row("Evan", bot=0)], GUILDS)
        self.assertEqual(names, [])
        self.assertTrue(reason)


class CapTest(unittest.TestCase):
    def _crowd(self, size):
        return [_row(f"Bot{i:03d}", level=1 + i % 60) for i in range(size)]

    def test_the_band_never_exceeds_the_cap(self):
        names, _ = resolve_targets("everyone", self._crowd(MAX_FANOUT_TARGETS + 25), GUILDS)
        self.assertEqual(len(names), MAX_FANOUT_TARGETS)

    def test_truncation_is_never_silent(self):
        crowd = self._crowd(MAX_FANOUT_TARGETS + 25)
        _, reason = resolve_targets("everyone", crowd, GUILDS)
        self.assertIn("25", reason)
        self.assertIn(str(MAX_FANOUT_TARGETS), reason)
        self.assertIn(str(len(crowd)), reason)

    def test_an_uncapped_band_says_nothing_about_the_cap(self):
        _, reason = resolve_targets("everyone", self._crowd(3), GUILDS)
        self.assertNotIn("left behind", reason)

    def test_the_cap_keeps_the_strongest(self):
        roster = [_row("Weak", level=5), _row("Mid", level=40), _row("Strong", level=60)]
        names, _ = resolve_targets("everyone", roster, GUILDS)
        self.assertEqual(names, ["Strong", "Mid", "Weak"])

    def test_level_ties_break_alphabetically(self):
        roster = [_row("Zed", level=10), _row("Abe", level=10), _row("Mia", level=10)]
        names, _ = resolve_targets("everyone", roster, GUILDS)
        self.assertEqual(names, ["Abe", "Mia", "Zed"])

    def test_selection_is_stable_across_shuffled_input(self):
        crowd = self._crowd(MAX_FANOUT_TARGETS + 25)
        first, _ = resolve_targets("everyone", crowd, GUILDS)
        second, _ = resolve_targets("everyone", list(reversed(crowd)), GUILDS)
        self.assertEqual(first, second)


class UnknownExpressionTest(unittest.TestCase):
    def test_a_word_that_names_no_group_refuses_with_usage(self):
        names, reason = resolve_targets("legion", [_row("Grug")], GUILDS)
        self.assertEqual(names, [])
        self.assertIn("@guild", reason)


class MusterReportTest(unittest.TestCase):
    def test_report_counts_rows_written_not_rows_intended(self):
        text = muster_report(reason="the guild Argentum", command="follow", called=15, written=12)
        self.assertIn("12", text)
        self.assertIn("3 could not be queued", text)

    def test_a_clean_muster_reports_only_what_landed(self):
        text = muster_report(reason="the Horde", command="grind", called=40, written=40)
        self.assertIn("40 orders queued", text)
        self.assertIn("grind", text)
        self.assertNotIn("could not be queued", text)

    def test_total_failure_says_so_plainly(self):
        text = muster_report(reason="the Horde", command="grind", called=40, written=0)
        self.assertIn("not one order", text)

    def test_a_band_of_one_reads_as_one_order(self):
        text = muster_report(reason="the guild Argentum", command="stay", called=1, written=1)
        self.assertIn("1 order queued", text)

    def test_the_reason_carries_the_cap_arithmetic_into_the_report(self):
        _, reason = resolve_targets(
            "everyone", [_row(f"Bot{i:03d}") for i in range(MAX_FANOUT_TARGETS + 7)], GUILDS
        )
        text = muster_report(
            reason=reason, command="follow", called=MAX_FANOUT_TARGETS, written=MAX_FANOUT_TARGETS
        )
        self.assertIn("7 left behind", text)


class ThoughtTest(unittest.TestCase):
    def test_a_participant_remembers_the_call_and_the_order(self):
        text = thought_text("guild Argentum", "follow")
        self.assertIn("Argentum", text)
        self.assertIn("follow", text)

    def test_the_thought_carries_no_cap_bookkeeping(self):
        text = thought_text("horde", "grind")
        self.assertIn("Horde", text)
        self.assertNotIn("cap", text.lower())


class DescribeExpressionTest(unittest.TestCase):
    def test_factions_and_guilds_read_as_english(self):
        self.assertEqual(describe_expression("horde"), "the Horde")
        self.assertEqual(describe_expression("alliance"), "the Alliance")
        self.assertEqual(describe_expression("guild Argentum"), "the guild Argentum")
        self.assertIn("world", describe_expression("everyone"))


class SplitGroupOrderTest(unittest.TestCase):
    def test_a_character_name_is_not_a_group(self):
        self.assertIsNone(split_group_order("Grug", "follow"))

    def test_faction_head_keeps_the_whole_rest_as_the_order(self):
        self.assertEqual(split_group_order("horde", "raid Astranaar tonight"),
                         ("horde", "raid Astranaar tonight"))

    def test_group_words_are_recognized_whatever_the_case(self):
        self.assertEqual(split_group_order("HORDE", "grind"), ("horde", "grind"))

    def test_single_word_guild_name_splits_off_the_order(self):
        self.assertEqual(split_group_order("guild", "Argentum follow"),
                         ("guild Argentum", "follow"))

    def test_quoted_guild_name_keeps_its_spaces(self):
        self.assertEqual(
            split_group_order("guild", '"Rangers of Vengeance" follow'),
            ("guild Rangers of Vengeance", "follow"),
        )

    def test_single_quotes_work_too(self):
        self.assertEqual(
            split_group_order("guild", "'Lost Armada' stay"),
            ("guild Lost Armada", "stay"),
        )

    def test_guild_with_no_name_yields_a_nameless_expression(self):
        self.assertEqual(split_group_order("guild", ""), ("guild", ""))

    def test_unterminated_quote_yields_a_nameless_expression(self):
        self.assertEqual(split_group_order("guild", '"Rangers of Vengeance follow'),
                         ("guild", ""))


if __name__ == "__main__":
    unittest.main()
