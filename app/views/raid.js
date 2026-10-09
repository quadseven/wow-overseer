// Raid: Molten Core, one guild at a time (#/raid/mc/cave|bonkers).
//
// Every sentence, tile, blocker, table cell and goal is the server's
// (/api/raidgoals: raidready, raidsupply, raidgoals, raidrun, preraid). The
// seats are the approved lineup (/api/v2/raidteams): an open seat is drawn
// open, never filled with a guess. Each family member's next upgrades come
// from /api/upgrades. The page owns layout, the tone a server tone is drawn
// in, and the count of who clears each readiness gate, from numbers the
// server reports; a number it does not report is "not measured".
//
// View state lives in the URL: ?view=group|gate&gate=<key>.

import { html, raw, item, member, memberHref, notMeasured, pendingRead, state, plural, classVar } from "../ui.js";
import { GUILDS } from "../router.js";

const TEAMS = (g) => "/api/v2/raidteams?guild=" + g;
const GOALS = "/api/raidgoals";
const UPS = (name) => "/api/upgrades?name=" + encodeURIComponent(name);

// The reads the router polls for this route (see after()).
let routed = [];

const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
const ROLE_ICON = { tank: "ph-fill ph-shield", healer: "ph-fill ph-first-aid", dps: "ph-fill ph-sword" };
const ROLE_WORD = { tank: "tank", healer: "healer", dps: "damage" };

// A server tone name, drawn in one of the status roles. An unknown tone is
// drawn plain rather than dropped.
function tone(t) {
  if (t === "no" || t === "bad" || t === "hard") return "bad";
  if (t === "unsure" || t === "warn" || t === "soft") return "warn";
  if (t === "up" || t === "ok") return "ok";
  return "";
}

function guildCard(goals, guild) {
  return ((goals && goals.guilds) || []).find((g) => String(g.guild || "").toLowerCase() === guild) || null;
}

function familyNames(card) {
  return ((card && card.attunement && card.attunement.members) || []).map((m) => m.name).filter(Boolean);
}

function upgradeReads(ctx) {
  const card = guildCard(ctx.get(GOALS).data, ctx.params.guild);
  if (!card || (card.preraid && (card.preraid.members || []).length)) return [];
  return familyNames(card).map(UPS);
}

function hrefFor(ctx, query) {
  const q = Object.entries(query).filter(([, v]) => v).map(([k, v]) => k + "=" + encodeURIComponent(v)).join("&");
  return "#/raid/mc/" + ctx.params.guild + (q ? "?" + q : "");
}

// ---- readiness gates -----------------------------------------------------
//
// Six bars a seated raider is held to. Each test answers true, false or null
// (not measured) from the server's numbers: the seats and the per-member raid
// fields from /api/v2/raidteams, the role's targets and the gear share from
// /api/raidgoals. A gate the instance keeps is drawn bad when it fails; a
// convention is drawn warn.

function gateList(card) {
  const bars = card.gates || {};
  const min = bars.min_level;
  const share = bars.gear_share;
  return [
    { key: "seat", noun: "seats", label: "Seats filled", rule: "a member in the approved seat", tone: "bad" },
    {
      key: "level", noun: "level", label: min ? "Level " + min + "+" : "Level", tone: "bad",
      rule: min ? "the lowest level the instance's own access row lets in" : "the instance's lowest level was not read",
      test: (m) => (min && m.level != null ? m.level >= min : null),
      have: (m) => (m.level == null ? null : "L" + m.level),
      gap: (m) => min - m.level, need: (m) => plural(min - m.level, "level"),
    },
    {
      key: "attune", noun: "attunement", label: "Attuned", tone: "warn", rule: "Attunement to the Core rewarded",
      test: (m) => m.attuned, have: () => "not attuned", gap: () => 1, need: () => "the quest",
    },
    {
      key: "fr", noun: "fire resistance", label: "Fire resistance", tone: "warn", rule: "the role's target, from worn gear",
      test: (m, r) => (m.fire_resistance == null || !r ? null : m.fire_resistance >= (r.fire_target || 0)),
      have: (m, r) => m.fire_resistance + " of " + r.fire_target + " FR",
      gap: (m, r) => r.fire_target - m.fire_resistance, need: (m, r) => (r.fire_target - m.fire_resistance) + " more FR",
    },
    {
      key: "supply", noun: "supplies", label: "Supplies carried", tone: "warn", rule: "the night's consumables for the role, in bags",
      test: (m, r) => (r ? r.supplies_carried >= r.supplies_wanted : null),
      have: (m, r) => r.supplies_carried + " of " + r.supplies_wanted + " supplies",
      gap: (m, r) => r.supplies_wanted - r.supplies_carried, need: (m, r) => (r.supplies_wanted - r.supplies_carried) + " more",
    },
    {
      key: "gear", noun: "pre-raid gear", label: "Pre-raid gear", tone: "warn",
      rule: share != null ? Math.round(share * 100) + "% of slots at or near pre-raid best" : "the gear bar was not read",
      test: (m, r) => (r && r.gear != null && share != null ? r.gear >= share : null),
      have: (m, r) => Math.round(r.gear * 100) + "% gear",
      gap: (m, r) => Math.round((share - r.gear) * 100), need: () => Math.round(share * 100) + "%",
    },
  ];
}

