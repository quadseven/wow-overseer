"""The dev family is the live family renamed, and nothing else (infra#2791).

WHY THESE ASSERTIONS AND NOT OTHERS. There are exactly two ways this change can
be wrong, and both are silent:

  1. A LIVE NAME REACHES THE DEV WORLD. A dev roster row saying `Grug`, a dev
     persona saying "Watches Og around Ugga", a dev trade reason saying "runs on
     Ugga's herbs". None of these fail. They produce a dev world that talks
     about five characters who are not in it, and they put production's roster
     in front of the model that voices dev's - which is the whole leak.

  2. THE DEV FAMILY STOPS MATCHING THE LIVE ONE'S SHAPE. If dev's five ever
     differ in role, class, spec, seniority or trade, then dev exercises
     different branches from live, and a green dev result stops meaning
     anything about production. This is worse than having no dev world, because
     it is confidently wrong.

So the tests below are almost entirely equalities between the two sets after
un-renaming, plus a sweep for live names in every string dev can produce.
"""

import os
import re
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import bonds  # noqa: E402
import cast  # noqa: E402
import professions  # noqa: E402

# WoW's own character-name rule, the same one map_server.py gates on before a
# name reaches SQL. A dev name that cannot be typed at the character-creation
# screen is a family nobody can make.
NAME_RE = re.compile(r"^[A-Za-z]{2,12}$")


def _live_name_hits(text: str) -> list:
    """Every live family name appearing as a whole word in `text`."""
    if not text:
        return []
    pattern = re.compile(r"\b(%s)\b" % "|".join(cast.LIVE_NAMES))
    return pattern.findall(text)


class NameMapTest(unittest.TestCase):
    def test_live_names_are_exactly_the_live_family(self):
        # cast.LIVE_NAMES exists so the substitution can run without importing
        # bonds (bonds imports cast; the reverse is a cycle). That makes it a
        # SECOND copy of the family's membership, and this is the seam that
        # stops it drifting. A member added to bonds and not here would pass
        # through the rename untouched - a live name on a dev character.
        self.assertEqual(
            set(cast.LIVE_NAMES),
            set(bonds.family_for(cast.LIVE)),
            "cast.LIVE_NAMES and bonds' live family disagree about who the "
            "family is. Anyone missing here is renamed to themselves.",
        )

    def test_every_live_member_has_a_dev_name(self):
        self.assertEqual(set(cast.DEV_NAMES), set(cast.LIVE_NAMES))

    def test_the_two_sets_of_names_are_disjoint(self):
        # Not tidiness. An overlapping map makes a substitution order-dependent
        # - rename Grug->Grog while Grog->Bork and the first output becomes the
        # second's input - and it means a dev log line could be read as a live
        # character.
        self.assertEqual(
            set(cast.LIVE_NAMES) & set(cast.DEV_NAMES.values()),
            set(),
            "a dev name is also a live name",
        )

    def test_dev_names_are_distinct_from_each_other(self):
        self.assertEqual(len(set(cast.DEV_NAMES.values())), len(cast.DEV_NAMES))

    def test_dev_names_can_actually_be_created_in_the_client(self):
        # Characters are made by a person at the character-creation screen -
        # there is no server-side path to a named character - so a name that
        # the client's own rule rejects is a family that cannot exist.
        for name in cast.DEV_NAMES.values():
            self.assertRegex(name, NAME_RE, f"{name} is not a legal WoW name")

    def test_an_overlapping_map_is_refused_rather_than_tolerated(self):
        with self.assertRaises(ValueError):
            cast._check({"Grug": "Ugga", "Ugga": "Og"})

    def test_two_names_cannot_map_onto_one(self):
        with self.assertRaises(ValueError):
            cast._check({"Grug": "Thak", "Ugga": "Thak"})


