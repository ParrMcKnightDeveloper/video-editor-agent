#!/usr/bin/env python3
"""Step 2b — the two speech maps the planner needs, off the MIC track.

  work/vad.txt    silero VAD speech segments
  work/words.json whisper word timestamps, OpenAI verbose_json shape ({"words": [{word,start,end}]})

Both are needed and neither is sufficient. VAD clips word ONSETS (it started
"Alright" at 3.52s where the energy and whisper both put it at 2.48s); whisper drifts
and stretches. plan.py uses them only as a cross-check on an energy gate.

    python3 transcribe.py [hooks.json]

Whisper runs through the Vercel AI Gateway (POST /v4/ai/transcription-model, model
VIDEO_QA_TRANSCRIBE_MODEL, default openai/whisper-1, word-level timestamps requested via
providerOptions.openai). Needs AI_GATEWAY_API_KEY (env, or a .env anywhere up the tree from
the config). The audio travels base64-inline, so the mic is encoded to 48k mono mp3 first.
"""
import base64, json, os, re, subprocess, sys, time, urllib.error, urllib.request
from _cfg import load, w, FFMPEG, VAD_BIN, VAD_MODEL

cfg = load()
mic = w(cfg, f"a{cfg['audio']['mic']}.wav")

# ── VAD ───────────────────────────────────────────────────────────────────────────
raw = subprocess.run([VAD_BIN, "-f", mic, "-vm", VAD_MODEL, "-vt", "0.5"],
                     capture_output=True, text=True).stdout
lines = [l for l in raw.splitlines() if "start" in l and "end" in l]
open(w(cfg, "vad.txt"), "w").write("\n".join(lines))
print(f"VAD: {len(lines)} segments")
# NOTE: this binary prints CENTISECONDS. Dividing by 1000 silently throws away
# everything past ~98s. plan.py divides by 100 — do not "fix" that.

# ── words, via whisper through the Vercel AI Gateway ──────────────────────────────
key = os.environ.get("AI_GATEWAY_API_KEY") or os.environ.get("VERCEL_OIDC_TOKEN")
if not key:
    d = cfg["_root"]
    for _ in range(6):
        p = os.path.join(d, ".env")
        if os.path.exists(p):
            m = re.search(r"^AI_GATEWAY_API_KEY=(.+)$", open(p).read(), re.M)
            if m: key = m.group(1).strip().strip('"').strip("'"); break
        d = os.path.dirname(d)
if not key:
    sys.exit("AI_GATEWAY_API_KEY not found (env or .env)")
GATEWAY = os.environ.get("AI_GATEWAY_BASE_URL", "https://ai-gateway.vercel.sh").rstrip("/")
MODEL = os.environ.get("VIDEO_QA_TRANSCRIBE_MODEL", "openai/whisper-1")

mp3 = w(cfg, "mic.mp3")
subprocess.run([FFMPEG, "-y", "-v", "error", "-i", mic,
                "-c:a", "libmp3lame", "-b:a", "48k", mp3], check=True)
size = os.path.getsize(mp3) / 1e6
print(f"mic.mp3 {size:.1f} MB  (sent base64-inline; keep it under ~20 MB — mono 48k mp3 holds ~55 min)")

opts = {"timestampGranularities": ["word"], "language": "en"}
if cfg.get("prompt"):
    opts["prompt"] = cfg["prompt"]
body = json.dumps({"audio": base64.b64encode(open(mp3, "rb").read()).decode(),
                   "mediaType": "audio/mpeg", "providerOptions": {"openai": opts}}).encode()
data = None
for attempt in range(3):
    r = urllib.request.Request(f"{GATEWAY}/v4/ai/transcription-model", data=body, method="POST",
                               headers={"Authorization": f"Bearer {key}", "ai-model-id": MODEL,
                                        "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=600) as resp:
            data = json.loads(resp.read().decode())
        break
    except urllib.error.HTTPError as e:
        msg = e.read().decode(errors="replace")[:600]
        if e.code in (429, 502, 503, 504) and attempt < 2:
            time.sleep(15 * (attempt + 1)); continue
        sys.exit(f"gateway transcription HTTP {e.code}: {msg}")
if data is None:
    sys.exit("gateway transcription: no response")

segs = [s for s in data.get("segments") or [] if (s.get("text") or "").strip()]
multi = sum(1 for s in segs if len(s["text"].split()) > 2)
if segs and multi > len(segs) / 2:
    sys.exit(f"{MODEL} returned sentence segments, not words; plan.py needs word timestamps "
             f"(providerOptions.openai.timestampGranularities=['word'] was requested)")
out = {"text": data.get("text", ""), "language": data.get("language"),
       "duration": data.get("durationInSeconds"),
       "words": [{"word": s["text"].strip(), "start": s["startSecond"], "end": s["endSecond"]} for s in segs]}
json.dump(out, open(w(cfg, "words.json"), "w"), indent=1)
print(f"words: {len(out['words'])}   (model {MODEL} via the AI Gateway)")
