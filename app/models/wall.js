// /api/wall: the Watch wall, every family's streamed characters (`members`,
// each with its `family`) and the wall's tiles (`wall.tiles`, by name).

import { ready } from "../ui.js";

// A family's head: the member named like the family, else its leader, else
// the first listed.
export function headOf(members, fam) {
  return members.find((m) => m.name === fam) || members.find((m) => m.leader) || members[0] || null;
}

// The read as a model. A read that is not ready holds nobody, and has no
// heads to show (null, not an empty wall).
export function wall(read) {
  const ok = ready(read);
  const members = ok ? read.data.members || [] : [];
  const tiles = (ok && read.data.wall && read.data.wall.tiles) || [];
  const families = () => {
    const out = new Map();
    members.forEach((m) => {
      const key = m.family || "";
      if (!out.has(key)) out.set(key, []);
      out.get(key).push(m);
    });
    return out;
  };
  const head = (fam) => headOf(families().get(fam) || [], fam);
  return {
    ready: ok,
    members,
    families,
    head,
    // The heads of the families named, in that order; a family with nobody
    // on the wall is left out.
    heads: (fams) => (ok ? fams.map(head).filter(Boolean) : null),
    tile: (name) => tiles.find((t) => t.name === name) || null,
  };
}
