"""What a guild member said lately, and the wording it may use now (#1636).

A reader watching the guild feed for 40 minutes should not see one member say
the same sentence twice. The social layer words an answer from a small pool
of templates, and a busy member answers more asks in a sitting than its pool
has wordings. Read on the dev realm on 2026-11-15: 2,958 guild lines in a
day, 126 of them the same member repeating its own sentence within 40
minutes. The pick skipped a wording said lately, but once every wording was
used it fell back to the first of the pool, whenever that one was last said.

Pure: the caller passes the answers it read and the clock.
"""

from __future__ import annotations

# One sitting: the 40 minutes a reader watched (#1636).
SAY_AGAIN_MINUTES = 40.0
# An answer read without its time. Old, not fresh: an unread time must never
# silence a member.
_UNKNOWN_AGE = 1e9


def _minutes_since(when, now) -> float:
    if when is None or now is None:
        return _UNKNOWN_AGE
    return max(0.0, (now - when).total_seconds() / 60.0)


def lately(answers, now) -> dict:
    """member -> {line: minutes since the member last said it}."""
    out: dict = {}
    for a in answers or ():
        if not a.said:
            continue
        age = _minutes_since(getattr(a, "created_at", None), now)
        lines = out.setdefault(a.member, {})
        lines[a.said] = min(age, lines.get(a.said, age))
    return out


def pick(options: tuple, render, said, start: int):
    """The template to say, or None to say nothing.

    `said` is the speaker's own {line: minutes since it said it}. The first
    template from `start` whose line it has not said; else the one it said
    longest ago, when that is at least SAY_AGAIN_MINUTES back; else None,
    because every wording it has was said this sitting.
    """
    order = [options[(start + step) % len(options)] for step in range(len(options))]
    for template in order:
        if render(template) not in said:
            return template
    oldest = max(order, key=lambda template: said[render(template)])
    if said[render(oldest)] >= SAY_AGAIN_MINUTES:
        return oldest
    return None
