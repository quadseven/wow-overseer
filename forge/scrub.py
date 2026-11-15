"""SQL the forge runs on the restored copy: auth scrub, state scrub, lean trim.

Every function returns plain statements and touches no database. `dialect` is
`"mysql"` (the forge's real target) or `"sqlite"`, which the tests use against
attached in-memory databases named like the realm's; the two differ only in the
`TRUNCATE` and `CONCAT` spellings.
"""

# ruff: noqa: S608
# S608 is a false positive here: every interpolated value is a validated schema or
# table identifier, a module constant, or a backup stamp matched by a strict regex.
# Nothing comes from user input.

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from forge.classes import TableClass, trim_order

CHARS = "acore_characters"
AUTH = "acore_auth"
BOTS = "acore_playerbots"

# The job value every roster row is reset to. A decree sets the real job.
NEUTRAL_JOB = "rest"
# The worldserver refuses a realm id outside 1..255 ("Realm ID must range from 1
# to 255") and then crashes on the way out.
EPHEMERAL_REALM_ID = 200
EPHEMERAL_REALM_NAME = "Ephemeral"

# `Playerbots.RandomBotAccountPrefix` in the realm's playerbots config. At boot
# mod-playerbots looks up `<prefix><n>` for every n below the account total it
# calculates, creates the missing accounts and tops each up to 10 characters
# (RandomPlayerbotFactory::CreateRandomBots).
BOT_PREFIX = "RNDBOT"
_PREFIX_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*$")

# Config a lean world must also carry. With `MaxRandomBots = 0` and
# `AddClassAccountPoolSize = 0` the factory calculates zero required accounts;
# the trim empties `playerbots_account_type`, so it finds no existing ones
# either and creates nothing. These are manifest settings, not database ones.
LEAN_PLAYERBOTS_CONF = {
    "Playerbots.RandomBotAccountCount": "0",
    "Playerbots.AddClassAccountPoolSize": "0",
}

KEEP_TABLE = f"{CHARS}._forge_keep"
KEEP_COUNT_SQL = f"SELECT COUNT(*) FROM {KEEP_TABLE}"

# 32 zero bytes: not a valid SRP salt or verifier for any password.
_ZERO32 = "X'" + "00" * 32 + "'"

_AUTH_EMPTY = (
    "account_banned",
    "account_muted",
    "ip_banned",
    "logs",
    "logs_ip_actions",
)


class EmptyKeepSet(RuntimeError):
    """The lean keep-set came out empty; trimming would delete every character."""


def _empty(table: str, dialect: str) -> str:
    if dialect == "mysql":
        return f"TRUNCATE TABLE {table}"
    if dialect == "sqlite":
        return f"DELETE FROM {table}"
    raise ValueError(f"unknown dialect {dialect!r}")


def _concat(left: str, right: str, dialect: str) -> str:
    return f"CONCAT({left}, {right})" if dialect == "mysql" else f"{left} || {right}"


def auth_scrub_statements(dialect: str = "mysql") -> list[str]:
    """Leave no usable credential, address or contact detail in acore_auth."""
    statements = [
        f"UPDATE {AUTH}.account SET salt = {_ZERO32}, verifier = {_ZERO32}, session_key = NULL,"
        " totp_secret = NULL, email = '', reg_mail = '', last_ip = '0.0.0.0',"
        " last_attempt_ip = '0.0.0.0', failed_logins = 0, online = 0"
    ]
    statements += [_empty(f"{AUTH}.{table}", dialect) for table in _AUTH_EMPTY]
    statements += [
        f"DELETE FROM {AUTH}.realmlist",
        f"INSERT INTO {AUTH}.realmlist (id, name, address, localAddress, localSubnetMask, port, icon,"
        " flag, timezone, allowedSecurityLevel, population, gamebuild)"
        f" VALUES ({EPHEMERAL_REALM_ID}, '{EPHEMERAL_REALM_NAME}', '127.0.0.1', '127.0.0.1',"
        " '255.255.255.0', 8085, 0, 0, 1, 0, 0, 12340)",
    ]
    return statements


