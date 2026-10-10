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
  liveQuery, setQuery, byName, stateOf, stateLabel, sectionTabs, gearSeg, head, paperdoll, bindTrees, roleWord,
  upgradesHead, upgradesControls, upgradesBody, upgradesFoot, bindUpgrades,
} from "./_members.js";
import { mountModels } from "./_model.js";

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
    return html`<a class="card gm-card" href="${"#/m/" + encodeURIComponent(m.name) + "/gear"}"><span class="row gm-top"><span class="mname" style="color:${classVar(m.class)}">${m.name}</span><span class="dim mb-s">L${m.level} ${m.class} | ${m.guild}</span></span>${strip(m)}<span class="dim mb-s">iLvl ${Math.round(m.avg_item_level)} | ${m.worn} of ${m.of} worn${w ? " | weakest " + (SLOT_WORDS[w.slot] || w.slot) + " at " + w.item_level : ""}${r.has(m.name) && r.get(m.name).stuck ? " | stuck" : ""}</span></a>`;
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
  const pairs = (a.pairs || []).map((p) => {
    const left = by.get(p.left), right = by.get(p.right);
    const role = roleWord((left && left.party_role) || (right && right.party_role) || p.role);
    const card = (m, name) => (m ? paperdoll(m, a.doll) : html`<div class="card pd pd-none">${a.no_counterpart || "no one in this role on this side"}${name ? " (" + name + ")" : ""}</div>`);
    return html`<section class="pd-pair"><h2 class="mb-kick">${role}</h2><div class="pd-row hscroll">${card(left)}${card(right)}</div></section>`;
  });
  const jump = html`<nav class="pd-jump" aria-label="Jump to a member">${order.map((n) => {
    const m = by.get(n);
    return html`<button type="button" class="btn btn-secondary" data-jump="${n}" style="color:${classVar(m && m.class)}">${n}</button>`;
  })}</nav>`;
  return html`${head("Members", "the two families, paired by role", armoryLine(a))}${sectionTabs("gear")}${gearSeg("armory")}${jump}${legend(a)}${pairs}<h2 class="mb-kick">Guildmates</h2>${mates(a, ctx.get("/api/guildgear").data, ctx.get("/api/v2/roster").data)}`;
}

// ---- Upgrades ----------------------------------------------------------------------

function picker(roster, name) {
  const members = (roster && roster.members) || [];
  const fams = Object.keys((roster && roster.families) || {});
  const groups = fams.map((f) => [f + "'s family", members.filter((m) => m.family === f)])
    .concat(["Cave", "Bonkers"].map((g) => [g, members.filter((m) => !m.family && m.guild === g)]))
    .concat([["Other", members.filter((m) => !m.family && m.guild !== "Cave" && m.guild !== "Bonkers")]])
    .filter((g) => g[1].length);
  return html`<label class="up-pick"><span class="dim mb-s">Guild member</span><select class="input" id="up-pick">${groups.map(([label, list]) => html`<optgroup label="${label}">${list.map((m) => html`<option value="${m.name}"${m.name === name ? raw(" selected") : ""}>${m.name}</option>`)}</optgroup>`)}</select></label>`;
}

function defaultName(roster) {
  const fams = (roster && roster.families) || {};
  const first = Object.values(fams)[0];
  return first && first.length ? first[0] : "";
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
  return html`${top}<div class="up-panel">${upgradesHead(up.data, roster.data ? picker(roster.data, name) : "")}${upgradesControls(filter, sort)}<div data-region="upslots">${upgradesBody(up.data, filter, sort)}</div>${upgradesFoot(up.data)}</div>`;
}

// ---- Table -------------------------------------------------------------------------

const COLS = [
  ["name", "Name", (m) => m.name], ["cls", "Class", (m) => m.class], ["level", "Lvl", (m) => m.level, 1],
  ["role", "Role", (m) => m.role], ["ilvl", "iLvl", (m) => m.avg_item_level, 1], ["worn", "Worn", (m) => m.worn, 1],
  ["empty", "Empty", (m) => m.empty, 1], ["weapon", "Weapon", (m) => (m.weapon ? 1 : 0), 1],
  ["weak", "Weakest", (m) => (m.weakest ? m.weakest.item_level : -1), 1], ["gold", "Gold", (m) => (m.gold ? m.gold.total : -1), 1],
  ["state", "State", (m) => m._state],
];

function worstFirst(a, b) {
  return (!a.flags.length - !b.flags.length) || (a.weapon - b.weapon) || (b.empty - a.empty) || (a.avg_item_level - b.avg_item_level) || a.name.localeCompare(b.name);
}

