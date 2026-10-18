// A view's tab strip (`nav.tabs`) scrolls sideways on a phone when its tabs
// are wider than the screen: a profile's seven tabs, or Economy's five. Two
// things keep the lit tab where it can be seen:
//
// - A new page brings its current tab into view. Without it, the strip opens
//   scrolled to its start and a tab near the end (Guild bank, Activity) is lit
//   off the right edge, so nothing on the screen says which tab is open.
// - A redraw keeps where the strip was scrolled. A view redraws every time a
//   read answers, which builds a new strip at its start; a reader who swiped
//   it along would be snapped back every few seconds.
//
// The scroll is set, not animated, so reduced motion has nothing to ask.

// The scroll that shows a tab from `start` to `end` (px along the strip's
// content) whole inside a strip `width` px wide now scrolled to `left`, with
// `pad` px clear on the side it comes in from. A tab already in view keeps the
// strip where it is.
export function revealLeft(left, width, start, end, pad) {
  if (start - pad < left) return Math.max(0, start - pad);
  if (end + pad > left + width) return Math.max(0, Math.min(start - pad, end + pad - width));
  return left;
}

// Where each strip under `root` is scrolled, by its label, before a redraw.
export function stripPlaces(root) {
  const kept = new Map();
  root.querySelectorAll("nav.tabs").forEach((s) => kept.set(s.getAttribute("aria-label") || "", s.scrollLeft));
  return kept;
}

// Scroll strip `s` so its current tab is in view; the scroll it ends at.
function reveal(s) {
  const cur = s.querySelector('[aria-current="page"]');
  if (!cur || s.scrollWidth <= s.clientWidth) return s.scrollLeft;
  const box = s.getBoundingClientRect();
  const at = cur.getBoundingClientRect();
  const start = at.left - box.left + s.scrollLeft;
  s.scrollLeft = revealLeft(s.scrollLeft, s.clientWidth, start, start + at.width, 16);
  return s.scrollLeft;
}

// After a draw: a strip that was on screen before goes back to where it was;
// any other brings its current tab into view. Labels drawn before the web
// font arrives are narrower than they end up, so a strip placed then is
// placed again once the font is in, unless the reader has moved it since.
export function placeStrips(root, kept) {
  root.querySelectorAll("nav.tabs").forEach((s) => {
    const key = s.getAttribute("aria-label") || "";
    if (kept && kept.has(key)) { s.scrollLeft = kept.get(key); return; }
    const placed = reveal(s);
    const fonts = typeof document !== "undefined" ? document.fonts : null;
    if (!fonts || fonts.status === "loaded") return;
    fonts.ready.then(() => {
      const now = [...root.querySelectorAll("nav.tabs")].find((n) => (n.getAttribute("aria-label") || "") === key);
      if (now && now.scrollLeft === placed) reveal(now);
    });
  });
}
