// The fetch layer. Every read is a GET under the page's own mount (see
// basepath.py: an origin-relative URL under a prefix would read another
// realm). Answers are kept in memory and served at once while a fresh copy is
// fetched (stale-while-revalidate); the server's ETag turns an unchanged
// answer into a 304, which the browser answers from its own cache. Only the reads of the view on screen are polled, and
// polling stops while the page is hidden. The last good answer to each read is
// also kept for this tab (sessionStorage), so a reload paints at once from it,
// marked "saved" until the world answers again (see the end of this file).

const BASE = (function () {
  const meta = document.querySelector('meta[name="overseer-base"]');
  const raw = meta ? meta.getAttribute("content") || "" : "";
  return raw.charAt(0) === "/" ? raw.replace(/\/+$/, "") : "";
})();

export function u(path) { return BASE + path; }

// Some reads (the decree console) take over ten seconds on a busy realm.
const TIMEOUT_MS = 30000;
const cache = new Map(); // path -> entry
const listeners = new Set();

function entry(path) {
  let e = cache.get(path) || restore(path);
  if (!e) {
    e = { data: undefined, text: "", at: 0, error: null, failures: 0, inflight: null, saved: false };
    cache.set(path, e);
  }
  return e;
}

// `changed` is false for a 304: the age moved, the data did not.
function notify(path, changed) { listeners.forEach((fn) => fn(path, changed)); }

export function onChange(fn) { listeners.add(fn); return () => listeners.delete(fn); }

// What is known about a read right now, without fetching.
export function peek(path) {
  const e = cache.get(path) || restore(path);
  if (!e) return { data: undefined, at: 0, error: null, failures: 0, loading: true, saved: false };
  return { data: e.data, at: e.at, error: e.error, failures: e.failures, loading: e.data === undefined && !e.error, saved: e.saved };
}

// Fetch once (or join the fetch in flight). Resolves to the entry; never
// rejects, so a view can always draw what it has.
//
// Revalidation is the browser's: `cache: "no-cache"` sends the stored ETag
// and turns the server's 304 into the stored body. An answer is "changed"
// when its text differs from the last one, so an unchanged poll redraws
// nothing.
export function load(path) {
  const e = entry(path);
  if (e.inflight) return e.inflight;
  e.inflight = fetch(u(path), { cache: "no-cache", signal: AbortSignal.timeout(TIMEOUT_MS) })
    .then(async (r) => {
      if (!r.ok) throw new Error("HTTP " + r.status);
      const text = await r.text();
      const changed = text !== e.text;
      if (changed) {
        let data;
        try { data = JSON.parse(text); } catch (err) { throw new Error("not JSON from " + path); }
        e.data = data; e.text = text;
      }
      // A saved copy the world has just confirmed is still a change on
      // screen: its "saved" mark has to go.
      const wasSaved = e.saved;
      e.at = Date.now(); e.error = null; e.failures = 0; e.saved = false;
      if (changed || wasSaved) save(path, e);
      return changed || wasSaved;
    })
    .catch((err) => { e.error = err; e.failures += 1; return true; })
    .then((changed) => { e.inflight = null; notify(path, changed); return e; });
  return e.inflight;
}

export function loadAll(paths) { return Promise.all(paths.map(load)); }

// Polling for the view on screen, restarted on every route. One timer per
// pace: the view's reads at its own `every`, and the few it names as `quick`
// at their shorter one. A pace waits for its own reads to answer before it
// counts again, so a slow read never piles up behind itself.
let pollPaths = [];
let paces = []; // [{paths, every, timer}]

function tick(p) {
  p.timer = null;
  if (document.hidden || !p.paths.length) return;
  loadAll(p.paths).finally(() => schedule(p));
}

function schedule(p) {
  if (p.timer || !p.every || document.hidden || !paces.includes(p)) return;
  p.timer = window.setTimeout(() => tick(p), p.every);
}

function stop() {
  paces.forEach((p) => { if (p.timer) { window.clearTimeout(p.timer); p.timer = null; } });
}

// `quick` is optional: {reads: [paths], every: ms} for reads cheap enough to
// ask for more often than the rest.
export function watch(paths, everyMs, quick) {
  stop();
  pollPaths = paths.slice();
  const fast = quick && quick.every ? pollPaths.filter((p) => quick.reads.includes(p)) : [];
  paces = [{ paths: pollPaths.filter((p) => !fast.includes(p)), every: everyMs || 0, timer: null }];
  if (fast.length) paces.push({ paths: fast, every: quick.every, timer: null });
  // A read that answered a moment ago (the roster a member page widened its
  // reads from) is not asked again straight away.
  return readNow(pollPaths.filter((p) => !justRead(p)));
}

