// Guilds: one guild's progress, its runs and its chronicle.
//
//   #/guilds/<cave|bonkers>             Progress
//   #/guilds/<cave|bonkers>/runs        Runs
//   #/guilds/<cave|bonkers>/chronicle   Chronicle
//
// Reads: /api/v2/guild (header, tiles, class quests, deaths, the path),
// /api/v2/series (guild XP per hour), /api/guildruns, /api/v2/dungeonups, /api/runtimeline, and for the
// chronicle /api/v2/chronicle, /api/loot, /api/recap, /api/council and
// /api/guildchat. Nothing here writes.

import {
  html, raw, pageHead, sectionHead, tabs, kpi, sparkline, histogram, notMeasured,
  state, pendingRead, item, member, memberHref, plural, duration, classVar,
} from "../ui.js";
import { peek } from "../api.js";
import {
  GUILD_NAME, GUILD_FAMILY, utc, since, runCard, bindRunCards, runHref, seatChips,
} from "./_runs.js";

const TABS = [["progress", "Progress"], ["runs", "Runs"], ["chronicle", "Chronicle"]];
const FEED_KINDS = [
  ["all", "All", null],
  ["levels", "Levels and runs", ["level", "clear", "run"]],
  ["loot", "Loot", ["loot"]],
  ["death", "Deaths", ["death"]],
];
const FEED_PAGE = 40;
const CQ_SHOWN = 8;
const CHAT_SHOWN = 10;

function key(ctx) { return ctx.params.guild; }
function gname(ctx) { return GUILD_NAME[key(ctx)]; }
function family(ctx) { return GUILD_FAMILY[key(ctx)]; }
function base(ctx) { return "#/guilds/" + key(ctx); }

const P = {
  guild: (ctx) => "/api/v2/guild?guild=" + key(ctx),
  roster: () => "/api/v2/roster",
  series: (ctx) => "/api/v2/series?guild=" + key(ctx),
  runs: () => "/api/guildruns",
  ups: (ctx) => "/api/v2/dungeonups?family=" + family(ctx).toLowerCase(),
  timeline: () => "/api/runtimeline",
  chronicle: (ctx) => "/api/v2/chronicle?guild=" + key(ctx),
  loot: () => "/api/loot",
  recap: () => "/api/recap",
  council: () => "/api/council",
  chat: (ctx) => "/api/guildchat?guild=" + gname(ctx),
};

const TAB_READS = {
  progress: ["guild", "series", "roster"],
  runs: ["guild", "runs", "ups", "timeline"],
  chronicle: ["guild", "runs", "chronicle", "loot", "recap", "council", "chat"],
};

// Per-device view state that is not worth a URL: the feed's page length and
// which path rows are open. The feed filter is in the URL (?kind=).
const view = { kind: "all", shown: FEED_PAGE, open: new Set(), hash: "" };

function median(nums) {
  const s = nums.slice().sort((a, b) => a - b);
  if (!s.length) return null;
  return s[Math.floor(s.length / 2)];
}

function n(v) { return Number(v || 0).toLocaleString("en-US"); }

// ---- header -----------------------------------------------------------------

function summary(g) {
  const levels = g.members.map((m) => m.level);
  return g.guild + ": median level " + median(levels) + ", " + g.gaining.length + " of " + g.count + " reached a new level in the last 24 hours" + (g.deaths.ghosts.length ? ", " + plural(g.deaths.ghosts.length, "ghost") + " now" : "") + ".";
}

function header(ctx, g) {
  const pick = html`<div class="seg g-pick" role="group" aria-label="Guild">${Object.keys(GUILD_NAME).map((k) => html`<a href="${"#/guilds/" + k + (ctx.params.tab === "progress" ? "" : "/" + ctx.params.tab)}"${k === key(ctx) ? raw(' aria-current="page"') : ""}>${GUILD_NAME[k]}</a>`)}</div>`;
  const facts = g
    ? html`${plural(g.count, "member")} | ${g.online} online | ${g.faction || notMeasured("faction not measured")}`
    : "";
  return html`<header class="page-head g-head">
<div class="g-title"><h1>${gname(ctx)}</h1><span class="g-facts">${facts}</span>${pick}</div>
${g ? html`<p class="summary g-summary">${summary(g)}</p>` : ""}
</header>
${tabs("Guild views", TABS.map(([k, label]) => ({ label, href: base(ctx) + (k === "progress" ? "" : "/" + k), current: k === ctx.params.tab })))}`;
}

