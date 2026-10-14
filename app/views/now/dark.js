// Detect a black or near-black WHEP picture in the browser.
//
// The stream can be connected and still show nothing: a minimized game client,
// an asleep display, or a loading screen all produce valid black frames that
// read as healthy because the video keeps arriving. This samples the rendered
// video and reports when the mean brightness stays below a small threshold for
// a few frames, so the panel can say why instead of "LIVE".
//
// The sampler is deliberately cheap: a small canvas, a luma average, and a
// short streak. It does not try to guess the exact cause from pixels alone;
// waking or re-aiming the client is the infra agent's job.

// A mean luma below this is treated as black. 18/255 is just above a fully
// black loading screen but well below any normal scene.
export const DARK_THRESHOLD = 18;

// How many consecutive dark samples are needed before the panel changes.
// At SAMPLE_INTERVAL_MS this is about 1.5 s, long enough to ignore a single
// bad frame and short enough to say so while it is still happening.
export const DARK_STREAK = 3;

export const SAMPLE_INTERVAL_MS = 500;
export const SAMPLE_WIDTH = 96;

// The luma of an ImageData object, 0-255, or 0 for an empty buffer.
export function meanBrightness(imageData) {
  const data = imageData && imageData.data;
  if (!data || !data.length) return 0;
  let sum = 0;
  for (let i = 0; i < data.length; i += 4) {
    sum += 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2];
  }
  return sum / (data.length / 4);
}

export function isDarkFrame(imageData, threshold = DARK_THRESHOLD) {
  return meanBrightness(imageData) < threshold;
}

// What the panel says when the picture is dark. The exact cause (asleep
// display vs loading screen) cannot be told from pixels alone, so the message
// names both possibilities and points at the infra agent to fix it.
export function darkReason() {
  return "The picture is black: the game window may be asleep or on a loading screen.";
}

// Sample a <video> and call onChange(dark) when the picture becomes or stops
// being dark. Returns {start, stop}. Safe to call start() repeatedly.
export function darkSampler(video, onChange, options = {}) {
  const threshold = options.threshold ?? DARK_THRESHOLD;
  const streak = options.streak ?? DARK_STREAK;
  const interval = options.interval ?? SAMPLE_INTERVAL_MS;
  const width = options.width ?? SAMPLE_WIDTH;
  let running = false;
  let timer = 0;
  let darkCount = 0;
  let wasDark = false;
  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d", { willReadFrequently: true });

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
