// Economy: bags and gold, the auction house, trades, skill levels and the
// guild bank. Every number is the server's: /api/wealth for purses, bags and
// auctions, /api/trades for professions (and ?skill= for one trade's crafts),
// /api/client/guildbank for the vaults. Which family, character, trade and
// guild is shown lives in the URL query, so every state can be linked.

import { html, raw, isHttps, pageHead, sectionHead, tabs, item, notMeasured, gold, plural, duration, pendingRead, state, classVar, memberHref, member } from "../ui.js";
import { build } from "../router.js";
import { familyKeys } from "../families.js";
import { since, fromClock } from "../models/time.js";

const TABS = [
  ["gold", "Bags and gold"],
  ["auction", "Auction house"],
  ["trades", "Trades"],
  ["professions", "Skill levels"],
  ["bank", "Guild bank"],
];
const SUMMARY = {
  trades: "Who holds which trade, how much of it they know, and what is still missing.",
  professions: "Every crafter in the two guilds, highest skill first.",
  bank: "Each guild's vault: its tabs, how full they are, and what is in them.",
};
const WEALTH = "/api/wealth";
const TRADES = "/api/trades";
const ROWS_SHOWN = 40;
const DUNGEONS_SHOWN = 12;
// <details> the reader opened or shut, kept across redraws: key -> open.
const folds = new Map();

const cap = (s) => String(s || "").charAt(0).toUpperCase() + String(s || "").slice(1);
// The server writes clauses; the page shows them as sentences.
const sentence = (t) => { const x = cap(String(t || "").trim()); return !x || /[.!?]$/.test(x) ? x : x + "."; };
const pct = (n) => Math.max(0, Math.min(100, Math.round(Number(n) || 0)));
const ecoHref = (tab, query) => build(tab === "gold" ? ["economy"] : ["economy", tab], query || {});
const skillPath = (skill, family) => TRADES + "?skill=" + encodeURIComponent(skill) + "&family=" + encodeURIComponent(family);
const bankPath = (name) => "/api/client/guildbank?name=" + encodeURIComponent(name);

function money(m) {
  return m && m.total !== undefined && m.total !== null ? html`<span class="eco-gold">${gold(m.total)}</span>` : notMeasured();
}

function bar(percent, tone) {
  return html`<span class="eco-bar${tone ? " " + tone : ""}" aria-hidden="true"><span style="width:${pct(percent)}%"></span></span>`;
}

function chipLink(label, href, on) {
  return html`<a class="chip eco-pick" href="${href}"${on ? raw(' aria-current="true"') : ""}>${label}</a>`;
}

function fold(key, summary, body, openByDefault) {
  const open = folds.has(key) ? folds.get(key) : !!openByDefault;
  return html`<details class="eco-fold" data-fold="${key}"${open ? raw(" open") : ""}><summary>${summary}</summary>${body}</details>`;
}

function itemOf(it) {
  return item({ entry: it.entry, name: it.name, quality: it.quality, icon: it.icon });
}

// ---- bags and gold ------------------------------------------------------------

function greys(m) {
  let copper = 0;
  (m.containers || []).forEach((c) => (c.items || []).forEach((it) => { if (it.quality === 0) copper += Number(it.value_copper) || 0; }));
  return copper;
}

function bagsWorn(m) {
  const counts = new Map();
  (m.containers || []).filter((c) => c.key !== "backpack").forEach((c) => counts.set(c.name, (counts.get(c.name) || 0) + 1));
  if (!counts.size) return "no bags worn";
  return Array.from(counts, ([name, n]) => (n > 1 ? n + " " + name : name)).join(", ");
}

function bagCard(m) {
  if (!m.present) {
    return html`<div class="card eco-bag"><span class="eco-name" style="color:${classVar(m.class)}">${m.name}</span><span class="muted">${m.absent_note || "Not read this time."}</span></div>`;
  }
  const r = m.room || {};
  const tone = r.tone ? "warn" : "";
  const grey = greys(m);
  return html`<a class="card eco-bag" href="${memberHref(m.name, "bags")}">
<div class="eco-line"><span class="eco-name" style="color:${classVar(m.class)}">${m.name}</span>${money(m.money)}</div>
<div class="eco-fill">${bar(r.percent, tone)}<span class="${tone}">${pct(r.percent)}% full</span></div>
<span class="eco-meta">${m.capacity ? m.capacity.used + " of " + m.capacity.slots + " slots" : notMeasured()} | ${grey ? "greys worth " + gold(grey) : "no greys"} | ${bagsWorn(m)}</span></a>`;
}

