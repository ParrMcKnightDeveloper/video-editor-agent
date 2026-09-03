#!/usr/bin/env node
/**
 * Per-shot word timestamps through the Vercel AI Gateway (a whisper model, word granularity).
 *
 *   node mg/transcribe-shots.mjs [<project dir>]      # or PROJECT_DIR=<project dir>
 *
 * Reads  <project>/mg/seg-audio/manifest.json  — [{ id, wav, master_start }] one entry per shot,
 *        each wav being that shot's dry mic audio for exactly the EDL's keep ranges.
 * Writes <project>/mg/words.json                — [{ text, start, end, seg }] in OUTPUT time.
 *
 * Why per shot: whisper on the concatenated cut drifts up to +1s by the back half; each shot
 * transcribed in isolation and offset by its master_start does not.
 *
 * Env: AI_GATEWAY_API_KEY (environment, or a .env from the project dir up to /),
 *      VIDEO_QA_TRANSCRIBE_MODEL (default openai/whisper-1),
 *      WHISPER_PROMPT — brand and product names the speaker says, so they are spelled right.
 * Plain node >= 20, no dependencies.
 */
import fs from "node:fs";
import path from "node:path";

const BASE = path.resolve(process.argv[2] || process.env.PROJECT_DIR || ".");
const GATEWAY = (process.env.AI_GATEWAY_BASE_URL || "https://ai-gateway.vercel.sh").replace(/\/$/, "");

function loadDotenvUp(start) {
  let dir = start;
  for (;;) {
    const p = path.join(dir, ".env");
    if (fs.existsSync(p)) {
      for (const line of fs.readFileSync(p, "utf8").split("\n")) {
        const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$/);
        if (m && !(m[1] in process.env)) process.env[m[1]] = m[2].replace(/^['"]|['"]$/g, "");
      }
    }
    const parent = path.dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
}
loadDotenvUp(BASE);

const KEY = process.env.AI_GATEWAY_API_KEY || process.env.VERCEL_OIDC_TOKEN;
if (!KEY) {
  console.error("AI_GATEWAY_API_KEY not set (environment or a .env up the tree)");
  process.exit(1);
}
const MODEL = process.env.VIDEO_QA_TRANSCRIBE_MODEL || "openai/whisper-1";
const PROMPT = process.env.WHISPER_PROMPT || "";

async function transcribe(wavBytes) {
  const openai = { timestampGranularities: ["word"] };
  if (PROMPT) openai.prompt = PROMPT;
  let res;
  for (let attempt = 0; attempt < 3; attempt++) {
    res = await fetch(`${GATEWAY}/v4/ai/transcription-model`, {
      method: "POST",
      headers: { Authorization: `Bearer ${KEY}`, "ai-model-id": MODEL, "Content-Type": "application/json" },
      body: JSON.stringify({ audio: Buffer.from(wavBytes).toString("base64"), mediaType: "audio/wav", providerOptions: { openai } }),
    });
    if (![429, 502, 503, 504].includes(res.status)) break;
    await new Promise((r) => setTimeout(r, 15_000 * (attempt + 1)));
  }
  if (!res.ok) throw new Error(`gateway transcription ${res.status}: ${(await res.text()).slice(0, 300)}`);
  return res.json(); // { text, segments:[{text,startSecond,endSecond}], language, durationInSeconds }
}

async function main() {
  const man = JSON.parse(fs.readFileSync(path.join(BASE, "mg/seg-audio/manifest.json"), "utf8"));
  const words = [];
  for (const m of man) {
    const r = await transcribe(fs.readFileSync(path.join(BASE, m.wav)));
    const segs = (r.segments ?? []).filter((s) => (s.text ?? "").trim());
    const multi = segs.filter((s) => s.text.trim().split(/\s+/).length > 2).length;
    if (segs.length && multi > segs.length / 2) {
      console.error(`${m.id}: the model returned sentence segments, not words — the per-word captions need word granularity (model=${MODEL})`);
      process.exit(1);
    }
    const ws = segs.map((s) => ({
      text: s.text.trim(),
      start: +(m.master_start + s.startSecond).toFixed(3),
      end: +(m.master_start + s.endSecond).toFixed(3),
      seg: m.id,
    }));
    words.push(...ws);
    console.log(`${m.id.padEnd(16)} ${String(ws.length).padStart(3)}w  ${(r.text ?? "").trim().slice(0, 78)}`);
  }
  words.sort((a, b) => a.start - b.start);
  fs.writeFileSync(path.join(BASE, "mg/words.json"), JSON.stringify(words, null, 1));
  console.log(`\nTOTAL ${words.length} words -> mg/words.json`);
}
main().catch((e) => { console.error(e); process.exit(1); });
