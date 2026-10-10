// One item tooltip for the whole app. Every item link carries data-item (see
// ui.item). On a device that can hover, hover or keyboard focus shows a
// 280px card beside the link; on a touch phone a tap opens a bottom sheet.
// The card is drawn from /api/item, read once per item and kept.

import { load, peek } from "./api.js";
import { html } from "./ui.js";

const QNAME = ["Poor", "Common", "Uncommon", "Rare", "Epic", "Legendary", "Artifact", "Heirloom"];
const SOURCE_KIND = {
  drop: "Drop", quest: "Quest", vendor: "Vendor", craft: "Crafted", honor: "Honor",
  pvp: "Honor", chest: "Container", reputation: "Reputation", fishing: "Fishing",
  pickpocket: "Pickpocket", world: "World drop", starting: "Starting gear",
};

let tip = null;     // the hover card
let scrim = null;   // the phone sheet
let current = 0;    // entry shown
let anchor = null;

const touchFirst = () => window.matchMedia("(hover: none), (max-width: 759.98px)").matches;

function path(entry) { return "/api/item?entry=" + entry; }

function sourceLines(sources) {
  const out = [];
  (sources || []).slice(0, 3).forEach((s) => {
    const kind = SOURCE_KIND[s.kind] || (s.kind ? s.kind.charAt(0).toUpperCase() + s.kind.slice(1) : "Source");
    const where = [s.boss || s.npc || s.quest || s.name, s.where || s.zone].filter(Boolean).join(", ");
    const chance = s.chance ? " (" + Math.round(s.chance * 10) / 10 + "%)" : "";
    out.push(html`<div class="ln ln-src"><span>Source: ${kind}</span><span></span></div>`);
    if (where) out.push(html`<div class="ln ln-where"><span>${where + chance}</span><span></span></div>`);
  });
  if (!out.length) out.push(html`<div class="ln ln-src"><span>Source: not measured</span><span></span></div>`);
  return out;
}

// The card's lines, in the game's order.
export function lines(payload, fallbackName) {
  if (!payload) return [html`<div class="ln ln-name"><span>${fallbackName || "Item"}</span><span></span></div>`, html`<div class="ln ln-dim"><span>Reading the item...</span><span></span></div>`];
  const t = payload.tooltip || {};
  const q = Number(t.quality ?? payload.quality ?? 1);
  const L = [];
  L.push(html`<div class="ln ln-name tq${q}"><span>${t.name || payload.name || fallbackName}</span><span></span></div>`);
  if (t.binding) L.push(html`<div class="ln"><span>${t.binding}</span><span></span></div>`);
  if (t.slot || t.kind) L.push(html`<div class="ln"><span>${t.slot || ""}</span><span>${t.kind || ""}</span></div>`);
  if (t.damage) {
    const d = t.damage;
    L.push(html`<div class="ln"><span>${Math.round(d.min) + " - " + Math.round(d.max) + " Damage"}</span><span>${"Speed " + Number(d.speed).toFixed(2)}</span></div>`);
    if (d.dps) L.push(html`<div class="ln"><span>${"(" + Number(d.dps).toFixed(1) + " damage per second)"}</span><span></span></div>`);
  }
  if (t.armor) L.push(html`<div class="ln"><span>${t.armor + " Armor"}</span><span></span></div>`);
  if (t.block) L.push(html`<div class="ln"><span>${t.block + " Block"}</span><span></span></div>`);
  (t.stats || []).forEach((s) => L.push(html`<div class="ln"><span>${s}</span><span></span></div>`));
  (t.resistances || []).forEach((s) => L.push(html`<div class="ln"><span>${s}</span><span></span></div>`));
  (t.enchant || []).forEach((s) => L.push(html`<div class="ln ln-bonus"><span>${s}</span><span></span></div>`));
  if (t.durability) L.push(html`<div class="ln"><span>${"Durability " + t.durability}</span><span></span></div>`);
  if (t.classes) L.push(html`<div class="ln"><span>${"Classes: " + (Array.isArray(t.classes) ? t.classes.join(", ") : t.classes)}</span><span></span></div>`);
  if (t.requires_level) L.push(html`<div class="ln"><span>${"Requires level " + t.requires_level}</span><span></span></div>`);
  (t.effects || []).forEach((s) => L.push(html`<div class="ln ln-bonus"><span>${typeof s === "string" ? s : s.text || ""}</span><span></span></div>`));
  if (t.set) L.push(html`<div class="ln ln-dim"><span>${typeof t.set === "string" ? t.set : t.set.name || ""}</span><span></span></div>`);
  if (t.flavor) L.push(html`<div class="ln" style="color:#ffd100"><span>${'"' + t.flavor + '"'}</span><span></span></div>`);
  if (t.item_level) L.push(html`<div class="ln ln-dim ln-gap"><span>${"Item level " + t.item_level}</span><span>${QNAME[q] || ""}</span></div>`);
  return L.concat(sourceLines(payload.sources));
}

