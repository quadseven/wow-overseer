// Members > Gear: the paperdoll pairs, the upgrades panel and the gear table.
//
//   #/members/gear            Paperdoll: the two families paired by role
//                             (/api/armory), then every guildmate with a
//                             quality strip (/api/guildgear)
//   #/members/gear/upgrades   one member's slots against their spec's lists,
//                             and the best drop at their level now
//                             (/api/v2/upgrades?name=)
//   #/members/gear/table      every guild member's gear, worst first
//                             (/api/guildgear), 11 sortable columns
//
// The picked member, the filters and the sort live in the URL query.

import { html, raw, notMeasured, pendingRead, state, classVar } from "../ui.js";
import {
  liveQuery, setQuery, stateLabel, sectionTabs, gearSeg, head, paperdoll, bindTrees, roleWord,
  upgradesHead, upgradesControls, upgradesBody, upgradesFoot, bindUpgrades, flipSort, sortHead,
} from "./_members.js";
import { mountModels } from "./_model.js";
import { byName, stateOf } from "../models/roster.js";
import { guilds } from "../families.js";

const SLOT_WORDS = {
  head: "head", neck: "neck", shoulders: "shoulders", back: "back", chest: "chest", wrists: "wrists",
  hands: "hands", waist: "waist", legs: "legs", feet: "feet", "finger 1": "ring", "finger 2": "ring",
  "trinket 1": "trinket", "trinket 2": "trinket", "main hand": "main hand", "off hand": "off hand", ranged: "ranged",
};

// ---- Paperdoll -------------------------------------------------------------------

function familyNames(arm) {
  return new Set(((arm && arm.sides) || []).flatMap((s) => s.names || []));
}

function pairOrder(arm) {
  return ((arm && arm.pairs) || []).flatMap((p) => [p.left, p.right]).filter(Boolean);
}

function armoryLine(arm) {
  const fam = (arm.members || []).filter((m) => m.present);
  if (!fam.length) return "No family member is in the world's save.";
  const worst = fam.slice().sort((a, b) => ((b.gear.empty_slots || []).length - (a.gear.empty_slots || []).length) || ((a.gear.average_item_level || 0) - (b.gear.average_item_level || 0)))[0];
  const empty = fam.reduce((s, m) => s + (m.gear.empty_slots || []).length, 0);
  return empty + " empty slots across the two families. " + worst.name + " needs it most: " + (worst.gear.empty_slots || []).length + " empty, item level " + (worst.gear.average_item_level ?? "not measured") + ".";
}

function strip(m) {
  return html`<span class="gm-strip" aria-hidden="true">${(m.strip || []).map((c) => html`<span class="${"gm-cell" + (c.quality === null || c.quality === undefined ? " none" : " q" + c.quality)}" title="${c.slot + ": " + (c.name || "empty")}"></span>`)}</span>`;
}

