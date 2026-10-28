# A realm world buff calendar

Research note for issue #621. It decides which world buffs a raid guild on
this realm can take, who holds a head until its announced turn-in time, how
that time is announced, where the guild gathers, and how it then reaches the
raid before the buffs fade. It ships no code; the build tickets at the end are
for the brain to brief.

## Decisions at a glance

Each line is argued in full in the section it names.

- Who holds the head: the guild leader, until the announced turn-in time.
  The loot master gives them the head at the kill (operator decision,
  2026-10-26). Natural kills only, no granted buffs.
- How the time is announced (see "How a turn-in time is announced"): the
  holder says it in guild chat at raid set, T-30 and T-5. They say it in the
  faction's public `lfg` channel at T-15 and T-2, because this realm has no
  separate world channel. The site's Raid tab is the calendar. T is
  the raid's door time minus the route time: 12 to 18 min for the Horde,
  7 to 16 min for the Alliance.
- Where the guild gathers (see "Where the guild gathers"): within 100 yd of
  Overlord Runthak in Orgrimmar (Horde) or Field Marshal Afrasiabi in
  Stormwind (Alliance), opening 10 min before T. For Zandalar they gather by
  Molthor on Yojamba Isle, for Songflower at a Felwood songflower, and for
  the Dire Maul buffs inside Dire Maul North. The table there gives the
  travel time to each spot.
- How the raid reaches the door before the buffs fade (see "Reaching the
  raid before the buffs fade"): the whole raid travels together by flight,
  zeppelin or boat, and on mounts. The Horde reaches the Blackrock Mountain
  doors at T+18 (T+12 without a heart), the Alliance at T+16 (T+7 without
  one). The shortest buff left at the door is Songflower, with 31 min or more.

## Rules this note keeps

- The guild leader holds the head until the announced turn-in time (operator
  decision, 2026-10-26). The raid's loot master gives the head to the guild
  leader at the kill, because the head binds on pickup and cannot be traded
  later; at the announced time the leader walks it to the turn-in NPC.
- Natural kills only. Every buff below comes from a real kill and a real quest
  turn-in, gossip or object click. Nothing is granted by script, by GM command
  or by an Overseer-side cast.
- The classic ruleset (`classic.py`): level at most 60, Eastern Kingdoms,
  Kalimdor and the classic instances only.

## Where the numbers come from

Every id, row and coordinate below was read on 2026-10-28, and nothing was
taken from a guide:

- The realm's world database (`acore_world`), read-only SELECTs on the dev
  realm. The live realm's database returned the same quest and script rows
  (`quest_template`, `smart_scripts`, the quest starter and ender tables).
- The worldserver's own DBC files (`Spell.dbc`, `SpellDuration.dbc`,
  `SpellRadius.dbc`, `TaxiNodes.dbc`, `TaxiPath.dbc`, `TaxiPathNode.dbc`), copied
  out of the running worldserver the way `tools/spell_bands_from_dbc.py` says.
- The pinned core source (`UPSTREAM-PINS.env`, `AC_CORE_SHA`), but only where a
  buff is cast by C++ rather than by a database row: `npc_thrall_warchief` in
  `src/server/scripts/Kalimdor/zone_orgrimmar.cpp`, and `PLAYER_FLIGHT_SPEED` in
  `src/server/game/Movement/MovementGenerators/WaypointMovementGenerator.cpp`.

## The buffs

Duration is from `SpellDuration.dbc`. "Level cap" is a `conditions` row
(type 27, level 63 or lower); a buff with no such row has no cap in the
database. Under the classic ruleset no character is above 60, so the caps
never bite here.

| Buff | Spell | Lasts | Source | Works here? |
|---|---|---|---|---|
| Warchief's Blessing | 16609 | 60 min | Head of Rend Blackhand | Yes, Horde only |
| Rallying Cry of the Dragonslayer (Nefarian) | 22888 | 120 min | Head of Nefarian | Yes, both factions |
| Rallying Cry of the Dragonslayer (Onyxia) | 22888 | 120 min | Head of Onyxia | No |
| Songflower Serenade | 15366 | 60 min | Cenarion Plant Salve at a Corrupted Songflower | Yes, both factions |
| Fengus' Ferocity | 22817 | 120 min | Dire Maul North tribute | Yes, both factions |
| Mol'dar's Moxie | 22818 | 120 min | Dire Maul North tribute | Yes, both factions |
| Slip'kik's Savvy | 22820 | 120 min | Dire Maul North tribute | Yes, both factions |
| Spirit of Zandalar | 24425 | 120 min | Heart of Hakkar | Yes, both factions |

