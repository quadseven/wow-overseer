// Operator actions. Talking to a character, decrees, starting and stopping
// streams and pointing the Watcher queue commands the realm acts on, so they
// live here, apart from the read-only app.
//
// LOCKED UNLESS THE SERVER SAYS OTHERWISE. Nothing on this route draws a form
// until GET /api/v2/operator answers {enabled: true}; while that read is
// loading, failed, or off, the page is the read-only console state and a lock.
//
// WHEN ON, each action is one form with one submit button, and every submit
// asks to be confirmed before anything is sent. The body sent is the one shown
// in the confirmation, captured at that moment. Nothing is drawn as done until
// the server answers, and a refusal is the server's own sentence, printed as
// it arrived: the handlers (map_server.POST_ROUTES) and decree.plan_order hold
// every rule about what an order may be, and this page holds none of them.
//
// /api/frame is the one POST route with no form: it is how the stream agent
// uploads a picture, not something a person does.

import { html, raw, esc, pageHead, sectionHead, state, skeletons, plural } from "../ui.js";
import { post, refreshNow } from "../api.js";

// Watch modes, stream.MODES. A pov or cam client is kept alive by a heartbeat
// every stream.HEARTBEAT_SECONDS; shot and record need none.
export const WATCH_MODES = ["cam", "pov", "shot", "record"];
export const NEEDS_A_VIEWER = ["cam", "pov"];
export const BEAT_MS = 10000;

// What each action sends. `fixed` is merged into every body; `fields` are the
// inputs, named exactly as the handler reads them. `header` sends one field as
// a request header instead of in the body. tests/test_operator_view.py checks
// every path and name here against map_server.py and decree.py.
const FAMILY = { name: "family", label: "Family", choices: "families", typed: "the family key", hint: "Needed when the realm runs more than one family." };
export const ACTIONS = {
  job: {
    path: "/api/decree", fixed: { section: "job" }, submit: "Set the family's job",
    fields: [FAMILY, { name: "mode", label: "Job mode", choices: "modes", typed: "a job mode" }],
  },
  cap: {
    path: "/api/decree", fixed: { section: "campaign" }, submit: "Set the run cap",
    fields: [FAMILY, { name: "wanted", label: "Runs wanted", kind: "number", hint: "0 stops the campaign outright." }],
  },
  restart: {
    path: "/api/decree", fixed: { section: "campaign", restart: true }, submit: "Start the count again",
    fields: [FAMILY],
  },
  queue: {
    path: "/api/decree", fixed: { section: "queue" }, submit: "Set the queue",
    fields: [FAMILY, { name: "entries", label: "Dungeons and runs, in order", kind: "textarea", example: "queue" }],
  },
  unqueue: {
    path: "/api/decree", fixed: { section: "queue", clear: true }, submit: "Clear the queue",
    fields: [FAMILY],
  },
  aim: {
    path: "/api/decree", fixed: { section: "travel" }, submit: "Send them",
    fields: [{ name: "name", label: "Character", choices: "who", typed: "a character name" }, { name: "role", label: "Where to", choices: "roles", typed: "a role or a creature entry" }],
  },
  standdown: {
    // role "" is travel.NONE: the value that clears the aim.
    path: "/api/decree", fixed: { section: "travel", role: "" }, submit: "Stand them down",
    fields: [{ name: "name", label: "Character", choices: "who", typed: "a character name" }],
  },
  chat: {
    path: "/api/chat", submit: "Send",
    fields: [{ name: "name", label: "Character", choices: "who", typed: "a character name" }, { name: "text", label: "What to say", kind: "textarea" }],
  },
  will: {
    // The will is the chat route once per character, oldest first, in the
    // order /api/decree's will.audience gives. decree.py refuses section
    // "will" on its own route for exactly this reason.
    path: "/api/chat", fanout: true, submit: "Let the family overhear it",
    fields: [{ name: "text", label: "The decree", kind: "textarea" }],
  },
  watchStart: {
    path: "/api/watch", fixed: { action: "start" }, submit: "Start the stream",
    fields: [{ name: "name", label: "Character", choices: "who", typed: "a character name" }, { name: "mode", label: "Mode", choices: "watchModes", initial: "cam" }],
  },
  watchStop: {
    path: "/api/watch", fixed: { action: "stop" }, submit: "Stop the stream",
    fields: [{ name: "name", label: "Character", choices: "who", typed: "a character name" }],
  },
  director: {
    path: "/api/director", submit: "Point the Watcher",
    fields: [
      { name: "watch", label: "Order", example: "usage" },
      { name: "token", label: "Director token", kind: "password", header: "X-Director-Token" },
    ],
  },
};

