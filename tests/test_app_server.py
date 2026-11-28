"""The Server view: a verdict band with the eye's age, each number once,
watcher tiles drawn, What's Live styled and toned, Upstream collapsed.

Run under node against small stand-ins for the browser, like the other app
view tests: the markup is checked as text. Fixtures follow the live reads'
shapes (the eye's tiers and strip, the watcher tiles, whats-live, upstream).
"""

import json
import pathlib
import re
import unittest
from datetime import datetime, timedelta, timezone

from test_app_flagship import app_file, needs_node
from test_app_shell import node_module

HERE = pathlib.Path(__file__).resolve().parent.parent


def iso_seconds_ago(seconds):
    when = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=seconds)
    return when.isoformat()


def tier(name, state, hue, value, headline, switch=""):
    return {
        "tier": name,
        "state": state,
        "hue": hue,
        "value": value,
        "headline": headline,
        "switch": switch,
    }


def all_on_eye(generated_at, tiles=None):
    return {
        "generated_at": generated_at,
        "tiers": [
            tier(
                "CHARACTER",
                "ON",
                "green",
                "20",
                "20 characters the module knows by name, of 5577 on the realm.",
            ),
            tier(
                "FAMILY",
                "ON",
                "green",
                "4",
                "4 families: Grug's (Bork, Grog, Grug, Og, Ugga); "
                "Jug's (Jork, Jrog, Jug, Oj, Ujja); "
                "Tug's (Ot, Tork, Trog, Tug, Utta); "
                "Zug's (Oz, Uzza, Zork, Zrog, Zug).",
            ),
            tier(
                "PARTY",
                "ON",
                "green",
                "4",
                "4 parties, one per family: Grug's family behind 1062, "
                "Jug's family behind 10758, Tug's family behind 10767, "
                "Zug's family behind 1630.",
            ),
            tier("GUILD", "ON", "green", "24", "24 guilds on the realm."),
            tier(
                "REALM",
                "ON",
                "green",
                "2603",
                "2603 souls in the world, 2603 of them played by the machine.",
            ),
        ],
        "strip": [
            {"label": "CHARACTERS", "value": "5577"},
            {"label": "IN WORLD", "value": "2603"},
            {"label": "FAMILIES", "value": "4"},
            {"label": "GUILDS", "value": "24"},
            {"label": "TIERS ON", "value": "5/5"},
        ],
        "honest": "Every tier is real. Nothing on this page is a placeholder "
        "for something that does not exist yet.",
        "tiles": tiles if tiles is not None else [],
    }


def render_server(eye):
    reads = {
        "/api/eye": {"data": eye, "error": None, "loading": False, "at": 1},
    }
    script = (
        "const reads = %s;"
        "const ctx = { get: (k) => reads[k] || "
        "{ data: null, error: null, loading: true, at: 0 } };"
        "console.log(JSON.stringify(M.default.render(ctx).s));"
    ) % json.dumps(reads)
    return node_module("views/server.js", script)


def row_for(markup, name):
    rows = markup.split('class="tier"')
    for row in rows[1:]:
        if ">%s<" % name in row.split('class="tier-state"')[0]:
            return row
    raise AssertionError("no tier row for %s" % name)


