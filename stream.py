"""Who is being watched live, and whether anyone is still watching.

Pure module, the same seam as questbook and bonds: facts in, judgements out.
No pymysql, no network, no clock reads except the one the caller passes in.
map_server.py runs the queries; the Windows box that owns the WoW client polls
the same table and never talks to this process at all.

WHY A TABLE RATHER THAN AN API. The box that renders the game
(usr-unraid-gpu-w11) already reaches MySQL and nothing else; giving it an
inbound port would be a second network surface for one button. The database is
the interface everywhere else in this system - overseer_command for bots,
overseer_goal for the supervisor - and a stream request is the same shape: a
row somebody else acts on, with its outcome written back.

THE LIFECYCLE IS THE HARD PART, not the video (infra#2663 says so in its own
acceptance criteria: "without leaving a WoW client running idle when nobody is
watching"). A client left running is a GPU and 300MB held for nobody, and it
is invisible - which is this project's favourite kind of bug.

WHY THE VIEWER'S HEARTBEAT DECIDES, and not Sunshine or the page:

  - a Sunshine session ending misses a browser viewer entirely;
  - a page-close handler misses a crashed tab, a slept laptop, a dropped
    tailnet, a killed browser;
  - a heartbeat misses NONE of them, because all of those stop it.

So `last_seen` is written by the map while the panel is open, and silence is
the signal. The failure mode is a client torn down while somebody is still
watching - recoverable by clicking again - rather than a client running
forever for nobody, which nobody would notice.
"""

from __future__ import annotations

from collections.abc import Mapping

# How often the open panel promises to say it is still there. The map sends on
# this cadence; the timeout below is a multiple of it so one dropped request
# cannot end a stream.
HEARTBEAT_SECONDS = 10

# Silence longer than this means nobody is watching. Six missed heartbeats:
# long enough to ride out a tab throttled in the background (browsers slow
# timers in hidden tabs, sometimes to once a minute), short enough that a
# forgotten stream costs a minute of GPU rather than a night of it.
STALE_AFTER_SECONDS = 60

# What the Windows agent is allowed to be asked for.
#
# POV is a real login as that character with the selfbot on: their hotbars,
# their bags, their camera. It is the Twitch view and it only exists for a
# character whose account we can log in as.
#
# CAM is a GM character teleported to the target and following it. Honest
# framing matters and the UI must carry it: this is watching them, not being
# them - the interface on screen belongs to the observer.
# `shot` is a watch that ends after one picture. It rides this lifecycle
# rather than getting its own table and its own poller because everything that
# makes a watch safe applies unchanged to it: the channel cap, the staleness
# sweep, the refusal reasons, and - most of all - the selfbot verification
# that stops a login wedging the family's loot (#2781). A screenshot is not
# cheap: it costs a real client login. It should cost the same care.
POV = "pov"
CAM = "cam"
SHOT = "shot"
# `record` is an UNATTENDED recording - a security camera on one character for
# days at a time. It rides this same table and lifecycle for the same reason
# `shot` does, but it is the one mode with NO VIEWER AND NO NATURAL END, so
# the sweep below is what bounds it. The Windows agent holds the same deadline
# in memory (wow-stream-agent/recording.py) so that a recording still ends on
# time when this map has been unreachable for most of it.
RECORD = "record"
# LITERAL ON PURPOSE, and it must stay literal. The Windows stream agent reads
# this file with ast.literal_eval to prove its own vocabulary has not drifted
# from the map's - the two are separate codebases on separate machines with no
# import between them. A tuple of NAMES is not literal-evaluable, so the agent
# does not see a mismatch, it sees the constant VANISH: KeyError instead of
# assertEqual, which is a strictly worse signal about a strictly worse problem.
# Caught exactly that way when `shot` landed. The names above and this tuple
# are gated against each other in tests so the duplication cannot drift.
MODES = ("pov", "cam", "shot", "record")

# A shot needs no heartbeat: nobody is watching it, so there is no viewer to
# fall silent. The staleness sweep is its TIMEOUT instead - a shot the agent
# never serves ends by itself with a reason, exactly like an unanswered watch.
NEEDS_A_VIEWER = ("pov", "cam")  # literal, same reason as MODES

