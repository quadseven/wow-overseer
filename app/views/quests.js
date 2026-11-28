// Quests: #/quests, and one quest's attempts at #/quests/<id>.
//
// The two quester parties (#922) set out to prove every quest can be done by
// playing it. The page draws, top to bottom:
//
//   The door    Broken and Taken chips counted off the quests read's
//               totals, one tap each to the catalogue filtered to that set
//   Parties     one card per quester, grouped by guild: level, the online
//               word, zone, the quests in its log (the whole log behind a
//               disclosure), and its all time ledger counts
//               (/api/v2/questers)
//   Coverage    completed, broken, taken, abandoned and not reached, per
//               faction from the by_faction totals in /api/v2/quests, and per
//               zone counted off that read's quests; not reached is the
//               coverage bar's track, not a segment
//   Catalogue   every quest in /api/v2/quests, narrowed by faction, zone,
//               level range, status and a search, in a chosen order (a
//               broken list defaults to most attempts first), under a
//               sticky line naming the count and the active filters. A row
//               opens the quest's attempts (/api/v2/quests/<id>): who
//               tried, how it ended and why it broke.
//
// The payloads, as apiv2/quests.py serves them (its docstring is the
// contract; tests/test_quests_view.py builds its fixtures with that module's
// own builders, so a shape drawn here that the server does not send fails):
//
//   /api/v2/questers    {questers: [{name, guild, present, level, zone,
//                        zone_name, online, current: [{id, title, status}],
//                        completed, broken, taken, abandoned}]}
//                        a flat list; the parties are its guilds, in order
//   /api/v2/quests      {quests: [{id, title, level, min_level, zone (an area
//                        id), zone_name, faction (horde, alliance or both),
//                        status, attempts}], totals: COUNTS,
//                        by_faction: {horde: COUNTS, alliance: COUNTS}, shown}
//                        COUNTS is {quests, completed, broken, taken,
//                        abandoned, not_reached}; the per-zone coverage is
//                        counted here off the quests the same read sends
//   /api/v2/quests/<id> {quest: {...as above}, attempts: [{character, guid,
//                        guild, state, first_taken, finished, reason}]}
//
// The filters live in the URL query (#/quests?faction=Horde&lvl=10-20&q=wolf),
// written with replaceState so typing never loses the caret, and a row's link
// carries them, so the way back from a quest lands on the same list.

import { html, raw, isHttps, notMeasured, pendingRead, pageHead, sectionHead, state, memberHref, plural, ready } from "../ui.js";
import { liveQuery, setQuery } from "./_members.js";
import { build } from "../router.js";
import { since } from "../models/time.js";

const QUESTERS = "/api/v2/questers";
const QUESTS = "/api/v2/quests";
const SEP = " \u00b7 ";
const questPath = (id) => QUESTS + "/" + encodeURIComponent(id);

// A quest's status: [label, icon, colour class, bar class]. The status
// colours carry an icon and a word, never the colour alone. The keys and their
// order are questledger.STATUS_ORDER.
const STATUS = {
  completed: ["Completed", "ph-fill ph-check-circle", "ok", "qs-bar-ok"],
  broken: ["Broken", "ph-fill ph-x-circle", "bad", "qs-bar-bad"],
  taken: ["Taken", "ph ph-circle-half", "accent", "qs-bar-taken"],
  abandoned: ["Abandoned", "ph ph-minus-circle", "dim", "qs-bar-left"],
  not_reached: ["Not reached", "ph ph-circle-dashed", "dim", "qs-bar-none"],
};
const STATUS_FILTER = Object.keys(STATUS);

// The sides, as the server keys them. A quest both sides take is "both", and
// a side's filter keeps it, as the server's own faction filter does.
const SIDES = [["horde", "Horde"], ["alliance", "Alliance"]];
const BOTH = "both";
const sideName = (v) => (v === BOTH ? "Both sides" : (SIDES.find((s) => s[0] === v) || [v, v])[1]);
// A quest's zone as words: the area id alone names nothing to a reader.
const zoneOf = (x) => (x && x.zone_name) || "";

function statusTag(s) {
  const st = STATUS[s];
  if (!st) return s ? html`<span class="status">${s}</span>` : notMeasured();
  return html`<span class="status qs-${st[2]}"><i class="${st[1]}" aria-hidden="true"></i>${st[0]}</span>`;
}

