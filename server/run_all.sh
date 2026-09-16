#!/usr/bin/env bash
# Dev helper: run the website AND the Discord bot together in one terminal,
# sharing the same database. Ctrl-C stops both. For production use the systemd
# units in deploy/ instead.
set -euo pipefail
cd "$(dirname "$0")"

# Both processes share this database file (WAL mode makes that safe).
export DIVINE_DB="${DIVINE_DB:-$PWD/data/divine.db}"
# On the real box this is the domain; the IP:port below is only the dev default so
# the link codes the bot prints are clickable from a browser on this machine.
export PUBLIC_BASE_URL="${PUBLIC_BASE_URL:-http://127.0.0.1:${PORT:-10230}}"

echo "Using database: $DIVINE_DB"

# start web (gunicorn if available, else Flask dev server)
if command -v gunicorn >/dev/null 2>&1; then
  gunicorn -w 2 -b 0.0.0.0:10230 app:app &
else
  PORT="${PORT:-10230}" python app.py &
fi
WEB_PID=$!

# start bot (only if a token is set)
if [ -n "${DISCORD_BOT_TOKEN:-}" ]; then
  python bot.py &
  BOT_PID=$!
else
  echo "DISCORD_BOT_TOKEN not set - skipping the bot. Set it to run the bot too."
  BOT_PID=""
fi

trap 'echo; echo "stopping..."; kill $WEB_PID $BOT_PID 2>/dev/null || true' INT TERM
wait
