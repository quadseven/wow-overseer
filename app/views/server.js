// Server: the eye's tiers (/api/eye), each reporting for itself, smallest
// real thing first. A tier that does not answer is shown as off, never as up.

import { html, kpi, state } from "../ui.js";
import * as D from "./now/data.js";

const HUE = { green: "var(--ok)", amber: "var(--warn)", vermilion: "var(--bad)" };
const WORD = { ON: "Up", PARTIAL: "Partial", OFF: "Off" };

function tierRow(t) {
  const color = HUE[t.hue] || "var(--color-neutral-500)";
  const word = WORD[t.state] || t.state || "not measured";
  return html`<div class="tier"><span class="b">${t.tier.charAt(0) + t.tier.slice(1).toLowerCase()}</span><span class="tier-state" style="color:${color}"><span class="rdot" style="background:${color}" aria-hidden="true"></span>${word}${t.value ? html` <span class="dim num">${t.value}</span>` : ""}</span><span class="muted">${t.headline}${t.switch ? html` <span class="warn">${t.switch}</span>` : ""}</span></div>`;
}

export default {
  css: ["views/now.css"],
  reads: () => ["/api/eye"],
  every: 30000,
  title: () => "Server",
  render(ctx) {
    const read = ctx.get("/api/eye");
    let body;
    if (D.ok(read)) {
      const e = read.data;
      const up = (e.tiers || []).filter((t) => t.state === "ON").length;
      body = html`<div class="card server-note"><span class="b">${up} of ${(e.tiers || []).length} tiers on</span><span class="muted">${e.honest || "Each tier reports for itself. A tier that does not answer is shown as off, never as up."}</span></div>
<div class="server-kpis">${(e.strip || []).map((s) => kpi(s.label.charAt(0) + s.label.slice(1).toLowerCase(), s.value))}</div>
<div class="card rows tiers">${(e.tiers || []).map(tierRow)}</div>`;
    } else if (read.data === undefined && !read.error) {
      body = html`<div class="skeletons" aria-busy="true"><div class="skeleton"></div></div>`;
    } else {
      body = state("error", "The world did not answer", "The server tiers could not be read, so none of them is shown as up.");
    }
    return html`<a class="back" href="#/now"><i class="ph ph-caret-left" aria-hidden="true"></i>Now</a><h1>Server</h1>${body}`;
  },
};