const known = (v) => v !== null && v !== undefined && v !== "";
const num = (v) => (known(v) && isFinite(v) ? Number(v) : null);
const count = (v) => (num(v) === null ? notMeasured() : num(v).toLocaleString("en-US"));

// ---- the filters ------------------------------------------------------------------

// The catalogue's orders. "server" is the order the read itself lists; a
// broken list with no sort chosen falls back to most attempts first, the
// order that puts the most-tried failures at the top.
const SORTS = ["server", "level", "attempts", "title"];

export function filters(q) {
  const lvl = /^(\d*)-(\d*)$/.exec(q.lvl || "");
  const status = STATUS_FILTER.includes(q.status) ? q.status : "";
  return {
    faction: q.faction || "", zone: q.zone || "",
    status,
    sort: SORTS.includes(q.sort) ? q.sort : status === "broken" ? "attempts" : "server",
    lo: lvl && lvl[1] ? Number(lvl[1]) : null, hi: lvl && lvl[2] ? Number(lvl[2]) : null,
    text: (q.q || "").trim().toLowerCase(),
  };
}

export function keep(x, f) {
  if (f.faction && x.faction !== f.faction && x.faction !== BOTH) return false;
  if (f.zone && zoneOf(x) !== f.zone) return false;
  if (f.status && x.status !== f.status) return false;
  if (f.lo !== null || f.hi !== null) {
    const l = num(x.level);
    if (l === null || (f.lo !== null && l < f.lo) || (f.hi !== null && l > f.hi)) return false;
  }
  // Only the fields the server sent: a missing one must not search as the word "undefined".
  if (f.text && ![x.title, x.zone_name, x.id].filter(known).join(" ").toLowerCase().includes(f.text)) return false;
  return true;
}

// The filter keys a row's link carries to the quest and back.
const FILTER_KEYS = ["faction", "zone", "lvl", "status", "q", "sort"];
const kept = (q) => Object.fromEntries(FILTER_KEYS.filter((k) => known(q[k])).map((k) => [k, q[k]]));

// ---- parties ----------------------------------------------------------------------

// The quests in a quester's log, linked: the first few on the card, and the
// whole log behind a disclosure when the log runs longer than they show.
const CURRENT_SHOWN = 3;
function current(m) {
  const qs = (m.current || []).filter((x) => x && x.title);
  if (!qs.length) return notMeasured("no quest on");
  const link = (x) => (known(x.id) ? html`<a href="${build(["quests", String(x.id)], {})}">${x.title}</a>` : x.title);
  const joined = (list) => list.map((x, i) => html`${i ? ", " : ""}${link(x)}`);
  if (qs.length <= CURRENT_SHOWN) return html`${joined(qs)}`;
  return html`${joined(qs.slice(0, CURRENT_SHOWN))}<details class="qs-logfold"><summary>Show all ${qs.length} current quests</summary><span>${joined(qs)}</span></details>`;
}

function questerCard(m) {
  const name = html`<a class="mname" href="${memberHref(m.name, "quests")}">${m.name}</a>`;
  if (m.present === false) {
    return html`<div class="card qs-quester"><span class="row qs-between">${name}</span><span class="dim qs-s">not on the realm yet</span></div>`;
  }
  const level = num(m.level) === null ? notMeasured("level not measured") : "L" + m.level;
  const onlineWord = m.online ? html`<span class="qs-on">online</span>` : html`<span class="dim">offline</span>`;
  return html`<div class="card qs-quester"><span class="row qs-between">${name}<span class="dim qs-s">${level} ${onlineWord}</span></span>
<span class="qs-s">${m.zone_name || notMeasured("zone not measured")}</span>
<div class="qs-s">${current(m)}</div>
<span class="row qs-s"><span class="dim">All time</span><span class="qs-ok"><i class="ph-fill ph-check-circle" aria-hidden="true"></i>${count(m.completed)} completed</span><span class="qs-bad"><i class="ph-fill ph-x-circle" aria-hidden="true"></i>${count(m.broken)} broken</span><span>${count(m.taken)} taken</span><span>${count(m.abandoned)} abandoned</span></span></div>`;
}

// The server lists the questers flat, guild by guild; a party is one guild.
function partiesOf(questers) {
  const by = new Map();
  for (const m of questers) {
    const g = m.guild || "";
    if (!by.has(g)) by.set(g, []);
    by.get(g).push(m);
  }
  return [...by].map(([guild, list]) => ({ guild: guild || "No guild", questers: list }));
}

