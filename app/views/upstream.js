// Upstream: how far behind each pinned dependency is, and what changed.
// One section of the Server view, drawn from /api/v2/upstream. The server
// measures; this only draws, and a number the server did not report reads
// "not measured", never 0.
//
// The section sits in a fold under a one-line summary and opens itself
// only when a crash or security count needs action. Rows sort hot behind
// first, then most behind; when nothing is measured at all, the steady
// state is one compact card, not a screen of identical full cards.

import { html, raw, isHttps, ago, notMeasured, plural, sectionHead, state } from "../ui.js";
import { ageOf, since } from "../models/time.js";

export const READ = "/api/v2/upstream";

const REPO = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/;

const KIND = {
  security: ["Security", "tag-bad"],
  crash: ["Crash", "tag-warn"],
  bots: ["Bots", "tag-accent"],
  runs: ["Dungeons", "tag-neutral"],
};

function kinds(tags) {
  return (tags || []).map((t) => (KIND[t] ? html`<span class="tag ${KIND[t][1]}">${KIND[t][0]}</span>` : ""));
}

function hotCount(r) {
  const c = r.counts || {};
  return (c.security || 0) + (c.crash || 0);
}

function verdict(r) {
  if (r.status === "current") return html`<span class="tag tag-neutral">Current</span>`;
  if (r.status === "behind") {
    const c = r.counts || {};
    let text = r.behind + " behind";
    if (c.security) text += ", " + c.security + " security";
    if (c.crash) text += ", " + c.crash + " crash";
    return html`<span class="tag ${hotCount(r) ? "tag-warn" : "tag-neutral"}">${text}</span>`;
  }
  return html`<span class="tag tag-outline">Not measured</span>`;
}

function pinLine(r, now) {
  if (!r.pinned) return html`<span class="muted">${r.reason || "Pin not reported."}</span>`;
  const age = ageOf(r.pinned_at, now);
  const days = age === null ? null : Math.floor(age / 86400);
  const head = r.head && r.behind > 0 ? html` to <code class="num">${r.head}</code>` : (r.status === "current" ? " (at the head)" : "");
  const old = days === null ? notMeasured("pin age not measured") : html`<span class="num">${days === 0 ? "less than a day" : plural(days, "day")}</span> old`;
  return html`<span>Pinned <code class="num">${r.pinned}</code>${head}, ${old}${r.carried ? html`, carries <span class="num">${plural(r.carried, "commit")}</span> ${r.role === "ours" ? "not on the branch" : "upstream lacks"}` : ""}</span>`;
}

function changes(r) {
  if (!r.notable || !r.notable.length) return "";
  const shown = r.notable.length;
  const label = r.behind > shown ? "Notable changes (" + shown + " of " + r.behind + ")" : "Notable changes (" + shown + ")";
  // A commit links only when the repo reads as owner/name, so the built URL
  // stays on github.com.
  const base = REPO.test(String(r.repo || "")) ? "https://github.com/" + r.repo + "/commit/" : "";
  const items = r.notable.map((c) => html`<li><span class="ud-kinds">${kinds(c.tags)}</span>${base ? html`<a href="${base + encodeURIComponent(c.sha)}" target="_blank" rel="noopener">${c.title}</a>` : c.title}</li>`);
  return html`<details class="fold ud-fold"${r.counts && r.counts.security ? raw(" open") : ""}><summary>${label}</summary><ul class="ud-list">${items}</ul></details>`;
}

function project(r, now) {
  const stale = r.stale ? html` <span class="warn">Last good reading; GitHub did not answer just now.</span>` : "";
  const checked = r.checked_at ? html`Checked ${since(r.checked_at, now)}.` : "";
  const open = isHttps(r.url) ? html` <a href="${r.url}" target="_blank" rel="noopener">Compare on GitHub</a>` : "";
  const hot = hotCount(r) ? ((r.counts && r.counts.security) ? " ud-hot-bad" : " ud-hot") : "";
  return html`<article class="card ud-row${hot}"><div class="ud-top"><h3 class="b">${r.label}</h3>${verdict(r)}</div><div class="ud-pin">${pinLine(r, now)}</div>${changes(r)}<div class="ud-foot dim">${checked}${stale}${open}</div></article>`;
}

