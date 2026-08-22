"""Event-thought tests: snapshot pairs in -> events out, canned LLM voicing.

No live LLM, no live database - detection is pinned on hand-built snapshot
rows (real Geometry for zone names, since the names ARE the feature), and
voicing is pinned on canned model output. That is the seam infra#2602
demands: the world's deltas decide WHAT happened, the model only voices it.
"""
import unittest

import events
from events import Event
from transform import Geometry

GEO = Geometry.load(".")

# Real Kalimdor coordinates, verified against zones.json: DUROTAR_POS sits
# in Durotar outside the Ogrimmar rectangle, OGRIMMAR_POS in its center.
# The dbc data spells the city "Ogrimmar" - the tests pin that spelling on
# purpose so a well-meaning "fix" to the expected string fails loudly here
# instead of silently disagreeing with zones.json.
DUROTAR_POS = (0.0, -4700.0)
OGRIMMAR_POS = (1800.0, -4380.0)


def row(name, *, level=5, map_id=1, zone_id=14, pos=DUROTAR_POS,
        health=100, in_combat=0):
    return {
        "name": name, "level": level, "map_id": map_id, "zone_id": zone_id,
        "pos_x": pos[0], "pos_y": pos[1], "health": health, "in_combat": in_combat,
    }


class GeometryPreconditionTest(unittest.TestCase):
    def test_pinned_coordinates_resolve_to_the_expected_zone_names(self):
        self.assertEqual(GEO.zone_name(1, *DUROTAR_POS), "Durotar")
        self.assertEqual(GEO.zone_name(1, *OGRIMMAR_POS), "Ogrimmar")


class DetectLevelUpTest(unittest.TestCase):
    def test_level_up_emits_exactly_one_event(self):
        prev = {"Grug": row("Grug", level=4)}
        curr = {"Grug": row("Grug", level=5)}
        self.assertEqual(
            events.detect_events(prev, curr, GEO),
            [Event("level_up", "Grug", {"level": 5})],
        )

    def test_level_up_does_not_repeat_once_prev_catches_up(self):
        curr = {"Grug": row("Grug", level=5)}
        self.assertEqual(events.detect_events(curr, curr, GEO), [])

    def test_level_down_is_not_an_event(self):
        prev = {"Grug": row("Grug", level=5)}
        curr = {"Grug": row("Grug", level=4)}
        self.assertEqual(events.detect_events(prev, curr, GEO), [])


class DetectZoneChangeTest(unittest.TestCase):
    def test_zone_change_carries_zone_names_from_geometry(self):
        prev = {"Grug": row("Grug", zone_id=14, pos=DUROTAR_POS)}
        curr = {"Grug": row("Grug", zone_id=1637, pos=OGRIMMAR_POS)}
        self.assertEqual(
            events.detect_events(prev, curr, GEO),
            [Event("zone_change", "Grug",
                   {"from_zone": "Durotar", "to_zone": "Ogrimmar"})],
        )

    def test_same_zone_id_is_not_a_zone_change(self):
        prev = {"Grug": row("Grug", zone_id=14, pos=DUROTAR_POS)}
        curr = {"Grug": row("Grug", zone_id=14, pos=(-1300.0, -5600.0))}
        self.assertEqual(events.detect_events(prev, curr, GEO), [])

    def test_zone_id_change_with_identical_names_is_suppressed(self):
        # zones.json is coarser than zone_id; "left Durotar for Durotar"
        # reads as a glitch, so the event is dropped.
        prev = {"Grug": row("Grug", zone_id=14, pos=DUROTAR_POS)}
        curr = {"Grug": row("Grug", zone_id=999, pos=(-1300.0, -5600.0))}
        self.assertEqual(events.detect_events(prev, curr, GEO), [])


class DetectCombatTest(unittest.TestCase):
    def test_combat_entered_fires_on_the_transition_edge(self):
        prev = {"Grug": row("Grug", in_combat=0)}
        curr = {"Grug": row("Grug", in_combat=1)}
        self.assertEqual(
            events.detect_events(prev, curr, GEO),
            [Event("combat_entered", "Grug")],
        )

    def test_staying_in_combat_is_not_an_event(self):
        prev = {"Grug": row("Grug", in_combat=1)}
        curr = {"Grug": row("Grug", in_combat=1, health=40)}
        self.assertEqual(events.detect_events(prev, curr, GEO), [])

    def test_combat_survived_fires_when_leaving_combat_alive(self):
        prev = {"Grug": row("Grug", in_combat=1, health=40)}
        curr = {"Grug": row("Grug", in_combat=0, health=40)}
        self.assertEqual(
            events.detect_events(prev, curr, GEO),
            [Event("combat_survived", "Grug")],
        )

    def test_health_collapse_is_a_death_not_a_survival(self):
        prev = {"Grug": row("Grug", in_combat=1, health=40)}
        curr = {"Grug": row("Grug", in_combat=0, health=0)}
        self.assertEqual(
            events.detect_events(prev, curr, GEO),
            [Event("death", "Grug")],
        )


