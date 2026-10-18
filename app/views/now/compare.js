// Two members' gear side by side, on the Character panel (#371).
//
// The panel's Compare control turns the one Character panel into two panes,
// each with its own character picker and its own close button. Both draw the
// same slot list in the same order (the paper doll's left column, then its
// right), one row per slot at one fixed height, so on a wide screen the rows
// line up across the two panes; on a phone the panes stack and every row
// still says how it differs from the other side.
//
// A difference is marked only when both sides were read and both members are
// in the world's save: a filled slot against an empty one, and a higher or
// lower item level. The shirt and the tabard are cosmetic and never marked.
// The mark is a word as well as a colour.
//
// Each pane reads only /api/armory/member for its member, the same read the
// Character panel's paperdoll draws from.

import { html, classVar, notMeasured, pendingRead, ready } from "../../ui.js";
import { cell, emptyCell } from "../_members.js";

export const SIDES = ["a", "b"];

export function armoryRead(name) {
  return "/api/armory/member?name=" + encodeURIComponent(name);
}

// ---- the pair -------------------------------------------------------------------
// {a, b}: the member in the first pane and the one in the second. These are
// pure, so the panel's state moves the same way the tests move it.

// The second pane opens on the first other member the picker lists (the same
// member again when nobody else was read; the picker changes it).
export function startPair(name, names) {
  const other = (names || []).find((n) => n !== name);
  return { a: name, b: other || name };
}

// One pane's picker chose `name`; the other pane keeps its member.
export function pick(pair, side, name) {
  if (!pair || !SIDES.includes(side) || !name) return pair;
  return side === "a" ? { a: name, b: pair.b } : { a: pair.a, b: name };
}

// The member left showing when `side`'s pane is closed.
export function closePane(pair, side) {
  return side === "a" ? pair.b : pair.a;
}

// ---- the difference, slot by slot ---------------------------------------------------

function level(s) {
  return s && typeof s.item_level === "number" && isFinite(s.item_level) ? s.item_level : null;
}

// How `mine` differs from `theirs`: "more" or "less" (item level), "filled"
// (worn here, empty there), "empty" (empty here, worn there), or "" (the same,
// or nothing to compare).
export function slotMark(mine, theirs) {
  if (!mine || !theirs || mine.cosmetic || theirs.cosmetic) return "";
  if (mine.empty && theirs.empty) return "";
  if (!mine.empty && theirs.empty) return "filled";
  if (mine.empty) return "empty";
  const a = level(mine), b = level(theirs);
  if (a === null || b === null || a === b) return "";
  return a > b ? "more" : "less";
}

// A member from an armory read, or null when the read is not ready or the
// member is not in the world's save.
function memberOf(read) {
  const m = ready(read) && read.data ? read.data.member : null;
  return m && m.present ? m : null;
}

// The slot order both panes draw, from whichever read answered.
export function slotOrder(readA, readB) {
  for (const r of [readA, readB]) {
    const d = ready(r) ? r.data : null;
    if (d && d.doll && Array.isArray(d.doll.left) && Array.isArray(d.doll.right)) return d.doll.left.concat(d.doll.right);
  }
  for (const r of [readA, readB]) {
    const m = memberOf(r);
    if (m && Array.isArray(m.slots)) return m.slots.map((s) => s.slot);
  }
  return [];
}

// One row per slot: {slot, a, b, ma, mb}, a and b the slot as each side
// wears it (undefined when that side was not read) and ma, mb the marks.
export function diffRows(readA, readB) {
  const ma = memberOf(readA), mb = memberOf(readB);
  const by = (m) => new Map(((m && m.slots) || []).map((s) => [s.slot, s]));
  const sa = by(ma), sb = by(mb);
  const both = !!(ma && mb);
  return slotOrder(readA, readB).map((slot) => {
    const a = sa.get(slot), b = sb.get(slot);
    return { slot, a, b, ma: both ? slotMark(a, b) : "", mb: both ? slotMark(b, a) : "" };
  });
}

