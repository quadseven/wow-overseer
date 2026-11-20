"""Stranded members cross to a map with a friendly class trainer (#2640).

A Draenei shaman on Kalimdor fails its trainer walk with NO_TRAINER_REASON
because only a Horde shaman trainer stands on Kalimdor. Instead of waiting on
map 1 indefinitely, the trainer pass reads class trainer spawns from the world
database and schedules a boat crossing (cross-to-map) to Eastern Kingdoms.
"""

import asyncio
import json
import types
import unittest
from dataclasses import replace
from unittest import mock

import modsource
from _stub_modules import PYMYSQL, fresh_import, stub_modules

with stub_modules(pymysql=PYMYSQL):
    import classtrain
    import guildjobs
    import guildlevel
    import guildroute

SHAMAN = 7
WARRIOR = 1
HUMAN = 1
ORC = 2
DRAENEI = 11

EASTERN_KINGDOMS = 0
KALIMDOR = 1
OUTLAND = 530

ALLIANCE_ENEMY_GROUP = 4  # Alliance NPC hostile mask includes Horde (4).
HORDE_ENEMY_GROUP = 2  # Horde NPC hostile mask includes Alliance (2).

ALLIANCE = "alliance"
DUSTWALLOW_MARSH = 15
DARKSHORE = 148

NO_TRAINER_RESULT = json.dumps(
    {
        "outcome": "refused",
        "retryable": False,
        "reason": classtrain.NO_TRAINER_REASON,
        "map": KALIMDOR,
    }
)


def _trainee(
    name="Shamy",
    guild="Cave",
    class_id=SHAMAN,
    race_id=DRAENEI,
    cost=500,
    money=2000,
    online=True,
):
    return classtrain.Trainee(
        name=name,
        guild=guild,
        level=12,
        money=money,
        due=classtrain.Due(count=1, copper=cost),
        online=online,
        class_id=class_id,
        race_id=race_id,
    )


def _walker(
    name="Shamy",
    map_id=KALIMDOR,
    zone_id=DARKSHORE,
    in_combat=False,
    by_row=True,
):
    return guildroute.Walker(
        name=name,
        map_id=map_id,
        zone_id=zone_id,
        in_combat=in_combat,
        by_row=by_row,
    )


def _spawns():
    return [
        # Horde shaman trainer on Kalimdor (Orgrimmar): hostile to Draenei.
        {"map": KALIMDOR, "class_id": SHAMAN, "enemy_group": HORDE_ENEMY_GROUP},
        # Alliance shaman trainer on Eastern Kingdoms (Exodar NPCs/stormwind).
        {
            "map": EASTERN_KINGDOMS,
            "class_id": SHAMAN,
            "enemy_group": ALLIANCE_ENEMY_GROUP,
        },
        # Shattrath / Outland neutral shaman trainer.
        {"map": OUTLAND, "class_id": SHAMAN, "enemy_group": 0},
        # Alliance warrior trainer on Kalimdor.
        {"map": KALIMDOR, "class_id": WARRIOR, "enemy_group": ALLIANCE_ENEMY_GROUP},
    ]


class TrainerMapsAndCrossings(unittest.TestCase):
    def test_train_cross_action_is_registered_with_cross_actions(self):
        self.assertEqual(guildjobs.TRAIN_CROSS_ACTION, "train-cross")
        self.assertIn(guildjobs.TRAIN_CROSS_ACTION, guildjobs.CROSS_ACTIONS)

    def test_trainer_maps_excludes_hostile_trainers_and_keeps_map_zero(self):
        maps = classtrain.trainer_maps(SHAMAN, DRAENEI, _spawns())
        self.assertEqual(maps, frozenset({EASTERN_KINGDOMS, OUTLAND}))
        horde_maps = classtrain.trainer_maps(SHAMAN, ORC, _spawns())
        self.assertEqual(horde_maps, frozenset({KALIMDOR, OUTLAND}))

    def test_crossing_for_plans_mainland_and_pocket_boats(self):
        valid = frozenset({EASTERN_KINGDOMS, OUTLAND})
        mainland = classtrain.crossing_for(ALLIANCE, KALIMDOR, DARKSHORE, valid)
        self.assertIsNotNone(mainland)
        self.assertEqual(mainland[0], EASTERN_KINGDOMS)
        self.assertIn("Menethil", mainland[1])

        pocket = classtrain.crossing_for(ALLIANCE, KALIMDOR, DUSTWALLOW_MARSH, valid)
        self.assertIsNotNone(pocket)
        self.assertEqual(pocket[0], EASTERN_KINGDOMS)
        self.assertIn("Theramore", pocket[1])

    def test_crossing_for_uses_boat_exit_from_azuremyst_outland(self):
        valid = frozenset({KALIMDOR})
        exit_trip = classtrain.crossing_for(ALLIANCE, OUTLAND, 3524, valid)
        self.assertEqual(exit_trip, (KALIMDOR, guildlevel.EXITS[ALLIANCE]))

    def test_crossing_for_respects_walls_and_already_valid_maps(self):
        valid = frozenset({EASTERN_KINGDOMS, OUTLAND})
        self.assertIsNone(
            classtrain.crossing_for(
                ALLIANCE, KALIMDOR, DARKSHORE, valid, walls={EASTERN_KINGDOMS}
            )
        )
        self.assertIsNone(classtrain.crossing_for(ALLIANCE, EASTERN_KINGDOMS, 0, valid))

    def test_trainees_from_rows_keeps_class_and_race(self):
        rows = [
            {
                "name": "Shamy",
                "guild_name": "Cave",
                "level": 12,
                "money": 2000,
                "online": 1,
                "class_id": SHAMAN,
                "race": DRAENEI,
            }
        ]
        dues = {"Shamy": classtrain.Due(1, 500)}
        (t,) = classtrain.trainees_from_rows(rows, dues)
        self.assertEqual(t.class_id, SHAMAN)
        self.assertEqual(t.race_id, DRAENEI)


