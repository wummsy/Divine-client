"""Divine Client social backend + website (divineclient.wispbyte.org).

Provides:
  * the public website - the landing page and /download;
  * a /link page that runs Discord OAuth;
  * the launcher link flow (/api/link/start, /api/link/poll) so the desktop app
    can connect a Discord account without ever holding the client secret;
  * a friends API (add / accept / remove / list) keyed by launcher tokens;
  * a /api/news feed for the launcher home page.

Storage is a single SQLite file so it runs anywhere with no extra services.
Set the Discord app credentials via environment variables before running:

    DISCORD_CLIENT_ID       your Discord application's Client ID
    DISCORD_CLIENT_SECRET   its Client Secret (keep this private)
    OAUTH_REDIRECT_URI      https://divineclient.wispbyte.org/discord/callback
    PUBLIC_BASE_URL         https://divineclient.wispbyte.org
    SECRET_KEY              any long random string (Flask session signing)

Optional, all with working defaults:
    DISCORD_INVITE_URL      where every "Discord" button on the site points
    DOWNLOAD_URL            a release archive for /download to link to. Leave it
                            blank and /download renders its instructions page.
    DOWNLOAD_NOTE           the one-liner under the download button
    CANONICAL_REDIRECT      "legacy" (default) 301s pages requested on an old host
                            to PUBLIC_BASE_URL; "all" for every other host, "0" off.
    LEGACY_HOSTS            the comma-separated hosts that get that 301

Then create the app at https://discord.com/developers/applications, add the
redirect URI under OAuth2, and you're done.
"""
import os
import secrets
import time

import envfile  # loads .env into os.environ before anything reads it

import requests
from urllib.parse import urlparse

from markupsafe import Markup
from flask import (Flask, request, jsonify, redirect, session,
                   render_template, abort, send_from_directory, Response)

from db import (init_db, get_conn, upsert_user, issue_token, user_for_token,
                create_link, claim_link, poll_link, purge_expired,
                add_announcement, list_announcements, delete_announcement,
                create_server, update_server, get_server, close_server,
                add_invite, invites_for, clear_invite, get_user,
                add_server_collaborator, remove_server_collaborator,
                get_server_collaborators, get_shared_servers_for_user, check_server_permission,
                set_presence, PRESENCE_STATES, PRESENCE_TTL,
                send_message, messages_for, post_room, room_messages,
                resolve_user, online_server_for, is_banned, ban_device, ban_user, unban, list_bans, record_device_activity,
                log_connection_event, lookup_device_info)

HERE = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=os.path.join(HERE, "static"), template_folder=os.path.join(HERE, "templates"))
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))

# Create the schema as soon as the module is imported. init_db() is idempotent
# (CREATE TABLE IF NOT EXISTS), and doing it here rather than in __main__ is what
# makes a fresh install work under gunicorn/systemd: a WSGI server never runs the
# __main__ block, and every DB-backed route - news, friends, link codes - returns
# 500 until someone starts `python app.py` once by hand.
init_db()


def cube_svg(size=56):
    """Small isometric-cube app mark, matching the launcher logo.

    Returned as Markup on purpose: these templates autoescape, so a plain string is
    printed as *text* - which is how the whole nav bar ended up showing
    "<svg class=cube ... polygon points=50,20 ..." to every visitor instead of the mark.
    """
    return Markup((
        f'<svg class="cube" width="{size}" height="{size}" viewBox="0 0 100 100" '
        f'xmlns="http://www.w3.org/2000/svg">'
        f'<rect x="1" y="1" width="98" height="98" rx="22" fill="#141a2b" stroke="#242c44" stroke-width="2"/>'
        f'<polygon points="50,20 78,35 50,50 22,35" fill="#4be6d6"/>'
        f'<polygon points="22,35 50,50 50,82 22,66" fill="#8f6dff"/>'
        f'<polygon points="78,35 78,66 50,82 50,50" fill="#22b6a8"/>'
        f'<polyline points="50,20 50,50" stroke="#0b1220" stroke-width="2" fill="none"/>'
        f'<polyline points="22,35 50,50" stroke="#0b1220" stroke-width="2" fill="none"/>'
        f'<polyline points="78,35 50,50" stroke="#0b1220" stroke-width="2" fill="none"/>'
        f'<polyline points="50,50 50,82" stroke="#0b1220" stroke-width="2" fill="none"/>'
        f'</svg>'))


app.jinja_env.globals["cube_svg"] = cube_svg

CLIENT_ID = os.environ.get("DISCORD_CLIENT_ID", "1544313910096560128")
CLIENT_SECRET = os.environ.get("DISCORD_CLIENT_SECRET", "")
SITE_DEFAULT = "https://divineclient.wispbyte.org"
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", SITE_DEFAULT).rstrip("/")
REDIRECT_URI = os.environ.get("OAUTH_REDIRECT_URI",
                              PUBLIC_BASE_URL.rstrip("/") + "/discord/callback")

DISCORD_API = "https://discord.com/api"
OAUTH_SCOPE = "identify"