# requested -> the map asked
# starting  -> the agent has taken it and is launching
# live      -> a client is rendering; `detail` carries where to look
# stopping  -> nobody is watching any more, or a stop was asked for
# ended     -> the agent has torn down, or refused; `detail` says which
STATES = ("requested", "starting", "live", "stopping", "ended")

# States where a client exists or is about to. Only these can go stale, and
# only these count against the channel limit.
OCCUPIES_A_CLIENT = ("requested", "starting", "live")

# A shot is judged on a different clock. A watch goes stale when its VIEWER
# falls silent, which takes one missed beat plus margin. A shot has no viewer;
# what it is waiting on is a client login, which WoW measured at 45-60 seconds
# on that hardware. Sweeping it at STALE_AFTER_SECONDS would tear down the very
# client that is midway through starting for it - the timeout would reliably
# beat the thing it is timing.
SHOT_TIMEOUT_SECONDS = 180

# A recording is swept on its own mandate rather than either clock above:
# seven days, measured from requested_at. Gated against the agent copy - a map
# that still swept a recording at 60s would move the row to `stopping` one
# minute into a seven-day mandate, and the agent would tear down a client it
# had correctly started.
RECORD_TIMEOUT_SECONDS = 604800

# The other end of the lifecycle. Every way a watch ends carries a REASON in
# `detail` - "nobody was watching" from the sweep, or whatever the Windows
# agent says when it cannot honour a request (cam mode with no spare GM
# account, say). Those rows hold no channel, so nothing else here looks at
# them - and for a while they were dropped on the floor, which turned a
# carefully worded refusal into a button that quietly re-enabled itself.
TERMINAL = ("stopping", "ended")

# How long a finished row still has something to say. Long enough to explain
# a refusal that happened while you were looking at the panel; short enough
# that yesterday's teardown does not greet you on open.
OUTCOME_RECENT_SECONDS = 120

# TWO WAS RIGHT WHEN A CHANNEL MEANT STARTING A CLIENT. infra#2663 measured
# it on the old Windows box - "one or two channels is the realistic target on
# one GPU" - and on that box a channel really did cost a client launch, a
# login, and an NVENC session shared with the game.
#
# NEITHER HALF OF THAT PREMISE SURVIVES (infra#4266). The clients are not
# started on demand any more: all ten are the two families, and they are
# logged in whether anyone is watching or not. And the encoder is no longer
# expensive - capture goes compositor-to-Quick-Sync without touching system
# memory, and each running stream measures 0.02 cores. Ten of them cost less
# than one of the old ones did.
#
# So the cap is the roster, not the hardware. It still exists: it is what
# stops a bug requesting a channel for something that is not a character.
MAX_CHANNELS = 10

# HOW LONG "STARTING" HONESTLY TAKES, measured rather than hoped for: the
# Windows agent needs 45-60 seconds to launch a client, type a login, reach
# the world and PROVE the selfbot attached (infra#2663, and #2781 for why that
# proof is not optional). The page shows this number while it waits, because a
# progress indicator with no stated duration is indistinguishable from a hang
# - and this one is long enough that people close the tab first.
STARTUP_SECONDS = 60

# A row still saying 'requested' after this long has not been PICKED UP. The
# agent polls every 5 seconds and writes 'starting' the moment it takes a row,
# so six missed ticks is not a slow login - it is nothing running on the box.
#
# THIS IS A DISTINCT FAILURE AND MUST READ AS ONE. "waiting for a client" and
# "nothing is listening" look identical on screen and are fixed in completely
# different places, and the second is the state the box is in whenever the
# agent has not been started - which is often, because it is started by hand.
# Left unsaid, a viewer waits forever on a machine that was never going to
# answer, and concludes the feature is broken rather than switched off.
UNCLAIMED_AFTER_SECONDS = 30


