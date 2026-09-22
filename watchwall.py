"""The Watch wall: five points of view, and what to say about each one.

WHY THIS IS A MODULE AND NOT A HANDFUL OF TEMPLATE EXPRESSIONS. The page used
to decide, in JavaScript, what a stream's state meant - `watchView` read a
payload and returned a phase, a sentence and a CSS class. That is judgement,
it lived where no test could reach it, and infra#2597 says judgement belongs
in a module the stdlib suite can call with no database and no browser. This is
that module for the wall.

THE WALL IS NOT THE ON-DEMAND WATCH, and the difference decides the whole
design. There are two entirely separate ways to see a character:

  the continuous broadcast   an encoder already running on the gaming box,
                             publishing one MediaMTX path per member. Nobody
                             starts it, nobody stops it, it costs no channel,
                             and `family.broadcast_url` names it.

  the on-demand watch        `stream.py`: log a client in as them, hold it up
                             with a heartbeat, tear it down when the viewer
                             leaves. One GPU runs two of these, which is what
                             `stream.MAX_CHANNELS` counts.

The wall is built entirely on the FIRST of those. That is why it can show five
at once when the channel budget is two, and why none of the budget's
vocabulary belongs on it: there is no queue to explain, no startup budget to
count down, and no request that can go unclaimed, because the wall never asks
for anything. Putting "both channels busy" on a wall of continuous broadcasts
would be a sentence about a mechanism the wall does not use.

WHAT IT REFUSES TO DECIDE. Which tile is the most interesting one right now.
That is the RedZone idea and it is a real feature, but it needs a score this
module has no inputs for, and a wall that promotes the wrong character with
apparent confidence is worse than one that promotes the first. The hero is
whoever the viewer picked. Nothing here ranks anybody.
"""

# THE THREE SHAPES, and they exist because five streams have three honestly
# different jobs. FIVE UP is the family: nobody is the subject, and the point
# is who is where. STACKED is reading: one column, in roster order, for a
# viewer scrolling rather than scanning. HERO is watching one of them, with
# the other four kept where a glance can find them.
FIVE_UP = "five-up"
STACKED = "stacked"
HERO = "hero"
MODES = (FIVE_UP, STACKED, HERO)
DEFAULT_MODE = FIVE_UP

MODE_LABELS = {
    FIVE_UP: "FIVE UP",
    STACKED: "STACKED",
    HERO: "HERO + WALL",
}

# The tones a tile can carry, kept as names rather than colours. A module that
# returns "#ff4d2e" has decided what the page's palette is, and then a theme
# change has to be made in Python.
TONE_DEAD = "dead"
TONE_COMBAT = "combat"
TONE_HURT = "hurt"
TONE_GONE = "gone"
TONE_CALM = "calm"


def _where(member) -> str:
    """The place-phrase, or "" when the member's row did not carry one.

    `family._member` already composes "inside an instance" for a character the
    geography cannot place, so an instance reads as its own phrase and must
    NOT be prefixed: "fighting in inside an instance" is the sentence that
    prefix produces, and it is the reason this is a function rather than an
    f-string at each call site.
    """
    zone = (member.get("zone") or "").strip()
    if not zone:
        return ""
    return zone if member.get("instance") else "in " + zone


def status_line(member) -> str:
    """One line saying what is true of this character right now.

    Ordered by what would make a viewer look: dead first, then a fight, then
    an injury, then where they are. A character can be all four at once and
    only the most urgent gets said, because a tile caption that lists every
    true thing is one nobody reads.

    ABSENT IS NOT DEAD and is said in its own words. The snapshot sweep drops
    the row of anyone who is not logged in, so absence is the ordinary way to
    be offline, and "dead" would be a lie about a character who is fine.
    """
    if not member.get("present"):
        return "logged out"
    where = _where(member)
    if member.get("condition") == "dead":
        return ("dead " + where).strip() if where else "dead"
    if member.get("combat"):
        return ("fighting " + where).strip() if where else "fighting"
    if member.get("condition") == "hurt":
        # The percentage is the one the family module already rounded. Two
        # surfaces rounding the same health differently is how a tile ends up
        # arguing with the bar next to it.
        pct = member.get("health_pct")
        hurt = "hurt" if pct is None else "hurt, " + str(pct) + "%"
        return (hurt + " " + where).strip() if where else hurt
    return where or "in the world"


