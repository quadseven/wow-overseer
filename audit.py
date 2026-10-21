"""Read-only dev-realm audit: six fields per character.

Pure module: normalized rows in, audit findings and `wow.dev.*` metrics out.
No MySQL, no network, and no clock of its own unless one is handed to it. That
is what lets the suite exercise the stalled / death-loop / under-geared watches
with no world running.

The six fields, one per online guild member and roster member:

  seconds since last moved        the snapshot's last refresh, in seconds
  deaths in the last hour         overseer_death rows in the trailing hour
  filled gear slots               equipped (bag 0, slot < 19)
  wearable items in bags          equippable items the character carries
  item level against character level average equipped item level vs level
  uncollected mail                mail rows not yet checked
  hours at the current level      characters.leveltime, in hours

Each finding carries the three digest-tier watch verdicts: stalled longer than
STALLED_SECONDS, more than DEATHS_PER_HOUR deaths in an hour, and an average
item level ILEVEL_GAP or more below the character's level.

`metrics()` turns the findings into `wow.dev.*` datapoints, one series per
character per field, plus a per-character watch flag. The bridge or a job owns
shipping them to the metrics backend; this module only shapes them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

# --- thresholds, named so a reader can argue with them ---------------------

# A member who has not been seen move in this long is stalled.
STALLED_SECONDS = 15 * 60
# More than this many deaths in one hour is a death loop, not a bad pull.
DEATHS_PER_HOUR = 6
# Average equipped item level this many or more below character level is a gap.
ILEVEL_GAP = 10

SECONDS_PER_HOUR = 3600
# bag 0, slots 0-18 inclusive, are the equipment slots in 3.3.5a.
EQUIPMENT_SLOT_END = 19

# --- findings --------------------------------------------------------------


@dataclass(frozen=True)
class Finding:
    """One character's six audit fields and the watches they imply."""

    name: str
    level: int
    seconds_since_moved: int | None
    deaths_last_hour: int
    gear_slots_filled: int
    wearable_in_bags: int
    item_level: float | None
    uncollected_mail: int
    hours_at_level: float | None

    @property
    def stalled(self) -> bool:
        """Stalled more than STALLED_SECONDS with a known last movement."""
        return (
            self.seconds_since_moved is not None
            and self.seconds_since_moved > STALLED_SECONDS
        )

    @property
    def deaths_excessive(self) -> bool:
        """More than DEATHS_PER_HOUR deaths in the last hour."""
        return self.deaths_last_hour > DEATHS_PER_HOUR

    @property
    def item_level_deficient(self) -> bool:
        """Average item level ILEVEL_GAP or more below character level."""
        return (
            self.item_level is not None
            and self.level - self.item_level >= ILEVEL_GAP
        )

    @property
    def any_watch(self) -> bool:
        """Whether any digest-tier watch fires for this character."""
        return self.stalled or self.deaths_excessive or self.item_level_deficient


# --- metrics ---------------------------------------------------------------


@dataclass(frozen=True)
class Metric:
    """One `wow.dev.*` datapoint: a name, a value, and per-character tags."""

    name: str
    value: float
    tags: dict


def metrics(findings, prefix: str = "wow.dev") -> list:
    """One datapoint per field per character, plus the watch flags.

    Fields with no data (None) are not emitted - a gauge with no reading is
    not a zero reading. Counts are always emitted. Watch flags are 1/0 gauges
    so an alert can threshold on the value directly.
    """

    out = []
    for f in findings:
        tags = {"character": f.name}
        base = f"{prefix}.audit"
        if f.seconds_since_moved is not None:
            out.append(
                Metric(f"{base}.seconds_since_moved", float(f.seconds_since_moved), dict(tags))
            )
        out.append(Metric(f"{base}.deaths_last_hour", float(f.deaths_last_hour), dict(tags)))
        out.append(Metric(f"{base}.gear_slots_filled", float(f.gear_slots_filled), dict(tags)))
        out.append(Metric(f"{base}.wearable_in_bags", float(f.wearable_in_bags), dict(tags)))
        if f.item_level is not None:
            out.append(Metric(f"{base}.item_level", f.item_level, dict(tags)))
        out.append(Metric(f"{base}.character_level", float(f.level), dict(tags)))
        out.append(Metric(f"{base}.uncollected_mail", float(f.uncollected_mail), dict(tags)))
        if f.hours_at_level is not None:
            out.append(Metric(f"{base}.hours_at_level", f.hours_at_level, dict(tags)))
        out.append(Metric(f"{base}.stalled", 1.0 if f.stalled else 0.0, dict(tags)))
        out.append(Metric(f"{base}.deaths_excessive", 1.0 if f.deaths_excessive else 0.0, dict(tags)))
        out.append(
            Metric(f"{base}.item_level_deficient", 1.0 if f.item_level_deficient else 0.0, dict(tags))
        )
    return out


