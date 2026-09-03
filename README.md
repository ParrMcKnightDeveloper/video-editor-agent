# Video Editor Agent

A Claude Code skill pack that edits short-form videos **end to end**: raw footage in, a
finished edit out — style cloned from a reference reel, sound-designed with ElevenLabs,
QA'd frame by frame and in dB, delivered on a live review page with timeline comments,
and revised round after round until sign-off.

This is not a rendering library. It is a set of skills, plus one QA engine, that make a
Claude Code session behave like a working video editor with a proven pipeline and a
"verify pixels and dB, not intentions" culture. It gets better with every real edit: the
process goes into the skills, the personal details stay in a gitignored context file.

## The pipeline

```
footage + (optional) reference reel + brand/site + ratio
        │
        ▼
[0] video-edit-pipeline picks the lane
      talking head + brand ─────────────→ [1]–[7] below
      creator's own reel look ──────────→ reel-recut
      multi-take screen+camera+mic ─────→ multicam-demo-edit
      one long file of many hooks ──────→ hook-splitter (→ hook-variations)
      AI-actor footage that sounds fake → ai-audio-sound-design
        │
        ▼
[1] reel-style-clone ──────────→ STYLE-GUIDE.md (only if a reference exists)
        │
        ▼
[2] branded-ad-edit
      ingest → two crop candidates (zoom vs blur-pad — show both)
      whisper transcript → storyboard from the style guide
      hand-authored composition + karaoke captions + SFX markers
      B-roll: broll-capture (real screens) / kie-broll / openart-broll (generated)
        │
        ▼
[3] sound-design ──────────────→ ElevenLabs SFX kit + music bed, mixed by math
        │
        ▼
[4] QA loop (video-qa + tools/video-qa)
      hyperframes check → ONE multi-timestamp snapshot → LOOK with vision
      → fix → render MP4 → the engine verifies the RENDERED file (frames + dB + seams)
        │
        ▼
[5] video-review-canvas ───────→ live review URL (reply leads with the link)
        │
        ▼
[6] revision rounds
      read notes → screenshot the exact frame per note → fix
      edl-tighten for pacing → new file per version → republish same slug
      per-note QA table with evidence from the rendered file
      one cut → many variants: hook-variations, then naming-convention
        │
        ▼
[7] (optional) capcut-export ──→ CapCut draft for a human's final pass
```

## Quickstart — from Claude Code on the web (nothing installed on your machine)

1. Open this repo in a Claude Code environment at claude.ai/code. The SessionStart hook
   installs the bundled ffmpeg/ffprobe and the QA engine and prints the setup checklist.
2. In the environment's settings, add the keys as secrets: `ELEVENLABS_API_KEY` (sound,
   required), `AI_GATEWAY_API_KEY` (Vercel AI Gateway — every LLM/whisper call, no OpenAI
   or Gemini keys) and `KIE_API_KEY` (kie.ai generated footage). Allowlist the hosts listed
   in **[SETUP.md § Cloud](SETUP.md)**.
3. Put your footage in SharePoint or OneDrive and paste the sharing link into the chat:
   **"edit this like `<reference reel>`"** — or just "edit this video". The
   `video-edit-pipeline` skill fetches the file, edits, QAs, and hands back a review-page
   link (and, if you want, pushes the master back to the library).

## Quickstart — on your own machine

1. Clone this repo, `npm run setup` (bundled ffmpeg + QA engine), open it in Claude Code.
2. Work through **[SETUP.md](SETUP.md)** (or run `bash scripts/check-setup.sh`) —
   it lists every tool and API with a check + fix for each. No MCP servers needed.
3. Copy `.env.example` to `.env` and paste the same three keys. Only ElevenLabs is required.
4. Copy `MASTER_CONTEXT.template.md` to `MASTER_CONTEXT.md` and fill in your brand,
   defaults and **projects directory** (where the videos live — default `outputs/`).
5. Drop your raw footage into the projects directory (or `footage/`) and say
   "edit this video".

## Using it from your own working repo

