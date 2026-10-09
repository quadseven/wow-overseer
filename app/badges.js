// Badges on the section nav: Members carries the stuck count, Guilds the
// chronicle items new since this device's last visit. Each provider is
//   { section, reads: [paths], compute(get, ctx) -> {n, tone, label, href} | null }
// and is refreshed on its own clock, whatever view is on screen. Sections add
// their provider here.

// The realm's timestamps without a zone are UTC (see views/_runs.js).
function utcSeconds(v) {
  const s = String(v || "").trim().replace(" ", "T");
  const t = Date.parse(/[zZ]|[+-]\d\d:?\d\d$/.test(s) ? s : s + "Z");
  return isFinite(t) ? t / 1000 : 0;
}

// Guilds: what /api/v2/chronicle (levels, runs, dungeon deaths) and /api/loot
// (notable loot) hold that is newer than the last visit, as the Chronicle tab
// tags it New. No badge on a first visit: everything would be new.
const guilds = {
  section: "guilds",
  reads: ["/api/v2/chronicle", "/api/loot"],
  compute(get, ctx) {
    const c = get("/api/v2/chronicle").data;
    if (!c || !ctx.previousVisit) return null;
    const after = ctx.previousVisit / 1000;
    const per = {};
    c.items.forEach((i) => { if (i.at > after) per[i.guild] = (per[i.guild] || 0) + 1; });
    const loot = get("/api/loot").data;
    ((loot && loot.stories) || []).forEach((s) => {
      if (c.guilds.includes(s.guild) && utcSeconds(s.at) > after) per[s.guild] = (per[s.guild] || 0) + 1;
    });
    const n = Object.values(per).reduce((a, b) => a + b, 0);
    if (!n) return null;
    const top = Object.keys(per).sort((a, b) => per[b] - per[a])[0];
    return { n, tone: "accent", label: n + " new in the chronicle since your last visit", href: "#/guilds/" + top.toLowerCase() + "/chronicle" };
  },
};

export default [guilds];