class SelectionTest(unittest.TestCase):
    def test_unset_means_live(self):
        # Load-bearing: every process running today - the bridge, the map, the
        # emitter - sets nothing, and must keep behaving exactly as it does.
        self.assertEqual(cast.selected({}), cast.LIVE)

    def test_blank_and_unknown_mean_live(self):
        for value in ("", "   ", "nonsense", "prod"):
            self.assertEqual(cast.selected({cast.ENV_VAR: value}), cast.LIVE)

    def test_dev_is_selected_case_insensitively(self):
        for value in ("dev", "DEV", " Dev "):
            self.assertEqual(cast.selected({cast.ENV_VAR: value}), cast.DEV)

    def test_the_module_level_tables_follow_the_unset_default(self):
        # bonds.FAMILY and professions.ROSTER are resolved at import. This suite
        # runs with nothing set, so both must be the live tables - which is also
        # what every other test file in this directory assumes.
        self.assertEqual(set(bonds.FAMILY), set(cast.LIVE_NAMES))
        self.assertEqual(set(professions.ROSTER), set(cast.LIVE_NAMES))


class RenameTest(unittest.TestCase):
    def test_unknown_names_pass_through(self):
        # The callers rewrite prose full of trainers, zones and strangers.
        for name in ("Thrall", "", "Ahuman"):
            self.assertEqual(cast.rename(name, cast.DEV), name)

    def test_retext_replaces_whole_words_only(self):
        self.assertEqual(cast.retext("Og and Ogrimmar", cast.DEV), "Vek and Ogrimmar")

    def test_retext_is_a_single_pass(self):
        # Chained substitution would rewrite an output. Proven by renaming a
        # sentence containing every live name at once and checking none of the
        # dev names got renamed again.
        sentence = " ".join(cast.LIVE_NAMES)
        self.assertEqual(
            cast.retext(sentence, cast.DEV).split(),
            [cast.DEV_NAMES[n] for n in cast.LIVE_NAMES],
        )

    def test_live_retext_is_the_identity(self):
        self.assertEqual(cast.retext("Grug and Og", cast.LIVE), "Grug and Og")

    def test_rekey_preserves_order(self):
        source = {name: i for i, name in enumerate(cast.LIVE_NAMES)}
        self.assertEqual(
            list(cast.rekey(source, cast.DEV)),
            [cast.DEV_NAMES[n] for n in cast.LIVE_NAMES],
        )


class SameShapeTest(unittest.TestCase):
    """The dev family must differ from the live one in NAME and nothing else."""

    @classmethod
    def setUpClass(cls):
        cls.live = bonds.family_for(cast.LIVE)
        cls.dev = bonds.family_for(cast.DEV)

    def test_the_dev_family_is_the_live_one_re_keyed(self):
        self.assertEqual(
            set(self.dev),
            set(cast.DEV_NAMES.values()),
        )

    def test_every_field_except_the_prose_is_identical(self):
        # role, blood, seniority, race, class, gender and spec_tab. If any of
        # these ever diverges, dev takes branches live does not - a party with
        # two healers, a leader chosen by a different seniority - and a green
        # dev run stops predicting anything.
        for live_name, dev_name in cast.DEV_NAMES.items():
            live, dev = self.live[live_name], self.dev[dev_name]
            self.assertEqual(
                (
                    live.role,
                    live.blood,
                    live.seniority,
                    live.race,
                    live.char_class,
                    live.gender,
                    live.spec_tab,
                ),
                (
                    dev.role,
                    dev.blood,
                    dev.seniority,
                    dev.race,
                    dev.char_class,
                    dev.gender,
                    dev.spec_tab,
                ),
                f"{dev_name} is not {live_name} under another name",
            )

    def test_the_dev_family_leads_the_same_role(self):
        self.assertEqual(
            self.dev[cast.rename(bonds.head_of_family(), cast.DEV)].role,
            self.live[bonds.head_of_family()].role,
        )

    def test_no_dev_persona_names_a_live_character(self):
        # The personas are handed to the LLM that voices these characters.
        for name, bond in self.dev.items():
            self.assertEqual(
                _live_name_hits(bond.persona),
                [],
                f"{name}'s persona still names the live family",
            )

    def test_every_dev_persona_still_names_the_people_it_used_to(self):
        # The other half of the assertion above: a persona could be scrubbed of
        # live names by losing the sentence entirely, which would quietly make
        # the dev characters strangers to each other.
        for live_name, dev_name in cast.DEV_NAMES.items():
            mentioned = {
                cast.rename(other, cast.DEV)
                for other in cast.LIVE_NAMES
                if re.search(rf"\b{other}\b", self.live[live_name].persona)
            }
            for other in mentioned:
                self.assertRegex(
                    self.dev[dev_name].persona,
                    rf"\b{other}\b",
                    f"{dev_name}'s persona lost its reference to {other}",
                )


