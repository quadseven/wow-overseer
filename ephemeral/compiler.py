"""The seed compiler: a decree's `cast` and `arrange` become SQL.

Nothing here touches a database. It reads through a `Resolver`, resolves every
anchor and name (zero or several matches is INVALID), and returns a `SeedPlan`
of statements built by `sqlgen.Builder`, so every table and column is checked
against the schema and every statement has one of four fixed shapes against the
world's own character database. Running the plan is `guard.apply_plan`.

The seeded rows follow how the core stores these things; whether the core then
plays the scenario as intended is what the first end-to-end run shows, and a
precondition that fails makes that run INVALID rather than a pass.
"""

from dataclasses import dataclass, field

from . import gamedata, lint
from .sqlgen import Builder, NowPlus, SeedError

BACKPACK_SLOTS = range(23, 39)  # INVENTORY_SLOT_ITEM_START .. END
PLAYER_FLAG_GHOST = 0x10
SEVEN_DAYS = 7 * 24 * 3600
TEN_YEARS = 10 * 365 * 24 * 3600
GRAVEYARD_NEAREST = "nearest"
_QUEST_STATUS = {"incomplete": 3, "complete": 1}
_MAX_RAID = 40


@dataclass
class Member:
    cast_index: int
    who: str
    guid: int
    name: str


@dataclass
class SeedPlan:
    statements: list = field(default_factory=list)
    variables: dict = field(default_factory=dict)
    members: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    def render(self):
        out = [f"-- {n}" for n in self.notes]
        out += [s.sql + ";" for s in self.statements]
        return "\n".join(out) + "\n"