function seatedOf(teams) {
  return (teams.seats || []).flat().filter((s) => s.name);
}

// {pass, fail, unread} for one gate over the seated raiders.
function gateCount(gate, teams, raiders) {
  const seated = seatedOf(teams);
  if (gate.key === "seat") return { pass: seated.length, fail: (teams.seats || []).flat().length - seated.length, unread: 0 };
  const out = { pass: 0, fail: 0, unread: 0 };
  seated.forEach((s) => {
    const r = gate.test(teams.members[s.name] || {}, raiders.get(s.name));
    if (r === true) out.pass += 1; else if (r === false) out.fail += 1; else out.unread += 1;
  });
  return out;
}

// The first gate a seated raider falls short of: {text, tone}.
function firstFail(gates, m, r) {
  let unread = false;
  for (const g of gates) {
    if (!g.test) continue;
    const ok = g.test(m, r);
    if (ok === false) return { text: g.have(m, r), tone: g.tone };
    if (ok == null) unread = true;
  }
  return unread ? { text: "not measured", tone: "dim" } : { text: "ready", tone: "ok" };
}

// ---- pieces ----------------------------------------------------------------

function tiles(card) {
  return html`<div class="raid-tiles">${(card.tiles || []).map((t) => html`<div class="raid-tile" data-tone="${tone(t.tone)}"><span class="v">${t.value}</span><span class="k">${t.label}</span></div>`)}</div>`;
}

function headCard(card) {
  return html`<div class="card raid-head-card"><span class="raid-headline">${card.headline}</span>${tiles(card)}${card.roster_line ? html`<span class="muted">${card.roster_line}</span>` : ""}${card.gear_line ? html`<span class="muted">${card.gear_line}</span>` : ""}</div>`;
}

function gateTable(ctx, gates, teams, raiders, view, picked) {
  const total = (teams.seats || []).flat().length;
  const rows = gates.map((g) => {
    const c = gateCount(g, teams, raiders);
    const pct = total ? Math.round((100 * c.pass) / total) : 0;
    const t = c.pass >= total ? "ok" : c.pass === 0 ? "bad" : "warn";
    const on = view === "gate" ? picked === g.key : g.key === "seat";
    const href = hrefFor(ctx, g.key === "seat" ? { view: "group" } : { view: "gate", gate: g.key });
    const unread = c.unread ? html`<span class="dim"> | ${c.unread} not measured</span>` : "";
    return html`<a class="gate" href="${href}"${on ? raw(' aria-current="true"') : ""}><span class="gate-label">${g.label}<span class="gate-rule">${g.rule}</span></span><span class="gate-count ${t}">${c.pass} / ${total}${unread}</span><span class="gate-bar" aria-hidden="true"><span style="width:${pct}%" data-tone="${t}"></span></span></a>`;
  });
  return html`<div class="card raid-gates"><span class="card-title">Readiness gates</span><span class="muted">Who clears each bar, of the ${total} seats. Pick one to see who falls short.</span><div class="gate-list">${rows}</div></div>`;
}

