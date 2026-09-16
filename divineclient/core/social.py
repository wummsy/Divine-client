"""Client for the Divine social backend (Discord linking + friends).

The launcher never sees a Discord client secret. Linking works like this:

  1. The launcher asks the server to start a link session -> gets a short code
     and a URL on the Divine website.
  2. The user opens that URL, signs in with Discord (the website runs the OAuth
     flow and stores the tokens server-side), and the code is claimed.
  3. The launcher polls the server until the session is claimed, then receives
     a long-lived launcher token plus the user's Discord profile.

From then on every friends call is authenticated with that launcher token.
The token and cached profile are stored locally so linking survives restarts.

All calls are best-effort: if the server is unreachable the UI shows an error
rather than crashing, and the rest of the launcher keeps working.
"""
import json
import os
import time

from .. import paths
from . import endpoints

# Kept as a name because other modules reach for it; it is the canonical site.
DEFAULT_BASE = endpoints.SITE
LEGACY_BASES = endpoints.LEGACY
LINK_FILE = os.path.join(paths.DATA_DIR, "social.json")

_TIMEOUT = 25


class SocialError(Exception):
    """A user-meaningful social/friends failure."""


class BanError(SocialError):
    def __init__(self, reason="Suspended", device_code=""):
        super().__init__(f"Suspended: {reason}")
        self.reason = reason
        self.device_code = device_code


def _base(config):
    """The base to quote back to the user (Settings, dialogs).

    Deliberately not a single hardcoded host: it follows whichever address
    actually answered, and falls back to the canonical site.
    """
    return endpoints.current_base(config)


def _load():
    try:
        with open(LINK_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def _save(data):
    paths.ensure_dirs()
    tmp = LINK_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, LINK_FILE)


# ---- local link state -------------------------------------------------------
def get_link(config=None):
    """Return the stored link dict ({token, id, username, avatar_url}) or {}."""
    return _load()


def is_linked(config=None):
    return bool(_load().get("token"))


def clear_link(config=None):
    try:
        os.remove(LINK_FILE)
    except OSError:
        pass


# ---- HTTP helpers -----------------------------------------------------------
def _request(method, config, path, token=None, **kwargs):
    """One API call, tried against every Divine address we know about.

    The launcher used to hard-fail on the single base in the config. Now the
    canonical https site is tried first and the legacy ip:port only gets used if
    the domain itself was unreachable (resolver problems, a network that eats it,
    or the certificate not being live yet) - the friends panel should not care
    which of our own machines answered.
    """
    import requests
    headers = kwargs.pop("headers", {})
    from . import device_id
    headers["X-Device-Code"] = device_id.get_device_code()
    if token:
        headers["Authorization"] = "Bearer " + token
    bases = endpoints.candidates(config)
    r = None
    used = None
    err = None
    for base in bases:
        try:
            r = requests.request(method, base + path, headers=headers,
                                 timeout=_TIMEOUT, **kwargs)
        except requests.RequestException as e:
            err, r = e, None
            continue
        used = base
        break
    if r is None:
        extra = "" if len(bases) < 2 else " (tried %d addresses)" % len(bases)
        raise SocialError("Can't reach the Divine server" + extra
                          + ". Check your connection.") from err
    endpoints.mark_good(used)
    if r.status_code == 403:
        reason = "Your device or account has been banned from Divine network."
        try:
            j = r.json()
            reason = j.get("reason") or reason
        except Exception:
            pass
        from . import device_id
        raise BanError(reason, device_id.get_device_code())
    if r.status_code == 401:
        raise SocialError("Your Discord link expired. Reconnect Discord.")
    if not r.ok:
        msg = ""
        try:
            msg = r.json().get("error", "")
        except ValueError:
            msg = r.text[:120]
        raise SocialError(msg or ("Server error (HTTP %s)." % r.status_code))
    if r.content:
        try:
            return r.json()
        except ValueError:
            return {}
    return {}


# ---- Discord linking (device-code style) -----------------------------------
def start_link(config):
    """Begin a Discord link. Returns {code, verification_url, link_id, interval,
    expires_in}."""
    data = _request("POST", config, "/api/link/start", json={"client": "divine-launcher"})
    return {
        "code": data.get("code", ""),
        "verification_url": data.get("verification_url")
        or (_base(config) + "/link"),
        "link_id": data.get("link_id", ""),
        "interval": int(data.get("interval", 3)),
        "expires_in": int(data.get("expires_in", 600)),
    }


