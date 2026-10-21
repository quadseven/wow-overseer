"""Party voice: one stable voice per character, and the deduplicated feed."""

import unittest

import bonds
import partyvoice


def family_members():
    return [name for house in bonds.HOUSES.values() for name in house.members]


class VoiceTableTest(unittest.TestCase):
    def test_every_family_member_has_a_hand_set_voice(self):
        # A member added to bonds without a voice would fall through to the
        # hashed voice a stranger gets; this is the line that stops that.
        for name in family_members():
            with self.subTest(name=name):
                self.assertIn(name, partyvoice._VOICES)

    def test_every_hand_set_voice_belongs_to_a_family_member(self):
        self.assertLessEqual(set(partyvoice._VOICES), set(family_members()))

    def test_each_family_member_sounds_distinct(self):
        voices = [partyvoice.voice_for(name) for name in family_members()]
        pitches = [v["pitch"] for v in voices]
        rates = [v["rate"] for v in voices]
        self.assertEqual(len(set(pitches)), len(pitches), pitches)
        self.assertEqual(len(set(rates)), len(rates), rates)

    def test_grug_is_low_and_slow_and_the_boys_higher_and_quicker(self):
        grug, ugga, grog, bork = (
            partyvoice.voice_for(n) for n in ("Grug", "Ugga", "Grog", "Bork")
        )
        self.assertLess(grug["pitch"], ugga["pitch"])
        self.assertLess(ugga["pitch"], grog["pitch"])
        self.assertLess(grog["pitch"], bork["pitch"])
        self.assertLess(grug["rate"], ugga["rate"])
        self.assertLess(ugga["rate"], grog["rate"])
        self.assertLess(grog["rate"], bork["rate"])

    def test_the_pinned_family_values(self):
        # Pinned, so a change to how a character sounds is a deliberate edit
        # to this test and not a side effect.
        self.assertEqual(
            partyvoice.voice_for("Grug"),
            {
                "engine_voice_hint": {"lang": "en", "gender": "male"},
                "pitch": 0.70,
                "rate": 0.85,
            },
        )
        self.assertEqual(
            partyvoice.voice_for("Ugga"),
            {
                "engine_voice_hint": {"lang": "en", "gender": "female"},
                "pitch": 1.10,
                "rate": 0.94,
            },
        )

    def test_the_hint_carries_the_gender_the_bond_records(self):
        for name in family_members():
            with self.subTest(name=name):
                hint = partyvoice.voice_for(name)["engine_voice_hint"]
                self.assertEqual(
                    hint["gender"], getattr(bonds.bond_of(name), "gender", None)
                )

    def test_case_is_ignored_because_chat_is(self):
        self.assertEqual(partyvoice.voice_for("grug"), partyvoice.voice_for("Grug"))
        self.assertEqual(
            partyvoice.voice_for("STRANGER"), partyvoice.voice_for("stranger")
        )

    def test_values_sit_in_the_range_speech_synthesis_takes(self):
        for name in [*family_members(), "Stranger", ""]:
            with self.subTest(name=name):
                voice = partyvoice.voice_for(name)
                self.assertTrue(0.5 <= voice["pitch"] <= 2.0, voice)
                self.assertTrue(0.5 <= voice["rate"] <= 2.0, voice)


