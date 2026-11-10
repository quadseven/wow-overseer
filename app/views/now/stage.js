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
// What sync() last showed: the dots' ticker reads it between redraws.
let last = { options: [], staged: "" };

function stageEl() { return document.getElementById("stage"); }

function dotsOf(el, options) {
  el.querySelectorAll("[data-stage-pick]").forEach((b) => {
    const o = options.find((x) => x.fam === b.getAttribute("data-stage-pick"));
    const live = dotOn(o, last.staged, o ? streams.stateOf(o.name) : "off");
    if (b.getAttribute("data-live") !== (live ? "1" : "0")) b.setAttribute("data-live", live ? "1" : "0");
  });
}

function switcher(options, staged) {
  return options.map((o) => html`<button type="button" class="stage-pick" data-stage-pick="${o.fam}" data-live="0" aria-pressed="${String(o.fam === staged)}" aria-label="${"Watch " + o.fam + "'s family"}"><span class="stage-dot" aria-hidden="true"></span><span class="stage-pick-l">${o.fam}</span></button>`).map(String).join("");
}

// Show the stage for `staged` (a family key) or hide it. `options` are the
// families that have a stream; only more than one gets a switcher.
export function sync(options, staged, narrow) {
  const el = stageEl();
  if (!el) return;
  last = { options, staged };
  const on = narrow && !!staged;
  el.hidden = !on;
  document.documentElement.toggleAttribute("data-stage", on);
  if (!on) return;
  wire(el);
  const slot = el.querySelector(".stage-slot");
  const o = options.find((x) => x.fam === staged);
  if (slot.getAttribute("data-stream") !== o.name) {
    slot.replaceChildren();
    slot.setAttribute("data-stream", o.name);
  }
  streams.mount(el);
  const bar = el.querySelector(".stage-switch");
  bar.hidden = options.length < 2;
  const sig = options.map((x) => x.fam).join("|") + "#" + staged;
  if (bar.getAttribute("data-sig") !== sig) {
    const focus = document.activeElement && bar.contains(document.activeElement) ? document.activeElement.getAttribute("data-stage-pick") : "";
    bar.setAttribute("data-sig", sig);
    bar.innerHTML = switcher(options, staged);
    if (focus) {
      const again = bar.querySelector('[data-stage-pick="' + CSS.escape(focus) + '"]');
      if (again) again.focus({ preventScroll: true });
    }
  }
  dotsOf(el, options);
}

// One listener on the stage, bound once; a pick saves the choice and asks
// for a redraw so the page below puts that family first.
function wire(el) {
  if (wired) return;
  wired = true;
  el.addEventListener("click", (e) => {
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
  // The picture states change without the page's markup changing, so the
  // dots follow on the second.
  window.setInterval(() => {
    if (!document.hidden && !el.hidden) dotsOf(el, last.options);
  }, 1000);
}
