// Now: what needs the operator, the realm, the two families, who is live,
// where they are, and (folded on phone) runs, attention, campaigns and the
// last roll. Read-only: the live tiles watch broadcasts that are already
// running and start nothing.

import { html, raw, ago, duration, plural, notMeasured, state, skeletons, STATUS } from "../ui.js";
import * as D from "./now/data.js";
import * as streams from "./now/streams.js";
import * as wm from "./now/worldmap.js";

const READS = ["/api/eye", "/api/v2/roll", "/api/wall", "/api/guildruns", "/api/v2/stuck", "/api/v2/roster", "/api/map", "/shapes.json"];
let foldOpen = null; // null: the default (open on desktop, closed on phone)

function readLayout() {
  try { return window.localStorage.getItem("overseer.wall") === "stacked" ? "stacked" : "side"; } catch (e) { return "side"; }
}
function saveLayout(v) {
  try { window.localStorage.setItem("overseer.wall", v); } catch (e) { /* storage off */ }
}

// ---- status chips -----------------------------------------------------------
function chip(kind, label, href) {
  const s = STATUS[kind];
  return html`<a class="nchip" role="listitem" href="${href}" data-tone="${kind}"><i class="${s[1]}" style="color:${s[2]}" aria-hidden="true"></i>${label}</a>`;
}

function stalledChip(agendas) {
  if (!agendas.every(D.ok)) return chip("stalled", "Stalled families not measured", "#/now/family/grug");
  const stalled = agendas.filter((a) => a.data.stalled);
  const href = "#/now/family/" + (stalled.length ? String(stalled[0].data.family).toLowerCase() : "grug");
  return chip("stalled", plural(stalled.length, "family", "families") + " stalled", href);
}

function stuckChip(st) {
  if (!st) return chip("stuck", "Stuck not measured", "#/members?stuck=1");
  const longest = st.list.length ? (st.longest === null ? ", since not measured" : ", longest " + duration(st.longest)) : "";
  return chip("stuck", st.list.length + " stuck" + longest, "#/members?stuck=1");
}

function ghostChip(gh) {
  return chip("ghost", gh ? plural(gh.length, "ghost") : "Ghosts not measured", "#/members?ghost=1");
}

function chips(ctx, agendas) {
  const runs = D.runsInside(ctx.get("/api/guildruns"));
  const fresh = D.runsNewSince(ctx.get("/api/guildruns"), ctx.previousVisit);
  const list = [
    stalledChip(agendas),
    stuckChip(D.stuck(ctx.get("/api/v2/stuck"))),
    ghostChip(D.ghosts(ctx.get("/api/v2/roster"))),
    runs ? chip("inside", plural(runs.length, "run") + " inside", runs.length ? "#/runs/" + runs[0].id : "#/guilds/cave/runs")
      : chip("inside", "Runs inside not measured", "#/guilds/cave/runs"),
  ];
  if (fresh) list.push(chip("new", plural(fresh, "run") + " new since your last visit", "#/guilds/cave/runs"));
  return html`<div class="nchips" role="list" aria-label="What needs you">${list}</div>`;
}

// ---- realm strip --------------------------------------------------------------
function strip(ctx) {
  const eye = ctx.get("/api/eye");
  const roll = ctx.get("/api/v2/roll");
  const tier = D.ok(eye) ? (eye.data.tiers || []).find((t) => t.tier === "REALM") : null;
  const inWorld = D.ok(eye) ? (eye.data.strip || []).find((s) => s.label === "IN WORLD") : null;
  const up = tier ? tier.state === "ON" : null;
  const ws = tier
    ? html`<span class="rv"><span class="rdot" style="background:${up ? "var(--ok)" : "var(--bad)"}" aria-hidden="true"></span>${up ? "Up" : "Not answering"}</span>`
    : html`<span class="rv">${notMeasured()}</span>`;
  const cell = (k, v) => html`<div class="rcell"><span class="rk">${k}</span>${v}</div>`;
  const r = D.ok(roll) ? roll.data : {};
  return html`<div class="card rstrip">
${cell("Worldserver", ws)}
${cell("Online", html`<span class="rv num">${inWorld ? inWorld.value : notMeasured()}</span>`)}
${cell("Uptime", html`<span class="rv">${r.uptime_seconds === undefined || r.uptime_seconds === null ? notMeasured() : duration(r.uptime_seconds)}</span>`)}
${cell("Build", html`<span class="rv num">${r.build || notMeasured()}</span>`)}
</div>`;
}

