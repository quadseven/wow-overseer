"""The Armory tab's page contract: the rules that cost something to learn.

Asserted against index.html as source, the same way test_family_tab.py guards
the Family tab - map_server.py imports pymysql and the page has no other test
seam. These are not "does it render": they are the handful of rules that a
refactor could quietly undo while leaving five columns on screen looking
perfectly fine.

Two of them are about where this tab's code is ALLOWED to sit. The Family
tab's tests slice the page by its own banners - CSS from its banner to
</style>, JS from its banner to loadZones().then( - so Armory code placed
inside either window silently becomes part of a slice about a different tab
and starts failing assertions that have nothing to do with it. That happened
once while this tab was being built; these two tests are so it does not
happen again to whoever adds the third one.

Tickets: infra#3096 (the tab), infra#3139 (the profile).
"""
import pathlib
import unittest

import armory
import family

HERE = pathlib.Path(__file__).resolve().parent.parent


class WhereTheCodeIsAllowedToSit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = (HERE / "index.html").read_text()

    def test_the_styles_sit_above_the_family_banner(self):
        """ThumbSized and the broadcast-grid CSS tests both slice from a
        Family banner to </style>. Armory rules dropped into that window get
        read as Family rules."""
        self.assertLess(self.page.index("--- the Armory tab (infra#3096, infra#3139)"),
                        self.page.index("--- the Family tab (infra#2892)"))

    def test_the_script_sits_below_the_family_slice(self):
        """TheFamilyTab slices from its banner to loadZones().then(. Armory
        code in that window is swept into the Family tab's own tests."""
        self.assertGreater(self.page.index("// --- the Armory tab (infra#3096, infra#3139)"),
                           self.page.index("loadZones().then("))


