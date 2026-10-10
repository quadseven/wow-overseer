// The family board: one family's live buffs, meter, quest board, what wants
// to move between them, who answers who, and the leveling route. Every block
// is one existing read; a block whose read fails says so on its own and the
// rest still draw.

import { html, raw, ago, plural, notMeasured, state, skeletons, memberHref, classVar } from "../ui.js";
import * as D from "./now/data.js";

// The buffs the classic page counts as the family's own (the rest are listed
// as "other positive auras").
const FAMILY_BUFFS = new Set([
  "power word: fortitude", "prayer of fortitude", "divine spirit", "prayer of spirit",
  "shadow protection", "prayer of shadow protection", "arcane intellect", "dalaran intellect",
  "mark of the wild", "gift of the wild", "thorns", "blessing of might", "greater blessing of might",
  "blessing of wisdom", "greater blessing of wisdom", "blessing of kings", "greater blessing of kings",
  "blessing of light", "greater blessing of light", "blessing of sanctuary", "greater blessing of sanctuary",
  "blessing of salvation", "greater blessing of salvation", "battle shout", "commanding shout",
  "stamina", "well fed",
]);
const METERS = [["damage", "Damage"], ["healing", "Healing"], ["threat", "Threat"]];
const BOND_TONE = { COUNTING: "warn", EXEMPT: "accent", ALWAYS: "ok", STOPPED: "bad" };

const famKey = (ctx) => ctx.params.family.charAt(0).toUpperCase() + ctx.params.family.slice(1);
const q = (path, fam) => path + "?family=" + encodeURIComponent(fam);

function paths(fam) {
  return {
    family: q("/api/family", fam), agenda: D.agendaPath(fam), levelroute: q("/api/levelroute", fam),
    needs: q("/api/needs", fam), questlog: q("/api/questlog", fam),
    auras: "/api/auras", meter: "/api/meter", party: "/api/party-status",
  };
}

// What a block draws while its read has nothing: a skeleton, or why not.
function waiting(read, what) {
  if (read.data === undefined && !read.error) return skeletons(1);
  const why = read.data && read.data.error ? "The server says: " + read.data.error + "." : "The read did not answer.";
  return state("unmeasured", what + " not measured", why);
}

function auraName(a) {
  return (a.name || "Spell " + a.spell).replace(/\s+\(rank \d+\)$/i, "");
}

// ---- members -----------------------------------------------------------------
function memberStrip(ctx, p) {
  const fam = ctx.get(p.family), party = ctx.get(p.party);
  if (!D.ok(fam)) return waiting(fam, "Family");
  const codes = new Map(D.ok(party) ? (party.data.members || []).map((m) => [m.name, m.label || m.code]) : []);
  return html`<div class="fam-members">${(fam.data.members || []).map((m) => {
    const st = !m.present ? "offline" : m.condition === "dead" ? "dead" : m.combat ? "in combat" : m.condition === "ok" ? "alive" : m.condition || "";
    return html`<a class="fam-member" href="${memberHref(m.name)}"><span class="b" style="color:${classVar(m["class"])}">${m.name}</span><span class="dim small">${m.present ? "L" + m.level + " " + m["class"] : "not in the world"}</span><span class="small muted">${st}${codes.has(m.name) ? " | party: " + codes.get(m.name) : ""}</span></a>`;
  })}</div>`;
}

// ---- buffs --------------------------------------------------------------------
function buffRows(members) {
  const online = members.filter((m) => String(m.status).toLowerCase() === "online");
  const held = new Map();
  let other = 0;
  online.forEach((m) => {
    const seen = new Set();
    (m.auras || []).filter((a) => a && a.positive).forEach((a) => {
      const name = auraName(a);
      if (!FAMILY_BUFFS.has(name.toLowerCase())) { other += 1; return; }
      if (seen.has(name)) return;
      seen.add(name);
      held.set(name, (held.get(name) || 0) + 1);
    });
  });
  return { online, held, other };
}

function buffs(ctx, p, fam) {
  const read = ctx.get(p.auras);
  let body;
  if (!D.ok(read)) body = waiting(read, "Buffs");
  else {
    const members = (read.data.members || []).filter((m) => m.family === fam);
    const { online, held, other } = buffRows(members);
    const sampled = read.data.sampled_at ? ago(Date.now() / 1000 - read.data.sampled_at) : "not measured";
    if (!online.length) body = state("unmeasured", "Buffs not measured", "No member of the family answered the aura probe" + (members[0] && members[0].error ? ": " + members[0].error : "") + ".");
    else if (!held.size) body = html`<span class="muted">No family buffs seen on the ${plural(online.length, "member")} who answered.</span>`;
    else body = [...held.entries()].sort((a, b) => b[1] - a[1]).map(([name, n]) => html`<div class="buff"><i class="ph ph-sparkle" aria-hidden="true"></i><span class="grow">${name}</span><span class="num ${n === online.length ? "ok" : "warn"}">${n} of ${online.length}</span></div>`);
    body = html`${body}<span class="dim small">Sampled ${sampled}${other ? "; " + plural(other, "other positive aura") : ""}.</span>`;
  }
  return html`<div class="card fam-card"><span class="b">Live buffs</span>${body}</div>`;
}