function ensure() {
  if (tip) return;
  tip = document.createElement("div");
  tip.className = "tip";
  tip.setAttribute("role", "tooltip");
  tip.id = "item-tip";
  tip.hidden = true;
  document.body.appendChild(tip);
  scrim = document.createElement("div");
  scrim.className = "scrim";
  scrim.hidden = true;
  scrim.innerHTML = '<div class="sheet item-sheet" role="dialog" aria-modal="true" aria-label="Item"><span class="grab" aria-hidden="true"></span><div class="tip-body"></div><button type="button" class="close">Close</button></div>';
  document.body.appendChild(scrim);
  scrim.addEventListener("click", (e) => { if (e.target === scrim || e.target.closest(".close")) hide(); });
}

function fill(target, entry, name) {
  target.innerHTML = lines(peek(path(entry)).data, name).join("");
}

function place(el) {
  const r = el.getBoundingClientRect();
  const h = tip.offsetHeight || 220;
  const left = Math.max(8, Math.min(r.left, window.innerWidth - 292));
  const below = r.bottom + h + 12 <= window.innerHeight;
  tip.style.left = left + "px";
  tip.style.top = (below ? r.bottom + 6 : Math.max(8, r.top - h - 6)) + "px";
}

export function show(el) {
  ensure();
  const entry = Number(el.getAttribute("data-item")) || 0;
  const name = el.getAttribute("data-name") || el.textContent.trim();
  current = entry; anchor = el;
  const phone = touchFirst();
  const body = phone ? scrim.querySelector(".tip-body") : tip;
  fill(body, entry, name);
  if (phone) {
    scrim.hidden = false;
    scrim.querySelector(".close").focus({ preventScroll: true });
  } else {
    tip.hidden = false;
    el.setAttribute("aria-describedby", "item-tip");
    place(el);
  }
  if (entry > 0 && peek(path(entry)).data === undefined) {
    load(path(entry)).then(() => {
      if (current !== entry) return;
      fill(phone ? scrim.querySelector(".tip-body") : tip, entry, name);
      if (!phone && anchor) place(anchor);
    });
  }
}

export function hide() {
  if (tip) tip.hidden = true;
  if (scrim && !scrim.hidden) {
    scrim.hidden = true;
    if (anchor && document.contains(anchor)) anchor.focus({ preventScroll: true });
  }
  if (anchor) anchor.removeAttribute("aria-describedby");
  current = 0;
}

export function install() {
  document.addEventListener("pointerover", (e) => {
    if (e.pointerType !== "mouse") return;
    const el = e.target.closest("[data-item]");
    if (el) show(el);
  });
  document.addEventListener("pointerout", (e) => {
    if (e.pointerType !== "mouse") return;
    const el = e.target.closest("[data-item]");
    if (el && !el.contains(e.relatedTarget)) hide();
  });
  document.addEventListener("focusin", (e) => {
    const el = e.target.closest && e.target.closest("[data-item]");
    if (el && !touchFirst()) show(el);
  });
  document.addEventListener("focusout", (e) => {
    const el = e.target.closest && e.target.closest("[data-item]");
    if (el && !touchFirst()) hide();
  });
  document.addEventListener("click", (e) => {
    const el = e.target.closest("[data-item]");
    if (!el) return;
    e.preventDefault();
    if (touchFirst()) show(el);
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") hide(); });
  window.addEventListener("hashchange", hide);
  window.addEventListener("scroll", () => { if (tip && !tip.hidden) hide(); }, { passive: true });
}