function parties(read) {
  const wait = pendingRead(read, 2);
  if (wait) return wait;
  const ps = partiesOf((read.data && read.data.questers) || []);
  if (!ps.length) return state("empty", "No quester parties", "The server reports no questers yet.");
  return html`<div class="qs-parties">${ps.map((p) => html`<section class="qs-party" aria-label="${p.guild + " questers"}"><h3 class="qs-party-head">${p.guild}<span class="dim qs-s">${plural(p.questers.length, "quester")}</span></h3><div class="qs-cards">${p.questers.map(questerCard)}</div></section>`)}</div>`;
}

// ---- coverage ---------------------------------------------------------------------

// A stacked bar of the reached statuses, with the numbers beside it in
// text: the bar is the shape, the words are the record. Not reached draws
// no segment: the track left behind the drawn segments is its share, and
// the counts line states its number once. `t` is a COUNTS of the server's.
function bar(t) {
  const total = num(t.quests);
  if (!total) return notMeasured();
  // Divide by at least the sum of the counts, so their widths stay within 100%.
  const scale = Math.max(total, STATUS_FILTER.reduce((sum, k) => sum + (num(t[k]) || 0), 0));
  const part = (k) => {
    const n = num(t[k]) || 0;
    return n ? html`<span class="${STATUS[k][3]}" style="width:${(Math.floor((n / scale) * 10000) / 100).toFixed(2)}%"></span>` : "";
  };
  const word = (k) => (num(t[k]) === null ? "not measured" : num(t[k]).toLocaleString("en-US")) + " " + STATUS[k][0].toLowerCase();
  const label = STATUS_FILTER.map(word).join(", ");
  const drawn = STATUS_FILTER.filter((k) => k !== "not_reached");
  return html`<span class="qs-bar" role="img" aria-label="${label + " of " + total}" title="${label + " of " + total}">${drawn.map(part)}</span>`;
}

function counts(t) {
  const cls = { completed: "qs-ok", broken: "qs-bad" };
  return html`<span class="qs-counts qs-s">${STATUS_FILTER.map((k) => html`<span class="${cls[k] || "dim"}">${count(t[k])} ${STATUS[k][0].toLowerCase()}</span>`)}<span class="dim">of ${count(t.quests)}</span></span>`;
}

// Each zone's COUNTS off the catalogue's own rows, by zone name. A quest with
// no zone (a class or holiday quest) counts in its side's total, not here.
export function zoneTotals(quests) {
  const by = new Map();
  for (const x of quests || []) {
    const z = zoneOf(x);
    if (!z) continue;
    if (!by.has(z)) by.set(z, Object.fromEntries([["zone", z], ["quests", 0], ...STATUS_FILTER.map((k) => [k, 0])]));
    const t = by.get(z);
    t.quests += 1;
    if (x.status in STATUS) t[x.status] += 1;
  }
  return [...by.values()].sort((a, b) => a.zone.localeCompare(b.zone));
}

function coverage(data) {
  const sides = data.by_faction || {};
  const fs = SIDES.filter(([k]) => sides[k]).map(([k, label]) => ({ ...sides[k], faction: k, label }));
  const zs = zoneTotals(data.quests);
  if (!fs.length && !zs.length) return state("unmeasured", "Coverage not measured", "The server sent no totals with the quests.");
  const faction = fs.map((t) => html`<div class="card qs-cover"><a class="qs-cover-name" href="${build(["quests"], { faction: t.faction })}">${t.label}</a>${bar(t)}${counts(t)}</div>`);
  const zone = zs.map((t) => html`<li class="qs-zone"><span class="row qs-between"><a class="qs-zone-name" href="${build(["quests"], { zone: t.zone })}">${t.zone}</a><span class="qs-s"><span class="qs-ok">${count(t.completed)} completed</span> <span class="qs-bad">${count(t.broken)} broken</span></span></span>${bar(t)}</li>`);
  const caption = fs.length ? html`<p class="dim qs-s qs-caption">Both sides quests count in each.</p>` : "";
  return html`<div class="qs-covers">${faction}</div>${caption}${zone.length ? html`<details class="card qs-zones"><summary>Per zone <span class="dim qs-s">${plural(zone.length, "zone")}</span></summary><ul class="qs-zone-list">${zone}</ul></details>` : ""}`;
}

// ---- catalogue ----------------------------------------------------------------------

