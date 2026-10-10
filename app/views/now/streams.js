// The live tiles on Now: one picture per streamed character, playing the
// broadcast /api/wall names over WHEP (whep.js).
//
// The pictures are built once and moved, never rebuilt. A view redraws its
// markup every time a read answers, and rebuilding a <video> would tear down
// its PeerConnection and re-buffer a stream that was playing fine. So the
// view draws an empty slot (`data-stream="<name>"`) and mount() moves the
// living picture into it. Leaving Now stops every picture; it never stops a
// broadcast, which is not this page's to stop.
//
// Full screen takes the living picture itself (its video, badge and the
// control that brings it back), so the WHEP stream plays on untouched. While
// it is full screen the picture is held at the foot of <body>: a redraw
// replaces the slot it came from, and a full screen element taken out of the
// document leaves full screen. Leaving full screen moves it back into its slot.

import { html, memberHref, duration, classVar } from "../../ui.js";
import { makePlayer, hasSound } from "./whep.js";

const tiles = new Map(); // name -> tile
let heard = null;        // the one tile heard; off on every load (autoplay policy)
const RETRY_MS = 20000;

function el(tag, cls) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  return n;
}

function setState(t, state, text) {
  t.state = state;
  t.pic.dataset.state = state;
  t.badge.lastChild.textContent = state === "live" ? "LIVE" : state === "connecting" ? "CONNECTING" : "OFF";
  t.offT.textContent = state === "connecting" ? "Connecting to the stream" : "No picture";
  t.offB.textContent = text || "";
}

// requestVideoFrameCallback says when a frame was actually painted, which is
// the frame age the caption shows. Without it, timeupdate is the fallback.
function trackFrames(t) {
  const v = t.video;
  if (typeof v.requestVideoFrameCallback === "function") {
    const loop = () => { t.lastFrame = Date.now(); v.requestVideoFrameCallback(loop); };
    v.requestVideoFrameCallback(loop);
  } else {
    v.addEventListener("timeupdate", () => { t.lastFrame = Date.now(); });
  }
}

function tile(name) {
  let t = tiles.get(name);
  if (t) return t;
  const pic = el("div", "st-pic");
  const video = el("video", "st-video");
  video.muted = true; video.autoplay = true; video.playsInline = true;
  video.setAttribute("muted", ""); video.setAttribute("playsinline", "");
  video.setAttribute("aria-label", name + "'s stream");
  const off = el("div", "st-off");
  const icon = el("i", "ph ph-video-camera-slash");
  icon.setAttribute("aria-hidden", "true");
  const offT = el("span", "st-off-t");
  const offB = el("span", "st-off-b");
  off.append(icon, offT, offB);
  const badge = el("span", "st-badge");
  badge.append(el("span", "st-badge-dot"), el("span"));
  // An id, so a redraw that moves the picture gives the control its focus back.
  const full = el("button", "st-full");
  full.type = "button";
  full.id = "st-full-" + name;
  full.append(el("i"));
  pic.append(video, off, badge, full);
  t = { name, pic, video, off, offT, offB, badge, full, isFull: false, state: "off", started: false, lastAttempt: 0, lastFrame: 0, url: "" };
  full.addEventListener("click", () => toggleFullscreen(t));
  video.addEventListener("webkitendfullscreen", () => leftFullscreen(t));
  fullLabel(t);
  t.player = makePlayer(video, (text, kind) => {
    if (kind === "live") setState(t, "live", "");
    else if (kind === "warn") setState(t, "off", text);
    else setState(t, "connecting", text);
  });
  trackFrames(t);
  setState(t, "off", "");
  tiles.set(name, t);
  return t;
}

// Start (or retry) the picture for `name` at `url`. A tile with no URL is
// not streamed: it says so and connects to nothing.
export function connect(name, url) {
  const t = tile(name);
  if (!url) {
    if (t.started) { t.player.stop(); t.started = false; }
    setState(t, "off", "This character is not streamed.");
    return;
  }
  const now = Date.now();
  if (!t.started || t.url !== url) {
    t.started = true; t.url = url; t.lastAttempt = now;
    t.player.start(name, url);
  } else if (t.state === "off" && now - t.lastAttempt > RETRY_MS) {
    t.lastAttempt = now;
    t.player.stop();
    t.player.start(name, url);
  }
}

