// One member: #/m/<name>[/overview|/gear|/upgrades|/quests|/bags|/bank|/activity].
//
// The header comes from /api/v2/roster (level, class, guild, zone, state), and
// each tab reads only what it draws:
//   Overview   stuck card or current step, XP per hour, item level, gold,
//              bags, the level line of the last week and the latest commands
//              (/api/v2/activity, /api/armory/member, /api/client/bags,
//              /api/v2/series for XP per hour)
//   Gear       the paperdoll card (/api/armory/member) and Standing
//              (/api/v2/training); Upgrades is /api/v2/upgrades
//   Quests     the class quest chains (/api/v2/classchain) and the quest log
//              (/api/client/quests)
//   Inventory  bags or bank, 44px cells (/api/client/bags, /api/client/bank)
//   Activity   every command and the realm's answer (/api/v2/activity)

import { html, notMeasured, pendingRead, state, classVar, iconUrl, sparkline, gold, plural, status } from "../ui.js";
import {
  liveQuery, byName, stateLabel, stuckFor, seg, paperdoll, bindTrees, cell, emptyCell,
  upgradesHead, upgradesControls, upgradesBody, upgradesFoot, bindUpgrades, coins,
} from "./_members.js";
import { mountModels } from "./_model.js";

const TABS = [["overview", "Overview"], ["gear", "Gear"], ["quests", "Quests"], ["bags", "Inventory"], ["activity", "Activity"]];
const TAB_OF = { upgrades: "gear", bank: "bags" };

function q(name) { return "?name=" + encodeURIComponent(name); }

// The reads and tabs below are also the Now tiles' panels (now/panel.js).
export function readsFor(name, tab) {
  const n = q(name);
  switch (tab) {
    case "gear": return ["/api/armory/member" + n, "/api/v2/training" + n];
    case "upgrades": return ["/api/v2/upgrades" + n];
    case "quests": return ["/api/v2/classchain" + n, "/api/client/quests" + n];
    case "bags": return ["/api/client/bags" + n];
    case "bank": return ["/api/client/bank" + n];
    case "activity": return ["/api/v2/activity" + n];
    default: return ["/api/v2/activity" + n, "/api/armory/member" + n, "/api/client/bags" + n, "/api/v2/series" + n];
  }
}

function href(name, tab) { return "#/m/" + encodeURIComponent(name) + (tab && tab !== "overview" ? "/" + tab : ""); }

function raceIcon(m) {
  if (!m.race) return "";
  return "achievement_character_" + m.race.toLowerCase().replace(/[^a-z]/g, "") + "_" + (m.gender === "female" ? "female" : "male");
}

function header(m, checkedAt) {
  const icon = raceIcon(m);
  return html`<a class="mb-back" href="#/members"><i class="ph ph-caret-left" aria-hidden="true"></i>Members</a>
<div class="pf-head">${icon ? html`<img class="pf-race" src="${iconUrl(icon)}" alt="${m.race}" width="48" height="48">` : ""}<div class="pf-id"><h1 style="color:${classVar(m.class)}">${m.name}</h1><span class="row muted"><span class="pf-line">L${m.level} ${m.race} ${m.class} | ${m.guild || "no guild"} | ${m.zone || "zone not measured"}</span>${stateLabel(m, checkedAt)}</span></div></div>`;
}

function tabRow(name, tab) {
  const cur = TAB_OF[tab] || tab;
  return html`<nav class="tabs" aria-label="Profile">${TABS.map(([k, label]) => html`<a href="${href(name, k)}"${k === cur ? html` aria-current="page"` : ""}>${label}</a>`)}</nav>`;
}

function read(ctx, path) { return ctx.get(path); }

// ---- Overview ----------------------------------------------------------------------

function stepCard(m, at) {
  if (m.stuck) {
    const d = stuckFor(m, at);
    return html`<div class="pf-stuck"><span class="warn mb-s row"><i class="ph ph-hand-palm" aria-hidden="true"></i>${d ? "Stuck " + d : "Stuck, since not measured"}</span><span class="mb-b">${m.step}</span><span class="muted">${m.blocker}</span></div>`;
  }
  return html`<div class="card"><span class="dim mb-s">Current step</span><span class="mb-b">${m.step || notMeasured()}</span>${m.line && m.line !== m.step ? html`<span class="muted mb-s">${m.line}</span>` : ""}${m.job && m.job !== m.step ? html`<span class="muted mb-s">${m.job}${m.job_answer ? ": " + m.job_answer : ""}</span>` : ""}</div>`;
}

