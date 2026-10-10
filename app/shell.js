// The frame around every view: the sidebar (760px and wider), the phone
// header and bottom tab bar, the data-age readout, badges and the theme
// button. Drawn once; `update` moves the current item, badges and age.

import { html, raw, ago } from "./ui.js";
import { families, guilds } from "./families.js";

const NAV = [
  { key: "now", label: "Now", icon: "pulse", href: "#/now" },
  { key: "guilds", label: "Guilds", icon: "users-three", href: "#/guilds" },
  { key: "members", label: "Members", icon: "user-list", href: "#/members" },
  { key: "raid", label: "Raid", icon: "sword", href: "#/raid/mc" },
  { key: "economy", label: "Economy", icon: "coins", href: "#/economy" },
];

// The guilds' links (the Guilds and Raid sub-items) and the families' ones are
// the realm's own families and guilds (families.js), so they are drawn when
// the nav is.
const familyLinks = () => families().map((f) => [f.key + " family", "#/now/family/" + f.slug]);
const guildLinks = (prefix) => guilds().map((g) => [g.name, prefix + g.slug]);

const SUBS = {
  get now() { return [["Now", "#/now"], ...familyLinks(), ["World map", "#/now/map"], ["Server", "#/now/server"]]; },
  get guilds() { return guildLinks("#/guilds/"); },
  members: [["Roster", "#/members"], ["Gear", "#/members/gear"]],
  get raid() { return guildLinks("#/raid/mc/"); },
  economy: [["Bags and gold", "#/economy"], ["Auction house", "#/economy/auction"], ["Trades", "#/economy/trades"], ["Skill levels", "#/economy/professions"], ["Guild bank", "#/economy/bank"]],
};

// Badges set by sections: {members: {n, tone, href}, guilds: {n, tone}}.
const badges = {};
let realmTag = "";
let operatorOn = false;

export function setBadge(section, badge) { badges[section] = badge || null; }
export function setRealmTag(tag) { realmTag = tag || ""; }
export function setOperator(on) { operatorOn = !!on; }

function hrefFor(n) {
  const b = badges[n.key];
  return b && b.href ? b.href : n.href;
}

function sideNav(section, hash) {
  return NAV.map((n) => {
    const cur = n.key === section;
    const b = badges[n.key];
    const icon = "ph" + (cur ? "-fill" : "") + " ph-" + n.icon;
    const subs = cur ? (SUBS[n.key] || []).map(([label, href]) => {
      const on = hash === href || hash.startsWith(href + "/") || hash.startsWith(href + "?");
      return html`<a class="subnav" href="${href}"${on ? raw(' aria-current="page"') : ""}>${label}</a>`;
    }) : "";
    return html`<a class="navlink" href="${hrefFor(n)}"${cur ? raw(' aria-current="page"') : ""}><i class="${icon}" aria-hidden="true"></i><span class="label">${n.label}</span>${b && b.n ? html`<span class="badge badge-${b.tone || "accent"}" aria-label="${b.label || ""}">${b.n}</span>` : ""}</a>${subs}`;
  });
}

function tabBar(section) {
  return NAV.map((n) => {
    const cur = n.key === section;
    const b = badges[n.key];
    const icon = "ph" + (cur ? "-fill" : "") + " ph-" + n.icon;
    return html`<a class="tab" href="${hrefFor(n)}"${cur ? raw(' aria-current="page"') : ""}><i class="${icon}" aria-hidden="true"></i>${n.label}${b && b.n ? html`<span class="dot dot-${b.tone || "accent"}" aria-label="${b.label || ""}">${b.n > 99 ? "99+" : b.n}</span>` : ""}</a>`;
  });
}

