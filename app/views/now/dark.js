// Detect a black or near-black WHEP picture in the browser.
//
// The stream can be connected and still show nothing: a minimized game client,
// an asleep display, or a loading screen all produce valid black frames that
// read as healthy because the video keeps arriving. This samples the rendered
// video and reports when its brightest tenth stays below a small threshold for
// a few frames, so the panel can say why instead of "LIVE".
//
// The sampler is deliberately cheap: a small canvas, a luma average, and a
// short streak. It does not try to guess the exact cause from pixels alone;
// waking or re-aiming the client is the infra agent's job.

// A picture is black when even its brightest tenth is dim: the 90th percentile
// of pixel luma below this. A mean cannot tell a dark room from an empty
// picture: a family view inside a dungeon sat near a mean of 22 to 35 for
// minutes, dipped as low as 16.5, and still held a real scene whose 90th
// percentile never fell below 38. A fully black loading screen reads near 0.
export const DARK_HIGH_THRESHOLD = 20;

// How many consecutive dark samples are needed before the panel changes.
// At SAMPLE_INTERVAL_MS this is about 1.5 s, long enough to ignore a single
// bad frame and short enough to say so while it is still happening.
export const DARK_STREAK = 3;

export const SAMPLE_INTERVAL_MS = 500;
export const SAMPLE_WIDTH = 96;

// The luma at the bottom of an ImageData's brightest tenth of pixels, 0-255:
// the sorted lumas read at index floor(0.9 n), so "the brightest tenth sits at
// 39 or more" reads 39 or more. 0 for an empty buffer.
export function highBrightness(imageData) {
  const data = imageData && imageData.data;
  if (!data || !data.length) return 0;
  const count = Math.floor(data.length / 4);
  if (!count) return 0;
  const luma = new Float64Array(count);
  for (let i = 0; i < count; i++) {
    const j = i * 4;
    luma[i] = 0.299 * data[j] + 0.587 * data[j + 1] + 0.114 * data[j + 2];
  }
  luma.sort();
  return luma[Math.min(count - 1, Math.floor(count * 0.9))];
}

export function isDarkFrame(imageData, threshold = DARK_HIGH_THRESHOLD) {
  return highBrightness(imageData) < threshold;
}

// What the panel says when the picture is dark. The exact cause (asleep
// display vs loading screen) cannot be told from pixels alone, so the message
// names both possibilities and points at the infra agent to fix it.
export function darkReason() {
  return "The picture is black: the game window may be asleep or on a loading screen.";
}

// A live tile whose frames stop painting is stalled, however healthy the
// connection claims to be: the stream can sit open while the picture freezes
// on its last frame (or on black). streams.js records when a frame was last
// actually painted; past this gap the badge must stop saying LIVE until a
// frame paints again. A tile that has never painted is still connecting,
// not stalled.
export const STALL_MS = 3000;

export function frameStalled(state, lastFrame, nowMs) {
  return state === "live" && lastFrame > 0 && nowMs - lastFrame > STALL_MS;
}

// The word on a live tile's badge: STALLED while its frames are stalled,
// LIVE once they paint again. Only a live tile's badge is decided here;
// every other state's word belongs to the tile's own state changes.
export function badgeWord(state, stalled) {
  if (state !== "live") return null;
  return stalled ? "STALLED" : "LIVE";
}

// Sample a <video> and call onChange(dark) when the picture becomes or stops
// being dark. Returns {start, stop}. Safe to call start() repeatedly.
export function darkSampler(video, onChange, options = {}) {
  const threshold = options.threshold ?? DARK_HIGH_THRESHOLD;
  const streak = options.streak ?? DARK_STREAK;
  const interval = options.interval ?? SAMPLE_INTERVAL_MS;
  const width = options.width ?? SAMPLE_WIDTH;
  let running = false;
  let timer = 0;
  let darkCount = 0;
  let wasDark = false;
  const canvas = document.createElement("canvas");
  if (typeof canvas.getContext !== "function") {
    // No canvas context in this environment (e.g. the node test harness).
    // The panel falls back to ordinary live/off states.
    return { start: () => {}, stop: () => {} };
  }
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  if (!ctx) {
    return { start: () => {}, stop: () => {} };
  }

  function sample() {
    if (!running) return;
    if (!video.videoWidth || video.readyState < 2) return;
    const height = Math.max(1, Math.round(width * video.videoHeight / video.videoWidth));
    canvas.width = width;
    canvas.height = height;
    ctx.drawImage(video, 0, 0, width, height);
    let dark;
    try {
      dark = isDarkFrame(ctx.getImageData(0, 0, width, height), threshold);
    } catch (e) {
      // A tainted canvas or missing context means we cannot measure; treat it
      // as not dark rather than getting stuck reporting a false positive.
      dark = false;
    }
    if (dark) {
      darkCount += 1;
    } else {
      darkCount = 0;
    }
    const nowDark = darkCount >= streak;
    if (nowDark !== wasDark) {
      wasDark = nowDark;
      onChange(nowDark);
    }
  }

  function start() {
    if (running) return;
    running = true;
    sample();
    timer = window.setInterval(sample, interval);
  }

  function stop() {
    running = false;
    window.clearInterval(timer);
    timer = 0;
    darkCount = 0;
    wasDark = false;
  }

  return { start, stop };
}
