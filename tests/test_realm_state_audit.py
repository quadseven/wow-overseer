"""Tests for the read-only realm snapshot report."""

from io import BytesIO
from unittest.mock import patch
from urllib.error import URLError

from tools.realm_state_audit import build_report
from tools import realm_state_audit


def test_report_groups_roster_and_counts_only_seated_levels():
    roster = {
        "checked_at": 1000,
        "members": [
            {
                "name": "SampleA",
                "guild": "Cave",
                "level": 10,
                "zone": "Westfall",
                "online": True,
                "life": "alive",
            },
            {
                "name": "SampleB",
                "guild": "Cave",
                "level": 20,
                "zone": "Duskwood",
                "online": True,
                "life": "ghost",
            },
            {
                "name": "SampleC",
                "guild": "Cave",
                "level": 30,
                "zone": "Elwynn",
                "online": False,
                "life": None,
            },
            {
                "name": "SampleD",
                "guild": "Bonkers",
                "level": 40,
                "zone": "Barrens",
                "online": True,
                "life": "dead",
                "stuck": True,
                "since": 700,
                "blocker": "Waiting",
                "step": "Walking",
            },
        ],
    }
    raidteams = {
        "Cave": {
            "seated": 2,
            "members": {"SampleA": {"level": 10}, "SampleB": {"level": 20}},
        },
        "Bonkers": {"seated": 40, "members": {"SampleD": {"level": 40}}},
    }
    guilds = {
        "Cave": {
            "deaths": {"ghosts": [{"name": "SampleB", "where": "Duskwood", "at": 900}]}
        },
        "Bonkers": {"deaths": {"ghosts": []}},
    }

    report = build_report(roster, raidteams, guilds)

    cave = report["guilds"]["Cave"]
    assert cave["online_count"] == 2
    assert cave["online_members"][0]["member_id"] == "Cave-001"
    assert "name" not in cave["online_members"][0]
    assert cave["level_distribution"]["seat_count"] == 2
    assert cave["level_distribution"]["median"] == 15
    assert cave["level_distribution"]["lowest"] == 10
    assert cave["level_distribution"]["histogram"]["10"] == 1
    assert cave["level_distribution"]["histogram"]["20"] == 1
    assert sum(cave["level_distribution"]["histogram"].values()) == 2
    assert cave["offline_members"][0]["last_seen"] is None
    assert report["guilds"]["Bonkers"]["dead_members"][0]["duration_seconds"] is None
    assert report["guilds"]["Bonkers"]["stuck_members"][0]["duration_seconds"] == 300
    ghost = report["guilds"]["Cave"]["ghost_members"][0]
    assert ghost["location"] == "Duskwood"
    assert ghost["duration_seconds"] == 100
    assert ghost["member_id"] == "Cave-002"
    assert "name" not in ghost


def test_missing_raidteam_is_reported_with_an_empty_distribution():
    report = build_report(
        {"checked_at": 1000, "members": []}, {"Cave": {"members": {}}}
    )

    assert report["guilds"]["Bonkers"]["level_distribution"]["seat_count"] == 0


def test_missing_checked_at_is_reported_clearly():
    try:
        build_report({"members": []}, {"Cave": {}, "Bonkers": {}})
    except ValueError as exc:
        assert "checked_at" in str(exc)
    else:
        raise AssertionError("a roster without checked_at must not be accepted")


def test_non_object_roster_member_is_reported_clearly():
    try:
        build_report(
            {"checked_at": 1000, "members": [None]},
            {"Cave": {}, "Bonkers": {}},
        )
    except ValueError as exc:
        assert "member" in str(exc)
    else:
        raise AssertionError("a non-object roster member must not be accepted")


def test_api_network_error_names_the_endpoint():
    url = "https://example.com/api/roster"
    with patch.object(
        realm_state_audit.urllib.request, "urlopen", side_effect=URLError("offline")
    ):
        try:
            realm_state_audit.fetch_json(url)
        except RuntimeError as exc:
            assert url in str(exc)
        else:
            raise AssertionError("network failures must identify the endpoint")


def test_api_rejects_non_http_schemes_before_opening_them():
    with patch.object(realm_state_audit.urllib.request, "urlopen") as open_url:
        try:
            realm_state_audit.fetch_json("file:///private/config")
        except ValueError as exc:
            assert "http" in str(exc)
        else:
            raise AssertionError("non-HTTP URLs must be rejected")
        open_url.assert_not_called()


def test_api_parse_error_names_the_endpoint():
    url = "https://example.com/api/roster"
    with patch.object(
        realm_state_audit.urllib.request, "urlopen", return_value=BytesIO(b"not json")
    ):
        try:
            realm_state_audit.fetch_json(url)
        except RuntimeError as exc:
            assert url in str(exc)
        else:
            raise AssertionError("invalid JSON must identify the endpoint")