function vendorRoute(members) {
  const rows = [];
  members.forEach((m) => {
    const pile = ((m.fates && m.fates.piles) || []).find((p) => p.key === "junk");
    if (pile) rows.push({ m, pile });
  });
  const body = rows.length
    ? rows.map(({ m, pile }) => html`<div class="eco-route"><span>${member({ name: m.name, cls: m.class })}</span><span>${pile.count} of junk</span><span class="muted">${sentence(pile.route)}${pile.blocker ? html` <span class="warn">${sentence("held: " + pile.blocker)}</span>` : ""}</span></div>`)
    : html`<div class="eco-route-empty muted">Nobody is carrying junk for a vendor right now.</div>`;
  return html`<div class="card eco-list"><div class="eco-list-title">Vendor route</div>${body}<div class="eco-note">Which town the next vendor trip stops in is not measured.</div></div>`;
}

function sideTotal(p, side) {
  let copper = 0;
  let seen = 0;
  p.members.filter((m) => side.names.includes(m.name) && m.money).forEach((m) => { copper += m.money.total; seen += 1; });
  return { label: side.guild + ", " + side.family + "'s family", value: seen ? html`<span class="eco-gold">${gold(copper)}</span>` : notMeasured(), sub: plural(seen, "purse") };
}

function totals(p) {
  const fam = p.family || {};
  const cards = (p.sides || []).map((s) => sideTotal(p, s));
  cards.push({ label: "Both families", value: money(fam.money), sub: "across " + plural(fam.present || 0, "purse") });
  cards.push({ label: "Carried goods", value: money(fam.vendor), sub: "what a vendor would pay" });
  return html`<div class="eco-totals">${cards.map((c) => html`<div class="card"><span class="eco-k">${c.label}</span><span class="eco-v">${c.value}</span><span class="eco-meta">${c.sub}</span></div>`)}</div>`;
}

function richList(members) {
  const withMoney = members.filter((m) => m.money);
  const top = Math.max(1, ...withMoney.map((m) => m.money.total));
  const rows = withMoney.slice().sort((a, b) => b.money.total - a.money.total);
  return html`<div class="card eco-list"><div class="eco-list-title">Purses, richest first</div>${rows.map((m) => html`<a class="eco-rich" href="${memberHref(m.name)}"><span><span class="eco-name" style="color:${classVar(m.class)}">${m.name}</span> <span class="muted">${m.guild || ""}</span></span>${bar((100 * m.money.total) / top, "gold")}<span class="num">${gold(m.money.total)}</span></a>`)}</div>`;
}

function goldTab(p) {
  const order = [];
  (p.sides || []).forEach((s) => s.names.forEach((n) => order.push(n)));
  const byName = new Map(p.members.map((m) => [m.name, m]));
  const members = order.map((n) => byName.get(n)).filter(Boolean).concat(p.members.filter((m) => !order.includes(m.name)));
  return html`<div class="eco-bags">${members.map(bagCard)}</div>${vendorRoute(members)}${totals(p)}${richList(members)}
<p class="eco-note">${p.saved_note || ""}</p>`;
}

// ---- auction house ------------------------------------------------------------

function left(at) {
  if (!at) return notMeasured();
  const secs = Number(at) - Date.now() / 1000;
  return secs <= 0 ? "ended" : duration(secs);
}

function bidOf(r) { return r.has_bid ? gold(r.bid.total) : html`${gold(r.start.total)} <span class="muted">start</span>`; }
function buyoutOf(r) { return r.buyout_label ? gold(r.buyout.total) : html`<span class="muted">none</span>`; }

function ticketSentence(s) {
  if (!s) return "";
  const t = s.ticket || {};
  if (!isHttps(t.url)) return html`${s.before}${t.label}${s.after}`;
  return html`${s.before}<a href="${t.url}" target="_blank" rel="noopener">${t.label}</a>${s.after}`;
}

