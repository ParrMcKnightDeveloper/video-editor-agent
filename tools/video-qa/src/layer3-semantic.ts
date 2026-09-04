/**
 * Layer 3 — whole-video semantic QA: a multimodal model WATCHES AND LISTENS to the
 * render, reached through the Vercel AI Gateway (one key, `provider/model` ids).
 *
 * - Sends a compressed proxy (480p) with the AUDIO INTACT at 128k AAC — half of
 *   real editing mistakes are audible.
 * - The proxy travels as a base64 `file` content part on an OpenAI-compatible chat
 *   completion; the gateway forwards it to the model (default: a Gemini Flash, the
 *   family that takes video + audio). Oversized proxies are re-encoded smaller
 *   once, then the layer skips with a reason rather than failing the run.
 * - JSON output is ENFORCED via response_format json_schema, not prompt-please.
 * - Model timestamps are approximate (±1–2s); issues get padded windows and
 *   anchor to the nearest manifest event. The model's job is to tell Claude WHERE
 *   to look — Layer 4 verifies before anything is changed.
 * - Graceful skip when AI_GATEWAY_API_KEY is missing.
 */
import { mkdtempSync } from "node:fs";
import { readFile, rm, stat } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { EditManifest, LayerResult, QaIssue, Severity } from "./types";
import { ffmpegBin, ffprobeJson, runCapture } from "./ffmpeg";
import { gatewayGenerateJson, gatewayKey, qaModel, type GatewayContentPart } from "./gateway";
import { nearestEvent } from "./manifest/schema";

const RESPONSE_SCHEMA = {
  type: "object",
  properties: {
    issues: {
      type: "array",
      items: {
        type: "object",
        properties: {
          startSec: { type: "number" },
          endSec: { type: "number" },
          severity: { type: "string", enum: ["high", "medium", "low"] },
          category: {
            type: "string",
            enum: [
              "abrupt_cut",
              "clipped_dialogue",
              "audio_glitch",
              "music_balance",
              "sync_issue",
              "dead_air",
              "caption_error",
              "visual_glitch",
              "duplicate_footage",
              "framing_crop",
              "graphic_timing",
              "pacing",
              "content_error",
              "other",
            ],
          },
          objective: { type: "boolean" },
          confidence: { type: "number" },
          description: { type: "string" },
        },
        required: ["startSec", "endSec", "severity", "category", "objective", "description"],
      },
    },
    overallNotes: { type: "string" },
  },
  required: ["issues"],
};

interface ModelIssue {
  startSec: number;
  endSec: number;
  severity: "high" | "medium" | "low";
  category: string;
  objective: boolean;
  confidence?: number;
  description: string;
}

interface ModelReview {
  issues: ModelIssue[];
  overallNotes?: string;
}

function manifestSummary(manifest: EditManifest): string {
  const cuts = manifest.events.filter((e) => e.kind === "cut");
  const caps = manifest.events.filter((e) => e.kind === "caption");
  const other = manifest.events.filter((e) => !["cut", "caption"].includes(e.kind));
  const lines: string[] = [];
  lines.push(`Lane: ${manifest.lane}. Expected duration: ${manifest.expectedDuration ?? "?"}s.`);
  if (cuts.length) {
    lines.push(
      `Edit seams (intentional jump-cut style) at output seconds: ${cuts
        .map((c) => c.out.start.toFixed(1))
        .join(", ")}.`
    );
  }
  if (caps.length) {
    lines.push(`Captions: ${caps.length} timed caption events (word-synced karaoke style is intentional).`);
  }
  if (other.length) {
    lines.push(
      `Placed elements: ${other
        .slice(0, 40)
        .map((e) => `${e.kind}@${e.out.start.toFixed(1)}s${e.label ? ` (${e.label})` : ""}`)
        .join(", ")}.`
    );
  }
  const intent = manifest.intentional ?? {};
  if (intent.blackRegions?.length) {
    lines.push(
      `INTENTIONAL black/dark regions: ${intent.blackRegions.map((r) => `${r.start}-${r.end}s`).join(", ")}.`
    );
  }
  if (intent.silentRegions?.length) {
    lines.push(
      `INTENTIONAL silences: ${intent.silentRegions.map((r) => `${r.start}-${r.end}s`).join(", ")}.`
    );
  }
  return lines.join("\n");
}

function buildPrompt(manifest: EditManifest, instructions?: string): string {
  return [
    "You are a professional short-form video editor doing final QA on an export before it ships.",
    "The attached file has BOTH video and audio. Review them TOGETHER — listen while you watch. Roughly half of real editing mistakes are audible, not visible (clipped words at cuts, duplicate phrases, abrupt music, dead air, clicks at splices, SFX drowning the voice).",
    "",
    "Report across both modalities:",
    "- VISUAL: glitches, stray/duplicate frames, wrong or repeated footage, jarring transitions, bad crop or framing, subject cut off, graphics appearing/disappearing at wrong times, captions covering the speaker's face, caption timing/text problems, unintended blank space, abrupt start or ending, b-roll that doesn't match what is being said.",
    "- AUDIO & AUDIO-VISUAL: words cut off mid-syllable, dialogue repeated across a cut, audio/video desync, dead air, unintentional silence, music starting/stopping abruptly, music/dialogue balance, sound effects mistimed or masking speech, pacing problems.",
    "",
    "Calibration — follow exactly:",
    "- Zero issues is a valid and expected outcome for a clean video. Do not invent problems.",
    "- Report mistakes, unintended behavior, deviations from instructions, and obvious quality problems. Do not fail the video because you would make a different creative choice.",
    "- Separate objective errors (objective=true) from subjective suggestions (objective=false) and label each.",
    "- Fast jump cuts, karaoke captions, and bold graphic cards are the INTENTIONAL style of these edits — only flag a cut if something is audibly or visibly broken at it.",
    "- Your timestamps may be off by ±2 seconds; report your best estimate without agonizing over precision.",
    "",
    "Edit intent (from the editing system — treat as ground truth for what is deliberate):",
    manifestSummary(manifest),
    instructions ? `\nOriginal editing request/instructions:\n${instructions}` : "",
    "",
    "Return JSON only, matching the response schema.",
  ].join("\n");
}