class UnknownSpeakerTest(unittest.TestCase):
    def test_an_unknown_speaker_gets_the_same_voice_every_time(self):
        self.assertEqual(
            partyvoice.voice_for("Stranger"), partyvoice.voice_for("Stranger")
        )

    def test_the_unknown_voice_is_pinned_not_random(self):
        # sha256 of the name, not hash(): hash() is salted per process, and a
        # voice that changed on every restart would not be stable.
        self.assertEqual(partyvoice._hashed("stranger"), partyvoice._hashed("Stranger"))
        self.assertEqual(
            partyvoice._hashed("stranger"), partyvoice._hashed(" stranger ")
        )
        self.assertEqual(partyvoice.voice_for("Stranger")["pitch"], 1.07)

    def test_unknown_speakers_differ_from_one_another(self):
        names = ["Stranger", "Wanderer", "Trader", "Guard", "Hermit"]
        voices = {
            (partyvoice.voice_for(n)["pitch"], partyvoice.voice_for(n)["rate"])
            for n in names
        }
        self.assertGreater(len(voices), 1)

    def test_an_unknown_speaker_has_no_gender_hint(self):
        hint = partyvoice.voice_for("Stranger")["engine_voice_hint"]
        self.assertEqual(hint, {"lang": "en", "gender": ""})


def row(i, sender="Grug", text="Aye.", at="2026-08-23 12:00:00", ch="party", age=2):
    return {
        "id": i,
        "sender_name": sender,
        "channel": ch,
        "text": text,
        "created_at": at,
        "age_s": age,
    }


class FeedTest(unittest.TestCase):
    def test_one_line_heard_by_five_is_one_line(self):
        out = partyvoice.feed([row(i) for i in range(1, 6)], 0)
        self.assertEqual([line["id"] for line in out["rows"]], [1])

    def test_the_cursor_moves_past_every_copy(self):
        # Stopping at the line kept (1) would read 2-5 again next poll, and
        # they would collapse to one line and be said twice.
        out = partyvoice.feed([row(i) for i in range(1, 6)], 0)
        self.assertEqual(out["cursor"], 5)

    def test_feed_caps_raw_rows_and_cursor_at_the_last_row_in_the_page(self):
        rows = [row(i) for i in range(1, partyvoice.PAGE + 6)]
        out = partyvoice.feed(rows, 0)
        self.assertEqual(out["cursor"], partyvoice.PAGE)
        self.assertEqual([line["id"] for line in out["rows"]], [1])

    def test_the_cursor_moves_past_addon_rows(self):
        out = partyvoice.feed([row(7, text="help me"), row(8, text="MBOT\tPING~1")], 6)
        self.assertEqual([line["id"] for line in out["rows"]], [7])
        self.assertEqual(out["cursor"], 8)

    def test_no_rows_keep_the_cursor_where_it_was(self):
        self.assertEqual(partyvoice.feed([], 41), {"rows": [], "cursor": 41})

    def test_party_and_raid_both_pass(self):
        out = partyvoice.feed([row(1, ch="party"), row(2, ch="raid", text="Pull.")], 0)
        self.assertEqual([line["channel"] for line in out["rows"]], ["party", "raid"])

    def test_a_line_carries_its_speakers_voice_and_age(self):
        out = partyvoice.feed([row(3, sender="Bork", text="WOW", age=4)], 0)
        self.assertEqual(
            out["rows"],
            [
                {
                    "id": 3,
                    "sender": "Bork",
                    "channel": "party",
                    "text": "WOW",
                    "age_s": 4,
                    "voice": partyvoice.voice_for("Bork"),
                }
            ],
        )

    def test_a_row_without_a_whole_id_or_age_is_dropped_and_logged(self):
        broken = [
            {"sender_name": "Grug", "text": "no id"},
            row("x"),
            row(4, age="soon"),
        ]
        with self.assertLogs("partyvoice", level="WARNING") as logs:
            out = partyvoice.feed([*broken, row(5, text="Aye.")], 3)
        self.assertEqual([line["id"] for line in out["rows"]], [5])
        self.assertEqual(out["cursor"], 5)
        self.assertEqual(len(logs.records), 3)

    def test_the_same_words_said_again_later_are_two_lines(self):
        # The moment is part of the key: only the hearers' copies collapse.
        out = partyvoice.feed(
            [row(1, at="2026-08-23 12:00:00"), row(2, at="2026-08-23 12:00:30")], 0
        )
        self.assertEqual(len(out["rows"]), 2)


if __name__ == "__main__":
    unittest.main()
