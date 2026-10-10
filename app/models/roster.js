// /api/v2/roster: every member of both family guilds, and the roster's own
// clock (`checked_at`, unix seconds).
//
// A member row carries `online`, `life` ("dead" for a corpse, "ghost" for a
// released spirit, "alive", or null when nothing was read), `stuck` and
// `since` (unix seconds, or null when the first sighting was not recorded).
// The gear rows of /api/guildgear carry `online` and `life` too, so
// stateOf() reads either.

import { duration, ready } from "../ui.js";

export function byName(list) {
  const out = new Map();
  (list || []).forEach((m) => { if (m && m.name) out.set(m.name, m); });
  return out;
}

// "ghost", "stuck", "online" or "offline", in that order of weight.
export function stateOf(m) {
  if (!m) return "offline";
  if (m.life === "ghost" || m.life === "dead") return "ghost";
  if (m.stuck) return "stuck";
  return m.online ? "online" : "offline";
}

// How long a stuck member has waited, by the roster's clock; null when it is
// not stuck or either time is missing.
export function stuckFor(m, checkedAt) {
  if (!m || !m.stuck) return null;
  if (m.since === null || m.since === undefined || !checkedAt) return null;
  return duration(checkedAt - m.since);
}

// The roster read as a model. A read that is not ready holds nobody, and
// every count it is asked for is null (not measured), never zero.
export function roster(read) {
  const ok = ready(read) && Array.isArray(read.data.members);
  const members = ok ? read.data.members : [];
  const names = byName(members);
  // Ghosts are measured only once some member's life was read.
  const ghosts = () => {
    if (!ok || !members.some((m) => typeof m.life === "string")) return null;
    return members.filter((m) => m.life === "ghost" || m.life === "dead");
  };
  return {
    ready: ok,
    members,
    checkedAt: ok ? read.data.checked_at || null : null,
    has: (name) => names.has(name),
    member: (name) => names.get(name) || null,
    ghosts,
    ghostNames: () => new Set((ghosts() || []).map((m) => m.name)),
    inGuild: (guild) => (ok ? members.filter((m) => m.guild === guild) : null),
  };
}
