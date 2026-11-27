// Saved clips: the shelf, and the link a story or timeline entry carries.
//
// The server decides everything here. /api/clips lists the ready clips, newest
// first, each with the URL the file is served at, a poster frame beside the
// video, and - for loot - the item's quality color and icon plus a context
// line (run and boss for a dungeon drop, zone for open-world). A clip plays in
// place in the browser's own video element; the video loads only after Play,
// while its poster loads lazily.

import { html, state, pendingRead, item, esc } from "../ui.js";
import { u } from "../api.js";
import { since } from "../models/time.js";

export const CSS = "views/clips.css";
export const READ = "/api/clips";

const KIND = { loot: "Loot", boss_kill: "Boss kill", clear: "Dungeon clear", level_60: "Level 60" };

// The video element of each clip opened in place, by URL. The page redraws by
// replacing the whole body, which would destroy a playing element and restart
// it paused at 0. So the markup holds only a slot for an open clip, and
// bindShelf puts this same element back in it, in the same task as the swap,
// so the browser keeps playing it at its position. An element is dropped when
// its clip leaves the list.
const kept = new Map();

function kindWord(kind) { return KIND[kind] || String(kind || "Clip").replace(/_/g, " "); }

// The line under a story or run card: a link to its clip (with the server's
// words for whose view filmed it, when not the subject's own), the server's
// words when no live view was up, or nothing.
export function clipLink(entry) {
  if (entry && entry.clip && entry.clip.url) {
    const from = entry.clip.view_note ? html` <span class="muted clip-note">${entry.clip.view_note}</span>` : "";
    return html`<a class="clip-link" href="${u(entry.clip.url)}" target="_blank" rel="noopener"><i class="ph-fill ph-play-circle" aria-hidden="true"></i>Watch the clip</a>${from}`;
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
  const body = kept.has(c.url)
    ? html`<div class="clip-slot" data-clip-slot="${c.url}"></div>`
    : html`<button type="button" class="clip-poster" data-clip="${c.url}"
        aria-label="Play clip: ${esc(c.subject || kindWord(c.kind))}">
        ${c.poster ? html`<img src="${u(c.poster)}" alt="" loading="lazy" decoding="async">` : ""}
        <span><i class="ph-fill ph-play" aria-hidden="true"></i>Play</span></button>`;
  const name = c.item
    ? item(c.item)
    : c.subject
      ? html`<span class="clip-subject">${c.subject}</span>`
      : "";
  const ctx = c.context ? html`<div class="clip-context">${c.context}</div>` : "";
  const nth = c.of > 1 ? html`<span class="tag tag-outline clip-nth">${c.nth} of ${c.of}</span>` : "";
  return html`<article class="card clip-card"><div class="clip-head"><span class="tag tag-outline">${kindWord(c.kind)}</span><span class="clip-who">${c.character}</span><span class="muted g-when">${since(c.at)}</span></div>${name}${ctx}${nth}${body}</article>`;
}

// The footer under the shelf: per day, how many moments left no clip and why.
// Counts only; a missed moment is never a card.
export function missedLine(d) {
  const parts = [];
  if (d.no_view) parts.push(`${d.no_view} with no streamed member in view`);
  if (d.failed) parts.push(`${d.failed} where recording failed`);
  return `${d.day}: ${parts.join(", ")}.`;
}

function missedFooter(missed) {
  const days = (missed || []).filter((d) => d.no_view || d.failed);
  if (!days.length) return "";
  return html`<footer class="clip-missed muted">${days.map((d) => html`<p>${missedLine(d)}</p>`)}</footer>`;
}

// The shelf section's body, from the /api/clips read.
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
  return html`<div class="clip-grid">${clips.map(card)}</div>${foot}`;
}

// Run after every draw. A slot gets back the kept element of its clip; a Play
// button turns into a new video, which starts at once.
export function bindShelf(main) {
  main.querySelectorAll("[data-clip-slot]").forEach((slot) => {
    const v = kept.get(slot.getAttribute("data-clip-slot"));
    if (v) slot.replaceWith(v);
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
