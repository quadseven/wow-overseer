// What the Members section's three views share: the member state words, the
// section's tab row, the URL query the filters live in, the paperdoll card
// and the upgrades panel. Every sentence the server writes is printed as it
// comes; this file only lays it out.

import { html, raw, status, statusColor, classVar, iconUrl, item, notMeasured, duration, gold, plural, esc } from "../ui.js";
import { parse, build } from "../router.js";
import { modelStage } from "./_model.js";

// ---- the query the view state lives in --------------------------------------

// The query as the address bar has it now. A filter typed into the page is
// written back with replaceState, so ctx.query (read when the route opened)
// can be older than this.
export function liveQuery() { return parse(location.hash).query; }

export function setQuery(patch) {
  const p = parse(location.hash);
  const q = Object.assign({}, p.query, patch);
  Object.keys(q).forEach((k) => { if (q[k] === "" || q[k] === null || q[k] === undefined) delete q[k]; });
  history.replaceState(null, "", build(p.parts, q));
  return q;
}

// ---- reads by name -------------------------------------------------------------

export function byName(list) {
  const out = new Map();
  (list || []).forEach((m) => { if (m && m.name) out.set(m.name, m); });
  return out;
}

// Every guild member's gear row from /api/guildgear, by name.
export function gearRows(gg) {
  const out = new Map();
  ((gg && gg.guilds) || []).forEach((g) => (g.members || []).forEach((m) => out.set(m.name, m)));
  return out;
}

// ---- member state ----------------------------------------------------------------

export function stateOf(m) {
  if (!m) return "offline";
  if (m.life === "ghost" || m.life === "dead") return "ghost";
  if (m.stuck) return "stuck";
  return m.online ? "online" : "offline";
}

export function stuckFor(m, checkedAt) {
  if (!m || !m.stuck) return null;
  if (m.since === null || m.since === undefined || !checkedAt) return null;
  return duration(checkedAt - m.since);
}

// The status label a member wears in a list.
export function stateLabel(m, checkedAt) {
  const k = stateOf(m);
  if (k === "stuck") {
    const d = stuckFor(m, checkedAt);
    return d ? status("stuck", "Stuck " + d) : html`<span class="status" style="color:var(--color-neutral-400)"><i class="ph-fill ph-hand-palm" aria-hidden="true"></i>Stuck, since not measured</span>`;
  }
  if (k === "ghost") return status("ghost", m.life === "dead" ? "Dead" : "Ghost");
  return status(k);
}

export function memberLink(m, tab) {
  return html`<a class="mname" href="${"#/m/" + encodeURIComponent(m.name) + (tab ? "/" + tab : "")}" style="color:${classVar(m.class || m.cls)}">${m.name}</a>`;
}

// ---- the section's tab row and the gear views' switch ------------------------------

export function sectionTabs(current) {
  return html`<nav class="tabs" aria-label="Member views"><a href="#/members"${current === "roster" ? raw(' aria-current="page"') : ""}>Roster</a><a href="#/members/gear"${current === "gear" ? raw(' aria-current="page"') : ""}>Gear</a></nav>`;
}

export function seg(label, items) {
  return html`<div class="seg mb-seg" role="group" aria-label="${label}">${items.map((o) => html`<a href="${o.href}"${o.current ? raw(' aria-current="page"') : ""}>${o.label}</a>`)}</div>`;
}

export function gearSeg(tab) {
  return seg("Gear views", [
    { label: "Paperdoll", href: "#/members/gear", current: tab === "armory" },
    { label: "Upgrades", href: "#/members/gear/upgrades", current: tab === "upgrades" },
    { label: "Table", href: "#/members/gear/table", current: tab === "table" },
  ]);
}

export function head(title, aside, line) {
  return html`<header class="mb-head"><div class="mb-title"><h1>${title}</h1>${aside ? html`<span class="mb-aside">${aside}</span>` : ""}</div>${line ? html`<p class="mb-line">${line}</p>` : ""}</header>`;
}

// ---- items in cells ------------------------------------------------------------------