// ---- family agendas -------------------------------------------------------------
function agendaCard(fam, read) {
  const href = "#/now/family/" + fam.toLowerCase();
  if (!D.ok(read)) {
    const body = read.data === undefined && !read.error ? skeletons(1) : state("unmeasured", fam + "'s family: agenda not measured", "The agenda read did not answer.");
    return html`<div class="agenda-wait">${body}</div>`;
  }
  const a = read.data;
  const detail = D.detailLines(a);
  const moved = a.moved_seconds === null || a.moved_seconds === undefined ? "not measured" : ago(a.moved_seconds);
  return html`<a class="agenda${a.stalled ? " is-stalled" : ""}" href="${href}">
<span class="agenda-label">${fam}'s family</span>
<span class="agenda-head">${a.headline || "No headline reported"}</span>
${a.queue && a.queue.line ? html`<span class="agenda-line">${a.queue.line}</span>` : ""}
${detail.length ? html`<span class="agenda-line">${detail.join(" ")}</span>` : ""}
<span class="agenda-foot">${a.stalled ? html`<span class="tag tag-warn agenda-tag">STALLED</span><span class="warn">${a.stall_line || "No progress since the walk began."}</span>` : ""}<span class="muted">last moved ${moved}</span></span>
</a>`;
}

// ---- live -----------------------------------------------------------------------
function heads(ctx) {
  const wall = ctx.get("/api/wall");
  if (!D.ok(wall)) return null;
  const fams = D.families(wall.data);
  return D.FAMILY_KEYS.map((f) => D.headOf(fams.get(f) || [], f)).filter(Boolean);
}

function live(ctx) {
  const wall = ctx.get("/api/wall");
  const hs = heads(ctx);
  const layout = readLayout();
  const seg = html`<div class="seg live-seg" role="radiogroup" aria-label="Stream layout">${[["side", "Side by side"], ["stacked", "Stacked"]].map(([k, label]) => html`<button type="button" role="radio" aria-checked="${String(layout === k)}" data-layout="${k}">${label}</button>`)}</div>`;
  let body;
  if (!hs) {
    body = wall.data === undefined && !wall.error ? skeletons(2) : state("error", "The streams did not answer", "The wall read failed, so no tile can be drawn.");
  } else {
    body = html`<div class="live-tiles" data-wall="${layout}">${hs.map((m) => streams.tileHtml(m, D.tileOf(wall.data, m.name)))}</div>`;
  }
  const streamed = hs ? hs.filter((m) => (D.tileOf(wall.data, m.name) || {}).url || m.broadcast_url).length : null;
  return html`<div class="live-head"><h2 class="kicker">Live</h2><span class="dim small">${streamed === null ? "" : streamed + " of " + hs.length + " streamed"}</span>${seg}</div>
${body}
<div class="watcher"><i class="ph ph-video-camera" aria-hidden="true"></i><div><span class="watcher-t">Watcher <span class="tag tag-neutral">Coming soon</span></span><span class="muted">The spectator camera gets a tile here once its stream is published.</span></div></div>`;
}

// ---- mini maps ---------------------------------------------------------------------
function miniMaps(ctx) {
  return html`<div class="minimaps">${D.FAMILY_KEYS.map((f) => html`<a class="minimap" data-minimap="${f}" href="#/now/map"><span class="kicker">Where ${f}'s family is</span><div class="wm wm-compact" data-map-box="${f}"><div class="wm-wait">Unrolling the map...</div></div></a>`)}</div>`;
}

function drawMiniMaps(main, ctx) {
  const shapes = ctx.get("/shapes.json"), map = ctx.get("/api/map"), wall = ctx.get("/api/wall");
  if (!D.ok(shapes) || !D.ok(map) || !D.ok(wall)) {
    if ((shapes.error || map.error || wall.error)) main.querySelectorAll("[data-map-box] .wm-wait").forEach((n) => { n.textContent = "Positions not measured: the map read did not answer."; });
    return;
  }
  const fams = D.families(wall.data);
  const ghostNames = D.ghostNames(ctx.get("/api/v2/roster"));
  D.FAMILY_KEYS.forEach((f) => {
    const box = main.querySelector('[data-map-box="' + f + '"]');
    const link = main.querySelector('[data-minimap="' + f + '"]');
    if (box) drawFamilyMap(box, link, f, fams.get(f) || [], map.data, shapes.data, ghostNames);
  });
}