class Compiler:
    def __init__(self, decree, resolver, schema, anchors):
        self.decree = decree
        self.r = resolver
        self.b = Builder(schema)
        self.anchors = anchors
        self.plan = SeedPlan()
        self.positions = {}  # guid -> (map, zone, x, y, z, o)
        self.instances = {}  # alias -> (id, map)
        self._item_guid = None
        self._freed = {}
        self._item_guid_next = 0

    # -- resolution -------------------------------------------------------
    def members_of(self, who, cast_index=None):
        if who.startswith("family:"):
            rows = self.r.family(who.split(":", 1)[1])
            if not rows:
                raise SeedError(f"{who} resolves to no enabled roster member")
            pairs = [(g, n) for g, n, _ in rows]
        elif who.startswith("guild:"):
            pairs = [self._guild_member(who)]
        else:
            rows = self.r.characters(who)
            if len(rows) != 1:
                raise SeedError(
                    f"character {who!r} resolves to {len(rows)} rows, need exactly 1"
                )
            pairs = [tuple(rows[0])]
        return [Member(cast_index, who, g, n) for g, n in pairs]

    def _guild_member(self, who):
        _, guild, role = who.split(":", 2)
        skill = gamedata.SKILLS.get(gamedata.ROLE_SKILLS.get(role, ""))
        if skill is None:
            raise SeedError(
                f"{who}: role {role!r} is not a profession this compiler knows"
            )
        rows = self.r.guild_role(guild, skill)
        if not rows:
            raise SeedError(f"{who} resolves to no guild member with that skill")
        self.plan.notes.append(
            f"{who} resolved to {rows[0][1]} (best skill, then lowest guid)"
        )
        return tuple(rows[0])  # best skill first, then lowest guid: deterministic

    def one(self, rows, what):
        if len(rows) != 1:
            raise SeedError(f"{what} resolves to {len(rows)} rows, need exactly 1")
        return rows[0]

    def place(self, anchor, corpse=None, resolved_with=None):
        """An anchor to (map, zone, x, y, z, o)."""
        kind, val = next(iter(anchor.items()))
        if kind in ("creature", "gameobject"):
            fetch = (
                self.r.creature_spawns
                if kind == "creature"
                else self.r.gameobject_spawns
            )
            s = self.one(fetch(val), f"{kind} {val!r}")
            return (s["map"], s["zone"], s["x"], s["y"], s["z"], s["o"])
        if kind == "areatrigger":
            t = self.r.areatrigger(val)
            if t is None:
                raise SeedError(f"areatrigger {val} not found")
            return (t["map"], 0, t["x"], t["y"], t["z"], t["o"])
        if kind == "graveyard":
            return self._graveyard(val, corpse)
        if kind == "captured":
            return self._captured(val)
        if kind == "with":
            if resolved_with is None or val not in resolved_with:
                raise SeedError(
                    f"with: {val!r} names a cast member with no position of its own"
                )
            return resolved_with[val]
        raise SeedError(f"unknown anchor kind {kind!r}")

    def _captured(self, key):
        if not self.anchors.has(key):
            raise SeedError(f"captured anchor {key!r} is not in anchors.yaml")
        pos = self.anchors.position(key)
        if pos is None:
            raise SeedError(
                f"captured anchor {key!r} is pending: its position was never captured"
            )
        return pos

    def _graveyard(self, val, corpse):
        if val != GRAVEYARD_NEAREST:
            g = self.r.graveyard(val)
            if g is None:
                raise SeedError(f"graveyard {val} not found")
            return (g["map"], 0, g["x"], g["y"], g["z"], 0.0)
        if corpse is None:
            raise SeedError("graveyard: nearest needs a corpse position")
        cmap, _, cx, cy, _, _ = corpse
        yards = self.r.graveyards_on_map(cmap)
        if not yards:
            raise SeedError(f"no graveyard on map {cmap}")
        g = min(yards, key=lambda y: ((y["x"] - cx) ** 2 + (y["y"] - cy) ** 2, y["id"]))
        return (cmap, 0, g["x"], g["y"], g["z"], 0.0)

    # -- compile ----------------------------------------------------------
    def run(self):
        cast = self.decree["cast"]
        by_entry = self._resolve_cast(cast)
        self.plan.members = [m for ms in by_entry for m in ms]
        self._variables(by_entry)
        arrange = [
            next(iter(item.items())) for item in self.decree.get("arrange") or []
        ]
        for kind, spec in arrange:
            if kind == "instance":
                self._instance(spec, by_entry)
        for kind, spec in arrange:
            if kind == "group":
                self._group(spec, by_entry)
            elif kind == "creature":
                self._creature_dead(spec)
        self._cast_rows(cast, by_entry)
        return self.plan

    def _resolve_cast(self, cast):
        by_entry = [self.members_of(entry["who"], i) for i, entry in enumerate(cast)]
        # A character named on its own overrides the same character inside a
        # family or guild entry: the specific entry beats the general one.
        general = ("family:", "guild:")
        named = {
            ms[0].name
            for ms, e in zip(by_entry, cast, strict=True)
            if not e["who"].startswith(general)
        }
        for i, entry in enumerate(cast):
            if entry["who"].startswith(general):
                by_entry[i] = [m for m in by_entry[i] if m.name not in named]
                if not by_entry[i]:
                    raise SeedError(
                        f"{entry['who']} has no member left once the named characters are taken out"
                    )
        seen = set()
        for m in (m for ms in by_entry for m in ms):
            if m.guid in seen:
                raise SeedError(f"{m.name} appears twice in the cast")
            seen.add(m.guid)
        return by_entry

    def _cast_rows(self, cast, by_entry):
        # Positions first (a `with` anchor reads another member's), then rows.
        resolved = {}
        for entry in cast:
            s = entry["set"]
            if "at" in s and "with" not in s["at"]:
                corpse = self.place(s["corpse_at"]) if "corpse_at" in s else None
                resolved[entry["who"]] = self.place(s["at"], corpse)
        for i, entry in enumerate(cast):
            s = entry["set"]
            corpse = self.place(s["corpse_at"]) if "corpse_at" in s else None
            at = None
            if "at" in s:
                at = resolved.get(entry["who"]) or self.place(s["at"], corpse, resolved)
            home = (
                self.place(s["homebind"], None, resolved) if "homebind" in s else None
            )
            for m in by_entry[i]:
                self._member(m, s, at, corpse, home)

    def _variables(self, by_entry):
        v = self.plan.variables
        v["cast"] = ", ".join(str(m.guid) for m in self.plan.members)
        for i, ms in enumerate(by_entry):
            v[f"cast{i}"] = ms[0].guid
        for m in self.plan.members:
            v[m.name] = m.guid
        for name, sid in gamedata.SKILLS.items():
            v[f"skill_{name.lower().replace(' ', '_')}"] = sid
        first = self.decree["cast"][0]["set"]
        info = self.r.character(by_entry[0][0].guid) or {}
        v["money_start"] = first.get("money", info.get("money", 0))
        for _name, spec in (first.get("skills") or {}).items():
            value = spec["value"] if isinstance(spec, dict) else spec
            mx = spec.get("max", value) if isinstance(spec, dict) else spec
            v.setdefault("seed_skill_value", value)
            v.setdefault("seed_skill_max", mx)

    def _instance(self, spec, by_entry):
        if spec["as"] in self.instances:
            raise SeedError(f"instance alias {spec['as']!r} is used twice")
        mp = gamedata.INSTANCE_MAPS[spec["map"]]
        iid = (
            max(self.r.max_instance_id(), *(i for i, _ in self.instances.values()), 0)
            + 1
        )
        self.instances[spec["as"]] = (iid, mp)
        self.plan.variables[spec["as"]] = iid
        self.plan.statements.append(
            self.b.insert(
                "instance",
                {"id": iid, "map": mp, "resettime": NowPlus(SEVEN_DAYS), "difficulty": 0,
                 "completedEncounters": 0, "data": ""},
            )
        )  # fmt: skip
        bound = [
            m
            for i, e in enumerate(self.decree["cast"])
            if e["who"] == spec.get("bind")
            for m in by_entry[i]
        ]
        for m in bound:
            self.plan.statements.append(
                self.b.insert(
                    "character_instance",
                    {"guid": m.guid, "instance": iid, "permanent": 1, "extended": 0},
                    replace=True,
                )
            )

    def _group(self, spec, by_entry):
        members = [
            m
            for i, e in enumerate(self.decree["cast"])
            if e["who"] == spec["members"]
            for m in by_entry[i]
        ]
        leader = [m for m in members if m.name == spec["leader"]]
        if len(leader) != 1:
            raise SeedError(
                f"group leader {spec['leader']!r} is not one of the members"
            )
        if len(members) > _MAX_RAID:
            raise SeedError("a group holds at most 40")
        gid = self.r.max_group_guid() + 1
        guids = [m.guid for m in members]
        s = self.plan.statements
        s.append(self.b.delete("group_member", {"memberGuid": guids}))
        s.append(
            self.b.insert(
                "groups",
                {"guid": gid, "leaderGuid": leader[0].guid, "lootMethod": 3, "looterGuid": 0, "lootThreshold": 2,
                 **{f"icon{n}": 0 for n in range(1, 9)}, "groupType": 2 if len(members) > 5 else 0,
                 "difficulty": 0, "raidDifficulty": 0, "masterLooterGuid": 0},
            )
        )  # fmt: skip
        for n, m in enumerate(members):
            s.append(
                self.b.insert(
                    "group_member",
                    {
                        "guid": gid,
                        "memberGuid": m.guid,
                        "memberFlags": 0,
                        "subgroup": n // 5,
                        "roles": 0,
                    },
                )
            )
        self.plan.variables["group"] = gid

    def _creature_dead(self, spec):
        if spec["in"] not in self.instances:
            raise SeedError(
                f"creature {spec['name']!r}: instance alias {spec['in']!r} was not arranged"
            )
        iid, mp = self.instances[spec["in"]]
        spawns = [s for s in self.r.creature_spawns(spec["name"]) if s["map"] == mp]
        s = self.one(spawns, f"creature {spec['name']!r} in map {mp}")
        self.plan.statements.append(
            self.b.insert(
                "creature_respawn",
                {
                    "guid": s["guid"],
                    "respawnTime": NowPlus(TEN_YEARS),
                    "mapId": mp,
                    "instanceId": iid,
                },
                replace=True,
            )
        )

    def _instance_for(self, mp):
        ids = [iid for iid, m in self.instances.values() if m == mp]
        if len(ids) > 1:
            raise SeedError(
                f"several arranged instances of map {mp}; a position cannot pick one"
            )
        if ids:
            return ids[0]
        if mp in gamedata.INSTANCE_MAPS.values():
            raise SeedError(
                f"position is inside instance map {mp} but the decree arranges no instance of it"
            )
        return 0

    def _member(self, m, s, at, corpse, home):
        cols = self._character_columns(m, s, at)
        if cols:
            self.plan.statements.append(
                self.b.update("characters", cols, {"guid": m.guid})
            )
        if s.get("alive") is False and corpse is not None:
            self._corpse(m, corpse)
        self._skills_and_spells(m, s)
        self._free_backpack(m, s.get("free_backpack_slots"))
        self._items(m, s.get("items") or [])
        for quest, state in (s.get("quests") or {}).items():
            self._quest(m, quest, state)
        if home is not None:
            hmap, hzone, hx, hy, hz, _ = home
            row = {
                "guid": m.guid,
                "mapId": hmap,
                "zoneId": hzone,
                "posX": hx,
                "posY": hy,
                "posZ": hz,
            }
            self.plan.statements.append(
                self.b.insert("character_homebind", row, replace=True)
            )

    def _character_columns(self, m, s, at):
        cols = {}
        if "level" in s:
            cols.update(level=s["level"], xp=0)
        if "money" in s:
            cols["money"] = s["money"]
        if at is not None:
            mp, zone, x, y, z, o = at
            cols.update(
                map=mp, instance_id=self._instance_for(mp), position_x=x, position_y=y, position_z=z,
                orientation=o, taxi_path="", transguid=0,
            )  # fmt: skip
            if zone:
                cols["zone"] = zone
        cols.update(self._life_columns(m, s))
        return cols

    def _life_columns(self, m, s):
        flags = (self.r.character(m.guid) or {}).get("player_flags", 0)
        if s.get("alive") is False:
            return {"health": 0, "playerFlags": flags | PLAYER_FLAG_GHOST}
        if s.get("alive") is True or "health_pct" in s:
            maxhealth = self.r.maxhealth(m.guid)
            if maxhealth <= 0:
                raise SeedError(
                    f"{m.name} has no character_stats row, so health cannot be set"
                )
            health = max(1, maxhealth * s.get("health_pct", 100) // 100)
            return {
                "health": health,
                "playerFlags": flags & ~PLAYER_FLAG_GHOST,
                "death_expire_time": 0,
            }
        return {}

    def _corpse(self, m, corpse):
        cmap, _, cx, cy, cz, co = corpse
        st = self.plan.statements
        st.append(self.b.delete("corpse", {"guid": m.guid}))
        row = {
            "guid": m.guid, "posX": cx, "posY": cy, "posZ": cz, "orientation": co, "mapId": cmap,
            "phaseMask": 1, "displayId": 0, "itemCache": "", "bytes1": 0, "bytes2": 0, "guildId": 0,
            "flags": 0, "dynFlags": 0, "time": NowPlus(0), "corpseType": 1,
            "instanceId": self._instance_for(cmap),
        }  # fmt: skip
        st.append(self.b.insert("corpse", row))

    def _skills_and_spells(self, m, s):
        st = self.plan.statements
        b = self.b
        for name, spec in (s.get("skills") or {}).items():
            value = spec["value"] if isinstance(spec, dict) else spec
            mx = spec.get("max", value) if isinstance(spec, dict) else spec
            row = {
                "guid": m.guid,
                "skill": gamedata.SKILLS[name],
                "value": value,
                "max": mx,
            }
            st.append(b.insert("character_skills", row, replace=True))
        for spell in s.get("spells_add") or []:
            st.append(
                b.insert(
                    "character_spell",
                    {"guid": m.guid, "spell": spell, "specMask": 255},
                    replace=True,
                )
            )
        for spell in s.get("spells_remove") or []:
            st.append(b.delete("character_spell", {"guid": m.guid, "spell": spell}))

    def _free_backpack(self, m, want):
        """Delete items from the highest used backpack slots until `want` slots are free.

        The throwaway world's family carries full backpacks, so a grant (a reagent, a
        key) has no slot. The removed items are the ones in the world's own copy only.
        """
        if not want:
            return
        held = sorted(self.r.backpack_items(m.guid))
        room = len(BACKPACK_SLOTS) - len(held)
        for slot, item in reversed(held):
            if room >= want:
                break
            self.plan.statements.append(
                self.b.delete(
                    "character_inventory", {"guid": m.guid, "bag": 0, "slot": slot}
                )
            )
            self.plan.statements.append(self.b.delete("item_instance", {"guid": item}))
            self._freed.setdefault(m.guid, set()).add(slot)
            room += 1

    def _items(self, m, items):
        if not items:
            return
        used = set(self.r.used_backpack_slots(m.guid)) - self._freed.get(m.guid, set())
        free = [slot for slot in BACKPACK_SLOTS if slot not in used]
        for it in items:
            rows = self.r.items(it["name"])
            row = self.one(rows, f"item {it['name']!r}")
            left = it.get("count", 1)
            stack = max(1, row["stackable"])
            while left > 0:
                if not free:
                    raise SeedError(
                        f"{m.name} has no free backpack slot for {it['name']!r}"
                    )
                n = min(left, stack)
                left -= n
                slot = free.pop(0)
                if self._item_guid is None:
                    self._item_guid = self.r.max_item_guid()
                self._item_guid += 1
                ig = self._item_guid
                self.plan.statements.append(
                    self.b.insert(
                        "item_instance",
                        {"guid": ig, "itemEntry": row["entry"], "owner_guid": m.guid, "creatorGuid": 0, "giftCreatorGuid": 0,
                         "count": n, "duration": 0, "charges": "0 0 0 0 0 ", "flags": 0, "enchantments": "0 " * 36,
                         "randomPropertyId": 0, "durability": row["max_durability"], "playedTime": 0},
                    )
                )  # fmt: skip
                self.plan.statements.append(
                    self.b.insert(
                        "character_inventory",
                        {"guid": m.guid, "bag": 0, "slot": slot, "item": ig},
                    )
                )

    def _quest_id(self, quest):
        if isinstance(quest, int):
            return quest
        if str(quest).isdigit():  # a quoted number is an id, not a title
            return int(quest)
        return self.one(self.r.quests(str(quest)), f"quest {quest!r}")

    def _quest(self, m, quest, state):
        qid = self._quest_id(quest)
        key = {"guid": m.guid, "quest": qid}
        st = self.plan.statements
        # Clear both places a quest can live, so the requested state is the only one.
        st.append(self.b.delete("character_queststatus", key))
        st.append(self.b.delete("character_queststatus_rewarded", key))
        if state == "rewarded":
            st.append(
                self.b.insert(
                    "character_queststatus_rewarded", {**key, "active": 1}, replace=True
                )
            )
        else:
            row = {**key, "status": _QUEST_STATUS[state], "explored": 0, "timer": 0}
            st.append(self.b.insert("character_queststatus", row, replace=True))


def compile_seed(decree, resolver, schema, anchors):
    """Compile a decree dict into a SeedPlan. Raises SeedError (verdict INVALID).

    The decree is linted first, so a decree that lint refuses never seeds.
    """
    findings = [
        f for f in lint.lint_document(decree, anchors, schema) if f.level == "error"
    ]
    if findings:
        raise SeedError("decree does not lint: " + "; ".join(str(f) for f in findings))
    return Compiler(decree, resolver, schema, anchors).run()