function viewSwitch(ctx, view, picked) {
  const items = [["group", "By group", { view: "group" }], ["gate", "By gate", { view: "gate", gate: picked }]];
  return html`<div class="seg" role="group" aria-label="Lineup view">${items.map(([k, label, q]) => html`<a href="${hrefFor(ctx, q)}"${view === k ? raw(' aria-current="page"') : ""}>${label}</a>`)}</div>`;
}

function seatRow(ctx, seat, teams, raiders, gates) {
  if (!seat.name) {
    return html`<div class="seat open"><span class="seat-name"><i class="ph ph-circle-dashed" aria-hidden="true"></i>open seat</span><span class="seat-sub">${seat.class} ${ROLE_WORD[seat.seat] || ""}, approved as ${seat.approved}</span></div>`;
  }
  const m = teams.members[seat.name] || {};
  const f = firstFail(gates, m, raiders.get(seat.name));
  const renamed = seat.approved !== seat.name ? html`<span class="dim"> (to be ${seat.approved})</span>` : "";
  const aura = seat.fire_aura ? html`<i class="ph-fill ph-fire aura" aria-hidden="true" title="Fire resistance aura or totem for the group"></i><span class="sr-only">, carries the group's fire resistance aura</span>` : "";
  return html`<a class="seat" href="${memberHref(seat.name)}"><span class="seat-name" style="color:${classVar(seat.class)}"><i class="${ROLE_ICON[seat.seat] || ROLE_ICON.dps}" aria-hidden="true" title="${ROLE_WORD[seat.seat] || ""}"></i>${seat.name}${renamed}${aura}</span><span class="seat-sub ${f.tone}">${f.text}</span></a>`;
}

function groupsView(ctx, card, teams, raiders, gates) {
  const gaps = teams.gaps || {};
  const short = (gaps.tanks || 0) + (gaps.healers || 0) + (gaps.damage || 0);
  const gapLine = short
    ? "Short " + plural(gaps.tanks || 0, "tank") + ", " + plural(gaps.healers || 0, "healer") + " and " + (gaps.damage || 0) + " damage. Open seats stay open; they are never filled with characters the guild does not have."
    : "Every approved seat has its member. Open seats would stay open; they are never filled with characters the guild does not have.";
  const cards = (teams.seats || []).map((group, i) => {
    return html`<div class="card raid-group"><span class="group-label">Group ${i + 1}${i === 0 ? " | the family" : ""}</span>${group.map((s) => seatRow(ctx, s, teams, raiders, gates))}</div>`;
  });
  return html`<span class="${short ? "warn" : "muted"}">${gapLine}</span>${card.gap_line ? html`<span class="muted">${card.gap_line}</span>` : ""}<div class="raid-groups">${cards}</div>`;
}

function gateView(gate, teams, raiders) {
  if (gate.key === "seat") return "";
  const rows = [];
  const unread = [];
  seatedOf(teams).forEach((s) => {
    const m = teams.members[s.name] || {};
    const r = raiders.get(s.name);
    const ok = gate.test(m, r);
    if (ok === false) rows.push({ s, m, r, gap: gate.gap(m, r) || 0 });
    else if (ok == null) unread.push(s);
  });
  rows.sort((a, b) => b.gap - a.gap || a.s.name.localeCompare(b.s.name));
  if (!rows.length && !unread.length) return state("empty", "Every seated raider clears this gate.");
  const line = (x) => html`<div class="gap-row"><span>${member({ name: x.s.name, cls: x.s.class })}<span class="dim"> ${x.m.level != null ? "L" + x.m.level + " " : ""}${x.s.class}</span></span><span class="${gate.tone}">${gate.have(x.m, x.r)}</span><span class="muted">needs ${gate.need(x.m, x.r)}</span></div>`;
  const notRead = unread.length ? html`<div class="gap-row"><span class="dim">${plural(unread.length, "raider")} not measured: ${unread.map((s) => s.name).join(", ")}</span></div>` : "";
  return html`<div class="card raid-gap"><span class="muted">${plural(rows.length, "raider")} short, sorted by the gap.</span>${rows.map(line)}${notRead}</div>`;
}