// ---- meter --------------------------------------------------------------------
function meterValue(m, k) {
  if (k === "threat") return m.threat_pct >= 0 ? m.threat_pct : null;
  return Number(m[k]) || 0;
}

function meter(ctx, p, fam) {
  const read = ctx.get(p.meter);
  const k = METERS.some(([x]) => x === ctx.query.meter) ? ctx.query.meter : "damage";
  const base = "#/now/family/" + ctx.params.family;
  const tabs = html`<div class="seg meter-tabs">${METERS.map(([key, label]) => html`<a href="${base}${key === "damage" ? "" : "?meter=" + key}"${key === k ? raw(' aria-current="page"') : ""}>${label}</a>`)}</div>`;
  let line = "", body;
  const entry = D.ok(read) ? (read.data.families || []).find((f) => f.family === fam) : null;
  if (!D.ok(read)) body = waiting(read, "Meter");
  else if (!entry || entry.status !== "online") body = state("unmeasured", "Meter not measured", "The meter probe said: " + ((entry && entry.error) || "no answer") + ".");
  else if (!(entry.members || []).length) body = state("empty", "No fight recorded yet.");
  else {
    line = (entry.live ? "fighting" : "last fight") + ", " + entry.seconds + "s" + (entry.target ? " on " + entry.target : "");
    const rows = entry.members.map((m) => ({ m, v: meterValue(m, k) })).sort((a, b) => (b.v || 0) - (a.v || 0));
    const top = Math.max(1, ...rows.map((r) => r.v || 0));
    body = rows.map(({ m, v }) => html`<div class="mrow"><a href="${memberHref(m.name)}" class="member">${m.name}</a><span class="mbar"><span class="mfill m-${k}" style="width:${Math.round((100 * (v || 0)) / top)}%"></span></span><span class="num mval">${v === null ? notMeasured("none") : k === "threat" ? v + "%" : v.toLocaleString("en-US")}</span></div>`);
  }
  return html`<div class="card fam-card"><div class="spread"><span class="b">Damage, healing and threat</span><span class="dim small">${line}</span></div>${tabs}${body}</div>`;
}

// ---- quest board --------------------------------------------------------------------
const ROLE = {
  hand_in: ["ready to hand in", "has"], on: ["has it", "has"], done: ["turned it in", "done"],
  helping: ["helping, does not have it", "helping"],
};

function questRow(row, roster) {
  const people = new Map((row.people || []).map((x) => [x.name, x]));
  const obj = (row.objectives || []).map((o) => o.what + " " + o.have + "/" + o.need).join(", ");
  const who = roster.map((m) => {
    const x = people.get(m.name);
    const r = x ? ROLE[x.role] || ["has it", "has"] : ["does not have it", "none"];
    return html`<a class="qwho q-${r[1]}" href="${memberHref(m.name, "quests")}" title="${m.name}: ${r[0]}" aria-label="${m.name}: ${r[0]}" style="${r[1] === "none" || r[1] === "helping" ? "" : "color:" + classVar(m["class"])}">${m.name.slice(0, 2)}</a>`;
  });
  return html`<div class="qrow"><div class="qmain"><span class="b">${row.title} <span class="dim small">level ${row.level}</span></span><span class="muted small">${obj || (row.hand_in ? plural(row.hand_in, "member") + " ready to hand in" : "no objectives read")}</span></div><div class="qwhos">${who}</div></div>`;
}

function questBoard(ctx, p) {
  const read = ctx.get(p.questlog);
  if (!D.ok(read)) return html`<h2 class="kicker">Quest board</h2>${waiting(read, "Quest board")}`;
  const ql = read.data, rows = (ql.board && ql.board.rows) || [];
  const roster = ql.members || [];
  const n = (ql.board && ql.board.preview) || 12;
  const head = plural(ql.held || rows.length, "quest") + " held: " + (ql.shared || 0) + " shared, " + (ql.alone || 0) + " held alone, " + (ql.everyone || 0) + " by everyone.";
  const list = rows.length ? html`<div class="card rows">${rows.slice(0, n).map((r) => questRow(r, roster))}</div>${rows.length > n ? html`<details class="fold"><summary>Show ${rows.length - n} more</summary><div class="card rows">${rows.slice(n).map((r) => questRow(r, roster))}</div></details>` : ""}` : state("empty", "No quests held.");
  return html`<h2 class="kicker">Quest board</h2><span class="muted">${head}</span>${list}`;
}