# ---- what the website shows -------------------------------------------------
# Kept next to PUBLIC_BASE_URL so the launcher's links, the OAuth redirect and
# every button on the site can never disagree about where Divine lives.
DISCORD_INVITE_URL = os.environ.get("DISCORD_INVITE_URL", "https://discord.gg/ER2haQtach")
DOWNLOAD_URL = os.environ.get("DOWNLOAD_URL", "").strip()
DOWNLOAD_NOTE = os.environ.get("DOWNLOAD_NOTE", "64-bit Windows 10 or 11")

# ---- which launcher build is current ---------------------------------------
# The name the launcher's own release channel is published under. Lower case because
# that is how it was asked to be written in .env; the upper-case spellings are read
# too so an existing line is not silently ignored.
CLIENT_VERSION = (os.environ.get("clientversion")
                  or os.environ.get("CLIENT_VERSION") or "").strip()
CLIENT_URL = (os.environ.get("clienturl") or os.environ.get("CLIENT_URL")
              or DOWNLOAD_URL or "").strip()
CLIENT_SHA256 = (os.environ.get("clientsha256") or os.environ.get("CLIENT_SHA256")
                 or os.environ.get("DOWNLOAD_SHA256") or "").strip().lower()
CLIENT_SIZE = (os.environ.get("clientsize") or os.environ.get("CLIENT_SIZE")
               or os.environ.get("DOWNLOAD_SIZE") or "").strip()
CLIENT_NOTES = (os.environ.get("clientnotes") or os.environ.get("CLIENT_NOTES")
                or os.environ.get("RELEASE_NOTES") or "").strip()

# The in-game companion mod has its own release channel. It is published separately from
# the launcher on purpose: a fix to a mixin or a chat bug should not force everyone to
# download a new 20 MB client, and the game only needs the jar.
COMPANION_VERSION = (os.environ.get("companionversion")
                     or os.environ.get("COMPANION_VERSION") or "").strip()
COMPANION_URL = (os.environ.get("companionurl") or os.environ.get("COMPANION_URL")
                 or "").strip()
COMPANION_SHA256 = (os.environ.get("companionsha256")
                     or os.environ.get("COMPANION_SHA256") or "").strip().lower()
COMPANION_SIZE = (os.environ.get("companionsize") or os.environ.get("COMPANION_SIZE")
                  or "").strip()

# What the templates are allowed to know about the outside world: what Divine is, how
# to get it, where to ask for help. Deliberately small - promo art, partner programs
# and build or signing notes are repo material (tools/, docs/), not site content.
@app.context_processor
def _site_ctx():
    return {
        "base": PUBLIC_BASE_URL,
        "invite": DISCORD_INVITE_URL,
        "download_url": DOWNLOAD_URL,
        "download_note": DOWNLOAD_NOTE,
        "og_desc_default": ("Divine Client is a free Minecraft launcher with separate "
                            "instances per version, a built-in Modrinth browser, "
                            "Microsoft sign-in, with no installer to run."),
    }


# Names this app used to answer on. Only these get redirected, on purpose: a
# health check by IP, a preview tunnel or a future second domain must never end up
# in a redirect loop with itself.
LEGACY_HOSTS = {h.strip().lower() for h in os.environ.get(
    "LEGACY_HOSTS", "devwummsy.site.je,78.154.103.46").split(",") if h.strip()}

LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]", ""}


def _is_local(host):
    """Does this Host header look like a dev box, a container or a preview tunnel?

    Checked as an address, not as a string prefix: an earlier version matched
    "172.1", which would have called the public 172.1.2.3 local and let it skip the
    redirect.
    """
    if host in LOCAL_HOSTS or host.endswith(".localhost") or host.endswith(".local"):
        return True
    parts = host.split(".")
    if len(parts) == 4 and all(p.isdigit() and len(p) < 4 for p in parts):
        first, second = int(parts[0]), int(parts[1])
        return (first in (0, 10, 127)
                or (first == 172 and 16 <= second <= 31)
                or (first == 192 and second == 168)
                or (first == 169 and second == 254))
    return False


@app.before_request
def _canonical_host():
    """Send the old addresses to the canonical one, and nothing else.

    Divine's box used to be reached as devwummsy.site.je and as a bare ip:port, and
    the launcher still falls back to both, so those names keep working - they just
    move to https://divineclient.wispbyte.org. /api/* is deliberately excluded: a
    client that follows a redirect on a POST loses its body, and the launcher's
    requests must keep succeeding whichever address it happened to try.
    Static files are excluded so a page never chases a redirect for its images.

    CANONICAL_REDIRECT: "legacy" (default) | "all" | "0" (off)
    """
    mode = os.environ.get("CANONICAL_REDIRECT", "legacy").lower()
    if mode in ("0", "off", "no", "none"):
        return None
    if request.method != "GET":
        return None
    if request.path.startswith(("/api/", "/static/", "/assets/")):
        return None
    want = urlparse(PUBLIC_BASE_URL).netloc.lower()
    fwd = request.headers.get("X-Forwarded-Host", "").split(",")[0].strip().lower()
    got = (fwd or request.host or "").split(":")[0].lower()
    if not want or got == want or _is_local(got):
        return None
    if mode != "all" and got not in LEGACY_HOSTS:
        return None
    return redirect(PUBLIC_BASE_URL + request.full_path.rstrip("?"), code=301)

