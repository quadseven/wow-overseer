// Members: every member of both family guilds, stuck first.
//
// Reads /api/v2/roster (who, where, what each is doing, stuck and ghost
// state), /api/guildgear (item level) and each guild's /api/v2/series (XP per
// hour over the last 24 hours, per member). The filter text, the chips, the
// level range and the sort live in the URL query (#/members?stuck=1&q=og),
// written with replaceState so typing never loses the caret; a poll redraw
// reads them back from the address bar.

import { html, raw, notMeasured, pendingRead, state, duration, classVar } from "../ui.js";
import { liveQuery, setQuery, gearRows, stateLabel, memberLink, sectionTabs, head, flipSort, sortHead } from "./_members.js";
import { stateOf, stuckFor } from "../models/roster.js";
import { guilds, guildSlugs } from "../families.js";
import { charButton, notice as watchNotice, bind as bindWatch, CSS as WATCH_CSS, READ as WATCH_READ, OPERATOR as WATCH_OPERATOR } from "./_spectate.js";

// One series read per family guild, as the realm reports them.
const series = () => guildSlugs().map((g) => "/api/v2/series?guild=" + g);
const reads = () => ["/api/v2/roster", "/api/guildgear", WATCH_READ, WATCH_OPERATOR, ...series()];

const SORTS = [["stuck", "Stuck longest"], ["level", "Level, high first"], ["ilvl", "Item level"], ["xp", "XP per hour"], ["name", "Name"]];
// Each sort's first direction. `dir` in the query (asc or desc) reverses it.
const FIRST = { stuck: "desc", level: "desc", ilvl: "desc", xp: "desc", name: "asc" };

// name -> {xp_per_hour_24h, xp_hours_measured} from every guild's series read.
function xpRates(get) {
  const out = new Map();
  series().forEach((path) => {
    const d = get(path).data;
    Object.entries((d && d.by_member) || {}).forEach(([name, r]) => out.set(name, r));
  });
  return out;
}

function xpValue(r) { return r && r.xp_per_hour_24h !== null && r.xp_per_hour_24h !== undefined ? r.xp_per_hour_24h : null; }

function xpText(r) { const v = xpValue(r); return v === null ? notMeasured() : v.toLocaleString("en-US"); }

function filters(q) {
  const sort = SORTS.some((s) => s[0] === q.sort) ? q.sort : "stuck";
  const lvl = /^(\d+)-(\d+)$/.exec(q.lvl || "");
  return {
    stuck: !!q.stuck, ghost: !!q.ghost, family: !!q.family, gear: !!q.gear,
    guild: (q.guild || "").toLowerCase(), text: (q.q || "").trim().toLowerCase(),
    lvl: lvl ? [Number(lvl[1]), Number(lvl[2])] : null,
    sort, dir: q.dir === "asc" || q.dir === "desc" ? q.dir : FIRST[sort],
  };
}

// A member the gear read flags: the read's own words for a gear problem
// (no weapon, too many empty slots), printed on the card as badges.
function flagged(g) { return !!g && (g.flags || []).length > 0; }

function keep(m, f, gear) {
  if (f.stuck && !m.stuck) return false;
  if (f.ghost && stateOf(m) !== "ghost") return false;
  if (f.family && !m.family) return false;
  if (f.gear && !flagged(gear && gear.get(m.name))) return false;
  if (f.guild && (m.guild || "").toLowerCase() !== f.guild) return false;
  if (f.lvl && (m.level < f.lvl[0] || m.level > f.lvl[1])) return false;
  if (f.text && !(m.name + " " + m.class + " " + m.zone + " " + m.guild).toLowerCase().includes(f.text)) return false;
  return true;
}

