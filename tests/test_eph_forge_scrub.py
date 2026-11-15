"""The ephemeral-world forge's scrub and trim SQL, run against throwaway SQLite.

SQLite is attached under the same schema names the realm uses
(`acore_auth`, `acore_characters`, `acore_playerbots`), so the statements the
forge generates run unchanged apart from the `TRUNCATE` and `CONCAT`
spellings, which the generator emits per dialect. Every MySQL statement also
parses as MySQL when sqlglot is installed (CI has it).

Every credential-looking value in these fixtures is made up.
"""

from __future__ import annotations

import re
import sqlite3
import unittest

from forge import classes, scrub

FAKE_SALT = bytes(range(1, 33))
FAKE_VERIFIER = bytes(range(100, 132))
FAKE_SESSION = b"S" * 40
FAKE_TOTP = b"totp-seed-value"
FAKE_EMAIL = "someone@example.invalid"
FAKE_IP = "203.0.113.77"


_OPEN: list[sqlite3.Connection] = []


def tearDownModule() -> None:
    while _OPEN:
        _OPEN.pop().close()


def connect() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    _OPEN.append(db)
    for schema in ("acore_auth", "acore_characters", "acore_playerbots"):
        db.execute(f"ATTACH ':memory:' AS {schema}")
    return db