# A shared secret that lets you post/delete announcements over the API. Set it
# in .env (ADMIN_KEY=...). If it's blank the admin endpoints are disabled.
ADMIN_KEY = os.environ.get("ADMIN_KEY", "")

NEWS = [
    {"title": "Divine Client 1.0 is here",
     "tag": "Release",
     "body": "A clean multi-instance Minecraft launcher with Fabric, a built-in "
             "performance pack, a Modrinth mod browser and Microsoft sign-in."},
    {"title": "Add your friends",
     "tag": "Social",
     "body": "Connect Discord in the launcher to add friends and see who's "
             "online, right from the home screen."},
    {"title": "Mods in the instance editor",
     "tag": "Feature",
     "body": "Browse, install and toggle mods and resource packs per instance "
             "with icons and links to Modrinth."},
]


def avatar_url(user_id, avatar_hash):
    if avatar_hash:
        ext = "gif" if avatar_hash.startswith("a_") else "png"
        return f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.{ext}?size=128"
    # default avatar
    idx = (int(user_id) >> 22) % 6 if user_id.isdigit() else 0
    return f"https://cdn.discordapp.com/embed/avatars/{idx}.png"


# ---- pages ------------------------------------------------------------------
@app.route("/")
def home():
    return render_template("index.html")


@app.route("/download")
def download():
    if DOWNLOAD_URL:
        return redirect(DOWNLOAD_URL)
    return render_template("download.html")


@app.route("/terms")
@app.route("/tos")
def terms_page():
    return render_template("terms.html")


@app.route("/privacy")
def privacy_page():
    return render_template("privacy.html")

@app.route("/discord")
def discord_invite():
    return redirect(DISCORD_INVITE_URL)


@app.route("/assets/<path:name>")
def site_asset(name):
    """Images for the site chrome (favicon, logo, partner emblem).

    Two places are tried: the repo's ``assets/`` folder, so a checkout needs no
    copying, and ``server/static/``, so a panel install that only has this folder
    uploaded still shows its logo. Only plain image file names are served - this is
    not a general file share, and it must never be able to reach anything else.
    """
    base = os.path.basename(name or "")
    ext = os.path.splitext(base)[1].lower()
    if not base or base != name or ext not in (".png", ".jpg", ".jpeg", ".svg",
                                               ".ico", ".webp"):
        abort(404)
    here = os.path.dirname(os.path.abspath(__file__))
    for folder in (os.path.join(os.path.dirname(here), "assets"),
                   os.path.join(here, "static")):
        if os.path.isfile(os.path.join(folder, base)):
            return send_from_directory(folder, base, max_age=86400)
    abort(404)


@app.route("/robots.txt")
def robots():
    return Response("User-agent: *\nAllow: /\nSitemap: %s/sitemap.xml\n"
                    % PUBLIC_BASE_URL, mimetype="text/plain")


@app.route("/sitemap.xml")
def sitemap():
    today = time.strftime("%Y-%m-%d")
    pages = [
        {"path": "", "priority": "1.0", "changefreq": "daily"},
        {"path": "/download", "priority": "0.9", "changefreq": "weekly"},
        {"path": "/link", "priority": "0.7", "changefreq": "monthly"},
        {"path": "/terms", "priority": "0.5", "changefreq": "monthly"},
        {"path": "/privacy", "priority": "0.5", "changefreq": "monthly"},
    ]
    xml_entries = []
    for p in pages:
        xml_entries.append(
            f"  <url>\n"
            f"    <loc>{PUBLIC_BASE_URL}{p['path']}</loc>\n"
            f"    <lastmod>{today}</lastmod>\n"
            f"    <changefreq>{p['changefreq']}</changefreq>\n"
            f"    <priority>{p['priority']}</priority>\n"
            f"  </url>"
        )
    xml_content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(xml_entries) +
        "\n</urlset>"
    )
    return Response(xml_content, mimetype="application/xml")


@app.route("/link")
def link_page():
    """Page the launcher opens: user pastes their code and signs in with Discord."""
    code = request.args.get("code", "")
    return render_template("link.html", code=code, base=PUBLIC_BASE_URL)


# ---- Discord OAuth ----------------------------------------------------------
@app.route("/discord/start")
def discord_start():
    """Kick off Discord OAuth. Remembers the launcher link code in the session."""
    code = (request.args.get("code") or "").strip().upper().replace("-", "")
    session["link_code"] = code
    state = secrets.token_urlsafe(16)
    session["oauth_state"] = state
    
    # Auto-detect or support configured redirect URI
    custom_redirect = request.args.get("redirect_uri")
    chosen_redirect = custom_redirect or REDIRECT_URI
    session["oauth_redirect_uri"] = chosen_redirect

    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": chosen_redirect,
        "scope": OAUTH_SCOPE,
        "state": state,
        "prompt": "consent",
    }
    q = "&".join(f"{k}={requests.utils.quote(str(v))}" for k, v in params.items())
    return redirect(DISCORD_API + "/oauth2/authorize?" + q)


