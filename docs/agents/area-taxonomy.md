# Area taxonomy for the WoW backlog

Status: proposed. It needs the operator's approval before it becomes a rule.

## Why

On 2026-10-24 the two WoW repos held 345 open issues. None of them carried an area label. Twelve epics shared one title: "work that triage, rewrites and health intake find". Several epics covered the same ground: dungeon progression appeared twice, and travel appeared four times across the two repos. A reader could not answer "what is open for Blackfathom?" or "what is open for Leatherworking?" without reading every title.

The hierarchy itself stays as Loom's decision 0003 sets it. A goal holds epics, an epic holds at most 15 tickets, and an epic finishes. This document adds the missing dimension, the area of play. Areas are labels, not epics, for two reasons:

- A GitHub issue has one parent, but a WoW ticket often touches two areas. A bag hold touches dungeons and bags.
- Epics must stay small and finish. An area such as Dungeons never finishes.

## The rule

1. **Every open ticket and every epic carries exactly one `area:` label.** It names the area of play where a player would notice the change.
2. **A ticket also carries one or more topic labels** when the area has topics (the table below). A ticket that touches two dungeons carries both dungeon labels.
3. **Every epic sits in one area.** It carries that area's label, and its tickets share it. When an area's open epic is full (15 tickets), the next ticket goes into a new epic in the same area, named for the work it holds, never a generic intake name.
4. **No catch-all epics.** Intake, whether from triage, health findings, review findings or rewrites, files each ticket into the open epic of its area. "Work that triage finds" is not an area.
5. **Both repos use the same labels.** A module ticket (mod-overseer) and a bridge ticket (wow-overseer) for the same area carry the same `area:` and topic labels. Epics live in wow-overseer, and module tickets join them as cross-repo sub-issues.
6. **Tooling and the site are areas too.** Work no player sees, such as CI, tests, review-finding cleanups and refactors, goes under `area:tooling` or `area:site`. It never goes unlabeled.

## Areas and topics

| Area label | What belongs | Topic labels |
|---|---|---|
| `area:dungeons` | 5-man runs, the dungeon queue, doors, bosses, wipes inside | `dungeon:<name>`, for example `dungeon:blackfathom`, `dungeon:uldaman`, `dungeon:scarlet-monastery`, `dungeon:razorfen-downs`, `dungeon:dire-maul`, `dungeon:gnomeregan` |
| `area:raids` | 20- and 40-man raids, raid prep, attunement, resistance gear | `raid:molten-core`, `raid:onyxia`, `raid:prep` |
| `area:professions` | trades, trainers, recipes, crafting, gathering | `trade:<name>`, for example `trade:leatherworking`, `trade:blacksmithing`, `trade:tailoring`, `trade:alchemy`, `trade:enchanting`, `trade:engineering`, `trade:herbalism`, `trade:mining`, `trade:skinning`, `trade:cooking`, `trade:first-aid`, `trade:fishing` |
| `area:economy` | bags, bank, auction house, vendors, gold, mail | `econ:bags`, `econ:bank`, `econ:auction`, `econ:vendor`, `econ:gold` |
| `area:travel` | crossings, boats, zeppelins, flight, pathing, walking, getting somewhere | `travel:crossing`, `travel:pathing`, `zone:<name>` |
| `area:questing` | quest pick, turn-in, quest stalls, levelling routes | `quest:class` for class quests |
| `area:class` | class training, spells, talents, gear and weapon skills | `class:training`, `class:gear`, `class:talents` |
| `area:guild` | guild runs, recruiting, social asks, chat and the local LLM | `guild:runs`, `guild:social`, `guild:chat` |
| `area:stability` | worldserver uptime, rolls, crashes, deaths and recovery, stuck members | `stab:roll`, `stab:deaths`, `stab:stuck` |
| `area:site` | the overseer dashboard, its API and CLI | none |
| `area:tooling` | CI, tests, review-finding cleanups, refactors, repo hygiene | none |

Every `dungeon:`, `raid:` and `trade:` label exists from the start, one per dungeon, raid and trade, even with a single ticket. That way "everything open for Leatherworking" is always one label. A `zone:` label is added only when a zone gains its third open ticket. Adding a topic label never needs approval.

## Epics inside an area

An epic stays finite and holds at most 15 tickets (Loom decision 0003). When an area or topic outgrows one epic, it splits by topic, never into a bigger epic. Professions splits into one epic per trade with work open (for example "Epic: Leatherworking reaches the raid recipes"). Dungeons splits by dungeon or level band. The result reads as area, then topic epic, then ticket. For example: Professions, then Leatherworking, then a ticket. Or: Dungeons, then Blackfathom Deeps, then a ticket.

## How it is checked

- The hunt collector reports an open ticket with no `area:` label as a fault, the same way it reports an epic that breaks the epic standard.
- Grug Chief's plan checks gain one row: a PR's linked issue carries an `area:` label.
- Loom's intake picks the area when it files a ticket. The station refuses to brief a ticket without one.

## Migration

The migration is a one-time, paced pass, run the burn-down way. Sweepers propose an area, topics and epic for every open ticket. A verifier spot-checks. One closer applies the labels and parents at one write every 3 seconds. That closer also merges duplicate epics, and moves the catch-all epics' children into area epics before closing the catch-alls. The dry run (`area-migration-dryrun.md`) lists every proposed change before anything is written.
