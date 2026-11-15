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

function label(runs, id) {
  const r = (runs || []).find((x) => Number(x.id) === id);
  return r ? r.guild + " in " + (r.place || r.keyword || "a dungeon") : "run " + id;
}

// The camera's own card: what it is on, why it is not showing yet, the picture.
// Always carries the status line, so a refusal has somewhere to be read.
export function stage(spRead, runs) {
  const sp = camera(spRead);
  const status = html`<p class="sp-msg" role="status" data-spectate-msg>${message}</p>`;
  if (!sp || !sp.active) return html`<div class="sp-region">${status}</div>`;
  const on = sp.run ? label(runs, sp.run) : sp.spec;
  const who = sp.target ? html` Following ${sp.target}.` : "";
  const why = !sp.target && sp.note ? html`<p class="muted sp-note">Waiting: ${sp.note}</p>` : "";
  const picture = sp.stream
    ? html`<div class="sp-slot" data-spectate-slot data-stream="${sp.stream}"></div>`
    : html`<p class="muted sp-note">The camera has no stream address yet.</p>`;
  return html`<div class="sp-region">${status}<div class="card sp-stage" aria-live="polite">
<span class="g-name"><i class="ph-fill ph-video-camera" aria-hidden="true"></i> Now watching ${on}.${who}</span>
${why}${picture}
<span class="muted sp-note">This is the camera's view, an invisible observer that follows the group. The interface on screen belongs to the camera, not to any of them.${wait(sp)}</span>
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
  const run = Number(button.getAttribute("data-spectate-run"));
  button.disabled = true;
  say("");
  const res = await post(READ, { run });
  if (!res.ok) say(failureWords(res));
  await load(READ);
  button.disabled = false;
}

// Run after every draw: the buttons, and the picture put back in its slot.
export function bind(main) {
  main.querySelectorAll("button[data-spectate-run]").forEach((b) => {
    b.addEventListener("click", () => { order(b); });
  });
  const slot = main.querySelector("[data-spectate-slot]");
  if (!slot) { stopPicture(); return; }
  const url = slot.getAttribute("data-stream");
  if (!kept.video) {
    kept.video = document.createElement("video");
    kept.video.className = "sp-video";
    kept.video.muted = true;
    kept.video.setAttribute("playsinline", "");
    kept.video.controls = true;
    kept.status = document.createElement("p");
    kept.status.className = "muted sp-note";
    kept.player = makePlayer(kept.video, (text) => { kept.status.textContent = text; });
  }
  slot.append(kept.video, kept.status);
  if (kept.url !== url) {
    kept.url = url;
    kept.player.start("the camera", url);
  }
}

function stopPicture() {
  if (kept.player && kept.url) kept.player.stop();
  kept.url = "";
}