function mates(arm, gg, roster) {
  const fam = familyNames(arm);
  const r = byName((roster && roster.members) || []);
  const rows = ((gg && gg.guilds) || []).flatMap((g) => g.members || []).filter((m) => !fam.has(m.name)).sort((a, b) => a.avg_item_level - b.avg_item_level || a.name.localeCompare(b.name));
  if (!rows.length) return state("empty", "No guildmates to show", "The family guilds have no other members in the world's save.");
  return html`<div class="gm-grid">${rows.map((m) => {
    const w = m.weakest;
    return html`<a class="card gm-card" id="${"armory-" + m.name}" href="${"#/m/" + encodeURIComponent(m.name) + "/gear"}"><span class="row gm-top"><span class="mname" style="color:${classVar(m.class)}">${m.name}</span><span class="dim mb-s">L${m.level} ${m.class} | ${m.guild}</span></span>${strip(m)}<span class="dim mb-s">iLvl ${Math.round(m.avg_item_level)} | ${m.worn} of ${m.of} worn${w ? " | weakest " + (SLOT_WORDS[w.slot] || w.slot) + " at " + w.item_level : ""}${r.has(m.name) && r.get(m.name).stuck ? " | stuck" : ""}</span></a>`;
  })}</div>`;
}

function legend(arm) {
  return html`<div class="pd-legend">${((arm && arm.sides) || []).map((s) => html`<span class="row"><span class="${"fbar " + s.faction}" aria-hidden="true"></span>${(s.faction === "alliance" ? "Alliance" : s.faction === "horde" ? "Horde" : "Neutral") + " | " + s.family + "'s family, guild " + s.guild}</span>`)}</div>`;
}

function paperdollTab(ctx) {
  const arm = ctx.get("/api/armory");
  const wait = pendingRead(arm, 4);
  if (wait) return html`${head("Members", "the two families, paired by role")}${sectionTabs("gear")}${gearSeg("armory")}${wait}`;
  const a = arm.data;
  const by = byName(a.members || []);
  const order = pairOrder(a);
  const guildOf = {};
  (a.sides || []).forEach((s) => (s.names || []).forEach((n) => { guildOf[n] = s.guild; }));
  const pairs = (a.pairs || []).map((p) => {
    const left = by.get(p.left), right = by.get(p.right);
    const role = roleWord((left && left.party_role) || (right && right.party_role) || p.role);
    const card = (m, name) => {
      const inner = m ? paperdoll(m, a.doll) : html`<div class="card pd pd-none">${a.no_counterpart || "no one in this role on this side"}${name ? " (" + name + ")" : ""}</div>`;
      const g = (m && m.guild) || guildOf[name] || "";
      return html`<div class="pd-slot">${g ? html`<span class="mb-kick pd-slot-guild">${g}</span>` : ""}${inner}</div>`;
    };
    return html`<section class="pd-pair"><h2 class="mb-kick">${role}</h2><div class="pd-row">${card(left, p.left)}${card(right, p.right)}</div></section>`;
  });
  // The jump bar reaches the guildmates too, not just the paired families:
  // their cards below carry the same armory- ids the jump handler scrolls to.
  const fam = familyNames(a);
  const mateNames = membersOf(ctx.get("/api/guildgear").data)
    .filter((m) => !fam.has(m.name) && !order.includes(m.name))
    .sort((x, y) => x.avg_item_level - y.avg_item_level || x.name.localeCompare(y.name))
    .map((m) => m.name);
  const jump = html`<nav class="pd-jump" aria-label="Jump to a member">${order.concat(mateNames).map((n) => {
    const m = by.get(n);
    return html`<button type="button" class="btn btn-secondary" data-jump="${n}" style="color:${classVar(m && m.class)}">${n}</button>`;
  })}</nav>`;
  return html`${head("Members", "the two families, paired by role", armoryLine(a))}${sectionTabs("gear")}${gearSeg("armory")}${jump}${legend(a)}${pairs}<h2 class="mb-kick">Guildmates</h2>${mates(a, ctx.get("/api/guildgear").data, ctx.get("/api/v2/roster").data)}`;
}

// ---- Upgrades ----------------------------------------------------------------------

function picker(roster, name) {
  const members = (roster && roster.members) || [];
  const fams = Object.keys((roster && roster.families) || {});
  const guildNames = guilds().map((g) => g.name);
  const groups = fams.map((f) => [f + "'s family", members.filter((m) => m.family === f)])
    .concat(guildNames.map((g) => [g, members.filter((m) => !m.family && m.guild === g)]))
    .concat([["Other", members.filter((m) => !m.family && !guildNames.includes(m.guild))]])
    .filter((g) => g[1].length);
  return html`<label class="up-pick"><span class="dim mb-s">Guild member</span><select class="input" id="up-pick">${groups.map(([label, list]) => html`<optgroup label="${label}">${list.map((m) => html`<option value="${m.name}"${m.name === name ? raw(" selected") : ""}>${m.name}</option>`)}</optgroup>`)}</select></label>`;
}

function defaultName(roster) {
  const fams = (roster && roster.families) || {};
  const first = Object.values(fams)[0];
  return first && first.length ? first[0] : "";
}

// Every member in the gear read, across both guilds.
function membersOf(gg) {
  return ((gg && gg.guilds) || []).flatMap((g) => g.members || []);
}

// The next member with problems, walking the flagged list in the table's
// own worst-first order: after the member on screen, or the first flagged
// member when this one is not flagged. Null when nobody follows.
function nextProblem(gg, name) {
  const rows = membersOf(gg).filter((m) => (m.flags || []).length).sort(worstFirst);
  const i = rows.findIndex((m) => m.name === name);
  if (i >= 0) return rows[i + 1] || null;
  return rows[0] || null;
}

function upgradesTab(ctx) {
  const roster = ctx.get("/api/v2/roster");
  const name = ctx.query.name || "";
  const top = html`${head("Members", "what each slot can become, now and at 60")}${sectionTabs("gear")}${gearSeg("upgrades")}`;
  if (!name) {
    const wait = pendingRead(roster, 3);
    return html`${top}${wait || state("empty", "Pick a member", "Choose a guild member to see their slots.")}`;
  }
  const up = ctx.get("/api/v2/upgrades?name=" + encodeURIComponent(name));
  if (up.data === undefined && up.error && /404/.test(String(up.error))) {
    return html`${top}${state("empty", "No such guild member", "Nobody called " + name + " is in a family guild. Names come from the roster the server reports.")}`;
  }
  const wait = pendingRead(up, 4);
  if (wait) return html`${top}${wait}`;
  const q = liveQuery();
  const filter = q.filter || "all", sort = q.usort || "slot";
  const gg = ctx.get("/api/guildgear");
  const nxt = nextProblem(gg.data, name);
  const walk = nxt
    ? html`<p class="mb-s gt-walk"><a href="${"#/members/gear/upgrades?name=" + encodeURIComponent(nxt.name)}">Next member with problems: ${nxt.name}</a> <span class="dim">(${(nxt.flags || []).join(", ")})</span></p>`
    : gg.error ? html`<p class="mb-s dim">Next member with problems not measured: the gear read did not answer.</p>` : "";
  return html`${top}<div class="up-panel">${upgradesHead(up.data, roster.data ? picker(roster.data, name) : "")}${upgradesControls(filter, sort)}<div data-region="upslots">${upgradesBody(up.data, filter, sort)}</div>${upgradesFoot(up.data)}</div>${walk}`;
}

