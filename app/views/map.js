// The world map: Kalimdor or the Eastern Kingdoms, drawn from shapes.json,
// with both families and their guildmates placed from /api/map. Drag to pan,
// wheel or the buttons to zoom, a dot opens the member.

import { html, raw, plural, state, classVar } from "../ui.js";
import * as D from "./now/data.js";
import * as wm from "./now/worldmap.js";
import { notice as watchNotice, bind as bindWatch, CSS as WATCH_CSS, READ as WATCH_READ, OPERATOR as WATCH_OPERATOR } from "./_spectate.js";
import { roster as rosterModel } from "../models/roster.js";
import { wall as wallModel } from "../models/wall.js";

const READS = ["/shapes.json", "/api/map", "/api/wall", "/api/guildgear", "/api/v2/roster", WATCH_READ, WATCH_OPERATOR];
const PICK = [["kal", "Kalimdor"], ["ek", "Eastern Kingdoms"]];

const pickOf = (ctx) => (ctx.params.continent === "ek" ? "ek" : "kal");

// name -> {family, color, ghost, head} for both families and every guildmate.
function people(ctx) {
  const out = new Map();
  // Ghost state is the roster's: neither the wall nor guildgear carries it.
  const ghosts = rosterModel(ctx.get("/api/v2/roster")).ghostNames();
  const gear = ctx.get("/api/guildgear");
  if (D.ok(gear)) {
    (gear.data.guilds || []).forEach((g) => (g.members || []).forEach((m) => {
      out.set(m.name, { family: false, color: wm.MATE, ghost: ghosts.has(m.name), head: false, guild: g.name, cls: classVar(m["class"]) });
    }));
  }
  wallModel(ctx.get("/api/wall")).members.forEach((m) => {
    out.set(m.name, { family: true, color: m.class_colour || wm.MATE, ghost: ghosts.has(m.name), head: m.role === "father" || m.role === "chief" || m.leader === true, cls: classVar(m["class"]) });
  });
  return out;
}

let cachedModel = null;

function model(ctx) {
  const pick = pickOf(ctx);
  const shapes = ctx.get("/shapes.json"), map = ctx.get("/api/map"), wallRead = ctx.get("/api/wall");
  if (!D.ok(shapes) || !D.ok(map)) return null;
  const gear = ctx.get("/api/guildgear"), roster = ctx.get("/api/v2/roster");
  if (
    cachedModel &&
    cachedModel.pick === pick &&
    cachedModel.shapesData === shapes.data &&
    cachedModel.mapData === map.data &&
    cachedModel.wallData === wallRead.data &&
    cachedModel.gearData === gear.data &&
    cachedModel.rosterData === roster.data
  ) {
    return cachedModel.value;
  }
  const wall = wallModel(wallRead);
  const cont = wm.CONTINENT[pick];
  const shape = shapes.data[cont];
  // A shapes file without this continent cannot be drawn on; say so.
  const value = !shape ? { missing: true } : (() => {
    const who = people(ctx);
    const dots = wm.dotsFor(shape, cont, map.data.dots, who);
    const placed = new Set((map.data.dots || []).map((d) => d.name));
    const fallback = wm.fallbackDots(shape, placed, wall.members);
    const all = dots.concat(fallback);
    // The count splits honestly: a fallback dot is a position not read,
    // and a member inside an instance is not standing in the open world.
    const counts = {
      placed: all.filter((d) => !d.fallback && !d.instance).length,
      instanced: all.filter((d) => !d.fallback && d.instance).length,
      unread: all.filter((d) => d.fallback).length,
    };
    // Ours on a continent this map cannot draw (its id is neither of
    // the two drawn ones): named on the page, never silently absent.
    const drawable = new Set(Object.values(wm.CONTINENT));
    const offMap = (map.data.dots || [])
      .filter((d) => !drawable.has(String(d.continent)) && who.has(d.name))
      .map((d) => ({ name: d.name, continent: String(d.continent) }));
    return { shape, shapes: shapes.data, cont, who, dots: all, map: map.data, wall, counts, offMap };
  })();
  cachedModel = {
    pick, shapesData: shapes.data, mapData: map.data,
    wallData: wallRead.data, gearData: gear.data, rosterData: roster.data,
    value,
  };
  return value;
}

// The continents /api/map reports that this page cannot draw, named the
// way a reader names them.
const OFF_CONTINENT = { quelthalas: "Quel'Thalas", azuremyst: "Azuremyst Isles", "530": "Outland" };

function offMapText(offMap) {
  const by = new Map();
  offMap.forEach((d) => {
    if (!by.has(d.continent)) by.set(d.continent, []);
    by.get(d.continent).push(d.name);
  });
  return [...by.entries()]
    .map(([c, names]) => names.join(", ") + " (" + (OFF_CONTINENT[c] || c) + ")")
    .join("; ");
}

// One chip per family: where its head is, how many of them are on this
// continent, and a tap centres the map on them.
function familyChips(m) {
  const here = new Set(m.dots.map((d) => d.name));
  const chips = D.familyKeys().map((f) => {
    const head = m.wall.head(f);
    const mine = (m.wall.families().get(f) || []).filter((x) => here.has(x.name)).length;
    const dot = head && (m.map.dots || []).find((d) => d.name === head.name);
    let where;
    if (!dot) where = "not placed";
    else if (dot.instance) where = "inside " + dot.zone;
    else {
      const there = m.shapes[dot.continent];
      where = !there ? "off these maps" : wm.zoneLabel(there, dot.zone) + (dot.continent === m.cont ? "" : " (" + there.name + ")");
    }
    return html`<button type="button" class="wm-chip" data-fam="${f}"${mine ? "" : raw(" disabled")}>${f}'s family · ${where} · ${mine} here</button>`;
  });
  return html`<div class="wm-chips">${chips}</div>`;
}

