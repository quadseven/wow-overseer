"""What the families hold away from their bags, as numbers: mail, bank, vault.

WHY THIS EXISTS. The Bags tab answered "what is he carrying" and stopped at
the edge of the backpack. Three places the family's wealth actually sits were
invisible on every surface:

  1. THE MAILBOX. An auction house settlement, a returned letter and every
     hand-over the mail pass sends all land in `mail` and `mail_items`, and
     until they are collected the gold on them is not in anybody's purse.
     mailrun.py plans the collection; nothing drew what is waiting.
  2. THE PERSONAL BANK. `character_inventory` holds it (bag 0, slots 39 to
     66, plus the contents of the bank bags in slots 67 to 73), and the Bags
     tab counted it into one "stored elsewhere" number with the keyring.
  3. THE GUILD VAULT'S GOLD. The tabs and items were read; `guild.BankMoney`
     was not.

AND NONE OF IT HAD A HISTORY. `characters.money`, `guild.BankMoney` and every
mailbox are balances, not ledgers: nothing in the schema remembers what any of
them were yesterday. The bridge now writes one `overseer_economy_sample` row
per member and per family guild every ten minutes, on the same cadence and
with the same retention as `overseer_sample`, and this module turns those rows
into a small series per subject for the page to draw.

THE SEAM. This module is numbers only. It folds rows the adapters fetched into
counts, picks the samples a series keeps, and scales them for a sparkline. It
composes no sentence: the words live in wealth.py, which imports this module,
so this one imports nothing from there and the two cannot form a cycle. Every
function is pure and tested with rows written by hand.
"""

from __future__ import annotations

import datetime

import mailrun

# What a sample row is about. One table carries both, told apart by `kind`,
# because the question "how did the gold move this week" is the same question
# about a purse and about a vault.
MEMBER = "member"
GUILD = "guild"

# The columns the sampler writes, in the order its INSERT names them. One list
# so the bridge's statement and the rows built here cannot disagree.
SAMPLE_COLUMNS = (
    "subject",
    "kind",
    "money",
    "mail_letters",
    "mail_money",
    "mail_items",
    "bank_items",
    "bank_tabs",
)

# The window the page draws, and how finely. A week of ten-minute samples is
# a thousand points per line; at phone width a line is about three hundred
# pixels, so two-hour buckets (84 a week) lose nothing a reader can see.
HISTORY_DAYS = 7
BUCKET_SECONDS = 2 * 3600

# `mail.checked` is a bit mask; bit 0 is MAIL_CHECK_MASK_READ in the core.
MAIL_READ = 0x01


def _int(value) -> int:
    """An adapter value as a non-negative int, 0 when missing or malformed."""
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def empty_mailbox() -> dict:
    return {"letters": 0, "unread": 0, "money": 0, "items": 0}


def mailboxes(rows: list[dict], names: list[str]) -> dict[str, dict]:
    """Per name: delivered letters waiting, how many are unread, their gold
    and their attachments.

    The rows are the mail adapter's, ONE ROW PER ATTACHMENT (a LEFT JOIN onto
    `mail_items`), so the fold back into letters is mailrun.letters_from_rows'
    and not a second copy of it here.

    ONLY DELIVERED LETTERS COUNT. A letter in transit sits in `mail` with a
    future `deliver_time`, and its gold cannot be collected yet; counting it
    would say money is waiting that nobody can take. `delivered` is answered
    in SQL, where the clock is.

    UNREAD IS COUNTED ONLY WHEN THE ROWS SAY. The view's query carries
    `checked`; the sampler's (the mail pass's own query) does not, and a
    letter with no `checked` column is not counted as unread rather than
    guessed at.

    Every name asked about gets an entry, so an empty mailbox is a zero rather
    than a missing key the caller has to tell apart from an unread one.
    """
    boxes = {name: empty_mailbox() for name in names}
    unread = set()
    for row in rows:
        if "checked" in row and not _int(row.get("checked")) & MAIL_READ:
            unread.add((row.get("holder"), _int(row.get("mail_id"))))
    for letter in mailrun.letters_from_rows(rows, names):
        if not letter.delivered:
            continue
        box = boxes[letter.holder]
        box["letters"] += 1
        box["money"] += letter.money
        box["items"] += len(letter.attachments)
        if (letter.holder, letter.mail_id) in unread:
            box["unread"] += 1
    return boxes


