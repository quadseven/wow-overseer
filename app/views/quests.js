// Quests: #/quests, and one quest's attempts at #/quests/<id>.
//
// The two quester parties (#922) set out to prove every quest can be done by
// playing it. The page draws, top to bottom:
//
//   Parties     one card per quester: level, zone, the quest it is on, and
//               how many it has completed and found broken (/api/v2/questers)
//   Coverage    completed, broken and not reached, per faction and per zone,
//               from the totals in /api/v2/quests
//   Catalogue   every quest in /api/v2/quests, narrowed by faction, zone,
//               level range, status and a search. A row opens the quest's
//               attempts (/api/v2/quests/<id>): who tried, how it ended, why
//               it broke and the ticket filed for it.
//
// The payloads, as this view reads them:
//
//   /api/v2/questers    {parties: [{guild, faction, questers: [{name, class,
//                        race, role, level, zone, quest: {id, title} | null,
//                        completed, broken}]}]}
//   /api/v2/quests      {totals: {factions: [{faction, completed, broken,
//                        not_reached, total}], zones: [{zone, faction, ...the
//                        same counts}]}, quests: [{id, title, faction, zone,
//                        level, status, attempts}]}
//   /api/v2/quests/<id> {quest: {id, title, faction, zone, level, status},
//                        attempts: [{quester, guild, level, started_at,
//                        ended_at, outcome, reason, ticket: {number, url}}]}
//
// The filters live in the URL query (#/quests?faction=Horde&lvl=10-20&q=wolf),
// written with replaceState so typing never loses the caret, and a row's link
// carries them, so the way back from a quest lands on the same list.

import { html, raw, notMeasured, pendingRead, pageHead, sectionHead, state, classVar, memberHref, plural, ready } from "../ui.js";
import { liveQuery, setQuery } from "./_members.js";
import { build } from "../router.js";
import { since } from "../models/time.js";

const QUESTERS = "/api/v2/questers";
const QUESTS = "/api/v2/quests";
const questPath = (id) => QUESTS + "/" + encodeURIComponent(id);

// A quest's status: [label, icon, colour class]. The status colours carry an
// icon and a word, never the colour alone.
const STATUS = {
  completed: ["Completed", "ph-fill ph-check-circle", "ok"],
  broken: ["Broken", "ph-fill ph-x-circle", "bad"],
  not_reached: ["Not reached", "ph ph-circle-dashed", "dim"],
  in_progress: ["In progress", "ph ph-circle-half", "accent"],
};
const STATUS_FILTER = ["completed", "broken", "not_reached"];

function statusTag(s) {
  const st = STATUS[s];
  if (!st) return s ? html`<span class="status">${s}</span>` : notMeasured();
  return html`<span class="status qs-${st[2]}"><i class="${st[1]}" aria-hidden="true"></i>${st[0]}</span>`;
}

const known = (v) => v !== null && v !== undefined && v !== "";
const num = (v) => (known(v) && isFinite(v) ? Number(v) : null);
const count = (v) => (num(v) === null ? notMeasured() : num(v).toLocaleString("en-US"));

