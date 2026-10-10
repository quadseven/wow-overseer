// Shared primitives. Every view builds markup with `html`, which escapes
// every interpolated value unless it is itself markup built here, so text
// from the realm (names, chat, item names) can never become markup.

export class Safe {
  constructor(s) { this.s = s; }
  toString() { return this.s; }
}

const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

export function esc(v) { return String(v).replace(/[&<>"']/g, (c) => ESC[c]); }

function part(v) {
  if (v === null || v === undefined || v === false) return "";
  if (v instanceof Safe) return v.s;
  if (Array.isArray(v)) return v.map(part).join("");
  return esc(v);
}

export function html(strings, ...vals) {
  let out = strings[0];
  for (let i = 0; i < vals.length; i++) out += part(vals[i]) + strings[i + 1];
  return new Safe(out);
}

export function raw(s) { return new Safe(String(s)); }

// ---- words and numbers -------------------------------------------------

export function ago(seconds) {
  if (seconds === null || seconds === undefined || !isFinite(seconds)) return "not measured";
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return s + "s ago";
  if (s < 3600) return Math.floor(s / 60) + "m ago";
  if (s < 86400) return Math.floor(s / 3600) + "h ago";
  return Math.floor(s / 86400) + "d ago";
}

export function duration(seconds) {
  if (seconds === null || seconds === undefined || !isFinite(seconds)) return null;
  const m = Math.max(0, Math.round(seconds / 60));
  if (m < 60) return m + "m";
  const h = Math.floor(m / 60);
  if (h < 48) return h + "h " + (m % 60) + "m";
  return Math.floor(h / 24) + "d " + (h % 24) + "h";
}

export function gold(copper) {
  if (copper === null || copper === undefined) return null;
  const g = Math.floor(copper / 10000), s = Math.floor(copper / 100) % 100, c = copper % 100;
  if (g) return g + "g " + String(s).padStart(2, "0") + "s";
  if (s) return s + "s " + String(c).padStart(2, "0") + "c";
  return c + "c";
}

export function plural(n, one, many) { return n + " " + (n === 1 ? one : (many || one + "s")); }

// The one way a missing number is said. Never 0, never a dash.
export function notMeasured(text) { return html`<span class="unmeasured">${text || "not measured"}</span>`; }

export function value(v, fmt) {
  if (v === null || v === undefined || (typeof v === "number" && !isFinite(v))) return notMeasured();
  return fmt ? fmt(v) : v;
}

// ---- status label --------------------------------------------------------

export const STATUS = {
  stuck: ["Stuck", "ph-fill ph-hand-palm", "var(--warn)"],
  stalled: ["Stalled", "ph-fill ph-pause-circle", "var(--warn)"],
  ghost: ["Ghost", "ph-fill ph-ghost", "var(--bad)"],
  live: ["Live", "ph-fill ph-broadcast", "var(--bad)"],
  online: ["Online", "ph-fill ph-circle", "var(--ok)"],
  offline: ["Offline", "ph ph-circle", "var(--color-neutral-500)"],
  upgrade: ["Upgrade", "ph-fill ph-arrow-circle-up", "var(--warn)"],
  best: ["At best", "ph-fill ph-check-circle", "var(--ok)"],
  near: ["Near best", "ph ph-check-circle", "var(--color-accent-300)"],
  inside: ["Inside", "ph-fill ph-door-open", "var(--color-accent-300)"],
  cleared: ["Cleared", "ph-fill ph-check-circle", "var(--ok)"],
  wiped: ["Wiped", "ph-fill ph-x-circle", "var(--bad)"],
  new: ["New", "ph-fill ph-sparkle", "var(--color-accent-300)"],
};

export function status(kind, label) {
  const s = STATUS[kind] || STATUS.offline;
  return html`<span class="status" style="color:${s[2]}"><i class="${s[1]}" aria-hidden="true"></i>${label || s[0]}</span>`;
}

export function statusColor(kind) { return (STATUS[kind] || STATUS.offline)[2]; }

// ---- members -------------------------------------------------------------

export function classVar(cls) {
  const k = String(cls || "").toLowerCase().replace(/\s+/g, "-");
  return k ? "var(--cls-" + k + ", var(--color-text))" : "var(--color-text)";
}

export function memberHref(name, tab) {
  return "#/m/" + encodeURIComponent(name) + (tab ? "/" + tab : "");
}

// A member's name in its class colour, linking to its profile, with a dot
// for its state when one is given.
export function member(m, opts) {
  const o = opts || {};
  const dot = m.state ? html`<span class="mdot" style="background:${statusColor(m.state)}" aria-hidden="true"></span>` : "";
  const title = m.state ? (STATUS[m.state] || STATUS.offline)[0] : "";
  return html`<a class="member" href="${memberHref(m.name, o.tab)}" style="color:${classVar(m.cls || m.class)}"${title ? raw(' title="' + esc(title) + '"') : ""}>${dot}${m.name}</a>`;
}

export function memberChip(m) {
  return html`<a class="chip" href="${memberHref(m.name)}"><span class="mdot" style="width:7px;height:7px;border-radius:50%;background:${statusColor(m.state || "offline")}" aria-hidden="true"></span><span style="color:${classVar(m.cls || m.class)}">${m.name}</span></a>`;
}

// ---- items ---------------------------------------------------------------

export const ICON_HOST = "https://wow.zamimg.com/images/wow/icons/large/";

export function iconUrl(icon) {
  if (!icon) return "";
  if (/^https:\/\//.test(icon)) return icon;
  return ICON_HOST + String(icon).toLowerCase().replace(/[^a-z0-9_-]/g, "") + ".jpg";
}

// An item: icon with a quality ring and the quality-coloured name. Hover or
// focus shows the tooltip on desktop, a tap opens the sheet on phone
// (tooltip.js listens for [data-item]). `mark` is the slot mark shown when the
// item has no icon.
export function item(it) {
  const q = Number.isFinite(Number(it.quality)) ? Number(it.quality) : 1;
  const entry = Number(it.entry || it.id || 0);
  const pic = it.icon
    ? html`<img src="${iconUrl(it.icon)}" alt="" width="18" height="18" loading="lazy" decoding="async">`
    : html`<span class="noicon" aria-hidden="true">${it.mark || ""}</span>`;
  return html`<button type="button" class="item q${q}" data-item="${entry}"${it.name ? raw(' data-name="' + esc(it.name) + '"') : ""}>${pic}<span class="nm">${it.name || "Item " + entry}</span></button>`;
}

// ---- states --------------------------------------------------------------

const STATE_ICON = {
  empty: "ph ph-circle-dashed",
  stale: "ph ph-clock-countdown",
  error: "ph ph-warning-octagon",
  unmeasured: "ph ph-question",
};

export function state(kind, title, body) {
  const role = kind === "error" ? "alert" : "status";
  return html`<div class="state" data-kind="${kind}" role="${role}"><i class="${STATE_ICON[kind] || STATE_ICON.empty}" aria-hidden="true"></i><div><div class="t">${title}</div>${body ? html`<div class="b">${body}</div>` : ""}</div></div>`;
}

export function skeletons(n) {
  const cards = [];
  for (let i = 0; i < (n || 3); i++) cards.push(html`<div class="skeleton"></div>`);
  return html`<div class="skeletons" role="status" aria-busy="true" aria-label="Loading">${cards}</div>`;
}

// What a view draws for one read before it has data: the skeleton while the
// first answer is on its way, "The world did not answer" with Retry when it
// failed and nothing earlier exists. The read's state is readState's, below.
export function pendingRead(read, rows) {
  const st = readState(read);
  if (st === "ready" || st === "refused") return null;
  if (st === "failed") {
    return html`<div class="state" data-kind="error" role="alert"><i class="${STATE_ICON.error}" aria-hidden="true"></i><div><div class="t">The world did not answer</div><div class="b">Nothing has been read yet. <button type="button" class="btn btn-ghost" data-action="retry">Retry</button></div></div></div>`;
  }
  return skeletons(rows || 3);
}

// ---- page furniture ------------------------------------------------------

export function pageHead(title, summary, extra) {
  return html`<header class="page-head"><h1>${title}</h1>${summary ? html`<p class="summary">${summary}</p>` : ""}${extra || ""}</header>`;
}

export function sectionHead(idx, title, aside) {
  return html`<div class="section-head">${idx ? html`<span class="idx">${idx}</span>` : ""}<h2>${title}</h2>${aside ? html`<span class="aside">${aside}</span>` : ""}</div>`;
}

// A tab row. `items` are {label, href, current}; the row sticks under the
// header and the phone swipe gesture moves along it.
export function tabs(label, items) {
  return html`<nav class="tabs" aria-label="${label}">${items.map((t) => html`<a href="${t.href}"${t.current ? raw(' aria-current="page"') : ""}>${t.label}</a>`)}</nav>`;
}

export function kpi(label, v, href) {
  const body = html`<span class="v">${v}</span><span class="k">${label}</span>`;
  return href ? html`<a class="kpi" href="${href}">${body}</a>` : html`<div class="kpi">${body}</div>`;
}

// ---- charts --------------------------------------------------------------

// An area sparkline over `values` (numbers, nulls skipped). Width is the
// viewBox; the SVG scales to its container.
export function sparkline(values, opts) {
  const o = Object.assign({ w: 300, h: 56, fit: false, label: "" }, opts || {});
  const pts = (values || []).map((v, i) => [i, v]).filter((p) => p[1] !== null && p[1] !== undefined && isFinite(p[1]));
  if (pts.length < 2) return notMeasured();
  const ys = pts.map((p) => p[1]);
  const hi = Math.max(...ys, o.fit ? -Infinity : 1);
  const lo = o.fit ? Math.min(...ys) : Math.min(...ys, 0);
  const span = hi - lo || 1;
  const n = values.length - 1 || 1;
  const xy = pts.map(([i, v]) => [(i * o.w) / n, o.h - 4 - ((v - lo) / span) * (o.h - 8)]);
  const line = xy.map((p) => p[0].toFixed(1) + "," + p[1].toFixed(1)).join(" ");
  const area = "M" + xy[0][0].toFixed(1) + "," + o.h + " L" + line.replace(/ /g, " L") + " L" + xy[xy.length - 1][0].toFixed(1) + "," + o.h + " Z";
  return html`<svg class="spark" viewBox="0 0 ${o.w} ${o.h}" preserveAspectRatio="none" role="img" aria-label="${o.label}"><path class="area" d="${area}"></path><polyline class="line" points="${line}"></polyline></svg>`;
}

// Bars, one per bin: {label, n, href, median}. Heights scale to the tallest.
export function histogram(bins, opts) {
  const o = opts || {};
  if (!bins || !bins.length) return notMeasured();
  const top = Math.max(1, ...bins.map((b) => b.n || 0));
  const bars = bins.map((b) => {
    const h = Math.max(2, Math.round(((b.n || 0) / top) * 100));
    const cls = b.median ? "median" : "";
    const label = b.label + ": " + plural(b.n || 0, o.unit || "member");
    return b.href
      ? html`<a class="hit" href="${b.href}" aria-label="${label}" title="${label}"><span class="bar ${cls}" style="height:${h}%"></span></a>`
      : html`<span class="bar ${cls}" style="height:${h}%" aria-label="${label}" title="${label}"></span>`;
  });
  const first = bins[0].label, last = bins[bins.length - 1].label;
  const role = bins.some((b) => b.href) ? "group" : "img";
  return html`<div class="histo" role="${role}" aria-label="${o.label || "Distribution"}">${bars}</div><div class="histo-axis"><span>${first}</span><span>${last}</span></div>`;
}

// ---- the state of a read ---------------------------------------------------
// The one decision every view and read model takes about a read from api.js
// ({data, error, ...}), so pendingRead and the models never disagree.
//
//   loading   nothing has answered yet
//   failed    nothing has answered and the last ask failed
//   refused   the server answered, but with no payload or an error body
//   ready     a payload to draw (kept even while a later poll fails)

export function readState(read) {
  if (!read || read.data === undefined) return read && read.error ? "failed" : "loading";
  if (read.data === null || read.data.error) return "refused";
  return "ready";
}

export function ready(read) { return readState(read) === "ready"; }
