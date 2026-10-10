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

// One series read per family guild, as the realm reports them.
const series = () => guildSlugs().map((g) => "/api/v2/series?guild=" + g);
const reads = () => ["/api/v2/roster", "/api/guildgear", ...series()];

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
    stuck: !!q.stuck, ghost: !!q.ghost, family: !!q.family,
    guild: (q.guild || "").toLowerCase(), text: (q.q || "").trim().toLowerCase(),
    lvl: lvl ? [Number(lvl[1]), Number(lvl[2])] : null,
    sort, dir: q.dir === "asc" || q.dir === "desc" ? q.dir : FIRST[sort],
  };
}

function keep(m, f) {
  if (f.stuck && !m.stuck) return false;
  if (f.ghost && stateOf(m) !== "ghost") return false;
  if (f.family && !m.family) return false;
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

function cards(rows, ilvl, xp, at) {
  return html`<div class="ro-cards">${rows.map((m) => html`<a class="card ro-card" href="${"#/m/" + encodeURIComponent(m.name)}"><span class="row ro-top"><span class="mname" style="color:${classVar(m.class)}">${m.name}</span>${stateLabel(m, at)}</span><span class="dim mb-s">L${m.level} ${m.class} | ${m.guild || "no guild"} | ${m.zone || "zone not measured"} | iLvl ${ilvlText(ilvl.get(m.name))} | XP/h ${xpText(xp.get(m.name))}</span><span>${m.step || notMeasured("step not measured")}</span>${m.blocker ? html`<span class="muted">${m.blocker}</span>` : ""}</a>`)}</div>`;
}

const HEADS = [["Name", "name"], ["Lvl", "level"], ["Class"], ["Guild"], ["iLvl", "ilvl"], ["XP/h", "xp"], ["Current step"], ["Blocker"], ["Stuck for", "stuck"]];

function table(rows, ilvl, xp, at, f) {
  const cur = { key: f.sort, dir: f.dir };
  const th = HEADS.map(([label, key]) => (key ? sortHead(label, key, cur, "data-sort") : html`<th scope="col">${label}</th>`));
  const tr = rows.map((m) => {
    const d = stuckFor(m, at);
    const k = stateOf(m);
    const tail = m.stuck ? (d ? html`<span class="warn">${d}</span>` : html`<span class="dim">since not measured</span>`) : k === "ghost" ? html`<span class="bad">${m.life === "dead" ? "dead" : "ghost"}</span>` : "";
    return html`<tr><td>${memberLink(m)}</td><td class="num">${m.level}</td><td>${m.class}</td><td>${m.guild}</td><td class="num">${ilvlText(ilvl.get(m.name))}</td><td class="num">${xpText(xp.get(m.name))}</td><td>${m.step || notMeasured()}</td><td class="muted">${m.blocker}</td><td>${tail}</td></tr>`;
  });
  return html`<div class="card ro-table"><table class="table"><thead><tr>${th}</tr></thead><tbody>${tr}</tbody></table></div>`;
}

function body(roster, gg, xp, q) {
  const f = filters(q);
  const ilvl = gearRows(gg);
  const all = roster.members || [];
  const rows = all.filter((m) => keep(m, f)).sort(sorter(f.sort, f.dir, ilvl, xp));
  if (!rows.length) {
    return html`${state("empty", "No members match", "No member fits every filter you have on. Nothing is hidden by the server.")}<div><button type="button" class="btn btn-ghost" data-clear>Clear filters</button></div>`;
  }
  return html`${cards(rows, ilvl, xp, roster.checked_at)}${table(rows, ilvl, xp, roster.checked_at, f)}`;
}

// A chip that filters to one guild: its key is the guild's slug.
const isGuildChip = (k) => guildSlugs().includes(k);

function chip(label, key, on, n) {
  return html`<button type="button" class="chip" data-chip="${key}" aria-pressed="${on ? "true" : "false"}">${label}${n !== undefined ? html`<span class="dim mb-s">${n}</span>` : ""}</button>`;
}

function controls(roster, q) {
  const f = filters(q);
  const all = roster.members || [];
  const stuck = all.filter((m) => m.stuck).length;
  const ghosts = all.filter((m) => stateOf(m) === "ghost").length;
  const fam = all.filter((m) => m.family).length;
  return html`<div class="row ro-controls"><label class="ro-filter"><i class="ph ph-funnel" aria-hidden="true"></i><input class="input" id="ro-filter" type="search" placeholder="Filter by name, class, zone" value="${q.q || ""}" aria-label="Filter members" autocomplete="off"></label>
${chip("Stuck", "stuck", f.stuck, stuck)}${chip("Ghosts", "ghost", f.ghost, ghosts)}${chip("Families", "family", f.family, fam)}${guilds().map((g) => chip(g.name, g.slug, f.guild === g.slug))}
<label class="ro-sort"><i class="ph ph-sort-descending" aria-hidden="true"></i><span class="sr-only">Sort members</span><select class="input" id="ro-sort" aria-label="Sort members">${SORTS.map(([k, label]) => html`<option value="${k}"${f.sort === k ? raw(" selected") : ""}>${label}</option>`)}</select></label></div>
${f.lvl ? html`<div class="row muted">Levels ${f.lvl[0]} to ${f.lvl[1]}<button type="button" class="btn btn-ghost" data-clear-lvl>clear</button></div>` : ""}`;
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

export default {
  css: ["views/members.css"],
  reads,
  every: 30000,
  title: () => "Members",
  render(ctx) {
    const roster = ctx.get("/api/v2/roster");
    const gg = ctx.get("/api/guildgear");
    const wait = pendingRead(roster, 4);
    if (wait) return html`${head("Members")}${sectionTabs("roster")}${wait}`;
    const q = liveQuery();
    const total = (roster.data.members || []).length;
    const shown = (roster.data.members || []).filter((m) => keep(m, filters(q))).length;
    const xp = xpRates(ctx.get);
    return html`${head("Members", shown + " of " + total, pageLine(roster.data))}${sectionTabs("roster")}<div class="ro-wrap">${controls(roster.data, q)}<div data-region="roster">${body(roster.data, gg.data, xp, q)}</div></div><p class="dim mb-s">${roster.data.basis || ""} ${xpNote(roster.data, xp)}</p>`;
  },
  after(main, ctx) {
    const roster = ctx.get("/api/v2/roster").data;
    if (!roster) return;
    const gg = ctx.get("/api/guildgear").data;
    const xp = xpRates(ctx.get);
    const region = main.querySelector("[data-region=roster]");
    const redraw = (q) => {
      region.innerHTML = body(roster, gg, xp, q).s;
      const f = filters(q);
      main.querySelectorAll("[data-chip]").forEach((c) => {
        const k = c.getAttribute("data-chip");
        const on = isGuildChip(k) ? f.guild === k : !!f[k];
        c.setAttribute("aria-pressed", String(on));
      });
      const total = (roster.members || []).length;
      const shown = (roster.members || []).filter((m) => keep(m, f)).length;
      const aside = main.querySelector(".mb-aside");
      if (aside) aside.textContent = shown + " of " + total;
    };
    const input = main.querySelector("#ro-filter");
    if (input) input.addEventListener("input", () => redraw(setQuery({ q: input.value })));
    const sel = main.querySelector("#ro-sort");
    if (sel) sel.addEventListener("change", () => redraw(setQuery({ sort: sel.value === "stuck" ? "" : sel.value, dir: "" })));
    const wrap = main.querySelector(".ro-wrap");
    if (!wrap) return;
    wrap.addEventListener("click", (e) => {
      const c = e.target.closest("[data-chip], [data-sort], [data-clear], [data-clear-lvl]");
      if (!c) return;
      const q = liveQuery();
      if (c.hasAttribute("data-chip")) {
        const k = c.getAttribute("data-chip");
        if (isGuildChip(k)) redraw(setQuery({ guild: (q.guild || "") === k ? "" : k }));
        else redraw(setQuery({ [k]: q[k] ? "" : "1" }));
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
        redraw(setQuery({ stuck: "", ghost: "", family: "", guild: "", q: "", lvl: "" }));
      }
    });
  },
};
