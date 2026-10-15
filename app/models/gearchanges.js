const PREFIX = "overseer.gear-since.";
const initial = new Map();

export function pageKey(member = "") { return member ? "member:" + member.toLowerCase() : "site"; }

export function since(key, storage, now = Date.now()) {
  try {
    storage = storage || window.localStorage;
    const stored = storage.getItem(PREFIX + key);
    const value = stored === null ? NaN : Number(stored);
    if (Number.isSafeInteger(value) && value > 0 && value <= 8640000000000000) {
      return new Date(value).toISOString();
    }
    if (!initial.has(key)) initial.set(key, new Date(now - 86400000).toISOString());
    return initial.get(key);
  } catch (error) {
    return new Date(now - 86400000).toISOString();
  }
}

export function markSeen(key, storage, now = Date.now()) {
  initial.set(key, new Date(now).toISOString());
  try { (storage || window.localStorage).setItem(PREFIX + key, String(now)); } catch (error) { return false; }
  return true;
}
