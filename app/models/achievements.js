// /api/v2/achievements: the announcer's achievements, for one guild or both
// (`items`) or for one member (`earned`). Each is {id, rule, title, line,
// tier, member, who, guild, earned_at, source}; `member` is "" for a guild's
// first, and `who` is the guild members who were there. Times are unix
// seconds. Flavor only: nothing here is granted in the game.

import { ready } from "../ui.js";

const TIERS = {
  bronze: { label: "Bronze", icon: "ph-fill ph-medal" },
  silver: { label: "Silver", icon: "ph-fill ph-medal-military" },
  gold: { label: "Gold", icon: "ph-fill ph-trophy" },
  dubious: { label: "Dubious", icon: "ph-fill ph-smiley-melting" },
};

// How a tier is drawn: its key (the CSS hook), its word and its icon. A tier
// this app does not know is drawn as bronze under its own word.
export function tier(t) {
  const known = TIERS[t];
  if (known) return { key: t, ...known };
  return { key: "bronze", label: String(t || "Unranked"), icon: TIERS.bronze.icon };
}

// The achievements in a read, newest first: a guild feed's items or a
// member's list. A read that is not ready holds none.
export function items(read) {
  if (!ready(read)) return [];
  const d = read.data || {};
  return (d.items || d.earned || []).slice().sort((a, b) => (b.earned_at || 0) - (a.earned_at || 0));
}

// Earned after `since` (unix seconds) and not in `seen` (ids already shown on
// this device), newest first. No visit before this one: nothing is new.
export function fresh(list, since, seen) {
  if (!since) return [];
  return (list || [])
    .filter((a) => (a.earned_at || 0) > since && !(seen && seen.has(a.id)))
    .sort((a, b) => (b.earned_at || 0) - (a.earned_at || 0));
}

// Worth a line in the Chronicle's All list as well as under Achievements: a
// gold one, or a guild's first.
export function notable(a) {
  return a.tier === "gold" || !a.member;
}

// The one a toast leads with: the newest notable one, else the newest. `list`
// is newest first, as fresh() gives it.
export function headline(list) {
  return (list || []).find(notable) || (list || [])[0] || null;
}
