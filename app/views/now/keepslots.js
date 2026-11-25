// The wall's pictures stay in the page across a redraw.
//
// A redraw replaces the page body, and a <video> taken out of the document
// and put back is interrupted. On a phone the one picture sits on the stage,
// outside the redrawn region (stage.js), so a redraw never touches it. The
// wall's slots are part of the page's own layout, so here the swap works
// around them instead: a slot the new body still has stays where it is, with
// the elements that hold it, and everything else is replaced by the new
// body's nodes. The pictures are still streams.js's, moved by mount() as
// they are for the stage; this only keeps their slots from leaving the page.
//
// Works on the nodes it is handed, so node tests it with a small fake DOM.

// The wall's slots; the Watcher's card plays its own picture (_spectate.js).
export const SLOT = "[data-stream]:not([data-spectate-slot])";

function slotsOf(root) {
  const out = new Map();
  root.querySelectorAll(SLOT).forEach((slot) => {
    const name = slot.getAttribute("data-stream");
    if (name && !out.has(name)) out.set(name, slot);
  });
  return out;
}

// The child of `parent` that is `node` or holds it; null when it is not below.
function childHolding(parent, node) {
  let n = node;
  while (n && n.parentNode !== parent) n = n.parentNode;
  return n || null;
}

function copyAttrs(to, from) {
  to.getAttributeNames().forEach((k) => { if (!from.hasAttribute(k)) to.removeAttribute(k); });
  from.getAttributeNames().forEach((k) => {
    const v = from.getAttribute(k);
    if (to.getAttribute(k) !== v) to.setAttribute(k, v);
  });
}

// Make `oldParent`'s children those of `newParent`, keeping in place each old
// child that holds a paired slot. `pairs` are [{old, neu}]: the slot on
// screen and the same stream's slot in the new body. A pair whose two sides
// do not sit alike (another element, another depth, another order) is not
// kept: its old side goes and the new one comes in, as a plain swap would do.
function merge(oldParent, newParent, pairs) {
  const olds = Array.from(oldParent.childNodes);
  const news = Array.from(newParent.childNodes);
  const groups = [];
  pairs.forEach((p) => {
    const o = childHolding(oldParent, p.old);
    const n = childHolding(newParent, p.neu);
    if (!o || !n || o.nodeName !== n.nodeName || (o === p.old) !== (n === p.neu)) return;
    const g = groups.find((x) => x.o === o || x.n === n);
    if (!g) groups.push({ o, n, pairs: [p] });
    else if (g.o === o && g.n === n) g.pairs.push(p);
  });
  groups.sort((a, b) => news.indexOf(a.n) - news.indexOf(b.n));
  let at = -1;
  const stay = groups.filter((g) => {
    const i = olds.indexOf(g.o);
    if (i <= at) return false;
    at = i;
    return true;
  });
  const staying = new Set(stay.map((g) => g.o));
  olds.forEach((c) => { if (!staying.has(c)) oldParent.removeChild(c); });
  let next = 0;
  news.forEach((c) => {
    const g = stay[next];
    if (g && g.n === c) {
      next += 1;
      copyAttrs(g.o, g.n);
      // The slot itself keeps what it holds: the living picture.
      if (g.pairs[0].old !== g.o) merge(g.o, g.n, g.pairs);
    } else {
      oldParent.insertBefore(c, g ? g.o : null);
    }
  });
}

function mapBoxesOf(root) {
  const out = new Map();
  root.querySelectorAll("[data-map-box]").forEach((box) => {
    const fam = box.getAttribute("data-map-box");
    if (fam && !out.has(fam)) out.set(fam, box);
  });
  return out;
}

// Draw `body` into `main` without taking a kept slot out of the document.
// False when there is nothing to keep (no slot on screen, or none of them in
// the new body): the caller swaps the body the plain way.
export function swapKeeping(main, body, doc = document) {
  const olds = slotsOf(main);
  if (!olds.size) return false;
  const next = doc.createElement("template");
  next.innerHTML = body;
  const news = slotsOf(next.content);
  const pairs = [];
  olds.forEach((old, name) => {
    const neu = news.get(name);
    if (neu) pairs.push({ old, neu });
  });
  if (!pairs.length) return false;
  const oldMaps = mapBoxesOf(main);
  if (oldMaps.size) {
    const newMaps = mapBoxesOf(next.content);
    oldMaps.forEach((old, fam) => {
      const neu = newMaps.get(fam);
      if (neu) pairs.push({ old, neu });
    });
  }
  merge(main, next.content, pairs);
  return true;
}
