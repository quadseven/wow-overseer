// The world map: Kalimdor or the Eastern Kingdoms, drawn from shapes.json,
// with both families and their guildmates placed from /api/map. Drag to pan,
// wheel or the buttons to zoom, a dot opens the member.

import { html, raw, plural, state, classVar } from "../ui.js";
import * as D from "./now/data.js";
import * as wm from "./now/worldmap.js";

const READS = ["/shapes.json", "/api/map", "/api/wall", "/api/guildgear", "/api/v2/roster"];
const PICK = [["kal", "Kalimdor"], ["ek", "Eastern Kingdoms"]];

const pickOf = (ctx) => (ctx.params.continent === "ek" ? "ek" : "kal");

// name -> {family, color, ghost, head} for both families and every guildmate.
function people(ctx) {
  const out = new Map();
  // Ghost state is the roster's: neither the wall nor guildgear carries it.
  const ghosts = D.ghostNames(ctx.get("/api/v2/roster"));
  const gear = ctx.get("/api/guildgear");
  if (D.ok(gear)) {
    (gear.data.guilds || []).forEach((g) => (g.members || []).forEach((m) => {
      out.set(m.name, { family: false, color: wm.MATE, ghost: ghosts.has(m.name), head: false, guild: g.name, cls: classVar(m["class"]) });
    }));
  }
  const wall = ctx.get("/api/wall");
  if (D.ok(wall)) {
    (wall.data.members || []).forEach((m) => {
      out.set(m.name, { family: true, color: m.class_colour || wm.MATE, ghost: ghosts.has(m.name), head: m.role === "father" || m.role === "chief" || m.leader === true, cls: classVar(m["class"]) });
    });
  }
  return out;
}

function model(ctx) {
  const shapes = ctx.get("/shapes.json"), map = ctx.get("/api/map"), wall = ctx.get("/api/wall");
  if (!D.ok(shapes) || !D.ok(map)) return null;
  const cont = wm.CONTINENT[pickOf(ctx)];
  const shape = shapes.data[cont];
  // A shapes file without this continent cannot be drawn on; say so.
  if (!shape) return { missing: true };
  const who = people(ctx);
  const dots = wm.dotsFor(shape, cont, map.data.dots, who);
  const placed = new Set((map.data.dots || []).map((d) => d.name));
  const members = D.ok(wall) ? wall.data.members || [] : [];
  const fallback = wm.fallbackDots(shape, placed, members);
  return { shape, shapes: shapes.data, cont, who, dots: dots.concat(fallback), map: map.data, members };
}

function familyLine(m) {
  const fams = D.families({ members: m.members });
  const parts = D.FAMILY_KEYS.map((f) => {
    const head = D.headOf(fams.get(f) || [], f);
    const dot = head && (m.map.dots || []).find((d) => d.name === head.name);
    if (!dot) return f + "'s family is not placed";
    if (dot.instance) return f + "'s family is inside " + dot.zone;
    const there = m.shapes[dot.continent];
    if (!there) return f + "'s family is off these maps";
    return f + "'s family is in " + wm.zoneLabel(there, dot.zone) + (dot.continent === m.cont ? "" : " (" + there.name + ")");
  });
  return parts.join(", ") + ". Drag to pan, scroll or use the buttons to zoom, tap a dot to open the member.";
}

function whereList(m) {
  const byZone = new Map();
  m.dots.forEach((d) => {
    const label = wm.zoneLabel(m.shape, d.zone);
    if (!byZone.has(label)) byZone.set(label, []);
    byZone.get(label).push(d);
  });
  const zones = [...byZone.entries()].sort((a, b) => b[1].length - a[1].length);
  if (!zones.length) return state("empty", "None of ours is on this continent right now.");
  return html`<div class="where">${zones.map(([zone, ds]) => html`<div class="card where-card"><span class="b">${zone}</span><span class="where-who">${ds.sort((a, b) => Number(b.family) - Number(a.family)).map((d) => {
    const p = m.who.get(d.name) || {};
    return html`<a href="#/m/${encodeURIComponent(d.name)}" style="color:${p.cls || "var(--color-text)"}"${d.family ? raw(' class="b"') : ""}>${d.name}${d.ghost ? " (ghost)" : ""}${d.fallback ? " (zone centre, position not read)" : ""}</a>`;
  })}</span></div>`)}</div>`;
}

export default {
  css: ["views/now.css", "views/map.css"],
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
    return html`${head}<p class="lead">${familyLine(m)}</p>
<div class="wm" data-map-box="full"></div>
${D.ok(gear) ? "" : html`<p class="dim small">Guildmates are not marked: the guild roster read did not answer.</p>`}
${m.map.unplaced ? html`<p class="dim small">${plural(m.map.unplaced, "character")} in the world could not be placed on any map.</p>` : ""}
${whereList(m)}`;
  },
  after(main, ctx) {
    const box = main.querySelector('[data-map-box="full"]');
    const m = model(ctx);
    if (!box || !m || m.missing) return;
    const counts = new Map();
    m.dots.forEach((d) => counts.set(d.zone, (counts.get(d.zone) || []).concat(d.name)));
    const summary = plural(m.dots.length, "of ours", "of ours") + " on this continent";
    wm.draw(box, {
      key: "full-" + m.cont, shape: m.shape, dots: m.dots, compact: false, focus: null, summary,
      whoIn: (zone) => wm.zoneLabel(m.shape, zone) + (counts.get(zone) ? ": " + counts.get(zone).join(", ") : ""),
    });
  },
};
