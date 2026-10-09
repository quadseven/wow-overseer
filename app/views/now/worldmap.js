// The world map, drawn as SVG from shapes.json (zone paths, coast, label
// anchors and `room`), with the characters placed from /api/map.
//
// Positions: the map server converts a character's world coordinates into
// fractions of its continent's bounds from zones.json (transform.py, the same
// conversion the classic page draws with), and sends them as `u` and `v`.
// shapes.json is drawn in a 1000-wide frame at the continent's true aspect,
// so a dot sits at (u * 1000, v * 1000 * aspect), exactly where the classic
// page's canvas puts it. A character is never placed at a zone's centre,
// except as a fallback that is labeled as one (see fallbackDots).

import { esc } from "../../ui.js";

export const CONTINENT = { kal: "1", ek: "0" };
const W = 1000;
const CITY_A = { "Stormwind City": 1, Ironforge: 1, Darnassus: 1 };
const CITY_H = { Orgrimmar: 1, Undercity: 1, "Thunder Bluff": 1 };
const CONTESTED = {
  "Stranglethorn Vale": 1, Tanaris: 1, "Thousand Needles": 1, "Hillsbrad Foothills": 1,
  "Arathi Highlands": 1, Desolace: 1, Ashenvale: 1, "Stonetalon Mountains": 1,
  "Dustwallow Marsh": 1, Feralas: 1, Badlands: 1, "Swamp Of Sorrows": 1,
  "Alterac Mountains": 1, Azshara: 1,
};
export const GHOST = "#9aa4b8";
export const MATE = "#d9c79c";

const views = new Map(); // map key -> viewBox, kept across redraws

function mix(hex, toward, t) {
  const a = parseInt(hex.slice(1), 16), b = parseInt(toward.slice(1), 16);
  const c = [16, 8, 0].map((sh) => Math.round(((a >> sh) & 255) * (1 - t) + ((b >> sh) & 255) * t));
  return "#" + c.map((v) => v.toString(16).padStart(2, "0")).join("");
}

function n(v) { return Number(v) || 0; }
function f1(v) { return v.toFixed(1); }

// The zone a /api/map zone name (compact, "BurningSteppes") is drawn as.
export function zoneIndex(shape) {
  const by = new Map();
  (shape ? shape.zones : []).forEach((z) => {
    by.set(z.name, z);
    by.set(String(z.label).replace(/[^a-z]/gi, "").toLowerCase(), z);
  });
  return (name) => by.get(name) || by.get(String(name || "").replace(/[^a-z]/gi, "").toLowerCase()) || null;
}

export function zoneLabel(shape, name) {
  const z = zoneIndex(shape)(name);
  return z ? z.label : name;
}

// /api/map dot -> SVG point on this continent.
export function place(shape, dot) {
  return { x: n(dot.u) * W, y: n(dot.v) * W * n(shape.aspect) };
}

// A viewBox around `points`, padded, inside the continent.
export function around(shape, points, compact) {
  const H = W * n(shape.aspect);
  if (!points.length) return null;
  const xs = points.map((p) => p.x), ys = points.map((p) => p.y);
  const cx = (Math.min(...xs) + Math.max(...xs)) / 2, cy = (Math.min(...ys) + Math.max(...ys)) / 2;
  const w = Math.max(compact ? 420 : 600, Math.max(...xs) - Math.min(...xs) + 160);
  const h = w * (compact ? 0.7 : 1.1);
  return clamp([cx - w / 2, cy - h / 2, w, h], H);
}

function clamp(vb, H) {
  let [x, y, w, h] = vb;
  w = Math.min(W, w); h = Math.min(H, h);
  x = Math.min(Math.max(0, x), W - w);
  y = Math.min(Math.max(0, y), H - h);
  return [x, y, w, h];
}