function blockersCard(card) {
  const list = (card.blockers || []).map((b) => {
    const hard = b.tone === "hard";
    return html`<div class="blocker"><i class="${hard ? "ph-fill ph-x-circle bad" : "ph ph-warning warn"}" aria-hidden="true"></i><span><span class="sr-only">${hard ? "Stops the raid: " : "Makes it harder: "}</span>${b.text}</span></div>`;
  });
  return html`<div class="card raid-block"><span class="card-title">What stands in the way</span>${card.blockers_line ? html`<span class="muted">${card.blockers_line}</span>` : ""}${list}</div>`;
}

function attuneCard(card) {
  const a = card.attunement || {};
  return html`<div class="card raid-block"><span class="card-title">Attunement to the Core</span>${a.line ? html`<span class="muted">${a.line}</span>` : ""}<div class="row">${(a.members || []).map((m) => html`<span class="tag ${m.status === "attuned" ? "tag-outline" : "tag-neutral"}">${m.line}</span>`)}</div><ol class="raid-steps">${(a.steps || []).map((s) => html`<li>${s}</li>`)}</ol>${a.unproven ? html`<span class="small dim">${a.unproven}</span>` : ""}${a.bots ? html`<span class="small dim">${a.bots}</span>` : ""}<span class="card-title raid-sub">The raid run</span>${card.run_line ? html`<span class="muted">${card.run_line}</span>` : ""}${card.clearing_line ? html`<span class="small dim">${card.clearing_line}</span>` : ""}</div>`;
}

// A table on desktop, one card per row on phone: every cell carries its
// column's name for the phone layout to print above it.
function table(columns, rows, cell) {
  return html`<table class="table raid-table"><thead><tr>${columns.map((c) => html`<th scope="col">${c}</th>`)}</tr></thead><tbody>${rows.map((r, ri) => html`<tr>${columns.map((c, i) => html`<td data-label="${c}">${cell(r, i, ri)}</td>`)}</tr>`)}</tbody></table>`;
}

function raidersFold(card, teams) {
  const cols = card.raider_columns || [];
  const rows = card.raiders || [];
  const cls = (n) => ((teams && teams.members && teams.members[n]) || {}).class;
  const cell = (r, i) => {
    const text = (r.cells || [])[i];
    if (i === 1) return member({ name: r.name, cls: cls(r.name) });
    if (i === cols.length - 1) return html`<span class="${r.ready ? "ok" : "warn"}">${text}</span>`;
    return text;
  };
  return html`<details class="card raid-fold"><summary><span class="fold-body"><span class="card-title">Every raider (${rows.length})</span><span class="muted">${card.raiders_line}</span></span></summary>${rows.length ? table(cols, rows, cell) : state("empty", "No raider is placed.")}</details>`;
}

function supplyCard(card) {
  const s = card.supply;
  if (!s) return html`<div class="card raid-block"><span class="card-title">Supply for a night in the Core</span>${notMeasured()}</div>`;
  // The last column ("how it closes") is a sentence, drawn under the name.
  const cols = (s.supply_columns || []).slice(0, 4);
  const cell = (r, i) => {
    const text = (r.cells || [])[i];
    if (i === 0) {
      const how = (r.cells || [])[4];
      return html`<span class="supply-name">${r.entry ? item({ entry: r.entry, name: text }) : text}${how ? html`<span class="small dim">${how}</span>` : ""}</span>`;
    }
    return html`<span class="num ${i === 3 && r.short ? "warn" : ""}">${text}</span>`;
  };
  return html`<div class="card raid-block"><span class="card-title">Supply for a night in the Core</span>${s.line ? html`<span class="muted">${s.line}</span>` : ""}${s.budget_line ? html`<span class="small dim">${s.budget_line}</span>` : ""}${table(cols, s.supplies || [], cell)}</div>`;
}