// A square item cell (the paperdoll's 48px slot, the inventory's 44px bag
// cell). It carries data-item, so the one tooltip opens on hover, focus and
// tap, exactly as ui.item's links do.
export function cell(c) {
  const q = Number.isFinite(Number(c.quality)) ? Number(c.quality) : 1;
  const pic = c.icon ? html`<img src="${iconUrl(c.icon)}" alt="" loading="lazy" decoding="async">` : "";
  const label = c.title || c.name || "Item " + c.entry;
  return html`<button type="button" class="${"icell q" + q + (c.size ? " " + c.size : "")}" data-item="${Number(c.entry) || 0}" data-name="${c.name || ""}" aria-label="${label}" title="${label}">${pic}${c.mark ? html`<span class="mk">${c.mark}</span>` : ""}${c.corner ? html`<span class="lv">${c.corner}</span>` : ""}</button>`;
}

export function emptyCell(label, kind, title, size) {
  return html`<span class="${"icell empty " + (kind || "") + (size ? " " + size : "")}" role="img" aria-label="${title || label}" title="${title || label}"><span>${label}</span></span>`;
}

// ---- the paperdoll card --------------------------------------------------------------

const ROLE_WORDS = { tank: "Tank", healer: "Healer", melee: "Melee", ranged: "Ranged", caster: "Caster", damage: "Damage" };

export function roleWord(r) { return ROLE_WORDS[r] || (r ? r.charAt(0).toUpperCase() + r.slice(1) : ""); }

function slotCell(s) {
  if (!s) return emptyCell("?", "", "not read");
  if (s.empty) {
    const kind = s.empty_kind === "cosmetic" ? "cosmetic" : "missing";
    return emptyCell(s.empty_label || "empty", kind, s.slot + ": " + (s.empty_label || "empty"));
  }
  return cell({ entry: s.entry, name: s.name, quality: s.quality, icon: s.icon, mark: s.mark, corner: s.item_level_mark || s.item_level, title: s.slot + ": " + s.name, size: "c48" });
}

function slotColumn(keys, slots) {
  const by = new Map((slots || []).map((s) => [s.slot, s]));
  return html`<div class="pd-col">${(keys || []).map((k) => slotCell(by.get(k)))}</div>`;
}

function tags(m) {
  const g = m.gear || {};
  const out = [html`<span class="tag tag-neutral">Average item level ${g.average_item_level ?? "not measured"}</span>`,
    html`<span class="tag tag-neutral">Slots worn ${g.worn ?? "?"} of ${g.slots ?? 17}</span>`];
  const empty = (g.empty_slots || []).length;
  if (empty) out.push(html`<span class="tag tag-warn">Empty ${empty}</span>`);
  if (m.weakest && m.weakest.shortfall > 12) out.push(html`<span class="tag tag-warn">Weakest slot ${m.weakest.said}</span>`);
  return out;
}

function statsTable(stats) {
  const rows = (stats && stats.rows) || [];
  if (!rows.length) return notMeasured("Stats not measured");
  return html`<div class="pd-stats">${rows.map((r) => html`<div class="pd-stat"><span>${r.label}</span><span class="num">${r.reading ?? notMeasured()}</span></div>`)}<div class="pd-gloss">${stats.gloss ? stats.gloss.charAt(0).toUpperCase() + stats.gloss.slice(1) : ""}</div></div>`;
}

function talents(spec, name) {
  if (!spec || !spec.trees) return html`<div class="pd-spec">${notMeasured("Talents not measured")}</div>`;
  const top = Math.max(...spec.trees.map((t) => t.points || 0));
  const pct = spec.available ? Math.round((100 * (spec.spent || 0)) / spec.available) : 0;
  const id = "trees-" + name;
  return html`<div class="pd-spec"><div class="row"><span class="pd-headline">${spec.headline || notMeasured()}</span><span class="dim">${spec.budget || ""}</span><button type="button" class="btn btn-secondary pd-trees-btn" aria-expanded="false" aria-controls="${id}" data-trees="${id}">Show trees</button></div><div class="mb-bar" aria-hidden="true"><span style="width:${pct}%"></span></div>${spec.unspent_note ? html`<span class="warn">${spec.unspent_note}</span>` : ""}<div class="pd-trees" id="${id}" hidden>${spec.trees.map((t) => html`<div class="${"pd-tree" + (t.points === top && top > 0 ? " top" : "")}"><span class="tn">${t.name}</span><span class="tp num">${t.points}</span><span class="dim">points</span></div>`)}</div></div>`;
}

