# Bot population cost: 500, 1000 and 2000 random bots on wow-dev

Research for [wo#514](https://github.com/quadseven/wow-overseer/issues/514), workstream C of [wo#512](https://github.com/quadseven/wow-overseer/issues/512). Read 2026-10-04. Live numbers are read-only reads of the wow-dev realm (kubelet stats, cgroup files, worldserver logs, read-only MySQL status queries) plus 7 days of container metrics. Capacity is stated as cores, GiB and per-bot cost; host identities are left out on purpose.

## Answer in brief

- A random bot costs about 1.5 MiB of worldserver memory at login, rising to about 2.2 MiB with uptime growth, and 0.3 to 3.6 mvCPU on this realm's 2.1 GHz cores. The repo's planning upper bound is 7 mvCPU for an always-active bot. Each online bot also needs two characters in the pool, at about 0.5 MiB of character data each, and adds about 0.2 MySQL queries per second.
- The first limit to bind is a policy gate, not hardware. The CI memory gate (limit at least 1.25x projected use) caps the dev world at about 680 online bots under today's 6656Mi limit. The character pool gate caps it at about 760 (1528 characters, two per online bot). Real memory is plentiful: the node runs at under half of its RAM.
- The first physical limit is the world tick on the two open-world continents. Each continent is one serial work item on one 2.1 GHz core, whatever `MapUpdate.Threads` says. SmartScale degrades it softly by idling bots, not by crashing. Today's tick has lots of headroom: 5 ms median and 11 ms mean at 500 bots, against upstream's comfort line of 70 to 80 ms.
- The worldserver's 4-vCPU limit is the hard wall between 1000 and 2000 bots at the pessimistic per-bot cost. Past 2000 bots, a dedicated, faster host is needed.

## Sources

| Source | What was read |
|---|---|
| Live wow-dev realm | Worldserver and MySQL resources, mounted `playerbots-overrides` and `worldserver-overrides` ConfigMaps, effective `worldserver.conf`, cgroup `cpu.stat` / `memory.current` / `memory.peak`, kubelet stats summary, `Playerbots.log` stats dump, worldserver logs, MySQL `SHOW GLOBAL STATUS` and `information_schema` sizes |
| Container metrics, 7 days | `kubernetes.cpu.usage.total`, `kubernetes.memory.{usage,working_set,rss,cache}` for the worldserver and mysql containers; `wow.dev.world.characters_online`; logged `Update time diff` summaries |
| infra main | `production/oke/manifests/wow-dev/footprint.yaml`, `config/playerbots.overrides.conf`, `tests/test_dev_world_isolation.py`; `production/oke/manifests/wow/50-worldserver.yaml`, `10-mysql.yaml`, `config/playerbots.overrides.conf` |
| Prior measurement | infra#4722 (142 bots: about 4.4 GiB and 2.5 vCPU projected), infra#3735 (the 20 to 500 staircase and the three-realm cost fit) |
| mod-playerbots @ [7a593fa][pb] (the pinned commit) | `PlayerbotAI::AllowActive`, `AllowActivity`, `AutoScaleActivity` in `src/Bot/PlayerbotAI.cpp`; `RandomPlayerbotMgr::PrintStats`; `conf/playerbots.conf.dist` ACTIVITY section |
| AzerothCore master | `src/server/game/Time/UpdateTime.cpp` (what the logged tick numbers mean, and the max-diff table SmartScale reads), `src/server/game/Maps/MapMgr.cpp` (one scheduled work item per map) |
| mod-playerbots wiki @ [75b233c][wiki] | `Playerbot-Configuration.md` (activity profiles, hardware, the 5000-bot reference), `Troubleshooting.md` (map threads, rising diff) |

[pb]: https://github.com/mod-playerbots/mod-playerbots/tree/7a593fa254840221f1d63b7beb8d9735e55309ba
[wiki]: https://github.com/mod-playerbots/mod-playerbots/wiki/Playerbot-Configuration

## What wow-dev runs today

| Setting | Value | Where |
|---|---|---|
| `MinRandomBots` / `MaxRandomBots` | 500 / 500 | playerbots overrides |
| Online characters, 7 days | 500 to 521 (bots plus the roster) | `wow.dev.world.characters_online` |
| `EnablePeriodicOnlineOffline`, ratio | on, 2.0 (two characters per online slot) | playerbots overrides |
| `RandomBotMaps` | 0, 1 (the two classic continents) | playerbots overrides |
| `BotActiveAlone` / `botActiveAloneSmartScale` | 100 / 1 (upstream "profile 2") | playerbots overrides |
| SmartScale floor / ceiling | 50 ms / 200 ms (dist defaults) | `playerbots.conf.dist` |
| `MapUpdate.Threads` | 2 (env `AC_MAP_UPDATE_THREADS=2` overrides the file's 1) | deployment env, effective conf |
| `MapUpdateInterval`, `MinWorldUpdateTime` | 10, 1 | deployment env |
| Worldserver requests / limits | 2 vCPU, 5Gi / 4 vCPU, 6656Mi | live deployment |
| MySQL requests / limits | 250m, 2Gi / no CPU limit, 3Gi | live statefulset |
| InnoDB buffer pool | 512 MiB effective (args pass `3G` then `512M`; the last wins; confirmed via `@@innodb_buffer_pool_size`) | live statefulset, MySQL |
| Node | 8 vCPU at 2.1 GHz, 26.9 GiB allocatable, shared with a paused sibling realm's MySQL | kubelet |

Production (`wow`, paused at 0 replicas today) runs the same 500 bots with `BotActiveAlone = 10`, four maps (`0,1,530,571`), 6 map threads and a 7 vCPU / 24Gi limit on a 16-vCPU host.

The repo enforces the over-250 throttle in `test_the_expensive_activity_path_is_gated_on_population`. Above `ALWAYS_ACTIVE_CEILING = 250` online bots, `botActiveAloneSmartScale` must be 1. With SmartScale on, `BotActiveAlone = 100` never takes the unconditional fast path (`botActiveAlone >= 100 && !smartScale`). Every unforced bot goes through `AutoScaleActivity`.

## Measured cost at 500 bots

### Worldserver CPU

- Over the last 7 days, the hourly average sat between 1.51 and 1.85 vCPU, with a median of 1.74. That is 44 percent of the 4-vCPU limit. The current cgroup shows `nr_throttled 0`.
- An instant read during bot login after a restart showed 1.64 vCPU, with the whole node at 2.3 of 8 vCPU.
- The same realm at 20 always-active bots measured 1.59 vCPU (2026-09-13, footprint.yaml). The 20 to 500 step therefore cost about 0.15 vCPU, or about 0.3 mvCPU per bot. infra#4722 found the same thing: no visible CPU step at any stair of the staircase.
- The pessimistic reading comes from the production fit. A sibling realm with 10 throttled bots measured 1.51 vCPU, and live production with 500 throttled bots measured 2.32 vCPU. The difference is 1.65 mvCPU per bot on cores worth about 2.2x these, so roughly 3.6 mvCPU per bot at this realm's clock. The two realms differ in maps and activity profile, so this is an upper estimate, not a measured slope.
- Most worldserver CPU is base cost, not bots. The always-active upper bound the repo plans with is 7 mvCPU per bot (`ALWAYS_ACTIVE_CEILING` comment).

### Worldserver memory

- At 4 minutes after restart with 499 bots logged in, `memory.current` was 4.39 GiB and the peak was 4.40 GiB.
- Over 7 days, RSS ranged from 4.04 to 5.25 GiB (median 4.84) and working set from 4.16 to 5.33 GiB. Container usage, page cache included, peaked at 6.50 GiB, which is the limit. The cache was 0 to 1.54 GiB, and nothing was OOMKilled in the window.
- Usage climbs steadily between restarts: about 0.1 GiB per hour across one 10-hour stretch, cache included. The upstream wiki warns that the footprint grows and recommends scheduled restarts. Frequent deploys restart wow-dev often enough to hide this.
- Fit: the repo's model is a 4198 MiB base, plus 1.5 MiB per online bot, plus 100 MiB for the auction house bot. The model holds at login. With uptime growth, the 7-day RSS maximum implies about 2.2 MiB per bot.

### World tick

The worldserver logs `Update time diff` every 5 minutes (`RecordUpdateTimeDiffInterval = 300000`). It logs only when the current tick exceeds `MinRecordUpdateTimeDiff = 100` ms, with a summary of the last 500 ticks (`UpdateTime.cpp`, `WorldUpdateTime::RecordUpdateTime`). Over 7 days of these summaries:

| Statistic of the last 500 ticks | min | median | p90 | max |
|---|---|---|---|---|
| Mean | 9 ms | 11 ms | 12 ms | 16 ms |
| p95 | 19 ms | 26 ms | 31 ms | 43 ms |
| p99 | 26 ms | 37 ms | 44 ms | 72 ms |
| Max | 101 ms | 162 ms | 204 ms | 332 ms |

A fresh summary at 19:14 UTC showed a 5 ms median, 11 ms mean and 40 ms p99. The max row is biased upward, because a summary is printed only when a tick over 100 ms occurs. Upstream's health line is a general latency under 70 to 80 ms with percentiles topping out around 100 to 150 ms (wiki, "Verify bot performance"). At 500 bots the mean sits at about one seventh of that line.

### How SmartScale reads the tick

`AutoScaleActivity` reads `GetMaxUpdateTimeOfCurrentTable()`, the maximum of the current and previous 500-tick tables. That window covers about 5 to 11 seconds at today's tick. Below 50 ms the full `BotActiveAlone` applies. Between 50 and 200 ms the active share scales down linearly. Above 200 ms, only force-active bots run: those in combat, in an instance, in LFG, grouped with a client, or in a guild with a real player.

The stats dump (`RandomBotPrintStatsInterval = 300`) at 19:13 UTC showed `499 online, Active: 497, In combat: 43, Dead: 13`. Spikes are rare enough (p99 under 50 ms) that at that sample almost every bot was active. Single spikes over 50 ms do throttle activity for a few seconds after they occur.

### MySQL

- Over 7 days the median was 0.10 vCPU and the maximum 0.17. Memory measured 2.15 GiB of the 3Gi limit (72 percent); that figure is sized by the schema and per-connection buffers, not the roster (footprint.yaml).
- Data: 778 MiB characters, 434 MiB world, 78 MiB playerbots, 1.29 GiB in total against a 512 MiB pool. The buffer pool hit ratio is 99.987 percent.
- Over the 21-day server lifetime, mostly at 500 online, the server averaged 112 queries/s, about 49 insert, update and delete statements/s, and 233 KB/s of InnoDB writes. Per online bot, that is about 0.2 queries/s and 0.1 write statements/s, with base load included, so these are upper bounds.
- 1633 characters exist, so character data runs at about 0.48 MiB per character. That figure will grow as bots level and fill bags and quest logs.

## Per-bot cost table

| Resource | Per online bot | Basis |
|---|---|---|
| Worldserver memory | 1.5 MiB at login, about 2.2 MiB with uptime growth | three-realm cgroup fit; 7-day RSS max |
| Worldserver CPU | 0.3 mvCPU observed, 3.6 mvCPU pessimistic, 7 mvCPU repo upper bound (always active) | 20 to 500 on this realm; production fit scaled by clock; `ALWAYS_ACTIVE_CEILING` |
| Characters needed | 2 (rotation ratio 2.0) | `PeriodicOnlineOfflineRatio`, `DEV_CHARACTER_POOL` test |
| Character data | about 1 MiB (two characters at 0.48 MiB) | `information_schema` |
| MySQL load | at most about 0.2 queries/s | 21-day `Questions / Uptime` |
| Base, not per bot | about 4.1 GiB and about 1.5 vCPU | same fit |

## Projection

| Online bots | Worldserver memory (login / with growth) | CI limit needed (1.25x) | Worldserver CPU (observed / pessimistic / always-active bound) | Characters | Character DB |
|---|---|---|---|---|---|
| 500 (today) | 5.0 / 5.3 GiB | 6.2 GiB (have 6.5) | 1.7 / 3.3 / 5.0 vCPU | 1000 (have 1633) | 0.8 GiB |
| 1000 | 5.7 / 6.4 GiB | 7.1 to 8.0 GiB | 1.9 / 5.1 / 8.5 vCPU | 2000 | about 1.0 GiB |
| 2000 | 7.1 / 8.5 GiB | 8.9 to 10.6 GiB | 2.2 / 8.7 / 15.5 vCPU | 4000 | about 1.9 GiB |

The CPU columns add the per-bot figures to the 1.59 vCPU measured at 20 bots. Only the observed column has data behind it at scale. The pessimistic column exceeds the 4-vCPU limit at about 700 bots, and the always-active column at about 340. The live realm already disproves the always-active column at 500, because SmartScale and the forced-activity rules hold activity well short of it. Treat 1000 as the measurement step that picks between the columns.

## Which limit binds first

In order of the online count at which each one stops the climb:

1. About 680 bots: the worldserver memory gate in CI. `test_the_roster_fits_inside_the_memory_limit_it_declares` requires 1.25 x (4198 + 1.5n + 100) MiB <= the limit. At 6656Mi that allows n <= 684. This is a policy limit; the memory is physically there.
2. About 760 bots: the character pool gate. `DEV_CHARACTER_POOL = 1528` at two characters per online slot allows 764. `RandomBotAccountCount = 0` lets the manager create accounts, but the test counts the verified pool.
3. Immediately after either fix: the node memory-limit budget gate. `test_the_node_can_honour_every_memory_limit_on_it_at_once` allows world plus MySQL limits of 0.9 x 27563 - 14798 = 10009 MiB, and they already total 9728 MiB, leaving 281 MiB of slack. The recorded `OTHER_MEMORY_LIMITS_MIB = 14798` includes the paused sibling realm's 6Gi worldserver. The live node's limits total 18318Mi, so with the sibling paused the real slack for world plus MySQL is about 16.2 GiB.
4. The first physical limit, somewhere between 1000 and 2000 bots: the per-continent tick and the 4-vCPU limit. `MapMgr::Update` schedules one work item per map, so 2000 bots on two continents is about 1000 bots per serial update on one 2.1 GHz core. Raising `MapUpdate.Threads` does not split a continent. The tick is protected by SmartScale: as spikes above 50 ms become common, activity drops and the world gets quieter, not dead. The CPU limit throttles the process if the pessimistic per-bot cost holds.
5. Not binding before 2000: MySQL CPU (0.1 vCPU), the buffer pool hit rate (99.99 percent), and node RAM (11.4 of 26.9 GiB working set).

## What to change at 1000

- Raise the worldserver memory limit to about 7.5Gi and the request to about 6Gi (projection 5.7 to 6.4 GiB). Re-measure the sibling realm's real limits into `OTHER_MEMORY_LIMITS_MIB`, or retire it from the node. Without that, the budget test fails.
- Grow the pool to at least 2000 characters by letting the manager create accounts (each RNDBOT account holds 10). Then count the result and update `DEV_CHARACTER_POOL`. New bots start at level 1, so this stays within the natural-progression rule.
- Keep `botActiveAloneSmartScale = 1`; the gate requires it anyway. `BotActiveAlone = 100` can stay while the tick holds.
- Raise `MapUpdate.Threads` from 2 to 3 if dungeon or raid runs overlap with the open world. Instances are separate maps; the continents are not. Keep the 4-vCPU half-node cap.
- MySQL needs no change. Watch its memory, which is at 72 percent of the limit today.
- Hold the step until it measures green: tick mean under 30 ms and p99 under 50 ms from the 5-minute summaries; `Active:` in the stats dump close to `online`; worldserver CPU under 3 vCPU with `nr_throttled` flat; MySQL memory under 85 percent of the limit. This step is the one that decides which CPU column is real.

## What to change at 2000

- Worldserver memory limit of about 10 to 11 GiB, request about 8.5 GiB. This fits the node's RAM only while the sibling realm stays off it.
- CPU: if the 1000-bot step lands on the pessimistic column, 2000 needs about 8.7 vCPU, which is more than the whole node. The lever is activity, not cores. Lower `BotActiveAlone` toward upstream's profile 1 (10, SmartScale on), which is what production runs. Forced-activity rules keep grouped, fighting, dungeon and guild-with-a-player bots fully active, so the raid roster loses nothing. Idle farmers tick less. If the observed column holds (about 2.2 vCPU), `BotActiveAlone = 100` can stay.
- Characters: 4000, about 400 RNDBOT accounts against the 162 today.
- MySQL: raise the buffer pool from 512M to 1.5 to 2G, because the dataset will be about 2.5 GiB. Raise the limit from 3Gi to about 4.5Gi and the CPU request from 250m to 500m. Also drop the dead `--innodb_buffer_pool_size=3G` argument so that only one value remains. Upstream recommends a pool of half of RAM.
- `MapUpdate.Threads` of 3 to 4 for concurrent instances, within the CPU limit.

## What past 2000 would take

- This node cannot hold it. Its cores run at 2.1 GHz, and the open world is two continents: with `MaxPlayerLevel = 60`, Outland and Northrend stay out of `RandomBotMaps`. Every added bot lands on one of two serial map updates.
- Upstream's reference point is 5000 bots on 6 cores at 4.6 GHz with 20 GB of RAM, running profile 1 (`BotActiveAlone = 10`, SmartScale on) (wiki, "Reference"). The wiki's recommended hardware is 6 or more cores at 4.4 GHz or faster and 32 GB or more. Scaled by clock, this node's 8 vCPU is worth about 3.6 such cores, before any sharing.
- So past 2000 means a dedicated host with fast cores (production's class: 16 vCPU), a worldserver with about 12 GiB or more (production's own projection is about 12 GB at 2000 under a 24Gi limit), MySQL with a pool of several GiB, `BotActiveAlone` around 10, and scheduled restarts for the memory growth upstream warns about. The cost per bot stays small. The serial per-continent tick and core speed decide how far it goes.

## Open questions

- Which CPU column is real. Only a measured 1000-bot step separates 0.3 from 3.6 mvCPU per bot. The 20-bot baseline is three weeks old and predates later mod-overseer work.
- Whether tick spikes over 100 ms grow with population or come from base work (saves, the overseer poll, logins). The 5-minute log samples cannot attribute them. `AiPlayerbot.PerfMonEnabled` is off.
- Whether the sibling realm is coming back to this node. Every memory step past about 700 bots depends on its 6Gi worldserver limit not being there.
