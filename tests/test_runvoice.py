"""Tests for runvoice.py: party and guild chat during runs."""

import unittest

import runvoice


class RunVoiceStateTest(unittest.TestCase):
    def setUp(self):
        self.state = runvoice.RunVoiceState(run_id=1, started_at=1000.0)

    def test_new_intent_may_be_said(self):
        key = ("og", "boss_kill:razorgore", "")
        self.assertTrue(runvoice.should_say_run(self.state, key, now=1000.0))

    def test_same_intent_not_said_twice_in_window(self):
        key = ("og", "boss_kill:razorgore", "")
        runvoice.remember_said_run(self.state, key, now=1000.0)
        self.assertFalse(runvoice.should_say_run(self.state, key, now=1060.0))

    def test_same_intent_said_after_cooldown(self):
        key = ("og", "boss_kill:razorgore", "")
        runvoice.remember_said_run(self.state, key, now=1000.0)
        self.assertTrue(
            runvoice.should_say_run(
                self.state, key, now=1000.0 + runvoice.RUN_SAY_ONCE_SECONDS
            )
        )

    def test_different_intent_not_silenced(self):
        key1 = ("og", "boss_kill:razorgore", "")
        key2 = ("og", "death:grug", "")
        runvoice.remember_said_run(self.state, key1, now=1000.0)
        self.assertTrue(runvoice.should_say_run(self.state, key2, now=1001.0))

    def test_expired_entries_forgotten(self):
        for i in range(3):
            runvoice.remember_said_run(
                self.state, ("og", f"subject{i}", ""), now=1000.0 + i
            )
        runvoice.remember_said_run(
            self.state,
            ("og", "boss_kill:razorgore", ""),
            now=1000.0 + runvoice.RUN_SAY_ONCE_SECONDS * 2,
        )
        self.assertEqual(len(self.state.said), 1)
        self.assertIn(("og", "boss_kill:razorgore", ""), self.state.said)


class FormatItemLinkTest(unittest.TestCase):
    def test_epic_item_link(self):
        link = runvoice._format_item_link("Sulfuras", 17182, 4)
        self.assertIn("|cffa335ee", link)
        self.assertIn("|Hitem:17182|h", link)
        self.assertIn("[Sulfuras]", link)

    def test_rare_item_link(self):
        link = runvoice._format_item_link("Obsidian Edged Blade", 18423, 3)
        self.assertIn("|cff0070dd", link)

    def test_uncommon_item_link(self):
        link = runvoice._format_item_link("Green Lens", 18250, 2)
        self.assertIn("|cff1eff00", link)


class ExcitementForQualityTest(unittest.TestCase):
    def test_epic_excitement(self):
        self.assertEqual(runvoice._excitement_for_quality(4), "!!")
        self.assertEqual(runvoice._excitement_for_quality(5), "!!")

    def test_rare_excitement(self):
        self.assertEqual(runvoice._excitement_for_quality(3), "!")

    def test_uncommon_no_excitement(self):
        self.assertEqual(runvoice._excitement_for_quality(2), "")

    def test_common_no_excitement(self):
        self.assertEqual(runvoice._excitement_for_quality(1), "")