// Rows drawn at once: a phone holding every quest in the game would crawl,
// so the list grows by a step on request: 40 on a phone, 100 on a wide
// screen. Changing a filter starts it over. render() and after() record
// which one this is from the context they were handed.
const STEP_WIDE = 100;
const STEP_NARROW = 40;
let narrow = false;
const step = () => (narrow ? STEP_NARROW : STEP_WIDE);
// Clicks and timed renders run to completion on the same browser thread; they
// cannot interleave the count update. The filter key resets it on a new list.
let shown = { key: "", n: STEP_WIDE };
function limitFor(q) {
  const key = JSON.stringify(kept(q));
  if (shown.key !== key) shown = { key, n: step() };
  return shown.n;
}

const levelText = (x) => (num(x.level) === null ? notMeasured() : String(x.level));

// A quest's attempts as a fact: a count the read sent, or the words for a
// count it did not send. Never a zero the page made up.
const attemptsText = (x) => (num(x.attempts) === null ? "attempts not measured" : plural(num(x.attempts), "attempt"));

function rows(list, q) {
  const link = (x) => build(["quests", String(x.id)], kept(q));
  const cards = list.map((x) => html`<a class="card qs-qcard" href="${link(x)}"><span class="row qs-between"><span class="qs-title">${x.title}</span>${statusTag(x.status)}</span><span class="qs-meta"><span>Level ${levelText(x)}</span><span>${zoneOf(x) || "zone not measured"}</span><span>${x.faction ? sideName(x.faction) : "faction not measured"}</span><span>${attemptsText(x)}</span></span></a>`);
  const tr = list.map((x) => html`<tr><td><a href="${link(x)}">${x.title}</a></td><td class="num">${levelText(x)}</td><td>${zoneOf(x) || notMeasured()}</td><td>${x.faction ? sideName(x.faction) : notMeasured()}</td><td>${statusTag(x.status)}</td><td class="num">${count(x.attempts)}</td></tr>`);
  return html`<div class="qs-qcards">${cards}</div><div class="card qs-table"><table class="table"><thead><tr><th scope="col">Quest</th><th scope="col">Lvl</th><th scope="col">Zone</th><th scope="col">Faction</th><th scope="col">Status</th><th scope="col">Attempts</th></tr></thead><tbody>${tr}</tbody></table></div>`;
}

// The chosen order applied to the matched list. An unmeasured level or
// attempt count sorts last, never as zero.
function sorted(list, sort) {
  const byTitle = (a, b) => String(a.title || "").localeCompare(String(b.title || ""));
  if (sort === "level") return [...list].sort((a, b) => (num(a.level) ?? Infinity) - (num(b.level) ?? Infinity) || byTitle(a, b));
  if (sort === "attempts") return [...list].sort((a, b) => (num(b.attempts) ?? -1) - (num(a.attempts) ?? -1) || byTitle(a, b));
  if (sort === "title") return [...list].sort(byTitle);
  return list;
}

// The sticky line names every active filter. Empty when nothing is filtered.
function filterWords(f) {
  const parts = [];
  if (f.status) parts.push(STATUS[f.status][0]);
  if (f.faction) parts.push(sideName(f.faction));
  if (f.zone) parts.push(f.zone);
  if (f.lo !== null && f.hi !== null) parts.push("levels " + f.lo + " to " + f.hi);
  else if (f.lo !== null) parts.push("level " + f.lo + " and up");
  else if (f.hi !== null) parts.push("up to level " + f.hi);
  if (f.text) parts.push('"' + f.text + '"');
  return parts;
}

export function catalogueBody(data, q) {
  const f = filters(q);
  const all = data.quests || [];
  const match = sorted(all.filter((x) => keep(x, f)), f.sort);
  if (!all.length) return state("empty", "No quests", "The server sent an empty catalogue.");
  if (!match.length) {
    return html`${state("empty", "No quests match", "No quest fits every filter you have on. Nothing is hidden by the server.")}<div><button type="button" class="btn btn-ghost" data-clear>Clear filters</button></div>`;
  }
  const n = limitFor(q);
  const more = match.length > n ? html`<button type="button" class="btn btn-secondary qs-more" data-more>Show ${Math.min(step(), match.length - n)} more</button>` : "";
  const words = filterWords(f);
  const active = words.length ? html`<span class="qs-active">${words.join(SEP)}</span><button type="button" class="btn btn-ghost qs-clear" data-clear>Clear filters</button>` : "";
  return html`<div class="qs-sticky"><p class="dim qs-s" data-region="count">${match.length.toLocaleString("en-US")} of ${all.length.toLocaleString("en-US")} quests${match.length > n ? ", the first " + n + " shown" : ""}</p>${active}</div>${rows(match.slice(0, n), q)}${more}`;
}