// The card for one /api/armory member. `doll` is the payload's slot layout.
export function paperdoll(m, doll, opts) {
  const o = opts || {};
  if (!m || !m.present) {
    return html`<article class="pd card" id="${"armory-" + (m ? m.name : "")}"><span class="card-title">${m ? m.name : "Member"}</span>${notMeasured("Not in the world's save: nothing to draw")}</article>`;
  }
  const portrait = m.portrait || {};
  const faction = m.faction === "alliance" ? "inv_bannerpvp_02" : m.faction === "horde" ? "inv_bannerpvp_01" : "";
  const headBlock = o.bare ? "" : html`<header class="pd-head"><div class="pd-icons">${portrait.race_icon ? html`<img src="${iconUrl(portrait.race_icon)}" alt="${m.race}" width="40" height="40">` : ""}${portrait.class_icon ? html`<img src="${iconUrl(portrait.class_icon)}" alt="${m.class}" width="40" height="40">` : ""}</div><div class="pd-id"><div class="row">${faction ? html`<img class="pd-banner" src="${iconUrl(faction)}" alt="${m.faction}" width="20" height="20">` : ""}<a class="pd-name" href="${"#/m/" + encodeURIComponent(m.name)}" style="color:${classVar(m.class)}">${m.name}</a><span class="pd-role">${roleWord(m.party_role)}</span></div><div class="pd-sub">Level ${m.level} ${m.race} ${m.class}${m.guild ? " | " + m.guild : ""} <span class="${m.online ? "ok" : "dim"}">${m.online ? "online" : "offline"}</span></div></div></header>`;
  return html`<article class="pd card" id="${"armory-" + m.name}">${headBlock}<div class="row pd-tags">${tags(m)}</div><div class="pd-body"><div class="pd-doll">${slotColumn(doll && doll.left, m.slots)}${modelStage(m)}${slotColumn(doll && doll.right, m.slots)}</div>${statsTable(m.stats)}</div>${talents(m.spec, m.name)}</article>`;
}

// The Show trees buttons, bound after a draw.
export function bindTrees(root) {
  root.querySelectorAll("[data-trees]").forEach((b) => {
    b.addEventListener("click", () => {
      const box = root.querySelector("#" + CSS.escape(b.getAttribute("data-trees")));
      if (!box) return;
      box.hidden = !box.hidden;
      b.setAttribute("aria-expanded", String(!box.hidden));
      b.textContent = box.hidden ? "Show trees" : "Hide trees";
    });
  });
}

// ---- the upgrades panel ------------------------------------------------------------------

const UP_STATE = { upgrade: ["upgrade", "var(--warn)"], near: ["near best", "var(--color-accent-300)"], bis: ["at best", "var(--ok)"], no_list: ["no list", "var(--color-neutral-500)"] };

function where(list) {
  return (list || []).map((w) => w.label || w.name || w.kind).filter(Boolean).join(", ");
}

function upItem(entry, name, items) {
  if (!entry) return notMeasured("nothing listed");
  const meta = (items || {})[String(entry)] || {};
  return item({ entry, name, quality: meta.quality, icon: meta.icon });
}

function score(v) { return v === null || v === undefined ? "" : String(Math.round(v * 10) / 10); }

// /api/upgrades reports a worn item's extras as {enchants, stats, score}; an
// older shape was the bare number. Either way the score is what is shown.
function bonusScore(b) {
  const v = b && typeof b === "object" ? b.score : b;
  return typeof v === "number" && isFinite(v) && v > 0 ? v : 0;
}

export const UP_FILTERS = [["all", "All 17"], ["now", "Upgrade now"], ["up", "Below pre-raid"], ["best", "At or near best"]];
export const UP_SORTS = [["slot", "Slot order"], ["now", "Biggest gain now"], ["gain", "Biggest pre-raid gain"]];

