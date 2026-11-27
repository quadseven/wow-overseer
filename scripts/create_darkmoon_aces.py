#!/usr/bin/env python3
"""Generate SQL to create the four missing Darkmoon Aces and mail them to Cave family recipients.

This script implements the one-off owner exception from ticket #2634:
create exactly one Ace per Cave-completable deck (Beasts, Warlords, Portals, Elementals)
and mail them to the designated recipients.

The Aces are created as item_instance rows and delivered via mail/mail_items
tables, using reserved GUID ranges that must be proven free before use.

Usage:
    python scripts/create_darkmoon_aces.py --output darkmoon_aces.sql
    python scripts/create_darkmoon_aces.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TextIO

from ephemeral import dbschema
from ephemeral.sqlgen import Builder, SeedError


# Ace item entries from the brief
ACE_OF_BEASTS = 19227
ACE_OF_WARLORDS = 19258
ACE_OF_PORTALS = 19276
ACE_OF_ELEMENTALS = 19268

# Deck and trinket info for mail body
ACE_INFO = {
    ACE_OF_BEASTS: {
        "name": "Ace of Beasts",
        "deck": "Beasts Deck",
        "quest": 7907,
        "npc": "Professor Thaddeus Paleo",
        "trinket": "Darkmoon Card: Blue Dragon",
        "recipient": "Ugga",
        "class": "priest",
    },
    ACE_OF_WARLORDS: {
        "name": "Ace of Warlords",
        "deck": "Warlords Deck",
        "quest": 7928,
        "npc": "Professor Thaddeus Paleo",
        "trinket": "Darkmoon Card: Heroism",
        "recipient": "Grug",
        "class": "warrior",
    },
    ACE_OF_PORTALS: {
        "name": "Ace of Portals",
        "deck": "Portals Deck",
        "quest": 7927,
        "npc": "Professor Thaddeus Paleo",
        "trinket": "Darkmoon Card: Twisting Nether",
        "recipient": "Grog",
        "class": "paladin",
    },
    ACE_OF_ELEMENTALS: {
        "name": "Ace of Elementals",
        "deck": "Elementals Deck",
        "quest": 7929,
        "npc": "Professor Thaddeus Paleo",
        "trinket": "Darkmoon Card: Maelstrom",
        "recipient": "Bork",
        "class": "rogue",
    },
}

# Default reserved ranges (must be verified free before use)
DEFAULT_ITEM_GUID_START = 2000000
DEFAULT_MAIL_ID_START = 3000000


@dataclass
class Character:
    """A character with GUID and name."""

    name: str
    guid: int


@dataclass
class AceItem:
    """An Ace item with its metadata."""

    entry: int
    name: str
    recipient: Character
    info: dict


@dataclass
class AuditEntry:
    """Audit trail entry for one Ace creation."""

    item_id: int
    item_guid: int
    mail_id: int
    recipient: str
    recipient_guid: int
    timestamp: str
    verification_query: str


def build_ace_items(recipients: dict[str, int]) -> list[AceItem]:
    """Build the four Ace items with assigned GUIDs."""
    items = []
    for entry, info in ACE_INFO.items():
        recipient_name = info["recipient"]
        recipient_guid = recipients[recipient_name]
        items.append(
            AceItem(
                entry=entry,
                name=info["name"],
                recipient=Character(recipient_name, recipient_guid),
                info=info,
            )
        )
    return items


def generate_item_instance_sql(builder: Builder, ace: AceItem, item_guid: int) -> str:
    """Generate INSERT for item_instance table."""
    stmt = builder.insert(
        "item_instance",
        {
            "guid": item_guid,
            "itemEntry": ace.entry,
            "owner_guid": ace.recipient.guid,
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
    return stmt.sql


def generate_mail_sql(builder: Builder, ace: AceItem, mail_id: int) -> str:
    """Generate INSERT for mail table."""
    info = ace.info
    subject = info["name"]
    body = (
        f"This {info['name']} completes your {info['deck']}. "
        f"Combine with the other seven cards to create the deck, "
        f"then turn in to {info['npc']} at the Darkmoon Faire "
        f"Quest {info['quest']} to receive {info['trinket']}."
    )
    stmt = builder.insert(
        "mail",
        {
            "id": mail_id,
            "messageType": 0,
            "stationery": 0,
            "mailTemplateId": 0,
            "sender": 0,
            "receiver": ace.recipient.guid,
            "subject": subject,
            "body": body,
            "has_items": 1,
            "expire_time": 604800,  # 7 days in seconds
            "deliver_time": 0,
            "money": 0,
            "cod": 0,
            "checked": 0,
        },
    )
    return stmt.sql


def generate_mail_items_sql(
    builder: Builder, mail_id: int, item_guid: int, receiver_guid: int
) -> str:
    """Generate INSERT for mail_items table."""
    stmt = builder.insert(
        "mail_items",
        {
            "mail_id": mail_id,
            "item_guid": item_guid,
            "receiver": receiver_guid,
        },
    )
    return stmt.sql


def generate_all_sql(
    recipients: dict[str, int],
    item_guid_start: int = DEFAULT_ITEM_GUID_START,
    mail_id_start: int = DEFAULT_MAIL_ID_START,
) -> tuple[list[str], list[AuditEntry]]:
    """Generate all SQL statements for the four Aces and return audit entries."""
    schema = dbschema.Schema.load()
    builder = Builder(schema)

    aces = build_ace_items(recipients)
    statements = []
    audit_entries = []
    timestamp = datetime.now(timezone.utc).isoformat()

    for i, ace in enumerate(aces):
        item_guid = item_guid_start + i + 1
        mail_id = mail_id_start + i + 1

        # Item instance
        statements.append(generate_item_instance_sql(builder, ace, item_guid))
        # Mail
        statements.append(generate_mail_sql(builder, ace, mail_id))
        # Mail items
        statements.append(
            generate_mail_items_sql(builder, mail_id, item_guid, ace.recipient.guid)
        )

        # Audit entry
        audit_entries.append(
            AuditEntry(
                item_id=ace.entry,
                item_guid=item_guid,
                mail_id=mail_id,
                recipient=ace.recipient.name,
                recipient_guid=ace.recipient.guid,
                timestamp=timestamp,
                verification_query=(
                    f"SELECT * FROM item_instance WHERE guid={item_guid}; "
                    f"SELECT * FROM mail WHERE id={mail_id}; "
                    f"SELECT * FROM mail_items WHERE mail_id={mail_id};"
                ),
            )
        )

    return statements, audit_entries


def write_sql_file(statements: list[str], output: TextIO) -> None:
    """Write SQL statements to output file."""
    output.write("-- Darkmoon Ace creation for ticket #2634\n")
    output.write(
        "-- One-off owner exception: create missing Aces for Cave family decks\n"
    )
    output.write("-- Generated by scripts/create_darkmoon_aces.py\n\n")
    for stmt in statements:
        output.write(stmt + ";\n")


def write_audit_file(audit_entries: list[AuditEntry], output: TextIO) -> None:
    """Write audit trail to output file as JSON."""
    data = [
        {
            "item_id": e.item_id,
            "item_guid": e.item_guid,
            "mail_id": e.mail_id,
            "recipient": e.recipient,
            "recipient_guid": e.recipient_guid,
            "timestamp": e.timestamp,
            "verification_query": e.verification_query,
        }
        for e in audit_entries
    ]
    json.dump(data, output, indent=2)
    output.write("\n")


def print_audit_summary(audit_entries: list[AuditEntry]) -> None:
    """Print audit trail summary to stderr."""
    print("\n=== Audit Trail for Ticket #2634 ===", file=sys.stderr)
    for e in audit_entries:
        print(
            f"Ace: {e.item_id} | Item GUID: {e.item_guid} | Mail ID: {e.mail_id} | "
            f"Recipient: {e.recipient} (GUID: {e.recipient_guid}) | Time: {e.timestamp}",
            file=sys.stderr,
        )
    print("=== End Audit Trail ===\n", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate SQL to create and mail four Darkmoon Aces"
    )
    parser.add_argument(
        "--output",
        "-o",
        type=argparse.FileType("w"),
        default=sys.stdout,
        help="Output SQL file (default: stdout)",
    )
    parser.add_argument(
        "--audit-output",
        type=argparse.FileType("w"),
        help="Output audit trail JSON file",
    )
    parser.add_argument(
        "--item-guid-start",
        type=int,
        default=DEFAULT_ITEM_GUID_START,
        help=f"Starting item_instance GUID (default: {DEFAULT_ITEM_GUID_START})",
    )
    parser.add_argument(
        "--mail-id-start",
        type=int,
        default=DEFAULT_MAIL_ID_START,
        help=f"Starting mail ID (default: {DEFAULT_MAIL_ID_START})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print SQL to stdout without writing file",
    )
    # Recipient GUIDs - these must be provided or looked up
    parser.add_argument(
        "--grug-guid", type=int, required=True, help="Grug's character GUID"
    )
    parser.add_argument(
        "--ugga-guid", type=int, required=True, help="Ugga's character GUID"
    )
    parser.add_argument(
        "--bork-guid", type=int, required=True, help="Bork's character GUID"
    )
    parser.add_argument(
        "--grog-guid", type=int, required=True, help="Grog's character GUID"
    )

    args = parser.parse_args()

    recipients = {
        "Grug": args.grug_guid,
        "Ugga": args.ugga_guid,
        "Bork": args.bork_guid,
        "Grog": args.grog_guid,
    }

    try:
        statements, audit_entries = generate_all_sql(
            recipients,
            item_guid_start=args.item_guid_start,
            mail_id_start=args.mail_id_start,
        )
    except SeedError as e:
        print(f"ERROR: Invalid SQL generated: {e}", file=sys.stderr)
        return 1
    except KeyError as e:
        print(f"ERROR: Missing recipient GUID: {e}", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"ERROR: Schema load failed: {e}", file=sys.stderr)
        return 1

    # Always print audit summary to stderr for visibility
    print_audit_summary(audit_entries)

    if args.audit_output:
        write_audit_file(audit_entries, args.audit_output)
        print(f"Wrote audit trail to {args.audit_output.name}", file=sys.stderr)

    if args.dry_run:
        write_sql_file(statements, sys.stdout)
    else:
        write_sql_file(statements, args.output)
        print(
            f"Generated {len(statements)} statements to {args.output.name}",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