class TheArmoryTab(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = (HERE / "index.html").read_text()
        cls.server = (HERE / "map_server.py").read_text()
        start = cls.page.index("// --- the Armory tab (infra#3096, infra#3139)")
        cls.tab = cls.page[start:cls.page.index("</script>", start)]
        # The Armory's OWN script, for the same reason cls.acss exists below:
        # cls.tab runs to the end of the script and so contains the standing
        # panel and the wealth grid, which are two other views sharing this
        # section. "The page never says this word" has to be asked of the
        # code that would have said it.
        cls.ajs = cls.tab[:cls.tab.index(
            "// --- the standing panel (mod-overseer#88, mod-overseer#160)")]
        css = cls.page.index("--- the Armory tab (infra#3096, infra#3139)")
        cls.css = cls.page[css:cls.page.index("--- the Family tab (infra#2892)")]
        # The Armory's OWN rules. cls.css runs to the Family banner, which
        # sweeps in the standing panel and the wealth grid - two views that
        # share this section and are not this tab. Anything asserted about
        # how the Armory paints has to be asserted here or it is asserting
        # something about somebody else's code.
        cls.acss = cls.css[:cls.css.index(
            "--- the standing panel (mod-overseer#88, mod-overseer#160)")]

    def test_the_tab_exists_beside_the_family_and_the_continents(self):
        self.assertIn('<section id="armory">', self.page)
        self.assertIn('ab.textContent = "Armory";', self.page)
        self.assertIn("ab.dataset.view = ARMORY_VIEW;", self.page)

    def test_a_third_tab_can_actually_light_up(self):
        """markTabs was a ternary hard-coded to FAMILY_VIEW: any other named
        view fell through to the continent branch, compared an undefined
        dataset.id against `current`, and could never be highlighted. The
        button worked and looked permanently unselected."""
        mark = self.page[self.page.index("function markTabs"):]
        mark = mark[:mark.index("function showView")]
        self.assertIn("view === b.dataset.view", mark)
        self.assertNotIn("FAMILY_VIEW", mark,
                         "markTabs must not know any view by name")

    def test_the_map_is_hidden_behind_every_view_that_is_not_the_map(self):
        """showView read 'not Family means map', so a third view would have
        drawn the canvas and the legend underneath itself."""
        show = self.page[self.page.index("function showView"):]
        show = show[:show.index("setInterval(pollFamily")]
        self.assertIn('wrapEl.style.display = view === MAP_VIEW ? "block" : "none";',
                      show)
        self.assertIn('legend.style.display = view === MAP_VIEW ? "" : "none";', show)

    def test_opening_the_tab_does_not_wait_for_the_timer(self):
        """Thirty seconds of blank page is indistinguishable from a broken
        tab, and it is the first thing anybody would see."""
        show = self.page[self.page.index("function showView"):]
        show = show[:show.index("setInterval(pollFamily")]
        arm = show[show.index("if (isArm) {"):]
        self.assertIn("pollArmory();", arm[:arm.index("return;")])

    def test_opening_the_tab_stops_the_broadcast_grid(self):
        """Five WHEP players kept running behind a view that shows none of
        them is 6Mbit across the tailnet for nothing."""
        show = self.page[self.page.index("function showView"):]
        show = show[:show.index("setInterval(pollFamily")]
        arm = show[show.index("if (isArm) {"):]
        self.assertIn("stopBroadcasts();", arm[:arm.index("return;")])

    def test_the_poll_is_gated_on_the_tab_being_open(self):
        """Every poll on this page guards on visibility rather than being
        started and stopped, because a timer that is only sometimes running is
        a timer somebody has to remember to restart."""
        poll = self.tab[self.tab.index("async function pollArmory"):]
        self.assertIn("if (view !== ARMORY_VIEW) return;", poll)

    def test_the_poll_is_deliberately_slower_than_every_other_poll(self):
        """The core writes gear and talents on its own save timer, so these
        rows cannot change at the 5s cadence the rest of the page uses. This
        is the one place a reviewer would 'fix' it back to 5000 for
        consistency, so the number and its reason are asserted together."""
        self.assertIn("setInterval(pollArmory, 30000);", self.tab)
        self.assertNotIn("setInterval(pollArmory, 5000)", self.page)
        self.assertIn("save timer", self.tab)

    def test_a_failed_poll_keeps_the_grid_it_has_already_drawn(self):
        """A blank Armory reads as 'they are wearing nothing', which is a
        worse lie than an old answer honestly labelled."""
        poll = self.tab[self.tab.index("async function pollArmory"):]
        poll = poll[:poll.index("setInterval(pollArmory")]
        self.assertIn("may be stale", poll)
        self.assertNotIn("textContent = \"\"", poll)

    def test_nothing_reaches_the_page_as_markup(self):
        """Item names come out of the world database. They are data, and data
        goes in through textContent."""
        self.assertNotIn("innerHTML", self.tab)
        self.assertNotIn("insertAdjacentHTML", self.tab)

    def test_the_roster_is_not_retyped_into_the_page(self):
        """WHO the family is belongs to bonds. A second list in the HTML is a
        second answer that can disagree with it, silently, by drawing four
        columns."""
        for name in family.roster():
            self.assertNotIn('"' + name + '"', self.tab)

    def test_the_slot_list_is_not_retyped_into_the_page(self):
        """Every profile draws the same cells in the same places exactly as
        long as one list decides what the slots are. The page must take
        that list from the payload and never name a slot itself."""
        for slot in armory.EQUIPPED_SLOTS:
            self.assertNotIn('"' + slot + '"', self.tab)

    def test_an_empty_slot_says_the_word_and_does_not_choose_it(self):
        """A blank cell reads as 'nothing to report'. An empty head slot on a
        level 25 warrior is the entire reason for opening this tab.

        WHICH word it says is armory.py's: a real gap says "empty" and a
        cosmetic slot says its own name, and that is a judgement about what
        an empty slot MEANS, not about how to draw one. The page used to
        make it in a ternary, where no test could reach it."""
        self.assertIn("cell.textContent = s.empty_label;", self.ajs)
        self.assertNotIn('"empty"', self.ajs, "the page names the state itself")
        # `s.cosmetic` may still pick a CSS class - how loud a cell is drawn
        # is the page's job. Picking the WORD is not.
        self.assertNotIn("s.cosmetic ? s.slot", self.ajs)

    def test_the_two_kinds_of_empty_are_told_apart_by_the_payload(self):
        """The page draws a cosmetic empty quietly and a real one loudly, and
        it must learn which is which from the payload rather than from a
        second copy of the shirt-and-tabard list."""
        for slot in armory.COSMETIC_SLOTS:
            self.assertNotIn('"' + slot + '"', self.ajs)
        self.assertIn("s.empty_note", self.ajs)

    def test_the_slot_mark_is_never_invented_in_the_page(self):
        """A 46px cell with no icon needs two letters in it, and which two is
        a naming decision: "finger 1" is R1 because a player calls it a ring,
        which no rule over the stored name would produce."""
        self.assertIn('el("span", "mk", s.mark)', self.ajs)
        for mark in armory.SLOT_MARKS.values():
            self.assertNotIn('"' + mark + '"', self.ajs)

    def test_the_cells_other_corner_is_the_item_level_and_never_a_zero(self):
        """A custom item the world database does not know has no level. The
        corner arrives as a string so there is no null here for the page to
        turn into a 0 that reads as a level."""
        self.assertIn('el("span", "lv", s.item_level_mark)', self.ajs)
        self.assertIn(".aslot .lv { right:0; bottom:0;", self.acss)

    def test_the_doll_layout_is_not_retyped_into_the_page(self):
        """Which slots go down which side of the character is a fact the
        payload carries (armory.DOLL_LEFT / DOLL_RIGHT); the page draws
        from it so it never names a slot itself."""
        self.assertIn("for (const spec of p.doll.left)", self.tab)
        self.assertIn("for (const spec of p.doll.right)", self.tab)

    def test_the_page_leaves_the_tailnet_for_exactly_two_things(self):
        """The game's art is in the client's archives, not in any table this
        server has, so the icons come from the host every armory site uses,
        and the 3D models are drawn by that host's own viewer script. Those
        two, named once each, and nothing else: the model DATA goes through
        this server's /modelviewer/ cache, never from the browser to the
        host, because the host refuses any origin but its own. Every image
        has a fallback so an unreachable host degrades to legible rather
        than to blank."""
        self.assertEqual(self.tab.count("https://"), 2)
        self.assertIn('const ICON_HOST = "https://wow.zamimg.com/images/wow/icons/large/";',
                      self.tab)
        self.assertIn('const MODEL_SCRIPT = "https://wow.zamimg.com/modelviewer/wrath/'
                      'deployment/viewer/', self.tab)
        # Through u(), like every other same-origin URL on this page: the
        # cache is served by THIS process, so on a realm mounted under a
        # prefix a root-anchored path here would fetch another realm's
        # copy of it. See basepath.py.
        self.assertIn('const MODEL_CONTENT_PATH = u("/modelviewer/");', self.tab)
        self.assertIn("img.onerror = () => { img.remove(); if (onFail) onFail(); };",
                      self.tab)
        self.assertIn('img.referrerPolicy = "no-referrer";', self.tab)

    def test_the_model_is_an_upgrade_over_the_portrait_never_a_replacement(self):
        """Every way the viewer can fail - script never arriving, viewer
        throwing, model never loading - must leave the portrait on screen.
        So: the script load has a timeout that resolves rather than hangs,
        the pane is shown only once every actor reports loaded, and the
        portrait is hidden by a class the pane's presence toggles rather
        than removed."""
        self.assertIn("const timer = setTimeout(() => { script.remove(); resolve(false); },"
                      " MODEL_LOAD_TIMEOUT);", self.tab)
        self.assertIn("if (actors.length && actors.every((a) => a.loaded)) {", self.tab)
        self.assertIn('c.portrait.classList.add("live");', self.tab)
        self.assertIn(".aportrait.live .race, .aportrait.live .sil, .aportrait.live .cls "
                      "{ display:none; }", self.css)

    def test_the_model_turns_by_itself_and_stops_under_a_finger(self):
        self.assertIn("r.azimuth = (r.azimuth + MODEL_TURN) % (2 * Math.PI);", self.tab)
        self.assertIn("} else if (!c.held && !r.mouseDown) {", self.tab)

    def test_a_viewer_is_rebuilt_only_when_the_model_changes(self):
        """Building one is megabytes of geometry and the poll is every
        thirty seconds; five rebuilt viewers a minute is a phone on fire."""
        self.assertIn('const key = m.model ? JSON.stringify(m.model) : "";', self.tab)
        self.assertIn("if (c.modelKey === key) return;", self.tab)
        self.assertIn("c.viewer.destroy();", self.tab)

    def test_the_face_is_the_worlds_five_numbers_matched_by_option_name(self):
        """A tauren's hairStyle is its Horn Style and a night elf's
        facialStyle its Markings: the match is by name, with the fifth
        option always being the facial one."""
        self.assertIn('if (optionName === "Horn Style" && !names.includes("Hair Style")) '
                      'return "hairStyle";', self.tab)
        self.assertIn('return "facialStyle";', self.tab)

    def test_jquery_is_served_from_here_not_a_third_host(self):
        self.assertIn('loadScript(u("/jquery.min.js"))', self.tab)
        self.assertIn('"/jquery.min.js": _jquery_file,', self.server)

    def test_the_portrait_is_never_blank(self):
        """No character renderer here: the centre is the race portrait icon
        with the class icon, and a silhouette when the host is down."""
        self.assertIn("function silhouette(colour)", self.tab)
        self.assertIn("m.portrait.race_icon", self.tab)
        self.assertIn("m.portrait.class_icon", self.tab)

    def test_the_item_card_is_in_the_flow_and_not_a_floating_tooltip(self):
        """A phone has no hover to lose and no room beside a 46px square. The
        card that replaced the tooltip is a block under the doll, which is
        why none of the tooltip's machinery survives: no hover branch, no
        pin, no Escape, and above all no hand-computed position that could
        put the card off the edge of a screen."""
        self.assertIn('const detail = el("div", "adetail");', self.tab)
        self.assertIn("function renderDetail(c, s)", self.tab)
        for gone in ("pointerenter", "arm.pinned", "getBoundingClientRect",
                     "window.innerWidth", "position:fixed"):
            self.assertNotIn(gone, self.ajs, gone + " is tooltip machinery")
        self.assertNotIn("#atip", self.page)

    def test_choosing_a_slot_rings_it_and_choosing_again_lets_go(self):
        """There is no hover here, so selection is the only way in and it has
        to be reversible with the same thumb that opened it."""
        self.assertIn("c.selected = c.selected === slot ? null : slot;", self.tab)
        self.assertIn('cell.classList.toggle("on", slot === c.selected)', self.tab)
        self.assertIn(".aslot.on { box-shadow:0 0 0 2px var(--ground); }", self.acss)
        self.assertIn(".aslot.broken { box-shadow:0 0 0 2px var(--vermilion); }",
                      self.acss)

    def test_a_doll_cell_is_a_button_so_a_keyboard_can_reach_the_card(self):
        """A div with a click handler is invisible to a keyboard and to a
        screen reader, and the card underneath is the only place the item's
        stats exist on this tab."""
        self.assertIn('cell = el("button", "aslot");', self.tab)
        self.assertIn('cell.type = "button";', self.tab)
        self.assertIn(":focus-visible", self.acss)

    def test_the_doll_cell_is_the_handoffs_geometry(self):
        """46px clears the 44px hit-target floor, and the quality colour is
        the border rather than a tint, so the icon inside stays the icon."""
        self.assertIn("width:46px; height:46px; border-radius:6px;", self.acss)
        self.assertIn("border:2px solid var(--line);", self.acss)

    def test_the_card_draws_the_lines_the_game_draws(self):
        """Name in quality colour, item level, binding, slot and kind, armor,
        stats, enchant, durability, classes, level, equip effects, the set
        with its pieces and bonuses, flavour text, sell price - in
        armory.py::_tooltip's own order."""
        tip = self.tab[self.tab.index("function renderDetail"):
                       self.tab.index("function renderStats")]
        for field in ("t.item_level", "t.binding", "t.slot", "t.kind", "t.armor",
                      "t.stats", "t.enchant", "t.durability", "t.classes",
                      "t.requires_level", "t.effects", "t.set.pieces", "t.set.bonuses",
                      "t.flavor", "t.sell_price"):
            self.assertIn(field, tip)

    def test_an_unavailable_stat_says_so_and_the_page_cannot_say_zero(self):
        """A stat the world has not saved is not a zero. Zero attack power is
        a number a person acts on, and the way it gets printed is a page that
        was left to turn a null into something - so the page is handed a
        string and given nothing to decide."""
        self.assertIn("r.v.textContent = s.reading;", self.tab)
        stats = self.tab[self.tab.index("function renderStats"):
                         self.tab.index("function showTrees")]
        self.assertNotIn("String(s.value)", stats)
        self.assertNotIn("|| 0", stats)
        self.assertNotIn('"unavailable"', self.ajs,
                         "the page must not name a stat's source itself")

    def test_a_stat_is_coloured_by_where_its_number_came_from(self):
        """A saved reading and a derived one are different claims, and a
        block that prints them in one ink invites a comparison between two
        numbers that do not mean the same thing."""
        self.assertIn('r.row.className = "astat " + s.source;', self.tab)
        for source in (armory.STAT_SAVED, armory.STAT_DERIVED,
                       armory.STAT_UNAVAILABLE):
            self.assertIn(".astat.%s .v {" % source, self.acss)
        # And the word is spelled out rather than left as a colour to crack.
        self.assertIn('el("span", "w", s.source)', self.tab)
        self.assertIn("s.gloss", self.tab)

    def test_the_talent_trees_are_collapsed_until_they_are_asked_for(self):
        """THE OPERATOR'S OWN COMPLAINT. Three grids of forty-four cells,
        five profiles over, is six hundred and sixty icons answering a
        question that "0/0/15 Protection" answers in six characters. The
        default is a product decision, so it arrives in the payload; the
        page reads it and does not have one of its own."""
        self.assertIn("arm.trees = p.talent_trees;", self.tab)
        self.assertIn("open: !!(arm.trees && arm.trees.expanded)", self.tab)
        self.assertIn("c.trees.hidden = !c.open;", self.tab)
        self.assertIn(".atrees[hidden] { display:none; }", self.acss)
        self.assertFalse(armory.TREES_EXPANDED,
                         "the trees must not start open")

    def test_a_shut_tree_is_not_built_at_all(self):
        """Hiding six hundred and sixty icons still builds them. Collapsed
        has to cost nothing or it is only a smaller version of the
        complaint."""
        # renderTree is defined further up, in the talent-grid section, so
        # the window is showTrees to the renderSpec that calls it.
        spec = self.tab[self.tab.index("function showTrees"):
                        self.tab.index("function renderSpec")]
        self.assertIn("if (c.open && c.specData) {", spec)
        self.assertNotIn("spec.trees.forEach", self.ajs)

    def test_the_page_does_not_name_the_toggle_or_the_summary(self):
        """Every word on this control is a word about the data, so every one
        of them comes from armory.py."""
        self.assertIn("c.toggle.textContent = c.open ? arm.trees.hide : arm.trees.show;",
                      self.tab)
        self.assertIn("c.sum.textContent = spec.headline;", self.tab)
        self.assertIn("c.budget.textContent = spec.budget;", self.tab)
        for word in (armory.TREES_SHOW, armory.TREES_HIDE):
            self.assertNotIn(word, self.ajs)
        self.assertNotIn("nothing spent", self.ajs)
        self.assertNotIn("points spent", self.ajs)

    def test_the_unspent_points_are_the_amber_half_of_the_bar(self):
        """The bar's segments arrive as a list, so the page never decides
        whether a death knight of unknown budget has an unspent half."""
        self.assertIn("for (const seg of spec.bar) {", self.tab)
        self.assertIn(".aspecbar .unspent { background:var(--caution-text); }",
                      self.acss)
        self.assertIn(".aspecbar .spent { background:var(--accent-text); }",
                      self.acss)

    def test_the_headline_verdict_is_not_a_ternary_in_the_page(self):
        """"Loud only for the two things somebody can act on today" is a
        verdict, and a verdict written into a page is a verdict no test can
        reach without a browser."""
        self.assertIn("aheadline.textContent = p.headline.text;", self.tab)
        self.assertIn('aheadline.className = p.headline.alarm ? "alarm" : "";',
                      self.tab)
        self.assertNotIn("empty slots", self.ajs)
        self.assertNotIn('of " + p.expected', self.ajs)

    def test_a_card_with_no_character_behind_it_shows_no_empty_controls(self):
        """Every part of a profile is built once and refilled, so a member
        with no saved row leaves a doll with no cells, an item card with no
        hint, and an unlabelled 44px button - which reads as broken software
        rather than as a missing character."""
        self.assertIn(".aprof.c-gone .abody, .aprof.c-gone .adetail, "
                      ".aprof.c-gone .aspec,", self.acss)
        self.assertIn(".aprof.c-gone .aspecbar, .aprof.c-gone .atrees "
                      "{ display:none; }", self.acss)

    def test_the_line_under_the_name_is_not_assembled_in_the_page(self):
        """Which of guild and honourable kills is worth a separator, and what
        a character with no saved row says instead, are both decisions about
        the data."""
        self.assertIn('c.line.append(el("span", "", m.identity + " "));', self.ajs)
        self.assertIn("c.line.textContent = m.identity;", self.ajs)
        self.assertNotIn("honourable", self.ajs.lower())
        self.assertNotIn("no saved character", self.ajs)

    def test_the_gear_chips_take_their_loudness_from_the_payload(self):
        """An empty slot is ordinary at these levels and a broken item is
        not. If the page decided that, every card would carry a permanently
        coloured chip, which is the same as carrying none."""
        self.assertIn('const g = el("span", "gc " + chip.tone);', self.ajs)
        for tone in (armory.TONE_CAUTION, armory.TONE_WARN):
            self.assertIn(".anums .gc.%s {" % tone, self.acss)
        self.assertNotIn("ILVL", self.ajs)
        self.assertNotIn("BROKEN", self.ajs)

    def test_the_talent_grid_is_the_trainers(self):
        """Talents at their true row and column, a count only once a point
        is in, and arrows between prerequisites lit when the prerequisite is
        met."""
        self.assertIn("cell.style.gridRow = String(t.row + 1);", self.tab)
        self.assertIn("cell.style.gridColumn = String(t.col + 1);", self.tab)
        self.assertIn('r.textContent = t.rank ? t.rank + "/" + t.max_rank : "";', self.tab)
        self.assertIn("arrow(box.svg, from, t, from.rank >= reqRank);", self.tab)

    def test_every_quality_the_game_has_is_coloured(self):
        """A quality with no rule inherits body text and silently reads as
        common - an epic drop that looks like a vendor shirt."""
        for quality in armory.QUALITY_NAMES:
            self.assertIn(".q%d { color:#" % quality, self.css)

    def test_a_cosmetic_empty_slot_is_quieter_than_a_real_one(self):
        """Shirt and tabard are empty on everyone forever. An alarm that
        always fires is an alarm nobody reads, and it would drown the empty
        head slot standing next to it. Both are dashed - neither holds
        anything - and only the real gap is amber."""
        self.assertIn(".aslot.empty { border-style:dashed; }", self.acss)
        self.assertIn(".aslot.empty.cosmetic { border-color:var(--on-dark-faint); "
                      "color:var(--on-dark-faint); }", self.acss)
        self.assertIn(".aslot.empty:not(.cosmetic) { border-color:var(--caution-text);",
                      self.acss)

    def test_every_quality_borders_its_slot(self):
        """The quality colour is the border of the icon, as the reference
        draws it - an epic with a grey border reads as a vendor item."""
        for quality in armory.QUALITY_NAMES:
            self.assertIn(".aslot.q%d { border-color:#" % quality, self.css)

    def test_one_profile_on_a_phone_and_two_on_a_wide_desktop(self):
        """A profile is as wide as its paper doll needs, and the page must
        never scroll sideways: one column until there is room for two."""
        self.assertIn("#aprofiles { display:grid; gap:1rem; grid-template-columns:minmax(0,1fr); }",
                      self.css)
        self.assertIn("grid-template-columns:repeat(2,minmax(0,1fr))", self.css)
        self.assertIn("grid-template-columns:repeat(3,minmax(0,1fr))", self.css)

    def test_one_content_breakpoint_and_it_is_the_handoffs(self):
        """Mobile first, and the doll goes beside the stat block at 640. The
        profile GRID still widens later, which is a different question - how
        many profiles fit on a monitor, not how one profile is laid out."""
        self.assertIn("@media (min-width:640px) { .abody {", self.acss)
        self.assertNotIn("min-width:760px", self.acss)

    def test_every_thumb_target_on_this_tab_clears_44px(self):
        """The jump links were 26px of text: five of them, wrapped, on the
        one device this tab is most likely to be read from."""
        self.assertIn("min-height:44px", self.acss)
        self.assertIn(".atoggle { min-height:44px;", self.acss)

    def test_the_armory_paints_text_from_roles_and_never_from_a_pigment(self):
        """A PIGMENT TOKEN SAYS WHAT A COLOUR IS; A ROLE SAYS WHAT IT IS FOR,
        and only a role survives being moved to another ground. This section
        is the page's one dark surface, where --rust lands at about 2.2:1 -
        so `color:var(--rust)` here is not a style choice, it is text nobody
        can read, and it was exactly what #aheadline.alarm said."""
        for pigment in ("--rust", "--vermilion", "--amber", "--amber-text",
                        "--green", "--deep-green", "--cyan"):
            self.assertNotIn("color:var(%s)" % pigment, self.acss,
                             "a text colour taken from a pigment token")
        self.assertIn("#aheadline.alarm { color:var(--warn-text); }", self.acss)

    def test_the_dark_card_carries_the_handoffs_own_text_ramp(self):
        """Three tiers, stated once in the scope rather than as three greys
        scattered through the rules."""
        scope = self.page[self.page.index("#armory {"):]
        scope = scope[:scope.index("}")]
        for token in ("--on-dark:#E8EFE6", "--on-dark-dim:#B9C9BC",
                      "--on-dark-faint:#8FA396"):
            self.assertIn(token, scope, token)
        for role in ("--warn-text:", "--caution-text:", "--accent-text:"):
            self.assertIn(role, scope, role + " is not re-pigmented for the dark card")

    def test_rare_is_lifted_off_the_clients_own_blue_exactly_once(self):
        """#0070dd is under 3:1 on this card and #3f9bf5 was a first attempt
        at fixing that. Two values for one canonical colour is the drift this
        file's own comments are about, so there is one."""
        self.assertIn(".q3 { color:#3B9DFF; }", self.acss)
        self.assertIn(".aslot.q3 { border-color:#3B9DFF; }", self.acss)
        self.assertNotIn("#3f9bf5", self.page)

    def test_the_page_says_the_numbers_are_a_save_rather_than_a_live_read(self):
        """The core writes these on a timer measured in minutes. Without the
        sentence, somebody equips a sword, sees no change, and concludes the
        tab is broken."""
        self.assertIn("last saved them", self.tab)


class TheEndpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = (HERE / "map_server.py").read_text()
        cls.dockerfile = (HERE.parent.parent / "docker" / "wow-overseer"
                          / "Dockerfile").read_text()

    def test_the_endpoint_is_reachable(self):
        self.assertIn('"/api/armory": _armory,', self.server)

    def test_the_endpoint_takes_no_roster_from_the_caller(self):
        """WHO the family is belongs to bonds. Accepting a roster would make
        this a general character query wearing a friendly name.

        THE TWO LINES PINNED HERE CHANGED SHAPE AND THE GUARD DID NOT. This
        used to assert the single expression
        `armory.build_armory(**_fetch_armory(), book=BOOK, items=ITEMS)`,
        which stopped being one line when the handler grew the provenance
        index: the fetch is now bound so its equip rows can be lifted off
        before the splat. What the guard is FOR is that the fetch takes
        nothing from the request and that the roster reaches the builder
        whole, and both halves are still asserted, splat included. The
        assertNotIn below is the load-bearing one and it is untouched."""
        handler = self.server[self.server.index("def _armory"):]
        handler = handler[:handler.index("def _thoughts")]
        self.assertIn("fetched = _fetch_armory()", handler)
        self.assertIn("armory.build_armory(**fetched, book=BOOK, items=ITEMS)",
                      handler)
        self.assertNotIn("query.get", handler)

    def test_a_dead_database_is_a_503_rather_than_a_hang(self):
        handler = self.server[self.server.index("def _armory"):]
        handler = handler[:handler.index("def _thoughts")]
        self.assertIn("self._send(503", handler)

    def test_the_talent_book_is_read_once_at_import_not_per_request(self):
        """It is 117KB of JSON and it never changes. Loading it inside the
        handler would parse it again on every poll, forever."""
        self.assertIn("BOOK = armory.TalentBook.load(HERE)", self.server)
        handler = self.server[self.server.index("def _armory"):]
        handler = handler[:handler.index("def _thoughts")]
        self.assertNotIn("TalentBook.load", handler)

    def test_the_gear_query_is_not_bounded_by_a_hand_typed_slot_count(self):
        """The SQL bound and the grid's rows must come from one list. Typing
        19 here would silently drop a slot the day panel's list grows one."""
        fetch = self.server[self.server.index("def _fetch_armory"):]
        fetch = fetch[:fetch.index("def _ensure_stream_store")]
        self.assertIn("len(armory.EQUIPPED_SLOTS)", fetch)

    def test_the_gear_query_reaches_the_world_database_for_item_names(self):
        """Item name, quality and level are in acore_world, not the characters
        database. Without the join every item renders as a bare entry id."""
        fetch = self.server[self.server.index("def _fetch_armory"):]
        fetch = fetch[:fetch.index("def _ensure_stream_store")]
        self.assertIn("LEFT JOIN acore_world.item_template", fetch)

    def test_the_talent_book_ships_in_the_image(self):
        """armory.TalentBook.load runs at IMPORT time, so an image without
        talents.json does not start at all - and that failure lands at pod
        start, long after CI has gone green."""
        self.assertIn("_shared/talents.json", self.dockerfile)
        for book in ("items", "icons", "spells"):
            self.assertIn(f"_shared/{book}.json", self.dockerfile)
        self.assertIn("_shared/armory.py", self.dockerfile)

    def test_the_gear_query_carries_the_instance_not_just_the_template(self):
        """enchantments and randomPropertyId are what make a belt a 'Belt
        of the Tiger'. Without them half the family's stats do not exist."""
        fetch = self.server[self.server.index("def _fetch_armory"):]
        fetch = fetch[:fetch.index("def _ensure_stream_store")]
        self.assertIn("ii.enchantments", fetch)
        self.assertIn("ii.randomPropertyId AS random_property_id", fetch)

    def test_the_saved_stats_are_read_when_the_world_has_written_them(self):
        fetch = self.server[self.server.index("def _fetch_armory"):]
        fetch = fetch[:fetch.index("def _ensure_stream_store")]
        self.assertIn("JOIN character_stats s ON s.guid = c.guid", fetch)
        self.assertIn("acore_world.player_class_stats", fetch)
        self.assertIn("acore_world.player_race_stats", fetch)

    def test_the_dev_world_saves_stats_for_external_readers(self):
        """character_stats is written only when PlayerSave.Stats.MinLevel
        allows, and only on logout unless SaveOnlyOnLogout is off. The dev
        overlay turns both on; without them the stat block is derived
        forever."""
        conf = (HERE.parent.parent / "oke" / "manifests" / "wow-dev" / "config"
                / "worldserver.overrides.conf").read_text()
        self.assertIn("\nPlayerSave.Stats.MinLevel = 1\n", conf)
        self.assertIn("\nPlayerSave.Stats.SaveOnlyOnLogout = 0\n", conf)


if __name__ == "__main__":
    unittest.main()
