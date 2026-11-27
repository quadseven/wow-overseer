import { html, raw, pendingRead, state, item, plural, memberHref } from "../ui.js";
import { load, peek } from "../api.js";
import { pageKey, since, markSeen } from "../models/gearchanges.js";
import { toSeconds, since as timeSince } from "../models/time.js";
import { liveQuery, setQuery } from "./_members.js";

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

// One change as a rail row: the rail and the delta chip carry the verdict
// (ok for an upgrade, bad for a downgrade, neutral for loot and sidegrades),
// the meta line says what happened and how long ago, in that order. The
// replaced item keeps its tooltip link; the stat comparison still loads
// underneath for a worn change with both items recorded.
function itemRow(row) {
  const worn = row.kind === "worn";
  const change = worn ? row.item_level_change : null;
  const tone = change > 0 ? " ok" : change < 0 ? " bad" : "";
  const delta = !worn
    ? html`<span class="gc-delta dim">looted</span>`
    : change ? html`<span class="gc-delta${tone} num">${change > 0 ? "+" : ""}${change} iLvl</span>` : "";
  const replaced = row.replaced === "was empty"
    ? "slot was empty"
    : row.replaced === "not recorded"
      ? "previous item not recorded"
      : html`replaced ${item({ entry: row.prior_entry, name: row.replaced, quality: row.prior_quality })} (ilvl ${row.prior_item_level})`;
  const meta = worn ? html`Worn · ${replaced} · ${timeSince(row.at)}${change < 0 ? html` · <span class="bad">a downgrade</span>` : ""}` : html`Not recorded as worn · ${timeSince(row.at)}`;
  const diff = worn && row.prior_entry && row.entry
    ? html`<span class="gc-diff" data-compare="${row.prior_entry},${row.entry}">Loading stat changes</span>` : "";
  return html`<div class="card gc-row"><span class="gc-rail${tone}"></span><div class="gc-main"><div class="gc-top"><strong>${item({ entry: row.entry, name: row.item, quality: row.quality })}</strong>${delta}</div><div class="gc-meta">${meta}</div>${diff}</div></div>`;
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
    }).catch((err) => {
      // load() never rejects, but a malformed item answer can still throw in
      // compareItems; say so rather than leave "Loading stat changes" up.
      node.textContent = "Stat changes unavailable";
      console.warn("gear stat comparison failed", err);
    });
  });
}


// The head's one computed line: what the fetched feed holds, counted over
// every change in it, whichever filter is on. Equips are the worn changes,
// upgrades the worn ones that gained item level, looted the rest.
export function summarize(changes) {
  const rows = changes || [];
  const out = { equips: 0, upgrades: 0, looted: 0, members: 0 };
  const seen = new Set();
  for (const row of rows) {
    seen.add(row.character);
    if (row.kind === "worn") {
      out.equips += 1;
      if (row.item_level_change > 0) out.upgrades += 1;
    } else {
      out.looted += 1;
    }
  }
  out.members = seen.size;
  return out;
}

// The marker as a person reads it: "Thu 13:20", never the raw ISO string.
function sinceLabel(iso) {
  const t = toSeconds(iso);
  if (t === null) return "your last visit";
  const d = new Date(t * 1000);
  return d.toLocaleDateString("en-US", { weekday: "short" }) + " " + d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}

function summaryLine(data, key) {
  const counts = summarize(data && data.changes);
  return "Since " + sinceLabel(since(key)) + " · " + plural(counts.equips, "equip") + ", " + plural(counts.upgrades, "upgrade") + ", " + counts.looted + " looted, " + plural(counts.members, "member");
}

// A member's header over their changes: their name links to their page, and
// the aside carries the guild and how many changes the group holds.
function memberHead(name, rows) {
  const guild = rows[0] && rows[0].guild;
  const aside = (guild ? guild + " · " : "") + plural(rows.length, "change");
  return html`<div class="gc-member-head"><a class="gc-name" href="${memberHref(name)}">${name}</a><span class="dim">${aside}</span></div>`;
}

// The feed's filters, living in the URL query like the rest of the section:
// `kind` is worn (the default), upgrades or looted, and `guild` narrows to
// one guild's changes. An unknown kind reads as the default, never as an
// empty feed.
const KINDS = [["worn", "Worn"], ["upgrades", "Upgrades only"], ["looted", "Looted"]];

export function filterFromQuery(query) {
  const q = query || {};
  return {
    kind: KINDS.some(([kind]) => kind === q.kind) ? q.kind : "worn",
    guild: q.guild || "",
  };
}

