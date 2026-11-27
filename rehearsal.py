"""Rehearsal world configuration: guards, markers and delegation rights.

A rehearsal world is a long-lived but disposable test fixture that holds a logical
copy of the realm databases. The organic realm keeps its rule: levels, gear,
skills, items and money are never granted. Nothing from the rehearsal world is
ever copied back, and it has no endpoint a game client can reach and no credential
for the organic database.

The overseer runs headless there (no chat service, no ticket filing), same code,
different configuration.
"""

from __future__ import annotations

import re

# The worldserver refuses a realm id outside 1..255 and then crashes on the way out.
REHEARSAL_REALM_ID = 201
REHEARSAL_REALM_NAME = "Rehearsal"

# The marker table that proves this is a rehearsal world.
REHEARSAL_MARKER_TABLE = "rehearsal_marker"
REHEARSAL_MARKER_ROW = "marker = 'rehearsal'"

# The namespace label value; must be exactly: rehearsal
REHEARSAL_WORLD_LABEL = "rehearsal"

# Config a rehearsal world must also carry. The bridge reads this and only grants
# levels, gear, skills, items and money when this is enabled.
REHEARSAL_GRANTS_ENABLED_ENV = "REHEARSAL_GRANTS_ENABLED"

# The string value that must be present in the environment for grants to be enabled.
REHEARSAL_GRANTS_ENABLED_VALUE = "grants: enabled"

# The expected value in the rehearsal world's marker table.
REHEARSAL_MARKER_VALUE = "rehearsal"

# Pattern to validate the grants flag value.
# Only the exact string is allowed.
GRANTS_FLAG_PATTERN = re.compile(r"^grants: enabled$")

# The delimiter between the prefix and the numbered suffix for bot accounts.
BOT_ACCOUNT_PREFIX = "RPR"
BOT_ACCOUNT_SUFFIX_RE = re.compile(r"^RPR\d+$")

# The realm id used for the rehearsal world in acore_auth.realmlist.
REALM_ID = REHEARSAL_REALM_ID

# The realm name used for the rehearsal world in acore_auth.realmlist.
REALM_NAME = REHEARSAL_REALM_NAME


class InvalidGrantFlag(ValueError):
    """The grant flag value is not the expected one."""


class NoRehearsalMarker(RuntimeError):
    """The rehearsal marker row is missing."""


def check_grants_flag(value: str | None) -> None:
    """Raise InvalidGrantFlag if the value is not the expected grants: enabled string.

    Args:
        value: The value of the REHEARSAL_GRANTS_ENABLED environment variable.

    Raises:
        InvalidGrantFlag: If the value is not exactly "grants: enabled".
    """
    if value != REHEARSAL_GRANTS_ENABLED_VALUE:
        raise InvalidGrantFlag(
            f"Expected REHEARSAL_GRANTS_ENABLED to be '{REHEARSAL_GRANTS_ENABLED_VALUE}', "
            f"got {value!r}"
        )


def check_rehearsal_marker(marker_row: str) -> None:
    """Raise NoRehearsalMarker if the marker row is not the expected one.

    Args:
        marker_row: The content of the rehearsal_marker table row.

    Raises:
        NoRehearsalMarker: If the marker row does not contain the expected marker value.
    """
    if marker_row != REHEARSAL_MARKER_VALUE:
        raise NoRehearsalMarker(
            f"Expected rehearsal marker row to be '{REHEARSAL_MARKER_VALUE}', got {marker_row!r}"
        )


def validate_bot_account_prefix(prefix: str) -> None:
    """Raise ValueError if the bot account prefix is not valid.

    Args:
        prefix: The bot account prefix to validate.

    Raises:
        ValueError: If the prefix is not a valid bot account prefix.
    """
    if not BOT_ACCOUNT_SUFFIX_RE.match(prefix):
        raise ValueError(
            f"Bot account prefix must match pattern {BOT_ACCOUNT_SUFFIX_RE.pattern}, got {prefix!r}"
        )