// Per action: the drafted values, where it is in send -> confirm -> answer,
// and the body captured when it was confirmed. Kept here, not in the DOM,
// because every poll redraws the page.
const forms = {};
function form(id) {
  if (!forms[id]) {
    const draft = {};
    ACTIONS[id].fields.forEach((f) => { draft[f.name] = f.initial || ""; });
    forms[id] = { draft, phase: "idle", body: null, headers: null, answer: null };
  }
  return forms[id];
}

let lastCtx = null;
let lastOn = false;
let bound = false;
const beat = { name: "", mode: "", timer: null, note: "" };

// ---- what the forms are given to choose from ------------------------------------

function choices(key, dec) {
  const d = dec || {};
  if (key === "families") return (d.families || []).map((f) => ({ value: f.key, label: f.label || f.key }));
  if (key === "modes") return ((d.job && d.job.chips) || []).map((c) => ({ value: c.mode, label: c.sendable ? c.mode : c.mode + " (not built)" }));
  if (key === "who") return ((d.travel && d.travel.who) || []).map((n) => ({ value: n, label: n }));
  if (key === "roles") return ((d.travel && d.travel.chips) || []).map((c) => ({ value: c.role, label: c.role }));
  if (key === "watchModes") return WATCH_MODES.map((m) => ({ value: m, label: m }));
  return [];
}

function example(key, dec, dir) {
  if (key === "queue") return (dec && dec.queue && dec.queue.example) || "";
  if (key === "usage") return (dir && dir.usage) || "";
  return "";
}

// A select when the console read says what the choices are, a text box when it
// did not answer: the server checks the value either way.
function control(id, f, dec, dir) {
  const st = form(id);
  const fid = "op-" + id + "-" + f.name;
  const locked = st.phase === "confirm" || st.phase === "sending";
  const val = st.draft[f.name];
  // With no choices to offer, the box says what to type in their place.
  // The Watcher's grammar is too long for a placeholder, so it is a hint.
  const said = f.example ? example(f.example, dec, dir) : "";
  const ph = f.example === "usage" ? "" : said || (f.typed ? "Type " + f.typed : "");
  const hint = f.hint || (f.example === "usage" && said ? "Orders: " + said : "");
  const opts = f.choices ? choices(f.choices, dec) : [];
  const dis = locked ? raw(" disabled") : "";
  let input;
  if (opts.length) {
    const known = opts.some((o) => o.value === val);
    input = html`<select class="input" id="${fid}" name="${f.name}" data-op-field="${id}"${dis}>${known ? "" : html`<option value="${val}" selected>${val ? val : "Pick one"}</option>`}${opts.map((o) => html`<option value="${o.value}"${o.value === val ? raw(" selected") : ""}>${o.label}</option>`)}</select>`;
  } else if (f.kind === "textarea") {
    input = html`<textarea class="input op-text" id="${fid}" name="${f.name}" data-op-field="${id}" rows="3"${ph ? raw(' placeholder="' + esc(ph) + '"') : ""}${dis}>${val}</textarea>`;
  } else {
    const type = f.kind === "password" ? "password" : "text";
    const mode = f.kind === "number" ? raw(' inputmode="numeric"') : "";
    const value = f.kind === "password" ? "" : raw(' value="' + esc(val) + '"');
    input = html`<input class="input" type="${type}" id="${fid}" name="${f.name}" data-op-field="${id}" autocomplete="off" spellcheck="false"${value}${mode}${ph ? raw(' placeholder="' + esc(ph) + '"') : ""}${dis}>`;
  }
  return html`<div class="op-field"><label for="${fid}">${f.label}</label>${input}${hint ? html`<span class="op-hint">${hint}</span>` : ""}</div>`;
}

