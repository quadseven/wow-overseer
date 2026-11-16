// The realm state banner: one line at the top of every page when the
// worldserver is not simply up (GET /api/v2/realm-status, apiv2/realm_status.py).
//
// Pure, so it is checked under node without a browser. Nothing is shown for
// UP or for a status that could not be read: an unmeasured realm is not a
// reason to put a line over every page.

const ALERT = ["OVERRUN", "DOWN_UNEXPLAINED"];

// {show, tone, text} for the banner. `bad` for the two states someone must act
// on; `warn` for a window inside its ETA, a boot, or a recent restart.
export function realmLine(status) {
  if (!status || !status.state || status.state === "UP" || status.state === "UNKNOWN") {
    return { show: false, tone: "", text: "" };
  }
  const text = status.summary || "Realm state: " + status.state;
  return { show: true, tone: ALERT.includes(status.state) || status.alert ? "bad" : "warn", text };
}
