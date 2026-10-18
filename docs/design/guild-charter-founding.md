# Founding a guild by charter: the alternative to `guild form`

Status: not built. The charter route remains a documented alternative to the `guild form` verb, pending an
operator decision (issue #1106). Nothing in the bridge or the module buys, signs or turns in a charter today.

This file records what the charter path would need, checked against the pinned core rather than recalled
from memory, so that whoever picks it up does not start from guessed flags. Every core reference below is to
the core pinned as `AC_CORE_SHA` in `UPSTREAM-PINS.env` (`47960183bb03`, the playerbots fork of AzerothCore).
References name a file and a symbol, not a line number, so they survive edits that only move code; grep the
symbol at the pinned SHA. When that pin moves, re-check the values in the table (item entry, flag bits,
config defaults), which are what a builder would rely on.

## 1. What the core actually requires

| Fact | Pinned core value | Where |
|---|---|---|
| Charter item | `GUILD_CHARTER = 5863` | `src/server/game/Petitions/PetitionMgr.h`, enum `CharterItemIDs`, entry `GUILD_CHARTER` |
| NPC that sells it | `UNIT_NPC_FLAG_PETITIONER = 0x00040000` (the header notes guild petitioners carry `0xC0000`, i.e. petitioner plus `UNIT_NPC_FLAG_TABARDDESIGNER = 0x00080000`) | `src/server/game/Entities/Unit/UnitDefines.h`, enum `NPCFlags` |
| Buy check | `HandlePetitionBuyOpcode` calls `GetNPCIfCanInteractWith(guidNPC, UNIT_NPC_FLAG_PETITIONER)` | `src/server/game/Handlers/PetitionsHandler.cpp`, `HandlePetitionBuyOpcode` |
| Price | `CONFIG_CHARTER_COST_GUILD`, config `Guild.CharterCost`, default 1000 copper (10 silver) | `src/server/game/World/WorldConfig.cpp`, `SetConfigValue` for `CONFIG_CHARTER_COST_GUILD` |
| Signatures needed | `CONFIG_MIN_PETITION_SIGNS`, config `MinPetitionSigns`, default 9, range 0-9, reloadable | `src/server/game/World/WorldConfig.cpp`, `SetConfigValue` for `CONFIG_MIN_PETITION_SIGNS` |
| How a signature arrives | `CMSG_PETITION_SIGN`, handled by `HandlePetitionSignOpcode` | `src/server/game/Handlers/PetitionsHandler.cpp`, `HandlePetitionSignOpcode` |
| One signature per account | the sign handler refuses a second signer from an account already on the charter, then lets `OnPlayerbotCheckPetitionAccount` override that answer | `src/server/game/Handlers/PetitionsHandler.cpp`, `HandlePetitionSignOpcode`, the loop over `signatureMap` before `OnPlayerbotCheckPetitionAccount` |
| Turn-in | `CMSG_TURN_IN_PETITION`, `HandleTurnInPetitionOpcode`; refuses with `PETITION_TURN_NEED_MORE_SIGNATURES` below the configured count, else destroys the charter, calls `Guild::Create` for the owner and `Guild::AddMember` for each signer | `src/server/game/Handlers/PetitionsHandler.cpp`, `HandleTurnInPetitionOpcode` |

Two consequences follow directly from the table:

- **The guild the charter makes is the same object `guild form` makes.** Turn-in ends in `Guild::Create` plus
  `sGuildMgr->AddGuild` plus `Guild::AddMember`, which is exactly the core API the module's formation machine
  already calls (`mod-overseer/src/mod_overseer.cpp`, the block headed "WHY Guild::Create AND NOT A
  CHARTER", and `NextGuildFormationStep` in `overseer_decisions.cpp`). A charter buys no extra correctness;
  it is a different road to the same rows.
- **The blocker is the signature count, not the item or the NPC.** Nine `CMSG_PETITION_SIGN` packets from
  nine characters who are not yet in the guild, at most one per account unless the playerbot hook says
  otherwise. A family of five cannot sign its own charter. That is why the guild was founded with
  `guild form` instead, and it stays the default.

## 2. If an operator chooses to build it

The route only makes sense once there are at least `CONFIG_MIN_PETITION_SIGNS` guildless characters willing
to sign, so it is a recruiting step, not a founding shortcut. The shape it would take:

1. **Scope the signers with the existing recruit loop, not a new one.** `recruit.py` already chooses who the
   family asks in, with its band, freshness and duplicate guards, and `RecruitShortlist` in the module's pure
   layer ranks them. A charter path reads that shortlist and asks for signatures from it; it does not grow a
   second cohort filter. No new accounts or characters are created for it.
2. **Find a petitioner from data, not from a hard-coded entry.** Pick a creature whose `npcflag` has
   `UNIT_NPC_FLAG_PETITIONER` set, in the founder's faction, reachable by the existing travel code. Verify the
   flag against the world database at run time; do not copy an entry id from a wiki.
3. **Buy, sign, turn in, each through the core handler.** The founder buys item 5863 from that NPC; each
   signer's signature must go through `HandlePetitionSignOpcode` (a real or emulated `CMSG_PETITION_SIGN`) so
   the account check and the playerbot hook both run; the founder turns in with `CMSG_TURN_IN_PETITION`.
   Never insert `petition`, `petition_sign`, `guild` or `guild_member` rows by hand: rows written that way look
   right and leave a world that has never heard of them.
4. **Refuse rather than fall back.** If the count is short at turn-in the core says
   `PETITION_TURN_NEED_MORE_SIGNATURES`; the job reports that and stops. It does not quietly switch to
   `guild form`, because the operator asked for one road and should see that it failed.

## 3. Test plan

Unit level (no realm):

- A pure decision function, in the style of `NextGuildFormationStep`, that takes the founder, the signer list
  and `CONFIG_MIN_PETITION_SIGNS` and answers buy / wait for signers / sign / turn in / blocked. Cases: fewer
  signers than the minimum blocks; two signers from one account count once; a signer already in a guild is
  refused; the founder never signs their own charter.
- A source-shape test that keeps the constants above in step with the module: item 5863, the petitioner flag
  and the config name are read from the core headers the module includes, not restated as literals.

On the realm, read-only, after one real charter turn-in:

- `SELECT guildid, name, leaderguid FROM guild WHERE name = '<name>'` returns exactly one row, and
  `leaderguid` is the founder's character guid.
- `SELECT guid, rank FROM guild_member WHERE guildid = <id>` returns the founder at rank 0 (guild master)
  plus one row per signer, and nobody else. The count equals 1 + the number of signatures on the charter.
- `SELECT * FROM petition WHERE ownerguid = <founder guid>` and the matching `petition_sign` rows are gone,
  and the founder no longer holds item 5863: turn-in consumed them.
- The module's own view agrees with the tables: `guild->GetMember(name)` finds every signer (the module asks
  the Guild object rather than `guild_member` for exactly the commit-lag reason noted beside the formation
  machine).

Until the operator decides to build it, the unit test in `tests/test_guild_verbs.py` only checks that this
document still names the constants, packets and tables above.
