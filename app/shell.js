// The frame around every view: the sidebar (760px and wider), the phone
// header and bottom tab bar, the data-age readout, badges and the theme
// button. Drawn once; `update` moves the current item, badges and age.

import { html, raw, ago } from "./ui.js";

const NAV = [
  { key: "now", label: "Now", icon: "pulse", href: "#/now" },
  { key: "guilds", label: "Guilds", icon: "users-three", href: "#/guilds/cave" },
  { key: "members", label: "Members", icon: "user-list", href: "#/members" },
  { key: "raid", label: "Raid", icon: "sword", href: "#/raid/mc/cave" },
  { key: "economy", label: "Economy", icon: "coins", href: "#/economy" },
];

const SUBS = {
  now: [["Now", "#/now"], ["Grug family", "#/now/family/grug"], ["Zug family", "#/now/family/zug"], ["World map", "#/now/map"], ["Server", "#/now/server"]],
  guilds: [["Cave", "#/guilds/cave"], ["Bonkers", "#/guilds/bonkers"]],
  members: [["Roster", "#/members"], ["Gear", "#/members/gear"]],
  raid: [["Cave", "#/raid/mc/cave"], ["Bonkers", "#/raid/mc/bonkers"]],
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
  if (a) a.innerHTML = html`${dot}<span role="status">${long}</span>`.s;
  if (b) b.innerHTML = html`${dot}<span>${short}</span>`.s;
}

// The floating Cave/Bonkers switch on phone (Guilds and Raid).
export function setThumb(root, opts) {
  const slot = root.querySelector('[data-slot="thumb"]');
  slot.hidden = !opts;
  if (!opts) { slot.innerHTML = ""; return; }
  slot.innerHTML = html`<div class="thumb"><div class="seg" role="group" aria-label="${opts.label}">${opts.items.map((o) => html`<a href="${o.href}"${o.current ? raw(' aria-current="page"') : ""}>${o.label}</a>`)}</div></div>`.s;
}

export { NAV, SUBS };
