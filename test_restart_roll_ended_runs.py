#!/usr/bin/env python3

"""
Test for worldserver roll ended runs filtering from uncleared_streak.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from datetime import datetime, timedelta
import dungeonpace as pace
from tests.test_dungeonpace import run, facts, head, members, ALLIANCE


def test_client_lost_during_restart_stays_at_door():
    """Test 1: A returned family whose only uncleared attempt ended in a client loss during a known restart window stays at the door."""
    # Create a run that ended during a restart
    # The run started before the worldserver restarted
    # It ends (or last progresses) before a worldserver start and was closed after it, or within the settle window after it
    start_before_restart = T0 - timedelta(hours=1)  # Started 1 hour before restart
    run_result = {
        "map_id": 48,
        "outcome": "client_lost",
        "started_at": start_before_restart,
    }

    # The family returns after the restart
    f = facts(
        head("blackfathom"),
        members(ALLIANCE),
        [run_result],
        returned=True,
    )

    decision = pace.decide(f)
    # Should stay at the door (STAY) because the client_lost run ended during a restart
    assert not decision.acts, f"Should stay at door, but got decision: {decision}"
    print("✓ Test 1 passed: client_lost during restart stays at door")


def test_wipe_outside_restart_steps_down():
    """Test 2: A returned family whose attempt ended in a wipe or a stall outside a restart still steps away at once."""
    # Create a run that happened outside of a restart window
    run_result = {
        "map_id": 48,
        "outcome": "wipe",
        "started_at": T0 - timedelta(minutes=5),  # Started well outside restart window
    }

    # The family returns
    f = facts(
        head("blackfathom"),
        members(ALLIANCE),
        [run_result],
        returned=True,
    )

    decision = pace.decide(f)
    # Should step down (ADVANCE) because the wipe happened outside restart window
    assert decision.kind == pace.ADVANCE, f"Should step down, but got decision: {decision}"
    assert "beat the family again" in decision.why, f"Should mention beating family again: {decision.why}"
    print("✓ Test 2 passed: wipe outside restart steps down")


def test_emptied_during_restart_stays():
    """Test 3: A returned family whose run ended with emptied during a restart stays at the door."""
    # Create a run that ended with emptied during restart
    start_before_restart = T0 - timedelta(hours=1)
    run_result = {
        "map_id": 48,
        "outcome": "emptied",
        "started_at": start_before_restart,
    }

    # The family returns after the restart
    f = facts(
        head("blackfathom"),
        members(ALLIANCE),
        [run_result],
        returned=True,
    )

    decision = pace.decide(f)
    # Should stay at the door because emptied during restart
    assert not decision.acts, f"Should stay at door, but got decision: {decision}"
    print("✓ Test 3 passed: emptied during restart stays at door")


def test_stalled_during_restart_stays():
    """Test 4: A returned family whose run ended with stalled during a restart stays at the door."""
    # Create a run that ended with stalled during restart
    start_before_restart = T0 - timedelta(hours=1)
    run_result = {
        "map_id": 48,
        "outcome": "stalled",
        "started_at": start_before_restart,
    }

    # The family returns after the restart
    f = facts(
        head("blackfathom"),
        members(ALLIANCE),
        [run_result],
        returned=True,
    )

    decision = pace.decide(f)
    # Should stay at the door because stalled during restart
    assert not decision.acts, f"Should stay at door, but got decision: {decision}"
    print("✓ Test 4 passed: stalled during restart stays at door")


def test_normal_client_lost_outside_restart_steps_down():
    """Test 5: A returned family whose run ended with client_lost outside a restart steps down."""
    # Create a run that ended with client_lost outside restart window
    run_result = {
        "map_id": 48,
        "outcome": "client_lost",
        "started_at": T0 - timedelta(minutes=1),  # Started well outside restart window
    }

    # The family returns
    f = facts(
        head("blackfathom"),
        members(ALLIANCE),
        [run_result],
        returned=True,
    )

    decision = pace.decide(f)
    # Should step down because client_lost happened outside restart window
    assert decision.kind == pace.ADVANCE, f"Should step down, but got decision: {decision}"
    assert "beat the family again" in decision.why, f"Should mention beating family again: {decision.why}"
    print("✓ Test 5 passed: normal client_lost outside restart steps down")


if __name__ == "__main__":
    T0 = datetime(2026, 9, 27, 16, 0, 0)

    print("Testing worldserver roll ended runs filtering...")
    test_client_lost_during_restart_stays_at_door()
    test_wipe_outside_restart_steps_down()
    test_emptied_during_restart_stays()
    test_stalled_during_restart_stays()
    test_normal_client_lost_outside_restart_steps_down()

    print("\n✓ All tests passed!")
