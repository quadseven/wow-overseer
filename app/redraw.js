// A redraw that does not fight the reader.
//
// A view redraws by replacing the page body. Two rules keep that from
// disturbing a scroll:
//   - makeHold: while a finger is down, or the page scrolled a moment ago,
//     a redraw waits. Only the latest request is kept, and it is applied
//     once the scroll has settled (the browser's `scrollend` where there is
//     one, a timer otherwise).
//   - makeGate: a body identical to the one on screen is not drawn at all.
//
// Pure of the DOM: the clock and the timers are handed in, so node can test
// them with a fake clock.

export const QUIET_MS = 150;

export function makeHold({ now, setTimer, clearTimer, apply, quiet = QUIET_MS }) {
  let touching = false;
  let lastScroll = -Infinity;
  let pending = false;
  let timer = null;

  const busy = () => touching || now() - lastScroll < quiet;

  function cancel() {
    if (timer !== null) { clearTimer(timer); timer = null; }
  }

  function flush() {
    cancel();
    if (!pending) return;
    if (busy()) { arm(); return; }
    pending = false;
    apply();
  }

  function arm() {
    cancel();
    if (!pending || touching) return; // touchEnd re-arms
    const wait = Math.max(1, quiet - (now() - lastScroll));
    timer = setTimer(() => { timer = null; flush(); }, wait);
  }

  return {
    request() {
      pending = true;
      if (busy()) arm();
      else flush();
    },
    touchStart() { touching = true; cancel(); },
    touchEnd() { touching = false; lastScroll = Math.max(lastScroll, now()); arm(); },
    scrolled() { lastScroll = now(); if (pending) arm(); },
    scrollEnd() { lastScroll = -Infinity; flush(); },
    get pending() { return pending; },
  };
}

// Run `fn` once, at the first touchend or touchcancel heard on `target`.
// A touch is always dispatched at the element it began on, even after a
// redraw removed that element from the page; an event on a removed element
// does not bubble, so a listener on <main> or window never hears it.
export function endOnce(target, fn) {
  let done = false;
  const end = (e) => {
    if (done) return;
    done = true;
    target.removeEventListener("touchend", end);
    target.removeEventListener("touchcancel", end);
    fn(e);
  };
  target.addEventListener("touchend", end, { passive: true });
  target.addEventListener("touchcancel", end, { passive: true });
}

// True when `key` is not what was drawn last for this page.
export function makeGate() {
  let page = null;
  let last = null;
  return {
    changed(pageKey, key) {
      if (page === pageKey && last === key) return false;
      page = pageKey; last = key;
      return true;
    },
    reset() { page = null; last = null; },
  };
}