export function upSlots(data, filter, sort) {
  let slots = (data.slots || []).filter((s) => filter === "now" ? !!s.now : filter === "up" ? s.state === "upgrade" : filter === "best" ? (s.state === "bis" || s.state === "near") : true);
  if (sort === "now") slots = slots.slice().sort((a, b) => (b.now ? b.now.gain : -1) - (a.now ? a.now.gain : -1));
  else if (sort === "gain") slots = slots.slice().sort((a, b) => (b.next ? b.next.gain : -1) - (a.next ? a.next.gain : -1));
  return slots;
}

function stateCell(s) {
  const st = UP_STATE[s.state] || [s.state || "", "var(--color-neutral-500)"];
  return html`<span class="up-state" style="color:${st[1]}">${st[0]}</span>`;
}

function wornBlock(s, items) {
  if (!s.worn) return html`<span class="warn">nothing worn</span>`;
  return html`<span>${upItem(s.worn.entry, s.worn.name, items)} <span class="dim num">(${score(s.worn.score)})</span></span>${bonusScore(s.worn.bonus) ? html`<span class="dim mb-s">enchants, gems and suffix +${score(bonusScore(s.worn.bonus))}</span>` : ""}`;
}

function nowBlock(s) {
  if (!s.now) return html`<span class="dim">nothing better at this level</span>`;
  return html`<span>${item({ entry: s.now.entry, name: s.now.name, quality: s.now.quality, icon: s.now.icon })} <span class="ok num">+${s.now.gain} iLvl</span></span><span class="muted mb-s">${s.now.where}</span>`;
}

function targetBlock(list, items) {
  const t = (list || [])[0];
  if (!t) return notMeasured("no list");
  const also = (list || []).slice(1).map((x) => x.name).join(", ");
  return html`<span>${upItem(t.entry, t.name, items)} <span class="dim num">(${score(t.score)})</span></span><span class="muted mb-s">${where(t.where)}</span>${also ? html`<span class="dim mb-s">also ${also}</span>` : ""}`;
}

function nextBlock(s, items) {
  if (!s.next) return html`<span class="dim">nothing better listed</span>`;
  return html`<span>${upItem(s.next.entry, s.next.name, items)} <span class="ok num">+${score(s.next.gain)}</span></span><span class="muted mb-s">${where(s.next.where)}</span><span class="dim mb-s">${s.next.phase === "raid" ? "raid" : "pre-raid"}</span>`;
}

export function upgradesBody(data, filter, sort) {
  const items = data.items || {};
  const slots = upSlots(data, filter, sort);
  const tg = (s) => s.targets || {};
  if (!slots.length) return html`<div class="state" data-kind="empty" role="status"><i class="ph ph-circle-dashed" aria-hidden="true"></i><div><div class="t">No slot fits this filter</div></div></div>`;
  const table = html`<div class="card up-table"><div class="up-row up-headrow"><span>Slot</span><span>Wearing</span><span class="mb-accent">At level ${data.level ?? "?"}, now</span><span>Pre-raid target</span><span>Raid target</span><span>Next upgrade</span></div>${slots.map((s) => html`<div class="up-row"><span class="up-slot"><span class="mb-b">${s.label}</span>${stateCell(s)}</span><span class="up-c">${wornBlock(s, items)}</span><span class="up-c">${nowBlock(s)}</span><span class="up-c">${targetBlock(tg(s).preraid, items)}</span><span class="up-c">${targetBlock(tg(s).raid, items)}</span><span class="up-c">${nextBlock(s, items)}</span></div>`)}</div>`;
  const cards = html`<div class="up-cards">${slots.map((s) => html`<div class="card up-card"><span class="row up-sum"><span class="mb-b">${s.label}</span>${stateCell(s)}</span><span class="mb-s"><span class="dim">Wearing</span> ${s.worn ? upItem(s.worn.entry, s.worn.name, items) : html`<span class="warn">nothing worn</span>`}</span><span class="mb-s"><span class="mb-accent">Now</span> ${s.now ? html`${item({ entry: s.now.entry, name: s.now.name, quality: s.now.quality, icon: s.now.icon })} <span class="ok">+${s.now.gain} iLvl</span> <span class="muted">| ${s.now.where}</span>` : html`<span class="dim">nothing better at this level</span>`}</span><span class="mb-s"><span class="dim">Pre-raid</span> ${targetBlock(tg(s).preraid, items)}</span><details class="fold up-fold"><summary>Raid target and next upgrade</summary><div class="up-more"><span><span class="dim">Raid</span> ${targetBlock(tg(s).raid, items)}</span><span><span class="dim">Next</span> ${nextBlock(s, items)}</span></div></details></div>`)}</div>`;
  return html`${table}${cards}`;
}

