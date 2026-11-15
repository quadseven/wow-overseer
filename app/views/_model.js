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
// every draw. On wide screens, stages near the viewport hold a viewer; on a
// phone width, only the single stage nearest the middle of the viewport stays
// live so the phone does not spin up a wall of WebGL contexts at once. Any
// hidden model or backgrounded tab cancels its animation frame loop and
// resumes when visible again.

import { html, iconUrl } from "../ui.js";
import { u } from "../api.js";

// THE VIEWER SCRIPT COMES FROM THIS SERVER, NOT FROM THE MODEL HOST (#1849).
// The host answers 403 to any request with an Origin header, so the page
// cannot pin its copy with an integrity hash, and a script loaded unpinned
// runs with the page's full rights, the operator view's writes among them.
// The server fetches this one build through its model cache and serves it
// only while its SHA-384 matches modelviewer.VIEWER_SHA384; a new build
// changes the path here and the pin there together.
const MODEL_SCRIPT = "/modelviewer/deployment/viewer/c3f890f/viewer.min.js";
const LOAD_TIMEOUT = 10000;
const TURN = 0.0035;
const ASPECT = 0.8;
const DISTANCE = 6;
const PHONE_QUERY = "(max-width: 759.98px)";
const RATIO_TIE = 1e-6;

let viewerReady = null;

