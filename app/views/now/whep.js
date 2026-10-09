// The WHEP player, ported from the classic page's makePlayer(). One player
// per <video>; the handshake, the failure sentences and the autoplay checks
// are the classic page's, so the two pages cannot disagree about whether a
// stream is up.
//
// The only request this sends is the WHEP offer to the media server named in
// the stream URL (and a DELETE of that session when it stops). Nothing goes
// to the realm: the broadcasts are already running, started by their own
// encoders, and this only watches them.

// Non-trickle WHEP: gather first, then send one complete offer. The timeout
// is a backstop for a browser that never declares gathering complete.
function iceGathered(pc) {
  if (pc.iceGatheringState === "complete") return Promise.resolve();
  return new Promise((resolve) => {
    const check = () => { if (pc.iceGatheringState === "complete") done(); };
    const timer = setTimeout(() => done(), 3000);
    function done() {
      clearTimeout(timer);
      pc.removeEventListener("icegatheringstatechange", check);
      resolve();
    }
    pc.addEventListener("icegatheringstatechange", check);
  });
}

// Every status a person could hit, in words that name the thing to look at.
export function whepFailure(status) {
  if (status === 404) return "The media server has no stream on that path yet: the client is up but its encoder has not started publishing.";
  if (status === 502 || status === 504) return "The gaming box is not answering. It is switched off more often than it is on, which is normal.";
  return "The media server refused the connection (HTTP " + status + ").";
}

// `note(text, kind)` is told what is happening: kind is "live", "warn" or "".
export function makePlayer(video, note) {
  const player = { url: null, pc: null, session: null };

  async function exchange(pc, url) {
    await pc.setLocalDescription(await pc.createOffer());
    await iceGathered(pc);
    const r = await fetch(url, {
      method: "POST",
      headers: { "content-type": "application/sdp" },
      body: pc.localDescription.sdp,
    });
    if (r.status !== 201) throw new Error(whepFailure(r.status));
    // Only reachable when the media server exposes Location across origins;
    // without it closing the PeerConnection ends the session.
    try {
      const loc = r.headers.get("location");
      if (loc) player.session = new URL(loc, url).toString();
    } catch (e) { player.session = null; }
    await pc.setRemoteDescription({ type: "answer", sdp: await r.text() });
  }

  function watchConnection(pc) {
    pc.onconnectionstatechange = () => {
      if (player.pc !== pc) return;
      if (pc.connectionState === "failed") note("The video connection failed: no media crossed between the browser and the box.", "warn");
      else if (pc.connectionState === "disconnected") note("The video connection dropped.", "warn");
    };
  }

  function onTrack(pc, name) {
    return (e) => {
      if (player.pc !== pc) return;
      // ontrack fires once per track; re-assigning the same stream would
      // restart loading and abort the play() below.
      if (video.srcObject !== e.streams[0]) video.srcObject = e.streams[0];
      note("Live from " + name + "'s screen.", "live");
      // The autoplay attribute is not enough for a stream handed over after
      // load; a rejected play() is checked before it is believed.
      video.play().catch(() => {
        if (!video.paused) return;
        note("The video is connected but this browser would not start it on its own. Press play on the picture.", "warn");
      });
    };
  }

  async function start(name, base) {
    const url = String(base || "").replace(/\/+$/, "") + "/whep";
    if (player.url === url) return;
    stop();
    player.url = url;
    if (location.protocol === "https:" && /^http:/i.test(url)) {
      note("The stream address is plain http and this page is https, so the browser would block it as mixed content.", "warn");
      return;
    }
    if (typeof RTCPeerConnection === "undefined") {
      note("This browser cannot play WebRTC video.", "warn");
      return;
    }
    note("Connecting to the video...", "");
    const pc = new RTCPeerConnection();
    player.pc = pc;
    pc.addTransceiver("video", { direction: "recvonly" });
    pc.addTransceiver("audio", { direction: "recvonly" });
    pc.ontrack = onTrack(pc, name);
    watchConnection(pc);
    try {
      await exchange(pc, url);
    } catch (e) {
      if (player.pc !== pc) return;
      note("Could not start the video: " + (e.message || e), "warn");
    }
  }

  function stop() {
    if (player.session) fetch(player.session, { method: "DELETE" }).catch(() => {});
    if (player.pc) { try { player.pc.close(); } catch (e) { /* already gone */ } }
    player.pc = null; player.session = null; player.url = null;
    video.srcObject = null;
  }

  return { start, stop, url: () => player.url };
}

// Whether a stream carries sound: a live, unmuted audio track. A remote track
// reports muted while no packets flow.
export function hasSound(video) {
  const src = video.srcObject;
  if (!src || typeof src.getAudioTracks !== "function") return false;
  return src.getAudioTracks().some((t) => t.readyState === "live" && !t.muted);
}
