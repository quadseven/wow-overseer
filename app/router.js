// The hash router: pure functions, no DOM, so node can test them.
//
// Routes are "#/section/part/part?key=value". Every hash the old page used
// (#armory, #family/zug, #dungeons/33, #aprof-Grog, ...) is redirected to its
// new home, so links already sent or bookmarked keep working.

export const SECTIONS = ["now", "guilds", "members", "raid", "economy"];

export const GUILDS = ["cave", "bonkers"];
export const FAMILIES = ["grug", "zug"];

// Old view -> new hash. A function takes the part after the first "/".
const LEGACY = {
  "": () => "",
  family: (rest) => "#/now/family/" + (FAMILIES.includes((rest || "").toLowerCase()) ? rest.toLowerCase() : "grug"),
  watch: () => "#/now",
  map: (rest) => "#/now/map" + (/^(kal|kalimdor|1)$/i.test(rest || "") ? "?c=kal" : /^(ek|eastern|0)/i.test(rest || "") ? "?c=ek" : ""),
  eye: () => "#/now/server",
  decree: () => "#/operator",
  armory: () => "#/members/gear",
  bags: () => "#/economy",
  upgrades: () => "#/members/gear/upgrades",
  lineup: () => "#/members/gear/table",
  trades: () => "#/economy/trades",
  dungeons: () => "#/guilds/cave/runs",
  guild: () => "#/guilds/cave/runs",
  guildchat: () => "#/guilds/cave/chronicle",
  chronicle: () => "#/guilds/cave/chronicle",
  achievements: () => "#/guilds/cave/chronicle",
  council: () => "#/guilds/cave/chronicle",
  raid: () => "#/raid/mc",
};

// The new hash for an old one, or "" when `hash` is already a new route (or
// empty). In-page anchors of the old Armory (#aprof-Name) open the member.
export function legacy(hash) {
  const raw = String(hash || "").replace(/^#/, "");
  if (!raw || raw.startsWith("/")) return "";
  let text = raw;
  try { text = decodeURIComponent(raw); } catch (e) { text = raw; }
  const prof = /^aprof-(.+)$/.exec(text);
  if (prof) return "#/m/" + encodeURIComponent(prof[1]) + "/gear";
  const cut = text.indexOf("/");
  const name = (cut < 0 ? text : text.slice(0, cut)).toLowerCase();
  const rest = cut < 0 ? "" : text.slice(cut + 1);
  const fn = LEGACY[name];
  return fn ? fn(rest) : "#/now";
}

// "#/members?stuck=1&lvl=10-20" -> {parts: ["members"], query: {...}}
export function parse(hash) {
  const raw = String(hash || "").replace(/^#\/?/, "");
  const q = raw.indexOf("?");
  const pathPart = q < 0 ? raw : raw.slice(0, q);
  const query = {};
  if (q >= 0) {
    raw.slice(q + 1).split("&").forEach((kv) => {
      if (!kv) return;
      const i = kv.indexOf("=");
      const k = decodeURIComponent(i < 0 ? kv : kv.slice(0, i));
      const v = i < 0 ? "1" : decodeURIComponent(kv.slice(i + 1).replace(/\+/g, " "));
      query[k] = v;
    });
  }
  const parts = pathPart.split("/").filter(Boolean).map((p) => {
    try { return decodeURIComponent(p); } catch (e) { return p; }
  });
  return { parts, query };
}

export function build(parts, query) {
  const path = "#/" + parts.map(encodeURIComponent).join("/");
  const keys = Object.keys(query || {}).filter((k) => query[k] !== "" && query[k] !== undefined && query[k] !== null);
  if (!keys.length) return path;
  return path + "?" + keys.map((k) => encodeURIComponent(k) + "=" + encodeURIComponent(query[k])).join("&");
}

// A parsed route -> {view, section, params} or a {redirect}.
export function resolve(route) {
  const p = route.parts;
  const q = route.query;
  const top = p[0] || "";
  if (!top) return { redirect: "#/now" };
  if (top === "now") {
    if (p[1] === "family") {
      const f = (p[2] || "").toLowerCase();
      if (!FAMILIES.includes(f)) return { redirect: "#/now/family/grug" };
      return { view: "family", section: "now", params: { family: f } };
    }
    if (p[1] === "map") return { view: "map", section: "now", params: { continent: q.c === "ek" ? "ek" : q.c === "kal" ? "kal" : "" } };
    if (p[1] === "server") return { view: "server", section: "now", params: {} };
    if (p.length > 1) return { redirect: "#/now" };
    return { view: "now", section: "now", params: {} };
  }
  if (top === "guilds") {
    const g = (p[1] || "").toLowerCase();
    if (!GUILDS.includes(g)) return { redirect: "#/guilds/cave" };
    const tab = p[2] === "runs" || p[2] === "chronicle" ? p[2] : "progress";
    if (p[2] && tab === "progress" && p[2] !== "progress") return { redirect: "#/guilds/" + g };
    return { view: "guild", section: "guilds", params: { guild: g, tab } };
  }
  if (top === "runs") {
    if (!p[1]) return { redirect: "#/guilds/cave/runs" };
    return { view: "run", section: "guilds", params: { id: p[1] } };
  }
  if (top === "members") {
    if (p[1] === "gear") {
      const tab = ["armory", "upgrades", "table"].includes(p[2]) ? p[2] : "armory";
      return { view: "gear", section: "members", params: { tab } };
    }
    return { view: "members", section: "members", params: {} };
  }
  if (top === "m") {
    if (!p[1]) return { redirect: "#/members" };
    const tabs = ["overview", "gear", "upgrades", "quests", "bags", "bank", "activity"];
    const tab = tabs.includes(p[2]) ? p[2] : "overview";
    return { view: "member", section: "members", params: { name: p[1], tab } };
  }
  if (top === "raid") {
    const g = (p[2] || "").toLowerCase();
    if (p[1] !== "mc" || !GUILDS.includes(g)) return { redirect: "#/raid/mc/cave" };
    return { view: "raid", section: "raid", params: { guild: g } };
  }
  if (top === "economy") {
    const tab = ["auction", "trades", "professions", "bank"].includes(p[1]) ? p[1] : "gold";
    return { view: "economy", section: "economy", params: { tab } };
  }
  if (top === "operator") return { view: "operator", section: "", params: {} };
  return { view: "notfound", section: "", params: {} };
}

// The tab row a phone swipe walks, for a resolved route.
export function swipeSiblings(hrefs, current) {
  const i = hrefs.indexOf(current);
  if (i < 0) return { prev: "", next: "" };
  return { prev: i > 0 ? hrefs[i - 1] : "", next: i < hrefs.length - 1 ? hrefs[i + 1] : "" };
}
