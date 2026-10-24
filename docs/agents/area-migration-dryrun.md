# Area migration dry run

Read-only proposal, generated 2026-10-24 from all 344 open issues in wow-overseer and mod-overseer (one, wow-overseer#1329, was missed by the sweep and gets classified at apply time). Nothing has been written. Ten sweepers classified the tickets against `area-taxonomy.md`. The epic decisions below were then reconciled by hand. The apply pass re-reads every ticket first, and a verifier spot-checks a random 1 in 5 before any write.

## Summary

| Area | Open tickets |
|---|---|
| `area:dungeons` | 54 |
| `area:stability` | 46 |
| `area:tooling` | 37 |
| `area:professions` | 35 |
| `area:economy` | 31 |
| `area:guild` | 29 |
| `area:travel` | 29 |
| `area:raids` | 28 |
| `area:questing` | 23 |
| `area:class` | 17 |
| `area:site` | 15 |

Topic labels proposed: 58. The most used are `stab:stuck` (24), `raid:prep` (22), `travel:pathing` (21), `stab:deaths` (19), `travel:crossing` (16), `raid:molten-core` (16), `guild:chat` (15), `quest:class` (14), `stab:roll` (13), `guild:social` (13), `guild:runs` (12), `econ:bags` (12), `econ:bank` (11), `econ:auction` (10), `class:gear` (9).

## Epic decisions

- **Retire 13 catch-all epics** ("work that triage, rewrites and health intake find"): mod-overseer#1065, mod-overseer#1100, mod-overseer#1118, mod-overseer#1134, mod-overseer#995, wow-overseer#1167, wow-overseer#1247, wow-overseer#1267, wow-overseer#1321, wow-overseer#1347, wow-overseer#1351, wow-overseer#1359, wow-overseer#1399. Their children move to the epic of their own area first, and each catch-all closes only once it is empty.
- **Split over-cap epics by topic** (each holds more than 15 tickets, against Loom decision 0003):
  - wow-overseer#21 (20 children, Epic: the family gathers and crafts until every profession is maxed): split by trade
  - wow-overseer#194 (18 children, Epic: the family keeps its bags, gold and sales moving): split: bags / bank and auction / vendors and gold
  - mod-overseer#518 (20 children, Epic: the family can reliably reach where it is sent): split: pathing / crossings
  - mod-overseer#35 (23 children, Epic: a hardcore realm where deaths are evidence and the bots get better): split: deaths / recovery
  - mod-overseer#46 (48 children, Epic: WoW overseer - command, observe, and converse with the world): reads as a goal; its children move to area epics
  - mod-overseer#88 (34 children, Epic: the party owns the run through one coordinator state machine): split by dungeon band
  - mod-overseer#141 (34 children, Epic: a living family: gear up in Deadmines, then live off the world): split: Deadmines gear-up / living off the world
- **Overlapping epics:**
  - wow-overseer#195 (Epic: the family progresses through dungeons to level 60 and raids): keep (dungeons, levels to 60); raid-readiness children move to #470
  - wow-overseer#467 (Epic: dungeon progression to level 60): keep alongside #195 (combined 24 children breaks the 15 cap); split the pair by level band
  - wow-overseer#468 (Epic: professions and crafting system): retire into per-trade epics (split of #21)
  - wow-overseer#469 (Epic: the guild economy - farming, gold and materials): merge into #194's split (economy)
  - mod-overseer#469 (Epic: the world is one map - inter-continent travel, transport, summons): merge into mod-overseer#513 (cross-continent travel)
  - mod-overseer#514 (Epic: enchanting for the family - enchant and disenchant): becomes the trade:enchanting epic
- **New epics the sweep asked for** (consolidated at apply time to one per theme):
  - gear has one owner and equips land (4 tickets)
  - class spell training and gear for guild members (3 tickets)
  - class training - trainers, weapon skills, talents and gear (2 tickets)
  - the overseer runs guild-scale goals stated in plain language (2 tickets)
  - two POV streams without taking the operator's desktop (2 tickets)
  - class quests come first for every member (2 tickets)
  - review-finding cleanups for the bridge (2 tickets)
  - group buffs and party upkeep verified live (1 ticket)
  - the family equips the best gear it owns (1 ticket)
  - tooling - audit signals and diagnostics for the playing realm (1 ticket)
  - none - this is a Goal, not an epic (1 ticket)
  - tooling - retire old realms and Hermes pieces (1 ticket)
  - PvP gear upgrades through battlegrounds (1 ticket)
  - class trainers are visited on levelup (1 ticket)
  - class AI fixes for tank, healer and caster roles (1 ticket)
  - module patch parity with the deploy repo (1 ticket)
  - run health findings name the real cause (1 ticket)
  - module unit test coverage (1 ticket)
  - class training ranks arrive on time (1 ticket)
  - ship and roll process is safe and documented (1 ticket)
  - module decisions are testable without a C++ harness (1 ticket)
  - none needed, this is a Goal not a ticket (1 ticket)
  - review-finding cleanups for overseer tests (1 ticket)
  - families train class spells and raise trades on time (1 ticket)
  - Ragnaros one-shot module work (goal issue, loom:goal, 18 children; not an epic) (1 ticket)
  - review-finding cleanups (1 ticket)
- **Likely duplicates** (closed as duplicates only after a person confirms):
  - mod-overseer#520 duplicates mod-overseer#523
  - mod-overseer#530 duplicates mod-overseer#446
  - wow-overseer#1108 duplicates wow-overseer#1337

## Every ticket, by area

### `area:dungeons`

| Ticket | Title | Topics | Proposed epic | Note |
|---|---|---|---|---|
| mod-overseer#141 (epic) | Epic: a living family: gear up in Deadmines, then live off the world | `dungeon:deadmines` | split: Deadmines gear-up / living off the world | 34 children, broad (economy, chat, professions); split by area |
| mod-overseer#516 (epic) | Epic: fair loot distribution for group and raid content |  | keep | loot for group and raid; spans dungeons and raids |
| mod-overseer#88 (epic) | Epic: the party owns the run through one coordinator state machine |  | split by dungeon band | 34 children, over the 15 cap |
| wow-overseer#195 (epic) | Epic: the family progresses through dungeons to level 60 and raids |  | keep (dungeons, levels to 60); raid-readiness children move to #470 | overlaps #467 dungeon progression; raid readiness part belongs in #470 |
| wow-overseer#467 (epic) | Epic: dungeon progression to level 60 |  | keep alongside #195 (combined 24 children breaks the 15 cap); split the pair by  |  |
| mod-overseer#1021 | A family member on a guild finder run is not adopted into a family dungeon run and walked  | `dungeon:blackfathom` `guild:runs` | mod-overseer#88 |  |
| mod-overseer#1045 | A family dungeon run the finder takes in is ended as emptied while the family is inside | `guild:runs` | mod-overseer#88 |  |
| mod-overseer#1086 | A guild finder run never skips a boss the dungeon brain cannot reach, so a stalled run hol | `guild:runs` | mod-overseer#88 |  |
| mod-overseer#127 | The dungeon-clear issuer warning fires every 8 seconds for a bot that is already armed |  | mod-overseer#88 | Log-noise issue |
| mod-overseer#152 | Post dungeon run report to Discord and family page |  | mod-overseer#88 | Depends on #82 and #144 |
| mod-overseer#153 | A leader who ends up outside an active dungeon run is never brought back to it |  | mod-overseer#88 |  |
| mod-overseer#165 | Fix staging deadlock when a member enters the dungeon early |  | mod-overseer#88 |  |
| mod-overseer#241 | The leader is revived onto another continent and the four followers can never rejoin it: t | `stab:stuck` | wow-overseer#195 | revive plus cross-continent rejoin; could also be stability |
| mod-overseer#384 | Live-check stranded dungeon member rejoin | `stab:stuck` | wow-overseer#195 |  |
| mod-overseer#396 | Add persisted quarantine after failed approach to prevent staging_failed loop | `stab:stuck` | wow-overseer#195 |  |
| mod-overseer#510 | Blackrock Depths has no portal row, so a level 60 family's dungeon job is refused with 'un | `dungeon:blackrock-depths` | wow-overseer#195 |  |
| mod-overseer#579 | Eleven new dungeon doors need a surveyed approach or a lift the walker cannot ride | `dungeon:gnomeregan` `dungeon:razorfen-downs` | wow-overseer#467 | wow-overseer#195 and #467 overlap (dungeon progression); consolidate |
| mod-overseer#645 | Give a Stratholme run a way out of the exit yard, so both rows can be offered again | `dungeon:stratholme` | wow-overseer#467 | Body says Part of #548 which is not in the open epic list |
| mod-overseer#696 | Run recovery escalates: summon at the door's meeting stone, then the dungeon finder as the |  | mod-overseer#88 | Run recovery ladder; related to mod-overseer#702 |
| mod-overseer#702 | Add ritual summoning rung for guild warlock recovery |  | mod-overseer#88 | Moves out of catch-all mod-overseer#1100; sibling of #696 (summon rungs), not a clear dupl |
| mod-overseer#720 | fix: Ragefire closes blame the staging point for the corridor start, and the reset asks wh | `dungeon:ragefire-chasm` | mod-overseer#88 |  |
| mod-overseer#739 | The Alliance family has been stuck since 05:10: a summon rung no warlock can serve never e | `dungeon:zul-farrak` `travel:crossing` | mod-overseer#88 |  |
| mod-overseer#759 | Ragefire: a leader who joins the corridor leaves it between points and wanders Orgrimmar's | `dungeon:ragefire-chasm` | mod-overseer#88 | Same dungeon as #720, different cause |
| mod-overseer#762 | A run-owned travel aim from before a restart has no owner and holds the next dungeon run f | `travel:pathing` | mod-overseer#88 |  |
| mod-overseer#767 | The dungeon queue has held both families for 40 hours: no level, no cleared run, no profes | `stab:deaths` | wow-overseer#467 | Has no parent today |
| mod-overseer#792 | A headless family enters its dungeon and can never clear it: the run's leader needs a sock | `dungeon:stockade` | mod-overseer#88 |  |
| mod-overseer#963 | Dungeon runs: lockouts, group forming, and honest refusals | `guild:runs` | wow-overseer#467 | Leaves catch-all mod-overseer#1118; lockouts and group forming |
| mod-overseer#964 | Item mandates: grind until it drops, and give it to the right hands | `raid:prep` | wow-overseer#467 | Spans dungeons, loot and goals; dungeon source runs chosen as the player-visible area |
| mod-overseer#971 | Record dungeon run boundaries, loot, boss kills and damage for post-run summary |  | mod-overseer#88 |  |
| mod-overseer#972 | A dungeon run has an end: every held quest done, then turned in together | `dungeon:deadmines` | mod-overseer#88 |  |
| wow-overseer#1074 | Health: Zug's family ran Blackfathom Deeps 3 times without a clear | `dungeon:blackfathom` | wow-overseer#195 |  |
| wow-overseer#1078 | The stall breaker steps past a held door instead of holding the family's queue silently |  | wow-overseer#195 |  |
| wow-overseer#1105 | Build automated warlock Ritual of Summoning network for Phase 2 |  | wow-overseer#195 | No parent; check overlap with #890 and mod-overseer#702 |
| wow-overseer#1287 | Health: Grug's family ran Razorfen Downs 3 times without a clear | `dungeon:razorfen-downs` | wow-overseer#195 |  |
| wow-overseer#1311 | A health finding about dungeon runs is diagnosed from its runs and logs |  | wow-overseer#195 |  |
| wow-overseer#1369 | A run ended by a worldserver roll does not count as the door beating a returned family | `stab:roll` | wow-overseer#467 |  |
| wow-overseer#1384 | Complete criteria left from PR #1371 |  | wow-overseer#467 | Combined 10-man run; criteria-left ticket |
| wow-overseer#1400 | Re-plan stalled dungeon families that clear without progress |  | wow-overseer#467 |  |
| wow-overseer#356 | Jev is acted on in 11% of staging_stall and 36% of run_recovery calls: low-confidence answ | `guild:chat` | wow-overseer#195 | Jev LLM quality in dungeon staging/recovery; could be guild:chat under #200 |
| wow-overseer#473 | Cross-family 10-man grouping for UBRS | `dungeon:ubrs` | wow-overseer#467 | parent #467 proposed to merge into #195 |
| wow-overseer#581 | Dungeon clear plays low-level dungeons like a careful group | `dungeon:deadmines` | wow-overseer#467 | Parent is a Goal; topic is low-level dungeons in general (Wailing Caverns example) |
| wow-overseer#745 | The Deadmines: both guilds 0 of 60+ clears | `dungeon:deadmines` | wow-overseer#467 | No parent; body says Part of epic #467 |
| wow-overseer#768 | Magmadar: fear protection before Panic, and Tranquilizing Shot on Frenzy | `raid:molten-core` | wow-overseer#467 | Magmadar is Molten Core (raid); consider area:raids / raid:molten-core and epic wow-overse |
| wow-overseer#782 | Blackfathom Deeps: no guild run can finish; followers drown and nothing lights the Fires o | `dungeon:blackfathom` | wow-overseer#467 |  |
| wow-overseer#783 | A Blackrock Depths guild run ends at its first boss: the finder's Prison row finishes on G | `dungeon:blackrock-depths` | wow-overseer#467 |  |
| wow-overseer#784 | Seven tanks and seven to ten healers a guild seat about half of each guild; Cave's healers |  | wow-overseer#467 | body says Part of #467 |
| wow-overseer#785 | Keyed dungeon doors: guild runs seat no key holder, and dungeon clear opens doors without  |  | wow-overseer#467 |  |
| wow-overseer#807 | Gnomeregan: mod-dungeon-clear has no data for its doors, so guild runs are held | `dungeon:gnomeregan` | wow-overseer#467 |  |
| wow-overseer#811 | Shadowforge Key via Dark Iron quest | `dungeon:blackrock-depths` | wow-overseer#467 | Shadowforge Key opens BRD door; currently under catch-all |
| wow-overseer#812 | A Dire Maul East run chases Pusillin down for the Crescent Key | `dungeon:dire-maul` | wow-overseer#467 |  |
| wow-overseer#835 | Guild runs time out at 2 h cap and lose boss credit |  | wow-overseer#467 |  |
| wow-overseer#890 | A summoner waits on call at the meeting stone of the door its family's campaign is heading |  | wow-overseer#195 | Summon network; overlaps mod-overseer#702/#696 work |
| wow-overseer#913 | A member waiting in a battleground queue is held from dungeon asks and seats |  | wow-overseer#195 |  |
| wow-overseer#96 | Do we need to be able to author a corridor at all? | `dungeon:wailing-caverns` `travel:pathing` | wow-overseer#467 | parent is a Map, not an epic |

### `area:stability`

| Ticket | Title | Topics | Proposed epic | Note |
|---|---|---|---|---|
| mod-overseer#35 (epic) | Epic: a hardcore realm where deaths are evidence and the bots get better | `stab:deaths` | split: deaths / recovery |  |
| mod-overseer#575 (epic) | Epic: the worldserver stays up while the family plays | `stab:roll` | keep |  |
| wow-overseer#1166 (epic) | Epic: no member stays held on a blocker the family can clear itself | `stab:stuck` | keep |  |
| wow-overseer#199 (epic) | Epic: every realm runs exactly what the repo says it runs |  | keep |  |
| wow-overseer#466 (epic) | Epic: bot stability and critical bug fixes |  | keep |  |
| mod-overseer#1046 | A guild run's ghost walks to the spirit healer while its run waits for adoption after a re | `guild:runs` `stab:deaths` | mod-overseer#35 |  |
| mod-overseer#1092 | A member sent to sit out leaves the dungeon instead of holding a run alone inside it | `stab:stuck` | wow-overseer#1166 |  |
| mod-overseer#151 | Learn from deaths: zone and creature danger memory | `stab:deaths` | mod-overseer#35 |  |
| mod-overseer#163 | The death guard does not hold: an operator travel aim is cleared and the quest drive walks | `stab:deaths` `zone:duskwood` | mod-overseer#35 |  |
| mod-overseer#188 | Investigate root cause of below-world deaths after recovery fixes B and C | `stab:deaths` | mod-overseer#35 |  |
| mod-overseer#252 | Clear dead-clock on revive and verify live release-prompt timing | `stab:deaths` | mod-overseer#35 |  |
| mod-overseer#254 | mod-playerbots CompleteDismount clears MOVEMENTFLAG_FALLING under a live MoveFall spline,  | `stab:deaths` | mod-overseer#35 | upstream mod-playerbots falling/dismount bug |
| mod-overseer#270 | Fix misleading death reports for characters falling in the void | `stab:deaths` | mod-overseer#35 |  |
| mod-overseer#503 | Three of the roster's self-attributed deaths are drowning: the leader was held on a stuck  | `stab:deaths` `stab:stuck` | mod-overseer#35 |  |
| mod-overseer#520 | Root-cause worldserver exit-139 segfault and logout crash path | `stab:roll` | mod-overseer#575 | related crash; possibly the same segfault |
| mod-overseer#523 | worldserver SIGSEGV (139): mod-dungeon-clear spins then crashes when a roster member leave | `stab:roll` | mod-overseer#575 | drop the invalid topic dungeon:crash if strict; area dungeons not needed |
| mod-overseer#741 | A worldserver segfault leaves no backtrace, so no crash can be given a cause: print a symb |  | mod-overseer#575 |  |
| mod-overseer#744 | A follower held far away is held still on ground above its level and killed over and over  | `stab:deaths` `stab:stuck` `zone:tanaris` | mod-overseer#35 |  |
| mod-overseer#746 | A member revived at the spirit healer stands sick at a hostile graveyard and dies again, o | `stab:deaths` `zone:dustwallow-marsh` | mod-overseer#35 |  |
| mod-overseer#933 | A graveyard is judged by the same danger test as repeat deaths: same-level hostiles and th | `stab:deaths` | mod-overseer#35 | Shipped, audit-failed label; leaves catch-all mod-overseer#995 |
| mod-overseer#958 | A sick ghost does not run back to a corpse its killers stand on | `stab:deaths` | mod-overseer#35 | Merged, regression; leaves catch-all mod-overseer#995 |
| wow-overseer#1093 | Dead members go idle as ghosts instead of entering recovery | `stab:deaths` | wow-overseer#1166 |  |
| wow-overseer#116 | wow and wow-dev worldserver init containers carry env from hand kubectl set env runs that  |  | wow-overseer#199 | needs:quadseven |
| wow-overseer#1192 | A roll still ends runs: held tanks are not logged back in, a family leader client stays di | `stab:roll` | wow-overseer#466 |  |
| wow-overseer#1193 | A worldserver roll forgets which travel aims were refused as lethal or unreachable | `stab:roll` | wow-overseer#466 |  |
| wow-overseer#1208 | Health: Bork is stuck: In state 'walking back to the leader' with Grug | `stab:stuck` | wow-overseer#1166 | Health ticket; body labels it gear area |
| wow-overseer#1209 | Health: Grug is stuck: Walking to the vendor for upkeep | `stab:stuck` | wow-overseer#1166 | Health ticket; body labels it gear area |
| wow-overseer#1211 | Health: Bork is stuck: In state 'held off a walk that kept killing... | `stab:stuck` `travel:pathing` | wow-overseer#1166 | Health ticket; body labels it gear area |
| wow-overseer#1219 | Health: Grug is stuck: Working its quests | `stab:stuck` | wow-overseer#1166 | Health ticket; body labels it gear area |
| wow-overseer#1237 | Health: Zug is stuck: Holding still for a member walking back | `stab:stuck` | wow-overseer#1166 |  |
| wow-overseer#124 | wow-stream-agent: clear a resurrect prompt stranded on a living character | `stab:deaths` | mod-overseer#35 | stream agent clears stranded resurrect prompt; needs:quadseven |
| wow-overseer#1298 | Every 'co +flee' is a no-op since roll 65: upstream deleted the flee strategy, and the bri |  | wow-overseer#466 |  |
| wow-overseer#1330 | death_dismiss is wired into a pass, or removed | `stab:deaths` | wow-overseer#466 |  |
| wow-overseer#1368 | A failed index ensure on the module's run-event table cannot stop the bridge's startup |  | wow-overseer#466 |  |
| wow-overseer#1374 | A dungeon job stalls 4 hours with no reason to wait recorded | `dungeon:gnomeregan` `stab:stuck` | wow-overseer#1166 |  |
| wow-overseer#1378 | Complete criteria left from PR #1377 | `dungeon:gnomeregan` `stab:stuck` | wow-overseer#1166 | Follow-up of #1374 (same gnomeregan stall); consider folding into it |
| wow-overseer#529 | Nightly upstream sync: how the job rebases, tests and hands a release to the roller | `stab:roll` | wow-overseer#199 | nightly sync/roll design question |
| wow-overseer#546 | Dev realm: guild members stay offline after a restart (patch 0019 underflows the random-bo | `stab:roll` | wow-overseer#466 |  |
| wow-overseer#590 | Build the realm roller from the approved prototype | `stab:roll` | wow-overseer#199 | Parent is a Goal |
| wow-overseer#743 | A family is never stalled for hours inside a dungeon | `dungeon:shadowfang-keep` `stab:stuck` | wow-overseer#466 | No parent; body says Part of epic #466 |
| wow-overseer#744 | Death loops in zones far above a member's level | `stab:deaths` `zone:searing-gorge` | wow-overseer#466 | No parent; body says Part of epic #466 |
| wow-overseer#789 | A worldserver roll still loses family runs, leftover finder groups, read-backs and the las | `stab:roll` | wow-overseer#466 |  |
| wow-overseer#817 | Bridge restart also resets the borrowed-lead, vendor and banker stall clocks | `stab:roll` `stab:stuck` | wow-overseer#466 | body says Part of #466 |
| wow-overseer#826 | Upgrade core, mod-playerbots, and mod-ollama-chat | `stab:roll` | wow-overseer#199 | core and module upgrade, realm runs what repo says |
| wow-overseer#833 | Profile and cut remaining guildjobs.plan loop time or accept ~3 s |  | wow-overseer#466 | bridge loop performance; could be tooling |
| wow-overseer#868 | Nobody stays stuck: the brain works the stuck list every tick | `stab:stuck` | wow-overseer#1166 | has 7 children and is itself a ticket acting as an epic; currently under 466. Consider con |

### `area:tooling`

| Ticket | Title | Topics | Proposed epic | Note |
|---|---|---|---|---|
| mod-overseer#1065 (epic) | Epic: work that triage, rewrites and health intake find |  | retire (catch-all) |  |
| mod-overseer#1100 (epic) | Epic: work that triage, rewrites and health intake find |  | retire (catch-all) |  |
| mod-overseer#1118 (epic) | Epic: work that triage, rewrites and health intake find |  | retire (catch-all) |  |
| mod-overseer#1134 (epic) | Epic: work that triage, rewrites and health intake find |  | retire (catch-all) | Empty, 0 children |
| mod-overseer#995 (epic) | Epic: work that triage, rewrites and health intake find |  | retire (catch-all) |  |
| wow-overseer#1167 (epic) | Epic: work that triage, rewrites and health intake find |  | retire (catch-all) |  |
| wow-overseer#1247 (epic) | Epic: work that triage, rewrites and health intake find |  | retire (catch-all) |  |
| wow-overseer#1267 (epic) | Epic: work that triage, rewrites and health intake find |  | retire (catch-all) |  |
| wow-overseer#1321 (epic) | Epic: work that triage, rewrites and health intake find |  | retire (catch-all) |  |
| wow-overseer#1347 (epic) | Epic: work that triage, rewrites and health intake find |  | retire (catch-all) |  |
| wow-overseer#1351 (epic) | Epic: work that triage, rewrites and health intake find |  | retire (catch-all) | Parent is the Ragnaros goal #512, unlike the other catch-alls |
| wow-overseer#1359 (epic) | Epic: work that triage, rewrites and health intake find |  | retire (catch-all) |  |
| wow-overseer#1399 (epic) | Epic: work that triage, rewrites and health intake find |  | retire (catch-all) |  |
| wow-overseer#741 (epic) | Epic: deepen the site and bridge modules |  | keep | 0 children via GitHub; checklist-style body |
| mod-overseer#1064 | Goal: Loom or a person works every open quadseven/mod-overseer issue |  | keep (loom:goal, not a ticket or epic) | Loom goal issue, not part of the area scheme; leave unparented |
| mod-overseer#1085 | The module's void-plane quest POI patch differs from the copy that ships |  | NEW: module patch parity with the deploy repo | Quest POI patch drift; CI parity only, no direct player change |
| mod-overseer#1089 | A stalled run records why the dungeon module stopped, not how it exited |  | NEW: run health findings name the real cause | Diagnostic recording for dungeon stalls; could be area:dungeons |
| mod-overseer#1108 | Complete criteria left from PR #1106 | `dungeon:uldaman` | mod-overseer#88 | Log-evidence criteria from PR 1106; says Part of #384 |
| mod-overseer#1113 | C++ unit test for DriveLockpick (follow-up to #445) |  | NEW: module unit test coverage | Follow-up test for #445 DriveLockpick |
| mod-overseer#134 | Lift the session-kind classification into overseer_decisions so it can be tested |  | NEW: Epic: module decisions are testable without a C++ harness |  |
| mod-overseer#574 | Adapter CI builds a different image than the realm runs |  | wow-overseer#199 | CI/realm image pin parity; current parent mod-overseer#575 (stability) does not fit |
| wow-overseer#1157 | Deferred review findings from quadseven/wow-overseer#1156 |  | NEW: review-finding cleanups | Deferred review findings, no parent |
| wow-overseer#1246 | Goal: Loom or a person works every open quadseven/wow-overseer issue |  | NEW: none needed, this is a Goal not a ticket | Goal issue, not an epic; leave out of the epic migration |
| wow-overseer#1271 | Settle the review findings left from PR #1269 |  | NEW: review-finding cleanups for overseer tests |  |
| wow-overseer#1332 | The class-party retry logs its line only after the retry, and success has its own line | `quest:class` | NEW: review-finding cleanups for the bridge | Log-line change only; no player-visible effect |
| wow-overseer#1333 | The newest boss credit query reads an index, not the whole event table |  | NEW: review-finding cleanups for the bridge | DB index change; remove the dungeon:* placeholder topic; could go under #876 if treated as |
| wow-overseer#1334 | The test submodule pins the mod-overseer revision the realm runs |  | wow-overseer#199 |  |
| wow-overseer#1392 | Check ship lock in ROLLS.md before opening roll | `stab:roll` | NEW: Epic: ship and roll process is safe and documented | Docs-only change to ROLLS.md |
| wow-overseer#374 | Add wow-dev audit signal and expand overseer_sample |  | NEW: tooling - audit signals and diagnostics for the playing realm |  |
| wow-overseer#524 | Retire the live and hardcore realms and the Hermes pieces |  | NEW: tooling - retire old realms and Hermes pieces | design question under the goal |
| wow-overseer#733 | Architecture S4: Every GET route in the v2 handler shape, with a narrow context |  | wow-overseer#741 | Refactor of API v2 handlers |
| wow-overseer#736 | Architecture B1: The command queue as one orders module |  | wow-overseer#741 |  |
| wow-overseer#737 | Architecture B3: Family as a value, not cohort=None |  | wow-overseer#741 | No parent; body says part of architecture epic |
| wow-overseer#738 | Deepen dungeon admission as a single decision | `dungeon:deadmines` | wow-overseer#741 | Refactor of dungeon admission; no dungeon-specific topic really applies |
| wow-overseer#739 | Architecture B5: Class quest step executor | `quest:class` | wow-overseer#741 | No parent; body says part of architecture epic |
| wow-overseer#740 | One schema owner and per-concept readers |  | wow-overseer#741 |  |
| wow-overseer#795 | Reads that grow with history: bound them |  | wow-overseer#741 | body says Part of #741 (epic with 0 children listed); read-scan bounding, non-player work |

### `area:professions`

| Ticket | Title | Topics | Proposed epic | Note |
|---|---|---|---|---|
| mod-overseer#514 (epic) | Epic: enchanting for the family - enchant and disenchant | `trade:enchanting` | becomes the trade:enchanting epic | 0 children |
| wow-overseer#19 (epic) | Epic: complete the crafting reagent supply chain |  | keep |  |
| wow-overseer#20 (epic) | Epic: jewelcrafting and inscription coverage for the guild | `trade:inscription` `trade:jewelcrafting` | keep | zero children |
| wow-overseer#21 (epic) | Epic: the family gathers and crafts until every profession is maxed |  | split by trade | 20 children, over the 15 cap; overlaps wow-overseer#468 (professions and crafting system) |
| wow-overseer#468 (epic) | Epic: professions and crafting system |  | retire into per-trade epics (split of #21) |  |
| mod-overseer#1012 | Professions feed the family: bags first, then wanted gear and consumables | `econ:bags` `trade:tailoring` | wow-overseer#21 |  |
| mod-overseer#1094 | TrainOnArrival buys the trainer recipe a roster character's trade needs |  | wow-overseer#21 | Module half of wow-overseer#769; related, not duplicate |
| mod-overseer#1098 | A roster character buys a recipe manual from a vendor and learns it | `econ:vendor` `trade:cooking` `trade:first-aid` | wow-overseer#21 |  |
| mod-overseer#1099 | DriveCraft writes a material-request event when a reagent runs out |  | wow-overseer#19 | Module half of wow-overseer#476 |
| mod-overseer#160 | Find why Og's tailoring slot stays empty after unlearn and enable disenchanting | `trade:enchanting` `trade:tailoring` | mod-overseer#514 |  |
| mod-overseer#444 | Implement DriveEnchant and DriveDisenchant drives | `trade:enchanting` | mod-overseer#514 |  |
| mod-overseer#445 | Implement DriveLockpick for Bork Lockpicking training | `trade:lockpicking` | wow-overseer#21 |  |
| mod-overseer#446 | job='fish': drive the family's Fishing skill via mod-playerbots' own fishing AI (the deploy repo | `trade:fishing` | wow-overseer#21 |  |
| mod-overseer#447 | Fishing rank-up past Apprentice: verify tiers, Artisan vendor, Master quest | `trade:fishing` | wow-overseer#21 |  |
| mod-overseer#524 | Blacksmithing craft-leveling: Anvil+Hammer and dye-dependent recipes need DriveCraft/buy e | `trade:blacksmithing` | wow-overseer#19 |  |
| mod-overseer#530 | [infra] Fishing cannot start: nobody owns a pole, and nothing in the module fishes | `trade:fishing` | wow-overseer#21 | overlaps #446 (fishing job) |
| mod-overseer#533 | [infra] Smelting needs a forge aim: walk a character to a spell-focus GameObject, then sme | `trade:mining` | wow-overseer#21 | smelting is mining/blacksmithing chain |
| mod-overseer#534 | [infra] Cooking needs one cast, not a trainer: light a campfire before the recipe | `trade:cooking` | wow-overseer#21 |  |
| wow-overseer#1108 | Wire secondary trainer rank-up errand + vendor recipe purchase mechanism for First Aid/Coo | `trade:cooking` `trade:first-aid` | wow-overseer#21 | Also overlaps wow-overseer#13 |
| wow-overseer#1116 | Visit trainer to unlock next profession tier when stuck at cap |  | wow-overseer#468 |  |
| wow-overseer#1274 | Engineering blocked at skill 31: verify smelting and bar production | `trade:engineering` `trade:mining` | wow-overseer#19 |  |
| wow-overseer#13 | craft: purchased First Aid/Cooking manuals + secondary trainer rank-up wiring (Silk Bandag | `trade:cooking` `trade:first-aid` | wow-overseer#468 |  |
| wow-overseer#1337 | Write the vendor-manual purchase errand for First Aid and Cooking | `trade:cooking` `trade:first-aid` | wow-overseer#21 |  |
| wow-overseer#16 | Craft supply reagent trip needs protected travel lease |  | wow-overseer#19 | also touches travel lease |
| wow-overseer#37 | wow: Leatherworking craft recipes past skill 45 need vendor-bought thread/dye (craft.py RE | `trade:leatherworking` | wow-overseer#19 |  |
| wow-overseer#39 | [infra] wow: wire Weak Flux / Moss Agate buying into towntrip.py so Engineering's Bronze T | `trade:engineering` | wow-overseer#19 |  |
| wow-overseer#47 | [infra] job='craft' stands down the drives that would produce its own reagents |  | wow-overseer#21 |  |
| wow-overseer#476 | Material acquisition loop emit requests when reagents low |  | wow-overseer#21 | reagent supply chain; #19 also fits |
| wow-overseer#486 | Guild work order system for profession coordination |  | wow-overseer#21 | profession coordination; parent #469 proposed to merge into #194 |
| wow-overseer#51 | [infra] Engineering stops dead at skill 31: nothing in the world produces a Copper Bar | `trade:engineering` `trade:mining` | wow-overseer#21 |  |
| wow-overseer#548 | mod-playerbots: learn trade ranks only from trainers on the bot maps |  | wow-overseer#468 | #468 proposed to merge into #21 |
| wow-overseer#72 | [infra] The gathering destination is chosen but never walked to: no aim is written |  | wow-overseer#21 | gathering walk; also travel |
| wow-overseer#761 | Add cooking ladder and enable raid food production | `raid:prep` `trade:cooking` | wow-overseer#21 | Current parent is a catch-all |
| wow-overseer#769 | Family crafters cannot learn a trainer recipe, so every crafting trade stops between 30 an |  | wow-overseer#468 |  |
| wow-overseer#774 | Blacksmithing, Engineering and Enchanting stop at 75 with no ladder to any raid craft | `trade:blacksmithing` `trade:enchanting` `trade:engineering` | wow-overseer#468 |  |

### `area:economy`

| Ticket | Title | Topics | Proposed epic | Note |
|---|---|---|---|---|
| mod-overseer#517 (epic) | Epic: guild bank item deposit and withdraw | `econ:bank` | keep | could merge into wow-overseer#194 |
| wow-overseer#194 (epic) | Epic: the family keeps its bags, gold and sales moving | `econ:auction` `econ:bags` `econ:vendor` | split: bags / bank and auction / vendors and gold | 18 children, over the 15 cap |
| wow-overseer#469 (epic) | Epic: the guild economy - farming, gold and materials |  | merge into #194's split (economy) |  |
| mod-overseer#148 | Post WTB and WTS in Trade, answer sellers, and complete the trade | `econ:auction` `guild:chat` | wow-overseer#194 |  |
| mod-overseer#496 | BankBuyTab verifies an async write with a sync read, so a successful purchase reports fail | `econ:bank` | mod-overseer#517 |  |
| mod-overseer#684 | Guild bank tabs: witness purchases from memory, deposit into a named tab, and name the tab | `econ:bank` | mod-overseer#517 |  |
| mod-overseer#705 | Keep a reserved item: never sold, given or destroyed, banked below its level and worn agai | `econ:bank` | wow-overseer#194 | Also touches class gear |
| mod-overseer#973 | Seek upgrades in open world: quest rewards, vendors, drops, and bags | `econ:bags` `econ:vendor` | wow-overseer#194 |  |
| mod-overseer#974 | Buy upgrades and consumables on auction house, sell surplus | `econ:auction` `econ:gold` | wow-overseer#194 | Related to wow-overseer#69 and #778, not a clear duplicate |
| wow-overseer#1170 | Gearup: let a gear-short member reach an auction house when the family home has none | `econ:auction` | wow-overseer#194 | No parent |
| wow-overseer#1235 | Verify live throughput and guild bank movement after #4227 | `econ:bank` | wow-overseer#194 |  |
| wow-overseer#1243 | Regression: bag-room hold family returned one hour after #1204 shipped | `econ:bags` `stab:stuck` | wow-overseer#194 | Regression of #1204; current parent #1166 also fits if stuck is treated as the primary are |
| wow-overseer#1261 | Town-errand members wait for a vendor within reach with no timeout | `econ:vendor` `stab:stuck` | wow-overseer#194 |  |
| wow-overseer#1263 | Health: Zug is stuck: Clearing bag space before the dungeon quests | `econ:bags` | wow-overseer#194 | Drop the dungeon:* placeholder; no specific dungeon named |
| wow-overseer#1302 | Health: Zug is stuck: Walking to Auctioneer Grimful in Orgrimmar on a... | `econ:auction` `stab:stuck` `travel:pathing` | wow-overseer#194 |  |
| wow-overseer#1349 | Complete criteria left from PR #1346 | `econ:vendor` `stab:stuck` | wow-overseer#194 | Follow-up to PR #1346; same ground as #1261 |
| wow-overseer#256 | Guild crafting corps: maintenance tailors craft bigger bags for the family | `econ:bags` `trade:tailoring` | wow-overseer#194 |  |
| wow-overseer#321 | Guild corps: run for every family, fetch the Runecloth Bag pattern across maps, post each  | `econ:bags` `trade:leatherworking` | wow-overseer#194 |  |
| wow-overseer#329 | Never ask the world to sell, give, mail or guild-bank an item the operator reserved | `econ:auction` `econ:bank` | wow-overseer#194 |  |
| wow-overseer#333 | Give every guild member a natural job: maintenance farms and gathers, warlocks farm near t | `econ:gold` | wow-overseer#194 |  |
| wow-overseer#527 | Market engine: what does it list, how does it price, and who buys? | `econ:auction` | wow-overseer#194 | design question |
| wow-overseer#540 | Members keep situational sets in the bank and swap them like players | `econ:bank` | wow-overseer#194 |  |
| wow-overseer#625 | Families never buy bank bag slots or craft bags | `econ:bags` `econ:bank` | wow-overseer#194 |  |
| wow-overseer#69 | [infra] Nothing ever lists family items for sale on the auction house | `econ:auction` | wow-overseer#194 |  |
| wow-overseer#747 | Implement guild bank demand forecasting and surplus selling | `econ:auction` `econ:bank` | wow-overseer#469 | Current parent is a catch-all |
| wow-overseer#778 | The auction house has no buyers and no seller; fix routing to empty house | `econ:auction` | wow-overseer#194 |  |
| wow-overseer#791 | Guild bank withdraw and class training go live together | `class:training` `econ:bank` | wow-overseer#469 | body says Part of #469; touches class training too |
| wow-overseer#8 | [infra] Verify live: town errand throughput actually rises, and guild_bank_item finally mo | `econ:bank` `econ:gold` | wow-overseer#194 | live-check ticket; guild_bank_item |
| wow-overseer#872 | A member waits 9 hours for a banker | `stab:stuck` | wow-overseer#868 | banker wait; fits stuck epic |
| wow-overseer#885 | A bigger spare bag is put on even when the biggest one sits inside a small worn pouch | `econ:bags` | wow-overseer#194 |  |
| wow-overseer#886 | A campaign withheld at the bag floor gives its family's time back to crafting | `econ:bags` | wow-overseer#194 | bag floor vs crafting; may be professions |

### `area:guild`

| Ticket | Title | Topics | Proposed epic | Note |
|---|---|---|---|---|
| mod-overseer#46 (epic) | Epic: WoW overseer - command, observe, and converse with the world | `guild:chat` | reads as a goal; its children move to area epics | 48 children, far over the 15 cap; needs splitting by area |
| wow-overseer#197 (epic) | Epic: the decree console can found and run a guild | `guild:social` | keep |  |
| wow-overseer#200 (epic) | Epic: bots talk through the local LLM, verified in game | `guild:chat` | keep |  |
| wow-overseer#22 (epic) | Epic: roster cohorts let Bonkers share Cave's automation safely |  | keep |  |
| wow-overseer#483 (epic) | Epic: social guild systems for helping, grouping and coordination | `guild:social` | keep |  |
| mod-overseer#1104 | Complete criteria left from PR #1095 | `guild:chat` `guild:social` | wow-overseer#483 | Leftover criteria from PR 1095 (kin history, council/reflection) |
| mod-overseer#150 | Discord orders to roster jobs via LLM | `guild:chat` | wow-overseer#200 |  |
| mod-overseer#179 | Verify group buff rebuff live check on dev realm | `guild:runs` | NEW: group buffs and party upkeep verified live | live-check ticket |
| mod-overseer#22 | Verify no self-echo whisper rows | `guild:chat` | wow-overseer#200 | Verification-only ticket waiting on whisper data |
| mod-overseer#269 | Add party and raid addon channels | `guild:chat` | wow-overseer#483 |  |
| mod-overseer#31 | Verify jealousy rule with separated council history | `guild:social` | wow-overseer#483 | Verification-only; code already merged |
| mod-overseer#7 | Fan-out commands: guilds, factions and conjured events | `guild:social` | wow-overseer#483 |  |
| wow-overseer#1173 | Mirror the guild petitioner travel role in travel.ROLES at the next mod-overseer bump |  | wow-overseer#197 | Bridge mirror of petitioner travel role for guild founding |
| wow-overseer#131 | mod-ollama-chat: confirm a real in-game bot reply | `guild:chat` | wow-overseer#200 |  |
| wow-overseer#347 | In-game ear reads the family's own bot speech as operator orders (reset ai, follow, stay) | `guild:chat` | wow-overseer#200 |  |
| wow-overseer#484 | Cross-party buff producer: kind=cast producer missing | `guild:social` | wow-overseer#483 |  |
| wow-overseer#485 | Carry/boost mode: powerleveling does not exist | `guild:social` | wow-overseer#483 |  |
| wow-overseer#535 | Recruit every bot guild toward 71 members (40 raiders, 21 summoners, 10 maintenance) | `guild:social` | wow-overseer#483 |  |
| wow-overseer#547 | Guild coordinator slice 1 live proof and Guild tab verification | `guild:runs` | wow-overseer#483 |  |
| wow-overseer#571 | Play sessions: bots log off and on like people | `guild:social` | wow-overseer#483 | Parent is a Goal, not an epic |
| wow-overseer#584 | Jev and door records drive the social layer's choices, and Jev learns from outcomes | `guild:runs` `guild:social` | wow-overseer#483 | Parent is a Goal |
| wow-overseer#618 | The guild coordinator runs any guild, not only Cave and Bonkers | `guild:runs` | wow-overseer#197 | Parent is a Goal |
| wow-overseer#619 | Bot guilds recruit and advertise like players | `guild:social` | wow-overseer#483 | Parent is a Goal |
| wow-overseer#820 | Jev scorecard: history, quality, cost and a recommendation on the decision model | `guild:chat` | wow-overseer#200 | Jev decision model scorecard; body says Part of #466 |
| wow-overseer#821 | Decision backends behind jev.ask: Clef, OpenAI, compare mode | `guild:chat` | wow-overseer#200 |  |
| wow-overseer#822 | Strands Decider 2B as a local decision backend | `guild:chat` | wow-overseer#200 |  |
| wow-overseer#88 | Map: the overseer runs a guild-scale goal stated in plain language | `guild:runs` | NEW: the overseer runs guild-scale goals stated in plain language | wayfinder Map with 8 children, not an Epic by title/label; needs its own epic or goal |
| wow-overseer#9 | [infra] Nothing can found a guild - Bonkers needs a charter-signing automation that does n | `guild:social` | wow-overseer#197 |  |
| wow-overseer#94 | What is a goal: schema and completion predicates? | `guild:runs` | NEW: the overseer runs guild-scale goals stated in plain language | parent is a Map, not an epic |

### `area:travel`

| Ticket | Title | Topics | Proposed epic | Note |
|---|---|---|---|---|
| mod-overseer#469 (epic) | Epic: the world is one map - inter-continent travel, transport, summons | `travel:crossing` | merge into mod-overseer#513 (cross-continent travel) | overlaps mod#513 and wow#196; four travel epics |
| mod-overseer#513 (epic) | Epic: cross-continent travel for the family via boat or portal | `travel:crossing` | keep | keep as the single crossing epic; merge mod#469 and wow#196 overlap here or into wow#196 |
| mod-overseer#518 (epic) | Epic: the family can reliably reach where it is sent | `travel:pathing` | split: pathing / crossings | 20 children, over the 15 cap; split |
| wow-overseer#196 (epic) | Epic: any character can be sent anywhere and gets there | `travel:crossing` | keep | one of four travel epics; consider merge with mod-overseer#518/#469/#513 |
| mod-overseer#1029 | The crossing catalogue skips a transport on one map, so ride-to-stop never prices the Unde | `travel:crossing` `zone:undercity` | mod-overseer#518 |  |
| mod-overseer#274 | Nothing walks a character onto a boat, family split permanent | `travel:crossing` | mod-overseer#469 |  |
| mod-overseer#279 | The crossing cannot board anybody: a transport stop frame is the ship's mooring, not a pie | `travel:crossing` | mod-overseer#469 |  |
| mod-overseer#398 | Live-verify named NPC travel after PR #415 | `travel:pathing` | mod-overseer#518 |  |
| mod-overseer#410 | Add use-portal verb and StrandedWay portal decision rule | `travel:crossing` | mod-overseer#469 |  |
| mod-overseer#502 | A planned foot route runs through a level 50 rare elite's spawn, and the guarded-ground ch | `travel:pathing` | mod-overseer#518 |  |
| mod-overseer#542 | [infra] Verify live: the flight-master caller actually learns a node | `travel:crossing` | mod-overseer#518 | Live-check ticket for the deploy repo flight-master learn |
| mod-overseer#544 | [infra] The 'petitioner' travel keyword can resolve to an Arena Organizer instead of a Gui | `travel:pathing` | mod-overseer#518 |  |
| mod-overseer#560 | A catch-up walk refused by a follower's profession errand is logged as started, and the fa | `travel:pathing` | mod-overseer#518 | Has no parent today |
| mod-overseer#70 | Followers can fall behind a travelling leader and stop, and never close the gap | `travel:pathing` | mod-overseer#518 |  |
| mod-overseer#722 | One movement owner per family leader: intent book, windowed stuck detection, no leaked sta | `travel:pathing` | mod-overseer#518 | needs:quadseven label; Part of #548 in body |
| mod-overseer#758 | Fix leader boarding failure on Lady Mehley transport | `travel:crossing` | mod-overseer#518 | needs:quadseven; verifies PRs for #739 crossing fix |
| mod-overseer#765 | The classic-world check reads the blood elf and draenei starting isles as Outland, so 42 g | `zone:azuremyst-isle` `zone:eversong-woods` | mod-overseer#518 | Also stalls levelling |
| mod-overseer#836 | Family town runs walk Gnomeregan to Stormwind through Burning Steppes and die | `stab:deaths` `travel:pathing` `zone:burning-steppes` | mod-overseer#518 | Has no parent today |
| mod-overseer#925 | A route's first survey node is on the character's own floor, not on a roof above it | `travel:pathing` `zone:stormwind` | mod-overseer#518 | Shipped; leaves catch-all mod-overseer#995 |
| mod-overseer#926 | A campaign crossing that makes no progress hands the dungeon back instead of walking forev | `travel:crossing` | mod-overseer#518 | Shipped; leaves catch-all mod-overseer#995 |
| mod-overseer#970 | Flight points are learned but never used, so every trip is still a long walk | `travel:pathing` | mod-overseer#518 |  |
| wow-overseer#1401 | A member crossing out of Teldrassil walks into the sea and drowns, about once a minute | `travel:crossing` `zone:teldrassil` | wow-overseer#196 | Also deaths (stab:deaths) |
| wow-overseer#1420 | A bag-room town errand sends a family across the sea to its hearth when its dungeon is on  | `dungeon:razorfen-downs` `econ:bags` `travel:crossing` | wow-overseer#196 | No parent today |
| wow-overseer#603 | An honor buyer crosses to the vendor's continent | `travel:crossing` | wow-overseer#196 | No parent; also touches PvP gear |
| wow-overseer#75 | gather does not hold column it wins | `travel:pathing` | mod-overseer#518 |  |
| wow-overseer#76 | [infra] gatheraim picks a field 2x further than one lease can reach, so the walk can never | `travel:pathing` | mod-overseer#518 | related to #75 and gather lease, not a duplicate |
| wow-overseer#779 | Guild members learn riding and buy mounts |  | wow-overseer#196 | riding and mounts; could be economy (mount purchase) but player notices faster travel |
| wow-overseer#815 | Crossings: survey the Draenei isle berth, ride the zeppelin, release held rows | `travel:crossing` | wow-overseer#196 |  |
| wow-overseer#870 | A walk to the Menethil Harbor docks restarted 309 times and never arrived | `stab:stuck` `travel:pathing` `zone:wetlands` | wow-overseer#868 |  |

### `area:raids`

| Ticket | Title | Topics | Proposed epic | Note |
|---|---|---|---|---|
| wow-overseer#470 (epic) | Epic: pre-raid preparation - fire resistance, consumables, attunements | `raid:prep` | keep |  |
| mod-overseer#538 | [wow] pre-raid logistics backlog: attunements, world buffs, tribute runs, portal/summon ne | `raid:onyxia` `raid:prep` | wow-overseer#470 | Current parent mod-overseer#515 (talents) does not fit; blocked on steerable-roster limit |
| mod-overseer#919 | Goal: the module side of the Ragnaros one-shot (Loom) | `raid:molten-core` | NEW: Ragnaros one-shot module work (goal issue, loom:goal, 18 children; not an e | Goal home issue, neither epic nor ticket; keep as a goal |
| mod-overseer#922 | Raid stragglers are summoned with the Blackrock Mountain meeting stone by seats already at | `raid:molten-core` `raid:prep` | wow-overseer#470 | Shipped, wait:live-event; leaves catch-all mod-overseer#995 |
| mod-overseer#923 | A raid repairs before the order and checks durability before Ragnaros | `raid:molten-core` `raid:prep` | wow-overseer#470 | Shipped; leaves catch-all mod-overseer#995 |
| wow-overseer#1307 | Verify raid prep live check and confirm proof | `raid:prep` | wow-overseer#470 |  |
| wow-overseer#269 | Get Cave ready for Molten Core: readiness, attunement path, and raid formation | `raid:molten-core` `raid:prep` | wow-overseer#470 |  |
| wow-overseer#479 | connect raidcraft.py plans to actual bot tasks | `raid:prep` | wow-overseer#470 |  |
| wow-overseer#480 | Dark Iron pipeline: plans, rep grind, Black Forge/Anvil | `raid:prep` `trade:blacksmithing` | wow-overseer#470 |  |
| wow-overseer#481 | Cloak enchant executor for other characters | `raid:prep` `trade:enchanting` | wow-overseer#470 |  |
| wow-overseer#512 | Goal: our guild one-shots Ragnaros on wow-dev, naturally | `raid:molten-core` | NEW: none - this is a Goal, not an epic | Goal issue, not epic; give it area:raids |
| wow-overseer#534 | Remove the free world and flask buffs from raids | `raid:prep` | wow-overseer#470 |  |
| wow-overseer#542 | Raid seats by pre-raid readiness, not item level | `raid:molten-core` `raid:prep` | wow-overseer#470 |  |
| wow-overseer#57 | [wow] proposal: a 'raid prep' job mode  -  the raid-readiness program the family is headin | `raid:prep` | wow-overseer#470 |  |
| wow-overseer#620 | Other raid guilds wait for Cave or Bonkers to kill Ragnaros first | `guild:runs` `raid:molten-core` | wow-overseer#195 | Parent is a Goal |
| wow-overseer#621 | A realm world buff calendar: heads turned in at announced times, guilds gather | `guild:social` `raid:prep` | wow-overseer#470 | Parent is a Goal |
| wow-overseer#684 | Raid lineup composition by encounter and buff scope | `raid:molten-core` `raid:prep` | wow-overseer#195 | Current parent is a catch-all |
| wow-overseer#759 | Tank fire resistance has no road: the fire resistance sets are read by nothing | `raid:molten-core` `raid:prep` | wow-overseer#470 | No parent |
| wow-overseer#760 | Extend pre-raid gear planning to all seated raiders | `class:gear` `raid:prep` | wow-overseer#470 | Current parent is a catch-all |
| wow-overseer#762 | Molten Core raid summon order decision and Blackrock Mountain stone addition | `raid:molten-core` `travel:crossing` | wow-overseer#195 | Current parent is a catch-all |
| wow-overseer#763 | Raid repairs: Field Repair Bot 74A has no source on this realm, and no repair walk is plan | `raid:molten-core` `raid:prep` `trade:engineering` | wow-overseer#470 | No parent |
| wow-overseer#765 | Raid run: bring every seated raider to the Molten Core door, not only the head | `raid:molten-core` `travel:pathing` | wow-overseer#195 | Current parent #467 is dungeons-to-60; raid work fits #195 better |
| wow-overseer#766 | Ragnaros: knockback return order, Magma Blast, Lava Burst spacing and the Sons of Flame fo | `raid:molten-core` | wow-overseer#195 | Current parent #467 is dungeons-to-60; #467 and #195 overlap and should be merged |
| wow-overseer#767 | Majordomo Executus: casters hold on reflection shields, healers die first, tanks re-take a | `raid:molten-core` | wow-overseer#195 | Current parent #467 is dungeons-to-60; #467 and #195 overlap |
| wow-overseer#770 | Garr: one tank per Firesworn inside 40 yards, banishes, and one add at a time | `raid:molten-core` | wow-overseer#470 | Garr is Molten Core; currently under dungeon epic |
| wow-overseer#891 | The raid page projects when each guild's alchemist reaches the raid ranks | `raid:prep` `trade:alchemy` | wow-overseer#470 |  |
| wow-overseer#892 | Raid supply makes Fire Protection Potions from the vendor recipe until the Greater recipe  | `raid:prep` `trade:alchemy` | wow-overseer#470 |  |
| wow-overseer#893 | Guild runs at 52 and up prefer a dungeon that drops a raid recipe nobody in the guild know | `raid:prep` | wow-overseer#470 |  |

### `area:questing`

| Ticket | Title | Topics | Proposed epic | Note |
|---|---|---|---|---|
| wow-overseer#922 (epic) | Epic: two questing groups prove every quest works, on a Quests page |  | keep |  |
| mod-overseer#180 | Verify completed quest hand-in and aim stability after merged fix |  | wow-overseer#922 |  |
| mod-overseer#19 | wow: a quest with no creature_questender can never be turned in, and looks like every othe |  | wow-overseer#922 |  |
| mod-overseer#21 | Goal supervisor: drive a character to a level target |  | wow-overseer#922 | Level-goal supervisor; also covers profession goals; has live-check box |
| mod-overseer#969 | Stop retrying share requests refused for durable reasons (backoff/give-up) |  | wow-overseer#922 |  |
| wow-overseer#1085 | A quester's complete quest is turned in, not sent an abandon the module refuses every 2 mi |  | wow-overseer#922 |  |
| wow-overseer#1094 | Overleveled members solo class quests instead of waiting for help | `quest:class` | wow-overseer#1166 | Current parent #868 is not an open epic |
| wow-overseer#1107 | Health: Clobba is stuck: Class quest: Redemption | `quest:class` | wow-overseer#1166 |  |
| wow-overseer#1140 | A done Binding use restarts the class hunt's stall clock | `quest:class` | wow-overseer#1166 | No parent |
| wow-overseer#1222 | Health: Ezzo is stuck: Class quest: Call of Water | `quest:class` | wow-overseer#1166 |  |
| wow-overseer#1294 | A quester hands in a complete quest the world keeps refusing every two minutes, forever |  | wow-overseer#922 |  |
| wow-overseer#1295 | Questers re-ask a refused far walk every pass: budget, held and far-above-road refusals ar | `travel:pathing` | wow-overseer#922 |  |
| wow-overseer#1297 | Questers re-walk every 2 minutes to a giver whose road the module refuses as lethal | `travel:pathing` | wow-overseer#922 |  |
| wow-overseer#1331 | A far-walk wait holds only far walks, not a nearby hand-in | `travel:pathing` | wow-overseer#922 |  |
| wow-overseer#1345 | Health: Hrunt is stuck: Class quest: Surena Caledon | `quest:class` | wow-overseer#922 |  |
| wow-overseer#1367 | The class quest comes before the make-room step for an equip upgrade again | `quest:class` | NEW: Epic: class quests come first for every member |  |
| wow-overseer#1375 | The queue pass clears the quest aim of a family the bag hold sent questing | `econ:bags` | NEW: Epic: class quests come first for every member | No parent today; touches bag hold and quest aim |
| wow-overseer#678 | Add death knight to class quest book to free Brug from starting zone | `class:training` `quest:class` | wow-overseer#922 | Current parent is a catch-all |
| wow-overseer#781 | Class quests ahead that no member can finish: tame, totems, Redemption, Berserker Stance,  | `quest:class` | wow-overseer#922 | currently under stability epic |
| wow-overseer#871 | Class quest help asks go unanswered for a day (56 asks, nobody came) | `quest:class` `stab:stuck` | wow-overseer#868 |  |
| wow-overseer#887 | A class quest help ask is posted only when a party can form for it; otherwise the quest yi | `quest:class` | wow-overseer#1166 |  |
| wow-overseer#888 | Class quest helpers come from across the continent and meet at the objective before the pa | `quest:class` | wow-overseer#1166 |  |
| wow-overseer#926 | Each broken quest becomes a ticket under the questers epic |  | wow-overseer#922 |  |

### `area:class`

| Ticket | Title | Topics | Proposed epic | Note |
|---|---|---|---|---|
| mod-overseer#515 (epic) | Epic: talent builds and raid role assignment for the family | `class:talents` | keep |  |
| mod-overseer#221 | Two systems equip the family and disagree: 923 equips across 12 slots, and 7 better items  | `class:gear` | NEW: the family equips the best gear it owns |  |
| mod-overseer#731 | Apply talent points based on raid seat requirements | `class:talents` | mod-overseer#515 | Moves out of catch-all mod-overseer#1100; blocked:progression |
| mod-overseer#965 | Family travels to class trainers on levelup instead of learning spells in place | `class:training` `quest:class` | NEW: class trainers are visited on levelup |  |
| mod-overseer#967 | tank warrior spams unaffordable ranged abilities when locked out of melee |  | NEW: class AI fixes for tank, healer and caster roles |  |
| wow-overseer#1005 | An equip hold names its real retry time and lifts when it passes | `class:gear` | NEW: gear has one owner and equips land |  |
| wow-overseer#1088 | Health: Gorvash is stuck: Trying to wear Burnt Buckler | `class:gear` | NEW: gear has one owner and equips land | Health ticket; body labels it gear area |
| wow-overseer#1319 | Families train affordable class spells and raise their trades | `class:training` `trade:blacksmithing` `trade:first-aid` `trade:mining` | NEW: families train class spells and raise trades on time | No parent today |
| wow-overseer#1389 | Trainer backoff: three short-lived endings still double the wait, and the passing list is  | `class:training` | NEW: Epic: class training ranks arrive on time |  |
| wow-overseer#399 | Send member to weapon master for unlearned carried weapon skill | `class:training` | NEW: class training - trainers, weapon skills, talents and gear |  |
| wow-overseer#550 | Tank-spec warriors and paladins carry and wear a shield | `class:gear` | NEW: class training - trainers, weapon skills, talents and gear |  |
| wow-overseer#589 | PvP for upgrades: members queue battlegrounds when their next upgrade is PvP gear | `class:gear` | NEW: PvP gear upgrades through battlegrounds | Parent is a Goal |
| wow-overseer#771 | Implement member purchase order to prioritize class spells over other costs | `class:training` | NEW: class spell training and gear for guild members |  |
| wow-overseer#792 | Class training gaps left after #752 | `class:training` | NEW: class spell training and gear for guild members | currently under dungeon epic |
| wow-overseer#793 | Members wear the upgrades they carry | `class:gear` | NEW: class spell training and gear for guild members | currently under dungeon epic |
| wow-overseer#896 | The family equip pass leaves roster members to the module's gear drive | `class:gear` | NEW: gear has one owner and equips land |  |
| wow-overseer#897 | A piece the world refused with a reason is held on that reason until the member's level or | `class:gear` | NEW: gear has one owner and equips land |  |

### `area:site`

| Ticket | Title | Topics | Proposed epic | Note |
|---|---|---|---|---|
| wow-overseer#198 (epic) | Epic: the public site shows each realm honestly |  | keep |  |
| wow-overseer#557 (epic) | Epic: a mobile-first overseer site with navigation and gear tooltips |  | keep |  |
| wow-overseer#748 (epic) | Epic: the overseer app has flagship polish and no ambiguity |  | keep | Overlaps #557 and #198 on site work; consider merging later |
| wow-overseer#876 (epic) | Epic: everything the overseer knows is readable over REST and a CLI |  | keep |  |
| wow-overseer#102 | Map: get WoW clients off the operator's daily driver, to two POV streams |  | NEW: two POV streams without taking the operator's desktop | wayfinder Map with 12 children, not an Epic by title/label |
| wow-overseer#103 | POV streams have no audio at all: the encoder captures a window and no sound |  | NEW: two POV streams without taking the operator's desktop | parent is a Map, not an epic |
| wow-overseer#1314 | A family clearing a dungeon is not called stuck while its bosses fall |  | wow-overseer#748 | Members page wording; touches dungeons and stuck |
| wow-overseer#1317 | Gear changes show item tooltips and what each change did to the character's stats |  | wow-overseer#557 |  |
| wow-overseer#1318 | Class trainer spells show names and links, not ids | `class:training` | wow-overseer#748 |  |
| wow-overseer#1386 | The bridge says which commit it runs, and the dashboard shows the deployed commit and a ro |  | wow-overseer#557 | Overlaps #1395 (deploy marker) |
| wow-overseer#1395 | Deploy marker: report the bridge's own uptime, show restarting when the site stops answeri |  | wow-overseer#557 | Overlaps #1386 |
| wow-overseer#177 | Watch wall: read party and raid chat aloud | `guild:chat` | wow-overseer#557 | currently under a catch-all epic |
| wow-overseer#259 | Virtual game client overlay on the Watch streams |  | wow-overseer#557 | currently under #198 which is about realm honesty |
| wow-overseer#562 | Verify the site at desktop widths after navigation and tooltip changes |  | wow-overseer#557 |  |
| wow-overseer#570 | Guild chat feed on the site: asks, answers and the runs they became | `guild:chat` | wow-overseer#748 | Parent is a Goal, not an epic |