// ---- the body, and what a person is asked to confirm ------------------------------

// A whole number typed as digits goes as a number; anything else goes as typed
// and the server's refusal says what was wrong with it.
function typed(f, v) {
  const s = String(v == null ? "" : v);
  if (f.kind === "number" && /^\s*\d+\s*$/.test(s)) return Number(s);
  return f.kind === "textarea" ? s : s.trim();
}

export function bodyOf(id, draft) {
  const a = ACTIONS[id];
  const body = Object.assign({}, a.fixed || {});
  const headers = {};
  a.fields.forEach((f) => {
    const v = typed(f, draft[f.name]);
    if (f.header) headers[f.header] = String(v);
    else body[f.name] = v;
  });
  return { body, headers };
}

function shown(v) {
  if (v === "") return "(empty)";
  if (v === true) return "yes";
  return String(v);
}

function confirmLines(id, st, dec) {
  const a = ACTIONS[id];
  const lines = Object.keys(st.body).map((k) => html`<li><span class="op-k">${k}</span> ${shown(st.body[k])}</li>`);
  Object.keys(st.headers).forEach((k) => lines.push(html`<li><span class="op-k">${k}</span> (hidden)</li>`));
  const who = a.fanout ? audience(dec) : [];
  const to = a.fanout ? html`<p class="op-hint">Sent once to each of: ${who.join(", ") || "nobody"}.</p>` : "";
  return html`<ul class="op-sent">${lines}</ul>${to}`;
}

function audience(dec) { return (dec && dec.will && dec.will.audience) || []; }

// ---- answers ----------------------------------------------------------------------

function refusalOf(res) {
  if (res.failed) return "The request did not get an answer (" + res.failed + "). It is not known whether it landed; the state on this page is read again.";
  const b = res.body;
  if (b && typeof b.error === "string" && b.error) return b.error;
  return "The server answered HTTP " + res.status + " without a reason.";
}

function successOf(id, res) {
  const b = res.body || {};
  if (id === "chat") {
    const parts = [b.say || ""];
    if (b.command) parts.push("Queued command row " + b.command_id + ": " + b.command + ".");
    if (b.degraded) parts.push("The inner voice did not answer, so this is the plain reply.");
    return { kind: b.present === false ? "neutral" : "ok", text: parts.filter(Boolean).join(" ") || "Sent." };
  }
  if (ACTIONS[id].path === "/api/decree") {
    return { kind: b.ok ? "ok" : "neutral", text: [b.says, b.note].filter(Boolean).join(" ") || "Sent." };
  }
  if (id === "director") {
    const mins = Math.round((Number(b.expires_in) || 0) / 60);
    return { kind: "ok", text: b.spec ? "The Watcher's order is now: " + b.spec + (mins ? ", for " + plural(mins, "minute") + "." : ".") : "The Watcher's order is cleared." };
  }
  if (id === "watchStart") return { kind: "ok", text: "The server took it" + (b.state ? ": the stream is " + b.state + "." : ".") };
  return { kind: "ok", text: "The server took it." };
}

function answerBlock(st) {
  const a = st.answer;
  if (!a) return "";
  if (a.list) {
    return html`<div class="op-answer" data-kind="list" role="status"><div class="t">Answers, in the order they were asked</div><ul class="op-heard">${a.list.map((r) => html`<li data-ok="${r.ok ? "1" : "0"}"><span class="op-k">${r.name}</span> ${r.text}</li>`)}</ul></div>`;
  }
  const title = a.kind === "refused" ? "Refused" : a.kind === "neutral" ? "Sent, nothing changed" : "Done";
  const icon = a.kind === "refused" ? "ph-warning-octagon" : a.kind === "neutral" ? "ph-info" : "ph-check-circle";
  return html`<div class="op-answer" data-kind="${a.kind}" role="${a.kind === "refused" ? "alert" : "status"}"><i class="ph ${icon}" aria-hidden="true"></i><div><div class="t">${title}</div><div class="b">${a.text}</div></div></div>`;
}

