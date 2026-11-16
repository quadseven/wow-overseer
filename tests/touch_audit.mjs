// Node jsdom-free touch-target audit helper for phone routes (390px, pointer: coarse).
// Parses stylesheet rules (including @media (pointer: coarse)) and rendered HTML
// markup to report interactive targets under 44 px on touch.

import fs from "node:fs";
import path from "node:path";

export const MIN_TOUCH_PX = 44;

function stripComments(css) {
  return css.replace(/\/\*[\s\S]*?\*\//g, "");
}

function parseDeclarations(body) {
  const decls = {};
  for (const part of body.split(";")) {
    const idx = part.indexOf(":");
    if (idx === -1) continue;
    const prop = part.slice(0, idx).trim().toLowerCase();
    const val = part.slice(idx + 1).trim();
    if (prop) decls[prop] = val;
  }
  return decls;
}

export function parseCssRules(cssText) {
  const text = stripComments(cssText);
  const rules = [];
  let i = 0;
  while (i < text.length) {
    while (i < text.length && /\s/.test(text[i])) i++;
    if (i >= text.length) break;
    if (text[i] === "@") {
      const brace = text.indexOf("{", i);
      if (brace === -1) break;
      const header = text.slice(i, brace).trim();
      let depth = 1;
      let j = brace + 1;
      while (j < text.length && depth > 0) {
        if (text[j] === "{") depth++;
        else if (text[j] === "}") depth--;
        j++;
      }
      const inner = text.slice(brace + 1, j - 1);
      if (/^@media\s*\(\s*pointer:\s*coarse\s*\)/i.test(header)) {
        for (const r of parseCssRules(inner)) {
          rules.push({ ...r, coarse: true });
        }
      }
      i = j;
      continue;
    }
    const brace = text.indexOf("{", i);
    if (brace === -1) break;
    const selText = text.slice(i, brace).trim();
    const close = text.indexOf("}", brace + 1);
    if (close === -1) break;
    const decls = parseDeclarations(text.slice(brace + 1, close));
    for (const rawSel of selText.split(",")) {
      const sel = rawSel.trim();
      if (sel) rules.push({ sel, decls, coarse: false });
    }
    i = close + 1;
  }
  return rules;
}

function parsePx(val) {
  if (!val) return null;
  const m = String(val).match(/^(-?\d+(?:\.\d+)?)px$/i);
  return m ? Number(m[1]) : null;
}

function parseAttrs(attrStr) {
  const attrs = {};
  const re = /([a-zA-Z_:][\w:.-]*)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+)))?/g;
  let m;
  while ((m = re.exec(attrStr)) !== null) {
    attrs[m[1].toLowerCase()] = m[2] ?? m[3] ?? m[4] ?? "";
  }
  return attrs;
}

function matchCompound(el, compound) {
  let s = compound.trim();
  if (!s) return false;
  let notNoClass = false;
  s = s.replace(/:not\(\[class\]\)/g, () => {
    notNoClass = true;
    return "";
  });
  if (notNoClass && el.classes.length > 0) return false;
  s = s.replace(/\[([a-zA-Z0-9_-]+)(?:="([^"]*)")?\]/g, (_, k, v) => {
    if (!(k in el.attrs)) return "\0FAIL";
    if (v !== undefined && el.attrs[k] !== v) return "\0FAIL";
    return "";
  });
  if (s.includes("\0FAIL")) return false;
  const classes = [];
  s = s.replace(/\.([a-zA-Z0-9_-]+)/g, (_, c) => {
    classes.push(c);
    return "";
  });
  for (const c of classes) {
    if (!el.classes.includes(c)) return false;
  }
  const tag = s.replace(/:[a-zA-Z0-9_-]+(\([^)]*\))?/g, "").trim().toLowerCase();
  if (tag && tag !== "*" && tag !== el.tag) return false;
  return true;
}

function matchSelector(el, ancestors, selector) {
  const clean = selector.replace(/::(before|after)$/i, "").trim();
  const tokens = [];
  let buf = "";
  for (const ch of clean) {
    if (ch === ">") {
      if (buf.trim()) tokens.push(buf.trim());
      tokens.push(">");
      buf = "";
    } else if (/\s/.test(ch)) {
      if (buf.trim()) {
        tokens.push(buf.trim());
        buf = "";
      }
    } else {
      buf += ch;
    }
  }
  if (buf.trim()) tokens.push(buf.trim());
  if (!tokens.length) return false;

  if (!matchCompound(el, tokens[tokens.length - 1])) return false;
  let ti = tokens.length - 2;
  let ai = ancestors.length - 1;
  while (ti >= 0) {
    if (tokens[ti] === ">") {
      ti--;
      if (ai < 0 || !matchCompound(ancestors[ai], tokens[ti])) return false;
      ai--;
      ti--;
    } else {
      while (ai >= 0 && !matchCompound(ancestors[ai], tokens[ti])) ai--;
      if (ai < 0) return false;
      ai--;
      ti--;
    }
  }
  return true;
}

