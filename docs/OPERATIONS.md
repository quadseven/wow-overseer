# Operations reference

Moved from README.md on 2026-11-01 and not rechecked.

## The Watcher (observer camera)

`director.py` points one invisible, flying GM character at whoever the
operator names, so its stream shows them. It queues moves as
`overseer_command` rows of kind `gm` for that character, and its allow-list
(`director.observer_allows`) holds only observer commands.

Orders come from Discord (in the overseer channel, from an allowed user) or
`POST /api/director {"watch": "<order>"}` with the `X-Director-Token` header:

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
