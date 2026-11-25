# Operations reference

Moved from README.md on 2026-11-01 and not rechecked.

## The Watcher (observer camera)

`director.py` points one invisible, flying GM character at whoever the
operator names, so its stream shows them. It queues moves as
`overseer_command` rows of kind `gm` for that character, and its allow-list
(`director.observer_allows`) holds only observer commands. The worldserver
module runs those lines only for a real client on a game master account (kind
`gm` is retired for every other character), so the Watcher's account must be a
game master's. The director reads each line's answer back: a refused line is
named on the card ("Could not reach ...") and returned to the move budget, and
the card says "Now watching" only once the Watcher stands on the target's map
and instance within follow range. The budget (12 moves per 600 seconds) is a
sliding window and the card says when it refills.

Orders come from Discord (in the overseer channel, from an allowed user) or
`POST /api/director {"watch": "<order>"}` with the `X-Director-Token` header
and `Content-Type: application/json` (every JSON POST on the site requires it):

```text
watch <character> | family [key] | guild <name> | run <id>
  | dungeon <keyword> | bg | raid | off
```

An order lapses after 30 minutes unless renewed. `GET /api/director` shows
the order and what the Watcher is doing.

| Variable | Meaning |
|---|---|
| `OVERSEER_WATCHER_NAME` | The observer character's name (default `Watcher`). |
| `OVERSEER_DIRECTOR_TOKEN` | Key for the HTTP order. Unset closes the HTTP door. |
| `WATCH_CYCLE_SECONDS` | How often the director decides (default 3). |
| `WOW_STREAMED_CHARACTERS` | Must list the observer for the site to show its card. |

The character, its game account and the client that logs it in are the
deployment's to provide.

## Item-goal dungeon campaigns

An allowed Discord user can order `queue <family>: deadmines until
Cookie's Stirring Rod drops`. Add a run ceiling before `until`, such as
`deadmines 10 until ... drops`; without one the ceiling is 65535 runs.

The bridge resolves one case-insensitive exact item name, or one partial
match if no exact match exists. Unknown or ambiguous names ask for a more
specific name and leave the existing queue untouched. The reply identifies
the family, dungeon keyword and item id. Item-goal orders name one family
and one dungeon.

The queue pass finishes the entry when an enabled family member owns the
item in saved equipment, bags or personal bank, or when the run ceiling is
reached. Mail and other characters' items do not count. Saved inventory can
lag the live client. Existing campaign holds still apply. The bridge reports
an observed item completion in the overseer channel and advances the queue.
Pending notices survive restarts and retry failed sends. Delivery is at least
once: a crash after sending but before acknowledgement may repeat a notice.

## Molten Core first-kill self-order

When the guild's eligible approved seats (online, level 50 or more) meet the
first-kill quorum, no campaign or Molten Core order is ahead, and no order for
the family ended inside its wait, each bridge queue pass writes the same
first-kill queue row a typed order writes. It never rewrites the lineup.

| Variable | Meaning |
|---|---|
| `RAID_MC_SELF_ORDER` | Set to `1` to turn the pass on. Off when unset. |

The log has one `moltencore:` line per family per change: ordered, short (by
how many seats, tanks or healers), or waiting behind a named queue row.

## Trade turn between dungeon runs

A family with a campaign queue used to do no trade work, because the queue
owns the family's job while it holds an entry. After a queued run ends, with
any outcome, the queue now yields the job for one trade turn, then admits its
next entry under the usual rules (the bag floor included). During the turn
the craft rhythm, craft supply, learn trips and the town passes see a family
with an empty queue. The turn never interrupts a run, and never removes or
reorders an entry.

| Variable | Meaning |
|---|---|
| `TRADE_TURN_SECONDS` | Length of the turn (default 1200). 0 turns the rule off. |

A turn starts on the first queue pass after a run ends with no run in
progress, once per finished run, and only when some member has a trade below
the profession cap. Its start is stored in `overseer_dungeon_queue_turn`, so a
restart resumes the turn with its remaining time. The log has one line for
each turn start, end and skip, naming the family and the reason.

## Realm roller

`realmroller.py` and `realmroller_world.py` hold the release and channel file
formats, the pure decision of what a realm rolls to next, and its gate
readers. `realmroller_plan.py` plans the one roll commit, and
`realmroller_act.py` holds the GitHub, Kubernetes and status adapters a
scheduled job runs as `python3 realmroller_act.py ...`. A paused channel acts
on nothing. `tools/realm_roller.py` is a dry run. The bridge does not import
these modules.

## Metric snapshots

`tools/metric_watcher.py` reads the versioned API and appends one aggregate
JSON object per guild to a JSON Lines file: level gains, measured XP per hour,
dungeon runs, class quests, deaths, stuck and offline members, and each
crafter's profession skills. It writes no member names and uses no write
endpoint. When the site's `METRIC_WATCHER_OUTPUT` points at the same file,
the Raid tab shows alchemy progress and projected dates.

The units under `systemd/` run it every 30 minutes as the `wow-overseer`
account from `/opt/wow-overseer`:

```sh
sudo install -d -o wow-overseer -g wow-overseer /var/lib/wow-overseer
sudo install -D -m 0644 systemd/metric-watcher.env.example \
  /etc/wow-overseer/metric-watcher.env
sudoedit /etc/wow-overseer/metric-watcher.env
sudo install -D -m 0644 systemd/metric-watcher.service \
  /etc/systemd/system/metric-watcher.service
sudo install -D -m 0644 systemd/metric-watcher.timer \
  /etc/systemd/system/metric-watcher.timer
sudo systemctl daemon-reload
sudo systemctl enable --now metric-watcher.timer
```

`--api-root` and `--output`, or `METRIC_WATCHER_API_ROOT` and
`METRIC_WATCHER_OUTPUT`, set the API root and output path.

## Clip retention

The clip scan expires saved clips beyond two caps, oldest first. Both come
from the environment of the map server:

- `CLIP_MAX_COUNT`: most saved clips kept (default 200).
- `CLIP_MAX_AGE_DAYS`: days a clip is kept (default 30).

A missing value uses the default. A value that is not a whole number of 1 or
more uses the default and logs one line. An expired row records the cap that
removed it in its detail: `expired: count cap (N)` or `expired: age cap (N
days)`. Only the retention pass removes a saved clip.
