# ARCHITECTURE — Video Editor Agent

## What this is

A Claude Code skill pack that turns raw footage into finished, reviewed short-form video.
All the intelligence lives in `.claude/skills/`; the one piece of real software (the QA
engine) lives in `tools/`; media and renders live in a **projects directory** that is
usually outside this repo. The pack is generic on purpose: a user's brand, machine, reviewer
habits and clients live in the gitignored `MASTER_CONTEXT.md`, and the pack gets better from
every real edit without ever carrying the edit's private details.

## Repo layout

```
.claude/settings.json      # registers the SessionStart hook
.claude/hooks/session-start.sh   # cloud sessions: npm installs, ffmpeg env, python libs, checklist
.claude/skills/            # the skills (each: SKILL.md + references/ scripts/ assets/)
  video-edit-pipeline/     # MASTER orchestrator — start here; routes to everything below
    scripts/fetch_media.py #   SharePoint/OneDrive ↔ container: fetch a sharing link, push a master
    references/sharepoint-media.md  # the cloud media flow, limits, token story
  branded-ad-edit/         # raw talking head → branded motion-graphics ad (HyperFrames)
  reel-recut/              # spec-driven creator reel: banner, karaoke captions, callouts, silence cuts
  reel-style-clone/        # reference reel → STYLE-GUIDE.md + build directives
  multicam-demo-edit/      # multi-take screen+camera+mic demo → EDL base cut → motion-graphics pass
  hook-splitter/           # one long composite of many hooks → N tightened standalone videos
  hook-variations/         # one body × N hooks → N standalone variants (lossless + AVFoundation-verified)
  naming-convention/       # descriptive filenames for a batch of deliverables
  edl-tighten/             # silence/pacing cuts with a full timeline remap
  sound-design/            # ElevenLabs SFX kit + music bed, audit, mixing math
  ai-audio-sound-design/   # AI-actor footage → location ambience, room reverb, bleeps, watermark removal
  broll-capture/           # real-website screenshots and scroll recordings
  kie-broll/               # generated b-roll / overlays / stills via the kie.ai job API (scripts/kie_gen.py)
  openart-broll/           # generated b-roll / overlays via the OpenArt MCP
  video-qa/                # the 4-layer QA procedure (what tools/video-qa automates)
  video-review-canvas/     # here.now review page + timeline-comment readback
  capcut-export/           # layered export to a CapCut draft (WIP)
tools/video-qa/            # the QA ENGINE: a standalone node package (tsx/zod), own package.json
  cli/qa-video.ts          #   4-layer run: --manifest | --lane hyperframes --edl … | --video
  cli/inspect-video.ts     #   Layer-4 inspection packet for one window
  cli/check-gateway.ts     #   qa:check — is the AI Gateway key + model ids in place?
  src/                     #   layer1-technical, layer2-transcript, layer3-semantic, inspect, report,
                           #   manifest/{schema,adapter-hyperframes}, transcribe, gateway, cache, env
  src/__tests__/           #   node:test suite; ffmpeg + macOS `say` fixtures generate on first run
package.json               # root: ONLY the bundled ffmpeg-static / ffprobe-static (+ `npm run setup`)
scripts/
  ffmpeg-env.sh            # resolves ffmpeg/ffprobe (env → bundled → PATH), exports vars + PATH shim
  check-setup.sh           # dependency checklist (mirrors SETUP.md)
  scrub-check.sh           # public-repo hygiene gate (secrets, paths, names, media)
  scrub-denylist.example.txt   # copy → scrub-denylist.local.txt (gitignored) with your own names
.githooks/                 # pre-commit (staged) + pre-push (all) → scrub-check.sh
footage/  outputs/         # gitignored conveniences for a standalone setup
CLAUDE.md                  # session rules
MASTER_CONTEXT.template.md # → MASTER_CONTEXT.md (gitignored): brand, defaults, projects dir, learnings
SESSION_LOG.md             # dated session history
SETUP.md                   # every tool + API with a CHECK and a FIX
.env                       # keys (gitignored; .env.example lists them)
```

## How the skills relate (the pipeline)

`video-edit-pipeline` is the only entry point users need. It decides the lane at intake:

- **Talking head + brand** → `reel-style-clone` (if a reference exists) → `branded-ad-edit`
  (crops/transcribe/storyboard/compose) → `sound-design` (SFX + bed) → QA loop with
  `video-qa` (snapshot → look → fix → render → verify the MP4 with the engine) → deliver via
  `video-review-canvas` → revision rounds (notes readback, frame-evidence per note,
  `edl-tighten` for pacing, new file per version, same slug) → optional `capcut-export`.
- **The creator's own signature reel look** → `reel-recut` (one JSON spec, deterministic).
- **Multi-take screen + camera + mic recordings** → `multicam-demo-edit` (EDL base cut the
  reviewer locks, then a motion-graphics pass).
- **One long recording of many hooks** → `hook-splitter`; an approved body plus many hooks →
  `hook-variations`; any batch of more than two files → `naming-convention` before delivery.
- **AI-actor footage that sounds sterile** → `ai-audio-sound-design` (audio-only pass).
- B-roll comes from `broll-capture` (real screens) or `kie-broll` / `openart-broll`
  (generated).

The specialist skills are also independently invocable for narrowly scoped requests.

## The QA engine (`tools/video-qa`)

