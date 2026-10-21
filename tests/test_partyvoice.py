"""party voice: one voice per character, shaped rows, rate-limited queue."""

import sys
import unittest

sys.path.insert(0, ".")

import partyvoice


class VoiceForTest(unittest.TestCase):
    def test_family_voices_are_hand_set_and_distinct(self):
        voices = {
            name: partyvoice.voice_for(name)
            for name in ("Grug", "Ugga", "Grog", "Bork", "Og")
        }
        pitches = {v["pitch"] for v in voices.values()}
        rates = {v["rate"] for v in voices.values()}
        # Every family member has a distinct, stable voice.
        self.assertEqual(len(pitches), 5, pitches)
        self.assertEqual(len(rates), 5, rates)
        # Grug low and slow; Ugga mid; the boys higher and quicker.
        self.assertLess(voices["Grug"]["pitch"], voices["Ugga"]["pitch"])
        self.assertLess(voices["Ugga"]["pitch"], voices["Bork"]["pitch"])
        self.assertLess(voices["Grug"]["rate"], voices["Ugga"]["rate"])
        self.assertLess(voices["Ugga"]["rate"], voices["Bork"]["rate"])

    def test_voice_is_stable_across_reloads(self):
        first = partyvoice.voice_for("Grug")
        for _ in range(50):
            self.assertEqual(partyvoice.voice_for("Grug"), first)

    def test_unknown_speaker_gets_a_deterministic_voice(self):
        first = partyvoice.voice_for("Thrall")
        second = partyvoice.voice_for("Thrall")
        self.assertEqual(first, second)
        self.assertIn(first["engine_voice_hint"], ("male-low", "female-mid"))
        self.assertGreaterEqual(first["pitch"], 0.85)
        self.assertLessEqual(first["pitch"], 1.15)
        self.assertGreaterEqual(first["rate"], 0.90)
        self.assertLessEqual(first["rate"], 1.20)

    def test_unknown_voices_differ_by_speaker(self):
        a = partyvoice.voice_for("Thrall")
        b = partyvoice.voice_for("Jaina")
        self.assertNotEqual(a["pitch"], b["pitch"])

    def test_case_is_ignored(self):
        self.assertEqual(partyvoice.voice_for("grug"), partyvoice.voice_for("Grug"))

    def test_voice_has_all_required_keys(self):
        v = partyvoice.voice_for("Grug")
        self.assertEqual(set(v), {"engine_voice_hint", "pitch", "rate"})


class ShapeTest(unittest.TestCase):
    def _row(self, i, sender="Grug", text="Aye.", at="2026-08-23 12:00:00", ch="party"):
        return {
            "id": i,
            "sender_name": sender,
            "channel": ch,
            "text": text,
            "created_at": at,
        }

    def test_one_line_heard_by_five_is_returned_once(self):
        rows = [self._row(i) for i in range(1, 6)]
        kept, dropped = partyvoice.shape(rows)
        self.assertEqual([r["id"] for r in kept], [1])
        self.assertEqual(dropped, [2, 3, 4, 5])

    def test_party_and_raid_both_pass_through(self):
        rows = [
            self._row(1, ch="party"),
            self._row(2, ch="raid"),
        ]
        kept, _ = partyvoice.shape(rows)
        self.assertEqual([r["id"] for r in kept], [1, 2])

    def test_addon_traffic_is_dropped_rather_than_spoken(self):
        rows = [
            self._row(1, text="help me"),
            self._row(2, text="MBOT\tGET~ROSTER"),
        ]
        kept, dropped = partyvoice.shape(rows)
        self.assertEqual([r["id"] for r in kept], [1])
        self.assertEqual(dropped, [2])

    def test_everything_addon_is_dropped(self):
        rows = [
            self._row(1, text="MBOT\tPING~1"),
            self._row(2, text="MBOT\tPING~2"),
        ]
        kept, dropped = partyvoice.shape(rows)
        self.assertEqual(kept, [])
        self.assertEqual(dropped, [1, 2])

    def test_empty_in_empty_out(self):
        self.assertEqual(partyvoice.shape([]), ([], []))


class NowSource:
    """A clock the tests advance at will."""

    def __init__(self, start=1000.0):
        self.now = start

    def __call__(self):
        return self.now


class ChatQueueTest(unittest.TestCase):
    def _row(self, i, sender="Grug", text="hi", moment=1000.0, ch="party"):
        return {
            "id": i,
            "sender_name": sender,
            "channel": ch,
            "text": text,
            "moment": moment,
        }

    def test_one_line_at_a_time(self):
        clock = NowSource()
        q = partyvoice.ChatQueue(now=clock)
        q.enqueue([self._row(1)])
        self.assertEqual(q.next()["id"], 1)
        # While speaking, nothing else comes out.
        self.assertIsNone(q.next())
        q.finish()
        self.assertIsNone(q.next())

    def test_stale_line_is_dropped(self):
        clock = NowSource()
        q = partyvoice.ChatQueue(now=clock, stale_seconds=20.0)
        q.enqueue([self._row(1, moment=900.0)])  # 100s old: stale
        q.enqueue([self._row(2, moment=995.0)])  # 5s old: fresh
        self.assertEqual(q.next()["id"], 2)
        self.assertEqual(q.queued(), 0)

    def test_repeat_is_skipped_within_the_window(self):
        clock = NowSource()
        q = partyvoice.ChatQueue(now=clock, repeat_seconds=60.0)
        q.enqueue([self._row(1, text="Aye.")])
        self.assertEqual(q.next()["id"], 1)
        q.finish()
        # Same speaker, same words, 10s later: repeat, skipped.
        q.enqueue([self._row(2, text="Aye.", moment=1010.0)])
        self.assertIsNone(q.next())
        self.assertEqual(q.queued(), 0)

    def test_repeat_is_spoken_after_the_window(self):
        clock = NowSource()
        q = partyvoice.ChatQueue(now=clock, repeat_seconds=60.0)
        q.enqueue([self._row(1, text="Aye.")])
        self.assertEqual(q.next()["id"], 1)
        q.finish()
        clock.now = 1070.0  # 70s later: outside the window
        q.enqueue([self._row(2, text="Aye.", moment=1070.0)])
        self.assertEqual(q.next()["id"], 2)

    def test_queue_is_capped(self):
        clock = NowSource()
        q = partyvoice.ChatQueue(now=clock, cap=3)
        q.enqueue(
            [self._row(1), self._row(2), self._row(3), self._row(4), self._row(5)]
        )
        self.assertEqual(q.queued(), 3)
        self.assertEqual([r["id"] for r in q._lines], [3, 4, 5])

    def test_cap_is_respected_exactly(self):
        clock = NowSource()
        q = partyvoice.ChatQueue(now=clock, cap=2)
        q.enqueue([self._row(1), self._row(2)])
        self.assertEqual(q.queued(), 2)
        q.enqueue([self._row(3)])
        self.assertEqual(q.queued(), 2)
        self.assertEqual([r["id"] for r in q._lines], [2, 3])

    def test_rows_without_moment_are_fresh(self):
        clock = NowSource()
        q = partyvoice.ChatQueue(now=clock, stale_seconds=1.0)
        q.enqueue([{"id": 1, "sender_name": "Grug", "channel": "party", "text": "hi"}])
        self.assertEqual(q.queued(), 1)


if __name__ == "__main__":
    unittest.main()
