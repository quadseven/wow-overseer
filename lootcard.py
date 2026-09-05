"""What a drop is worth showing on the stream, and for how long.

infra#3334, follow-up. When something drops, a viewer sees a small roll frame
with a truncated name and a chat line that scrolls away. What dropped, whether
it is any good, and who got it are the whole moment, and all three are
invisible unless somebody hovers the icon. Nobody is at the keyboard to hover.

THE STATS ARE THE GAME'S, NOT OURS. The addon calls
`GameTooltip:SetHyperlink(link)` on the link that came through chat and the
client renders its own tooltip, so a suffix, an enchant or a random stat roll
is right because the client drew it. Nothing here reconstructs an item, and
nothing here ever should: a display that composes its own stats is a display
that starts lying the first time an item is not the plain case.

WHAT THIS MODULE DECIDES, which is everything a test can reach:

  which drops are worth a card    the quality bar, below
  what the headline says          "Og won", "Grug looted"
  how long a card stays           DWELL_SECONDS
  how many can be up at once      MAX_CARDS, and how many keep their stats
  which chat lines are loot       MESSAGE_FORMS, and the ORDER to try them in
  when two lines are one drop     DEDUPE_SECONDS

The addon reads the format strings out of the client's own globals and turns
them into patterns. That part cannot move here - `LOOT_ITEM` only exists inside
a running client, and hardcoding "%s receives loot: %s." in English is exactly
what those globals exist to prevent. What CAN live here is the table: which
globals, in what order, and which argument of each is the winner and which is
the item. tests/test_lootcard.py holds the Lua to that table as source text.

THE ORDER IS NOT ALPHABETICAL AND IS NOT DECORATION. "%s won: %s" matches the
"|cff818181(Need - 76)|r" line too, with the suffix swallowed into the item
capture, and it matches "You won: ..." with a winner called "You". So the
specific forms are tried before the general ones and the self forms before the
third-person ones. Reorder this list and the wrong capture wins silently.

A DROP IS ONE MOMENT AND THE SERVER SENDS IT TWICE. Group loot writes the roll
result ("Og won: [x]") and then the loot itself ("Og receives loot: [x]."), so
the same robe would open two cards seconds apart. They collapse, and the WON
wording beats LOOTED because a contested item that somebody actually won is the
more interesting sentence.

ROLLS IN PROGRESS ARE NOT SHOWN. `START_LOOT_ROLL` already puts a roll frame on
screen with its own timer; a card for the roll and another for its result would
double the screen time of every drop to say the same thing twice. The moment
worth showing is the resolution.

PURE MODULE: facts in, decisions out. No client, no clock of its own unless one
is not handed to it. Nothing in the images imports it yet - it exists to be
the one place these rules are written down and the one place they are tested
- but it ships with the rest anyway, because the manifest is all or nothing:
tests/test_ship_manifest.py requires every top-level module to be named in
the Dockerfile, after a rerere replay once dropped panel.py from it and gave
the map server an import crash at pod start, long after CI was green.
"""
from __future__ import annotations

# The bar. UNCOMMON, which is 2, and the number is the operator's complaint
# rather than taste: a stream that announces every scrap of wool and every
# Moss Agate is noise with a robe hidden in it. Greens and better are the
# things a level-25 party actually stops for.
#
# AN ITEM WHOSE QUALITY CANNOT BE READ IS NOT SHOWN, and that direction is
# chosen deliberately. Quality comes out of the link's own colour code, so a
# link we cannot classify means the reader is broken rather than that one
# unusual item arrived - and a broken reader that shows everything would put
# every grey on a permanent stream, while a broken reader that shows nothing
# costs one missed card and is obvious.
MIN_QUALITY = 2

# A couple of minutes, taken literally. Long enough that a viewer who looked
# away at the pull still sees what dropped; short enough that a card is gone
# before the next pull is over.
DWELL_SECONDS = 120

# How many cards may be up, and how many of those keep their tooltip.
#
# BOTH NUMBERS COME FROM THE SCREEN. A tooltip for a level-25 green is about
# 160 units tall with its headline, and a PrintWindow capture of a live client
# measures the free band on the right - under the quest tracker, above the bag
# bar - at roughly 470 units. Three tooltips do not fit. Two do, with the third
# drop keeping its headline alone so nobody loses the attribution, which is
# half of what was asked for. A busy pull therefore costs one line of text
# rather than burying the fight.
MAX_CARDS = 3
MAX_EXPANDED = 2

# Group loot says the same drop twice - the roll result, then the loot - and
# the gap between them is a fraction of a second. Fifteen seconds is far wider
# than that gap and far narrower than the time it takes for the same character
# to genuinely loot a second copy of the same item.
DEDUPE_SECONDS = 15

# The headline's font size, and it is here rather than in the Lua because
# "readable on a phone watching the video" is a requirement rather than a
# palette choice. 18 with an outline against a 12-point tooltip underneath it.
# This is the number most likely to want tuning once somebody has actually
# watched it, which is the other reason it is written down somewhere tested.
HEADLINE_SIZE = 18

