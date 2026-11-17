"""The send seam's repeat gate: the same line is not spoken twice (#2247).

Guild chat showed the same line from the same member more than once in a
second, and one member repeating an identical reagent request. Every spoken row
passes `bridge._insert_speak`, so the gate sits there and no producer needs to
know about it.

THE RULE. A line is the speaker, the channel, who it is whispered to and the
words (casefolded, whitespace collapsed). The same line inside
`DEDUPE_SECONDS` of its last send is suppressed. A STANDING request (a source
in `STANDING_PREFIXES`, the craft and reagent asks) is repeated only after
`STANDING_SECONDS`. A suppressed line is counted by reason and the caller logs
it; nothing is dropped silently.

PURE: a ledger of key -> the monotonic moment it was last sent, in, a verdict
out. No MySQL, no clock of its own.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

DEDUPE_SECONDS = 30.0
STANDING_SECONDS = 1800.0
# Sources whose lines are standing asks, repeated only after STANDING_SECONDS.
STANDING_PREFIXES = ("overseer:craft:",)

SEND = "send"
SAME_LINE = "the same line from the same speaker inside %d seconds"
STANDING = "a standing request repeated inside %d seconds"


def _seconds(name: str, default: float, environ=None) -> float:
    env = os.environ if environ is None else environ
    try:
        value = float(str(env.get(name, "") or "").strip())
    except ValueError:
        return default
    return value if value >= 0 else default


def line_key(speaker, channel, whisper_to, text) -> tuple:
    return (
        str(speaker or "").strip().casefold(),
        str(channel or "").strip().casefold(),
        str(whisper_to or "").strip().casefold(),
        " ".join(str(text or "").split()).casefold(),
    )


def is_standing(source) -> bool:
    return str(source or "").startswith(STANDING_PREFIXES)


@dataclass
class SpeakGate:
    """Remembers when each line was last sent, and counts what it held back."""

    dedupe_seconds: float = DEDUPE_SECONDS
    standing_seconds: float = STANDING_SECONDS
    sent: dict = field(default_factory=dict)
    suppressed: dict = field(default_factory=dict)

    @classmethod
    def from_environ(cls, environ=None) -> "SpeakGate":
        return cls(
            _seconds("SPEAK_DEDUPE_SECONDS", DEDUPE_SECONDS, environ),
            _seconds("SPEAK_STANDING_SECONDS", STANDING_SECONDS, environ),
        )

    def check(self, speaker, channel, whisper_to, text, source, now: float) -> str:
        """SEND to write the line (and remember it), or the reason it is a
        repeat. The ledger is pruned of expired lines as it is asked."""
        longest = max(self.dedupe_seconds, self.standing_seconds)
        for old, when in list(self.sent.items()):
            if now - when >= longest:
                del self.sent[old]
        key = line_key(speaker, channel, whisper_to, text)
        standing = is_standing(source)
        window = self.standing_seconds if standing else self.dedupe_seconds
        last = self.sent.get(key)
        if last is not None and now - last < window:
            reason = (STANDING if standing else SAME_LINE) % int(window)
            self.suppressed[reason] = self.suppressed.get(reason, 0) + 1
            return reason
        self.sent[key] = now
        return SEND