// ---- progress -----------------------------------------------------------------

function kpis(ctx, g) {
  const q = "#/members?guild=" + key(ctx);
  const levels = g.members.map((m) => m.level);
  const ghosts = g.members.filter((m) => m.ghost).length;
  const cq = g.class_quests;
  // Stuck is the roster's reading (the Members page's), counted for this guild.
  const roster = peek(P.roster(ctx));
  const list = roster.data && Array.isArray(roster.data.members) ? roster.data.members : null;
  const mine = list ? list.filter((m) => m.guild === g.guild) : null;
  const stuck = mine ? mine.filter((m) => m.stuck).length : null;
  const stuckSub = mine ? "of " + plural(mine.length, "member") + ", waiting on help" : roster.loading ? "reading the roster" : "the roster read did not answer";
  const tile = (label, v, sub, href, tone) => html`<a class="kpi g-kpi" href="${href}"><span class="k">${label}</span><span class="v"${tone ? raw(' data-gt="' + tone + '"') : ""}>${v}</span><span class="s">${sub}</span></a>`;
  return html`<div class="g-kpis">
${tile("Gaining XP", g.gaining.length + "/" + g.count, "a new level in the last 24h", q + "&sort=xp")}
${tile("Median level", levels.length ? median(levels) : notMeasured(), levels.length ? Math.min(...levels) + " to " + Math.max(...levels) : "", q + "&sort=level")}
${tile("Class quests done", n(cq.done), cq.open + " in progress, " + cq.blocked + " blocked", q)}
${tile("Stuck", stuck === null ? notMeasured() : stuck, stuckSub, q + "&stuck=1", stuck ? "warn" : "")}
${tile("Ghosts now", ghosts, g.deaths.total + " deaths in 24h", q + "&ghost=1", ghosts ? "bad" : "")}
</div>`;
}

function xpCard(ctx) {
  const s = peek(P.series(ctx));
  const head = html`<span class="g-card-title">XP per hour, whole guild, last 24h</span>`;
  if (!s.data) return html`<div class="card g-card">${head}${s.error ? notMeasured("the series read did not answer") : html`<div class="skeleton g-skel"></div>`}</div>`;
  const pts = s.data.xp_per_hour || [];
  const vals = pts.map((p) => p[1]);
  const known = vals.filter((v) => v !== null);
  const now = known.length ? vals[vals.length - 1] : null;
  const aside = known.length
    ? html`now ${now === null ? notMeasured() : n(now)} | peak ${n(Math.max(...known))}`
    : "";
  return html`<div class="card g-card">
<div class="g-card-head">${head}<span class="muted">${aside}</span></div>
${known.length >= 2 ? html`<div class="g-spark">${sparkline(vals, { w: 300, h: 80, label: "Guild XP per hour over 24 hours" + (now !== null ? ", now " + n(now) : "") })}</div><div class="g-axis"><span>24h ago</span><span>12h</span><span>now</span></div>` : state("unmeasured", "XP per hour is not measured", "No member has a level change on record in the window, so there is no rate to draw.")}
<details class="fold g-note"><summary>${s.data.measured} of ${s.data.members} members measured. How this is worked out</summary><p>${s.data.basis}</p></details>
</div>`;
}

function spreadCard(ctx, g) {
  const levels = g.members.map((m) => m.level).filter((l) => l > 0);
  if (!levels.length) return html`<div class="card g-card"><span class="g-card-title">Level spread</span>${notMeasured()}</div>`;
  const lo = Math.min(...levels), hi = Math.max(...levels), med = median(levels);
  const bins = [];
  for (let a = lo - (lo % 2); a <= hi; a += 2) {
    const b = a + 1;
    bins.push({ label: a + "-" + b, n: levels.filter((l) => l >= a && l <= b).length, median: med >= a && med <= b, href: "#/members?guild=" + key(ctx) + "&lvl=" + a + "-" + b });
  }
  return html`<div class="card g-card">
<div class="g-card-head"><span class="g-card-title">Level spread</span><span class="muted">median ${med} | ${lo} to ${hi}</span></div>
${histogram(bins, { label: "Members by level, two levels a bar", unit: "member" })}
</div>`;
}