// XP per hour over the last 24 hours, from /api/v2/series: the mean of the
// hours it could measure, or null when it measured none (or did not answer).
function xpRate(ser) {
  const v = ser && ser.xp_per_hour_24h;
  return v === null || v === undefined ? null : v.toLocaleString("en-US");
}

function xpLine(ser) {
  const rate = xpRate(ser);
  if (rate === null) return notMeasured();
  const k = ser.xp_hours_measured;
  return k && k < 24 ? rate + ", over the " + plural(k, "hour") + " measured" : rate;
}

function numbers(arm, bags, ser) {
  const g = arm && arm.member && arm.member.gear;
  const ilvl = g && g.average_item_level !== undefined ? g.average_item_level : null;
  const money = bags && bags.money ? bags.money.gold * 10000 + bags.money.silver * 100 + bags.money.copper : null;
  const fill = bags && bags.total ? Math.round((100 * bags.used) / bags.total) + "% full" : null;
  const cellOf = (k, v) => html`<div class="pf-num"><span class="dim mb-s">${k}</span><span class="mb-b num">${v === null || v === undefined ? notMeasured() : v}</span></div>`;
  return html`<div class="card pf-nums">${cellOf("XP per hour", xpRate(ser))}${cellOf("Item level", ilvl)}${cellOf("Gold", money === null ? null : gold(money))}${cellOf("Bags", fill)}</div>`;
}

function levelLine(act, ser) {
  if (!act) return pendingRead({ data: undefined }, 1);
  const start = act.start_level ?? act.level;
  // One value per hour over the window, so the line's x axis is time.
  const end = act.checked_at || Math.floor(Date.now() / 1000);
  const ups = act.levels || [];
  const values = [];
  for (let h = act.days * 24; h >= 0; h--) {
    const t = end - h * 3600;
    let lv = start;
    ups.forEach((p) => { if (p[0] <= t) lv = p[1]; });
    values.push(lv);
  }
  const gained = (act.level ?? 0) - (start ?? 0);
  const label = gained > 0 ? "Level rose from " + start + " to " + act.level + " over " + act.days + " days" : "No level gained in " + act.days + " days";
  return html`<div class="card"><div class="row mb-between"><span class="dim mb-s">Level, last ${act.days} days</span><span class="muted mb-s">${gained > 0 ? "+" + plural(gained, "level") : "no change"}</span></div>${sparkline(values, { h: 64, fit: true, label })}<div class="row mb-between dim mb-s"><span>${act.days}d ago, L${start ?? "?"}</span><span>now, L${act.level ?? "?"}</span></div><span class="dim mb-s">XP per hour, 24h: ${xpLine(ser)}</span></div>`;
}

function commandRows(list) {
  return list.map((c) => html`<div class="pf-cmd"><span class="dim mb-s">${c.at ? new Date(c.at * 1000).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "time not measured"} | ${c.kind} | ${c.source}</span><span class="pf-cmdtext">${c.command}</span><span class="${c.status === "error" ? "warn mb-s" : "muted mb-s"}">${c.answer}</span></div>`);
}

function family(m, roster) {
  const all = roster.members || [];
  const mine = m.family ? all.filter((x) => x.family === m.family && x.name !== m.name) : all.filter((x) => x.guild === m.guild && x.name !== m.name && x.family).slice(0, 10);
  const title = m.family ? m.family + "'s family" : "The families in " + (m.guild || "the guild");
  const g = all.filter((x) => x.guild === m.guild);
  const online = g.filter((x) => x.online).length;
  const guildHref = /^(cave|bonkers)$/i.test(m.guild || "") ? "#/guilds/" + m.guild.toLowerCase() : "";
  return html`<div class="pf-grid"><div class="card pf-list"><span class="dim mb-s">${title}</span>${mine.length ? mine.map((x) => html`<a class="pf-row" href="${href(x.name)}"><span class="mb-b" style="color:${classVar(x.class)}">${x.name}</span><span class="dim mb-s">L${x.level} ${x.class}</span></a>`) : notMeasured("no one else")}</div><div class="card"><span class="dim mb-s">Guild</span><span class="mb-b">${m.guild || notMeasured("no guild")}</span><span class="muted">${plural(g.length, "member")}, ${online} online</span>${guildHref ? html`<a href="${guildHref}">Open ${m.guild}</a>` : ""}</div></div>`;
}

