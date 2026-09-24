import dungeonquests


def test_plans_eligible_quest_at_giver_and_turns_in_completed_quest():
    quest = dungeonquests.Quest(
        quest_id=100,
        zone=1581,
        min_level=18,
        races=1,
        prev_quest_id=0,
        starter=500,
        ender=500,
    )
    facts = dungeonquests.Facts(
        dungeon="deadmines",
        quests=(quest,),
        members=(
            dungeonquests.Member("Grug", level=20, race=1, map_id=0, x=10, y=10, z=0),
        ),
        rewarded=frozenset(),
        statuses={"Grug": {100: dungeonquests.STATUS_NONE}},
        spawn=(0, 10, 10, 0),
        due=True,
    )

    take = dungeonquests.step(facts)
    assert take.rows == (("Grug", "take quest:100"),)
    assert take.release

    complete = facts.with_status("Grug", 100, dungeonquests.STATUS_COMPLETE)
    turnin = dungeonquests.step(complete)
    assert turnin.rows == (("Grug", "turnin quest:100"),)


def test_walks_to_the_giver_before_writing_rows():
    quest = dungeonquests.Quest(100, 1581, 18, 1, 0, 500, 500)
    facts = dungeonquests.Facts(
        dungeon="deadmines",
        quests=(quest,),
        members=(dungeonquests.Member("Grug", level=20, race=1, map_id=0),),
        statuses={"Grug": {100: dungeonquests.STATUS_NONE}},
        spawn=(0, 100, 100, 0),
        due=True,
    )
    step = dungeonquests.step(facts)
    assert step.aim == 500
    assert step.hold_planner
    assert not step.rows


def test_planner_rejects_low_wrong_faction_missing_prerequisite_and_done():
    rows = [
        {"quest": 1, "zone": 1581, "min_level": 20, "races": 1, "prev_quest": 0},
        {"quest": 2, "zone": 1581, "min_level": 1, "races": 2, "prev_quest": 0},
        {"quest": 3, "zone": 1581, "min_level": 1, "races": 0, "prev_quest": 99},
        {"quest": 4, "zone": 1581, "min_level": 1, "races": 0, "prev_quest": 0},
    ]
    assert (
        dungeonquests.open_quests(
            rows,
            rewarded={"Grug": {4}},
            members=(dungeonquests.Member("Grug", level=19, race=1),),
        )
        == {}
    )