def make_auth(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE acore_auth.account (
            id INTEGER PRIMARY KEY, username TEXT, salt BLOB, verifier BLOB,
            session_key BLOB, totp_secret BLOB, email TEXT, reg_mail TEXT,
            last_ip TEXT, last_attempt_ip TEXT, failed_logins INTEGER DEFAULT 0,
            online INTEGER DEFAULT 0, expansion INTEGER DEFAULT 2);
        CREATE TABLE acore_auth.account_banned (id INTEGER, bannedby TEXT);
        CREATE TABLE acore_auth.account_muted (guid INTEGER, mutedby TEXT);
        CREATE TABLE acore_auth.ip_banned (ip TEXT, bannedby TEXT);
        CREATE TABLE acore_auth.logs (time INTEGER, string TEXT);
        CREATE TABLE acore_auth.logs_ip_actions (id INTEGER, ip TEXT);
        CREATE TABLE acore_auth.realmlist (
            id INTEGER PRIMARY KEY, name TEXT, address TEXT, localAddress TEXT,
            localSubnetMask TEXT, port INTEGER, icon INTEGER, flag INTEGER,
            timezone INTEGER, allowedSecurityLevel INTEGER, population REAL,
            gamebuild INTEGER);
        """
    )
    db.execute(
        "INSERT INTO acore_auth.account (id, username, salt, verifier, session_key,"
        " totp_secret, email, reg_mail, last_ip, last_attempt_ip) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            7,
            "REALPLAYER",
            FAKE_SALT,
            FAKE_VERIFIER,
            FAKE_SESSION,
            FAKE_TOTP,
            FAKE_EMAIL,
            FAKE_EMAIL,
            FAKE_IP,
            FAKE_IP,
        ),
    )
    db.execute("INSERT INTO acore_auth.account_banned VALUES (7, 'gm')")
    db.execute("INSERT INTO acore_auth.account_muted VALUES (7, 'gm')")
    db.execute("INSERT INTO acore_auth.ip_banned VALUES ('203.0.113.9', 'gm')")
    db.execute("INSERT INTO acore_auth.logs VALUES (1, 'login from 203.0.113.77')")
    db.execute("INSERT INTO acore_auth.logs_ip_actions VALUES (7, '203.0.113.77')")
    db.execute(
        "INSERT INTO acore_auth.realmlist VALUES (1, 'Live', '203.0.113.5', '203.0.113.5',"
        " '255.255.255.0', 8085, 1, 0, 1, 0, 0.5, 12340)"
    )


def run(db: sqlite3.Connection, statements: list[str]) -> None:
    for sql in statements:
        db.execute(sql)


class AuthScrub(unittest.TestCase):
    def setUp(self) -> None:
        self.db = connect()
        make_auth(self.db)
        run(self.db, scrub.auth_scrub_statements("sqlite"))

    def test_no_original_credential_survives_in_any_account_column(self) -> None:
        rows = self.db.execute("SELECT * FROM acore_auth.account").fetchall()
        self.assertEqual(len(rows), 1)
        values = [v for v in rows[0] if v is not None]
        for secret in (
            FAKE_SALT,
            FAKE_VERIFIER,
            FAKE_SESSION,
            FAKE_TOTP,
            FAKE_EMAIL,
            FAKE_IP,
        ):
            self.assertNotIn(secret, values)

    def test_salt_and_verifier_are_the_unusable_constant(self) -> None:
        salt, verifier = self.db.execute(
            "SELECT salt, verifier FROM acore_auth.account"
        ).fetchone()
        self.assertEqual(salt, bytes(32))
        self.assertEqual(verifier, bytes(32))

    def test_session_totp_mail_and_ip_columns_are_cleared(self) -> None:
        row = self.db.execute(
            "SELECT session_key, totp_secret, email, reg_mail, last_ip, last_attempt_ip FROM acore_auth.account"
        ).fetchone()
        self.assertIsNone(row[0])
        self.assertIsNone(row[1])
        self.assertEqual(row[2:4], ("", ""))
        self.assertEqual(row[4:6], ("0.0.0.0", "0.0.0.0"))

    def test_ban_mute_and_ip_log_tables_are_emptied(self) -> None:
        for table in (
            "account_banned",
            "account_muted",
            "ip_banned",
            "logs",
            "logs_ip_actions",
        ):
            count = self.db.execute(
                f"SELECT COUNT(*) FROM acore_auth.{table}"
            ).fetchone()[0]
            self.assertEqual(count, 0, table)

    def test_the_live_realm_address_is_replaced_by_loopback(self) -> None:
        rows = self.db.execute(
            "SELECT id, name, address, localAddress, port FROM acore_auth.realmlist"
        ).fetchall()
        self.assertEqual(
            rows,
            [(scrub.EPHEMERAL_REALM_ID, "Ephemeral", "127.0.0.1", "127.0.0.1", 8085)],
        )

    def test_the_audit_queries_report_clean_after_the_scrub(self) -> None:
        for sql in scrub.credential_audit_queries("sqlite"):
            self.assertEqual(self.db.execute(sql).fetchone()[0], 0, sql)

    def test_the_audit_queries_catch_an_unscrubbed_account(self) -> None:
        fresh = connect()
        make_auth(fresh)
        counts = [
            fresh.execute(sql).fetchone()[0]
            for sql in scrub.credential_audit_queries("sqlite")
        ]
        self.assertTrue(all(counts), counts)


class AuthSynthesis(unittest.TestCase):
    """With no auth dump, accounts are synthesised from the characters table."""

    def setUp(self) -> None:
        self.db = connect()
        make_auth(self.db)
        self.db.execute("DELETE FROM acore_auth.account")
        self.db.execute(
            "CREATE TABLE acore_characters.characters (guid INTEGER, account INTEGER, name TEXT)"
        )
        self.db.executemany(
            "INSERT INTO acore_characters.characters VALUES (?,?,?)",
            [(1, 10, "A"), (2, 10, "B"), (3, 11, "C")],
        )
        run(self.db, scrub.auth_synthesis_statements("sqlite"))
        run(self.db, scrub.auth_scrub_statements("sqlite"))

    def test_one_account_per_distinct_character_account(self) -> None:
        rows = self.db.execute(
            "SELECT id, username FROM acore_auth.account ORDER BY id"
        ).fetchall()
        self.assertEqual(rows, [(10, "ACCT10"), (11, "ACCT11")])

    def test_synthesised_accounts_hold_no_usable_credential(self) -> None:
        for sql in scrub.credential_audit_queries("sqlite"):
            self.assertEqual(self.db.execute(sql).fetchone()[0], 0, sql)


class PlayerbotsScrub(unittest.TestCase):
    def test_account_keys_are_emptied(self) -> None:
        db = connect()
        db.execute(
            "CREATE TABLE acore_playerbots.playerbots_account_keys (account_id INTEGER, key_value TEXT)"
        )
        db.execute(
            "INSERT INTO acore_playerbots.playerbots_account_keys VALUES (7, 'abc123')"
        )
        run(db, scrub.playerbots_scrub_statements("sqlite"))
        self.assertEqual(
            db.execute(
                "SELECT COUNT(*) FROM acore_playerbots.playerbots_account_keys"
            ).fetchone()[0],
            0,
        )


def make_characters(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE acore_characters.characters (guid INTEGER, account INTEGER, name TEXT, online INTEGER);
        CREATE TABLE acore_characters.character_spell (guid INTEGER, spell INTEGER);
        CREATE TABLE acore_characters.character_pet (id INTEGER, owner INTEGER);
        CREATE TABLE acore_characters.pet_aura (guid INTEGER, spell INTEGER);
        CREATE TABLE acore_characters.item_instance (guid INTEGER, owner_guid INTEGER);
        CREATE TABLE acore_characters.item_soulbound_trade_data (itemGuid INTEGER);
        CREATE TABLE acore_characters.guild (guildid INTEGER, leaderguid INTEGER);
        CREATE TABLE acore_characters.guild_member (guildid INTEGER, guid INTEGER);
        CREATE TABLE acore_characters.guild_rank (guildid INTEGER, rid INTEGER);
        CREATE TABLE acore_characters.overseer_roster (name TEXT, family TEXT, job TEXT);
        CREATE TABLE acore_characters.overseer_raid_seat (family TEXT, name TEXT);
        CREATE TABLE acore_characters.overseer_goal (id INTEGER, character_name TEXT);
        CREATE TABLE acore_characters.groups (guid INTEGER);
        CREATE TABLE acore_characters.updates (name TEXT);
        """
    )
    chars = [
        (1, 1, "Head", 1),  # roster
        (2, 1, "Seat", 1),  # raid seat
        (3, 2, "Guildie", 1),  # guild mate of the roster
        (4, 3, "Stranger", 1),  # unrelated guild
        (5, 3, "Loner", 1),  # no guild
    ]
    db.executemany("INSERT INTO acore_characters.characters VALUES (?,?,?,?)", chars)
    db.executemany(
        "INSERT INTO acore_characters.character_spell VALUES (?,?)",
        [(g, 100) for g in range(1, 6)],
    )
    db.executemany(
        "INSERT INTO acore_characters.character_pet VALUES (?,?)", [(50, 1), (51, 4)]
    )
    db.executemany(
        "INSERT INTO acore_characters.pet_aura VALUES (?,?)", [(50, 9), (51, 9)]
    )
    db.executemany(
        "INSERT INTO acore_characters.item_instance VALUES (?,?)", [(900, 1), (901, 4)]
    )
    db.executemany(
        "INSERT INTO acore_characters.item_soulbound_trade_data VALUES (?)",
        [(900,), (901,)],
    )
    db.executemany("INSERT INTO acore_characters.guild VALUES (?,?)", [(1, 1), (2, 4)])
    db.executemany(
        "INSERT INTO acore_characters.guild_member VALUES (?,?)",
        [(1, 1), (1, 3), (2, 4)],
    )
    db.executemany(
        "INSERT INTO acore_characters.guild_rank VALUES (?,?)", [(1, 0), (2, 0)]
    )
    db.execute(
        "INSERT INTO acore_characters.overseer_roster VALUES ('Head', 'Grug', 'dungeon:x')"
    )
    db.execute(
        "INSERT INTO acore_characters.overseer_raid_seat VALUES ('Grug', 'Seat')"
    )
    db.execute("INSERT INTO acore_characters.overseer_goal VALUES (1, 'Head')")
    db.execute("INSERT INTO acore_characters.groups VALUES (1)")
    db.execute("INSERT INTO acore_characters.updates VALUES ('x.sql')")


