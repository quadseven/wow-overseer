// Badges on the section nav: Members carries the stuck count, Guilds the
// chronicle items new since this device's last visit. Each provider is
//   { section, reads: [paths], compute(get, ctx) -> {n, tone, label, href} | null }
// and is refreshed on its own clock, whatever view is on screen. Sections add
// their provider here.

import { toSeconds, fromClock } from "./models/time.js";

// Guilds: what /api/v2/chronicle (levels, runs, dungeon deaths) and /api/loot
// (notable loot) hold that is newer than the last visit, as the Chronicle tab
// tags it New. No badge on a first visit: everything would be new.
const guilds = {
  section: "guilds",
  reads: ["/api/v2/chronicle", "/api/loot"],
  compute(get, ctx) {
    const c = get("/api/v2/chronicle").data;
    if (!c || !ctx.previousVisit) return null;
    const after = fromClock(ctx.previousVisit);
    const per = {};
    c.items.forEach((i) => { if (i.at > after) per[i.guild] = (per[i.guild] || 0) + 1; });
    const loot = get("/api/loot").data;
    ((loot && loot.stories) || []).forEach((s) => {
      if (c.guilds.includes(s.guild) && toSeconds(s.at) > after) per[s.guild] = (per[s.guild] || 0) + 1;
    });
    const n = Object.values(per).reduce((a, b) => a + b, 0);
    if (!n) return null;
    const top = Object.keys(per).sort((a, b) => per[b] - per[a])[0];
    return { n, tone: "accent", label: n + " new in the chronicle since your last visit", href: "#/guilds/" + top.toLowerCase() + "/chronicle" };
  },
};


// Members: a warn badge with the stuck count (/api/v2/stuck), and the tab
// opens the roster filtered to them while anyone is stuck.
const members = {
  section: "members",
  reads: ["/api/v2/stuck"],
  compute(get) {
    const s = get("/api/v2/stuck");
    const n = s.data && Array.isArray(s.data.members) ? s.data.members.length : 0;
    return n ? { n, tone: "warn", label: n + " stuck", href: "#/members?stuck=1" } : null;
  },
};

export default [guilds, members];
