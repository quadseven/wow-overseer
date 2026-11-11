// Saved clips: the shelf, and the link a story or timeline entry carries.
//
// The server decides everything here. /api/clips lists the ready clips, newest
// first, each with the URL the file is served at; a loot story or a run card
// carries `clip` ({url, kind}) when its event has a saved clip, or `clip_note`
// when no live view was up. This only draws them. A clip plays in place in the
// browser's own video element; nothing is fetched but its metadata until Play.

import { html, state, pendingRead } from "../ui.js";
import { u } from "../api.js";
import { since } from "../models/time.js";

export const CSS = "views/clips.css";
export const READ = "/api/clips";

const KIND = { loot: "Loot", boss_kill: "Boss kill", clear: "Dungeon clear", level_60: "Level 60" };

// Clips opened in place this visit. A redraw keeps them open.
const open = new Set();

function kindWord(kind) { return KIND[kind] || String(kind || "Clip").replace(/_/g, " "); }

// The line under a story or run card: a link to its clip, the server's words
// when no live view was up, or nothing.
export function clipLink(entry) {
  if (entry && entry.clip && entry.clip.url) {
    return html`<a class="clip-link" href="${u(entry.clip.url)}" target="_blank" rel="noopener"><i class="ph-fill ph-play-circle" aria-hidden="true"></i>Watch the clip</a>`;
  }
  if (entry && entry.clip_note) return html`<span class="muted clip-note">${entry.clip_note}</span>`;
  return "";
}

function video(url) {
  return html`<video class="clip-video" controls preload="metadata" playsinline src="${u(url)}"></video>`;
}

function card(c) {
  const body = open.has(c.url)
    ? video(c.url)
    : html`<button type="button" class="btn clip-play" data-clip="${c.url}"><i class="ph-fill ph-play" aria-hidden="true"></i>Play</button>`;
  return html`<article class="card clip-card"><div class="clip-head"><span class="tag tag-outline">${kindWord(c.kind)}</span><span class="clip-who">${c.character}</span><span class="muted g-when">${since(c.at)}</span></div>${body}</article>`;
}

// The shelf section's body, from the /api/clips read.
export function shelf(read) {
  const wait = pendingRead(read, 2);
  if (wait) return wait;
  const clips = (read.data && read.data.clips) || [];
  if (!clips.length) return state("empty", "No clips yet", (read.data && read.data.empty) || "No clips have been saved yet.");
  return html`<div class="clip-grid">${clips.map(card)}</div>`;
}

// Play in place: the button becomes the video, which starts at once.
export function bindShelf(main) {
  main.querySelectorAll("button[data-clip]").forEach((b) => {
    b.addEventListener("click", () => {
      const url = b.getAttribute("data-clip");
      open.add(url);
      const v = document.createElement("video");
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