// ---- one form ------------------------------------------------------------------------

function footer(id, st, dec) {
  const a = ACTIONS[id];
  if (st.phase === "confirm") {
    return html`<div class="op-confirm" role="group" aria-labelledby="op-${id}-ask"><p class="t" id="op-${id}-ask">Send this to the realm?</p>${confirmLines(id, st, dec)}<div class="row"><button type="button" class="btn btn-primary" data-op-confirm="${id}" id="op-${id}-yes"><i class="ph ph-paper-plane-tilt" aria-hidden="true"></i>Yes, send it</button><button type="button" class="btn btn-secondary" data-op-cancel="${id}">Cancel</button></div></div>`;
  }
  if (st.phase === "sending") {
    return html`<div class="op-sending" role="status"><i class="ph ph-spinner-gap" aria-hidden="true"></i>Sending. Waiting for the server's answer.</div>`;
  }
  return html`${answerBlock(st)}<div class="row"><button type="submit" class="btn btn-primary" id="op-${id}-send">${a.submit}</button></div>`;
}

function formOf(id, title, lede, dec, dir) {
  const st = form(id);
  const a = ACTIONS[id];
  st.title = title; st.lede = lede;
  return html`<form class="op-form" data-op="${id}" data-path="${a.path}" novalidate${st.phase === "sending" ? raw(' aria-busy="true"') : ""}><div class="op-form-title">${title}</div>${lede ? html`<p class="op-lede">${lede}</p>` : ""}${a.fields.map((f) => control(id, f, dec, dir))}${footer(id, st, dec)}</form>`;
}

// ---- the console state (GET /api/decree) ---------------------------------------------

function sectionDoes(dec, key) {
  const s = ((dec && dec.sections) || []).find((x) => x.key === key);
  return s ? s.does : "";
}

function consoleState(read) {
  const wait = read.data === undefined
    ? (read.error
      ? html`<div class="state" data-kind="error" role="alert"><i class="ph ph-warning-octagon" aria-hidden="true"></i><div><div class="t">The decree console did not answer</div><div class="b">GET /api/decree failed (${read.error.message || "no answer"}). On a busy realm this read is slow and can time out, so the current job, run counts and queues are not known. The forms still send: the server checks every order itself. <button type="button" class="btn btn-ghost" data-action="retry">Retry</button></div></div></div>`
      : html`<div class="op-loading" role="status">${skeletons(1)}<span class="muted">Reading the decree console. This read can take a while.</span></div>`)
    : null;
  if (wait) return wait;
  const d = read.data;
  const fams = d.families || [];
  const stale = read.error ? state("stale", "Showing the last answer", "The decree read failed; this is from earlier.") : "";
  const famRows = fams.length
    ? fams.map((f) => html`<div class="op-fam"><div class="op-fam-name">${f.label || f.key}</div><ul class="op-lines"><li><span class="op-k">Job</span> ${(f.job && f.job.line) || html`<span class="unmeasured">not measured</span>`}${f.job && f.job.split_line ? html` <span class="muted">(${f.job.split_line})</span>` : ""}</li><li><span class="op-k">Campaign</span> ${(f.campaign && f.campaign.line) || html`<span class="unmeasured">not measured</span>`}${f.campaign && f.campaign.means ? " " + f.campaign.means : ""}${f.campaign && f.campaign.warning ? html` <span class="op-warn">${f.campaign.warning}</span>` : ""}</li><li><span class="op-k">Queue</span> ${(f.queue && f.queue.line) || html`<span class="unmeasured">not measured</span>`}</li></ul></div>`)
    : html`<p class="muted">${(d.job && d.job.line) || "No family is on the roster."}</p>`;
  const travel = d.travel && d.travel.line ? html`<div class="op-fam"><div class="op-fam-name">Travel</div><p class="muted">${d.travel.line}</p></div>` : "";
  const orders = (d.orders || []).slice(0, 4);
  const recent = orders.length
    ? html`<div class="op-fam"><div class="op-fam-name">Recent orders</div><ul class="op-lines">${orders.map((o) => html`<li data-tone="${o.tone || ""}">${o.verdict}${o.ago ? html` <span class="muted">${o.ago}</span>` : ""}</li>`)}</ul></div>`
    : "";
  return html`${stale}<div class="card op-console">${famRows}${travel}${recent}</div>`;
}