function auctionTab(a) {
  const rows = a.listings || [];
  const foot = html`<p class="eco-note">Listings by family characters only. Market prices from the auction bot are not shown as ours.${a.tracked ? "" : " " + a.caveat}</p>`;
  if (!rows.length) {
    const e = a.empty || {};
    const lead = a.any ? "Nothing listed by the family right now." : e.lead || "Nothing listed.";
    return html`${state("empty", lead, html`${a.any ? "" : e.body || ""} ${ticketSentence(e.why)}`)}${foot}`;
  }
  const seller = (r) => (r.owner ? html`<a href="${memberHref(r.owner)}">${r.owner}</a>` : notMeasured("unknown"));
  return html`<div class="card eco-auc-table"><table class="table"><thead><tr><th>Item</th><th>Qty</th><th>Seller</th><th>Bid</th><th>Buyout</th><th>Left</th></tr></thead><tbody>
${rows.map((r) => html`<tr><td>${itemOf(r.item)}</td><td class="num">${r.item.count || 1}</td><td>${seller(r)}</td><td>${bidOf(r)}</td><td>${buyoutOf(r)}</td><td class="muted">${left(r.expires_at)}</td></tr>`)}</tbody></table></div>
<div class="eco-auc-cards">${rows.map((r) => html`<div class="card"><div class="eco-line">${itemOf(r.item)}<span class="muted">x${r.item.count || 1}</span><span class="eco-meta">${left(r.expires_at)}</span></div><span class="eco-meta">${r.owner || "seller unknown"} | bid ${bidOf(r)} | buyout ${buyoutOf(r)}</span></div>`)}</div>${foot}`;
}

// ---- trades -----------------------------------------------------------------

function chosenFamily(p, q) {
  const fams = p.families && p.families.length ? p.families : [p];
  return fams.find((f) => String(f.family).toLowerCase() === (q.family || "").toLowerCase()) || fams[0];
}

function craftRow(c, groupState) {
  const who = groupState === "k" ? ["Knows", c.known_by, c.known_more] : ["Can learn", c.can_learn, c.can_learn_more];
  const names = who[1] || [];
  return html`<div class="eco-craft"><span>${c.name} <span class="muted">asks ${c.rank}</span></span>${names.length ? html`<span class="eco-who">${who[0]}${names.map((n) => html`<a class="eco-namechip" href="${memberHref(n)}"><span>${n}</span></a>`)}${who[2] ? html`<span>+${who[2]}</span>` : ""}</span>` : ""}</div>`;
}

function craftGroup(key, list, idx, g) {
  const color = g.state === "k" ? "ok" : g.state === "l" ? "accent" : "muted";
  const head = html`<span>${g.label}</span><span class="${color} num">${g.count}</span>`;
  if (!g.count) return html`<div class="eco-group-empty">${head}</div>`;
  const crafts = list.crafts.filter((c) => c.states.charAt(idx) === g.state);
  const shown = crafts.slice(0, ROWS_SHOWN).map((c) => craftRow(c, g.state));
  const rest = crafts.length > ROWS_SHOWN
    ? fold(key + "|more", html`${plural(crafts.length - ROWS_SHOWN, "more craft")}`, html`${crafts.slice(ROWS_SHOWN).map((c) => craftRow(c, g.state))}`)
    : "";
  return fold(key, head, html`<div class="eco-crafts">${shown}${rest}</div>`, g.state === "l");
}

function groupLinks(prof, hrefOpen) {
  const c = prof.counts || {};
  const rows = [["Known", c.known, "ok"], ["Ready to learn now", c.learnable, "accent"], ["Needs more skill", c.skill, "muted"]];
  return rows.map(([label, n, color]) => html`<a class="eco-group-link" href="${hrefOpen}"><span>${label}</span><span class="${color} num">${n === undefined ? notMeasured() : n}</span></a>`);
}

function profCard(fam, prof, ctx, get) {
  const q = ctx.query;
  const isOpen = !!q.family && String(q.open || "") === String(prof.skill);
  const read = isOpen ? get(skillPath(prof.skill, fam.family)) : null;
  const list = read && read.data && (read.data.views || []).length ? read.data : null;
  const at = list ? list.views.findIndex((v) => v.key === (q.who || "")) : -1;
  const idx = at < 0 ? 0 : at;
  const view = list ? list.views[idx] : null;
  const percent = view ? view.percent : prof.percent;
  const brief = view ? view.brief : prof.brief;
  const ready = view ? (view.counts || {}).l : (prof.counts || {}).learnable;
  const base = { family: fam.family.toLowerCase(), who: q.who || "" };
  const hrefOpen = ecoHref("trades", Object.assign({}, base, { open: prof.skill }));
  const hrefShut = ecoHref("trades", base);
  let body;
  if (!isOpen) body = html`<div class="eco-groups">${groupLinks(prof, hrefOpen)}</div>`;
  else if (!list) body = html`<div class="eco-groups">${pendingRead(read, 1) || state("unmeasured", "The crafts for this trade are not measured.")}</div>`;
  else body = html`<div class="eco-groups">${(view.groups || []).map((g) => craftGroup(fam.family + "|" + prof.skill + "|" + g.state, list, idx, g))}</div><span class="eco-meta">${list.reagents_line}</span>`;
  return html`<div class="card eco-prof${ready ? " ready" : ""}" id="trade-${prof.skill}">
<div class="eco-line"><span class="eco-trade">${cap(prof.name)}</span><span class="num${percent >= 75 ? " ok" : ""}">${percent}%</span></div>
<span class="eco-sub">${sentence(brief)}</span>${bar(percent, "accent")}${body}
${isOpen ? html`<a class="eco-shut" href="${hrefShut}">Hide the crafts</a>` : html`<a class="eco-shut" href="${hrefOpen}">Show the crafts</a>`}</div>`;
}