// ---- moves and bonds ----------------------------------------------------------------
function moves(needs) {
  const mv = needs.moving || {};
  const rows = mv.rows || [];
  const body = rows.length ? html`<div class="card rows">${rows.map((r) => html`<div class="crow"><span class="row"><span class="b">${r.title}</span><span class="tag ${r.blocked ? "tag-bad" : "tag-warn"}">${r.word}</span></span><span class="muted">${r.said}</span>${r.refusal_line ? html`<span class="warn small">${r.refusal_line}</span>` : ""}</div>`)}</div>` : state("empty", "Nothing wants to move between them.");
  return html`<div class="fold-col"><h2 class="kicker">What wants to move</h2><span class="muted">${mv.headline || ""}</span>${body}${(mv.notes || []).map((n) => html`<span class="dim small">${n}</span>`)}<span class="dim small">${mv.rule || ""}</span></div>`;
}

function bonds(needs) {
  const an = needs.answering || {};
  const rows = an.rows || [];
  const body = rows.length ? html`<div class="card rows">${rows.map((r) => {
    const tone = BOND_TONE[r.word] || "neutral";
    return html`<div class="crow"><span class="row"><span class="b">${r.pair}</span><span class="tag bond-${tone}">${r.word}</span><span class="dim small">${r.progress}</span></span>${r.pct !== null && r.pct !== undefined ? html`<span class="bbar"><span class="bfill bond-${tone}" style="width:${r.pct}%"></span></span>` : ""}<span class="muted">${r.note}</span></div>`;
  })}</div>` : state("empty", "No answering pairs reported.");
  return html`<div class="fold-col"><h2 class="kicker">Who answers who</h2><span class="muted">${an.headline || ""}</span>${body}<span class="dim small">${an.rule || ""}</span></div>`;
}

function needsBlocks(ctx, p) {
  const read = ctx.get(p.needs);
  if (!D.ok(read)) return html`<div class="fold-col"><h2 class="kicker">What wants to move, who answers who</h2>${waiting(read, "Moves and bonds")}</div>`;
  return html`${moves(read.data)}${bonds(read.data)}`;
}

// ---- leveling route ----------------------------------------------------------------
function band(b, i) {
  const zones = (b.zones || []).map((z) => z.zone + (z.hub ? " (" + z.hub + ")" : "") + (z.away ? ", across the sea" : "")).join("; ");
  return html`<div class="card band${i === 0 ? " is-now" : ""}"><span class="b">Levels ${b.band}</span><span class="muted">${zones || "no zones"}</span><span class="dim small">Dungeons: ${(b.dungeons || []).join(", ") || "none in this band"}</span>${(b.milestones || []).map((m) => html`<span class="small accent">${m}</span>`)}</div>`;
}

function route(ctx, p) {
  const read = ctx.get(p.levelroute);
  if (!D.ok(read)) return html`<h2 class="kicker">Leveling route</h2>${waiting(read, "Leveling route")}`;
  const r = read.data;
  return html`<h2 class="kicker">Leveling route</h2>
<div class="card route"><span>${r.where || ""}</span><span class="muted">${r.queue || ""}</span><span class="b">${r.now || ""}</span><span class="muted">${r.next || ""}</span></div>
<div class="bands">${(r.route || []).map(band)}</div>`;
}

export default {
  css: ["views/now.css", "views/family.css"],
  reads: (ctx) => Object.values(paths(famKey(ctx))),
  every: 15000,
  title: (ctx) => famKey(ctx) + "'s family",
  render(ctx) {
    const fam = famKey(ctx);
    const p = paths(fam);
    const agenda = ctx.get(p.agenda);
    const lead = D.ok(agenda) ? [agenda.data.headline, agenda.data.queue && agenda.data.queue.line].filter(Boolean).join(". ").replace(/\.\./g, ".") : "";
    const pick = D.familyKeys().map((f) => html`<a href="#/now/family/${f.toLowerCase()}"${f === fam ? raw(' aria-current="page"') : ""}>${f}'s family</a>`);
    return html`<a class="back" href="#/now"><i class="ph ph-caret-left" aria-hidden="true"></i>Now</a>
<div class="head-row"><h1>Family board</h1><nav class="seg" aria-label="Family">${pick}</nav></div>
${lead ? html`<p class="lead">${lead}</p>` : D.ok(agenda) ? "" : html`<p class="lead">${notMeasured("The agenda is not measured.")}</p>`}
${memberStrip(ctx, p)}
<div class="fam-grid">${buffs(ctx, p, fam)}${meter(ctx, p, fam)}</div>
${questBoard(ctx, p)}
<div class="fam-grid">${needsBlocks(ctx, p)}</div>
${route(ctx, p)}`;
  },
};
