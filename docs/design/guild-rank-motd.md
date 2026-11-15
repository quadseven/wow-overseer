# Guild rank promotion and MOTD specification (#2616)

Status: pure ranking, command shaping, and rank-drift reporting live in
`guildranks.py` and `apiv2/guild.py`; C++ verb execution in `mod-overseer` is
specified below and not yet wired into `bridge.py` (`tests/test_guild_verbs.py`
gates `kind='guild'` writers on `guildcorps.MODULE_GUILD_VERBS`).

## 1. Findings in the pinned playerbots module

Checked `quadseven/mod-playerbots` at `AC_MODULE_SHA=40884e9c135c1daf27ffd894a6047502a5701130`
(`UPSTREAM-PINS.env`):

- `src/Ai/Base/Actions/GuildManagementActions.h` and
  `src/Ai/Base/Actions/GuildManagementActions.cpp` (`GuildPromoteAction`,
  `GuildManageNearbyAction`): `GuildManageNearbyAction::Execute` calls
  `botAI->DoSpecificAction("guild promote", Event("guild management", guid), true)`
  only on `!urand(0, 30) && dCount < 2` for nearby same-guild players, sending
  `CMSG_GUILD_PROMOTE` without any level rule, raid-seat lookup, target rank,
  or offline member handling.
- `src/Mgr/Guild/PlayerbotGuildMgr.cpp`: handles guild creation and random
  emblems only. No MOTD action (`CMSG_GUILD_MOTD` or `MOTD`) exists in
  `quadseven/mod-playerbots`.

Because playerbots cannot drive deterministic level/seat promotions or set MOTD,
dedicated `mod-overseer` guild verbs are required.

## 2. Core APIs at the pinned revision

Checked `mod-playerbots/azerothcore-wotlk` at `AC_CORE_SHA=47960183bb03b83e8943eb2f0f39c16df9710c9d`:

- Default rank IDs in `mod-overseer/src/overseer_decisions.h`
  (`GUILD_RANK_MASTER = 0`, `GUILD_RANK_OFFICER = 1`, `GUILD_RANK_VETERAN = 2`,
  `GUILD_RANK_MEMBER = 3`, `GUILD_RANK_INITIATE = 4`).
- `src/server/game/Guilds/Guild.h` and `src/server/game/Guilds/Guild.cpp`:
  - `GR_RIGHT_PROMOTE` (`0x00000080`) and `GR_RIGHT_SETMOTD` (`0x00001000`).
  - `Guild::ChangeMemberRank(ObjectGuid guid, uint8 newRank)` updates
    `guild_member.rank` on the in-memory `Guild` object and DB, enforcing
    `newRank <= _GetLowestRankId()`.
  - `Guild::HandleSetMOTD(WorldSession* session, std::string_view motd)` checks
    `HasRankRight(session->GetPlayer(), GR_RIGHT_SETMOTD)`, updates `m_motd`,
    and triggers `sScriptMgr->OnGuildMOTDChanged(this, m_motd)`.

## 3. Specified `mod-overseer` module verbs

Add two variants to `OverseerDecisions::GuildVerb` in
`mod-overseer/src/overseer_decisions.h` and dispatch them in `DoGuild`
(`mod-overseer/src/mod_overseer.cpp`), patterned after `GuildVerb::Invite` and
`GuildVerb::BankGrantDeposit`:

1. `GuildVerb::Promote`: `promote rank:<id>` with `target_arg = <member_name>`.
   - Parser requires `id` in `{1, 2, 3, 4}`.
   - Executor checks `guild->HasRankRight(who, GR_RIGHT_PROMOTE)`, resolves
     target member by name (`guild->GetMember(targetArg)`), refuses
     self-promotion and promoting to or above `me->GetRankId()`, calls
     `guild->ChangeMemberRank` / `HandleUpdateMemberRank`, and witnesses
     `after->GetMember(targetGuid)->GetRankId() == requestedRank`.
2. `GuildVerb::Motd`: `motd <text>` (single-line ASCII, max 128 bytes).
   - Executor checks `guild->HasRankRight(who, GR_RIGHT_SETMOTD)`, calls
     `guild->HandleSetMOTD(who->GetSession(), text)`, and witnesses
     `after->GetMOTD() == text`.

Once implemented in `mod-overseer` and its submodule pin is bumped in
`UPSTREAM-PINS.env`, add `"promote"` and `"motd"` to
`guildcorps.MODULE_GUILD_VERBS` and enqueue `guildranks.plan_actions(...)`
through `_insert_guild` via the guild master.
