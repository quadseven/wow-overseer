// The Watch control on a live dungeon group, and the camera's "now watching" card.
//
// One observer character follows whoever the site last pointed it at, so there
// is one camera and one stream, shared by everyone looking. The server decides
// everything: GET /api/spectate says where the camera is and how long until a
// different group may take it; POST /api/spectate {run} points it, and answers
// in words when it will not (a second group inside the dwell is a 409). This
// only draws that, sends the one integer, and plays the picture.
//
// The picture is the OBSERVER's view of the group, not any character's own
// screen: the interface on it belongs to the camera.

import { html } from "../ui.js";
import { load, post } from "../api.js";
import { makePlayer } from "./now/whep.js";

export const CSS = "views/spectate.css";
export const READ = "/api/spectate";
export const OPERATOR = "/api/v2/operator";

// The last refusal or failure, kept across redraws (the page replaces its body
// on every read) until the next click or until the order goes through.
let message = "";

// The one <video> and its player, kept across redraws for the reason clips keep
// theirs: rebuilding the element would drop the connection and restart it.
const kept = { video: null, player: null, url: "", status: null };

function camera(read) { return read && read.data ? read.data : null; }
function operatorOn(read) { return !!(read && read.data && read.data.enabled); }

function wait(sp) {
  const n = Number(sp.switch_in) || 0;
  return n > 0 ? " It can be switched in " + n + " seconds." : "";
}

// The control on one run card. `spRead` and `opRead` are peek() results.
export function control(run, spRead, opRead) {
  const sp = camera(spRead);
  const id = Number(run && run.id);
  if (!sp) return html`<div class="sp-ctl"><button type="button" class="btn btn-secondary sp-btn" disabled><i class="ph ph-video-camera" aria-hidden="true"></i>Watch</button><span class="muted sp-hint">The camera has not been read yet.</span></div>`;
  if (sp.active && sp.run === id) {
    return html`<div class="sp-ctl"><span class="sp-on" data-state="on"><i class="ph-fill ph-video-camera" aria-hidden="true"></i>Now watching</span></div>`;
  }
  if (!operatorOn(opRead)) {
    return html`<div class="sp-ctl"><button type="button" class="btn btn-secondary sp-btn" disabled><i class="ph ph-video-camera" aria-hidden="true"></i>Watch</button><span class="muted sp-hint">Operator actions are off on this site, so the camera cannot be pointed from here.</span></div>`;
  }
  const other = sp.active && sp.run !== id;
  return html`<div class="sp-ctl"><button type="button" class="btn btn-secondary sp-btn" data-spectate-run="${id}"><i class="ph ph-video-camera" aria-hidden="true"></i>${other ? "Watch instead" : "Watch"}</button>${other ? html`<span class="muted sp-hint">The camera is on another group.${wait(sp)}</span>` : ""}</div>`;
}

// A Watch button on one character (a roster row, a family card, a map list).
// The same states as a run's button, in less room: the reason it is disabled
// is the button's title, and the one status line (notice()) says why a click
// failed. `spRead` and `opRead` are peek() or ctx.get() results.
export function charButton(name, spRead, opRead) {
  const sp = camera(spRead);
  const who = String(name || "");
  const icon = html`<i class="ph ph-video-camera" aria-hidden="true"></i>`;
  if (!sp) return html`<button type="button" class="btn btn-secondary sp-btn sp-mini" disabled title="The camera has not been read yet.">${icon}Watch</button>`;
  if (sp.active && sp.character === who) {
    return html`<span class="sp-on sp-mini" data-state="on"><i class="ph-fill ph-video-camera" aria-hidden="true"></i>Now watching</span>`;
  }
  if (!operatorOn(opRead)) {
    return html`<button type="button" class="btn btn-secondary sp-btn sp-mini" disabled title="Operator actions are off on this site, so the camera cannot be pointed from here.">${icon}Watch</button>`;
  }
  const other = sp.active && sp.character !== who;
  const title = other ? "The camera is on another target." + wait(sp) : "Point the Watcher at " + who + ".";
  return html`<button type="button" class="btn btn-secondary sp-btn sp-mini" data-spectate-char="${who}" title="${title}">${icon}${other ? "Watch instead" : "Watch"}</button>`;
}

// A Jump in button for one live group: `order` is what /api/live gave, either
// {run} or {character}. Same states as the buttons above.
export function jumpButton(order, spRead, opRead) {
  const sp = camera(spRead);
  const byRun = order && order.run !== undefined;
  const icon = html`<i class="ph ph-video-camera" aria-hidden="true"></i>`;
  const on = sp && sp.active && (byRun ? sp.run === Number(order.run) : sp.character === order.character);
  if (on) return html`<span class="sp-on sp-mini" data-state="on"><i class="ph-fill ph-video-camera" aria-hidden="true"></i>Now watching</span>`;
  if (!sp || !operatorOn(opRead)) {
    const why = !sp ? "The camera has not been read yet." : "Operator actions are off on this site, so the camera cannot be pointed from here.";
    return html`<button type="button" class="btn btn-secondary sp-btn sp-mini" disabled title="${why}">${icon}Jump in</button>`;
  }
  if (byRun) return html`<button type="button" class="btn btn-secondary sp-btn sp-mini" data-spectate-run="${Number(order.run)}">${icon}Jump in</button>`;
  return html`<button type="button" class="btn btn-secondary sp-btn sp-mini" data-spectate-char="${String(order.character || "")}">${icon}Jump in</button>`;
}

// The one status line a view with Watch buttons carries, so a refusal (the
// dwell, the switch off) has somewhere to be read.
export function notice() {
  return html`<p class="sp-msg" role="status" data-spectate-msg>${message}</p>`;
}