### Warchief's Blessing (Rend Blackhand, Upper Blackrock Spire)

- Item: Head of Rend Blackhand, 12630. It drops from Warchief Rend Blackhand
  (creature 10429, Upper Blackrock Spire, map 229) at 100% with
  `QuestRequired = 1`. It is a quest item (bonding 4), so it is not a
  loot-master item: every Horde raider with quest 4974 in their log loots
  their own head.
- Quest: For The Horde! (4974), Horde races only, started and ended by Thrall
  (4949, Grommash Hold, Orgrimmar). It follows quest 4941 and is not
  repeatable (`SpecialFlags` 0), so each character can turn it in once.
- The cast: Thrall's C++ script (`npc_thrall_warchief::OnQuestReward`)
  summons the Herald of Thrall (10719) and, 9 s after the reward, casts 16609
  around Thrall (100 yd) and on every living player in the Orgrimmar area.
  Ten seconds later it casts it on every living player in the Crossroads.
- Conditions on 16609: Horde, at least Friendly with Orgrimmar, level 63 or
  lower.
- Alliance: no Alliance turn-in exists, so the Alliance gets no Warchief's
  Blessing.
- How the operator's decision applies: the head is not handed out by the loot
  master, but the guild leader still holds one, the head they looted
  themselves, if they carry 4974. The item has no duration (`duration` 0), so
  the leader can keep it until the announced time.

### Rallying Cry of the Dragonslayer from Nefarian (Blackwing Lair)

- Items: Head of Nefarian, 19003 (Alliance, starts 7781) and 19002 (Horde,
  starts 7783). Nefarian (11583) drops it at 100%. It binds on pickup
  (bonding 1), has no duration and a `maxcount` of 1. This is the head the
  operator's decision is about: the loot master gives it to the guild leader.
- Horde: 7783 is turned in to Thrall (4949). Its follow-up 7784 is started by
  Thrall and turned in to Overlord Runthak (14392, the Valley of Strength in
  Orgrimmar). Runthak's SmartAI (`smart_scripts` 14392 id 3, action list
  1439201) shows the head (gameobject 179881) and casts 22888 about 24 s after
  the reward.
- Alliance: 7781 is turned in to King Varian Wrynn (29611, Stormwind Keep). Its
  follow-up 7782 is started by Varian or Highlord Bolvar Fordragon (1748) and
  turned in to Field Marshal Afrasiabi (14721, Valley of Heroes, Stormwind).
  His action list 1472100 shows the head (179882) and casts 22888 about 24 s
  after the reward.
- Reach: 22888 targets allies within 100 yd of the caster
  (`SpellRadius.dbc`, implicit targets 22/30). No `conditions` row caps it.
- Neither 7781 to 7784 is repeatable, so each character can turn a Nefarian
  head in once.

### Rallying Cry from Onyxia: does not work here

- Onyxia (10184) is a level 83 raid here, and the classic ruleset already
  excludes her.
- More to the point, her loot no longer carries the classic heads. Her loot
  table holds 49643 and 49644 (Head of Onyxia), which start quests 24429 and
  24428, "A Most Puzzling Circumstance". Those end at Neeru Fireblade (3216)
  and Zardeth of the Black Claw (1435), and no script on either casts a buff.
- The classic heads 18422 and 18423 are in no loot table. Their quests 7490
  and 7495 have no quest ender, so the chains to For All To See (7491,
  Runthak, gameobject 179556) and Celebrating Good Times (7496, Major
  Mattingly 14394, gameobject 179558) can never start. Their scripts are in
  the database but cannot be reached.

### Songflower Serenade (Felwood)

- Quest: Corrupted Songflower. There are ten quest ids (2523, 2878, 3363, 4113,
  4114, 4116, 4118, 4401, 4464, 4465), each started and ended by its own
  Corrupted Songflower gameobject (164886, 171939, 171942, 174594 to 174598,
  174712, 174713). All of them are repeatable (`SpecialFlags` 257) and need one
  Cenarion Plant Salve (11516).
- The cast: on the reward, the Corrupted Songflower's SmartAI summons a
  Cleansed Songflower (164882) for 30 s and despawns itself. The cleansed
  flower is a goober whose `Data10` is 15366, so each player who clicks it
  casts Songflower Serenade on themselves (implicit target 21, single ally).
