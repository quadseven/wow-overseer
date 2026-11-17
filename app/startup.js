// Family and guild destinations need the realm lists to resolve correctly.
// Everything else can start loading while the realm read is still in flight.
function needsRealmLists(hash) {
  const parts = String(hash || "")
    .replace(/^#\/?/, "")
    .split(/[/?]/)
    .filter(Boolean)
    .map((part) => part.toLowerCase());
  const [section, page] = parts;
  return (
    section === "guilds" ||
    (section === "now" && page === "family") ||
    ["family", "guild", "dungeons", "guildchat", "chronicle", "achievements", "council"].includes(section)
  );
}

export function waitForRouteRealm(hash, hasRealmLists, realmReady) {
  if (!needsRealmLists(hash) || hasRealmLists) return Promise.resolve();
  return Promise.resolve(realmReady).then(() => undefined);
}

// Start secondary work once the first page is on screen, then keep its pace.
export function afterFirstDraw(refresh, everyMs, schedule) {
  let started = false;
  return function start() {
    if (started) return null;
    started = true;
    const pending = refresh();
    schedule(refresh, everyMs);
    return pending;
  };
}
