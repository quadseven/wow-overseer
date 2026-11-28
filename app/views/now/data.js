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
// A family can be mid campaign with nothing left in its queue, and then the
// agenda's own reading is the only one that knows: campaign_state says
// running, off the leader's counter, while the queue entries are empty.
// That reading is the fallback, so the block never reports a running
// campaign as nothing queued. With neither source showing a campaign there
// is none to draw, and the block says so about the queue only.
export function campaign(agenda) {
  const q = agenda && agenda.queue;
  const entries = (q && q.entries) || [];
  if (!entries.length) return runningCampaign(agenda);
  const i = Math.max(0, entries.findIndex((e) => e.status === "active"));
  const cur = entries[i];
  const next = entries[i + 1];
  return {
    name: cur.place,
    step: cur.status !== "active" ? "starting" : stepOf(q.done, cur.runs),
    next: next ? next.place + ", " + next.runs + " runs" : null,
    line: q.line || "",
  };
}

// A campaign's progress in words, or null when its count was not read.
function stepOf(done, runs) {
  if (done === null || done === undefined || runs === null || runs === undefined) return null;
  return done + " of " + runs + " done";
}

// The campaign the agenda's counter is counting, when the queue holds no
// entry for it: its progress is the counter's done of its wanted, and
// nothing is queued after it. The fallback takes both halves of the
// agenda's reading, the state word and the counter; either one missing,
// or a state other than running, is no campaign to show.
function runningCampaign(agenda) {
  if (!agenda || agenda.campaign_state !== "running" || !agenda.campaign) return null;
  const c = agenda.campaign;
  return {
    name: "Dungeon campaign",
    step: stepOf(c.done, c.wanted),
    next: null,
    line: "",
  };
}

export function detailLines(agenda) {
  const queue = agenda.queue && agenda.queue.line;
  return (agenda.detail || []).filter((d) => d && d !== queue);
}