export function refreshNow() { return readNow(pollPaths); }

function readNow(paths) {
  stop();
  const now = paces;
  return loadAll(paths).finally(() => now.forEach(schedule));
}

// Back on screen: read at once rather than at the next tick, so a page left
// in a pocket for an hour does not show an hour's data. main.js does the same
// when the network comes back.
document.addEventListener("visibilitychange", () => {
  if (document.hidden) stop();
  else refreshNow();
});

// The age and health of what the screen shows: the oldest successful read
// among the view's reads, and how many reads in a row failed. "stale" means a
// read that had answered before has stopped answering; a read that never
// answered is the view's own error card, not the banner's business.
export function health(paths) {
  const list = (paths && paths.length ? paths : pollPaths).map(peek);
  if (!list.length) return { at: 0, failures: 0, state: "loading" };
  const ats = list.map((p) => p.at).filter(Boolean);
  const at = ats.length ? Math.min(...ats) : 0;
  const had = list.filter((p) => p.data !== undefined);
  const failures = Math.max(0, ...had.map((p) => p.failures));
  let state = "fresh";
  if (!had.length) state = list.some((p) => p.error) ? "error" : "loading";
  else if (failures) state = "stale";
  else if (had.some((p) => p.saved)) state = "saved";
  return { at, failures, state };
}

export function currentReads() { return pollPaths.slice(); }

// The one write, used only by the operator view after a person has confirmed
// it. A JSON body to a path under the mount; a header (the Watcher's token)
// when given. Never rejects: resolves to {ok, status, body, failed}, where
// `body` is the server's JSON answer (its refusal sentence on a 4xx) or null,
// and `failed` says why no answer came. A chat waits on the language model,
// so the wait is longer than a read's.
const POST_TIMEOUT_MS = 150000;

export async function post(path, body, headers) {
  try {
    const r = await fetch(u(path), {
      method: "POST",
      cache: "no-store",
      headers: Object.assign({ "Content-Type": "application/json" }, headers || {}),
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(POST_TIMEOUT_MS),
    });
    let data = null;
    try { data = await r.json(); } catch (err) { data = null; }
    return { ok: r.ok, status: r.status, body: data, failed: "" };
  } catch (err) {
    return { ok: false, status: 0, body: null, failed: String((err && err.message) || err) };
  }
}

function justRead(path) {
  const e = cache.get(path);
  return !!(e && e.at && !e.saved && !e.error && Date.now() - e.at < 1000);
}

// ---- the copy kept for this tab -------------------------------------------------
// The last good answer to each read, kept in sessionStorage under the page's
// own mount (another realm on the same origin keeps its own). A reload draws
// from it at once with its real age, flagged `saved` so health() reports
// "saved" and the page says so until the world answers. Storage can be off,
// full or throw: every touch is guarded, and without it the app reads as
// before. Errors are never kept, and an answer too big to keep drops the old
// copy rather than leave it to be shown as current.
const SAVE_PREFIX = "overseer.read:";
const SAVE_MAX_CHARS = 1000000;

function saveKey(path) { return SAVE_PREFIX + u(path); }

function save(path, e) {
  try {
    if (e.text.length > SAVE_MAX_CHARS) { window.sessionStorage.removeItem(saveKey(path)); return; }
    window.sessionStorage.setItem(saveKey(path), JSON.stringify({ at: e.at, text: e.text }));
  } catch (err) {
    try { window.sessionStorage.removeItem(saveKey(path)); } catch (err2) { /* storage off */ }
  }
}

function restore(path) {
  let kept = null;
  try {
    const raw = window.sessionStorage.getItem(saveKey(path));
    kept = raw ? JSON.parse(raw) : null;
  } catch (err) { kept = null; }
  if (!kept || typeof kept.text !== "string" || !kept.at) return null;
  let data;
  try { data = JSON.parse(kept.text); } catch (err) { return null; }
  const e = { data, text: kept.text, at: kept.at, error: null, failures: 0, inflight: null, saved: true };
  cache.set(path, e);
  return e;
}