// ---- Table -------------------------------------------------------------------------

const COLS = [
  ["name", "Name", (m) => m.name], ["cls", "Class", (m) => m.class], ["level", "Lvl", (m) => m.level, 1],
  ["role", "Role", (m) => m.role], ["ilvl", "iLvl", (m) => m.avg_item_level, 1], ["worn", "Worn", (m) => m.worn, 1],
  ["empty", "Empty", (m) => m.empty, 1], ["weapon", "Weapon", (m) => (m.weapon ? 1 : 0), 1],
  ["weak", "Weakest", (m) => (m.weakest ? m.weakest.item_level : -1), 1], ["gold", "Gold", (m) => (m.gold ? m.gold.total : -1), 1],
  ["state", "State", (m) => m._state],
];

// The table's sort as the query has it: `sort=ilvl` is low to high, `sort=-ilvl`
// high to low, and no sort is worst first.
function gearSort(q) {
  const sort = q.sort || "";
  return { key: sort.replace(/^-/, ""), dir: sort.startsWith("-") ? "desc" : "asc" };
}

const WORST = "worst first: flagged, then no weapon, most empty slots, lowest item level";

function gearNote(q) {
  const cur = gearSort(q);
  const col = COLS.find((c) => c[0] === cur.key);
  if (!col) return html`${WORST}`;
  return html`sorted by ${col[1]}, ${cur.dir === "asc" ? "ascending" : "descending"}<button type="button" class="btn btn-ghost" data-gworst>Worst first</button>`;
}

function worstFirst(a, b) {
  return (!a.flags.length - !b.flags.length) || (a.weapon - b.weapon) || (b.empty - a.empty) || (a.avg_item_level - b.avg_item_level) || a.name.localeCompare(b.name);
}

// Grey or white pieces worn at level 50 or more, counted off the quality
// strip the read already carries: quality 0 is poor (grey), 1 is common
// (white). Below 50 the same pieces are ordinary levelling gear.
function greyWhite(m) {
  if ((m.level || 0) < 50) return 0;
  return (m.strip || []).filter((c) => c.quality === 0 || c.quality === 1).length;
}