// Each key compares low to high; "desc" turns it round. Ties go by name, A to Z.
function sorter(sort, dir, ilvl, xp) {
  const il = (m) => { const g = ilvl.get(m.name); return g ? g.avg_item_level : -1; };
  const rate = (m) => { const v = xpValue(xp.get(m.name)); return v === null ? -1 : v; };
  const waited = (m) => (m.stuck ? (m.since === null || m.since === undefined ? 0 : Number.MAX_SAFE_INTEGER - m.since) : -1);
  const ghost = (m) => Number(stateOf(m) === "ghost");
  let by = (a, b) => (a.stuck - b.stuck) || (waited(a) - waited(b)) || (ghost(a) - ghost(b)) || a.level - b.level;
  if (sort === "level") by = (a, b) => a.level - b.level;
  else if (sort === "ilvl") by = (a, b) => il(a) - il(b);
  else if (sort === "xp") by = (a, b) => rate(a) - rate(b);
  else if (sort === "name") by = (a, b) => a.name.localeCompare(b.name);
  const d = dir === "asc" ? 1 : -1;
  return (a, b) => d * by(a, b) || a.name.localeCompare(b.name);
}

function ilvlText(g) { return g ? String(Math.round(g.avg_item_level)) : notMeasured(); }

// How far below its own level a worn slot has to be before the card calls
// it weak: the server's own gap (the armory's WEAKEST_FLAG), unweighted,
// because the gear row carries no per-slot weights.
const WEAK_GAP = 20;

// The gear problems on a member's card, from the gear read already fetched:
// the read's flags in its own words, then the weakest slot when it is far
// behind the member's level. No problem, no badge row.
function badges(m, g) {
  if (!g) return "";
  const out = (g.flags || []).map((f) => f.charAt(0).toUpperCase() + f.slice(1));
  const w = g.weakest;
  if (w && m.level - w.item_level >= WEAK_GAP) out.push("Weakest: " + w.slot + ", ilvl " + w.item_level);
  return out.length ? html`<span class="ro-badges">${out.map((b) => html`<span class="tag tag-warn">${b}</span>`)}</span>` : "";
}

function cards(rows, ilvl, at, cam, hideBlocker = false) {
  return html`<div class="ro-cards">${rows.map((m) => html`<div class="card ro-card stretch-card"><a class="stretch-link ro-link" href="${"#/m/" + encodeURIComponent(m.name)}"><span class="row ro-top"><span class="mname" style="color:${classVar(m.class)}">${m.name}</span>${stateLabel(m, at)}</span><span class="ro-meta">L${m.level} ${m.class} \u00b7 ${m.guild || "no guild"} \u00b7 ${m.zone || "zone not measured"}</span><span>${m.step || notMeasured("step not measured")}</span>${badges(m, ilvl.get(m.name))}${!hideBlocker && m.stuck && m.blocker ? html`<span class="muted ro-blocker">${m.blocker}</span>` : ""}</a>${charButton(m.name, cam.sp, cam.op)}</div>`)}</div>`;
}

const HEADS = [["Watch"], ["Name", "name"], ["Lvl", "level"], ["Class"], ["Guild"], ["iLvl", "ilvl"], ["XP/h", "xp"], ["Current step"], ["Blocker"], ["Stuck for", "stuck"]];

function table(rows, ilvl, xp, at, f, cam, groups = null) {
  const cur = { key: f.sort, dir: f.dir };
  const th = HEADS.map(([label, key]) => (key ? sortHead(label, key, cur, "data-sort") : html`<th scope="col">${label}</th>`));
  const tr = (m, grouped) => {
    const d = stuckFor(m, at);
    const k = stateOf(m);
    const tail = m.stuck ? (d ? html`<span class="warn">${d}</span>` : html`<span class="dim">since not measured</span>`) : k === "ghost" ? html`<span class="bad">${m.life === "dead" ? "dead" : "ghost"}</span>` : "";
    return html`<tr><td>${charButton(m.name, cam.sp, cam.op)}</td><td>${memberLink(m)}</td><td class="num">${m.level}</td><td>${m.class}</td><td>${m.guild}</td><td class="num">${ilvlText(ilvl.get(m.name))}</td><td class="num">${xpText(xp.get(m.name))}</td><td>${m.step || notMeasured()}</td><td class="muted">${grouped ? "" : m.blocker}</td><td>${tail}</td></tr>`;
  };
  const bodyRows = groups
    ? groups.flatMap((g) => [html`<tr class="ro-famrow"><td colspan="${HEADS.length}">${g.head}</td></tr>`, ...g.members.map((m) => tr(m, true))])
    : rows.map((m) => tr(m, false));
  return html`<div class="card ro-table"><table class="table"><thead><tr>${th}</tr></thead><tbody>${bodyRows}</tbody></table></div>`;
}

