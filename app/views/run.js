// One guild run: #/runs/<id>. Progress, seats and the timeline.
//
// The run comes from /api/v2/run (the one run, with its gear, bosses and
// wipes); the /api/guildruns row (the groups out now and the recent ones
// back) stands in while that read is on its way. The timeline is the coordinator's own steps (formed, its lines, how
// it came back) with what each seat said while the run lasted, from
// /api/thoughts, read once per visit after the run itself is known.

import { html, raw, state, pendingRead, plural, member, item, readState, duration, ago } from "../ui.js";
import { load, peek } from "../api.js";
import {
  findRun, stateTag, runState, pips, seatRows, steps, isInside,
} from "./_runs.js";
import { toSeconds, fromClock, ageOf, nowSeconds, since, clock } from "../models/time.js";
import { formedAt, endedAt, lastAt, chose, cause } from "../models/guildruns.js";
import { guilds, guildSlug, firstGuild } from "../families.js";

const THOUGHTS = 30;
const SHOWN = 40;

// The timeline filter the reader last picked, kept across the view's
// redraws; a different run starts back at All.
let tlFilter = "all";
let tlRun = null;

function runPath(id) { return "/api/v2/run?id=" + encodeURIComponent(id); }

function thoughtsPath(name) { return "/api/thoughts?name=" + encodeURIComponent(name) + "&limit=" + THOUGHTS; }

// The run to draw. The one-run read (/api/v2/run) is the same run_view as the
// /api/guildruns row plus its gear, bosses and wipes, so it wins once it has
// answered; the list row stands in only while that read is on its way (or if
// it failed), and is all an older run's page lacks until then.
function theRun(ctx) {
  const one = ctx.get(runPath(ctx.params.id));
  return (one.data && one.data.run) || findRun(ctx.params.id) || null;
}

// A read that failed says nothing about the run; a 404 says there is no such run.
export function readFailed(read) {
  return Boolean(read.error) && read.error.message !== "HTTP 404";
}

// True while the one-run read has neither answered nor failed: the gear the
// list row lacks is still being read, not missing.
function byIdPending(ctx) {
  const one = ctx.get(runPath(ctx.params.id));
  return one.data === undefined && !one.error;
}

function guildKey(r) {
  return guildSlug(r.guild) || firstGuild();
}

// What the seats said between the run forming and coming back, oldest first.
// Null while any seat's read is still on its way.
function said(r) {
  const from = formedAt(r);
  const to = endedAt(r) || nowSeconds();
  const reads = (r.members || []).map((m) => [m.name, peek(thoughtsPath(m.name))]);
  if (reads.some(([, t]) => readState(t) === "loading")) return null;
  const out = [];
  reads.forEach(([name, t]) => {
    ((t.data && t.data.thoughts) || []).forEach((x) => {
      const at = toSeconds(x.created_at);
      if (at && from && at >= from && at <= to) out.push({ t: at, who: name, text: x.text });
    });
  });
  return {
    list: out.sort((a, b) => a.t - b.t),
    failed: reads.filter(([, t]) => t.error).map(([n]) => n),
  };
}

// What a seat said, as its timeline line: {lead, text}. A line that already
// starts with the seat's name ("Durg entered The Deadmines.") is drawn with
// the name once, as its subject, and not as "Durg: Durg entered".
//
// Lines the world narrated before maps were named say "crossed into an
// unknown place". That fallback was written only for a map outside the four
// continents, and the only such map a seat crosses into while its run lasts
// is the run's dungeon, so the line names it.
export function seatLine(name, text, place) {
  let t = String(text || "");
  if (place) t = t.replace(/\bcrossed into an unknown place\b/, "entered " + place);
  const own = name && t.startsWith(name + " ");
  return { lead: !!own, text: own ? t.slice(name.length + 1) : t };
}

export function bossEvents(r) {
  const out = [];
  (r.bosses || []).forEach((b) => {
    if (b.killed) out.push({ t: toSeconds(b.at), kind: "boss", text: "The group killed " + b.name + "." });
  });
  (r.wipes || []).forEach((w) => {
    out.push({ t: toSeconds(w.at), kind: "boss", text: w.deaths + " death" + (w.deaths === 1 ? "" : "s") + " to " + (w.name || "a boss") + "." });
  });
  return out;
}

// The timeline's filters: everything, the boss kills and wipes, or the loot.
const TL_FILTERS = [["all", "All"], ["boss", "Bosses and wipes"], ["loot", "Loot"]];

