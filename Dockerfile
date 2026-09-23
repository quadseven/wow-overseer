# wow-overseer bridge: Discord <-> overseer_command / overseer_snapshot.
#
# Extracted 2026-09-18 from quadseven/infra (production/docker/wow-overseer/
# + production/scripts/wow-overseer/), history preserved via `git filter-repo`.
# infra built this image itself, inside its own cluster, via a k8s buildkit
# Job whose context arrived split across three ConfigMaps (a 1MiB-per-object
# limit that does not exist here) - hence the old Dockerfile COPYing from a
# synthetic `_shared/` directory. This build is a plain `docker build .`
# against this repo's own tree (build.yml, GitHub-hosted runner), so that
# indirection is gone; the explicit file list below is unchanged in spirit -
# still hand-maintained, still excludes tests/, tools/, mod-overseer/ and
# patches/ on purpose, so the image ships only what bridge.py imports.
FROM python:3.12-slim

RUN pip install --no-cache-dir discord.py==2.4.0 PyMySQL==1.1.1

WORKDIR /app

COPY core.py bridge.py voice.py transform.py \
     map_core.py map_server.py events.py \
     panel.py family.py goals.py protect.py fanout.py chat.py \
     kin.py cast.py bonds.py council.py persona.py \
     bonkers.py \
     quests.py overhear.py questbook.py \
     questshare.py travel.py stream.py frames.py \
     professions.py craft.py craft_supply.py auction.py jobs.py trainjob.py \
     craft_rhythm.py \
     skillgoal.py gatheraim.py gatherband.py \
     flightlearn.py \
     learnaim.py recipebook.py \
     craftpleas.py materials.py \
     gear.py handover.py \
     armory.py wealth.py questlog.py modelviewer.py \
     relay.py digest.py \
     achievements.py recap.py standing.py agenda.py eye.py decree.py \
     dungeonplan.py dungeonpath.py raidgoals.py raidcraft.py raidprep.py raidlineup.py raidready.py \
     dungeonprogression.py \
     guildcraft.py tradespec.py guildbank.py guildshare.py guildroute.py recruit.py \
     bag_pressure.py bag_upgrade.py bag_economy.py disposition.py bagfate.py \
     item_plan.py \
     jev.py jev_items.py jev_choices.py jev_activity.py jevview.py \
     bank.py \
     mailrun.py \
     realm.py basepath.py watchwall.py realmnav.py \
     needs.py partystatus.py lootcard.py lootstory.py towntrip.py \
     townslot.py tradechoice.py \
     enroll.py \
     tabard.py crossing.py \
     vendor_stall.py \
     campaignqueue.py \
     zones.json entrances.json shapes.json \
     talents.json items.json icons.json spells.json viewerdisplays.json \
     standing.json craftbook.json taxinodes.json \
     index.html /app/

# It stays VENDORED. map_server._jquery_file says why - the page reaches no
# third host for it - and moving it to a CDN to save the same bytes would have
# traded that away. Same file, same served path, same origin.
COPY jquery.min.js /app/

USER 10000
CMD ["python", "-u", "bridge.py"]
