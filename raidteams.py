"""The approved raid teams: who raids in which group, who summons, who keeps
the guild running, and who leaves (operator, 2026-10-05).

WHY THIS EXISTS. raidlineup.build_lineup fills forty seats from whatever a
guild holds, as eight groups of one tank, one healer and three damage. That is
a five-man dungeon's shape, not Molten Core's. The operator approved a lineup
built for Ragnaros instead: per guild, 8 tanks (Garr's 8 adds), 11 healers and
21 damage, a fire resistance source (a paladin aura or a shaman totem, both
party-only in 3.3.5) in every group, group 1 the family, groups 2 to 8 named
from B to H. Missing roles are recruited at level 1 and the surplus leaves;
nobody respecs. The 21 warlock summoners stay summoners.

NAMES. Every seat names the character as the operator named it and, until the
rename lands, the name it has now (`was`), so the lineup holds before and
after the renames. A seat with no `was` and no character of its name yet is a
recruit still to come: the lineup reports it as an open seat.

PURE: data and lookups only.
"""

from __future__ import annotations

from typing import NamedTuple


class Seat(NamedTuple):
    name: str  # the approved name
    was: str  # the name it has until the rename, or "" (unchanged or a recruit)
    class_id: int
    tree: str  # the talent tree the seat plays
    seat: str  # raidroles.SEAT_TANK, SEAT_HEALER or SEAT_DAMAGE
    race: str
    fire_resistance: bool  # this group's fire resistance aura or totem