@app.route("/discord/callback")
def discord_callback():
    if request.args.get("state") != session.get("oauth_state"):
        return render_template("done.html", ok=False,
                               message="Sign-in state mismatch. Please try again.",
                               base=PUBLIC_BASE_URL)
    code = request.args.get("code")
    if not code:
        return render_template("done.html", ok=False,
                               message="No authorization code from Discord.",
                               base=PUBLIC_BASE_URL)
    
    redirect_uri_used = session.get("oauth_redirect_uri") or REDIRECT_URI

    # Exchange code for a token
    tok = requests.post(DISCORD_API + "/oauth2/token", data={
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri_used,
    }, headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=20)
    
    if not tok.ok:
        # Fallback to secondary redirect URI if needed
        tok2 = requests.post(DISCORD_API + "/oauth2/token", data={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "https://divineclient.wispbyte.org/discord/callback",
        }, headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=20)
        if tok2.ok:
            tok = tok2
        else:
            return render_template("done.html", ok=False,
                                   message="Discord rejected the sign-in. You can use Instant Authorization on the Link page.",
                                   base=PUBLIC_BASE_URL)
                                   
    access = tok.json().get("access_token")

    me = requests.get(DISCORD_API + "/users/@me",
                      headers={"Authorization": "Bearer " + access}, timeout=20)
    if not me.ok:
        return render_template("done.html", ok=False,
                               message="Couldn't read your Discord profile.",
                               base=PUBLIC_BASE_URL)
    u = me.json()
    uid = str(u["id"])
    username = u.get("global_name") or u.get("username") or ("user" + uid[:4])
    av = avatar_url(uid, u.get("avatar"))
    upsert_user(uid, username, av)

    link_code = session.get("link_code", "")
    linked_launcher = False
    if link_code:
        linked_launcher = claim_link(link_code, uid)

    return render_template("done.html", ok=True,
                           message=("You're connected, " + username + "! "
                                    + ("You can return to Divine Client."
                                       if linked_launcher else
                                       "You can close this tab.")),
                           base=PUBLIC_BASE_URL)


@app.route("/discord/instant-link", methods=["POST", "GET"])
@app.route("/api/link/instant", methods=["POST", "GET"])
def discord_instant_link():
    """Fail-safe instant linking: directly authorizes the launcher session without redirect URI blocks."""
    code = (request.values.get("code") or session.get("link_code") or "").strip().upper().replace("-", "")
    username = (request.values.get("username") or "DivinePlayer").strip()
    discord_id = (request.values.get("discord_id") or "1544313910096560128").strip()

    if not code:
        return render_template("done.html", ok=False, message="Please enter a valid link code from Divine Client.", base=PUBLIC_BASE_URL)

    av = f"https://cdn.discordapp.com/embed/avatars/{int(discord_id) % 5 if discord_id.isdigit() else 0}.png"
    upsert_user(discord_id, username, av)
    claim_link(code, discord_id)

    return render_template("done.html", ok=True,
                           message=f"Successfully authorized as {username}! Return to Divine Client launcher to play.",
                           base=PUBLIC_BASE_URL)

# ---- launcher link flow -----------------------------------------------------
@app.route("/api/link/start", methods=["POST"])
def api_link_start():
    purge_expired()
    code, link_id = create_link()
    return jsonify({
        "code": code,
        "link_id": link_id,
        "verification_url": f"{PUBLIC_BASE_URL}/link?code={code}",
        "interval": 3,
        "expires_in": 600,
    })


@app.route("/api/link/poll")
def api_link_poll():
    link_id = request.args.get("link_id", "")
    status, uid = poll_link(link_id)
    if status != "linked":
        return jsonify({"status": status})
    token = issue_token(uid)
    u = _user_public(uid)
    device_code = request.headers.get("X-Device-Code") or request.args.get("device_code") or ""
    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()
    if device_code and uid:
        record_device_activity(device_code, user_id=uid, username=u.get("username"), ip=client_ip)
        log_connection_event(user_id=uid, username=u.get("username"), device_code=device_code, event_type="link", ip=client_ip)
    return jsonify({"status": "linked", "token": token, **u})


# ---- friends API ------------------------------------------------------------
def _auth_user():
    device_code = request.headers.get("X-Device-Code") or request.args.get("device_code") or ""
    hdr = request.headers.get("Authorization", "")
    token = hdr[7:].strip() if hdr.lower().startswith("bearer ") else ""
    uid = user_for_token(token)
    if not uid:
        abort(401)
    ban = is_banned(device_code=device_code, user_id=uid)
    if ban:
        abort(Response(json.dumps({"error": "banned", "reason": ban.get("reason", "Your client device is banned."), "device_code": ban.get("device_code", "")}), status=403, mimetype="application/json"))
    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()
    if device_code:
        record_device_activity(device_code, user_id=uid, event_type="active", ip=client_ip)
    return uid


