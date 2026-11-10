// The one width that splits a phone layout from a wide one. The stylesheets
// use the same number, so a change here is a change there.

export const NARROW = "(max-width: 759.98px)";

// Call `fn` each time the screen crosses the breakpoint (a turn, a resize).
// An older browser has only `addListener`, and one with neither goes without
// the redraw: this runs while the app starts, so it must never throw.
export function onCross(fn) {
  const mq = window.matchMedia ? window.matchMedia(NARROW) : null;
  if (!mq) return;
  const heard = () => fn();
  if (mq.addEventListener) mq.addEventListener("change", heard);
  else if (mq.addListener) mq.addListener(heard);
}
