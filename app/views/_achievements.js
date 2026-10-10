// The announcer's achievements, drawn three ways from /api/v2/achievements:
// a Chronicle row (views/guild.js), the badges on a member's profile
// (views/member.js) and a brief toast on Now (views/now.js). Styles are in
// views/achievements.css. Read-only, and flavor only.

import { html, member, memberHref, plural, pendingRead, state } from "../ui.js";
import { since, fromClock } from "../models/time.js";
import { tier, items, fresh, headline } from "../models/achievements.js";
import { guildSlug } from "../families.js";

export const CSS = "views/achievements.css";
const BADGES_SHOWN = 6;
const TOAST_MS = 9000;
const SEEN_KEY = "overseer.achievements.seen";
const SEEN_MAX = 400;

export function medal(a, size) {
  const t = tier(a.tier);
  return html`<span class="ach-medal${size === "lg" ? " ach-medal-lg" : ""}" data-tier="${t.key}" aria-hidden="true"><i class="${t.icon}"></i></span>`;
}

function tierTag(a) {
  const t = tier(a.tier);
  return html`<span class="ach-tier" data-tier="${t.key}">${t.label}</span>`;
}

// Who earned it: the member, or the guild members who were there for a
// guild's first ("Durg, Dunga and 3 more").
function party(who) {
  const names = who || [];
  if (names.length <= 3) return names.join(", ").replace(/, ([^,]*)$/, " and $1");
  return names.slice(0, 2).join(", ") + " and " + (names.length - 2) + " more";
}

function earner(a, cls) {
  if (a.member) return member({ name: a.member, cls: cls && cls(a.member) });
  return html`<span class="ach-guild">${party(a.who) || a.guild}</span>`;
}

// ---- the Chronicle --------------------------------------------------------------

// One achievement in the guild feed, in the row shape views/guild.js draws.
export function feedRow(a, opts) {
  const o = opts || {};
  return html`<div class="g-row g-feed ach-row">${medal(a)}<span class="g-grow ach-body"><span class="ach-head"><b class="ach-title">${a.title}</b>${tierTag(a)}<span class="ach-who">${earner(a, o.cls)}</span></span><span class="ach-line">${a.line}</span></span>${o.fresh ? html`<span class="tag tag-accent">New</span>` : ""}<span class="muted g-when">${since(a.earned_at)}</span></div>`;
}

// ---- the profile ------------------------------------------------------------------

function badge(a) {
  const firstOf = !a.member && a.guild ? html` <span class="dim">for ${a.guild}</span>` : "";
  return html`<li class="ach-badge" data-tier="${tier(a.tier).key}">${medal(a, "lg")}<span class="ach-body"><span class="ach-head"><b class="ach-title">${a.title}</b>${tierTag(a)}</span><span class="ach-line">${a.line}</span><span class="ach-meta">${since(a.earned_at)}${firstOf}</span></span></li>`;
}

function tally(d) {
  const t = d.tiers || {};
  const parts = ["gold", "silver", "bronze", "dubious"].filter((k) => t[k]).map((k) => t[k] + " " + tier(k).label.toLowerCase());
  return d.count + " of " + d.of + (parts.length ? " | " + parts.join(", ") : "");
}

export function badgesCard(read, name) {
  const wait = pendingRead(read, 1);
  const head = (aside) => html`<div class="row mb-between"><span class="dim mb-s">Achievements</span>${aside ? html`<span class="muted mb-s">${aside}</span>` : ""}</div>`;
  if (wait) return html`<div class="card ach-card">${head("")}${wait}</div>`;
  const d = read.data;
  const list = items(read);
  const first = list.slice(0, BADGES_SHOWN), rest = list.slice(BADGES_SHOWN);
  const body = list.length
    ? html`<ul class="ach-badges">${first.map(badge)}</ul>${rest.length ? html`<details class="fold ach-more"><summary>${plural(rest.length, "more achievement")}</summary><ul class="ach-badges">${rest.map(badge)}</ul></details>` : ""}`
    : state("empty", "Nothing earned yet", name + " has done nothing the announcer found worth a remark. Give it time.");
  return html`<section class="card ach-card" aria-label="Achievements">${head(tally(d))}${body}<details class="fold"><summary>How this is worked out</summary><p class="dim mb-s">${d.basis}</p></details></section>`;
}

// ---- the toast on Now --------------------------------------------------------------

function readSeen() {
  try { return new Set(JSON.parse(window.localStorage.getItem(SEEN_KEY) || "[]")); } catch (e) { return new Set(); }
}

function saveSeen(seen) {
  try { window.localStorage.setItem(SEEN_KEY, JSON.stringify([...seen].slice(-SEEN_MAX))); } catch (e) { /* storage off */ }
}

let toastEl = null;
let toastTimer = 0;

function closeToast() {
  window.clearTimeout(toastTimer);
  if (!toastEl) return;
  const el = toastEl;
  toastEl = null;
  el.classList.add("is-leaving");
  window.setTimeout(() => el.remove(), 180);
}

function arm() {
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(closeToast, TOAST_MS);
}

function toastHtml(a, more) {
  const href = a.member ? memberHref(a.member) : "#/guilds/" + (guildSlug(a.guild) || "") + "/chronicle?kind=achievements";
  const who = a.member || a.guild;
  const moreHref = "#/guilds/" + (guildSlug(a.guild) || "") + "/chronicle?kind=achievements";
  return html`<div class="ach-toast-card" data-tier="${tier(a.tier).key}">${medal(a, "lg")}<a class="ach-toast-main" href="${href}"><span class="ach-toast-who">${who} earned <b>${a.title}</b></span><span class="ach-line">${a.line}</span></a>${more ? html`<a class="ach-toast-more" href="${moreHref}">and ${more} more</a>` : ""}<button type="button" class="ach-toast-x" aria-label="Dismiss"><i class="ph ph-x" aria-hidden="true"></i></button></div>`;
}

// Show the newest achievement earned since the last visit that this device
// has not shown yet, once. Everything new is marked shown, so a poll that
// redraws Now never shows the same one twice.
export function announce(read, previousVisit) {
  if (typeof document === "undefined" || toastEl) return;
  const seen = readSeen();
  const news = fresh(items(read), fromClock(previousVisit), seen);
  if (!news.length) return;
  news.forEach((a) => seen.add(a.id));
  saveSeen(seen);
  toastEl = document.createElement("div");
  toastEl.className = "ach-toast";
  toastEl.setAttribute("role", "status");
  // The feed is capped, so past the cap the count is a floor: "119+ more".
  const capped = read.data && read.data.count > items(read).length;
  const more = news.length - 1 ? String(news.length - 1) + (capped ? "+" : "") : "";
  toastEl.innerHTML = toastHtml(headline(news), more).s;
  toastEl.querySelector(".ach-toast-x").addEventListener("click", closeToast);
  toastEl.querySelectorAll("a").forEach((l) => l.addEventListener("click", closeToast));
  // Paused while a pointer or the focus is on it, so it can be read.
  ["mouseenter", "focusin"].forEach((ev) => toastEl.addEventListener(ev, () => window.clearTimeout(toastTimer)));
  ["mouseleave", "focusout"].forEach((ev) => toastEl.addEventListener(ev, arm));
  document.body.appendChild(toastEl);
  arm();
}