def subjects(roster_rows: list[dict], fallback: list[str]) -> list[str]:
    """Every member to sample: every roster family, then the fallback names.

    The Bags tab draws every family in `overseer_roster`, so the sampler has
    to cover the same names or a card would have no history for a reason the
    reader cannot see. The fallback (the bridge's own family) covers a realm
    whose roster has no family column yet. Order is kept and duplicates drop.
    """
    names = [r.get("name") for r in roster_rows] + list(fallback)
    return list(dict.fromkeys(n for n in names if n))


def sample_rows(
    char_rows: list[dict],
    bank_stacks: dict[str, int],
    boxes: dict[str, dict] | None,
    guild_rows: list[dict],
) -> tuple[list[dict], list[dict]]:
    """One member row per character and one guild row per guild.

    A member row carries the purse, the mailbox and the personal bank; a
    guild row carries the vault's gold in `money` and its stored items in
    `bank_items`, with the mail columns at zero because a guild has no
    mailbox. `boxes` is None when the mail tables could not be read, and the
    mail columns are then zero rather than the sample being skipped: the
    purse and the bank are still worth a point.

    A guild shared by two members is one row, keyed by its id, so a family
    of five in one guild does not write the vault five times.
    """
    members = []
    for row in char_rows:
        name = row.get("name")
        if not name:
            continue
        box = (boxes or {}).get(name) or empty_mailbox()
        members.append(
            {
                "subject": name,
                "kind": MEMBER,
                "money": _int(row.get("money")),
                "mail_letters": box["letters"],
                "mail_money": box["money"],
                "mail_items": box["items"],
                "bank_items": _int(bank_stacks.get(name)),
                "bank_tabs": 0,
            }
        )
    guilds: dict[int, dict] = {}
    for row in guild_rows:
        name = row.get("guild_name")
        if not name or row.get("guild_id") is None:
            continue
        guilds.setdefault(
            _int(row["guild_id"]),
            {
                "subject": name,
                "kind": GUILD,
                "money": _int(row.get("bank_money")),
                "mail_letters": 0,
                "mail_money": 0,
                "mail_items": 0,
                "bank_items": _int(row.get("item_count")),
                "bank_tabs": _int(row.get("tab_count")),
            },
        )
    return members, [guilds[k] for k in sorted(guilds)]


def timeline_end(rows: list[dict]) -> datetime.datetime | None:
    """The newest sample, which is the right edge every series shares.

    Not the clock: this module has none, and the newest sample is what the
    lines can honestly reach. One edge for all of them means two sparklines
    side by side are on the same time axis.
    """
    times = [r["taken_at"] for r in rows if r.get("taken_at") is not None]
    return max(times) if times else None


def series(
    rows: list[dict],
    kind: str,
    subject: str,
    field: str,
    end: datetime.datetime | None,
    days: int = HISTORY_DAYS,
    bucket_seconds: int = BUCKET_SECONDS,
) -> dict | None:
    """One subject's one field over the window, scaled for a sparkline.

    Returns None when the subject has no sample in the window. Otherwise the
    first and last values, the low and the high, the span actually covered in
    seconds, and `points`: [x, y] pairs with both in 0..1, x across the window
    (0 is `days` before `end`, 1 is `end`) and y between the low and the high.
    A flat line sits at 0.5, because a line pinned to the floor reads as
    "nothing" and a flat one reads as "unchanged", which is what it is.

    THE LAST SAMPLE IN EACH BUCKET IS KEPT, not an average: a balance is a
    level, and the mean of two balances is a balance nobody ever held.
    """
    if end is None:
        return None
    window = datetime.timedelta(days=days)
    start = end - window
    mine = sorted(
        (
            r
            for r in rows
            if r.get("kind") == kind
            and r.get("subject") == subject
            and r.get("taken_at") is not None
            and start <= r["taken_at"] <= end
        ),
        key=lambda r: r["taken_at"],
    )
    if not mine:
        return None
    buckets: dict[int, dict] = {}
    for row in mine:
        key = int((row["taken_at"] - start).total_seconds() // bucket_seconds)
        buckets[key] = row
    kept = [buckets[k] for k in sorted(buckets)]
    values = [_int(r.get(field)) for r in kept]
    low, high = min(values), max(values)
    total = window.total_seconds()
    points = []
    for row, value in zip(kept, values, strict=True):
        x = (row["taken_at"] - start).total_seconds() / total
        y = 0.5 if high == low else (value - low) / (high - low)
        points.append([round(x, 4), round(y, 4)])
    return {
        "first": values[0],
        "last": values[-1],
        "low": low,
        "high": high,
        "span_seconds": int(
            (mine[-1]["taken_at"] - mine[0]["taken_at"]).total_seconds()
        ),
        "points": points,
    }
