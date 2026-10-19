/**
 * Encodes the demo recordings in docs/demo/raw (from `npm run demo:record`) for the README:
 * an MP4 (H.264) and a smaller GIF preview per tab, plus one MP4 tour of them all.
 * Each recording's sidecar JSON says where it starts and which waits to play faster.
 *
 * Needs ffmpeg: on PATH, or its path in FFMPEG.
 *   npm run demo:videos
 */
import { execFileSync } from "node:child_process";
import { existsSync, readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const ROOT = join(process.cwd(), "..", "docs", "demo");
const RAW = join(ROOT, "raw");
const FFMPEG = process.env.FFMPEG || "ffmpeg";
const GIF_WIDTH = Number(process.env.GIF_WIDTH || 800);
const GIF_FPS = Number(process.env.GIF_FPS || 6);

function ff(args) {
  execFileSync(FFMPEG, ["-hide_banner", "-loglevel", "error", "-y", ...args], { stdio: "inherit" });
}

/** A filter that drops the lead-in and plays each fast stretch at its speed. */
function cutFilter({ start = 0, fast = [] }) {
  const parts = [];
  let at = start;
  for (const f of [...fast].sort((a, b) => a.from - b.from)) {
    if (f.to <= at) continue;
    const from = Math.max(f.from, at);
    if (from > at) parts.push({ a: at, b: from, speed: 1 });
    parts.push({ a: from, b: f.to, speed: f.speed });
    at = f.to;
  }
  parts.push({ a: at, b: null, speed: 1 });
  const chains = parts.map((p, i) => {
    const end = p.b == null ? "" : `:end=${p.b.toFixed(3)}`;
    return `[0:v]trim=start=${p.a.toFixed(3)}${end},setpts=(PTS-STARTPTS)/${p.speed}[s${i}]`;
  });
  const inputs = parts.map((_, i) => `[s${i}]`).join("");
  return `${chains.join(";")};${inputs}concat=n=${parts.length}:v=1:a=0,fps=25[v]`;
}

const names = existsSync(RAW)
  ? readdirSync(RAW)
      .filter((f) => f.endsWith(".webm"))
      .map((f) => f.slice(0, -5))
      .sort()
  : [];
if (!names.length) {
  console.error(`No recordings in ${RAW}. Run npm run demo:record first.`);
  process.exit(1);
}

const mb = (f) => (statSync(f).size / 1e6).toFixed(1) + " MB";
const mp4s = [];
for (const name of names) {
  const src = join(RAW, `${name}.webm`);
  const sidecar = join(RAW, `${name}.json`);
  const edits = existsSync(sidecar) ? JSON.parse(readFileSync(sidecar, "utf8")) : {};
  const mp4 = join(ROOT, `${name}.mp4`);
  const gif = join(ROOT, `${name}.gif`);

  ff(["-i", src, "-filter_complex", cutFilter(edits), "-map", "[v]", "-c:v", "libx264", "-preset", "slow", "-crf", "26", "-pix_fmt", "yuv420p", "-movflags", "+faststart", mp4]);
  ff([
    "-i",
    mp4,
    "-filter_complex",
    `fps=${GIF_FPS},scale=${GIF_WIDTH}:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle`,
    gif,
  ]);
  mp4s.push(mp4);
  console.log(`${name}: ${mb(mp4)} mp4, ${mb(gif)} gif`);
}

// One tour: every tab back to back.
const list = join(RAW, "tour.txt");
writeFileSync(list, mp4s.map((f) => `file '${f.replace(/\\/g, "/").replace(/'/g, "'\\''")}'`).join("\n"));
const tour = join(ROOT, "vik-tour.mp4");
ff(["-f", "concat", "-safe", "0", "-i", list, "-c", "copy", "-movflags", "+faststart", tour]);
console.log(`vik-tour: ${mb(tour)}`);