function cqCard(ctx, g) {
  const cq = g.class_quests;
  const row = (q) => {
    const blocked = q.state === "blocked";
    return html`<a class="g-row g-cq" href="${memberHref(q.member, "quests")}">
<i class="${blocked ? "ph-fill ph-hand-palm" : "ph ph-circle-dashed"}" data-gt="${blocked ? "warn" : "accent"}" aria-hidden="true"></i>
<span class="g-cq-body"><span class="g-cq-line"><span><b style="color:${classVar(q.class)}">${q.member}</b> <span class="muted">${q.quest || (q.quest_id ? "quest " + q.quest_id : q.walk_to || notMeasured("quest not recorded on its step"))}</span></span><span class="g-cq-state" data-gt="${blocked ? "warn" : "accent"}">${q.state}</span></span>
${blocked ? html`<span class="muted">${q.note}${q.at ? " | " + since(q.at) : ""}</span>` : ""}</span></a>`;
  };
  const first = cq.rows.slice(0, CQ_SHOWN), rest = cq.rows.slice(CQ_SHOWN);
  return html`<div class="card g-list">
<div class="g-list-head"><span class="g-card-title">Class quests</span><span class="muted">${n(cq.done)} done | ${cq.blocked} blocked | ${cq.open} in progress</span></div>
${cq.rows.length ? first.map(row) : html`<div class="g-row muted">No class quest is in anybody's log.</div>`}
${rest.length ? html`<details class="fold g-more"><summary>${plural(rest.length, "more class quest")}</summary>${rest.map(row)}</details>` : ""}
</div>`;
}

function lastWord(d) {
  if (d.inside) return { text: "inside now", tone: "accent" };
  if (d.last_at) return { text: since(d.last_at), tone: "" };
  return { text: "never", tone: "dim" };
}

function dungeonCard(ctx, g) {
  const clears = g.dungeons.reduce((a, d) => a + d.cleared, 0);
  return html`<div class="card g-list">
<div class="g-list-head"><span class="g-card-title">Dungeons, level order</span><span class="muted">${plural(clears, "clear")}</span></div>
${g.dungeons.map((d) => {
    const last = lastWord(d);
    return html`<div class="g-row g-dun"><span>${d.place}</span><span class="muted g-lv">${levelsOf(d)}</span><span class="num"${d.cleared ? "" : raw(' data-gt="dim"')}>${d.cleared}x</span><span class="g-last" data-gt="${last.tone}">${last.text}</span></div>`;
  })}
</div>`;
}

function levelsOf(d) { return d.floor ? d.floor + "-" + d.ceiling : "levels not measured"; }

function deathsCard(ctx, g) {
  const d = g.deaths;
  const ghosts = d.ghosts.map((x) => html`<div class="g-row g-death"><i class="ph-fill ph-ghost" aria-hidden="true"></i><span class="g-grow">${member({ name: x.name, cls: (g.members.find((m) => m.name === x.name) || {}).class })} is a ghost${x.killer ? ": killed by " + x.killer : ""}${x.where ? " in " + x.where : ""}</span><span class="muted">${x.at ? since(x.at) : "now"}</span></div>`);
  const killers = d.killers.map((k) => html`<div class="g-row g-death"><i class="ph ph-skull" aria-hidden="true"></i><span class="g-grow">${k.killer || "The world"} killed ${plural(k.members, "member")}, ${plural(k.n, "time")} in 24h</span></div>`);
  return html`<div class="card g-list">
<div class="g-list-head"><span class="g-card-title">Deaths and ghosts</span><span class="muted">${n(d.total)} deaths in 24h | ${d.ghosts.length} ${d.ghosts.length === 1 ? "ghost" : "ghosts"} now</span></div>
${ghosts}${killers}
${!ghosts.length && !killers.length ? html`<div class="g-row muted">Nobody died in the last 24 hours.</div>` : ""}
</div>`;
}

function progress(ctx, g) {
  return html`${kpis(ctx, g)}
<div class="g-two">${xpCard(ctx)}${spreadCard(ctx, g)}</div>
<div class="g-two">${cqCard(ctx, g)}${dungeonCard(ctx, g)}</div>
${deathsCard(ctx, g)}`;
}

// ---- runs ---------------------------------------------------------------------

function mine(ctx, list) { return (list || []).filter((r) => r.guild === gname(ctx)); }

function upsFor(ctx, mapId) {
  const u = peek(P.ups(ctx));
  if (!Array.isArray(u.data)) return null;
  return u.data.filter((x) => x.map_id === mapId);
}

function upRow(x) {
  const at = x.now ? "" : " at " + x.req;
  return html`<div class="g-up">${item({ entry: x.item.entry, name: x.item.name, quality: x.item.quality, icon: x.item.icon })}<span class="muted">${x.boss}</span><a href="${memberHref(x.member, "upgrades")}" class="g-up-who">${x.member}, ${x.slot}${at}</a><span class="g-up-gain">+${x.gain} iLvl</span></div>`;
}

function pathRow(ctx, g, d, med, upsRead) {
  const ups = d.map_id !== null ? upsFor(ctx, d.map_id) : null;
  const last = lastWord(d);
  const opens = med !== null && d.floor && med < d.floor;
  let upsText, upsTone = "dim";
  if (ups === null) upsText = upsRead.error ? "upgrades not measured" : "reading upgrades";
  else if (ups.length) {
    upsText = plural(ups.length, "upgrade") + " for the family: " + [...new Set(ups.map((x) => x.member))].join(", ");
    upsTone = "accent";
  } else upsText = opens ? "opens at median level " + d.floor : "no upgrades for the family";
  const shared = /\(/.test(d.place) ? html`<div class="g-up-note muted">Drops are read for the whole dungeon, every wing.</div>` : "";
  const cells = html`<span class="g-name">${d.place}</span><span class="muted g-lv">${levelsOf(d)}</span><span class="num"${d.cleared ? "" : raw(' data-gt="dim"')}>${d.cleared}x</span><span class="g-ups" data-gt="${upsTone}">${upsText}</span><span class="g-last" data-gt="${last.tone}">${last.text}</span>`;
  const hot = d.inside ? " g-hot" : "";
  if (!ups || !ups.length) return html`<div class="g-path-row${hot}"><span class="g-caret" aria-hidden="true"></span>${cells}</div>`;
  const id = "path-" + d.keyword;
  return html`<details class="g-path${hot}" data-path="${d.keyword}"${view.open.has(d.keyword) ? raw(" open") : ""}><summary class="g-path-row" id="${id}"><i class="ph ph-caret-right g-caret" aria-hidden="true"></i>${cells}</summary><div class="g-ups-list">${shared}${ups.map(upRow)}</div></details>`;
}

function runsTab(ctx, g) {
  const gr = peek(P.runs());
  const upsRead = peek(P.ups(ctx));
  const tl = peek(P.timeline());
  const checked = gr.at ? "Checked " + since(gr.at / 1000) + "." : "";
  let now = pendingRead(gr, 1), done = now;
  if (gr.data) {
    const out = mine(ctx, gr.data.active);
    const back = mine(ctx, gr.data.recent);
    now = out.length ? html`<div class="g-cards">${out.map((r) => runCard(r))}</div>` : state("empty", "No group from " + gname(ctx) + " is out right now.", checked);
    done = back.length ? html`<div class="g-cards">${back.map((r) => runCard(r, { done: true }))}</div>` : state("empty", "No group from " + gname(ctx) + " has come back in the recent runs.", checked);
  }
  const learned = g.dungeons.filter((d) => d.runs > 0);
  const med = median(g.members.map((m) => m.level));
  return html`
<section class="section">${sectionHead("01", "Groups out now")}${now}</section>
<section class="section">${sectionHead("02", "How they came back")}${done}</section>
<section class="section">${sectionHead("03", "What the guild has learned")}
${learned.length ? html`<div class="card g-list g-narrow">${learned.map((d) => html`<div class="g-row g-learn"><span class="g-learn-what"><span class="g-name">${d.place}</span><span class="muted">${lesson(d)}</span></span><span class="muted">${tally(d)}</span><span class="muted g-best">${d.best_seconds ? "best " + duration(d.best_seconds) : "no clear yet"}</span></div>`)}</div>` : state("empty", "Nothing learned yet: no run of " + gname(ctx) + " has gone in.")}
</section>
<section class="section">${sectionHead("04", "The path, in level order")}
<p class="muted g-lede">Run in this order: each dungeon opens when the median level of the guild reaches its floor. Open a row to see each drop that beats what ${family(ctx)}'s family wears, who it is for and from which boss.</p>
${g.family && g.family !== family(ctx) ? state("stale", "This guild's family reads as " + g.family + "'s here", "The upgrades below are for " + family(ctx) + "'s family.") : ""}
<div class="card g-list g-pathlist">${g.dungeons.map((d) => pathRow(ctx, g, d, med, upsRead))}</div>
</section>
<section class="section">${sectionHead("05", "Run timelines", tl.data ? tl.data.line : "")}${timelines(ctx, tl)}</section>`;
}

function tally(d) {
  return d.cleared + (d.cleared === 1 ? " clear" : " clears") + " of " + plural(d.runs, "run") + (d.wiped ? ", " + plural(d.wiped, "wipe") : "");
}

function lesson(d) {
  if (!d.lesson) return "nothing went wrong often enough to learn from";
  return d.lesson.outcome + " " + d.lesson.n + "x" + (d.lesson.why ? ": " + d.lesson.why : "");
}

function timelines(ctx, tl) {
  const wait = pendingRead(tl, 2);
  if (wait) return wait;
  const fam = (tl.data.families || []).find((f) => f.title === family(ctx));
  if (!fam || !(fam.runs || []).length) return state("empty", "No run of " + family(ctx) + "'s family in the last 14 days.");
  return html`<p class="muted g-lede">${family(ctx)}'s family. ${fam.line || ""}</p><div class="g-timelines">${fam.runs.map((r) => html`<div class="card g-timeline"><span class="g-name">${r.title}</span><span class="muted">${r.line}</span>${r.cause ? html`<span class="g-tl-cause">${r.cause}</span>` : ""}<div class="g-steps">${(r.events || []).map((e) => html`<div class="g-step" data-gt="${e.tone || ""}"><span class="g-step-t">${e.at}</span><span>${e.line}</span></div>`)}</div></div>`)}</div>`;
}