// ---- the Watcher (GET /api/director) ------------------------------------------------

function watcherState(read) {
  if (read.data === undefined) {
    return read.error
      ? state("error", "The Watcher's state did not answer", "GET /api/director failed (" + (read.error.message || "no answer") + "). Its current order is not known.")
      : skeletons(1);
  }
  const d = read.data;
  const off = d.enabled ? "" : html`<p class="op-warn">This server has no director token set, so it refuses every order.</p>`;
  const now = d.active
    ? html`Watching <strong>${d.spec}</strong>${d.target ? html` (${d.target})` : ""}, for ${plural(Math.max(1, Math.round((d.expires_in || 0) / 60)), "more minute")}.`
    : "No order. The Watcher is idle.";
  return html`<div class="card op-console"><p>${d.watcher || "The Watcher"}: ${now}</p>${d.note ? html`<p class="muted">${d.note}</p>` : ""}${off}</div>`;
}

// ---- the page ---------------------------------------------------------------------------

function lockCard(op) {
  if (op.data === undefined && !op.error) return skeletons(1);
  if (op.data === undefined) {
    return html`<div class="card op-lock"><span class="card-title op-lock-title"><i class="ph ph-lock-simple" aria-hidden="true"></i>Off on this deployment</span><span class="muted">The operator setting could not be read, so the controls stay locked. <button type="button" class="btn btn-ghost" data-action="retry">Retry</button></span></div>`;
  }
  return html`<div class="card op-lock"><span class="card-title op-lock-title"><i class="ph ph-lock-simple" aria-hidden="true"></i>Off on this deployment</span><span class="muted">Talking to a character, decrees, starting and stopping streams, and pointing the Watcher all queue commands the realm acts on. The rest of this app is read-only. These live on this separate route, which only works when the operator setting is turned on on the server.</span></div>`;
}

const LOCKED_CARDS = [
  { key: "job", title: "Standing job", send: "Set the family's job" },
  { key: "campaign", title: "Campaign counter", send: "Set the run cap" },
  { key: "queue", title: "Dungeon queue", send: "Set the queue" },
];

function lockedView(op, dec) {
  const wait = dec.data === undefined ? consoleState(dec) : null;
  const d = dec.data || {};
  const cards = wait || html`<div class="grid">${LOCKED_CARDS.map((c) => {
    const lines = (d.families || []).map((f) => f[c.key] && f[c.key].line).filter(Boolean);
    return html`<div class="card op-locked-card"><span class="card-title">${c.title}</span>${lines.length ? lines.map((l) => html`<span class="muted">${l}</span>`) : html`<span class="unmeasured">Current state not measured</span>`}<span class="op-hint">${sectionDoes(d, c.key)}</span><button type="button" class="btn btn-primary" disabled><i class="ph ph-lock-simple" aria-hidden="true"></i>${c.send}</button></div>`;
  })}</div>`;
  return html`${pageHead("Operator actions")}${lockCard(op)}${dec.error && dec.data ? state("stale", "Showing the last answer", "The decree read failed; the cards below are from earlier.") : ""}${cards}`;
}

function beatLine() {
  if (!beat.timer && !beat.note) return "";
  if (!beat.timer) return html`<p class="op-hint" role="status">${beat.note}</p>`;
  return html`<p class="op-hint" role="status">Holding ${beat.name}'s ${beat.mode} stream open: this page tells the server it is still watching every ${BEAT_MS / 1000} seconds. Leave this page or stop the stream to end it.</p>`;
}