// Move every living picture into its slot under `root`.
export function mount(root) {
  root.querySelectorAll("[data-stream]").forEach((slot) => {
    const t = tile(slot.getAttribute("data-stream"));
    if (t.isFull) return;
    if (t.pic.parentElement !== slot) slot.appendChild(t.pic);
    if (t.video.srcObject && t.video.paused) t.video.play().catch(() => {});
  });
  applyAudio();
  ageTick();
}

export function stopAll() {
  if (fullscreenElement(document)) exitFullscreen(document);
  tiles.forEach((t) => {
    t.player.stop();
    t.started = false;
    setState(t, "off", "");
  });
  heard = null;
}

// ---- full screen ------------------------------------------------------------
// The standard API on the picture where the browser has it (desktop, iPad,
// Android), webkit's prefixed one on older Safari, and on iPhone, where only
// a video may go full screen, the video's own native player. Returns which
// one it asked: "element", "webkit", "video", or "" when there is none.
// `refused` is called if the browser turns the standard request down.
export function enterFullscreen(pic, video, refused) {
  if (typeof pic.requestFullscreen === "function") {
    const p = pic.requestFullscreen();
    if (p && typeof p.catch === "function") p.catch(() => { if (refused) refused(); });
    return "element";
  }
  if (typeof pic.webkitRequestFullscreen === "function") { pic.webkitRequestFullscreen(); return "webkit"; }
  if (typeof video.webkitEnterFullscreen === "function") { video.webkitEnterFullscreen(); return "video"; }
  return "";
}

export function fullscreenElement(doc) {
  return doc.fullscreenElement || doc.webkitFullscreenElement || null;
}

function exitFullscreen(doc) {
  if (typeof doc.exitFullscreen === "function") return doc.exitFullscreen().catch(() => {});
  if (typeof doc.webkitExitFullscreen === "function") doc.webkitExitFullscreen();
  return null;
}

function fullLabel(t) {
  const on = t.isFull;
  t.full.setAttribute("aria-label", (on ? "Exit full screen, " : "Full screen, ") + t.name + "'s stream");
  t.full.title = on ? "Exit full screen" : "Full screen";
  t.full.firstChild.className = on ? "ph ph-corners-in" : "ph ph-corners-out";
  t.full.firstChild.setAttribute("aria-hidden", "true");
  t.pic.classList.toggle("is-full", on);
}

export function toggleFullscreen(t) {
  if (t.isFull && fullscreenElement(document) === t.pic) { exitFullscreen(document); return "exit"; }
  // Held at the foot of <body> first, so no redraw can take it out of the page.
  t.isFull = true;
  document.body.appendChild(t.pic);
  t.full.focus({ preventScroll: true });
  const how = enterFullscreen(t.pic, t.video, () => { if (t.isFull) leftFullscreen(t); });
  if (!how) { leftFullscreen(t); return ""; }
  fullLabel(t);
  if (t.video.srcObject && t.video.paused) t.video.play().catch(() => {});
  return how;
}

// Back into its slot (if Now is still on screen) and playing.
function leftFullscreen(t) {
  t.isFull = false;
  fullLabel(t);
  const slot = document.querySelector('[data-stream="' + CSS.escape(t.name) + '"]');
  if (slot) { slot.appendChild(t.pic); t.full.focus({ preventScroll: true }); }
  else t.pic.remove();
  if (t.video.srcObject && t.video.paused) t.video.play().catch(() => {});
}

function onFullscreenChange() {
  const now = fullscreenElement(document);
  tiles.forEach((t) => { if (t.isFull && now !== t.pic && !t.video.webkitDisplayingFullscreen) leftFullscreen(t); });
}
document.addEventListener("fullscreenchange", onFullscreenChange);
document.addEventListener("webkitfullscreenchange", onFullscreenChange);

// ---- sound: exactly one tile is ever heard -----------------------------
function applyAudio() {
  tiles.forEach((t) => {
    const on = t.name === heard;
    if (t.video.muted === on) t.video.muted = !on;
    if (on && t.video.paused && t.video.srcObject) t.video.play().catch(() => {});
  });
  document.querySelectorAll("[data-hear]").forEach((b) => {
    const name = b.getAttribute("data-hear");
    const on = name === heard;
    b.setAttribute("aria-pressed", String(on));
    const icon = b.querySelector("i");
    if (icon) icon.className = on ? "ph-fill ph-speaker-high" : "ph ph-speaker-slash";
    const word = b.querySelector(".st-hear-l");
    if (word) word.textContent = on ? "Hearing" : "Hear";
    const t = tiles.get(name);
    let say = "";
    if (on && (!t || !t.video.srcObject)) say = "Waiting for " + name + "'s stream.";
    else if (on && !hasSound(t.video)) say = name + "'s stream has no sound yet.";
    const note = document.querySelector('[data-hear-note="' + CSS.escape(name) + '"]');
    if (note && note.textContent !== say) note.textContent = say;
  });
}

