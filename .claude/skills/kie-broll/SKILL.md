---
name: kie-broll
description: >
  GENERATE B-roll clips, motion-graphic overlays and shot-card stills for an edit with AI
  video/image models through the kie.ai job API (Seedance, Kling, Wan, Hailuo, Grok Imagine,
  Nano Banana, GPT Image and more behind one key) — product b-roll beats, scene inserts,
  UGC-style shots, animated stills, and flat-black screen-blend overlay clips. Use when an
  edit needs footage that cannot be captured: "generate b-roll of the product", "make an AI
  clip for this beat", "motion graphic overlay for this line", "AI insert shot", "animate
  this frame". NOT for capturing real websites/screens (broll-capture), OpenArt-MCP
  generation (openart-broll), or hand-authored composition cards (branded-ad-edit).
---

# kie.ai B-roll, overlays & stills

Two kinds of generated material for an edit, plus stills:

1. **B-roll beats** — AI clips that replace the talking head for 1.5–6s (product shots,
   scene beats, UGC inserts, stylized illustrations of a spoken claim).
2. **Motion-graphic overlays** — short generated clips layered OVER footage with a blend
   mode, when you want a generated look instead of (or on top of) hand-authored cards.
3. **Stills** — shot-card images and reference frames (a still can also seed an
   image→video clip so the first frame is exactly what the storyboard drew).

## The call contract

Everything runs through `scripts/kie_gen.py` (python3, stdlib only) against
`api.kie.ai`. Key: `KIE_API_KEY` in `.env` (or `~/.config/kie/api-key`). Hosts and
limits: [references/models.md](references/models.md).

1. `python3 scripts/kie_gen.py preflight` once per session — key accepted, host reachable.
2. **Pick the model and copy its id + input fields from its page on
   <https://docs.kie.ai/market>** (or the table in `references/models.md` when it is
   already recorded there). Field names differ per family; a wrong one comes back as a
   non-200 `code` from `createTask`, never as a partial result.
3. `--dry-run` first: shows the exact payload. Then **state the per-clip price from the
   model page and get a yes before submitting** (kie.ai has no quote endpoint; `--est-cost`
   puts the number you read in the log and the confirmation). Retries and re-rolls included.
4. Generate:

   ```bash
   python3 scripts/kie_gen.py generate --model bytedance/seedance-1.5-pro \
     --prompt "..." --aspect 9:16 --duration 5 --slug hero-pour --out <project>/mg/gen \
     --est-cost '$0.xx'
   # image→video from a storyboard frame / a kie still:
   python3 scripts/kie_gen.py generate --model kling-3.0/video --prompt "..." \
     --aspect 9:16 --duration 5 --ref <project>/mg/frames/hero.png --set mode=std --set sound=false
   # a still for a shot card:
   python3 scripts/kie_gen.py generate --model nano-banana-pro --prompt "..." --aspect 9:16 --set resolution=2K
   ```

   The script polls `recordInfo` until `success`/`fail`, downloads every result URL
   (kie.ai links are short-lived and files expire in ~14 days — a bare URL is never the
   deliverable), and appends to `<out>/_kie_log.jsonl` (taskId, fields, creditsConsumed).
   `--no-poll` submits and prints the resume command; `status --task-id … --download`
   finishes a job later.
5. Before placing: re-encode dense keyframes (`-g 30 -keyint_min 30`), frame-extract and
   LOOK — hands, text, logos, warped products. Regenerate defects (budget ~2 retries),
   don't ship them. Record a newly verified model + field set in `references/models.md`.

## Editor rules

### B-ROLL BEATS for a cut

- Generate at the EDIT's aspect (9:16 for reels) and slightly LONGER than the beat window —
  you trim to the best 1.5–6s, never stretch.
- Match the grade direction of the surrounding footage in the prompt (warm/neutral,
  contrast level) or plan a color pass; mismatched grade is what makes AI b-roll feel
  pasted in.
- Follow the reference-reel grammar if a STYLE-GUIDE.md exists: b-roll replaces the face
  for proof/drama beats, 1.3–4.1s, never longer.
- For a product that must look exactly right, generate a still first (Nano Banana Pro
  holds text and labels best), approve it, then animate it image→video — cheaper than
  re-rolling video until the label reads.
- Stills for shot-cards display like real screenshots: sharp card over a blurred blow-up
  of itself, or inside a browser-chrome frame (branded-ad-edit `references/design.md`).

### MOTION-GRAPHIC OVERLAYS (the screen-blend trick)

Generated overlays composite cleanly when you control the background. Proven prompt
contract — every clause matters:

- **flat solid black background (#000000)**, no gradients/vignette/floor, and only BRIGHT
  elements (white/neon) → layer with **Screen or Add blend** and the black vanishes. (True
  alpha isn't a thing text-to-video models give you; black+Screen is the portable
  substitute.)
- **One motion idea per clip** (a slide-in, a count-up, a pulse); end settled or
  seamlessly looping so the editor can freeze/loop to fill the beat.
- On-screen text ≤ 3 words, ALL CAPS, one string — more garbles. Zero-text icon clips are
  safest.
- State the placement zone (top 20% / bottom 25%) in the prompt BUT expect models to
  ignore it and center the graphic — fine: it's a keyed floater, you reposition the layer.
- The script appends "no subtitles, no captions, no on-screen text, no watermark" unless
  `--allow-text`.
- Verify each clip's background is truly flat black before compositing (frame-extract; a
  gray wash under Screen blend reads as haze).

### Placement

Generated beats drop into the composition like any media: a `<video>` inside a card
(unique id, `data-start`/`data-duration`, dense keyframes), or full-bleed via a takeover
card. Overlay clips go on a track above footage with the blend mode — in HyperFrames,
CapCut, or any NLE.

## Provenance

The editor rules were distilled from shipped edits that used generated overlay packs
(flat-black Screen-blend motion graphics with word-synced pops) and generated b-roll /
scene / UGC flows on an earlier vendor's API. The kie.ai transport (`kie_gen.py`) replaces
that vendor; its job API and upload host mirror the kie-image workflow.