GROUPS = {
    "Cave": (
        (  # group 1
            Seat("Grug", "", 1, "Protection", "tank", "Human", False),
            Seat("Ugga", "", 5, "Holy", "healer", "Human", False),
            Seat("Grog", "", 2, "Retribution", "dps", "Dwarf", True),
            Seat("Bork", "", 4, "Combat", "dps", "Gnome", False),
            Seat("Og", "", 8, "Frost", "dps", "Human", False),
        ),
        (  # group 2
            Seat("Brug", "Aalall", 6, "Blood", "tank", "Draenei", False),
            Seat("Bonk", "Goraraa", 2, "Retribution", "dps", "Draenei", True),
            Seat("Bunga", "Barem", 5, "Holy", "healer", "Draenei", False),
            Seat("Brakk", "Auren", 7, "Enhancement", "dps", "Draenei", False),
            Seat("Bluk", "Aurehun", 7, "Enhancement", "dps", "Draenei", False),
        ),
        (  # group 3
            Seat("Crag", "Annian", 1, "Protection", "tank", "Night Elf", False),
            Seat("Clobba", "Asvil", 2, "Retribution", "dps", "Draenei", True),
            Seat("Clunk", "Asparano", 5, "Holy", "healer", "Human", False),
            Seat("Cronk", "Ganras", 7, "Enhancement", "dps", "Draenei", False),
            Seat("Chukk", "Achevar", 3, "Survival", "dps", "Draenei", False),
        ),
        (  # group 4
            Seat("Durg", "Krebraco", 1, "Protection", "tank", "Gnome", False),
            Seat("Drogg", "Aurevil", 2, "Retribution", "dps", "Draenei", True),
            Seat("Dunga", "Bramitho", 5, "Holy", "healer", "Dwarf", False),
            Seat("Dakk", "Beerix", 7, "Enhancement", "dps", "Draenei", False),
            Seat("Dug", "Ariaad", 3, "Survival", "dps", "Draenei", False),
        ),
        (  # group 5
            Seat("Erg", "Eveline", 1, "Protection", "tank", "Human", False),
            Seat("Embo", "Ahgeathou", 2, "Retribution", "dps", "Dwarf", True),
            Seat("Ekka", "Actehuurn", 5, "Holy", "healer", "Draenei", False),
            Seat("Ezzo", "", 7, "Restoration", "healer", "Draenei", False),
            Seat("Eggrok", "Derred", 8, "Frost", "dps", "Draenei", False),
        ),
        (  # group 6
            Seat("Flintt", "Selie", 1, "Protection", "tank", "Human", False),
            Seat("Frakk", "Anneve", 2, "Retribution", "dps", "Human", True),
            Seat("Fumma", "Aurerim", 5, "Holy", "healer", "Draenei", False),
            Seat("Fizzog", "", 7, "Restoration", "healer", "Draenei", False),
            Seat("Fuggo", "", 9, "Affliction", "dps", "Gnome", False),
        ),
        (  # group 7
            Seat("Gronk", "Nangri", 1, "Protection", "tank", "Dwarf", False),
            Seat("Gakk", "Aeshontu", 2, "Retribution", "dps", "Dwarf", True),
            Seat("Gugga", "Aylysae", 5, "Holy", "healer", "Night Elf", False),
            Seat("Glob", "", 11, "Restoration", "healer", "Night Elf", False),
            Seat("Gorrk", "", 9, "Affliction", "dps", "Human", False),
        ),
        (  # group 8
            Seat("Hurk", "Bytkiz", 1, "Protection", "tank", "Gnome", False),
            Seat("Hokk", "Baleron", 2, "Retribution", "dps", "Human", True),
            Seat("Hugga", "Bazeite", 5, "Holy", "healer", "Dwarf", False),
            Seat("Haggo", "", 9, "Destruction", "dps", "Gnome", False),
            Seat("Hrunt", "", 9, "Destruction", "dps", "Human", False),
        ),
    ),
    "Bonkers": (
        (  # group 1
            Seat("Zug", "", 1, "Protection", "tank", "Orc", False),
            Seat("Uzza", "", 5, "Holy", "healer", "Troll", False),
            Seat("Zrog", "", 7, "Enhancement", "dps", "Orc", True),
            Seat("Zork", "", 11, "Feral Combat", "dps", "Tauren", False),
            Seat("Oz", "", 8, "Fire", "dps", "Troll", False),
        ),
        (  # group 2
            Seat("Bigzug", "Dakturm", 1, "Protection", "tank", "Orc", False),
            Seat("Blingz", "Velalenn", 2, "Holy", "healer", "Blood Elf", True),
            Seat("Bigmon", "Bazmoth", 5, "Holy", "healer", "Troll", False),
            Seat("Bongo", "Xahtugu", 8, "Frost", "dps", "Troll", False),
            Seat("Bonesy", "", 9, "Affliction", "dps", "Undead", False),
        ),
        (  # group 3
            Seat("Chillmon", "Dazmah", 1, "Protection", "tank", "Troll", False),
            Seat("Coom", "", 7, "Enhancement", "dps", "Orc", True),
            Seat("Coiffure", "Belethos", 5, "Holy", "healer", "Blood Elf", False),
            Seat("Cooltusk", "Almun", 4, "Combat", "dps", "Troll", False),
            Seat("Cowpoke", "Dutlan", 3, "Survival", "dps", "Tauren", False),
        ),
        (  # group 4
            Seat("Dreadlox", "Eazoth", 1, "Protection", "tank", "Troll", False),
            Seat("Dairymoo", "", 7, "Restoration", "healer", "Tauren", True),
            Seat("Divalicious", "Ansalia", 5, "Holy", "healer", "Blood Elf", False),
            Seat("Deadbeat", "Elis", 4, "Combat", "dps", "Undead", False),
            Seat("Dazzlebow", "Alavie", 3, "Survival", "dps", "Blood Elf", False),
        ),
        (  # group 5
            Seat("Eyesocket", "Astitan", 1, "Protection", "tank", "Undead", False),
            Seat("Everymon", "", 7, "Enhancement", "dps", "Troll", True),
            Seat("Eyeliner", "Azaedine", 5, "Holy", "healer", "Blood Elf", False),
            Seat("Elbowbone", "Cario", 4, "Combat", "dps", "Undead", False),
            Seat("Elfabulous", "Aellen", 4, "Combat", "dps", "Blood Elf", False),
        ),
        (  # group 6
            Seat("Fleshless", "Aradak", 1, "Protection", "tank", "Undead", False),
            Seat("Fancyhair", "", 2, "Retribution", "dps", "Blood Elf", True),
            Seat("Femur", "Biannise", 5, "Holy", "healer", "Undead", False),
            Seat("Funkymon", "Viwece", 3, "Beast Mastery", "dps", "Troll", False),
            Seat("Frostymon", "Xohjaz", 8, "Frost", "dps", "Troll", False),
        ),
        (  # group 7
            Seat("Ghoulish", "Daidanden", 1, "Protection", "tank", "Undead", False),
            Seat("Grassfed", "", 7, "Restoration", "healer", "Tauren", True),
            Seat("Groovymon", "Ahehro", 5, "Holy", "healer", "Troll", False),
            Seat("Gnarlytusk", "Gonka", 8, "Frost", "dps", "Troll", False),
            Seat("Grumpzug", "", 9, "Demonology", "dps", "Orc", False),
        ),
        (  # group 8
            Seat("Hairspray", "Quelmin", 2, "Protection", "tank", "Blood Elf", True),
            Seat("Hoofhearted", "", 11, "Restoration", "healer", "Tauren", False),
            Seat("Halfdead", "Arianah", 8, "Frost", "dps", "Undead", False),
            Seat("Hungrygrunt", "", 9, "Destruction", "dps", "Orc", False),
            Seat("Highlights", "", 9, "Destruction", "dps", "Blood Elf", False),
        ),
    ),
}

