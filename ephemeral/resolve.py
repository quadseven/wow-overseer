"""Name resolution for the seed step: names in a decree to rows in the world.

`Resolver` is the interface the compiler reads through. `SqlResolver` answers
from the world's own database over a guarded connection, using fixed SELECT
templates (parameters are bound by the driver, never formatted in). Tests use
an in-memory resolver. Every template is checked against the schema snapshot
by the unit tests, so a renamed column fails there first.
"""

# name -> SELECT template. %s is a bound parameter.
QUERIES = {
    "characters": "SELECT guid, name FROM acore_characters.characters WHERE name = %s",
    "family": (
        "SELECT c.guid, c.name, r.lead FROM acore_characters.overseer_roster r "
        "JOIN acore_characters.characters c ON c.name = r.name "
        "WHERE LOWER(r.family) = %s AND r.enabled = 1 ORDER BY r.lead DESC, c.guid"
    ),
    "guild_role": (
        "SELECT c.guid, c.name FROM acore_characters.guild g "
        "JOIN acore_characters.guild_member m ON m.guildid = g.guildid "
        "JOIN acore_characters.characters c ON c.guid = m.guid "
        "JOIN acore_characters.character_skills s ON s.guid = c.guid "
        "WHERE g.name = %s AND s.skill = %s ORDER BY s.value DESC, c.guid"
    ),
    "creature": (
        "SELECT c.guid, c.map, c.zoneId, c.position_x, c.position_y, c.position_z, c.orientation "
        "FROM acore_world.creature c JOIN acore_world.creature_template t ON t.entry = c.id "
        "WHERE t.name = %s ORDER BY c.guid"
    ),
    "gameobject": (
        "SELECT o.guid, o.map, o.zoneId, o.position_x, o.position_y, o.position_z, o.orientation "
        "FROM acore_world.gameobject o JOIN acore_world.gameobject_template t ON t.entry = o.id "
        "WHERE t.name = %s ORDER BY o.guid"
    ),
    "areatrigger": "SELECT map, x, y, z, orientation FROM acore_world.areatrigger WHERE entry = %s",
    "graveyard": "SELECT Map, x, y, z FROM acore_world.game_graveyard WHERE ID = %s",
    "graveyards_on_map": "SELECT ID, x, y, z FROM acore_world.game_graveyard WHERE Map = %s ORDER BY ID",
    "item": "SELECT entry, stackable, MaxDurability FROM acore_world.item_template WHERE name = %s ORDER BY entry",
    "quest": "SELECT ID FROM acore_world.quest_template WHERE LogTitle = %s ORDER BY ID",
    "maxhealth": "SELECT maxhealth FROM acore_characters.character_stats WHERE guid = %s",
    "character": "SELECT money, playerFlags FROM acore_characters.characters WHERE guid = %s",
    "used_slots": "SELECT slot FROM acore_characters.character_inventory WHERE guid = %s AND bag = 0",
    "max_item_guid": "SELECT COALESCE(MAX(guid), 0) FROM acore_characters.item_instance",
    "max_instance_id": "SELECT COALESCE(MAX(id), 0) FROM acore_characters.instance",
    "max_group_guid": "SELECT COALESCE(MAX(guid), 0) FROM acore_characters.`groups`",
}


class Resolver:
    """What the compiler needs to know about the world. Every method is read-only."""

    def characters(self, name):
        """[(guid, name)] for an exact character name."""
        raise NotImplementedError

    def family(self, family):
        """[(guid, name, lead)] enabled roster members of a family, leader first."""
        raise NotImplementedError

    def guild_role(self, guild, skill_id):
        """[(guid, name)] guild members with the skill, best first."""
        raise NotImplementedError

    def creature_spawns(self, name):
        """[dict(guid, map, zone, x, y, z, o)] spawns of creatures with this template name."""
        raise NotImplementedError

    def gameobject_spawns(self, name):
        raise NotImplementedError

    def areatrigger(self, trigger_id):
        """dict(map, x, y, z, o) or None."""
        raise NotImplementedError

    def graveyard(self, graveyard_id):
        """dict(map, x, y, z) or None."""
        raise NotImplementedError

    def graveyards_on_map(self, map_id):
        """[dict(id, x, y, z)]."""
        raise NotImplementedError

    def items(self, name):
        """[dict(entry, stackable, max_durability)] for an exact item name."""
        raise NotImplementedError

    def quests(self, title):
        """[quest id] for an exact quest title."""
        raise NotImplementedError

    def maxhealth(self, guid):
        raise NotImplementedError

    def character(self, guid):
        """dict(money, player_flags) or None."""
        raise NotImplementedError

    def used_backpack_slots(self, guid):
        raise NotImplementedError

    def max_item_guid(self):
        raise NotImplementedError

    def max_instance_id(self):
        raise NotImplementedError

    def max_group_guid(self):
        raise NotImplementedError


class SqlResolver(Resolver):
    def __init__(self, guarded):
        self._g = guarded

    def _q(self, name, *params):
        return self._g.query(QUERIES[name], params)

    @staticmethod
    def _spawn(row):
        return dict(zip(("guid", "map", "zone", "x", "y", "z", "o"), row))

    def characters(self, name):
        return [tuple(r) for r in self._q("characters", name)]

    def family(self, family):
        return [(r[0], r[1], bool(r[2])) for r in self._q("family", family.lower())]

    def guild_role(self, guild, skill_id):
        return [tuple(r) for r in self._q("guild_role", guild, skill_id)]

    def creature_spawns(self, name):
        return [self._spawn(r) for r in self._q("creature", name)]

    def gameobject_spawns(self, name):
        return [self._spawn(r) for r in self._q("gameobject", name)]

    def areatrigger(self, trigger_id):
        rows = self._q("areatrigger", trigger_id)
        return dict(zip(("map", "x", "y", "z", "o"), rows[0])) if rows else None

    def graveyard(self, graveyard_id):
        rows = self._q("graveyard", graveyard_id)
        return dict(zip(("map", "x", "y", "z"), rows[0])) if rows else None

    def graveyards_on_map(self, map_id):
        return [
            dict(zip(("id", "x", "y", "z"), r))
            for r in self._q("graveyards_on_map", map_id)
        ]

    def items(self, name):
        return [
            {"entry": r[0], "stackable": r[1], "max_durability": r[2]}
            for r in self._q("item", name)
        ]

    def quests(self, title):
        return [r[0] for r in self._q("quest", title)]

    def maxhealth(self, guid):
        rows = self._q("maxhealth", guid)
        return rows[0][0] if rows else 0

    def character(self, guid):
        rows = self._q("character", guid)
        return {"money": rows[0][0], "player_flags": rows[0][1]} if rows else None

    def used_backpack_slots(self, guid):
        return {r[0] for r in self._q("used_slots", guid)}

    def max_item_guid(self):
        return self._q("max_item_guid")[0][0]

    def max_instance_id(self):
        return self._q("max_instance_id")[0][0]

    def max_group_guid(self):
        return self._q("max_group_guid")[0][0]
