#!/usr/bin/env bash
# check-setup.sh — verify every tool/API this pack needs. Mirrors SETUP.md.
# Exit 0 = all required present. Optional items report but never fail the run.
set -u
pass=0; fail=0; warn=0
ok()   { printf "  PASS  %s\n" "$1"; pass=$((pass+1)); }
bad()  { printf "  FAIL  %s\n" "$1"; fail=$((fail+1)); }
opt()  { printf "  SKIP  %s (optional)\n" "$1"; warn=$((warn+1)); }

echo "== required =="
command -v node >/dev/null && [ "$(node -e 'console.log(process.versions.node.split(".")[0])')" -ge 20 ] \
  && ok "node $(node -v)" || bad "node >= 20 (SETUP.md #1)"
# ffmpeg/ffprobe: the npm-bundled build counts (scripts/ffmpeg-env.sh), no machine install needed
if envs="$(bash scripts/ffmpeg-env.sh 2>/dev/null)"; then eval "$envs"; fi
if [ -n "${FFMPEG:-}" ] && "$FFMPEG" -version >/dev/null 2>&1; then
  case "$FFMPEG" in *node_modules/ffmpeg-static*) ok "ffmpeg (bundled via npm install)";; *) ok "ffmpeg ($FFMPEG)";; esac
else bad "ffmpeg — run \`npm install\` at the pack root for the bundled build (SETUP.md #2)"; fi
if [ -n "${FFPROBE:-}" ] && "$FFPROBE" -version >/dev/null 2>&1; then
  case "$FFPROBE" in *node_modules/ffprobe-static*) ok "ffprobe (bundled via npm install)";; *) ok "ffprobe ($FFPROBE)";; esac
else bad "ffprobe — run \`npm install\` at the pack root for the bundled build (SETUP.md #2)"; fi
npx --yes hyperframes --version >/dev/null 2>&1 \
  && ok "hyperframes ($(npx --yes hyperframes --version 2>/dev/null | head -1))" \
  || bad "npx hyperframes (SETUP.md #3)"
# keys: the environment wins (cloud sessions inject secrets as env vars), then .env
haskey() { [ -n "${!1:-}" ] || { [ -f .env ] && grep -q "^$1=.\+" .env; }; }
haskey ELEVENLABS_API_KEY && ok "ELEVENLABS_API_KEY (env or .env)" || bad "ELEVENLABS_API_KEY — env var or .env (SETUP.md #4)"
command -v python3 >/dev/null && ok "python3 $(python3 --version 2>&1 | cut -d' ' -f2)" || bad "python3 (SETUP.md #6)"
[ -d tools/video-qa/node_modules ] && ok "video-qa engine installed" || bad "video-qa engine: npm --prefix tools/video-qa install (SETUP.md #6b)"
[ -f MASTER_CONTEXT.md ] && ok "MASTER_CONTEXT.md present" || bad "MASTER_CONTEXT.md — copy the template and fill in the projects directory (SETUP.md #0)"

echo "== optional =="
python3 -c "import PIL" 2>/dev/null && ok "PIL" || opt "PIL — vignette/overlay PNGs"
[ -f "$HOME/.herenow/credentials" ] && ok "here.now credentials" || opt "here.now — review canvas delivery (SETUP.md #7)"
PUB="${HERENOW_PUBLISH:-$HOME/.agents/skills/here-now/scripts/publish.sh}"
[ -f "$PUB" ] && ok "here-now publish.sh" || opt "here-now skill publish script (SETUP.md #7)"
if haskey AI_GATEWAY_API_KEY; then
  ok "AI_GATEWAY_API_KEY (env or .env)"
  if [ -d tools/video-qa/node_modules ]; then
    if npm --prefix tools/video-qa run -s qa:check >/dev/null 2>&1; then ok "AI Gateway models reachable (qa:check)"
    else opt "AI Gateway qa:check did not pass — run: npm --prefix tools/video-qa run qa:check (SETUP.md #8)"; fi
  fi
else opt "AI_GATEWAY_API_KEY — video-qa L3 + cloud whisper via the Vercel AI Gateway (SETUP.md #8)"; fi
"$HOME/.venvs/capcut/bin/python" -c "import pyJianYingDraft" 2>/dev/null \
  && ok "pyJianYingDraft venv" || opt "pyJianYingDraft — capcut-export (SETUP.md #11)"
command -v whisper-cli >/dev/null && ok "whisper-cli" || opt "whisper-cli — VAD cut planners + faster QA seam probes"
command -v swiftc >/dev/null && ok "swiftc" || opt "swiftc — hook-variations AVFoundation probe (SETUP.md #12)"
[ "$(git config core.hooksPath 2>/dev/null)" = ".githooks" ] && ok "scrub hook enabled" || opt "scrub hook — git config core.hooksPath .githooks (SETUP.md #13)"
node -e "require.resolve('puppeteer')" 2>/dev/null && ok "puppeteer" || opt "puppeteer — broll-capture screenshots (SETUP.md #9)"
[ -d "/Applications/Screen Studio.app" ] && ok "Screen Studio" || opt "Screen Studio — Lane C B-roll (SETUP.md #9)"
printf "  NOTE  OpenArt MCP (openart-broll) — verify in-session: openart_account_get (SETUP.md #10)\n"
haskey KIE_API_KEY && ok "KIE_API_KEY (env or .env)" || opt "KIE_API_KEY — kie-broll generated B-roll / overlays / stills (SETUP.md #10b)"
haskey MS_GRAPH_TOKEN && ok "MS_GRAPH_TOKEN (SharePoint push / org-only links)" || opt "MS_GRAPH_TOKEN — only needed to push renders to SharePoint or fetch org-only links (SETUP.md § Cloud)"
[ "${CLAUDE_CODE_REMOTE:-}" = "true" ] && printf "  NOTE  cloud session: media arrives via SharePoint/OneDrive links (video-edit-pipeline/scripts/fetch_media.py); Mac-only lanes (AVFoundation probe, Screen Studio, CapCut export) are unavailable here\n"
for legacy in GEMINI_API_KEY OPENAI_API_KEY ARCADS_API_KEY ARCADS_BASIC_AUTH; do
  haskey "$legacy" && printf "  NOTE  %s is set but no longer used — the pack routes through AI_GATEWAY_API_KEY / KIE_API_KEY now\n" "$legacy"
done

echo
echo "$pass passed, $fail required missing, $warn optional skipped"
[ "$fail" -eq 0 ] && echo "READY — required setup complete." || echo "NOT READY — fix the FAIL lines via SETUP.md."
exit "$fail"