function onView(dec, dirRead) {
  const d = dec.data;
  const dir = dirRead.data;
  const willReady = audience(d).length > 0;
  return html`${pageHead("Operator actions", "Every action asks you to confirm before it sends. The server checks each order and its answer is shown as it was given.")}
<div class="card op-lock"><span class="card-title op-lock-title"><i class="ph ph-lock-simple-open" aria-hidden="true"></i>On for this deployment</span><span class="muted">The operator setting is on, so these controls send orders to the realm.</span></div>
<section class="op-sec" aria-labelledby="op-h-decree">${sectionHead("01", html`<span id="op-h-decree">Decree console</span>`)}${consoleState(dec)}
<div class="op-grid">
<div class="card op-card">${formOf("job", "Standing job", sectionDoes(d, "job"), d)}</div>
<div class="card op-card">${formOf("cap", "Campaign counter", sectionDoes(d, "campaign"), d)}${formOf("restart", "Start the count again", "Sets the runs done back to the start on every member of the family.", d)}</div>
<div class="card op-card">${formOf("queue", "Dungeon queue", sectionDoes(d, "queue"), d)}${formOf("unqueue", "Clear the queue", "", d)}</div>
<div class="card op-card">${formOf("aim", "Travel", (d && d.travel && d.travel.caveat) || sectionDoes(d, "travel"), d)}${formOf("standdown", "Stand them down", "", d)}</div>
<div class="card op-card">${willReady ? formOf("will", "Speak to the family", "Every one of them hears it and answers in their own words, oldest first.", d) : html`<div class="op-form-title">Speak to the family</div>${state("unmeasured", "Waiting for the console", "Who hears the decree comes from the decree console read, which has not answered.")}`}</div>
</div></section>
<section class="op-sec" aria-labelledby="op-h-chat">${sectionHead("02", html`<span id="op-h-chat">Talk to a character</span>`)}<div class="op-grid"><div class="card op-card">${formOf("chat", "One character", "Your words are kept even if the character does not answer.", d)}</div></div></section>
<section class="op-sec" aria-labelledby="op-h-streams">${sectionHead("03", html`<span id="op-h-streams">Streams</span>`)}<div class="op-grid"><div class="card op-card">${formOf("watchStart", "Start a stream", "cam and pov need a viewer and end after a minute of silence; shot takes one picture; record runs unattended.", d)}${beatLine()}</div><div class="card op-card">${formOf("watchStop", "Stop a stream", "", d)}</div></div></section>
<section class="op-sec" aria-labelledby="op-h-watcher">${sectionHead("04", html`<span id="op-h-watcher">The Watcher</span>`)}${watcherState(dirRead)}<div class="op-grid"><div class="card op-card">${formOf("director", "Point the Watcher", "", d, dir)}</div></div></section>
<p class="op-hint op-foot">The stream agent's picture upload (POST /api/frame) is not an operator action and has no form here.</p>`;
}

// ---- sending -------------------------------------------------------------------------

function redrawForm(id) {
  const el = document.querySelector('form[data-op="' + id + '"]');
  if (!el || !lastCtx) return;
  // Only this form is drawn again, from the same builder the page uses, so a
  // half-typed draft in the form beside it is left alone.
  const st = form(id);
  const tmp = document.createElement("div");
  tmp.innerHTML = formOf(id, st.title, st.lede, lastCtx.get("/api/decree").data, lastCtx.get("/api/director").data).s;
  el.parentNode.replaceChild(tmp.firstChild, el);
}

function focusIn(id, sel) {
  const el = document.querySelector('form[data-op="' + id + '"] ' + sel);
  if (el) el.focus();
}

async function sendOne(id, st) {
  const res = await post(ACTIONS[id].path, st.body, st.headers);
  if (res.ok) {
    const s = successOf(id, res);
    st.answer = { kind: s.kind, text: s.text };
    if (id === "watchStart" && NEEDS_A_VIEWER.includes(st.body.mode)) startBeat(st.body.name, st.body.mode);
    if (id === "watchStop" && st.body.name === beat.name) stopBeat("");
  } else {
    st.answer = { kind: "refused", text: refusalOf(res) };
  }
}

