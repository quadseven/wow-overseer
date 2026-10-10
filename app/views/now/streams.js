// The live tiles on Now: one picture per streamed character, playing the
// broadcast /api/wall names over WHEP (whep.js).
//
// The pictures are built once and moved, never rebuilt. A view redraws its
// markup every time a read answers, and rebuilding a <video> would tear down
// its PeerConnection and re-buffer a stream that was playing fine. So the
// view draws an empty slot (`data-stream="<name>"`) and mount() moves the
// living picture into it. Leaving Now stops every picture; it never stops a
// broadcast, which is not this page's to stop.

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
  pic.append(video, off, badge);
  t = { name, pic, video, off, offT, offB, badge, state: "off", started: false, lastAttempt: 0, lastFrame: 0, url: "" };
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
    if (t.pic.parentElement !== slot) slot.appendChild(t.pic);
    if (t.video.srcObject && t.video.paused) t.video.play().catch(() => {});
  });
  applyAudio();
  ageTick();
}

export function stopAll() {
  tiles.forEach((t) => {
    t.player.stop();
    t.started = false;
    setState(t, "off", "");
  });
  heard = null;
}

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
const FRAMES = [
  ["BAG", "Bags", "bags"],
  ["BNK", "Bank", "bank"],
  ["GBK", "Guild bank", "guildbank"],
  ["CHR", "Character", "gear"],
  ["SOC", "Social", ""],
  ["QST", "Quest log", "quests"],
];

function frameHref(name, tab) {
  if (tab === "guildbank") return "#/economy/bank";
  return memberHref(name, tab);
}

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
  return html`<figure class="st">
<div class="st-slot" data-stream="${name}"></div>
<figcaption class="st-cap">
<div class="st-head"><a class="st-name" href="${memberHref(name)}" style="color:${classVar(m["class"])}">${name}</a><span class="st-sub">${sub}</span><span class="st-age" data-frame-age="${name}">no frame</span></div>
${doingLine(t && t.now)}
<div class="st-bar"><button type="button" class="btn btn-secondary st-hear" data-hear="${name}" aria-pressed="false"><i class="ph ph-speaker-slash" aria-hidden="true"></i>Hear</button><span class="st-hear-note dim" data-hear-note="${name}" role="status"></span>
<div class="st-frames">${FRAMES.map(([mark, label, tab]) => html`<a class="st-frame" href="${frameHref(name, tab)}" title="${label}, ${name}" aria-label="${label}, ${name}">${mark}</a>`)}</div></div>
</figcaption></figure>`;
}

// Bind the Hear buttons under `root`.
export function bind(root) {
  root.querySelectorAll("[data-hear]").forEach((b) => {
    b.addEventListener("click", () => toggleHear(b.getAttribute("data-hear")));
  });
}