// The problems the triage chips filter on. Every one is computable from the
// gear read today; wrong armour and dead stats are not, until the server
// flags grow them.
const PROBLEMS = [
  ["", "All"], ["empty", "Empty slots"], ["weapon", "No weapon"],
  ["grey", "Grey or white at 50+"], ["flagged", "Flagged"],
];

function problemHit(m, prob) {
  if (prob === "empty") return m.empty > 0;
  if (prob === "weapon") return !m.weapon;
  if (prob === "grey") return greyWhite(m) > 0;
  if (prob === "flagged") return (m.flags || []).length > 0;
  return true;
}

function tableRows(gg, roster, q) {
  const r = byName((roster && roster.members) || []);
  const guild = (q.guild || "").toLowerCase();
  let rows = membersOf(gg).filter((m) => !guild || (m.guild || "").toLowerCase() === guild)
    .filter((m) => problemHit(m, q.prob || ""))
    .map((m) => Object.assign({}, m, { _r: r.get(m.name), _state: stateOf(r.get(m.name) || m) }));
  const sort = q.sort || "";
  const col = COLS.find((c) => c[0] === sort.replace(/^-/, ""));
  if (!col) return rows.sort(worstFirst);
  const dir = sort.startsWith("-") ? -1 : 1;
  return rows.sort((x, y) => {
    const a = col[2](x), b = col[2](y);
    return dir * (col[3] ? a - b : String(a).localeCompare(String(b))) || x.name.localeCompare(y.name);
  });
}

function weakText(m) { return m.weakest ? (SLOT_WORDS[m.weakest.slot] || m.weakest.slot) + ", " + m.weakest.item_level : notMeasured("nothing worn"); }

// The roster's row when it has one (it adds stuck), else the gear row: both
// carry `online` and `life`, the one reading apiv2/presence.py makes.
function stateCell(m, at) { return stateLabel(m._r || m, at); }

function gearTable(rows, q, at) {
  const cur = gearSort(q);
  const th = COLS.map(([k, label]) => sortHead(label, k, cur, "data-gsort"));
  const tr = rows.map((m) => html`<tr><td><a class="mname" href="${"#/m/" + encodeURIComponent(m.name) + "/gear"}" style="color:${classVar(m.class)}">${m.name}</a></td><td>${m.class}</td><td class="num">${m.level}</td><td>${roleWord(m.role)}</td><td class="num">${m.avg_item_level}</td><td class="num">${m.worn}</td><td class="${"num" + (m.empty ? " warn" : " dim")}">${m.empty}</td><td class="${m.weapon ? "" : "bad"}">${m.weapon ? "yes" : "none"}</td><td class="muted">${weakText(m)}</td><td class="num">${m.gold ? m.gold.text : notMeasured()}</td><td>${stateCell(m, at)}</td></tr>`);
  return html`<div class="card gt-table"><table class="table"><thead><tr>${th}</tr></thead><tbody>${tr}</tbody></table></div>`;
}

// The strip said in words, for under the strip itself: how much is empty
// and what the weakest worn piece is.
function stripText(m) {
  const parts = [];
  if (m.empty) parts.push(m.empty + " empty");
  if (m.weakest) parts.push("weakest " + (SLOT_WORDS[m.weakest.slot] || m.weakest.slot) + " at item level " + m.weakest.item_level);
  return parts.join(", ");
}

function gearCards(rows, at) {
  return html`<div class="gt-cards">${rows.map((m) => {
    const grey = greyWhite(m);
    const flagged = (m.flags || []).length > 0;
    const href = flagged ? "#/members/gear/upgrades?name=" + encodeURIComponent(m.name) : "#/m/" + encodeURIComponent(m.name) + "/gear";
    const tags = (m.flags || []).map((f) => html`<span class="${"tag " + (f === "no weapon" ? "tag-bad" : "tag-warn")}">${f}</span>`);
    if (grey) tags.push(html`<span class="tag tag-warn">${grey} grey or white at 50+</span>`);
    return html`<a class="card gt-card" href="${href}"><span class="row gm-top"><span class="mname" style="color:${classVar(m.class)}">${m.name}</span>${stateCell(m, at)}</span><span class="dim mb-s">L${m.level} ${m.class}, ${roleWord(m.role)}, ${m.guild}</span><span class="mb-s">iLvl ${m.avg_item_level}, ${m.worn} of ${m.worn + m.empty} worn${m.empty ? html`, <span class="${m.empty >= 6 ? "warn" : ""}">${m.empty} empty</span>` : ""}${m.weapon ? "" : html`, <span class="bad">no weapon</span>`}</span>${strip(m)}<span class="muted mb-s">${stripText(m)}</span>${tags.length ? html`<span class="row gt-tags">${tags}</span>` : ""}</a>`;
  })}</div>`;
}

