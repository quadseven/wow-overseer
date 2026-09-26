"""LLM_MODE=off: one switch that stops every language model call.

Both `_ask_llm` implementations (bridge.py and map_server.py) call `check()`
before they build a request. With the switch off, `check()` raises `LLMOff`
instead of sending anything, so each caller takes the fallback it already has
for an unreachable model: a templated event line, the plain sentence instead of
the in-character one, an order relayed untranslated, a digest with no greeting.
Characters stop speaking in their own voice. Nothing is retried, because every
caller already treats a failed call as final for that turn.

Why a switch and not an unreachable URL: an unreachable URL still costs a
connection attempt and a timeout per call, and it reads in the log as an outage
rather than a decision. The switch sends nothing and says so once.

Only "off" turns it off, matching VISION_MODE in vision.py. Any other value,
or no value, leaves the model on, so an existing deployment is unchanged.
"""

from __future__ import annotations

import logging
import os
import threading

log = logging.getLogger("wow-overseer.llm")

_lock = threading.Lock()
_announced = False


class LLMOff(RuntimeError):
    """Raised instead of a network call while LLM_MODE=off."""


def enabled(environ=None) -> bool:
    """False only when LLM_MODE is "off" (any case, surrounding space ignored)."""
    env = os.environ if environ is None else environ
    return str(env.get("LLM_MODE", "") or "").strip().lower() != "off"


def check(environ=None) -> None:
    """Return when calls are allowed; otherwise log once and raise LLMOff.

    The log line is once per process on purpose: the event narrator alone
    would otherwise repeat it every cycle, and the fact it reports does not
    change until the pod is restarted with a different environment.
    """
    if enabled(environ):
        return
    global _announced
    with _lock:
        first = not _announced
        _announced = True
    if first:
        log.warning(
            "LLM_MODE=off: no language model calls will be made; "
            "characters fall back to their plain lines"
        )
    raise LLMOff("LLM_MODE=off")
