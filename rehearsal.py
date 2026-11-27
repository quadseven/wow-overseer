"""Rehearsal world configuration and guards.

A rehearsal world is a disposable clone of the organic realm databases, built from
the same images as the organic realm, holding a logical copy. The organic realm
keeps its rule: levels, gear, skills, items and money are never granted. Nothing
from the rehearsal world is ever copied back, and it has no endpoint a game
client can reach and no credential for the organic database.

The overseer runs headless there (no chat service, no ticket filing), same code,
different configuration.
"""

import re

REALM_ID = 201
REALM_NAME = "Rehearsal"

REHEARSAL_MARKER_TABLE = "rehearsal_marker"
REHEARSAL_MARKER_ROW = "marker = 'rehearsal'"
REHEARSAL_MARKER_VALUE = "rehearsal"

REHEARSAL_WORLD_LABEL = "rehearsal"

REHEARSAL_GRANTS_ENABLED_ENV = "REHEARSAL_GRANTS_ENABLED"
REHEARSAL_GRANTS_ENABLED_VALUE = "grants: enabled"

BOT_ACCOUNT_PREFIX = "RPR"
BOT_ACCOUNT_SUFFIX_RE = re.compile(r"^RPR\d+$")


class InvalidGrantFlag(ValueError):
    """The REHEARSAL_GRANTS_ENABLED value is invalid."""

    pass


class NoRehearsalMarker(ValueError):
    """The rehearsal marker is missing or has the wrong value."""

    pass


def check_grants_flag(value):
    """Validate the REHEARSAL_GRANTS_ENABLED environment variable.

    Args:
        value: The value to validate. May be None, an empty string, or a
            string containing the exact value.

    Raises:
        InvalidGrantFlag: If the value is not exactly "grants: enabled".

    The rehearsal grant flag lives only in the rehearsal world, behind a guard
    that requires the rehearsal namespace, an explicit flag that exists only
    in the rehearsal deployment, and a marker table only the clone creates.
    """
    if value != REHEARSAL_GRANTS_ENABLED_VALUE:
        raise InvalidGrantFlag(
            f"Expected REHEARSAL_GRANTS_ENABLED to be {REHEARSAL_GRANTS_ENABLED_VALUE!r}, "
            f"got {value!r}"
        )


def check_rehearsal_marker(value):
    """Validate the rehearsal marker value in the database.

    Args:
        value: The marker value to validate.

    Raises:
        NoRehearsalMarker: If the value is not the expected rehearsal marker.

    The marker is written by the rehearsal template when it is built, so a
    world that did not come from a rehearsal template has none.
    """
    if value != REHEARSAL_MARKER_VALUE:
        raise NoRehearsalMarker(
            f"Expected rehearsal marker row to be {REHEARSAL_MARKER_ROW!r}, "
            f"got marker = {value!r}"
        )


def validate_bot_account_prefix(value):
    """Validate a bot account prefix used in the rehearsal world.

    Args:
        value: The prefix to validate.

    Raises:
        ValueError: If the prefix does not match the required pattern.

    Bot accounts in the rehearsal world use the prefix RPR followed by a
    number, to distinguish them from organic bot accounts.
    """
    if not BOT_ACCOUNT_SUFFIX_RE.match(value):
        raise ValueError(
            f"Bot account prefix must match {BOT_ACCOUNT_SUFFIX_RE.pattern!r}, "
            f"got {value!r}"
        )