function hundred(fam, ctx, get) {
  const g = fam.goal;
  if (!g) return state("unmeasured", "The hundred per cent is not measured on this server.");
  const q = ctx.query;
  const who = (g.people || []).map((p) => chipLink(p.label, ecoHref("trades", { family: fam.family.toLowerCase(), who: p.key, open: q.open || "" }), (q.who || "") === p.key));
  return html`<section class="section">${sectionHead("01", "The hundred per cent")}
<p class="eco-sub">${sentence(g.empty_note || g.line)}</p>
<div class="eco-chips" role="group" aria-label="Whose crafts">${who}</div>
<div class="eco-profs">${(g.professions || []).map((prof) => profCard(fam, prof, ctx, get))}</div></section>`;
}

function branches(g) {
  const rows = (g && g.specs) || [];
  if (!rows.length) return html`<section class="section">${sectionHead("02", "Who takes which branch")}${state("empty", "No branch is planned for this family.")}</section>`;
  return html`<section class="section">${sectionHead("02", "Who takes which branch")}
<div class="card eco-list">${rows.map((s) => html`<div class="eco-pair"><span class="eco-trade-s">${s.label}<span class="muted">${s.profession}</span></span><div class="eco-pair-body">${s.holder ? html`<span>${member({ name: s.holder })} takes it.</span>` : ""}<span>${sentence(s.line)}</span>${s.why ? fold("spec|" + s.spec, "Why", html`<p class="eco-why">${s.why}</p>`) : ""}</div></div>`)}</div></section>`;
}

function ladder(g) {
  const rows = (g && g.hierarchy) || [];
  return html`<section class="section">${sectionHead("03", "The order of crafters")}
<p class="eco-sub muted">Who takes which specialization first: the family at the top, then the slots nobody fills.</p>
<div class="card eco-list">${rows.map((r) => html`<div class="eco-rung"><span class="muted num">${r.rank}</span><span class="eco-trade-s">${r.label}<span class="muted">${r.profession}</span></span><span>${r.holder ? member({ name: r.holder }) : html`<span class="muted">open slot</span>`}</span><span class="num">${plural(r.unlocks || 0, "craft")}</span></div>`)}</div>
${g ? fold("ladder|how", "How this is ordered, and what cannot be asked", html`<p class="eco-why">${sentence(g.order)}</p><p class="eco-why warn">${sentence(g.limit_line)}</p><p class="eco-why">${sentence(g.grant_line)}</p>`) : ""}</section>`;
}

function nobody(fam) {
  const gaps = fam.gaps || [];
  const lines = Array.from(new Set(gaps.map((x) => String(x.line || "").replace(/^[^:]+:\s*/, "")).filter(Boolean)));
  const body = gaps.length
    ? html`<div class="eco-chips">${gaps.map((x) => html`<span class="tag tag-warn eco-gap">${cap(x.name)}</span>`)}<span class="eco-sub muted">Nobody in the guild holds these, so nothing they make can come from inside it.</span></div>${lines.map((l) => html`<p class="eco-why">${sentence(l)}</p>`)}`
    : html`<p class="eco-sub">Every trade has somebody in the guild who holds it.</p>`;
  return html`<section class="section">${sectionHead("04", "What nobody holds")}${body}</section>`;
}

function missingRecipe(r) {
  const src = (r.sources || [])[0];
  return html`<div class="eco-recipe">${itemOf(r)}<span class="eco-meta">${sentence(r.reach_line)}${src ? " " + sentence(src.line) : ""}</span></div>`;
}