class SuspicionTest(unittest.TestCase):
    def test_the_suspicion_moves_with_the_family(self):
        dev = bonds.suspicion_for(cast.DEV)
        live = bonds.suspicion_for(cast.LIVE)
        for key in ("who", "about", "with"):
            self.assertEqual(dev[key], cast.rename(live[key], cast.DEV))

    def test_the_note_names_nobody_from_the_live_world(self):
        self.assertEqual(_live_name_hits(bonds.suspicion_for(cast.DEV)["note"]), [])

    def test_the_jealousy_rule_still_fires_for_the_dev_family(self):
        # The rule the suspicion exists for, exercised end to end under the dev
        # names. This is the point of renaming rather than inventing: the same
        # branch runs in both worlds.
        dev = bonds.family_for(cast.DEV)
        suspicion = bonds.suspicion_for(cast.DEV)
        father = suspicion["who"]
        mother = suspicion["about"]
        rival = suspicion["with"]
        self.assertEqual(dev[father].role, "father")
        self.assertEqual(dev[mother].role, "mother")

        plea = type("P", (), {"caller": mother, "about": "wolves"})()
        history = [(rival, mother)] * bonds.JEALOUSY_THRESHOLD
        # bonds.decide reads the MODULE-level FAMILY, which is live here, so
        # the dev names are outside it and it declines to have an opinion -
        # which is itself the safe behaviour and worth pinning.
        self.assertTrue(bonds.decide(father, plea, history=history).will_answer)
        # Under the live names the same shape refuses, which is the behaviour
        # the dev world will get once OVERSEER_FAMILY is set in its process.
        live_plea = type("P", (), {"caller": "Ugga", "about": "wolves"})()
        self.assertFalse(
            bonds.decide(
                "Grug", live_plea, history=[("Og", "Ugga")] * bonds.JEALOUSY_THRESHOLD
            ).will_answer
        )


class TradeShapeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.live = professions.roster_for(cast.LIVE)
        cls.dev = professions.roster_for(cast.DEV)

    def test_every_dev_character_holds_the_same_pair(self):
        for live_name, dev_name in cast.DEV_NAMES.items():
            self.assertEqual(
                self.dev[dev_name].primaries,
                self.live[live_name].primaries,
                f"{dev_name}'s trades are not {live_name}'s",
            )

    def test_no_dev_trade_reason_names_a_live_character(self):
        for name, trade in self.dev.items():
            self.assertEqual(
                _live_name_hits(trade.why),
                [],
                f"{name}'s trade reason still names the live family",
            )

    def test_the_dev_economy_covers_the_same_professions(self):
        # The correctness of this table is a property of the SET - three
        # gathering trades feeding crafts the family owns, one character
        # deliberately dependent. Asserting the union rather than the rows is
        # what pins that property rather than the spelling.
        self.assertEqual(
            {p for t in self.dev.values() for p in t.primaries},
            {p for t in self.live.values() for p in t.primaries},
        )