function zoneRows(C, ppu, px) {
  return C.zones.map((z) => {
    const city = String(z.city) === "True" || z.city === true;
    const room = n(z.room) || 20;
    const tint = CITY_A[z.label] ? "#b8b49a" : CITY_H[z.label] ? "#c9a488" : mix(z.fill || "#c8b487", "#c9b184", 0.55);
    const fs = px(city ? 10.5 : Math.max(10, Math.min(13, room * ppu * 0.32)));
    const show = room * ppu >= (city ? 16 : 12);
    return { z, city, room, tint, fs, show, cx: n(z.cx), cy: n(z.cy) };
  });
}

function box(cx, cy, fs, text, mid) {
  const w = fs * 0.56 * text.length, h = fs * 1.05;
  const x0 = mid ? cx - w / 2 : cx;
  return [x0, cy - h * 0.8, x0 + w, cy + h * 0.25];
}

function overlaps(placed, b) {
  return placed.some((p) => b[0] < p[2] && b[2] > p[0] && b[1] < p[3] && b[3] > p[1]);
}

// Greedy label placement: member labels first, then cities, then by room.
function placeLabels(zones, dots) {
  const placed = [];
  dots.filter((d) => d.labeled).forEach((d) => placed.push(box(d.lx, d.ly, d.fs, d.label, false)));
  dots.forEach((d) => placed.push([d.x - d.r, d.y - d.r, d.x + d.r, d.y + d.r]));
  const order = zones.filter((z) => z.show).sort((a, b) => (Number(b.city) - Number(a.city)) || (b.room - a.room));
  const shown = new Set();
  order.forEach((z) => {
    const b = box(z.cx, z.cy, z.fs, z.z.label, true);
    if (!overlaps(placed, b)) { placed.push(b); shown.add(z.z.label); }
  });
  return shown;
}

function dotRows(dots, ppu, px) {
  return dots.map((d) => {
    const r = px(d.family ? 5.5 : 3.2);
    const label = d.name + (d.ghost ? " (ghost)" : "") + (d.fallback ? " (zone centre, position not read)" : "");
    return Object.assign({}, d, {
      r, label, fs: px(12), lx: d.x - px(10), ly: d.y - r - px(5),
      labeled: d.head || d.fallback || (d.family && ppu > 0.9),
    });
  });
}

function dotSvg(d, px, linked) {
  const c = esc(d.color);
  const ring = d.fallback
    ? `<circle cx="${f1(d.x)}" cy="${f1(d.y)}" r="${f1(d.r)}" fill="none" stroke="${c}" stroke-width="${f1(px(2))}" stroke-dasharray="${f1(px(2))} ${f1(px(2))}"></circle>`
    : `<circle cx="${f1(d.x)}" cy="${f1(d.y)}" r="${f1(d.r * 2.2)}" fill="${c}" fill-opacity=".25"></circle><circle cx="${f1(d.x)}" cy="${f1(d.y)}" r="${f1(d.r)}" fill="${c}" stroke="#1a1208" stroke-width="${f1(px(1.5))}"></circle>`;
  const hit = `<circle cx="${f1(d.x)}" cy="${f1(d.y)}" r="${f1(px(16))}" fill="transparent"></circle>`;
  if (!linked) return `<g class="wm-dot">${ring}</g>`;
  return `<a class="wm-dot" href="#/m/${encodeURIComponent(d.name)}" aria-label="${esc(d.label)}">${hit}${ring}</a>`;
}

function labelSvg(zones, shown, dots, px) {
  const zl = zones.filter((z) => shown.has(z.z.label)).map((z) =>
    `<text x="${f1(z.cx)}" y="${f1(z.cy)}" text-anchor="middle" class="wm-zl${z.city ? " city" : ""}" font-size="${f1(z.fs)}" stroke-width="${f1(px(2.4))}">${esc(z.z.label)}</text>`);
  const dl = dots.filter((d) => d.labeled).map((d) =>
    `<text x="${f1(d.lx)}" y="${f1(d.ly)}" class="wm-dl" font-size="${f1(d.fs)}" stroke-width="${f1(px(3))}">${esc(d.label)}</text>`);
  return `<g class="wm-labels" aria-hidden="true">${zl.join("")}${dl.join("")}</g>`;
}

