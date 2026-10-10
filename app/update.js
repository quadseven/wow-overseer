// A new deploy, picked up without losing the reader's place.
//
// A phone keeps this page open for hours and goes on running the code it
// loaded. The page carries the build it was served with (the overseer-build
// meta, appbuild.py), and /api/realm reports the build the server holds now
// (`app_build`). When the two differ:
//   - a small "Updated" toast offers the refresh; a tap reloads the page and
//     puts the reader back where they were on it;
//   - the next move to another page reloads instead, which loses nothing,
//     because that page starts at the top anyway.
// Nothing reloads by itself while someone is reading or typing.
//
// The realm read is asked again when the page comes back on screen and
// every few minutes while it is shown; any other view that reads /api/realm
// feeds the same check.

import { load, onChange, peek } from "./api.js";
import { html } from "./ui.js";

const REALM = "/api/realm";
const CHECK_MS = 5 * 60 * 1000;
const PLACE_KEY = "overseer.place";
const SETTLE_MS = 6000;
const BUILD = /^[0-9a-f]{12}$/;

// The build this page was served with; "" when the server did not stamp one
// (an old server, or the file opened from disk), which turns the check off.
export function servedBuild(doc) {
  const d = doc || (typeof document !== "undefined" ? document : null);
  const meta = d && d.querySelector ? d.querySelector('meta[name="overseer-build"]') : null;
  const v = meta ? meta.getAttribute("content") || "" : "";
  return BUILD.test(v) ? v : "";
}

// True when the server reports a build, this page knows its own, and they differ.
export function isNewer(served, reported) {
  return BUILD.test(served || "") && BUILD.test(reported || "") && served !== reported;
}

// "#/members?stuck=1" -> "#/members": a filter or sort is the same page.
export function routePath(hash) { return String(hash || "").split("?")[0]; }

let served = "";
let pending = false;
let toast = null;

export function pendingUpdate() { return pending; }

function examine(entry) {
  if (pending || !entry || !entry.data) return;
  if (isNewer(served, entry.data.app_build)) {
    pending = true;
    showToast();
  }
}

export function check() {
  return load(REALM).then(examine);
}

function showToast() {
  if (toast || typeof document === "undefined") return;
  toast = document.createElement("div");
  toast.className = "update-toast";
  toast.setAttribute("role", "status");
  toast.innerHTML = html`<button type="button" class="update-btn" data-update="reload"><i class="ph ph-arrow-clockwise" aria-hidden="true"></i><span>Updated, tap to refresh</span></button>`.s;
  toast.addEventListener("click", (e) => {
    if (e.target.closest('[data-update="reload"]')) reloadHere();
  });
  document.body.appendChild(toast);
}

function typing() {
  const el = document.activeElement;
  if (!el) return false;
  return /^(INPUT|SELECT|TEXTAREA)$/.test(el.tagName || "") || !!el.isContentEditable;
}

// The tap on the toast: keep the place on this page, then reload.
export function reloadHere() {
  try {
    window.sessionStorage.setItem(PLACE_KEY, JSON.stringify({ hash: location.hash, y: Math.round(window.scrollY) }));
  } catch (err) { /* storage off: the reload starts at the top */ }
  location.reload();
}

// Called on every hash change before the router draws. When a new build is
// waiting and the move is to another page (not a filter on this one), with
// nobody typing, the page reloads at the new address and the router does not
// draw. Returns true when it reloaded.
let lastPath = typeof location !== "undefined" ? routePath(location.hash) : "";

export function reloadIfPending() {
  const path = routePath(location.hash);
  const moved = path !== lastPath;
  lastPath = path;
  if (!pending || !moved || typing()) return false;
  location.reload();
  return true;
}

// After a reload from the toast: the scroll offset to restore on this hash,
// once (0 when there is none). The router scrolls there on its first draw;
// draws in the next few seconds, as the reads come in and the page grows,
// scroll there again until the reader moves.
let settle = null;

export function takePlace(hash) {
  let kept = null;
  try {
    const raw = window.sessionStorage.getItem(PLACE_KEY);
    window.sessionStorage.removeItem(PLACE_KEY);
    kept = raw ? JSON.parse(raw) : null;
  } catch (err) { kept = null; }
  if (!kept || kept.hash !== hash || !(kept.y > 0)) return 0;
  settle = { y: kept.y, until: Date.now() + SETTLE_MS };
  return kept.y;
}

function resettle() {
  if (!settle) return;
  if (Date.now() > settle.until) { settle = null; return; }
  const y = settle.y;
  window.requestAnimationFrame(() => {
    if (settle && Math.abs(window.scrollY - y) > 2) window.scrollTo(0, y);
  });
}

function stopSettling() { settle = null; }

export function install() {
  served = servedBuild();
  if (!served) return;
  lastPath = routePath(location.hash);
  onChange((path) => {
    if (path === REALM) examine(peek(REALM));
    resettle();
  });
  ["wheel", "touchstart", "keydown"].forEach((t) => window.addEventListener(t, stopSettling, { passive: true }));
  document.addEventListener("visibilitychange", () => { if (!document.hidden) check(); });
  window.setInterval(() => { if (!document.hidden) check(); }, CHECK_MS);
  check();
}