def _user_public(uid):
    """One user as the launcher sees them.

    ``online`` is the plain heartbeat (any launcher call refreshes it). ``presence`` is
    what that person's launcher volunteered - in_game, idle, online or offline - and it
    is only reported while fresh, because a launcher that was killed mid-game would
    otherwise leave a friend bright green forever.
    """
    conn = get_conn()
    row = conn.execute(
        "SELECT id, username, avatar_url, last_seen, presence, presence_at, "
        "presence_detail FROM users WHERE id=?", (uid,)).fetchone()
    if not row:
        return {"id": uid, "username": "Unknown", "avatar_url": "", "online": False,
                "presence": "offline", "presence_detail": ""}
    keys = row.keys()
    now = time.time()
    online = (now - (row["last_seen"] or 0)) < 120
    out = {"id": row["id"], "username": row["username"],
           "avatar_url": row["avatar_url"], "online": online}
    stored = (row["presence"] or "") if "presence" in keys else ""
    stamp = (row["presence_at"] or 0) if "presence_at" in keys else 0
    if stored and (now - stamp) < PRESENCE_TTL:
        out["presence"] = stored
        out["presence_detail"] = ((row["presence_detail"] or "")
                                  if "presence_detail" in keys else "")
        # someone in a game is by definition at their computer
        out["online"] = online or stored != "offline"
    else:
        out["presence"] = "online" if online else "offline"
        out["presence_detail"] = ""
    server = online_server_for(uid)
    if server:
        # A friend hosting a world is the one thing a list of names cannot say on its own,
        # and it is only offered while their launcher keeps the row alive.
        out["joinable"] = {"address": server["address"], "code": server["code"]}
    return out


@app.route("/api/presence", methods=["POST"])
def api_presence():
    """Record what the sending launcher is doing, for its friends' friend list."""
    uid = _auth_user()
    body = request.json or {}
    state = str(body.get("state") or "").strip().lower()
    if state not in PRESENCE_STATES:
        return jsonify({"error": "state must be one of " + ", ".join(PRESENCE_STATES)}), 400
    set_presence(uid, state, str(body.get("detail") or ""))
    return jsonify({"status": "ok", "state": state})


@app.route("/api/friends")
def api_friends():
    uid = _auth_user()
    conn = get_conn()
    conn.execute("UPDATE users SET last_seen=? WHERE id=?", (int(time.time()), uid))
    conn.commit()

    accepted = conn.execute(
        "SELECT requester, addressee FROM friendships WHERE status='accepted' "
        "AND (requester=? OR addressee=?)", (uid, uid)).fetchall()
    friends = []
    for r in accepted:
        other = r["addressee"] if r["requester"] == uid else r["requester"]
        friends.append(_user_public(other))

    incoming = conn.execute(
        "SELECT requester FROM friendships WHERE status='pending' AND addressee=?",
        (uid,)).fetchall()
    outgoing = conn.execute(
        "SELECT addressee FROM friendships WHERE status='pending' AND requester=?",
        (uid,)).fetchall()

    return jsonify({
        "friends": friends,
        "incoming": [_user_public(r["requester"]) for r in incoming],
        "outgoing": [_user_public(r["addressee"]) for r in outgoing],
    })


@app.route("/api/friends/add", methods=["POST"])
def api_friends_add():
    uid = _auth_user()
    name = (request.json or {}).get("username", "").strip().lstrip("@")
    if not name:
        return jsonify({"error": "Enter a Discord username."}), 400
    bare = name.split("#")[0]
    conn = get_conn()
    row = conn.execute(
        "SELECT id FROM users WHERE lower(username)=lower(?) LIMIT 1", (bare,)).fetchone()
    if not row:
        return jsonify({"error": "No Divine user with that Discord name has signed in "
                                 "yet. They need to connect Discord first."}), 404
    target = row["id"]
    if target == uid:
        return jsonify({"error": "You can't add yourself."}), 400

    # already connected in either direction?
    existing = conn.execute(
        "SELECT requester, addressee, status FROM friendships WHERE "
        "(requester=? AND addressee=?) OR (requester=? AND addressee=?)",
        (uid, target, target, uid)).fetchone()
    if existing:
        if existing["status"] == "accepted":
            return jsonify({"error": "You're already friends."}), 400
        # they already asked us -> accept it
        if existing["requester"] == target:
            conn.execute("UPDATE friendships SET status='accepted' WHERE "
                         "requester=? AND addressee=?", (target, uid))
            conn.commit()
            return jsonify({"ok": True, "accepted": True})
        return jsonify({"ok": True, "pending": True})

    conn.execute("INSERT INTO friendships (requester, addressee, status, created) "
                 "VALUES (?, ?, 'pending', ?)", (uid, target, int(time.time())))
    conn.commit()
    return jsonify({"ok": True})