// A faction or zone is server text. `html` escapes every interpolated value,
// quotes included, so one holding `"` or `<` stays inside value="..." and the
// option's text; the only markup passed through unescaped is raw(" selected").
// `blank` is the empty option's word ("All" on a filter); pass null where
// every option is a real value, as the sort's are.
function select(id, label, value, options, blank = "All") {
  const empty = blank === null ? "" : html`<option value="">${blank}</option>`;
  return html`<label class="qs-field"><span class="qs-s dim">${label}</span><select class="input" id="${id}" aria-label="${label}">${empty}${options.map(([v, text]) => html`<option value="${v}"${v === value ? raw(" selected") : ""}>${text}</option>`)}</select></label>`;
}

function controls(data, q) {
  const f = filters(q);
  const all = data.quests || [];
  const uniq = (xs) => [...new Set(xs.filter(known))].sort((a, b) => String(a).localeCompare(String(b)));
  // The zones offered are the chosen side's (its own and both sides'), or every zone.
  const zones = uniq(all.filter((x) => keep(x, { ...f, zone: "", status: "", lo: null, hi: null, text: "" })).map(zoneOf));
  if (f.zone && !zones.includes(f.zone)) zones.unshift(f.zone);
  return html`<div class="qs-controls"><label class="qs-search"><i class="ph ph-magnifying-glass" aria-hidden="true"></i><input class="input" id="qs-q" type="search" placeholder="Search quests by name, zone or id" value="${q.q || ""}" aria-label="Search quests" autocomplete="off"></label>
${select("qs-faction", "Faction", f.faction, SIDES)}${select("qs-zone", "Zone", f.zone, zones.map((v) => [v, v]))}${select("qs-status", "Status", f.status, STATUS_FILTER.map((k) => [k, STATUS[k][0]]))}${select("qs-sort", "Sort", f.sort, [["server", "Server order"], ["level", "Level"], ["attempts", "Most attempts"], ["title", "Title"]], null)}
<fieldset class="qs-field qs-levels"><legend class="qs-s dim">Level</legend><span class="row"><input class="input" id="qs-lo" type="number" inputmode="numeric" min="1" max="80" placeholder="From" aria-label="Lowest level" value="${f.lo === null ? "" : f.lo}"><span class="dim">to</span><input class="input" id="qs-hi" type="number" inputmode="numeric" min="1" max="80" placeholder="To" aria-label="Highest level" value="${f.hi === null ? "" : f.hi}"></span></fieldset></div>`;
}

// ---- one quest ------------------------------------------------------------------------

function attempt(a) {
  const when = a.finished ? "finished " + since(a.finished) : a.first_taken ? "taken " + since(a.first_taken) : "";
  return html`<li class="card qs-attempt"><span class="row qs-between"><span>${a.character ? html`<a class="mname" href="${memberHref(a.character, "quests")}">${a.character}</a>` : notMeasured("quester not measured")}${a.guild ? html` <span class="dim qs-s">${a.guild}</span>` : ""}</span>${statusTag(a.state)}</span>
${when ? html`<span class="dim qs-s">${when}</span>` : ""}${a.reason ? html`<p class="qs-reason">${a.reason}</p>` : a.state === "broken" ? html`<p class="qs-reason">${notMeasured("no reason recorded")}</p>` : ""}</li>`;
}

// A ticket renders only as an object with an https url: the link comes from a
// read, and anything else is not a link to follow.
function ticketLink(ticket) {
  if (!ticket || typeof ticket !== "object" || !isHttps(ticket.url)) return "";
  return html` <a class="qs-s" href="${ticket.url}" target="_blank" rel="noopener">Ticket #${ticket.number}</a>`;
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
  const line = html`${statusTag(x.status)} <span class="dim">L${levelText(x)} | ${zoneOf(x) || "zone not measured"} | ${x.faction ? sideName(x.faction) : "faction not measured"}</span>${ticketLink(x.ticket)}`;
  return html`${back}${pageHead(x.title || "Quest " + ctx.params.id, line)}${sectionHead("", "Attempts", plural(list.length, "attempt"))}${list.length ? html`<ol class="qs-attempts">${list.map(attempt)}</ol>` : state("empty", "No attempts yet", "No quester has tried this quest.")}`;
}

