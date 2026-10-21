"""Reading party and raid chat aloud: the feed and one voice per character.

Pure stdlib module, same seam as relay.py: no SQL, no HTTP, no browser
objects. map_server.py reads overseer_chat and hands the rows here; the page
(app/views/now/chatvoice.js) queues, ducks and speaks what this returns.

overseer_chat stores one row per LISTENER, so a party line heard by five is
five rows. The feed reuses relay.collapse_hearers for that and
relay.partition_addon for addon protocol riding the channel, rather than
solving either again. It never touches `relayed`, which belongs to the
Discord relay: the page keeps its own cursor, the row id.
"""

from __future__ import annotations

import hashlib
import logging

import bonds
import cast
import relay

# The channels read aloud. Raid is here from the start, so a family in a raid
# group is heard with no further change. Guild, say, yell and whisper are not.
CHANNELS = ("party", "raid")
# At most this many raw rows per poll. A council burst must not become a
# minute of backlog; the page's queue drops what it cannot say in time.
PAGE = 20

# THE FAMILIES' VOICES, hand-set by live name. pitch and rate are on the
# browser speechSynthesis scale, 1.0 neutral. Grug low, slow and gruff; Ugga
# mid; the boys higher and quicker, Bork the highest and quickest because he
# is the smallest. Zug's band runs from the chief (lowest) down to the
# youngest. Every pitch and every rate differs, so two characters who land on
# the same system voice still sound apart.
_LIVE_VOICES: dict[str, tuple[float, float]] = {
    "Grug": (0.70, 0.85),
    "Ugga": (1.10, 0.94),
    "Og": (0.95, 1.00),
    "Grog": (1.30, 1.12),
    "Bork": (1.55, 1.25),
    "Zug": (0.75, 0.88),
    "Zrog": (0.85, 0.92),
    "Uzza": (0.90, 0.96),
    "Oz": (1.05, 1.08),
    "Zork": (1.15, 1.02),
}
# The same table in the names this process's world uses (cast.py), as
# bonds.FAMILY is.
_VOICES = {cast.rename(name): pr for name, pr in _LIVE_VOICES.items()}

# A speaker no family claims gets a pitch and a rate inside these bounds,
# drawn from a hash of the name.
_UNKNOWN_PITCH = (0.85, 1.25)
_UNKNOWN_RATE = (0.90, 1.15)

log = logging.getLogger(__name__)


def voice_for(name: str) -> dict:
    """{engine_voice_hint, pitch, rate} for `name`, the same on every call.

    A family member keeps the hand-set pitch and rate, and the hint carries
    the gender bonds.Bond records so the page can pick a matching system
    voice where the platform names one. Anyone else gets a hash-derived
    pitch and rate, deterministic across reloads and processes.
    """
    bond = bonds.bond_of(name)
    pitch, rate = _VOICES.get(bonds.canon_of(name) or "") or _hashed(name or "")
    return {
        "engine_voice_hint": {"lang": "en", "gender": bond.gender if bond else ""},
        "pitch": pitch,
        "rate": rate,
    }


def _hashed(name: str) -> tuple[float, float]:
    """(pitch, rate) from a hash of the lower-cased name: chat is case-blind."""
    digest = hashlib.sha256(name.strip().lower().encode("utf-8")).digest()
    lo, hi = _UNKNOWN_PITCH
    pitch = round(lo + (hi - lo) * digest[0] / 255, 2)
    lo, hi = _UNKNOWN_RATE
    rate = round(lo + (hi - lo) * digest[1] / 255, 2)
    return pitch, rate


def feed(rows: list[dict], cursor: int) -> dict:
    """{rows: one voiced line per utterance, cursor: the next `after`}.

    The cursor moves past every raw row read, the hearers' copies and the
    addon rows included. Moving it only to the last line spoken would read
    the dropped copies again on the next poll, where they would collapse to
    one row and be spoken a second time. A row without a whole id or age
    is logged and left out: it cannot move the cursor or be timed.
    """
    rows = [row for row in rows if _well_formed(row)]
    top = max([cursor, *(int(row["id"]) for row in rows)])
    kept, _copies = relay.collapse_hearers(rows)
    spoken, _addon = relay.partition_addon(kept)
    return {"rows": [_line(row) for row in spoken], "cursor": top}


def _well_formed(row: dict) -> bool:
    """True when the row's id and age (if any) read as whole numbers."""
    try:
        int(row["id"])
        int(row.get("age_s") or 0)
    except (KeyError, TypeError, ValueError):
        log.warning("party chat row skipped, no whole id or age: %r", row)
        return False
    return True


def _line(row: dict) -> dict:
    """One row as the page reads it, with the voice its speaker uses."""
    sender = str(row.get("sender_name") or "")
    return {
        "id": int(row["id"]),
        "sender": sender,
        "channel": str(row.get("channel") or ""),
        "text": str(row.get("text") or ""),
        "age_s": int(row.get("age_s") or 0),
        "voice": voice_for(sender),
    }
