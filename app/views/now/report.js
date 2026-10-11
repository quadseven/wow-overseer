import { html, notMeasured, plural } from "../../ui.js";
import { ageOf } from "../../models/time.js";

export function reportFacts({ guild, series, stuck, now = Date.now() / 1000 }) {
  const levels = series && series.level || [];
  const first = levels.length ? Number(levels[0][1]) : null;
  const last = levels.length ? Number(levels[levels.length - 1][1]) : null;
  const xp = series && series.xp_to_level_60_by_member || {};
  const names = Object.keys(xp);
  const byMember = series && series.by_member || {};
  const remaining = names.map((name) => xp[name]);
  const rates = names.map((name) => byMember[name] || {});
  const memberCount = Number(guild && guild.count);
  const complete = Number.isFinite(memberCount) && memberCount > 0 && names.length === memberCount
    && remaining.every(Number.isFinite)
    && rates.every((rate) => Number(rate.xp_hours_measured || 0) > 0 && Number.isFinite(Number(rate.xp_per_hour_24h)));
  const remainingXp = complete ? remaining.reduce((a, b) => a + b, 0) : null;
  const hourly = complete ? rates.reduce((sum, rate) => sum + Number(rate.xp_per_hour_24h), 0) : null;
  const projectedAt = remainingXp !== null && hourly > 0 ? now + remainingXp / hourly * 3600 : null;
  const dungeons = (guild && guild.dungeons || []).map((d) => {
    const attempts = Number(d.runs || 0);
    const cleared = Number(d.cleared || 0);
    return { ...d, attempts, cleared, clearRate: attempts ? cleared / attempts : null };
  });
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
    projectedAt,
    measuredMembers: complete ? names.length : 0,
  };
}

function projectionLabel(at) {
  return at ? new Date(at * 1000).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" }) : "not measured";
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
  const ladder = facts.dungeons.length ? html`<ol class="nr-ladder">${facts.dungeons.map((d) => html`<li><span class="nr-dungeon"><span>${d.place}</span><span class="dim">L${d.floor ?? "?"}${d.ceiling ? "-" + d.ceiling : ""}</span></span><span class="nr-clears">${d.cleared} clear${d.cleared === 1 ? "" : "s"}</span><span class="dim">${d.attempts} attempts${d.clearRate === null ? "" : " | " + Math.round(d.clearRate * 100) + "%"}</span></li>`)}</ol>` : html`<p class="muted">Dungeon ladder not measured.</p>`;
  const blocker = facts.topBlocker ? `${facts.topBlocker.reason} | ${facts.topBlocker.memberHours.toFixed(1)} member-hours across ${plural(facts.topBlocker.members, "member")}` : "No current blocker recorded.";
  return html`<article class="card nr-guild"><div class="nr-head"><h3>${guild.name}</h3><span class="nr-delta">${delta}</span></div><div><span class="kicker">Cleared dungeons | level order</span>${ladder}</div><p class="nr-blocker"><span class="kicker">Top blocker</span><span>${blocker}</span></p><p class="nr-projection"><span class="kicker">Level 60 projection</span><span>${projectionLabel(facts.projectedAt)}${facts.measuredMembers ? " | estimate from each member's measured 24h XP rate" : " | complete member XP rates not measured"}</span></p></article>`;
}

export function reportSection(ctx, guilds, agendas, roll) {
  const stuck = ctx.get("/api/v2/stuck");
  const shipped = roll && roll.data && roll.data.shipped;
  const shippedText = shipped && shipped.length ? shipped.join(" | ") : "Release details and verification are not recorded by the realm.";
  const next = agendas.flatMap((read) => {
    const queue = read && read.data && read.data.queue;
    if (!queue) return [];
    const entries = queue.entries || [];
    const active = entries.findIndex((entry) => entry && entry.status === "active");
    const following = active >= 0 ? entries[active + 1] : null;
    return [following && (following.place || following.title || following.name), queue.line].filter(Boolean);
  }).slice(0, 3);
  const blocker = stuck && stuck.data && stuck.data.members && stuck.data.members.length ? plural(stuck.data.members.length, "member", "members") + " waiting; details are grouped in each guild report." : "No blocker currently recorded.";
  return html`<section class="nr" aria-labelledby="nr-title"><div class="nr-title"><div><span class="kicker">Realm report</span><h2 id="nr-title">Progress at a glance</h2></div><span class="dim small">Refreshes every 30 seconds</span></div><div class="nr-grid">${guilds.map((guild) => guildCard(ctx, guild))}</div><div class="card nr-summary"><div><span class="kicker">Shipped and verified</span><p>${shippedText}</p></div><div><span class="kicker">Next actions</span><p>${next.length ? next.join(" | ") : "No next action recorded."}</p></div><div><span class="kicker">Current blockers</span><p>${blocker}</p></div></div></section>`;
}
