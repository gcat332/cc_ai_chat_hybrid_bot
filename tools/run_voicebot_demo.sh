#!/usr/bin/env bash
# Demo: start the voice bot and a Cloudflare quick tunnel, then print the wss:// address for Genesys.
#
#   cp voicebot.env.example voicebot.env   # fill in the keys
#   tools/run_voicebot_demo.sh
#
# Needs cloudflared (https://github.com/cloudflare/cloudflared/releases). No open ports, no
# certificate: Cloudflare provides https. The address changes every time this script starts,
# so update the Genesys integration after each restart. Ctrl+C stops both.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -f voicebot.env ]; then set -a; . ./voicebot.env; set +a; fi
: "${AUDIO_CONNECTOR_API_KEY:?Set AUDIO_CONNECTOR_API_KEY in voicebot.env}"
if [ "${FAKE_SPEECH:-}" != "1" ]; then
  : "${AZURE_SPEECH_KEY:?Set AZURE_SPEECH_KEY in voicebot.env}"
fi
command -v cloudflared >/dev/null || { echo "cloudflared is not installed (see the README)"; exit 1; }
PORT="${PORT:-8080}"
PYTHON="${PYTHON:-$( [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3 )}"
LOG="$(mktemp -d)/cloudflared.log"

export TLS_BY_PROXY=1   # the tunnel provides https/wss
extra=()
[ "${FAKE_SPEECH:-}" = "1" ] && extra+=(--fake-speech)
# ${extra[@]+...}: macOS ships bash 3.2, where an empty "${extra[@]}" fails under set -u
"$PYTHON" -m channels.audio_connector.server --host 127.0.0.1 --port "$PORT" ${extra[@]+"${extra[@]}"} &
BOT=$!
cloudflared tunnel --no-autoupdate --url "http://127.0.0.1:$PORT" >"$LOG" 2>&1 &
TUNNEL=$!
trap 'kill $BOT $TUNNEL 2>/dev/null; wait 2>/dev/null' EXIT INT TERM

URL=""
for _ in $(seq 1 60); do
  URL=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' "$LOG" | head -n1 || true)
  [ -n "$URL" ] && break
  kill -0 $TUNNEL 2>/dev/null || { echo "cloudflared stopped:"; cat "$LOG"; exit 1; }
  sleep 1
done
[ -n "$URL" ] || { echo "No tunnel address after 60 s:"; cat "$LOG"; exit 1; }

cat <<MSG

  Voice bot is reachable. In Genesys (Admin > Integrations > Audio Connector > Configuration):
    Base Connection URI:  ${URL/https:/wss:}/audiohook
    API Key:              the AUDIO_CONNECTOR_API_KEY in voicebot.env

  Health check: $URL/   (should say OK)
  Logs below. Ctrl+C stops the bot and the tunnel.

MSG
wait $BOT
