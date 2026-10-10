// The one clock the app reads time in: unix seconds, UTC.
//
// The server sends a time as unix seconds, or as the realm database's own
// text ("2026-10-09 20:12:04"), which carries no zone and is UTC. Both are
// read here, and nowhere else, into seconds. The browser's own clock (Date.now,
// a read's `at`, the last visit) counts milliseconds: fromClock() turns those
// into seconds before anything compares them with the server's.

import { ago } from "../ui.js";

// A time the server sent, as unix seconds; null when there is none.
export function toSeconds(v) {
  if (v === null || v === undefined || v === "") return null;
  if (typeof v === "number") return isFinite(v) ? v : null;
  const s = String(v).trim().replace(" ", "T");
  const t = Date.parse(/[zZ]|[+-]\d\d:?\d\d$/.test(s) ? s : s + "Z");
  return isFinite(t) ? t / 1000 : null;
}

// A time from the browser's clock (milliseconds), as unix seconds.
export function fromClock(ms) {
  return ms ? ms / 1000 : null;
}

export function nowSeconds() {
  return Date.now() / 1000;
}

// Seconds from `v` (any time toSeconds reads) to `now`; never below zero.
export function ageOf(v, now) {
  const t = toSeconds(v);
  if (t === null) return null;
  return Math.max(0, (now === undefined ? nowSeconds() : now) - t);
}

// "42s ago", "2h ago", or "not measured" when there is no time.
export function since(v, now) {
  return ago(ageOf(v, now));
}

// The local clock time of `v`, hours and minutes; "" when there is none.
export function clock(v) {
  const t = toSeconds(v);
  if (!t) return "";
  return new Date(t * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
