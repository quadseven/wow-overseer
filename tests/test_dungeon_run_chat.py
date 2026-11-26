import unittest
import unittest.mock as mock
from unittest import mock as mock_module
import sys
from unittest.mock import MagicMock, patch

# Mock discord before importing bridge
sys.modules['discord'] = MagicMock()

import bridge
from _stub_modules import PYMYSQL, stub_modules

with stub_modules(pymysql=PYMYSQL):
    import apiv2

import chat
import core
import dungeonpath
import events
import relay
import spoken


class PartyChatDuringRunsTest(unittest.TestCase):
    """Party chat reactions to dungeon run events."""

    @patch('bridge._fetch_dungeon_run_events')
    @patch('bridge._fetch_enabled_names')
    @patch('bridge._generate_party_chat_from_events')
    @patch('bridge._generate_guild_chat_from_events')
    @patch('bridge.CHAT_CHANNEL_ID', '1234567890')
    def test_dungeon_chat_pass_generates_chat(self, mock_guild_chat, mock_party_chat, mock_names, mock_events):
        """The dungeon chat generation pass generates party and guild chat lines."""
        mock_names.return_value = ['Grog', 'Og', 'Grug', 'Ugga', 'Bree']
        mock_events.return_value = []
        mock_guild_chat.return_value = []
        
        bridge.Bridge(None)._dungeon_chat_generation()
        
        mock_names.assert_called_once()
        mock_events.assert_called_once()

    @patch('bridge._fetch_dungeon_run_events')
    @patch('bridge._fetch_enabled_names')
    @patch('bridge._generate_party_chat_from_events')
    @patch('bridge._generate_guild_chat_from_events')
    @patch('bridge.CHAT_CHANNEL_ID', '1234567890')
    def test_dungeon_chat_skips_when_no_family(self, mock_guild_chat, mock_party_chat, mock_names, mock_events):
        """When no family is found, the pass does nothing."""
        mock_names.return_value = []
        mock_events.return_value = []
        mock_guild_chat.return_value = []
        
        bridge.Bridge(None)._dungeon_chat_generation()
        
        mock_names.assert_called_once()
        mock_guild_chat.assert_not_called()

    @patch('bridge._fetch_dungeon_run_events')
    @patch('bridge._fetch_enabled_names')
    @patch('bridge._generate_party_chat_from_events')
    @patch('bridge._generate_guild_chat_from_events')
    @patch('bridge.CHAT_CHANNEL_ID', None)
    def test_dungeon_chat_skips_when_no_channel(self, mock_guild_chat, mock_party_chat, mock_names, mock_events):
        """When CHAT_CHANNEL_ID is unset, the pass does nothing."""
        mock_names.return_value = ['Grog', 'Og']
        mock_events.return_value = []
        mock_guild_chat.return_value = []
        
        bridge.Bridge(None)._dungeon_chat_generation()
        
        mock_guild_chat.assert_not_called()
        mock_party_chat.assert_not_called()

    @patch('bridge._fetch_dungeon_run_events')
    @patch('bridge._fetch_enabled_names')
    @patch('bridge._generate_party_chat_from_events')
    @patch('bridge._generate_guild_chat_from_events')
    @patch('bridge.CHAT_CHANNEL_ID', '1234567890')
    def test_dungeon_chat_handles_fetch_error(self, mock_guild_chat, mock_party_chat, mock_names, mock_events):
        """When fetching events fails, the pass handles it gracefully."""
        mock_names.return_value = ['Grog', 'Og']
        mock_events.side_effect = Exception("Database error")
        mock_guild_chat.return_value = []
        
        bridge.Bridge(None)._dungeon_chat_generation()
        
        mock_names.assert_called_once()


class GuildChatEchoingEventsTest(unittest.TestCase):
    """Guild chat echoes notable run events."""

    @patch('bridge._fetch_dungeon_run_events')
    @patch('bridge._fetch_enabled_names')
    @patch('bridge._generate_guild_chat_from_events')
    @patch('bridge.CHAT_CHANNEL_ID', '1234567890')
    def test_guild_chat_generation_fires(self, mock_guild_chat, mock_names, mock_events):
        """Guild chat generation is called during the pass."""
        mock_names.return_value = ['Grog', 'Og', 'Grug', 'Ugga', 'Bree']
        mock_events.return_value = []
        mock_guild_chat.return_value = ['First boss down in deadmines!']
        
        bridge.Bridge(None)._dungeon_chat_generation()
        
        mock_guild_chat.assert_called_once()

    @patch('bridge._fetch_dungeon_run_events')
    @patch('bridge._fetch_enabled_names')
    @patch('bridge._generate_guild_chat_from_events')
    @patch('bridge.CHAT_CHANNEL_ID', '1234567890')
    def test_guild_chat_handles_error(self, mock_guild_chat, mock_names, mock_events):
        """When generating guild chat fails, the pass handles it gracefully."""
        mock_names.return_value = ['Grog', 'Og']
        mock_events.side_effect = Exception("Database error")
        mock_guild_chat.return_value = []
        
        bridge.Bridge(None)._dungeon_chat_generation()
        
        mock_guild_chat.assert_called_once()


