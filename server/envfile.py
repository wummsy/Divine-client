"""Load a .env file into the environment.

Small and dependency-free so it works on any host. Import this at the very top
of app.py and bot.py (before reading os.environ). It reads a file named .env
sitting next to these Python files and sets any variables that are not already
defined in the real environment - so panel/systemd variables still win over the
file if both are set.

.env format (one KEY=VALUE per line):

    DISCORD_CLIENT_ID=1544313910096560128
    DISCORD_CLIENT_SECRET=your_oauth_secret
    DISCORD_BOT_TOKEN=your_bot_token
    SECRET_KEY=some_long_random_string
    PUBLIC_BASE_URL=https://divineclient.wispbyte.org
    OAUTH_REDIRECT_URI=https://divineclient.wispbyte.org/discord/callback
    DIVINE_DB=divine.db
    PORT=10230

Lines starting with # are comments. Surrounding single or double quotes around a
value are stripped. Blank lines are ignored.
"""
import os


def load(path=None):
    if path is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.lower().startswith("export "):
                line = line[7:].strip()
            if "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
                val = val[1:-1]
            if key and key not in os.environ:
                os.environ[key] = val


load()