function drawFamilyMap(box, link, fam, members, map, shapes, ghostNames) {
  const names = new Map(members.map((m) => [m.name, m]));
  const mine = (map.dots || []).filter((d) => names.has(d.name));
  const head = D.headOf(members, fam);
  const at = mine.find((d) => head && d.name === head.name) || mine[0];
  if (!at || !shapes[at.continent]) {
    box.innerHTML = html`<div class="wm-wait">${fam}'s family is not on a continent map right now${mine.length ? "" : " (no position read)"}.</div>`.s;
    return;
  }
  const shape = shapes[at.continent];
  const people = new Map(members.map((m) => [m.name, { family: true, color: m.class_colour, ghost: ghostNames.has(m.name), head: m.leader }]));
  const dots = wm.dotsFor(shape, at.continent, mine, people);
  const c = at.continent === "1" ? "kal" : at.continent === "0" ? "ek" : "";
  if (link) link.setAttribute("href", "#/now/map" + (c ? "?c=" + c : ""));
  const zone = wm.zoneLabel(shape, at.zone);
  wm.draw(box, { key: "mini-" + fam, shape, dots, compact: true, focus: wm.around(shape, dots, true), summary: dots.length + " of " + members.length + " here; " + (head ? head.name : fam) + " in " + zone });
}

// ---- the fold ------------------------------------------------------------------------
function runCard(r, at) {
  const total = Number(r.bosses_total) || 0;
  const pips = [];
  for (let i = 0; i < total; i++) pips.push(html`<span class="pip${i < r.bosses_done ? " on" : ""}"></span>`);
  const seats = (r.members || []).map((m) => m.name).join(", ");
  return html`<a class="card runcard" href="#/runs/${encodeURIComponent(r.id)}">
<div class="runcard-top"><span class="b">${r.guild} | ${r.place || r.keyword}</span><span class="dim small">${duration(r.seconds_inside) || "not measured"} inside</span></div>
${total ? html`<div class="pips" role="img" aria-label="${r.bosses_done} of ${total} bosses down">${pips}</div>` : ""}
<div class="dim small">${total ? r.bosses_done + " of " + total + " bosses down" : "bosses not measured"} | ${seats || "no seats read"} | read ${ago(at ? (Date.now() - at) / 1000 : null)}</div>
</a>`;
}

function runsBlock(ctx) {
  const read = ctx.get("/api/guildruns");
  const runs = D.runsInside(read);
  let body;
  if (runs === null) body = read.data === undefined && !read.error ? skeletons(1) : state("unmeasured", "Guild runs not measured", "The guild runs read did not answer.");
  else if (!runs.length) body = state("empty", "No guild runs inside right now.", "Checked " + ago((Date.now() - read.at) / 1000) + ".");
  else body = runs.map((r) => runCard(r, read.at));
  return html`<div class="fold-col"><h2 class="kicker">Guild runs inside</h2>${body}</div>`;
}

function attention(ctx) {
  const st = D.stuck(ctx.get("/api/v2/stuck"));
  const gh = D.ghosts(ctx.get("/api/v2/roster"));
  const stuckText = st ? plural(st.list.length, "member") + " stuck" : html`Stuck ${notMeasured()}`;
  const longest = st && st.list.length ? (st.longest === null ? "since not measured" : "longest " + duration(st.longest)) : "";
  const ghostText = gh ? plural(gh.length, "ghost") + (gh.length ? ": " + gh.map((g) => g.name).join(", ") : "") : html`Ghosts ${notMeasured()}`;
  return html`<h2 class="kicker">Attention</h2><div class="card rows">
<a class="arow" href="#/members?stuck=1"><i class="ph ph-hand-palm warn" aria-hidden="true"></i><span class="grow">${stuckText}</span><span class="dim small">${longest}</span><i class="ph ph-caret-right dim" aria-hidden="true"></i></a>
<a class="arow" href="#/members?ghost=1"><i class="ph ph-skull bad" aria-hidden="true"></i><span class="grow">${ghostText}</span><i class="ph ph-caret-right dim" aria-hidden="true"></i></a>
</div>`;
}