def standing(member) -> str:
    """What this character IS, for the caption under their picture.

    THE WALL COULD NOT SAY THIS AT ALL UNTIL infra#3482, and the way it lost
    it is worth writing down. The tile arrived from the Family tab still
    wearing that tab's overlay, so "Grug - L33 Warrior" was printed over the
    picture while the caption underneath printed "Grug" again. Taking the
    duplicate off meant taking the overlay off, and the level and the class
    went with it: the Watch wall could show you five characters and not tell
    you what any of them was.

    So it is composed here, beside the sentence it sits next to, rather than
    assembled from two payload fields in the page. What to do when a level is
    missing is a judgement - say the class alone, never "L None Warrior" or a
    bare "L33" - and judgements on this view live where the suite can call
    them.

    ABSENT CHARACTERS KEEP THEIR STANDING. A logged-out character is still a
    level 33 warrior; `present` decides what they are DOING, which is
    status_line's question, not what they are.
    """
    klass = (member.get("class") or "").strip()
    level = member.get("level")
    if not level:
        return klass
    if not klass:
        return "L%s" % level
    return "L%s %s" % (level, klass)


def tone_of(member) -> str:
    """Which of the five tones dresses this tile.

    Same order as the sentence, deliberately: the colour and the words must
    agree about what the urgent thing is, or the tile says one thing and looks
    like another.
    """
    if not member.get("present"):
        return TONE_GONE
    if member.get("condition") == "dead":
        return TONE_DEAD
    if member.get("combat"):
        return TONE_COMBAT
    if member.get("condition") == "hurt":
        return TONE_HURT
    return TONE_CALM


def playable(member) -> bool:
    """Does this tile get a real player, or a caption saying why not?

    ONLY when a URL genuinely exists, which is `stream.delivery_of`'s rule
    applied to the other kind of stream. A player pointed at nothing is a
    black rectangle that reads as a broken feature, and the correct thing to
    draw instead is the tile saying so in words.
    """
    return bool((member.get("broadcast_url") or "").strip())


def leader_warning(members) -> dict | None:
    """What watching costs, in the one case where watching costs something.

    `stream.pov_changes_the_family` says in as many words that the UI must not
    hide this, and `family._member` has already asked it per member, so this
    reads that answer rather than re-deriving it. Nobody flagged means no
    sentence: the party may be led by someone the snapshot has not got, and a
    warning naming nobody is worse than no warning.

    WORDED FOR AN ALWAYS-ON CLIENT. The design handoff is explicit about this
    and about the wording that must NOT come back: `pov_changes_the_family`'s
    own docstring says the effect stops when you stop watching, and that
    framing predates the five clients streaming continuously. They do not log
    out, so the condition is true right now whether or not anybody has this
    page open, and saying otherwise invites a reader to believe they can turn
    it off by closing a tab.

    RETURNED AS A TITLE AND A BODY, not one paragraph. It is five sentences of
    genuinely important text, the operator reads this on a phone, and five
    sentences above the video is how a warning gets scrolled past unread. The
    title is the whole claim in four words; the body is why. The page collapses
    to the title on a narrow screen and this is what lets it.
    """
    named = [m.get("name") for m in members if m.get("pov_changes_the_family")]
    named = [n for n in named if n]
    if not named:
        return None
    if len(named) > 1:
        # THE WALL OF HEADS carries one leader per family, and each of them
        # is a selfbot for the same reason. Naming only the first would tell
        # a viewer the second family was acting on its own when it is not.
        who = " and ".join(named)
        return {
            "title": "THE LEADERS ARE SELFBOTS",
            "body": (
                who + " each have a client logged in as them, which makes "
                "each a selfbot, and FindNewMaster hands the rest of each "
                "family a master, so they follow and obey their head. That "
                "is true right now whether or not you are looking at these "
                "tiles, and it does not stop, because the clients never log "
                "out. Any cohesion you see is the streamed configuration, "
                "not the families on their own. Only a POV login does this; "
                "a follow-cam is a GM watching from outside and changes "
                "nothing."
            ),
        }
    who = named[0]
    return {
        "title": "THE LEADER IS A SELFBOT",
        "body": (
            who + "'s client is logged in as him, which makes him a selfbot, "
            "and FindNewMaster hands the other four a master, so they follow "
            "and obey him. That is true right now whether or not you are "
            "looking at this tile, and it does not stop, because the client "
            "never logs out. Any cohesion you see is the streamed "
            "configuration, not the family on their own. Only a POV login "
            "does this; a follow-cam is a GM watching from outside and "
            "changes nothing."
        ),
    }


