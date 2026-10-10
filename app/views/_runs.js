// Guild runs as the Guilds view and the run page both draw them: the card,
// the boss pips, the seats, and the phone's bottom sheet. Runs come from
// /api/guildruns (`active` and `recent`), read by models/guildruns.js.

import { html, duration, plural, classVar, memberHref } from "../ui.js";
import { peek } from "../api.js";
import { since, clock } from "../models/time.js";
import { guildRuns, formedAt, endedAt, lastAt, bossText, chose, cause } from "../models/guildruns.js";

export function titleCase(s) {
  return String(s || "").replace(/(^|[\s-])([a-z])/g, (m, a, b) => a + b.toUpperCase());
}

const STATE = {
  inside: { text: "inside now", tone: "accent", icon: "ph-fill ph-door-open" },
  cleared: { text: "cleared", tone: "ok", icon: "ph-fill ph-check-circle" },
  wiped: { text: "wiped", tone: "bad", icon: "ph-fill ph-x-circle" },
};

// `run_state` is the one field that says where a run is (guildrun.run_state):
// queued, inside, or how it came back.
export function runState(r) {
  const key = r.run_state || "";
  return STATE[key] || { text: String(key || "state not recorded").replace(/_/g, " "), tone: "warn", icon: "ph ph-warning-circle" };
}

export function stateTag(r) {
  const s = runState(r);
  return html`<span class="tag g-run-tag" data-gt="${s.tone}"><i class="${s.icon}" aria-hidden="true"></i>${s.text}</span>`;
}

export function pips(r, cls) {
  const total = Number(r.bosses_total) || 0;
  if (!total) return "";
  const done = Number(r.bosses_done) || 0;
  const wiped = runState(r).tone === "bad";
  const cells = [];
  for (let i = 0; i < total; i++) {
    const kind = i < done ? "done" : wiped && i === done ? "fail" : "";
    cells.push(html`<span class="${kind}"></span>`);
  }
  return html`<div class="g-pips ${cls || ""}" role="img" aria-label="${done + " of " + total + " bosses down"}">${cells}</div>`;
}

// A run's seats in the order a group reads: tank, healer, then damage, and
// any seat not measured last; the payload's order within each.
const SEAT_ORDER = { tank: 0, healer: 1, dps: 2 };
const SEAT_ICON = {
  tank: ["ph-fill ph-shield", "tank"],
  healer: ["ph-fill ph-first-aid", "healer"],
};

export function seatOrder(members) {
  const rank = (m) => (m.seat in SEAT_ORDER ? SEAT_ORDER[m.seat] : 3);
  return (members || []).map((m, i) => [m, i]).sort((a, b) => rank(a[0]) - rank(b[0]) || a[1] - b[1]).map((x) => x[0]);
}

// The role symbol for a tank or a healer, with its word for a screen
// reader; damage dealers carry none.
export function seatIcon(seat) {
  const s = SEAT_ICON[seat];
  return s ? html`<i class="${s[0] + " seat-ic seat-" + seat}" role="img" aria-label="${s[1]}" title="${s[1]}"></i>` : "";
}

// Each seat as a chip: its role symbol and its name in its class colour,
// linking to the member's page. The row wraps; on a touch screen each chip
// is a 44px tap around a smaller pill (app.css, .seat-chip).
export function seatChips(r) {
  const list = seatOrder(r.members);
  if (!list.length) return "";
  return html`<ul class="seat-chips" aria-label="Seats">${list.map((m) => html`<li><a class="seat-chip" href="${memberHref(m.name)}" style="color:${classVar(m.class)}"><span class="seat-pill">${seatIcon(m.seat)}<span>${m.name}</span></span></a></li>`)}</ul>`;
}

export function inside(r) {
  const s = Number(r.seconds_inside);
  return s ? duration(s) + " inside" : "";
}

export function runHref(r) { return "#/runs/" + encodeURIComponent(r.id); }

export function findRun(id) {
  return guildRuns(peek("/api/guildruns")).find(id);
}