# HOW A VIEWER ACTUALLY SEES IT, and the two are not interchangeable.
#
# SUNSHINE HAS NO BROWSER PLAYER. Measured on the box: 47984/47989 are its
# control APIs, 48010 is RTSP, and 47990 is the WEB CONFIG UI - a settings
# page, which is very easy to mistake for "the video is on a web port". Video
# leaves over the Moonlight protocol (RTSP handshake plus custom UDP), which
# no browser can consume. An <iframe> pointed at any Sunshine port shows
# settings or nothing.
#
# So infra#2663's delivery criterion is really two criteria of very different
# cost:
#   "reaches the Switch via Moonlight"     - works today, zero new machinery
#   "reaches a browser on the tailnet"     - needs a media server
#                                            (game -> NVENC -> RTMP -> WebRTC)
#
# `detail` therefore carries a KIND, and the map renders the right thing:
# instructions for a Moonlight viewer, an embeddable player only when a URL
# genuinely exists. Rendering a player for a Moonlight stream would be a
# black rectangle and a bug report.
DELIVERY_MOONLIGHT = "moonlight"  # detail = app name + instructions, TEXT
DELIVERY_EMBED = "embed"  # detail = a URL a browser can actually play


def delivery_of(row: Mapping) -> str:
    """How to present a live row: playable here, or instructions.

    Defaults to Moonlight, because that is what exists today and because the
    failure of guessing wrong in that direction is a sentence telling someone
    to open Moonlight. Guessing the other way renders a dead player.
    """
    kind = (row.get("delivery") or "").strip().lower()
    return DELIVERY_EMBED if kind == DELIVERY_EMBED else DELIVERY_MOONLIGHT


def needs_a_viewer(row) -> bool:
    """Does this row expect somebody to keep saying they are there?

    A watch does - silence means the viewer left, and the client must go. A
    shot does not: it is one picture, taken and finished, and demanding a
    heartbeat for it would tear down the very client that is mid-capture.

    ASKED AS "IS THIS A SHOT?", NOT AS "IS THIS IN NEEDS_A_VIEWER". The two
    differ on exactly one input and it is the one that matters: a mode nobody
    has heard of. Membership answers False for it - handing an unrecognised
    row a THREE MINUTE leash, which is a client rendering for nobody for three
    minutes if that row turns out to be a watch someone typed wrong. Asking
    the negative puts every unknown on the short, safe clock, where being
    wrong costs somebody a second click.

    An absent mode is right either way - `or POV` already covered rows that
    predate the column - but it is right here by construction rather than by a
    default that has to be remembered.

    TWO VIEWERLESS MODES NOW, AND STILL ASKED AS A NEGATIVE. `record` joined
    `shot` here, and the tempting rewrite - `mode in NEEDS_A_VIEWER` - would
    hand an unknown mode a seven-day leash instead of a sixty-second one.
    Listing the exceptions keeps every unrecognised row on the short clock.
    """
    return (row.get("mode") or "").strip().lower() not in (SHOT, RECORD)


def is_stale(row: Mapping, now_seconds: float) -> bool:
    """Has the viewer stopped saying they are there?

    A row that does not occupy a client cannot go stale - `ended` rows are
    history, and history does not need tearing down.

    A row with NO heartbeat yet is judged by when it was asked for, so a
    request the agent never picks up cannot sit in `requested` forever.
    """
    if row.get("state") not in OCCUPIES_A_CLIENT:
        return False
    last = row.get("last_seen_seconds")
    if last is None:
        last = row.get("requested_seconds")
    if last is None:
        # No clock at all on the row: refuse to guess. A caller that cannot
        # say when it last heard from the viewer has not measured anything,
        # and tearing a stream down on an absence of data is the mistake this
        # module exists to avoid.
        return False
    if needs_a_viewer(row):
        limit = STALE_AFTER_SECONDS
    elif (row.get("mode") or "").strip().lower() == RECORD:
        limit = RECORD_TIMEOUT_SECONDS
    else:
        limit = SHOT_TIMEOUT_SECONDS
    return (now_seconds - float(last)) > limit


def outcome_of(row: Mapping, now_seconds: float) -> dict | None:
    """What just happened to a watch that is no longer running.

    Returns None for a row that is still going, for one that ended too long
    ago to be news, and for one with nothing to say - a reason is the whole
    point, and "ended" on its own tells a viewer nothing they did not already
    see when the buttons came back.
    """
    if row.get("state") not in TERMINAL:
        return None
    detail = (row.get("detail") or "").strip()
    if not detail:
        return None
    when = row.get("last_seen_seconds")
    if when is None:
        # Same rule as staleness: no clock is not a measurement. Showing a
        # reason of unknown age is worse than showing none.
        return None
    if (now_seconds - float(when)) > OUTCOME_RECENT_SECONDS:
        return None
    return {"state": row.get("state"), "detail": detail}