function label(runs, id) {
  const r = (runs || []).find((x) => Number(x.id) === id);
  return r ? r.guild + " in " + (r.place || r.keyword || "a dungeon") : "run " + id;
}

// The camera's own card: what it is on, why it is not showing yet, the picture,
// and (when `opRead` says operator actions are on) a Stop button. Always carries
// the status line, so a refusal has somewhere to be read. With `idle` set, an
// unwatched camera still draws a card, saying so, instead of nothing.
export function stage(spRead, runs, opRead, idle) {
  const sp = camera(spRead);
  const status = html`<p class="sp-msg" role="status" data-spectate-msg>${message}</p>`;
  if (!sp || !sp.active) {
    if (!idle || !sp) return html`<div class="sp-region">${status}</div>`;
    return html`<div class="sp-region">${status}<div class="card sp-stage"><span class="g-name"><i class="ph ph-video-camera" aria-hidden="true"></i> The Watcher is not watching anyone.</span><span class="muted sp-note">Press Watch on a character or Jump in on a live group to point it.</span></div></div>`;
  }
  const on = sp.run ? label(runs, sp.run) : sp.character || sp.spec;
  const who = sp.target && sp.target !== sp.character ? html` Following ${sp.target}.` : "";
  const way = sp.character && sp.target ? html`<p class="muted sp-note">The Watcher is on its way to ${sp.target}. Until it arrives the picture shows wherever it is now.</p>` : "";
  // The director's latest word, which is the reason when the Watcher is not
  // moving (no target yet, or its moves are held).
  const why = !sp.note ? "" : !sp.target ? html`<p class="muted sp-note">Waiting: ${sp.note}</p>` : html`<p class="muted sp-note">Latest from the camera: ${sp.note}</p>`;
  const stop = operatorOn(opRead) ? html`<button type="button" class="btn btn-secondary sp-btn sp-stop" data-spectate-stop><i class="ph ph-stop" aria-hidden="true"></i>Stop watching</button>` : "";
  // Not the wall's `data-stream`: Now's wall moves a family picture into every
  // slot carrying that, and one in here covered the whole page.
  const picture = sp.stream
    ? html`<div class="sp-slot" data-spectate-slot data-spectate-stream="${sp.stream}"><p class="muted sp-note" data-spectate-wait>Starting the Watcher's stream. If it stays dark, the Watcher's client may be off.</p></div>`
    : html`<p class="muted sp-note">The camera has no stream address yet.</p>`;
  return html`<div class="sp-region">${status}<div class="card sp-stage" aria-live="polite">
<span class="g-name"><i class="ph-fill ph-video-camera" aria-hidden="true"></i> Now watching ${on}.${who}</span>
${way}${why}${picture}${stop}
<span class="muted sp-note">This is the camera's view, an invisible observer that follows the target. The interface on screen belongs to the camera, not to any of them.${wait(sp)}</span>
</div></div>`;
}

function say(text) {
  message = text;
  document.querySelectorAll("[data-spectate-msg]").forEach((n) => { n.textContent = text; });
}

function failureWords(res) {
  const why = res.body && res.body.error ? String(res.body.error) : "";
  if (res.status === 403) return "Operator actions are off on this site, so the camera cannot be pointed from here.";
  if (res.status === 409 || res.status === 400) return why || "The camera would not move.";
  if (res.status === 503) return "The world did not answer, so the camera was not moved.";
  return "The order did not go through" + (res.failed ? " (" + res.failed + ")" : res.status ? " (HTTP " + res.status + ")" : "") + ".";
}

async function order(button) {
  const body = {};
  if (button.hasAttribute("data-spectate-run")) body.run = Number(button.getAttribute("data-spectate-run"));
  else if (button.hasAttribute("data-spectate-char")) body.character = button.getAttribute("data-spectate-char");
  else body.stop = true;
  button.disabled = true;
  say("");
  const res = await post(READ, body);
  if (!res.ok) say(failureWords(res));
  await load(READ);
  button.disabled = false;
}

// Run after every draw: the buttons, and the picture put back in its slot.
export function bind(main) {
  main.querySelectorAll("button[data-spectate-run], button[data-spectate-char], button[data-spectate-stop]").forEach((b) => {
    b.addEventListener("click", () => { order(b); });
  });
  const slot = main.querySelector("[data-spectate-slot]");
  // A view with no Watcher slot (or a renderer that answers every selector
  // with something that is not an element) has no picture to place.
  if (!slot || typeof slot.getAttribute !== "function") { stopPicture(); return; }
  const url = slot.getAttribute("data-spectate-stream");
  if (!kept.video) {
    kept.video = document.createElement("video");
    kept.video.className = "sp-video";
    kept.video.muted = true;
    kept.video.setAttribute("playsinline", "");
    kept.video.controls = true;
    kept.status = document.createElement("p");
    kept.status.className = "muted sp-note";
    kept.player = makePlayer(kept.video, (text) => {
      kept.status.textContent = text;
      // The player has its own word now, so the "starting" line goes.
      document.querySelectorAll("[data-spectate-wait]").forEach((n) => { n.hidden = true; });
    });
  }
  slot.append(kept.video, kept.status);
  // A redraw draws the "starting" line again; once the player has spoken it stays hidden.
  if (kept.status.textContent && typeof slot.querySelector === "function") {
    const wait = slot.querySelector("[data-spectate-wait]");
    if (wait) wait.hidden = true;
  }
  if (kept.url !== url) {
    kept.url = url;
    kept.player.start("the camera", url);
  }
}

function stopPicture() {
  if (kept.player && kept.url) kept.player.stop();
  kept.url = "";
}

