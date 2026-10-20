// Guild progress at the foot of Now: each guild's dungeon ladder, its top
// blocker and, in the card's foot, its level 60 projection, read from /api/v2/guild,
// /api/v2/series and /api/v2/stuck. Nothing here is guessed: a value the
// realm does not report is said quietly as not measured.

import { html, notMeasured, plural } from "../../ui.js";
import { ageOf } from "../../models/time.js";

// The guild series' own level 60 answer (/api/v2/series level_60_projection,
// #1256): {at} the date at the members' measured rates (unix seconds), or
// {why} naming each member with no rate. The page used to do this sum itself
// and could only say "not measured"; the series now does it and says who and
// why. null when the bridge predates the field, so the card says nothing.
export function projection(series) {
  const p = series && series.level_60_projection;
  if (!p || typeof p !== "object") return null;
  const at = p.at === null || p.at === undefined || !Number.isFinite(Number(p.at)) ? null : Number(p.at);
  const why = typeof p.why === "string" ? p.why.trim() : "";
  if (at === null && !why) return null;
  return { at, why };
}

export function reportFacts({ guild, series, stuck, now = Date.now() / 1000 }) {
  const levels = series && series.level || [];
  const first = levels.length ? Number(levels[0][1]) : null;
  const last = levels.length ? Number(levels[levels.length - 1][1]) : null;
  const dungeons = (guild && guild.dungeons || []).map((d) => {
    const attempts = Number(d.runs || 0);
    const cleared = Number(d.cleared || 0);
    const clearsPerAttempt = attempts ? cleared / attempts : null;
    return { ...d, attempts, cleared, clearsPerAttempt, clearRate: clearsPerAttempt };
  }).sort((a, b) => Number(a.floor ?? Infinity) - Number(b.floor ?? Infinity));
  const blockers = new Map();
  const memberNames = new Set((guild && guild.members || []).map((member) => member.name));
  for (const member of (stuck && stuck.members) || []) {
    if (memberNames.size && !memberNames.has(member.name)) continue;
    const reason = String(member.blocker || member.step || "Reason not recorded");
    const age = ageOf(member.since, now);
    const row = blockers.get(reason) || { reason, members: 0, memberHours: 0 };
    row.members += 1;
    if (age !== null) row.memberHours += age / 3600;
    blockers.set(reason, row);
  }
  const topBlocker = [...blockers.values()].sort((a, b) => b.memberHours - a.memberHours)[0] || null;
  return {
    levelDelta: first === null || last === null ? null : last - first,
    dungeons,
    topBlocker,
    projection: projection(series),
  };
}

// ---- the ladder ---------------------------------------------------------------
// Every dungeon in level order, each one "cleared" (at least one clear),
// "tried" (attempts but no clear) or "open" (never tried), and the frontier:
// the lowest dungeon above the highest one cleared that is not cleared yet,
// the one already tried when two share a floor. With nothing cleared, the
// frontier is the lowest dungeon; with everything cleared, there is none.
// `dungeons` are reportFacts' rows (attempts, cleared, floor), in any order.
export function ladder(dungeons) {
  const floorOf = (d) => (d.floor === null || d.floor === undefined || !Number.isFinite(Number(d.floor)) ? Infinity : Number(d.floor));
  const steps = (dungeons || []).map((d) => {
    const attempts = Number(d.attempts ?? d.runs ?? 0) || 0;
    const cleared = Number(d.cleared || 0) || 0;
    return {
      place: d.place || d.keyword || "",
      floor: d.floor ?? null,
      ceiling: d.ceiling ?? null,
      attempts,
      cleared,
      rate: attempts ? cleared / attempts : null,
      inside: d.inside === true,
      state: cleared > 0 ? "cleared" : attempts > 0 ? "tried" : "open",
      frontier: false,
    };
  }).sort((a, b) => floorOf(a) - floorOf(b));
  let top = -1;
  steps.forEach((s, i) => { if (s.state === "cleared") top = i; });
  const above = steps.slice(top + 1);
  let frontier = null;
  if (above.length) {
    const low = floorOf(above[0]);
    const tie = above.filter((s) => floorOf(s) === low);
    frontier = tie.find((s) => s.state === "tried") || tie[0];
    frontier.frontier = true;
  }
  const count = (st) => steps.filter((s) => s.state === st).length;
  return {
    steps,
    total: steps.length,
    cleared: count("cleared"),
    tried: count("tried"),
    open: count("open"),
    frontier,
    reached: steps.filter((s) => s.state !== "open"),
    unreached: steps.filter((s) => s.state === "open"),
  };
}

function levels(s) {
  if (s.floor === null) return "L?";
  return "L" + s.floor + (s.ceiling ? "-" + s.ceiling : "");
}

function pct(rate) {
  return rate === null ? "" : Math.round(rate * 100) + "%";
}