function tableRows(gg, roster, q) {
  const r = byName((roster && roster.members) || []);
  const guild = (q.guild || "").toLowerCase();
  let rows = ((gg && gg.guilds) || []).flatMap((g) => g.members || []).filter((m) => !guild || (m.guild || "").toLowerCase() === guild)
    .map((m) => Object.assign({}, m, { _r: r.get(m.name), _state: stateOf(r.get(m.name)) }));
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

function stateCell(m, at) { return m._r ? stateLabel(m._r, at) : html`<span class="dim mb-s">${m.presence}</span>`; }

function gearTable(rows, q, at) {
  const sort = q.sort || "";
  const th = COLS.map(([k, label]) => {
    const on = sort.replace(/^-/, "") === k;
    const dir = sort.startsWith("-") ? "descending" : "ascending";
    return html`<th scope="col"${on ? raw(' aria-sort="' + dir + '"') : ""}><button type="button" data-gsort="${k}">${label}${on ? html`<i class="${sort.startsWith("-") ? "ph ph-caret-down" : "ph ph-caret-up"}" aria-hidden="true"></i>` : ""}</button></th>`;
  });
  const tr = rows.map((m) => html`<tr><td><a class="mname" href="${"#/m/" + encodeURIComponent(m.name) + "/gear"}" style="color:${classVar(m.class)}">${m.name}</a></td><td>${m.class}</td><td class="num">${m.level}</td><td>${roleWord(m.role)}</td><td class="num">${m.avg_item_level}</td><td class="num">${m.worn}</td><td class="${"num" + (m.empty ? " warn" : " dim")}">${m.empty}</td><td class="${m.weapon ? "" : "bad"}">${m.weapon ? "yes" : "none"}</td><td class="muted">${weakText(m)}</td><td class="num">${m.gold ? m.gold.text : notMeasured()}</td><td>${stateCell(m, at)}</td></tr>`);
  return html`<div class="card gt-table"><table class="table"><thead><tr>${th}</tr></thead><tbody>${tr}</tbody></table></div>`;
}

function gearCards(rows, at) {
  return html`<div class="gt-cards">${rows.map((m) => html`<a class="card gt-card" href="${"#/m/" + encodeURIComponent(m.name) + "/gear"}"><span class="row gm-top"><span class="mname" style="color:${classVar(m.class)}">${m.name}</span>${stateCell(m, at)}</span><span class="dim mb-s">L${m.level} ${m.class} | ${roleWord(m.role)} | iLvl ${m.avg_item_level} | ${m.worn} worn | <span class="${m.empty ? "warn" : ""}">${m.empty} empty</span>${m.weapon ? "" : html` | <span class="bad">no weapon</span>`}</span><span class="muted mb-s">Weakest: ${weakText(m)} | ${m.gold ? m.gold.text : notMeasured()}</span></a>`)}</div>`;
}

function tableBody(gg, roster, q) {
  const rows = tableRows(gg, roster, q);
  if (!rows.length) return state("empty", "No members in this guild", "The guild gear read listed nobody for it.");
  const at = roster && roster.checked_at;
  return html`${gearTable(rows, q, at)}${gearCards(rows, at)}`;
}

function guildChips(q) {
  const g = (q.guild || "").toLowerCase();
  return html`<div class="row"><div class="row" role="group" aria-label="Guild">${[["", "Both guilds"], ["cave", "Cave"], ["bonkers", "Bonkers"]].map(([k, label]) => html`<button type="button" class="chip" data-guild="${k}" aria-pressed="${g === k ? "true" : "false"}">${label}</button>`)}</div><span class="dim mb-s gt-note">${q.sort ? "sorted by " + q.sort.replace(/^-/, "") : "worst first: flagged, then no weapon, most empty slots, lowest item level"}</span></div>`;
}

function tableTab(ctx) {
  const gg = ctx.get("/api/guildgear");
  const top = html`${head("Members", "every guild member, worst first")}${sectionTabs("gear")}${gearSeg("table")}`;
  const wait = pendingRead(gg, 4);
  if (wait) return html`${top}${wait}`;
  const q = liveQuery();
  return html`${top}<div class="gt-wrap">${guildChips(q)}<div data-region="gtable">${tableBody(gg.data, ctx.get("/api/v2/roster").data, q)}</div></div>`;
}

function bindTable(main, ctx) {
  const wrap = main.querySelector(".gt-wrap");
  if (!wrap) return;
  const region = wrap.querySelector("[data-region=gtable]");
  wrap.addEventListener("click", (e) => {
    const b = e.target.closest("[data-gsort], [data-guild]");
    if (!b) return;
    const q = liveQuery();
    let next;
    if (b.hasAttribute("data-guild")) next = setQuery({ guild: b.getAttribute("data-guild") });
    else {
      const k = b.getAttribute("data-gsort");
      next = setQuery({ sort: q.sort === k ? "-" + k : q.sort === "-" + k ? "" : k });
    }
    region.innerHTML = tableBody(ctx.get("/api/guildgear").data, ctx.get("/api/v2/roster").data, next).s;
    wrap.querySelectorAll("[data-guild]").forEach((c) => c.setAttribute("aria-pressed", String(c.getAttribute("data-guild") === (next.guild || ""))));
    const note = wrap.querySelector(".gt-note");
    if (note) note.textContent = next.sort ? "sorted by " + next.sort.replace(/^-/, "") : "worst first: flagged, then no weapon, most empty slots, lowest item level";
    const focus = b.hasAttribute("data-gsort") ? region.querySelector('[data-gsort="' + b.getAttribute("data-gsort") + '"]') : null;
    if (focus) focus.focus({ preventScroll: true });
  });
}

// ---- the view ------------------------------------------------------------------------

export default {
  css: ["views/members.css"],
  reads(ctx) {
    if (ctx.params.tab === "upgrades") {
      return ctx.query.name ? ["/api/v2/upgrades?name=" + encodeURIComponent(ctx.query.name), "/api/v2/roster"] : ["/api/v2/roster"];
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


