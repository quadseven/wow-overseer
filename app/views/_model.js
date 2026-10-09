// The paperdoll's model stage: the classic Armory's 3D viewer, reused.
//
// The same viewer build, the same /modelviewer/ cache and the same rules as
// classic.html's model code (infra#88, #3488, #3510): Wowhead's script draws a
// 3.3.5 character, its data comes only through this server's own cache, jQuery
// is served from here, and every failure leaves the race portrait where it is.
// A drag turns the model; it turns slowly on its own until touched.
//
// WHAT IS DIFFERENT HERE. A view redraws by replacing its markup, and a
// viewer owns a WebGL canvas that must not be rebuilt every poll. So each
// stage is a placeholder (data-model="<name>") and the live pane, with its
// canvas, is kept in this module and moved into the new placeholder after
// every draw. Only stages near the screen hold a viewer: a browser keeps only
// so many WebGL contexts alive, and ten cards would pass the limit.

import { html, iconUrl } from "../ui.js";
import { u } from "../api.js";

const MODEL_SCRIPT = "https://wow.zamimg.com/modelviewer/wrath/deployment/viewer/c3f890f/viewer.min.js";
const LOAD_TIMEOUT = 10000;
const TURN = 0.0035;
const ASPECT = 0.8;
const DISTANCE = 6;

const models = new Map();  // name -> the model block from /api/armory
const live = new Map();    // name -> {key, pane, viewer, held, loaded}
let viewerReady = null;
let resizeBound = false;

export function modelStage(m) {
  if (m.model) models.set(m.name, m.model);
  const p = m.portrait || {};
  return html`<div class="pd-stage" data-model="${m.name}" data-no-swipe><div class="pd-portrait">${p.race_icon ? html`<img src="${iconUrl(p.race_icon)}" alt="" width="96" height="96">` : html`<i class="ph ph-person-simple" aria-hidden="true"></i>`}<span class="dim mb-s">${m.model ? "3D model, drag to turn" : "No model to draw"}</span></div></div>`;
}

function loadScript(src) {
  return new Promise((resolve) => {
    const s = document.createElement("script");
    const timer = setTimeout(() => { s.remove(); resolve(false); }, LOAD_TIMEOUT);
    s.onload = () => { clearTimeout(timer); resolve(true); };
    s.onerror = () => { clearTimeout(timer); s.remove(); resolve(false); };
    s.src = src;
    document.head.appendChild(s);
  });
}

function ensureViewer() {
  if (viewerReady) return viewerReady;
  viewerReady = (async () => {
    window.WH = window.WH || {};
    const WH = window.WH;
    WH.debug = WH.debug || (() => {});
    WH.defaultAnimation = WH.defaultAnimation || "Stand";
    WH.WebP = WH.WebP || { getImageExtension: () => ".webp" };
    return (await loadScript(u("/jquery.min.js"))) && (await loadScript(MODEL_SCRIPT)) && typeof window.ZamModelViewer === "function";
  })();
  return viewerReady;
}

// The five numbers the world stores for a face, matched to the viewer's
// option names for the race and gender (classic.html's appearanceKey).
function appearanceKey(optionName, names) {
  if (optionName === "Skin Color") return "skin";
  if (optionName === "Face") return "face";
  if (optionName === "Hair Style") return "hairStyle";
  if (optionName === "Hair Color") return "hairColor";
  if (optionName === "Horn Style" && !names.includes("Hair Style")) return "hairStyle";
  if (optionName === "Horn Color" && !names.includes("Hair Color")) return "hairColor";
  return "facialStyle";
}

function customisation(model, options) {
  const names = options.map((o) => o.Name);
  return options.map((o) => {
    const choice = o.Choices[model[appearanceKey(o.Name, names)]] || o.Choices[0];
    return { optionId: o.Id, choiceId: choice.Id };
  });
}