// The timeline: the coordinator's steps, what the seats said, the gear and
// the boss kills and wipes, as one list. While the run is inside it reads
// newest first, so the latest thing is at the top where a reader looks;
// once the run is back it reads oldest first, as the story of the run. Only
// the last SHOWN events are drawn, and the line says so when that cap
// bites instead of silently dropping the rest.
export function timeline(r, filter) {
  const kind = filter || "all";
  const own = steps(r).filter((s) => s.t).map((s) => ({ ...s, kind: "other" }));
  const heard = said(r);
  const gear = (r.gear || []).map((g) => ({ t: toSeconds(g.at), who: g.member, kind: "loot",
    text: g.source === "equipped" ? "equipped " + g.name + "."
      : g.source === "won by loot council" ? "was awarded " + g.name + " by the loot council."
      : "looted " + g.name + "." }));
  const rows = own
    .concat(heard ? heard.list.map((h) => ({ ...h, kind: "other" })) : [], gear, bossEvents(r))
    .sort((a, b) => (a.t || 0) - (b.t || 0));
  const picked = kind === "all" ? rows : rows.filter((x) => x.kind === kind);
  const capped = picked.length > SHOWN;
  const last = picked.slice(-SHOWN);
  const ordered = isInside(r) ? last.slice().reverse() : last;
  const lines = ordered.map((s) => {
    const l = s.who ? seatLine(s.who, s.text, r.place) : { text: s.text };
    const who = s.who ? html`${member({ name: s.who })}${l.lead ? " " : ": "}` : "";
    return html`<div class="g-step"><span class="g-step-t">${s.t ? clock(s.t) : ""}</span><span>${who}${l.text}</span></div>`;
  });
  let note = "";
  if (!heard) note = html`<span class="muted">Reading what the seats said...</span>`;
  else if (heard.failed.length) note = html`<span class="muted">Not measured for ${heard.failed.join(", ")}: their reads did not answer.</span>`;
  else if (!heard.list.length) note = html`<span class="muted">The seats said nothing on record while the run lasted.</span>`;
  const cap = capped ? html`<span class="muted">Showing the last ${SHOWN} events</span>` : "";
  return html`<div class="g-steps">${lines}</div>${cap}${note}`;
}

function gearRows(r) {
  const rows = r.gear || [];
  return html`<div class="card g-list"><div class="g-list-head"><span class="g-card-title">Gear</span></div>${rows.length ? rows.map((g) => html`<div class="g-row g-r-gear"><span>${member({ name: g.member })}</span><span class="g-grow">${item({ entry: g.entry, name: g.name, quality: g.quality })}</span><span class="muted">${g.source}</span></div>`) : html`<div class="g-row muted">No gear recorded for this run.</div>`}</div>`;
}

function gearReading() {
  return html`<div class="card g-list"><div class="g-list-head"><span class="g-card-title">Gear</span></div><div class="g-row muted">Reading the gear...</div></div>`;
}

// The dungeon's bosses as named segments: killed bosses in color, the rest
// dim, each name readable on a phone. Past eight bosses a named cell would
// be a sliver (23 bosses at 15px each, every name truncated to nothing), so
// the strip becomes a segmented bar with no names and the groups below the
// bar carry the names instead.
export function bossPips(r) {
  const bosses = r.bosses || [];
  if (Array.isArray(r.bosses) && unverified(r)) {
    return pips(r, "g-pips-lg", {
      unknown: true,
      label: "Boss count unverified: the count says " + (Number(r.bosses_done) || 0) + " of " + (Number(r.bosses_total) || 0) + " down, but the record names " + bosses.filter((b) => b.killed).length + " kills",
    });
  }
  if (!bosses.length || bosses.length > NAMED_MAX) return pips(r, "g-pips-lg");
  const cells = bosses.map((b) => html`<div class="g-r-pip ${b.killed ? "done" : ""}"><span class="g-r-pip-bar"></span><span class="g-r-pip-name">${b.name}</span></div>`);
  const done = bosses.filter((b) => b.killed).length;
  return html`<div class="g-r-pips" role="img" aria-label="${done + " of " + bosses.length + " bosses down"}">${cells}</div>`;
}