@needs_node
class TheVerdictBand(unittest.TestCase):
    def test_realm_up_fresh_eye_and_no_note_card(self):
        out = render_server(all_on_eye(iso_seconds_ago(22)))
        self.assertIn("verdict-band", out)
        self.assertIn('data-tone="ok"', out)
        self.assertIn("Realm up", out)
        self.assertIn("Eye read", out)
        self.assertRegex(out, r"Eye read \d+s ago")
        self.assertNotIn("server-note", out)
        self.assertNotIn("Every tier is real", out)

    def test_stale_eye_never_renders_a_clean_green_verdict(self):
        out = render_server(all_on_eye(iso_seconds_ago(300)))
        self.assertNotIn('data-tone="ok"', out)
        self.assertIn('data-tone="warn"', out)
        self.assertIn("Stale", out)

    def test_partial_verdict_names_the_offending_tier(self):
        eye = all_on_eye(iso_seconds_ago(10))
        eye["tiers"][2] = tier(
            "PARTY",
            "PARTIAL",
            "amber",
            "3",
            "2 groups, not one: Grug's family is split.",
            "Each family behind one leader again.",
        )
        out = render_server(eye)
        self.assertIn("Realm partial: Party partial", out)
        self.assertIn('data-tone="warn"', out)

    def test_off_tier_turns_the_band_bad_and_is_named(self):
        eye = all_on_eye(iso_seconds_ago(10))
        eye["tiers"][3] = tier(
            "GUILD",
            "OFF",
            "vermilion",
            "0",
            "No guild exists on this realm.",
            "A charter with 9 signatures.",
        )
        out = render_server(eye)
        self.assertIn("Realm partial: Guild off", out)
        self.assertIn('data-tone="bad"', out)

    def test_each_number_once(self):
        out = render_server(all_on_eye(iso_seconds_ago(22)))
        # The strip's TIERS ON duplicates the verdict band's own count.
        self.assertNotIn("TIERS ON", out)
        self.assertNotIn("5/5", out)
        # Family, Guild and Realm tier values duplicate strip KPIs.
        self.assertNotIn('dim num">4<', row_for(out, "Family"))
        self.assertNotIn('dim num">24<', row_for(out, "Guild"))
        self.assertNotIn('dim num">2603<', row_for(out, "Realm"))
        # The Character value stays, labelled as the named count.
        self.assertIn("20 named", row_for(out, "Character"))

    def test_unknown_hue_maps_to_warn_never_grey(self):
        eye = all_on_eye(iso_seconds_ago(10))
        eye["tiers"][0] = tier(
            "CHARACTER", "ON", "purple", "20", "20 characters the module knows by name."
        )
        out = render_server(eye)
        self.assertIn("var(--warn)", row_for(out, "Character"))
        self.assertNotIn("var(--color-neutral-500)", row_for(out, "Character"))

    def test_headlines_clamp_and_party_identifiers_get_a_label(self):
        out = render_server(all_on_eye(iso_seconds_ago(10)))
        self.assertIn("tier-detail", out)
        self.assertIn("behind group 1062", out)
        self.assertNotIn("behind 1062", out)

    def test_non_on_tiers_sort_to_the_top(self):
        eye = all_on_eye(iso_seconds_ago(10))
        eye["tiers"][2] = tier(
            "PARTY",
            "PARTIAL",
            "amber",
            "3",
            "2 groups, not one: Grug's family is split.",
            "Each family behind one leader again.",
        )
        out = render_server(eye)
        tiers_at = out.index('id="sv-tiers"')
        self.assertLess(
            out.index(">Party<", tiers_at), out.index(">Character<", tiers_at)
        )

    def test_watcher_tiles_row_shows_the_no_frame_tile(self):
        tiles = [
            {
                "name": "Grug",
                "live": True,
                "frame_age_seconds": 1,
                "frame_state": "fresh",
                "frame_source": "frame",
            },
            {
                "name": "Zug",
                "live": True,
                "frame_age_seconds": None,
                "frame_state": "no_frame",
                "frame_source": None,
            },
        ]
        out = render_server(all_on_eye(iso_seconds_ago(10), tiles))
        self.assertIn("Watcher frames", out)
        self.assertIn("Grug", out)
        self.assertIn("No frame", out)
        self.assertIn("var(--warn)", out)

    def test_anchor_chips_point_at_the_sections(self):
        out = render_server(all_on_eye(iso_seconds_ago(10)))
        for target in ("sv-tiers", "sv-live", "sv-upstream"):
            self.assertIn('data-goto="%s"' % target, out)
            self.assertIn('id="%s"' % target, out)


def whats_live_payload(**over):
    # Fixture hashes are invented hex, not readings from any deployment;
    # only their shapes (lengths, the sha256: prefix) are realistic.
    payload = {
        "checked_at": "2026-11-27T21:30:09Z",
        "bridge": {
            "commit": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1",
            "short": "a1a1a1a1a1a1",
            "digest": "sha256:" + "b2" * 32,
            "deployed_at": "2026-11-27T20:40:01Z",
            "deployed_seconds": 1795812001,
            "ship_pr": 3384,
        },
        "realm": {
            "state": "UP",
            "module_commit": "c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3",
            "core_revision": "d4d4d4d4d4d4",
            "started_at": "2026-11-25T00:23:13Z",
            "pins": "match",
        },
        "prs_state": "ready",
        "window_hours": 48,
        "prs": [
            {
                "repo": "quadseven/wow-overseer",
                "component": "bridge",
                "number": 3384,
                "title": "Ship the thing",
                "merge_commit": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1",
                "merge_short": "a1a1a1a1a1a1",
                "merged_at": "2026-11-27T20:00:00Z",
                "refs": [],
                "url": "https://example.com/pull/3384",
                "state": "live-proven",
            },
            {
                "repo": "quadseven/mod-overseer",
                "component": "module",
                "number": 1568,
                "title": "A module change",
                "merge_commit": "c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3",
                "merge_short": "c3c3c3c3c3c3",
                "merged_at": "2026-11-27T19:00:00Z",
                "refs": [],
                "url": "https://example.com/pull/1568",
                "state": "merged",
            },
        ],
        "unmeasured": {},
    }
    payload.update(over)
    return payload