// The panel above the slot list: what each slot can become, in four tiles.
export function upgradesHead(data, picker) {
  const ready = data.ready || {};
  const pct = ready.pct === null || ready.pct === undefined ? null : Math.round(ready.pct * 100);
  const gain = (data.slots || []).reduce((a, s) => a + (s.next ? s.next.gain || 0 : 0), 0);
  const spec = data.spec || {};
  return html`<div class="row up-top"><div class="up-who"><span class="mb-kick">${spec.tree ? spec.tree + " " + (data.class || "") + (spec.assumed ? " (assumed)" : "") : notMeasured("spec not measured")}</span><span class="mb-b">${data.name} | level ${data.level ?? "?"} ${data.class || ""}</span></div>${picker || ""}</div>
<div class="up-tiles"><div class="card up-tile hi"><span class="v num">${data.now_count ?? "?"} / ${(data.slots || []).length}</span><span class="k">slots with an upgrade at level ${data.level ?? "?"}</span></div><div class="card up-tile"><span class="v num">${ready.slots_ready ?? "?"} / ${ready.slots_scored ?? "?"}</span><span class="k">slots at or near pre-raid best</span></div><div class="card up-tile"><span class="v num">${pct === null ? notMeasured() : pct + "%"}</span><span class="k">pre-raid ready</span></div><div class="card up-tile"><span class="v num ok">+${Math.round(gain)}</span><span class="k">score to gain from pre-raid targets</span></div></div>
<div class="up-meter"><span class="muted">${ready.line || ""}</span><div class="mb-bar" role="meter" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${pct || 0}" aria-label="${ready.line || "pre-raid ready"}"><span style="width:${pct || 0}%"></span></div></div>`;
}

export function upgradesControls(filter, sort) {
  const btns = (list, cur, key) => list.map(([k, label]) => html`<button type="button" data-up-${raw(key)}="${k}" aria-pressed="${cur === k ? "true" : "false"}">${label}</button>`);
  return html`<div class="row up-controls"><span class="mb-kick">Slot by slot</span><div class="seg" role="group" aria-label="Filter slots">${btns(UP_FILTERS, filter, "filter")}</div><div class="seg" role="group" aria-label="Sort slots">${btns(UP_SORTS, sort, "sort")}</div></div>`;
}

export function upgradesFoot(data) {
  return html`<p class="dim mb-s">${data.now_basis || ""} ${data.scored_from || ""}</p>`;
}

// Bind the filter and sort buttons: the choice goes into the URL query and
// the slot list is redrawn in place.
export function bindUpgrades(root, data) {
  const region = root.querySelector("[data-region=upslots]");
  if (!region) return;
  root.querySelectorAll("[data-up-filter], [data-up-sort]").forEach((b) => {
    b.addEventListener("click", () => {
      const f = b.getAttribute("data-up-filter"), s = b.getAttribute("data-up-sort");
      const q = setQuery(f ? { filter: f === "all" ? "" : f } : { usort: s === "slot" ? "" : s });
      const filter = q.filter || "all", sort = q.usort || "slot";
      root.querySelectorAll("[data-up-filter]").forEach((x) => x.setAttribute("aria-pressed", String(x.getAttribute("data-up-filter") === filter)));
      root.querySelectorAll("[data-up-sort]").forEach((x) => x.setAttribute("aria-pressed", String(x.getAttribute("data-up-sort") === sort)));
      region.innerHTML = upgradesBody(data, filter, sort).s;
    });
  });
}

// ---- small words ---------------------------------------------------------------------------

export function coins(c) { return c === null || c === undefined ? notMeasured() : gold(c); }
export function count(n, one, many) { return plural(n, one, many); }
export function attr(s) { return esc(s); }
export { statusColor };