// ---- chronicle ----------------------------------------------------------------

function loottime(s) { return utc(s.at); }

function feedItems(ctx) {
  const c = peek(P.chronicle(ctx));
  const loot = peek(P.loot());
  const items = c.data ? c.data.items.slice() : [];
  if (loot.data) {
    (loot.data.stories || []).filter((s) => s.guild === gname(ctx)).forEach((s) => {
      items.push({ kind: "loot", at: loottime(s), text: s.line, item: s.item });
    });
  }
  items.sort((a, b) => (b.at || 0) - (a.at || 0));
  return items;
}

const FEED_ICON = {
  level: ["ph-fill ph-arrow-fat-up", "gold"], clear: ["ph-fill ph-trophy", "gold"],
  run: ["ph ph-door-open", "warn"], loot: ["ph-fill ph-sword", "accent"], death: ["ph ph-skull", "bad"],
};

function feedRow(ctx, x) {
  const fresh = ctx.previousVisit && x.at && x.at * 1000 > ctx.previousVisit;
  const [icon, tone] = FEED_ICON[x.kind] || ["ph ph-circle", ""];
  const body = x.kind === "loot" && x.item
    ? html`${item({ entry: x.item.entry, name: x.item.name, quality: x.item.quality, icon: x.item.icon })} <span>${x.text}</span>`
    : x.run ? html`<a href="${runHref({ id: x.run })}" class="g-feed-link">${x.text}</a>` : x.text;
  return html`<div class="g-row g-feed"><i class="${icon}" data-gt="${tone}" aria-hidden="true"></i><span class="g-grow">${body}</span>${fresh ? html`<span class="tag tag-accent">New</span>` : ""}<span class="muted g-when">${since(x.at)}</span></div>`;
}

