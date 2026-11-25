"""Hold and loop clocks that survive a bridge restart (#3226).

The bridge keeps its clocks on the monotonic clock, which starts again with
the process: a restart made every hold begin its wait afresh, and a family
went back to town once per restart. This module keeps the same clocks in the
bridge memo store, written as wall time, and turns them back into monotonic
readings when the next process reads them.

PURE MODULE: no MySQL, no clock of its own. The caller passes the store
functions and the two clocks.
"""

from __future__ import annotations

import time

# How long a stored clock is kept. Longer than any hold's own ceiling, so an
# entry only lapses once nothing has touched it for days.
KEEP_SECONDS = 3 * 86400.0

PROF_LOOP_KIND = "prof_loop_state"
GEAR_HOLD_KIND = "gear_hold_clock"
TOWN_FIRST_KIND = "town_first_clock"

# profloop.State fields that hold a monotonic reading (0.0 means unset).
_STATE_TIMES = ("since", "asserted", "queued_since")


def subject(key) -> str:
    """The memo subject for a clock key (a name, or a tuple of names)."""
    if isinstance(key, (tuple, list)):
        return "|".join(str(k) for k in key)
    return str(key)


def to_wall(mono: float, mono_now: float, wall_now: float) -> float:
    return wall_now - (mono_now - mono)


def to_mono(wall: float, mono_now: float, wall_now: float) -> float:
    """A stored wall time as a monotonic reading; never later than now."""
    return min(mono_now, mono_now - (wall_now - wall))


def state_to_wall(state, mono_now: float, wall_now: float) -> dict:
    out = {}
    for field in _STATE_TIMES:
        value = float(getattr(state, field))
        out[field] = to_wall(value, mono_now, wall_now) if value else 0.0
    out["phase"] = state.phase
    out["town_seen"] = bool(state.town_seen)
    out["entered"] = [list(p) for p in state.entered]
    out["fruitless"] = list(state.fruitless)
    out["fruitless_stamps"] = [
        [name, to_wall(float(at), mono_now, wall_now)]
        for name, at in state.fruitless_stamps]
    out["yielded"] = bool(state.yielded)
    return out


def state_from_wall(cls, data: dict, mono_now: float, wall_now: float):
    """A State of class `cls` from state_to_wall's dict; None when unreadable."""
    try:
        kw = {"phase": str(data["phase"]),
              "town_seen": bool(data["town_seen"]),
              "yielded": bool(data["yielded"]),
              "entered": tuple((str(n), v) for n, v in data["entered"]),
              "fruitless": tuple(str(n) for n in data["fruitless"]),
              "fruitless_stamps": tuple(
                  (str(n), to_mono(float(w), mono_now, wall_now))
                  for n, w in data["fruitless_stamps"])}
        for field in _STATE_TIMES:
            w = float(data[field])
            kw[field] = to_mono(w, mono_now, wall_now) if w else 0.0
        return cls(**kw)
    except (KeyError, TypeError, ValueError):
        return None


class Clocks(dict):
    """key -> monotonic reading, mirrored to the memo store as wall time.

    A dict in every read; the writes the bridge makes (setdefault, item
    assignment, pop) also reach the store. The store is read once, on first
    use, so a restart finds the clocks the last process left.
    """

    def __init__(self, kind, read, upsert, delete,
                 mono=time.monotonic, wall=time.time):
        super().__init__()
        self._kind, self._read, self._upsert, self._delete = (
            kind, read, upsert, delete)
        self._mono, self._wall = mono, wall
        self._loaded = False
        self._keys = {}

    def load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        mono_now, wall_now = self._mono(), self._wall()
        try:
            rows = self._read(self._kind)
        except Exception:
            return
        for sub, (value, _since) in rows.items():
            try:
                key = tuple(sub.split("|"))
                dict.__setitem__(self, key, to_mono(float(value), mono_now, wall_now))
                self._keys[key] = sub
            except (TypeError, ValueError):
                continue

    def _save(self, key, mono) -> None:
        wall_now = self._wall()
        wall = to_wall(mono, self._mono(), wall_now)
        try:
            self._upsert(self._kind, subject(key), wall, wall_now,
                         wall_now + KEEP_SECONDS)
        except Exception:
            pass

    def __getitem__(self, key):
        self.load()
        return dict.__getitem__(self, key)

    def get(self, key, default=None):
        self.load()
        return dict.get(self, key, default)

    def __contains__(self, key):
        self.load()
        return dict.__contains__(self, key)

    def __setitem__(self, key, value):
        self.load()
        dict.__setitem__(self, key, value)
        self._save(key, value)

    def setdefault(self, key, default=None):
        self.load()
        if dict.__contains__(self, key):
            return dict.__getitem__(self, key)
        self[key] = default
        return default

    def pop(self, key, *default):
        self.load()
        had = dict.__contains__(self, key)
        value = dict.pop(self, key, *default)
        if had:
            try:
                self._delete(self._kind, subject(key))
            except Exception:
                pass
        return value
