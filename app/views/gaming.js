// The gaming section (#2075): both families, both guilds and the Major
// Moments feed, drawn only from the overseer site's existing reads
// (/api/family, /api/realm, /api/v2/roster, /api/loot). The pure shaping
// lives in models/gaming.js; this view feeds it the cached payloads and
// prints the sync state those reads report, so a failed refresh leaves
// the last good data on screen marked stale instead of blanking it.

import { html, pageHead } from "../ui.js";
import { familyKeys } from "../families.js";
import * as G from "../models/gaming.js";

const REALM = "/api/realm";
const ROSTER = "/api/v2/roster";
const LOOT = "/api/loot";
const familyPath = (key) => "/api/family?family=" + encodeURIComponent(key);

function paths(ctx) {
  return [REALM, ROSTER, LOOT, ...familyKeys().map(familyPath)];
}

export default {
  reads: (ctx) => paths(ctx),
  every: 86400000,
  title: () => "Gaming",
  render(ctx) {
    const reads = paths(ctx).map((p) => ctx.get(p));
    const failed = reads.some((r) => r && r.error);
    const at = Math.max(0, ...reads.map((r) => (r && r.at) || 0));
    const data = {
      families: G.families(familyKeys().map((k) => (ctx.get(familyPath(k)) || {}).data)),
      guilds: G.guilds(
        (ctx.get(REALM) || {}).data,
        ((ctx.get(ROSTER) || {}).data || {}).members || []
      ),
      moments: G.moments((ctx.get(LOOT) || {}).data),
    };
    const state = G.sync(null, !failed && at > 0, at || null, data);
    const syncLine = state.lastSync
      ? "Last sync " + new Date(state.lastSync).toISOString() + (failed ? " (stale: the last refresh failed, showing the last good data)" : "")
      : "Last sync not yet completed" + (failed ? " (stale: the last refresh failed)" : "");
    const fams = data.families.map((f) => html`<div class="card"><span class="b">${f.family}</span>${f.members.map((m) => html`<div><span class="b">${m.name}</span> <span>L${m.level} ${m.class}</span> <span class="muted">${m.activity}</span></div>`)}</div>`);
    const guilds = data.guilds.map((g) => html`<div class="card"><span class="b">${g.name}</span><span>${g.headline}</span><span class="muted">${g.size} members</span></div>`);
    const moments = data.moments.map((m) => html`<div class="card"><a href="${m.href}"><span class="b">${m.item}</span></a><span>${m.winner} won it from ${m.source}${m.equipped ? " and equipped it" : ""}</span></div>`);
    return html`${pageHead("Gaming", "Both families, both guilds, and the major moments, from the overseer reads.")}<p class="muted">${syncLine}</p><h2>Families</h2>${fams}<h2>Guilds</h2>${guilds}<h2>Major Moments</h2>${moments}`;
  },
};
