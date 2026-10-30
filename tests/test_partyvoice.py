"""Reading party and raid chat aloud: the voice table and the feed's shaping.

The page speaks what /api/chat/party hands it, in the voice it is handed.
Both halves of that are decided here, in partyvoice, so they are pinned here:
every family member sounds like nobody else, and the same line heard by five
listeners reaches the page once.

Ticket: 177.
"""

import unittest

import bonds
import partyvoice


def row(
    rid, sender="Grug", text="Aye.", channel="party", at="2026-08-23 12:00:00", age=3
):
    return {
        "id": rid,
        "sender_name": sender,
        "channel": channel,
        "text": text,
        "created_at": at,
        "age_s": age,
    }


def everyone():
    return [name for house in bonds.HOUSES.values() for name in house.members]


class VoiceTable(unittest.TestCase):
    def test_every_family_member_has_a_hand_set_voice(self):
        for name in everyone():
            with self.subTest(name=name):
                self.assertIn(name, partyvoice.FAMILY_VOICES)

    def test_no_two_members_sound_alike(self):
        # Two members may share a system voice, so pitch and rate carry the
        # difference: every pair differs by a step the ear can hear in one.
        names = everyone()
        for i, a in enumerate(names):
            for b in names[i + 1 :]:
                va, vb = partyvoice.voice_for(a), partyvoice.voice_for(b)
                apart = round(
                    max(abs(va["pitch"] - vb["pitch"]), abs(va["rate"] - vb["rate"])), 2
                )
                with self.subTest(a=a, b=b):
                    self.assertGreaterEqual(apart, partyvoice.MIN_APART)

    def test_the_family_voices_are_pinned(self):
        family = ["Grug", "Ugga", "Grog", "Bork", "Og"]
        voices = {name: partyvoice.voice_for(name) for name in family}
        self.assertEqual(
            {name: (v["pitch"], v["rate"]) for name, v in voices.items()},
            {
                "Grug": (0.7, 0.85),
                "Ugga": (1.15, 1.0),
                "Grog": (1.3, 1.05),
                "Bork": (1.55, 1.2),
                "Og": (0.9, 0.95),
            },
        )

    def test_grug_is_low_and_slow_and_the_boys_higher_and_quicker(self):
        grug, ugga = partyvoice.voice_for("Grug"), partyvoice.voice_for("Ugga")
        grog, bork = partyvoice.voice_for("Grog"), partyvoice.voice_for("Bork")
        self.assertLess(grug["pitch"], ugga["pitch"])
        self.assertLess(grug["rate"], ugga["rate"])
        self.assertLess(ugga["pitch"], grog["pitch"])
        self.assertLess(grog["pitch"], bork["pitch"])
        self.assertLess(grog["rate"], bork["rate"])

    def test_the_hint_follows_the_bond_gender(self):
        for name in everyone():
            with self.subTest(name=name):
                gender = bonds.bond_of(name).gender
                self.assertEqual(
                    partyvoice.voice_for(name)["engine_voice_hint"], "en-" + gender
                )

    def test_chat_spelling_finds_the_same_voice(self):
        self.assertEqual(partyvoice.voice_for("grug"), partyvoice.voice_for("Grug"))

    def test_a_stranger_gets_a_deterministic_voice(self):
        first = partyvoice.voice_for("Thrall")
        self.assertEqual(first, partyvoice.voice_for("Thrall"))
        self.assertEqual(first["engine_voice_hint"], "en")
        self.assertTrue(0.5 <= first["pitch"] <= 2.0)
        self.assertTrue(0.5 <= first["rate"] <= 2.0)

    def test_strangers_do_not_all_share_one_voice(self):
        voices = {
            tuple(partyvoice.voice_for(n).values())
            for n in ("Thrall", "Jaina", "Rexxar", "Varian")
        }
        self.assertGreater(len(voices), 1)

    def test_a_caller_cannot_change_the_table(self):
        partyvoice.voice_for("Grug")["pitch"] = 2.0
        self.assertEqual(partyvoice.voice_for("Grug")["pitch"], 0.7)


class Feed(unittest.TestCase):
    def test_a_line_heard_by_five_is_spoken_once(self):
        rows = [row(i) for i in range(1, 6)]
        got = partyvoice.feed(rows, after=0)
        self.assertEqual([r["id"] for r in got["rows"]], [1])

    def test_the_cursor_passes_every_row_read_even_the_dropped(self):
        rows = [row(7), row(8), row(9, text="MBOT\x01PING")]
        self.assertEqual(partyvoice.feed(rows, after=6)["after"], 9)

    def test_no_rows_keeps_the_cursor(self):
        self.assertEqual(partyvoice.feed([], after=42), {"rows": [], "after": 42})

    def test_addon_traffic_is_never_spoken(self):
        got = partyvoice.feed([row(1, text="MBOT\x01PING~18265384")], after=0)
        self.assertEqual(got["rows"], [])

    def test_raid_rides_the_same_feed(self):
        self.assertIn("raid", partyvoice.CHANNELS)
        got = partyvoice.feed(
            [row(1, sender="Ugga", channel="raid", text="Ready.")], after=0
        )
        self.assertEqual(got["rows"][0]["channel"], "raid")

    def test_guild_and_say_are_not_read(self):
        self.assertEqual(set(partyvoice.CHANNELS), {"party", "raid"})

    def test_each_row_carries_its_speakers_voice_and_age(self):
        got = partyvoice.feed([row(3, sender="Bork", age=4)], after=0)["rows"][0]
        self.assertEqual(
            got,
            {
                "id": 3,
                "speaker": "Bork",
                "channel": "party",
                "text": "Aye.",
                "age_s": 4,
                "voice": partyvoice.voice_for("Bork"),
            },
        )

    def test_an_unmeasured_age_stays_unmeasured(self):
        got = partyvoice.feed([row(3, age=None)], after=0)["rows"][0]
        self.assertIsNone(got["age_s"])


if __name__ == "__main__":
    unittest.main()