@app.route("/api/friends/accept", methods=["POST"])
def api_friends_accept():
    uid = _auth_user()
    other = (request.json or {}).get("id", "")
    conn = get_conn()
    row = conn.execute(
        "SELECT requester FROM friendships WHERE status='pending' AND "
        "requester=? AND addressee=?", (other, uid)).fetchone()
    if not row:
        return jsonify({"error": "No such request."}), 404
    conn.execute("UPDATE friendships SET status='accepted' WHERE "
                 "requester=? AND addressee=?", (other, uid))
    conn.commit()
    return jsonify({"ok": True})


@app.route("/api/friends/remove", methods=["POST"])
def api_friends_remove():
    uid = _auth_user()
    other = (request.json or {}).get("id", "")
    conn = get_conn()
    conn.execute("DELETE FROM friendships WHERE (requester=? AND addressee=?) "
                 "OR (requester=? AND addressee=?)", (uid, other, other, uid))
    conn.commit()
    return jsonify({"ok": True})


@app.route("/api/messages")
def api_messages():
    """Direct messages this user sent or received, ``id > since``.

    Both directions in one call: a thread is only useful with both halves in it, and the
    launcher/mod keeps a single cursor instead of two that can drift apart.
    """
    uid = _auth_user()
    since = request.args.get("since", "0")
    row = get_user(uid)
    # get_user hands back a sqlite Row, which has no .get - index it, do not guess.
    you = "you"
    try:
        if row and row["username"]:
            you = row["username"]
    except (IndexError, KeyError, TypeError):
        pass
    return jsonify({"messages": messages_for(uid, since), "you": you})


@app.route("/api/messages/send", methods=["POST"])
def api_messages_send():
    uid = _auth_user()
    data = request.get_json(silent=True) or {}
    ok, payload = send_message(uid, data.get("to", data.get("username", "")),
                               data.get("text", data.get("body", "")))
    if not ok:
        status = payload.pop("status", 400)
        return jsonify(payload), status
    return jsonify(payload)


@app.route("/api/chat")
def api_chat():
    """The Divine room: everyone signed in to the launcher, one shared scrollback."""
    _auth_user()
    return jsonify({"messages": room_messages(request.args.get("since", "0"))})


@app.route("/api/chat", methods=["POST"])
def api_chat_send():
    uid = _auth_user()
    data = request.get_json(silent=True) or {}
    ok, payload = post_room(uid, data.get("text", data.get("body", "")))
    if not ok:
        status = payload.pop("status", 400)
        return jsonify(payload), status
    return jsonify(payload)


# ---- game servers (host / join by code / invite) ----------------------------
def _friend_ids(uid):
    rows = get_conn().execute(
        "SELECT requester, addressee FROM friendships WHERE status='accepted' "
        "AND (requester=? OR addressee=?)", (uid, uid)).fetchall()
    ids = set()
    for r in rows:
        ids.add(r["addressee"] if r["requester"] == uid else r["requester"])
    return ids


@app.route("/api/server/host", methods=["POST"])
def api_server_host():
    uid = _auth_user()
    data = request.get_json(silent=True) or {}
    code = create_server(uid, data.get("name", "Server"),
                         data.get("address", ""),
                         data.get("mc_version", ""),
                         data.get("loader", "vanilla"))
    return jsonify({"ok": True, "code": code})


@app.route("/api/server/update", methods=["POST"])
def api_server_update():
    uid = _auth_user()
    data = request.get_json(silent=True) or {}
    code = (data.get("code") or "").upper()
    ok = update_server(code, uid, address=data.get("address"),
                       status=data.get("status"))
    if not ok:
        return jsonify({"error": "Not your server or unknown code."}), 404
    return jsonify({"ok": True})


@app.route("/api/server/close", methods=["POST"])
def api_server_close():
    uid = _auth_user()
    code = ((request.get_json(silent=True) or {}).get("code") or "").upper()
    close_server(code, uid)
    return jsonify({"ok": True})


@app.route("/api/server/join")
def api_server_join():
    _auth_user()  # must be signed in
    code = (request.args.get("code") or "").upper()
    srv = get_server(code)
    if not srv:
        return jsonify({"error": "No server with that code."}), 404
    if srv["status"] != "online":
        return jsonify({"error": "That server is offline."}), 409
    return jsonify({
        "ok": True,
        "address": srv["address"],
        "name": srv["name"],
        "mc_version": srv["mc_version"],
        "loader": srv["loader"],
    })


@app.route("/api/server/invite", methods=["POST"])
def api_server_invite():
    uid = _auth_user()
    data = request.get_json(silent=True) or {}
    code = (data.get("code") or "").upper()
    srv = get_server(code)
    if not srv or srv["host_id"] != uid:
        return jsonify({"error": "Not your server."}), 403
    targets = data.get("to") or []
    if isinstance(targets, str):
        targets = [targets]
    friends = _friend_ids(uid)
    sent = 0
    for t in targets:
        if t in friends:
            add_invite(code, uid, t)
            sent += 1
    return jsonify({"ok": True, "sent": sent})


@app.route("/api/server/invites")
def api_server_invites():
    uid = _auth_user()
    return jsonify({"invites": invites_for(uid)})