function tableBody(gg, roster, q) {
  const rows = tableRows(gg, roster, q);
  if (!rows.length) {
    return q.prob
      ? state("empty", "No members with this problem", q.guild ? "Nobody in this guild in the gear read matches the problem picked." : "Nobody in the gear read matches the problem picked.")
      : state("empty", "No members in this guild", "The guild gear read listed nobody for it.");
  }
  const at = roster && roster.checked_at;
  return html`${gearTable(rows, q, at)}${gearCards(rows, at)}`;
}

function guildChips(q) {
  const g = (q.guild || "").toLowerCase();
  return html`<div class="row"><div class="row" role="group" aria-label="Guild">${[["", guilds().length === 2 ? "Both guilds" : "All guilds"]].concat(guilds().map((x) => [x.slug, x.name])).map(([k, label]) => html`<button type="button" class="chip" data-guild="${k}" aria-pressed="${g === k ? "true" : "false"}">${label}</button>`)}</div><span class="dim mb-s gt-note">${gearNote(q)}</span></div>`;
}

// The sorts the card list offers, as the query values the table already
// understands: no sort is worst first, a bare key is low to high, a dashed
// key is high to low.
const TRIAGE_SORTS = [
  ["", "Worst first"], ["ilvl", "Item level, low first"],
  ["-empty", "Most empty slots"], ["level", "Level, low first"],
];

function sortWord(sort) {
  const cur = gearSort({ sort });
  const col = COLS.find((c) => c[0] === cur.key);
  return (col ? col[1] : sort) + (cur.dir === "asc" ? ", low first" : ", high first");
}

// The cards' own sort control: on a phone the table header that sorts is
// display:none, so without this the list cannot be sorted at all. A sort
// the select does not offer (set from a table header) rides as one extra
// option so the control never claims a sort the rows are not in.
function sortSelect(q) {
  const cur = q.sort || "";
  const offered = TRIAGE_SORTS.some(([k]) => k === cur);
  const extra = offered ? "" : html`<option value="${cur}" selected>${sortWord(cur)}</option>`;
  return html`<label class="gt-sort"><span class="sr-only">Sort gear</span><select class="input" data-gselect aria-label="Sort gear">${extra}${TRIAGE_SORTS.map(([k, label]) => html`<option value="${k}"${k === cur ? raw(" selected") : ""}>${label}</option>`)}</select></label>`;
}

function problemChips(q) {
  const cur = q.prob || "";
  return html`<div class="row gt-probs" role="group" aria-label="Problem">${PROBLEMS.map(([k, label]) => html`<button type="button" class="chip" data-prob="${k}" aria-pressed="${cur === k ? "true" : "false"}">${label}</button>`)}</div>`;
}

function tableTab(ctx) {
  const gg = ctx.get("/api/guildgear");
  const top = html`${head("Members", "every guild member, worst first")}${sectionTabs("gear")}${gearSeg("table")}`;
  const wait = pendingRead(gg, 4);
  if (wait) return html`${top}${wait}`;
  const q = liveQuery();
  return html`${top}<div class="gt-wrap">${guildChips(q)}<div class="row gt-controls">${sortSelect(q)}${problemChips(q)}</div><div data-region="gtable">${tableBody(gg.data, ctx.get("/api/v2/roster").data, q)}</div></div>`;
}