// The stuck list grouped by family, in the order the sorted list first
// meets each family. A member with no family groups under no key.
function groupByFamily(list) {
  const out = [];
  const byKey = new Map();
  list.forEach((m) => {
    const key = m.family || "";
    if (!byKey.has(key)) { const g = { key, members: [] }; byKey.set(key, g); out.push(g); }
    byKey.get(key).members.push(m);
  });
  return out;
}

// A family header: the family, how many of its members are stuck, how long
// the family has been stalled when the roster's stalled list knows it, and
// the blocker the family shares, stated here once instead of on every card.
// The stalled list is the roster's own word for the shared blocker; when it
// has no entry, the blocker counts as shared only if every member states
// the same one.
function familyHead(roster, group) {
  const stalled = group.key ? (roster.stalled_families || []).find((s) => s.leader === group.key) : null;
  let blocker = stalled && stalled.blocker ? stalled.blocker : "";
  if (!blocker) {
    const first = group.members[0] && group.members[0].blocker;
    if (first && group.members.every((m) => m.blocker === first)) blocker = first;
  }
  const waited = stalled && stalled.since !== null && stalled.since !== undefined ? duration(roster.checked_at - stalled.since) : null;
  const name = group.key ? group.key + "'s family" : "Not in a family";
  return html`<span class="ro-famname">${name}</span> <span class="dim">${group.members.length} stuck</span>${waited ? html` <span class="tag tag-warn">Stalled ${waited}</span>` : ""}${blocker ? html`<span class="ro-famblock">Shared blocker, stated once: ${blocker}</span>` : ""}`;
}

function body(roster, gg, xp, q, cam, f = filters(q), rows = null) {
  const ilvl = gearRows(gg);
  const all = roster.members || [];
  const list = (rows || all.filter((m) => keep(m, f, ilvl))).slice().sort(sorter(f.sort, f.dir, ilvl, xp));
  if (!list.length) {
    return html`${state("empty", "No members match", "No member fits every filter you have on. Nothing is hidden by the server.")}<div><button type="button" class="btn btn-ghost" data-clear>Clear filters</button></div>`;
  }
  if (!f.stuck) {
    return html`${cards(list, ilvl, roster.checked_at, cam)}${table(list, ilvl, xp, roster.checked_at, f, cam)}`;
  }
  const groups = groupByFamily(list);
  groups.forEach((g) => { g.head = familyHead(roster, g); });
  return html`${groups.map((g) => html`<div class="ro-famhead">${g.head}</div>${cards(g.members, ilvl, roster.checked_at, cam, true)}`)}${table(list, ilvl, xp, roster.checked_at, f, cam, groups)}`;
}

// The guilds the chips offer: the family guilds in their order, then any
// other guild the roster itself carries (a guild chip is its name in lower
// case, the slug every guild goes by).
function rosterGuilds(all) {
  const out = guilds().map((g) => ({ name: g.name, slug: g.slug }));
  const seen = new Set(out.map((g) => g.slug));
  all.forEach((m) => {
    const slug = (m.guild || "").toLowerCase();
    if (slug && !seen.has(slug)) { seen.add(slug); out.push({ name: m.guild, slug }); }
  });
  return out;
}

// Level bands a chip can set; the range is the lvl query's own shape.
const BANDS = [["60-60", "Level 60"], ["50-59", "Level 50 to 59"], ["1-49", "Below 50"]];

function bandChip([range, label], f) {
  const on = !!f.lvl && f.lvl[0] + "-" + f.lvl[1] === range;
  return html`<button type="button" class="chip" data-band="${range}" aria-pressed="${on ? "true" : "false"}">${label}</button>`;
}

