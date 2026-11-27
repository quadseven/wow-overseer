# Random bot population and leveling

The November 15, 2026 census counted 322 death knights among 351 level-60
bots. Among 2,032 guildless non-death-knight bots, none were level 60. It
counted 649 warriors and 758 paladins, compared with 126 priests, 100 druids
and 82 shamans. The snapshot shows who was present, with no history of XP
or account refills. [Issue and census](https://github.com/quadseven/wow-overseer/issues/2617).

## Overseer retirement starts at level 42

With `RETIRE_FACTORY=on`, the bridge queues eligible factory characters for
retirement at level 42 or above. `retire.ELIGIBLE_SQL` includes guildless
characters and exempts death knights, protected guilds and roster characters.
The selector uses current level and has no field for how the bot earned its
XP. Eligible characters can disappear before reaching 60 or after reaching it.
The worldserver's `RetireVerdictFor` rechecks the rules and protects active
guild-run participants and characters with an attached client.
`ResolveRetireChecks` calls `Player::DeleteFromDB` after logout and records
`outcome=retired` on success. [Bridge selection](../../retire.py) and
[worldserver delete at the November 15 pin](https://github.com/quadseven/mod-overseer/blob/27274af5838bfdbd897c0c759437bffbda2368ed/src/mod_overseer.cpp#L72753-L72787).

The October 5 deployment enabled the pass to remove 877 legacy pre-leveled
characters. The November 15 classic dev overlay (`kustomization.yaml`)
still declared the pass on and set the bridge to one replica. Completed
retirement rows for the census population were unavailable.

## Playerbots starts death knights at the heroic level

The dev overlay's `playerbots.overrides.conf` set `Playerbots.DisableRandomLevels = 1`,
`Playerbots.RandombotStartingLevel = 1` and `Playerbots.RandomBotXPRate = 1.0`.
`Playerbots.RandomBotFixedLevel` and `Playerbots.LevelBrackets.Enabled` were
off, as were the defaults for `Playerbots.DowngradeMaxLevelBot` and
`Playerbots.ResetBotLevel.Enabled`. The range from `RandomBotMinLevel` to
`RandomBotMaxLevel` was 1 to 60. `worldserver.overrides.conf` set `MaxPlayerLevel = 60`.

With randomized levels disabled, `RandomPlayerbotMgr::RandomizeFirst` starts
ordinary bots at the configured starting level. It gives death knights
the greater of that value and the core's heroic starting level, documented
as 55 in the overlay. `Playerbots.DisableDeathKnightLogin = 0` allowed them
to log in. The heroic start shortens their path to 60, and the exemption lets
them stay there. [Pinned playerbots level settings](https://github.com/quadseven/mod-playerbots/blob/40884e9c135c1daf27ffd894a6047502a5701130/conf/playerbots.conf.dist#L804-L870),
[pinned level reset default](https://github.com/quadseven/mod-playerbots/blob/40884e9c135c1daf27ffd894a6047502a5701130/conf/playerbots.conf.dist#L1082-L1085)
and [pinned-source read in #2617](https://github.com/quadseven/wow-overseer/issues/2617).

## Quest and travel options for guildless bots

The deployment set `Playerbots.AutoTeleportForLevel = 1` and limited teleport
destinations to the classic continents with `Playerbots.RandomBotMaps = 0,1`.
New RPG defaults to on and weights questing,
grinding and flight. `NewRpgBaseAction::CheckRpgStatusAvailable` checks for
an eligible quest point, a cached grind or camp destination, or a usable
flight path for each corresponding action. At levels 40 to 60 the unpatched
grind and camp selectors search within 2,500 yards and, outside capitals,
within the current zone. With no weighted action available,
`RandomChangeStatus` sits the bot down to rest. Patch 0050 adds a same-map
fallback for grind and camp when the current zone offers no destination. It
records low-level examples, and the census has no time of day to compare with
the patch's November 15 rollout. [Pinned RPG settings](https://github.com/quadseven/mod-playerbots/blob/40884e9c135c1daf27ffd894a6047502a5701130/conf/playerbots.conf.dist#L1419-L1447)
and [pinned RPG action selection](https://github.com/quadseven/mod-playerbots/blob/40884e9c135c1daf27ffd894a6047502a5701130/src/Ai/World/Rpg/Action/NewRpgBaseAction.cpp#L975-L1293).

Overseer's guild jobs route guild members when the guild includes an enrolled
family member. The separate leveling route and quester loop serve roster
families and named questers. Outside those groups, guildless bots rely on
playerbots for ordinary quest and grind XP. The census cannot establish
whether questing, travel or combat also stalled XP in the 40 to 60 band.
[Guild leveling](../../guildlevel.py) and [bridge scheduler](../../bridge.py).

## Factory refills attempt warriors and paladins first

`RandomPlayerbotFactory::CreateRandomBots` walks class IDs from
`CLASS_WARRIOR` to below `MAX_CLASSES - count`. The issue cites that loop at
the pin. The earlier local revision confirms that `count` is the number of
existing characters on the account. An empty account attempts each enabled
playable class. A partial account starts again at warrior and stops earlier.
It can attempt another warrior or paladin and skip a missing later class,
such as priest. The world class mask excludes whole classes, and
`Playerbots.RandomClassSpecProb.<class>.<specno>` chooses specs within a class.
`DeleteRandomBotAccounts` resets all random-bot accounts and defaults to off.
[Pinned-source read in #2617](https://github.com/quadseven/wow-overseer/issues/2617),
[earlier factory code](https://github.com/quadseven/mod-playerbots/blob/7bae1b5c58c76a0aa20381155edc08096d1485b2/src/Bot/Factory/RandomPlayerbotFactory.cpp#L682-L744),
[pinned spec settings](https://github.com/quadseven/mod-playerbots/blob/40884e9c135c1daf27ffd894a6047502a5701130/conf/playerbots.conf.dist#L2196-L2202)
and [pinned account reset setting](https://github.com/quadseven/mod-playerbots/blob/40884e9c135c1daf27ffd894a6047502a5701130/conf/playerbots.conf.dist#L108-L111).

Overseer retirement can leave the vacancies that trigger an ordered refill.
Recruitment chooses among existing characters and can change which classes
remain guildless. The size of the refill effect, and why paladins outnumbered
warriors, requires per-account class counts and records of successful
creations and retirements. An online sample also needs to account for
random-bot rotation. [Retirement selection](../../retire.py) and
[recruitment ranking](../../recruit.py).

## Configuration proposal

If the legacy cleanup is complete, set `RETIRE_FACTORY=off` so newly
eligible characters can keep their earned progress. Keep ordinary XP, the
level-1 start for non-heroic bots, the level-60 cap and classic travel limits.
Turning off retirement only affects future retirement requests.
Raising the starting level or enabling bracket redistribution would assign
levels without play.
[Bridge retirement gate](../../bridge.py) and
[pinned level settings](https://github.com/quadseven/mod-playerbots/blob/40884e9c135c1daf27ffd894a6047502a5701130/conf/playerbots.conf.dist#L804-L870).

## Evidence limits and follow-ups

The deployment history and repository fixture agree on playerbots
`40884e9c135c1daf27ffd894a6047502a5701130`. The full RPG destination-selection
file, pinned config, deployment patches and pinned Overseer retirement code
were read. The full pinned factory, random-bot manager, core heroic start,
RPG scheduler and travel manager were not read. The earlier pinned-source
observations come from the issue. [Pinned factory source](https://github.com/quadseven/mod-playerbots/blob/40884e9c135c1daf27ffd894a6047502a5701130/src/Bot/Factory/RandomPlayerbotFactory.cpp)
and [pinned random-bot manager source](https://github.com/quadseven/mod-playerbots/blob/40884e9c135c1daf27ffd894a6047502a5701130/src/Bot/RandomPlayerbotMgr.cpp).

- Measure guildless XP and retirement between levels 40 and 60. Compare
  anonymized XP changes, online time, zone and quest or kill activity with
  applied retire rows and the worldserver build running during the sample.
- Reconcile random-bot class counts across retirements and factory refills.
  Read the full pinned factory and compare per-account class counts before
  and after refill, separating stored random bots, add-class accounts and
  the online rotation.