function fireCard(card, teams) {
  const s = card.supply;
  if (!s) return html`<div class="card raid-block"><span class="card-title">Fire resistance, tanks first</span>${notMeasured()}</div>`;
  const cls = (n) => ((teams && teams.members && teams.members[n]) || {}).class;
  const cols = s.fire_columns || [];
  const cell = (r, i) => {
    const text = (r.cells || [])[i];
    if (i === 0) return member({ name: text, cls: cls(text) });
    if (i === cols.length - 1) return html`<span class="num ${r.short ? "warn" : "ok"}">${text}</span>`;
    return i >= 2 ? html`<span class="num">${text}</span>` : text;
  };
  return html`<div class="card raid-block"><span class="card-title">Fire resistance, tanks first</span>${table(cols, s.fire || [], cell)}${s.fire_line ? html`<span class="small dim">${s.fire_line}</span>` : ""}</div>`;
}

// ---- next upgrades -----------------------------------------------------------

function whereText(where) {
  return (where || []).map((w) => w.label).filter(Boolean).join("; ");
}

function upgradesFromRead(name, read, teams) {
  const cls = ((teams && teams.members && teams.members[name]) || {}).class;
  const head = (line) => html`<summary><span class="fold-body"><span>${member({ name, cls })} <span class="muted">${line}</span></span></span></summary>`;
  if (read.data === undefined) {
    return html`<details class="card raid-fold">${head(read.error ? "upgrades not measured" : "reading upgrades")}</details>`;
  }
  const d = read.data;
  const rows = (d.slots || []).filter((s) => s.next).sort((a, b) => (b.next.gain || 0) - (a.next.gain || 0)).slice(0, 5);
  const list = rows.length
    ? rows.map((s) => html`<div class="up-row"><span class="dim">${s.label}</span><span>${item({ entry: s.next.entry, name: s.next.name })}</span><span class="muted">${whereText(s.next.where) || notMeasured()}</span><span class="num ok">+${Math.round(s.next.gain)}</span></div>`)
    : html`<span class="muted">No listed piece beats what is worn.</span>`;
  return html`<details class="card raid-fold">${head((d.ready && d.ready.line) || "")}<div class="up-rows">${list}</div><a class="raid-more" href="${memberHref(name, "upgrades")}">All ${(d.slots || []).length} slots for ${name}</a></details>`;
}

function preraidMember(m, columns, teams) {
  const cls = ((teams && teams.members && teams.members[m.name]) || {}).class;
  const cell = (r, i) => {
    const text = r.cells[i];
    const it = (r.items || [])[i];
    if (it && text.startsWith(it.name)) return html`${item({ entry: it.entry, name: it.name, quality: it.quality })}${text.slice(it.name.length)}`;
    return text;
  };
  return html`<details class="card raid-fold"><summary><span class="fold-body"><span>${member({ name: m.name, cls })} <span class="muted">${m.line}</span></span></span></summary>${table(columns, m.rows || [], cell)}<a class="raid-more" href="${memberHref(m.name, "upgrades")}">All slots for ${m.name}</a></details>`;
}

function upgradesSection(ctx, card, teams) {
  const pre = card.preraid || {};
  const members = pre.members || [];
  const body = members.length
    ? members.map((m) => preraidMember(m, pre.columns || [], teams))
    : familyNames(card).map((n) => upgradesFromRead(n, ctx.get(UPS(n)), teams));
  const notes = [...(pre.runs || []), ...(pre.progress || []), ...(pre.closed || [])];
  return html`<section class="section"><h2 class="raid-h2">Next upgrades and where they drop</h2>${pre.line ? html`<span class="muted">${pre.line}${members.length ? "" : " Until then, each member's next upgrades from the gear lists:"}</span>` : ""}<div class="raid-stack">${body}</div>${notes.map((n) => html`<span class="small dim">${n}</span>`)}</section>`;
}

// ---- consumables -----------------------------------------------------------------

function itemLine(entry, name, line) {
  if (entry && line && line.startsWith(name)) return html`<span class="il">${item({ entry, name })}${line.slice(name.length)}</span>`;
  return line;
}

function reagent(r) {
  return html`<div class="reagent"><span class="il">${itemLine(r.entry, r.name, r.line)}${r.source ? html` <span class="dim">| ${r.source}</span>` : ""}</span>${r.made_line ? html`<span class="small dim">${r.made_line}</span>` : ""}${(r.made || []).map(reagent)}</div>`;
}

