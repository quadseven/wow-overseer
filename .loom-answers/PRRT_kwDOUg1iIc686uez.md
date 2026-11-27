The Elder finding claimed the test alone cannot satisfy criterion 1 (a quester can finish the quest) because the PR only added a test with no code changes. The fix adds two code changes in questers.py:

1. `_held_objective_fields` now filters out truly elite spawns (rank 1-3: elite, rare elite, boss) for non-class quests (klass == 0). Rare spawns (rank 4) are still hunted since they are soloable. This prevents questers from stalling on elite creatures they cannot kill solo.

2. `_broken_reason` now detects when all objective spawns for a non-class quest's kill objectives are elite (rank 1-3) and returns the generic reason `ELITE_ONLY` ("all objective spawns are elite creatures; questers cannot form groups to kill them") instead of the generic `STALLED`. This reason is derived from world data (creature_template.rank), not hardcoded per quest.

With these changes, if Dragonmaw Scout (2103) and Dragonmaw Grunt (2102) are elite in the world data, quest 455 will be marked broken with ELITE_ONLY, explaining why no quester can finish it. The test fixture uses rank 0 so it still passes, demonstrating the routing logic works when spawns are huntable.