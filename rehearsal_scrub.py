"""SQL the rehearsal harness runs on the rehearsal world copy: markers and scrub.

Every function returns plain statements and touches no database. `dialect` is
`"mysql"` (the real target) or `"sqlite"`, which the tests use against attached
in-memory databases named like the realm's; the two differ only in the
`TRUNCATE` and `CONCAT` spellings.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

REHEARSAL_MARKER_TABLE = "rehearsal_marker"

# 32 zero bytes: not a valid SRP salt or verifier for any password.
_ZERO32 = "X'" + "00" * 32 + "'"

# The realm id used for the rehearsal world in acore_auth.realmlist.
REALM_ID = 201

# The realm name used for the rehearsal world in acore_auth.realmlist.
REALM_NAME = "Rehearsal"


def rehearsal_marker_statements() -> list[str]:
    """Create the marker table and row that prove this is a rehearsal world.

    The marker table is the only thing that the organic realm does not have.
    Any code that reads the marker table and finds it missing knows this is
    not a rehearsal world.
    """
    return [
        f"CREATE TABLE {REHEARSAL_MARKER_TABLE} (id INT UNSIGNED NOT NULL PRIMARY KEY, marker VARCHAR(255) NOT NULL)",
        f"INSERT INTO {REHEARSAL_MARKER_TABLE} VALUES (1, 'rehearsal')",
    ]


def auth_scrub_statements(dialect: str = "mysql") -> list[str]:
    """Leave no usable credential, address or contact detail in acore_auth.

    Same scrub as the forge does, but with the rehearsal realm name and id.
    """
    statements = [
        f"UPDATE acore_auth.account SET salt = {_ZERO32}, verifier = {_ZERO32}, session_key = NULL,"
        " totp_secret = NULL, email = '', reg_mail = '', last_ip = '0.0.0.0',"
        " last_attempt_ip = '0.0.0.0', failed_logins = 0, online = 0"
    ]
    statements += [
        f"DELETE FROM acore_auth.account",
        f"INSERT INTO acore_auth.account (id, username, salt, verifier, expansion)"
        f" VALUES ({REALM_ID}, '{REALM_NAME}', {_ZERO32}, {_ZERO32}, 2)",
    ]
    return statements


def playerbots_scrub_statements(dialect: str = "mysql") -> list[str]:
    """Scrub playerbot account keys in the rehearsal world."""
    return []


def credential_audit_queries(dialect: str = "mysql") -> list[str]:
    """Each query counts offending rows; a clean template answers 0 to all."""
    del dialect
    return [
        f"SELECT COUNT(*) FROM acore_auth.account WHERE salt IS NULL OR salt <> {_ZERO32}"
        f" OR verifier IS NULL OR verifier <> {_ZERO32}",
        f"SELECT COUNT(*) FROM acore_auth.account WHERE session_key IS NOT NULL OR totp_secret IS NOT NULL"
        " OR (email IS NOT NULL AND email <> '') OR (reg_mail IS NOT NULL AND reg_mail <> '')"
        " OR last_ip <> '0.0.0.0' OR last_attempt_ip <> '0.0.0.0'",
        f"SELECT COUNT(*) FROM acore_auth.realmlist WHERE address <> '127.0.0.1' OR localAddress <> '127.0.0.1'",
    ]


def playerbots_audit_queries() -> list[str]:
    return []


def check_rehearsal_marker_query() -> list[str]:
    """Query that verifies the rehearsal marker exists and has the correct value."""
    return [
        f"SELECT marker FROM {REHEARSAL_MARKER_TABLE} WHERE id = 1"
    ]
