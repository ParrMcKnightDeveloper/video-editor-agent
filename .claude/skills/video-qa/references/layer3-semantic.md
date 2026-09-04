# Layer 3 — whole-video semantic QA (a multimodal model watches AND listens)

Optional layer. A multimodal model reviews the whole render — video **and** audio together —
and returns candidate issues as schema-enforced JSON. Its timestamps are approximate (±1–2s):
its job is to tell you WHERE to look. L4 verifies before anything is changed. Model-only
findings never exceed HIGH; corroboration with a deterministic finding is what raises
confidence.

**Transport:** the **Vercel AI Gateway** — one key for every hosted model, ids as
`provider/model`, spend visible in the Vercel dashboard. Nothing calls Google or OpenAI
directly. **Auth:** `AI_GATEWAY_API_KEY` from the `.env` at repo root (e.g.
`set -a; . ./.env; set +a`). Missing → mark the layer `skipped` with the reason and move on —
never crash, never block the run. **Model:** `VIDEO_QA_MODEL`, default
`google/gemini-3.6-flash`. Keep it on a Gemini id: that is the family that takes a video file
with its audio. `GET https://ai-gateway.vercel.sh/v1/models` (no key) lists current ids with a
`file-input` tag; `npm --prefix tools/video-qa run qa:check` does that lookup for you.

## 1. Build a 480p proxy — with the audio intact

Half of real editing mistakes are audible. Never strip or downsample the audio to nothing:

```bash
"$FF" -nostdin -y -i "$VIDEO" -vf "scale=-2:480,fps=15" \
  -c:v libx264 -preset veryfast -crf 30 -c:a aac -b:a 128k \
  -movflags +faststart "$QA/proxy.mp4"
```

The proxy is attached **inline as base64**, so it has a size ceiling (the engine uses 18 MB,
`VIDEO_QA_PROXY_MAX_MB`). Over it: re-encode once at `fps=8`, `-crf 36`; still over → skip the
layer with the reason and QA the render in shorter sections.

## 2. One chat completion with the file attached and the schema enforced

OpenAI-compatible request; the video is a `file` content part, JSON output is enforced via
`response_format: json_schema`, not prompt-please:

```bash
B64=$(base64 -i "$QA/proxy.mp4")
curl -s -X POST https://ai-gateway.vercel.sh/v1/chat/completions \
  -H "Authorization: Bearer $AI_GATEWAY_API_KEY" -H "Content-Type: application/json" \
  -d @- <<EOF
{
  "model": "${VIDEO_QA_MODEL:-google/gemini-3.6-flash}",
  "temperature": 0.2,
  "messages": [{ "role": "user", "content": [
    { "type": "file", "file": { "data": "$B64", "media_type": "video/mp4", "filename": "qa-proxy.mp4" } },
    { "type": "text", "text": "<the prompt, below>" }
  ]}],
  "response_format": { "type": "json_schema", "json_schema": { "name": "video_qa_review", "schema": {
    "type": "object", "required": ["issues"], "properties": {
      "issues": { "type": "array", "items": { "type": "object",
        "required": ["startSec","endSec","severity","category","objective","description"],
        "properties": {
          "startSec": {"type":"number"}, "endSec": {"type":"number"},
          "severity": {"type":"string","enum":["high","medium","low"]},
          "category": {"type":"string","enum":["abrupt_cut","clipped_dialogue","audio_glitch","music_balance","sync_issue","dead_air","caption_error","visual_glitch","duplicate_footage","framing_crop","graphic_timing","pacing","content_error","other"]},
          "objective": {"type":"boolean"}, "confidence": {"type":"number"},
          "description": {"type":"string"} } } },
      "overallNotes": {"type":"string"} } } } }
}
EOF
```

The review is `choices[0].message.content` (a JSON string). **Retry 429/502/503/504 ×3**
with growing backoff (~15s, 30s, 45s), then degrade the layer to `skipped` with the reason.
Frame sampling is the model's default through this route (roughly 1 fps); fast visual events
are L1's job (flash/black/freeze detection is deterministic), so nothing is lost there.

## 3. The prompt (calibration lines matter — keep them)

> You are a professional short-form video editor doing final QA on an export before it
> ships. The attached file has BOTH video and audio. Review them TOGETHER — listen while you
> watch. Roughly half of real editing mistakes are audible, not visible (clipped words at
> cuts, duplicate phrases, abrupt music, dead air, clicks at splices, SFX drowning the
> voice).
>
> Report across both modalities:
> - VISUAL: glitches, stray/duplicate frames, wrong or repeated footage, jarring
>   transitions, bad crop or framing, subject cut off, graphics appearing/disappearing at
>   wrong times, captions covering the speaker's face, caption timing/text problems,
>   unintended blank space, abrupt start or ending, b-roll that doesn't match what is
>   being said.
> - AUDIO & AUDIO-VISUAL: words cut off mid-syllable, dialogue repeated across a cut,
>   audio/video desync, dead air, unintentional silence, music starting/stopping
>   abruptly, music/dialogue balance, sound effects mistimed or masking speech, pacing.
>
> Calibration — follow exactly:
> - Zero issues is a valid and expected outcome for a clean video. Do not invent problems.
> - Report mistakes, unintended behavior, deviations from instructions, and obvious
>   quality problems. Do not fail the video because you would make a different creative
>   choice.
> - Separate objective errors (objective=true) from subjective suggestions
>   (objective=false) and label each.
> - Fast jump cuts, karaoke captions, and bold graphic cards are the INTENTIONAL style of
>   these edits — only flag a cut if something is audibly or visibly broken at it.
> - Your timestamps may be off by ±2 seconds; report your best estimate without agonizing
>   over precision.
>
> Edit intent (from the editing system — treat as ground truth for what is deliberate):
> `<summary: lane, expected duration, cut seam times, caption count, placed elements,
> INTENTIONAL black/silent regions from the manifest>`
>
> Original editing request/instructions: `<the user's brief, when available>`
>
> Return JSON only, matching the response schema.

Feeding the manifest summary in is what stops the model from flagging deliberate jump cuts
and intentional silences. Feeding the original brief lets it catch deviations from
instructions.

## 4. Post-process

For each returned issue: clamp times into [0, duration]; map severity high/medium/low →
HIGH/MEDIUM/LOW; anchor to the nearest manifest event within 2s; keep the raw reported
window in evidence. Pad windows ±1.5s before building an L4 packet. Layer status: any HIGH →
`fail` · any issue → `warn` · else `pass`.

## Cost

One call bills the proxy's video+audio tokens plus the short JSON reply on the Gemini model;
a 60 s ad is a few cents. It shows under the gateway key in Vercel. The layer is cached per
video+manifest+model+rubric, so a re-run on an unchanged render is free.