function feed(ctx) {
  const c = peek(P.chronicle(ctx));
  const wait = pendingRead(c, 2);
  if (wait) return wait;
  const all = feedItems(ctx);
  const kinds = FEED_KINDS.find((k) => k[0] === view.kind) || FEED_KINDS[0];
  const list = kinds[2] ? all.filter((x) => kinds[2].includes(x.kind)) : all;
  const chips = FEED_KINDS.map(([k, label, ks]) => html`<button type="button" class="chip g-filter" data-kind="${k}" aria-pressed="${k === view.kind ? "true" : "false"}">${label} <span class="muted">${ks ? all.filter((x) => ks.includes(x.kind)).length : all.length}</span></button>`);
  const shown = list.slice(0, view.shown);
  return html`<div class="row g-filters" role="group" aria-label="Show">${chips}</div>
<div class="card g-list" id="g-feed">${shown.map((x) => feedRow(ctx, x))}
${list.length ? "" : html`<div class="g-row muted">Nothing of this kind in the last ${c.data.days} days.</div>`}
${list.length > shown.length ? html`<div class="g-row"><button type="button" class="btn btn-ghost" data-more="feed">Show ${Math.min(FEED_PAGE, list.length - shown.length)} more of ${list.length - shown.length}</button></div>` : ""}
</div>`;
}