# (name now, approved name) for the 21 warlock summoners.
SUMMONERS = {
    "Cave": (
        ("Nyflyllen", "Ooga"),
        ("Fineklees", "Booga"),
        ("Ceneelkarn", "Mok"),
        ("Fincizz", "Rokk"),
        ("Bitlubro", "Thog"),
        ("Fugotik", "Krog"),
        ("Oswalt", "Snarg"),
        ("Fuxek", "Wukk"),
        ("Hellengi", "Yugg"),
        ("Alindy", "Nubb"),
        ("Flanu", "Pogg"),
        ("Avenah", "Tukk"),
        ("Fitozz", "Lugg"),
        ("Oden", "Mukk"),
        ("Hebus", "Sogg"),
        ("Helindy", "Vugg"),
        ("Gleenkick", "Jubb"),
        ("Danderollo", "Yobb"),
        ("Amilyn", "Kekk"),
        ("Caelianon", "Oot"),
        ("Cesca", "Zotz"),
    ),
    "Bonkers": (
        ("Grerarm", "Swoleblood"),
        ("Mutuk", "Zugzugz"),
        ("Casonik", "Grumbles"),
        ("Atkermi", "Tusktusk"),
        ("Dumdith", "Workwork"),
        ("Blandorion", "Rotney"),
        ("Ginny", "Skelly"),
        ("Amony", "Bonejangles"),
        ("Carancan", "Deadpan"),
        ("Eduin", "Ribcage"),
        ("Belaney", "Stinkfoot"),
        ("Emeranka", "Ghoulia"),
        ("Lengie", "Jawless"),
        ("Doriana", "Morbidly"),
        ("Nomarrin", "Sparklez"),
        ("Bacden", "Glitterz"),
        ("Astalnath", "Shinyhair"),
        ("Azarise", "Prettyboi"),
        ("Feyda", "Fabulosa"),
        ("Loeron", "Manicure"),
        ("Allenn", "Selfie"),
    ),
}

# (name now, approved name) for the 10 maintenance members.
MAINTENANCE = {
    "Cave": (
        ("Baall", "Chopp"),
        ("Balressian", "Diggo"),
        ("Arran", "Pokka"),
        ("Baldam", "Rubba"),
        ("Aehuurn", "Skinna"),
        ("Behodiir", "Stakk"),
        ("Bakurn", "Totta"),
        ("Atherene", "Whakk"),
        ("Alemid", "Snipp"),
        ("Auremir", "Tugga"),
    ),
    "Bonkers": (
        ("Argam", "Grunty"),
        ("Cigtek", "Lokkie"),
        ("Cokderl", "Snotgob"),
        ("Alestheon", "Twinkletoes"),
        ("Inhen", "Glamhands"),
        ("Glolana", "Lipgloss"),
        ("Bezki", "Mellowmon"),
        ("Zora", "Yamon"),
        ("Deladoris", "Gutsy"),
        ("Dianore", "Nobody"),
    ),
}

# Members who leave the guild to make room for the recruits.
LEAVING = {
    "Cave": (
        "Annestia",
        "Aristina",
        "Astamara",
        "Becalin",
        "Alylienne",
        "Ameth",
        "Arehr",
    ),
    "Bonkers": (
        "Whiona",
        "Farrin",
        "Agalan",
        "Adalok",
        "Dalene",
        "Zanron",
        "Wylstus",
        "Tynneda",
        "Aennian",
        "Duir",
    ),
}


def seats(guild: str) -> list:
    return [s for group in GROUPS.get(guild, ()) for s in group]


def names_of(guild: str) -> set:
    """Every name, old and approved, the guild's teams know a member by."""
    out = set()
    for s in seats(guild):
        out.add(s.name)
        if s.was:
            out.add(s.was)
    for pairs in (SUMMONERS.get(guild, ()), MAINTENANCE.get(guild, ())):
        for old, new in pairs:
            out.update((old, new))
    out.update(LEAVING.get(guild, ()))
    return out


def renames(guild: str) -> list:
    """(name now, approved name) for every member the operator renamed."""
    out = [(s.was, s.name) for s in seats(guild) if s.was]
    out += list(SUMMONERS.get(guild, ())) + list(MAINTENANCE.get(guild, ()))
    return [(old, new) for old, new in out if old and old != new]


def guild_of(member_names) -> str:
    """The approved guild whose teams hold at least half these names, or "".
    How raidlineup tells a guild with an approved lineup from any other read
    without every caller passing the guild."""
    names = {str(n) for n in member_names if n}
    if not names:
        return ""
    best, hits = "", 0
    for guild in GROUPS:
        found = len(names & names_of(guild))
        if found > hits:
            best, hits = guild, found
    return best if hits * 2 >= len(names) else ""
