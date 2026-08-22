# wow-overseer bridge: Discord <-> overseer_command / overseer_snapshot.
# Service code arrives via the reusable's shared-dir mechanism as _shared/
# (source of truth: production/scripts/wow-overseer/, where its tests live).
FROM python:3.12-slim

RUN pip install --no-cache-dir discord.py==2.4.0 PyMySQL==1.1.1

WORKDIR /app
COPY _shared/core.py _shared/bridge.py _shared/voice.py _shared/transform.py \
     _shared/map_core.py _shared/map_server.py _shared/events.py \
     _shared/panel.py _shared/goals.py _shared/protect.py _shared/fanout.py _shared/chat.py \
     _shared/relay.py \
     _shared/zones.json _shared/entrances.json _shared/index.html /app/

USER 10000
CMD ["python", "-u", "bridge.py"]