function crafterHierarchy(t) {
  const holders = (t.holders || []).slice().sort((a, b) => (b.value || 0) - (a.value || 0));
  if (!holders.length) return "";
  const assigned = new Set(t.assigned || []);
  const masters = holders.filter((h) => assigned.has(h.who));
  const others = holders.filter((h) => !assigned.has(h.who));
  const ordered = masters.concat(others);
  const chip = (h, isMaster) => html`<span class="eco-hier-chip">${member({ name: h.who })}${isMaster ? html` <span class="tag tag-accent">Master</span>` : ""}<span class="muted num">${h.value || 0}</span></span>`;
  return html`<div class="eco-hierarchy"><span class="eco-meta">New recipes go to:</span> ${ordered.map((h) => chip(h, assigned.has(h.who)))}<span class="eco-meta muted">- first copy to the master, duplicates fan out.</span></div>`;
}

function needs(fam) {
  const rows = (fam.trades || []).filter((t) => t.held);
  return html`<section class="section">${sectionHead("05", "What each trade still needs")}
<div class="card eco-list">${rows.map((t) => html`<div class="eco-pair"><span class="eco-trade-s">${cap(t.name)}</span><div class="eco-pair-body">${crafterHierarchy(t)}<span>${t.missing_count ? sentence(t.missing_head) : "Everything the recipe items list is known."}</span><span class="eco-meta">${sentence(t.trainer_line)}</span>${(t.missing || []).length ? fold("need|" + fam.family + "|" + t.skill, plural(t.missing.length, "recipe") + " to find", html`${t.missing.map(missingRecipe)}`) : ""}</div></div>`)}</div></section>`;
}

function dungeonCard(d) {
  return html`<div class="card eco-dungeon"><span class="eco-trade">${d.name}</span><span class="eco-meta">${sentence(d.level_line)}</span><span class="eco-sub">${sentence(d.line)}</span>
${(d.recipes || []).map((r) => html`<div class="eco-recipe">${itemOf(r)}<span class="eco-meta">${(r.chips || []).map((c) => c.text).join(" | ")}</span></div>`)}</div>`;
}

function rare(fam) {
  const d = fam.dungeons;
  if (!d) return html`<section class="section">${sectionHead("06", "Rare recipes by dungeon")}${state("unmeasured", "Dungeon recipes are not measured on this server.")}</section>`;
  const list = d.dungeons || [];
  const rest = list.length > DUNGEONS_SHOWN
    ? fold("dungeons|" + fam.family, plural(list.length - DUNGEONS_SHOWN, "more dungeon"), html`<div class="eco-dungeons">${list.slice(DUNGEONS_SHOWN).map(dungeonCard)}</div>`)
    : "";
  return html`<section class="section">${sectionHead("06", "Rare recipes by dungeon")}<p class="eco-sub">${sentence(d.line)}</p>
<div class="eco-dungeons">${list.slice(0, DUNGEONS_SHOWN).map(dungeonCard)}</div>${rest}</section>`;
}

function tradesTab(p, ctx, get) {
  const fam = chosenFamily(p, ctx.query);
  const fams = p.families && p.families.length ? p.families : [p];
  const pick = fams.length > 1
    ? html`<div class="eco-chips" role="group" aria-label="Family">${fams.map((f) => chipLink(f.heading || f.family, ecoHref("trades", { family: String(f.family).toLowerCase() }), f === fam))}</div>`
    : "";
  return html`<div class="eco-head"><span class="eco-headline">${sentence(fam.line)}</span>${pick}<span class="eco-sub">${sentence(fam.guild_line)}</span><span class="eco-meta">${fam.coverage}</span></div>
${hundred(fam, ctx, get)}${branches(fam.goal)}${ladder(fam.goal)}${nobody(fam)}${needs(fam)}${rare(fam)}`;
}

// ---- skill levels -------------------------------------------------------------

function professionsTab(p) {
  const fams = p.families && p.families.length ? p.families : [p];
  const byTrade = new Map();
  fams.forEach((f) => (f.trades || []).forEach((t) => {
    const list = byTrade.get(t.name) || [];
    (t.holders || []).forEach((h) => list.push(Object.assign({ guild: f.family }, h)));
    byTrade.set(t.name, list);
  }));
  const cards = Array.from(byTrade, ([name, list]) => ({ name, list: list.sort((a, b) => b.value - a.value) }))
    .filter((c) => c.list.length).sort((a, b) => b.list.length - a.list.length || a.name.localeCompare(b.name));
  const row = (h) => html`<div class="eco-skill"><span>${member({ name: h.who })}</span>${bar((100 * h.value) / (h.max || 1), "accent")}<span class="num" title="${h.value + " of " + h.max}">${h.value}<span class="muted">/${h.max}</span></span></div>`;
  return html`<div class="eco-skills">${cards.map((c) => html`<div class="card"><div class="eco-line"><span class="eco-trade">${cap(c.name)}</span><span class="eco-meta">${plural(c.list.length, "crafter")}</span></div>
${c.list.slice(0, 6).map(row)}${c.list.length > 6 ? fold("skill|" + c.name, plural(c.list.length - 6, "more crafter"), html`${c.list.slice(6).map(row)}`) : ""}</div>`)}</div>
<p class="eco-note">The bar is each crafter's skill against the cap of the training they hold.</p>`;
}