export function visible(changes, filter) {
  const rows = changes || [];
  const byKind = filter.kind === "upgrades"
    ? rows.filter((row) => row.kind === "worn" && row.item_level_change > 0)
    : rows.filter((row) => (filter.kind === "looted" ? row.kind !== "worn" : row.kind === "worn"));
  return filter.guild ? byKind.filter((row) => row.guild === filter.guild) : byKind;
}

function filterBar(data, filter) {
  const guilds = [...new Set(((data && data.changes) || []).map((row) => row.guild).filter(Boolean))];
  return html`<div class="gc-bar"><div class="gc-chips" role="group" aria-label="Show">${KINDS.map(([kind, label]) => html`<button type="button" class="chip" data-gc-kind="${kind}" aria-pressed="${filter.kind === kind ? "true" : "false"}">${label}</button>`)}${guilds.map((g) => html`<button type="button" class="chip" data-gc-guild="${g}" aria-pressed="${filter.guild === g ? "true" : "false"}">${g}</button>`)}</div></div>`;
}

const NO_MATCH = { worn: "No equips since then", upgrades: "No upgrades since then", looted: "No loot since then" };

// The newest change in the fetched feed, as the milliseconds the seen
// marker stores. Mark all seen advances to this, never to the moment of
// the click: a change that lands while the page renders is after the
// newest shown one, so it stays unseen and shows on the next visit.
export function newestChangeMs(changes) {
  let newest = null;
  (changes || []).forEach((row) => {
    const t = toSeconds(row.at);
    if (t !== null && (newest === null || t > newest)) newest = t;
  });
  return newest === null ? null : newest * 1000;
}

export function renderFeed(data, key, member = "", filter = null) {
  const all = grouped(data && data.changes);
  const groups = filter ? grouped(visible(data && data.changes, filter)) : all;
  const body = groups.length
    ? groups.map(([name, rows]) => html`<section class="gc-member">${memberHead(name, rows)}${rows.map(itemRow)}</section>`)
    : filter && all.length
      ? state("empty", NO_MATCH[filter.kind], "The feed has changes, but none match the filters on. The summary above counts everything in the feed.")
      : state("empty", "No gear changes since then", member ? "This character has no recorded loot or equips in this period." : "The guilds have no recorded loot or equips in this period.");
  const newest = newestChangeMs(data && data.changes);
  return html`<div class="gc-head"><p class="dim">${summaryLine(data, key)}</p><button type="button" data-mark-seen="${key}"${newest === null ? "" : raw(' data-newest="' + newest + '"')}>Mark all seen</button></div>${filter ? filterBar(data, filter) : ""}${body}`;
}

export default {
  css: ["views/gearchanges.css"],
  reads: () => { const key = pageKey(); return [pathFor(key)]; },
  every: 30000,
  title: () => "Gear changes",
  render(ctx) {
    const key = pageKey();
    const read = ctx.get(pathFor(key));
    const wait = pendingRead(read, 1);
    if (wait) return html`<h1>Gear changes</h1>${wait}`;
    return html`<h1>Gear changes</h1><div data-region="gc-feed">${renderFeed(read.data, key, "", filterFromQuery(liveQuery()))}</div>`;
  },
  after(main, ctx) {
    const region = main.querySelectorAll("[data-region=gc-feed]")[0] || null;
    const bind = () => {
      fillComparisons(main);
      main.querySelectorAll("[data-mark-seen]").forEach((button) => button.addEventListener("click", () => {
        const key = button.getAttribute("data-mark-seen");
        const newest = Number(button.getAttribute("data-newest"));
        if (Number.isFinite(newest) && newest > 0) markSeen(key, undefined, newest);
        else markSeen(key);
        window.dispatchEvent(new Event("overseer:redraw"));
      }));
    };
    bind();
    if (!region) return;
    region.addEventListener("click", (event) => {
      const chip = event.target && event.target.closest ? event.target.closest("[data-gc-kind], [data-gc-guild]") : null;
      if (!chip) return;
      const patch = chip.hasAttribute("data-gc-kind")
        ? { kind: chip.getAttribute("data-gc-kind") }
        : { guild: liveQuery().guild === chip.getAttribute("data-gc-guild") ? "" : chip.getAttribute("data-gc-guild") };
      const q = setQuery(patch);
      const key = pageKey();
      const read = ctx.get(pathFor(key));
      region.innerHTML = renderFeed(read && read.data, key, "", filterFromQuery(q)).s;
      bind();
    });
  },
};
