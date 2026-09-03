# kie.ai models for generated B-roll, overlays and stills

One key (`KIE_API_KEY`), one prepaid credit wallet, one job API for every model:

- create: `POST https://api.kie.ai/api/v1/jobs/createTask` body `{"model": "<id>", "input": {…}}`
  (optional `"callBackUrl"`) → `{"code": 200, "data": {"taskId": "…"}}`
- poll: `GET https://api.kie.ai/api/v1/jobs/recordInfo?taskId=<id>` → `data.state` in
  `waiting | queuing | generating | success | fail`; on success `data.resultJson` is a JSON
  **string** with `resultUrls: […]`; `data.creditsConsumed` is the spend; on fail
  `data.failCode` / `data.failMsg`.
- header on both: `Authorization: Bearer <KIE_API_KEY>`.

`scripts/kie_gen.py` wraps this. Model ids and input field names are **per model family** and
kie.ai does not keep them consistent (some namespaced, some not) — before the first call on a
model, open its page under <https://docs.kie.ai/market>, copy the id and fields, and record
them here. `createTask` returning a non-200 `code` is almost always a field mismatch.

## Video models (ids seen on docs.kie.ai, Sep 2026 — verify fields on the model page before use)

| id | family | notes |
|---|---|---|
| `bytedance/seedance-1.5-pro` | Seedance 1.5 Pro | text→video and image→video; the workhorse for product beats |
| `bytedance/seedance-2` | Seedance 2.0 (+ `-fast`, `-mini` variants listed) | newest Seedance; audio-capable |
| `bytedance/v1-pro-text-to-video` | Seedance 1.0 Pro | cheaper text→video |
| `bytedance/v1-lite-image-to-video` | Seedance 1.0 Lite | cheapest image→video (animate a still / first frame) |
| `kling-3.0/video` | Kling 3.0 | inputs seen: `prompt`, `image_urls` (first/last frame), `sound`, `duration` (3–15 s), `aspect_ratio` (16:9 / 9:16 / 1:1), `mode` (`std` / `pro`); multi-shot supported |
| Veo 3.1 | Google | lives behind a **separate** endpoint (`/api/v1/veo/generate`, fields `prompt`, `model`, `aspect_ratio`, `generationType`), not the jobs API — `kie_gen.py` does not cover it |

Also on the market: Wan, Hailuo, Grok Imagine, PixVerse and others — same job API.

## Stills (shot cards, reference frames)

| id | reference field | notes |
|---|---|---|
| `nano-banana-pro` | `image_input` | best at readable in-image text; `aspect_ratio`, `resolution` (`1K`/`2K`/`4K`), `output_format` |
| `nano-banana-2` | `image_input` | cheaper, same shape |
| `gpt-image-2` / `gpt-image-2-image-to-image` | `input_urls` | different field name |

## Costs (indicative — read the live price off the model page and pass it as `--est-cost`)

Prepaid credits, no expiry, failed tasks reportedly not charged. kie.ai has no quote
endpoint, so the gate is manual: read the per-clip price, say it, get the yes, then submit.
Third-party reviews (Aug 2026) put Seedance/Kling short clips in the tens of cents each and
stills at roughly $0.03–0.09; treat those as order-of-magnitude only.

## Hosts (each one needs a network allowlist entry in a sandboxed session)

- `api.kie.ai` — createTask / recordInfo (JSON only)
- `tempfile.aiquickdraw.com` — where finished files are served from
- `kieai.redpandaai.co` — base64 upload host for local reference files (≤ 10 MB; anything
  bigger must be hosted and passed as an https URL)

## Limits and retention

- 20 new tasks per 10 s; HTTP 429 is rejected, not queued.
- Generated media is kept ~14 days; direct download links are short-lived. **Always download
  immediately** (the script does) — a bare kie.ai URL is never the deliverable.
- Task history and spend: <https://kie.ai/logs>.

## Verified-here log

Append a line when a model + field set is confirmed working from this pack:

- (none yet — `python3 scripts/kie_gen.py generate --dry-run …` shows the payload before spending)
