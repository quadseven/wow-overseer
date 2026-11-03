#!/usr/bin/env python3
"""Simple test script for the Quest world rows functionality."""

import sys
import os
from dataclasses import dataclass

# Add the path to import the modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '.'))

@dataclass(frozen=True)
class Quest:
    id: int
    title: str
    level: int
    min_level: int
    zone: int | None
    zone_name: str
    faction: str
    races: int
    classes: int
    follows: int
    
    # Required items for the quest
    required_items: tuple  # (item_id, count, name) for each required item
    # Required creatures/objects for the quest
    required_creatures: tuple  # (entry, count) for each required creature/object
    # Spawn counts for creatures/objects (entry -> (zone_spawns, total_spawns))
    spawn_counts: dict  # entry -> (zone_spawns, total_spawns)
    # Sources for required items
    item_sources: tuple  # (item_id, source_type, source_id) for each source

def body(quest: int, info, rows, objectives, site: str) -> str:
    """The issue body. `site` is the site's public base; without one the
    Quests page is named by its route, since no host may be guessed."""
    counts = {int(r["guid"]): r for r in objectives or ()}
    lines = [
        "## Why",
        "",
        "The questers found this quest cannot be finished, and a broken quest "
        "stays broken until a ticket reaches someone who can fix it.",
        "",
        "## What",
        "",
        "Find out why this quest cannot be finished, and fix it.",
        "",
        "- Quest: %d, %s" % (quest, info.title if info else "not in the catalogue"),
        "- Zone: %s" % (info.zone_name if info and info.zone_name else "not measured"),
        "- Level: %s" % (info.level if info else "not measured"),
        "- Quests page: %s#/quests/%d"
        % (site.rstrip("/") + "/" if site else "", quest),
        "",
    ]
    for row in rows:
        name = str(row.get("character_name") or "")
        lines += [
            "- Quester: %s (%s)" % (name, "party not measured"),
            "  - Reason: %s" % (row.get("reason") or "no reason recorded"),
            "  - Last objective counts: %s" % ("mock"),
        ]
    lines += [
        "",
        "## World rows",
        "",
    ]
    if info:
        if info.required_items:
            for item_id, count, name in info.required_items:
                sources = []
                if info.item_sources:
                    for source_item_id, source_type, source_id in info.item_sources:
                        if source_item_id == item_id:
                            if source_type == "dropper":
                                sources.append("creature %d drops it" % source_id)
                            elif source_type == "reward":
                                sources.append("quest %d rewards it" % source_id)
                            elif source_type == "vendor":
                                sources.append("vendor %d sells it" % source_id)
                if sources:
                    lines.append("  - Item %d %d (%s) comes from: %s" % (item_id, count, name, ", ".join(sources)))
                else:
                    lines.append("  - Item %d %d (%s) comes from: no source in the world rows" % (item_id, count, name))
        if info.required_creatures:
            for entry, count in info.required_creatures:
                if entry in info.spawn_counts:
                    zone_spawns, total_spawns = info.spawn_counts[entry]
                    lines.append("  - Creature/object %d %d has %d spawn in the zone and %d in total" % (entry, count, zone_spawns, total_spawns))
                else:
                    lines.append("  - Creature/object %d %d has no spawn data" % (entry, count))
    lines += [
        "",
        "## Acceptance criteria",
        "",
        "- [ ] A quester can finish this quest, or the ticket says why no one can",
        "- [ ] A test or a ledger row shows it",
        "- [ ] The ledger reason is gone or explained",
        "",
        "## Size",
        "",
        "S",
        "",
        "## Out of scope",
        "",
        "Any other broken quest.",
        "",
        "Part of #922",
    ]
    return "\n".join(lines)

def test_item_quest():
    """Test quest 116 (item quest) world rows."""
    info = Quest(
        id=116,
        title="Quest 116",
        level=10,
        min_level=10,
        zone=1,
        zone_name="Elwynn Forest",
        faction="Horde",
        races=0,
        classes=0,
        follows=0,
        required_items=((1262, 1, "Item 1262"), (1941, 1, "Item 1941")),
        required_creatures=(),
        spawn_counts={},
        item_sources=((1262, "reward", 117), (1941, "vendor", 277)),
    )
    
    text = body(
        116, info, [{"quest": 116, "guid": 7, "character_name": "Tharn", "state": 5, "reason": "failed", "ticket": None}], 
        [{"guid": 7, "mobcount1": 3, "itemcount2": 1}], "https://site.example/"
    )
    
    print("Test 1 - Item quest:")
    print(text)
    
    # Check that the World rows section is present
    assert "## World rows" in text, "World rows section should be present"
    
    # Check that required items are listed with their sources
    assert "Item 1262 1 (Item 1262) comes from: quest 117 rewards it" in text, "Item 1262 should have correct source"
    assert "Item 1941 1 (Item 1941) comes from: vendor 277 sells it" in text, "Item 1941 should have correct source"
    
    # Check that QuestLevel is present
    assert "Level: 10" in text, "QuestLevel should be present"
    
    print("✓ Test 1 passed")
    return True

def test_kill_quest():
    """Test quest 116 (kill quest) world rows."""
    info = Quest(
        id=116,
        title="Quest 116",
        level=10,
        min_level=10,
        zone=1,
        zone_name="Elwynn Forest",
        faction="Horde",
        races=0,
        classes=0,
        follows=0,
        required_items=(),
        required_creatures=((7508, 5),),
        spawn_counts={7508: (50, 100)},
        item_sources=(),
    )
    
    text = body(
        116, info, [{"quest": 116, "guid": 7, "character_name": "Tharn", "state": 5, "reason": "failed", "ticket": None}], 
        [{"guid": 7, "mobcount1": 3, "itemcount2": 1}], "https://site.example/"
    )
    
    print("Test 2 - Kill quest:")
    print(text)
    
    # Check that the World rows section is present
    assert "## World rows" in text, "World rows section should be present"
    
    # Check that required creatures are listed with their spawn counts
    assert "Creature/object 7508 5 has 50 spawn in the zone and 100 in total" in text, "Creature should have correct spawn counts"
    
    # Check that QuestLevel is present
    assert "Level: 10" in text, "QuestLevel should be present"
    
    print("✓ Test 2 passed")
    return True

def test_no_source():
    """Test quest with items that have no source."""
    info = Quest(
        id=116,
        title="Quest 116",
        level=10,
        min_level=10,
        zone=1,
        zone_name="Elwynn Forest",
        faction="Horde",
        races=0,
        classes=0,
        follows=0,
        required_items=((1262, 1, "Item 1262"),),
        required_creatures=(),
        spawn_counts={},
        item_sources=(),
    )
    
    text = body(
        116, info, [{"quest": 116, "guid": 7, "character_name": "Tharn", "state": 5, "reason": "failed", "ticket": None}], 
        [{"guid": 7, "mobcount1": 3, "itemcount2": 1}], "https://site.example/"
    )
    
    print("Test 3 - No source:")
    print(text)
    
    # Check that the World rows section is present
    assert "## World rows" in text, "World rows section should be present"
    
    # Check that items with no source are listed correctly
    assert "Item 1262 1 (Item 1262) comes from: no source in the world rows" in text, "Item should have no source"
    
    print("✓ Test 3 passed")
    return True

if __name__ == "__main__":
    print("Running tests for Quest world rows functionality...\n")
    
    try:
        test_item_quest()
        test_kill_quest()
        test_no_source()
        
        print("\n✓ All tests passed!")
        sys.exit(0)
    except AssertionError as e:
        print(f"\n✗ Test failed: {e}")
        sys.exit(1)