- Nine of the ten corrupted flowers are spawned, all in Felwood, each with a
  180 s respawn.
- Salve: the repeatable "Salve via Hunting / Mining / Gathering / Skinning /
  Disenchanting" quests (4108 to 4112 from Arathandris Silversky 9528, 5887 to
  5891 from Maybess Riverbreeze 9529) give two salves each.
- No head and no holder: whoever carries a salve can turn it in. No
  `conditions` row caps 15366.
- Unread: whether one cleansed flower serves more than one clicker in its
  30 s. The rows do not say, so a build ticket below measures it.

### The Dire Maul tribute buffs (Dire Maul North, map 429)

- The guards are Guard Fengus (14321), Guard Slip'kik (14323) and Guard
  Mol'dar (14326). Each casts its buff on the player who picks gossip option 0
  of its menu: Fengus menu 5734 casts 22817, Slip'kik 5733 casts 22820,
  Mol'dar 5735 casts 22818 (SmartAI event 62).
- The option shows only if the player lacks that aura and is level 63 or
  lower (`conditions` source 15). The tribute itself is natural: a guard who
  dies sets instance data 4, and King Gordok (11501) summons Mizzle the Crafty
  (14353) on death.
- Who gets it: anyone inside that Dire Maul North instance with the guards
  still alive. Dire Maul is a five-player dungeon, so a 40-seat raid group
  cannot enter it. A tribute party of five clears it, and raiders then take
  turns in the party leader's party to zone in, talk to the three guards and
  leave.

### Spirit of Zandalar (Zul'Gurub)

