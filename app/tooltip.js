// One item tooltip for the whole app. Every item link carries data-item (see
// ui.item). On a device that can hover, hover or keyboard focus shows a
// 280px card beside the link; on a touch phone a tap opens a bottom sheet,
// and a second tap, on the item, the sheet or outside it, closes it.
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

// One line of the card. A two-cell row (slot | type, damage | speed, item
// level | quality) is two elements laid out left and right, with a space
// between them, so the cells never run together: not on screen, not read
// aloud and not copied. A one-cell row is one element.
function row(cls, left, right) {
  const c = "ln" + (cls ? " " + cls : "");
  if (right === undefined || right === null || right === "") return html`<div class="${c}"><span class="ln-l">${left}</span></div>`;
  return html`<div class="${c}"><span class="ln-l">${left}</span> <span class="ln-r">${right}</span></div>`;
}

// A drop chance as the card says it. /api/item reports a percent rounded to
// two places (itemsource.py), so 0 there means a chance too small to keep,
// never "cannot drop", and a chance under a tenth of a percent rounds to 0
// at one place. Both read as "rare drop" rather than "0%".
export function chanceText(n) {
  const v = Number(n);
  if (!isFinite(v) || v < 0.1) return "rare drop";
  return Math.round(v * 10) / 10 + "%";
}

function kindOf(s) {
  return SOURCE_KIND[s.kind] || (s.kind ? s.kind.charAt(0).toUpperCase() + s.kind.slice(1) : "Source");
}

function placeOf(s) {
  return [s.boss || s.npc || s.quest || s.object || s.recipe || s.name, s.where || s.zone].filter(Boolean).join(", ");
}

// One source that is not one of several drops: the kind and its chance on
// one row, the boss, quest or vendor and the zone under it.
function chanceCell(s) {
  const has = (v) => v !== undefined && v !== null;
  if (!has(s.chance) && !has(s.chance_max)) return "";
  const t = chanceText(has(s.chance) ? s.chance : s.chance_max);
  if (t === "rare drop") return t;
  return has(s.chance) ? t + " chance" : "up to " + t;
}

function oneSource(s, first) {
  const out = [row(first ? "ln-src ln-sep" : "ln-src", "Source: " + kindOf(s), chanceCell(s))];
  const where = placeOf(s);
  if (where) out.push(row("ln-where", where));
  return out;
}

// Several bosses dropping the item: one "Drops from" heading, then each
// zone once with its bosses and their chances under it.
function dropGroup(drops, first) {
  const out = [row(first ? "ln-src ln-sep" : "ln-src", "Drops from")];
  const zones = [];
  drops.forEach((d) => {
    const z = d.where || d.zone || "";
    let g = zones.find((x) => x.zone === z);
    if (!g) { g = { zone: z, list: [] }; zones.push(g); }
    g.list.push(d);
  });
  zones.forEach((g) => {
    if (g.zone) out.push(row("ln-where ln-zone", g.zone));
    g.list.forEach((d) => out.push(row("ln-drop", d.boss || d.name || "A creature", chanceText(d.chance))));
  });
  return out;
}

// Where an item comes from, set apart under a rule.
function sourceLines(sources) {
  const list = sources || [];
  const drops = list.filter((s) => s.kind === "drop");
  const out = [];
  if (drops.length > 1) {
    out.push(...dropGroup(drops, true));
    list.filter((s) => s.kind !== "drop").slice(0, 2).forEach((s) => out.push(...oneSource(s, false)));
  } else {
    list.slice(0, 3).forEach((s, i) => out.push(...oneSource(s, i === 0)));
  }
  if (!out.length) out.push(row("ln-src ln-sep", "Source: not measured"));
  return out;
}

// The name row. The phone sheet also draws the item's icon beside it, ringed
// in the quality colour: the icon the tapped link shows, or its slot mark.
function nameRow(q, name, art) {
  let pic = "";
  if (art && art.icon) pic = html`<img class="ticon" src="${art.icon}" alt="" width="36" height="36">`;
  else if (art) pic = html`<span class="ticon noicon" aria-hidden="true">${art.mark || ""}</span>`;
  return html`<div class="ln ln-name tq${q}">${pic}<span class="ln-l">${name}</span></div>`;
}