function fit(entry, stage) {
  const r = entry.viewer && entry.viewer.renderer;
  if (!r || !stage) return;
  const w = Math.round(stage.clientWidth), h = Math.round(stage.clientHeight);
  if (w && h && (r.width !== w || r.height !== h)) r.onResize(w, h, w / h);
}

function drop(name) {
  const e = live.get(name);
  if (!e) return;
  try { e.viewer && e.viewer.destroy(); } catch (err) { /* already gone */ }
  if (e.pane) e.pane.remove();
  live.delete(name);
}

function watch(name, entry) {
  const tick = () => {
    if (live.get(name) !== entry || !entry.viewer) return;
    const r = entry.viewer.renderer;
    if (r) {
      if (!entry.loaded) {
        const actors = r.actors || [];
        if (actors.length && actors.every((a) => a.loaded)) {
          entry.loaded = true;
          r.distance = DISTANCE;
          const stage = entry.pane.parentElement;
          if (stage) { stage.classList.add("live"); fit(entry, stage); }
        }
      } else if (!entry.held && !r.mouseDown) {
        r.azimuth = (r.azimuth + TURN) % (2 * Math.PI);
      }
    }
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

async function build(name, stage, model, key) {
  const entry = { key, pane: document.createElement("div"), viewer: null, held: false, loaded: false };
  entry.pane.className = "pd-model";
  entry.pane.addEventListener("pointerdown", () => { entry.held = true; });
  window.addEventListener("pointerup", () => { entry.held = false; });
  live.set(name, entry);
  if (!(await ensureViewer()) || live.get(name) !== entry) return;
  try {
    const id = model.race * 2 - 1 + model.gender;
    const r = await fetch(u("/modelviewer/") + "meta/charactercustomization/" + id + ".json");
    if (!r.ok) throw new Error("customisation " + r.status);
    const options = (await r.json()).Options || [];
    const host = entry.pane.parentElement || stage;
    if (live.get(name) !== entry || !host) return;
    host.appendChild(entry.pane);
    entry.viewer = new window.ZamModelViewer({
      type: 2, contentPath: u("/modelviewer/"), container: window.jQuery(entry.pane), aspect: ASPECT,
      models: { id, type: 16 }, items: model.items,
      charCustomization: { options: customisation(model, options) },
    });
    watch(name, entry);
  } catch (err) {
    live.delete(name);
    console.warn("model build failed; the portrait stays", err);
  }
}

const seen = typeof IntersectionObserver === "function" ? new IntersectionObserver((list) => {
  list.forEach((e) => {
    const name = e.target.getAttribute("data-model");
    if (e.isIntersecting) place(e.target, name);
    else drop(name);
  });
}, { rootMargin: "400px 0px" }) : null;

function place(stage, name) {
  const model = models.get(name);
  if (!model) return;
  const key = JSON.stringify(model);
  const e = live.get(name);
  if (e && e.key === key) {
    if (e.pane.parentElement !== stage) stage.appendChild(e.pane);
    if (e.loaded) { stage.classList.add("live"); fit(e, stage); }
    return;
  }
  if (e) drop(name);
  build(name, stage, model, key);
  const fresh = live.get(name);
  if (fresh) stage.appendChild(fresh.pane);
}

// After every draw: put each kept viewer back into its new stage, and watch
// the stages so only those near the screen hold one.
export function mountModels(root) {
  if (!seen) return;
  seen.disconnect();
  const names = new Set();
  root.querySelectorAll("[data-model]").forEach((stage) => {
    const name = stage.getAttribute("data-model");
    names.add(name);
    const e = live.get(name);
    if (e && e.pane.parentElement !== stage) stage.appendChild(e.pane);
    if (e && e.loaded) stage.classList.add("live");
    seen.observe(stage);
  });
  Array.from(live.keys()).forEach((n) => { if (!names.has(n)) drop(n); });
  if (!resizeBound) {
    resizeBound = true;
    window.addEventListener("resize", () => live.forEach((e) => fit(e, e.pane.parentElement)));
  }
}