// The bosses under the bar, in the three groups a reader scans for: Down
// (with kill times and who landed the blow), Next (the first unkilled, in
// full colour and marked), and Still to come (muted). Past eight bosses the
// last group folds behind a 44px toggle, so a 23-boss dungeon does not push
// the rest of the page a full screen down.
export function bossGroups(r) {
  const bosses = r.bosses || [];
  if (!bosses.length) return "";
  const down = bosses.filter((b) => b.killed);
  const up = bosses.filter((b) => !b.killed);
  const next = up[0] || null;
  const rest = up.slice(1);
  const row = (b, mark) => html`<div class="g-r-boss ${b.killed ? "killed" : mark ? "next" : ""}"><span class="g-r-boss-name">${b.name}</span>${b.killed ? html`<span class="muted">${clock(toSeconds(b.at))}${b.by ? " - " + member({ name: b.by }) : ""}</span>` : mark ? html`<span class="tag tag-warn">NEXT</span>` : ""}</div>`;
  const parts = [];
  if (down.length) parts.push(html`<div class="g-r-group"><div class="g-r-group-h">Down</div>${down.map((b) => row(b))}</div>`);
  if (next) parts.push(html`<div class="g-r-group"><div class="g-r-group-h">Next</div>${row(next, true)}</div>`);
  if (rest.length) {
    if (bosses.length > NAMED_MAX) {
      parts.push(html`<details class="g-r-more"><summary>Still to come, ${rest.length} more ${rest.length === 1 ? "boss" : "bosses"}</summary>${rest.map((b) => row(b))}</details>`);
    } else {
      parts.push(html`<div class="g-r-group"><div class="g-r-group-h">Still to come</div>${rest.map((b) => row(b))}</div>`);
    }
  }
  return html`<div class="g-r-groups">${parts}</div>`;
}

// ---- the lead card ---------------------------------------------------------

// Past this many bosses the strip is a segmented bar and the Still to come
// group folds: a named cell per boss would be a sliver at phone width.
const NAMED_MAX = 8;

// Seconds the run has been inside, as the lead shows it. For a run still
// inside, counted from when it formed to now, so the figure moves as the
// page redraws instead of freezing at the read's snapshot; for one back,
// the run's own seconds inside, or its formed-to-ended span.
export function insideSeconds(r, now) {
  if (isInside(r)) {
    const formed = formedAt(r);
    if (formed) return Math.max(0, (now === undefined ? nowSeconds() : now) - formed);
  }
  const s = Number(r.seconds_inside);
  if (s) return s;
  const formed = formedAt(r);
  const ended = endedAt(r);
  return formed && ended ? Math.max(0, ended - formed) : null;
}

// The stall line: how long since the last boss kill, for a run still
// inside. It is the one line that separates a stalled run from a healthy
// slow one, so it is always there while the run is in: past 25 minutes it
// warns, past 40 it is bad. A kill the count claims but no row names cannot
// be timed, so the line says so and counts from the start instead; a run
// with no kill yet counts from the start too.
export function stallLine(r, now) {
  if (!isInside(r)) return null;
  const at = now === undefined ? nowSeconds() : now;
  const kills = (r.bosses || [])
    .filter((b) => b.killed)
    .map((b) => toSeconds(b.at))
    .filter((t) => t !== null);
  const formed = formedAt(r);
  let text;
  let age;
  if (kills.length) {
    age = at - Math.max(...kills);
    text = "Last boss " + ago(age);
  } else if (formed || Number(r.seconds_inside)) {
    age = formed ? at - formed : Number(r.seconds_inside);
    text = (Number(r.bosses_done) || 0) > 0
      ? "Last boss not named in the record, " + (duration(age) || "0m") + " inside"
      : "No boss down yet, " + (duration(age) || "0m") + " in";
  } else {
    return null;
  }
  const tone = age > 40 * 60 ? "bad" : age > 25 * 60 ? "warn" : "";
  return { text, tone };
}

// The honesty rule for a count that stands alone: when the run's counted
// bosses and the kills its record names disagree, the count is not a fact
// the page may state. Returns the sentence to print, or null when the named
// list accounts for the count (or no named list has answered yet, which is
// a read on its way, not a verdict). The server leaves the list empty when
// its kill rows do not account for the count, so an empty list under a
// positive count is exactly this case.
export function unverified(r) {
  if (!Array.isArray(r.bosses)) return null;
  const total = Number(r.bosses_total) || 0;
  if (!total) return null;
  const done = Number(r.bosses_done) || 0;
  const named = r.bosses.filter((b) => b.killed).length;
  if (named === done) return null;
  if (!named) {
    return "Count says " + done + " of " + total + " down, but no boss kills are named in the record. Treat this run as unverified.";
  }
  if (named < done) {
    return "Count says " + done + " of " + total + " down, but the record names only " + named + " boss kill" + (named === 1 ? "" : "s") + ". Treat this run as unverified.";
  }
  return "Count says " + done + " of " + total + " down, but the record names " + named + " boss kills. Treat this run as unverified.";
}

