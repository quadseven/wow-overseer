// The one width that splits a phone layout from a wide one. The stylesheets
// use the same number, so a change here is a change there.

export const NARROW = "(max-width: 759.98px)";

// Call `fn` each time the screen crosses the breakpoint (a turn, a resize).
export function onCross(fn) {
  window.matchMedia(NARROW).addEventListener("change", () => fn());
}