def render_whats_live(payload):
    read = {"data": payload, "error": None, "loading": False, "at": 1}
    return node_module(
        "views/whatslive.js",
        "console.log(JSON.stringify(M.whatsLiveSection(%s, %d).s));"
        % (json.dumps(read), 1795812060),
    )


@needs_node
class WhatsLiveStyledAndToned(unittest.TestCase):
    def test_pr_state_tags_are_toned(self):
        out = render_whats_live(whats_live_payload())
        rows = out.split('class="upstream-row"')
        proven = [r for r in rows if "Live proven" in r]
        merged = [r for r in rows if ">Merged<" in r]
        self.assertEqual(len(proven), 1)
        self.assertEqual(len(merged), 1)
        self.assertIn("tag-ok", proven[0])
        self.assertIn("tag-neutral", merged[0])

    def test_ship_pr_is_a_link_when_the_pr_is_listed(self):
        out = render_whats_live(whats_live_payload())
        self.assertIn(
            'href="https://example.com/pull/3384" target="_blank" '
            'rel="noopener">#3384</a>',
            out,
        )

    def test_realm_state_reads_up_not_up(self):
        out = render_whats_live(whats_live_payload())
        self.assertIn('<span class="v">Up</span>', out)
        self.assertNotIn('<span class="v">UP</span>', out)

    def test_verdict_sentence_leads_the_fold(self):
        out = render_whats_live(whats_live_payload())
        self.assertIn("<details", out)
        self.assertIn("pins match", out)
        self.assertIn("1 live proven", out)
        self.assertIn("1 merged", out)

    def test_checking_keeps_the_last_good_list_under_a_stale_banner(self):
        out = render_whats_live(whats_live_payload(prs_state="checking"))
        self.assertIn("Ship the thing", out)
        self.assertIn("last good", out)

    def test_digest_can_be_copied_in_full(self):
        out = render_whats_live(whats_live_payload())
        self.assertIn('data-copy="sha256:' + "b2" * 32 + '"', out)

    def test_all_four_pr_state_tones(self):
        prs = []
        for n, state in enumerate(
            ["live-proven", "deployed", "merged", "unknown"], start=1
        ):
            prs.append(
                {
                    "repo": "quadseven/wow-overseer",
                    "component": "bridge",
                    "number": 100 + n,
                    "title": "PR %s" % state,
                    "merge_commit": "a1a1a1a1a1a1",
                    "merge_short": "a1a1a1a1a1a1",
                    "merged_at": "2026-11-27T20:00:00Z",
                    "refs": [],
                    "url": "https://example.com/pull/%d" % (100 + n),
                    "state": state,
                }
            )
        out = render_whats_live(
            whats_live_payload(
                prs=prs,
                bridge={
                    "commit": "unknown",
                    "digest": "unknown",
                    "deployed_at": "unknown",
                    "ship_pr": None,
                },
            )
        )
        rows = out.split('class="upstream-row"')
        tones = {
            "live-proven": "tag-ok",
            "deployed": "tag-accent",
            "merged": "tag-neutral",
            "unknown": "tag-outline",
        }
        for state, tone in tones.items():
            row = [r for r in rows if "PR %s" % state in r]
            self.assertEqual(len(row), 1, state)
            self.assertIn(tone, row[0], state)

    def test_verdict_names_no_window_the_read_did_not_report(self):
        payload = whats_live_payload()
        del payload["window_hours"]
        out = render_whats_live(payload)
        self.assertIn("1 live proven, 1 merged.", out)
        self.assertNotIn("48 hours", out)

    def test_the_section_classes_are_styled(self):
        css = (HERE / "app" / "views" / "server.css").read_text(encoding="utf-8")
        for selector in (".panel", ".kpis", ".tag-ok", ".verdict-band"):
            self.assertIn(selector, css)
        self.assertIn("views/server.css", app_file("views/server.js"))


