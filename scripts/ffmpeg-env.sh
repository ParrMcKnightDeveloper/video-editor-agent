#!/usr/bin/env bash
# ffmpeg-env.sh — point every script at ONE ffmpeg/ffprobe without installing anything.
#
# Resolution order (per binary): an explicit FFMPEG / FFPROBE env var → the binaries bundled
# by `npm install` at the pack root (ffmpeg-static / ffprobe-static, Linux/macOS/Windows) →
# whatever is on PATH. Prints `export …` lines, so:
#
#   eval "$(bash scripts/ffmpeg-env.sh)"        # in a shell
#   bash scripts/ffmpeg-env.sh >> "$CLAUDE_ENV_FILE"   # in the SessionStart hook
#
# It also creates <pack>/.bin/{ffmpeg,ffprobe} symlinks (gitignored) and prepends that dir to
# PATH, so scripts that call bare `ffmpeg` find the same binary as the ones reading the vars.
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

resolve() { # $1 env var, $2 name, $3 bundled path
  local v="${!1:-}"
  if [ -n "$v" ] && [ -x "$v" ]; then echo "$v"; return; fi
  if [ -x "$3" ]; then echo "$3"; return; fi
  command -v "$2" 2>/dev/null || echo ""
}

BUNDLED_FFMPEG="$ROOT/node_modules/ffmpeg-static/ffmpeg"
[ -x "$BUNDLED_FFMPEG" ] || BUNDLED_FFMPEG="$ROOT/node_modules/ffmpeg-static/ffmpeg.exe"
BUNDLED_FFPROBE=""
if [ -d "$ROOT/node_modules/ffprobe-static/bin" ]; then
  BUNDLED_FFPROBE="$(cd "$ROOT" && node -p "require('ffprobe-static').path" 2>/dev/null || true)"
fi

FFMPEG_BIN="$(resolve FFMPEG ffmpeg "$BUNDLED_FFMPEG")"
FFPROBE_BIN="$(resolve FFPROBE ffprobe "$BUNDLED_FFPROBE")"

if [ -z "$FFMPEG_BIN" ] || [ -z "$FFPROBE_BIN" ]; then
  echo "# ffmpeg-env: no ffmpeg/ffprobe found — run \`npm install\` at the pack root to fetch the bundled build" >&2
  exit 1
fi

mkdir -p "$ROOT/.bin"
ln -sfn "$FFMPEG_BIN" "$ROOT/.bin/ffmpeg"
ln -sfn "$FFPROBE_BIN" "$ROOT/.bin/ffprobe"

printf 'export FFMPEG=%q\n' "$FFMPEG_BIN"
printf 'export FFPROBE=%q\n' "$FFPROBE_BIN"
printf 'export FFMPEG_PATH=%q\n' "$FFMPEG_BIN"
printf 'export FFPROBE_PATH=%q\n' "$FFPROBE_BIN"
case ":${PATH:-}:" in *":$ROOT/.bin:"*) ;; *) printf 'export PATH=%q:"$PATH"\n' "$ROOT/.bin";; esac