class PartyLinesTest(unittest.TestCase):
    def setUp(self):
        self.members = frozenset({"Grug", "Ugga", "Grog", "Bork", "Og"})
        self.state = runvoice.RunVoiceState(run_id=1, started_at=1000.0)
        runvoice._set_random_seed(42)

    def test_boss_kill_generates_line(self):
        event = runvoice.RunEvent(
            kind="boss_kill", run_id=1, boss_name="Princess Theradras"
        )
        lines = runvoice.generate_party_lines(
            event, self.members, self.state, now=1000.0
        )
        self.assertEqual(len(lines), 1)
        speaker, line = lines[0]
        self.assertIn(speaker, self.members)
        self.assertIn("Princess Theradras", line)

    def test_boss_kill_not_repeated_same_run(self):
        event = runvoice.RunEvent(
            kind="boss_kill", run_id=1, boss_name="Princess Theradras"
        )
        lines1 = runvoice.generate_party_lines(
            event, self.members, self.state, now=1000.0
        )
        lines2 = runvoice.generate_party_lines(
            event, self.members, self.state, now=1060.0
        )
        self.assertEqual(len(lines1), 1)
        self.assertEqual(len(lines2), 0)

    def test_death_generates_line(self):
        event = runvoice.RunEvent(kind="death", run_id=1, character="Og")
        lines = runvoice.generate_party_lines(
            event, self.members, self.state, now=1000.0
        )
        self.assertEqual(len(lines), 1)
        speaker, line = lines[0]
        self.assertNotEqual(speaker, "Og")  # Should not be the dead person
        self.assertIn("Og", line)

    def test_wipe_generates_line(self):
        event = runvoice.RunEvent(kind="wipe", run_id=1)
        lines = runvoice.generate_party_lines(
            event, self.members, self.state, now=1000.0
        )
        self.assertEqual(len(lines), 1)
        speaker, line = lines[0]
        self.assertIn(speaker, self.members)

    def test_item_loot_generates_line_with_link(self):
        event = runvoice.RunEvent(
            kind="item_loot",
            run_id=1,
            character="Grug",
            item_name="Sulfuras",
            item_id=17182,
            item_quality=4,
        )
        lines = runvoice.generate_party_lines(
            event, self.members, self.state, now=1000.0
        )
        self.assertEqual(len(lines), 1)
        speaker, line = lines[0]
        self.assertIn("|Hitem:17182|h[Sulfuras]|h", line)
        self.assertIn("!!", line)  # Epic excitement

    def test_item_loot_rare_excitement(self):
        event = runvoice.RunEvent(
            kind="item_loot",
            run_id=1,
            character="Grug",
            item_name="Obsidian Edged Blade",
            item_id=18423,
            item_quality=3,
        )
        lines = runvoice.generate_party_lines(
            event, self.members, self.state, now=1000.0
        )
        self.assertEqual(len(lines), 1)
        _, line = lines[0]
        self.assertIn("!", line)  # Rare excitement

    def test_item_loot_uncommon_no_excitement(self):
        event = runvoice.RunEvent(
            kind="item_loot",
            run_id=1,
            character="Grug",
            item_name="Green Lens",
            item_id=18250,
            item_quality=2,
        )
        lines = runvoice.generate_party_lines(
            event, self.members, self.state, now=1000.0
        )
        self.assertEqual(len(lines), 1)
        _, line = lines[0]
        self.assertNotIn("!", line)
        self.assertNotIn("!!", line)

    def test_wing_done_generates_line(self):
        event = runvoice.RunEvent(
            kind="wing_done", run_id=1, wing_name="The Wicked Grotto"
        )
        lines = runvoice.generate_party_lines(
            event, self.members, self.state, now=1000.0
        )
        self.assertEqual(len(lines), 1)
        _, line = lines[0]
        self.assertIn("Wicked Grotto", line)

    def test_stall_generates_line(self):
        event = runvoice.RunEvent(kind="stall", run_id=1)
        lines = runvoice.generate_party_lines(
            event, self.members, self.state, now=1000.0
        )
        self.assertEqual(len(lines), 1)
        _, line = lines[0]
        self.assertIn("stuck", line.lower())

    def test_different_speakers_for_different_events(self):
        """Different events should be able to have different speakers."""
        event1 = runvoice.RunEvent(kind="boss_kill", run_id=1, boss_name="Boss1")
        event2 = runvoice.RunEvent(kind="boss_kill", run_id=1, boss_name="Boss2")

        lines1 = runvoice.generate_party_lines(
            event1, self.members, self.state, now=1000.0
        )
        lines2 = runvoice.generate_party_lines(
            event2, self.members, self.state, now=1001.0
        )

        self.assertEqual(len(lines1), 1)
        self.assertEqual(len(lines2), 1)
        # They could be the same speaker by chance, but different intents


