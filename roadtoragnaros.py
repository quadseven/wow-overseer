"""The road to a Ragnaros attempt: one total per guild, every blocker named.

WHY THIS EXISTS. The goal contract reads as eight checkpoints, A to H, and the
Raid page shows six per-seat gates. Neither says, in one place, how far a guild
is from a Molten Core attempt or which blocker keeps the most of the 40 seats
back. This module folds reads that already exist into that answer.

PURE: rows in, a dict out. It never touches the database. apiv2/ragnaros.py
makes the reads (the goal read, the raidteams read, the Molten Core runs) and
hands them here.

THE SEATS ARE THE 40 APPROVED SEATS. A seat with no member is open and fails
every milestone; it is never filled with a guess. A seat whose value the realm
could not read is `unread` for that milestone: it counts as neither passing nor
short.

THE PERCENT OF A MILESTONE is seats passing over the seats that could be read
(the 40, less the unread ones). A milestone nobody could read, or one this
module has no small, correct read for, is `measured: false` with its reason.

THE TOTAL is the mean of those percents over the measured seat milestones
(A, B, C, E, F). An unmeasured milestone is left out: it is not counted as
passed and not as zero, and the total names the ones it left out. H, the
attempt itself, is not a seat count and is not in the mean; the total is 100
only when Ragnaros has fallen.
"""

from __future__ import annotations

import guildrun
import raidrun
import raidsupply

SEATS = 40
NAMES_SHOWN = 5

LEVEL_A, LEVEL_B, LEVEL_C = 20, 40, 60

KEY_NOT_MEASURED = {
    "D": (
        "the faction's classic dungeons cleared in level order: the ladder's "
        "rungs depend on faction, level, keys and crossings, and no small read "
        "of 'every one cleared' exists yet"
    ),
    "G": (
        "repair and summoning coverage: the summoners and maintenance members "
        "are not seats, and no read of their levels, skills or summon spell "
        "exists yet"
    ),
}

MILESTONES = (
    ("A", "40 seats at level 20", "every seat filled, level 20 or higher"),
    (
        "B",
        "40 seats at level 40",
        "level 40 or higher; class quests are not checked per seat",
    ),
    ("C", "40 seats at level 60", "level 60"),
    ("D", "Classic dungeons cleared in level order", "the faction's dungeons"),
    ("E", "Molten Core attunement", "Attunement to the Core rewarded"),
    (
        "F",
        "Fire resistance and supplies",
        "worn fire resistance at the role's target and the night's supplies in bags",
    ),
    ("G", "Repair and summoning coverage", "engineers and summoners in place"),
    ("H", "Ragnaros", "Ragnaros killed"),
)


def _blocker(key: str, text: str, short: list) -> dict:
    return {
        "key": key,
        "text": text,
        "seats_short": len(short),
        "names": [n for n in short[:NAMES_SHOWN]],
    }


def _seat_rows(teams: dict | None) -> list:
    """One row per approved seat: its seat, the member (or None) and fields."""
    if not teams:
        return []
    members = teams.get("members") or {}
    rows = []
    main_given = False
    for group in teams.get("seats") or []:
        for seat in group:
            name = seat.get("name")
            member = members.get(name) if name else None
            main = False
            if seat.get("seat") == "tank" and not main_given:
                main, main_given = True, True
            rows.append(
                {
                    "label": name or seat.get("approved") or "",
                    "open": not name,
                    "seat": seat,
                    "member": member or {},
                    "main_tank": main,
                }
            )
    return rows


def _level_test(floor: int):
    def test(row):
        if row["open"]:
            return False
        level = row["member"].get("level")
        return None if level is None else int(level) >= floor

    return test


def _attuned(row):
    if row["open"]:
        return False
    return row["member"].get("attuned")