const VOID_TAGS = new Set(["area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr", "circle", "path", "rect", "line", "polyline"]);

export function auditHtml(htmlText, rules, route = "unknown") {
  const stack = [];
  const targets = [];
  const tagRe = /<\/?([a-zA-Z][a-zA-Z0-9-]*)([^>]*?)(\/?)>/g;
  let m;
  while ((m = tagRe.exec(htmlText)) !== null) {
    const raw = m[0];
    const tag = m[1].toLowerCase();
    const isClose = raw.startsWith("</");
    if (isClose) {
      for (let k = stack.length - 1; k >= 0; k--) {
        if (stack[k].tag === tag) {
          const closed = stack.splice(k)[0];
          if (closed._target) closed._target.inner += closed._inner || "";
          break;
        }
      }
      continue;
    }
    const attrs = parseAttrs(m[2]);
    const classes = (attrs.class || "").split(/\s+/).filter(Boolean);
    const el = { tag, attrs, classes, _inner: "" };

    if (tag === "circle" && stack.length) {
      const parentAnchor = [...stack].reverse().find((s) => s.tag === "a" && s._target);
      if (parentAnchor && attrs.r) {
        const r = Number(attrs.r);
        if (Number.isFinite(r)) {
          parentAnchor._target.circleDiameters.push(r * 2);
        }
      }
    }

    const isInteractive = tag === "a" || tag === "button" || tag === "summary";
    if (isInteractive) {
      const ancestors = stack.slice();
      const base = {};
      const pseudo = {};
      for (const r of rules) {
        const isPseudo = /::(before|after)$/i.test(r.sel);
        if (matchSelector(el, ancestors, r.sel)) {
          Object.assign(isPseudo ? pseudo : base, r.decls);
        }
      }
      const target = {
        route,
        tag,
        classes,
        href: attrs.href || "",
        ariaLabel: attrs["aria-label"] || "",
        base,
        pseudo,
        inner: "",
        circleDiameters: [],
      };
      el._target = target;
      targets.push(target);
    }

    const selfClose = m[3] === "/" || VOID_TAGS.has(tag);
    if (!selfClose) stack.push(el);
  }

  const offenders = [];
  const chartStrips = [];
  for (const t of targets) {
    // SVG map pin hit circle: diameter in viewBox units, scaled by caller if needed.
    if (t.classes.includes("wm-dot")) {
      const maxD = t.circleDiameters.length ? Math.max(...t.circleDiameters) : 0;
      if (maxD < MIN_TOUCH_PX) {
        offenders.push({ route, tag: t.tag, class: t.classes.join(" "), width: maxD, height: maxD, reason: "svg hit circle < 44" });
      }
      continue;
    }
    // Documented narrow chart strip (.histo a.hit): stays as-is to avoid neighbor overlap.
    if (t.classes.includes("hit")) {
      chartStrips.push({ route, tag: t.tag, class: t.classes.join(" "), documented: true, width: 12, height: 96 });
      continue;
    }

    const minH = parsePx(t.base["min-height"]) ?? parsePx(t.base["height"]) ?? 0;
    const minW = parsePx(t.base["min-width"]) ?? parsePx(t.base["width"]) ?? 0;
    const pMinH = parsePx(t.pseudo["min-height"]) ?? parsePx(t.pseudo["height"]) ?? 0;
    const pMinW = parsePx(t.pseudo["min-width"]) ?? parsePx(t.pseudo["width"]) ?? 0;

    // Cards/rows/full-width links span container width (~358px at 390px viewport).
    const isBlockFull = t.classes.some((c) =>
      ["card", "qs-cover-name", "qs-zone-name", "qs-qcard", "eco-rich", "eco-group-link", "eco-shut", "eco-btab", "g-row", "g-seat-row"].includes(c)
    );
    const disp = t.base.display || "";
    const textEstW = Math.max(19, t.ariaLabel.length * 7);
    const effW = Math.max(minW, pMinW, isBlockFull || disp === "flex" || disp === "block" ? 320 : textEstW);
    const effH = Math.max(minH, pMinH);

    if (effH < MIN_TOUCH_PX || effW < MIN_TOUCH_PX) {
      offenders.push({
        route,
        tag: t.tag,
        class: t.classes.join(" "),
        href: t.href,
        width: effW,
        height: effH,
      });
    }
  }
  return { route, total: targets.length, offenders, chartStrips };
}

export function loadAppRules(appDir) {
  const names = ["quests.css", "economy.css", "map.css", "now.css", "guild.css"];
  const files = [path.join(appDir, "app.css")];
  for (const name of names) {
    const inViews = path.join(appDir, "views", name);
    files.push(fs.existsSync(inViews) ? inViews : path.join(appDir, name));
  }
  const css = files.filter((f) => fs.existsSync(f)).map((f) => fs.readFileSync(f, "utf8")).join("\n");
  return parseCssRules(css);
}
