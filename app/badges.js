// Badges on the section nav: Members carries the stuck count, Guilds the
// chronicle items new since this device's last visit. Each provider is
//   { section, reads: [paths], compute(get, ctx) -> {n, tone, label, href} | null }
// and is refreshed on its own clock, whatever view is on screen. Sections add
// their provider here.
export default [
  // Members: a warn badge with the stuck count (/api/v2/stuck), and the tab
  // opens the roster filtered to them while anyone is stuck.
  {
    section: "members",
    reads: ["/api/v2/stuck"],
    compute(get) {
      const s = get("/api/v2/stuck");
      const n = s.data && Array.isArray(s.data.members) ? s.data.members.length : 0;
      return n ? { n, tone: "warn", label: n + " stuck", href: "#/members?stuck=1" } : null;
    },
  },
];
