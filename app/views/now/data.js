// What the Now views read and how they read it: the families, the stuck list
// and each family's agenda. The roster, the guild runs and the wall have
// read models of their own (app/models/), and every time is read by
// models/time.js, in unix seconds.

import { ready } from "../../ui.js";
import { ageOf } from "../../models/time.js";

// familyKeys(): "Grug", "Zug", every family the realm reports, default first.
export { familyKeys } from "../../families.js";

export function agendaPath(fam) { return "/api/agenda?family=" + encodeURIComponent(fam); }

// A read that answered with data the server meant (not an error body).
export { ready as ok };

// /api/v2/stuck: {members: [{name, step, blocker, since, kind}]}; `since` is
// unix seconds, or null when the first sighting was not recorded. `longest`
// is how long the earliest of them has waited by `now` (unix seconds).
// `stalls` is how many of them are a stalled family's leader (kind "stall",
// #1257): they are stuck members like the rest, so the count the Now page
// says is the Members badge's and the stuck filter's, and the stalls are
// said beside it rather than left out of it.
export function stuck(read, now) {
  if (!ready(read) || !Array.isArray(read.data.members)) return null;
  const list = read.data.members;
  const ages = list.map((m) => ageOf(m.since, now)).filter((a) => a !== null);
  const stalls = list.filter((m) => m && m.kind === "stall").length;
  return { list, longest: ages.length ? Math.max(...ages) : null, stalls };
}

// A stalled family's sentence under its STALLED tag. The agenda's stall_line
// opens with "STALLED:" itself, so beside the tag the card said it twice; the
// word is dropped here only when the line starts with it. The line ends with
// the hold that explains the stall (stall_blocker) when the bridge read the
// leader; a blocker the line does not carry is added after it.
export function stallText(agenda) {
  let line = String((agenda && agenda.stall_line) || "").trim();
  const lead = /^STALLED:\s*/.exec(line);
  if (lead) {
    line = line.slice(lead[0].length);
    line = line.charAt(0).toUpperCase() + line.slice(1);
  }
  const blocker = String((agenda && agenda.stall_blocker) || "").trim();
  if (blocker && !line.includes(blocker)) line = line ? line + " " + blocker : blocker;
  return line || "No progress since the walk began.";
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
