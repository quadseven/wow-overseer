# Family meter shows zero healing: are healers healing? (#576)

Verdict: the meter is not missing healing events. Nobody in either family took enough damage to need a heal, so zero is the expected reading. No code bug was found; no PR was opened.

## Who heals

Source: `overseer_raid_spec` and `characters` on the wow-dev realm, read-only, 2026-10-05.

| Family | Member | Class | Tree | Duty |
|---|---|---|---|---|
| Grug | Grug | Warrior | Protection | main tank |
| Grug | Bork | Rogue | Combat | melee |
| Grug | Grog | Paladin | Retribution | melee |
| Grug | Og | Mage | Frost | caster |
| Grug | Ugga | Priest | Holy | healer |
| Zug | Zug | Warrior | Protection | main tank |
| Zug | Oz | Mage | Fire | caster |
| Zug | Uzza | Priest | Holy | healer |
| Zug | Zork | Druid | Feral Combat | melee |
| Zug | Zrog | Shaman | Enhancement | melee |

- Ugga and Uzza are the only healers. Grog is a Retribution paladin, so his low mana (the "Waiting on Grog (low mana)" hold) is a melee-paladin mana issue, not a healer issue, and does not bear on healing.
- Ugga's playerbots combat strategy string includes `+holy heal`, `+cure`, `+save mana`, `+potions`; her non-combat string includes `+food`. The strategies are heal-capable. Grog's strings carry `+dps`, `+behind`, `+baoe` (melee).
- The Zug family shows the same shape: Zrog (Enhancement shaman) is the one logged as "Waiting on Zrog (low mana)".

## Does the meter capture heals

Capture path, all primary source:

- Core: `Unit::DealHeal` calls `sScriptMgr->OnHeal(healer, victim, gain)` after `ModifyHealth` (azerothcore-wotlk `src/server/game/Entities/Unit/Unit.cpp`). `Unit::HealBySpell` routes through `DealHeal`. `ScriptMgr::OnHeal` dispatches to every `UnitScript` that enabled `UNITHOOK_ON_HEAL`.
- Module: `OverseerMeterScript` (`src/mod_overseer.cpp` in mod-overseer) enables both `UNITHOOK_ON_DAMAGE` and `UNITHOOK_ON_HEAL`. `OnHeal` returns when `!gain || !healer`, otherwise calls `Note(..., MeterKind::Healing, gain)`; `MeterRecord` in `src/overseer_decisions.cpp` adds it to `totals.healing`, and the JSON emits `healing` and `hps`. The hook is wired and the damage hook beside it is demonstrably working (see below).
- Meter API: `GET /api/meter` in `map_server.py` and `meter.py` in wow-overseer pass `healing` and `hps` through unchanged.

Raw data, `/api/meter` polled 15 times over about 90 seconds on 2026-10-05:

| Member | max healing | max damage taken | max damage done | max HP |
|---|---|---|---|---|
| Grug | 0 | 259 | 4462 | 2531 |
| Grog | 0 | 105 | 3622 | 2237 |
| Ugga | 0 | 81 | 620 | 1460 |
| Zug | 0 | 149 | 3222 | 1169 |
| Zork | 0 | 91 | 589 | 1130 |
| Uzza | 0 | 0 | 384 | 832 |

The damage and taken columns prove the hooks run for roster members. The worst-hit member (Grug, the tank) lost at most 259 of 2531 HP, about 10 percent, spread over the fight. Playerbots healers do not cast at that level of damage, and the worldserver log shows both families' readiness checks reading "tank 100% HP, healer 100% mana" and the tanks at 99 to 100 percent HP throughout (`[playerbots.dungeonclear.pull]` lines, 2026-10-05 01:14).

## Caveats

- A positive healing sample was not observed live in this window, because no fight hurt anyone enough. The conclusion rests on the wired hook plus the damage-taken data, not on a captured heal. The first real test is a fight where a member drops under about 70 percent HP; if healing still reads 0 there, reopen.
- Comment drift in mod-overseer: the `MeterKind` comment says healing is "raw, overheal included: the core's OnHeal hook carries the amount cast". The core passes `gain`, the HP actually restored from `ModifyHealth`, so overheal is excluded and a heal on a full-health target records nothing. This is a doc inaccuracy, not a capture bug, and too small for a tested PR.

## Resolution

The meter is correct. Healers are configured and capable. Zero healing reflects trivial incoming damage (at most 10 percent of max HP), which is a sign of an overgeared or overleveled pull, not a healing bug. No spec, strategy, or mana change is warranted on this evidence.