function chip(label, key, on, n) {
  return html`<button type="button" class="chip" data-chip="${key}" aria-pressed="${on ? "true" : "false"}">${label}${n !== undefined ? html`<span class="dim mb-s">${n}</span>` : ""}</button>`;
}

function controls(roster, gg, q) {
  const f = filters(q);
  const all = roster.members || [];
  const gear = gearRows(gg);
  const stuck = all.filter((m) => m.stuck).length;
  const ghosts = all.filter((m) => stateOf(m) === "ghost").length;
  const fam = all.filter((m) => m.family).length;
  const prob = all.filter((m) => flagged(gear.get(m.name))).length;
  const emptyFlagged = all.filter((m) => (gear.get(m.name)?.flags || []).some((x) => /^\d+ empty$/.test(x))).length;
  return html`<div class="ro-triage"><p class="ro-summary"><b>${stuck} stuck</b> \u00b7 <b>${ghosts}</b> dead or ghost \u00b7 <b>${emptyFlagged}</b> flagged for empty slots \u00b7 of ${all.length}</p>
<div class="ro-chips">${chip("Stuck", "stuck", f.stuck, stuck)}${chip("Ghosts", "ghost", f.ghost, ghosts)}${chip("Families", "family", f.family, fam)}${chip("Gear problems", "gear", f.gear, prob)}${rosterGuilds(all).map((g) => chip(g.name, g.slug, f.guild === g.slug))}${BANDS.map((b) => bandChip(b, f))}</div>
<div class="row ro-controls"><label class="ro-filter"><i class="ph ph-funnel" aria-hidden="true"></i><input class="input" id="ro-filter" type="search" placeholder="Filter by name, class, zone" value="${q.q || ""}" aria-label="Filter members" autocomplete="off"></label>
<label class="ro-sort"><i class="ph ph-sort-descending" aria-hidden="true"></i><span class="sr-only">Sort members</span><select class="input" id="ro-sort" aria-label="Sort members">${SORTS.map(([k, label]) => html`<option value="${k}"${f.sort === k ? raw(" selected") : ""}>${label}</option>`)}</select></label></div>
${f.lvl ? html`<div class="row muted">Levels ${f.lvl[0]} to ${f.lvl[1]}<button type="button" class="btn btn-ghost" data-clear-lvl>clear</button></div>` : ""}</div>`;
}

function pageLine(roster) {
  const stuck = (roster.members || []).filter((m) => m.stuck);
  if (!stuck.length) return "Nobody is stuck right now.";
  const known = stuck.filter((m) => m.since !== null && m.since !== undefined).sort((a, b) => a.since - b.since);
  const first = known[0] || stuck[0];
  const d = known.length ? duration(roster.checked_at - first.since) : null;
  const n = stuck.length === 1 ? "1 member is stuck." : stuck.length + " members are stuck.";
  return n + " " + first.name + " has waited " + (d ? "longest, " + d : "longest; since not measured") + ": " + first.blocker;
}

// The footnote under the table: how XP per hour is counted and how many of
// the roster it covers.
function xpNote(roster, xp) {
  const names = (roster.members || []).map((m) => m.name);
  const known = names.filter((n) => xp.has(n));
  if (!known.length) return "XP per hour is not measured: the series reads have not answered.";
  const measured = known.filter((n) => xpValue(xp.get(n)) !== null).length;
  return "XP per hour is the mean over the last 24 hours of the straight line between a member's level changes and the experience held now. " +
    measured + " of " + names.length + " members have a level change on record to measure it from; the rest are not measured.";
}

function camOf(ctx) { return { sp: ctx.get(WATCH_READ), op: ctx.get(WATCH_OPERATOR) }; }

