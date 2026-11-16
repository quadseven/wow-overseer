// "Live now" on the Now page: every active dungeon run, raid and battleground,
// each with the seats it can name, its progress, and a Jump in button that
// points the Watcher at it. The server (GET /api/live) decides what is live
// and what order jumps in; this only draws it and sends the order the server
// gave, through _spectate.js (a run id, or a character name, never a sentence).

import { html, plural, state } from "../../ui.js";
import { jumpButton } from "../_spectate.js";

export const READ = "/api/live";

function seatLine(g) {
  if (g.kind === "dungeon") {
    return (g.seats || []).map((s) => s.name + (s.seat ? " (" + s.seat + ")" : "")).join(", ") || "seats not recorded";
  }
  const roles = plural(g.tanks || 0, "tank") + ", " + plural(g.healers || 0, "healer");
  const names = (g.members || []).slice(0, 8).join(", ");
  return roles + ". " + names + ((g.members || []).length > 8 ? ", and others" : "");
}

function row(g, sp, op) {
  const title = g.kind === "dungeon" ? g.title || g.place : g.place;
  const kind = g.kind === "dungeon" ? "Dungeon" : g.kind === "raid" ? "Raid" : "Battleground";
  return html`<div class="card sp-live-group" data-live-kind="${g.kind}">
<div class="sp-live-row"><span class="g-name">${kind}: ${title}</span>${jumpButton(g.order, sp, op)}</div>
<span class="muted">${g.progress}</span>
<span class="dim small">${seatLine(g)}</span>
</div>`;
}

// `liveRead`, `spRead` and `opRead` are ctx.get() or peek() results.
export function section(liveRead, spRead, opRead) {
  if (!liveRead || !liveRead.data) {
    return html`<section class="sp-live" aria-label="Live now"><h2 class="kicker">Live now</h2>${liveRead && liveRead.error ? state("error", "The live list did not answer", "No group is listed, which is not the same as none being out.") : html`<p class="muted">Reading the live groups...</p>`}</section>`;
  }
  const d = liveRead.data;
  const all = [].concat(d.dungeons || [], d.raids || [], d.battlegrounds || []);
  if (!all.length) {
    return html`<section class="sp-live" aria-label="Live now"><h2 class="kicker">Live now</h2>${state("empty", "No dungeon, raid or battleground is live right now.")}</section>`;
  }
  return html`<section class="sp-live" aria-label="Live now"><h2 class="kicker">Live now</h2>${all.map((g) => row(g, spRead, opRead))}</section>`;
}