function bindTable(main, ctx) {
  const wrap = main.querySelector(".gt-wrap");
  if (!wrap) return;
  const region = wrap.querySelector("[data-region=gtable]");
  const redraw = (next) => {
    region.innerHTML = tableBody(ctx.get("/api/guildgear").data, ctx.get("/api/v2/roster").data, next).s;
    wrap.querySelectorAll("[data-guild]").forEach((c) => c.setAttribute("aria-pressed", String(c.getAttribute("data-guild") === (next.guild || ""))));
    wrap.querySelectorAll("[data-prob]").forEach((c) => c.setAttribute("aria-pressed", String((c.getAttribute("data-prob") || "") === (next.prob || ""))));
    const note = wrap.querySelector(".gt-note");
    if (note) note.innerHTML = gearNote(next).s;
    const sel = wrap.querySelector("[data-gselect]");
    if (sel && TRIAGE_SORTS.some(([k]) => k === (next.sort || ""))) sel.value = next.sort || "";
  };
  wrap.addEventListener("click", (e) => {
    const b = e.target.closest("[data-gsort], [data-guild], [data-gworst], [data-prob]");
    if (!b) return;
    const q = liveQuery();
    let next;
    if (b.hasAttribute("data-guild")) next = setQuery({ guild: b.getAttribute("data-guild") });
    else if (b.hasAttribute("data-prob")) next = setQuery({ prob: b.getAttribute("data-prob") });
    else if (b.hasAttribute("data-gworst")) next = setQuery({ sort: "" });
    else {
      const n = flipSort(gearSort(q), b.getAttribute("data-gsort"), "asc");
      next = setQuery({ sort: (n.dir === "desc" ? "-" : "") + n.key });
    }
    redraw(next);
    const focus = b.hasAttribute("data-gsort") ? region.querySelector('[data-gsort="' + b.getAttribute("data-gsort") + '"]')
      : b.hasAttribute("data-gworst") ? region.querySelector("[data-gsort]") : null;
    if (focus) focus.focus({ preventScroll: true });
  });
  const sel = wrap.querySelector("[data-gselect]");
  if (sel) sel.addEventListener("change", () => redraw(setQuery({ sort: sel.value })));
}

// ---- the view ------------------------------------------------------------------------

export default {
  css: ["views/members.css"],
  reads(ctx) {
    if (ctx.params.tab === "upgrades") {
      return ctx.query.name ? ["/api/v2/upgrades?name=" + encodeURIComponent(ctx.query.name), "/api/v2/roster", "/api/guildgear"] : ["/api/v2/roster"];
    }
    if (ctx.params.tab === "table") return ["/api/guildgear", "/api/v2/roster"];
    return ["/api/armory", "/api/guildgear", "/api/v2/roster"];
  },
  every: 60000,
  title: (ctx) => (ctx.params.tab === "upgrades" ? "Upgrades" : ctx.params.tab === "table" ? "Gear table" : "Gear"),
  render(ctx) {
    if (ctx.params.tab === "upgrades") return upgradesTab(ctx);
    if (ctx.params.tab === "table") return tableTab(ctx);
    return paperdollTab(ctx);
  },
  after(main, ctx) {
    if (ctx.params.tab === "upgrades") {
      const roster = ctx.get("/api/v2/roster").data;
      if (!ctx.query.name && roster) {
        const first = defaultName(roster);
        if (first) location.replace("#/members/gear/upgrades?name=" + encodeURIComponent(first));
        return;
      }
      const pick = main.querySelector("#up-pick");
      if (pick) pick.addEventListener("change", () => { location.hash = "#/members/gear/upgrades?name=" + encodeURIComponent(pick.value); });
      const up = ctx.get("/api/v2/upgrades?name=" + encodeURIComponent(ctx.query.name || "")).data;
      if (up) bindUpgrades(main, up);
      return;
    }
    if (ctx.params.tab === "table") { bindTable(main, ctx); return; }
    bindTrees(main);
    mountModels(main);
    main.querySelectorAll("[data-jump]").forEach((b) => b.addEventListener("click", () => {
      const el = document.getElementById("armory-" + b.getAttribute("data-jump"));
      const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      if (el) el.scrollIntoView({ behavior: still ? "auto" : "smooth", block: "start", inline: "start" });
    }));
  },
};