function recipe(rc, products) {
  const p = products.find((x) => x.name === rc.product);
  return html`<div class="recipe"><span class="recipe-head">${p ? item({ entry: p.entry, name: p.name, quality: p.quality }) : rc.product}${rc.rank_line ? html` <span class="dim">| ${rc.rank_line}</span>` : ""}</span><span>${rc.line}</span>${rc.who_line ? html`<span class="muted">${rc.who_line}</span>` : ""}${(rc.blocked || []).map((b) => html`<span class="bad">${b}</span>`)}${(rc.unknown || []).map((b) => html`<span class="dim">${b}</span>`)}${(rc.reagents || []).map(reagent)}</div>`;
}

function goalCard(g) {
  const products = g.products || [];
  const holders = (g.members || []).filter((m) => (m.held || 0) + (m.banked || 0) > 0);
  const chips = (g.chips || []).map((c) => html`<span class="tag raid-chip" data-tone="${tone(c.tone)}">${c.text}</span>`);
  const everyone = (g.members || []).length
    ? html`<details class="fold"><summary>Every member (${g.members.length})</summary><div class="raid-lines">${g.members.map((m) => html`<span class="muted">${m.line}</span>`)}</div></details>`
    : "";
  return html`<details class="card raid-goal"><summary><span class="goal-top"><span class="goal-name">${g.name}</span><span class="muted">${g.line}</span></span><span class="row">${chips}</span></summary><div class="goal-body">${g.need_line ? html`<span class="muted">${g.need_line}</span>` : ""}${products.map((p) => html`<span>${itemLine(p.entry, p.name, p.line)}</span>`)}${holders.length ? holders.map((m) => html`<span>${m.line}</span>`) : html`<span class="dim">Nobody holds any yet.</span>`}${everyone}${g.recipes_line ? html`<span class="small dim">${g.recipes_line}</span>` : ""}${(g.recipes || []).map((rc) => recipe(rc, products))}</div></details>`;
}

function consumablesSection(card) {
  const gl = card.goals || {};
  return html`<section class="section"><h2 class="raid-h2">Consumables, per guild</h2>${gl.line ? html`<span class="muted">${gl.line}${gl.roster_line ? ", " + gl.roster_line : ""}.</span>` : ""}${gl.order ? html`<span class="small dim">${gl.order}</span>` : ""}<div class="raid-stack">${(gl.goals || []).map(goalCard)}</div>${gl.empty_note ? html`<span class="muted">${gl.empty_note}</span>` : ""}</section>`;
}

function tierSection(card) {
  const gl = card.goals || {};
  const others = (gl.others || []).filter((o) => !o.modelled);
  return html`<section class="section"><h2 class="raid-h2">The rest of the tier</h2>${gl.others_line ? html`<span class="muted">${gl.others_line}</span>` : ""}<div class="raid-tier">${others.map((o) => html`<div class="card"><span class="card-title">${o.name}</span><span class="muted">${o.line}</span></div>`)}</div></section>`;
}

function basis(goals, card) {
  const lines = [goals.basis, card.supply && card.supply.basis, card.goals && card.goals.basis, card.preraid && card.preraid.basis].filter(Boolean);
  return html`<details class="fold raid-basis"><summary>How this is counted</summary><div class="raid-lines">${lines.map((l) => html`<span class="small dim">${l}</span>`)}<span class="small dim">Seats come from /api/v2/raidteams. Open seats are shown as open, never filled in.</span></div></details>`;
}

// ---- the page --------------------------------------------------------------------

function summaryLine(card, teams, gates, raiders) {
  if (!teams) return card.headline;
  const total = (teams.seats || []).flat().length;
  const seated = seatedOf(teams).length;
  const ready = (card.raiders || []).filter((r) => r.ready).length;
  const short = gates.filter((g) => g.test)
    .map((g) => ({ g, n: gateCount(g, teams, raiders).fail }))
    .filter((x) => x.n > 0)
    .sort((a, b) => b.n - a.n)
    .slice(0, 3)
    .map((x) => x.g.noun);
  const readyText = ready ? ready + " of them are ready" : "none of them is ready yet";
  const why = short.length ? ": most fall short on " + (short.length > 1 ? short.slice(0, -1).join(", ") + " and " + short[short.length - 1] : short[0]) + ", in that order." : ".";
  return seated + " of " + total + " seats have a member, and " + readyText + why;
}