MINI = classes.parse_classes(
    """
characters: per-character guid
character_spell: per-character guid
character_pet: per-character owner
pet_aura: per-character guid > character_pet.id
item_instance: per-character owner_guid
item_soulbound_trade_data: per-character itemGuid > item_instance.guid
guild: per-character leaderguid
guild_member: per-character guid
guild_rank: per-character guildid > guild.guildid
overseer_roster: scrub neutral-job
overseer_raid_seat: keep
overseer_goal: truncate
groups: truncate
updates: keep
"""
)


class StateScrub(unittest.TestCase):
    def setUp(self) -> None:
        self.db = connect()
        make_characters(self.db)
        run(self.db, scrub.state_scrub_statements(MINI, "sqlite"))

    def count(self, table: str) -> int:
        return self.db.execute(
            f"SELECT COUNT(*) FROM acore_characters.{table}"
        ).fetchone()[0]

    def test_truncate_tables_are_emptied(self) -> None:
        self.assertEqual((self.count("overseer_goal"), self.count("groups")), (0, 0))

    def test_keep_tables_are_untouched(self) -> None:
        self.assertEqual(
            (self.count("updates"), self.count("overseer_raid_seat")), (1, 1)
        )

    def test_the_roster_job_is_reset_to_the_neutral_value(self) -> None:
        jobs = self.db.execute(
            "SELECT job FROM acore_characters.overseer_roster"
        ).fetchall()
        self.assertEqual(jobs, [(scrub.NEUTRAL_JOB,)])

    def test_every_character_is_marked_offline(self) -> None:
        self.assertEqual(
            self.db.execute(
                "SELECT DISTINCT online FROM acore_characters.characters"
            ).fetchall(),
            [(0,)],
        )

    def test_per_character_rows_are_not_trimmed_by_the_state_scrub(self) -> None:
        self.assertEqual(self.count("characters"), 5)


