"""The gaming section model (app/models/gaming.js), for #2075.

Pure functions over the existing /api/family, /api/realm, /api/loot and
/api/recap payloads, run under node the way test_app_models.py runs its
models. No new data source: every figure comes from those payloads.
"""

import shutil
import unittest

from test_app_shell import node_module

NODE = unittest.skipUnless(shutil.which("node"), "node is needed")


def run(script):
    return node_module(
        "models/gaming.js", "console.log(JSON.stringify(" + script + "));"
    )


@NODE
class GamingModel(unittest.TestCase):
    def test_families_show_members_levels_and_activity(self):
        got = run(
            "M.families([{family:'Grug',members:[{name:'Grug',level:42,class:'Warrior',zone:'Elwynn',online:true}]},"
            "{family:'Zug',members:[{name:'Zug',level:60,class:'Druid',zone:'',online:false}]}])"
            ".map(f=>[f.family,f.members[0].name,f.members[0].level,f.members[0].activity])"
        )
        self.assertEqual(got, [["Grug", "Grug", 42, "Elwynn"], ["Zug", "Zug", 60, "offline"]])

    def test_guild_readiness_is_level60_count_vs_40(self):
        got = run(
            "M.guilds({guilds:[{name:'Cave',size:45}]},"
            "[{name:'A',level:60},{name:'B',level:60},{name:'C',level:12}])"
            ".map(g=>[g.name,g.size,g.at60,g.needed])"
        )
        self.assertEqual(got, [["Cave", 45, 2, 38]])

    def test_moments_keep_only_epic_or_better_with_winner_source_and_equip(self):
        got = run(
            "M.moments({stories:["
            "{item:{name:'Staff',quality:4},guild:'Cave',line:'Wug won Staff from Boss in Blackrock Depths and equipped it.',at:'2026-11-01T10:00:00'},"
            "{item:{name:'Blade',quality:3},guild:'Cave',line:'Sogg won Blade',at:'2026-11-01T09:00:00'}]})"
            ".map(m=>[m.item,m.winner,m.equipped,m.href])"
        )
        self.assertEqual(got, [["Staff", "Wug", True, "#/guilds/cave/chronicle"]])

    def test_failed_sync_keeps_last_good_data_marked_stale(self):
        got = run(
            "(()=>{const ok=M.sync(null,true,100,{a:1});const bad=M.sync(ok,false,200,null);"
            "return [ok.lastSync,ok.stale,bad.lastSync,bad.stale,bad.data];})()"
        )
        self.assertEqual(got, [100, False, 100, True, {"a": 1}])
