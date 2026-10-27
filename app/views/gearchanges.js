import { html, pendingRead, state, item } from "../ui.js";
import { load, peek } from "../api.js";
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
    : html`Replaced ${item({ entry: row.prior_entry, name: row.replaced, quality: row.prior_quality })} (${quality(row.prior_quality)}, item level ${row.prior_item_level})`;
  const diff = row.kind === "worn" && row.prior_entry && row.entry
    ? html`<span class="gc-diff" data-compare="${row.prior_entry},${row.entry}">Loading stat changes</span>` : "";
  return html`<div class="card gc-row"><span class="gc-label">${upgrade ? "Upgrade" : row.kind === "worn" ? "Worn" : "Looted"}</span><strong>${item({ entry: row.entry, name: row.item, quality: row.quality })}</strong><span class="dim">${quality(row.quality)}, ${level}</span><span class="muted">${row.kind === "worn" ? replaced : "Not recorded as worn"}</span>${diff}<time>${row.at}</time></div>`;
}

function number(v) { return Number.isFinite(Number(v)) ? Number(v) : 0; }

function statMap(lines) {
  const values = {};
  (lines || []).forEach((line) => {
    const match = String(line).match(/^([+-]?\d+)\s+(.+)$/);
    if (match) values[match[2]] = number(match[1]);
  });
  return values;
}

export function compareItems(prior, next) {
  const a = prior && prior.tooltip || {}, b = next && next.tooltip || {};
  const left = statMap(a.stats), right = statMap(b.stats);
  const names = new Set([...Object.keys(left), ...Object.keys(right)]);
  const changes = [...names].map((name) => [name, (right[name] || 0) - (left[name] || 0)]).filter(([, delta]) => delta);
  [["Armor", number(b.armor) - number(a.armor)], ["DPS", number(b.damage && b.damage.dps) - number(a.damage && a.damage.dps)], ["item level", number(b.item_level) - number(a.item_level)]].forEach(([name, delta]) => { if (delta) changes.push([name, delta]); });
  return changes.map(([name, delta]) => `${delta > 0 ? "+" : ""}${delta} ${name} ${delta > 0 ? "gain" : "loss"}`).join(", ") || "No stat changes";
}

function fillComparisons(main) {
  main.querySelectorAll("[data-compare]").forEach((node) => {
    const [prior, next] = node.getAttribute("data-compare").split(",").map(Number);
    Promise.all([load("/api/item?entry=" + prior), load("/api/item?entry=" + next)]).then(() => {
      const before = peek("/api/item?entry=" + prior).data;
      const after = peek("/api/item?entry=" + next).data;
      node.textContent = before && after ? compareItems(before, after) : "Stat changes unavailable";
    });
  });
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
    fillComparisons(main);
    main.querySelectorAll("[data-mark-seen]").forEach((button) => button.addEventListener("click", () => {
      markSeen(button.getAttribute("data-mark-seen"));
      window.location.reload();
    }));
  },
};
