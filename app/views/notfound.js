import { html, pageHead } from "../ui.js";

export default {
  reads: () => [],
  title: () => "Not found",
  render(ctx) {
    return html`${pageHead("Not found")}<div class="card" style="max-width:560px;padding:16px;gap:8px"><span>Nothing lives at ${ctx.hash || "this address"}. It may be an old link.</span><div class="row"><a href="#/now" class="btn btn-primary">Now</a><a href="#/members" class="btn btn-secondary">All members</a></div></div>`;
  },
};
