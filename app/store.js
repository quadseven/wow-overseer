// Per-device memory: the theme picked, the last page open, and when this
// device last looked. localStorage can be missing or throw (private windows,
// blocked site data), so every read and write is guarded and the app works
// the same without it.

const KEYS = {
  theme: "overseer.theme",
  last: "overseer.last",
  visit: "overseer.visit",
  stage: "overseer.stage",
};

function read(key) {
  try { return window.localStorage.getItem(key); } catch (e) { return null; }
}

function write(key, value) {
  try { window.localStorage.setItem(key, value); } catch (e) { /* storage off */ }
}

export function savedTheme() {
  const t = read(KEYS.theme);
  return t === "light" || t === "dark" ? t : "";
}

export function saveTheme(theme) { write(KEYS.theme, theme); }

export function lastPage() {
  const h = read(KEYS.last) || "";
  return h.startsWith("#/") ? h : "";
}

export function saveLastPage(hash) {
  if (hash && hash.startsWith("#/") && !hash.startsWith("#/operator")) write(KEYS.last, hash);
}

// The visit before this one, read once at boot so "new since your last
// visit" stays put while the page is open; this visit is stamped when the
// page is hidden or left.
const previous = Number(read(KEYS.visit)) || 0;

export function previousVisit() { return previous; }

export function stampVisit() { write(KEYS.visit, String(Date.now())); }

// The family on Now's stage on a phone: its key, or "" for no choice yet.
export function savedStage() { return read(KEYS.stage) || ""; }

export function saveStage(family) { write(KEYS.stage, String(family || "")); }