# Where the stack sits, as an offset from UIParent's BOTTOMRIGHT, growing UP.
#
# MEASURED, NOT GUESSED. On a live client the right column holds the buffs and
# the minimap down to y=200, the quest tracker to y=345, and then nothing at
# all until the action bar art begins around y=875. The bottom UI - bar, bags,
# micro menu - is about 103 units tall. 130 clears it with room, and growing
# upward means a busier stack extends into empty sky rather than down over the
# action bar. It is the opposite corner from the party frames and the chat
# log, so this and the status labels cannot collide.
#
# The one thing that would break it is turning on the right-hand vertical
# action bars, which are off on these clients and would occupy this column.
ANCHOR_X = -12
ANCHOR_Y = 130

# What a card says happened.
WON = "won"
LOOTED = "looted"

# (global name, which ARGUMENT is the winner, which is the item, what happened)
#
# Argument 0 means the message has no winner in it because it is one of the
# forms the client writes about itself. The addon substitutes the character it
# is watching, so a stream never says "You won" at a viewer who has no idea
# who "you" is.
MESSAGE_FORMS = (
    ("LOOT_ROLL_YOU_WON_NO_SPAM_NEED", 0, 2, WON),
    ("LOOT_ROLL_YOU_WON_NO_SPAM_GREED", 0, 2, WON),
    ("LOOT_ROLL_YOU_WON_NO_SPAM_DE", 0, 2, WON),
    ("LOOT_ROLL_WON_NO_SPAM_NEED", 1, 3, WON),
    ("LOOT_ROLL_WON_NO_SPAM_GREED", 1, 3, WON),
    ("LOOT_ROLL_WON_NO_SPAM_DE", 1, 3, WON),
    ("LOOT_ROLL_YOU_WON", 0, 1, WON),
    ("LOOT_ROLL_WON", 1, 2, WON),
    ("LOOT_ITEM_SELF_MULTIPLE", 0, 1, LOOTED),
    ("LOOT_ITEM_MULTIPLE", 1, 2, LOOTED),
    ("LOOT_ITEM_PUSHED_SELF_MULTIPLE", 0, 1, LOOTED),
    ("LOOT_ITEM_SELF", 0, 1, LOOTED),
    ("LOOT_ITEM", 1, 2, LOOTED),
    ("LOOT_ITEM_PUSHED_SELF", 0, 1, LOOTED),
)


def worth_showing(quality) -> bool:
    """Whether this drop earns a card.

    `quality` is what the client knows: 0 Poor through 6 Artifact, or None when
    the link carried no colour this build recognises.
    """
    if quality is None:
        return False
    return int(quality) >= MIN_QUALITY


def headline(winner: str, verb: str, viewer: str) -> str:
    """"Og won" - the words above the tooltip, without the item.

    The item is not in here because only the client can render it. The addon
    appends the link itself, which draws as a coloured `[Robe of the Moccasin]`
    for free; composing that name here would mean re-deriving the colour and
    the brackets and getting one of them wrong.

    NOBODY IS CALLED "YOU" ON A STREAM. The self forms carry no name, so the
    watched character's is used instead - a viewer looking at a video has no
    way to know whose screen it is otherwise, and "You won" beside four other
    people's names is the one sentence that could be about any of them.
    """
    who = (winner or "").strip() or (viewer or "").strip()
    if not who:
        return ""
    return "%s %s" % (who, verb)


def expire(stack: list[dict], now: float) -> list[dict]:
    """The cards still inside their dwell, oldest first."""
    return [c for c in stack if (now - float(c.get("at", 0))) < DWELL_SECONDS]


def admit(stack: list[dict], card: dict, now: float) -> list[dict]:
    """The stack after one drop arrives.

    INDEPENDENT TIMERS, and a new drop does NOT reset the old ones. Each card
    is a different moment and each gets its own couple of minutes; a version
    that restarted the clock on every drop would keep the first robe of a
    dungeon on screen until the run ended.

    The collapse of a duplicate keeps the ORIGINAL timestamp for the same
    reason. Group loot's second message about one drop must not buy that drop
    another two minutes.
    """
    kept = expire(list(stack), now)
    for existing in kept:
        if existing.get("link") != card.get("link"):
            continue
        if existing.get("winner") != card.get("winner"):
            continue
        if (now - float(existing.get("at", 0))) > DEDUPE_SECONDS:
            continue
        # Same drop, said twice. Upgrade the wording if the second telling is
        # the better one, and leave the clock alone.
        if existing.get("verb") == LOOTED and card.get("verb") == WON:
            existing["verb"] = WON
        return kept
    fresh = dict(card)
    fresh["at"] = now
    kept.append(fresh)
    # Oldest off the front: the newest drop is the one somebody is watching
    # for, so it must never be the one that is refused.
    return kept[-MAX_CARDS:]


def layout(stack: list[dict]) -> list[dict]:
    """Each card with whether it keeps its tooltip, oldest first.

    The NEWEST cards are the expanded ones. The addon draws the newest nearest
    the anchor and the rest above it, so the card a viewer is waiting for
    always appears in the same place instead of being pushed around by the ones
    before it.
    """
    out = []
    for i, card in enumerate(stack):
        entry = dict(card)
        entry["expanded"] = i >= len(stack) - MAX_EXPANDED
        out.append(entry)
    return out