function rightNow(ctx) {
  const gr = peek(P.runs());
  const rc = peek(P.recap());
  const out = gr.data ? mine(ctx, gr.data.active) : [];
  const cards = out.map((r) => html`<div class="card g-now stretch-card"><a class="g-name stretch-link" href="${runHref(r)}" data-run="${r.id}">${gname(ctx)} is in ${r.place}: ${r.bosses_total ? r.bosses_done + " of " + r.bosses_total + " bosses down" : "bosses not measured"}, ${plural(r.deaths || 0, "death")}${r.seconds_inside ? ", " + duration(r.seconds_inside) + " inside" : ""}.</a>${seatChips(r)}</div>`);
  const live = rc.data && rc.data.live && rc.data.family === family(ctx) ? recapCard(ctx, rc.data) : "";
  if (!cards.length && !live) {
    if (!gr.data) return pendingRead(gr, 1);
    return state("empty", "Nobody from " + gname(ctx) + " is inside a dungeon right now.", gr.at ? "Checked " + since(gr.at / 1000) + "." : "");
  }
  return html`${live}${cards}`;
}

function recapCard(ctx, r) {
  const p = r.progress || {};
  const down = new Set(p.down || []);
  const bosses = (r.board && r.board.bosses) || [];
  const next = bosses.find((b) => !down.has(b.name));
  const wanted = [];
  bosses.forEach((b) => (b.drops || []).forEach((d) => { if ((d.wanted_by || []).length) wanted.push(d); }));
  return html`<div class="card g-recap">
<span class="g-name">${family(ctx)}'s family: ${r.headline}</span>
<span class="muted">${[r.party_line, p.line, r.deaths_line].filter(Boolean).join(" | ")}</span>
${bosses.length ? html`<div class="g-bosses">${bosses.map((b) => {
    const st = down.has(b.name) ? "down" : b === next ? "next" : "alive";
    const icon = st === "down" ? "ph-fill ph-check-circle" : st === "next" ? "ph ph-arrow-circle-right" : "ph ph-circle";
    return html`<span class="g-boss" data-state="${st}"><i class="${icon}" aria-hidden="true"></i>${b.name}</span>`;
  })}</div>` : ""}
${wanted.length ? html`<details class="fold"><summary>What could drop in here, and who it would suit</summary>${wanted.map((d) => html`<div class="g-row g-drop">${item(d)}<span class="muted">${d.verdict_line || ""}</span></div>`)}</details>` : ""}
</div>`;
}

