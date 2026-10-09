// A section that has not been rebuilt yet: one line saying so and a link to
// the same view on the classic page, so nothing is lost while the redesign
// lands section by section.

import { html, pageHead } from "../ui.js";
import { u } from "../api.js";
import { classicFor } from "../router.js";

export function pending(title, summary) {
  return {
    reads: () => [],
    title: () => title,
    render(ctx) {
      const href = u("/classic") + "#" + classicFor(ctx.view, ctx.params);
      return html`${pageHead(title, summary)}
<div class="card pending"><span class="card-title">This view is still on the classic page</span><span class="muted">It moves into this app in a later step of the redesign. Until then it opens in the classic page, with the same data.</span><div><a class="btn btn-primary" href="${href}">Open in the classic page</a></div></div>`;
    },
  };
}
