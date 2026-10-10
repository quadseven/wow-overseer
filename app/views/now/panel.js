// The tile panels on Now: a member's Bags, Bank, Guild bank, Character,
// Social and Quests, drawn over the page so the live pictures keep playing.
// A bottom sheet on phone (grab handle, drag down or tap outside to close),
// a side panel on desktop. Escape closes it; focus stays inside while it is
// open and goes back to the button that opened it.
//
// Nothing here draws a frame of its own: Bags, Bank, Character and Quests are
// the member profile's tabs (member.js), the Guild bank is the Economy tab
// (economy.js), each reading what that page reads. Social is drawn here, from
// /api/v2/social, because no page draws it. A link inside the panel to one of
// these frames switches the panel; any other link leaves the page as usual.

import { load, peek, onChange } from "../../api.js";
import { html, classVar, memberHref, notMeasured, plural, pendingRead, statusColor } from "../../ui.js";
import { parse } from "../../router.js";
import * as member from "../member.js";
import * as economy from "../economy.js";
import { bindTrees } from "../_members.js";
import { roster as rosterModel } from "../../models/roster.js";
import { mountModels } from "../_model.js";
import { ACTIONS } from "./streams.js";

const POLL_MS = 30000;
const DISMISS_PX = 110;
const q = (name) => "?name=" + encodeURIComponent(name);
const GUILD_BANK = { params: { tab: "bank" }, query: {} };

// Each panel: the reads it needs, how it draws, and its full page.
export const PANELS = {
  bags: { reads: (n) => member.readsFor(n, "bags"), draw: (c, m) => member.inventoryTab(c, m, "bags"), page: (n) => memberHref(n, "bags") },
  bank: { reads: (n) => member.readsFor(n, "bank"), draw: (c, m) => member.inventoryTab(c, m, "bank"), page: (n) => memberHref(n, "bank") },
  guildbank: { reads: () => economy.readsFor(GUILD_BANK), draw: (c) => economy.bankTab(c, c.get), page: () => "#/economy/bank" },
  gear: { reads: (n) => member.readsFor(n, "gear"), draw: (c, m) => member.gearTab(c, m), page: (n) => memberHref(n, "gear") },
  social: { reads: (n) => ["/api/v2/social" + q(n)], draw: (c, m) => socialBody(c.get("/api/v2/social" + q(m.name)), m.name), page: (n) => memberHref(n) },
  quests: { reads: (n) => member.readsFor(n, "quests"), draw: (c, m) => member.questsTab(c, m), page: (n) => memberHref(n, "quests") },
};

let open = null; // {name, kind, query, back, scrim, sheet, body, timer, off}

// ---- Social ------------------------------------------------------------------
const cap = (s) => String(s || "").charAt(0).toUpperCase() + String(s || "").slice(1);

function person(p, link, extra) {
  const dot = html`<span class="np-dot" style="background:${statusColor(p.online ? "online" : "offline")}" aria-hidden="true"></span>`;
  const who = html`<span class="np-who" style="color:${classVar(p["class"])}">${p.name}</span>`;
  const line = html`<span class="np-line">${p.line || notMeasured()}${extra ? " | " + extra : ""}</span>`;
  const inner = html`${dot}<span class="np-id">${who}${line}</span><span class="sr-only">${p.online ? ", online" : ", offline"}</span>`;
  return link ? html`<a class="np-row" href="${memberHref(p.name)}">${inner}</a>` : html`<div class="np-row">${inner}</div>`;
}

function group(title, aside, rows) {
  return html`<section class="np-group"><div class="np-ghead"><h3>${title}</h3>${aside ? html`<span class="dim">${aside}</span>` : ""}</div>${rows}</section>`;
}

export function socialBody(read, name) {
  const wait = pendingRead(read, 3);
  if (wait) return wait;
  const s = read.data;
  const fam = (s.family && s.family.members) || [];
  const g = s.guild || {};
  const roster = g.members || [];
  const on = roster.filter((p) => p.online), off = roster.filter((p) => !p.online);
  const famTitle = s.family && s.family.key ? s.family.key + "'s family" : name + "'s family";
  const friends = (s.friends || []).map((p) => person(p, false, p.note));
  const guildRows = roster.length
    ? html`${on.map((p) => person(p, true, p.rank))}${off.length ? html`<details class="np-more"><summary>${plural(off.length, "member")} offline</summary>${off.map((p) => person(p, true, p.rank))}</details>` : ""}`
    : html`<p class="muted np-note">${cap(g.note) || "No guild roster was read."}</p>`;
  return html`${group(famTitle, plural(fam.length, "member"), fam.length ? fam.map((p) => person(p, p.level !== null)) : html`<p class="muted np-note">No family was read.</p>`)}
${group("Friends", friends.length ? plural(friends.length, "friend") : "", friends.length ? friends : html`<p class="muted np-note">${cap(s.friends_note) || "No friends on the list."}</p>`)}
${group(g.name || "Guild", g.name ? g.online + " of " + plural(g.total, "member") + " online" : "", guildRows)}
${(s.ignored || []).length ? group("Ignored", "", html`<p class="muted np-note">${s.ignored.join(", ")}</p>`) : ""}`;
}