if __name__ == "__main__":
    unittest.main()
    """Party chat reactions to dungeon run events."""

    def test_boss_kill_generates_party_chat(self):
        """A boss kill in a dungeon generates short party chat lines."""
        with mock_module.patch.object(
            bridge,
            "_connect",
            return_value=mock.MagicMock(
                cursor=lambda: mock.MagicMock(
                    execute=lambda sql, params=None: None,
                    fetchall=lambda: [
                        {
                            "id": 1,
                            "family": "grug",
                            "leader_name": "Grug",
                            "character_name": "Grog",
                            "run_id": 100,
                            "campaign_id": 1,
                            "run_number": 1,
                            "portal": "deadmines",
                            "phase": "CLEARING",
                            "kind": "boss",
                            "detail": "1 encounter credited, 5 in all (mask 16 -> 32)",
                            "created_at": "2026-11-26 15:30:00",
                        }
                    ],
                )
            ),
        ):
            rows = bridge._fetch_dungeon_run_events("grug", "boss", 1)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["kind"], "boss")
            self.assertIn("1 encounter credited", rows[0]["detail"])

    def test_member_death_generates_party_chat(self):
        """A member death generates a party chat line."""
        with mock_module.patch.object(
            bridge,
            "_connect",
            return_value=mock.MagicMock(
                cursor=lambda: mock.MagicMock(
                    execute=lambda sql, params=None: None,
                    fetchall=lambda: [
                        {
                            "id": 2,
                            "family": "grug",
                            "leader_name": "Grug",
                            "character_name": "Og",
                            "run_id": 100,
                            "campaign_id": 1,
                            "run_number": 1,
                            "portal": "deadmines",
                            "phase": "CLEARING",
                            "kind": "dc_off",
                            "detail": "Og disconnected",
                            "created_at": "2026-11-26 15:35:00",
                        }
                    ],
                )
            ),
        ):
            rows = bridge._fetch_dungeon_run_events("grug", "dc_off", 1)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["kind"], "dc_off")
            self.assertEqual(rows[0]["character_name"], "Og")

    def test_run_complete_generates_party_chat(self):
        """A completed run generates a wrap-up line."""
        with mock_module.patch.object(
            bridge,
            "_connect",
            return_value=mock.MagicMock(
                cursor=lambda: mock.MagicMock(
                    execute=lambda sql, params=None: None,
                    fetchall=lambda: [
                        {
                            "id": 3,
                            "family": "grug",
                            "leader_name": "Grug",
                            "character_name": "Grug",
                            "run_id": 100,
                            "campaign_id": 1,
                            "run_number": 1,
                            "portal": "deadmines",
                            "phase": "EXIT",
                            "kind": "complete",
                            "detail": "every encounter the map credits has been credited",
                            "created_at": "2026-11-26 16:00:00",
                        }
                    ],
                )
            ),
        ):
            rows = bridge._fetch_dungeon_run_events("grug", "complete", 1)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["kind"], "complete")

    def test_no_duplicate_lines_in_same_run(self):
        """The same party chat line is not generated twice in one run."""
        with mock_module.patch.object(
            bridge,
            "_connect",
            return_value=mock.MagicMock(
                cursor=lambda: mock.MagicMock(
                    execute=lambda sql, params=None: None,
                    fetchall=lambda: [
                        {
                            "id": 1,
                            "family": "grug",
                            "leader_name": "Grug",
                            "character_name": "Grog",
                            "run_id": 100,
                            "campaign_id": 1,
                            "run_number": 1,
                            "portal": "deadmines",
                            "phase": "CLEARING",
                            "kind": "boss",
                            "detail": "1 encounter credited, 5 in all (mask 16 -> 32)",
                            "created_at": "2026-11-26 15:30:00",
                        },
                        {
                            "id": 2,
                            "family": "grug",
                            "leader_name": "Grug",
                            "character_name": "Grog",
                            "run_id": 100,
                            "campaign_id": 1,
                            "run_number": 1,
                            "portal": "deadmines",
                            "phase": "CLEARING",
                            "kind": "boss",
                            "detail": "1 encounter credited, 5 in all (mask 16 -> 32)",
                            "created_at": "2026-11-26 15:32:00",
                        },
                    ],
                )
            ),
        ):
            rows = bridge._fetch_dungeon_run_events("grug", "boss", 2)
            self.assertEqual(len(rows), 1)

    def test_chat_lines_are_sanitized(self):
        """Party chat lines have game markup stripped."""
        with mock_module.patch.object(
            bridge,
            "_connect",
            return_value=mock.MagicMock(
                cursor=lambda: mock.MagicMock(
                    execute=lambda sql, params=None: None,
                    fetchall=lambda: [
                        {
                            "id": 1,
                            "family": "grug",
                            "leader_name": "Grug",
                            "character_name": "Grog",
                            "run_id": 100,
                            "campaign_id": 1,
                            "run_number": 1,
                            "portal": "deadmines",
                            "phase": "CLEARING",
                            "kind": "boss",
                            "detail": "1 encounter credited, 5 in all (mask 16 -> 32)",
                            "created_at": "2026-11-26 15:30:00",
                        }
                    ],
                )
            ),
        ):
            rows = bridge._fetch_dungeon_run_events("grug", "boss", 1)
            text = relay.sanitize(str(rows[0]["detail"]))
            self.assertNotIn("|cffffffff", text)
            self.assertNotIn("|H", text)


