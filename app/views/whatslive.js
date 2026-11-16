// What is live right now across the bridge follower, the running realm,
// and merged pull requests from the last 48 hours (/api/v2/whats-live).

import {
  html,
  isHttps,
  kpi,
  notMeasured,
  pendingRead,
  readState,
  sectionHead,
  state,
} from "../ui.js";
import { since } from "../models/time.js";

export const READ = "/api/v2/whats-live";

const STATE_LABEL = {
  "live-proven": "Live proven",
  deployed: "Deployed",
  merged: "Merged",
  unknown: "Unknown",
};

function shortDigest(d) {
  if (!d || d === "unknown") return "";
  return d.length > 19 ? d.slice(0, 19) : d;
}

function unmeasuredText(v, reason) {
  return html`${notMeasured(reason || v || "unknown")}`;
}

function bridgePanel(data, now) {
  const b = data.bridge || {};
  const reason = (data.unmeasured && data.unmeasured.bridge) || "";
  const commit = (!b.commit || b.commit === "unknown")
    ? unmeasuredText("unknown", reason)
    : html`<code>${b.short || b.commit.slice(0, 12)}</code>`;
  const digest = (!b.digest || b.digest === "unknown")
    ? notMeasured("unknown")
    : html`<code>${shortDigest(b.digest)}</code>`;
  const rolled = (!b.deployed_at || b.deployed_at === "unknown")
    ? notMeasured("unknown")
    : since(b.deployed_seconds !== undefined && b.deployed_seconds !== null ? b.deployed_seconds : b.deployed_at, now);
  const shipPr = b.ship_pr ? "#" + b.ship_pr : notMeasured("unknown");
  return html`<div class="panel">
    <h3 class="kicker">Bridge</h3>
    <div class="kpis">
      ${kpi("Commit", commit)}
      ${kpi("Image", digest)}
      ${kpi("Rolled", rolled)}
      ${kpi("Ship PR", shipPr)}
    </div>
    ${reason ? html`<p class="small">${reason}</p>` : ""}
  </div>`;
}

function realmPanel(data, now) {
  const r = data.realm || {};
  const reason = (data.unmeasured && data.unmeasured.realm) || "";
  const realmState = (!r.state || r.state === "unknown")
    ? unmeasuredText("unknown", reason)
    : r.state;
  const modCommit = (!r.module_commit || r.module_commit === "unknown")
    ? unmeasuredText("unknown", reason)
    : html`<code>${r.module_commit.slice(0, 12)}</code>`;
  const coreRev = (!r.core_revision || r.core_revision === "unknown")
    ? notMeasured("unknown")
    : html`<code>${r.core_revision.slice(0, 12)}</code>`;
  const started = (!r.started_at || r.started_at === "unknown")
    ? notMeasured("unknown")
    : since(r.started_at, now);
  return html`<div class="panel">
    <h3 class="kicker">Realm</h3>
    <div class="kpis">
      ${kpi("State", realmState)}
      ${kpi("mod-overseer", modCommit)}
      ${kpi("Core", coreRev)}
      ${kpi("Started", started)}
    </div>
    ${reason ? html`<p class="small">${reason}</p>` : ""}
  </div>`;
}

function prRow(pr, now) {
  const label = STATE_LABEL[pr.state] || pr.state || "Unknown";
  const comp = pr.component === "module" ? "Module" : "Bridge";
  const num = "#" + pr.number;
  const heading = isHttps(pr.url)
    ? html`<a class="upstream-link" href="${pr.url}" target="_blank" rel="noopener">${num} ${pr.title || "(untitled)"}</a>`
    : html`<span class="upstream-title">${num} ${pr.title || "(untitled)"}</span>`;
  const sha = pr.merge_short || (pr.merge_commit && pr.merge_commit !== "unknown" ? pr.merge_commit.slice(0, 12) : "unknown");
  const merged = pr.merged_at ? since(pr.merged_at, now) : "unknown";
  const refs = (pr.refs && pr.refs.length) ? "Refs " + pr.refs.map((n) => "#" + n).join(", ") : "";
  return html`<li class="upstream-row">
    <div class="upstream-tags">
      <span class="tag">${label}</span>
      <span class="tag">${comp}</span>
    </div>
    <div class="grow">
      ${heading}
      <div class="meta small"><code>${sha}</code> - ${merged}${refs ? " - " + refs : ""}</div>
    </div>
  </li>`;
}

export function whatsLiveSection(read, now) {
  const wait = pendingRead(read, 2);
  if (wait) {
    return html`<section class="section">${sectionHead("", "What's live")}${wait}</section>`;
  }
  if (readState(read) === "refused") {
    const err = read && read.data && read.data.error ? read.data.error : "";
    return html`<section class="section">${sectionHead("", "What's live")}${state("error", "What's live failed", err)}</section>`;
  }
  const data = read.data || {};
  const prs = data.prs || [];
  const prReason = (data.unmeasured && data.unmeasured.prs) || "";
  let prsBody;
  if (prs.length) {
    prsBody = html`<ul class="upstream-rows">${prs.map((pr) => prRow(pr, now))}</ul>`;
  } else if (data.prs_state === "checking") {
    prsBody = state("unmeasured", "Checking recent merged PRs", "GitHub lookup in progress.");
  } else if (data.prs_state === "unknown") {
    prsBody = state("unmeasured", "Recent merged PRs unknown", prReason || "GitHub unavailable.");
  } else {
    prsBody = state("empty", "No merged PRs in window", "No PRs merged in the last " + (data.window_hours || 48) + " hours.");
  }
  const aside = data.checked_at ? "Checked " + since(data.checked_at, now) : "";
  return html`<section class="section">
    ${sectionHead("", "What's live", aside)}
    ${bridgePanel(data, now)}
    ${realmPanel(data, now)}
    ${prReason && prs.length ? state("stale", "PR states partial", prReason) : ""}
    ${prsBody}
  </section>`;
}