def channels_in_use(rows) -> int:
    """How many of the GPU's channels are spoken for."""
    return sum(1 for r in rows if r.get("state") in OCCUPIES_A_CLIENT)


def can_start(rows, character: str, mode: str) -> tuple[bool, str]:
    """May this watch request start? Returns (allowed, reason-if-not).

    Reasons are written to be shown to a person, because they will be.
    """
    if mode not in MODES:
        return False, "unknown mode"
    for r in rows:
        if r.get("state") in OCCUPIES_A_CLIENT and r.get("character") == character:
            # Already watching them. Not an error - the answer is "you are
            # already there", and the caller should re-use that row's stream
            # rather than starting a second client on the same character.
            return False, "already watching"
    if channels_in_use(rows) >= MAX_CHANNELS:
        return False, (
            "both channels are in use - one GPU runs two clients, "
            "so stop one to start another"
        )
    return True, ""


def pov_changes_the_family(character: str, leader: str) -> bool:
    """Does watching this character in POV change what the family does?

    YES FOR THE LEADER, and the UI must say so rather than hide it. Logging in
    as a character makes it a selfbot; FindNewMaster hands the group leader to
    the followers when the leader is a selfbot, so the four of them acquire a
    master and `follow` starts resolving for as long as the stream is up.

    That is not a defect - it is arguably the best thing about watching Grug -
    but it means the family behaves differently while observed, and any
    cohesion measured during a stream is measuring the streamed configuration.
    A viewer should be told, not surprised - AND told that it stops when they
    stop watching, or they will wonder why the family scattered again after
    they closed the tab.
    """
    return bool(character) and character == leader


def stream_migrations(existing_columns) -> list:
    """The ALTERs overseer_stream needs to reach the shape this module writes.

    Same reasoning as goals.goal_migrations, and the same trap it was written
    for: CREATE TABLE IF NOT EXISTS is a no-op on an existing table, INCLUDING
    every word of the column definitions inside it. A table made by an older
    bridge keeps its old shape forever while CI, whose database is always
    fresh, produces the final shape directly and passes.

    Idempotent by construction: the input describes the CURRENT shape, so a
    table already correct yields an empty list. Feeding this its own result
    twice is a no-op the second time.
    """
    have = {c.lower() for c in existing_columns}
    wanted = [
        (
            "mode",
            "ALTER TABLE overseer_stream ADD COLUMN mode "
            "VARCHAR(16) NOT NULL DEFAULT 'cam'",
        ),
        (
            "state",
            "ALTER TABLE overseer_stream ADD COLUMN state "
            "VARCHAR(16) NOT NULL DEFAULT 'requested'",
        ),
        ("detail", "ALTER TABLE overseer_stream ADD COLUMN detail TEXT NULL"),
        (
            "last_seen",
            "ALTER TABLE overseer_stream ADD COLUMN last_seen "
            "TIMESTAMP NULL DEFAULT NULL",
        ),
    ]
    # VARCHAR, not ENUM, deliberately: overseer_goal's kind-ENUM is exactly
    # the trap above, and a new state word should never need a migration to
    # be sayable. The vocabulary lives in STATES, where a test can read it.
    return [sql for col, sql in wanted if col not in have]


def waited_seconds(row, now_seconds: float):
    """How long this request has been going, or None if it cannot be known.

    From `requested_at`, not from `last_seen`: the heartbeat rewrites last_seen
    every ten seconds, so a clock derived from it would read "3 seconds"
    forever and tell a waiting viewer nothing about the wait.

    None rather than 0 for a row with no clock, for the same reason is_stale
    refuses to guess: an invented elapsed time next to a stated 45-60s budget
    is a lie with a number on it, and a viewer would believe it.
    """
    started = row.get("requested_seconds")
    if started is None:
        return None
    return max(0, int(now_seconds - float(started)))


def looks_unclaimed(row, now_seconds: float) -> bool:
    """Is this request sitting in a queue that nobody is reading?

    ONLY EVER TRUE OF 'requested'. Once the agent writes 'starting' it holds
    the row and is spending its 45-60 seconds on it, and calling that
    unclaimed would accuse a working machine of being switched off, mid-login.
    """
    if row.get("state") != "requested":
        return False
    waited = waited_seconds(row, now_seconds)
    return waited is not None and waited > UNCLAIMED_AFTER_SECONDS
