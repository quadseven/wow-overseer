// Operator actions. Talking to a character, decrees and pointing the Watcher
// queue commands the realm acts on, so they
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

// What each action sends. `fixed` is merged into every body; `fields` are the
// inputs, named exactly as the handler reads them. `header` sends one field as
// a request header instead of in the body. tests/test_operator_view.py checks
// every path and name here against map_server.py and decree.py.
const FAMILY = { name: "family", label: "Family", choices: "families", typed: "the family key", hint: "Needed when the realm runs more than one family.", need: "Pick which family this is for." };
export const ACTIONS = {
  job: {
    path: "/api/decree", fixed: { section: "job" }, submit: "Set the family's job",
    fields: [FAMILY, { name: "mode", label: "Job mode", choices: "modes", typed: "a job mode", need: "Pick a job mode." }],
  },
  muster: {
    path: "/api/decree", fixed: { section: "muster" }, submit: "Send to the guild",
    fields: [{ name: "guild", label: "Guild name", typed: "a guild name", need: "Name the guild." },
      { name: "command", label: "Order", kind: "textarea", need: "Type the order." }],
  },
  guildrun: {
    path: "/api/decree", fixed: { section: "guildrun" }, submit: "Form the run",
    fields: [{ name: "guild", label: "Guild name", typed: "a guild name", need: "Name the guild." },
      { name: "keyword", label: "Dungeon keyword", typed: "a dungeon keyword such as scarlet-armory", need: "Type a dungeon keyword." }],
  },
  cap: {
    path: "/api/decree", fixed: { section: "campaign" }, submit: "Set the run cap",
    fields: [FAMILY, { name: "wanted", label: "Runs wanted", kind: "number", hint: "0 stops the campaign outright.", need: "Type how many runs are wanted. 0 stops the campaign." }],
  },
  restart: {
    path: "/api/decree", fixed: { section: "campaign", restart: true }, submit: "Start the count again",
    fields: [FAMILY],
  },
  queue: {
    path: "/api/decree", fixed: { section: "queue" }, submit: "Set the queue",
    fields: [FAMILY, { name: "entries", label: "Dungeons and runs, in order", kind: "textarea", example: "queue", need: "Type the dungeons and runs, in order." }],
  },
  unqueue: {
    path: "/api/decree", fixed: { section: "queue", clear: true }, submit: "Clear the queue",
    fields: [FAMILY],
  },
  aim: {
    path: "/api/decree", fixed: { section: "travel" }, submit: "Send them",
    fields: [{ name: "name", label: "Character", choices: "who", typed: "a character name", need: "Pick who to send." }, { name: "role", label: "Where to", choices: "roles", typed: "a role or a creature entry", need: "Pick where to send them." }],
  },
  standdown: {
    // role "" is travel.NONE: the value that clears the aim.
    path: "/api/decree", fixed: { section: "travel", role: "" }, submit: "Stand them down",
    fields: [{ name: "name", label: "Character", choices: "who", typed: "a character name", need: "Pick who to stand down." }],
  },
  chat: {
    path: "/api/chat", submit: "Send",
    fields: [{ name: "name", label: "Character", choices: "who", typed: "a character name", need: "Pick who to talk to." }, { name: "text", label: "What to say", kind: "textarea", need: "Type what to say." }],
  },
  priorities: {
    // The whole ranking, highest first. decree.py holds it to a full
    // permutation of the fixed list (priorities.validate) and refuses
    // anything else; this page only reorders what the read gave it.
    path: "/api/decree", fixed: { section: "priorities" }, submit: "Save this order",
    fields: [{ name: "order", label: "Highest first", kind: "ranked", need: "The saved order is not read yet." }],
  },
  unrank: {
    path: "/api/decree", fixed: { section: "priorities", reset: true }, submit: "Reset to default",
    fields: [],
  },
  will: {
    // The will is the chat route once per character, oldest first, in the
    // order /api/decree's will.audience gives. decree.py refuses section
    // "will" on its own route for exactly this reason. `section` here is
    // not sent (it is not in `fixed`); it names the console card whose
    // can_send this form honours.
    path: "/api/chat", fanout: true, section: "will", submit: "Let the family overhear it",
    fields: [{ name: "text", label: "The decree", kind: "textarea", need: "Type the decree." }],
  },
  director: {
    path: "/api/director", submit: "Point the Watcher",
    fields: [
      { name: "watch", label: "Order", example: "usage", need: "Type the Watcher's order." },
      { name: "token", label: "Director token", kind: "password", header: "X-Director-Token", need: "Type the director token." },
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
    forms[id] = { draft, phase: "idle", body: null, headers: null, answer: null, invalid: null, invalidField: null, touched: false, sentCount: 0 };
  }
  return forms[id];
}

let lastCtx = null;
let lastOn = false;
let bound = false;
let dragging = null;

// ---- what the forms are given to choose from ------------------------------------

function choices(key, dec) {
  const d = dec || {};
  if (key === "families") return (d.families || []).map((f) => ({ value: f.key, label: f.label || f.key }));
  if (key === "modes") return ((d.job && d.job.chips) || []).map((c) => ({ value: c.mode, label: c.sendable ? c.mode : c.mode + " (not built)" }));
  if (key === "who") return ((d.travel && d.travel.who) || []).map((n) => ({ value: n, label: n }));
  if (key === "roles") return ((d.travel && d.travel.chips) || []).map((c) => ({ value: c.role, label: c.role }));
  return [];
}

function example(key, dec, dir) {
  if (key === "queue") return (dec && dec.queue && dec.queue.example) || "";
  if (key === "usage") return (dir && dir.usage) || "";
  return "";
}

// ---- the console's word on whether a card may be sent ------------------------------
//
// The decree read carries per-section can_send, why_not and instead
// (decree.py). A section that cannot be sent renders its form disabled
// with the read's own sentences where the submit was: the page never
// decides this for itself, and a section the read does not mention, or
// one whose can_send is not false, is left as it was.

function sectionOf(id, dec) {
  const a = ACTIONS[id];
  const key = (a.fixed && a.fixed.section) || a.section || "";
  if (!key) return null;
  return ((dec && dec.sections) || []).find((x) => x.key === key) || null;
}

function blockedOf(id, dec) {
  const s = sectionOf(id, dec);
  return !!(s && s.can_send === false);
}

function blockedBlock(id, dec) {
  const s = sectionOf(id, dec) || {};
  const tag = (dec && dec.refusal_tag) || "This cannot be sent from here";
  return html`<div class="op-blocked" role="note"><p class="t">${tag}</p>${s.why_not ? html`<p>${s.why_not}</p>` : ""}${s.instead ? html`<p>${s.instead}</p>` : ""}</div>`;
}

// ---- the family's priorities (decree.py's priorities card, #1559) ----------------

// The saved order, as the console read gives it, or [] before it answers.
function savedOrder(dec) {
  return ((dec && dec.priorities && dec.priorities.order) || []).slice();
}

function sameSet(a, b) {
  return a.length === b.length && a.every((x) => b.includes(x)) && new Set(a).size === a.length;
}

// What the list shows: the operator's unsaved reorder while it is still a
// ranking of the same priorities, else the saved order.
function shownOrder(id, dec) {
  const saved = savedOrder(dec);
  const draft = form(id).draft.order;
  return Array.isArray(draft) && sameSet(draft, saved) ? draft.slice() : saved;
}

// `pid` moved to `rank` (1 is highest), the rest shifted rather than swapped:
// the same rule as priorities.move.
export function moveTo(order, pid, rank) {
  const rest = order.filter((x) => x !== pid);
  if (rest.length === order.length) return order.slice();
  const at = Math.max(0, Math.min(rest.length, rank - 1));
  rest.splice(at, 0, pid);
  return rest;
}

function entryOf(dec, pid) {
  return ((dec && dec.priorities && dec.priorities.entries) || []).find((e) => e.id === pid) || { id: pid, label: pid, sentence: "" };
}

function rankedControl(id, f, dec) {
  const st = form(id);
  const order = shownOrder(id, dec);
  const locked = st.phase === "confirm" || st.phase === "sending" || blockedOf(id, dec);
  const fid = "op-" + id + "-" + f.name;
  const dis = locked ? raw(" disabled") : "";
  const rows = order.map((pid, i) => {
    const e = entryOf(dec, pid);
    const up = locked || i === 0 ? raw(" disabled") : "";
    const down = locked || i === order.length - 1 ? raw(" disabled") : "";
    return html`<li class="op-rank-item" data-op-rank="${id}" data-pid="${pid}"${locked ? "" : raw(' draggable="true"')} tabindex="0" aria-label="${i + 1}. ${e.label}. ${e.sentence}"><span class="op-rank-n" aria-hidden="true">${i + 1}</span><span class="op-rank-text"><span class="op-rank-label">${e.label}</span><span class="op-rank-sentence">${e.sentence}</span></span><span class="op-rank-moves"><button type="button" class="btn btn-ghost op-rank-btn" data-op-move="up" data-op-rank="${id}" data-pid="${pid}" aria-label="Move ${e.label} up"${up}><i class="ph ph-arrow-up" aria-hidden="true"></i></button><button type="button" class="btn btn-ghost op-rank-btn" data-op-move="down" data-op-rank="${id}" data-pid="${pid}" aria-label="Move ${e.label} down"${down}><i class="ph ph-arrow-down" aria-hidden="true"></i></button></span></li>`;
  });
  const changed = order.join(",") !== savedOrder(dec).join(",");
  const list = order.length
    ? html`<ol class="op-rank" id="${fid}-list" aria-labelledby="${fid}-label">${rows}</ol>`
    : html`<span class="unmeasured">The saved order is not read yet. It comes from the decree console read.</span>`;
  return html`<div class="op-field"><span class="op-flabel" id="${fid}-label">${f.label}</span>${list}<input type="hidden" id="${fid}" name="${f.name}" data-op-field="${id}" value="${order.join(",")}"${dis}><span class="op-hint"><span class="op-hint-fine">Drag a row, use its arrows, or focus it and press Alt with the up or down arrow.</span></span>${changed ? html`<span class="op-hint op-unsaved" role="status">Not saved yet. Until it is, the family keeps the saved order.</span>` : ""}</div>`;
}

function reorder(id, pid, rank) {
  const dec = lastCtx && lastCtx.get("/api/decree").data;
  const st = form(id);
  if (st.phase !== "idle") return;
  if (blockedOf(id, dec)) return;
  st.touched = true;
  if (st.invalidField === "order") { st.invalid = null; st.invalidField = null; }
  st.draft.order = moveTo(shownOrder(id, dec), pid, rank);
  st.answer = null;
  redrawForm(id);
}

function rankOf(id, pid) {
  const dec = lastCtx && lastCtx.get("/api/decree").data;
  return shownOrder(id, dec).indexOf(pid) + 1;
}

function prioritiesCard(d, agendaRead) {
  const p = (d && d.priorities) || null;
  const a = agendaRead && agendaRead.data;
  const now = a && a.headline
    ? html`<p class="op-pri-now">${a.headline}</p>`
    : agendaRead && agendaRead.error
      ? html`<p class="unmeasured">What the family is doing now did not answer (${agendaRead.error.message || "no answer"}).</p>`
      : html`<p class="unmeasured">What the family is doing now is not read yet.</p>`;
  const said = p ? html`<p class="op-hint">${p.state_says}</p>` : "";
  return html`<div class="card op-card op-pri"><div class="op-pri-side"><div class="op-form-title">Doing now</div>${now}<p class="op-hint">${(p && p.takes_effect) || ""}</p>${said}</div><div class="op-pri-main">${formOf("priorities", "Family priorities", sectionDoes(d, "priorities"), d)}${formOf("unrank", "Reset to default", "Puts the default order back through the same save.", d)}</div></div>`;
}

// A select when the console read says what the choices are, a text box when it
// did not answer: the server checks the value either way.
function control(id, f, dec, dir) {
  if (f.kind === "ranked") return rankedControl(id, f, dec);
  const st = form(id);
  const fid = "op-" + id + "-" + f.name;
  const locked = st.phase === "confirm" || st.phase === "sending" || blockedOf(id, dec);
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
  if (f.kind === "ranked") return Array.isArray(v) ? v.slice() : String(v == null ? "" : v).split(",").filter(Boolean);
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

// The first field with nothing in it, or null when the form is complete.
// Every field is required: an empty one is a sentence the server would
// refuse, said here first with the field's own name for what is missing.
// A typed 0 is a value (it stops a campaign), not a blank.
function missingField(id, st) {
  for (const f of ACTIONS[id].fields) {
    const v = typed(f, st.draft[f.name]);
    if (Array.isArray(v) ? v.length === 0 : String(v).trim() === "") return f;
  }
  return null;
}

// ---- what a person is asked to confirm, in plain words ---------------------------
//
// The confirm names the action, not the wire: family labels rather than
// keys, the words being sent in quotes, and nothing the person did not
// type (the fixed fields and the director token are never shown). The five
// destructive actions carry a consequence line and their own verb on the
// button, so they cannot be mistaken for a reversible send.

function familyLabel(dec, key) {
  const f = ((dec && dec.families) || []).find((x) => x.key === key);
  return (f && f.label) || key;
}

function quoted(s) { return '"' + String(s == null ? "" : s) + '"'; }

function confirmSpec(id, st, dec) {
  const b = st.body || {};
  const fam = b.family !== undefined ? familyLabel(dec, b.family) : "";
  switch (id) {
    case "job":
      return { heading: "Set the family's job", lines: [["Family", fam], ["Job mode", b.mode]] };
    case "muster":
      return { heading: "Send to the guild", lines: [["Guild", b.guild], ["Order", quoted(b.command)]] };
    case "guildrun":
      return { heading: "Form the run", lines: [["Guild", b.guild], ["Dungeon", b.keyword]] };
    case "cap":
      if (Number(b.wanted) === 0) {
        return {
          heading: "Stop the campaign", lines: [["Family", fam], ["Runs wanted", 0]],
          danger: { verb: "Yes, stop the campaign", consequence: "The campaign stops outright. The family runs no more dungeons until the cap is set above 0 again." },
        };
      }
      return { heading: "Set the run cap", lines: [["Family", fam], ["Runs wanted", b.wanted]] };
    case "restart":
      return {
        heading: "Start the count again", lines: [["Family", fam]],
        danger: { verb: "Yes, start the count again", consequence: "Every member's runs done count goes back to the start. The runs themselves are not undone." },
      };
    case "queue":
      return { heading: "Set the queue", lines: [["Family", fam], ["Queue", quoted(b.entries)]] };
    case "unqueue":
      return {
        heading: "Clear the queue", lines: [["Family", fam]],
        danger: { verb: "Yes, clear the queue", consequence: "The waiting dungeons are wiped. A run already going is not stopped." },
      };
    case "aim":
      return { heading: "Send them", lines: [["Character", b.name], ["Where to", b.role]] };
    case "standdown":
      return {
        heading: "Stand them down", lines: [["Character", b.name]],
        danger: { verb: "Yes, stand them down", consequence: "Their errand is cleared outright rather than replaced. Whatever they were walking to is given up." },
      };
    case "chat":
      return { heading: "Send this to " + b.name, lines: [quoted(b.text)] };
    case "priorities": {
      const names = (b.order || []).map((pid, i) => (i + 1) + ". " + entryOf(dec, pid).label).join(", ");
      return { heading: "Save this order", lines: [["Highest first", names]] };
    }
    case "unrank":
      return {
        heading: "Reset the priorities", lines: [],
        danger: { verb: "Yes, reset the priorities", consequence: "The ranking goes back to the default order. The order on screen now is lost." },
      };
    case "will": {
      const who = audience(dec);
      return {
        heading: "Let the family overhear it",
        lines: [quoted(b.text), ["Heard by", who.length + " of them: " + who.join(", ")]],
        note: "It goes to each of them one by one, and a line already sent cannot be unsent.",
      };
    }
    case "director":
      return { heading: "Point the Watcher", lines: [["Order", quoted(b.watch)]] };
    default:
      return { heading: ACTIONS[id].submit, lines: [] };
  }
}

function confirmBlock(id, st, dec) {
  const spec = confirmSpec(id, st, dec);
  const danger = spec.danger || null;
  const lines = spec.lines.length
    ? html`<ul class="op-sent">${spec.lines.map((l) => Array.isArray(l)
      ? html`<li><span class="op-k">${l[0]}</span> ${l[1]}</li>`
      : html`<li>${l}</li>`)}</ul>`
    : "";
  return html`<div class="op-confirm"${danger ? raw(' data-danger="1"') : ""} role="group" aria-labelledby="op-${id}-ask"><p class="t" id="op-${id}-ask">${spec.heading}</p>${lines}${spec.note ? html`<p class="op-hint">${spec.note}</p>` : ""}${danger ? html`<p class="op-consequence">${danger.consequence}</p>` : ""}<div class="row"><button type="button" class="btn ${danger ? "btn-danger" : "btn-primary"}" data-op-confirm="${id}" id="op-${id}-yes"><i class="ph ph-paper-plane-tilt" aria-hidden="true"></i>${danger ? danger.verb : "Yes, send it"}</button><button type="button" class="btn btn-secondary" data-op-cancel="${id}">Cancel</button></div></div>`;
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
  if (blockedOf(id, dec)) {
    return blockedBlock(id, dec);
  }
  if (st.phase === "confirm") {
    return confirmBlock(id, st, dec);
  }
  if (st.phase === "sending") {
    if (a.fanout) {
      const total = audience(dec).length;
      const line = st.sentCount ? "Sent " + st.sentCount + " of " + total + "." : "Sending to " + total + " of them, one by one.";
      return html`<div class="op-sending" role="status"><i class="ph ph-spinner-gap" aria-hidden="true"></i>${line}</div>`;
    }
    return html`<div class="op-sending" role="status"><i class="ph ph-spinner-gap" aria-hidden="true"></i>Sending. Waiting for the server's answer.</div>`;
  }
  return html`${answerBlock(st)}${st.invalid ? html`<p class="op-invalid" role="alert">${st.invalid}</p>` : ""}<div class="row"><button type="submit" class="btn btn-primary" id="op-${id}-send">${a.submit}</button></div>`;
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
    ? fams.map((f) => html`<div class="op-fam"><div class="op-fam-name">${f.label || f.key}</div><ul class="op-lines"><li><span class="op-k">Job</span> ${(f.job && f.job.line) || html`<span class="unmeasured">not measured</span>`}${f.job && f.job.split_line ? html` <span class="muted">(${f.job.split_line})</span>` : ""}</li>${f.job && f.job.members_line ? html`<li><span class="op-k">Each member</span> ${f.job.members_line}</li>` : ""}${f.job && f.job.link && f.job.link.line ? html`<li><span class="op-k">Linked</span> ${f.job.link.line}</li>` : ""}<li><span class="op-k">Campaign</span> ${(f.campaign && f.campaign.line) || html`<span class="unmeasured">not measured</span>`}${f.campaign && f.campaign.means ? " " + f.campaign.means : ""}${f.campaign && f.campaign.warning ? html` <span class="op-warn">${f.campaign.warning}</span>` : ""}</li><li><span class="op-k">Queue</span> ${(f.queue && f.queue.line) || html`<span class="unmeasured">not measured</span>`}</li></ul></div>`)
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
  { key: "muster", title: "Guild muster", send: "Send to the guild" },
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

function onView(dec, dirRead, agendaRead) {
  const d = dec.data;
  const dir = dirRead.data;
  const willReady = audience(d).length > 0;
  // Sections run in the order a phone reaches for them: Talk and Travel
  // first, the decree console behind them, the Watcher last.
  return html`${pageHead("Operator actions", "Every action asks you to confirm before it sends. The server checks each order and its answer is shown as it was given.")}
<div class="card op-lock"><span class="card-title op-lock-title"><i class="ph ph-lock-simple-open" aria-hidden="true"></i>On for this deployment</span><span class="muted">The operator setting is on, so these controls send orders to the realm.</span></div>
<section class="op-sec" aria-labelledby="op-h-talk">${sectionHead("01", html`<span id="op-h-talk">Talk to a character</span>`)}<div class="op-grid"><div class="card op-card">${formOf("chat", "One character", "Your words are kept even if the character does not answer.", d)}</div></div></section>
<section class="op-sec" aria-labelledby="op-h-travel">${sectionHead("02", html`<span id="op-h-travel">Travel</span>`)}<div class="op-grid"><div class="card op-card">${formOf("aim", "Send them somewhere", (d && d.travel && d.travel.caveat) || sectionDoes(d, "travel"), d)}${formOf("standdown", "Stand them down", "", d)}</div></div></section>
<section class="op-sec" aria-labelledby="op-h-decree">${sectionHead("03", html`<span id="op-h-decree">Decree console</span>`)}${consoleState(dec)}
${prioritiesCard(d, agendaRead)}
<div class="op-grid">
<div class="card op-card">${formOf("job", "Standing job", sectionDoes(d, "job"), d)}</div>
<div class="card op-card">${formOf("muster", "Guild muster", sectionDoes(d, "muster"), d)}</div>
<div class="card op-card">${formOf("guildrun", "Guild finder run", sectionDoes(d, "guildrun"), d)}</div>
<div class="card op-card">${formOf("cap", "Campaign counter", sectionDoes(d, "campaign"), d)}${formOf("restart", "Start the count again", "Sets the runs done back to the start on every member of the family.", d)}</div>
<div class="card op-card">${formOf("queue", "Dungeon queue", sectionDoes(d, "queue"), d)}${formOf("unqueue", "Clear the queue", "", d)}</div>
<div class="card op-card">${willReady ? formOf("will", "Speak to the family", "Every one of them hears it and answers in their own words, oldest first.", d) : html`<div class="op-form-title">Speak to the family</div>${state("unmeasured", "Waiting for the console", "Who hears the decree comes from the decree console read, which has not answered.")}`}</div>
</div></section>
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
  } else {
    st.answer = { kind: "refused", text: refusalOf(res) };
  }
}

async function sendFanout(id, st) {
  const list = [];
  for (const name of audience(lastCtx && lastCtx.get("/api/decree").data)) {
    const res = await post(ACTIONS[id].path, Object.assign({ name }, st.body), st.headers);
    list.push({ name, ok: res.ok, text: res.ok ? successOf("chat", res).text : refusalOf(res) });
    // The send is one by one and cannot be hurried; say how far it got.
    st.sentCount = list.length;
    redrawForm(id);
  }
  st.answer = { list };
}

async function confirmed(id) {
  const st = form(id);
  if (st.phase !== "confirm" || !lastOn) return;
  st.phase = "sending";
  st.sentCount = 0;
  redrawForm(id);
  if (ACTIONS[id].fanout) await sendFanout(id, st);
  else await sendOne(id, st);
  // A reset or a save hands the list back to the saved order once the read
  // comes round: the draft was the operator's, the order is now the realm's.
  if (id === "unrank" && st.answer && st.answer.kind !== "refused") form("priorities").draft.order = "";
  st.phase = "idle";
  st.touched = false;
  st.body = null; st.headers = null;
  redrawForm(id);
  focusIn(id, ".op-answer, button[type=submit]");
  // What the realm says now belongs to the reads, not to this answer.
  refreshNow();
}

function bind(main) {
  if (bound) return;
  bound = true;
  const fieldOf = (e) => e.target.closest && e.target.closest("[data-op-field]");
  const keep = (e) => {
    const el = fieldOf(e);
    if (!el) return;
    const st = form(el.getAttribute("data-op-field"));
    st.draft[el.name] = el.value;
    st.touched = true;
    // Typing in the named field answers its reason; the line itself goes
    // at the next redraw, so a keystroke never rebuilds the field being
    // typed in. Typing anywhere else leaves the reason standing.
    if (st.invalidField === el.name) { st.invalid = null; st.invalidField = null; }
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
    if (blockedOf(id, lastCtx && lastCtx.get("/api/decree").data)) return;
    // The ranking sent is the one on screen at this moment.
    if (ACTIONS[id].fields.some((x) => x.kind === "ranked")) {
      st.draft.order = shownOrder(id, lastCtx && lastCtx.get("/api/decree").data);
    }
    const miss = missingField(id, st);
    if (miss) {
      st.invalid = miss.need || "Type " + (miss.typed || "a value") + ".";
      st.invalidField = miss.name;
      st.answer = null;
      redrawForm(id);
      focusIn(id, '[name="' + miss.name + '"]');
      return;
    }
    st.invalid = null;
    st.invalidField = null;
    const sent = bodyOf(id, st.draft);
    st.body = sent.body; st.headers = sent.headers; st.answer = null;
    st.phase = "confirm";
    redrawForm(id);
    focusIn(id, "[data-op-confirm]");
  });
  main.addEventListener("click", (e) => {
    const mv = e.target.closest && e.target.closest("[data-op-move]");
    if (mv) {
      e.preventDefault();
      const id = mv.getAttribute("data-op-rank");
      const pid = mv.getAttribute("data-pid");
      const step = mv.getAttribute("data-op-move") === "up" ? -1 : 1;
      reorder(id, pid, rankOf(id, pid) + step);
      // Focus follows the row: its same arrow while it can still move that
      // way, the row itself once it has reached the end.
      focusIn(id, '[data-op-move="' + mv.getAttribute("data-op-move") + '"][data-pid="' + pid + '"]:not([disabled])');
      if (!document.activeElement || document.activeElement.getAttribute("data-pid") !== pid) focusIn(id, 'li[data-pid="' + pid + '"]');
      return;
    }
    const yes = e.target.closest && e.target.closest("[data-op-confirm]");
    if (yes) { e.preventDefault(); confirmed(yes.getAttribute("data-op-confirm")); return; }
    const no = e.target.closest && e.target.closest("[data-op-cancel]");
    if (no) {
      e.preventDefault();
      const id = no.getAttribute("data-op-cancel");
      const st = form(id);
      st.phase = "idle"; st.body = null; st.headers = null;
      // The confirm was put down on purpose; the draft stays in the
      // fields, and the poll may draw the page again.
      st.touched = false;
      redrawForm(id);
      focusIn(id, "button[type=submit]");
    }
  });
  // Alt+ArrowUp / Alt+ArrowDown on a focused priority moves it one place.
  main.addEventListener("keydown", (e) => {
    if (!e.altKey || (e.key !== "ArrowUp" && e.key !== "ArrowDown")) return;
    const li = e.target.closest && e.target.closest("li[data-op-rank]");
    if (!li) return;
    e.preventDefault();
    const id = li.getAttribute("data-op-rank");
    const pid = li.getAttribute("data-pid");
    reorder(id, pid, rankOf(id, pid) + (e.key === "ArrowUp" ? -1 : 1));
    focusIn(id, 'li[data-pid="' + pid + '"]');
  });
  // Drag a row onto another: it takes that row's place and the rest shift.
  main.addEventListener("dragstart", (e) => {
    const li = e.target.closest && e.target.closest("li[data-op-rank]");
    if (!li) return;
    dragging = { id: li.getAttribute("data-op-rank"), pid: li.getAttribute("data-pid") };
    if (e.dataTransfer) { e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", dragging.pid); }
  });
  main.addEventListener("dragover", (e) => {
    const li = e.target.closest && e.target.closest("li[data-op-rank]");
    if (li && dragging) e.preventDefault();
  });
  main.addEventListener("drop", (e) => {
    const li = e.target.closest && e.target.closest("li[data-op-rank]");
    if (!li || !dragging) return;
    e.preventDefault();
    const { id, pid } = dragging;
    dragging = null;
    if (li.getAttribute("data-op-rank") !== id) return;
    reorder(id, pid, rankOf(id, li.getAttribute("data-pid")));
    focusIn(id, 'li[data-pid="' + pid + '"]');
  });
  main.addEventListener("dragend", () => { dragging = null; });
}

// ---- the poll waits for the operator --------------------------------------------
//
// main.js offers a view its own swap, to keep what a plain swap would
// take out of the document. Here what it would take out is the operator:
// a form being typed in, a confirm standing open, a send in flight, a
// priority row mid drag. While any of those is live the swap is claimed
// and the page left exactly as it is, so the 30 second poll never
// redraws over a draft, a focus, a caret or a scroll. The next poll
// whose moment is quiet draws the page whole again.

function editingNow(main) {
  if (!main || typeof main.querySelector !== "function" || !main.querySelector('form[data-op]')) return false;
  if (dragging) return true;
  for (const id of Object.keys(forms)) {
    if (forms[id].phase === "confirm" || forms[id].phase === "sending") return true;
    // An unsent draft is an edit in progress whether or not its field
    // still holds the focus: a tap elsewhere must not cost the typing.
    if (forms[id].touched) return true;
  }
  const ae = typeof document !== "undefined" ? document.activeElement : null;
  if (ae && typeof ae.getAttribute === "function" && ae.getAttribute("data-op-field")
    && typeof main.contains === "function" && main.contains(ae)) return true;
  return false;
}

export default {
  css: ["views/operator.css"],
  reads: (ctx) => {
    const op = ctx.get("/api/v2/operator");
    const on = !!(op.data && op.data.enabled);
    return on ? ["/api/v2/operator", "/api/decree", "/api/director", "/api/agenda"] : ["/api/v2/operator", "/api/decree"];
  },
  every: 30000,
  title: () => "Operator actions",
  swap(main, body) {
    if (editingNow(main)) return true;
    main.innerHTML = body;
    return true;
  },
  render(ctx) {
    lastCtx = ctx;
    const op = ctx.get("/api/v2/operator");
    lastOn = !!(op.data && op.data.enabled);
    const dec = ctx.get("/api/decree");
    if (!lastOn) return lockedView(op, dec);
    return onView(dec, ctx.get("/api/director"), ctx.get("/api/agenda"));
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

