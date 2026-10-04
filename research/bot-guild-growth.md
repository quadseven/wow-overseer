# Bot guild growth: how random-bot guilds form, and what lets one reach 71

Resolves [wow-overseer#515](https://github.com/quadseven/wow-overseer/issues/515), workstream C of [wow-overseer#512](https://github.com/quadseven/wow-overseer/issues/512).
Researched 2026-10-04 (America/New_York). Read-only: no realm writes, no realm reads.

Sources, pinned:

- Upstream mod-playerbots `037c014` (2026-10-02): `UP` below, https://github.com/mod-playerbots/mod-playerbots/tree/037c01418b5d01506917a3db9b44fd56ac5f965c
- Our fork quadseven/mod-playerbots `7bae1b5` (2026-09-20): the guild files are identical to upstream apart from an emblem write in `PlayerbotGuildMgr::SetGuildEmblem` and one comment.
- quadseven/mod-overseer `ec7645a`, quadseven/wow-overseer `b1b7626`.
- The infra repo's wow and wow-dev manifests and image patches (private; cited as infra#N and by path).
- AzerothCore `Guild::AddMember` (`src/server/game/Guilds/Guild.cpp`, master).

## Answer in brief

Upstream random-bot guilds do not grow by recruiting. They are filled by the factory, which drops each guildless random bot into a random partly filled guild of its faction, up to `RandomBotGuildSizeMax` (15 on both realms). The only bot-to-bot invite path sits in the `guild` strategy, which upstream never adds to random bots, and the same strategy carries a "leave large guild" trigger that would empty a 71-member bot-led guild within minutes. Cave and Bonkers reach 71 by a different machine entirely: the wow-overseer bridge's recruit sweep issues mod-overseer `shortlist` and `invite` verbs (`Guild::AddMember`, rank Initiate) toward `Overseer.Recruit.TargetSize = 71`. The raider, summoner and maintenance split is computed afterward from the roster by class, not recruited for directly. To let any bot guild grow naturally to 71 with the 40/21/10 mix, generalize that sweep from the family to a configured list of guilds, give each guild its own shortlist and actor, and leave the upstream size cap and `guild` strategy alone.

## 1. How upstream random-bot guilds form

### Config keys (UP `conf/playerbots.conf.dist`, `src/PlayerbotAIConfig.cpp:188,580-581`)

| Key | Default | Both realms | Effect |
|---|---|---|---|
| `AiPlayerbot.RandomBotGuildCount` | 20 | 20 | Max bot-led guilds. `> 0` also turns on `InitGuild` at factory and at every bot login. |
| `AiPlayerbot.RandomBotGuildSizeMax` | 15 | 15 | Fill cap used by `AssignToGuild`. The dist says "minimum is hardcoded to 10"; no such floor exists in the code read. |
| `AiPlayerbot.RandomBotGuildNearby` | 0 | 0 (unset) | Lets `GuildManageNearbyAction` invite nearby players and bots. |
| `AiPlayerbot.DeleteRandomBotGuilds` | 0 | 0 | On startup disbands every guild whose leader is on a random-bot account. |
| `AiPlayerbot.RandomBotInvitePlayer` | 0 | 1 | Lets bots invite real players to groups and guilds. |
| `AiPlayerbot.InviteChat` | 0 | unset | Chat lines on invite (the text block is commented out in UP). |
| `AiPlayerbot.EnableGuildTasks` and `*GuildTask*` | 0 | 0 | Guild errands by mail. Not membership. infra's live override documents that nothing calls `GuildTaskMgr::Update()`; image patch 0017 addresses that. |
| `AiPlayerbot.RandomBotNonCombatStrategies` | "" | unset | The only way the `guild` strategy reaches random bots. |
| `AiPlayerbot.BotActiveAloneDurationSeconds` | 30 | unset | Also the re-roll period for each bot's guild-size preference (section 3). |

Sources: wow-dev `config/playerbots.overrides.conf` lines 154-164, wow `config/playerbots.overrides.conf` lines 80-85 (infra#2791 for the dev sizing rule).

### Creation and fill (UP `src/Mgr/Guild/PlayerbotGuildMgr.cpp`, `src/Bot/Factory/PlayerbotFactory.cpp:4921`)

1. `PlayerbotFactory::InitGuild` runs during factory init (`PlayerbotFactory.cpp:1044`) and again on every random-bot login (`RandomPlayerbotMgr::OnBotLoginInternal`, `RandomPlayerbotMgr.cpp:2656`), whenever `RandomBotGuildCount > 0` and the bot has no guild.
2. `PlayerbotGuildMgr::AssignToGuild` (lines 70-113) returns a random cached guild with `status == 1` (members below `maxMembers`), the bot's faction, and `hasRealPlayer == false`. Only if none exists and the count of bot-led guilds is under `RandomBotGuildCount` does it return a fresh name from `playerbots_guild_names`.
3. A fresh name makes the bot the leader via `Guild::Create` (lines 26-50). An existing guild gets `Guild::AddMember` at a random rank between Officer and Initiate (`InitGuild`, line 4946). No invite, no accept, no class or role logic.
4. `hasRealPlayer` is "the leader's account is not in the random-bot account list" (`ValidateGuildCache`, line 208). A guild led by a real account is never filled by the factory. The cache is rebuilt hourly (lines 282-303).

There is no petition or charter step in this path. The upstream dist comment about "10 initial randombots needed to sign the charter" describes the separate `guild` strategy (`BuyPetitionAction`, `PetitionOfferAction` in `src/Ai/Base/Actions/GuildCreateActions.cpp`), which random bots do not run.

The core sets no guild size limit: `Guild::AddMember` checks only that the character is unguilded and not already a member.

### Natural recruiting upstream: present in code, off in practice

- `GuildStrategy` (`src/Ai/Base/Strategy/GuildStrategy.cpp`) fires `offer petition nearby`, `guild manage nearby`, `turn in petition`, `buy tabard`, and `leave large guild` (on the `leave large guild` trigger).
- `AiFactory.cpp:613,646` has `nonCombatEngine->addStrategy("guild")` commented out for random bots. Neither realm sets `RandomBotNonCombatStrategies`, so no random bot runs this strategy today.
- `GuildManageNearbyAction::Execute` (`GuildManagementActions.cpp:131-282`) promotes or demotes nearby members on a 1-in-31 roll by death count, and, only with `RandomBotGuildNearby = 1`, sends `guild invite` to nearby unguilded players within spell distance. It skips SOLO-type bots and bots owned by a real player, and caps only at 1000 members. It ignores `RandomBotGuildSizeMax`, class, and role.
- `GuildAcceptAction` accepts any invite from a guilded inviter that passes `PLAYERBOT_SECURITY_INVITE`.
- Guild chat: `GuildFeedback`, `GuildRepliesRate` and `BroadcastToGuildRecruitmentGlobalChance` drive chatter only. Nothing in guild chat leads to an invite.

### Leadership

The founder bot leads. Nothing upstream transfers leadership, and rank changes happen only through the strategy above. Factory members get random ranks from Officer down, so roughly a fifth of a factory guild holds officer rights.

## 2. How Cave and Bonkers reach 71 today

1. **Target.** wow-dev `config/overseer.overrides.conf` sets `Overseer.Recruit.TargetSize = 71` with the argument "40 raiders + 10 guild managers + 21 warlocks" (infra#4173, infra#4138, infra#4162). Live sets 40. `Overseer.Recruit.LevelMin = LevelMax = 1` on dev: only level-1 characters are invited, and they level naturally.
2. **Judgement (mod-overseer).** `RecruitPolicyFromConfig` (`src/mod_overseer.cpp:52494`) reads the three keys per command. `GuildNeedsFrom` and `RecruitVerdictFor` (`src/overseer_decisions.h:14656-14711`) refuse in order: already guilded (the no-poaching rule), other faction, deleted, below or above band, nothing missing, roster full. Otherwise they invite for depth, role, service, or profession. The `invite` verb calls `Guild::AddMember(guid, GUILD_RANK_RECRUIT)`, where `GUILD_RANK_RECRUIT = GUILD_RANK_INITIATE` (`overseer_decisions.h:14376`; `mod_overseer.cpp:55769`). Offline candidates join too.
3. **Pace and turn (wow-overseer).** `bridge._recruit_once` (`bridge.py:12569`) runs every `RECRUIT_CYCLE_SECONDS` (300). `recruit.plan_recruit` writes one `shortlist` or one `invite` row per pass, at least `MIN_MINUTES_BETWEEN_INVITES = 5` apart, with a 30-day asked-memory (infra#3650, infra#3651). `_recruit_prefer` orders the shortlist by `raidlineup.build_lineup(...)["recruit_classes"]`, the classes the eight raid groups lack.
4. **Roles are derived after the fact.** `raidlineup.build_lineup` (`raidlineup.py:363`, constants `RAIDERS, MAINTENANCE, SUMMONERS = 40, 10, 21` at line 65) assigns warlocks to the summoner corps first, then seats tanks, healers, and damage for eight groups of five, then fills maintenance from the remainder. Everyone else is `surplus`. `guildjobs.py:127` names the same roles for the job passes. Recruiting therefore targets only the raid's class gaps. Nothing steers recruits toward 21 warlocks or 10 maintenance members, so the summoner corps fills only if enough warlocks happen to arrive.
5. **Presence and natural progression (image patches).** infra patch `0019-keep-a-named-guild-online` and `AiPlayerbot.AlwaysOnlineGuild = "Cave,Bonkers"` log the guilds' random-bot members in ahead of rotation (infra#3961, infra#3966, infra#4119; dev only, infra#3964). Patch `0024-a-natural-guild-is-granted-nothing` and `AiPlayerbot.NaturalGuild = "Cave,Bonkers"` exempt members from randomize, refresh, level-up grants, autogear, maintenance, and taxi loans.

### Limits of the current sweep

- **Family-only actors.** `_online_guild_members` (`bridge.py:24415`) returns only names in `OVERSEER_NOTABLE_NAMES` that are guilded and online. A guild with no family member online, or none at all, is never recruited for.
- **One guild per pass, one shared shortlist.** `plan_recruit` acts as `sorted(actors)[0]` (`recruit.py`, about line 215), and `_latest_guild_shortlist` (`bridge.py:24270`) reads the newest delivered shortlist from any actor. With Cave and Bonkers heads both online, the first-sorted name's guild gets every invite, and a shortlist built for one guild's faction and gaps can feed the other guild's turn. `RecruitVerdictFor` rejects the wrong faction, so this wastes passes rather than mis-joining characters.
- **Candidate supply depends on the factory cap.** Recruits must be unguilded. Upstream `InitGuild` places every unguilded random bot at login while any same-faction factory guild has room. Unguilded level-1 bots therefore exist only because the 20 x 15 = 300 factory slots are full or faction-mismatched.

## 3. Options and risks for growing any bot guild to 71

### Do not raise `RandomBotGuildSizeMax` to 71

Raising the cap fills guilds by random placement, not recruiting: random class mix, random officer ranks, no 40/21/10 shape. At 20 x 71 = 1420 slots against a roster of about 1000 (500 online x rotation ratio 2.0), it breaks the infra#2791 rule that count x sizeMax stays well under the roster. It would also absorb every unguilded bot at login and starve the natural sweep's candidate pool. Lowering `RandomBotGuildCount` (for example 4 x 71) avoids the churn but still yields random rosters.

### Do not turn on the `guild` strategy for random bots as is

`LeaveLargeGuildTrigger::IsActive` (`src/Ai/Base/Trigger/GuildTriggers.cpp:22-55`) makes a bot leave when the guild has more members than `uint8(GetGuilderType())`. `GuilderType` maps to caps SOLO 0, TINY 30, SMALL 50, MEDIUM 70, LARGE 120, and VERY_LARGE 250 (`PlayerbotAI.h:247`). `GetGuilderType` (`PlayerbotAI.cpp:4550`) draws from `GetFixedBotNumber(100)`, which mixes in a time slot of `BotActiveAloneDurationSeconds` (30 s, line 4508). The bot's type is re-rolled every 30 seconds.

At 71 members, about 60 percent of rolls (SOLO 20, TINY 10, SMALL 10, MEDIUM 20) say "too big". The trigger fires only when the guild's leader is an online, non-selfbot bot, and the member is not a selfbot or altbot and not in a real-led guild. In a bot-led guild kept online by `AlwaysOnlineGuild`, every non-leader member would therefore leave within minutes. Enabling the strategy also turns on `RandomBotGuildNearby`-gated invites that ignore class and size, plus random promote and demote. Any use of it needs a patch first that exempts `NaturalGuild` and `AlwaysOnlineGuild` guilds from `LeaveLargeGuildTrigger`.

### Recommended path: generalize the overseer sweep

1. **Config, a new key.** Add a list of guilds to recruit for, such as `Overseer.Recruit.Guilds = "Cave,Bonkers,..."`, and optionally per-guild target sizes. `Overseer.Recruit.TargetSize = 71` and the level band already exist. Each listed guild should also join `AiPlayerbot.AlwaysOnlineGuild` and `AiPlayerbot.NaturalGuild` so members stay present and earn their progression.
2. **Per-guild actor.** The `guild` verbs resolve the guild from the acting character (`DoGuild`), so each listed guild needs one online member to carry rows: its leader, or any member. The invite calls `Guild::AddMember` directly rather than the invite packet; whether `DoGuild` checks the actor's rank was not verified here. `AlwaysOnlineGuild` makes one reliably available. Replace `OVERSEER_NOTABLE_NAMES` in `_online_guild_members` with a per-guild lookup.
3. **Per-guild shortlist and pacing.** Filter `_latest_guild_shortlist`, `_minutes_since_last_guild_invite`, and the asked-memory by the actor's guild. Run `plan_recruit` once per guild per pass instead of acting as `sorted(actors)[0]`.
4. **Recruit for the full 40/21/10 shape.** Extend `_recruit_prefer` to add warlock while `shortfall.summoners > 0`. Maintenance takes any class, so it fills from depth once raid and summoner gaps close. `RecruitVerdictFor` still decides who qualifies; the bridge only orders the list.
5. **Leadership.** Promote the founding leader of a bot-led guild through the existing guild verbs or leave it alone. Do not rely on upstream promotion, which is off with the strategy.

### Risks

- **`DeleteRandomBotGuilds = 1` disbands any guild whose leader is on a random-bot account** (`PlayerbotGuildMgr.cpp:229-255`). A grown bot-led guild is one restart from deletion if that key is ever flipped. Cave and Bonkers are protected only if their leaders are on non-random accounts, which this research did not measure.
- **Factory fill into a natural guild.** `AssignToGuild` adds any unguilded same-faction bot to any bot-led guild under `RandomBotGuildSizeMax`. A new bot-led natural guild below 15 members is topped up at random by the factory, and every factory join lands at a random rank up to Officer. Exempt listed guilds in `AssignToGuild`, or found them under a non-random account so `hasRealPlayer` excludes them.
- **Level brackets and resets.** `LevelBrackets.IgnoreGuildBotsWithRealPlayers` and `ResetBotLevel.IgnoreGuildBotsWithRealPlayers` protect only real-led guilds. Check that patch 0024 covers bracket level changes for a bot-led natural guild before relying on it.
- **Online budget.** Each `AlwaysOnlineGuild` guild pins up to 71 bots ahead of rotation. Two guilds take 142 of the 500 online slots on dev, and every added guild shrinks the rotating world.
- **Warlock supply.** 21 warlocks per guild at level 1 in one faction may exceed the unguilded pool. The sweep idles on "nothing missing" rather than failing, so watch the shortfall instead of the roster count.
- **Write load and stop condition.** Each invite is a guild write. The sweep must idle at 71 of 71 (the property infra#4173 calls out), and adding guilds multiplies the pace. Per-guild pacing keeps the 5-minute gap meaningful.
- **Two-guild shortlist bleed** (section 2) already affects Cave and Bonkers today and should be fixed before more guilds are added.

## Open questions not answered here

- Which accounts lead Cave and Bonkers. This decides whether `DeleteRandomBotGuilds`, `AssignToGuild`, and `LeaveLargeGuildTrigger` can touch them. It needs a read of `guild.leaderguid` against the random-bot account list.
- The current unguilded level-1 pool per faction and class on wow-dev, which bounds how fast a third guild could fill.
