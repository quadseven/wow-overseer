// Badges on the section nav: Members carries the stuck count, Guilds the
// chronicle items new since this device's last visit. Each provider is
//   { section, reads: [paths], compute(get, ctx) -> {n, tone, label, href} | null }
// and is refreshed on its own clock, whatever view is on screen. Sections add
// their provider here.
export default [];