// ---- guild bank ---------------------------------------------------------------

// The bank page's own view state: which way the tab is drawn and the name
// filter, kept across the view's redraws like the folds above.
const bankUI = { mode: "grid", q: "" };

// The guild the reader last looked at, so the bank opens on it when the
// URL does not say. Guarded the way store.js guards: storage can refuse.
const BANK_GUILD_KEY = "overseer.bank-guild";
let bankGuildMem = "";
function savedBankGuild() {
  try { return (typeof window !== "undefined" && window.localStorage && window.localStorage.getItem(BANK_GUILD_KEY)) || bankGuildMem; } catch { return bankGuildMem; }
}
function saveBankGuild(g) {
  bankGuildMem = g;
  try { if (typeof window !== "undefined" && window.localStorage) window.localStorage.setItem(BANK_GUILD_KEY, g); } catch { /* storage refused */ }
}

const SMALL_WORD = new Set(["of", "the", "a", "an"]);

// The two letters an icon-less stack shows. The server's letters are the
// first two words' initials, so every Libram reads "LO"; where distinct
// items in one tab share a mark, the mark is rebuilt from the item's own
// first and last full words (Libram of Rumination -> LR).
export function bankMarks(cells) {
  const entries = new Map();
  cells.forEach((c) => {
    if (!entries.has(c.letters)) entries.set(c.letters, new Set());
    entries.get(c.letters).add(c.entry);
  });
  const marks = new Map();
  cells.forEach((c) => {
    if (marks.has(c.entry)) return;
    let mark = c.letters;
    if (entries.get(c.letters).size > 1) {
      const words = String(c.name || "").split(/\s+/).filter((w) => /[a-z]/i.test(w) && !SMALL_WORD.has(w.toLowerCase()));
      if (words.length >= 2) mark = (words[0][0] + words[words.length - 1][0]).toUpperCase();
    }
    marks.set(c.entry, mark);
  });
  return marks;
}

// The list view's rows: one per distinct item, its stacks summed.
export function bankListRows(cells) {
  const byEntry = new Map();
  cells.forEach((c) => {
    if (!byEntry.has(c.entry)) byEntry.set(c.entry, { cell: c, count: 0 });
    byEntry.get(c.entry).count += c.count || 1;
  });
  return [...byEntry.values()];
}

function bankCell(c, mark) {
  return html`<span class="eco-cell" data-bank-cell>${item({ entry: c.entry, name: c.name, quality: c.quality, icon: c.icon, mark: mark || c.letters })}${c.count > 1 ? html`<span class="ct" aria-hidden="true">${c.count}</span>` : ""}</span>`;
}

// A tab's stacks under small headers by kind (cloth, herbs, recipes...),
// when the guild bank read says each stack's category; the slot order holds
// inside each. One block, as the game draws it, when it does not.
export function bankGroups(cells) {
  if (!cells.some((c) => c.category)) return [{ label: "", cells }];
  const groups = new Map();
  cells.forEach((c) => {
    const label = c.category || "Other";
    if (!groups.has(label)) groups.set(label, { label, rank: Number.isFinite(c.category_rank) ? c.category_rank : 99, cells: [] });
    groups.get(label).cells.push(c);
  });
  return Array.from(groups.values()).sort((a, b) => a.rank - b.rank);
}

// The tab's empty slots, drawn as the game draws them, capped: a wall of
// 98 blanks says nothing after the first row, so past seven the rest are
// one counted cell.
const EMPTY_DRAWN = 7;
function emptyCells(empties) {
  if (!empties) return "";
  const plain = empties <= EMPTY_DRAWN ? empties : EMPTY_DRAWN - 1;
  const cells = [];
  for (let i = 0; i < plain; i += 1) cells.push(html`<span class="eco-cell eco-empty" aria-hidden="true"></span>`);
  if (empties > EMPTY_DRAWN) cells.push(html`<span class="eco-cell eco-empty eco-more" aria-hidden="true">+${empties - plain} empty</span>`);
  return html`${cells}`;
}

