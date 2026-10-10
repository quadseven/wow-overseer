// The fetch layer. Every read is a GET under the page's own mount (see
// basepath.py: an origin-relative URL under a prefix would read another
// realm). Answers are kept in memory and served at once while a fresh copy is
// fetched (stale-while-revalidate); the server's ETag turns an unchanged
// answer into a 304, which the browser answers from its own cache. Only the reads of the view on screen are polled, and
// polling stops while the page is hidden.

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
  let e = cache.get(path);
  if (!e) {
    e = { data: undefined, text: "", at: 0, error: null, failures: 0, inflight: null };
    cache.set(path, e);
  }
  return e;
}

// `changed` is false for a 304: the age moved, the data did not.
function notify(path, changed) { listeners.forEach((fn) => fn(path, changed)); }

export function onChange(fn) { listeners.add(fn); return () => listeners.delete(fn); }

// What is known about a read right now, without fetching.
export function peek(path) {
  const e = cache.get(path);
  if (!e) return { data: undefined, at: 0, error: null, failures: 0, loading: true };
  return { data: e.data, at: e.at, error: e.error, failures: e.failures, loading: e.data === undefined && !e.error };
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
      e.at = Date.now(); e.error = null; e.failures = 0;
      return changed;
    })
    .catch((err) => { e.error = err; e.failures += 1; return true; })
    .then((changed) => { e.inflight = null; notify(path, changed); return e; });
  return e.inflight;
}

export function loadAll(paths) { return Promise.all(paths.map(load)); }

// Polling for the view on screen. One timer; restarted on every route.
let pollPaths = [];
let pollEvery = 0;
let timer = null;

function tick() {
  timer = null;
  if (document.hidden || !pollPaths.length) return;
  loadAll(pollPaths).finally(schedule);
}

function schedule() {
  if (timer || !pollEvery || document.hidden) return;
  timer = window.setTimeout(tick, pollEvery);
}

export function watch(paths, everyMs) {
  if (timer) { window.clearTimeout(timer); timer = null; }
  pollPaths = paths.slice();
  pollEvery = everyMs || 0;
  loadAll(pollPaths).finally(schedule);
}

export function refreshNow() {
  if (timer) { window.clearTimeout(timer); timer = null; }
  return loadAll(pollPaths).finally(schedule);
}

document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    if (timer) { window.clearTimeout(timer); timer = null; }
  } else {
    refreshNow();
  }
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