// ---- drawing -------------------------------------------------------------------
function who(name) {
  return rosterModel(peek("/api/v2/roster")).member(name) || { name, class: open && open.cls };
}

function readsOf(o) { return PANELS[o.kind].reads(o.name); }

function ctxOf(o) {
  return { get: peek, params: { name: o.name, tab: o.kind }, query: o.query, isPhone: () => window.matchMedia("(max-width: 759.98px)").matches };
}

function label(kind) { return (ACTIONS.find((a) => a[0] === kind) || [kind, kind])[1]; }

function headHtml(o, m) {
  const tabsRow = ACTIONS.map(([key, text, icon]) => html`<button type="button" class="np-tab" data-kind="${key}"${key === o.kind ? html` aria-current="true"` : ""}><i class="${"ph " + icon}" aria-hidden="true"></i>${text}</button>`);
  return html`<div class="np-top" data-drag><span class="grab" aria-hidden="true"></span>
<div class="np-head"><h2 class="np-title" id="np-title"><span style="color:${classVar(m["class"])}">${o.name}</span> <span class="np-kind">${label(o.kind)}</span></h2>
<a class="np-page" href="${PANELS[o.kind].page(o.name)}"><span>Full page</span><i class="ph ph-arrow-square-out" aria-hidden="true"></i></a>
<button type="button" class="np-close" data-close aria-label="Close"><i class="ph ph-x" aria-hidden="true"></i></button></div>
<div class="np-tabs" role="group" aria-label="${o.name + "'s frames"}">${tabsRow}</div></div>`;
}

// When the guild bank opens, it opens on this member's guild.
function seedQuery(o, m) {
  if (o.kind === "guildbank" && !o.query.guild && m.guild) o.query = { guild: String(m.guild).toLowerCase() };
}

// The header (title, Full page, Close and the frame switch) is drawn when the
// panel opens or switches; the body again on every answer to its reads.
function drawHead() {
  const o = open, m = who(o.name);
  seedQuery(o, m);
  o.head.innerHTML = headHtml(o, m).s;
}

function drawBody() {
  if (!open) return;
  const o = open, m = who(o.name);
  const focusAt = focusIndex(o.body);
  o.body.innerHTML = html`<div class="np-content">${PANELS[o.kind].draw(ctxOf(o), m)}</div>`.s;
  bindTrees(o.body);
  if (o.kind === "gear") mountModels(o.body);
  restoreFocus(o.body, focusAt);
}

function focusables(root) {
  return Array.from(root.querySelectorAll('a[href], button:not([disabled]), summary, input, select, textarea, [tabindex]:not([tabindex="-1"])'))
    .filter((n) => !n.closest("[hidden]") && n.getClientRects().length);
}

function focusIndex(root) {
  const a = document.activeElement;
  return a && root.contains(a) && a !== root ? focusables(root).indexOf(a) : -1;
}

function restoreFocus(root, i) {
  if (i < 0) return;
  const list = focusables(root);
  const to = list[Math.min(i, list.length - 1)];
  if (to) to.focus({ preventScroll: true });
}

function fetchAll() {
  if (!open) return;
  readsOf(open).forEach((p) => load(p));
}

// ---- open and close -----------------------------------------------------------
function build() {
  const scrim = document.createElement("div");
  scrim.className = "scrim np-scrim";
  scrim.innerHTML = '<div class="np-sheet" role="dialog" aria-modal="true" aria-labelledby="np-title" tabindex="-1"><div class="np-headbox"></div><div class="np-body"></div></div>';
  return { scrim, sheet: scrim.firstChild, head: scrim.querySelector(".np-headbox"), body: scrim.querySelector(".np-body") };
}

const reduced = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

// Opens `kind` for `name` over the page, or switches the open panel to it.
// `back` is the button to give focus back to; it is found again by its
// data-focus key, since a redraw of Now replaces it while the panel is open.
export function openPanel(name, kind, back) {
  if (!PANELS[kind]) return;
  if (open && open.name === name) { switchTo(kind, {}); return; }
  closePanel(true);
  const parts = build();
  const tile = back && back.closest ? back.closest(".st") : null;
  open = Object.assign(parts, {
    name, kind, query: {},
    cls: tile ? tile.getAttribute("data-class") || "" : "",
    backKey: back && back.getAttribute ? back.getAttribute("data-focus") || "" : "",
  });
  wire(open);
  document.body.appendChild(parts.scrim);
  setInert(true);
  drawHead();
  drawBody();
  fetchAll();
  open.off = onChange((path) => { if (open && readsOf(open).includes(path)) drawBody(); });
  open.timer = window.setInterval(() => { if (!document.hidden) fetchAll(); }, POLL_MS);
  pressed();
  window.requestAnimationFrame(() => { if (open && open.scrim === parts.scrim) parts.scrim.setAttribute("data-open", ""); });
  parts.sheet.focus({ preventScroll: true });
}