/** 480p proxy with the audio intact. `fps` is the encoded frame rate; `crf` trades size. */
async function makeProxy(video: string, outPath: string, fps: number, crf: number): Promise<void> {
  await runCapture(ffmpegBin(), [
    "-nostdin",
    "-y",
    "-i",
    video,
    "-vf",
    `scale=-2:480,fps=${fps}`,
    "-c:v",
    "libx264",
    "-preset",
    "veryfast",
    "-crf",
    String(crf),
    "-c:a",
    "aac",
    "-b:a",
    "128k",
    "-movflags",
    "+faststart",
    outPath,
  ]);
}

/** Inline (base64) attachments have a request-size ceiling; keep the proxy under it. */
function proxyMaxBytes(): number {
  return Number(process.env.VIDEO_QA_PROXY_MAX_MB || 18) * 1024 * 1024;
}

const sevMap: Record<string, Severity> = { high: "HIGH", medium: "MEDIUM", low: "LOW" };

export async function runSemanticLayer(
  manifest: EditManifest,
  opts: { instructions?: string; fps?: number; log?: (m: string) => void } = {}
): Promise<LayerResult> {
  const log = opts.log ?? (() => {});
  if (!gatewayKey()) {
    log("[qa:L3] semantic QA skipped — AI_GATEWAY_API_KEY not set");
    return { status: "skipped", reason: "AI_GATEWAY_API_KEY not set", issues: [] };
  }

  const probe = await ffprobeJson(manifest.video);
  const duration = parseFloat(probe.format.duration ?? "0");
  const fps =
    opts.fps ?? (process.env.VIDEO_QA_PROXY_FPS ? Number(process.env.VIDEO_QA_PROXY_FPS) : 15);

  const dir = mkdtempSync(join(tmpdir(), "vqa-proxy-"));
  const proxyPath = join(dir, "proxy.mp4");
  try {
    log(`[qa:L3] building 480p proxy @ ${fps}fps (audio intact @128k)`);
    await makeProxy(manifest.video, proxyPath, fps, 30);
    let size = (await stat(proxyPath)).size;
    if (size > proxyMaxBytes()) {
      log(`[qa:L3] proxy is ${(size / 1e6).toFixed(1)} MB — re-encoding smaller for the inline attachment limit`);
      await makeProxy(manifest.video, proxyPath, Math.min(fps, 8), 36);
      size = (await stat(proxyPath)).size;
      if (size > proxyMaxBytes()) {
        return {
          status: "skipped",
          reason: `proxy ${(size / 1e6).toFixed(1)} MB exceeds VIDEO_QA_PROXY_MAX_MB (${proxyMaxBytes() / 1024 / 1024}); QA the render in shorter sections`,
          issues: [],
        };
      }
    }

    log(`[qa:L3] sending ${(size / 1e6).toFixed(1)} MB proxy to ${qaModel()} via the AI Gateway; reviewing ${duration.toFixed(1)}s (audio included)`);
    const parts: GatewayContentPart[] = [
      {
        type: "file",
        file: {
          data: (await readFile(proxyPath)).toString("base64"),
          media_type: "video/mp4",
          filename: "qa-proxy.mp4",
        },
      },
      { type: "text", text: buildPrompt(manifest, opts.instructions) },
    ];

    let review: ModelReview;
    try {
      review = await gatewayGenerateJson<ModelReview>(parts, RESPONSE_SCHEMA);
    } catch (e) {
      return {
        status: "skipped",
        reason: `gateway call failed: ${(e as Error).message.slice(0, 300)}`,
        issues: [],
      };
    }

    const issues: QaIssue[] = (review.issues ?? []).map((gi, i) => {
      const start = Math.max(0, Math.min(gi.startSec, duration));
      const end = Math.max(start, Math.min(gi.endSec, duration));
      const anchor = nearestEvent(manifest.events, (start + end) / 2, 2.0);
      return {
        id: `L3-${gi.category}-${String(i + 1).padStart(3, "0")}`,
        source: "semantic",
        // The model alone never exceeds HIGH; corroboration is applied in report.ts.
        severity: sevMap[gi.severity] ?? "LOW",
        category: gi.category,
        eventId: anchor?.id ?? null,
        timeWindow: { start, end },
        message: gi.description,
        objective: gi.objective,
        confidence: gi.confidence,
        evidence: { modelReported: [gi.startSec, gi.endSec], model: qaModel() },
      };
    });

    log(`[qa:L3] ${qaModel()} identified ${issues.length} possible issue(s)`);
    return {
      status: issues.some((i) => i.severity === "HIGH") ? "fail" : issues.length ? "warn" : "pass",
      issues,
      stats: { model: qaModel(), proxyFps: fps, proxyBytes: size, overallNotes: review.overallNotes, proxyDuration: duration },
    };
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}