function svgMarkup(o, vb, ppu) {
  const C = o.shape, id = o.key.replace(/[^a-z0-9]/gi, "");
  const px = (v) => v / ppu;
  const zones = zoneRows(C, ppu, px);
  const dots = dotRows(o.dots, ppu, px);
  const shown = placeLabels(zones, dots);
  const coast = (C.coast || []).map((d) => `<path d="${esc(d)}" fill="none" stroke="#9fd0e0" stroke-opacity=".22" stroke-width="18" filter="url(#wmg${id})"></path>`).join("")
    + (C.coast || []).map((d) => `<path d="${esc(d)}" fill="#b49c6c" stroke="#3b2c17" stroke-width="2.4"></path>`).join("");
  const zonePaths = zones.map((z) => `<path class="wm-zone" data-zone="${esc(z.z.name)}" d="${esc(z.z.d)}" fill="${z.tint}"${CONTESTED[z.z.label] ? ' stroke-dasharray="5 4"' : ""}></path>`).join("");
  return `<svg class="wm-svg" viewBox="${vb.map(f1).join(" ")}" preserveAspectRatio="xMidYMid meet" role="img" aria-label="${esc(C.name + " map with " + o.dots.length + " characters marked")}">`
    + `<defs><filter id="wmt${id}" x="-5%" y="-5%" width="110%" height="110%"><feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" seed="7" result="n"></feTurbulence><feColorMatrix in="n" type="saturate" values="0" result="g"></feColorMatrix><feComponentTransfer in="g" result="t"><feFuncA type="linear" slope="0.18"></feFuncA></feComponentTransfer><feComposite in="t" in2="SourceGraphic" operator="in" result="tex"></feComposite><feMerge><feMergeNode in="SourceGraphic"></feMergeNode><feMergeNode in="tex"></feMergeNode></feMerge></filter><filter id="wmg${id}"><feGaussianBlur stdDeviation="6"></feGaussianBlur></filter></defs>`
    + coast + `<g filter="url(#wmt${id})">${zonePaths}</g>` + labelSvg(zones, shown, dots, px)
    + dots.map((d) => dotSvg(d, px, !o.compact)).join("") + `</svg>`;
}

function chrome(o) {
  const head = `<div class="wm-title"><span class="wm-name">${esc(o.shape.name)}</span><span class="wm-hover" data-hover>${esc(o.summary || "")}</span></div>`;
  if (o.compact) return head;
  return head + `<div class="wm-zoom"><button type="button" class="wm-btn" data-zoom="in" aria-label="Zoom in"><i class="ph ph-plus" aria-hidden="true"></i></button><button type="button" class="wm-btn" data-zoom="out" aria-label="Zoom out"><i class="ph ph-minus" aria-hidden="true"></i></button><button type="button" class="wm-btn" data-zoom="reset" aria-label="Reset view"><i class="ph ph-arrows-in" aria-hidden="true"></i></button></div>`
    + `<div class="wm-legend" aria-hidden="true"><span><span class="wm-key fam"></span>family, by class colour</span><span><span class="wm-key mate"></span>guildmate</span><span><span class="wm-key fall"></span>zone centre, position not read</span><span>dashed border: contested</span></div>`;
}

