// Saved clips: the shelf, and the link a story or timeline entry carries.
//
// The server decides everything here. /api/clips lists the ready clips, newest
// first, each with the URL the file is served at and `view_owner`, whose eyes
// the clip was filmed from; a loot story or a run card carries `clip` ({url,
// kind}, plus `view_note` when the clip was filmed from another member's view)
// when its event has a saved clip, or `clip_note` when no live view was up.
// This only draws them. A clip plays in place in the browser's own video
// element; nothing is fetched but its metadata until Play.

import { html, raw, state, pendingRead, plural } from "../ui.js";
import { u } from "../api.js";
import { clock, toSeconds } from "../models/time.js";

export const CSS = "views/clips.css";
export const READ = "/api/clips";

const KIND = { loot: "Loot", boss_kill: "Boss kill", clear: "Dungeon clear", level_60: "Level 60" };
const PAGE = 12;

// The video element of each clip opened in place, by URL. The page redraws by
// replacing the whole body, which would destroy a playing element and restart
// it paused at 0. So the markup holds only a slot for an open clip, and
// bindShelf puts this same element back in it, in the same task as the swap,
// so the browser keeps playing it at its position. An element is dropped when
// its clip leaves the list.
const kept = new Map();

// The shelf's own state: the kind the reader filtered to ("" is all kinds)
// and how many clips the shelf shows before it offers more. Both survive a
// redraw because this module does.
let kindOnly = "";
let shown = PAGE;

function kindWord(kind) { return KIND[kind] || String(kind || "Clip").replace(/_/g, " "); }

function dayLabel(at) {
  const t = toSeconds(at);
  if (!t) return "";
  return new Date(t * 1000).toLocaleDateString([], { day: "numeric", month: "short" });
}

// The line under a clip's title: what happened, who it happened to, whose
// eyes filmed it when they were not the subject's own, and when. The read
// sends view_owner on every clip; naming the filmer here is what stops a
// kill being credited to the character it was filmed from.
function metaLine(c) {
  const parts = [];
  if (c.subject) parts.push(kindWord(c.kind));
  parts.push(c.character);
  if (c.view_owner && c.view_owner !== c.character) parts.push("filmed by " + c.view_owner);
  if (c.of > 1) parts.push(c.nth + " of " + c.of);
  const when = [dayLabel(c.at), clock(c.at)].filter(Boolean).join(" ");
  if (when) parts.push(when);
  return parts.join(", ");
}

// The line under a story or run card: a button that plays the clip in place
// (with the server's words for whose view filmed it, when not the subject's
// own), the file itself as a secondary link, the server's words when no live
// view was up, or nothing.
export function clipLink(entry) {
  if (entry && entry.clip && entry.clip.url) {
    const url = entry.clip.url;
    const from = entry.clip.view_note ? html` <span class="muted clip-note">${entry.clip.view_note}</span>` : "";
    const play = kept.has(url)
      ? html`<div class="clip-slot" data-clip-slot="${url}"></div>`
      : html`<button type="button" class="clip-link" data-clip="${url}"><i class="ph-fill ph-play-circle" aria-hidden="true"></i>Watch the clip</button>`;
    return html`${play}${from} <a class="clip-file" href="${u(url)}" target="_blank" rel="noopener">Open the file</a>`;
  }
  if (entry && entry.clip_note) return html`<span class="muted clip-note">${entry.clip_note}</span>`;
  return "";
}

// One link or quiet line per character on an entry that holds several, such as
// a level 60 feed item or the clips inside a run: each is the same markup
// clipLink draws, with the name (`who` on a feed item, `character` on a run).
export function clipLinks(entry) {
  const list = (entry && entry.clips) || [];
  if (!list.length) return "";
  return html`${list.map((c) => html`<span class="clip-named"><span class="muted">${c.who || c.character}</span> ${clipLink(c)}</span>`)}`;
}

function card(c) {
  const stage = kept.has(c.url)
    ? html`<div class="clip-slot" data-clip-slot="${c.url}"></div>`
    : html`<button type="button" class="clip-stage" data-clip="${c.url}" aria-label="Play the clip: ${c.subject || kindWord(c.kind)}"><i class="ph-fill ph-play" aria-hidden="true"></i></button>`;
  return html`<article class="card clip-card">${stage}${c.subject ? html`<div class="clip-subject">${c.subject}</div>` : ""}<div class="clip-meta">${metaLine(c)}</div></article>`;
}