Most people keep their videos, queues and brand tooling in a repo of their own. Keep that,
and point it at this pack instead of copying skills into it:

- Symlink every skill: `ln -s "../../../../Video Editor Agent/.claude/skills/<name>"
  <your repo>/.claude/skills/<name>` (relative links survive network mounts). A session
  started in your repo loads the skills; the files stay here, edited and committed here.
- Set the projects directory in `MASTER_CONTEXT.md` (and `VIDEO_PROJECTS_DIR` in `.env`)
  to your media folder. Media never moves into this repo.
- Alias the QA engine in your `package.json`:
  `"qa:video": "npm --prefix \"<path to this repo>/tools/video-qa\" run qa:video --"`.
  Relative paths resolve from where you run it; your `.env` is read first.
- Improvements from every real edit go back into the skills here — generic process only.
  Your client names, fees, reviewer preferences and machine paths belong in
  `MASTER_CONTEXT.md`, which never leaves your disk.

## Prerequisites

| Dependency | Why | Install / notes |
|---|---|---|
| Node.js >= 20 | HyperFrames, the QA engine, the scripts | nodejs.org |
| ffmpeg / ffprobe | every probe, extract, crop, mux | **bundled**: `npm install` at the root pulls static builds (`ffmpeg-static`, `ffprobe-static`); `scripts/ffmpeg-env.sh` wires the paths — no brew/apt, no libass/drawtext needed |
| SharePoint / OneDrive (cloud sessions) | footage in, masters out | sharing links + `video-edit-pipeline/scripts/fetch_media.py`; `MS_GRAPH_TOKEN` only for org-only links and pushes |
| HyperFrames | composition + rendering engine | `npx hyperframes`; then `npx hyperframes skills update talking-head-recut` (pulls fonts + gsap) |
| whisper (bundled route) | word-level transcription | `npx hyperframes transcribe` manages whisper.cpp models; `whisper-cli` + a ggml model unlocks the VAD-driven cut planners |
| python3 | helper scripts | PIL (`pip install pillow`) for overlays; numpy + scipy for `ai-audio-sound-design` |
| QA engine | `tools/video-qa` | `npm --prefix tools/video-qa install` (tsx, zod, dotenv) |
| ElevenLabs API key | SFX + music + ambience generation | `ELEVENLABS_API_KEY` in `.env` at repo root |
| here-now skill + credentials | canvas review delivery | agent docs at https://here.now/docs (fetch with `User-Agent: claude`); credentials live in `~/.herenow/credentials` |
| `AI_GATEWAY_API_KEY` (optional) | Vercel AI Gateway — video-qa's watch+listen layer (L3, a Gemini model) and the cloud whisper fallback (QA engine, hook-splitter, multicam-demo-edit) | one key, `provider/model` ids; skip if unset — L3 skips, local whisper.cpp stays the default; `npm --prefix tools/video-qa run qa:check` verifies it |
| Puppeteer (optional) | scripted website screenshots/B-roll (`broll-capture`) | `npm i puppeteer` in the repo; or use a connected browser MCP instead |
| Screen Studio (optional) | high-fidelity real-browser B-roll (`broll-capture` Lane C) | any screen recorder works; Screen Studio + its CLI is the polished path |
| OpenArt MCP (optional) | AI-generated B-roll / talking heads / overlays (`openart-broll`) | connect the OpenArt MCP in your client; verify with `openart_account_get` — no API key |
| kie.ai (optional) | generated B-roll, overlays and stills (`kie-broll`), also the clip source for `multicam-demo-edit` | `KIE_API_KEY` in `.env`; `python3 .claude/skills/kie-broll/scripts/kie_gen.py preflight` |
| Swift toolchain (optional, **Mac only**) | `hook-variations`' AVFoundation probe (`avtest`) | Xcode command-line tools; built on first use; skipped with a note in cloud sessions |
| pyJianYingDraft in a venv (optional, **Mac only**) | CapCut draft export | only needed for the capcut-export handoff; not available in cloud sessions |

