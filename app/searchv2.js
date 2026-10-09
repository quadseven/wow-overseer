// The realm half of global search: members, items, quests, dungeons and runs
// from /api/v2/search. The server caps each group and keeps answers for a
// minute; this waits for a short pause in typing before it asks.

import { addProvider } from "./search.js";
import { load } from "./api.js";
import { classVar, memberHref } from "./ui.js";

const PAUSE_MS = 180;
const QUALITY = ["var(--q-poor)", "var(--q-common)", "var(--q-uncommon)", "var(--q-rare)", "var(--q-epic)", "var(--q-legendary)"];
let latest = "";

const pause = (ms) => new Promise((done) => window.setTimeout(done, ms));
const guildKey = (g) => String(g || "").toLowerCase();

function runsHref(guild) {
  const g = guildKey(guild);
  return g ? "#/guilds/" + encodeURIComponent(g) + "/runs" : "#/guilds";
}

function runSub(r) {
  const how = r.state === "ended" ? r.outcome || "ended" : r.state;
  const bosses = r.bosses_total ? ", " + r.bosses_done + " of " + r.bosses_total + " bosses" : "";
  return [r.guild, how + bosses, r.when ? r.when.slice(0, 16) : ""].filter(Boolean).join(" | ");
}

// The server's answer as the dialog's groups ({label, rows}).
export function groups(p) {
  if (!p) return [];
  const out = [
    { label: "Members", rows: (p.members || []).map((m) => ({
      name: m.name, href: memberHref(m.name), color: classVar(m.class),
      sub: [["Level " + m.level, m.class].filter(Boolean).join(" "), m.guild, m.online ? "online" : ""].filter(Boolean).join(", "),
    })) },
    { label: "Items", rows: (p.items || []).map((it) => ({
      name: it.name, item: it.entry, href: location.hash || "#/now", color: QUALITY[it.quality] || "",
      sub: it.item_level ? "Item level " + it.item_level : "",
    })) },
    { label: "Quests", rows: (p.quests || []).map((q) => Object.assign({}, q, { holders: (q.holders || []).filter(Boolean) })).filter((q) => q.holders.length).map((q) => ({
      name: q.title, href: memberHref(q.holders[0], "quests"),
      sub: "In the log of " + q.holders.join(", "),
    })) },
    { label: "Dungeons", rows: (p.dungeons || []).map((d) => ({
      name: d.name, href: runsHref(d.guild), sub: d.guild ? d.guild + " runs" : "Runs",
    })) },
    { label: "Runs", rows: (p.runs || []).map((r) => ({
      name: r.place, href: "#/runs/" + encodeURIComponent(r.id), sub: runSub(r),
    })) },
  ];
  return out.filter((g) => g.rows.length);
}

addProvider(async (q) => {
  latest = q;
  if (q.length < 2) return [];
  await pause(PAUSE_MS);
  if (q !== latest) return [];
  const e = await load("/api/v2/search?q=" + encodeURIComponent(q));
  return groups(e.data);
});