function campaigns(agendas) {
  const rows = D.FAMILY_KEYS.map((f, i) => {
    const read = agendas[i];
    if (!D.ok(read)) return html`<div class="crow"><span class="b">${f}'s family</span><span class="muted">Campaign ${notMeasured()}</span></div>`;
    const c = D.campaign(read.data);
    if (!c) return html`<div class="crow"><span class="b">${f}'s family</span><span class="muted">No campaign queued.</span></div>`;
    return html`<div class="crow"><div class="crow-top"><span class="b">${f}'s family: ${c.name}</span><span class="dim small nowrap">${c.step ? "step " + c.step : html`step ${notMeasured()}`}</span></div><span class="muted">Next: ${c.next || "nothing queued after it"}</span></div>`;
  });
  return html`<h2 class="kicker">Campaigns</h2><div class="card rows">${rows}</div>`;
}

function lastRoll(ctx) {
  const read = ctx.get("/api/v2/roll");
  let card;
  if (!D.ok(read)) {
    card = read.data === undefined && !read.error ? skeletons(1) : state("unmeasured", "Last roll not measured", "The roll read did not answer.");
  } else {
    const r = read.data;
    const when = r.when_seconds === null || r.when_seconds === undefined ? notMeasured() : ago(r.when_seconds);
    const shipped = Array.isArray(r.shipped) && r.shipped.length
      ? html`<ul class="shipped">${r.shipped.map((s) => html`<li>${s}</li>`)}</ul>`
      : html`<span class="muted">What shipped: ${notMeasured()}</span>`;
    card = html`<div class="card roll"><span class="b num">${r.build || notMeasured()}</span><span class="muted small">Running since ${when}. Channel: ${r.channel || notMeasured()}</span>${shipped}</div>`;
  }
  return html`<div class="fold-col"><h2 class="kicker">Last roll</h2>${card}<div class="fold-btns"><a href="#/now/map" class="btn btn-secondary"><i class="ph ph-map-trifold" aria-hidden="true"></i>World map</a><a href="#/now/server" class="btn btn-secondary"><i class="ph ph-gauge" aria-hidden="true"></i>Server</a></div></div>`;
}

function fold(ctx, agendas) {
  const open = foldOpen === null ? !ctx.isPhone : foldOpen;
  return html`<details class="nfold"${open ? raw(" open") : ""}><summary><i class="ph ph-caret-down" aria-hidden="true"></i>Runs, attention, campaigns, last roll</summary>
<div class="fold-grid">${runsBlock(ctx)}<div class="fold-col">${attention(ctx)}${campaigns(agendas)}</div>${lastRoll(ctx)}</div>
</details>`;
}

export default {
  css: ["views/now.css"],
  reads: () => READS.concat(D.FAMILY_KEYS.map(D.agendaPath)),
  every: 15000,
  title: () => "Now",
  render(ctx) {
    const agendas = D.FAMILY_KEYS.map((f) => ctx.get(D.agendaPath(f)));
    return html`<header class="page-head"><h1>Now</h1></header>
${chips(ctx, agendas)}
${strip(ctx)}
<div class="agendas">${D.FAMILY_KEYS.map((f, i) => agendaCard(f, agendas[i]))}</div>
${live(ctx)}
${miniMaps(ctx)}
${fold(ctx, agendas)}`;
  },
  after(main, ctx) {
    const wall = ctx.get("/api/wall");
    (heads(ctx) || []).forEach((m) => {
      const t = D.tileOf(wall.data, m.name);
      streams.connect(m.name, (t && t.playable !== false && t.url) || m.broadcast_url || "");
    });
    streams.mount(main);
    streams.bind(main);
    drawMiniMaps(main, ctx);
    main.querySelectorAll("button[data-layout]").forEach((b) => b.addEventListener("click", () => {
      saveLayout(b.getAttribute("data-layout"));
      const tilesEl = main.querySelector(".live-tiles");
      if (tilesEl) tilesEl.setAttribute("data-wall", readLayout());
      main.querySelectorAll("button[data-layout]").forEach((x) => {
        const on = x.getAttribute("data-layout") === readLayout();
        x.setAttribute("aria-checked", String(on));
      });
    }));
    const det = main.querySelector(".nfold");
    if (det) det.addEventListener("toggle", () => { foldOpen = det.open; });
  },
};