class ChurnTest(unittest.TestCase):
    def test_first_poll_with_no_prev_emits_nothing(self):
        curr = {"Grug": row("Grug"), "Zug": row("Zug", level=60, in_combat=1)}
        self.assertEqual(events.detect_events({}, curr, GEO), [])

    def test_disappearance_and_reappearance_are_not_events(self):
        prev = {"Grug": row("Grug")}
        curr = {"Zug": row("Zug")}
        self.assertEqual(events.detect_events(prev, curr, GEO), [])


class PriorityAndCapTest(unittest.TestCase):
    def _mixed_events(self):
        prev = {
            "Aggra": row("Aggra", zone_id=14, pos=DUROTAR_POS),
            "Bine": row("Bine", zone_id=14, pos=DUROTAR_POS),
            "Grug": row("Grug", level=4),
            "Zug": row("Zug", level=9),
            "Mok": row("Mok", in_combat=0),
        }
        curr = {
            "Aggra": row("Aggra", zone_id=1637, pos=OGRIMMAR_POS),
            "Bine": row("Bine", zone_id=1637, pos=OGRIMMAR_POS),
            "Grug": row("Grug", level=5),
            "Zug": row("Zug", level=10),
            "Mok": row("Mok", in_combat=1),
        }
        return events.detect_events(prev, curr, GEO)

    def test_level_ups_outrank_zone_changes_which_outrank_combat(self):
        kinds = [e.kind for e in self._mixed_events()]
        self.assertEqual(
            kinds,
            ["level_up", "level_up", "zone_change", "zone_change", "combat_entered"],
        )

    def test_ordering_is_deterministic_by_name_within_a_kind(self):
        names = [e.name for e in self._mixed_events()]
        self.assertEqual(names, ["Grug", "Zug", "Aggra", "Bine", "Mok"])

    def test_cap_voices_the_top_priority_events_and_keeps_the_rest(self):
        all_events = self._mixed_events()
        voiced, overflow = events.split_for_voicing(all_events, 3)
        self.assertEqual([e.kind for e in voiced],
                         ["level_up", "level_up", "zone_change"])
        self.assertEqual([e.name for e in overflow], ["Bine", "Mok"])
        # Nothing is dropped: voiced + overflow is the whole event list.
        self.assertEqual(voiced + overflow, all_events)

    def test_cap_of_zero_voices_nothing_but_keeps_everything(self):
        all_events = self._mixed_events()
        voiced, overflow = events.split_for_voicing(all_events, 0)
        self.assertEqual(voiced, [])
        self.assertEqual(overflow, all_events)


class TemplateLineTest(unittest.TestCase):
    def test_every_kind_has_a_plain_sentence(self):
        self.assertEqual(
            events.template_line(Event("level_up", "Grug", {"level": 5})),
            "Grug reached level 5.",
        )
        self.assertEqual(
            events.template_line(
                Event("zone_change", "Grug",
                      {"from_zone": "Durotar", "to_zone": "The Barrens"})
            ),
            "Grug crossed into The Barrens.",
        )
        self.assertEqual(events.template_line(Event("death", "Grug")),
                         "Grug fell in battle.")
        self.assertEqual(events.template_line(Event("combat_entered", "Grug")),
                         "Grug entered combat.")
        self.assertEqual(events.template_line(Event("combat_survived", "Grug")),
                         "Grug survived the fight.")


class BatchPromptTest(unittest.TestCase):
    def test_prompt_carries_every_event_and_demands_a_json_array(self):
        prompt = events.build_batch_prompt([
            Event("level_up", "Grug", {"level": 5}),
            Event("zone_change", "Aggra",
                  {"from_zone": "Durotar", "to_zone": "Ogrimmar"}),
        ])
        self.assertIn('"name": "Grug"', prompt)
        self.assertIn('"event": "reached level 5"', prompt)
        self.assertIn('"event": "crossed from Durotar into Ogrimmar"', prompt)
        self.assertIn("ONLY a JSON array", prompt)


VOICE_BATCH = [
    Event("level_up", "Grug", {"level": 5}),
    Event("zone_change", "Aggra",
          {"from_zone": "Durotar", "to_zone": "Ogrimmar"}),
]