External dependencies are documented, not vendored — nothing in this repo ships a copy of
HyperFrames, whisper models, or ffmpeg.

## Skills catalog

| Skill | What it does |
|---|---|
| `video-edit-pipeline` | **Master orchestrator.** Picks the lane and routes any edit request through the full pipeline. Start here. |
| `branded-ad-edit` | Raw talking head → finished branded motion-graphics ad: framing grammar, card-per-line, karaoke captions, ~40 SFX + bed, QA → render → verify. |
| `reel-recut` | The creator's own short-form look from ONE JSON spec: title banner, karaoke captions, callout boxes, silence-cut pacing; raw-cut mode for footage a client's editor finishes. |
| `reel-style-clone` | Reverse-engineer a reference reel frame by frame into a STYLE-GUIDE.md + build directives. |
| `multicam-demo-edit` | Multi-take screen + camera + mic recordings → an EDL-driven base cut the reviewer locks, then a HyperFrames motion-graphics pass with takeovers, the base video as a character, captions, SFX and music. |
| `hook-splitter` | One long recording of many hooks/takes → one tightened standalone video per hook, QA'd by re-transcribing the renders, delivered on a gallery canvas with a comment box per video. |
| `hook-variations` | One approved body × N hooks → N standalone variants, joined losslessly, loudness-matched, verified with AVFoundation (not just ffmpeg). |
| `naming-convention` | Filenames that carry every axis that varies; verify a subject label before baking it into 40 files. |
| `edl-tighten` | Surgical silence/pacing cuts with a full timeline remap (captions/cards/SFX stay synced). |
| `sound-design` | ElevenLabs SFX/music generation, audit pass, style-matching a reference track, mixing math. |
| `ai-audio-sound-design` | Rebuild the audio of AI-actor footage: location ambience beds, room-matched reverb, outdoor distance, censor bleeps, watermark-whine removal, social loudness master. |
| `video-qa` | The 4-layer QA procedure — and `tools/video-qa`, the engine that runs it on any rendered MP4. |
| `video-review-canvas` | here.now review page with frame-accurate scrubber + timeline comments; reads notes back per version. |
| `broll-capture` | Website screenshots + B-roll: Puppeteer/Playwright-MCP full-page shots, scripted-scroll recordings, and a Screen Studio real-browser lane for automation-blocked sites. |
| `kie-broll` | GENERATED B-roll, screen-blend overlays and shot-card stills via the **kie.ai job API** (Seedance, Kling, Wan, Nano Banana, GPT Image…) — the pipeline's primary generation lane; `scripts/kie_gen.py` submits, polls, downloads. |
| `openart-broll` | Alternative generation lane via the **OpenArt MCP** — identity-referenced talking heads from a reference video, plus b-roll and overlays. |
| `capcut-export` | Layered export into a CapCut draft via pyJianYingDraft. |

## Limitations (honest)

- **The gateway route for video review is documented, not yet run from this pack.** Layer 3
  attaches the proxy as a `file` part on an OpenAI-compatible chat completion; the first
  live run with a real key is the proof. `npm --prefix tools/video-qa run qa:check` confirms
  the model ids beforehand, and the layer degrades to `skipped` with the reason if the
  gateway rejects the attachment.
- **kie.ai model ids and input fields are per family.** `kie-broll/references/models.md`
  holds the ids seen on the docs; confirm fields on the model page before the first spend.
- **CapCut export is work-in-progress.** The layered export works but the schema patch is
  still being hardened — always verify the draft opens in CapCut before relying on it.
- **Canvas delivery requires here.now.** Without the here-now skill and credentials you
  still get the rendered MP4, just no live review page or timeline-comment loop.
- Transcription quality tracks your whisper model choice; tiny models miss words that then
  miss captions.
- The main build assumes single-subject talking-head source footage; multi-shot sources go
  through `multicam-demo-edit` (screen + camera takes) or `hook-splitter` (one long composite)
  first.
- The QA engine's mid-word-cut test fixture uses macOS `say`; on other platforms that one
  test is skipped.