function bankGrid(cells, marks, empties) {
  const tail = emptyCells(empties || 0);
  const groups = bankGroups(cells);
  if (groups.length < 2) return html`<div class="eco-grid">${cells.map((c) => bankCell(c, marks.get(c.entry)))}${tail}</div>`;
  return html`<div class="eco-cats">${groups.map((g) => html`<section class="eco-cat" aria-label="${g.label}"><h3 class="eco-cat-head"><span>${g.label}</span><span class="num">${g.cells.length}</span></h3><div class="eco-grid">${g.cells.map((c) => bankCell(c, marks.get(c.entry)))}</div></section>`)}${tail ? html`<div class="eco-grid">${tail}</div>` : ""}</div>`;
}

function bankList(cells, marks) {
  return html`<div class="eco-banklist">${bankListRows(cells).map((r) => html`<div class="eco-brow" data-bank-row>${item({ entry: r.cell.entry, name: r.cell.name, quality: r.cell.quality, icon: r.cell.icon, mark: marks.get(r.cell.entry) })}${r.cell.category ? html`<span class="eco-meta">${r.cell.category}</span>` : ""}<span class="num">${r.count}</span></div>`)}</div>`;
}

// Also the Now tiles' Guild bank panel (now/panel.js). The panel host
// passes its own ctx (params.tab "guildbank"): it gets the grid as it
// always has, without the page's tools, and it neither reads nor writes
// the last-viewed guild.
export function bankTab(ctx, get) {
  const reads = familyKeys().map((n) => get(bankPath(n)));
  if (!reads.length) return state("unmeasured", "Which families the realm has is not measured yet.");
  const ready = reads.filter((r) => r.data && r.data.guild);
  if (!ready.length) return pendingRead(reads[0], 3) || state("empty", "Neither family is in a guild.");
  const onPage = !!ctx.params && ctx.params.tab === "bank";
  const wanted = (ctx.query.guild || (onPage ? savedBankGuild() : "") || "").toLowerCase();
  const chosen = ready.find((r) => r.data.guild.toLowerCase() === wanted) || ready[0];
  const bank = chosen.data;
  const g = bank.guild.toLowerCase();
  if (onPage) saveBankGuild(g);
  const pick = html`<div class="eco-chips" role="group" aria-label="Guild">${ready.map((r) => chipLink(r.data.guild, ecoHref("bank", { guild: r.data.guild.toLowerCase() }), r.data === bank))}</div>`;
  const head = html`<div class="eco-line eco-vault"><span>${bank.guild} vault holds ${money(bank.money ? { total: Number(bank.money.gold || 0) * 10000 + Number(bank.money.silver || 0) * 100 + Number(bank.money.copper || 0) } : null)}</span></div>`;
  const tabs = (bank.tabs || []).filter(Boolean);
  if (!tabs.length) return html`${pick}${head}${state("empty", bank.note || "The guild has not bought a bank tab yet.")}`;
  const stacks = tabs.reduce((n, t) => n + (t.used || 0), 0);
  const stamp = chosen.at ? html`<div class="eco-meta">${bank.guild} vault · read ${since(fromClock(chosen.at))} · ${plural(stacks, "stack")} in ${plural(tabs.length, "tab")}</div>` : "";
  const at = tabs.find((t) => String(t.tab) === String(ctx.query.tab)) || tabs[0];
  const rail = html`<div class="eco-chips" role="group" aria-label="Bank tab">${tabs.map((t) => chipLink(t.name + " · " + t.used + "/" + t.total, ecoHref("bank", { guild: g, tab: t.tab }), t === at))}</div>`;
  const pctFull = Math.round((100 * (at.used || 0)) / (at.total || 1));
  const full = html`<div class="eco-full">${bar(pctFull, pctFull >= 85 ? "warn" : "accent")}<span class="eco-meta">${at.name} is ${pctFull} percent full</span></div>${at.holds ? html`<span class="eco-meta">${sentence(at.holds)}</span>` : ""}`;
  const rawCells = at.cells || [];
  const cells = rawCells.filter(Boolean);
  const empties = Math.max(0, (at.total || rawCells.length) - cells.length);
  const marks = bankMarks(cells);
  const tools = onPage && cells.length ? html`<div class="eco-bank-tools"><div class="seg" role="group" aria-label="Bank view"><button type="button" data-bank-mode="grid" aria-pressed="${bankUI.mode === "grid" ? "true" : "false"}">Grid</button><button type="button" data-bank-mode="list" aria-pressed="${bankUI.mode === "list" ? "true" : "false"}">List</button></div><label class="eco-bank-filter"><i class="ph ph-funnel" aria-hidden="true"></i><input class="input" type="search" data-bank-q placeholder="Filter by item name" value="${bankUI.q}"></label></div>` : "";
  const drawn = !cells.length
    ? state("empty", "This tab is empty.")
    : onPage
      ? html`<div data-bank-grid${bankUI.mode === "list" ? raw(" hidden") : ""}>${bankGrid(cells, marks, empties)}</div><div data-bank-list${bankUI.mode === "grid" ? raw(" hidden") : ""}>${bankList(cells, marks)}</div><p class="eco-note" data-bank-none hidden>No item in this tab matches the filter.</p>`
      : bankGrid(cells, marks, empties);
  return html`${pick}${head}${stamp}${rail}${full}
<div class="section eco-bank" data-bank>${sectionHead("", at.name, plural(cells.length, "stack") + (empties ? " · " + empties + " empty" : ""))}${tools}${drawn}</div>
<p class="eco-note">Read only. The bank changes in game.</p>`;
}