The `video-qa` skill documents the four layers as a procedure; `tools/video-qa` implements
them. It is a self-contained node package: `npm --prefix tools/video-qa install` once, then
`npm --prefix tools/video-qa run qa:video -- …` from anywhere (relative paths resolve
against the directory you ran it from via `INIT_CWD`, and `.env` is read from there first,
then from this repo's root). Reports land next to the video in `_qa/<stem>/`; exit codes
0 / 1 / 2 = PASS / PASS_WITH_WARNINGS / FAIL. Every hosted-model call goes through the
**Vercel AI Gateway** (`src/gateway.ts`, plain fetch): Layer 3 attaches the 480p proxy to an
OpenAI-compatible chat completion on a Gemini model (`VIDEO_QA_MODEL`) with a JSON schema
enforced, and skips cleanly without `AI_GATEWAY_API_KEY`; transcription uses whisper.cpp via
`npx hyperframes transcribe`, falling back to whisper through the gateway
(`VIDEO_QA_TRANSCRIBE_MODEL`, word-level timestamps) when the key is set. `npm --prefix
tools/video-qa run qa:check` verifies the key and model ids; `npm --prefix tools/video-qa
test` runs the suite (a clean canary + a real mid-word-cut fixture).

## Cloud mode (Claude Code on the web)

The pack is built to be opened from claude.ai/code by anyone on the team with nothing on
their machine: the SessionStart hook installs the bundled ffmpeg and the QA engine; keys are
environment secrets; footage arrives as a SharePoint/OneDrive link and is fetched into
`outputs/<slug>/` in the container; the cut ships on the review canvas and optionally back
to the library. Mac-only lanes (AVFoundation probe, Screen Studio capture, CapCut export)
report themselves as unavailable rather than failing. SETUP.md § Cloud has the allowlist.

## Working-folder mode and the projects directory

A user's videos usually live in their own working repo, not here. The pattern:

1. That repo symlinks every skill in `.claude/skills/` here with **relative** links
   (`../../../../Video Editor Agent/.claude/skills/<name>`), so a Claude Code session started
   there loads the skills while the files stay in this repo — edited here, committed here.
2. `MASTER_CONTEXT.md` (here, gitignored) names the **projects directory**; every skill
   creates `<projects dir>/<project-slug>/` for its working files and never moves media into
   this repo. `VIDEO_PROJECTS_DIR` in `.env` says the same for scripts.
3. The working repo aliases the QA engine (`"qa:video": "npm --prefix \"<pack>/tools/video-qa\" run qa:video --"`).
4. Personal/process split: generic lessons go into the skill; the client, the fee, the
   reviewer's name, machine paths and review URLs go into MASTER_CONTEXT.md or the working
   repo's own logs. `scripts/scrub-check.sh` enforces it at commit and push time.

## External dependencies (documented, not vendored)

- **HyperFrames** — composition + render engine: `npx hyperframes`, plus
  `npx hyperframes skills update talking-head-recut` for fonts/gsap; `npx hyperframes
  transcribe` is the default whisper.cpp route.
- **ffmpeg / ffprobe** — all probing, extraction, cropping, muxing. **Bundled** through the
  root `package.json` (`ffmpeg-static`, `ffprobe-static`), so no machine install; scripts
  read `FFMPEG` / `FFPROBE` (or `FFMPEG_PATH` / `FFPROBE_PATH`), then the bundled build,
  then PATH / Homebrew. `scripts/ffmpeg-env.sh` exports the paths and a PATH shim. No
  libass/drawtext needed anywhere — text goes through PIL PNGs or HTML.
- **SharePoint / OneDrive** — the team's media home for cloud sessions. Sharing links in,
  Graph upload sessions out (`fetch_media.py`; `MS_GRAPH_TOKEN` for org-only links and
  pushes). The Microsoft 365 connector covers lookups and sub-1 MB text artefacts.
- **whisper-cli + ggml models** — word-level transcription and VAD for the cut planners
  (`WHISPER_CLI`, `WHISPER_MODEL`, `VAD_BIN`, `VAD_MODEL`).
- **node >= 20**, **python3** (+ PIL; numpy/scipy for `ai-audio-sound-design`).
- **ElevenLabs API** — `ELEVENLABS_API_KEY`; **Vercel AI Gateway** (optional) —
  `AI_GATEWAY_API_KEY`, the single key for every LLM / whisper call (`VIDEO_QA_MODEL`,
  `VIDEO_QA_TRANSCRIBE_MODEL` pick `provider/model` ids); **kie.ai** (optional) — `KIE_API_KEY`
  for generated footage; **OpenArt MCP** (optional). No direct OpenAI, Google or Arcads keys.
- **here-now skill** — canvas publishing; docs at https://here.now/docs (fetch with
  `User-Agent: claude`), credentials in `~/.herenow/credentials`.
- **pyJianYingDraft** in a venv — CapCut export only. **Swift toolchain** — builds
  `hook-variations`' `avtest` probe on first use.

## Provenance

Distilled from a production editing stack and real shipped edits: a 4-round paid brand ad,
a style-clone reel, a product-news explainer built from a generated likeness, an eight-version
multi-take product demo, a 21-hook composite split and re-joined into 42 variants, and a
10-scene AI-actor audio pass. The hard-won lessons (two crop candidates shown as images, one
batched snapshot, per-note evidence tables, new file per version, verify-in-pixels, verify with
a different decoder than you built with) are baked into the skills rather than left as tribal
knowledge.