// Draw (or redraw) the map into `boxEl`. `o`: {key, shape, dots, compact,
// focus: viewBox | null, summary, whoIn(zoneName) -> text}.
export function draw(boxEl, o) {
  const H = W * n(o.shape.aspect);
  const full = [0, 0, W, H];
  let vb = views.get(o.key) || o.focus || full;
  const size = () => ({ w: boxEl.clientWidth || 600, h: boxEl.clientHeight || 500 });
  const ppuOf = (v) => Math.min(size().w / v[2], size().h / v[3]);
  const paint = () => {
    boxEl.innerHTML = svgMarkup(o, vb, ppuOf(vb)) + chrome(o);
    bindHover(boxEl, o);
  };
  paint();
  if (o.compact) return;
  const set = (v, repaint) => {
    vb = clamp(v, H);
    views.set(o.key, vb);
    if (repaint) paint();
    else boxEl.querySelector("svg").setAttribute("viewBox", vb.map(f1).join(" "));
  };
  const zoomBy = (k) => {
    const [x, y, w, h] = vb;
    const nw = Math.min(W, Math.max(180, w * k)), nh = nw * (h / w);
    set([x + (w - nw) / 2, y + (h - nh) / 2, nw, nh], true);
  };
  boxEl.onclick = (e) => {
    const b = e.target.closest("[data-zoom]");
    if (!b) return;
    const z = b.getAttribute("data-zoom");
    if (z === "in") zoomBy(0.7); else if (z === "out") zoomBy(1.4); else set(full, true);
  };
  boxEl.onwheel = (e) => { e.preventDefault(); zoomBy(e.deltaY > 0 ? 1.15 : 0.87); };
  bindDrag(boxEl, () => vb, (v) => set(v, false));
}

function bindHover(boxEl, o) {
  const line = boxEl.querySelector("[data-hover]");
  const svg = boxEl.querySelector("svg");
  if (!line || !svg) return;
  svg.addEventListener("pointerover", (e) => {
    const p = e.target.closest && e.target.closest("[data-zone]");
    if (!p) return;
    const name = p.getAttribute("data-zone");
    line.textContent = o.whoIn ? o.whoIn(name) : name;
  });
  svg.addEventListener("pointerleave", () => { line.textContent = o.summary || ""; });
}

// Drag pans only after 5px of movement, so a tap on a dot still opens it.
function bindDrag(boxEl, getVb, setVb) {
  let drag = null;
  let dragged = false;
  boxEl.onpointerdown = (e) => {
    if (e.target.closest("[data-zoom]")) return;
    const svg = boxEl.querySelector("svg");
    dragged = false;
    drag = { x: e.clientX, y: e.clientY, vb: getVb().slice(), w: svg.getBoundingClientRect().width, moved: false, id: e.pointerId, svg };
  };
  boxEl.onpointermove = (e) => {
    if (!drag) return;
    if (!drag.moved) {
      if (Math.hypot(e.clientX - drag.x, e.clientY - drag.y) < 5) return;
      drag.moved = true; dragged = true;
      try { boxEl.setPointerCapture(drag.id); } catch (err) { /* released */ }
      boxEl.classList.add("dragging");
    }
    const k = drag.vb[2] / drag.w;
    setVb([drag.vb[0] - (e.clientX - drag.x) * k, drag.vb[1] - (e.clientY - drag.y) * k, drag.vb[2], drag.vb[3]]);
  };
  const end = () => { drag = null; boxEl.classList.remove("dragging"); };
  boxEl.onpointerup = end;
  boxEl.onpointercancel = end;
  boxEl.addEventListener("click", (e) => {
    if (dragged) { e.preventDefault(); e.stopPropagation(); dragged = false; }
  }, true);
}

// The dots for one continent: every member named in `people` (name ->
// {family, color, ghost, head}) that /api/map places there.
export function dotsFor(shape, cont, mapDots, people) {
  return (mapDots || []).filter((d) => d.continent === cont && people.has(d.name)).map((d) => {
    const p = people.get(d.name);
    const xy = place(shape, d);
    return { name: d.name, x: xy.x, y: xy.y, zone: d.zone, family: p.family, head: p.head, ghost: p.ghost, color: p.ghost ? GHOST : p.family ? p.color : MATE };
  });
}

// Family members /api/map does not place, but whose zone /api/wall names: a
// hollow ring at that zone's centre, labeled as exactly that.
export function fallbackDots(shape, placedNames, members) {
  const find = zoneIndex(shape);
  return members.filter((m) => !placedNames.has(m.name) && m.present && m.zone).map((m) => {
    const z = find(m.zone);
    if (!z) return null;
    return { name: m.name, x: n(z.cx), y: n(z.cy), zone: z.name, family: true, head: false, ghost: false, fallback: true, color: m.class_colour || MATE };
  }).filter(Boolean);
}