// The card's lines, in the game's order: white stats, green Equip and Use
// lines, dim requirements, the item level and quality, then the sources.
export function lines(payload, fallbackName, art) {
  if (!payload) return [nameRow(1, fallbackName || "Item", art), row("ln-dim", "Reading the item...")];
  const t = payload.tooltip || {};
  const q = Number(t.quality ?? payload.quality ?? 1);
  const L = [nameRow(q, t.name || payload.name || fallbackName, art)];
  if (t.binding) L.push(row("", t.binding));
  if (t.slot || t.kind) L.push(row("", t.slot || "", t.kind || ""));
  if (t.damage) {
    const d = t.damage;
    L.push(row("", Math.round(d.min) + " - " + Math.round(d.max) + " Damage", "Speed " + Number(d.speed).toFixed(2)));
    if (d.dps) L.push(row("", "(" + Number(d.dps).toFixed(1) + " damage per second)"));
  }
  if (t.armor) L.push(row("", t.armor + " Armor"));
  if (t.block) L.push(row("", t.block + " Block"));
  (t.stats || []).forEach((s) => L.push(row("", s)));
  (t.resistances || []).forEach((s) => L.push(row("", s)));
  (t.enchant || []).forEach((s) => L.push(row("ln-bonus", s)));
  if (t.durability) L.push(row("", "Durability " + t.durability));
  if (t.classes) L.push(row("ln-req", "Classes: " + (Array.isArray(t.classes) ? t.classes.join(", ") : t.classes)));
  if (t.requires_level) L.push(row("ln-req", "Requires level " + t.requires_level));
  (t.effects || []).forEach((s) => L.push(row("ln-bonus", typeof s === "string" ? s : s.text || "")));
  if (t.set) L.push(row("ln-dim", typeof t.set === "string" ? t.set : t.set.name || ""));
  if (t.flavor) L.push(row("ln-flavor", '"' + t.flavor + '"'));
  if (t.item_level) L.push(row("ln-dim ln-gap", "Item level " + t.item_level, QNAME[q] || ""));
  return L.concat(sourceLines(payload.sources));
}

function ensure() {
  if (tip) return;
  tip = document.createElement("div");
  tip.className = "tip tipcard";
  tip.setAttribute("role", "tooltip");
  tip.id = "item-tip";
  tip.hidden = true;
  document.body.appendChild(tip);
  scrim = document.createElement("div");
  scrim.className = "scrim";
  scrim.hidden = true;
  scrim.innerHTML = '<div class="sheet item-sheet" role="dialog" aria-modal="true" aria-label="Item"><span class="grab" aria-hidden="true"></span><div class="tip-body tipcard"></div><button type="button" class="close">Close</button></div>';
  document.body.appendChild(scrim);
  // The sheet only shows the card, so any tap on it, or outside it, closes it.
  scrim.addEventListener("click", () => hide());
}

function fill(target, entry, name, art) {
  target.innerHTML = lines(peek(path(entry)).data, name, art).join("");
}

// The tapped link's icon (or slot mark), for the sheet's name row.
function artOf(el) {
  const img = el.querySelector && el.querySelector("img");
  if (img && img.getAttribute("src")) return { icon: img.getAttribute("src") };
  const mark = el.querySelector && el.querySelector(".noicon");
  return { mark: mark ? mark.textContent.trim() : "" };
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
  const art = phone ? artOf(el) : null;
  fill(body, entry, name, art);
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
      fill(phone ? scrim.querySelector(".tip-body") : tip, entry, name, art);
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
    if (!touchFirst()) return;
    if (scrim && !scrim.hidden && anchor === el) hide();
    else show(el);
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") hide(); });
  window.addEventListener("hashchange", hide);
  window.addEventListener("scroll", () => { if (tip && !tip.hidden) hide(); }, { passive: true });
}

