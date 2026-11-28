// Epic journeys: every epic item copy's life as a short timeline, on a
// guild's Chronicle tab.
//
// The server writes every sentence (epicjourney.py through /api/v2/journeys):
// where it dropped and how it was won, the loot council's decision, every
// hand-over and equip, how it ended, and a flag line for a decision worth a
// human look. This only draws them, filtered by character (?who= in the URL).

import { html, raw, state, pendingRead, item, plural } from "../ui.js";
import { since } from "../models/time.js";

export const CSS = "views/journeys.css";
export const read = (guildSlug) => "/api/v2/journeys?guild=" + encodeURIComponent(guildSlug);

const SHOWN = 12;
const STEP_ICON = {
  won: "ph-fill ph-dice-five", council: "ph ph-scales", handed: "ph ph-hand-arrow-up",
  equipped: "ph-fill ph-t-shirt", sold: "ph ph-coins",
};
const END_TONE = { sold: "warn", worn: "ok", in_bags: "dim" };
const END_WORD = { sold: "Sold", worn: "Worn", in_bags: "In bags" };

function councilBlock(c) {
  if (!c) return "";
  const pct = (n) => (n > 0 ? "+" + n + "%" : n + "%");
  const rows = (c.candidates || []).map((x) => html`<li class="ej-cand"><span class="ej-cand-name">${x.name}${x.family ? "" : html` <span class="muted">(guild)</span>`}</span><span class="muted">score ${Number(x.score || 0).toFixed(1)}, ${pct(x.upgrade_percent || 0)}${x.wearable ? "" : ", cannot wear"}</span></li>`);
  const who = c.recipient || "nobody";
  const reason = c.reason || c.heuristic_why || "";
  return html`<details class="fold ej-council"><summary>Loot council: picked ${who}${c.decided_by ? ", decided by " + c.decided_by : ""}${reason ? ": " + reason : ""}</summary>
${c.heuristic_why && c.reason && c.heuristic_why !== c.reason ? html`<p class="muted">${c.heuristic_why}</p>` : ""}
${c.given_to && c.given_to !== c.recipient ? html`<p class="muted">Given to ${c.given_to}.</p>` : ""}
${rows.length ? html`<ul class="ej-cands">${rows}</ul>` : html`<p class="muted">No candidate was recorded.</p>`}
</details>`;
}

// The people line in a card's head: the cast in the order the item passed
// through them, and where it ended. From `who` and the ending, both already
// sent; it is what lets a reader scan for one member without reading steps.
function peopleLine(j) {
  const end = END_WORD[(j.ending || {}).state] || "Unknown";
  const names = (j.who && j.who.length) ? j.who : ((j.ending || {}).who ? [j.ending.who] : []);
  if (!names.length) return end;
  return names[0] + names.slice(1).map((n) => ", via " + n).join("") + ", " + end;
}

// Whether the last step already tells the ending (a sale step names the
// seller and the price, an equip step the wearer), so the ending paragraph
// would only say it again. An ending that adds something the steps do not
// say, the holder and the hedge, stays.
function endingTold(j) {
  const steps = j.steps || [];
  const last = steps[steps.length - 1];
  const state = (j.ending || {}).state;
  return !!last && ((state === "sold" && last.kind === "sold") || (state === "worn" && last.kind === "equipped"));
}

function card(j) {
  const end = j.ending || {};
  const steps = (j.steps || []).map((s) => html`<li class="ej-step" data-kind="${s.kind}"><i class="${STEP_ICON[s.kind] || "ph ph-circle"}" aria-hidden="true"></i><span class="ej-text">${s.text}</span><span class="muted ej-when">${since(s.at)}</span></li>`);
  const flags = (j.flags || []).map((f) => html`<p class="ej-flag"><i class="ph-fill ph-warning" aria-hidden="true"></i> ${f}</p>`);
  return html`<article class="card ej-card"${flags.length ? raw(' data-flagged="true"') : ""}>
<div class="ej-head">${item(j.item || {})}<span class="tag ej-end" data-gt="${END_TONE[end.state] || "dim"}">${END_WORD[end.state] || "Unknown"}</span></div>
<div class="ej-people">${peopleLine(j)}</div>
${flags}
<ol class="ej-steps">${steps}</ol>
${endingTold(j) ? "" : html`<p class="ej-ending">${end.text || ""}</p>`}
${councilBlock(j.council)}
</article>`;
}

// The section's body from the /api/v2/journeys read, kept to `who` when set.
// Flagged journeys, the ones worth a human look, sort first, and the count
// line under the filter says how many journeys are shown and how many of
// them need that look.
export function section(r, who) {
  const wait = pendingRead(r, 2);
  if (wait) return wait;
  const all = (r.data && r.data.journeys) || [];
  const names = [...new Set(all.flatMap((j) => j.who || []))].sort();
  const kept = who ? all.filter((j) => (j.who || []).includes(who)) : all;
  const shown = kept.slice().sort((a, b) => ((b.flags || []).length ? 1 : 0) - ((a.flags || []).length ? 1 : 0));
  const options = names.map((n) => html`<option value="${n}"${n === who ? raw(" selected") : ""}>${n}</option>`);
  const filter = names.length ? html`<label class="ej-filter"><span class="muted">Character</span><select class="input ej-who" aria-label="Show the journeys of one character"><option value="">Everyone</option>${options}</select></label>` : "";
  if (!shown.length) return html`${filter}${state("empty", "No epic journey", (r.data && r.data.empty) || "")}`;
  const flagged = shown.filter((j) => (j.flags || []).length).length;
  let countLine = plural(shown.length, "journey") + (who ? " for " + who : "");
  if (flagged) countLine += ", " + (flagged === 1 ? "1 needs a look" : flagged + " need a look");
  const count = html`<p class="ej-count muted">${countLine}</p>`;
  const first = shown.slice(0, SHOWN), rest = shown.slice(SHOWN);
  return html`${filter}${count}<div class="ej-list">${first.map(card)}</div>
${rest.length ? html`<details class="fold ej-more"><summary>${plural(rest.length, "older journey")}</summary><div class="ej-list">${rest.map(card)}</div></details>` : ""}
<details class="fold"><summary>How this is worked out</summary><p class="muted">${(r.data && r.data.basis) || ""}</p></details>`;
}

// After a draw: the character filter rewrites ?who= in the URL and redraws.
export function bind(main) {
  const sel = main.querySelector(".ej-who");
  if (!sel) return;
  sel.addEventListener("change", () => {
    const [path, query] = location.hash.split("?");
    const q = new URLSearchParams(query || "");
    if (sel.value) q.set("who", sel.value);
    else q.delete("who");
    const s = q.toString();
    history.replaceState(null, "", path + (s ? "?" + s : ""));
    window.dispatchEvent(new Event("overseer:redraw"));
  });
}