function compactRow(r) {
  return html`<div class="ud-compact-row"><span class="b">${r.label}</span><span class="tag tag-outline">Not measured</span></div>`;
}

function compactCard(rows) {
  return html`<article class="card ud-compact">${rows.map(compactRow)}</article>`;
}

// Full cards are for rows with a real status; a row the server did not
// measure stays a compact line even beside measured neighbours.
function rowCard(r, now) {
  return r.status === "not measured"
    ? html`<article class="card ud-compact">${compactRow(r)}</article>`
    : project(r, now);
}

// Hot behind first, then most behind, measured rows before unmeasured
// ones, which keep the server's order among themselves.
function sortedRows(rows) {
  const measured = rows.filter((r) => r.status !== "not measured");
  const unmeasured = rows.filter((r) => r.status === "not measured");
  measured.sort((a, b) => hotCount(b) - hotCount(a) || (b.behind || 0) - (a.behind || 0) || String(a.label).localeCompare(String(b.label)));
  return measured.concat(unmeasured);
}

function summaryLine(rows) {
  const seen = rows.filter((r) => r.status !== "not measured");
  if (!seen.length) return "Nothing measured yet";
  const behind = seen.filter((r) => r.behind > 0).length;
  // The crash or security total sums only rows whose counts the server
  // reported; a measured row without counts makes the total itself
  // not measured, never a printed 0.
  const counted = seen.filter((r) => r.counts);
  const hot = counted.reduce((n, r) => n + hotCount(r), 0);
  const hotText = counted.length === seen.length ? hot + " crash or security" : "crash or security not measured";
  return behind + " of " + seen.length + " projects behind, " + hotText;
}

const NOTE = "Pins are what the realm reports it is running. Each project is compared with its public upstream on GitHub, at most once an hour. Kinds are read from commit titles, so they point at what to read, not at what is verified.";

export function upstreamSection(read, now) {
  const head = sectionHead(null, "Upstream", read && read.data && read.data.checked_at ? "checked " + ago(ageOf(read.data.checked_at, now)) : "");
  if (!read || read.data === undefined) {
    return html`<section class="section" id="sv-upstream">${head}${read && read.error ? state("error", "Upstream did not answer", "Nothing is shown as current.") : html`<div class="skeletons" aria-busy="true"><div class="skeleton"></div></div>`}</section>`;
  }
  const d = read.data;
  if (!d || d.error || !Array.isArray(d.rows)) return html`<section class="section" id="sv-upstream">${head}${state("error", "Upstream did not answer", "Nothing is shown as current.")}</section>`;
  const banner = d.state === "checking"
    ? state("empty", "Checking GitHub", "The first reading takes a few seconds. It will appear here without a reload.")
    : d.state === "limited"
      ? state("empty", "GitHub rate limit reached", "Readings below are the last good ones, or not measured, until the limit resets.")
      : "";
  const rows = sortedRows(d.rows);
  const allUnmeasured = d.rows.length > 0 && d.rows.every((r) => r.status === "not measured");
  const hot = d.rows.reduce((n, r) => n + (r.status !== "not measured" ? hotCount(r) : 0), 0);
  const body = allUnmeasured
    ? compactCard(rows)
    : html`<div class="ud-rows">${rows.map((r) => rowCard(r, now))}</div>`;
  return html`<section class="section" id="sv-upstream">${head}${banner}<details class="fold sv-fold"${hot ? raw(" open") : ""}><summary><span class="sv-line">${summaryLine(d.rows)}</span></summary><div class="sv-body">${body}<details class="fold ud-fold"><summary>How this is worked out</summary><p class="muted ud-note">${NOTE}</p></details></div></details></section>`;
}
