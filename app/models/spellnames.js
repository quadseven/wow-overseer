// Names for class trainer spells, from the classic client spell table.
// Keep rank in the name where the client distinguishes spell ranks.
const SPELL_NAMES = {
  750: "Plate Mail",
  11566: "Heroic Strike (Rank 7)",
};

export function classSpellName(spell) {
  const id = Number(spell) || 0;
  return SPELL_NAMES[id] || "Spell " + id;
}

export function wowheadSpellUrl(spell) {
  return "https://www.wowhead.com/wotlk/spell=" + (Number(spell) || 0);
}