def hero_of(members, chosen=None) -> str | None:
    """Who is big in HERO mode.

    Whoever the viewer picked, and otherwise the first of the roster who is
    actually in the world, so opening the wall in hero mode does not lead with
    a tile that says "logged out". Falls back to the first member rather than
    None, because a hero mode with no hero has no layout at all.

    THE CHOICE IS VALIDATED AGAINST THE ROSTER, not trusted. It arrives from
    browser storage, which is to say from anywhere, and a name that is not one
    of the five would leave every tile in the small rail and the big slot
    empty.
    """
    names = [m.get("name") for m in members]
    if chosen in names:
        return chosen
    for m in members:
        if m.get("present"):
            return m.get("name")
    return names[0] if names else None


def headline(members) -> str:
    """One line over the whole wall, and it must not claim what it cannot see.

    THE FIRST VERSION OF THIS CLAIMED "5 of 5 broadcasting" AND WAS WRONG ON
    PRODUCTION THE MOMENT IT SHIPPED. It counted `playable`, which means "a URL
    exists to try", not "an encoder is publishing" - and the production page
    reported five characters broadcasting while reporting the same five logged
    out, on the same screen, from the same payload.

    Nothing this module can see knows whether video is flowing. That is the
    WHEP handshake, it happens in the browser, and it is the tile's own job to
    say so. So this counts the only thing the payload actually knows: who is in
    the world. A count of streams is not offered at all, because an honest one
    is not available here and a dishonest one is worse than none.
    """
    if not members:
        return "no family"
    here = sum(1 for m in members if m.get("present"))
    if here == 0:
        # Said as a sentence rather than as "0 of 5", because zero of five is
        # a statistic and nobody being there is the thing worth reading.
        return "nobody is in the world"
    return "%d of %d in the world" % (here, len(members))


def build_heads(families) -> dict:
    """The Watch wall across every family: only the characters with a picture.

    `families` is [(family key, family.build_family payload)], in the order
    the families should appear. Only members with a broadcast are kept,
    because the wall is a place to watch and a headless bot has nothing to
    show; their status is on their own family's tab. On a realm with two
    game clients that is the two heads, side by side.

    Each kept member carries the key of the family it came from, so a tile
    can say whose head it is without the page knowing any roster.
    """
    members = []
    keys = []
    for key, payload in families:
        keys.append(key)
        for m in payload.get("members", []):
            if playable(m):
                members.append(dict(m, family=key))
    return {
        "members": members,
        "families": keys,
        "wall": build_wall(members),
        "here": sum(1 for m in members if m.get("present")),
        "expected": len(members),
    }


def build_wall(members, chosen=None) -> dict:
    """The whole wall, composed, in roster order.

    ROSTER ORDER IS NEVER TOUCHED. `family.roster` is seniority, which is the
    family table's own answer to who comes first, and re-sorting the wall by
    who is fighting would move a character out from under the viewer's cursor
    every time a fight started. The wall is a place, and things stay where
    they were put. Hero mode promotes a tile without reordering the rest.
    """
    tiles = []
    for m in members:
        tiles.append(
            {
                "name": m.get("name"),
                "role": m.get("role"),
                "class": m.get("class"),
                "class_colour": m.get("class_colour"),
                "leader": bool(m.get("leader")),
                "playable": playable(m),
                "url": (m.get("broadcast_url") or "") or None,
                "standing": standing(m),
                "line": status_line(m),
                "tone": tone_of(m),
            }
        )
    return {
        "modes": list(MODES),
        "mode_labels": dict(MODE_LABELS),
        "default_mode": DEFAULT_MODE,
        "headline": headline(members),
        "hero": hero_of(members, chosen),
        "warning": leader_warning(members),
        "tiles": tiles,
    }