function ladderHtml(lad, slug) {
  if (!lad.total) return html`<p class="muted">Dungeon ladder not measured.</p>`;
  const f = lad.frontier;
  const next = f
    ? html`<p class="lad-next"><span class="dim">Next up</span> <span class="b">${f.place}</span> <span class="dim">${levels(f)}${f.attempts ? ", " + plural(f.attempts, "attempt") + ", no clear yet" : ", not tried yet"}</span></p>`
    : html`<p class="lad-next"><span class="b">Every dungeon on the ladder has a clear.</span></p>`;
  const first = lad.steps[0], last = lad.steps[lad.steps.length - 1];
  const bar = html`<div class="lad-bar" aria-hidden="true">${lad.steps.map((s) => html`<span class="lad-step" data-state="${s.state}"${s.frontier ? html` data-frontier=""` : ""}${s.inside ? html` data-inside=""` : ""} title="${s.place + " " + levels(s) + ": " + s.cleared + " of " + s.attempts + " cleared"}"></span>`)}</div>
<div class="lad-axis" aria-hidden="true"><span>${levels(first).split("-")[0]}</span><span class="lad-key"><span><i data-state="cleared"></i>Cleared</span><span><i data-state="tried"></i>Tried</span><span><i data-state="open"></i>Not tried</span></span><span>L${last.ceiling ?? last.floor ?? "?"}</span></div>`;
  const rows = lad.reached.map((s) => html`<li class="lad-row${s.frontier ? " is-frontier" : ""}"><span class="lad-place">${s.inside ? html`<i class="ph-fill ph-door-open lad-in" aria-hidden="true"></i><span class="sr-only">Inside now: </span>` : ""}${s.place}</span><span class="lad-lv dim">${levels(s)}</span><span class="lad-n num">${s.cleared}<span class="dim"> / ${s.attempts}</span></span><span class="lad-rate num${s.state === "tried" ? " warn" : ""}">${pct(s.rate)}</span></li>`);
  const rest = lad.unreached.length
    ? html`<details class="lad-more"><summary>${plural(lad.unreached.length, "dungeon")} not tried yet</summary><ul>${lad.unreached.map((s) => html`<li${s.frontier ? html` class="is-frontier"` : ""}><span>${s.place}</span><span class="dim">${levels(s)}</span></li>`)}</ul></details>`
    : "";
  return html`<div class="lad">
<p class="lad-sum"><span class="lad-big num">${lad.cleared}</span><span> of ${lad.total} dungeons cleared</span><span class="dim">${lad.tried ? " | " + lad.tried + " tried without a clear" : ""}</span></p>
${bar}
${next}
${lad.reached.length ? html`<div class="lad-head dim" aria-hidden="true"><span>Tried, in level order</span><span>clears / attempts</span><span>rate</span></div><ol class="lad-list" aria-label="Dungeons tried, in level order: clears of attempts and clear rate">${rows}</ol>` : ""}
${rest}
<a class="lad-path" href="${"#/guilds/" + slug + "/runs"}">The full path and every run<i class="ph ph-caret-right" aria-hidden="true"></i></a>
</div>`;
}

function projectionLabel(at) {
  return new Date(at * 1000).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
}

// The card's foot: one quiet line, the date when the series gives one, else
// its reason; nothing at all from a bridge that does not send it.
function projectionFoot(p) {
  if (!p) return "";
  const said = [p.at !== null ? "Level 60 by " + projectionLabel(p.at) : "Level 60", p.why].filter(Boolean).join(" | ");
  return html`<p class="nr-foot muted">${said}</p>`;
}

function guildCard(ctx, guild) {
  const slug = guild.slug;
  const state = ctx.get("/api/v2/guild?guild=" + slug);
  const seriesRead = ctx.get("/api/v2/series?guild=" + slug);
  const g = state && state.data;
  const s = seriesRead && seriesRead.data;
  if (!g || !s) return html`<article class="card nr-guild"><h3>${guild.name}</h3><p class="muted">Guild metrics are not measured yet.</p></article>`;
  const facts = reportFacts({ guild: g, series: s, stuck: ctx.get("/api/v2/stuck")?.data, now: g.now });
  const delta = facts.levelDelta === null ? notMeasured("level change not measured") : (facts.levelDelta > 0 ? "+" : "") + facts.levelDelta.toFixed(1) + " median levels / 7d";
  const blocker = facts.topBlocker
    ? html`<div><dt>Top blocker</dt><dd>${facts.topBlocker.reason} <span class="dim">| ${facts.topBlocker.memberHours.toFixed(1)} member-hours across ${plural(facts.topBlocker.members, "member")}</span></dd></div>`
    : html`<div><dt>Top blocker</dt><dd class="dim">None recorded.</dd></div>`;
  return html`<article class="card nr-guild"><div class="nr-head"><h3>${guild.name}</h3><span class="nr-delta">${delta}</span></div>
${ladderHtml(ladder(facts.dungeons), slug)}
<dl class="nr-facts">${blocker}</dl>${projectionFoot(facts.projection)}</article>`;
}

export function reportSection(ctx, guilds) {
  return html`<section class="nr" aria-labelledby="nr-title"><div class="sec-row"><h2 class="kicker" id="nr-title">Guild progress</h2></div><div class="nr-grid">${guilds.map((guild) => guildCard(ctx, guild))}</div></section>`;
}