class VoiceEventsTest(unittest.TestCase):
    BATCH = VOICE_BATCH

    def test_clean_model_output_voices_every_event(self):
        content = ('[{"name": "Grug", "say": "Level five. I feel it."},'
                   ' {"name": "Aggra", "say": "Ogrimmar at last."}]')
        self.assertEqual(
            events.voice_events(self.BATCH, content),
            ["Level five. I feel it.", "Ogrimmar at last."],
        )

    def test_reasoning_preamble_before_the_array_is_ignored(self):
        content = ('Let me think {not: "json"} about it... {"draft": 1}\n'
                   '[{"name": "Grug", "say": "Stronger now."},'
                   ' {"name": "Aggra", "say": "The city."}]')
        self.assertEqual(
            events.voice_events(self.BATCH, content),
            ["Stronger now.", "The city."],
        )

    def test_unusable_output_degrades_every_event_to_the_template(self):
        self.assertEqual(
            events.voice_events(self.BATCH, "the model rambles with no json"),
            ["Grug reached level 5.", "Aggra crossed into Ogrimmar."],
        )

    def test_missing_character_degrades_only_that_event(self):
        content = '[{"name": "Aggra", "say": "The city gates."}]'
        self.assertEqual(
            events.voice_events(self.BATCH, content),
            ["Grug reached level 5.", "The city gates."],
        )

    def test_single_object_answer_is_accepted_for_a_batch_of_one(self):
        batch = [Event("level_up", "Grug", {"level": 5})]
        content = '{"name": "Grug", "say": "Five."}'
        self.assertEqual(events.voice_events(batch, content), ["Five."])

    def test_two_events_for_one_character_consume_lines_in_order(self):
        batch = [
            Event("level_up", "Grug", {"level": 5}),
            Event("combat_survived", "Grug"),
        ]
        content = ('[{"name": "Grug", "say": "Level five."},'
                   ' {"name": "Grug", "say": "Still breathing."}]')
        self.assertEqual(events.voice_events(batch, content),
                         ["Level five.", "Still breathing."])

    def test_overlong_say_is_truncated_not_dropped(self):
        batch = [Event("level_up", "Grug", {"level": 5})]
        content = '[{"name": "Grug", "say": "' + "a" * 900 + '"}]'
        out = events.voice_events(batch, content)
        self.assertEqual(len(out[0]), 400)


if __name__ == "__main__":
    unittest.main()


class VoiceLengthContractTest(unittest.TestCase):
    """voice_events must return exactly one line per event, whatever the
    model said - bridge.py zips the two lists with strict=True, so a short
    return would raise instead of silently dropping thoughts."""

    def _events(self, n):
        return [
            events.Event(kind="level_up", name="Bot%02d" % i, data={"level": i + 2})
            for i in range(n)
        ]

    def test_partial_model_output_still_yields_one_line_per_event(self):
        evs = self._events(3)
        content = '[{"name": "Bot00", "say": "I grow stronger."}]'
        self.assertEqual(len(events.voice_events(evs, content)), 3)

    def test_garbage_model_output_still_yields_one_line_per_event(self):
        evs = self._events(4)
        self.assertEqual(len(events.voice_events(evs, "I am a language model")), 4)

    def test_extra_model_lines_do_not_lengthen_the_result(self):
        evs = self._events(2)
        content = (
            '[{"name": "Bot00", "say": "a"}, {"name": "Bot01", "say": "b"}, '
            '{"name": "Ghost", "say": "c"}]'
        )
        self.assertEqual(len(events.voice_events(evs, content)), 2)


class StoryFilterTest(unittest.TestCase):
    """Combat is weather for a random bot and drama for a character you
    follow. Live data one hour after shipping #2602: 508 of 727 event
    thoughts were 'entered combat' / 'survived the fight', burying the 20
    level ups a reader actually wants. The filter keeps the arc for
    everyone and the heartbeat only for notable characters."""

    def _ev(self, kind, name="Randombot"):
        return events.Event(kind=kind, name=name, data={"level": 5})

    def test_progress_events_survive_for_anyone(self):
        evs = [self._ev("level_up"), self._ev("zone_change")]
        self.assertEqual(events.filter_for_story(evs, notable=frozenset()), evs)

    def test_combat_noise_is_dropped_for_ordinary_bots(self):
        evs = [self._ev("combat_entered"), self._ev("combat_survived")]
        self.assertEqual(events.filter_for_story(evs, notable=frozenset()), [])

    def test_combat_survives_for_a_notable_character(self):
        evs = [self._ev("combat_entered", "Grug"), self._ev("combat_survived", "Grug")]
        self.assertEqual(events.filter_for_story(evs, notable=frozenset({"Grug"})), evs)

    def test_death_always_survives_because_dying_is_a_story(self):
        evs = [self._ev("death")]
        self.assertEqual(events.filter_for_story(evs, notable=frozenset()), evs)

    def test_notable_matching_ignores_case(self):
        evs = [self._ev("combat_entered", "Grug")]
        self.assertEqual(len(events.filter_for_story(evs, notable=frozenset({"grug"}))), 1)

    def test_order_is_preserved(self):
        evs = [self._ev("level_up", "A"), self._ev("combat_entered", "Grug"),
               self._ev("zone_change", "B")]
        out = events.filter_for_story(evs, notable=frozenset({"Grug"}))
        self.assertEqual([e.name for e in out], ["A", "Grug", "B"])
