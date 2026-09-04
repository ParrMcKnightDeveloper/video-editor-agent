/**
 * ffmpeg/ffprobe plumbing for video QA.
 *
 * Binary resolution: explicit env (FFMPEG_PATH / FFMPEG) → the build bundled by
 * `npm install` at the pack root (ffmpeg-static / ffprobe-static, so nothing has to
 * be installed on the machine) → Homebrew → /usr/local → PATH. Some builds have no
 * libass/drawtext — text on images goes through PIL (see py/draw_markers.py).
 */
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { createReadStream, existsSync } from "node:fs";
import { createRequire } from "node:module";
import { join } from "node:path";
import { PACK_ROOT } from "./env";

/** Path of the npm-bundled binary, if the root package has been installed. */
function bundledBin(name: "ffmpeg" | "ffprobe"): string | null {
  try {
    const req = createRequire(join(PACK_ROOT, "package.json"));
    const p: string = name === "ffmpeg" ? req("ffmpeg-static") : req("ffprobe-static").path;
    return p && existsSync(p) ? p : null;
  } catch {
    return null;
  }
}

function resolveBin(envVars: string[], name: "ffmpeg" | "ffprobe"): string {
  for (const v of envVars) {
    const fromEnv = process.env[v];
    if (fromEnv) return fromEnv;
  }
  const bundled = bundledBin(name);
  if (bundled) return bundled;
  for (const c of [`/opt/homebrew/bin/${name}`, `/usr/local/bin/${name}`]) {
    if (existsSync(c)) return c;
  }
  return name;
}

export function ffmpegBin(): string {
  return resolveBin(["FFMPEG_PATH", "FFMPEG"], "ffmpeg");
}

export function ffprobeBin(): string {
  return resolveBin(["FFPROBE_PATH", "FFPROBE"], "ffprobe");
}

export interface RunResult {
  code: number;
  stdout: string;
  stderr: string;
}

/**
 * Run a binary capturing FULL stdout+stderr (Layer 1 parses filter logs from
 * stderr, so unlike render helpers we keep everything, capped at 4 MB).
 */
export function runCapture(
  bin: string,
  args: string[],
  opts?: { allowNonZero?: boolean; maxBuffer?: number }
): Promise<RunResult> {
  const cap = opts?.maxBuffer ?? 4 * 1024 * 1024;
  return new Promise((resolve, reject) => {
    const proc = spawn(bin, args, { stdio: ["ignore", "pipe", "pipe"] });
    let out = "";
    let err = "";
    proc.stdout.on("data", (d) => {
      if (out.length < cap) out += d.toString();
    });
    proc.stderr.on("data", (d) => {
      if (err.length < cap) err += d.toString();
    });
    proc.on("error", reject);
    proc.on("close", (code) => {
      if (code === 0 || opts?.allowNonZero) {
        resolve({ code: code ?? -1, stdout: out, stderr: err });
      } else {
        reject(
          new Error(`${bin} exited ${code}: ${err.slice(-1500)}`)
        );
      }
    });
  });
}

export interface StreamInfo {
  codec_type?: string;
  codec_name?: string;
  width?: number;
  height?: number;
  r_frame_rate?: string;
  avg_frame_rate?: string;
  pix_fmt?: string;
  channels?: number;
  channel_layout?: string;
  sample_rate?: string;
  duration?: string;
  nb_frames?: string;
}

export interface ProbeInfo {
  format: {
    duration?: string;
    size?: string;
    bit_rate?: string;
    format_name?: string;
  };
  streams: StreamInfo[];
}

export async function ffprobeJson(path: string): Promise<ProbeInfo> {
  const { stdout } = await runCapture(ffprobeBin(), [
    "-v",
    "error",
    "-print_format",
    "json",
    "-show_format",
    "-show_streams",
    path,
  ]);
  return JSON.parse(stdout) as ProbeInfo;
}

export function fpsOf(stream: StreamInfo): number | null {
  const raw = stream.avg_frame_rate || stream.r_frame_rate;
  if (!raw) return null;
  const [n, d] = raw.split("/").map(Number);
  if (!n || !d) return null;
  return n / d;
}

/** Extract a mono 16k WAV window (for whisper re-probes / astats windows). */
export async function extractAudioWindow(
  video: string,
  start: number,
  duration: number,
  outWav: string
): Promise<void> {
  await runCapture(ffmpegBin(), [
    "-nostdin",
    "-y",
    "-ss",
    start.toFixed(3),
    "-t",
    duration.toFixed(3),
    "-i",
    video,
    "-vn",
    "-ac",
    "1",
    "-ar",
    "16000",
    outWav,
  ]);
}

/** Extract full audio as mono 16k WAV (for source transcription). */
export async function extractAudioFull(video: string, outWav: string): Promise<void> {
  await runCapture(ffmpegBin(), [
    "-nostdin",
    "-y",
    "-i",
    video,
    "-vn",
    "-ac",
    "1",
    "-ar",
    "16000",
    outWav,
  ]);
}

export function sha256File(path: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const h = createHash("sha256");
    const s = createReadStream(path);
    s.on("data", (d) => h.update(d));
    s.on("error", reject);
    s.on("end", () => resolve(h.digest("hex")));
  });
}

export function sha256Text(text: string): string {
  return createHash("sha256").update(text).digest("hex");
}