export function switchTo(kind, query) {
  if (!open || !PANELS[kind]) return;
  open.kind = kind;
  open.query = query || {};
  open.body.scrollTop = 0;
  drawHead();
  drawBody();
  fetchAll();
  pressed();
  const tab = open.head.querySelector('[data-kind="' + kind + '"]');
  if (tab) tab.focus({ preventScroll: true });
}

// `quiet`: no focus return (another panel is opening, or the page is leaving).
export function closePanel(quiet) {
  if (!open) return;
  const o = open;
  open = null;
  window.clearInterval(o.timer);
  if (o.off) o.off();
  setInert(false);
  pressed();
  o.scrim.removeAttribute("data-open");
  o.sheet.style.transform = "";
  const gone = () => o.scrim.remove();
  if (quiet || reduced()) gone();
  else window.setTimeout(gone, 360);
  if (quiet) return;
  const back = o.backKey ? document.querySelector('[data-focus="' + CSS.escape(o.backKey) + '"]') : null;
  if (back) back.focus({ preventScroll: true });
}

export function isOpen() { return !!open; }

// The page behind is out of reach while the panel is up.
function setInert(on) {
  document.querySelectorAll("body > #app, body > .skip").forEach((n) => {
    if (on) n.setAttribute("inert", ""); else n.removeAttribute("inert");
  });
}

// The tile button whose panel is open says so (again after every redraw of Now).
export function pressed() {
  document.querySelectorAll("[data-panel]").forEach((b) => {
    const on = !!open && b.getAttribute("data-name") === open.name && b.getAttribute("data-panel") === open.kind;
    b.setAttribute("aria-expanded", String(on));
  });
}

// ---- links, keys and the drag ------------------------------------------------------
// A link to one of the panel's own frames, for this member: {kind, query}.
export function inPanel(href, name) {
  const p = parse(href);
  const [a, b, c] = p.parts;
  if (a === "m" && b === name && PANELS[c] && c !== "social" && c !== "guildbank") return { kind: c, query: {} };
  if (a === "economy" && b === "bank" && !c) return { kind: "guildbank", query: p.query };
  return null;
}

function onClick(e) {
  const o = open;
  if (!o) return;
  if (e.target === o.scrim || e.target.closest("[data-close]")) { e.preventDefault(); closePanel(); return; }
  const tab = e.target.closest("[data-kind]");
  if (tab) { switchTo(tab.getAttribute("data-kind"), {}); return; }
  if (e.target.closest('[data-action="retry"]')) { fetchAll(); return; }
  const a = e.target.closest("a[href]");
  if (!a || a.classList.contains("np-page")) return;
  const to = inPanel(a.getAttribute("href"), o.name);
  if (to) { e.preventDefault(); switchTo(to.kind, to.query); }
}

function itemTipShowing() {
  const tip = document.getElementById("item-tip");
  return !!(tip && !tip.hidden);
}

function onKey(e) {
  if (!open) return;
  if (e.key === "Escape") {
    // An item's hover card closes first; the tooltip's own Escape does that.
    if (itemTipShowing()) return;
    e.preventDefault();
    closePanel();
    return;
  }
  if (e.key !== "Tab") return;
  const list = focusables(open.sheet);
  if (!list.length) { e.preventDefault(); return; }
  const first = list[0], last = list[list.length - 1];
  const at = document.activeElement;
  if (e.shiftKey && (at === first || at === open.sheet)) { e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && at === last) { e.preventDefault(); first.focus(); }
}

// Drag down to close, on phone: from the grab and the header always, from the
// content only when it is scrolled to its top. Short of DISMISS_PX (and not a
// flick) it springs back.
function wire(o) {
  o.scrim.addEventListener("click", onClick);
  o.scrim.addEventListener("keydown", onKey);
  let y0 = 0, t0 = 0, dy = 0, drag = false;
  o.sheet.addEventListener("touchstart", (e) => {
    if (e.touches.length !== 1 || !window.matchMedia("(max-width: 759.98px)").matches) { drag = false; return; }
    const fromHead = !!e.target.closest("[data-drag]") && !e.target.closest(".np-tabs");
    drag = fromHead || (o.body.contains(e.target) && o.body.scrollTop <= 0 && !e.target.closest(".hscroll, .np-tabs"));
    y0 = e.touches[0].clientY; t0 = Date.now(); dy = 0;
  }, { passive: true });
  o.sheet.addEventListener("touchmove", (e) => {
    if (!drag) return;
    dy = Math.max(0, e.touches[0].clientY - y0);
    if (dy <= 0) return;
    if (e.cancelable) e.preventDefault();
    o.sheet.setAttribute("data-dragging", "");
    o.sheet.style.transform = "translateY(" + dy + "px)";
  }, { passive: false });
  o.sheet.addEventListener("touchend", () => {
    if (!drag) return;
    drag = false;
    o.sheet.removeAttribute("data-dragging");
    const flick = dy > 40 && dy / Math.max(1, Date.now() - t0) > 0.6;
    if (dy > DISMISS_PX || flick) closePanel();
    else o.sheet.style.transform = "";
  });
}

// Leaving Now closes it; nothing it shows belongs to another page.
window.addEventListener("hashchange", () => closePanel(true));
