// Now's stage on a phone: the watched family's picture, pinned to the top of
// the screen, with a slim switcher under it.
//
// The stage element is drawn once by the shell (#stage) and lives outside
// <main>, so a redraw of the page never touches it: the staged <video> stays
// in the document. The pictures themselves still come from streams.js, which
// moves the living picture into the stage's slot (a slot named like the
// wall's, `data-stream`), so Hear, full screen and the picture states work as
// they do in the wall.

import { html } from "../../ui.js";
import * as streams from "./streams.js";
import { saveStage } from "../../store.js";
import { NARROW } from "../../breakpoint.js";
import { pickScroll, dotOn } from "./stagechoice.js";

export { NARROW };

export function isNarrow() {
  return typeof window !== "undefined" && typeof window.matchMedia === "function" && window.matchMedia(NARROW).matches;
}

let wired = false;
// What sync() last showed: the dots' ticker and stream-state listener read it between redraws.
let last = { options: [], staged: "", deps: {} };

function stageEl() { return document.getElementById("stage"); }

function dotsOf(el, options, deps) {
  const streamState = (deps && deps.streamState) || streams.stateOf;
  el.querySelectorAll("[data-stage-pick]").forEach((b) => {
    const o = options.find((x) => x.fam === b.getAttribute("data-stage-pick"));
    const live = dotOn(o, last.staged, o ? streamState(o.name) : "off");
    if (b.getAttribute("data-live") !== (live ? "1" : "0")) b.setAttribute("data-live", live ? "1" : "0");
  });
}

function switcher(options, staged) {
  return options.map((o) => html`<button type="button" class="stage-pick" data-stage-pick="${o.fam}" data-live="0" aria-pressed="${String(o.fam === staged)}" aria-label="${"Watch " + o.fam + "'s family"}"><span class="stage-dot" aria-hidden="true"></span><span class="stage-pick-l">${o.fam}</span></button>`).map(String).join("");
}

function stripMessage(options, o, state) {
  if (!options.length && !o) return "Checking live picture";
  if (!o) return "No stream active";
  const who = o.label || o.fam;
  if (state === "connecting") return who + ": connecting";
  return who + ": stream offline";
}

// Show the stage on a phone. Starts as a one-line strip so nothing below
// shifts when reads land, and only expands to the 16:9 picture when a stream
// actually plays (live or dark).
export function sync(options, staged, narrow, deps = {}) {
  const el = stageEl();
  if (!el) return;
  const streamState = deps.streamState || streams.stateOf;
  const mountStreams = deps.mount || streams.mount;
  const prevH = !el.hidden && typeof el.getBoundingClientRect === "function" ? el.getBoundingClientRect().height : 0;
  last = { options, staged, deps };
  const on = Boolean(narrow);
  el.hidden = !on;
  if (document.documentElement) document.documentElement.toggleAttribute("data-stage", on);
  if (!on) {
    el.removeAttribute("data-compact");
    return;
  }
  wire(el, deps);
  const o = staged ? options.find((x) => x.fam === staged) : null;
  const st = o ? streamState(o.name) : "none";
  const expanded = Boolean(o && (st === "live" || st === "dark"));
  if (expanded) el.removeAttribute("data-compact");
  else el.setAttribute("data-compact", "1");

  const msg = el.querySelector(".stage-msg");
  if (msg) msg.textContent = stripMessage(options, o, st);
  const retryBtn = el.querySelector("[data-stage-retry]");
  if (retryBtn) retryBtn.hidden = expanded || !o || !o.url;

  const slot = el.querySelector(".stage-slot");
  if (slot) {
    if (o) {
      if (slot.getAttribute("data-stream") !== o.name) {
        slot.replaceChildren();
        slot.setAttribute("data-stream", o.name);
      }
      mountStreams(el);
    } else {
      slot.replaceChildren();
      slot.setAttribute("data-stream", "");
    }
  }
  const bar = el.querySelector(".stage-switch");
  if (bar) {
    bar.hidden = !expanded || options.length < 2;
    const sig = options.map((x) => x.fam).join("|") + "#" + (staged || "");
    if (bar.getAttribute("data-sig") !== sig) {
      const focus = document.activeElement && bar.contains && bar.contains(document.activeElement) ? document.activeElement.getAttribute("data-stage-pick") : "";
      bar.setAttribute("data-sig", sig);
      bar.innerHTML = switcher(options, staged);
      if (focus) {
        const again = bar.querySelector('[data-stage-pick="' + CSS.escape(focus) + '"]');
        if (again) again.focus({ preventScroll: true });
      }
    }
  }
  dotsOf(el, options, deps);
  const nextH = typeof el.getBoundingClientRect === "function" ? el.getBoundingClientRect().height : 0;
  if (prevH > 0 && nextH !== prevH && window.scrollY > 0 && typeof window.scrollBy === "function") {
    window.scrollBy(0, nextH - prevH);
  }
}

// One listener on the stage, bound once; a pick saves the choice and asks
// for a redraw so the page below puts that family first.
export function wire(el, deps) {
  if (deps) last.deps = deps;
  if (wired) return;
  wired = true;
  el.addEventListener("click", (e) => {
    const retryBtn = e.target.closest("[data-stage-retry]");
    if (retryBtn) {
      const o = last.staged ? last.options.find((x) => x.fam === last.staged) : null;
      const fn = (last.deps && last.deps.retry) || streams.retry;
      if (o) fn(o.name);
      return;
    }
    const b = e.target.closest("[data-stage-pick]");
    if (!b) return;
    const fam = b.getAttribute("data-stage-pick");
    saveStage(fam);
    // The redraw is synchronous, so the page is already reordered here.
    window.dispatchEvent(new Event("overseer:redraw"));
    const main = document.getElementById("main") || document.querySelector("main");
    if (!main) return;
    const to = pickScroll(window.scrollY, main.getBoundingClientRect().top + window.scrollY, el.getBoundingClientRect().height);
    if (to !== null) window.scrollTo(0, to);
  });
  window.addEventListener("overseer:streamstate", () => {
    if (!document.hidden && !el.hidden) sync(last.options, last.staged, isNarrow(), last.deps);
  });
  // The picture states change without the page's markup changing, so the
  // dots follow on the second.
  window.setInterval(() => {
    if (!document.hidden && !el.hidden) dotsOf(el, last.options, last.deps);
  }, 1000);
}
