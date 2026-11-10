// Phone gestures on the main column. A swipe left or right of more than 70px
// (and under 40px up or down) moves to the next or previous tab of the tab
// row on screen. Pulling down more than 90px from the top refreshes.

import { swipeSiblings } from "./router.js";
import { endOnce } from "./redraw.js";

export function install(main, opts) {
  let x0 = 0, y0 = 0, top = false, active = false;
  main.addEventListener("touchstart", (e) => {
    if (e.touches.length !== 1) { active = false; return; }
    // Horizontal scrollers (tab rows, wide tables, maps) keep their own drag.
    if (e.target.closest(".tabs, .hscroll, [data-no-swipe], input, textarea, select")) { active = false; return; }
    active = true;
    x0 = e.touches[0].clientX; y0 = e.touches[0].clientY;
    top = window.scrollY <= 0;
    endOnce(e.target, onEnd);
  }, { passive: true });
  main.addEventListener("touchmove", (e) => {
    if (!active || !top) return;
    const dy = e.touches[0].clientY - y0;
    opts.onPull(dy > 90);
  }, { passive: true });
  // The end is heard on the touched element itself: a pull redraws <main>
  // and removes that element, and an event on a removed element does not
  // bubble up to <main>.
  function onEnd(e) {
    if (!active) return;
    active = false;
    if (e.type === "touchcancel") { opts.onPull(false); return; }
    const t = e.changedTouches[0];
    const dx = t.clientX - x0, dy = t.clientY - y0;
    if (top && dy > 90 && Math.abs(dx) < 60) { opts.onRefresh(); return; }
    opts.onPull(false);
    if (Math.abs(dx) > 70 && Math.abs(dy) < 40) {
      const row = main.querySelector(".tabs");
      if (!row) return;
      const hrefs = Array.from(row.querySelectorAll("a")).map((a) => a.getAttribute("href"));
      const cur = row.querySelector('a[aria-current="page"]');
      const { prev, next } = swipeSiblings(hrefs, cur ? cur.getAttribute("href") : "");
      const to = dx < 0 ? next : prev;
      if (to) location.hash = to;
    }
  }
}
