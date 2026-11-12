// Two start-up decisions, as pure functions so node can test them.
//
// 1. earlyRoute: what the first route can start before the realm read has
//    answered. Until the realm answers, the router keeps any family or guild
//    slug it is given (families.js), so a route that carries its own slug
//    (quests, members, economy, Now, a member, a family or guild page) is the
//    route that will be drawn, and its view module and reads can be on the
//    wire while the realm read is. A hash that needs the list to pick its
//    family or guild (no slug given), and an old-style hash that may map to
//    one, waits: the router would send it somewhere else.
//
// 2. afterFirstDraw: the nav badges' reads (chronicle, loot, stuck) are about
//    26 KB that nothing on screen needs yet. They start once the first view
//    has drawn, or after a fallback wait if nothing draws, never before.

import { legacy, parse, resolve } from "./router.js";

// {view, params, query, hash} for the route to start early, or null.
//   learned: the realm's families and guilds are already known (nothing to gain)
//   last: the page the app restores for an empty hash
export function earlyRoute(hash, { learned, last }) {
  if (learned) return null;
  let h = hash || "";
  if (!h || h === "#" || h === "#/") h = last || "#/now";
  if (legacy(h)) return null;
  const parsed = parse(h);
  const r = resolve(parsed);
  if (r.redirect || !r.view) return null;
  return { view: r.view, section: r.section, params: r.params, query: parsed.query, hash: h };
}

// Calls `start` once: at the first `drawn()`, or when the fallback timer
// fires, whichever comes first.
export function afterFirstDraw(start, { setTimer, clearTimer, fallbackMs }) {
  let done = false;
  let timer = null;
  const go = () => {
    if (done) return;
    done = true;
    if (timer !== null) { clearTimer(timer); timer = null; }
    start();
  };
  timer = setTimer(() => { timer = null; go(); }, fallbackMs);
  return { drawn: go };
}