// The honesty rule for a run that ended short: it prints its shortfall
// instead of keeping a green check. The final boss is named only when the
// named list shows it still up; a run that never went in has no boss count
// to fall short of.
export function shortfall(r) {
  if (isInside(r) || !endedAt(r)) return null;
  if (["refused", "not entered"].includes(r.outcome || r.run_state || "") && !Number(r.seconds_inside)) return null;
  const total = Number(r.bosses_total) || 0;
  const done = Number(r.bosses_done) || 0;
  if (!total || done >= total) return null;
  let s = "Ended with " + (total - done) + " of " + total + " bosses still up";
  const bosses = r.bosses || [];
  if (bosses.length && !bosses[bosses.length - 1].killed) s += ", including the final boss";
  return s + ".";
}

// The lead's first line, large: where the run is, and the boss count as a
// sentence ("Inside now, 2 of 23 bosses down"). A run with no boss count
// measured gets the state word alone, and so does an unverified one: its
// count is the thing in dispute.
export function stateSentence(r) {
  const s = runState(r);
  const lead = s.text.charAt(0).toUpperCase() + s.text.slice(1);
  const total = Number(r.bosses_total) || 0;
  if (!total || unverified(r)) return lead;
  return lead + ", " + (Number(r.bosses_done) || 0) + " of " + total + " bosses down";
}

// The header's state tag. A run that ended short does not carry the green
// check its state word would otherwise give it; the shortfall sentence in
// the lead says why. A tag that already reads bad (a wipe) keeps its tone.
function leadTag(r) {
  const s = runState(r);
  if (!shortfall(r) || s.tone !== "ok") return stateTag(r);
  return html`<span class="tag g-run-tag" data-gt="warn"><i class="ph ph-warning-circle" aria-hidden="true"></i>${s.text}</span>`;
}

// The lead card and nothing else in it: the state sentence, the three
// figures a reader checks mid run, the stall line, then the progress bar
// and the boss list. Who proposed the run, why it went and how it came back
// live in the timeline's steps, not stacked on top of these facts.
export function leadCard(r, now) {
  const total = Number(r.bosses_total) || 0;
  const secs = insideSeconds(r, now);
  const stall = stallLine(r, now);
  const unv = unverified(r);
  const short = unv ? null : shortfall(r);
  return html`<div class="card g-r-lead"><span class="g-r-state">${stateSentence(r)}</span>
${unv ? html`<span class="g-r-unverified">${unv}</span>` : ""}
${short ? html`<span class="g-r-shortfall">${short}</span>` : ""}
<div class="g-r-figs"><div class="g-r-fig"><span class="g-r-fig-v">${unv ? "unverified" : total ? (Number(r.bosses_done) || 0) + " / " + total : "not measured"}</span><span class="g-r-fig-l">Bosses</span></div><div class="g-r-fig"><span class="g-r-fig-v">${secs !== null ? duration(secs) : "not measured"}</span><span class="g-r-fig-l">Time inside</span></div><div class="g-r-fig"><span class="g-r-fig-v">${Number(r.deaths) || 0}</span><span class="g-r-fig-l">Deaths</span></div></div>
${stall ? html`<span class="g-r-stall" data-gt="${stall.tone}">${stall.text}</span>` : ""}
${bossPips(r)}${bossGroups(r)}</div>`;
}

// The run's own lines, in their own card under the lead rather than
// stacked on it: why it went (chose), how it came back (cause), its story,
// and the loot count and level band the lead's figures do not carry.
export function runNotes(r) {
  const bits = [];
  if (chose(r)) bits.push(html`<span class="muted">${chose(r)}</span>`);
  if (cause(r)) bits.push(html`<span>${cause(r)}</span>`);
  if (r.story) bits.push(html`<span class="muted">${r.story}</span>`);
  const meta = [r.loot_items ? plural(r.loot_items, "item") + " looted" : "", r.band_line || ""].filter(Boolean).join(" | ");
  if (meta) bits.push(html`<span class="muted">${meta}</span>`);
  return bits.length ? html`<div class="card g-r-notes">${bits}</div>` : "";
}