function chips(clips) {
  const kinds = [...new Set(clips.map((c) => c.kind))];
  if (kinds.length < 2) return "";
  const chip = (k, label) => html`<button type="button" class="chip clip-chip" data-clip-kind="${k}"${k === kindOnly ? raw(' aria-pressed="true"') : ""}>${label}</button>`;
  return html`<div class="clip-chips" role="group" aria-label="Kind of clip">${chip("", "All")}${kinds.map((k) => chip(k, kindWord(k)))}</div>`;
}

// The footer under the shelf: the moments that left no clip, as one summary
// card. Counts only; a missed moment is never a card, and the per day detail
// folds under the summary.
export function missedLine(d) {
  const parts = [];
  if (d.no_view) parts.push(`${d.no_view} with no streamed member in view`);
  if (d.failed) parts.push(`${d.failed} where recording failed`);
  return `${d.day}: ${parts.join(", ")}.`;
}

function missedFooter(missed) {
  const days = (missed || []).filter((d) => d.no_view || d.failed);
  if (!days.length) return "";
  const total = days.reduce((n, d) => n + (d.no_view || 0) + (d.failed || 0), 0);
  const worst = days.reduce((a, d) => ((d.no_view || 0) + (d.failed || 0) > (a.no_view || 0) + (a.failed || 0) ? d : a), days[0]);
  const line = `${plural(total, "moment")} left no clip, most on ${dayLabel(worst.day) || worst.day}.`;
  return html`<div class="card clip-missed-card"><p class="clip-missed-line">${line}</p><details class="fold"><summary>Per day</summary>${days.map((d) => html`<p class="clip-missed-day">${missedLine(d)}</p>`)}</details></div>`;
}

// The shelf section's body, from the /api/clips read: filter chips, the
// clips grouped under their day, the first PAGE of the filtered list with a
// way to show more, and the missed summary.
export function shelf(read) {
  const wait = pendingRead(read, 2);
  if (wait) return wait;
  const clips = (read.data && read.data.clips) || [];
  for (const [url, v] of kept) {
    if (!clips.some((c) => c.url === url)) {
      if (v.pause) v.pause();
      kept.delete(url);
    }
  }
  const foot = missedFooter(read.data && read.data.missed);
  if (!clips.length && !foot) return state("empty", "No clips yet", (read.data && read.data.empty) || "No clips have been saved yet.");
  if (!clips.length) return foot;
  const filtered = kindOnly ? clips.filter((c) => c.kind === kindOnly) : clips;
  const page = filtered.slice(0, shown);
  let body = "";
  if (!page.length) {
    body = state("empty", "No clips of this kind", "No clip of this kind has been saved yet.");
  } else {
    let day = null;
    const parts = [];
    for (const c of page) {
      const d = String(c.at || "").slice(0, 10);
      if (d !== day) {
        day = d;
        parts.push(html`<div class="clip-day">${dayLabel(c.at) || d}</div>`);
      }
      parts.push(card(c));
    }
    body = html`<div class="clip-grid">${parts}</div>`;
  }
  const more = filtered.length > page.length
    ? html`<button type="button" class="btn clip-more" data-clip-more>Show more clips (${filtered.length - page.length} more)</button>`
    : "";
  return html`${chips(clips)}${body}${more}${foot}`;
}

// Run after every draw. A slot gets back the kept element of its clip; a Play
// button (a shelf stage or a story's clip link) turns into a new video, which
// starts at once; the shelf's chips and its Show more set the shelf state and
// ask for a redraw.
export function bindShelf(main) {
  main.querySelectorAll("[data-clip-slot]").forEach((slot) => {
    const v = kept.get(slot.getAttribute("data-clip-slot"));
    if (v) slot.replaceWith(v);
  });
  main.querySelectorAll("button[data-clip-kind]").forEach((b) => {
    b.addEventListener("click", () => {
      kindOnly = b.getAttribute("data-clip-kind") || "";
      shown = PAGE;
      window.dispatchEvent(new Event("overseer:redraw"));
    });
  });
  main.querySelectorAll("button[data-clip-more]").forEach((b) => {
    b.addEventListener("click", () => {
      shown += PAGE;
      window.dispatchEvent(new Event("overseer:redraw"));
    });
  });
  main.querySelectorAll("button[data-clip]").forEach((b) => {
    b.addEventListener("click", () => {
      const url = b.getAttribute("data-clip");
      const v = document.createElement("video");
      kept.set(url, v);
      v.className = "clip-video";
      v.controls = true;
      v.setAttribute("playsinline", "");
      v.preload = "metadata";
      v.src = u(url);
      b.replaceWith(v);
      const started = v.play();
      if (started && started.catch) started.catch(() => {});
    });
  });
}
