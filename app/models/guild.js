// /api/v2/guild: one guild's header, members, class quests, deaths and its
// dungeon path. The view prints the payload's own fields; what is worked out
// from them (the median level, the level spread, ghosts now, the dungeons
// learned from) is worked out here.

import { ready } from "../ui.js";

// The middle value, the upper one of the two for an even count; null for none.
function median(nums) {
  const s = nums.slice().sort((a, b) => a - b);
  if (!s.length) return null;
  return s[Math.floor(s.length / 2)];
}

// The read as a model. A read that is not ready has no members and no
// dungeons, so every figure it is asked for is null.
export function guild(read) {
  const ok = ready(read);
  const members = ok ? read.data.members || [] : [];
  const dungeons = ok ? read.data.dungeons || [] : [];
  const levels = () => members.map((m) => m.level);
  return {
    ready: ok,
    levels,
    medianLevel: () => median(levels()),
    // Members by level, two levels a bar from an even level, over the levels
    // read (a level of 0 is none); null when no level was read.
    levelSpread: () => {
      const known = levels().filter((l) => l > 0);
      if (!known.length) return null;
      const lo = Math.min(...known), hi = Math.max(...known), med = median(known);
      const bins = [];
      for (let a = lo - (lo % 2); a <= hi; a += 2) {
        const b = a + 1;
        bins.push({ from: a, to: b, n: known.filter((l) => l >= a && l <= b).length, median: med >= a && med <= b });
      }
      return { lo, hi, median: med, bins };
    },
    ghostsNow: () => members.filter((m) => m.ghost).length,
    // The dungeons the guild has gone into at least once.
    learned: () => dungeons.filter((d) => d.runs > 0),
    classOf: (name) => (members.find((m) => m.name === name) || {}).class,
  };
}