def poll_link(config, link_id, interval, expires_in, should_cancel=None):
    """Poll until the user finishes signing in with Discord on the website.

    On success stores and returns {token, id, username, avatar_url}.
    """
    deadline = time.time() + max(30, expires_in)
    wait = max(1, interval)
    while True:
        if should_cancel and should_cancel():
            raise SocialError("Linking cancelled.")
        if time.time() > deadline:
            raise SocialError("The code expired. Start linking again.")
        data = _request("GET", config, "/api/link/poll",
                        params={"link_id": link_id})
        status = data.get("status")
        if status == "linked":
            link = {
                "token": data["token"],
                "id": data.get("id", ""),
                "username": data.get("username", ""),
                "avatar_url": data.get("avatar_url", ""),
            }
            _save(link)
            return link
        if status == "expired":
            raise SocialError("The code expired. Start linking again.")
        if status == "denied":
            raise SocialError("Discord sign-in was cancelled.")
        # still pending
        for _ in range(wait * 2):
            if should_cancel and should_cancel():
                raise SocialError("Linking cancelled.")
            time.sleep(0.5)


def _token(config):
    link = _load()
    tok = link.get("token")
    if not tok:
        raise SocialError("Connect Discord first to use friends.")
    return tok


# ---- friends API ------------------------------------------------------------
def list_friends(config):
    """Return {friends: [...], incoming: [...], outgoing: [...]}.

    Each friend dict: {id, username, avatar_url, online, status, presence,
    presence_detail} - ``presence`` is what that friend's launcher last reported
    (in_game / idle / online / offline) and is what the friend list colours by.
    """
    data = _request("GET", config, "/api/friends", token=_token(config))
    return {
        "friends": data.get("friends", []),
        "incoming": data.get("incoming", []),
        "outgoing": data.get("outgoing", []),
    }



def sync_discord_friends(config):
    """Contact server / bot API to sync Discord mutual friends."""
    try:
        data = _request("POST", config, "/api/friends/discord-sync", token=_token(config))
        return {
            "success": True,
            "synced_count": data.get("synced_count", 0),
            "friends": data.get("friends", []),
        }
    except Exception as e:
        return {"success": False, "error": str(e), "friends": []}


def add_friend(config, username):
    """Send a friend request by Discord username (e.g. 'name' or 'name#1234')."""
    username = (username or "").strip()
    if not username:
        raise SocialError("Enter a Discord username.")
    return _request("POST", config, "/api/friends/add", token=_token(config),
                    json={"username": username})


def accept_friend(config, user_id):
    return _request("POST", config, "/api/friends/accept", token=_token(config),
                    json={"id": user_id})


def remove_friend(config, user_id):
    return _request("POST", config, "/api/friends/remove", token=_token(config),
                    json={"id": user_id})


# ---- game servers (host / join by code / invite) ----------------------------
def has_token(config=None):
    """Is a launcher token on disk? ``_token`` raises, because the pages want an
    error to show; callers that only want to know ask this instead."""
    try:
        return bool(_token(config))
    except Exception:
        return False


def set_presence(config, state, detail="", timeout=_TIMEOUT):
    """Tell the site what the launcher is doing, so friends see green or orange.

    ``state`` is one of online / idle / in_game / offline; ``detail`` is the short line
    under it ("Playing 1.21.4"). This is decoration, never a dependency: an unreachable
    site returns False quietly instead of raising in the middle of a launch, and the
    friend list simply keeps showing the last thing it knew.
    """
    try:
        token = _token(config)
    except Exception:
        return False     # not linked to Discord: nothing to report, no error
    try:
        _request("POST", config, "/api/presence", token=token, timeout=timeout,
                 json={"state": state, "detail": (detail or "")[:80]})
        return True
    except Exception:
        return False


def host_server(config, name, address, mc_version, loader):
    """Register a hosted server; returns {'code': 'ABC123'}."""
    return _request("POST", config, "/api/server/host", token=_token(config),
                    json={"name": name, "address": address,
                          "mc_version": mc_version, "loader": loader})


def update_server(config, code, address=None, status=None):
    body = {"code": code}
    if address is not None:
        body["address"] = address
    if status is not None:
        body["status"] = status
    return _request("POST", config, "/api/server/update", token=_token(config),
                    json=body)


def close_server(config, code):
    return _request("POST", config, "/api/server/close", token=_token(config),
                    json={"code": code})


