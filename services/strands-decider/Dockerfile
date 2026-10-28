# The Strands Decider wrapper (#822): strands_server.py and the strands-decider
# package on CPU torch. Built by .github/workflows/build.strands-decider.yml
# with this directory as the build context, so nothing of the bridge's tree is
# in it.
#
# The weights are NOT in the image. The package downloads the checkpoint and
# its base model (about 4.5 GB) to HF_HOME on first load; mount a volume there
# so a restart reads them from disk. CPU serving runs the torso in fp32: about
# 8 GB of memory at peak.
FROM python:3.12-slim

COPY requirements.txt /tmp/requirements.txt
# torch from the CPU wheel index first, so the CUDA wheels never download;
# the pinned set then finds it already satisfied.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch==2.13.0 \
 && pip install --no-cache-dir -r /tmp/requirements.txt \
 && rm /tmp/requirements.txt

WORKDIR /app
COPY strands_server.py /app/

RUN mkdir -p /models && chown 10000:10000 /models
ENV HF_HOME=/models \
    BIND=127.0.0.1 \
    PORT=8790 \
    STRANDS_DEVICE=cpu
VOLUME /models
EXPOSE 8790

USER 10000
CMD ["python", "-u", "strands_server.py"]
