// Global search: "/" anywhere or the search button opens it, Esc closes it,
// arrows move through the hits, Enter opens one. Providers answer a query
// with groups of hits ({label, rows: [{name, sub, href, color, item}]}).
// The shell ships the pages provider; /api/v2/search adds members, items,
// quests, dungeons and runs.

import { html, raw } from "./ui.js";

const providers = [];
let scrim = null;
let input = null;
let list = null;
let seq = 0;
let lastFocus = null;

export function addProvider(fn) { providers.push(fn); }

const PAGES = [
  ["Now", "#/now", "Realm, families, live streams"],
  ["Grug family", "#/now/family/grug", "Family board"],
  ["Zug family", "#/now/family/zug", "Family board"],
  ["World map", "#/now/map", "Where everyone is"],
  ["Server", "#/now/server", "Server tiers"],
  ["Cave", "#/guilds/cave", "Guild progress"],
  ["Bonkers", "#/guilds/bonkers", "Guild progress"],
  ["Cave runs", "#/guilds/cave/runs", "Dungeon runs"],
  ["Bonkers runs", "#/guilds/bonkers/runs", "Dungeon runs"],
  ["Cave chronicle", "#/guilds/cave/chronicle", "Feed, loot, council, guild chat"],
  ["Bonkers chronicle", "#/guilds/bonkers/chronicle", "Feed, loot, council, guild chat"],
  ["Roster", "#/members", "Every member"],
  ["Stuck members", "#/members?stuck=1", "Who is stuck and why"],
  ["Gear", "#/members/gear", "Paperdolls"],
  ["Upgrades", "#/members/gear/upgrades", "What to wear next"],
  ["Gear table", "#/members/gear/table", "Every member's gear"],
  ["Molten Core, Cave", "#/raid/mc/cave", "Raid readiness"],
  ["Molten Core, Bonkers", "#/raid/mc/bonkers", "Raid readiness"],
  ["Bags and gold", "#/economy", "Economy"],
  ["Auction house", "#/economy/auction", "Our listings"],
  ["Trades", "#/economy/trades", "Professions and recipes"],
  ["Skill levels", "#/economy/professions", "Profession levels"],
  ["Guild bank", "#/economy/bank", "Tabs and items"],
  ["Operator actions", "#/operator", "Locked unless turned on"],
];

addProvider((q) => {
  const rows = PAGES.filter(([name, , sub]) => (name + " " + sub).toLowerCase().includes(q))
    .slice(0, 6).map(([name, href, sub]) => ({ name, href, sub }));
  return rows.length ? [{ label: "Pages", rows }] : [];
});

function ensure() {
  if (scrim) return;
  scrim = document.createElement("div");
  scrim.className = "scrim search-scrim";
  scrim.hidden = true;
  scrim.innerHTML = html`<div class="search-box" role="dialog" aria-modal="true" aria-label="Search">
<div class="search-row"><i class="ph ph-magnifying-glass" aria-hidden="true"></i><input type="search" placeholder="Character, item, quest or dungeon" aria-label="Search" aria-controls="search-results" autocomplete="off" enterkeyhint="go"><button type="button" class="btn btn-ghost" data-close>Close</button></div>
<div class="search-results" id="search-results" role="listbox" aria-label="Results"></div></div>`.s;
  document.body.appendChild(scrim);
  input = scrim.querySelector("input");
  list = scrim.querySelector(".search-results");
  scrim.addEventListener("click", (e) => {
    if (e.target === scrim || e.target.closest("[data-close]")) close();
    else if (e.target.closest(".search-hit")) close(true);
  });
  input.addEventListener("input", () => run(input.value));
  scrim.addEventListener("keydown", onKey);
}

function hits() { return Array.from(list.querySelectorAll(".search-hit")); }

function onKey(e) {
  const all = hits();
  const i = all.findIndex((a) => a.getAttribute("aria-selected") === "true");
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    if (!all.length) return;
    const j = e.key === "ArrowDown" ? Math.min(all.length - 1, i + 1) : Math.max(0, i - 1);
    all.forEach((a, k) => a.setAttribute("aria-selected", k === j ? "true" : "false"));
    all[j].scrollIntoView({ block: "nearest" });
  } else if (e.key === "Enter") {
    const pick = all[i >= 0 ? i : 0];
    if (pick) { e.preventDefault(); location.hash = pick.getAttribute("href"); close(true); }
  } else if (e.key === "Escape") {
    e.preventDefault(); close();
  }
}

async function run(text) {
  const q = text.trim().toLowerCase();
  const mine = ++seq;
  if (!q) {
    list.innerHTML = html`<div class="search-note">Type a name, an item, a quest or a dungeon. Press / anywhere to open, Esc to close.</div>`.s;
    return;
  }
  const answers = await Promise.all(providers.map((p) => Promise.resolve().then(() => p(q)).catch(() => [])));
  if (mine !== seq) return;
  const groups = answers.flat().filter((g) => g && g.rows && g.rows.length);
  if (!groups.length) {
    list.innerHTML = html`<div class="search-note">Nothing matches "${text.trim()}".</div>`.s;
    return;
  }
  list.innerHTML = groups.map((g) => html`<div class="search-group">${g.label}</div>${g.rows.map((r, k) => html`<a class="search-hit" role="option" aria-selected="false" href="${r.href}"${r.item ? raw(' data-item="' + Number(r.item) + '"') : ""}><span${r.color ? html` style="color:${r.color}"` : ""}>${r.name}</span><span class="sub">${r.sub || ""}</span></a>`)}`).join("");
  const first = hits()[0];
  if (first) first.setAttribute("aria-selected", "true");
}

export function open() {
  ensure();
  lastFocus = document.activeElement;
  scrim.hidden = false;
  input.value = "";
  run("");
  window.setTimeout(() => input.focus(), 0);
}

export function close(navigated) {
  if (!scrim || scrim.hidden) return;
  scrim.hidden = true;
  if (!navigated && lastFocus && document.contains(lastFocus)) lastFocus.focus({ preventScroll: true });
}

export function isOpen() { return !!scrim && !scrim.hidden; }
