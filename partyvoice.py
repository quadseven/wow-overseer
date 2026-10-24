"""Reading party and raid chat aloud: which lines, and in whose voice.

Pure stdlib, the same seam as relay.py: no SQL, no HTTP, no browser. The map
server reads overseer_chat and hands the rows here; the page (app/views/now/
chatvoice.js) speaks what comes back through the browser's speechSynthesis.

WHICH LINES. overseer_chat stores a row per LISTENER, so a party line with
five in the party is five rows, and addon protocol rides the same channels.
relay.collapse_hearers and relay.partition_addon already answer both for the
Discord relay; the feed reuses them rather than re-solving them. The relay's
`relayed` column is never read or written here: the page keeps its own
cursor, the row id.

WHOSE VOICE. pitch and rate are on the speechSynthesis scale (1.0 neutral).
Two characters may land on one system voice, so pitch and rate carry the
difference on their own. The family's are hand-set; the language and gender
the browser picks a system voice by come from bonds.Bond. Anyone no family
claims gets a voice drawn from a hash of the name: stable from one line to the
next and across reloads, never random.

Ticket: 177.
"""

from __future__ import annotations

import hashlib

import bonds
import cast
import relay

# What the feed reads. Raid is here from the start, so a family in a raid
# group is heard with no further change.
CHANNELS = ("party", "raid")

# The smallest pitch-or-rate gap that still sounds like a different person.
MIN_APART = 0.1

# (pitch, rate) by LIVE name: a renamed world (cast.py) reads the same table.
# Grug low, slow and gruff; Ugga mid; the boys higher and quicker. Zug's band
# deep and unhurried at the top, Oz quick and young.
FAMILY_VOICES: dict[str, tuple[float, float]] = {
    "Grug": (0.7, 0.85),
    "Ugga": (1.15, 1.0),
    "Grog": (1.3, 1.05),
    "Bork": (1.55, 1.2),
    "Og": (0.9, 0.95),
    "Zug": (0.6, 0.9),
    "Zrog": (0.85, 1.1),
    "Uzza": (1.0, 0.9),
    "Oz": (1.15, 1.2),
    "Zork": (0.5, 0.8),
}

_LIVE_NAME = {renamed: live for live, renamed in cast.names().items()}


def voice_for(name: str) -> dict:
    """{engine_voice_hint, pitch, rate} for a speaker, the same every time."""
    canonical = bonds.canon_of(name)
    pitch_rate = (
        FAMILY_VOICES.get(_LIVE_NAME.get(canonical, canonical)) if canonical else None
    )
    bond = bonds.bond_of(name)
    if pitch_rate is None or bond is None:
        return _stranger_voice(name)
    pitch, rate = pitch_rate
    hint = "en-" + bond.gender if bond.gender else "en"
    return {"engine_voice_hint": hint, "pitch": pitch, "rate": rate}


def _stranger_voice(name: str) -> dict:
    """A voice drawn from a hash of the name: deterministic, never random."""
    digest = hashlib.sha256((name or "").strip().lower().encode("utf-8")).digest()
    return {
        "engine_voice_hint": "en",
        "pitch": round(0.8 + 0.5 * digest[0] / 255, 2),
        "rate": round(0.9 + 0.3 * digest[1] / 255, 2),
    }


def feed(rows: list[dict], after: int) -> dict:
    """The /api/chat/party payload for `rows` read past the cursor `after`.

    One row per utterance, addon traffic dropped, each with its speaker's
    voice. `after` moves past EVERY row read, the dropped copies included:
    a page of nothing but copies must still advance, or the feed stalls.
    """
    spoken, _copies = relay.collapse_hearers(rows)
    spoken, _addon = relay.partition_addon(spoken)
    return {
        "rows": [_line(row) for row in spoken],
        "after": max((int(row["id"]) for row in rows), default=after),
    }


def _line(row: dict) -> dict:
    speaker = str(row.get("sender_name") or "")
    age = row.get("age_s")
    return {
        "id": int(row["id"]),
        "speaker": speaker,
        "channel": str(row.get("channel") or ""),
        "text": str(row.get("text") or ""),
        "age_s": None if age is None else int(age),
        "voice": voice_for(speaker),
    }