function overview(ctx, m, roster) {
  const n = q(m.name);
  const act = read(ctx, "/api/v2/activity" + n);
  const arm = read(ctx, "/api/armory/member" + n);
  const bags = read(ctx, "/api/client/bags" + n);
  const ser = read(ctx, "/api/v2/series" + n).data;
  const cmds = act.data ? (act.data.commands || []).slice(0, 3) : [];
  return html`<div class="pf-grid"><div class="pf-col">${stepCard(m, roster.checked_at)}${numbers(arm.data, bags.data, ser)}</div><div class="pf-col">${levelLine(act.data, ser)}<div class="card"><span class="dim mb-s">Recent commands and answers</span>${act.data ? (cmds.length ? commandRows(cmds) : notMeasured("no commands recorded")) : pendingRead(act, 1)}<a href="${href(m.name, "activity")}">All activity</a></div></div></div>${family(m, roster)}`;
}

// ---- Gear and Standing --------------------------------------------------------------------

function spellChip(s, tone) {
  return html`<a class="${"st-spell " + tone}" href="${"https://www.wowhead.com/wotlk/spell=" + s.spell}" target="_blank" rel="noopener"><i class="${tone === "warn" ? "ph ph-coins" : "ph ph-circle"}" aria-hidden="true"></i>Spell ${s.spell} <span class="dim mb-s">L${s.level}${s.cost ? " | " + gold(s.cost) : ""}</span></a>`;
}

function tradeLine(t) {
  const n = t.next;
  const words = {
    learned: "top rank held",
    trainable: n ? "next rank (" + n.cap + ") trainable now, " + gold(n.cost) : "trainable now",
    above: n ? "next rank (" + n.cap + ") at level " + n.level : "above level",
    skill: n ? "needs skill " + n.needs + " for the next rank (" + n.cap + ")" : "needs more skill",
  }[t.state] || t.state;
  const tone = t.state === "trainable" ? "warn" : t.state === "learned" ? "" : "dim";
  return html`<div class="st-trade"><span class="mb-b">${t.name}</span><span class="num">${t.value} / ${t.max}</span><span class="${tone}">${words}</span></div>`;
}

function standing(tr, name) {
  if (!tr) return "";
  const s = tr.spells || {};
  const tradeRows = (tr.trades || []).map(tradeLine);
  return html`<div class="card st-card"><div class="row mb-between"><span class="mb-b">Standing: what ${name} has learned, and has not</span><span class="muted mb-s">${tr.line}</span></div>
<div class="st-groups"><div class="st-group"><span class="mb-kick ok">Learned</span><span>${plural((s.learned || []).length, "class spell")} from the trainer</span></div>
<div class="st-group"><span class="mb-kick warn">Trainable now</span>${(s.trainable || []).length ? html`<span class="muted mb-s">${plural(s.trainable.length, "spell")}, ${gold(s.trainable_cost || 0)} at a class trainer</span><div class="st-spells">${s.trainable.map((x) => spellChip(x, "warn"))}</div>` : html`<span class="muted">nothing waiting at the trainer</span>`}${(s.needs || []).length ? html`<span class="dim mb-s">${plural(s.needs.length, "spell")} at this level need another spell or talent first</span>` : ""}</div>
<div class="st-group"><span class="mb-kick">Above level</span>${(s.above || []).length ? html`<span class="muted mb-s">${plural(s.above.length, "spell")} up to level ${tr.cap}, the next at level ${s.next_level}</span><div class="st-spells">${s.above.slice(0, 8).map((x) => spellChip(x, "dim"))}</div>` : html`<span class="muted">nothing more up to level ${tr.cap}</span>`}</div></div>
${tradeRows.length ? html`<div class="st-trades"><span class="mb-kick">Trades</span>${tradeRows}</div>` : ""}<span class="dim mb-s">${tr.basis}</span></div>`;
}

export function gearTab(ctx, m) {
  const n = q(m.name);
  const arm = read(ctx, "/api/armory/member" + n);
  const tr = read(ctx, "/api/v2/training" + n);
  const wait = pendingRead(arm, 3);
  const data = arm.data || {};
  const card = wait || paperdoll(data.member, data.doll, { bare: true });
  return html`${seg("Gear views", [{ label: "Paperdoll", href: href(m.name, "gear"), current: true }, { label: "Upgrades", href: href(m.name, "upgrades") }])}<div class="pf-gear">${card}</div><div class="pf-gear">${tr.data ? standing(tr.data, m.name) : pendingRead(tr, 1)}</div>`;
}

