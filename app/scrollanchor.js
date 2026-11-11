// Keeping the reader's place across a redraw, by content rather than pixels.
//
// A view redraws by replacing the whole page body. The old restore scrolled
// back to the same pixel count, but a redraw can change the height of
// anything above the reader (a card whose text wraps differently, a section
// that has just arrived), and then the same count is a different place: the
// page visibly jumps and the reader loses their line. Instead, before the
// swap we note the element sitting at the reader's line as a path of child
// indices from the page root plus the line's offset inside that element;
// after the swap we find that element again and shift the scroll by however
// far it moved. The structure of a view is stable across its own redraws
// (same sections, same order), so the path resolves; when it does not, the
// caller keeps the old pixel restore as the fallback.
//
// Pure functions over element-shaped values ({children, getBoundingClientRect}),
// so node can test them without a DOM.

// Descend from `root` into the deepest element whose box contains `lineY`
// (a viewport-relative y). Returns {path, offset} or null when nothing
// under root contains the line.
export function captureAnchor(root, lineY) {
  if (!root || !root.children) return null;
  let node = root;
  const path = [];
  for (;;) {
    const kids = node.children || [];
    let next = -1;
    for (let i = 0; i < kids.length; i++) {
      const r = kids[i].getBoundingClientRect();
      if (r.top <= lineY && lineY < r.bottom) { next = i; break; }
    }
    if (next < 0) break;
    path.push(next);
    node = kids[next];
  }
  if (!path.length) return null;
  const r = node.getBoundingClientRect();
  return { path, offset: lineY - r.top };
}

// The element an anchor names under `root`, or null when the path no longer
// resolves (the redraw changed the structure above it).
export function resolveAnchor(root, anchor) {
  if (!root || !anchor || !anchor.path) return null;
  let node = root;
  for (const i of anchor.path) {
    const kids = node.children || [];
    if (i < 0 || i >= kids.length) return null;
    node = kids[i];
  }
  return node;
}

// How far to shift the scroll so the reader's line sits at the same offset
// inside the anchored element as it did before the redraw. Positive means
// the element moved down and the scroll must follow it.
export function scrollShift(el, anchor, lineY) {
  if (!el || !anchor) return 0;
  const r = el.getBoundingClientRect();
  return (r.top + anchor.offset) - lineY;
}

// Where to write the scroll after a redraw, or null when nothing needs
// writing. `y` is the scroll before the swap, `shift` what scrollShift said
// (0 with no anchor), `current` the scroll now. A write that would move the
// page less than a pixel is not made: it can only interrupt a fling.
export function restoreTarget(y, shift, current) {
  const target = Math.max(0, y + shift);
  return Math.abs(target - current) < 1 ? null : target;
}
