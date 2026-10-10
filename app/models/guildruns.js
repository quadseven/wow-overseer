// /api/guildruns: the guild coordinator's groups, `active` (out now) and
// `recent` (back), one run shape for both lists. A run's `created_at` and
// `ended_at` are the realm database's UTC text; every time read from here is
// unix seconds (models/time.js).

import { ready } from "../ui.js";
import { toSeconds } from "./time.js";

export function formedAt(r) { return toSeconds(r.created_at); }

export function endedAt(r) { return toSeconds(r.ended_at); }

// When the run was last heard of: back, or else formed.
export function lastAt(r) { return endedAt(r) || formedAt(r); }

// The outcomes of a run that never reached the door (guildrun.OUTCOMES):
// no instance was read, so there is no boss count to measure.
const NEVER_IN = ["refused", "not entered"];

export function bossText(r) {
  const total = Number(r.bosses_total) || 0;
  if (total) return (Number(r.bosses_done) || 0) + " of " + total + " bosses down";
  return NEVER_IN.includes(r.outcome) && !Number(r.seconds_inside) ? "never went in" : "bosses not measured";
}

// Why the run went where it went: the coordinator's first lines.
export function chose(r) {
  return (r.lines || []).filter((l) => /^(dungeon|group):/.test(l)).join(". ");
}

// Why it came back the way it did.
export function cause(r) {
  const c = r.cause || r.why || "";
  return c.replace(/^Cause: /, "");
}

// The read as a model. A read that is not ready holds no run, and the counts
// it is asked for are null (not measured).
export function guildRuns(read) {
  const ok = ready(read);
  const active = ok ? read.data.active || [] : [];
  const recent = ok ? read.data.recent || [] : [];
  const all = active.concat(recent);
  return {
    ready: ok,
    active,
    recent,
    all,
    find: (id) => all.find((r) => String(r.id) === String(id)) || null,
    // The groups inside a dungeon now, by the one field that says where a
    // run is (guildrun.run_state).
    insideNow: () => (ok ? active.filter((r) => r.run_state === "inside") : null),
    // How many runs formed or came back after `seconds` (unix seconds).
    newSince: (seconds) => {
      if (!ok || !seconds) return null;
      return all.filter((r) => Math.max(formedAt(r) || 0, endedAt(r) || 0) > seconds).length;
    },
  };
}
