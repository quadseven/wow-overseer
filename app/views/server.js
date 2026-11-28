// Server: the eye's tiers (/api/eye), each reporting for itself, smallest
// real thing first. A tier that does not answer is shown as off, never as up.
//
// A verdict band leads: the worst tier sets its tone and names itself, and
// the eye's own age is printed under the line, so a stale eye never renders
// as a clean green verdict on a page that refreshes every 30 seconds.

import { html, ago, kpi, state } from "../ui.js";
import * as D from "./now/data.js";
import { READ as UPSTREAM, upstreamSection } from "./upstream.js";
import { READ as WHATS_LIVE, whatsLiveSection } from "./whatslive.js";
import { ageOf, nowSeconds } from "../models/time.js";

const HUE = { green: "var(--ok)", amber: "var(--warn)", vermilion: "var(--bad)" };
const WORD = { ON: "Up", PARTIAL: "Partial", OFF: "Off" };
const RANK = { OFF: 0, PARTIAL: 1, ON: 2 };
// The eye reads every few seconds and the page refreshes every 30, so a
// reading older than this is not a live verdict, however green its tiers are.
const STALE_AFTER = 120;

// A tier value the strip already states is not printed twice: the strip
// counts families, guilds and souls in the world, so those tiers carry no
// value of their own beside it. The Character tier's value is the one count
// the strip does not carry (its Characters is the whole realm), so it
// stays, labelled as the named count it is.
const STRIP_TWIN = { FAMILY: "FAMILIES", GUILD: "GUILDS", REALM: "IN WORLD" };

function tierName(t) {
  return t.tier ? t.tier.charAt(0) + t.tier.slice(1).toLowerCase() : "";
}

function tierValue(t, strip) {
  if (!t.value) return "";
  if (t.tier === "CHARACTER") return t.value + " named";
  const twin = STRIP_TWIN[t.tier];
  if (twin && (strip || []).some((s) => String(s.label || "").toUpperCase() === twin)) return "";
  return t.value;
}

function headlineText(t) {
  // The party tier's headline names the group each family follows by its
  // internal id ("behind 1062"). The id stays, labelled as what it is,
  // instead of reading as a count of anything.
  return String(t.headline || "").replace(/\bbehind (\d+)\b/g, "behind group $1");
}

function tierRow(t, strip) {
  // An unrecognised hue is a reading the page does not understand, so it
  // warns; it never falls back to a neutral grey beside a word like "Up".
  const color = HUE[t.hue] || "var(--warn)";
  const word = WORD[t.state] || t.state || "not measured";
  const value = tierValue(t, strip);
  return html`<div class="tier"><span class="b">${tierName(t)}</span><span class="tier-state" style="color:${color}"><span class="rdot" style="background:${color}" aria-hidden="true"></span>${word}${value ? html` <span class="dim num">${value}</span>` : ""}</span><div class="tier-text"><details class="tier-detail"><summary class="muted">${headlineText(t)}</summary></details>${t.switch ? html`<span class="warn">${t.switch}</span>` : ""}</div></div>`;
}

function verdictBand(e, now) {
  const tiers = e.tiers || [];
  const age = ageOf(e.generated_at, now);
  const stale = age === null || age > STALE_AFTER;
  const offenders = tiers.filter((t) => t.state !== "ON");
  const anyOff = offenders.some((t) => t.state === "OFF");
  const tone = anyOff ? "bad" : offenders.length || stale ? "warn" : "ok";
  let line;
  if (!offenders.length) {
    line = "Realm up";
  } else {
    const names = offenders.map(
      (t) => tierName(t) + (t.state === "OFF" ? " off" : t.state === "PARTIAL" ? " partial" : " " + String(t.state || "").toLowerCase()),
    );
    line = (offenders.length === tiers.length ? "Realm down: " : "Realm partial: ") + names.join(", ");
  }
  const count = offenders.length
    ? tiers.length - offenders.length + " of " + tiers.length + " tiers on."
    : "All " + tiers.length + " tiers reporting.";
  const read = age === null ? "Eye read time not measured." : "Eye read " + ago(age) + ".";
  const staleNote = stale
    ? html` <span class="warn">Stale: the eye has not reported in over 2 minutes, so this verdict is not shown as live.</span>`
    : "";
  return html`<div class="card verdict-band" data-tone="${tone}"><div class="verdict-line">${line}</div><p class="verdict-sub">${count} ${read}${staleNote}</p></div>`;
}

const TILE_WORD = { fresh: "Fresh", stale: "Stale", no_frame: "No frame" };

function tileRow(tile) {
  const st = tile.frame_state || "no_frame";
  const color = st === "fresh" ? "var(--ok)" : "var(--warn)";
  const age = tile.frame_age_seconds === null || tile.frame_age_seconds === undefined
    ? "no frame yet"
    : "frame " + ago(tile.frame_age_seconds);
  return html`<div class="watch-row"><span class="b">${tile.name}</span><span class="watch-state" style="color:${color}">${TILE_WORD[st] || st}</span><span class="dim num">${age}</span></div>`;
}

function watcherTiles(e) {
  const tiles = e.tiles || [];
  if (!tiles.length) return "";
  return html`<div class="card rows watch-rows"><div class="watch-head">Watcher frames</div>${tiles.map(tileRow)}</div>`;
}

export default {
  css: ["views/now.css", "views/upstream.css", "views/server.css"],
  reads: () => ["/api/eye", UPSTREAM, WHATS_LIVE],
  every: 30000,
  title: () => "Server",
  render(ctx) {
    const read = ctx.get("/api/eye");
    const now = nowSeconds();
    let body;
    if (D.ok(read)) {
      const e = read.data;
      const strip = (e.strip || []).filter((s) => String(s.label || "").toUpperCase() !== "TIERS ON");
      const tiers = [...(e.tiers || [])].sort((a, b) => (RANK[a.state] ?? 1) - (RANK[b.state] ?? 1));
      body = html`${verdictBand(e, now)}
<div class="server-kpis">${strip.map((s) => kpi(s.label.charAt(0) + s.label.slice(1).toLowerCase(), s.value))}</div>
<div class="card rows tiers" id="sv-tiers">${tiers.map((t) => tierRow(t, e.strip || []))}</div>${watcherTiles(e)}`;
    } else if (read.data === undefined && !read.error) {
      body = html`<div class="skeletons" aria-busy="true"><div class="skeleton"></div></div>`;
    } else {
      body = state("error", "The world did not answer", "The server tiers could not be read, so none of them is shown as up.");
    }
    return html`<a class="back" href="#/now"><i class="ph ph-caret-left" aria-hidden="true"></i>Now</a><h1>Server</h1><nav class="sv-chips" aria-label="On this page"><button type="button" class="chip" data-goto="sv-tiers">Tiers</button><button type="button" class="chip" data-goto="sv-live">What's live</button><button type="button" class="chip" data-goto="sv-upstream">Upstream</button></nav>${body}${whatsLiveSection(ctx.get(WHATS_LIVE), now)}${upstreamSection(ctx.get(UPSTREAM), now)}`;
  },
  after(main) {
    main.querySelectorAll("[data-goto]").forEach((b) => b.addEventListener("click", () => {
      const el = document.getElementById(b.getAttribute("data-goto"));
      if (el) el.scrollIntoView({ block: "start" });
    }));
    main.querySelectorAll("[data-copy]").forEach((el) => el.addEventListener("click", () => {
      if (navigator.clipboard) navigator.clipboard.writeText(el.getAttribute("data-copy"));
    }));
  },
};
