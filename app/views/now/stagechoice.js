// Which family is on Now's stage, and which streams a screen connects.
// Pure: no DOM, so node tests it.

// Options are [{fam, name, url}]: a family, its head character and that
// character's stream URL ("" when it is not streamed).

// The saved family when it still has a stream, else the first family with
// one, else "" (nothing to stage).
export function pickStaged(options, saved) {
  const streamed = options.filter((o) => o.url);
  if (saved && streamed.some((o) => o.fam === saved)) return saved;
  return streamed.length ? streamed[0].fam : "";
}

// A narrow screen connects the staged stream only and lets the rest go;
// a wide one connects every head, as the wall always has.
export function connectPlan(options, staged, narrow) {
  if (!narrow) return { connect: options.map((o) => ({ name: o.name, url: o.url })), release: [] };
  const on = options.find((o) => o.fam === staged && o.url);
  return {
    connect: on ? [{ name: on.name, url: on.url }] : [],
    release: options.filter((o) => o !== on).map((o) => o.name),
  };
}
