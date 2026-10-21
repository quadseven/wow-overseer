"""Reading party and raid chat aloud: one voice per character.

Pure stdlib module, same seam as relay.py (infra#2597): no SQL, no HTTP, no
browser objects. The whole feature - the voice table, the row shaping, and the
rate-limited queue - can be tested here with no database and no browser.

The voice table is derived from bonds.Bond (gender, role, age from seniority,
persona) and hand-set for the family. Anyone outside the family gets a
deterministic, hash-derived voice so the choice never shifts between one line
and the next.

Ticket: 177.
"""

from __future__ import annotations

import hashlib
import time

import bonds
import relay

# One row per utterance, newest first, at most this many. A council burst must
# not become a minute of backlog.
_PAGE_CAP = 20
# A line older than this, in seconds, is stale when the queue backs up and is
# dropped rather than spoken long after the moment passed.
_STALE_SECONDS = 20.0
# The same speaker saying the same words within this many seconds is a repeat
# and is skipped (the page's own guard on top of chat.py's SAY IT ONCE rule).
_REPEAT_SECONDS = 60.0
# The queue never grows beyond this; the oldest lines fall off first.
_QUEUE_CAP = 50

# THE FAMILY'S VOICES, hand-set from bonds.Bond (gender, role, age from
# seniority, persona). Stable across reloads: deterministic, never random, so
# the same character always sounds the same. Grug low, slow and gruff; Ugga
# mid; the boys higher and quicker.
#
# pitch and rate sit at the browser speechSynthesis scale: 0.5-2.0 for pitch,
# 0.1-10 (0.5-2 sensible) for rate, with 1.0 the neutral default.
_VOICES: dict[str, dict] = {
    "Grug": {"engine_voice_hint": "male-low", "pitch": 0.80, "rate": 0.90},
    "Ugga": {"engine_voice_hint": "female-mid", "pitch": 1.00, "rate": 1.00},
    "Grog": {"engine_voice_hint": "male-mid", "pitch": 1.10, "rate": 1.10},
    "Bork": {"engine_voice_hint": "male-high", "pitch": 1.30, "rate": 1.20},
    "Og": {"engine_voice_hint": "male-mid", "pitch": 1.05, "rate": 0.95},
}


def voice_for(name: str) -> dict:
    """{engine_voice_hint, pitch, rate} for `name`.

    Family members keep their hand-set voice. Anyone outside the family gets a
    hash-derived voice, deterministic across reloads and stable across lines,
    so the choice never shifts between one line and the next.
    """
    canonical = bonds.canon_of(name)
    if canonical is not None and canonical in _VOICES:
        return dict(_VOICES[canonical])
    return _voice_for_unknown(name or "")


def _voice_for_unknown(name: str) -> dict:
    """A deterministic voice for a speaker no bond knows.

    Drawn from a hash of the name, so it never changes between lines and never
    depends on import order, process restarts or anything random.
    """
    digest = hashlib.sha256(name.encode("utf-8")).digest()
    pitch = round(0.85 + 0.30 * (digest[0] / 255), 2)
    rate = round(0.90 + 0.30 * (digest[1] / 255), 2)
    hint = "male-low" if digest[2] < 128 else "female-mid"
    return {"engine_voice_hint": hint, "pitch": pitch, "rate": rate}


def shape(rows: list[dict]) -> tuple[list[dict], list[int]]:
    """(one row per utterance, ids of the copies to retire).

    Applies relay.collapse_hearers then relay.partition_addon, in that order,
    so the page never speaks a line twice (five listeners, one line) and never
    speaks machine traffic (addon protocol riding the channel).
    """
    kept, dropped = relay.collapse_hearers(rows)
    kept, addon_dropped = relay.partition_addon(kept)
    return kept, dropped + addon_dropped


class ChatQueue:
    """One line at a time: stale lines dropped, exact repeats skipped, capped.

    Pure logic the page's speech loop drives. `enqueue` accepts shaped rows,
    `next` hands out the next line to speak (None while one is speaking), and
    `start`/`finish` mark the speaking window so ducking can lift on end or
    error.
    """

    def __init__(
        self,
        *,
        cap: int = _QUEUE_CAP,
        stale_seconds: float = _STALE_SECONDS,
        repeat_seconds: float = _REPEAT_SECONDS,
        now: callable = time.time,
    ) -> None:
        self.cap = cap
        self.stale_seconds = stale_seconds
        self.repeat_seconds = repeat_seconds
        self._now = now
        self._lines: list[dict] = []
        self._speaking = False
        # (speaker, text) -> moment last spoken, for the repeat guard.
        self._spoken: dict[tuple, float] = {}

    def enqueue(self, rows: list[dict]) -> None:
        """Add shaped rows, dropping stale ones and repeats, capping the total.

        A row carries `moment` (unix seconds) for the staleness check; rows
        without one are treated as fresh.
        """
        now = self._now()
        accepted: list[dict] = []
        for row in rows:
            moment = row.get("moment")
            if moment is not None and now - moment > self.stale_seconds:
                continue
            key = (row.get("sender_name"), row.get("text"))
            last = self._spoken.get(key)
            if last is not None and now - last < self.repeat_seconds:
                continue
            accepted.append(row)
        self._lines.extend(accepted)
        if len(self._lines) > self.cap:
            self._lines = self._lines[-self.cap :]

    def start(self) -> None:
        """A line is now being spoken; next() returns None until finish()."""
        self._speaking = True

    def finish(self) -> None:
        """The speaking line is done (spoken or errored); next() may run."""
        self._speaking = False

    def next(self) -> dict | None:
        """The next line to speak, or None while speaking or empty.

        Marks the line spoken so the repeat guard skips a second copy within
        the repeat window.
        """
        if self._speaking or not self._lines:
            return None
        row = self._lines.pop(0)
        self._speaking = True
        key = (row.get("sender_name"), row.get("text"))
        self._spoken[key] = self._now()
        return row

    def queued(self) -> int:
        """How many lines are waiting to be spoken."""
        return len(self._lines)