export function modelStage(m) {
  if (m.model) controller.models.set(m.name, m.model);
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
    return (await loadScript(u("/jquery.min.js"))) && (await loadScript(u(MODEL_SCRIPT))) && typeof window.ZamModelViewer === "function";
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

// The model turns on its own unless the system asks for reduced motion.
const defaultStillMotion = () =>
  typeof window !== "undefined" && typeof window.matchMedia === "function"
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

const defaultIsPhone = () =>
  typeof window !== "undefined" && typeof window.matchMedia === "function"
    && window.matchMedia(PHONE_QUERY).matches;

const defaultIsHidden = () =>
  typeof document !== "undefined" && Boolean(document.hidden);

function normalizeRect(r) {
  if (!r) return null;
  const left = Number.isFinite(r.left) ? r.left : 0;
  const top = Number.isFinite(r.top) ? r.top : 0;
  const width = Number.isFinite(r.width) ? r.width : Math.max(0, (r.right ?? left) - left);
  const height = Number.isFinite(r.height) ? r.height : Math.max(0, (r.bottom ?? top) - top);
  const right = Number.isFinite(r.right) ? r.right : left + width;
  const bottom = Number.isFinite(r.bottom) ? r.bottom : top + height;
  return { left, top, right, bottom, width, height };
}

function rectIntersectionRatio(rect, viewport) {
  const r = normalizeRect(rect);
  if (!r || r.width <= 0 || r.height <= 0) return 0;
  const vw = (viewport && viewport.width) || 0;
  const vh = (viewport && viewport.height) || 0;
  if (vw <= 0 || vh <= 0) return 0;
  const xo = Math.max(0, Math.min(r.right, vw) - Math.max(r.left, 0));
  const yo = Math.max(0, Math.min(r.bottom, vh) - Math.max(r.top, 0));
  return (xo * yo) / (r.width * r.height);
}

// Pick the single intersecting stage for a phone viewport: highest intersection
// ratio wins, and equal ratios break toward the center of the viewport.
export function pickPhoneStage(candidates, viewport) {
  const vw = (viewport && viewport.width) || 0;
  const vh = (viewport && viewport.height) || 0;
  const mx = vw / 2;
  const my = vh / 2;
  let best = null;
  for (const item of candidates || []) {
    const stage = item && item.stage ? item.stage : item;
    const name = (item && item.name)
      || (stage && typeof stage.getAttribute === "function" && stage.getAttribute("data-model"))
      || "";
    if (!name) continue;
    const rawRect = (item && item.rect)
      || (stage && typeof stage.getBoundingClientRect === "function" ? stage.getBoundingClientRect() : null);
    const rect = normalizeRect(rawRect);
    const ratio = Number.isFinite(item && item.intersectionRatio)
      ? item.intersectionRatio
      : rectIntersectionRatio(rect, viewport);
    if ((item && item.isIntersecting === false) || ratio <= 0) continue;
    const dx = rect ? rect.left + rect.width / 2 - mx : 0;
    const dy = rect ? rect.top + rect.height / 2 - my : 0;
    const dist2 = dx * dx + dy * dy;
    if (!best || ratio > best.ratio + RATIO_TIE || (Math.abs(ratio - best.ratio) <= RATIO_TIE && dist2 < best.dist2)) {
      best = { name, stage, ratio, dist2 };
    }
  }
  return best ? { name: best.name, stage: best.stage, ratio: best.ratio } : null;
}

export function createModelController(deps = {}) {
  const models = new Map(); // name -> the model block from /api/armory
  const live = new Map();   // name -> {key, pane, viewer, held, loaded, rafId, visible}
  const isHidden = deps.isHidden || defaultIsHidden;
  const stillMotion = deps.stillMotion || defaultStillMotion;
  const raf = deps.raf || ((fn) => requestAnimationFrame(fn));
  const caf = deps.caf || ((id) => cancelAnimationFrame(id));
  const createPane = deps.createPane || (() => {
    const p = document.createElement("div");
    p.className = "pd-model";
    return p;
  });
  const onPlace = deps.onPlace || null;
  const onDrop = deps.onDrop || null;

  async function defaultBuildViewer(name, stage, model, entry) {
    if (!(await ensureViewer()) || live.get(name) !== entry) return;
    try {
      const id = model.race * 2 - 1 + model.gender;
      const r = await fetch(u("/modelviewer/") + "meta/charactercustomization/" + id + ".json");
      if (!r.ok) throw new Error("customisation " + r.status);
      const options = (await r.json()).Options || [];
      const host = (entry.pane && entry.pane.parentElement) || stage;
      if (live.get(name) !== entry || !host) return;
      host.appendChild(entry.pane);
      entry.viewer = new window.ZamModelViewer({
        type: 2, contentPath: u("/modelviewer/"), container: window.jQuery(entry.pane), aspect: ASPECT,
        models: { id, type: 16 }, items: model.items,
        charCustomization: { options: customisation(model, options) },
      });
    } catch (err) {
      if (live.get(name) === entry) live.delete(name);
      console.warn("model build failed; the portrait stays", err);
    }
  }

  const buildViewer = deps.buildViewer || defaultBuildViewer;

  function stopLoop(entry) {
    if (!entry || entry.rafId === null) return;
    caf(entry.rafId);
    entry.rafId = null;
  }

  function startLoop(name, entry) {
    if (live.get(name) !== entry || !entry.viewer || entry.rafId !== null) return;
    if (isHidden() || entry.visible === false) return;
    const tick = () => {
      entry.rafId = null;
      if (live.get(name) !== entry || !entry.viewer) return;
      if (isHidden() || entry.visible === false) return;
      const r = entry.viewer.renderer;
      if (r) {
        if (!entry.loaded) {
          const actors = r.actors || [];
          if (actors.length && actors.every((a) => a.loaded)) {
            entry.loaded = true;
            r.distance = DISTANCE;
            const stage = entry.pane && entry.pane.parentElement;
            if (stage) { stage.classList.add("live"); fit(entry, stage); }
          }
        } else if (!entry.held && !r.mouseDown && !stillMotion()) {
          r.azimuth = (r.azimuth + TURN) % (2 * Math.PI);
        }
      }
      entry.rafId = raf(tick);
    };
    entry.rafId = raf(tick);
  }

  function syncLoops() {
    const hidden = isHidden();
    live.forEach((entry, name) => {
      if (hidden || entry.visible === false) stopLoop(entry);
      else if (entry.viewer) startLoop(name, entry);
    });
  }

  function setVisible(name, visible) {
    const entry = live.get(name);
    if (!entry) return;
    entry.visible = Boolean(visible);
    if (!entry.visible || isHidden()) stopLoop(entry);
    else if (entry.viewer) startLoop(name, entry);
  }

  function drop(name) {
    const e = live.get(name);
    if (!e) return false;
    stopLoop(e);
    const stage = e.pane && e.pane.parentElement;
    if (stage && stage.classList && typeof stage.classList.remove === "function") {
      stage.classList.remove("live");
    }
    try { e.viewer && e.viewer.destroy(); } catch (err) { /* already gone */ }
    if (e.pane && typeof e.pane.remove === "function") e.pane.remove();
    live.delete(name);
    if (onDrop) onDrop(name);
    return true;
  }

  function place(stage, name) {
    const model = models.get(name);
    if (!model) return;
    const key = JSON.stringify(model);
    const e = live.get(name);
    if (e && e.key === key) {
      if (e.pane && e.pane.parentElement !== stage && stage && typeof stage.appendChild === "function") {
        stage.appendChild(e.pane);
      }
      if (e.loaded && stage && stage.classList) {
        stage.classList.add("live");
        fit(e, stage);
      }
      e.visible = true;
      if (e.viewer) startLoop(name, e);
      return;
    }
    if (e) drop(name);
    const pane = createPane();
    const entry = { key, pane, viewer: null, held: false, loaded: false, rafId: null, visible: true };
    if (pane && typeof pane.addEventListener === "function") {
      pane.addEventListener("pointerdown", () => { entry.held = true; });
    }
    live.set(name, entry);
    if (stage && typeof stage.appendChild === "function" && pane) stage.appendChild(pane);
    if (onPlace) onPlace(name);
    Promise.resolve(buildViewer(name, stage, model, entry)).then(() => {
      if (live.get(name) === entry && entry.viewer) startLoop(name, entry);
    });
  }

  function reconcilePhone(candidates, viewport) {
    const winner = pickPhoneStage(candidates, viewport);
    const keep = winner ? winner.name : null;
    Array.from(live.keys()).forEach((name) => {
      if (name !== keep) drop(name);
    });
    if (winner) place(winner.stage, winner.name);
    return keep;
  }

  function reconcileWide(entries) {
    (entries || []).forEach((item) => {
      const stage = item && item.stage ? item.stage : item;
      const name = (item && item.name)
        || (stage && typeof stage.getAttribute === "function" && stage.getAttribute("data-model"))
        || "";
      if (!name) return;
      if (item.isIntersecting) place(stage, name);
      else drop(name);
    });
  }

  return {
    models,
    live,
    place,
    drop,
    setVisible,
    syncLoops,
    reconcilePhone,
    reconcileWide,
  };
}

const controller = createModelController();
let trackedStages = [];
const phoneEntries = new WeakMap();
const boundRows = new WeakSet();
let listenersBound = false;
let lastPhoneMode = null;
let phoneScrollRaf = null;

const browserViewport = () => ({
  width: typeof window !== "undefined" ? window.innerWidth || 0 : 0,
  height: typeof window !== "undefined" ? window.innerHeight || 0 : 0,
});

function syncPhoneStages(useDomRects) {
  if (!trackedStages.length) return;
  const vp = browserViewport();
  const candidates = trackedStages.map((stage) => {
    const name = stage.getAttribute("data-model");
    const seenEntry = phoneEntries.get(stage);
    const rect = typeof stage.getBoundingClientRect === "function"
      ? stage.getBoundingClientRect()
      : (seenEntry && seenEntry.rect);
    let ratio;
    if (useDomRects) {
      ratio = rectIntersectionRatio(rect, vp);
      phoneEntries.set(stage, { ratio, isIntersecting: ratio > 0, rect });
    } else if (seenEntry) {
      ratio = seenEntry.ratio;
    }
    return { name, stage, rect, intersectionRatio: ratio };
  });
  controller.reconcilePhone(candidates, vp);
}

function schedulePhoneSync() {
  if (phoneScrollRaf !== null || !defaultIsPhone() || !trackedStages.length) return;
  phoneScrollRaf = requestAnimationFrame(() => {
    phoneScrollRaf = null;
    if (defaultIsPhone() && trackedStages.length) syncPhoneStages(true);
  });
}

const wideSeen = typeof IntersectionObserver === "function"
  ? new IntersectionObserver((list) => {
      if (defaultIsPhone()) return;
      controller.reconcileWide(
        list.map((e) => ({ name: e.target.getAttribute("data-model"), stage: e.target, isIntersecting: e.isIntersecting }))
      );
    }, { rootMargin: "400px 0px" })
  : null;

const phoneSeen = typeof IntersectionObserver === "function"
  ? new IntersectionObserver((list) => {
      list.forEach((e) => {
        phoneEntries.set(e.target, {
          ratio: e.isIntersecting ? e.intersectionRatio : 0,
          isIntersecting: e.isIntersecting,
          rect: e.boundingClientRect,
        });
      });
      if (defaultIsPhone()) syncPhoneStages(false);
    }, { rootMargin: "0px", threshold: [0, 0.1, 0.25, 0.5, 0.75, 0.9, 1] })
  : null;

function observeAll() {
  if (wideSeen) wideSeen.disconnect();
  if (phoneSeen) phoneSeen.disconnect();
  const phone = defaultIsPhone();
  lastPhoneMode = phone;
  const activeObserver = phone ? phoneSeen : wideSeen;
  trackedStages.forEach((stage) => {
    if (activeObserver) activeObserver.observe(stage);
  });
  if (phone && trackedStages.some((s) => {
    const r = typeof s.getBoundingClientRect === "function" ? s.getBoundingClientRect() : null;
    return r && r.width > 0 && r.height > 0;
  })) {
    syncPhoneStages(true);
  }
}

function bindListeners() {
  if (listenersBound || typeof window === "undefined" || typeof document === "undefined") return;
  listenersBound = true;
  // One listener for every stage: a released pointer lets each model turn again.
  window.addEventListener("pointerup", () => controller.live.forEach((e) => { e.held = false; }));
  // After every route change, a viewer whose pane is no longer on the page is dropped.
  window.addEventListener("hashchange", () => {
    window.setTimeout(() => {
      Array.from(controller.live.entries()).forEach(([name, e]) => {
        if (!e.pane || !document.contains(e.pane)) controller.drop(name);
      });
    }, 1500);
  });
  document.addEventListener("visibilitychange", () => controller.syncLoops());
  window.addEventListener("scroll", schedulePhoneSync, { passive: true });
  window.addEventListener("resize", () => {
    controller.live.forEach((e) => fit(e, e.pane && e.pane.parentElement));
    const phone = defaultIsPhone();
    if (lastPhoneMode !== null && phone !== lastPhoneMode && trackedStages.length) {
      observeAll();
    } else if (phone) {
      schedulePhoneSync();
    }
  });
}

// After every draw: put each kept viewer back into its new stage, and watch
// the stages so only those near the screen hold one (or on a phone, only the
// single stage nearest the middle of the viewport).
export function mountModels(root) {
  bindListeners();
  if (!wideSeen && !phoneSeen) return;
  trackedStages = Array.from(root.querySelectorAll("[data-model]"));
  const names = new Set();
  trackedStages.forEach((stage) => {
    const name = stage.getAttribute("data-model");
    names.add(name);
    const e = controller.live.get(name);
    if (e && e.pane && e.pane.parentElement !== stage) stage.appendChild(e.pane);
    if (e && e.loaded) stage.classList.add("live");
  });
  Array.from(controller.live.keys()).forEach((n) => {
    if (!names.has(n)) controller.drop(n);
  });
  if (typeof root.querySelectorAll === "function") {
    root.querySelectorAll(".pd-row").forEach((row) => {
      if (boundRows.has(row)) return;
      boundRows.add(row);
      row.addEventListener("scroll", schedulePhoneSync, { passive: true });
    });
  }
  observeAll();
}