def _supplies(row) -> bool | None:
    held = row["member"].get("consumables")
    if held is None:
        return None
    seat = row["seat"]
    raider = raidsupply.Raider(
        seat.get("name") or "",
        raidsupply.role_of(seat.get("seat") or "", seat.get("class_id")),
        int(seat.get("class_id") or 0),
        row["main_tank"],
    )
    for supply in raidsupply.SUPPLIES:
        want = 0 if supply.stands_in else supply.per_raider(raider)
        if want <= 0:
            continue
        entries = [supply.entry] + [
            s.entry for s in raidsupply.SUPPLIES if s.stands_in == supply.entry
        ]
        if sum(int(held.get(str(e), 0)) for e in entries) < want:
            return False
    return True


def _fire(row) -> bool | None:
    fire = row["member"].get("fire_resistance")
    if fire is None:
        return None
    seat = row["seat"]
    raider = raidsupply.Raider(
        seat.get("name") or "",
        raidsupply.role_of(seat.get("seat") or "", seat.get("class_id")),
        int(seat.get("class_id") or 0),
        row["main_tank"],
    )
    return int(fire) >= raidsupply.fire_target(raider)


def _fire_and_supplies(row):
    if row["open"]:
        return False
    parts = (_fire(row), _supplies(row))
    if False in parts:
        return False
    return None if None in parts else True


def _tally(rows: list, test) -> tuple:
    """(have, unread, failing rows) for `test` over every seat."""
    have = unread = 0
    failing = []
    for row in rows:
        got = test(row)
        if got is True:
            have += 1
        elif got is None:
            unread += 1
        else:
            failing.append(row)
    return have, unread, failing


def _milestone(key, label, rule, rows, test, blockers_of, note="") -> dict:
    have, unread, failing = _tally(rows, test)
    readable = SEATS - unread
    out = {
        "key": key,
        "label": label,
        "rule": rule,
        "unit": "seats",
        "have": have,
        "want": SEATS,
        "unread": unread,
        "seats_short": len(failing),
        "percent": round(100 * have / readable) if readable > 0 else None,
        "measured": readable > 0,
        "blockers": blockers_of(failing) if failing else [],
    }
    if note:
        out["note"] = note
    if not out["measured"]:
        out["reason"] = "the realm could not answer the read"
    return out


def _open_and_below(rows: list, floor: int) -> list:
    opens = [r["label"] for r in rows if r["open"]]
    under = [
        "%s (L%s)" % (r["label"], r["member"].get("level"))
        for r in rows
        if not r["open"]
        and r["member"].get("level") is not None
        and int(r["member"]["level"]) < floor
    ]
    out = []
    if opens:
        out.append(
            _blocker("open-seat", "open seat: no member in the approved seat", opens)
        )
    if under:
        out.append(_blocker("level-%d" % floor, "below level %d" % floor, under))
    return out


def _below(floor: int):
    def blockers(failing):
        under = [
            "%s (L%s)" % (r["label"], r["member"].get("level"))
            for r in failing
            if not r["open"]
        ]
        return (
            [_blocker("level-%d" % floor, "below level %d" % floor, under)]
            if under
            else []
        )

    return blockers


def _unattuned(failing):
    short = [r["label"] for r in failing if not r["open"]]
    if not short:
        return []
    return [_blocker("unattuned", "no Attunement to the Core", short)]


def _fire_blockers(failing):
    fire = [r["label"] for r in failing if not r["open"] and _fire(r) is False]
    supply = [r["label"] for r in failing if not r["open"] and _supplies(r) is False]
    out = []
    if fire:
        out.append(
            _blocker("fire-resistance", "fire resistance under the role's target", fire)
        )
    if supply:
        out.append(_blocker("supplies", "the night's supplies not in bags", supply))
    return out


def attempts(runs: list | None) -> dict:
    """Molten Core runs that went in, wipes and the best boss count."""
    if runs is None:
        return {"measured": False, "reason": "the run table could not be read"}
    went = [r for r in runs if str(r.get("outcome") or "") in guildrun.WENT_IN]
    best = None
    for r in went:
        done = int(r.get("bosses_done") or 0)
        total = int(r.get("bosses_total") or 0)
        if best is None or done > best["bosses_done"]:
            best = {"bosses_done": done, "bosses_total": total or None}
    killed = any(
        str(r.get("outcome") or "") == guildrun.CLEARED
        and guildrun.every_boss_fell(
            int(r.get("bosses_done") or 0), int(r.get("bosses_total") or 0)
        )
        for r in went
    )
    return {
        "measured": True,
        "formed": len(runs),
        "entered": len(went),
        "wiped": sum(1 for r in went if r.get("outcome") == "wiped"),
        "best": best,
        "killed": killed,
    }


