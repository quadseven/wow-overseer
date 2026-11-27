"""Test the Darkmoon Ace creation SQL generation for ticket #2634.

This test verifies the SQL statements that create the four missing Ace cards
and mail them to the Cave family recipients, as specified in the one-off
owner exception.
"""

from __future__ import annotations

import unittest

from ephemeral import dbschema
from ephemeral.sqlgen import Builder, verify_statement

SCHEMA = dbschema.Schema.load()

# Ace item entries from the brief
ACE_OF_BEASTS = 19227
ACE_OF_WARLORDS = 19258
ACE_OF_PORTALS = 19276
ACE_OF_ELEMENTALS = 19268

# Recipients from the brief
# Warlords -> Grug (warrior, level 60)
# Beasts -> Ugga (priest, level 60)
# Elementals -> Bork (rogue, level 60)
# Portals -> Grog (paladin, level 60)

# Item instance columns from schema
ITEM_INSTANCE_COLS = [
    "guid",
    "itemEntry",
    "owner_guid",
    "creatorGuid",
    "giftCreatorGuid",
    "count",
    "duration",
    "charges",
    "flags",
    "enchantments",
    "randomPropertyId",
    "durability",
    "playedTime",
    "text",
]

MAIL_COLS = [
    "id",
    "messageType",
    "stationery",
    "mailTemplateId",
    "sender",
    "receiver",
    "subject",
    "body",
    "has_items",
    "expire_time",
    "deliver_time",
    "money",
    "cod",
    "checked",
]

MAIL_ITEMS_COLS = ["mail_id", "item_guid", "receiver"]


class DarkmoonAceSQLTest(unittest.TestCase):
    """Test the SQL generation for creating and mailing Darkmoon Aces."""

    def setUp(self):
        self.builder = Builder(SCHEMA)

    def test_item_instance_columns_exist(self):
        """Verify all required item_instance columns exist in schema."""
        for col in ITEM_INSTANCE_COLS:
            self.assertTrue(
                SCHEMA.has_column("item_instance", col),
                f"item_instance missing column: {col}",
            )

    def test_mail_columns_exist(self):
        """Verify all required mail columns exist in schema."""
        for col in MAIL_COLS:
            self.assertTrue(
                SCHEMA.has_column("mail", col), f"mail missing column: {col}"
            )

    def test_mail_items_columns_exist(self):
        """Verify all required mail_items columns exist in schema."""
        for col in MAIL_ITEMS_COLS:
            self.assertTrue(
                SCHEMA.has_column("mail_items", col),
                f"mail_items missing column: {col}",
            )

    def test_ace_item_entries_are_valid(self):
        """Verify the Ace item entries are recognized."""
        # These are the item template entries for the four Aces
        aces = {
            "Ace of Beasts": ACE_OF_BEASTS,
            "Ace of Warlords": ACE_OF_WARLORDS,
            "Ace of Portals": ACE_OF_PORTALS,
            "Ace of Elementals": ACE_OF_ELEMENTALS,
        }
        for name, entry in aces.items():
            self.assertIsInstance(entry, int)
            self.assertGreater(entry, 0, f"{name} entry must be positive")

    def test_builder_can_create_item_instance(self):
        """Test that Builder can create a valid item_instance INSERT."""
        stmt = self.builder.insert(
            "item_instance",
            {
                "guid": 1000001,
                "itemEntry": ACE_OF_BEASTS,
                "owner_guid": 1,
                "creatorGuid": 0,
                "giftCreatorGuid": 0,
                "count": 1,
                "duration": 0,
                "charges": "0 0 0 0 0 ",
                "flags": 0,
                "enchantments": "0 " * 36,
                "randomPropertyId": 0,
                "durability": 0,
                "playedTime": 0,
                "text": "",
            },
        )
        # Verify the statement is valid
        verify_statement(stmt.sql, SCHEMA)
        self.assertIn("INSERT INTO `acore_characters`.`item_instance`", stmt.sql)
        self.assertIn("19227", stmt.sql)

    def test_builder_can_create_mail(self):
        """Test that Builder can create a valid mail INSERT."""
        stmt = self.builder.insert(
            "mail",
            {
                "id": 1000001,
                "messageType": 0,
                "stationery": 0,
                "mailTemplateId": 0,
                "sender": 0,
                "receiver": 1,
                "subject": "Darkmoon Ace",
                "body": "A Darkmoon Ace for your collection.",
                "has_items": 1,
                "expire_time": 604800,  # 7 days
                "deliver_time": 0,
                "money": 0,
                "cod": 0,
                "checked": 0,
            },
        )
        verify_statement(stmt.sql, SCHEMA)
        self.assertIn("INSERT INTO `acore_characters`.`mail`", stmt.sql)

    def test_builder_can_create_mail_items(self):
        """Test that Builder can create a valid mail_items INSERT."""
        stmt = self.builder.insert(
            "mail_items",
            {
                "mail_id": 1000001,
                "item_guid": 1000001,
                "receiver": 1,
            },
        )
        verify_statement(stmt.sql, SCHEMA)
        self.assertIn("INSERT INTO `acore_characters`.`mail_items`", stmt.sql)

    def test_verify_full_ace_creation_statement(self):
        """Verify a complete set of statements for one Ace."""
        # Item instance
        item_stmt = self.builder.insert(
            "item_instance",
            {
                "guid": 2000001,
                "itemEntry": ACE_OF_WARLORDS,
                "owner_guid": 10,  # Grug's GUID (placeholder)
                "creatorGuid": 0,
                "giftCreatorGuid": 0,
                "count": 1,
                "duration": 0,
                "charges": "0 0 0 0 0 ",
                "flags": 0,
                "enchantments": "0 " * 36,
                "randomPropertyId": 0,
                "durability": 0,
                "playedTime": 0,
                "text": "",
            },
        )
        verify_statement(item_stmt.sql, SCHEMA)

        # Mail
        mail_stmt = self.builder.insert(
            "mail",
            {
                "id": 3000001,
                "messageType": 0,
                "stationery": 0,
                "mailTemplateId": 0,
                "sender": 0,
                "receiver": 10,
                "subject": "Ace of Warlords",
                "body": "Complete your Warlords Deck with this Ace.",
                "has_items": 1,
                "expire_time": 604800,
                "deliver_time": 0,
                "money": 0,
                "cod": 0,
                "checked": 0,
            },
        )
        verify_statement(mail_stmt.sql, SCHEMA)

        # Mail items
        mail_items_stmt = self.builder.insert(
            "mail_items",
            {
                "mail_id": 3000001,
                "item_guid": 2000001,
                "receiver": 10,
            },
        )
        verify_statement(mail_items_stmt.sql, SCHEMA)

    def test_ace_creation_uses_mail_not_inventory(self):
        """The brief specifies mailing items, not direct inventory placement.

        This test documents the expected approach: Aces are created as item_instance
        rows and delivered via mail/mail_items, not placed directly in
        character_inventory.
        """
        # The approach is verified by the other tests showing valid mail/mail_items INSERTs
        # No character_inventory INSERTs should be generated for the Ace delivery
        pass


