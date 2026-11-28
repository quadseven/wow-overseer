import { u } from "../api.js";
import { toSeconds } from "./time.js";

const MOUNT = u("");
const LEGACY_PREFIX = "overseer.gear-since.";
const PREFIX = LEGACY_PREFIX + "v1:" + encodeURIComponent(MOUNT || "/") + ":";
export const CHANGE_LIMIT = 500;
const initial = new Map();

export function pageKey(member = "") { return member ? "member:" + member.toLowerCase() : "site"; }

const validTime = (ms) => Number.isSafeInteger(ms) && ms > 0 && ms <= 8640000000000000;
const validId = (id) => typeof id === "string" && /^[1-9][0-9]{0,19}$/.test(id);
const validCount = (count) => Number.isSafeInteger(count) && count > 0 && count <= 4294967295;

function parseMarker(value) {
  if (typeof value !== "string") return null;
  try {
    const marker = JSON.parse(value);
    if (marker?.v !== 1 || !validTime(marker.at) || !Array.isArray(marker.seen)
        || !marker.seen.length || marker.seen.length > CHANGE_LIMIT) return null;
    const seen = new Map();
    for (const pair of marker.seen) {
      if (!Array.isArray(pair) || pair.length !== 2 || !validId(pair[0]) || !validCount(pair[1])
          || seen.has(pair[0])) return null;
      seen.set(pair[0], pair[1]);
    }
    return { at: marker.at, seen };
  } catch (error) { return null; }
}

function readMarker(key, storage) {
  try {
    const local = storage || window.localStorage;
    const current = local.getItem(PREFIX + key);
    if (current != null) return parseMarker(current);
    // The old click-time key was origin-wide. Import it only at the root,
    // and keep old tabs from overwriting the versioned cursor.
    const legacy = !MOUNT ? Number(local.getItem(LEGACY_PREFIX + key)) : 0;
    return validTime(legacy) ? { at: legacy } : null;
  } catch (error) { return null; }
}

function firstVisit(key, now) {
  if (!initial.has(key)) initial.set(key, new Date(now - 86400000).toISOString());
  return initial.get(key);
}

export function since(key, storage, now = Date.now()) {
  const marker = readMarker(key, storage);
  return marker ? new Date(marker.at).toISOString() : firstVisit(key, now);
}

export function changesPath(key, member = "") {
  const marker = readMarker(key);
  const start = marker ? new Date(marker.at).toISOString() : firstVisit(key, Date.now());
  return "/api/v2/gear/changes?since=" + encodeURIComponent(start) + "&oldest_first=1"
    + (marker?.seen ? "&include_boundary=1" : "")
    + (member ? "&member=" + encodeURIComponent(member) : "");
}

export function changeTime(value) {
  if (typeof value !== "string" && typeof value !== "number") return null;
  const time = toSeconds(value);
  if (time === null) return null;
  const ms = Math.round(time * 1000);
  return validTime(ms) ? ms : null;
}

export function unreadChanges(data, key) {
  const changes = Array.isArray(data?.changes) ? data.changes : [];
  const marker = readMarker(key);
  return changes.filter((row) => row && typeof row === "object"
    && !(marker?.seen && changeTime(row.at) === marker.at && validCount(row.occurrences)
      && marker.seen.get(row.event_id) >= row.occurrences));
}

// The DB can revise an older event ID within the same second. Snapshot only
// the exact revisions known at the newest fetched timestamp, and leave the
// cursor alone when the read cannot establish coverage.
export function observedMarker(data, key = "") {
  const changes = data?.changes;
  const through = data?.limited === true ? changeTime(data.complete_through) : null;
  if ((data?.limited !== false && through === null) || !Array.isArray(changes)
      || !changes.length || changes.length > CHANGE_LIMIT * 2) return null;
  let at = 0;
  const seen = new Map();
  const ids = new Set();
  for (const row of changes) {
    const ms = changeTime(row?.at);
    if (ms === null || !validId(row?.event_id) || !validCount(row.occurrences)
        || ids.has(row.event_id)) return null;
    ids.add(row.event_id);
    if (through !== null && ms > through) continue;
    if (ms < at) continue;
    if (ms > at) { at = ms; seen.clear(); }
    seen.set(row.event_id, row.occurrences);
  }
  if (!seen.size || seen.size > CHANGE_LIMIT || (through !== null && at !== through)) return null;
  const current = key && readMarker(key);
  if (current && current.at > at) return null;
  if (current?.seen && current.at === at
      && [...seen].every(([id, revision]) => current.seen.get(id) >= revision)) return null;
  return JSON.stringify({ v: 1, at, seen: [...seen] });
}

export function markSeen(key, storage, value) {
  const next = parseMarker(value);
  if (!key || !next?.seen) return false;
  try {
    const local = storage || window.localStorage;
    const current = readMarker(key, local);
    if (current && current.at > next.at) return false;
    if (current?.seen && current.at === next.at) {
      for (const [id, revision] of current.seen) {
        next.seen.set(id, Math.max(next.seen.get(id) || 0, revision));
      }
    }
    if (next.seen.size > CHANGE_LIMIT) return false;
    local.setItem(PREFIX + key, JSON.stringify({ v: 1, at: next.at, seen: [...next.seen] }));
    return true;
  } catch (error) { return false; }
}
