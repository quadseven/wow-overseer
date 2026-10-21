// Read party and raid chat aloud over the Watch wall, one voice per character.
//
// /api/chat/party hands over one row per utterance (the hearers' copies are
// already collapsed server side) with the voice its speaker uses. This module
// queues those lines, says one at a time through speak(), and lowers the
// stream being heard while a line is said.
//
// Nothing here touches the page or the network directly: makeReader() is
// handed what it reads from (the feed, the heard video, the speech engine,
// the clock), so the queue, the ducking and the restore-on-error can all be
// driven from a test with fakes. streams.js wires the real ones.
//
// Off on every load. The viewer's last choice is remembered, but reading
// only starts from a click: speechSynthesis needs a user gesture on several
// browsers, and a page that starts talking unasked is worse than one that
// asks.

export const DUCK_VOLUME = 0.25;  // the heard stream's volume while a line is said
export const POLL_MS = 4000;      // so a line is said within about 10 s
export const STALE_MS = 20000;    // a line older than this is no longer worth saying
export const REPEAT_MS = 60000;   // the same words from the same speaker, skipped
export const QUEUE_CAP = 8;       // the oldest waiting line falls off past this

const STORE_KEY = "overseer.chatVoice";

// ---- the queue --------------------------------------------------------------
// One line at a time: take() hands out nothing while a line is out, until
// done(). Repeats are skipped as they arrive, the queue keeps only the newest
// `cap`, and a line that waited past `staleMs` is dropped when its turn comes.
// A line is {sender, text, voice, at}; `at` and `now` are milliseconds.
export function makeQueue({ cap = QUEUE_CAP, staleMs = STALE_MS, repeatMs = REPEAT_MS } = {}) {
  let lines = [];
  let busy = false;
  const said = new Map(); // sender + "\n" + text -> when it was accepted

  function forget(now) {
    said.forEach((when, key) => { if (now - when >= repeatMs) said.delete(key); });
  }

  return {
    offer(line, now) {
      forget(now);
      const key = line.sender + "\n" + line.text;
      if (said.has(key)) return false;
      said.set(key, now);
      lines.push(line);
      if (lines.length > cap) lines.shift();
      return true;
    },
    take(now) {
      if (busy) return null;
      lines = lines.filter((l) => now - l.at <= staleMs);
      const line = lines.shift() || null;
      busy = line !== null;
      return line;
    },
    done() { busy = false; },
    clear() { lines = []; busy = false; },
    size() { return lines.length; },
  };
}

// ---- ducking ----------------------------------------------------------------
// Lower `video` to `level` and return what puts it back. A muted or absent
// video is left alone (ducking never unmutes a stream), and the restore
// leaves a volume the viewer changed mid-line where they put it.
export function duck(video, level = DUCK_VOLUME) {
  if (!video || video.muted || video.volume <= level) return () => {};
  const before = video.volume;
  video.volume = level;
  return () => { if (video.volume === level) video.volume = before; };
}

// ---- the engine -------------------------------------------------------------
// The system voice nearest the hint: the hint's language, and its gender
// where the platform puts one in the voice's name. Most platforms do not, so
// the per-character pitch and rate carry the difference.
export function pickVoice(voices, hint) {
  const h = hint || {};
  const lang = new RegExp("^" + (h.lang || "en") + "\\b", "i");
  const fit = (voices || []).filter((v) => lang.test(v.lang || ""));
  const gender = h.gender ? new RegExp("\\b" + h.gender + "\\b", "i") : null;
  return (gender && fit.find((v) => gender.test(v.name || ""))) || fit[0] || null;
}

// Say one line, then call done(error or null). The single seam to the speech
// engine: a server voice can replace the browser's here without the feed, the
// queue or the voice table changing. `engine` holds speechSynthesis and
// SpeechSynthesisUtterance (the window, in the page).
export function speak(line, done, engine = globalThis) {
  const synth = engine.speechSynthesis;
  if (!synth || typeof engine.SpeechSynthesisUtterance !== "function") {
    done(new Error("this browser has no speech engine"));
    return;
  }
  const v = line.voice || {};
  const utter = new engine.SpeechSynthesisUtterance(line.text);
  utter.pitch = v.pitch || 1;
  utter.rate = v.rate || 1;
  const system = pickVoice(synth.getVoices(), v.engine_voice_hint);
  if (system) utter.voice = system;
  utter.onend = () => done(null);
  utter.onerror = (e) => done(e.error ? new Error("speech failed: " + e.error) : new Error("speech failed"));
  synth.speak(utter);
}

// ---- the viewer's choice ----------------------------------------------------
// Remembered per browser. Storage can throw (private mode, quota, a blocked
// site); the choice then lasts for the page and the reason is logged.
export function remembered(store) {
  try { return store.getItem(STORE_KEY) === "1"; } catch (e) {
    console.warn("read chat aloud: the remembered choice could not be read", e);
    return false;
  }
}

function remember(store, on) {
  try { store.setItem(STORE_KEY, on ? "1" : "0"); } catch (e) {
    console.warn("read chat aloud: the choice could not be remembered", e);
  }
}

// ---- the reader -------------------------------------------------------------
// deps: families() -> family keys; fetchFeed(family, after) -> Promise of
// {rows, cursor}; audible() -> the heard <video> or null; engine (see speak);
// store (localStorage); now() -> ms; every(fn, ms) -> handle; cancel(handle).
export function makeReader(deps) {
  const queue = makeQueue();
  const cursors = new Map(); // family -> the `after` its next poll sends
  let on = false;
  let timer = null;
  let restore = null;
  let polling = false;

  function finished(err) {
    if (err && on) console.warn("read chat aloud: a line was not said", err);
    if (restore) { restore(); restore = null; }
    queue.done();
    if (on) next();
  }

  function next() {
    const line = queue.take(deps.now());
    if (!line) return;
    restore = duck(deps.audible());
    // An engine that throws instead of firing onerror still lifts the duck.
    try { speak(line, finished, deps.engine); } catch (e) { finished(e); }
  }

  function hear(rows, at) {
    for (const r of rows || []) {
      queue.offer({ sender: r.sender, text: r.text, voice: r.voice, at: at - (r.age_s || 0) * 1000 }, at);
    }
  }

  async function pollOne(family) {
    const feed = await deps.fetchFeed(family, cursors.get(family));
    if (!on) return;
    cursors.set(family, feed.cursor);
    hear(feed.rows, deps.now());
  }

  // One poll at a time: a slow answer overlapping the next tick would send
  // the same cursor twice.
  async function poll() {
    if (polling) return;
    polling = true;
    const reads = deps.families().map((f) => pollOne(f).catch((e) => {
      console.warn("read chat aloud: the " + f + " feed did not answer", e);
    }));
    await Promise.all(reads);
    polling = false;
    if (on) next();
  }

  // The first poll's promise, so a caller can wait for the cursor to be set.
  function start() {
    if (on) return Promise.resolve();
    on = true;
    remember(deps.store, true);
    timer = deps.every(poll, POLL_MS);
    return poll();
  }

  // `forget` is false when leaving Now: reading stops, the choice stays.
  function stop(forget = true) {
    if (!on) return;
    on = false;
    if (forget) remember(deps.store, false);
    deps.cancel(timer);
    timer = null;
    cursors.clear();
    queue.clear();
    if (deps.engine.speechSynthesis) deps.engine.speechSynthesis.cancel();
    if (restore) { restore(); restore = null; }
  }

  return {
    start,
    stop,
    poll,
    isOn: () => on,
    toggle() { if (on) stop(); else start(); },
  };
}
