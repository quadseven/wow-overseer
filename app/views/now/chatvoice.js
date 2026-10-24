// Reading party and raid chat aloud over the Watch wall (ticket 177).
//
// /api/chat/party hands over each line once (not once per listener), with the
// voice its speaker is read in (partyvoice.py). This module decides what is
// spoken and when: one line at a time, a stale line dropped rather than read
// long after the moment, an exact repeat from one speaker skipped, the queue
// capped so a council burst never becomes a minute of backlog. The heard
// stream is lowered while a line is read and lifted after, error or not.
//
// It imports nothing. Every browser object it touches (fetch, timers,
// speechSynthesis, the heard <video>) is handed to makeReader, so node drives
// the whole of it in tests/test_app_chatvoice.py. speakLine is the one seam a
// server-side voice could replace without touching the feed or the queue.

export const POLL_MS = 4000;      // a line said is read within about 10 s
export const STALE_MS = 20000;    // older than this when its turn comes: dropped
export const REPEAT_MS = 60000;   // the same words from the same speaker: skipped
export const QUEUE_CAP = 6;       // waiting lines; the oldest falls off first
export const DUCK_VOLUME = 0.25;  // the heard stream while a line is read

// ---- the queue ------------------------------------------------------------
// A line: {speaker, text, heardAt (ms), voice}. offer() says what became of
// it: "queued", "stale" or "repeat".
export function makeQueue() {
  let lines = [];
  let speaking = false;
  const lastSaid = new Map(); // speaker + text -> when it was offered

  function forget(now) {
    lastSaid.forEach((at, key) => { if (now - at >= REPEAT_MS) lastSaid.delete(key); });
  }

  return {
    offer(line, now) {
      if (now - line.heardAt > STALE_MS) return "stale";
      forget(now);
      const key = line.speaker + "\n" + line.text;
      if (lastSaid.has(key)) return "repeat";
      lastSaid.set(key, now);
      lines.push(line);
      if (lines.length > QUEUE_CAP) lines.shift();
      return "queued";
    },
    // The next line to read, or null while one is being read or none is fresh.
    take(now) {
      if (speaking) return null;
      lines = lines.filter((l) => now - l.heardAt <= STALE_MS);
      const next = lines.shift() || null;
      speaking = next !== null;
      return next;
    },
    done() { speaking = false; },
    clear() { lines = []; speaking = false; },
    size() { return lines.length; },
  };
}

// A feed row as a line, heard `age_s` before `now` (the database's clock
// measured the age, so no two clocks are compared).
export function lineFromRow(row, now) {
  const age = typeof row.age_s === "number" ? row.age_s * 1000 : 0;
  return { speaker: row.speaker, text: row.text, heardAt: now - age, voice: row.voice };
}

// ---- ducking ----------------------------------------------------------------
// Lower `video` to `level` and return what puts it back. A muted stream is
// never unmuted to duck it, and a stream already quieter is left alone.
export function duck(video, level) {
  if (!video || video.muted || !(video.volume > level)) return () => {};
  const before = video.volume;
  video.volume = level;
  return () => { video.volume = before; };
}

// ---- the voice ----------------------------------------------------------------
// Browsers rarely say a voice's gender, so it is read off the name where the
// platform's voices are known by one; otherwise the language decides.
const NAMED = {
  female: /female|woman|samantha|victoria|karen|moira|tessa|fiona|zira|susan|hazel/i,
  male: /(^|[^e])male|daniel|alex|fred|david|mark|george|rishi/i,
};

// The system voice for a hint such as "en-male", or null for the default.
export function pickVoice(voices, hint) {
  const [lang, gender] = String(hint || "en").split("-");
  const pool = (voices || []).filter((v) => String(v.lang || "").toLowerCase().startsWith(lang));
  if (!pool.length) return null;
  const named = NAMED[gender];
  return (named && pool.find((v) => named.test(v.name))) || pool[0];
}

// Read one line through speechSynthesis, ducked; `done` runs exactly once,
// when the line ends or fails.
export function speakLine(line, env, done) {
  const restore = duck(env.video(), DUCK_VOLUME);
  let finished = false;
  const finish = () => {
    if (finished) return;
    finished = true;
    restore();
    done();
  };
  const voice = line.voice || {};
  try {
    const u = new env.Utterance(line.text);
    u.pitch = typeof voice.pitch === "number" ? voice.pitch : 1;
    u.rate = typeof voice.rate === "number" ? voice.rate : 1;
    const system = pickVoice(env.synth.getVoices(), voice.engine_voice_hint);
    if (system) { u.voice = system; u.lang = system.lang; }
    u.onend = finish;
    u.onerror = finish;
    env.synth.speak(u);
  } catch (e) {
    finish();
    throw e;
  }
}

// ---- the reader ----------------------------------------------------------------
// env: {fetchJson(path), families(), video(), synth, Utterance, now(),
// setTimer(fn, ms), clearTimer(id), warn(...)}. Off until start(), which only
// a click calls: nothing is read on load.
export function makeReader(env) {
  const queue = makeQueue();
  let on = false;
  let timer = null;
  let cursors = new Map(); // family key -> last row id read

  function path(fam) {
    const after = cursors.get(fam);
    return "/api/chat/party?family=" + encodeURIComponent(fam) + (after === undefined ? "" : "&after=" + after);
  }

  function pump() {
    if (!on) return;
    const line = queue.take(env.now());
    if (!line) return;
    try {
      speakLine(line, env, () => { queue.done(); pump(); });
    } catch (e) {
      env.warn("chat line could not be read aloud", e);
    }
  }

  async function read(fam) {
    const primed = cursors.has(fam);
    const body = await env.fetchJson(path(fam));
    if (!on) return;
    cursors.set(fam, body.after);
    if (!primed) return; // the first read only learns where the chat ends
    (body.rows || []).forEach((row) => queue.offer(lineFromRow(row, env.now()), env.now()));
  }

  async function poll() {
    timer = null;
    if (!on) return;
    await Promise.all(env.families().map((fam) => read(fam).catch((e) => env.warn("chat feed read failed", fam, e))));
    pump();
    if (on && timer === null) timer = env.setTimer(poll, POLL_MS);
  }

  return {
    on: () => on,
    poll,
    start() {
      if (on) return Promise.resolve();
      on = true;
      return poll();
    },
    stop() {
      on = false;
      if (timer !== null) { env.clearTimer(timer); timer = null; }
      queue.clear();
      cursors = new Map();
      env.synth.cancel();
    },
  };
}
