"""The two-way chat bridge: what Discord says becomes speech, and what the
world says becomes Discord lines (infra#2597)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core
import relay


class ParseSpeak(unittest.TestCase):
    def test_every_slash_form_maps_to_its_channel(self):
        cases = {
            "/say hi": "say", "/s hi": "say",
            "/yell hi": "yell", "/y hi": "yell", "/shout hi": "yell",
            "/emote hi": "emote", "/e hi": "emote", "/me hi": "emote",
            "/party hi": "party", "/p hi": "party",
            "/raid hi": "raid", "/ra hi": "raid",
            "/guild hi": "guild", "/g hi": "guild",
            "/officer hi": "officer", "/o hi": "officer",
        }
        for text, channel in cases.items():
            got = relay.parse_speak("Grug", text, "src")
            self.assertIsInstance(got, relay.SpeakCommand, text)
            self.assertEqual(got.channel, channel, text)
            self.assertEqual(got.text, "hi", text)

    def test_slash_verb_is_case_insensitive(self):
        self.assertEqual(relay.parse_speak("Grug", "/SAY hi", "s").channel, "say")

    def test_whisper_splits_target_from_message(self):
        got = relay.parse_speak("Grug", "/w Thrall meet me in Orgrimmar", "s")
        self.assertEqual(got.channel, "whisper")
        self.assertEqual(got.whisper_to, "Thrall")
        self.assertEqual(got.text, "meet me in Orgrimmar")

    def test_whisper_with_no_message_is_not_a_speak(self):
        self.assertIsNone(relay.parse_speak("Grug", "/w Thrall", "s"))

    def test_whisper_to_a_non_name_is_refused(self):
        # "/w hey there" would otherwise whisper "there" to a player "hey".
        self.assertIsNone(relay.parse_speak("Grug", "/w hey1 there", "s"))

    def test_dot_command_becomes_a_gm_command_keeping_its_dot(self):
        # The worldserver's ChatHandler::ParseCommands REJECTS anything that
        # does not start with '.' - the dot must survive the whole journey.
        got = relay.parse_speak("Grug", ".appear Thrall", "s")
        self.assertIsInstance(got, relay.GmCommand)
        self.assertEqual(got.command, ".appear Thrall")

    def test_a_lone_dot_is_not_a_command(self):
        self.assertIsNone(relay.parse_speak("Grug", ".", "s"))

    def test_unknown_slash_falls_through_to_the_old_paths(self):
        # Returning None is what keeps "/dance" a natural-language order
        # instead of swallowing it as an unknown channel.
        self.assertIsNone(relay.parse_speak("Grug", "/dance", "s"))

    def test_plain_words_fall_through(self):
        self.assertIsNone(relay.parse_speak("Grug", "go to Thunder Bluff", "s"))

    def test_message_is_capped_at_the_column_width(self):
        got = relay.parse_speak("Grug", "/say " + "a" * 400, "s")
        self.assertEqual(len(got.text), relay.MAX_SPEAK_LEN)


class GmAllowlist(unittest.TestCase):
    def test_the_commands_this_feature_exists_for_are_allowed(self):
        for cmd in (
            ".appear Thrall",
            ".summon Thrall",
            ".playerbots bot self",
            ".revive",
            ".go xyz 1 2 3",
            ".modify speed 2",
            ".pinfo Grug",
        ):
            self.assertIsInstance(relay.parse_speak("Grug", cmd, "s"), relay.GmCommand, cmd)

    def test_the_irreversible_surface_is_refused(self):
        for cmd in (
            ".account set gmlevel Grug 3 -1",
            ".ban account Thrall 1d x",
            ".server shutdown 1",
            ".server restart 1",
            ".character delete Grug",
            ".reload config",
            ".unban account Thrall",
        ):
            self.assertIsInstance(relay.parse_speak("Grug", cmd, "s"), relay.GmRefused, cmd)

    def test_an_allowed_two_word_prefix_does_not_admit_its_siblings(self):
        # "server info" is allowed; "server shutdown" must not ride in on it.
        self.assertTrue(relay.gm_is_allowed(".server info"))
        self.assertFalse(relay.gm_is_allowed(".server shutdown 1"))

    def test_prefixes_match_whole_words_only(self):
        # A bare startswith would let ".gmail" through on "gm".
        self.assertTrue(relay.gm_is_allowed(".gm on"))
        self.assertFalse(relay.gm_is_allowed(".gmail"))
        self.assertFalse(relay.gm_is_allowed(".golist"))

    def test_case_and_spacing_do_not_get_past_it(self):
        self.assertFalse(relay.gm_is_allowed(".  ACCOUNT   set gmlevel"))
        self.assertTrue(relay.gm_is_allowed(".APPEAR Thrall"))

    # AzerothCore command trees that contain a destructive leaf. None of these
    # may appear in the allowlist as a bare tree, because admitting the tree
    # admits the leaf - which is exactly how ".npc delete" got in behind "npc"
    # the first time round. Their safe leaves may be listed individually.
    DESTRUCTIVE_TREES = (
        "npc", "gobject", "character", "account", "guild", "server",
        "reload", "ban", "unban", "titles", "arena", "instance",
    )

    def test_no_destructive_command_tree_is_admitted_whole(self):
        # An invariant about the LIST, so re-adding a dangerous tree fails
        # here rather than being discovered in the world.
        for tree in self.DESTRUCTIVE_TREES:
            self.assertNotIn(tree, relay.GM_ALLOWED_PREFIXES, tree)

    def test_any_entry_naming_such_a_tree_is_a_specific_leaf(self):
        for entry in relay.GM_ALLOWED_PREFIXES:
            head = entry.split(" ")[0]
            if head in self.DESTRUCTIVE_TREES:
                self.assertIn(" ", entry, "%r admits a whole tree" % entry)

    # Real AzerothCore leaves that permanently remove persistent state. This
    # is the invariant that actually protects: every one of these must be
    # refused, whether its parent tree is on the allowlist or not.
    DESTRUCTIVE_LEAVES = (
        "tele del Orgrimmar",
        "npc delete",
        "gobject delete",
        "character delete Grug",
        "character erase Grug",
        "account delete Grug",
        "guild delete Argentum",
        "server exit",
        "server shutdown 1",
        "server restart 1",
        "server idlerestart 1",
        "reload all",
        "titles reset",
    )

    def test_every_known_destructive_leaf_is_refused(self):
        for leaf in self.DESTRUCTIVE_LEAVES:
            self.assertFalse(relay.gm_is_allowed("." + leaf), leaf)

    def test_every_abbreviation_of_a_denied_leaf_is_refused(self):
        # The worldserver resolves subcommands by PREFIX (StringStartsWithI in
        # ChatCommands/ChatCommand.cpp), so ".tele d" reaches ".tele del".
        # Refusing only the full spelling would be a guarantee in name only.
        for leaf in relay.GM_DENIED_LEAVES:
            head, _, sub = leaf.partition(" ")
            if not sub:
                continue
            for i in range(1, len(sub) + 1):
                cmd = ".%s %s Orgrimmar" % (head, sub[:i])
                self.assertFalse(relay.gm_is_allowed(cmd), cmd)

    def test_a_location_beginning_with_the_denied_letter_is_not_collateral(self):
        # Denying ".tele d" must not cost ".tele Dalaran": the worldserver only
        # resolves a token that PREFIXES a registered subcommand, and
        # "dalaran" does not prefix "del".
        for place in (".tele Dalaran", ".tele Darnassus", ".tele Durotar"):
            self.assertTrue(relay.gm_is_allowed(place), place)

    def test_tele_still_works_for_the_thing_it_is_for(self):
        # The deny-leaf layer exists so this keeps working while `.tele del`
        # does not: dropping the whole tree would have cost the feature.
        self.assertTrue(relay.gm_is_allowed(".tele Orgrimmar"))
        self.assertFalse(relay.gm_is_allowed(".tele del Orgrimmar"))

    def test_known_destructive_commands_are_refused(self):
        # A regression net of real AzerothCore commands that permanently
        # change realm state.
        for cmd in (
            ".npc delete",
            ".gobject delete",
            ".account delete Grug",
            ".character erase Grug",
            ".character delete Grug",
            ".server exit",
            ".server idlerestart 1",
            ".reload all",
            ".ban character Thrall 1d x",
            ".guild delete Argentum",
            ".titles reset",
        ):
            self.assertIsInstance(relay.parse_speak("Grug", cmd, "s"), relay.GmRefused, cmd)

    def test_the_read_only_leaves_of_those_trees_are_still_allowed(self):
        self.assertTrue(relay.gm_is_allowed(".npc info"))
        self.assertTrue(relay.gm_is_allowed(".gobject info"))

    def test_a_refused_command_is_answered_not_handed_to_the_llm(self):
        # Falling through would give ".account set gmlevel" to an LLM to
        # interpret, which is the worst of both worlds.
        got = core.parse_directive(".x", "u1", frozenset({"u1"}))
        self.assertEqual(got, [])
        got = core.parse_directive("@Grug .ban account Thrall", "u1", frozenset({"u1"}))
        self.assertEqual(len(got), 1)
        self.assertIsInstance(got[0], core.Reply)
        self.assertIn("allowlist", got[0].text)


class Sanitize(unittest.TestCase):
    def test_mass_mentions_cannot_summon_the_room(self):
        # Bot chat is LLM-generated, so it is untrusted text.
        for raw in ("@everyone look", "@here look", "@EveryOne look"):
            out = relay.sanitize(raw)
            self.assertNotIn("@everyone", out.lower())
            self.assertNotIn("@here", out.lower())
            self.assertIn("look", out)

    def test_backticks_cannot_break_the_fence(self):
        self.assertNotIn("`", relay.sanitize("look at ```this"))

    def test_role_mentions_cannot_ping_a_role(self):
        # The gap an @everyone-only filter leaves: any of 500 characters can
        # type <@&roleid> in guild chat and ping a whole Discord role.
        out = relay.sanitize("<@&123456789> to arms")
        self.assertNotIn("<@&123456789>", out)
        self.assertIn("to arms", out)

    def test_user_mentions_cannot_ping_a_person(self):
        for raw in ("<@99> hi", "<@!99> hi"):
            out = relay.sanitize(raw)
            self.assertNotIn(raw.split(" ")[0], out)
            self.assertIn("hi", out)

    def test_channel_links_are_defanged_too(self):
        self.assertNotIn("<#4321>", relay.sanitize("see <#4321>"))

    def test_a_bare_angle_bracket_is_not_mangled(self):
        # Only the id forms are touched; ordinary text keeps its shape.
        self.assertEqual(relay.sanitize("3 < 4 > 2"), "3 < 4 > 2")

    def test_the_separator_is_written_as_an_escape_not_pasted(self):
        # An invisible character living literally in source is unreadable in
        # a diff and unsearchable; the module must stay pure ASCII.
        import os
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "relay.py")
        with open(path, "rb") as fh:
            raw = fh.read()
        self.assertEqual([b for b in raw if b > 127], [])
        self.assertEqual(relay.ZERO_WIDTH, "\u200b")

    def test_ordinary_text_is_left_alone(self):
        self.assertEqual(relay.sanitize("hail, traveller"), "hail, traveller")


class FormatLine(unittest.TestCase):
    def line(self, **kw):
        row = {"id": 1, "sender_name": "Thrall", "channel": "say", "text": "hi"}
        row.update(kw)
        return relay.format_line(row)

    def test_say_is_bare(self):
        self.assertEqual(self.line(), "Thrall: hi")

    def test_yell_reads_as_a_yell(self):
        self.assertEqual(self.line(channel="yell"), "Thrall yells: hi")

    def test_emote_is_third_person(self):
        self.assertEqual(self.line(channel="emote", text="waves"), "* Thrall waves")

    def test_group_channels_are_labelled(self):
        self.assertEqual(self.line(channel="guild"), "[Guild] Thrall: hi")
        self.assertEqual(self.line(channel="party"), "[Party] Thrall: hi")

    def test_whisper_is_marked(self):
        self.assertEqual(self.line(channel="whisper"), "[whisper] Thrall: hi")

    def test_public_channel_uses_its_own_name(self):
        self.assertEqual(
            self.line(channel="channel", channel_name="Trade"), "[Trade] Thrall: hi"
        )

    def test_text_is_sanitized_on_the_way_out(self):
        self.assertNotIn("@everyone", self.line(text="@everyone run").lower())


class FormatBatch(unittest.TestCase):
    def rows(self, n, text="hi"):
        return [
            {"id": i, "sender_name": "Bot%d" % i, "channel": "say", "text": text}
            for i in range(1, n + 1)
        ]

    @staticmethod
    def ids(posts):
        return [i for _, chunk in posts for i in chunk]

    def test_empty_in_empty_out(self):
        self.assertEqual(relay.format_batch([]), [])

    def test_a_small_batch_is_one_post_covering_every_row(self):
        posts = relay.format_batch(self.rows(3))
        self.assertEqual(len(posts), 1)
        text, ids = posts[0]
        self.assertEqual(ids, [1, 2, 3])
        self.assertEqual(text.count("\n"), 2)

    def test_a_long_batch_splits_below_the_discord_limit(self):
        posts = relay.format_batch(self.rows(20, text="x" * 200))
        self.assertGreater(len(posts), 1)
        for text, _ in posts:
            self.assertLessEqual(relay.discord_len(text), relay.MAX_DISCORD_UNITS)

    def test_each_post_carries_exactly_its_own_rows(self):
        # The property the caller depends on to acknowledge honestly: every
        # row appears in exactly one post, in order, and nothing is invented.
        posts = relay.format_batch(self.rows(20, text="x" * 200))
        flat = self.ids(posts)
        self.assertEqual(flat, sorted(flat))
        self.assertEqual(len(flat), len(set(flat)))
        self.assertTrue(set(flat).issubset(set(range(1, 21))))
        for text, ids in posts:
            self.assertEqual(len(text.split("\n")), len(ids))

    def test_astral_emoji_are_sized_as_discord_counts_them(self):
        # Discord measures UTF-16 units, so an emoji costs two. Sizing with
        # len() undercounts by half: twenty of these lines measure ~965 code
        # points but 2639 Discord units, which Discord rejects outright.
        fire = chr(0x1F525)
        posts = relay.format_batch(self.rows(20, text=fire * 63))
        self.assertEqual(len(self.ids(posts)), 20)
        for text, _ in posts:
            self.assertLessEqual(relay.discord_len(text), relay.MAX_DISCORD_UNITS)
            text.encode("utf-8")  # no split surrogate pairs

    def test_one_enormous_line_is_clipped_rather_than_sent_unsendable(self):
        # A single line over the cap would otherwise be a post Discord always
        # refuses, blocking every later line behind it forever.
        posts = relay.format_batch(self.rows(1, text=chr(0x1F525) * 5000))
        self.assertEqual(len(posts), 1)
        text, ids = posts[0]
        self.assertLessEqual(relay.discord_len(text), relay.MAX_DISCORD_UNITS)
        text.encode("utf-8")
        self.assertEqual(ids, [1])

    def test_clipping_is_safe_at_every_edge(self):
        # Including the one that matters most: a limit too small to hold even
        # one emoji must yield empty text, never half a surrogate pair, which
        # would not be encodable and would fail on the way out.
        fire = chr(0x1F525)
        for text in ("", "a", fire, fire * 500, "a" + fire * 300):
            for limit in (0, 1, 2, 3, 1900):
                out = relay._clip_to_units(text, limit)
                self.assertLessEqual(relay.discord_len(out), max(limit, 0))
                out.encode("utf-8")
        self.assertEqual(relay._clip_to_units(fire, 1), "")

    def test_discord_len_counts_utf16_units(self):
        self.assertEqual(relay.discord_len("abc"), 3)
        self.assertEqual(relay.discord_len(chr(0x1F525)), 2)
        self.assertEqual(relay.discord_len("a" + chr(0x1F525)), 3)

    def test_rows_past_the_line_cap_appear_in_no_post(self):
        # Anything trimmed here must stay unrelayed so it goes out next tick
        # instead of being silently dropped.
        rows = self.rows(relay.MAX_LINES_PER_POST + 5)
        flat = self.ids(relay.format_batch(rows))
        self.assertEqual(len(flat), relay.MAX_LINES_PER_POST)
        self.assertNotIn(rows[-1]["id"], flat)


class CoreIntegration(unittest.TestCase):
    ALLOWED = frozenset({"u1"})

    def parse(self, text):
        return core.parse_directive(text, "u1", self.ALLOWED)

    def test_a_slash_line_becomes_speech(self):
        got = self.parse("@Grug /say Hello Durotar")
        self.assertEqual(len(got), 1)
        self.assertIsInstance(got[0], relay.SpeakCommand)
        self.assertEqual(got[0].target_name, "Grug")

    def test_a_dot_line_becomes_a_gm_command(self):
        got = self.parse("@Grug .appear Thrall")
        self.assertIsInstance(got[0], relay.GmCommand)

    def test_a_playerbot_command_still_works(self):
        got = self.parse("@Grug follow")
        self.assertIsInstance(got[0], core.InsertCommand)

    def test_a_natural_order_still_works(self):
        got = self.parse("@Grug go and find something to kill")
        self.assertIsInstance(got[0], core.NLDirective)

    def test_spoken_lines_count_against_the_flood_cap(self):
        text = "\n".join("@Grug /say line %d" % i for i in range(9))
        got = self.parse(text)
        self.assertEqual(len(got), 1)
        self.assertIsInstance(got[0], core.Reply)
        self.assertIn("cap", got[0].text)


class OutcomeReporting(unittest.TestCase):
    def report(self, **kw):
        row = {
            "id": 7, "target_name": "Grug", "command": "hi",
            "kind": "bot", "status": "delivered", "detail": "",
        }
        row.update(kw)
        replies, _ = core.report_outcomes([row], set())
        return replies

    def test_a_spoken_line_is_acknowledged_silently(self):
        # It comes back through the chat relay; a second note would be an echo.
        # The id must still be returned or the caller's pending map leaks.
        replies = self.report(kind="chat")
        self.assertEqual(len(replies), 1)
        self.assertEqual(replies[0][0], 7)
        self.assertIsNone(replies[0][1])

    def test_a_failed_line_says_why(self):
        replies = self.report(kind="chat", status="error", detail="not in a guild")
        self.assertIsNotNone(replies[0][1])
        self.assertIn("not in a guild", replies[0][1].text)

    def test_a_gm_command_confirms(self):
        replies = self.report(kind="gm", command=".appear Thrall")
        self.assertIn("done", replies[0][1].text)

    def test_a_refused_gm_command_says_so(self):
        replies = self.report(
            kind="gm", command=".appear Thrall", status="error", detail="refused"
        )
        self.assertIn("refused", replies[0][1].text)

    def test_an_abandoned_command_reports_rather_than_going_quiet(self):
        # A worldserver that dies mid-command leaves the row claimed, which is
        # what stops it running twice. The bridge later ends it as an error so
        # the person who gave the order finds out, instead of the row sitting
        # there pinning the poller's floor forever.
        replies = self.report(
            kind="gm",
            command=".appear Thrall",
            status="error",
            detail="worldserver did not finish this command",
        )
        self.assertIn("worldserver did not finish", replies[0][1].text)

    def test_bot_commands_report_exactly_as_before(self):
        replies = self.report(command="follow")
        self.assertEqual(replies[0][1].text, "Grug heard the order: follow")

    def test_a_row_written_before_this_feature_has_no_kind(self):
        row = {"id": 7, "target_name": "Grug", "command": "follow", "status": "delivered"}
        replies, _ = core.report_outcomes([row], set())
        self.assertEqual(replies[0][1].text, "Grug heard the order: follow")


if __name__ == "__main__":
    unittest.main()