function lootSection(ctx) {
  const l = peek(P.loot());
  const wait = pendingRead(l, 2);
  if (wait) return { loot: wait, council: wait };
  const stories = (l.data.stories || []).filter((s) => s.guild === gname(ctx)).slice(0, 12);
  const loot = html`<div class="card g-list">${stories.length ? stories.map((s) => html`<div class="g-row g-loot"><span class="g-loot-top">${item(s.item)}<span class="muted g-when">${since(utc(s.at))}</span></span><span class="muted">${s.line}</span></div>`) : html`<div class="g-row muted">${l.data.empty || "No notable loot yet."}</div>`}</div>
<details class="fold"><summary>How this is worked out</summary><p class="muted g-basis">${l.data.basis || ""}</p></details>`;
  const c = l.data.council || {};
  const awards = (c.awards || []).filter((a) => a.family === family(ctx)).slice(0, 12);
  const council = html`<div class="card g-list">${awards.length ? awards.map((a) => html`<div class="g-row g-loot"><span class="g-loot-top"><span>${item({ entry: a.item_entry, name: a.item_name, quality: a.quality })} <span class="muted">to</span> ${a.to ? member({ name: a.to }) : "nobody"}</span><span class="muted g-when">${since(utc(a.at))}</span></span><span class="muted">${a.reason || a.outcome || ""}</span></div>`) : html`<div class="g-row muted">${c.empty || "The loot council has not handed anything out."}</div>`}</div>`;
  return { loot, council };
}

function sittings(ctx) {
  const c = peek(P.council());
  const wait = pendingRead(c, 1);
  if (wait) return wait;
  const f = (c.data.families || []).find((x) => x.family === family(ctx));
  if (!f) return state("unmeasured", family(ctx) + "'s family has no council on record.");
  const k = f.consensus;
  if (!k) return state("empty", f.note || f.quiet || f.undecided || "No sitting on record.");
  return html`<div class="card g-sitting">
<div class="g-card-head"><span class="g-name">${f.title}</span><span class="muted">sat ${since(utc(k.at))}</span></div>
<span class="tag tag-outline g-label">${k.label}</span>
<span>${k.decision}</span>
${k.who_line ? html`<span class="muted">${k.who_line}</span>` : ""}
${(k.older || []).length ? html`<ul class="g-carried">${k.older.map((x) => html`<li>${x}</li>`)}</ul>` : ""}
<span><span class="muted">Next:</span> ${k.next_line || notMeasured()}</span>
</div>`;
}

// Chat lines carry the game's item links: |cffxxxxxx|Hitem:N:...|h[Name]|h|r.
function said(text) {
  const re = /\|c[0-9a-fA-F]{8}\|Hitem:(\d+)[^|]*\|h\[([^\]]*)\]\|h\|r/g;
  const t = String(text || "");
  const out = [];
  let at = 0, m;
  while ((m = re.exec(t)) !== null) {
    if (m.index > at) out.push(t.slice(at, m.index));
    out.push(item({ entry: Number(m[1]), name: m[2] }));
    at = m.index + m[0].length;
  }
  if (at < t.length) out.push(t.slice(at));
  return out;
}

function chat(ctx) {
  const c = peek(P.chat(ctx));
  const wait = pendingRead(c, 2);
  if (wait) return wait;
  const asks = c.data.asks || [];
  if (!asks.length) return state("empty", "Nobody in " + gname(ctx) + " has asked for anything yet.");
  const row = (a) => {
    const answers = a.answers || [];
    const out = a.run ? html`<a href="${runHref(a.run)}">${a.run.outcome ? "The run " + a.run.outcome : "The run is " + (a.run.state || "on")}${a.run.bosses_total ? ", " + a.run.bosses_done + " of " + a.run.bosses_total + " bosses" : ""}</a>` : "";
    return html`<div class="g-chat">
<div class="g-chat-top"><span>${member({ name: a.asker })} <span class="g-said">${said(a.said)}</span></span><span class="muted g-when">${since(utc(a.created_at))}</span></div>
<div class="g-answers">${answers.length ? answers.map((x) => html`<span>${member({ name: x.member })}: ${said(x.said)}</span>`) : html`<span data-gt="warn">${a.state === "open" ? "No answer yet." : "No answer: the ask " + a.state + "."}</span>`}${out}</div>
</div>`;
  };
  const first = asks.slice(0, CHAT_SHOWN), rest = asks.slice(CHAT_SHOWN);
  return html`<div class="card g-list g-narrow">${first.map(row)}${rest.length ? html`<details class="fold g-more"><summary>${plural(rest.length, "older ask")}</summary>${rest.map(row)}</details>` : ""}</div>`;
}

