import { html, pendingRead, state } from "../ui.js";
import { pageKey, since, markSeen } from "../models/gearchanges.js";

const pathFor = (key, member) => "/api/v2/gear/changes?since=" + encodeURIComponent(since(key)) + (member ? "&member=" + encodeURIComponent(member) : "");

export function grouped(changes) {
  const rows = (changes || []).slice().sort((a, b) => {
    const rank = (x) => x.kind === "worn" && x.item_level_change > 0 ? 0 : x.kind === "worn" ? 1 : 2;
    return rank(a) - rank(b) || String(b.at).localeCompare(String(a.at));
  });
  const groups = new Map();
  rows.forEach((row) => groups.set(row.character, [...(groups.get(row.character) || []), row]));
  return [...groups.entries()];
}

function itemRow(row) {
  const upgrade = row.kind === "worn" && row.item_level_change > 0;
  const level = row.item_level_change === null ? "item level not recorded" : "item level " + row.item_level + (row.item_level_change ? " (" + (row.item_level_change > 0 ? "+" : "") + row.item_level_change + ")" : "");
  const replaced = row.replaced === "was empty" || row.replaced === "not recorded"
    ? row.replaced
    : "Replaced " + row.replaced + " (" + quality(row.prior_quality) + ", item level " + row.prior_item_level + ")";
  return html`<div class="card gc-row"><span class="gc-label">${upgrade ? "Upgrade" : row.kind === "worn" ? "Worn" : "Looted"}</span><strong>${row.item}</strong><span class="dim">${quality(row.quality)}, ${level}</span><span class="muted">${row.kind === "worn" ? replaced : "Not recorded as worn"}</span><time>${row.at}</time></div>`;
}

function quality(value) {
  return ["poor", "common", "uncommon", "rare", "epic", "legendary"][Number(value)] || "quality not recorded";
}

export function renderFeed(data, key, member = "") {
  const groups = grouped(data && data.changes);
  return html`<div class="gc-head"><p class="dim">Since ${since(key)}</p><button type="button" data-mark-seen="${key}">Mark all seen</button></div>${groups.length ? groups.map(([name, rows]) => html`<section class="gc-member"><h2>${name}</h2>${rows.map(itemRow)}</section>`) : state("empty", "No gear changes since then", member ? "This character has no recorded loot or equips in this period." : "The guilds have no recorded loot or equips in this period.")}`;
}

export default {
  css: ["views/gearchanges.css"],
  reads: () => { const key = pageKey(); return [pathFor(key)]; },
  every: 30000,
  title: () => "Gear since your last visit",
  render(ctx) {
    const key = pageKey();
    const read = ctx.get(pathFor(key));
    const wait = pendingRead(read, 1);
    return html`<h1>Gear since your last visit</h1>${wait || renderFeed(read.data, key)}`;
  },
  after(main) {
    main.querySelectorAll("[data-mark-seen]").forEach((button) => button.addEventListener("click", () => {
      markSeen(button.getAttribute("data-mark-seen"));
      window.location.reload();
    }));
  },
};