// Only a web link becomes a ticket link: the href comes from the server.
function ticketLink(t) {
  if (!t || !/^https:\/\//.test(t.url || "")) return "";
  return html`<a class="qs-ticket" href="${t.url}" target="_blank" rel="noopener"><i class="ph ph-ticket" aria-hidden="true"></i>${t.number ? "Ticket #" + t.number : "Ticket"}</a>`;
}

// ---- the filters ------------------------------------------------------------------

export function filters(q) {
  const lvl = /^(\d*)-(\d*)$/.exec(q.lvl || "");
  return {
    faction: q.faction || "", zone: q.zone || "",
    status: STATUS_FILTER.includes(q.status) ? q.status : "",
    lo: lvl && lvl[1] ? Number(lvl[1]) : null, hi: lvl && lvl[2] ? Number(lvl[2]) : null,
    text: (q.q || "").trim().toLowerCase(),
  };
}

export function keep(x, f) {
  if (f.faction && x.faction !== f.faction) return false;
  if (f.zone && x.zone !== f.zone) return false;
  if (f.status && x.status !== f.status) return false;
  if (f.lo !== null || f.hi !== null) {
    const l = num(x.level);
    if (l === null || (f.lo !== null && l < f.lo) || (f.hi !== null && l > f.hi)) return false;
  }
  // Only the fields the server sent: a missing one must not search as the word "undefined".
  if (f.text && ![x.title, x.zone, x.id].filter(known).join(" ").toLowerCase().includes(f.text)) return false;
  return true;
}

// The filter keys a row's link carries to the quest and back.
const FILTER_KEYS = ["faction", "zone", "lvl", "status", "q"];
const kept = (q) => Object.fromEntries(FILTER_KEYS.filter((k) => known(q[k])).map((k) => [k, q[k]]));

// ---- parties ----------------------------------------------------------------------

function questerCard(m) {
  const quest = m.quest && m.quest.title
    ? (known(m.quest.id) ? html`<a href="${build(["quests", String(m.quest.id)], {})}">${m.quest.title}</a>` : m.quest.title)
    : notMeasured("no quest on");
  return html`<div class="card qs-quester"><span class="row qs-between"><a class="mname" href="${memberHref(m.name, "quests")}" style="color:${classVar(m.class)}">${m.name}</a><span class="dim qs-s">${num(m.level) === null ? notMeasured("level not measured") : "L" + m.level}</span></span>
<span class="dim qs-s">${[m.race, m.class, m.role].filter(Boolean).join(" ")}</span><span class="qs-s">${m.zone || notMeasured("zone not measured")}</span>
<span class="qs-s">${quest}</span>
<span class="row qs-s"><span class="qs-ok"><i class="ph-fill ph-check-circle" aria-hidden="true"></i>${count(m.completed)} completed</span><span class="qs-bad"><i class="ph-fill ph-x-circle" aria-hidden="true"></i>${count(m.broken)} broken</span></span></div>`;
}

function parties(read) {
  const wait = pendingRead(read, 2);
  if (wait) return wait;
  const ps = (read.data && read.data.parties) || [];
  if (!ps.length) return state("empty", "No quester parties", "The server reports no questers yet.");
  return html`<div class="qs-parties">${ps.map((p) => html`<section class="qs-party" aria-label="${p.guild + " questers"}"><h3 class="qs-party-head">${p.guild}${p.faction ? html` <span class="dim qs-s">${p.faction}</span>` : ""}<span class="dim qs-s">${plural((p.questers || []).length, "quester")}</span></h3><div class="qs-cards">${(p.questers || []).map(questerCard)}</div></section>`)}</div>`;
}

// ---- coverage ---------------------------------------------------------------------

// A stacked bar of completed, broken and not reached, with the numbers
// beside it in text: the bar is the shape, the words are the record.
function bar(t) {
  const total = num(t.total);
  if (!total) return notMeasured();
  // Divide by at least the sum of the counts, so their widths stay within 100%.
  const scale = Math.max(total, STATUS_FILTER.reduce((sum, k) => sum + (num(t[k]) || 0), 0));
  const part = (k, cls) => {
    const n = num(t[k]) || 0;
    return n ? html`<span class="${cls}" style="width:${(Math.floor((n / scale) * 10000) / 100).toFixed(2)}%"></span>` : "";
  };
  const word = (k) => (num(t[k]) === null ? "not measured" : num(t[k]).toLocaleString("en-US")) + " " + STATUS[k][0].toLowerCase();
  const label = STATUS_FILTER.map(word).join(", ");
  return html`<span class="qs-bar" role="img" aria-label="${label + " of " + total}" title="${label + " of " + total}">${part("completed", "qs-bar-ok")}${part("broken", "qs-bar-bad")}${part("not_reached", "qs-bar-none")}</span>`;
}

function counts(t) {
  return html`<span class="qs-counts qs-s"><span class="qs-ok">${count(t.completed)} completed</span><span class="qs-bad">${count(t.broken)} broken</span><span class="dim">${count(t.not_reached)} not reached</span><span class="dim">of ${count(t.total)}</span></span>`;
}

function coverage(data) {
  const totals = data.totals || {};
  const fs = totals.factions || [];
  const zs = (totals.zones || []).slice().sort((a, b) => String(a.zone).localeCompare(String(b.zone)));
  if (!fs.length && !zs.length) return state("unmeasured", "Coverage not measured", "The server sent no totals with the quests.");
  const faction = fs.map((t) => html`<div class="card qs-cover"><a class="qs-cover-name" href="${build(["quests"], { faction: t.faction })}">${t.faction}</a>${bar(t)}${counts(t)}</div>`);
  const zone = zs.map((t) => html`<li class="qs-zone"><a class="qs-zone-name" href="${build(["quests"], { faction: t.faction || "", zone: t.zone })}">${t.zone}${t.faction ? html` <span class="dim qs-s">${t.faction}</span>` : ""}</a>${bar(t)}${counts(t)}</li>`);
  return html`<div class="qs-covers">${faction}</div>${zone.length ? html`<details class="card qs-zones"><summary>Per zone <span class="dim qs-s">${plural(zone.length, "zone")}</span></summary><ul class="qs-zone-list">${zone}</ul></details>` : ""}`;
}

// ---- catalogue ----------------------------------------------------------------------

// Rows drawn at once: a phone holding every quest in the game would crawl,
// so the list grows by STEP on request. Changing a filter starts it over.
const STEP = 100;
// Clicks and timed renders run to completion on the same browser thread; they
// cannot interleave the count update. The filter key resets it on a new list.
let shown = { key: "", n: STEP };
function limitFor(q) {
  const key = JSON.stringify(kept(q));
  if (shown.key !== key) shown = { key, n: STEP };
  return shown.n;
}

const levelText = (x) => (num(x.level) === null ? notMeasured() : String(x.level));

function rows(list, q) {
  const link = (x) => build(["quests", String(x.id)], kept(q));
  const cards = list.map((x) => html`<a class="card qs-qcard" href="${link(x)}"><span class="row qs-between"><span class="qs-title">${x.title}</span>${statusTag(x.status)}</span><span class="dim qs-s">L${levelText(x)} | ${x.zone || "zone not measured"} | ${x.faction || "faction not measured"} | ${plural(num(x.attempts) || 0, "attempt")}</span></a>`);
  const tr = list.map((x) => html`<tr><td><a href="${link(x)}">${x.title}</a></td><td class="num">${levelText(x)}</td><td>${x.zone || notMeasured()}</td><td>${x.faction || notMeasured()}</td><td>${statusTag(x.status)}</td><td class="num">${count(x.attempts)}</td></tr>`);
  return html`<div class="qs-qcards">${cards}</div><div class="card qs-table"><table class="table"><thead><tr><th scope="col">Quest</th><th scope="col">Lvl</th><th scope="col">Zone</th><th scope="col">Faction</th><th scope="col">Status</th><th scope="col">Attempts</th></tr></thead><tbody>${tr}</tbody></table></div>`;
}

export function catalogueBody(data, q) {
  const f = filters(q);
  const all = data.quests || [];
  const match = all.filter((x) => keep(x, f));
  if (!all.length) return state("empty", "No quests", "The server sent an empty catalogue.");
  if (!match.length) {
    return html`${state("empty", "No quests match", "No quest fits every filter you have on. Nothing is hidden by the server.")}<div><button type="button" class="btn btn-ghost" data-clear>Clear filters</button></div>`;
  }
  const n = limitFor(q);
  const more = match.length > n ? html`<button type="button" class="btn btn-secondary qs-more" data-more>Show ${Math.min(STEP, match.length - n)} more</button>` : "";
  return html`<p class="dim qs-s" data-region="count">${match.length.toLocaleString("en-US")} of ${all.length.toLocaleString("en-US")} quests${match.length > n ? ", the first " + n + " shown" : ""}</p>${rows(match.slice(0, n), q)}${more}`;
}

// A faction or zone is server text. `html` escapes every interpolated value,
// quotes included, so one holding `"` or `<` stays inside value="..." and the
// option's text; the only markup passed through unescaped is raw(" selected").
function select(id, label, value, options) {
  return html`<label class="qs-field"><span class="qs-s dim">${label}</span><select class="input" id="${id}" aria-label="${label}"><option value="">All</option>${options.map(([v, text]) => html`<option value="${v}"${v === value ? raw(" selected") : ""}>${text}</option>`)}</select></label>`;
}

function controls(data, q) {
  const f = filters(q);
  const all = data.quests || [];
  const uniq = (xs) => [...new Set(xs.filter(known))].sort((a, b) => String(a).localeCompare(String(b)));
  const factions = uniq(all.map((x) => x.faction));
  // The zones offered are the chosen faction's, or every zone.
  const zones = uniq(all.filter((x) => !f.faction || x.faction === f.faction).map((x) => x.zone));
  if (f.zone && !zones.includes(f.zone)) zones.unshift(f.zone);
  return html`<div class="qs-controls"><label class="qs-search"><i class="ph ph-magnifying-glass" aria-hidden="true"></i><input class="input" id="qs-q" type="search" placeholder="Search quests by name, zone or id" value="${q.q || ""}" aria-label="Search quests" autocomplete="off"></label>
${select("qs-faction", "Faction", f.faction, factions.map((v) => [v, v]))}${select("qs-zone", "Zone", f.zone, zones.map((v) => [v, v]))}${select("qs-status", "Status", f.status, STATUS_FILTER.map((k) => [k, STATUS[k][0]]))}
<fieldset class="qs-field qs-levels"><legend class="qs-s dim">Level</legend><span class="row"><input class="input" id="qs-lo" type="number" inputmode="numeric" min="1" max="80" placeholder="From" aria-label="Lowest level" value="${f.lo === null ? "" : f.lo}"><span class="dim">to</span><input class="input" id="qs-hi" type="number" inputmode="numeric" min="1" max="80" placeholder="To" aria-label="Highest level" value="${f.hi === null ? "" : f.hi}"></span></fieldset></div>`;
}

// ---- one quest ------------------------------------------------------------------------

function attempt(a) {
  const when = a.ended_at ? "ended " + since(a.ended_at) : a.started_at ? "started " + since(a.started_at) : "";
  return html`<li class="card qs-attempt"><span class="row qs-between"><span>${a.quester ? html`<a class="mname" href="${memberHref(a.quester, "quests")}">${a.quester}</a>` : notMeasured("quester not measured")}${a.guild ? html` <span class="dim qs-s">${a.guild}</span>` : ""}</span>${statusTag(a.outcome)}</span>
<span class="dim qs-s">${num(a.level) === null ? "level not measured" : "at L" + a.level}${when ? " | " + when : ""}</span>${a.reason ? html`<p class="qs-reason">${a.reason}</p>` : a.outcome === "broken" ? html`<p class="qs-reason">${notMeasured("no reason recorded")}</p>` : ""}${ticketLink(a.ticket)}</li>`;
}

function questPage(ctx) {
  // render() calls this only for a route with an id; #/quests uses the catalogue.
  const back = html`<a class="qs-back" href="${build(["quests"], kept(ctx.query))}"><i class="ph ph-arrow-left" aria-hidden="true"></i>All quests</a>`;
  const read = ctx.get(questPath(ctx.params.id));
  // A read with no entry yet (null) is "loading" to pendingRead, so it returns
  // skeletons here and nothing below reads into a null `read`.
  const wait = pendingRead(read, 3);
  if (wait) return html`${back}${pageHead("Quest " + ctx.params.id)}${wait}`;
  if (!read.data || read.data.error) {
    return html`${back}${pageHead("Quest " + ctx.params.id)}${state("unmeasured", "This quest was not found", read.data && read.data.error ? "The server says: " + read.data.error + "." : "The server sent nothing for it.")}`;
  }
  const x = read.data.quest || {};
  const list = read.data.attempts || [];
  const line = html`${statusTag(x.status)} <span class="dim">L${levelText(x)} | ${x.zone || "zone not measured"} | ${x.faction || "faction not measured"}</span>`;
  return html`${back}${pageHead(x.title || "Quest " + ctx.params.id, line)}${sectionHead("", "Attempts", plural(list.length, "attempt"))}${list.length ? html`<ol class="qs-attempts">${list.map(attempt)}</ol>` : state("empty", "No attempts yet", "No quester has tried this quest.")}`;
}

// ---- the page ---------------------------------------------------------------------------

function summary(data) {
  const fs = (data.totals && data.totals.factions) || [];
  const sum = (k) => fs.reduce((s, t) => (num(t[k]) === null ? s : s + num(t[k])), 0);
  if (!fs.length) return "";
  return sum("completed").toLocaleString("en-US") + " quests completed and " + sum("broken").toLocaleString("en-US") + " found broken, of " + sum("total").toLocaleString("en-US") + ".";
}

export default {
  css: ["views/quests.css"],
  reads: (ctx) => (ctx.params.id ? [questPath(ctx.params.id)] : [QUESTERS, QUESTS]),
  every: 30000,
  title: (ctx) => (ctx.params.id ? "Quest " + ctx.params.id : "Quests"),
  render(ctx) {
    if (ctx.params.id) return html`<div class="qs">${questPage(ctx)}</div>`;
    const quests = ctx.get(QUESTS);
    const ok = ready(quests);
    const q = liveQuery();
    const wait = pendingRead(quests, 4);
    const cover = wait || (ok ? coverage(quests.data) : state("unmeasured", "Quests not measured", "The quests read answered with no catalogue."));
    const cat = ok ? html`${controls(quests.data, q)}<div data-region="catalogue">${catalogueBody(quests.data, q)}</div>` : wait || "";
    return html`<div class="qs">${pageHead("Quests", ok ? summary(quests.data) : "")}${sectionHead("", "Quester parties")}${parties(ctx.get(QUESTERS))}${sectionHead("", "Coverage")}${cover}${sectionHead("", "Catalogue")}<div class="qs-catalogue">${cat}</div></div>`;
  },
  after(main, ctx) {
    if (ctx.params.id) return;
    const data = ctx.get(QUESTS).data;
    const region = main.querySelector("[data-region=catalogue]");
    if (!data || !region) return;
    // Both redraws run whole on the browser's one thread, reading the URL that
    // setQuery has just written; limitFor() keys `shown` to those filters.
    const redraw = (q) => { region.innerHTML = catalogueBody(data, q).s; };
    const val = (id) => { const el = main.querySelector("#" + id); return el ? el.value : ""; };
    const levels = () => { const lo = val("qs-lo"), hi = val("qs-hi"); return lo || hi ? lo + "-" + hi : ""; };
    const on = (id, ev, fn) => { const el = main.querySelector("#" + id); if (el) el.addEventListener(ev, fn); };
    on("qs-q", "input", () => redraw(setQuery({ q: val("qs-q") })));
    on("qs-zone", "change", () => redraw(setQuery({ zone: val("qs-zone") })));
    on("qs-status", "change", () => redraw(setQuery({ status: val("qs-status") })));
    on("qs-lo", "input", () => redraw(setQuery({ lvl: levels() })));
    on("qs-hi", "input", () => redraw(setQuery({ lvl: levels() })));
    // The controls and the list together, when the controls change too: a new
    // faction changes the zones offered, and Clear empties every field. The
    // list region sits inside .qs-catalogue, so the rewrite replaces it and
    // every control with new elements; calling after() again binds each
    // listener, the region's click included, once on the new ones. The old
    // listeners leave with the old elements and nothing stacks.
    const redrawAll = (q, focus) => {
      main.querySelector(".qs-catalogue").innerHTML = html`${controls(data, q)}<div data-region="catalogue">${catalogueBody(data, q)}</div>`.s;
      this.after(main, ctx);
      const el = focus && main.querySelector("#" + focus);
      if (el) el.focus({ preventScroll: true });
    };
    on("qs-faction", "change", () => redrawAll(setQuery({ faction: val("qs-faction"), zone: "" }), "qs-faction"));
    region.addEventListener("click", (e) => {
      if (e.target.closest("[data-more]")) {
        shown.n += STEP;
        redraw(liveQuery());
      } else if (e.target.closest("[data-clear]")) {
        redrawAll(setQuery({ faction: "", zone: "", lvl: "", status: "", q: "" }), "qs-q");
      }
    });
  },
};