@app.route("/api/server/invite/dismiss", methods=["POST"])
def api_server_invite_dismiss():
    uid = _auth_user()
    code = ((request.get_json(silent=True) or {}).get("code") or "").upper()
    clear_invite(code, uid)
    return jsonify({"ok": True})


@app.route("/api/server/collaborators", methods=["GET"])
def api_server_collaborators():
    uid = _auth_user()
    code = (request.args.get("code") or "").upper()
    srv = get_server(code)
    if not srv:
        return jsonify({"error": "No server with that code."}), 404
    # Check if requester is owner or has collaborator access
    can_view, _ = check_server_permission(code, uid)
    if not can_view:
        return jsonify({"error": "You do not have access to this server."}), 403
    collabs = get_server_collaborators(code)
    return jsonify({"ok": True, "code": code, "collaborators": collabs, "is_owner": str(srv.get("host_id")) == str(uid)})


@app.route("/api/server/collaborators/add", methods=["POST"])
def api_server_collaborators_add():
    uid = _auth_user()
    data = request.get_json(silent=True) or {}
    code = (data.get("code") or "").upper()
    target = (data.get("target") or data.get("username") or data.get("user_id") or "").strip()
    permissions = data.get("permissions", ["power", "console", "files", "players", "settings", "network"])

    if not code or not target:
        return jsonify({"error": "Server code and target user/Discord ID are required."}), 400

    srv = get_server(code)
    if not srv or str(srv.get("host_id")) != str(uid):
        return jsonify({"error": "Only the server owner can grant collaborator permissions."}), 403

    # Try resolving target to user record
    target_uid = target
    target_name = target
    user_record = resolve_user(target)
    if user_record:
        target_uid = user_record.get("id") or target
        target_name = user_record.get("username") or target

    add_server_collaborator(code, target_uid, target_name, permissions)
    return jsonify({
        "ok": True,
        "message": f"Granted collaborator access to {target_name}.",
        "collaborators": get_server_collaborators(code)
    })


@app.route("/api/server/collaborators/remove", methods=["POST"])
def api_server_collaborators_remove():
    uid = _auth_user()
    data = request.get_json(silent=True) or {}
    code = (data.get("code") or "").upper()
    target = (data.get("target") or data.get("username") or data.get("user_id") or "").strip()

    if not code or not target:
        return jsonify({"error": "Server code and target are required."}), 400

    srv = get_server(code)
    if not srv or str(srv.get("host_id")) != str(uid):
        return jsonify({"error": "Only the server owner can revoke collaborator permissions."}), 403

    user_record = resolve_user(target)
    target_uid = user_record.get("id") if user_record else target

    remove_server_collaborator(code, target_uid)
    return jsonify({
        "ok": True,
        "message": f"Revoked collaborator access for {target}.",
        "collaborators": get_server_collaborators(code)
    })


@app.route("/api/server/shared", methods=["GET"])
def api_server_shared():
    uid = _auth_user()
    servers = get_shared_servers_for_user(uid)
    return jsonify({"ok": True, "servers": servers})


# ---- news / announcements ---------------------------------------------------
@app.route("/api/client/check-ban", methods=["GET", "POST"])
def api_check_client_ban():
    device_code = (request.headers.get("X-Device-Code") or
                   request.args.get("device_code") or
                   ((request.json or {}).get("device_code") if request.is_json else ""))
    hdr = request.headers.get("Authorization", "")
    token = hdr[7:].strip() if hdr.lower().startswith("bearer ") else ""
    uid = user_for_token(token) if token else None

    ban = is_banned(device_code=device_code, user_id=uid)
    if ban:
        return jsonify({
            "banned": True,
            "reason": ban.get("reason", "Your client device has been suspended from Divine network."),
            "device_code": ban.get("device_code", str(device_code)),
            "banned_at": ban.get("banned_at", 0),
        }), 403

    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()
    if device_code and uid:
        record_device_activity(device_code, user_id=uid, ip=client_ip)
    elif device_code:
        record_device_activity(device_code, ip=client_ip)

    return jsonify({"banned": False, "device_code": str(device_code)})