class LeanTrim(unittest.TestCase):
    def setUp(self) -> None:
        self.db = connect()
        make_characters(self.db)
        scrub.run_lean(
            lambda sql: self.db.execute(sql).fetchall(),
            scrub.lean_statements(MINI, "sqlite"),
        )

    def names(self) -> list[str]:
        return [
            r[0]
            for r in self.db.execute(
                "SELECT name FROM acore_characters.characters ORDER BY guid"
            )
        ]

    def test_keep_set_is_roster_raid_seats_and_their_guild_mates(self) -> None:
        self.assertEqual(self.names(), ["Head", "Seat", "Guildie"])

    def test_child_rows_follow_the_kept_characters(self) -> None:
        rows = self.db.execute(
            "SELECT DISTINCT guid FROM acore_characters.character_spell ORDER BY 1"
        )
        self.assertEqual([r[0] for r in rows], [1, 2, 3])

    def test_dependents_follow_a_trimmed_parent(self) -> None:
        pets = self.db.execute("SELECT guid FROM acore_characters.pet_aura").fetchall()
        self.assertEqual(pets, [(50,)])
        trade = self.db.execute(
            "SELECT itemGuid FROM acore_characters.item_soulbound_trade_data"
        ).fetchall()
        self.assertEqual(trade, [(900,)])
        ranks = self.db.execute(
            "SELECT guildid FROM acore_characters.guild_rank"
        ).fetchall()
        self.assertEqual(ranks, [(1,)])

    def test_the_helper_table_is_dropped(self) -> None:
        tables = {
            r[0]
            for r in self.db.execute("SELECT name FROM acore_characters.sqlite_master")
        }
        self.assertNotIn("_forge_keep", tables)

    def test_non_per_character_tables_are_left_alone(self) -> None:
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM acore_characters.updates").fetchone()[
                0
            ],
            1,
        )

    def test_an_empty_keep_set_refuses_to_trim(self) -> None:
        db = connect()
        make_characters(db)
        db.execute("DELETE FROM acore_characters.overseer_roster")
        db.execute("DELETE FROM acore_characters.overseer_raid_seat")
        with self.assertRaises(scrub.EmptyKeepSet):
            scrub.run_lean(
                lambda sql: db.execute(sql).fetchall(),
                scrub.lean_statements(MINI, "sqlite"),
            )
        self.assertEqual(
            db.execute("SELECT COUNT(*) FROM acore_characters.characters").fetchone()[
                0
            ],
            5,
        )


class MysqlSyntax(unittest.TestCase):
    def test_every_generated_mysql_statement_parses(self) -> None:
        try:
            import sqlglot
        except ImportError:
            self.skipTest("sqlglot not installed")
        real = classes.load_classes(classes.DEFAULT_PATH)
        statements = [
            *scrub.auth_scrub_statements("mysql"),
            *scrub.auth_synthesis_statements("mysql"),
            *scrub.playerbots_scrub_statements("mysql"),
            *scrub.state_scrub_statements(real, "mysql"),
            *scrub.lean_statements(real, "mysql"),
            *scrub.credential_audit_queries("mysql"),
        ]
        self.assertGreater(len(statements), 100)
        for sql in statements:
            sqlglot.parse_one(sql, read="mysql")

    def test_mysql_truncates_and_sqlite_deletes(self) -> None:
        self.assertIn(
            "TRUNCATE TABLE acore_auth.logs", scrub.auth_scrub_statements("mysql")
        )
        self.assertIn(
            "DELETE FROM acore_auth.logs", scrub.auth_scrub_statements("sqlite")
        )

    def test_every_non_keep_table_in_the_real_classes_gets_a_statement(self) -> None:
        real = classes.load_classes(classes.DEFAULT_PATH)
        text = "\n".join(
            [
                *scrub.state_scrub_statements(real, "mysql"),
                *scrub.lean_statements(real, "mysql"),
            ]
        )
        for name, entry in real.items():
            if entry.kind != "keep":
                self.assertRegex(
                    text, rf"\bacore_characters\.{re.escape(name)}\b", name
                )

    def test_the_statements_never_name_the_live_realm(self) -> None:
        text = "\n".join(scrub.auth_scrub_statements("mysql"))
        self.assertNotIn("wow-dev", text)


if __name__ == "__main__":
    unittest.main()
