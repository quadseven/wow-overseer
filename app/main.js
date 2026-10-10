// Boot: theme, shell, router, fetch layer, search, tooltips and gestures.
//
// A view is a module in app/views/ whose default export is
//   { reads(ctx) -> [paths], every?: ms, quick?: {reads, every}, title?(ctx), render(ctx) -> markup,
//     after?(main, ctx), thumb?(ctx) -> {label, items}, css?: ["views/x.css"] }
// (app/README.md has the whole contract).
// render() draws from ctx.get(path) (what is cached, never a fetch), and is
// called again whenever one of its reads answers with new data.

import * as api from "./api.js";
import * as shell from "./shell.js";
import * as search from "./search.js";
import "./searchv2.js";
import * as tooltip from "./tooltip.js";
import * as gestures from "./gestures.js";
import { legacy, parse, resolve } from "./router.js";
import { savedTheme, saveTheme, lastPage, saveLastPage, stampVisit, previousVisit } from "./store.js";
import { html, ago, plural } from "./ui.js";
import badgeProviders from "./badges.js";

const root = document.getElementById("app");
shell.mount(root);
const main = document.getElementById("main");
const views = new Map();
let current = null;   // {view, module, ctx, reads, hash}
let pulling = false;

// ---- theme ---------------------------------------------------------------
function effectiveTheme() {
  const t = document.documentElement.getAttribute("data-theme");
  if (t === "light" || t === "dark") return t;
  return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

function applyTheme(t) {
  if (t) document.documentElement.setAttribute("data-theme", t);
  // The page's background token, so the bar matches whichever theme won.
  const bg = getComputedStyle(document.documentElement).getPropertyValue("--color-bg").trim();
  if (bg) document.querySelectorAll('meta[name="theme-color"]').forEach((m) => m.setAttribute("content", bg));
}

function toggleTheme() {
  const next = effectiveTheme() === "light" ? "dark" : "light";
  saveTheme(next);
  applyTheme(next);
  drawShell();
}

applyTheme(savedTheme());
window.matchMedia("(prefers-color-scheme: light)").addEventListener("change", () => { applyTheme(savedTheme()); drawShell(); });

// ---- shell -----------------------------------------------------------------
// The reads the data age describes: the view's own, or the realm read for a
// view that has none.
function ageReads() { return current && current.reads.length ? current.reads : ["/api/realm"]; }

function drawShell() {
  shell.update(root, {
    section: current ? current.section : "",
    hash: location.hash || "#/now",
    health: api.health(ageReads()),
    theme: effectiveTheme(),
  });
}

// ---- views -----------------------------------------------------------------
function loadView(name) {
  if (!views.has(name)) {
    views.set(name, import("./views/" + name + ".js").then((m) => m.default));
  }
  return views.get(name);
}

const isPhone = () => window.matchMedia("(max-width: 759.98px)").matches;

// A view's own stylesheet (paths under app/), linked once.
function useCss(path) {
  const href = api.u("/app/" + path);
  if (document.querySelector('link[data-view-css="' + CSS.escape(path) + '"]')) return;
  const link = document.createElement("link");
  link.rel = "stylesheet"; link.href = href; link.setAttribute("data-view-css", path);
  document.head.appendChild(link);
}

function banner(h) {
  if (h.state !== "stale") return "";
  const secs = h.at ? (Date.now() - h.at) / 1000 : null;
  return html`<div class="banner" role="status"><i class="ph ph-clock-countdown" aria-hidden="true"></i><div><div style="font-weight:500">Showing data from ${ago(secs)}</div><div class="muted">The world did not answer the last ${plural(h.failures, "read")}. Nothing below has been refreshed since then.</div></div></div>`;
}

function draw(keepPlace) {
  if (!current) return;
  const { module, ctx } = current;
  const y = window.scrollY;
  const focused = document.activeElement && main.contains(document.activeElement) ? document.activeElement : null;
  const focusKey = focused ? (focused.id || focused.getAttribute("data-focus") || "") : "";
  const caret = focused && typeof focused.selectionStart === "number" ? [focused.selectionStart, focused.selectionEnd] : null;
  const h = api.health(current.reads);
  const pull = pulling ? html`<div class="refreshing" role="status"><i class="ph ph-arrows-clockwise" aria-hidden="true"></i>Refreshing. Data was ${h.at ? ago((Date.now() - h.at) / 1000) : "not read yet"}.</div>` : "";
  main.innerHTML = html`${pull}${banner(h)}${module.render(ctx)}`.s;
  if (module.after) module.after(main, ctx);
  // A view may widen its reads once its first data is in (a member page reads
  // the roster first, then that member's own reads), so they are asked again
  // after every draw and polling follows when they change.
  const next = module.reads(ctx) || [];
  if (next.join("\n") !== current.reads.join("\n")) {
    current.reads = next;
    api.watch(next, module.every || 15000, module.quick);
  }
  if (keepPlace) {
    window.scrollTo(0, y);
    if (focusKey) {
      const el = main.querySelector("#" + CSS.escape(focusKey)) || main.querySelector('[data-focus="' + CSS.escape(focusKey) + '"]');
      if (el) {
        el.focus({ preventScroll: true });
        if (caret && typeof el.setSelectionRange === "function") el.setSelectionRange(caret[0], caret[1]);
      }
    }
  }
  shell.setThumb(root, module.thumb ? module.thumb(ctx) : null);
  drawShell();
}

async function route() {
  let hash = location.hash;
  if (!hash || hash === "#" || hash === "#/") {
    const to = lastPage() || "#/now";
    history.replaceState(null, "", to);
    hash = to;
  }
  const old = legacy(hash);
  if (old) { history.replaceState(null, "", old); hash = old; }
  const parsed = parse(hash);
  const r = resolve(parsed);
  if (r.redirect) { history.replaceState(null, "", r.redirect); return route(); }
  saveLastPage(hash);
  const module = await loadView(r.view);
  (module.css || []).forEach(useCss);
  const ctx = {
    view: r.view, section: r.section, params: r.params, query: parsed.query, hash,
    get: api.peek, isPhone: isPhone(), previousVisit: previousVisit(),
  };
  const reads = module.reads(ctx) || [];
  const fresh = !current || current.hash !== hash;
  current = { view: r.view, section: r.section, module, ctx, reads, hash };
  document.title = (module.title ? module.title(ctx) : "Overseer") + " | Overseer";
  draw(!fresh);
  if (fresh) {
    window.scrollTo(0, 0);
    main.focus({ preventScroll: true });
  }
  api.watch(current.reads, module.every || 15000, module.quick);
}

api.onChange((path, changed) => {
  if (!current) return;
  if (changed && current.reads.includes(path)) draw(true);
  else drawShell();
});

window.addEventListener("hashchange", () => { search.close(true); route(); });

// ---- global controls ---------------------------------------------------------
document.addEventListener("click", (e) => {
  const a = e.target.closest("[data-action]");
  if (!a) return;
  const what = a.getAttribute("data-action");
  if (what === "search") { e.preventDefault(); search.open(); }
  else if (what === "theme") { e.preventDefault(); toggleTheme(); }
  else if (what === "retry") { e.preventDefault(); api.refreshNow(); }
  else if (what === "skip") { e.preventDefault(); main.focus(); }
});

document.addEventListener("keydown", (e) => {
  if (e.key !== "/" || search.isOpen() || e.metaKey || e.ctrlKey || e.altKey) return;
  const tag = (document.activeElement && document.activeElement.tagName) || "";
  if (/^(INPUT|SELECT|TEXTAREA)$/.test(tag) || (document.activeElement && document.activeElement.isContentEditable)) return;
  e.preventDefault();
  search.open();
});

gestures.install(main, {
  onPull(show) { if (show !== pulling) { pulling = show; draw(true); } },
  onRefresh() { pulling = true; draw(true); api.refreshNow().finally(() => { pulling = false; draw(true); }); },
});

tooltip.install();

document.addEventListener("visibilitychange", () => { if (document.hidden) stampVisit(); });
window.addEventListener("pagehide", stampVisit);
// Back on the network: read at once, as api.js does when the page is shown again.
window.addEventListener("online", () => { if (!document.hidden) api.refreshNow(); });
// The data age counts up by the second, between the reads that reset it.
window.setInterval(() => { if (!document.hidden) shell.updateAge(root, api.health(ageReads())); }, shell.AGE_TICK_MS);

// ---- realm tag and operator flag (read once) ------------------------------------
api.load("/api/realm").then((e) => {
  if (e.data && e.data.realm) { shell.setRealmTag(e.data.realm); drawShell(); }
});
api.load("/api/v2/operator").then((e) => {
  shell.setOperator(!!(e.data && e.data.enabled));
  drawShell();
});

// ---- nav badges (badges.js): refreshed every minute, whatever is on screen --
function refreshBadges() {
  if (document.hidden) return;
  badgeProviders.forEach((b) => {
    api.loadAll(b.reads).then(() => {
      shell.setBadge(b.section, b.compute(api.peek, { previousVisit: previousVisit() }));
      drawShell();
    });
  });
}
refreshBadges();
window.setInterval(refreshBadges, 60000);

route();
