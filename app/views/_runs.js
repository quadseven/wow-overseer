// Guild runs as the Guilds view and the run page both draw them: the card,
// the boss pips, the seats, and the phone's bottom sheet. Runs come from
// /api/guildruns (`active` and `recent`), one shape for both lists.

import { html, ago, duration, plural, classVar, memberHref } from "../ui.js";
import { peek } from "../api.js";

export const GUILD_NAME = { cave: "Cave", bonkers: "Bonkers" };
// Each guild's family (Grug's family plays in Cave, Zug's in Bonkers). The
// guild read says the family it found too; the view checks the two agree.
export const GUILD_FAMILY = { cave: "Grug", bonkers: "Zug" };

// The realm's database clock is UTC and its timestamps arrive without a zone
// ("2026-10-09 20:12:04"), so they are read as UTC. Unix seconds pass through.
export function utc(v) {
  if (v === null || v === undefined || v === "") return null;
  if (typeof v === "number") return v;
  const s = String(v).trim().replace(" ", "T");
  const t = Date.parse(/[zZ]|[+-]\d\d:?\d\d$/.test(s) ? s : s + "Z");
  return isFinite(t) ? t / 1000 : null;
}

export function since(ts) {
  return ts === null || ts === undefined ? "not measured" : ago(Date.now() / 1000 - ts);
}

export function titleCase(s) {
  return String(s || "").replace(/(^|[\s-])([a-z])/g, (m, a, b) => a + b.toUpperCase());
}

const STATE = {
  inside: { text: "inside now", tone: "accent", icon: "ph-fill ph-door-open" },
  cleared: { text: "cleared", tone: "ok", icon: "ph-fill ph-check-circle" },
  wiped: { text: "wiped", tone: "bad", icon: "ph-fill ph-x-circle" },
};

export function runState(r) {
  const key = r.state === "inside" ? "inside" : r.outcome || r.status || r.state || "";
  return STATE[key] || { text: String(key || "unknown").replace(/_/g, " "), tone: "warn", icon: "ph ph-warning-circle" };
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

export function bossText(r) {
  const total = Number(r.bosses_total) || 0;
  return total ? (Number(r.bosses_done) || 0) + " of " + total + " bosses down" : "bosses not measured";
}

export function seatNames(r) { return (r.members || []).map((m) => m.name).join(", "); }

export function inside(r) {
  const s = Number(r.seconds_inside);
  return s ? duration(s) + " inside" : "";
}

export function runHref(r) { return "#/runs/" + encodeURIComponent(r.id); }

export function allRuns(gr) {
  const d = gr && gr.data;
  if (!d) return [];
  return (d.active || []).concat(d.recent || []);
}

export function findRun(id) {
  return allRuns(peek("/api/guildruns")).find((r) => String(r.id) === String(id)) || null;
}

// Why the run went where it went: the coordinator's first lines.
export function chose(r) {
  return (r.lines || []).filter((l) => /^(dungeon|group):/.test(l)).join(". ");
}

export function cause(r) {
  const c = r.cause || r.why || "";
  return c.replace(/^Cause: /, "");
}

export function runCard(r, opts) {
  const o = opts || {};
  const when = r.state === "inside" ? "" : " | " + since(utc(r.ended_at) || utc(r.created_at));
  const meta = [bossText(r), seatNames(r), o.done ? "" : inside(r)].filter(Boolean).join(" | ");
  return html`<a class="card g-run-card" href="${runHref(r)}" data-run="${r.id}">
<div class="g-run-top"><span class="g-run-name">${r.place || "A dungeon"} <span class="muted">#${r.id}${when}</span></span>${stateTag(r)}</div>
${o.done ? "" : pips(r)}
${o.done && cause(r) ? html`<span class="g-run-cause">${cause(r)}</span>` : ""}
<span class="g-run-meta">${meta}</span>
${!o.done && chose(r) ? html`<span class="g-run-chose">${chose(r)}</span>` : ""}
</a>`;
}

export function seatRows(r) {
  return (r.members || []).map((m) => html`<a class="g-seat-row" href="${memberHref(m.name)}"><span class="g-seat-name" style="color:${classVar(m.class)}">${m.name}</span><span class="muted">L${m.level} ${titleCase(m.class)} | ${m.seat || "seat not measured"}</span></a>`);
}

// The steps a guild run can show without a per-event record: when it formed,
// the coordinator's lines, and how it came back.
export function steps(r) {
  const out = [];
  const formed = utc(r.created_at);
  if (formed) out.push({ t: formed, text: "Formed: " + plural((r.members || []).length, "seat") + " filled." });
  (r.lines || []).forEach((l) => out.push({ t: null, text: l }));
  const ended = utc(r.ended_at);
  if (ended) out.push({ t: ended, text: "Came back: " + (r.story || cause(r) || runState(r).text) });
  return out;
}

export function clock(ts) {
  if (!ts) return "";
  return new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
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
<span class="g-run-meta">${[bossText(r), seatNames(r), inside(r)].filter(Boolean).join(" | ")}</span>
<div class="g-steps">${stepRows(steps(r))}</div>
<div class="g-sheet-actions"><a class="btn btn-secondary" href="${runHref(r)}" data-sheet="close">Full page</a><button type="button" class="btn btn-primary" data-sheet="close">Close</button></div>
</div>`.s;
  const onKey = (e) => { if (e.key === "Escape") closeSheet(); };
  scrim.addEventListener("click", (e) => {
    if (e.target === scrim || e.target.closest('[data-sheet="close"]')) closeSheet();
  });
  document.addEventListener("keydown", onKey);
  document.body.appendChild(scrim);
  open = { scrim, back, onKey };
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