// The bosses as one flat list, with kill times and who landed the killing
// blow. The lead card draws the grouped form (bossGroups); this flat form
// stays as the module's plain list of the same facts.
export function bossRows(r) {
  const bosses = r.bosses || [];
  if (!bosses.length) return "";
  return html`<div class="g-r-bosses">${bosses.map((b) => html`<div class="g-r-boss ${b.killed ? "killed" : ""}"><span class="g-r-boss-name">${b.name}</span>${b.killed ? html`<span class="muted">${clock(toSeconds(b.at))}${b.by ? " - " + member({ name: b.by }) : ""}</span>` : html`<span class="muted">no kill recorded</span>`}</div>`)}</div>`;
}

export default {
  css: ["views/guild.css"],
  every: 15000,
  // The runs out now and the last thirty back come with /api/guildruns; an
  // older run (the chronicle links them) is read on its own by id.
  reads: (ctx) => ["/api/guildruns", runPath(ctx.params.id)],
  title: (ctx) => "Run " + ctx.params.id,
  render(ctx) {
    const gr = peek("/api/guildruns");
    const wait = pendingRead(gr, 2);
    if (wait) return html`<header class="page-head"><h1>Run ${ctx.params.id}</h1></header>${wait}`;
    const one = ctx.get(runPath(ctx.params.id));
    const r = theRun(ctx);
    const reading = byIdPending(ctx);
    // A failed read says nothing about the run, so it is not told as a missing one.
    if (!r && (reading || readFailed(one))) {
      return html`<header class="page-head"><h1>Run ${ctx.params.id}</h1></header>${pendingRead(one, 2)}`;
    }
    if (!r) {
      return html`<header class="page-head"><h1>Not found</h1></header>
${state("empty", "No run #" + ctx.params.id + " in the guild runs the realm has recorded.", raw(guilds().map((g) => html`<a href="${"#/guilds/" + g.slug + "/runs"}">${g.name} runs</a>`.s).join(" | ")))}`;
    }
    if (tlRun !== String(ctx.params.id)) { tlRun = String(ctx.params.id); tlFilter = "all"; }
    const g = guildKey(r);
    const when = r.state === "inside" ? "started " + since(formedAt(r)) : since(lastAt(r));
    const upd = Math.max(one.at || 0, gr.at || 0);
    const fresh = upd ? " | updated " + clock(fromClock(upd)) + " | refreshes every 15 seconds" : "";
    return html`<a class="g-r-back" href="${"#/guilds/" + g + "/runs"}"><i class="ph ph-caret-left" aria-hidden="true"></i>${r.guild} runs</a>
<header class="g-r-head"><h1>${r.place || "A dungeon"}</h1><span class="muted">run #${r.id} | ${r.guild} | ${when}${fresh}</span>${leadTag(r)}</header>
<div class="g-r-grid">
<div class="g-r-col">
${leadCard(r)}${runNotes(r)}
<div class="card g-list"><div class="g-list-head"><span class="g-card-title">Seats</span><span class="muted">${plural((r.members || []).length, "seat")}</span></div>${seatRows(r)}</div>
${reading ? gearReading() : gearRows(r)}
</div>
<div class="card g-r-timeline"><div class="g-r-tl-head"><span class="g-card-title">Timeline</span><span class="muted">${isInside(r) ? "Newest first" : "Oldest first"}</span></div><div class="g-r-filters" role="group" aria-label="Timeline filter">${TL_FILTERS.map(([k, label]) => html`<button type="button" class="chip" data-tl-filter="${k}" aria-pressed="${tlFilter === k ? "true" : "false"}">${label}</button>`)}</div><div id="g-r-timeline">${timeline(r, tlFilter)}</div></div>
</div>`;
  },
  after(main, ctx) {
    const r = theRun(ctx);
    if (!r) return;
    const box = main.querySelector("#g-r-timeline");
    main.querySelectorAll("[data-tl-filter]").forEach((c) => c.addEventListener("click", () => {
      tlFilter = c.getAttribute("data-tl-filter") || "all";
      main.querySelectorAll("[data-tl-filter]").forEach((x) => x.setAttribute("aria-pressed", String(x.getAttribute("data-tl-filter") === tlFilter)));
      if (box) box.innerHTML = timeline(r, tlFilter).s;
    }));
    // Read once per visit, and again when what is held is over a minute old.
    const missing = (r.members || []).filter((m) => {
      const t = peek(thoughtsPath(m.name));
      return readState(t) === "loading" || ageOf(fromClock(t.at)) > 60;
    });
    if (!missing.length) return;
    Promise.all(missing.map((m) => load(thoughtsPath(m.name)))).then(() => {
      if (box.isConnected) box.innerHTML = timeline(r, tlFilter).s;
    });
  },
};