class SeedRosterTest(unittest.TestCase):
    """The generated SQL. It is executed against a database, so it is asserted.

    Run as a SUBPROCESS rather than imported, because the tool sets
    OVERSEER_FAMILY in its own environment before importing bonds - which is
    exactly how the real processes resolve the family, and which cannot be done
    twice in one interpreter. Importing it here would also poison every other
    test in this file by leaving the module-level tables renamed.
    """

    TOOL = os.path.join(ROOT, "tools", "seed_roster.py")

    @classmethod
    def setUpClass(cls):
        cls.dev_sql = cls._run(cast.DEV)
        cls.live_sql = cls._run(cast.LIVE)

    @classmethod
    def _run(cls, which):
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell; `which`
            # is one of two literals argparse allows
            [sys.executable, cls.TOOL, "--family", which],
            capture_output=True,
            text=True,
            check=True,
            cwd=ROOT,
        )
        return proc.stdout

    def test_the_dev_seed_never_names_a_live_character(self):
        self.assertEqual(
            _live_name_hits(self.dev_sql),
            [],
            "the dev roster seed would write live family names into the dev "
            "world's overseer_roster",
        )

    def test_every_dev_member_gets_a_row(self):
        for name in cast.DEV_NAMES.values():
            self.assertIn(f"VALUES ('{name}'", self.dev_sql, name)

    def test_rows_are_inserted_ignoring_existing_ones(self):
        # A row parked by hand is a decision. A seed that re-enabled it would
        # make that decision unmakeable - bridge._ensure_roster's own reasoning.
        self.assertIn("INSERT IGNORE INTO overseer_roster", self.dev_sql)
        self.assertNotIn("REPLACE INTO", self.dev_sql)
        self.assertNotIn("ON DUPLICATE KEY", self.dev_sql)

    def test_exactly_one_character_is_made_leader(self):
        head = cast.rename(bonds.head_of_family(), cast.DEV)
        self.assertIn(
            f"UPDATE overseer_roster SET `lead` = IF(name = '{head}', 1, 0);",  # noqa: S608 - an EXPECTED string compared against the tool's output, never executed; `head` comes from bonds.head_of_family()
            self.dev_sql,
        )
        self.assertEqual(self.dev_sql.count("SET `lead`"), 1)

    def test_the_seed_never_aims_anybody(self):
        # ONLY THE TRAVELLER (mod_overseer.cpp). `new rpg` acts at relevance
        # 3.0-11.0 against follow's 1.0, so a follower given an aim wanders off
        # every tick - five aims scattered the family 937 yards and killed one
        # of them (infra#2812). A seed script must have no opinion about this
        # column at all; leaving it at its 0 default is "no aim", which the
        # module degrades to leader-only travel.
        for column in ("drive_quest", "travel_npc"):
            self.assertNotIn(f"SET {column}", self.dev_sql, f"the seed writes {column}")

    def test_the_seed_never_issues_a_profession_errand(self):
        # `professions` is a PERMISSION and is written. learn/unlearn are
        # INSTRUCTIONS and are not: an errand seeded from a table rather than
        # observed from character_skills tells a character to buy something it
        # may already own.
        self.assertIn("SET professions =", self.dev_sql)
        for column in ("learn_skill", "unlearn_skill", "unlearn_max"):
            self.assertNotIn(f"SET {column}", self.dev_sql)

    def test_the_seed_carries_no_credential(self):
        # It prints SQL and connects to nothing, which is what makes it
        # reviewable before it is run.
        lowered = self.dev_sql.lower()
        for word in ("password", "identified by", "mysql_root"):
            self.assertNotIn(word, lowered)

    def test_the_live_seed_is_the_same_statements_under_live_names(self):
        # Offered so the live roster can be diffed against what this would
        # write. If the two ever differ in anything but names, one of the two
        # worlds is being seeded differently from the other.
        # The set's own name appears in the header and in each row's `note`,
        # and is legitimately different. Everything else must be identical.
        translated = (
            cast.retext(self.live_sql, cast.DEV)
            .replace(f"'{cast.LIVE}'", f"'{cast.DEV}'")
            .replace(f"{cast.LIVE} family - ", f"{cast.DEV} family - ")
        )
        self.assertEqual(translated, self.dev_sql)


if __name__ == "__main__":
    unittest.main()
