#!/usr/bin/env python3
"""Verify operator-created named characters and random-bot guild cohorts.

This tool is deliberately read-only.  AzerothCore creates a named character
through the game client, not by inserting a partial ``characters`` row, so
provisioning remains an operator action.  The tool checks the result afterwards
against the realm's own auth and character databases.

Examples (run with the wow-dev MySQL secret in the environment)::

    verify_named_cohort.py --realm-id 1 --realm-name Homelab-Dev
    verify_named_cohort.py --guild Cave --guild Bonkers \
        --minimum-random-bot-members 50

The account password is never read, printed, or accepted as an argument.
"""
from __future__ import annotations

import argparse
import json
import os
import sys


# WotLK race and class ids are data, not guesses made by the database adapter.
# These are the five Horde characters from the Bonkers cohort definition.
BONKERS = {
    "Blammo": {"account": "BLAMMO", "race": 2, "class": 1, "faction": "horde"},
    "Hexmama": {"account": "HEXMAMA", "race": 8, "class": 5, "faction": "horde"},
    "Moojuice": {"account": "MOOJUICE", "race": 6, "class": 11, "faction": "horde"},
    "Rotgut": {"account": "ROTGUT", "race": 5, "class": 4, "faction": "horde"},
    "Zapzap": {"account": "ZAPZAP", "race": 10, "class": 8, "faction": "horde"},
}

HORDE_RACES = frozenset((2, 5, 6, 8, 10))


def placeholders(count: int) -> str:
    """Return only bound-parameter markers for a fixed-size IN clause."""
    if count < 1:
        raise ValueError("count must be positive")
    return ",".join(["%s"] * count)


def verify_realm(rows: list[dict], expected_id: int, expected_name: str | None) -> list[str]:
    """Return realm errors without touching a database."""
    if len(rows) != 1:
        return [f"expected one realmlist row, got {len(rows)}"]
    row = rows[0]
    errors = []
    if int(row.get("id", -1)) != expected_id:
        errors.append(f"realm id is {row.get('id')}, expected {expected_id}")
    if expected_name and row.get("name") != expected_name:
        errors.append(f"realm name is {row.get('name')!r}, expected {expected_name!r}")
    return errors


def verify_characters(
    rows: list[dict],
    expected: dict[str, dict],
) -> list[str]:
    """Validate names, account ownership, race, class, faction and uniqueness."""
    errors = []
    by_name = {row.get("name"): row for row in rows}
    if len(rows) != len(expected):
        errors.append(f"expected {len(expected)} character rows, got {len(rows)}")
    if len(by_name) != len(rows):
        errors.append("character result contains duplicate names")
    accounts = []
    for name, wanted in expected.items():
        row = by_name.get(name)
        if row is None:
            errors.append(f"missing character {name}")
            continue
        account = str(row.get("username", "")).upper()
        accounts.append(account)
        if account != wanted["account"]:
            errors.append(f"{name} belongs to {account!r}, expected {wanted['account']!r}")
        if int(row.get("race", -1)) != wanted["race"]:
            errors.append(f"{name} race is {row.get('race')}, expected {wanted['race']}")
        if int(row.get("class", -1)) != wanted["class"]:
            errors.append(f"{name} class is {row.get('class')}, expected {wanted['class']}")
        actual_faction = "horde" if int(row.get("race", -1)) in HORDE_RACES else "other"
        if actual_faction != wanted["faction"]:
            errors.append(f"{name} faction is {actual_faction}, expected {wanted['faction']}")
    if len(set(accounts)) != len(accounts):
        errors.append("named characters do not have separate accounts")
    return errors


def verify_guilds(
    rows: list[dict],
    names: list[str],
    minimum_random_bot_members: int,
) -> list[str]:
    """Validate guild membership counts from a read-only aggregate query."""
    errors = []
    by_name = {row.get("guild_name"): row for row in rows}
    for name in names:
        row = by_name.get(name)
        if row is None:
            errors.append(f"missing guild {name}")
            continue
        count = int(row.get("random_bot_members", 0))
        if count < minimum_random_bot_members:
            errors.append(
                f"{name} has {count} eligible random-bot members, "
                f"expected at least {minimum_random_bot_members}"
            )
    return errors


def _connect():
    import pymysql

    return pymysql.connect(
        host=os.environ.get("MYSQL_HOST", "mysql"),
        user="root",
        password=os.environ["MYSQL_ROOT_PASSWORD"],
        database="acore_characters",
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=5,
        read_timeout=10,
        write_timeout=10,
    )


def _read(cur, args) -> tuple[list[dict], list[dict], list[str]]:
    names = list(BONKERS)
    cur.execute("SELECT id, name FROM acore_auth.realmlist WHERE id = %s", (args.realm_id,))
    realm_rows = list(cur.fetchall())
    cur.execute(
        "SELECT c.name, c.account, c.race, c.class, a.username "
        "FROM characters c JOIN acore_auth.account a ON a.id = c.account "
        f"WHERE c.name IN ({placeholders(len(names))})",
        tuple(names),
    )
    character_rows = list(cur.fetchall())
    guild_rows = []
    if args.guild:
        prefix = args.random_bot_prefix.rstrip("%") + "%"
        cur.execute(
            "SELECT g.name AS guild_name, "
            "COUNT(DISTINCT CASE WHEN a.username LIKE %s THEN c.guid END) "
            "AS random_bot_members "
            "FROM guild g LEFT JOIN guild_member gm ON gm.guildid = g.guildid "
            "LEFT JOIN characters c ON c.guid = gm.guid "
            "LEFT JOIN acore_auth.account a ON a.id = c.account "
            f"WHERE g.name IN ({placeholders(len(args.guild))}) GROUP BY g.name",
            (prefix, *args.guild),
        )
        guild_rows = list(cur.fetchall())
    return realm_rows, character_rows, guild_rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--realm-id", type=int, required=True)
    parser.add_argument("--realm-name")
    parser.add_argument("--guild", action="append", default=[])
    parser.add_argument("--minimum-random-bot-members", type=int, default=0)
    parser.add_argument("--random-bot-prefix", default="RNDBOT")
    args = parser.parse_args(argv)
    if args.minimum_random_bot_members and not args.guild:
        parser.error("--minimum-random-bot-members requires at least one --guild")

    with _connect() as conn, conn.cursor() as cur:
        realm_rows, character_rows, guild_rows = _read(cur, args)
    errors = verify_realm(realm_rows, args.realm_id, args.realm_name)
    errors.extend(verify_characters(character_rows, BONKERS))
    errors.extend(verify_guilds(guild_rows, args.guild, args.minimum_random_bot_members))
    report = {
        "realm": realm_rows,
        "characters": character_rows,
        "guilds": guild_rows,
        "ok": not errors,
        "errors": errors,
    }
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