class GuildLinesTest(unittest.TestCase):
    def setUp(self):
        self.guild_members = frozenset(
            {"Grug", "Ugga", "Grog", "Bork", "Og", "Stranger1", "Stranger2"}
        )
        self.guild_said = {}
        runvoice._set_random_seed(123)

    def test_epic_drop_guild_echo(self):
        event = runvoice.RunEvent(
            kind="item_loot",
            run_id=1,
            character="Grug",
            item_name="Sulfuras",
            item_id=17182,
            item_quality=4,
        )
        lines = runvoice.generate_guild_lines(
            event,
            self.guild_members,
            self.guild_said,
            now=1000.0,
            is_guild_first=False,
            is_family_first=True,
            place="Molten Core",
        )
        self.assertEqual(len(lines), 1)
        speaker, line = lines[0]
        self.assertIn(speaker, self.guild_members)
        self.assertIn("Sulfuras", line)
        self.assertIn("Molten Core", line)

    def test_epic_drop_not_repeated(self):
        event = runvoice.RunEvent(
            kind="item_loot",
            run_id=1,
            character="Grug",
            item_name="Sulfuras",
            item_id=17182,
            item_quality=4,
        )
        lines1 = runvoice.generate_guild_lines(
            event, self.guild_members, self.guild_said, now=1000.0, is_family_first=True
        )
        lines2 = runvoice.generate_guild_lines(
            event, self.guild_members, self.guild_said, now=1060.0, is_family_first=True
        )
        self.assertEqual(len(lines1), 1)
        self.assertEqual(len(lines2), 0)

    def test_first_kill_guild_announce(self):
        event = runvoice.RunEvent(
            kind="boss_kill", run_id=1, character="Grug", boss_name="Ragnaros"
        )
        lines = runvoice.generate_guild_lines(
            event,
            self.guild_members,
            self.guild_said,
            now=1000.0,
            is_guild_first=True,
            place="Molten Core",
        )
        self.assertEqual(len(lines), 1)
        _, line = lines[0]
        self.assertIn("Ragnaros", line)
        self.assertIn("Grug", line)

    def test_ding_at_round_number(self):
        event = runvoice.RunEvent(
            kind="level_up", run_id=1, character="Og", detail="60"
        )
        lines = runvoice.generate_guild_lines(
            event, self.guild_members, self.guild_said, now=1000.0
        )
        self.assertEqual(len(lines), 1)
        _, line = lines[0]
        self.assertIn("60", line)
        self.assertIn("Og", line)

    def test_ding_not_at_round_number_silent(self):
        event = runvoice.RunEvent(
            kind="level_up", run_id=1, character="Og", detail="57"
        )
        lines = runvoice.generate_guild_lines(
            event, self.guild_members, self.guild_said, now=1000.0
        )
        self.assertEqual(len(lines), 0)

    def test_class_quest_help(self):
        event = runvoice.RunEvent(kind="class_quest_help", run_id=1, character="Grug")
        lines = runvoice.generate_guild_lines(
            event, self.guild_members, self.guild_said, now=1000.0
        )
        self.assertEqual(len(lines), 1)
        _, line = lines[0]
        self.assertIn("class quest", line.lower())


class ParseDungeonRunEventsTest(unittest.TestCase):
    def test_boss_kill_parsed(self):
        rows = [
            {"run_id": 1, "kind": "boss", "detail": "1 encounter done, 2 of 5 in all"}
        ]
        events = runvoice.parse_dungeon_run_events(rows)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].kind, "boss_kill")
        self.assertEqual(events[0].run_id, 1)

    def test_wipe_parsed(self):
        rows = [{"run_id": 1, "kind": "wipe", "detail": "the raid wiped (wipe 1)"}]
        events = runvoice.parse_dungeon_run_events(rows)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].kind, "wipe")

    def test_stall_parsed(self):
        rows = [
            {"run_id": 1, "kind": "stalled", "detail": "nothing left it could reach"}
        ]
        events = runvoice.parse_dungeon_run_events(rows)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].kind, "stall")

    def test_complete_parsed(self):
        rows = [{"run_id": 1, "kind": "complete", "detail": "every encounter credited"}]
        events = runvoice.parse_dungeon_run_events(rows)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].kind, "wing_done")

    def test_multiple_events_parsed(self):
        rows = [
            {"run_id": 1, "kind": "boss", "detail": "1 encounter done"},
            {"run_id": 1, "kind": "wipe", "detail": "wiped"},
            {"run_id": 1, "kind": "stalled", "detail": "stalled"},
        ]
        events = runvoice.parse_dungeon_run_events(rows)
        self.assertEqual(len(events), 3)


class ParseOverseerEventsTest(unittest.TestCase):
    def test_boss_kill_parsed(self):
        rows = [
            {
                "kind": "boss_kill",
                "character_name": "Grug",
                "subject_name": "Ragnaros",
                "subject_id": 11502,
            }
        ]
        events = runvoice.parse_overseer_events(rows)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].kind, "boss_kill")
        self.assertEqual(events[0].character, "Grug")
        self.assertEqual(events[0].boss_name, "Ragnaros")

    def test_death_parsed(self):
        rows = [{"kind": "death", "character_name": "Og"}]
        events = runvoice.parse_overseer_events(rows)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].kind, "death")
        self.assertEqual(events[0].character, "Og")

    def test_level_up_parsed(self):
        rows = [{"kind": "level_up", "character_name": "Og", "subject_id": 60}]
        events = runvoice.parse_overseer_events(rows)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].kind, "level_up")
        self.assertEqual(events[0].character, "Og")
        self.assertEqual(events[0].detail, "60")

    def test_item_loot_parsed(self):
        rows = [
            {
                "kind": "item_loot",
                "character_name": "Grug",
                "subject_name": "Sulfuras",
                "subject_id": 17182,
                "detail": "epic",
            }
        ]
        events = runvoice.parse_overseer_events(rows)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].kind, "item_loot")
        self.assertEqual(events[0].character, "Grug")
        self.assertEqual(events[0].item_name, "Sulfuras")
        self.assertEqual(events[0].item_id, 17182)
        self.assertEqual(events[0].item_quality, 4)


if __name__ == "__main__":
    unittest.main()