export default {
  css: ["views/members.css", WATCH_CSS],
  reads,
  every: 30000,
  title: () => "Members",
  render(ctx) {
    const roster = ctx.get("/api/v2/roster");
    const gg = ctx.get("/api/guildgear");
    const wait = pendingRead(roster, 4);
    if (wait) return html`${head("Members")}${sectionTabs("roster")}${wait}`;
    const q = liveQuery();
    const f = filters(q);
    const all = roster.data.members || [];
    const matched = all.filter((m) => keep(m, f, gearRows(gg.data)));
    const xp = xpRates(ctx.get);
    return html`${head("Members", matched.length + " of " + all.length, pageLine(roster.data))}${sectionTabs("roster")}${watchNotice()}<div class="ro-wrap">${controls(roster.data, gg.data, q)}<div data-region="roster">${body(roster.data, gg.data, xp, q, camOf(ctx), f, matched)}</div></div><p class="dim mb-s">${roster.data.basis || ""} ${xpNote(roster.data, xp)}</p>`;
  },
  after(main, ctx) {
    const roster = ctx.get("/api/v2/roster").data;
    if (!roster) return;
    const gg = ctx.get("/api/guildgear").data;
    const xp = xpRates(ctx.get);
    const region = main.querySelector("[data-region=roster]");
    const guildKeys = new Set([...guildSlugs(), ...(roster.members || []).map((m) => (m.guild || "").toLowerCase())]);
    const redraw = (q) => {
      region.innerHTML = body(roster, gg, xp, q, camOf(ctx)).s;
      bindWatch(region);
      const f = filters(q);
      main.querySelectorAll("[data-chip]").forEach((c) => {
        const k = c.getAttribute("data-chip");
        const on = guildKeys.has(k) ? f.guild === k : !!f[k];
        c.setAttribute("aria-pressed", String(on));
      });
      main.querySelectorAll("[data-band]").forEach((c) => {
        const on = !!f.lvl && f.lvl[0] + "-" + f.lvl[1] === c.getAttribute("data-band");
        c.setAttribute("aria-pressed", String(on));
      });
      const total = (roster.members || []).length;
      const shown = (roster.members || []).filter((m) => keep(m, f, gearRows(gg))).length;
      const aside = main.querySelector(".mb-aside");
      if (aside) aside.textContent = shown + " of " + total;
    };
    bindWatch(main);
    const input = main.querySelector("#ro-filter");
    if (input) input.addEventListener("input", () => redraw(setQuery({ q: input.value })));
    const sel = main.querySelector("#ro-sort");
    if (sel) sel.addEventListener("change", () => redraw(setQuery({ sort: sel.value === "stuck" ? "" : sel.value, dir: "" })));
    const wrap = main.querySelector(".ro-wrap");
    if (!wrap) return;
    wrap.addEventListener("click", (e) => {
      const c = e.target.closest("[data-chip], [data-band], [data-sort], [data-clear], [data-clear-lvl]");
      if (!c) return;
      const q = liveQuery();
      if (c.hasAttribute("data-chip")) {
        const k = c.getAttribute("data-chip");
        if (guildKeys.has(k)) redraw(setQuery({ guild: (q.guild || "") === k ? "" : k }));
        else redraw(setQuery({ [k]: q[k] ? "" : "1" }));
      } else if (c.hasAttribute("data-band")) {
        const range = c.getAttribute("data-band");
        redraw(setQuery({ lvl: (q.lvl || "") === range ? "" : range }));
      } else if (c.hasAttribute("data-sort")) {
        const f = filters(q);
        const n = flipSort({ key: f.sort, dir: f.dir }, c.getAttribute("data-sort"), FIRST[c.getAttribute("data-sort")]);
        redraw(setQuery({ sort: n.key, dir: n.dir }));
        if (sel) sel.value = n.key;
        const again = region.querySelector('[data-sort="' + n.key + '"]');
        if (again) again.focus({ preventScroll: true });
      } else if (c.hasAttribute("data-clear-lvl")) {
        setQuery({ lvl: "" });
        c.parentElement.remove();
        redraw(liveQuery());
      } else {
        if (input) input.value = "";
        redraw(setQuery({ stuck: "", ghost: "", family: "", gear: "", guild: "", q: "", lvl: "" }));
      }
    });
  },
};