class StrandedTrainerCrossingPlan(unittest.TestCase):
    def _refused_row(self, name="Shamy", age=5):
        return {
            "target_name": name,
            "source": f"{classtrain.SOURCE}:{name}",
            "age": age,
            "status": "refused",
            "result": NO_TRAINER_RESULT,
        }

    def test_stranded_draenei_shaman_is_planned_cross_to_map_zero(self):
        rows = [self._refused_row("Shamy", age=5)]
        stranded = classtrain.stranded(rows)
        recent = classtrain.recent_walkers(rows)
        self.assertNotIn("Shamy", recent)

        planned, notes = classtrain.plan(
            [_trainee("Shamy")],
            {"Shamy": _walker("Shamy", KALIMDOR, DARKSHORE)},
            recent,
            busy=frozenset(),
            stranded=stranded,
            trainer_spawns=_spawns(),
        )
        self.assertEqual(notes, [])
        self.assertEqual(len(planned), 1)
        cross = planned[0]
        self.assertIsInstance(cross, classtrain.Cross)
        self.assertEqual(cross.name, "Shamy")
        self.assertEqual(cross.target_map, EASTERN_KINGDOMS)
        self.assertEqual(cross.kind, "job")
        self.assertEqual(cross.command, f"cross-to-map map:{EASTERN_KINGDOMS}")
        self.assertEqual(
            cross.source, guildjobs.source_for(guildjobs.TRAIN_CROSS_ACTION, "Shamy")
        )

    def test_after_crossing_to_map_zero_shaman_walks_immediately_despite_recent_refusal(
        self,
    ):
        rows = [self._refused_row("Shamy", age=10)]
        stranded = classtrain.stranded(rows)
        recent = classtrain.recent_walkers(rows)
        planned, notes = classtrain.plan(
            [_trainee("Shamy")],
            {"Shamy": _walker("Shamy", EASTERN_KINGDOMS, 12)},
            recent,
            busy=frozenset(),
            stranded=stranded,
            trainer_spawns=_spawns(),
        )
        self.assertEqual(notes, [])
        self.assertEqual(len(planned), 1)
        self.assertIsInstance(planned[0], classtrain.Walk)
        self.assertTrue(planned[0].command.startswith(classtrain.VERB))
        self.assertEqual(planned[0].kind, classtrain.KIND)

    def test_crossing_allowance_and_active_inflight_crossings_are_respected(self):
        names = ["ShamyA", "ShamyB", "ShamyC"]
        rows = [self._refused_row(n, age=5) for n in names]
        trainees = [_trainee(n) for n in names]
        walkers = {n: _walker(n, KALIMDOR, DARKSHORE) for n in names}

        planned, notes = classtrain.plan(
            trainees,
            walkers,
            classtrain.recent_walkers(rows),
            busy=frozenset(),
            stranded=classtrain.stranded(rows),
            trainer_spawns=_spawns(),
        )
        self.assertEqual([p.name for p in planned], ["ShamyA", "ShamyB"])
        self.assertTrue(any("ShamyC" in n for n in notes))

        # With one active in-flight crossing in the same guild, only one more is allowed.
        inflight = guildjobs.recent_from_rows(
            [
                {
                    "source": f"{guildjobs.SOURCE}:level-cross:Guildie",
                    "target_name": "Guildie",
                    "command": f"cross-to-map map:{EASTERN_KINGDOMS}",
                    "status": "pending",
                    "age": 3,
                    "result": None,
                }
            ]
        )
        planned2, notes2 = classtrain.plan(
            trainees,
            walkers,
            classtrain.recent_walkers(rows),
            busy=frozenset(),
            stranded=classtrain.stranded(rows),
            trainer_spawns=_spawns(),
            cross_recent=inflight,
            guild_of={"Guildie": "Cave"},
        )
        self.assertEqual([p.name for p in planned2], ["ShamyA"])
        self.assertEqual(len(notes2), 2)

    def test_walls_cooling_walk_refusal_busy_and_unreadable_spawns_hold_crossing(self):
        rows = [self._refused_row("Shamy", age=5)]
        t = _trainee("Shamy")
        w = {"Shamy": _walker("Shamy", KALIMDOR, DARKSHORE)}

        # Wall against target map 0.
        wall_reason = "no transport the module knows sails from this map to that map for this faction"
        wall_rows = guildjobs.recent_from_rows(
            [
                {
                    "source": guildjobs.source_for(
                        guildjobs.TRAIN_CROSS_ACTION, "Shamy"
                    ),
                    "target_name": "Shamy",
                    "command": f"cross-to-map map:{EASTERN_KINGDOMS}",
                    "status": "refused",
                    "age": 5,
                    "result": json.dumps(
                        {"outcome": "refused", "reason": wall_reason},
                        separators=(",", ":"),
                    ),
                }
            ]
        )
        planned, notes = classtrain.plan(
            [t],
            w,
            classtrain.recent_walkers(rows),
            frozenset(),
            stranded=classtrain.stranded(rows),
            trainer_spawns=_spawns(),
            cross_recent=wall_rows,
        )
        self.assertEqual(planned, [])
        self.assertTrue(any("Shamy" in n for n in notes))

        # Cooldown / retry hold from prior crossing attempt.
        cool_rows = guildjobs.recent_from_rows(
            [
                {
                    "source": guildjobs.source_for(
                        guildjobs.TRAIN_CROSS_ACTION, "Shamy"
                    ),
                    "target_name": "Shamy",
                    "command": f"cross-to-map map:{EASTERN_KINGDOMS}",
                    "status": "done",
                    "age": 5,
                    "result": json.dumps(
                        {"outcome": "completed"}, separators=(",", ":")
                    ),
                }
            ]
        )
        planned_cool, _ = classtrain.plan(
            [t],
            w,
            classtrain.recent_walkers(rows),
            frozenset(),
            stranded=classtrain.stranded(rows),
            trainer_spawns=_spawns(),
            cross_recent=cool_rows,
        )
        self.assertEqual(planned_cool, [])

        # Combat / walk_refusal holds crossing too.
        planned_combat, _ = classtrain.plan(
            [t],
            {"Shamy": _walker("Shamy", KALIMDOR, DARKSHORE, in_combat=True)},
            classtrain.recent_walkers(rows),
            frozenset(),
            stranded=classtrain.stranded(rows),
            trainer_spawns=_spawns(),
        )
        self.assertEqual(planned_combat, [])

        # Unreadable trainer spawns (None) falls back to wait note.
        planned_none, notes_none = classtrain.plan(
            [t],
            w,
            classtrain.recent_walkers(rows),
            frozenset(),
            stranded=classtrain.stranded(rows),
            trainer_spawns=None,
        )
        self.assertEqual(planned_none, [])
        self.assertTrue(any("map change" in n for n in notes_none))