// ---- the view -----------------------------------------------------------------

export function readsFor(ctx) {
  const t = ctx.params.tab;
  if (t === "gold" || t === "auction") return [WEALTH];
  if (t === "bank") return familyKeys().map(bankPath);
  const q = ctx.query;
  if (t === "trades" && q.open && q.family) return [TRADES, skillPath(q.open, cap(q.family))];
  return [TRADES];
}

function body(ctx) {
  const t = ctx.params.tab;
  if (t === "bank") return bankTab(ctx, ctx.get);
  const main = ctx.get(readsFor(ctx)[0]);
  const wait = pendingRead(main, 4);
  if (wait) return wait;
  if (t === "gold") return goldTab(main.data);
  if (t === "auction") return auctionTab(main.data.auctions || {});
  if (t === "trades") return tradesTab(main.data, ctx, ctx.get);
  return professionsTab(main.data);
}

function summary(ctx) {
  const t = ctx.params.tab;
  if (t !== "gold" && t !== "auction") return SUMMARY[t];
  const w = ctx.get(WEALTH).data;
  const f = w && w.family && w.family.finding;
  return f ? f.lead + ". " + f.detail : "Purses, bags and auctions, as the world last saved them.";
}

export default {
  css: ["views/economy.css"],
  reads: readsFor,
  every: 60000,
  title: (ctx) => (TABS.find((x) => x[0] === ctx.params.tab) || TABS[0])[1],
  render(ctx) {
    const row = tabs("Economy views", TABS.map(([k, label]) => ({ label, href: ecoHref(k), current: k === ctx.params.tab })));
    return html`${pageHead("Economy", summary(ctx))}${row}<div class="eco">${body(ctx)}</div>`;
  },
  after(main) {
    main.querySelectorAll("details[data-fold]").forEach((d) => {
      d.addEventListener("toggle", () => folds.set(d.getAttribute("data-fold"), d.open));
    });
    const box = main.querySelector("[data-bank]");
    if (!box) return;
    // The filter works on what is already drawn: it hides cells and rows
    // in place, so typing never loses the input to a redraw.
    const applyBank = () => {
      const query = bankUI.q.trim().toLowerCase();
      let hits = 0;
      box.querySelectorAll("[data-bank-cell], [data-bank-row]").forEach((el) => {
        const anchor = el.querySelector("[data-name]");
        const hit = !query || (anchor && (anchor.getAttribute("data-name") || "").toLowerCase().includes(query));
        el.classList.toggle("eco-hide", !hit);
        if (hit) hits += 1;
      });
      box.querySelectorAll(".eco-empty").forEach((el) => el.classList.toggle("eco-hide", !!query));
      const none = box.querySelector("[data-bank-none]");
      if (none) none.hidden = !(query && hits === 0);
      const grid = box.querySelector("[data-bank-grid]");
      const list = box.querySelector("[data-bank-list]");
      if (grid) grid.hidden = bankUI.mode !== "grid";
      if (list) list.hidden = bankUI.mode !== "list";
      box.querySelectorAll("[data-bank-mode]").forEach((b) => b.setAttribute("aria-pressed", String(b.getAttribute("data-bank-mode") === bankUI.mode)));
    };
    box.querySelectorAll("[data-bank-mode]").forEach((b) => b.addEventListener("click", () => { bankUI.mode = b.getAttribute("data-bank-mode"); applyBank(); }));
    const input = box.querySelector("[data-bank-q]");
    if (input) input.addEventListener("input", () => { bankUI.q = input.value; applyBank(); });
    applyBank();
  },
};
