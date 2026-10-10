// Operator actions. Talking to a character, decrees, starting and stopping
// streams and pointing the Watcher queue commands the realm acts on, so they
// live here, apart from the read-only app, and render locked unless the
// server's operator setting is on. This view only reads; it sends nothing.

import { html, pageHead, state, pendingRead } from "../ui.js";

const CARDS = [
  { key: "job", title: "Standing job", send: "Send the job" },
  { key: "campaign", title: "Campaign counter", send: "Set the counter" },
  { key: "queue", title: "Dungeon queue", send: "Set the queue" },
];

function nowLine(key, d) {
  if (key === "job") return d.job && d.job.line;
  if (key === "campaign") return d.campaign && [d.campaign.line, d.campaign.means].filter(Boolean).join(" ");
  if (key === "queue") {
    const fams = (d.families || []).map((f) => f.queue && (f.queue.line || "")).filter(Boolean);
    return fams.length ? fams.join(" ") : null;
  }
  return null;
}

function chips(key, d) {
  if (key !== "job" || !d.job || !d.job.chips) return [];
  return d.job.chips.map((c) => ({ text: c.mode, on: c.mode === d.job.standing, ok: c.sendable }));
}

export default {
  reads: () => ["/api/v2/operator", "/api/decree"],
  every: 30000,
  title: () => "Operator actions",
  render(ctx) {
    const op = ctx.get("/api/v2/operator");
    const dec = ctx.get("/api/decree");
    const enabled = !!(op.data && op.data.enabled);
    const lock = enabled
      ? html`<div class="card" style="max-width:640px"><span class="card-title" style="display:flex;gap:8px;align-items:center"><i class="ph ph-lock-simple-open" aria-hidden="true"></i>On for this deployment</span><span class="muted">The operator setting is on. The controls are not drawn in this view yet; the server's endpoints for them are unchanged.</span></div>`
      : html`<div class="card" style="max-width:640px"><span class="card-title" style="display:flex;gap:8px;align-items:center"><i class="ph ph-lock-simple" aria-hidden="true"></i>Off on this deployment</span><span class="muted" style="text-wrap:pretty">Talking to a character, decrees, starting and stopping streams, and pointing the Watcher all queue commands the realm acts on. The rest of this app is read-only. These live on this separate route, which only works when the operator setting is turned on on the server.</span></div>`;
    const wait = pendingRead(dec, 3);
    const d = dec.data || {};
    const cards = wait || html`<div class="grid">${CARDS.map((c) => {
      const sec = (d.sections || []).find((s) => s.key === c.key) || {};
      const now = nowLine(c.key, d);
      return html`<div class="card" style="padding:14px 16px;gap:8px"><span class="card-title">${sec.title || c.title}</span><span class="muted">${now || html`<span class="unmeasured">Current state not measured</span>`}</span>${chips(c.key, d).length ? html`<div class="row">${chips(c.key, d).map((ch) => html`<span class="tag ${ch.on ? "tag-outline" : "tag-neutral"}">${ch.text}</span>`)}</div>` : ""}<span class="dim" style="font-size:var(--fs-1)">${sec.does || ""}</span><button type="button" class="btn btn-primary" disabled style="align-self:flex-start"><i class="ph ph-lock-simple" aria-hidden="true"></i>${c.send}</button></div>`;
    })}</div>`;
    return html`${pageHead("Operator actions")}${lock}${dec.error && dec.data ? state("stale", "Showing the last answer", "The decree read failed; the cards below are from earlier.") : ""}${cards}`;
  },
};
