"""Hold and loop clocks that survive a bridge restart (#3226).

The bridge keeps its clocks on the monotonic clock, which starts again with
the process: a restart made every hold begin its wait afresh, and a family
went back to town once per restart. This module keeps the same clocks in the
bridge memo store, written as wall time, and turns them back into monotonic
readings when the next process reads them.

PURE MODULE: no MySQL, no clock of its own. The caller passes the store
functions and the two clocks.

A store that fails never stops a bridge pass: the clock keeps working in
memory for this process. Each failure is logged with its traceback, because
a clock that was not stored starts again at the next restart.
"""

from __future__ import annotations

import logging
import time

LOG = logging.getLogger(__name__)

# How long a stored clock is kept. Longer than any hold's own ceiling, so an
# entry only lapses once nothing has touched it for days.
KEEP_SECONDS = 3 * 86400.0

PROF_LOOP_KIND = "prof_loop_state"
GEAR_HOLD_KIND = "gear_hold_clock"
TOWN_FIRST_KIND = "town_first_clock"
TOWN_ERRAND_KIND = "town_errand_end"

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
        for name, at in state.fruitless_stamps
    ]
    out["yielded"] = bool(state.yielded)
    return out


def state_from_wall(cls, data: dict, mono_now: float, wall_now: float):
    """A State of class `cls` from state_to_wall's dict; None when unreadable."""
    try:
        kw = {
            "phase": str(data["phase"]),
            "town_seen": bool(data["town_seen"]),
            "yielded": bool(data["yielded"]),
            "entered": tuple((str(n), v) for n, v in data["entered"]),
            "fruitless": tuple(str(n) for n in data["fruitless"]),
            "fruitless_stamps": tuple(
                (str(n), to_mono(float(w), mono_now, wall_now))
                for n, w in data["fruitless_stamps"]
            ),
        }
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

    def __init__(self, kind, read, upsert, delete, mono=time.monotonic, wall=time.time):
        super().__init__()
        self._kind, self._read, self._upsert, self._delete = (
            kind,
            read,
            upsert,
            delete,
        )
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
            LOG.warning(
                "hold clock %s: stored clocks could not be read, starting empty",
                self._kind,
                exc_info=True,
            )
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
            self._upsert(
                self._kind, subject(key), wall, wall_now, wall_now + KEEP_SECONDS
            )
        except Exception:
            LOG.warning(
                "hold clock %s: %s was not stored and will restart with the bridge",
                self._kind,
                subject(key),
                exc_info=True,
            )

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
                LOG.warning(
                    "hold clock %s: %s was not cleared from the store",
                    self._kind,
                    subject(key),
                    exc_info=True,
                )
        return value


class ErrandEnds(dict):
    """key -> town errand state, with each errand's end mirrored to the store.

    The town errand's cooldown runs from `State.ended`, a monotonic reading,
    so a restart forgot it and a family that had just been to town went
    again at once. Only what the cooldown reads is stored: the end, whether
    a run was seen since, and whether the walk never landed. A restored
    family starts idle with that end; an errand under way is not resumed.
    `make` builds the state from those three fields.
    """

    def __init__(
        self, kind, read, upsert, delete, make, mono=time.monotonic, wall=time.time
    ):
        super().__init__()
        self._kind, self._read, self._upsert, self._delete = (
            kind,
            read,
            upsert,
            delete,
        )
        self._make = make
        self._mono, self._wall = mono, wall
        self._loaded = False
        self._saved = {}

    @staticmethod
    def _mark(state):
        return (
            float(getattr(state, "ended", 0.0) or 0.0),
            bool(getattr(state, "ran_since", False)),
            bool(getattr(state, "unlanded", False)),
        )

    def load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        mono_now, wall_now = self._mono(), self._wall()
        try:
            rows = self._read(self._kind)
        except Exception:
            LOG.warning(
                "hold clock %s: stored errand ends could not be read, starting empty",
                self._kind,
                exc_info=True,
            )
            return
        for sub, (value, _since) in rows.items():
            try:
                key = tuple(sub.split("|"))
                wall = float(value["ended"])
                if wall <= 0 or dict.__contains__(self, key):
                    continue
                state = self._make(
                    ended=to_mono(wall, mono_now, wall_now),
                    ran_since=bool(value.get("ran_since")),
                    unlanded=bool(value.get("unlanded")),
                )
            except (KeyError, TypeError, ValueError, AttributeError):
                continue
            dict.__setitem__(self, key, state)
            self._saved[key] = self._mark(state)

    def _save(self, key, state) -> None:
        mark = self._mark(state)
        if not mark[0] or self._saved.get(key) == mark:
            return
        self._saved[key] = mark
        wall_now = self._wall()
        value = {
            "ended": to_wall(mark[0], self._mono(), wall_now),
            "ran_since": mark[1],
            "unlanded": mark[2],
        }
        try:
            self._upsert(
                self._kind, subject(key), value, wall_now, wall_now + KEEP_SECONDS
            )
        except Exception:
            self._saved.pop(key, None)
            LOG.warning(
                "hold clock %s: %s was not stored and will restart with the bridge",
                self._kind,
                subject(key),
                exc_info=True,
            )

    def __getitem__(self, key):
        self.load()
        return dict.__getitem__(self, key)

    def get(self, key, default=None):
        self.load()
        return dict.get(self, key, default)

    def __contains__(self, key):
        self.load()
        return dict.__contains__(self, key)

    def __iter__(self):
        self.load()
        return dict.__iter__(self)

    def keys(self):
        self.load()
        return dict.keys(self)

    def values(self):
        self.load()
        return dict.values(self)

    def items(self):
        self.load()
        return dict.items(self)

    def __setitem__(self, key, value):
        self.load()
        dict.__setitem__(self, key, value)
        self._save(key, value)