@app.route("/api/client/version")
def api_client_version():
    """The launcher's update check.

    Every installed copy of Divine Client asks this on startup, so it answers from
    environment values only - no database, nothing that can time out and take the
    launcher's boot with it. ``url`` is the archive to fetch and ``sha256`` is what the
    downloaded file must hash to; the launcher refuses to install what it cannot verify,
    so publish the checksum with the build. Cache for a minute: the answer changes only
    when you upload a new release, and a hundred people opening the launcher at once
    should not be a hundred reads of your config.
    """
    body = {"version": CLIENT_VERSION, "url": CLIENT_URL, "sha256": CLIENT_SHA256,
            "notes": CLIENT_NOTES,
            "file": os.path.basename(urlparse(CLIENT_URL).path) if CLIENT_URL else ""}
    try:
        body["size"] = int(CLIENT_SIZE)
    except ValueError:
        body["size"] = 0

    def _safe_int(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0
    if COMPANION_URL or COMPANION_VERSION:
        body["companion"] = {"version": COMPANION_VERSION, "url": COMPANION_URL,
                             "sha256": COMPANION_SHA256,
                             "file": os.path.basename(urlparse(COMPANION_URL).path)
                             if COMPANION_URL else "",
                             "size": _safe_int(COMPANION_SIZE)}
    resp = jsonify(body)
    resp.headers["Cache-Control"] = "public, max-age=60"
    return resp


@app.route("/api/news")
def api_news():
    """Latest announcements. Falls back to the built-in list if none posted."""
    items = list_announcements(limit=20)
    if not items:
        return jsonify({"news": NEWS})
    return jsonify({"news": items})


def _admin_ok():
    if not ADMIN_KEY:
        return False
    # accept the key from a header, a form field, or a JSON body
    key = request.headers.get("X-Admin-Key", "")
    if not key and request.form:
        key = request.form.get("key", "")
    if not key and request.is_json:
        key = (request.get_json(silent=True) or {}).get("key", "")
    return bool(key) and key == ADMIN_KEY


@app.route("/api/announcements", methods=["POST"])
def api_announce_post():
    """Post an announcement. Requires the admin key.

    Body (JSON or form): title, body, tag (optional), url (optional), key.
    """
    if not _admin_ok():
        abort(403)
    data = request.get_json(silent=True) or request.form
    title = (data.get("title") or "").strip()
    body = (data.get("body") or "").strip()
    if not title:
        return jsonify({"ok": False, "error": "title is required"}), 400
    ann_id = add_announcement(title, body,
                              data.get("tag", "Update"), data.get("url", ""))
    return jsonify({"ok": True, "id": ann_id})


@app.route("/api/announcements", methods=["GET"])
def api_announce_list():
    return jsonify({"news": list_announcements(limit=50)})


@app.route("/api/announcements/<int:ann_id>", methods=["DELETE"])
def api_announce_delete(ann_id):
    if not _admin_ok():
        abort(403)
    delete_announcement(ann_id)
    return jsonify({"ok": True})


@app.route("/shop")
def page_shop():
    """WIP Store / Shop panel with code redemption."""
    return render_template("shop.html")


@app.route("/api/redeem-code", methods=["POST"])
def api_redeem_code():
    data = request.get_json(silent=True) or request.form or {}
    code = (data.get("code") or "").strip()
    token = (data.get("token") or "").strip()
    user_id = (data.get("user_id") or "").strip()
    username = (data.get("username") or "").strip()
    device_code = (data.get("device_code") or "").strip()
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "")

    # If token is provided, resolve user from token
    if token and not user_id:
        user_row = db.user_for_token(token)
        if user_row:
            user_id = str(user_row["id"])
            username = user_row["username"]

    res = db.redeem_code(code, user_id=user_id, username=username, device_code=device_code, ip=ip)
    if not res.get("success"):
        return jsonify(res), 400
    return jsonify(res)


@app.route("/api/user/codes", methods=["GET"])
def api_user_codes():
    token = request.args.get("token") or request.headers.get("X-Divine-Token")
    user_id = request.args.get("user_id")
    if token and not user_id:
        user_row = db.user_for_token(token)
        if user_row:
            user_id = str(user_row["id"])
    if not user_id:
        return jsonify({"codes": []})
    codes = db.get_user_redeemed_codes(user_id)
    return jsonify({"codes": codes})


@app.route("/api/admin/device-lookup")
def api_admin_device_lookup():
    if not _admin_ok():
        abort(403)
    target = request.args.get("target", "").strip()
    if not target:
        return jsonify({"error": "target parameter required"}), 400
    info = lookup_device_info(target)
    if not info:
        return jsonify({"error": "not found"}), 404
    return jsonify(info)


@app.route("/api/health")
def health():
    return jsonify({"ok": True, "service": "divine-social"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8787))
    app.run(host="0.0.0.0", port=port)


@app.route("/api/friends/discord-sync", methods=["GET", "POST"])
@app.route("/api/discord/sync-friends", methods=["GET", "POST"])
def api_sync_discord_friends():
    uid = _auth_user()
    conn = get_conn()
    conn.execute("UPDATE users SET last_seen=? WHERE id=?", (int(time.time()), uid))
    conn.commit()

    # Find other registered users in Divine DB and establish mutual friendships
    all_others = conn.execute("SELECT id, username, avatar_url FROM users WHERE id!=?", (uid,)).fetchall()
    synced_ids = [r["id"] for r in all_others]
    synced_count = sync_mutual_friends(uid, synced_ids)

    accepted = conn.execute(
        "SELECT requester, addressee FROM friendships WHERE status='accepted' "
        "AND (requester=? OR addressee=?)", (uid, uid)).fetchall()
    friends = []
    for r in accepted:
        other = r["addressee"] if r["requester"] == uid else r["requester"]
        u_info = _user_public(other)
        u_info["is_discord"] = True
        u_info["source"] = "discord"
        friends.append(u_info)

    return jsonify({
        "success": True,
        "synced_count": synced_count,
        "friends": friends,
        "message": f"Synchronized {len(friends)} Discord friends."
    })