// Called from a click, which is what lets the unmute past the autoplay policy.
export function toggleHear(name) {
  heard = heard === name ? null : name;
  applyAudio();
}

// ---- frame age ------------------------------------------------------------
function ageText(t) {
  if (!t || t.state !== "live") return "no frame";
  if (!t.lastFrame) return "frame age not measured";
  const s = Math.max(0, Math.round((Date.now() - t.lastFrame) / 1000));
  return "frame " + s + "s old";
}

function ageTick() {
  document.querySelectorAll("[data-frame-age]").forEach((n) => {
    const text = ageText(tiles.get(n.getAttribute("data-frame-age")));
    if (n.textContent !== text) n.textContent = text;
  });
}

window.setInterval(() => { if (!document.hidden) { ageTick(); applyAudio(); } }, 1000);

// Leaving Now stops the pictures (the broadcasts keep running).
window.addEventListener("hashchange", () => {
  if (!/^#\/now\/?(\?|$)/.test(location.hash)) stopAll();
});

// ---- the caption ----------------------------------------------------------
// The member's frames, each opened as a panel over Now (panel.js), never a
// page of its own: the pictures keep playing. [key, label, icon].
export const ACTIONS = [
  ["bags", "Bags", "ph-backpack"],
  ["bank", "Bank", "ph-vault"],
  ["guildbank", "Guild bank", "ph-bank"],
  ["gear", "Character", "ph-t-shirt"],
  ["social", "Social", "ph-users-three"],
  ["quests", "Quests", "ph-scroll"],
];

function trim(s) { return String(s).replace(/[.\s]+$/, ""); }

function doingLine(now) {
  if (!now || now.known === false || !now.doing) {
    return html`<div class="st-doing"><span class="dim">Doing:</span> <span class="unmeasured">not measured</span></div>`;
  }
  const forText = now.for_s !== null && now.for_s !== undefined ? " (for " + duration(now.for_s) + ")" : "";
  return html`<div class="st-doing"><span class="dim">Doing:</span> ${trim(now.doing)}.${now.waiting ? html` <span class="dim">Waiting for:</span> ${trim(now.waiting)}${forText}.` : ""}</div>`;
}

// One tile: the slot the picture moves into, then the caption. `m` is the
// /api/wall member, `t` its wall tile.
export function tileHtml(m, t) {
  const name = m.name;
  const sub = [t && t.standing, t && t.line].filter(Boolean).join(", ");
  return html`<figure class="st" data-class="${m["class"] || ""}">
<div class="st-slot" data-stream="${name}"></div>
<figcaption class="st-cap">
<div class="st-head"><a class="st-name" href="${memberHref(name)}" style="color:${classVar(m["class"])}">${name}</a><span class="st-sub">${sub}</span><span class="st-age" data-frame-age="${name}">no frame</span></div>
${doingLine(t && t.now)}
<div class="st-bar"><button type="button" class="st-hear" data-hear="${name}" data-focus="${"hear-" + name}" aria-pressed="false"><i class="ph ph-speaker-slash" aria-hidden="true"></i><span class="st-hear-l">Hear</span></button><span class="st-hear-note dim" data-hear-note="${name}" role="status"></span></div>
<div class="st-acts" role="group" aria-label="${name + "'s frames"}">${ACTIONS.map(([key, label, icon]) => html`<button type="button" class="st-act" data-panel="${key}" data-name="${name}" data-focus="${"act-" + key + "-" + name}" aria-haspopup="dialog" aria-label="${label + ", " + name}"><i class="${"ph " + icon}" aria-hidden="true"></i><span>${label}</span></button>`)}</div>
</figcaption></figure>`;
}

// Bind the Hear buttons and the frame buttons under `root`. A frame button
// calls `openPanel(name, key, button)`: a panel over this page, no navigation.
export function bind(root, openPanel) {
  root.querySelectorAll("[data-hear]").forEach((b) => {
    b.addEventListener("click", () => toggleHear(b.getAttribute("data-hear")));
  });
  root.querySelectorAll("[data-panel]").forEach((b) => {
    b.addEventListener("click", () => openPanel(b.getAttribute("data-name"), b.getAttribute("data-panel"), b));
  });
}
