# wow-overseer bridge: Discord <-> overseer_command / overseer_snapshot.
# Service code arrives via the reusable's shared-dir mechanism as _shared/
# (source of truth: production/scripts/wow-overseer/, where its tests live).
FROM python:3.12-slim

RUN pip install --no-cache-dir discord.py==2.4.0 PyMySQL==1.1.1

WORKDIR /app

COPY _shared/core.py _shared/bridge.py _shared/voice.py _shared/transform.py \
     _shared/map_core.py _shared/map_server.py _shared/events.py \
     _shared/panel.py _shared/family.py _shared/goals.py _shared/protect.py _shared/fanout.py _shared/chat.py \
     _shared/kin.py _shared/cast.py _shared/bonds.py _shared/council.py _shared/persona.py \
     _shared/quests.py _shared/overhear.py _shared/questbook.py \
     _shared/questshare.py _shared/travel.py _shared/stream.py _shared/frames.py \
     _shared/professions.py _shared/jobs.py _shared/craftpleas.py _shared/materials.py \
     _shared/gear.py \
     _shared/armory.py _shared/wealth.py _shared/questlog.py _shared/modelviewer.py \
     _shared/relay.py _shared/digest.py \
     _shared/achievements.py _shared/standing.py _shared/agenda.py _shared/eye.py _shared/decree.py \
     _shared/realm.py _shared/basepath.py _shared/watchwall.py _shared/realmnav.py \
     _shared/needs.py \
     _shared/zones.json _shared/entrances.json _shared/shapes.json \
     _shared/talents.json _shared/items.json _shared/icons.json _shared/spells.json \
     _shared/standing.json \
     _shared/index.html /app/

# jQuery comes from the build CONTEXT, not the shared tarball, and that is a
# budget decision rather than a tidying one. The shared dir is packed into ONE
# configMap and handed to EVERY image built from it, so a browser asset there
# is 30KB gzipped charged to the bridge as well as the map, for a file only
# the map serves. The context configMap holds this image's own files and had
# nothing in it but this Dockerfile.
#
# It stays VENDORED. map_server._jquery_file says why - the page reaches no
# third host for it - and moving it to a CDN to save the same bytes would have
# traded that away. Same file, same served path, same origin.
COPY jquery.min.js /app/

USER 10000
CMD ["python", "-u", "bridge.py"]