function header(ctx, line, seats) {
  const pick = GUILDS.map((g) => html`<a href="#/raid/mc/${g}"${g === ctx.params.guild ? raw(' aria-current="page"') : ""}>${cap(g)}</a>`);
  return html`<header class="page-head"><div class="raid-title"><h1>Molten Core</h1>${seats ? html`<span class="muted">${seats}</span>` : ""}<div class="seg raid-pick" role="group" aria-label="Guild">${pick}</div></div>${line ? html`<p class="summary">${line}</p>` : ""}</header>`;
}

function lineupSection(ctx, card, teamsRead, raiders, gates) {
  const wait = pendingRead(teamsRead, 2);
  if (wait) return html`<section class="section"><h2 class="raid-h2">The eight groups</h2>${wait}</section>`;
  const teams = teamsRead.data;
  const keys = gates.map((g) => g.key);
  const view = ctx.query.view === "gate" ? "gate" : "group";
  const picked = keys.includes(ctx.query.gate) && ctx.query.gate !== "seat" ? ctx.query.gate : "level";
  const gate = gates.find((g) => g.key === picked);
  const seated = seatedOf(teams).length;
  const total = (teams.seats || []).flat().length;
  const title = view === "group" ? "The eight groups" : gate.label + ", who falls short";
  const sub = view === "group" ? seated + " of " + total + " seated, " + (total - seated) + " open" : gate.rule;
  return html`${gateTable(ctx, gates, teams, raiders, view, picked)}<section class="section"><div class="raid-viewhead"><h2 class="raid-h2">${title}</h2><span class="dim">${sub}</span>${viewSwitch(ctx, view, picked)}</div>${view === "group" ? groupsView(ctx, card, teams, raiders, gates) : gateView(gate, teams, raiders)}</section>`;
}

export default {
  css: ["views/raid.css"],
  every: 60000,
  reads(ctx) {
    routed = [GOALS, TEAMS(ctx.params.guild), ...upgradeReads(ctx)];
    return routed;
  },
  title: (ctx) => "Molten Core, " + cap(ctx.params.guild),
  render(ctx) {
    const goalsRead = ctx.get(GOALS);
    const teamsRead = ctx.get(TEAMS(ctx.params.guild));
    const wait = pendingRead(goalsRead, 4);
    if (wait) return html`${header(ctx, "", "")}${wait}`;
    const card = guildCard(goalsRead.data, ctx.params.guild);
    if (!card) return html`${header(ctx, "", "")}${state("empty", "The raid read has no guild named " + cap(ctx.params.guild) + ".", goalsRead.data.line)}`;
    const teams = teamsRead.data;
    const raiders = new Map((card.raiders || []).map((r) => [r.name, r]));
    const gates = gateList(card);
    const seats = teams ? plural((teams.seats || []).flat().length, "seat") : "";
    return html`${header(ctx, summaryLine(card, teams, gates, raiders), seats)}
${headCard(card)}
${lineupSection(ctx, card, teamsRead, raiders, gates)}
<div class="raid-two">${blockersCard(card)}${attuneCard(card)}</div>
${raidersFold(card, teams)}
<div class="raid-two">${supplyCard(card)}${fireCard(card, teams)}</div>
${upgradesSection(ctx, card, teams)}
${consumablesSection(card)}
${tierSection(card)}
${basis(goalsRead.data, card)}`;
  },
  // The family's upgrade reads are known only once the raid read names the
  // family. When they were not among this route's reads, route again (same
  // hash, so the place is kept) and the reads list picks them up.
  after(main, ctx) {
    const want = upgradeReads(ctx);
    if (!want.some((p) => !routed.includes(p))) return;
    routed = routed.concat(want);
    window.setTimeout(() => window.dispatchEvent(new HashChangeEvent("hashchange")), 0);
  },
  thumb(ctx) {
    if (!ctx.isPhone) return null;
    const q = ctx.hash.indexOf("?");
    const keep = q < 0 ? "" : ctx.hash.slice(q);
    return { label: "Guild", items: GUILDS.map((g) => ({ label: cap(g), href: "#/raid/mc/" + g + keep, current: g === ctx.params.guild })) };
  },
};
