// What the Now views read and how they read it: the families, the wall's
// members, the stuck list and the times the server sends. Pure functions of
// payloads, so the views stay markup.

import { FAMILIES } from "../../router.js";

export const FAMILY_KEYS = FAMILIES.map((f) => f.charAt(0).toUpperCase() + f.slice(1));

export function agendaPath(fam) { return "/api/agenda?family=" + encodeURIComponent(fam); }

// A read that answered with data the server meant (not an error body).
export function ok(read) {
  return !!(read && read.data !== undefined && read.data !== null && !read.data.error);
}

// "2026-10-09 20:12:04" from the realm's database is UTC.
export function dbTime(text) {
  if (!text) return null;
  const t = Date.parse(String(text).replace(" ", "T") + "Z");
  return isFinite(t) ? t : null;
}

export function secondsSince(ms) { return ms === null ? null : Math.max(0, (Date.now() - ms) / 1000); }

// The wall's members grouped by family, and each family's head: the member
// named like the family, else its leader.
export function families(wall) {
  const out = new Map();
  ((wall && wall.members) || []).forEach((m) => {
    const key = m.family || "";
    if (!out.has(key)) out.set(key, []);
    out.get(key).push(m);
  });
  return out;
}

export function headOf(members, fam) {
  return members.find((m) => m.name === fam) || members.find((m) => m.leader) || members[0] || null;
}

export function tileOf(wall, name) {
  const tiles = (wall && wall.wall && wall.wall.tiles) || [];
  return tiles.find((t) => t.name === name) || null;
}

// Ghosts from /api/v2/roster, the read the Members page counts: each member's
// `life` is "dead" (a corpse), "ghost" (a released spirit), "alive", or null
// when nothing was read. The wall's members carry no ghost state at all, so
// the chip once said "not measured" while the roster listed ghosts.
export function ghosts(roster) {
  if (!ok(roster)) return null;
  const members = roster.data.members || [];
  if (!members.some((m) => typeof m.life === "string")) return null;
  return members.filter((m) => m.life === "ghost" || m.life === "dead");
}

// The names ghosts() finds, for the map dots; empty when not measured.
export function ghostNames(roster) {
  return new Set((ghosts(roster) || []).map((m) => m.name));
}

// /api/v2/stuck: {members: [{name, step, blocker, since}]}; `since` is a
// timestamp (seconds) or null when the first sighting was not recorded.
export function stuck(read) {
  if (!ok(read) || !Array.isArray(read.data.members)) return null;
  const list = read.data.members;
  const sinces = list.map((m) => m.since).filter((s) => s !== null && s !== undefined && isFinite(s));
  const longest = sinces.length ? Math.max(0, Date.now() / 1000 - Math.min(...sinces.map((s) => (s > 1e12 ? s / 1000 : s)))) : null;
  return { list, longest };
}

// Guild runs inside a dungeon now.
export function runsInside(read) {
  if (!ok(read)) return null;
  return (read.data.active || []).filter((r) => (r.status || r.state) === "inside");
}

// Runs that formed or came back since this device last looked.
export function runsNewSince(read, since) {
  if (!ok(read) || !since) return null;
  const all = (read.data.active || []).concat(read.data.recent || []);
  return all.filter((r) => {
    const t = Math.max(dbTime(r.created_at) || 0, dbTime(r.ended_at) || 0);
    return t > since;
  }).length;
}

// A family's campaign from its queue: the entry being worked and the next.
export function campaign(agenda) {
  const q = agenda && agenda.queue;
  const entries = (q && q.entries) || [];
  if (!entries.length) return null;
  const i = Math.max(0, entries.findIndex((e) => e.status === "active"));
  const cur = entries[i];
  const next = entries[i + 1];
  return {
    name: cur.place,
    step: (q.done === null || q.done === undefined ? null : q.done + " of " + cur.runs),
    next: next ? next.place + ", " + next.runs + " runs" : null,
    line: q.line || "",
  };
}

export function detailLines(agenda) {
  const queue = agenda.queue && agenda.queue.line;
  return (agenda.detail || []).filter((d) => d && d !== queue);
}
