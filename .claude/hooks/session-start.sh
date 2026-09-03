#!/bin/bash
# SessionStart hook — make a fresh Claude Code on the web container ready to edit video.
#
# Runs only in remote sessions (CLAUDE_CODE_REMOTE=true). Installs the two npm packages
# (the bundled ffmpeg/ffprobe at the root, the QA engine under tools/video-qa), exports the
# ffmpeg paths into the session environment, best-effort installs the python libs some
# skills use, and prints the setup checklist. Idempotent; the container image is cached
# after the hook completes, so re-runs are fast. Never prints a secret.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
cd "$ROOT"

echo "[session-start] installing bundled ffmpeg/ffprobe + QA engine"
npm install --no-audit --no-fund --loglevel=error
npm --prefix tools/video-qa install --no-audit --no-fund --loglevel=error

# ffmpeg/ffprobe for every script in the session (env vars + PATH shim)
if envs="$(bash scripts/ffmpeg-env.sh)"; then
  if [ -n "${CLAUDE_ENV_FILE:-}" ]; then printf '%s\n' "$envs" >> "$CLAUDE_ENV_FILE"; fi
  eval "$envs"
  echo "[session-start] ffmpeg: $("$FFMPEG" -version 2>/dev/null | head -1)"
else
  echo "[session-start] WARNING: ffmpeg could not be resolved" >&2
fi

# python helpers (PIL for overlays/markers, numpy+scipy for the audio skills) — best effort
if command -v python3 >/dev/null 2>&1; then
  python3 -m pip install --quiet --disable-pip-version-check pillow numpy scipy >/dev/null 2>&1 \
    || echo "[session-start] note: python libs not installed (pip unavailable or blocked); PIL/numpy-dependent steps will say so"
fi

# warm the HyperFrames CLI cache so the first render does not pay the download
npx --yes hyperframes --version >/dev/null 2>&1 || echo "[session-start] note: npx hyperframes not reachable yet"

# cloud sessions have no MASTER_CONTEXT.md (gitignored) — start from the template so the
# session can populate it from the team's SharePoint copy or the conversation
if [ ! -f MASTER_CONTEXT.md ] && [ -f MASTER_CONTEXT.template.md ]; then
  cp MASTER_CONTEXT.template.md MASTER_CONTEXT.md
  echo "[session-start] MASTER_CONTEXT.md created from the template — fill it from the team copy (see SETUP.md § Cloud)"
fi

bash scripts/check-setup.sh || true
