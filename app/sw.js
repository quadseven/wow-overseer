// Mount-scoped app-shell worker (#2314): caches the current build's shell
// (page + stylesheets + boot graph) and serves them cache-first, while keeping
// data reads (/api/...), clips, model assets, and non-app paths on the network.

const BASE = "__OVERSEER_BASE__";
const BUILD = "__OVERSEER_BUILD__";
const CACHE_PREFIX = "overseer-shell-";
const CACHE_NAME = CACHE_PREFIX + BUILD;
const PAGE_URL = BASE + "/";
const SHELL_FILES = __OVERSEER_SHELL__;
const PRECACHE_URLS = [PAGE_URL].concat(
  SHELL_FILES.map((file) => BASE + "/app/" + BUILD + "/" + file)
);

function mountRelative(pathname) {
  if (!BASE) return pathname;
  if (pathname === BASE) return "/";
  if (pathname.startsWith(BASE + "/")) return pathname.slice(BASE.length);
  return null;
}

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE_URLS))
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key.startsWith(CACHE_PREFIX) && key !== CACHE_NAME)
          .map((key) => caches.delete(key))
      )
    )
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (!req || req.method !== "GET") return;
  const url = new URL(req.url, self.location.href);
  if (url.origin !== self.location.origin) return;
  const rel = mountRelative(url.pathname);
  if (!rel) return;

  if (rel.startsWith("/app/" + BUILD + "/")) {
    event.respondWith(
      caches.open(CACHE_NAME).then((cache) =>
        cache.match(req).then((hit) => {
          if (hit) return hit;
          return fetch(req).then((res) => {
            if (res && res.ok) cache.put(req, res.clone());
            return res;
          });
        })
      )
    );
    return;
  }

  if (rel === "/" || rel === "/index.html") {
    const refresh = fetch(PAGE_URL)
      .then((res) => {
        if (!res || !res.ok) return res;
        return caches
          .open(CACHE_NAME)
          .then((cache) => cache.put(PAGE_URL, res.clone()).then(() => res));
      })
      .catch(() => null);
    event.waitUntil(refresh);
    event.respondWith(
      caches.open(CACHE_NAME).then((cache) =>
        cache
          .match(PAGE_URL)
          .then((hit) => hit || refresh.then((res) => res || fetch(req)))
      )
    );
  }
});