class GuildChatEchoingEventsTest(unittest.TestCase):
    """Guild chat echoes notable run events."""

    def test_first_boss_kill_echoes_in_guild(self):
        """The first boss kill in a new dungeon echoes in guild chat."""
        with mock_module.patch.object(
            bridge,
            "_connect",
            return_value=mock.MagicMock(
                cursor=lambda: mock.MagicMock(
                    execute=lambda sql, params=None: None,
                    fetchall=lambda: [
                        {
                            "id": 1,
                            "family": "grug",
                            "leader_name": "Grug",
                            "character_name": "Grog",
                            "run_id": 100,
                            "campaign_id": 1,
                            "run_number": 1,
                            "portal": "deadmines",
                            "phase": "CLEARING",
                            "kind": "boss",
                            "detail": "1 encounter credited, 5 in all (mask 16 -> 32)",
                            "created_at": "2026-11-26 15:30:00",
                        }
                    ],
                )
            ),
        ):
            guild_lines = bridge._generate_guild_chat_from_events("grug")
            self.assertGreater(len(guild_lines), 0)
            self.assertIn("deadmines", guild_lines[0])
            self.assertIn("first", guild_lines[0])

    def test_completed_run_echoes_in_guild(self):
        """A completed dungeon run echoes in guild chat."""
        with mock_module.patch.object(
            bridge,
            "_connect",
            return_value=mock.MagicMock(
                cursor=lambda: mock.MagicMock(
                    execute=lambda sql, params=None: None,
                    fetchall=lambda: [
                        {
                            "id": 1,
                            "family": "grug",
                            "leader_name": "Grug",
                            "character_name": "Grug",
                            "run_id": 100,
                            "campaign_id": 1,
                            "run_number": 1,
                            "portal": "deadmines",
                            "phase": "EXIT",
                            "kind": "complete",
                            "detail": "every encounter the map credits has been credited",
                            "created_at": "2026-11-26 16:00:00",
                        }
                    ],
                )
            ),
        ):
            guild_lines = bridge._generate_guild_chat_from_events("grug")
            self.assertGreater(len(guild_lines), 0)
            self.assertIn("cleared", guild_lines[0])
            self.assertIn("deadmines", guild_lines[0])

    def test_multiple_family_events_keeps_rate_human(self):
        """Guild chat does not echo every single event."""
        with mock_module.patch.object(
            bridge,
            "_connect",
            return_value=mock.MagicMock(
                cursor=lambda: mock.MagicMock(
                    execute=lambda sql, params=None: None,
                    fetchall=lambda: [
                        {
                            "id": i,
                            "family": "grug",
                            "leader_name": "Grug",
                            "character_name": f"Char{i}",
                            "run_id": 100,
                            "campaign_id": 1,
                            "run_number": 1,
                            "portal": "deadmines",
                            "phase": "CLEARING",
                            "kind": "boss",
                            "detail": f"{i} encounter credited",
                            "created_at": f"2026-11-26 15:{i}:00",
                        }
                        for i in range(1, 11)
                    ],
                )
            ),
        ):
            guild_lines = bridge._generate_guild_chat_from_events("grug")
            self.assertGreater(len(guild_lines), 0)
            self.assertLessEqual(len(guild_lines), 3)


if __name__ == "__main__":
    unittest.main()
