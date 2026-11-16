// Register the mount-scoped app-shell worker after first paint on secure
// origins. Missing support or registration failure leaves drawing untouched.

import { u } from "./api.js";

export function registerWorker(win, nav) {
  const w = win || (typeof window !== "undefined" ? window : null);
  const n = nav || (typeof navigator !== "undefined" ? navigator : null);
  if (!w || !n || !n.serviceWorker || typeof n.serviceWorker.register !== "function") {
    return Promise.resolve(null);
  }
  const secure = w.isSecureContext !== undefined
    ? !!w.isSecureContext
    : !!(w.location && (w.location.protocol === "https:" || /^(localhost|127\.0\.0\.1)$/.test(w.location.hostname || "")));
  if (!secure) return Promise.resolve(null);
  try {
    return Promise.resolve(n.serviceWorker.register(u("/sw.js"), { scope: u("/") })).catch(() => null);
  } catch (err) {
    return Promise.resolve(null);
  }
}

export function installWorker(win, doc, nav) {
  const w = win || (typeof window !== "undefined" ? window : null);
  const d = doc || (typeof document !== "undefined" ? document : null);
  if (!w || !d) return;
  const schedule = () => {
    const raf = w.requestAnimationFrame;
    if (typeof raf === "function") {
      raf(() => { registerWorker(w, nav); });
    } else {
      registerWorker(w, nav);
    }
  };
  if (d.readyState === "complete") {
    schedule();
  } else if (typeof w.addEventListener === "function") {
    w.addEventListener("load", schedule, { once: true });
  }
}