function upgradesTab(ctx, m) {
  const up = read(ctx, "/api/v2/upgrades" + q(m.name));
  const s = seg("Gear views", [{ label: "Paperdoll", href: href(m.name, "gear") }, { label: "Upgrades", href: href(m.name, "upgrades"), current: true }]);
  if (up.data === undefined && up.error && /404/.test(String(up.error))) return html`${s}${state("empty", "No upgrade list for " + m.name, "The upgrade tracker answers for members present in the world's save.")}`;
  const wait = pendingRead(up, 4);
  if (wait) return html`${s}${wait}`;
  const lq = liveQuery();
  const filter = lq.filter || "all", sort = lq.usort || "slot";
  return html`${s}<div class="up-panel">${upgradesHead(up.data, "")}${upgradesControls(filter, sort)}<div data-region="upslots">${upgradesBody(up.data, filter, sort)}</div>${upgradesFoot(up.data)}</div>`;
}

// ---- Quests -------------------------------------------------------------------------------

const STEP = {
  done: ["var(--ok)", "ph-fill ph-check-circle", "Turned in."],
  ready: ["var(--ok)", "ph ph-check-circle", "Complete, waiting to be handed in."],
  "in progress": ["var(--color-accent-300)", "ph ph-circle-dashed", "In the quest log."],
  blocked: ["var(--warn)", "ph-fill ph-hand-palm", ""],
  open: ["var(--color-neutral-400)", "ph ph-circle", "Open at this level, not taken."],
  locked: ["var(--color-neutral-500)", "ph ph-lock-simple", ""],
};

function chainCard(c, m) {
  return html`<div class="card qs-chain"><span class="row mb-between"><span class="dim mb-s">${m.class} class quest chain: ${c.title}</span>${c.done ? status("best", "Done") : ""}</span>${c.steps.map((s) => {
    const st = STEP[s.state] || STEP.open;
    const note = s.state === "blocked" ? (m.blocker || "Asked the guild for help.") : s.state === "locked" ? "Opens at level " + s.level + "." : st[2];
    return html`<div class="qs-step"><i class="${st[1]}" style="color:${st[0]}" aria-hidden="true"></i><div class="qs-body"><span class="row mb-between"><span class="mb-b">${s.title}</span><span class="mb-s" style="color:${st[0]}">${s.state}</span></span><span class="muted mb-s">${note}</span></div></div>`;
  })}</div>`;
}

function questLog(cq) {
  const mem = cq && cq.member;
  if (!mem) return state("unmeasured", "No quest log", "The quest log was not read for this member.");
  const qs = mem.quests || [];
  return html`<div class="card qs-log"><span class="row mb-between"><span class="dim mb-s">Quest log</span><span class="muted mb-s">${mem.used} of ${mem.slots} slots</span></span>${qs.length ? qs.map((x) => html`<div class="qs-q"><span class="${x.failed ? "bad" : x.ready ? "ok" : ""}">${x.title} <span class="dim mb-s">L${x.level}</span></span><span class="muted mb-s">${x.ready ? "ready to hand in" : x.failed ? "failed" : (x.objectives || []).map((o) => o.have + "/" + o.need + " " + o.what).join(", ") || x.status}</span></div>`) : notMeasured("the log is empty")}</div>`;
}

export function questsTab(ctx, m) {
  const n = q(m.name);
  const chain = read(ctx, "/api/v2/classchain" + n);
  const cq = read(ctx, "/api/client/quests" + n);
  const chains = chain.data ? ((chain.data.chains || []).length ? html`<span class="muted mb-s">${chain.data.line}</span>${chain.data.chains.map((c) => chainCard(c, m))}` : state("empty", "No class quest chain", "The class quest book has no reward chain for this class and race.")) : pendingRead(chain, 2);
  return html`<div class="pf-grid"><div class="pf-col">${chains}</div><div class="pf-col">${cq.data ? questLog(cq.data) : pendingRead(cq, 2)}</div></div>`;
}

// ---- Inventory -------------------------------------------------------------------------------