- Item: Heart of Hakkar, 19802. Hakkar (14834, Zul'Gurub, map 309) drops it at
  100%. It binds on pickup, has no duration and a `maxcount` of 1, so the
  loot master gives it to the guild leader like a Nefarian head.
- Quest: The Heart of Hakkar (8183), both factions, started by the heart and
  turned in to Molthor (14875, Yojamba Isle, Stranglethorn Vale). It is not
  repeatable.
- The cast: Molthor walks to waypoint 12 and runs action list 1487500. It
  casts 24425 36 s into the script (SmartAI target type 17, players in range),
  and the spell reaches allies within 100 yd. On the reward he also sets data on the Zandalarian
  Emissary (15076, creature guid 436, in Booty Bay), who casts 24425 50 s
  later.
- Conditions on 24425: level 63 or lower.

## The holder, and a gap in the decision

The rows bear out the operator's decision, but they add one constraint the
decision does not cover. Every head quest here (4974, 7781 to 7784, 8183) can
be completed once per character, and each head has a `maxcount` of 1. After
the guild leader has turned in a Nefarian head once, the next Nefarian head
given to them can never start its quest: it is dead in their bags. It also
blocks them from looting another one.

This note does not change the decision. It flags this for the operator: who
holds the second head, when the guild leader's own quest is done? A natural
answer would be the highest-ranked officer whose quest is not done. The build
ticket that hands the head out must wait for that answer before it covers the
second kill.

## How a turn-in time is announced

The holder announces it, as a player would. Overseer only decides the time
and which lines to say. Three surfaces, each already used for a different
purpose:

1. Guild chat, by the holder. This is the same mechanism `guildsocial.py`
   uses for asks. One line when the raid night is set, and one at 30 min and
   at 5 min before the time: the buff, the time in server time and the place
   ("Rallying Cry at 20:45 by Overlord Runthak in the Valley of Strength").
2. The faction's public channel, by the holder. This is the module's `lfg`
   channel that `guildpug.py` already speaks in (LookingForGroup, else the
   zone's General). One line at 15 min and one at 2 min before the time. A
   classic drop was announced publicly because the buff reaches everyone in
   range, guild or not. This realm has no separate "world" channel and this
   note adds none.
3. The site: the guild's Raid tab shows each buff planned for the raid night,
   its holder, the turn-in time, the place and the time the raid should
   reach the door. This is the calendar. The two chat surfaces are how
   characters in the world learn the same facts.

The turn-in time is computed backwards from the raid's start time: the time
the raid should reach the door, minus the route time from the turn-in place
in the tables below. The gathering opens 10 min before the turn-in time.

## Where the guild gathers

| Buff | Gather at | Why there | Travel time it assumes |
|---|---|---|---|
| Warchief's Blessing + Rallying Cry, Horde | Within 100 yd of Overlord Runthak (14392), Valley of Strength, Orgrimmar | Rallying Cry reaches 100 yd around Runthak. Warchief's Blessing reaches all of Orgrimmar, so the same spot gets both. | 5.5 min from Bloodvenom Post (flight 4.5, walk 1) |
| Rallying Cry, Alliance | Within 100 yd of Field Marshal Afrasiabi (14721), Valley of Heroes, Stormwind | 100 yd around Afrasiabi. | 9.2 min from Talonbranch Glade (flight 2.9, boat at most 5, ride 1.3) |
| Spirit of Zandalar | Within 100 yd of Molthor (14875), Yojamba Isle | 100 yd around Molthor. The Booty Bay emissary is a second chance, 50 s later. | Horde 8.5 min from Runthak (walk 1, zeppelin at most 5, swim 2.5); Alliance 5 min from Afrasiabi (flight 2, ride and swim 3) |
| Songflower Serenade | At a Corrupted Songflower in Felwood, next to Bloodvenom Post (65 yd) or Talonbranch Glade (79 yd) | Each raider clicks the cleansed flower within its 30 s. | Horde 10.7 min from Dire Maul, Alliance 14.5 min |
| Dire Maul tribute | Inside Dire Maul North, in turns of five | A five-player instance. | First stop of the night; the run itself is unmeasured (build ticket 8) |

Order in which to take them: shortest-lived buffs last, and the order follows
the geography. Horde: Dire Maul, Felwood, Orgrimmar, Yojamba Isle, then
Blackrock Mountain. Alliance: Dire Maul, Felwood, Stormwind, Yojamba Isle, then
Blackrock Mountain. A guild that holds only a Nefarian head (or a Rend head)
takes that one buff and goes straight to the raid.

## Reaching the raid before the buffs fade

The routes below assume Molten Core or Blackwing Lair: both doors are inside
Blackrock Mountain (`entrances.json` maps 409 and 469). They also assume:

- Flight at 32 yd/s (`PLAYER_FLIGHT_SPEED`). Each flight is the shortest path
  over that faction's flight nodes in `TaxiPath.dbc` / `TaxiPathNode.dbc`.
- Zeppelins and the Auberdine boat: the in-world track at 30 yd/s
  (`gameobject_template.Data1`) plus two 60 s stops per loop
  (`TaxiPathNode.dbc` paths 285, 302 and 967). That gives a loop of under
  4 min. The note budgets 5 min per crossing, wait included.
- Ground travel mounted at 11.2 yd/s (run speed 7 with a 60% mount) over 1.3
  times the straight-line distance. Swims (Yojamba Isle) are budgeted at a
  flat 2.5 to 3 min each way.
- Turn-in scripts: Rallying Cry about 24 s after the reward, Warchief's
  Blessing 9 s, Spirit of Zandalar about 1 min (Molthor's walk plus 36 s).
- Unmeasured: the length of a Dire Maul tribute run and of the guard
  rotation. The tables start the clock when the last raider leaves Dire Maul.

### Horde, full set (D = last raider leaves Dire Maul North, T = turn-in time)

| Leg | Time | Clock |
|---|---|---|
| Ride Dire Maul to Camp Mojache (1,310 yd) | 2 min | D+2 |
| Fly Camp Mojache to Bloodvenom Post via Crossroads (14,774 yd) | 7.7 min | D+10 |
| Ride to a songflower, turn in a salve, click | 1 min | D+11, Songflower |
| Back to Bloodvenom, fly to Orgrimmar (7,415 yd) | 4.5 min | D+16 |
| Walk to Runthak | 1 min | D+17 |
| Wait for the announced time (T = D+20) | 3 min | T, Blessing and Rallying Cry by T+0.5 |
| Walk to the zeppelin towers outside the gate (about 350 yd) | 1 min | |
| Zeppelin to Grom'gol | at most 5 min | |
| Grom'gol to Molthor, swim included (1,267 yd straight) | 2.5 min | |
| Heart of Hakkar turn-in | 1 min | T+10, Zandalar |
| Back to Grom'gol | 2.5 min | |
| Fly Grom'gol to Flame Crest (5,930 yd) | 3.1 min | |
| Ride Flame Crest to the Blackrock Mountain doors (1,151 yd straight) | 2.2 min | T+18, at the door |

Left at the door: Warchief's Blessing 42 min, Songflower 33 min, Rallying Cry
102 min, Spirit of Zandalar 112 min, Dire Maul buffs 82 min. Without a Heart of
Hakkar the Yojamba detour (6 min) drops out, and the raid reaches the door at
T+12.

### Alliance, full set

| Leg | Time | Clock |
|---|---|---|
| Ride Dire Maul to Thalanaar (1,872 yd straight) | 3.6 min | D+4 |
| Fly Thalanaar to Talonbranch Glade (19,034 yd) | 9.9 min | D+14 |
| Turn in a salve and click | 1 min | D+15, Songflower |
| Fly Talonbranch Glade to Auberdine (5,622 yd) | 2.9 min | |
| Boat to Stormwind Harbor | at most 5 min | |
| Ride the harbor to Afrasiabi (860 yd straight) | 1.3 min | D+24 |
| Wait for the announced time (T = D+27) | 3 min | T, Rallying Cry by T+0.5 |
| Walk to the Stormwind flight master, fly to Rebel Camp (2,755 yd) | 2 min | |
| Ride and swim to Molthor (1,550 yd straight) | 3 min | |
| Heart of Hakkar turn-in | 1 min | T+6.5, Zandalar |
| Back to Rebel Camp | 3 min | |
| Fly Rebel Camp to Morgan's Vigil (5,053 yd) | 2.6 min | |
| Ride Morgan's Vigil to the Blackrock Mountain doors (1,905 yd straight) | 3.7 min | T+16, at the door |

Left at the door: Songflower 31 min, Rallying Cry 104 min, Spirit of Zandalar
110 min, Dire Maul buffs 77 min. Without a heart, Stormwind straight to the
door is 0.5 + 2.4 + 3.7 = under 7 min.

### Why the raid travels, not summons

Raid nights already decided that the raid's own warlocks summon and everyone
else walks (#762, `raidrun.py`). With world buffs, a summoner and the two
raiders who click the portal must already be at the stone, and so they miss
the city buffs. Summoning 37 raiders one at a time is also no faster than the
12 to 18 min route above. So the whole raid travels together from the last
buff, and summoning stays what #762 made it: the way a straggler, or a raider
who missed the gathering, reaches the door.

Zul'Gurub as the night's raid: from Molthor to the Zul'Gurub door
(`entrances.json` map 309) is about 2,500 yd straight plus the swim, about
5 min. The Heart of Hakkar then comes last and the city buffs come before
it. AQ20 and AQ40 (Silithus) are not routed here; the same DBC method gives
their times when the realm raids there.

## Build tickets to file

One line each: what changes, and in which repo.

1. wow-overseer: a pure `worldbuff.py` holding the catalogue in this note
   (spell, item, quest, NPC, place, duration, faction, radius) and the route
   planner that gives the turn-in time from the raid's start time, with tests
   whose fixture rows are the world rows cited here.
2. wow-overseer: a bridge pass that reads who holds a head and whether their
   quest is done (`character_inventory` for 12630, 19002, 19003 and 19802;
   `character_queststatus_rewarded` for 4974, 7781, 7783 and 8183), and writes
   one planned turn-in row per guild raid night.
3. mod-overseer: at a Nefarian or Hakkar kill, the master looter assigns the
   head to the guild leader. The rule for a leader whose quest is done waits
   for the operator's answer above.
4. mod-overseer: a timed turn-in row. The holder walks to Thrall and Runthak,
   to Varian and Afrasiabi, or to Molthor, and completes the quest at the
   planned time, never before.
5. wow-overseer: the holder's guild chat lines (at raid set, T-30, T-5) and
   public `lfg` channel lines (T-15, T-2), through the existing guildsocial
   and guildpug write paths.
6. wow-overseer: the site's Raid tab shows the world buff calendar: each
   planned turn-in with buff, holder, time, place and door time.
7. mod-overseer: the buff gathering. Seated raiders walk to the gathering spot
   before T, and after the last buff travel the route above to the raid door
   (zeppelin, boat and flight legs included). This extends the GATHERS work
   from #762.
8. wow-overseer: measure on the dev realm whether one Cleansed Songflower
   serves more than one clicker in its 30 s, and how long a Dire Maul North
   tribute run and its guard rotation take. Then fold the numbers into the
   planner.
9. mod-overseer: the Songflower leg. A raider carrying a Cenarion Plant Salve
   turns it in at a Corrupted Songflower and clicks the cleansed flower;
   salves come from the repeatable Salve via quests.
10. mod-overseer: the Dire Maul tribute leg. A five-player tribute clear that
    leaves the three guards alive, then raiders take turns in the party to
    talk to each guard.