function chronicleTab(ctx) {
  const ls = lootSection(ctx);
  return html`
<section class="section">${sectionHead("01", "What is happening right now")}${rightNow(ctx)}</section>
<section class="section">${sectionHead("02", "What they have done", "New since your last visit is tagged")}${feed(ctx)}</section>
<div class="g-two g-two-wide">
<section class="section">${sectionHead("03", "Notable loot, and where it went")}${ls.loot}</section>
<section class="section">${sectionHead("04", "The loot council: who got what, and why")}${ls.council}</section>
</div>
<section class="section">${sectionHead("05", "The council: last sitting, what it carried, where next")}${sittings(ctx)}</section>
<section class="section">${sectionHead("06", "Guild chat: asks and answers")}${chat(ctx)}</section>`;
}

// ---- the view -------------------------------------------------------------------

export default {
  css: ["views/guild.css"],
  every: 30000,
  reads: (ctx) => (TAB_READS[ctx.params.tab] || TAB_READS.progress).map((k) => P[k](ctx)),
  title: (ctx) => gname(ctx) + (ctx.params.tab === "progress" ? "" : " " + ctx.params.tab),
  render(ctx) {
    const hashPath = ctx.hash.split("?")[0];
    if (view.hash !== hashPath) {
      view.hash = hashPath;
      view.shown = FEED_PAGE;
      view.kind = FEED_KINDS.some((k) => k[0] === ctx.query.kind) ? ctx.query.kind : "all";
    }
    const g = peek(P.guild(ctx));
    const wait = pendingRead(g, 3);
    if (wait) return html`${header(ctx, null)}${wait}`;
    const body = ctx.params.tab === "runs" ? runsTab(ctx, g.data) : ctx.params.tab === "chronicle" ? chronicleTab(ctx) : progress(ctx, g.data);
    return html`${header(ctx, g.data)}${body}`;
  },
  after(main, ctx) {
    bindRunCards(main, () => window.matchMedia("(max-width: 759.98px)").matches);
    main.querySelectorAll("details[data-path]").forEach((d) => {
      d.addEventListener("toggle", () => {
        if (d.open) view.open.add(d.getAttribute("data-path"));
        else view.open.delete(d.getAttribute("data-path"));
      });
    });
    const redrawFeed = () => {
      const box = main.querySelector("#g-feed");
      if (!box) return;
      const wrap = box.parentElement;
      const holder = document.createElement("div");
      holder.innerHTML = feed(ctx).s;
      wrap.querySelector(".g-filters").replaceWith(holder.querySelector(".g-filters"));
      box.replaceWith(holder.querySelector("#g-feed"));
      bindFeed();
    };
    const bindFeed = () => {
      main.querySelectorAll(".g-filter").forEach((b) => b.addEventListener("click", () => {
        view.kind = b.getAttribute("data-kind");
        view.shown = FEED_PAGE;
        const q = view.kind === "all" ? "" : "?kind=" + view.kind;
        history.replaceState(null, "", view.hash + q);
        redrawFeed();
        const now = main.querySelector('.g-filter[data-kind="' + view.kind + '"]');
        if (now) now.focus({ preventScroll: true });
      }));
      const more = main.querySelector('[data-more="feed"]');
      if (more) more.addEventListener("click", () => { view.shown += FEED_PAGE; redrawFeed(); });
    };
    bindFeed();
  },
  thumb(ctx) {
    return {
      label: "Guild",
      items: Object.keys(GUILD_NAME).map((k) => ({ label: GUILD_NAME[k], href: "#/guilds/" + k + (ctx.params.tab === "progress" ? "" : "/" + ctx.params.tab), current: k === key(ctx) })),
    };
  },
};