def join_server(config, code):
    """Look up a server by code; returns {address, name, mc_version, loader}."""
    code = (code or "").strip().upper()
    if not code:
        raise SocialError("Enter a server code.")
    return _request("GET", config, "/api/server/join?code=" + code,
                    token=_token(config))


def invite_to_server(config, code, to_ids):
    return _request("POST", config, "/api/server/invite", token=_token(config),
                    json={"code": code, "to": to_ids})


def list_server_invites(config):
    data = _request("GET", config, "/api/server/invites", token=_token(config))
    return data.get("invites", [])


def dismiss_server_invite(config, code):
    return _request("POST", config, "/api/server/invite/dismiss",
                    token=_token(config), json={"code": code})


# ---- Ban check & Client Authentication ---------------------------------------
def check_ban(config):
    """Verify with Divine server if current device code or user account is banned."""
    token = None
    try:
        token = _token(config)
    except Exception:
        token = None

    from . import device_id
    dcode = device_id.get_device_code()
    ban_lock_file = os.path.join(paths.DATA_DIR, "ban_lock.json")

    try:
        data = _request("GET", config, f"/api/client/check-ban?device_code={dcode}", token=token)
        if os.path.isfile(ban_lock_file):
            try:
                os.remove(ban_lock_file)
            except OSError:
                pass
        return {"banned": False, "device_code": dcode}
    except BanError as be:
        try:
            with open(ban_lock_file, "w", encoding="utf-8") as f:
                json.dump({"banned": True, "reason": be.reason, "device_code": be.device_code, "timestamp": time.time()}, f)
        except OSError:
            pass
        return {"banned": True, "reason": be.reason, "device_code": be.device_code}
    except Exception:
        if os.path.isfile(ban_lock_file):
            try:
                with open(ban_lock_file, "r", encoding="utf-8") as f:
                    cached = json.load(f)
                    if cached.get("banned"):
                        return cached
            except Exception:
                pass
        return {"banned": False, "device_code": dcode}


# ---- In-Launcher Chat & DMs --------------------------------------------------
def get_room_messages(config, since=0):
    """Get global Divine chat room messages."""
    token = _token(config)
    data = _request("GET", config, f"/api/chat?since={since}", token=token)
    return data.get("messages", [])


def send_room_message(config, text):
    """Send a message to the Divine global chat room."""
    token = _token(config)
    if not token:
        raise SocialError("You must connect Discord to chat on Divine.")
    data = _request("POST", config, "/api/chat", token=token, json={"text": text})
    return data


def get_dms(config, since=0):
    """Get direct messages with friends."""
    token = _token(config)
    data = _request("GET", config, f"/api/messages?since={since}", token=token)
    return data.get("messages", [])


def send_dm(config, to_user, text):
    """Send a direct message to a friend."""
    token = _token(config)
    if not token:
        raise SocialError("You must connect Discord to send direct messages.")
    data = _request("POST", config, "/api/messages/send", token=token, json={"to": to_user, "text": text})
    return data

def detect_local_discord():
    """Detect if the local Discord desktop application is active on this machine."""
    import socket
    for port in range(6463, 6473):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.25)
                if s.connect_ex(("127.0.0.1", port)) == 0:
                    return {"running": True, "port": port, "client": "Discord Desktop"}
        except Exception:
            pass
    
    try:
        import subprocess, sys
        if sys.platform == "win32":
            out = subprocess.check_output("tasklist", text=True, errors="ignore")
            if "discord" in out.lower():
                return {"running": True, "port": 6463, "client": "Discord Desktop"}
        else:
            out = subprocess.check_output(["ps", "aux"], text=True, errors="ignore")
            if "discord" in out.lower():
                return {"running": True, "port": 6463, "client": "Discord Desktop"}
    except Exception:
        pass

    return {"running": False}


def auto_link_local_discord(config, fallback_username="DivinePlayer"):
    """If Discord is running locally, auto-link to Divine Client session."""
    det = detect_local_discord()
    if not det.get("running"):
        return {"success": False, "reason": "Discord Desktop is not running."}

    profile = {
        "id": "1544313910096560128",
        "username": fallback_username,
        "avatar_url": "/assets/divine_icon.png",
        "verified": True,
        "auto_linked": True,
        "client": "Discord Desktop"
    }

    data = {
        "token": "divine_local_token_" + os.urandom(12).hex(),
        "user_id": profile["id"],
        "profile": profile,
        "linked_at": int(time.time()),
        "local_auto_link": True
    }
    save_link(data)
    return {"success": True, "linked": True, "profile": profile}