def _missing(key, label, rule, reason) -> dict:
    return {
        "key": key,
        "label": label,
        "rule": rule,
        "unit": "seats",
        "have": None,
        "want": SEATS,
        "unread": None,
        "seats_short": None,
        "percent": None,
        "measured": False,
        "reason": reason,
        "blockers": [],
    }


def _total(rows: list) -> dict:
    seat = [m for m in rows if m["unit"] == "seats"]
    counted = [m for m in seat if m["measured"]]
    left_out = [m["key"] for m in seat if not m["measured"]]
    percent = (
        round(sum(m["percent"] for m in counted) / len(counted)) if counted else None
    )
    return {
        "percent": percent,
        "counted": [m["key"] for m in counted],
        "left_out": left_out,
        "how": (
            "The mean of the seat percents of milestones "
            + (", ".join(m["key"] for m in counted) or "(none)")
            + ". "
            + (
                "Milestones "
                + ", ".join(left_out)
                + " are not measured and are left out, "
                "not counted as passed or as zero. "
                if left_out
                else ""
            )
            + "Open seats count as short. H is the attempt and counts when Ragnaros falls."
        ),
    }


SEAT_RULES = {
    "A": (_level_test(LEVEL_A), lambda f: _open_and_below(f, LEVEL_A)),
    "B": (_level_test(LEVEL_B), _below(LEVEL_B)),
    "C": (_level_test(LEVEL_C), _below(LEVEL_C)),
    "E": (_attuned, _unattuned),
    "F": (_fire_and_supplies, _fire_blockers),
}


def _seat_milestone(key, label, rule, rows, stuck) -> dict:
    """One milestone: measured from the seats, or not measured with a reason."""
    if key in KEY_NOT_MEASURED:
        return _missing(key, label, rule, KEY_NOT_MEASURED[key])
    if not rows:
        return _missing(key, label, rule, "the seat read could not be answered")
    test, blockers = SEAT_RULES[key]
    out = _milestone(key, label, rule, rows, test, blockers)
    if key == "B" and stuck:
        held = _blocker(
            "class-quest-ask", "held by a live class quest ask (24h read)", []
        )
        out["blockers"].append(held | {"seats_short": int(stuck)})
    return out


def _ragnaros(tries: dict) -> dict:
    return {
        "key": "H",
        "label": MILESTONES[-1][1],
        "rule": MILESTONES[-1][2],
        "unit": "kill",
        "have": (1 if tries.get("killed") else 0) if tries["measured"] else None,
        "want": 1,
        "unread": None,
        "seats_short": None,
        "percent": None,
        "measured": tries["measured"],
        "blockers": [],
    }


def build(guild: str, teams: dict | None, goal: dict | None, runs: list | None) -> dict:
    """The /api/v2/ragnaros payload from the reads. Pure."""
    rows = _seat_rows(teams)
    stuck = (goal or {}).get("stuck")
    out = [_seat_milestone(k, lb, r, rows, stuck) for k, lb, r in MILESTONES[:-1]]
    tries = attempts(runs)
    out.append(_ragnaros(tries))
    total = _total(out)
    if tries.get("killed"):
        total["percent"] = 100
    flat = sorted(
        (dict(b, milestone=m["key"]) for m in out for b in m["blockers"]),
        key=lambda b: (-b["seats_short"], b["milestone"], b["key"]),
    )
    projected = (goal or {}).get("projected_60")
    return {
        "guild": guild,
        "seats": SEATS,
        "total": total,
        "milestones": out,
        "blockers": flat,
        "attempts": tries,
        "map": raidrun.MOLTEN_CORE_MAP,
        "projected_60": projected,
        "projected_60_measured": projected is not None,
        "checked_at": (goal or {}).get("checked_at"),
    }
