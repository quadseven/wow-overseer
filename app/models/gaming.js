// The gaming section (#2075): a pure aggregation of the overseer site's
// existing public-to-the-operator reads. No new data source: families come
// from /api/family payloads, guild readiness from /api/realm plus a roster,
// and Major Moments from /api/loot stories. A view feeds it the payloads it
// already fetched; this module only works out what the section prints.

export const RAID_SIZE = 40;
export const MAJOR_QUALITY = 4; // epic or better

function memberActivity(m) {
  if (m.online === false) return "offline";
  return m.zone || m.activity || (m.online ? "online" : "offline");
}

// One /api/family payload per family -> {family, members} with each
// member's name, level, class and current activity, in payload order.
export function families(payloads) {
  return (payloads || []).filter(Boolean).map((p) => ({
    family: p.family || p.name || "",
    members: (p.members || []).map((m) => ({
      name: m.name || "",
      level: m.level || 0,
      class: m.class || "",
      activity: memberActivity(m),
    })),
  }));
}

// /api/realm guilds plus roster members -> a raid-readiness headline per
// guild: how many of its members are level 60, out of a 40-man roster.
// A member names its guild when the roster says so; a lone guild with an
// unnamed roster reads the whole roster as its own.
export function guilds(realm, roster) {
  const list = (realm && realm.guilds) || [];
  const members = roster || [];
  return list.map((g) => {
    const name = g.name || "";
    const own = members.filter(
      (m) => !m.guild || String(m.guild).toLowerCase() === name.toLowerCase()
    );
    const pool = members.some((m) => m.guild) || list.length === 1 ? own : [];
    const at60 = pool.filter((m) => (m.level || 0) >= 60).length;
    return {
      name,
      size: g.size != null ? g.size : pool.length,
      at60,
      needed: Math.max(0, RAID_SIZE - at60),
      headline: at60 + " of " + RAID_SIZE + " raid-ready (level 60)",
    };
  });
}

// /api/loot stories -> Major Moments: epic-or-better loot only, with the
// winner, the source named in the story line, whether it was equipped,
// and a link back to that guild's Chronicle, where the story lives.
export function moments(loot) {
  const stories = (loot && loot.stories) || [];
  return stories
    .filter((s) => s.item && (s.item.quality || 0) >= MAJOR_QUALITY)
    .map((s) => {
      const line = s.line || "";
      const won = /^(.+?) won /.exec(line);
      const from = / from (.+?)(?: in | and |$)/.exec(line);
      const guild = String(s.guild || "").toLowerCase();
      return {
        item: s.item.name || "",
        quality: s.item.quality,
        winner: won ? won[1] : "",
        source: from ? from[1] : "",
        equipped: /equipped/i.test(line),
        at: s.at || "",
        line,
        href: guild ? "#/guilds/" + guild + "/chronicle" : "",
      };
    });
}

// The section's sync state. A successful refresh stamps lastSync and
// clears stale; a failed one keeps the last good data and its stamp, and
// marks the section stale, so old data never reads as fresh.
export function sync(prev, ok, at, data) {
  if (ok) return { lastSync: at, stale: false, data: data != null ? data : prev ? prev.data : null };
  return {
    lastSync: prev ? prev.lastSync : null,
    stale: true,
    data: prev ? prev.data : null,
  };
}