def upstream_row(label, status, behind=None, counts=None, **over):
    row = {
        "label": label,
        "status": status,
        "pinned": "abc1234" if status != "not measured" else None,
        "head": "def5678",
        "behind": behind,
        "counts": counts,
        "repo": "acore/example",
        "url": "https://example.com/compare",
        "notable": [],
        "pinned_at": None,
        "checked_at": None,
        "stale": False,
        "carried": 0,
        "role": "upstream",
        "reason": "",
    }
    row.update(over)
    return row


def render_upstream(rows, **data_over):
    data = {"rows": rows, "checked_at": None, "state": "ready"}
    data.update(data_over)
    read = {"data": data, "error": None, "loading": False, "at": 1}
    return node_module(
        "views/upstream.js",
        "console.log(JSON.stringify(M.upstreamSection(%s, %d).s));"
        % (json.dumps(read), 1795812060),
    )


@needs_node
class UpstreamCollapsed(unittest.TestCase):
    def test_all_unmeasured_is_one_compact_card(self):
        rows = [upstream_row("Proj %d" % n, "not measured") for n in range(8)]
        out = render_upstream(rows)
        self.assertIn("ud-compact", out)
        self.assertNotIn('class="card ud-row"', out)
        for n in range(8):
            self.assertIn("Proj %d" % n, out)

    def test_hot_rows_sort_first_then_most_behind(self):
        rows = [
            upstream_row(
                "Plain behind", "behind", behind=3, counts={"security": 0, "crash": 0}
            ),
            upstream_row(
                "Hot behind", "behind", behind=1, counts={"security": 2, "crash": 0}
            ),
            upstream_row(
                "Far behind", "behind", behind=9, counts={"security": 0, "crash": 0}
            ),
            upstream_row("Current one", "current", behind=0),
        ]
        out = render_upstream(rows)
        self.assertLess(out.index("Hot behind"), out.index("Far behind"))
        self.assertLess(out.index("Far behind"), out.index("Plain behind"))
        self.assertLess(out.index("Plain behind"), out.index("Current one"))

    def test_verdict_tag_carries_count_and_tone(self):
        rows = [
            upstream_row("Hot", "behind", behind=12, counts={"security": 2, "crash": 0})
        ]
        out = render_upstream(rows)
        self.assertIn("12 behind, 2 security", out)
        self.assertIn("tag-warn", out)
        self.assertIn("ud-hot", out)

    def test_mixed_rows_keep_unmeasured_rows_compact(self):
        rows = [
            upstream_row(
                "Measured", "behind", behind=2, counts={"security": 0, "crash": 0}
            ),
            upstream_row("Unmeasured", "not measured"),
        ]
        out = render_upstream(rows)
        self.assertEqual(out.count('class="card ud-row"'), 1)
        compact = out.split("ud-compact", 1)[1]
        self.assertIn("Unmeasured", compact)

    def test_summary_never_sums_counts_the_server_did_not_report(self):
        rows = [upstream_row("Behind", "behind", behind=2, counts=None)]
        out = render_upstream(rows)
        self.assertIn("crash or security not measured", out)

    def test_methodology_note_becomes_a_fold_below_the_rows(self):
        rows = [upstream_row("One", "current", behind=0)]
        out = render_upstream(rows)
        self.assertIn("How this is worked out", out)
        self.assertLess(out.index("One"), out.index("How this is worked out"))

    def test_fold_summary_counts_and_opens_only_when_hot(self):
        calm = render_upstream(
            [
                upstream_row(
                    "Behind", "behind", behind=2, counts={"security": 0, "crash": 0}
                ),
                upstream_row(
                    "Current",
                    "current",
                    behind=0,
                    counts={"security": 0, "crash": 0},
                ),
            ]
        )
        self.assertIn("1 of 2 projects behind, 0 crash or security", calm)
        first_fold = re.search(r"<details[^>]*>", calm).group(0)
        self.assertNotIn(" open", first_fold)
        hot = render_upstream(
            [
                upstream_row(
                    "Hot", "behind", behind=2, counts={"security": 1, "crash": 0}
                ),
            ]
        )
        first_fold = re.search(r"<details[^>]*>", hot).group(0)
        self.assertIn(" open", first_fold)


if __name__ == "__main__":
    unittest.main()
