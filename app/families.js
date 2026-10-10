// The realm's families and the guilds they play in, as /api/realm reports
// them (its `families` and `guilds` fields, from the server's families.py).
// The router, the nav and the views draw these rather than names written
// into the app. Pure: no DOM, so node can test it.
//
// A family's slug is its key in lower case ("grug" for "Grug"); a guild's is
// its name in lower case ("cave" for "Cave"). Until the realm has answered
// both lists are empty: a route then keeps any slug it is given, and each
// view's own reads say what they can.

let fams = [];   // [{key, slug, names}], the default family first
let guildList = []; // [{name, slug, family}], in family order

const lower = (s) => String(s || "").toLowerCase();

// Take the families and guilds from an /api/realm payload. A payload without
// them (an older server, or a failed families read) changes nothing. True
// when the lists changed.
export function learn(realm) {
  if (!realm || !Array.isArray(realm.families) || !Array.isArray(realm.guilds)) return false;
  const nextFams = realm.families.filter((f) => f && f.key).map((f) => ({ key: f.key, slug: lower(f.key), names: (f.names || []).slice() }));
  const nextGuilds = realm.guilds.filter((g) => g && g.name).map((g) => ({ name: g.name, slug: lower(g.name), family: g.family || "" }));
  const changed = JSON.stringify([nextFams, nextGuilds]) !== JSON.stringify([fams, guildList]);
  fams = nextFams;
  guildList = nextGuilds;
  return changed;
}

export function families() { return fams.map((f) => ({ ...f, names: f.names.slice() })); }
export function guilds() { return guildList.map((g) => ({ ...g })); }

// "Grug", "Zug": the keys the family reads take.
export function familyKeys() { return fams.map((f) => f.key); }
export function guildSlugs() { return guildList.map((g) => g.slug); }

function guildOf(slug) { return guildList.find((g) => g.slug === lower(slug)) || null; }

// "Cave" for "cave", or "" for a guild the realm does not report.
export function guildName(slug) { const g = guildOf(slug); return g ? g.name : ""; }
// The family that plays in the guild: "Grug" for "cave", or "".
export function guildFamily(slug) { const g = guildOf(slug); return g ? g.family : ""; }
// "cave" for a guild named "Cave", or "" when it is not a family guild.
export function guildSlug(name) { const g = guildList.find((x) => x.name === name); return g ? g.slug : ""; }

// Whether a route may name this slug: one the realm reports, or any slug at
// all while the realm has not answered.
export function isFamily(slug) { return !!slug && (!fams.length || fams.some((f) => f.slug === slug)); }
export function isGuild(slug) { return !!slug && (!guildList.length || guildList.some((g) => g.slug === slug)); }

// The slug a route opens on when it names none, or "" when none is known.
export function firstFamily() { return fams.length ? fams[0].slug : ""; }
export function firstGuild() { return guildList.length ? guildList[0].slug : ""; }
