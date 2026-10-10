# The Overseer app

A read-only operations app for the realm: plain HTML, CSS and ES modules served by `map_server.py`. No framework and no build step. `index.html` loads `app/main.js`, and everything else is imported from there.

## Files

| File | What it holds |
|---|---|
| `tokens.css` | Design tokens: colours (dark and light), type scale, status, quality and class colours, radii, shadows. |
| `app.css` | Base styles, components (buttons, cards, tags, tables), the shell, and the shared primitives. |
| `main.js` | Boot: theme, shell, router, polling, search, tooltip, gestures, nav badges. |
| `router.js` | Hash routes, legacy redirects, and route-to-view resolution. Pure functions, tested under node. |
| `api.js` | Reads (`load`, `peek`, `watch`), the mount helper `u()`, the data age (`health`), and `post()`, the operator view's one write. |
| `ui.js` | The `html` builder (escapes every value) and the primitives: `status`, `member`, `memberChip`, `item`, `state`, `pendingRead`, `pageHead`, `sectionHead`, `tabs`, `kpi`, `sparkline`, `histogram`, `notMeasured`, `value`, `ago`, `gold`. |
| `tooltip.js` | The one item tooltip, for any element with `data-item="<entry>"`. It reads `/api/item`. |
| `search.js` | The search dialog and `addProvider(fn)`. |
| `shell.js` | The sidebar, phone header and tab bar, data age, `setBadge`, and `setThumb` (the Cave/Bonkers switch on phone). |
| `badges.js` | Nav badge providers. |
| `views/<name>.js` | One view per route kind. |
| `views/<name>.css` | That view's own styles, listed in its `css`. |

## A view

```js
import { html, pageHead, pendingRead } from "../ui.js";

export default {
  css: ["views/now.css"],                       // optional
  reads: (ctx) => ["/api/realm", "/api/agenda"], // polled while on screen
  every: 15000,                                  // poll interval, ms
  quick: { reads: ["/api/realm"], every: 5000 }, // optional: cheap reads polled faster
  title: (ctx) => "Now",
  render(ctx) {                                  // markup from the cache only
    const realm = ctx.get("/api/realm");         // {data, at, error, failures, loading}
    const wait = pendingRead(realm, 3);           // skeleton, or error with Retry
    if (wait) return html`${pageHead("Now")}${wait}`;
    return html`${pageHead("Now")}<p>${realm.data.realm}</p>`;
  },
  after(main, ctx) {},                           // optional: bind events after a draw
  thumb(ctx) { return null; },                   // optional: phone Cave/Bonkers switch
};
```

The `ctx` passed to every method is `{view, section, params, query, hash, get, isPhone, previousVisit}`.

- `render` is called again whenever one of its reads answers with new data. The scroll position and the focused input are kept across the redraw.
- Keep filter and sort state in the URL query (`#/members?stuck=1&sort=level&dir=asc`), so every view state can be linked. A sortable table header is `sortHead` from `views/_members.js`: clicking the column already sorted reverses it (`flipSort`).
- Polling stops while the page is hidden, and every read is asked again at once when the page comes back on screen or the network comes back.

## Rules

- **Read-only.** No view sends a POST except `#/operator`, which draws no form unless `/api/v2/operator` reports the operator setting on. Its forms send through `post()` in `api.js`, only after a confirmation step, to the existing POST routes.
- **Every number comes from the server.** When the server does not report a value, show `notMeasured()` ("not measured"), never 0, a dash or a guess.
- **Every URL goes through the mount.** Build reads with paths like `/api/...`, and `api.js` prefixes the mount. Never write an origin-relative URL into markup.
- **Copy:** ASCII only, no em dashes, sentence case.
- **Accessibility:** taps are at least 44px, focus is the 2px accent outline, body text contrast is at least 4.5:1, and nothing scrolls sideways at 375px.
- **Items:** draw an item with `item({entry, name, quality, icon, mark})`. The tooltip comes for free on hover, focus and tap.
- **New data** goes under `/api/v2/` as a module in `apiv2/` with a `ROUTES` table and unit tests.