async function sendFanout(id, st) {
  const list = [];
  for (const name of audience(lastCtx && lastCtx.get("/api/decree").data)) {
    const res = await post(ACTIONS[id].path, Object.assign({ name }, st.body), st.headers);
    list.push({ name, ok: res.ok, text: res.ok ? successOf("chat", res).text : refusalOf(res) });
  }
  st.answer = { list };
}

async function confirmed(id) {
  const st = form(id);
  if (st.phase !== "confirm" || !lastOn) return;
  st.phase = "sending";
  redrawForm(id);
  if (ACTIONS[id].fanout) await sendFanout(id, st);
  else await sendOne(id, st);
  st.phase = "idle";
  st.body = null; st.headers = null;
  redrawForm(id);
  focusIn(id, ".op-answer, button[type=submit]");
  // What the realm says now belongs to the reads, not to this answer.
  refreshNow();
}

// ---- the heartbeat for a stream started here -------------------------------------

function startBeat(name, mode) {
  stopBeat("");
  beat.name = name; beat.mode = mode;
  beat.timer = window.setInterval(async () => {
    if (!String(location.hash || "").startsWith("#/operator") || !lastOn) { stopBeat("Stopped holding " + name + "'s stream open: this page was left."); return; }
    const res = await post("/api/watch", { name, action: "beat", mode }, {});
    if (!res.ok) stopBeat("Stopped holding " + name + "'s stream open: " + refusalOf(res));
  }, BEAT_MS);
}

function stopBeat(note) {
  if (beat.timer) window.clearInterval(beat.timer);
  beat.timer = null;
  beat.note = note;
  if (note) redrawForm("watchStart");
}

function bind(main) {
  if (bound) return;
  bound = true;
  const fieldOf = (e) => e.target.closest && e.target.closest("[data-op-field]");
  const keep = (e) => {
    const el = fieldOf(e);
    if (!el) return;
    form(el.getAttribute("data-op-field")).draft[el.name] = el.value;
  };
  main.addEventListener("input", keep);
  main.addEventListener("change", keep);
  main.addEventListener("submit", (e) => {
    const f = e.target.closest && e.target.closest("form[data-op]");
    if (!f) return;
    e.preventDefault();
    const id = f.getAttribute("data-op");
    const st = form(id);
    if (!lastOn || st.phase !== "idle") return;
    const sent = bodyOf(id, st.draft);
    st.body = sent.body; st.headers = sent.headers; st.answer = null;
    st.phase = "confirm";
    redrawForm(id);
    focusIn(id, "[data-op-confirm]");
  });
  main.addEventListener("click", (e) => {
    const yes = e.target.closest && e.target.closest("[data-op-confirm]");
    if (yes) { e.preventDefault(); confirmed(yes.getAttribute("data-op-confirm")); return; }
    const no = e.target.closest && e.target.closest("[data-op-cancel]");
    if (no) {
      e.preventDefault();
      const id = no.getAttribute("data-op-cancel");
      const st = form(id);
      st.phase = "idle"; st.body = null; st.headers = null;
      redrawForm(id);
      focusIn(id, "button[type=submit]");
    }
  });
}

export default {
  css: ["views/operator.css"],
  reads: (ctx) => {
    const op = ctx.get("/api/v2/operator");
    const on = !!(op.data && op.data.enabled);
    return on ? ["/api/v2/operator", "/api/decree", "/api/director"] : ["/api/v2/operator", "/api/decree"];
  },
  every: 30000,
  title: () => "Operator actions",
  render(ctx) {
    lastCtx = ctx;
    const op = ctx.get("/api/v2/operator");
    lastOn = !!(op.data && op.data.enabled);
    const dec = ctx.get("/api/decree");
    if (!lastOn) return lockedView(op, dec);
    return onView(dec, ctx.get("/api/director"));
  },
  after(main) {
    if (!lastOn) return;
    bind(main);
    // A password is never written into the markup; it is put back here.
    main.querySelectorAll('input[type="password"][data-op-field]').forEach((el) => {
      el.value = form(el.getAttribute("data-op-field")).draft[el.name] || "";
    });
  },
};

