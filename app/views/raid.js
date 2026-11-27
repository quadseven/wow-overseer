// Raid: Molten Core, one guild at a time (#/raid/mc/<guild>).
//
// The page answers once, first, in a verdict card; everything after it
// is the working the answer came from. Every sentence, blocker, table
// cell and goal below the verdict is the server's (/api/raidgoals:
// raidready, raidsupply, raidgoals, raidrun, preraid; /api/v2/ragnaros
// for the road). The verdict card's own short lines are the page's,
// composed only from numbers the server reports and the server's own
// blocker texts, the same licence as the counts of who clears each
// readiness gate. The seats are the approved lineup (/api/v2/raidteams):
// an open seat is drawn open, never filled with a guess. Each family
// member's next upgrades come from /api/upgrades. The page owns layout
// and the tone a server tone is drawn in; a number the server does not
// report is "not measured".
//
// View state lives in the URL: ?view=group|gate&gate=<key>.

import { html, raw, item, member, memberHref, notMeasured, pendingRead, state, plural, classVar } from "../ui.js";
import { guildSlugs, guildName } from "../families.js";

const TEAMS = (g) => "/api/v2/raidteams?guild=" + encodeURIComponent(g);
const GOALS = "/api/raidgoals";
const ROAD = (g) => "/api/v2/ragnaros?guild=" + encodeURIComponent(g);
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
      key: "level", noun: "level", chip: "Level", label: min ? "Level " + min + "+" : "Level", tone: "bad",
      rule: min ? "the lowest level the instance's own access row lets in" : "the instance's lowest level was not read",
      test: (m) => (min && m.level != null ? m.level >= min : null),
      have: (m) => (m.level == null ? null : "L" + m.level),
      gap: (m) => min - m.level, need: (m) => plural(min - m.level, "level"),
    },
    {
      key: "attune", noun: "attunement", chip: "Attunement", label: "Attuned", tone: "warn", rule: "Attunement to the Core rewarded",
      test: (m) => m.attuned, have: () => "not attuned", gap: () => 1, need: () => "the quest",
    },
    {
      key: "fr", noun: "fire resistance", chip: "Fire resistance", label: "Fire resistance", tone: "warn", rule: "the role's target, from worn gear",
      test: (m, r) => (m.fire_resistance == null || !r ? null : m.fire_resistance >= (r.fire_target || 0)),
      have: (m, r) => m.fire_resistance + " of " + r.fire_target + " FR",
      gap: (m, r) => r.fire_target - m.fire_resistance, need: (m, r) => (r.fire_target - m.fire_resistance) + " more FR",
    },
    {
      key: "supply", noun: "supplies", chip: "Supplies", label: "Supplies carried", tone: "warn", rule: "the night's consumables for the role, in bags",
      test: (m, r) => (r ? r.supplies_carried >= r.supplies_wanted : null),
      have: (m, r) => r.supplies_carried + " of " + r.supplies_wanted + " supplies",
      gap: (m, r) => r.supplies_wanted - r.supplies_carried, need: (m, r) => (r.supplies_wanted - r.supplies_carried) + " more",
    },
    {
      key: "gear", noun: "pre-raid gear", chip: "Pre-raid gear", label: "Pre-raid gear", tone: "warn",
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

// Every gate a seated raider falls short of, and every gate no read
// measures for them, each in gate order: {fail: [gate], unread: [gate]}.
// A seat row shows all of them as chips, so a seat short on four gates
// never reads as one fix away.
function memberGates(gates, m, r) {
  const fail = [];
  const unread = [];
  for (const g of gates) {
    if (!g.test) continue;
    const ok = g.test(m, r);
    if (ok === false) fail.push(g);
    else if (ok == null) unread.push(g);
  }
  return { fail, unread };
}

// ---- pieces ----------------------------------------------------------------

function gateTable(ctx, gates, teams, raiders, view, picked) {
  const total = (teams.seats || []).flat().length;
  const seated = seatedOf(teams).length;
  const rows = gates.map((g) => {
    const c = gateCount(g, teams, raiders);
    const isSeat = g.key === "seat";
    // A member gate divides by the seated raiders and says so; the seat
    // gate itself counts filled and open against every approved seat.
    const denom = isSeat ? total : seated;
    const pct = denom ? Math.round((100 * c.pass) / denom) : 0;
    const t = denom && c.pass >= denom ? "ok" : c.pass === 0 ? "bad" : "warn";
    const on = view === "gate" ? picked === g.key : g.key === "seat";
    const href = hrefFor(ctx, g.key === "seat" ? { view: "group" } : { view: "gate", gate: g.key });
    const count = isSeat
      ? html`${c.pass} filled<span class="dim"> | ${c.fail} open</span>`
      : html`${c.pass} pass<span class="dim"> | ${c.fail} short${c.unread ? " | " + c.unread + " not measured" : ""} (of ${seated} seated)</span>`;
    return html`<a class="gate" href="${href}"${on ? raw(' aria-current="true"') : ""}><span class="gate-label">${g.label}<span class="gate-rule">${g.rule}</span></span><span class="gate-count ${t}">${count}</span><span class="gate-bar" aria-hidden="true"><span style="width:${pct}%" data-tone="${t}"></span></span></a>`;
  });
  return html`<div class="card raid-gates"><span class="card-title">Readiness gates</span><span class="muted">Who clears each bar. Pick one to see who falls short.</span><div class="gate-list">${rows}</div></div>`;
}

function viewSwitch(ctx, view, picked) {
  const items = [["group", "By group", { view: "group" }], ["gate", "By gate", { view: "gate", gate: picked }]];
  return html`<div class="seg" role="group" aria-label="Lineup view">${items.map(([k, label, q]) => html`<a href="${hrefFor(ctx, q)}"${view === k ? raw(' aria-current="page"') : ""}>${label}</a>`)}</div>`;
}

// The chips under a seat's name: every failing gate, then every
// unmeasured one, three named and the rest counted. No failing or
// unmeasured gate at all is the one "ready" chip.
function seatChips(gates, m, r) {
  const { fail, unread } = memberGates(gates, m, r);
  if (!fail.length && !unread.length) return html`<span class="gate-chip" data-tone="ok">ready</span>`;
  const shown = [
    ...fail.map((g) => ({ text: g.chip, tone: g.tone })),
    ...unread.map((g) => ({ text: g.chip + " not measured", tone: "dim" })),
  ];
  const chips = shown.slice(0, 3).map((c) => html`<span class="gate-chip" data-tone="${c.tone}">${c.text}</span>`);
  const more = shown.length > 3 ? html`<span class="gate-chip">${shown.length - 3} more</span>` : "";
  return html`${chips}${more}`;
}

function seatRow(ctx, seat, teams, raiders, gates) {
  if (!seat.name) {
    return html`<div class="seat open"><span class="seat-name"><i class="ph ph-circle-dashed" aria-hidden="true"></i>open seat</span><span class="seat-sub">${seat.class} ${ROLE_WORD[seat.seat] || ""}, approved as ${seat.approved}</span></div>`;
  }
  const m = teams.members[seat.name] || {};
  const renamed = seat.approved !== seat.name ? html`<span class="dim"> (to be ${seat.approved})</span>` : "";
  const aura = seat.fire_aura ? html`<i class="ph-fill ph-fire aura" aria-hidden="true" title="Fire resistance aura or totem for the group"></i><span class="sr-only">, carries the group's fire resistance aura</span>` : "";
  return html`<a class="seat" href="${memberHref(seat.name)}"><span class="seat-main"><span class="seat-name" style="color:${classVar(seat.class)}"><i class="${ROLE_ICON[seat.seat] || ROLE_ICON.dps}" aria-hidden="true" title="${ROLE_WORD[seat.seat] || ""}"></i>${seat.name}${renamed}${aura}</span><span class="seat-chips">${seatChips(gates, m, raiders.get(seat.name))}</span></span><span class="seat-sub">${m.level != null ? "L" + m.level : ""}</span></a>`;
}

// The project's seat target, named beside the split the server placed:
// the two differ today, and the page says both so the difference is
// visible rather than argued about elsewhere. No read carries the
// target, so it lives in this one constant; a deployment aiming at a
// different split changes it here.
const ROLE_TARGET_LINE = "Target split: 8 tanks, 11 healers, 21 damage.";

function roleLine(teams, raiders) {
  const placed = { tank: 0, healer: 0, dps: 0 };
  const ready = { tank: 0, healer: 0, dps: 0 };
  seatedOf(teams).forEach((s) => {
    const k = s.seat in placed ? s.seat : "dps";
    placed[k] += 1;
    const r = raiders.get(s.name);
    if (r && r.ready) ready[k] += 1;
  });
  const part = (k, word) => word + " " + placed[k] + " (" + ready[k] + " ready)";
  return "Placed: " + part("tank", "tanks") + ", " + part("healer", "healers") + ", " + part("dps", "damage") + ". " + ROLE_TARGET_LINE + " The placed split is the server's; the target is the project's.";
}

// One group's subtotal: how many of its seated raiders are ready, how
// many are short, and the gate the most of them fall short of.
function groupSubtotal(group, teams, raiders, gates) {
  const seated = group.filter((s) => s.name);
  let ready = 0;
  const fails = new Map();
  seated.forEach((s) => {
    const r = raiders.get(s.name);
    if (r && r.ready) ready += 1;
    memberGates(gates, teams.members[s.name] || {}, r).fail.forEach((g) => fails.set(g.noun, (fails.get(g.noun) || 0) + 1));
  });
  let worst = "";
  let worstN = 0;
  fails.forEach((n, noun) => {
    if (n > worstN) {
      worstN = n;
      worst = noun;
    }
  });
  return ready + " ready, " + (seated.length - ready) + " short" + (worst ? ", worst gap " + worst : "");
}

function groupsView(ctx, card, teams, raiders, gates) {
  const gaps = teams.gaps || {};
  const short = (gaps.tanks || 0) + (gaps.healers || 0) + (gaps.damage || 0);
  const gapLine = short
    ? "Short " + plural(gaps.tanks || 0, "tank") + ", " + plural(gaps.healers || 0, "healer") + " and " + (gaps.damage || 0) + " damage. Open seats stay open; they are never filled with characters the guild does not have."
    : "Every approved seat has its member. Open seats would stay open; they are never filled with characters the guild does not have.";
  const cards = (teams.seats || []).map((group, i) => {
    return html`<div class="card raid-group"><span class="group-label">Group ${i + 1}${i === 0 ? " | the family" : ""}</span><span class="group-sub">${groupSubtotal(group, teams, raiders, gates)}</span>${group.map((s) => seatRow(ctx, s, teams, raiders, gates))}</div>`;
  });
  return html`<span class="role-line">${roleLine(teams, raiders)}</span><span class="${short ? "warn" : "muted"}">${gapLine}</span>${card.gap_line ? html`<span class="muted">${card.gap_line}</span>` : ""}<div class="raid-groups">${cards}</div>`;
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

// The attunement card opens with its verdict, counted over the whole
// raid from the road's attunement milestone (the card's own member list
// covers the family only). At none attuned the verdict says what that
// means before a single name is drawn.
function attuneVerdict(card, road) {
  const e = road && (road.milestones || []).find((m) => m.key === "E");
  let have = null;
  let want = 0;
  if (e && e.measured) {
    have = e.have;
    want = e.want;
  } else {
    const members = (card.attunement && card.attunement.members) || [];
    if (members.length) {
      have = members.filter((m) => m.status === "attuned").length;
      want = members.length;
    }
  }
  if (have == null) return "";
  return have + " of " + want + " attuned." + (have === 0 ? " Nobody can zone in." : "");
}

function attuneCard(card, road) {
  const a = card.attunement || {};
  const verdict = attuneVerdict(card, road);
  return html`<div class="card raid-block"><span class="card-title">Attunement to the Core</span>${verdict ? html`<span class="attune-verdict">${verdict}</span>` : ""}${a.line ? html`<span class="muted">${a.line}</span>` : ""}<div class="row">${(a.members || []).map((m) => html`<span class="tag ${m.status === "attuned" ? "tag-outline" : "tag-neutral"}">${m.line}</span>`)}</div><ol class="raid-steps">${(a.steps || []).map((s) => html`<li>${s}</li>`)}</ol>${a.unproven ? html`<span class="small dim">${a.unproven}</span>` : ""}${a.bots ? html`<span class="small dim">${a.bots}</span>` : ""}<span class="card-title raid-sub">The raid run</span>${card.run_line ? html`<span class="muted">${card.run_line}</span>` : ""}${card.clearing_line ? html`<span class="small dim">${card.clearing_line}</span>` : ""}${card.first_kill && card.first_kill.line ? html`<span class="small dim">${card.first_kill.line}</span>` : ""}${card.healer_levels && card.healer_levels.line ? html`<span class="small dim">${card.healer_levels.line}</span>` : ""}${card.healer_levels && card.healer_levels.projection ? html`<span class="small dim">${card.healer_levels.projection.line}</span>` : ""}</div>`;
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

function herbShortfall(hs) {
  if (!hs || !(hs.herbs || []).length) return "";
  return html`<details class="fold"><summary>${hs.line || "Herb shortfall for the night (" + hs.herbs.length + ")"}</summary><div class="raid-lines">${hs.herbs.map((r) => html`<span class="small dim">${itemLine(r.entry, r.name, r.line)}</span>`)}${hs.lotus_note ? html`<span class="small dim">${hs.lotus_note}</span>` : ""}</div></details>`;
}

// The detail zone below the groups: one closed fold per card, its
// summary carrying the card's headline line so nothing below the fold
// is a surprise when opened.
function detailFold(title, line, body) {
  return html`<details class="card raid-fold"><summary><span class="fold-body"><span class="card-title">${title}</span>${line ? html`<span class="muted">${line}</span>` : ""}</span></summary><div class="fold-detail">${body}</div></details>`;
}

function supplyCard(card) {
  const s = card.supply;
  if (!s) return detailFold("Supply for a night in the Core", "", notMeasured());
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
  const top = (s.top_recipes || []).length
    ? html`<details class="fold"><summary>TOP raid recipes (${s.top_recipes.filter((r) => r.acquired).length} of ${s.top_recipes.length} acquired)</summary><div class="raid-lines">${s.top_recipes.map((r) => html`<span class="${r.acquired ? "ok" : "warn"}">${r.line}</span>`)}</div></details>`
    : "";
  const seatCell = (r, i) => {
    const text = (r.cells || [])[i];
    if (i === 0) return text;
    if (i === (r.cells || []).length - 1) return text;
    if (i === (r.cells || []).length - 2) return html`<span class="num ${r.short ? "warn" : ""}">${text}</span>`;
    return text;
  };
  const reagentsFold = (s.seat_reagents || []).length
    ? html`<details class="fold"><summary>Group-buff & portal reagents (${s.seat_reagents.filter((r) => r.short).length} short)</summary>${table(s.reagent_columns || [], s.seat_reagents, seatCell)}</details>`
    : "";
  const drinkFold = (s.seat_drink || []).length
    ? html`<details class="fold"><summary>Drink per mana seat (${s.seat_drink.filter((d) => d.short).length} short)</summary>${table(s.drink_columns || [], s.seat_drink, seatCell)}</details>`
    : "";
  return detailFold("Supply for a night in the Core", s.line || "", html`${s.budget_line ? html`<span class="small dim">${s.budget_line}</span>` : ""}${(s.pace || []).map((p) => html`<span class="small dim">${p.line}</span>`)}${s.level_60_line ? html`<span class="small dim">${s.level_60_line}</span>` : ""}${(s.unobtainable || []).map((u) => html`<span class="small warn">${u}</span>`)}${top}${table(cols, s.supplies || [], cell)}${reagentsFold}${drinkFold}${herbShortfall(s.herb_shortfall)}`);
}

function fireCard(card, teams) {
  const s = card.supply;
  if (!s) return detailFold("Fire resistance, tanks first", "", notMeasured());
  const cls = (n) => ((teams && teams.members && teams.members[n]) || {}).class;
  const cols = s.fire_columns || [];
  const shortAt = cols.indexOf("short") >= 0 ? cols.indexOf("short") : cols.length - 1;
  const cell = (r, i) => {
    const text = (r.cells || [])[i];
    if (i === 0) return member({ name: text, cls: cls(text) });
    if (i === shortAt) return html`<span class="num ${r.short ? "warn" : "ok"}">${text}</span>`;
    return i >= 2 && i < shortAt ? html`<span class="num">${text}</span>` : text;
  };
  const fireRows = s.fire || [];
  const under = fireRows.filter((r) => r.short).length;
  const head = fireRows.length ? under + " of " + plural(fireRows.length, "raider") + " under their fire target" : "";
  return detailFold("Fire resistance, tanks first", head, html`${table(cols, fireRows, cell)}${s.fire_line ? html`<span class="small dim">${s.fire_line}</span>` : ""}`);
}

// ---- next upgrades -----------------------------------------------------------

function whereText(where) {
  return (where || []).map((w) => w.label).filter(Boolean).join("; ");
}

function upgradesFromRead(name, read, teams) {
  const cls = ((teams && teams.members && teams.members[name]) || {}).class;
  const head = (line) => html`<summary><span class="fold-body"><span>${foldName(name, cls)} <span class="muted">${line}</span></span></span></summary>`;
  if (read.data === undefined) {
    return html`<details class="card raid-fold">${head(read.error ? "upgrades not measured" : "reading upgrades")}<a class="raid-more" href="${memberHref(name, "upgrades")}">All slots for ${name}</a></details>`;
  }
  const d = read.data;
  const rows = (d.slots || []).filter((s) => s.next).sort((a, b) => (b.next.gain || 0) - (a.next.gain || 0)).slice(0, 5);
  const list = rows.length
    ? rows.map((s) => html`<div class="raid-up-row"><span class="dim">${s.label}</span><span>${item({ entry: s.next.entry, name: s.next.name })}</span><span class="muted">${whereText(s.next.where) || notMeasured()}</span><span class="num ok">+${Math.round(s.next.gain)}</span></div>`)
    : html`<span class="muted">No listed piece beats what is worn.</span>`;
  return html`<details class="card raid-fold">${head((d.ready && d.ready.line) || "")}<div class="raid-up-rows">${list}</div><a class="raid-more" href="${memberHref(name, "upgrades")}">All ${(d.slots || []).length} slots for ${name}</a></details>`;
}

function preraidMember(m, columns, teams) {
  const cls = ((teams && teams.members && teams.members[m.name]) || {}).class;
  const cell = (r, i) => {
    const text = r.cells[i];
    const it = (r.items || [])[i];
    if (it && text.startsWith(it.name)) return html`${item({ entry: it.entry, name: it.name, quality: it.quality })}${text.slice(it.name.length)}`;
    return text;
  };
  return html`<details class="card raid-fold"><summary><span class="fold-body"><span>${foldName(m.name, cls)} <span class="muted">${m.line}</span></span></span></summary>${table(columns, m.rows || [], cell)}<a class="raid-more" href="${memberHref(m.name, "upgrades")}">All slots for ${m.name}</a></details>`;
}

function upgradesSection(ctx, card, teams) {
  const pre = card.preraid || {};
  const members = pre.members || [];
  const body = members.length
    ? members.map((m) => preraidMember(m, pre.columns || [], teams))
    : familyNames(card).map((n) => upgradesFromRead(n, ctx.get(UPS(n)), teams));
  const notes = [...(pre.runs || []), ...(pre.progress || []), ...(pre.closed || [])];
  const line = pre.line ? pre.line + (members.length ? "" : " Until then, each member's next upgrades from the gear lists:") : "";
  return detailFold("Next upgrades and where they drop", line, html`<div class="raid-stack">${body}</div>${notes.map((n) => html`<span class="small dim">${n}</span>`)}`);
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
  const line = gl.line ? gl.line + (gl.roster_line ? ", " + gl.roster_line : "") + "." : "";
  return detailFold("Consumables, per guild", line, html`${gl.order ? html`<span class="small dim">${gl.order}</span>` : ""}<div class="raid-stack">${(gl.goals || []).map(goalCard)}</div>${gl.empty_note ? html`<span class="muted">${gl.empty_note}</span>` : ""}`);
}

function tierSection(card) {
  const gl = card.goals || {};
  const others = (gl.others || []).filter((o) => !o.modelled);
  return detailFold("The rest of the tier", gl.others_line || "", html`<div class="raid-tier">${others.map((o) => html`<div class="card"><span class="card-title">${o.name}</span><span class="muted">${o.line}</span></div>`)}</div>`);
}

function basis(goals, card) {
  const lines = [goals.basis, card.supply && card.supply.basis, card.goals && card.goals.basis, card.preraid && card.preraid.basis].filter(Boolean);
  return html`<details class="fold raid-basis"><summary>How this is counted</summary><div class="raid-lines">${lines.map((l) => html`<span class="small dim">${l}</span>`)}<span class="small dim">Seats come from /api/v2/raidteams. Open seats are shown as open, never filled in.</span></div></details>`;
}

// ---- the verdict and the road to Ragnaros --------------------------------------
//
// The page answers once, first: a verdict card built from the server
// total (/api/v2/ragnaros), the seats (/api/v2/raidteams) and the ready
// flags (/api/raidgoals). Below it the road card groups the eight goal
// checkpoints under plain subheads and carries the one blocker list,
// sorted by seats short, that the whole page shares. A milestone the
// server could not measure says so with its reason; it is never drawn
// as zero.

function roadTone(m) {
  if (m.percent == null) return "";
  return m.percent >= 100 ? "ok" : m.percent === 0 ? "bad" : "warn";
}

function milestonesByKey(d) {
  return Object.fromEntries((d.milestones || []).map((m) => [m.key, m]));
}

// Which gate view a road blocker drills into, by its server key first
// and its milestone second: one decision, two lookup tables. A blocker
// with no gate view (dungeon clears, coverage) names its next step in
// words instead of linking.
const BLOCKER_GATE = { unattuned: "attune", supplies: "supply", "fire-resistance": "fr", "level-60": "level", "level-40": "level", "class-quest": "level" };
const MILESTONE_GATE = { A: "level", B: "level", C: "level", E: "attune", F: "supply" };

function blockerNext(ctx, b, gates, inRoad) {
  const key = BLOCKER_GATE[b.key] || MILESTONE_GATE[b.milestone] || null;
  if (!key) return inRoad ? "" : html`<span class="dim">Next: tracked on the road below</span>`;
  const g = (gates || []).find((x) => x.key === key);
  const what = b.key === "class-quest" ? "who is short on the road to 40" : "who is short on " + (g ? g.noun : key);
  return html`<a class="blocker-next" href="${hrefFor(ctx, { view: "gate", gate: key })}">Next: ${what}</a>`;
}

// The one blocker list, most seats first. The server sends it sorted;
// the sort is repeated here so the page's own order does not depend on
// the read having kept that promise.
function sortedBlockers(d) {
  return [...(d.blockers || [])].sort((x, y) => (y.seats_short || 0) - (x.seats_short || 0));
}

function verdictBlocker(ctx, b, gates) {
  return html`<div class="verdict-blocker"><span>${b.text} · ${plural(b.seats_short, "seat")} short</span>${blockerNext(ctx, b, gates)}</div>`;
}

// The one answer, first: can this guild raid yet, the biggest reason it
// cannot, how far along the road it is with the counting rule in normal
// text, four figures, and the top three blockers with next actions. The
// placement tiles the headline card used to draw are gone: placed is
// not ready, and a green tile above a gate at zero said otherwise.
function verdictCard(ctx, card, teams, raiders, gates, roadRead) {
  const wait = pendingRead(roadRead, 2);
  if (wait) return html`<section class="card raid-verdict"><span class="card-title">Road to Ragnaros</span>${wait}</section>`;
  const d = roadRead.data;
  const name = guildName(ctx.params.guild) || cap(ctx.params.guild);
  if (!d || !d.milestones) {
    return html`<section class="card raid-verdict"><span class="verdict-line">${card.headline}</span>${card.roster_line ? html`<span class="muted">${card.roster_line}</span>` : ""}${card.gear_line ? html`<span class="muted">${card.gear_line}</span>` : ""}</section>`;
  }
  const byKey = milestonesByKey(d);
  const total = (teams ? (teams.seats || []).flat().length : 0) || (byKey.A && byKey.A.want) || (card.raiders || []).length;
  const seated = teams ? seatedOf(teams).length : null;
  const ready = (card.raiders || []).filter((r) => r.ready).length;
  const canRaid = total > 0 && seated === total && ready >= total;
  const blockers = sortedBlockers(d);
  const top = blockers[0];
  const pct = d.total.percent;
  const bar = pct == null ? "" : html`<span class="gate-bar" aria-hidden="true"><span style="width:${pct}%" data-tone="${pct >= 100 ? "ok" : ""}"></span></span>`;
  const fig = (value, label) => html`<div class="verdict-fig"><span class="v">${value}</span><span class="k">${label}</span></div>`;
  const figVal = (m) => (m && m.measured ? m.have + " of " + m.want : notMeasured());
  const top3 = blockers.slice(0, 3);
  return html`<section class="card raid-verdict"><span class="verdict-line">${canRaid ? name + " can raid" : name + " cannot raid yet"}</span>${!canRaid && top ? html`<span class="verdict-reason">Biggest reason: ${top.text}.</span>` : ""}<div class="road-total"><span>${pct == null ? notMeasured() : html`<span class="road-total-n">${pct}%</span>`}<span class="muted"> on the road to Ragnaros</span></span>${bar}</div><span class="verdict-how">${d.total.how}</span><div class="verdict-figs">${fig(seated == null ? notMeasured() : seated + " of " + total, "Seats placed")}${fig(figVal(byKey.C), "At level 60")}${fig(figVal(byKey.E), "Attuned")}${fig(ready + " of " + total, "Ready tonight")}</div>${top3.length ? html`<div class="verdict-blockers">${top3.map((b) => verdictBlocker(ctx, b, gates))}</div>` : ""}</section>`;
}

function roadRow(m, counted, attempts) {
  const key = html`<span class="road-key">${m.key}</span>`;
  const tag = m.unit !== "kill" && counted && !counted.includes(m.key) ? html` <span class="tag tag-neutral">not in the total</span>` : "";
  if (m.unit === "kill") {
    const text = !m.measured ? notMeasured() : m.have ? "fallen" : attempts && attempts.entered ? "not yet" : "Not attempted yet";
    return html`<div class="road-row"><span class="road-label">${key} ${m.label}</span><span class="road-count ${m.have ? "ok" : ""}">${text}</span></div>`;
  }
  if (!m.measured) {
    return html`<div class="road-row"><span class="road-label">${key} ${m.label}${tag}<span class="gate-rule">${m.reason || ""}</span></span><span class="road-count">${notMeasured()}</span></div>`;
  }
  const t = roadTone(m);
  const unread = m.unread ? html`<span class="dim"> | ${m.unread} not measured</span>` : "";
  return html`<div class="road-row"><span class="road-label">${key} ${m.label}${tag}<span class="gate-rule">${m.rule}${m.note ? ". " + m.note : ""}</span></span><span class="road-count ${t}">${m.have} of ${m.want} ${m.unit}${unread}</span><span class="gate-bar" aria-hidden="true"><span style="width:${m.percent}%" data-tone="${t}"></span></span></div>`;
}

function roadBlocker(ctx, b, milestones, gates) {
  const m = milestones.find((x) => x.key === b.milestone);
  const names = (b.names || []).length ? html`<span class="dim"> ${b.names.join(", ")}${b.seats_short > b.names.length ? " and " + (b.seats_short - b.names.length) + " more" : ""}</span>` : "";
  return html`<div class="road-blocker"><span><span class="road-key">${b.milestone}</span> ${b.text}${names} ${blockerNext(ctx, b, gates, true)}</span><span class="${roadTone(m || {}) || "warn"}">${plural(b.seats_short, "seat")} short</span></div>`;
}

// The milestones in their three plain groups, the attempt as an outcome
// row of its own, and the one blocker list the page shares (the verdict
// card's top three are this list's head, not a second list).
const ROAD_GROUPS = [
  ["Getting to 60", ["A", "B", "C"]],
  ["Getting in", ["D", "E"]],
  ["Ready for the night", ["F", "G"]],
];

function roadCard(ctx, read, gates) {
  const wait = pendingRead(read, 2);
  if (wait) return html`<section class="card raid-road"><span class="card-title">The road to Ragnaros</span>${wait}</section>`;
  const d = read.data;
  if (!d || !d.milestones) return "";
  const byKey = milestonesByKey(d);
  // Null when the read does not name its counted set: then no milestone
  // is tagged either way, rather than every one drawing the tag.
  const counted = d.total && Array.isArray(d.total.counted) ? d.total.counted : null;
  const a = d.attempts || {};
  const best = a.best ? a.best.bosses_done + (a.best.bosses_total ? " of " + a.best.bosses_total : "") + " bosses" : "no boss yet";
  const attempts = !a.measured
    ? html`Attempts: ${notMeasured()}.`
    : a.entered
      ? html`Ragnaros attempts: ${plural(a.entered, "run")} went in, ${plural(a.wiped, "wipe")}, best ${best}.`
      : "No Molten Core attempt yet.";
  const sixty = d.projected_60 ? " Level 60 for the 30th seat is projected for " + d.projected_60 + "." : "";
  const groups = ROAD_GROUPS.map(([head, keys]) => html`<p class="road-group-head">${head}</p><div class="road-rows">${keys.map((k) => (byKey[k] ? roadRow(byKey[k], counted, a) : ""))}</div>`);
  const sorted = sortedBlockers(d);
  const blockers = sorted.length
    ? html`<div class="road-blockers">${sorted.map((b) => roadBlocker(ctx, b, d.milestones, gates))}</div>`
    : html`<span class="muted">No measured blocker.</span>`;
  return html`<section class="card raid-road"><span class="card-title">The road to Ragnaros</span>${groups}<p class="road-group-head">The attempt</p><div class="road-rows">${byKey.H ? roadRow(byKey.H, counted, a) : ""}</div><span class="muted">${attempts}${sixty}</span><span class="card-title">Blockers, most seats first</span>${blockers}</section>`;
}

// ---- the page --------------------------------------------------------------------

function header(ctx, line, seats) {
  const pick = guildSlugs().map((g) => html`<a href="#/raid/mc/${g}"${g === ctx.params.guild ? raw(' aria-current="page"') : ""}>${guildName(g)}</a>`);
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
    routed = [GOALS, TEAMS(ctx.params.guild), ROAD(ctx.params.guild), ...upgradeReads(ctx)];
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
    const roadRead = ctx.get(ROAD(ctx.params.guild));
    const seats = teams ? plural((teams.seats || []).flat().length, "seat") : "";
    return html`${header(ctx, "", seats)}
${verdictCard(ctx, card, teams, raiders, gates, roadRead)}
${roadCard(ctx, roadRead, gates)}
${card.encounter_line ? html`<section class="card raid-block"><h2 class="raid-h2">Encounter capabilities</h2><p class="muted">${card.encounter_line}</p></section>` : ""}
${lineupSection(ctx, card, teamsRead, raiders, gates)}
${attuneCard(card, roadRead.data)}
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
    return { label: "Guild", items: guildSlugs().map((g) => ({ label: guildName(g), href: "#/raid/mc/" + g + keep, current: g === ctx.params.guild })) };
  },
};

// A name in a fold's summary: the member's class colour without a link,
// because a link inside a <summary> is a control inside a control. The fold
// body links to the member.
function foldName(name, cls) {
  return html`<span class="member" style="color:${classVar(cls)}">${name}</span>`;
}