// Where cards opened in full, by zone label; a card shows 8 names until
// its show-all is tapped.
const shownZones = new Set();

function whereList(m) {
  const byZone = new Map();
  m.dots.forEach((d) => {
    const label = wm.zoneLabel(m.shape, d.zone);
    if (!byZone.has(label)) byZone.set(label, []);
    byZone.get(label).push(d);
  });
  const zones = [...byZone.entries()].sort((a, b) => b[1].length - a[1].length);
  if (!zones.length) return state("empty", "None of ours is on this continent right now.");
  return html`<div class="where">${zones.map(([zone, ds]) => {
    const sorted = ds.sort((a, b) => Number(b.family) - Number(a.family));
    const open = shownZones.has(zone);
    const shown = open ? sorted : sorted.slice(0, 8);
    return html`<div class="card where-card"><span class="b">${zone}</span><span class="dim small">${ds.length} here</span><span class="where-who">${shown.map((d) => {
      const p = m.who.get(d.name) || {};
      return html`<span class="where-one"><a href="#/m/${encodeURIComponent(d.name)}" style="color:${p.cls || "var(--color-text)"}"${d.family ? raw(' class="b"') : ""}>${d.name}${d.ghost ? " (ghost)" : ""}${d.fallback ? " (zone centre, position not read)" : ""}</a></span>`;
    })}</span>${!open && sorted.length > 8 ? html`<button type="button" class="btn btn-secondary where-more" data-showall="${zone}">Show all ${sorted.length}</button>` : ""}</div>`;
  })}</div>`;
}

export default {
  css: ["views/now.css", "views/map.css", WATCH_CSS],
  reads: () => READS,
  every: 15000,
  title: () => "World map",
  render(ctx) {
    const pick = pickOf(ctx);
    const m = model(ctx);
    const seg = html`<nav class="seg" aria-label="Continent">${PICK.map(([k, label]) => html`<a href="#/now/map?c=${k}"${k === pick ? raw(' aria-current="page"') : ""}>${label}</a>`)}</nav>`;
    const head = html`<a class="back" href="#/now"><i class="ph ph-caret-left" aria-hidden="true"></i>Now</a><div class="head-row"><h1>World map</h1>${seg}</div>`;
    if (!m) {
      const failed = ctx.get("/api/map").error || ctx.get("/shapes.json").error;
      return html`${head}${failed ? state("error", "The world did not answer", "Positions come from /api/map, which did not answer, so no dot is drawn.") : html`<div class="wm"><div class="wm-wait">Unrolling the map...</div></div>`}`;
    }
    if (m.missing) return html`${head}${state("unmeasured", "This continent is not drawn", "shapes.json has no shape for it, so no position can be placed on it.")}`;
    const gear = ctx.get("/api/guildgear");
    return html`${head}${familyChips(m)}
<div class="wm" data-map-box="full"></div>
<p class="dim small wm-hint">Drag to pan. Pinch or use the buttons to zoom. Tap a dot for the member, tap a zone to see who is in it.</p>
${D.ok(gear) ? "" : html`<p class="dim small">Guildmates are not marked: the guild roster read did not answer.</p>`}
<p class="dim small">Of ours on this continent: ${m.counts.placed} placed · ${m.counts.instanced} in an instance · ${m.counts.unread} position not read.</p>
${m.offMap.length ? html`<p class="dim small">Not on a map this page draws: ${offMapText(m.offMap)}.</p>` : ""}
${m.map.unplaced ? html`<p class="dim small">${plural(m.map.unplaced, "character")} in the world could not be placed on any map.</p>` : ""}
${watchNotice()}${whereList(m)}`;
  },
  after(main, ctx) {
    bindWatch(main);
    const m = model(ctx);
    if (!m || m.missing) return;
    main.querySelectorAll("[data-fam]").forEach((b) => b.addEventListener("click", () => {
      const names = new Set((m.wall.families().get(b.getAttribute("data-fam")) || []).map((x) => x.name));
      const pts = m.dots.filter((d) => names.has(d.name));
      const vb = pts.length && wm.around(m.shape, pts, false);
      if (!vb) return;
      wm.setView("full-" + m.cont, m.shape, vb);
      window.dispatchEvent(new Event("overseer:redraw"));
    }));
    main.querySelectorAll("[data-showall]").forEach((b) => b.addEventListener("click", () => {
      shownZones.add(b.getAttribute("data-showall"));
      window.dispatchEvent(new Event("overseer:redraw"));
    }));
    const box = main.querySelector('[data-map-box="full"]');
    if (!box) return;
    const counts = new Map();
    m.dots.forEach((d) => {
      let list = counts.get(d.zone);
      if (!list) {
        list = [];
        counts.set(d.zone, list);
      }
      list.push(d.name);
    });
    const summary = "Of ours here: " + m.counts.placed + " placed, " + m.counts.instanced + " in an instance, " + m.counts.unread + " position not read";
    wm.draw(box, {
      key: "full-" + m.cont, shape: m.shape, dots: m.dots, compact: false, focus: null, summary,
      whoIn: (zone) => wm.zoneLabel(m.shape, zone) + (counts.get(zone) ? ": " + counts.get(zone).join(", ") : ""),
    });
  },
};