def _check_prefix(prefix: str) -> str:
    if not _PREFIX_RE.match(prefix):
        raise ValueError(f"bot account prefix must be a plain word, not {prefix!r}")
    return prefix


def auth_synthesis_statements(
    dialect: str = "mysql", bot_prefix: str = BOT_PREFIX
) -> list[str]:
    """Build accounts from the restored tables, so no credential is ever read.

    Used when no auth dump is supplied. Accounts listed in
    `playerbots_account_type` are the factory's: they are named
    `<prefix><n>` in id order, because the factory looks them up by that name and
    would otherwise create a fresh full set. Every other account that owns a
    character is named `ACCT<id>`. All get the unusable salt and verifier.
    """
    prefix = _check_prefix(bot_prefix)
    bot_name = _concat(
        f"'{prefix}'", "(ROW_NUMBER() OVER (ORDER BY account_id) - 1)", dialect
    )
    player_name = _concat("'ACCT'", "account", dialect)
    return [
        f"INSERT INTO {AUTH}.account (id, username, salt, verifier, expansion)"
        f" SELECT account_id, {bot_name}, {_ZERO32}, {_ZERO32}, 2 FROM {BOTS}.playerbots_account_type"
        f" WHERE account_id NOT IN (SELECT id FROM {AUTH}.account)",
        f"INSERT INTO {AUTH}.account (id, username, salt, verifier, expansion)"
        f" SELECT DISTINCT account, {player_name}, {_ZERO32}, {_ZERO32}, 2 FROM {CHARS}.characters"
        f" WHERE account NOT IN (SELECT id FROM {AUTH}.account)",
    ]


def playerbots_scrub_statements(dialect: str = "mysql") -> list[str]:
    return [_empty(f"{BOTS}.playerbots_account_keys", dialect)]


def credential_audit_queries(dialect: str = "mysql") -> list[str]:
    """Each query counts offending rows; a clean template answers 0 to all."""
    del dialect
    return [
        f"SELECT COUNT(*) FROM {AUTH}.account WHERE salt IS NULL OR salt <> {_ZERO32}"
        f" OR verifier IS NULL OR verifier <> {_ZERO32}",
        f"SELECT COUNT(*) FROM {AUTH}.account WHERE session_key IS NOT NULL OR totp_secret IS NOT NULL"
        " OR (email IS NOT NULL AND email <> '') OR (reg_mail IS NOT NULL AND reg_mail <> '')"
        " OR last_ip <> '0.0.0.0' OR last_attempt_ip <> '0.0.0.0'",
        f"SELECT COUNT(*) FROM {AUTH}.realmlist WHERE address <> '127.0.0.1' OR localAddress <> '127.0.0.1'",
        "SELECT "
        + " + ".join(f"(SELECT COUNT(*) FROM {AUTH}.{table})" for table in _AUTH_EMPTY),
    ]


def playerbots_audit_queries() -> list[str]:
    return [f"SELECT COUNT(*) FROM {BOTS}.playerbots_account_keys"]


def _neutral_job(table: str) -> str:
    return f"UPDATE {CHARS}.{table} SET job = '{NEUTRAL_JOB}'"


SCRUB_RULES: dict[str, Callable[[str], str]] = {"neutral-job": _neutral_job}


def state_scrub_statements(
    classes: dict[str, TableClass], dialect: str = "mysql"
) -> list[str]:
    """Empty the truncate tables and apply each scrub rule."""
    statements: list[str] = []
    for name in sorted(classes):
        entry = classes[name]
        if entry.kind == "truncate":
            statements.append(_empty(f"{CHARS}.{name}", dialect))
        elif entry.kind == "scrub":
            rule = SCRUB_RULES.get(entry.spec)
            if rule is None:
                raise ValueError(f"{name}: no scrub rule named {entry.spec!r}")
            statements.append(rule(name))
    if "characters" in classes:
        statements.append(f"UPDATE {CHARS}.characters SET online = 0")
    return statements


