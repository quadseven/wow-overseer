// Spell names, asked for only when a page draws one.
//
// The catalog (models/spellnames.js) is a generated table of about 220 KB.
// A view that draws a spell imports this small module instead, so the
// catalog is not a static import of any page: it is fetched the first time
// a name is asked for.
//
// - Loaded: spellName answers from the catalog.
// - Not loaded yet: it answers "Spell N", the same words the catalog gives
//   an id it does not know, starts the load, and asks for one redraw
//   (overseer:redraw, main.js) when the catalog arrives.
// - Load failed: it keeps answering "Spell N" and no redraw is asked for.
//   The failure is not kept: a later ask tries again, but not before
//   RETRY_MS has passed, so a page that redraws on every poll while
//   offline does not start a fetch each time.

export const RETRY_MS = 30000;

const fetchCatalog = () => import("./spellnames.js");
const announce = () => {
  if (typeof window !== "undefined" && typeof window.dispatchEvent === "function" && typeof Event === "function") {
    window.dispatchEvent(new Event("overseer:redraw"));
  }
};

// makeLookup is the whole behaviour with its three outside edges passed in
// (the import, the redraw request and the clock), so a test can hold each.
export function makeLookup({ load = fetchCatalog, redraw = announce, now = () => Date.now() } = {}) {
  let catalog = null;
  let pending = null;
  let failedAt = null;

  function request() {
    if (catalog) return Promise.resolve(true);
    if (pending) return pending;
    if (failedAt !== null && now() - failedAt < RETRY_MS) return Promise.resolve(false);
    pending = Promise.resolve().then(load).then((m) => {
      if (!m || typeof m.classSpellName !== "function") throw new Error("spell names module has no classSpellName");
      catalog = m;
      pending = null;
      failedAt = null;
      redraw();
      return true;
    }, (e) => {
      pending = null;
      failedAt = now();
      if (typeof console !== "undefined") console.warn("spell names did not load; drawing spell ids", e);
      return false;
    });
    return pending;
  }

  function spellName(spell) {
    const id = Number(spell) || 0;
    if (catalog) return catalog.classSpellName(id);
    request();
    return "Spell " + id;
  }

  return { spellName, request, loaded: () => catalog !== null };
}

const shared = makeLookup();

export const spellName = shared.spellName;
// Resolves true once the catalog is loaded, false when the load failed.
export const requestSpellNames = shared.request;

// The link needs no catalog, so it is here and a spell links at first paint.
export function wowheadSpellUrl(spell) {
  return "https://www.wowhead.com/wotlk/spell=" + (Number(spell) || 0);
}
