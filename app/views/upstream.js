// Upstream: how far behind each pinned dependency is, and what changed.
// One section of the Server view, drawn from /api/v2/upstream. The server
// measures; this only draws, and a number the server did not report reads
// "not measured", never 0.

import { html, raw, ago, notMeasured, plural, sectionHead, state, kpi } from "../ui.js";
import { ageOf, since } from "../models/time.js";

export const READ = "/api/v2/upstream";

const KIND = {
  security: ["Security", "tag-bad"],
  crash: ["Crash", "tag-warn"],
  bots: ["Bots", "tag-accent"],
  runs: ["Dungeons", "tag-neutral"],
};

function kinds(tags) {
  return (tags || []).map((t) => (KIND[t] ? html`<span class="tag ${KIND[t][1]}">${KIND[t][0]}</span>` : ""));
}

function verdict(r) {
  if (r.status === "current") return html`<span class="tag tag-neutral">Current</span>`;
  if (r.status === "behind") {
    const hot = r.counts && (r.counts.security || r.counts.crash);
    return html`<span class="tag ${hot ? "tag-warn" : "tag-neutral"}">${plural(r.behind, "commit")} behind</span>`;
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
  const base = "https://github.com/" + r.repo + "/commit/";
  const items = r.notable.map((c) => html`<li><span class="ud-kinds">${kinds(c.tags)}</span><a href="${base + c.sha}" target="_blank" rel="noopener">${c.title}</a></li>`);
  return html`<details class="fold ud-fold"${r.counts && r.counts.security ? raw(" open") : ""}><summary>${label}</summary><ul class="ud-list">${items}</ul></details>`;
}

function project(r, now) {
  const stale = r.stale ? html` <span class="warn">Last good reading; GitHub did not answer just now.</span>` : "";
  const checked = r.checked_at ? html`Checked ${since(r.checked_at, now)}.` : "";
  const open = r.url ? html` <a href="${r.url}" target="_blank" rel="noopener">Compare on GitHub</a>` : "";
  return html`<article class="card ud-row"><div class="ud-top"><h3 class="b">${r.label}</h3>${verdict(r)}</div><div class="ud-pin">${pinLine(r, now)}</div>${changes(r)}<div class="ud-foot dim">${checked}${stale}${open}</div></article>`;
}

function summary(rows) {
  const seen = rows.filter((r) => r.status !== "not measured");
  const behind = seen.filter((r) => r.behind > 0);
  const hot = seen.reduce((n, r) => n + ((r.counts && (r.counts.security + r.counts.crash)) || 0), 0);
  return html`<div class="server-kpis">${kpi("Projects behind", seen.length ? behind.length + " of " + seen.length : notMeasured())}${kpi("Crash or security titles", seen.length ? hot : notMeasured())}</div>`;
}

const NOTE = "Pins are what the realm reports it is running. Each project is compared with its public upstream on GitHub, at most once an hour. Kinds are read from commit titles, so they point at what to read, not at what is verified.";

export function upstreamSection(read, now) {
  const head = sectionHead(null, "Upstream", read && read.data && read.data.checked_at ? "checked " + ago(ageOf(read.data.checked_at, now)) : "");
  if (!read || read.data === undefined) {
    return html`<section class="section">${head}${read && read.error ? state("error", "Upstream did not answer", "Nothing is shown as current.") : html`<div class="skeletons" aria-busy="true"><div class="skeleton"></div></div>`}</section>`;
  }
  const d = read.data;
  if (!d || d.error || !Array.isArray(d.rows)) return html`<section class="section">${head}${state("error", "Upstream did not answer", "Nothing is shown as current.")}</section>`;
  const banner = d.state === "checking"
    ? state("empty", "Checking GitHub", "The first reading takes a few seconds. It will appear here without a reload.")
    : d.state === "limited"
      ? state("empty", "GitHub rate limit reached", "Readings below are the last good ones, or not measured, until the limit resets.")
      : "";
  return html`<section class="section">${head}<p class="muted ud-note">${NOTE}</p>${banner}${summary(d.rows)}<div class="ud-rows">${d.rows.map((r) => project(r, now))}</div></section>`;
}