function invCells(cells) {
  return (cells || []).map((x) => (x
    ? cell({ entry: x.entry, name: x.name, quality: x.quality, icon: x.icon, corner: x.count > 1 ? String(x.count) : "", title: x.name + (x.count > 1 ? " x" + x.count : ""), size: "c44" })
    : emptyCell("", "slot", "Empty slot", "c44")));
}

// Each bag its own small grid under its name and how full it is, as the game
// opens them, so a long inventory reads bag by bag.
function invBags(frame) {
  const bags = (frame.containers || []).filter((c) => (c.cells || []).length);
  return html`<div class="inv-bags">${bags.map((c) => {
    const used = c.cells.filter(Boolean).length;
    return html`<section class="inv-bag" aria-label="${c.name}"><h3 class="inv-bag-head"><span>${c.name}</span><span class="num">${used} of ${c.cells.length}</span></h3><div class="inv-grid">${invCells(c.cells)}</div></section>`;
  })}</div>`;
}

export function inventoryTab(ctx, m, tab) {
  const bank = tab === "bank";
  const r = read(ctx, (bank ? "/api/client/bank" : "/api/client/bags") + q(m.name));
  const s = seg("Inventory", [{ label: "Bags", href: href(m.name, "bags"), current: !bank }, { label: "Bank", href: href(m.name, "bank"), current: bank }]);
  const wait = pendingRead(r, 2);
  if (wait) return html`${s}${wait}`;
  const f = r.data;
  return html`${s}<span class="muted">${bank ? "Bank" : "Bags"}: ${f.used ?? "?"} of ${f.total ?? "?"} slots used | hover or tap an item${!bank && f.money ? " | " + coins(f.money.gold * 10000 + f.money.silver * 100 + f.money.copper) : ""}</span>${f.note ? html`<span class="dim mb-s">${f.note}</span>` : ""}${invBags(f)}`;
}

// ---- Activity ---------------------------------------------------------------------------------

function activityTab(ctx, m) {
  const act = read(ctx, "/api/v2/activity" + q(m.name));
  const wait = pendingRead(act, 3);
  if (wait) return wait;
  const cmds = act.data.commands || [];
  return html`<div class="card pf-activity">${cmds.length ? commandRows(cmds) : notMeasured("no commands recorded")}</div><p class="dim mb-s">The newest ${cmds.length} commands the bridge gave ${m.name}, with the realm's answer. Aura reads are left out.</p>`;
}

// ---- the view --------------------------------------------------------------------------------

function body(ctx, m, roster) {
  const tab = ctx.params.tab;
  if (tab === "gear") return gearTab(ctx, m);
  if (tab === "upgrades") return upgradesTab(ctx, m);
  if (tab === "quests") return questsTab(ctx, m);
  if (tab === "bags" || tab === "bank") return inventoryTab(ctx, m, tab);
  if (tab === "activity") return activityTab(ctx, m);
  return overview(ctx, m, roster);
}

export default {
  css: ["views/members.css"],
  // The roster first: a name it does not hold is not a guild member, and that
  // member's own reads would only be refused. Once the roster is in and holds
  // the name, main.js widens the reads to the tab's.
  reads: (ctx) => {
    const roster = ctx.get("/api/v2/roster").data;
    if (!roster || !byName(roster.members).has(ctx.params.name)) return ["/api/v2/roster"];
    return ["/api/v2/roster"].concat(readsFor(ctx.params.name, ctx.params.tab));
  },
  every: 30000,
  title: (ctx) => ctx.params.name,
  render(ctx) {
    const roster = ctx.get("/api/v2/roster");
    const wait = pendingRead(roster, 3);
    if (wait) return html`<a class="mb-back" href="#/members">Members</a><h1>${ctx.params.name}</h1>${wait}`;
    const m = byName(roster.data.members).get(ctx.params.name);
    if (!m) return html`<a class="mb-back" href="#/members"><i class="ph ph-caret-left" aria-hidden="true"></i>Members</a><h1>${ctx.params.name}</h1>${state("empty", "No member is called " + ctx.params.name, "Names come from the roster the server reports: the families and the guilds they are in.")}`;
    return html`${header(m, roster.data.checked_at)}${tabRow(m.name, ctx.params.tab)}${body(ctx, m, roster.data)}`;
  },
  after(main, ctx) {
    bindTrees(main);
    mountModels(main);
    if (ctx.params.tab === "upgrades") {
      const up = ctx.get("/api/v2/upgrades" + q(ctx.params.name)).data;
      if (up) bindUpgrades(main, up);
    }
  },
};

