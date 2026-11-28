// What is live right now across the bridge follower, the running realm,
// and merged pull requests from the last 48 hours (/api/v2/whats-live).
//
// The section leads with one sentence computed from the read itself, and
// the detail sits in a fold under it. PR states are toned, because on this
// page the whole question is whether a PR actually reached the realm:
// Live proven is not Merged, and the tags must not pretend otherwise.

import {
  html,
  raw,
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

const STATE_TONE = {
  "live-proven": "tag-ok",
  deployed: "tag-accent",
  merged: "tag-neutral",
  unknown: "tag-outline",
};

function shortDigest(d) {
  if (!d || d === "unknown") return "";
  return d.length > 19 ? d.slice(0, 19) : d;
}

function unmeasuredText(v, reason) {
  return html`${notMeasured(reason || v || "unknown")}`;
}

// The realm state arrives in the realm's own capitals ("UP"); the tiers
// above say "Up", and so does this panel.
function stateWord(s) {
  const v = String(s);
  return v === v.toUpperCase() ? v.charAt(0) + v.slice(1).toLowerCase() : v;
}

// One sentence from what the read already carries: where the bridge is,
// what the realm runs, whether the pins agree, and the PR counts by state.
function verdictLine(data) {
  const b = data.bridge || {};
  const r = data.realm || {};
  const bits = [];
  if (b.commit && b.commit !== "unknown") bits.push("Bridge at " + (b.short || b.commit.slice(0, 12)));
  if (r.module_commit && r.module_commit !== "unknown") bits.push("realm module " + r.module_commit.slice(0, 12));
  if (r.pins === "match") bits.push("pins match");
  else if (r.pins === "stale") bits.push("pins stale");
  const prs = data.prs || [];
  const counts = [];
  for (const key of Object.keys(STATE_LABEL)) {
    const n = prs.filter((p) => p.state === key).length;
    if (n) counts.push(n + " " + STATE_LABEL[key].toLowerCase());
  }
  const parts = [];
  if (bits.length) parts.push(bits.join(", "));
  if (counts.length) {
    // The window is stated only when the read reports it; an unreported
    // window is not filled in with the server's usual 48.
    parts.push(counts.join(", ") + (data.window_hours ? " in the last " + data.window_hours + " hours" : ""));
  } else if (data.prs_state === "checking") {
    parts.push("PR check running");
  }
  return parts.length ? parts.join("; ") + "." : "Nothing measured yet.";
}

function shipPr(data) {
  const n = (data.bridge || {}).ship_pr;
  if (!n) return notMeasured("unknown");
  const pr = (data.prs || []).find((p) => p.number === n);
  if (pr && isHttps(pr.url)) {
    return html`<a href="${pr.url}" target="_blank" rel="noopener">#${n}</a>`;
  }
  return "#" + n;
}

function bridgePanel(data, now) {
  const b = data.bridge || {};
  const reason = (data.unmeasured && data.unmeasured.bridge) || "";
  const commit = (!b.commit || b.commit === "unknown")
    ? unmeasuredText("unknown", reason)
    : html`<code data-copy="${b.commit}" title="Tap to copy the full commit">${b.short || b.commit.slice(0, 12)}</code>`;
  const digest = (!b.digest || b.digest === "unknown")
    ? notMeasured("unknown")
    : html`<code data-copy="${b.digest}" title="Tap to copy the full digest">${shortDigest(b.digest)}</code>`;
  const rolled = (!b.deployed_at || b.deployed_at === "unknown")
    ? notMeasured("unknown")
    : since(b.deployed_seconds !== undefined && b.deployed_seconds !== null ? b.deployed_seconds : b.deployed_at, now);
  return html`<div class="panel">
    <h3 class="kicker">Bridge</h3>
    <div class="kpis">
      ${kpi("Commit", commit)}
      ${kpi("Image", digest)}
      ${kpi("Rolled", rolled)}
      ${kpi("Ship PR", shipPr(data))}
    </div>
    ${reason ? html`<p class="small">${reason}</p>` : ""}
  </div>`;
}

function realmPanel(data, now) {
  const r = data.realm || {};
  const reason = (data.unmeasured && data.unmeasured.realm) || "";
  const realmState = (!r.state || r.state === "unknown")
    ? unmeasuredText("unknown", reason)
    : stateWord(r.state);
  const modCommit = (!r.module_commit || r.module_commit === "unknown")
    ? unmeasuredText("unknown", reason)
    : html`<code data-copy="${r.module_commit}" title="Tap to copy the full commit">${r.module_commit.slice(0, 12)}</code>`;
  const coreRev = (!r.core_revision || r.core_revision === "unknown")
    ? notMeasured("unknown")
    : html`<code data-copy="${r.core_revision}" title="Tap to copy the full revision">${r.core_revision.slice(0, 12)}</code>`;
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
  const tone = STATE_TONE[pr.state] || "tag-outline";
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
      <span class="tag ${tone}">${label}</span>
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
    return html`<section class="section" id="sv-live">${sectionHead("", "What's live")}${wait}</section>`;
  }
  if (readState(read) === "refused") {
    const err = read && read.data && read.data.error ? read.data.error : "";
    return html`<section class="section" id="sv-live">${sectionHead("", "What's live")}${state("error", "What's live failed", err)}</section>`;
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
  // A check in flight does not blank the list: the last good one stays,
  // under a banner that says that is what it is.
  const checking = data.prs_state === "checking" && prs.length
    ? state("stale", "Checking GitHub", "The list below is the last good one while the check runs.")
    : "";
  const needsAction = Object.keys(data.unmeasured || {}).length > 0 || data.prs_state === "unknown";
  const aside = data.checked_at ? "Checked " + since(data.checked_at, now) : "";
  return html`<section class="section" id="sv-live">
    ${sectionHead("", "What's live", aside)}
    <details class="fold sv-fold"${needsAction ? raw(" open") : ""}>
      <summary><span class="sv-line">${verdictLine(data)}</span></summary>
      <div class="sv-body">
        ${bridgePanel(data, now)}
        ${realmPanel(data, now)}
        ${prReason && prs.length ? state("stale", "PR states partial", prReason) : ""}
        ${checking}
        ${prsBody}
      </div>
    </details>
  </section>`;
}