export function mount(root) {
  root.innerHTML = html`
<aside class="sidebar" aria-label="Overseer">
  <a class="brand" href="#/now"><span class="brand-name">Overseer</span><span class="tag tag-neutral" data-slot="realm"></span></a>
  <button type="button" class="search-btn" data-action="search"><i class="ph ph-magnifying-glass" aria-hidden="true"></i><span style="flex:1">Search</span><span class="kbd" aria-hidden="true">/</span></button>
  <nav aria-label="Sections" data-slot="sidenav"></nav>
  <div class="sidebar-foot">
    <div class="age" data-slot="age"></div>
    <a class="op-link" href="#/operator" data-slot="op"></a>
    <button type="button" class="btn btn-secondary theme-btn" data-action="theme"></button>
  </div>
</aside>
<div class="column">
  <header class="topbar">
    <span class="brand-name">Overseer</span><span class="tag tag-neutral" data-slot="realm"></span>
    <span class="age" data-slot="age-short"></span>
    <button type="button" class="btn btn-icon" aria-label="Search" data-action="search"><i class="ph ph-magnifying-glass" aria-hidden="true"></i></button>
    <button type="button" class="btn btn-icon" data-action="theme" data-slot="theme-icon"></button>
  </header>
  <main class="main" id="main" tabindex="-1"></main>
  <nav data-slot="thumb" aria-label="Switch guild" hidden></nav>
  <span class="sr-only" role="status" data-slot="age-state"></span>
  <nav class="tabbar" aria-label="Sections" data-slot="tabbar"></nav>
</div>`.s;
}

export function update(root, opts) {
  const { section, hash, health, theme } = opts;
  root.querySelector('[data-slot="sidenav"]').innerHTML = sideNav(section, hash).map(String).join("");
  root.querySelector('[data-slot="tabbar"]').innerHTML = tabBar(section).map(String).join("");
  root.querySelectorAll('[data-slot="realm"]').forEach((el) => { el.textContent = realmTag; el.hidden = !realmTag; });
  updateAge(root, health);
  const themeLabel = theme === "light" ? "Dark theme" : "Light theme";
  const themeIcon = theme === "light" ? "ph ph-moon" : "ph ph-sun";
  root.querySelectorAll('[data-action="theme"]').forEach((b) => {
    b.setAttribute("aria-label", themeLabel);
    b.innerHTML = b.classList.contains("btn-icon")
      ? html`<i class="${themeIcon}" aria-hidden="true"></i>`.s
      : html`<i class="${themeIcon}" aria-hidden="true"></i>${themeLabel}`.s;
  });
  const op = root.querySelector('[data-slot="op"]');
  op.innerHTML = html`<i class="ph ph-lock-simple${operatorOn ? "-open" : ""}" aria-hidden="true"></i>Operator actions: ${operatorOn ? "on" : "off"}`.s;
}

export function updateAge(root, health) {
  const h = health || { state: "loading", at: 0 };
  const secs = h.at ? (Date.now() - h.at) / 1000 : null;
  const long = h.state === "loading" ? "Reading the world" : h.state === "error" ? "The world did not answer" : "Data " + ago(secs);
  const short = h.state === "loading" ? "reading" : h.state === "error" ? "no answer" : ago(secs);
  const dot = html`<span class="age-dot" data-state="${h.state}" aria-hidden="true"></span>`;
  const a = root.querySelector('[data-slot="age"]');
  const b = root.querySelector('[data-slot="age-short"]');
  if (a) a.innerHTML = html`${dot}<span>${long}</span>`.s;
  if (b) b.innerHTML = html`${dot}<span>${short}</span>`.s;
  sayAgeState(root, h.state);
}

// The floating guild switch on phone (Guilds and Raid).
export function setThumb(root, opts) {
  const slot = root.querySelector('[data-slot="thumb"]');
  slot.hidden = !opts;
  if (!opts) { slot.innerHTML = ""; return; }
  slot.innerHTML = html`<div class="thumb"><div class="seg" role="group" aria-label="${opts.label}">${opts.items.map((o) => html`<a href="${o.href}"${o.current ? raw(' aria-current="page"') : ""}>${o.label}</a>`)}</div></div>`.s;
}

export { NAV, SUBS };

// ---- the ticking age -----------------------------------------------------------
// The age is redrawn every second (main.js), which is too often for a live
// region: a screen reader would read "Data 4s ago" without end. So the
// counting text is silent, and one polite region says only when the state of
// the data changes.
export const AGE_TICK_MS = 1000;
const AGE_WORDS = {
  loading: "Reading the world",
  fresh: "Data is current",
  stale: "Data is stale: the world stopped answering",
  error: "The world did not answer",
};
let saidState = "";

function sayAgeState(root, state) {
  if (state === saidState) return;
  const el = root.querySelector('[data-slot="age-state"]');
  if (!el) return;
  saidState = state;
  el.textContent = AGE_WORDS[state] || "";
}
