// What the Now views read and how they read it: the families, the stuck list
// and each family's agenda. The roster, the guild runs and the wall have
// read models of their own (app/models/), and every time is read by
// models/time.js, in unix seconds.

import { FAMILIES } from "../../router.js";
import { ready } from "../../ui.js";
import { ageOf } from "../../models/time.js";

export const FAMILY_KEYS = FAMILIES.map((f) => f.charAt(0).toUpperCase() + f.slice(1));

export function agendaPath(fam) { return "/api/agenda?family=" + encodeURIComponent(fam); }

// A read that answered with data the server meant (not an error body).
export { ready as ok };

// /api/v2/stuck: {members: [{name, step, blocker, since}]}; `since` is unix
// seconds, or null when the first sighting was not recorded. `longest` is
// how long the earliest of them has waited by `now` (unix seconds).
export function stuck(read, now) {
  if (!ready(read) || !Array.isArray(read.data.members)) return null;
  const list = read.data.members;
  const ages = list.map((m) => ageOf(m.since, now)).filter((a) => a !== null);
  return { list, longest: ages.length ? Math.max(...ages) : null };
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