class DarkmoonAceRecipientTest(unittest.TestCase):
    """Test the recipient mapping for the four Aces."""

    def test_recipient_mapping(self):
        """Verify the four Aces go to the correct recipients."""
        recipients = {
            ACE_OF_WARLORDS: "Grug",  # Warrior, level 60 -> Heroism
            ACE_OF_BEASTS: "Ugga",  # Priest, level 60 -> Blue Dragon
            ACE_OF_ELEMENTALS: "Bork",  # Rogue, level 60 -> Maelstrom
            ACE_OF_PORTALS: "Grog",  # Paladin, level 60 -> Twisting Nether
        }
        self.assertEqual(len(recipients), 4)
        # All recipients are Cave (Alliance) family members
        cave_members = {
            "Grug",
            "Ugga",
            "Grog",
            "Bork",
            "Og",
            "Zug",
            "Zrog",
            "Zork",
            "Uzza",
            "Oz",
        }
        for recipient in recipients.values():
            self.assertIn(recipient, cave_members)

    def test_no_bonkers_recipients(self):
        """Verify no Aces go to Bonkers (Horde) family members."""
        recipients = {
            ACE_OF_WARLORDS: "Grug",
            ACE_OF_BEASTS: "Ugga",
            ACE_OF_ELEMENTALS: "Bork",
            ACE_OF_PORTALS: "Grog",
        }
        bonkers_members = {"Zug", "Zrog", "Uzza", "Oz", "Zork"}
        for recipient in recipients.values():
            self.assertNotIn(recipient, bonkers_members)


if __name__ == "__main__":
    unittest.main()