// ---- the page ---------------------------------------------------------------------------

function summary(data) {
  const t = data.totals || {};
  const n = (k) => (num(t[k]) || 0).toLocaleString("en-US");
  if (num(t.quests) === null) return "";
  return n("completed") + " quests completed and " + n("broken") + " found broken, of " + n("quests") + ".";
}

// The door to the actionable sets: the broken and the taken, counted off the
// read's own totals, one tap each to the catalogue already filtered there.
function chips(data) {
  const t = data.totals || {};
  if (num(t.quests) === null) return "";
  const chip = (status, label) => html`<a class="qs-chip" href="${build(["quests"], { status })}">${label}${SEP}${count(t[status])}</a>`;
  return html`<div class="qs-chips">${chip("broken", "Broken")}${chip("taken", "Taken")}</div>`;
}

let catalogueShortcut = "";

function focusCatalogue(catalogue) {
  catalogue.focus({ preventScroll: true });
  catalogue.scrollIntoView({ block: "start" });
}

export default {
  css: ["views/quests.css"],
  reads: (ctx) => (ctx.params.id ? [questPath(ctx.params.id)] : [QUESTERS, QUESTS]),
  every: 30000,
  title: (ctx) => (ctx.params.id ? "Quest " + ctx.params.id : "Quests"),
  render(ctx) {
    narrow = !!ctx.isPhone;
    if (ctx.params.id) return html`<div class="qs">${questPage(ctx)}</div>`;
    const quests = ctx.get(QUESTS);
    const ok = ready(quests);
    const q = liveQuery();
    const wait = pendingRead(quests, 4);
    const cover = wait || (ok ? coverage(quests.data) : state("unmeasured", "Quests not measured", "The quests read answered with no catalogue."));
    const cat = ok ? html`${controls(quests.data, q)}<div data-region="catalogue">${catalogueBody(quests.data, q)}</div>` : wait || "";
    return html`<div class="qs">${pageHead("Quests", ok ? summary(quests.data) : "")}${ok ? chips(quests.data) : ""}${sectionHead("", "Quester parties")}<p class="dim qs-s qs-parties-note">Two dedicated parties proving every quest can be played, one per guild.</p>${parties(ctx.get(QUESTERS))}${sectionHead("", "Coverage")}${cover}${sectionHead("", "Catalogue")}<section class="qs-catalogue" tabindex="-1" id="quest-catalogue" aria-label="Quest catalogue">${cat}</section></div>`;
  },
  after(main, ctx) {
    if (ctx.params.id) return;
    narrow = !!ctx.isPhone;
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
    on("qs-sort", "change", () => redraw(setQuery({ sort: val("qs-sort") })));
    on("qs-status", "change", () => {
      const q2 = setQuery({ status: val("qs-status") });
      redraw(q2);
      // A broken list with no sort chosen changes order under the reader
      // (most attempts first); keep the select honest about it.
      const s = main.querySelector("#qs-sort");
      if (s) s.value = filters(q2).sort;
    });
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
    // Keep the link's native hash navigation, so the router redraws and
    // records the visit. Rebinding a shortcut replaces its old handler.
    const shortcuts = main.querySelector(".qs-chips");
    if (shortcuts) shortcuts.onclick = (event) => {
      if (event.defaultPrevented || event.button !== 0 || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
      const link = event.target.closest("a.qs-chip");
      const href = link && link.getAttribute("href");
      if (!href) return;
      if (location.hash === href) {
        event.preventDefault();
        focusCatalogue(main.querySelector(".qs-catalogue"));
      } else {
        catalogueShortcut = href;
      }
    };
    if (catalogueShortcut && ctx.hash === catalogueShortcut) {
      const href = catalogueShortcut;
      catalogueShortcut = "";
      // The router resets scroll and focus after drawing a new hash.
      window.requestAnimationFrame(() => {
        const current = main.querySelector(".qs-catalogue");
        if (current && location.hash === href) focusCatalogue(current);
      });
    }
    on("qs-faction", "change", () => redrawAll(setQuery({ faction: val("qs-faction"), zone: "" }), "qs-faction"));
    region.addEventListener("click", (e) => {
      if (e.target.closest("[data-more]")) {
        shown.n += step();
        redraw(liveQuery());
      } else if (e.target.closest("[data-clear]")) {
        redrawAll(setQuery({ faction: "", zone: "", lvl: "", status: "", q: "" }), "qs-q");
      }
    });
  },
};