def keep_set_statements() -> list[str]:
    """Fill the helper table with the guids the lean class keeps.

    Roster characters, approved raid seats, and every member of a guild that
    holds one of those characters.
    """
    guids = f"SELECT guid FROM {KEEP_TABLE}"
    return [
        f"DROP TABLE IF EXISTS {KEEP_TABLE}",
        f"CREATE TABLE {KEEP_TABLE} (guid INT UNSIGNED NOT NULL PRIMARY KEY)",
        f"INSERT INTO {KEEP_TABLE} SELECT guid FROM {CHARS}.characters"
        f" WHERE name IN (SELECT name FROM {CHARS}.overseer_roster)",
        f"INSERT INTO {KEEP_TABLE} SELECT guid FROM {CHARS}.characters"
        f" WHERE name IN (SELECT name FROM {CHARS}.overseer_raid_seat) AND guid NOT IN ({guids})",
        f"INSERT INTO {KEEP_TABLE} SELECT guid FROM {CHARS}.guild_member"
        f" WHERE guildid IN (SELECT guildid FROM {CHARS}.guild_member WHERE guid IN ({guids}))"
        f" AND guid NOT IN ({guids})",
        KEEP_COUNT_SQL,
    ]


def lean_statements(
    classes: dict[str, TableClass], dialect: str = "mysql", bot_prefix: str = BOT_PREFIX
) -> list[str]:
    """Delete every character outside the keep-set, with their child rows.

    Also removes what would make mod-playerbots refill the database at boot:
    accounts no kept character uses, the `playerbots_account_type` and link
    rows, and the factory prefix on the accounts that stay (so a kept account is
    never one the factory counts as its own and tops up to 10 characters).
    """
    prefix = _check_prefix(bot_prefix)
    statements = keep_set_statements()
    for entry in trim_order(classes):
        if entry.parent is None:
            target = f"SELECT guid FROM {KEEP_TABLE}"
        else:
            parent_table, parent_col = entry.parent
            target = f"SELECT {parent_col} FROM {CHARS}.{parent_table}"
        statements.append(
            f"DELETE FROM {CHARS}.{entry.table} WHERE {entry.key} NOT IN ({target})"
        )
    kept = f"SELECT guid FROM {KEEP_TABLE}"
    statements += [
        f"DELETE FROM {BOTS}.playerbots_random_bots WHERE bot <> 0 AND bot NOT IN ({kept})",
        f"DELETE FROM {BOTS}.playerbots_db_store WHERE guid NOT IN ({kept})",
        f"DELETE FROM {BOTS}.playerbots_preferred_mounts WHERE guid NOT IN ({kept})",
        _empty(f"{BOTS}.playerbots_account_type", dialect),
        _empty(f"{BOTS}.playerbots_account_links", dialect),
        f"DELETE FROM {AUTH}.account WHERE id NOT IN (SELECT account FROM {CHARS}.characters)",
        f"DELETE FROM {AUTH}.account_access WHERE id NOT IN (SELECT id FROM {AUTH}.account)",
        f"UPDATE {AUTH}.account SET username = {_concat(chr(39) + 'ACCT' + chr(39), 'id', dialect)}"
        f" WHERE username LIKE '{prefix}%'",
        f"DROP TABLE {KEEP_TABLE}",
    ]
    return statements


def run_lean(execute: Callable[[str], Any], statements: list[str]) -> None:
    """Run the lean statements, refusing to trim when the keep-set is empty."""
    for sql in statements:
        rows = execute(sql)
        if sql == KEEP_COUNT_SQL and rows and rows[0][0] == 0:
            raise EmptyKeepSet(
                "the lean keep-set is empty; refusing to delete every character"
            )
