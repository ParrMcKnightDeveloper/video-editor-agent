/**
 * Minimal Vercel AI Gateway client (fetch-based, no SDK). ONE key for every hosted
 * model the engine touches:
 *
 *   - Layer 3 watch+listen — OpenAI-compatible chat completions
 *     (`POST /v1/chat/completions`) with the 480p proxy attached as a `file` content
 *     part and the JSON output enforced through `response_format: json_schema`.
 *   - Cloud transcription fallback — `POST /v4/ai/transcription-model` with
 *     word-level timestamps requested through `providerOptions.openai`.
 *
 * Key:    AI_GATEWAY_API_KEY (Bearer; VERCEL_OIDC_TOKEN also honoured, as on Vercel).
 * Models: VIDEO_QA_MODEL            default "google/gemini-3.6-flash" — a Gemini Flash;
 *                                   Gemini is the family that watches AND listens to a
 *                                   video file, so keep this on a `google/…` id.
 *         VIDEO_QA_TRANSCRIBE_MODEL default "openai/whisper-1".
 * Base:   AI_GATEWAY_BASE_URL       default https://ai-gateway.vercel.sh
 *
 * Model ids are `provider/model`; `GET /v1/models` (no auth) lists them with tags —
 * `npm run qa:check` prints whether the configured ids exist and accept file input.
 */

export const GATEWAY_BASE = (process.env.AI_GATEWAY_BASE_URL || "https://ai-gateway.vercel.sh").replace(/\/$/, "");

export function gatewayKey(): string | null {
  return process.env.AI_GATEWAY_API_KEY || process.env.VERCEL_OIDC_TOKEN || null;
}

export function qaModel(): string {
  return process.env.VIDEO_QA_MODEL || "google/gemini-3.6-flash";
}

export function transcribeModel(): string {
  return process.env.VIDEO_QA_TRANSCRIBE_MODEL || "openai/whisper-1";
}

export type GatewayContentPart =
  | { type: "text"; text: string }
  | { type: "file"; file: { data: string; media_type: string; filename: string } };

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

/** POST with ×3 retries on transient statuses (429/502/503/504). */
async function postWithRetry(url: string, init: RequestInit, label: string): Promise<Response> {
  let res: Response | null = null;
  for (let attempt = 0; attempt < 3; attempt++) {
    res = await fetch(url, init);
    if (![429, 502, 503, 504].includes(res.status)) break;
    await sleep(15_000 * (attempt + 1));
  }
  if (!res) throw new Error(`${label}: no response`);
  if (!res.ok) throw new Error(`${label} failed: ${res.status} ${(await res.text()).slice(0, 400)}`);
  return res;
}

/** Chat completion with an enforced JSON schema. Returns the parsed object. */
export async function gatewayGenerateJson<T>(
  parts: GatewayContentPart[],
  responseSchema: Record<string, unknown>,
  opts?: { model?: string; temperature?: number; schemaName?: string }
): Promise<T> {
  const key = gatewayKey();
  if (!key) throw new Error("AI_GATEWAY_API_KEY not set");
  const model = opts?.model ?? qaModel();
  const res = await postWithRetry(
    `${GATEWAY_BASE}/v1/chat/completions`,
    {
      method: "POST",
      headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
      body: JSON.stringify({
        model,
        messages: [{ role: "user", content: parts }],
        temperature: opts?.temperature ?? 0.2,
        response_format: {
          type: "json_schema",
          json_schema: { name: opts?.schemaName ?? "video_qa_review", schema: responseSchema },
        },
        stream: false,
      }),
    },
    `gateway chat.completions (${model})`
  );
  const data = (await res.json()) as {
    choices?: Array<{ message?: { content?: string | Array<{ type?: string; text?: string }> } }>;
  };
  const raw = data.choices?.[0]?.message?.content;
  const text = Array.isArray(raw) ? raw.map((p) => p.text ?? "").join("") : raw ?? "";
  if (!text) throw new Error("gateway returned an empty response");
  // Tolerate a fenced block even though the schema is enforced.
  const cleaned = text.trim().replace(/^```(?:json)?\s*/i, "").replace(/\s*```$/, "");
  return JSON.parse(cleaned) as T;
}

export interface GatewayTranscriptSegment {
  text: string;
  startSecond: number;
  endSecond: number;
}

export interface GatewayTranscript {
  text: string;
  segments: GatewayTranscriptSegment[];
  language?: string;
  durationInSeconds?: number;
  warnings?: unknown[];
}

/** Transcribe an audio buffer through the gateway. With `words: true` (default) the
 *  OpenAI provider is asked for word-level timestamps, so `segments` come back one
 *  word each — the shape Layer 2 needs. */
export async function gatewayTranscribe(
  audio: Uint8Array,
  mediaType: string,
  opts?: { model?: string; language?: string; prompt?: string; words?: boolean }
): Promise<GatewayTranscript> {
  const key = gatewayKey();
  if (!key) throw new Error("AI_GATEWAY_API_KEY not set");
  const model = opts?.model ?? transcribeModel();
  const openai: Record<string, unknown> = {};
  if (opts?.words ?? true) openai.timestampGranularities = ["word"];
  if (opts?.language) openai.language = opts.language;
  if (opts?.prompt) openai.prompt = opts.prompt;
  const res = await postWithRetry(
    `${GATEWAY_BASE}/v4/ai/transcription-model`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${key}`,
        "ai-model-id": model,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        audio: Buffer.from(audio).toString("base64"),
        mediaType,
        providerOptions: { openai },
      }),
    },
    `gateway transcription (${model})`
  );
  const data = (await res.json()) as Partial<GatewayTranscript>;
  return {
    text: data.text ?? "",
    segments: (data.segments ?? []).map((s) => ({
      text: (s.text ?? "").trim(),
      startSecond: Number(s.startSecond ?? 0),
      endSecond: Number(s.endSecond ?? 0),
    })),
    language: data.language,
    durationInSeconds: data.durationInSeconds,
    warnings: data.warnings,
  };
}

export interface GatewayModelInfo {
  id: string;
  type?: string;
  tags?: string[];
  name?: string;
}

/** `GET /v1/models` — public, no key needed. */
export async function listGatewayModels(): Promise<GatewayModelInfo[]> {
  const res = await fetch(`${GATEWAY_BASE}/v1/models`);
  if (!res.ok) throw new Error(`gateway /v1/models failed: ${res.status}`);
  const data = (await res.json()) as { data?: GatewayModelInfo[] };
  return data.data ?? [];
}
