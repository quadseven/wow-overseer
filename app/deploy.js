// The deploy marker: which commit the bridge runs and for how long, and
// "restarting" while a rollout settles (deployinfo.py, /api/realm `deploy`).
//
// Pure, so it is checked under node without a browser.

const UP = [[86400, "d"], [3600, "h"], [60, "m"]];

export function uptime(secs) {
  const n = Math.max(0, Math.floor(Number(secs) || 0));
  for (const [size, unit] of UP) if (n >= size) return Math.floor(n / size) + unit;
  return n + "s";
}

// {text, restarting} for the footer. `deploy` is the realm's field (or
// undefined before it is known); `state` is api.health's: a stale or error
// read means the bridge stopped answering, which mid-rollout is a restart.
export function marker(deploy, state) {
  const down = state === "stale" || state === "error";
  const starting = !!(deploy && deploy.starting);
  if (starting || down) {
    const known = deploy && deploy.commit && deploy.commit !== "unknown" ? " (was " + deploy.commit + ")" : "";
    return { restarting: true, text: starting ? "Restarting: new build starting" : "Restarting or not answering" + known };
  }
  if (!deploy || !deploy.commit) return { restarting: false, text: "" };
  const pr = deploy.ship_pr ? " PR #" + deploy.ship_pr : "";
  return { restarting: false, text: "Build " + deploy.commit + pr + ", up " + uptime(deploy.uptime_seconds) };
}