// The card is one tap to the run, and each seat in it a tap to that member:
// the run's link covers the card (app.css, .stretch-link) and the seat chips
// sit above it, so no link is nested in another.
export function runCard(r, opts) {
  const o = opts || {};
  const when = r.state === "inside" ? "" : " | " + since(lastAt(r));
  const meta = [bossText(r), o.done ? "" : inside(r)].filter(Boolean).join(" | ");
  return html`<div class="card g-run-card stretch-card">
<div class="g-run-top"><a class="g-run-name stretch-link" href="${runHref(r)}" data-run="${r.id}">${r.place || "A dungeon"} <span class="muted">#${r.id}${when}</span></a>${stateTag(r)}</div>
${o.done ? "" : pips(r)}
${o.done && cause(r) ? html`<span class="g-run-cause">${cause(r)}</span>` : ""}
<span class="g-run-meta">${meta}</span>
${seatChips(r)}
${!o.done && chose(r) ? html`<span class="g-run-chose">${chose(r)}</span>` : ""}
</div>`;
}

export function seatRows(r) {
  return seatOrder(r.members).map((m) => html`<a class="g-seat-row" href="${memberHref(m.name)}"><span class="g-seat-name" style="color:${classVar(m.class)}">${seatIcon(m.seat)}${m.name}</span><span class="muted">L${m.level} ${titleCase(m.class)} | ${m.seat || "seat not measured"}</span></a>`);
}

// The steps a guild run can show without a per-event record: when it formed,
// the coordinator's lines, and how it came back.
export function steps(r) {
  const out = [];
  const formed = formedAt(r);
  if (formed) out.push({ t: formed, text: "Formed: " + plural((r.members || []).length, "seat") + " filled." });
  (r.lines || []).forEach((l) => out.push({ t: null, text: l }));
  const ended = endedAt(r);
  if (ended) out.push({ t: ended, text: "Came back: " + (r.story || cause(r) || runState(r).text) });
  return out;
}

export function stepRows(list) {
  return list.map((s) => html`<div class="g-step"><span class="g-step-t">${s.t ? clock(s.t) : ""}</span><span>${s.text}</span></div>`);
}

// ---- the phone's bottom sheet --------------------------------------------

let open = null; // {scrim, back}

export function closeSheet() {
  if (!open) return;
  const { scrim, back, onKey } = open;
  open = null;
  document.removeEventListener("keydown", onKey);
  scrim.remove();
  if (back && back.isConnected) back.focus({ preventScroll: true });
}

export function openSheet(r, back) {
  closeSheet();
  const guild = r.guild || "";
  const scrim = document.createElement("div");
  scrim.className = "scrim g-run-scrim";
  scrim.innerHTML = html`<div class="sheet g-run-sheet" role="dialog" aria-modal="true" aria-label="${guild + " | " + (r.place || "run")}">
<span class="grab" aria-hidden="true"></span>
<div class="g-run-top"><span class="g-sheet-title">${guild} | ${r.place || "A dungeon"}</span>${stateTag(r)}</div>
${pips(r, "g-pips-lg")}
<span class="g-run-meta">${[bossText(r), inside(r)].filter(Boolean).join(" | ")}</span>
${seatChips(r)}
<div class="g-steps">${stepRows(steps(r))}</div>
<div class="g-sheet-actions"><a class="btn btn-secondary" href="${runHref(r)}" data-sheet="close">Full page</a><button type="button" class="btn btn-primary" data-sheet="close">Close</button></div>
</div>`.s;
  const onKey = (e) => { if (e.key === "Escape") closeSheet(); };
  scrim.addEventListener("click", (e) => {
    if (e.target === scrim || e.target.closest('[data-sheet="close"]')) closeSheet();
  });
  document.addEventListener("keydown", onKey);
  // Known before it is on the page, so anything that closes it from here on
  // finds it.
  open = { scrim, back, onKey };
  document.body.appendChild(scrim);
  const first = scrim.querySelector("button");
  if (first) first.focus({ preventScroll: true });
}

// Run cards open the sheet on phone instead of navigating.
export function bindRunCards(main, isPhone) {
  main.querySelectorAll("[data-run]").forEach((a) => {
    a.addEventListener("click", (e) => {
      if (!isPhone()) return;
      const r = findRun(a.getAttribute("data-run"));
      if (!r) return;
      e.preventDefault();
      openSheet(r, a);
    });
  });
}

// A route change (back button, a link in the sheet) never leaves it open.
window.addEventListener("hashchange", closeSheet);