# --- computation -----------------------------------------------------------


def _by_name(rows: list, key: str = "name") -> dict:
    """Group rows by the named string column, name -> rows in input order."""
    out: dict = {}
    for row in rows:
        out.setdefault(str(row.get(key) or ""), []).append(row)
    return out


def _seconds_since(updated_at, now: datetime) -> int | None:
    """Seconds between `updated_at` and `now`, or None when there is no stamp."""
    if updated_at is None:
        return None
    return int((now - updated_at).total_seconds())


def _deaths_in_hour(death_rows: list, cutoff: datetime) -> int:
    """Deaths whose stamp falls in the trailing hour, inclusive of the edge."""
    total = 0
    for row in death_rows:
        when = row.get("created_at")
        if when is not None and when >= cutoff:
            total += 1
    return total


def _gear_and_bags(inv_rows: list) -> tuple:
    """(filled equipment slots, wearable items carried in bags) for one name."""
    filled = 0
    wearable = 0
    for row in inv_rows:
        bag = int(row.get("bag") or 0)
        slot = int(row.get("slot") or 0)
        if bag == 0 and slot < EQUIPMENT_SLOT_END:
            filled += 1
        elif bag > 0 and bool(row.get("equippable")):
            wearable += 1
    return filled, wearable


def _uncollected_mail(mail_rows: list) -> int:
    """Mail rows that have not been checked (checked == 0)."""
    total = 0
    for row in mail_rows:
        if int(row.get("checked") or 0) == 0:
            total += 1
    return total


def _hours_at_level(leveltime_rows: list) -> float | None:
    """PLAYED seconds at the current level, as hours, or None when unknown."""
    row = leveltime_rows[0] if leveltime_rows else None
    if row is None or row.get("leveltime") is None:
        return None
    return int(row.get("leveltime") or 0) / SECONDS_PER_HOUR


def compute(
    members: list,
    snapshots: list,
    deaths: list,
    inventory: list,
    mails: list,
    leveltime: list,
    ilevels: dict,
    now: datetime,
) -> list:
    """One `Finding` per member, each carrying all six audit fields.

    `members` is the authoritative list of who to report on (every online
    guild member and roster member). Every other input is looked up by name;
    a member with no row for a field gets None for that field rather than a
    fabricated number.
    """
    by_snapshot = _by_name(snapshots)
    by_death = _by_name(deaths, "character_name")
    by_inventory = _by_name(inventory)
    by_mail = _by_name(mails)
    by_leveltime = _by_name(leveltime)
    cutoff = now - timedelta(hours=1)

    findings = []
    for member in members:
        name = str(member.get("name") or "")
        level = int(member.get("level") or 0)
        snap = (by_snapshot.get(name) or [None])[0]
        seconds_since_moved = _seconds_since(
            snap.get("updated_at") if snap is not None else None, now
        )
        deaths_last_hour = _deaths_in_hour(by_death.get(name, []), cutoff)
        gear_slots_filled, wearable_in_bags = _gear_and_bags(by_inventory.get(name, []))
        item_level = ilevels.get(name)
        uncollected_mail = _uncollected_mail(by_mail.get(name, []))
        hours_at_level = _hours_at_level(by_leveltime.get(name, []))
        findings.append(
            Finding(
                name=name,
                level=level,
                seconds_since_moved=seconds_since_moved,
                deaths_last_hour=deaths_last_hour,
                gear_slots_filled=gear_slots_filled,
                wearable_in_bags=wearable_in_bags,
                item_level=item_level,
                uncollected_mail=uncollected_mail,
                hours_at_level=hours_at_level,
            )
        )
    return findings