def _import_bridge():
    stub = types.ModuleType("discord")

    class Client:
        def __init__(self, *args, **kwargs):
            pass

    stub.Client = Client
    return fresh_import("bridge", discord=stub, pymysql=PYMYSQL)


bridge = _import_bridge()


class BridgeTrainerCrossingWiring(unittest.TestCase):
    def test_dues_members_sql_reads_race(self):
        self.assertIn("c.race", bridge._DUES_MEMBERS_SQL)

    def test_class_trainer_spawns_handles_missing_table_as_none(self):
        bridge._CLASS_TRAINER_SPAWNS = []

        class _BoomCursor:
            def execute(self, sql, params=()):
                raise PYMYSQL.err.ProgrammingError(1146, "Table doesn't exist")

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        class _BoomConn:
            def cursor(self):
                return _BoomCursor()

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with mock.patch.object(bridge, "_connect", return_value=_BoomConn()):
            self.assertIsNone(bridge._class_trainer_spawns())

    def test_guild_train_once_writes_cross_job_for_stranded_shaman(self):
        trainee = _trainee("Shamy", cost=500, money=2000)
        train_rows = [
            {
                "target_name": "Shamy",
                "source": f"{classtrain.SOURCE}:Shamy",
                "age": 5,
                "status": "refused",
                "result": NO_TRAINER_RESULT,
            }
        ]
        walkers = {"Shamy": _walker("Shamy", KALIMDOR, DARKSHORE)}
        inserted = []

        def fake_insert(name, command, kind, source):
            inserted.append((name, command, kind, source))
            return 901

        bot = bridge.Bridge.__new__(bridge.Bridge)
        bot._train_walks = {}
        bot._mail_walk_unsupported_until = 0.0

        with (
            mock.patch.object(bridge, "_names_of", return_value=["Shamy"]),
            mock.patch.object(bridge, "_fetch_trainees", return_value=[trainee]),
            mock.patch.object(bridge, "_guild_train_rows", return_value=train_rows),
            mock.patch.object(bridge, "_class_trainer_spawns", return_value=_spawns()),
            mock.patch.object(bridge, "_guild_cross_rows", return_value=[]),
            mock.patch.object(bridge, "_route_walkers", return_value=walkers),
            mock.patch.object(bridge, "_insert_crafter_row", side_effect=fake_insert),
            mock.patch.object(bot, "_guild_walkers_busy", return_value=frozenset()),
            mock.patch.object(bot, "_guild_walk_cap", return_value=5000.0),
        ):
            asyncio.run(bot._guild_train_once())

        self.assertEqual(
            inserted,
            [
                (
                    "Shamy",
                    f"cross-to-map map:{EASTERN_KINGDOMS}",
                    "job",
                    guildjobs.source_for(guildjobs.TRAIN_CROSS_ACTION, "Shamy"),
                )
            ],
        )

    def test_nonretryable_refusal_holds_walk_until_map_or_level_changes(self):
        fixture = json.loads(
            modsource.read(modsource.SUBMODULE / "fixtures" / "walk_refusals.json")
        )
        refusal = next(
            row
            for row in fixture["rows"]
            if row["reason"].endswith("on this map has a class spell to teach it now")
        )
        trainee = _trainee("Shamy", cost=500, money=2000)
        row = {
            "target_name": trainee.name,
            "source": f"{classtrain.SOURCE}:{trainee.name}",
            "age": classtrain.COOLDOWN_MINUTES + 1,
            "status": "error",
            "target_arg": str(trainee.level),
            "result": json.dumps(dict(refusal, map=KALIMDOR)),
        }
        for map_id, level, should_walk in (
            (KALIMDOR, trainee.level, False),
            (EASTERN_KINGDOMS, trainee.level, True),
            (KALIMDOR, trainee.level + 1, True),
        ):
            with self.subTest(map_id=map_id, level=level):
                bot = bridge.Bridge.__new__(bridge.Bridge)
                bot._train_walks = {}
                bot._mail_walk_unsupported_until = 0.0
                with (
                    mock.patch.object(bridge, "_names_of", return_value=[trainee.name]),
                    mock.patch.object(
                        bridge,
                        "_fetch_trainees",
                        return_value=[replace(trainee, level=level)],
                    ),
                    mock.patch.object(bridge, "_guild_train_rows", return_value=[row]),
                    mock.patch.object(
                        bridge, "_class_trainer_spawns", return_value=None
                    ),
                    mock.patch.object(bridge, "_guild_cross_rows", return_value=[]),
                    mock.patch.object(
                        bridge,
                        "_route_walkers",
                        return_value={trainee.name: _walker(trainee.name, map_id, 12)},
                    ),
                    mock.patch.object(
                        bridge, "_insert_crafter_row", return_value=901
                    ) as insert,
                    mock.patch.object(
                        bot, "_guild_walkers_busy", return_value=frozenset()
                    ),
                    mock.patch.object(bot, "_guild_walk_cap", return_value=5000.0),
                ):
                    asyncio.run(bot._guild_train_once())
                if should_walk:
                    insert.assert_called_once()
                    self.assertTrue(
                        insert.call_args.args[1].startswith(classtrain.VERB)
                    )
                    self.assertEqual(
                        insert.call_args.kwargs, {"target_arg": str(level)}
                    )
                else:
                    insert.assert_not_called()


if __name__ == "__main__":
    unittest.main()
