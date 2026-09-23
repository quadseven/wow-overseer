"""The guild crafting corps (#256): who in each guild's maintenance crew holds which
trade, and what each tailor does next toward a bigger bag.

WHAT WAS ASKED FOR. Each family guild should CRAFT bigger bags instead of only
buying them (the auction house's largest are 12 slots), with the maintenance
members learning basic crafts split the way a guild officer would split them:
tailors for bags, gatherers feeding them, 14 to 16 slot bags as the target.

WHAT THE REALM SAID, which changed the plan. Read on dev (2026-09-23) from
`character_skills` and `character_spell`: the twenty maintenance members are
random bots, and the random-bot factory already gave each of them four to six
primary trades at 300. Eight of them are tailors at 300 who already know every
trainer bag up to Red Mageweave Bag and Bolt of Runecloth. Nobody needs a new
profession, and nobody has a free primary slot to take one. What they lack is
the recipes above 300 and the patterns, and the cloth and thread in the right
bags. So the corps ASSIGNS the trades they already hold, and the tailors' steps
below buy recipes at a trainer, buy patterns and thread at a vendor, gather
cloth by post, craft, and post the finished bag.

THE BAGS, MEASURED RATHER THAN REMEMBERED. Reagents come from the running
worldserver's Spell.dbc (md5 543b9fe61355b6a77a01714d52fea2e5), the grey
levels from its SkillLineAbility.dbc (md5 d8c11abfcfe70596cb9068c0e97a1d9a),
the learn ranks and costs from `acore_world.trainer_spell`, the patterns and
their vendor from `item_template` and `npc_vendor`, all read 2026-09-23:

    Runecloth Bag   14 slots  260  5 Bolt of Runecloth, 2 Rugged Leather,
                                   1 Rune Thread; Pattern 14468, sold only by
                                   Qia in Everlook (limited stock)
    Netherweave Bag 16 slots  315  4 Bolt of Netherweave, 1 Rune Thread;
                                   Outland and Northrend trainers only
    Mooncloth Bag   16 slots  300  Pattern 14499 is a 0.02% drop and no
                                   vendor sells it: reachable only if carried

PURE MODULE: rows in, a plan and sentences out. No MySQL, no clock; the bridge
reads the facts, passes them in, and writes the rows a step names.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import guildroute

TAILORING = 197
SKINNING = 393
MINING = 186
HERBALISM = 182
ALCHEMY = 171
LEATHERWORKING = 165

SKILL_NAMES = {
    TAILORING: "Tailoring",
    SKINNING: "Skinning",
    MINING: "Mining",
    HERBALISM: "Herbalism",
    ALCHEMY: "Alchemy",
    LEATHERWORKING: "Leatherworking",
}

# The command log's `source` for every row this pass writes, and the prefix the
# page and the cooldowns read back. Its own, so no other pass's window counts it.
SOURCE = "guildcorps"

# THE CORPS, IN THE ORDER A GUILD OFFICER FILLS IT. Tailors first, because bags
# are the point; then the skinners, whose Rugged Leather is in every Runecloth
# Bag; then miners and herbalists for the guild's other crafters. Two of each:
# one to work and one to cover when the first is offline or far away.
ROLES = (
    ("tailor", TAILORING, 2),
    ("skinner", SKINNING, 2),
    ("miner", MINING, 2),
    ("herbalist", HERBALISM, 2),
)


@dataclass(frozen=True)
class Recipe:
    """One tailoring craft on the road to a bag, as the realm measured it."""

    spell: int
    name: str
    makes: int
    learn_rank: int
    grey: int
    reagents: tuple
    source: str = "trainer"  # "trainer" or "pattern"
    pattern: int = 0
    slots: int = 0


BOLTS = (
    Recipe(2963, "Bolt of Linen Cloth", 2996, 1, 50, ((2589, 2),)),
    Recipe(2964, "Bolt of Woolen Cloth", 2997, 75, 105, ((2592, 3),)),
    Recipe(3839, "Bolt of Silk Cloth", 4305, 125, 145, ((4306, 4),)),
    Recipe(3865, "Bolt of Mageweave", 4339, 175, 185, ((4338, 4),)),
    Recipe(18401, "Bolt of Runecloth", 14048, 250, 260, ((14047, 4),)),
    Recipe(26745, "Bolt of Netherweave", 21840, 300, 325, ((21877, 5),)),
)

BAGS = (
    Recipe(3755, "Linen Bag", 4238, 45, 105, ((2996, 3), (2320, 3)), slots=6),
    Recipe(3757, "Woolen Bag", 4240, 80, 140, ((2997, 3), (2321, 1)), slots=8),
    Recipe(
        3813,
        "Small Silk Pack",
        4245,
        150,
        200,
        ((4305, 3), (4234, 2), (2321, 3)),
        slots=10,
    ),
    Recipe(12065, "Mageweave Bag", 10050, 225, 270, ((4339, 4), (4291, 2)), slots=12),
    Recipe(
        18405,
        "Runecloth Bag",
        14046,
        260,
        305,
        ((14048, 5), (8170, 2), (14341, 1)),
        "pattern",
        14468,
        14,
    ),
    Recipe(
        18445,
        "Mooncloth Bag",
        14155,
        300,
        345,
        ((14048, 4), (14342, 1), (14341, 1)),
        "pattern",
        14499,
        16,
    ),
    Recipe(
        26746, "Netherweave Bag", 21841, 315, 340, ((21840, 4), (14341, 1)), slots=16
    ),
)

# The ranks a trainer sells, spell -> the ceiling it gives, and the value it
# asks for (`trainer_spell`, 2026-09-23). The module buys the rank itself when
# the walk arrives; the planner only needs to know one is due.
RANKS = {
    3912: (150, 50),
    3913: (225, 125),
    12181: (300, 200),
    26791: (375, 275),
    51308: (450, 350),
}

# Threads, bought at a vendor (item_template.BuyPrice, copper each).
THREAD_PRICE = {2320: 10, 2321: 100, 4291: 500, 8343: 2000, 14341: 5000}
# The patterns a vendor sells, and what each costs (copper).
PATTERN_PRICE = {14468: 12000}
# What a buy row may pay above the list price, for the reputation discount's
# absence and nothing else: a price the planner did not expect is refused.
BUY_CEILING_NUM, BUY_CEILING_DEN = 5, 4

BOLT_OF = {r.makes: r for r in BOLTS}
BAG_ITEMS = {r.makes: r for r in BAGS}
PATH_SPELLS = frozenset(r.spell for r in BOLTS + BAGS) | frozenset(RANKS)

# How much cloth to ask for at a time: one stack.
STACK = 20
# Crafts in one batch. A batch is one pass's work for one tailor.
CRAFT_BATCH = 10
# Walks and letters one guild starts in one pass.
SUPPLY_LETTERS_PER_GUILD = 2

# How long one step waits before it is tried again for the same holder and
# the same thing, whatever the last one answered. Counted from the command log,
# so a restart forgets nothing.
COOLDOWN_MINUTES = {
    "train": 180,
    "buy": 120,
    "learn": 30,
    "craft": 5,
    "collect": 30,
    "post": 30,
    "supply": 120,
}


@dataclass(frozen=True)
class Held:
    """One carried stack: its item_instance guid, entry and count."""

    guid: int
    entry: int
    count: int = 1


@dataclass(frozen=True)
class Letter:
    """One attachment waiting in a mailbox; `ready` once delivered."""

    mail_id: int
    guid: int
    entry: int
    count: int = 1
    ready: bool = True


@dataclass(frozen=True)
class Member:
    """One guild member as the bridge read it."""

    name: str
    guild: str
    class_id: int = 0
    level: int = 0
    online: bool = False
    map_id: int | None = None
    maintenance: bool = False
    family: bool = False
    skills: dict = field(default_factory=dict)  # skill -> (value, max)
    known: frozenset = frozenset()
    carried: tuple = ()  # Held
    mail: tuple = ()  # Letter
    worn_bags: tuple = ()  # ContainerSlots of each worn bag, family only

    def skill(self, skill_id) -> tuple:
        value, cap = self.skills.get(int(skill_id), (0, 0))
        return int(value or 0), int(cap or 0)

    def count(self, entry) -> int:
        return sum(int(h.count) for h in self.carried if int(h.entry) == int(entry))

    def incoming(self, entry) -> int:
        return sum(int(x.count) for x in self.mail if int(x.entry) == int(entry))


# ---------------------------------------------------------------------------
# THE CORPS: who does what, from the trades they already hold.


@dataclass(frozen=True)
class Post:
    name: str
    role: str
    skill: int
    value: int
    cap: int

    @property
    def said(self) -> str:
        return "%s %s %d/%d" % (
            self.role,
            SKILL_NAMES.get(self.skill, "?"),
            self.value,
            self.cap,
        )


def _rank_for(member: Member, skill: int) -> tuple:
    """Higher is better: the ceiling first (room to grow), then the value."""
    value, cap = member.skill(skill)
    return (cap, value, 1 if member.online else 0)


def plan_corps(members) -> dict:
    """guild -> tuple of Post, from each guild's maintenance members.

    Each member takes at most one post; a role is filled by whoever holds the
    trade highest, and a member who holds none of them keeps the dues job.
    """
    guilds = {}
    for member in members or ():
        if member.maintenance:
            guilds.setdefault(member.guild, []).append(member)
    out = {}
    for guild, crew in sorted(guilds.items()):
        taken, posts = set(), []
        for role, skill, want in ROLES:
            holders = [m for m in crew if m.name not in taken and m.skill(skill)[0] > 0]
            holders.sort(key=lambda m: (_rank_for(m, skill), m.name), reverse=True)
            for m in holders[:want]:
                value, cap = m.skill(skill)
                posts.append(Post(m.name, role, skill, value, cap))
                taken.add(m.name)
        out[guild] = tuple(posts)
    return out


# ---------------------------------------------------------------------------
# A TAILOR'S NEXT STEP.


@dataclass(frozen=True)
class Row:
    """One overseer_command row: kind, command, target_arg and source."""

    kind: str
    command: str
    target_arg: str = ""
    source: str = ""


@dataclass(frozen=True)
class Step:
    """What one holder does this pass.

    `walk` is written first; `rows` are written once the walk arrives (or at
    once when there is no walk). `repeat` asks the bridge to write `rows[0]`
    that many times in a row, one at a time, for a craft batch.
    """

    holder: str
    action: str
    key: int
    said: str
    rows: tuple = ()
    walk: Row | None = None
    repeat: int = 1


def source_for(action, key) -> str:
    return "%s:%s:%d" % (SOURCE, action, int(key))


def _walk_to_mailbox(action, key) -> Row:
    return Row(
        "mail",
        "%s max:%d" % (guildroute.WALK_VERB, int(guildroute.MAIL_RUN_YARDS)),
        "",
        source_for(action + "-walk", key),
    )


def _ceiling(copper) -> int:
    return int(copper) * BUY_CEILING_NUM // BUY_CEILING_DEN


def _cloth_for(recipe: Recipe) -> tuple:
    """(cloth entry, per bolt) for a bolt recipe."""
    entry, count = recipe.reagents[0]
    return int(entry), int(count)


def _vendor_reagent(entry) -> bool:
    return int(entry) in THREAD_PRICE


def _reach(
    bag: Recipe, tailor: Member, trainable: frozenset, vendors: frozenset
) -> str:
    """How this tailor could come to know this bag: "" when it cannot."""
    if bag.spell in tailor.known:
        return "known"
    if bag.source == "trainer":
        return "trainer" if bag.spell in trainable else ""
    if tailor.count(bag.pattern):
        return "pattern"
    return "vendor" if bag.pattern in vendors else ""


def _bolt_usable(bolt: Recipe, tailor: Member, trainable: frozenset) -> bool:
    value, _ = tailor.skill(TAILORING)
    return value >= bolt.learn_rank and (
        bolt.spell in tailor.known or bolt.spell in trainable
    )


def _guild_total(entry, members) -> int:
    """What the guild can put in a tailor's hands: the family is not counted,
    because a roster character cannot be walked to a mailbox by a row."""
    return sum(m.count(entry) + m.incoming(entry) for m in members if not m.family)


def _materials_exist(bag, tailor, members, trainable, vendors) -> bool:
    """Can the guild, between its members, make this bag at all?"""
    for entry, need in bag.reagents:
        if _vendor_reagent(entry):
            if entry not in vendors and tailor.count(entry) < need:
                return False
            continue
        bolt = BOLT_OF.get(int(entry))
        have = _guild_total(entry, members)
        if bolt is not None and have < need:
            if not _bolt_usable(bolt, tailor, trainable):
                return False
            cloth, per = _cloth_for(bolt)
            if have + _guild_total(cloth, members) // per < need:
                return False
        elif bolt is None and have < need:
            return False
    return True


def target_bag(tailor, members, trainable, vendors):
    """(bag, reach) the tailor works toward now, or (None, why)."""
    value, _ = tailor.skill(TAILORING)
    for bag in sorted(BAGS, key=lambda r: (r.slots, r.learn_rank), reverse=True):
        if value < bag.learn_rank:
            continue
        reach = _reach(bag, tailor, trainable, vendors)
        if reach and _materials_exist(bag, tailor, members, trainable, vendors):
            return bag, reach
    return None, "no bag its skill allows can be learned and supplied on its map"


def skillup_bolt(tailor, members, trainable):
    """The bolt that still teaches this tailor something, if the guild has the cloth."""
    value, cap = tailor.skill(TAILORING)
    if value >= cap:
        return None  # at its ceiling nothing teaches it anything: a rank first
    for bolt in sorted(BOLTS, key=lambda r: r.learn_rank, reverse=True):
        if not (bolt.learn_rank <= value < bolt.grey):
            continue
        if not _bolt_usable(bolt, tailor, trainable):
            continue
        cloth, per = _cloth_for(bolt)
        if _guild_total(cloth, members) >= per:
            return bolt
    return None


def _due_rank(tailor, trainable) -> int:
    """The rank spell a trainer on the map would sell now, 0 when none."""
    value, cap = tailor.skill(TAILORING)
    for spell, (gives, needs) in sorted(RANKS.items(), key=lambda kv: kv[1][0]):
        if gives > cap and value >= needs and spell in trainable:
            return spell
    return 0


def _recipient(bag, family):
    """The family member whose smallest worn bag this bag improves most."""
    best = None
    for member in family or ():
        worn = list(member.worn_bags) + [0] * max(0, 4 - len(member.worn_bags))
        smallest = min(worn) if worn else 0
        if smallest >= bag.slots:
            continue
        key = (smallest, member.name)
        if best is None or key < best[0]:
            best = (key, member)
    return best[1] if best else None


def _post_step(tailor, family):
    for held in tailor.carried:
        bag = BAG_ITEMS.get(int(held.entry))
        if bag is None:
            continue
        taker = _recipient(bag, family)
        if taker is None:
            continue
        return Step(
            tailor.name,
            "post",
            bag.makes,
            "%s posts the %s it made to %s, whose smallest bag is %d slots"
            % (tailor.name, bag.name, taker.name, min(list(taker.worn_bags) or [0])),
            rows=(
                Row(
                    "mail",
                    "send item:%d subject:%s" % (int(held.guid), bag.name),
                    taker.name,
                    source_for("post", bag.makes),
                ),
            ),
            walk=_walk_to_mailbox("post", bag.makes),
        )
    return None


def _path_entries() -> frozenset:
    entries = set(PATTERN_PRICE) | set(THREAD_PRICE)
    for recipe in BOLTS + BAGS:
        entries.add(recipe.makes)
        entries.update(int(e) for e, _ in recipe.reagents)
    return frozenset(entries)


PATH_ENTRIES = _path_entries()


def _collect_step(tailor):
    ready = [x for x in tailor.mail if x.ready and int(x.entry) in PATH_ENTRIES]
    if not ready:
        return None
    rows = tuple(
        Row(
            "mail",
            "take-item mail:%d item:%d" % (int(x.mail_id), int(x.guid)),
            "",
            source_for("collect", x.entry),
        )
        for x in ready[:6]
    )
    return Step(
        tailor.name,
        "collect",
        int(ready[0].entry),
        "%s walks to a mailbox to collect %d letter(s) of materials"
        % (tailor.name, len(rows)),
        rows=rows,
        walk=_walk_to_mailbox("collect", ready[0].entry),
    )


def _craft(tailor, recipe, count, why) -> Step:
    return Step(
        tailor.name,
        "craft",
        recipe.spell,
        "%s crafts %d %s (%s)" % (tailor.name, count, recipe.name, why),
        rows=(Row("cast", str(recipe.spell), "", source_for("craft", recipe.spell)),),
        repeat=max(1, int(count)),
    )


def _buy(tailor, entry, count, price, name) -> Step:
    return Step(
        tailor.name,
        "buy",
        entry,
        "%s walks to a vendor to buy %d %s" % (tailor.name, count, name),
        rows=(
            Row(
                "buy",
                "entry:%d count:%d max:%d" % (entry, count, _ceiling(price * count)),
                "",
                source_for("buy", entry),
            ),
        ),
        walk=Row(
            "buy", "walk-to-vendor item:%d" % entry, "", source_for("buy-walk", entry)
        ),
    )


def _can_make(tailor, recipe) -> int:
    """How many of this recipe the tailor's own bags can make now."""
    if recipe.spell not in tailor.known:
        return 0
    return min(tailor.count(e) // int(n) for e, n in recipe.reagents)


def _learnable(recipe, tailor, trainable) -> bool:
    """A trainer on the tailor's map teaches this recipe, and its skill allows it."""
    value, _ = tailor.skill(TAILORING)
    return (
        recipe.source == "trainer"
        and recipe.spell in trainable
        and recipe.spell not in tailor.known
        and value >= recipe.learn_rank
    )


def _recipes_to_train(tailor, bag, bolt, trainable) -> list:
    """The path recipes this tailor should buy at a trainer now, in order."""
    path = [bag, bolt]
    if bag is not None:
        path.extend(BOLT_OF.get(int(e)) for e, _ in bag.reagents)
    wanted = []
    for recipe in path:
        if recipe is not None and recipe.spell not in wanted:
            if _learnable(recipe, tailor, trainable):
                wanted.append(recipe.spell)
    return wanted


def _train_step(tailor, bag, bolt, trainable):
    wanted = _recipes_to_train(tailor, bag, bolt, trainable)
    rank = _due_rank(tailor, trainable)
    if not wanted and not rank:
        return None
    command = "walk-to-trainer skill:%d" % TAILORING
    if wanted:
        command += " learn:%s" % ",".join(str(s) for s in wanted)
    key = wanted[0] if wanted else rank
    return Step(
        tailor.name,
        "train",
        key,
        "%s walks to a tailoring trainer to learn %s"
        % (tailor.name, ", ".join(str(s) for s in wanted) or "the next rank"),
        rows=(Row("cast", command, "", source_for("train", key)),),
    )


def _pattern_step(tailor, bag, reach, vendors):
    """Learn the carried pattern, or buy it; None when neither applies."""
    held = next((h for h in tailor.carried if int(h.entry) == bag.pattern), None)
    if reach == "pattern" and held is None:
        reach = "vendor" if bag.pattern in vendors else ""
    if reach == "pattern":
        command = "use guid:%d" % int(held.guid)
        return Step(
            tailor.name,
            "learn",
            bag.pattern,
            "%s learns %s from the pattern it carries" % (tailor.name, bag.name),
            rows=(Row("cast", command, "", source_for("learn", bag.pattern)),),
        )
    if reach == "vendor":
        price = PATTERN_PRICE.get(bag.pattern, 0)
        return _buy(tailor, bag.pattern, 1, price, "pattern")
    return None


def _bolt_step(tailor, bag):
    """Craft the bolts the bag still lacks from cloth in the bags."""
    for entry, need in bag.reagents:
        bolt = BOLT_OF.get(int(entry))
        short = int(need) - tailor.count(entry)
        if bolt is None or short <= 0 or bolt.spell not in tailor.known:
            continue
        cloth, per = _cloth_for(bolt)
        n = min(short, tailor.count(cloth) // per)
        if n > 0:
            return _craft(tailor, bolt, n, "for the %s" % bag.name)
    return None


def _thread_step(tailor, bag, vendors):
    """Buy the vendor's thread, once everything else for the bag is in hand."""
    if not _only_thread_missing(tailor, bag):
        return None
    for entry, need in bag.reagents:
        if _vendor_reagent(entry) and tailor.count(entry) < need and entry in vendors:
            return _buy(tailor, entry, int(need), THREAD_PRICE[entry], "thread")
    return None


def _bag_steps(tailor, bag, reach, trainable, vendors):
    """The steps toward crafting `bag`, in order; the first that applies wins."""
    if reach in ("pattern", "vendor"):
        return _pattern_step(tailor, bag, reach, vendors)
    if _can_make(tailor, bag):
        return _craft(tailor, bag, 1, "the bag")
    return _bolt_step(tailor, bag) or _thread_step(tailor, bag, vendors)


def _only_thread_missing(tailor, bag) -> bool:
    """Every reagent but the vendor's is in the bags, or is cloth for a bolt."""
    for entry, need in bag.reagents:
        if _vendor_reagent(entry):
            continue
        have = tailor.count(entry)
        bolt = BOLT_OF.get(int(entry))
        if bolt is not None:
            cloth, per = _cloth_for(bolt)
            have += tailor.count(cloth) // per
        if have < need:
            return False
    return True


def _shortfall(tailor, bag, bolt) -> list:
    """(entry, count) the tailor still needs by post, most needed first."""
    need = []
    if bag is not None:
        for entry, count in bag.reagents:
            if _vendor_reagent(entry):
                continue
            have = tailor.count(entry) + tailor.incoming(entry)
            recipe = BOLT_OF.get(int(entry))
            if recipe is not None:
                cloth, per = _cloth_for(recipe)
                have += (tailor.count(cloth) + tailor.incoming(cloth)) // per
                if have < count:
                    need.append((cloth, (count - have) * per))
            elif have < count:
                need.append((int(entry), count - have))
    if bolt is not None:
        cloth, per = _cloth_for(bolt)
        if tailor.count(cloth) + tailor.incoming(cloth) < STACK:
            need.append((cloth, STACK))
    return need


def supply_steps(
    tailor, bag, bolt, members, busy, per_guild=SUPPLY_LETTERS_PER_GUILD, recent=None
):
    """Letters from guild members who carry what the tailor lacks.

    Nothing is asked for twice inside the supply cooldown: `recent` holds
    ("to:<tailor>", "supply", entry) for every letter already written to this
    tailor, because a letter in flight is not in its mailbox yet.
    """
    steps = []
    for entry, count in _shortfall(tailor, bag, bolt):
        asked = (recent or {}).get(("to:" + tailor.name, "supply", int(entry)))
        if asked is not None and asked < COOLDOWN_MINUTES["supply"]:
            continue
        left = int(count)
        senders = [
            m
            for m in members
            if m.name != tailor.name
            and not m.family
            and m.online
            and m.name not in busy
            and m.count(entry) > 0
        ]
        senders.sort(key=lambda m: (-m.count(entry), m.name))
        for sender in senders:
            if left <= 0 or len(steps) >= per_guild:
                break
            stack = max(
                (h for h in sender.carried if int(h.entry) == entry),
                key=lambda h: (int(h.count), -int(h.guid)),
            )
            steps.append(
                Step(
                    sender.name,
                    "supply",
                    entry,
                    "%s posts %d of item %d to %s for the corps"
                    % (sender.name, int(stack.count), entry, tailor.name),
                    rows=(
                        Row(
                            "mail",
                            "send item:%d subject:For the guild tailor"
                            % int(stack.guid),
                            tailor.name,
                            source_for("supply", entry),
                        ),
                    ),
                    walk=_walk_to_mailbox("supply", entry),
                )
            )
            busy.add(sender.name)
            left -= int(stack.count)
    return steps


def tailor_step(tailor, members, family, trainable, vendors):
    """(Step or None, note): this tailor's one step this pass, and why."""
    if not tailor.online:
        return None, "%s is offline" % tailor.name
    step = _post_step(tailor, family)
    if step:
        return step, ""
    step = _collect_step(tailor)
    if step:
        return step, ""
    bag, reach = target_bag(tailor, members, trainable, vendors)
    bolt = skillup_bolt(tailor, members, trainable)
    step = _train_step(tailor, bag, bolt, trainable)
    if step:
        return step, ""
    if bag is not None:
        step = _bag_steps(tailor, bag, reach, trainable, vendors)
        if step:
            return step, ""
    if bolt is not None and bolt.spell in tailor.known:
        cloth, per = _cloth_for(bolt)
        n = min(CRAFT_BATCH, tailor.count(cloth) // per)
        if n > 0:
            return _craft(tailor, bolt, n, "a skill-up"), ""
    what = bag.name if bag is not None else reach
    return None, "%s waits for materials (%s)" % (tailor.name, what)


def _cooling(step, recent) -> bool:
    minutes = COOLDOWN_MINUTES.get(step.action, 30)
    age = (recent or {}).get((step.holder, step.action, int(step.key)))
    return age is not None and age < minutes


@dataclass(frozen=True)
class CorpsPlan:
    corps: dict
    steps: tuple = ()
    notes: tuple = ()


def _supply_for(tailor, crew, trainable, vendors, busy, room, recent) -> list:
    """Letters the guild posts to a tailor that has no step of its own."""
    bag, _ = target_bag(tailor, crew, trainable, vendors)
    bolt = skillup_bolt(tailor, crew, trainable)
    letters = supply_steps(tailor, bag, bolt, crew, busy, room, recent)
    return [s for s in letters if not _cooling(s, recent)]


def _guild_steps(guild_facts, posts, recent, busy, steps, notes) -> None:
    """One guild's tailors: a step each, or letters from their guildmates."""
    crew, family, trainable_by_map, vendors_by_map = guild_facts
    named = {m.name: m for m in crew}
    letters = 0
    for post in posts:
        if post.role != "tailor":
            continue
        tailor = named.get(post.name)
        if tailor is None:
            notes.append("%s holds a post and is missing from the crew" % post.name)
            continue
        if tailor.name in busy:
            notes.append("%s is already on a corps errand" % tailor.name)
            continue
        trainable = frozenset((trainable_by_map or {}).get(tailor.map_id, ()))
        vendors = frozenset((vendors_by_map or {}).get(tailor.map_id, ()))
        step, why = tailor_step(tailor, crew, family, trainable, vendors)
        if step is not None and not _cooling(step, recent):
            steps.append(step)
            busy.add(tailor.name)
            continue
        notes.append(
            "%s: %s waits out its cooldown" % (tailor.name, step.action)
            if step
            else why
        )
        if tailor.online and letters < SUPPLY_LETTERS_PER_GUILD:
            room = SUPPLY_LETTERS_PER_GUILD - letters
            sent = _supply_for(tailor, crew, trainable, vendors, busy, room, recent)
            steps.extend(sent)
            letters += len(sent)


def plan(
    members, family_by_guild, trainable_by_map, vendors_by_map, recent, busy
) -> CorpsPlan:
    """Every guild's corps, and each tailor's step this pass.

    `members` are every member of every family guild (Member). `family_by_guild`
    maps a guild to its family Members. `trainable_by_map` and `vendors_by_map`
    map a map id to the tailoring spells a trainer there teaches and the items a
    vendor there sells. `recent` maps (holder, action, key) to the minutes since
    the last row of that step; `busy` holds names already on a walk.
    """
    corps = plan_corps(members)
    by_guild = {}
    for m in members or ():
        by_guild.setdefault(m.guild, []).append(m)
    busy = set(busy or ())
    steps, notes = [], []
    for guild, posts in sorted(corps.items()):
        facts = (
            by_guild.get(guild, []),
            (family_by_guild or {}).get(guild, ()),
            trainable_by_map,
            vendors_by_map,
        )
        _guild_steps(facts, posts, recent, busy, steps, notes)
    return CorpsPlan(
        corps=corps, steps=tuple(steps), notes=tuple(n for n in notes if n)
    )


# ---------------------------------------------------------------------------
# WHAT THE PAGE SAYS.


def _made(row) -> bool:
    """A craft row the world says completed: applied, and not a refusal."""
    if str(row.get("status") or "") != "applied":
        return False
    result = row.get("result")
    try:
        body = json.loads(result) if isinstance(result, str) else (result or {})
    except (TypeError, ValueError):
        return True
    return not isinstance(body, dict) or body.get("outcome") != "refused"


def bags_made(rows) -> dict:
    """name -> {bag name: count} from the corps' craft rows."""
    names = {r.spell: r.name for r in BAGS}
    out = {}
    for row in rows or ():
        source = str(row.get("source") or "")
        parts = source.split(":")
        if len(parts) != 3 or parts[0] != SOURCE or parts[1] != "craft":
            continue
        try:
            spell = int(parts[2])
        except ValueError:
            continue
        if spell not in names or not _made(row):
            continue
        who = str(row.get("target_name") or "")
        out.setdefault(who, {})
        out[who][names[spell]] = out[who].get(names[spell], 0) + 1
    return out


def corps_line(post, made) -> str:
    """One sentence for a member's corps post and what it has made."""
    line = "corps: %s" % post.said
    bags = (made or {}).get(post.name) or {}
    if bags:
        line += "; made " + ", ".join(
            "%d %s" % (n, name) for name, n in sorted(bags.items())
        )
    return line


def attach_corps(lineup, posts, made) -> dict:
    """The lineup with a `corps` line on each posted maintenance member.

    `lineup` is one guild's `raidlineup.build_lineup` result, changed in place
    and returned; `posts` are that guild's `plan_corps` posts.
    """
    by_name = {p.name: p for p in posts or ()}
    total = 0
    for member in lineup.get("maintenance") or ():
        post = by_name.get(member.get("name"))
        if post is None:
            continue
        member["corps"] = corps_line(post, made)
        member["profession"] = {
            "role": post.role,
            "skill": SKILL_NAMES.get(post.skill, ""),
            "value": post.value,
            "max": post.cap,
        }
        total += sum(((made or {}).get(post.name) or {}).values())
    lineup["corps"] = {
        "bags_made": total,
        "said": "crafting corps: %d bag%s made" % (total, "" if total == 1 else "s"),
    }
    return lineup


# ---------------------------------------------------------------------------
# FROM THE BRIDGE'S ROWS.


def _int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _grouped(rows, key, make) -> dict:
    """`make(row)` for each row, grouped by the int in `key`."""
    out = {}
    for row in rows or ():
        out.setdefault(_int(row.get(key)), []).append(make(row))
    return out


def _held_from(row) -> Held:
    return Held(
        _int(row.get("item_guid")), _int(row.get("entry")), _int(row.get("count"), 1)
    )


def _letter_from(row) -> Letter:
    return Letter(
        _int(row.get("mail_id")),
        _int(row.get("item_guid")),
        _int(row.get("entry")),
        _int(row.get("count"), 1),
        bool(_int(row.get("ready"))),
    )


def _skill_pair(row) -> tuple:
    return _int(row.get("skill")), (_int(row.get("value")), _int(row.get("max")))


def members_from_rows(
    member_rows,
    skill_rows,
    spell_rows,
    item_rows,
    mail_rows,
    bag_rows,
    maintenance,
    family,
):
    """Member facts out of the rows the bridge read; no judgement here.

    `member_rows` carry guild_name, guid, name, class_id, level, online and
    map_id, one per member of every family guild. The other rows are keyed by
    `guid` (skills, spells), `owner` (carried stacks, worn bag slots) or
    `receiver` (mail). `maintenance` and `family` are sets of names.
    """
    maintenance = {str(n) for n in maintenance or ()}
    family = {str(n) for n in family or ()}
    skills = _grouped(skill_rows, "guid", _skill_pair)
    known = _grouped(spell_rows, "guid", lambda r: _int(r.get("spell")))
    carried = _grouped(item_rows, "owner", _held_from)
    mail = _grouped(mail_rows, "receiver", _letter_from)
    bags = _grouped(bag_rows, "owner", lambda r: _int(r.get("slots")))
    out = []
    for row in member_rows or ():
        name, guid = str(row.get("name") or ""), _int(row.get("guid"))
        if not name or not guid:
            continue
        map_id = row.get("map_id")
        out.append(
            Member(
                name=name,
                guild=str(row.get("guild_name") or ""),
                class_id=_int(row.get("class_id")),
                level=_int(row.get("level")),
                online=bool(_int(row.get("online"))),
                map_id=None if map_id is None else _int(map_id),
                maintenance=name in maintenance,
                family=name in family,
                skills=dict(skills.get(guid, ())),
                known=frozenset(known.get(guid, ())),
                carried=tuple(carried.get(guid, ())),
                mail=tuple(mail.get(guid, ())),
                worn_bags=tuple(sorted(bags.get(guid, ()))),
            )
        )
    return out


def places_from_rows(rows, column) -> dict:
    """map id -> frozenset of `column` values, from (map_id, column) rows."""
    out = {}
    for row in rows or ():
        out.setdefault(_int(row.get("map_id")), set()).add(_int(row.get(column)))
    return {k: frozenset(v) for k, v in out.items()}


def recent_from_rows(rows) -> dict:
    """(holder, action, key) -> minutes since the newest corps row of that step.

    A walk row counts for the step it opens. A supply letter also counts under
    ("to:<tailor>", "supply", entry), so a tailor is not asked for twice.
    """
    out = {}

    def note(key, age):
        if key not in out or age < out[key]:
            out[key] = age

    for row in rows or ():
        parts = str(row.get("source") or "").split(":")
        if len(parts) != 3 or parts[0] != SOURCE:
            continue
        action = parts[1][: -len("-walk")] if parts[1].endswith("-walk") else parts[1]
        key, age = _int(parts[2], -1), _int(row.get("age"), 0)
        note((str(row.get("target_name") or ""), action, key), age)
        if action == "supply" and row.get("target_arg"):
            note(("to:" + str(row["target_arg"]), "supply", key), age)
    return out


def posts_for_lineup(lineup, guild, skill_rows) -> tuple:
    """The corps posts for one guild's lineup, from name-keyed skill rows.

    The page's own read: `skill_rows` carry name, skill, value and max.
    """
    by_name = {}
    for row in skill_rows or ():
        by_name.setdefault(str(row.get("name") or ""), {})[_int(row.get("skill"))] = (
            _int(row.get("value")),
            _int(row.get("max")),
        )
    crew = [
        Member(
            name=str(m.get("name")),
            guild=guild,
            maintenance=True,
            skills=by_name.get(str(m.get("name")), {}),
        )
        for m in lineup.get("maintenance") or ()
    ]
    return plan_corps(crew).get(guild, ())
