// Spell names for the views, without paying for the table up front.
//
// models/spellnames.js is generated (tools/class_spell_names_from_dbc.py) and
// is over 200 KB. Importing it statically put it in the first load of every
// page that reaches the member view, the Now page among them. This module
// imports it on the first lookup instead and asks the page for one redraw
// when it arrives (main.js listens for overseer:redraw), so a page that never
// draws a spell never loads it. Until then, and if the table cannot be
// loaded, a spell reads as an unknown id does: "Spell <id>".

let table = null;
let loading = null;

function load() {
  if (!loading) {
    loading = import("./spellnames.js").then(
      (m) => {
        table = m;
        if (typeof window !== "undefined" && typeof Event === "function") window.dispatchEvent(new Event("overseer:redraw"));
      },
      () => { /* the fallback stays; the next lookup does not retry a missing file in a loop */ },
    );
  }
  return loading;
}

// The name of a class spell, or "Spell <id>" while the table is not here.
export function spellName(spell) {
  if (table) return table.classSpellName(spell);
  load();
  return "Spell " + (Number(spell) || 0);
}

// Resolves when the table's load has finished (for tests).
export function ready() { return loading || Promise.resolve(); }

export function wowheadSpellUrl(spell) {
  return "https://www.wowhead.com/wotlk/spell=" + (Number(spell) || 0);
}