// ---- drawing ---------------------------------------------------------------------------

const cap = (s) => String(s || "").charAt(0).toUpperCase() + String(s || "").slice(1);

// [the short word on the row, the sentence a screen reader hears]
function markWords(mark, mine, theirs) {
  if (mark === "more" || mark === "less") {
    const d = Math.abs(level(mine) - level(theirs));
    const sign = mark === "more" ? "+" : "-";
    return [sign + d + " ilvl", d + " item levels " + (mark === "more" ? "higher" : "lower") + " than the other"];
  }
  if (mark === "filled") return ["only here", "worn here, empty on the other"];
  if (mark === "empty") return ["missing", "empty here, worn on the other"];
  return ["", ""];
}

function slotCell(s) {
  if (!s) return emptyCell("?", "", "not read");
  if (s.empty) return emptyCell(s.empty_label || "empty", s.empty_kind === "cosmetic" ? "cosmetic" : "missing", s.slot + ": " + (s.empty_label || "empty"));
  return cell({ entry: s.entry, name: s.name, quality: s.quality, icon: s.icon, mark: s.mark, corner: s.item_level_mark || s.item_level, title: s.slot + ": " + s.name, size: "c48" });
}

function row(slot, mine, theirs, mark) {
  const what = !mine ? notMeasured() : mine.empty ? (mine.empty_label || "empty") : mine.name;
  const lv = level(mine);
  const [word, said] = markWords(mark, mine, theirs);
  return html`<li class="${"cmp-row" + (mark ? " cmp-" + mark : "")}" data-slot="${slot}"${mark ? html` data-mark="${mark}"` : ""}>${slotCell(mine)}<span class="cmp-id"><span class="cmp-slot">${cap(slot)}</span><span class="cmp-item">${what}</span></span><span class="cmp-lv">${lv === null ? "" : "ilvl " + lv}</span>${word ? html`<span class="cmp-mark" aria-hidden="true">${word}</span><span class="sr-only">${", " + said}</span>` : ""}</li>`;
}

function options(name, names) {
  const list = (names || []).includes(name) ? names : [name].concat(names || []);
  return list.map((n) => html`<option value="${n}"${n === name ? html` selected` : ""}>${n}</option>`);
}

function paneHtml(side, name, read, rows, names, cls) {
  const m = memberOf(read);
  const where = side === "a" ? "first" : "second";
  const gear = (m && m.gear) || {};
  const sum = m ? html`<p class="cmp-sum muted">Average item level ${gear.average_item_level ?? "not measured"} | ${gear.worn ?? "?"} of ${gear.slots ?? 17} slots worn</p>` : "";
  const wait = pendingRead(read, 3);
  const body = wait || (m ? html`<ol class="cmp-slots">${rows.map((r) => side === "a" ? row(r.slot, r.a, r.b, r.ma) : row(r.slot, r.b, r.a, r.mb))}</ol>` : notMeasured("Not in the world's save: nothing to compare"));
  return html`<section class="cmp-pane" data-side="${side}" aria-label="${name + "'s gear, " + where + " panel"}"><div class="cmp-head"><select class="input cmp-pick" data-pick="${side}" aria-label="${"Character in the " + where + " panel"}" style="color:${classVar(cls)}">${options(name, names)}</select><button type="button" class="np-close cmp-close" data-unpane="${side}" aria-label="${"Close " + name + "'s panel"}"><i class="ph ph-x" aria-hidden="true"></i></button></div>${sum}${body}</section>`;
}

// The two panes. `get` reads the cache (api.peek); `names` is what each
// picker lists; `clsOf(name)` the class a name is coloured by.
export function compareHtml(pair, get, names, clsOf) {
  const ra = get(armoryRead(pair.a)), rb = get(armoryRead(pair.b));
  const rows = diffRows(ra, rb);
  const c = clsOf || (() => "");
  return html`<div class="cmp">${paneHtml("a", pair.a, ra, rows, names, c(pair.a))}${paneHtml("b", pair.b, rb, rows, names, c(pair.b))}</div>`;
}
