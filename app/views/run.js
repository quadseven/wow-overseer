// One guild run: #/runs/<id>. Progress, seats and the timeline.
//
// The run comes from /api/guildruns (the groups out now and the recent ones
// back). The timeline is the coordinator's own steps (formed, its lines, how
// it came back) with what each seat said while the run lasted, from
// /api/thoughts, read once per visit after the run itself is known.

import { html, raw, state, pendingRead, plural, member } from "../ui.js";
import { load, peek } from "../api.js";
import {
  utc, since, findRun, stateTag, pips, bossText, chose, cause, seatRows,
  steps, clock, inside,
} from "./_runs.js";
import { guilds, guildSlug, firstGuild } from "../families.js";

const THOUGHTS = 30;
const SHOWN = 40;

function runPath(id) { return "/api/v2/run?id=" + encodeURIComponent(id); }

function thoughtsPath(name) { return "/api/thoughts?name=" + encodeURIComponent(name) + "&limit=" + THOUGHTS; }

function guildKey(r) {
  return guildSlug(r.guild) || firstGuild();
}

// What the seats said between the run forming and coming back, oldest first.
// Null while any seat's read is still on its way.
function said(r) {
  const from = utc(r.created_at);
  const to = utc(r.ended_at) || Date.now() / 1000;
  const reads = (r.members || []).map((m) => [m.name, peek(thoughtsPath(m.name))]);
  if (reads.some(([, t]) => t.data === undefined && !t.error)) return null;
  const out = [];
  reads.forEach(([name, t]) => {
    ((t.data && t.data.thoughts) || []).forEach((x) => {
      const at = utc(x.created_at);
      if (at && from && at >= from && at <= to) out.push({ t: at, who: name, text: x.text });
    });
  });
  return {
    list: out.sort((a, b) => a.t - b.t).slice(-SHOWN),
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

function timeline(r) {
  const own = steps(r).filter((s) => s.t);
  const heard = said(r);
  const rows = own.concat(heard ? heard.list : []).sort((a, b) => (a.t || 0) - (b.t || 0));
  const lines = rows.map((s) => {
    const l = s.who ? seatLine(s.who, s.text, r.place) : { text: s.text };
    const who = s.who ? html`${member({ name: s.who })}${l.lead ? " " : ": "}` : "";
    return html`<div class="g-step"><span class="g-step-t">${s.t ? clock(s.t) : ""}</span><span>${who}${l.text}</span></div>`;
  });
  let note = "";
  if (!heard) note = html`<span class="muted">Reading what the seats said...</span>`;
  else if (heard.failed.length) note = html`<span class="muted">Not measured for ${heard.failed.join(", ")}: their reads did not answer.</span>`;
  else if (!heard.list.length) note = html`<span class="muted">The seats said nothing on record while the run lasted.</span>`;
  return html`<div class="g-steps">${lines}</div>${note}`;
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
    const r = findRun(ctx.params.id) || (one.data && one.data.run) || null;
    if (!r && one.data === undefined && !one.error) {
      return html`<header class="page-head"><h1>Run ${ctx.params.id}</h1></header>${pendingRead(one, 2)}`;
    }
    if (!r) {
      return html`<header class="page-head"><h1>Not found</h1></header>
${state("empty", "No run #" + ctx.params.id + " in the guild runs the realm has recorded.", raw(guilds().map((g) => html`<a href="${"#/guilds/" + g.slug + "/runs"}">${g.name} runs</a>`.s).join(" | ")))}`;
    }
    const g = guildKey(r);
    const when = r.state === "inside" ? "started " + since(utc(r.created_at)) : since(utc(r.ended_at) || utc(r.created_at));
    const extra = [plural(r.deaths || 0, "death"), inside(r), r.loot_items ? plural(r.loot_items, "item") + " looted" : ""].filter(Boolean).join(" | ");
    return html`<a class="g-r-back" href="${"#/guilds/" + g + "/runs"}"><i class="ph ph-caret-left" aria-hidden="true"></i>${r.guild} runs</a>
<header class="g-r-head"><h1>${r.place || "A dungeon"}</h1><span class="muted">run #${r.id} | ${r.guild} | ${when}</span>${stateTag(r)}</header>
<div class="g-r-grid">
<div class="g-r-col">
<div class="card"><span class="muted">${bossText(r)}</span>${pips(r, "g-pips-lg")}
${chose(r) ? html`<span class="muted">${chose(r)}</span>` : ""}
${cause(r) ? html`<span>${cause(r)}</span>` : ""}
${r.story ? html`<span class="muted">${r.story}</span>` : ""}
<span class="muted">${extra}${r.band_line ? " | " + r.band_line : ""}</span></div>
<div class="card g-list"><div class="g-list-head"><span class="g-card-title">Seats</span><span class="muted">${plural((r.members || []).length, "seat")}</span></div>${seatRows(r)}</div>
</div>
<div class="card g-r-timeline"><span class="g-card-title">Timeline</span><div id="g-r-timeline">${timeline(r)}</div></div>
</div>`;
  },
  after(main, ctx) {
    const r = findRun(ctx.params.id);
    if (!r) return;
    const box = main.querySelector("#g-r-timeline");
    // Read once per visit, and again when what is held is over a minute old.
    const missing = (r.members || []).filter((m) => {
      const t = peek(thoughtsPath(m.name));
      return (t.data === undefined && !t.error) || (t.at && Date.now() - t.at > 60000);
    });
    if (!missing.length) return;
    Promise.all(missing.map((m) => load(thoughtsPath(m.name)))).then(() => {
      if (box.isConnected) box.innerHTML = timeline(r).s;
    });
  },
};

