"""Account management for Divine Client.

Supports two kinds of accounts:
  * offline  - just a username, for singleplayer / offline-mode servers.
  * microsoft - real premium auth using the device/redirect OAuth flow provided
                by minecraft-launcher-lib. Tokens are cached and refreshed.
"""
import json
import os
import shutil
import uuid

from .. import paths

# Public "AzureAD" style client id used by open-source launchers for the
# Microsoft OAuth flow. Users can override this via env if they register their own.
CLIENT_ID = os.environ.get("DIVINE_CLIENT_ID", "00000000402b5328")  # Minecraft's own public id
REDIRECT_URI = "https://login.microsoftonline.com/common/oauth2/nativeclient"


def _offline_uuid(username: str) -> str:
    """Deterministic offline UUID (matches the vanilla 'OfflinePlayer:' scheme)."""
    return str(uuid.uuid3(uuid.NAMESPACE_DNS, "OfflinePlayer:" + username))


class AccountStore:
    def __init__(self):
        self.accounts = []      # list of dicts
        self.active_id = None
        self.load()

    # ---- persistence -------------------------------------------------
    def load(self):
        paths.ensure_dirs()
        if os.path.exists(paths.ACCOUNTS_FILE):
            try:
                with open(paths.ACCOUNTS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.accounts = data.get("accounts", [])
                self.active_id = data.get("active_id")
            except (json.JSONDecodeError, OSError):
                self.accounts, self.active_id = [], None
        return self

    def save(self):
        paths.ensure_dirs()
        tmp = paths.ACCOUNTS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"accounts": self.accounts, "active_id": self.active_id}, f, indent=2)
        shutil.move(tmp, paths.ACCOUNTS_FILE)

    # ---- queries -----------------------------------------------------
    def get_active(self):
        for a in self.accounts:
            if a["id"] == self.active_id:
                return a
        return self.accounts[0] if self.accounts else None

    def set_active(self, account_id):
        self.active_id = account_id
        self.save()

    def remove(self, account_id):
        self.accounts = [a for a in self.accounts if a["id"] != account_id]
        if self.active_id == account_id:
            self.active_id = self.accounts[0]["id"] if self.accounts else None
        self.save()

    # ---- add accounts ------------------------------------------------
    def add_offline(self, username):
        username = username.strip() or "Player"
        acc = {
            "id": "offline:" + username.lower(),
            "type": "offline",
            "name": username,
            "uuid": _offline_uuid(username),
        }
        self.accounts = [a for a in self.accounts if a["id"] != acc["id"]]
        self.accounts.append(acc)
        self.active_id = acc["id"]
        self.save()
        return acc

    def add_microsoft(self, login_data):
        """login_data is a CompleteLoginResponse dict from minecraft-launcher-lib."""
        acc = {
            "id": "ms:" + login_data["id"],
            "type": "microsoft",
            "name": login_data["name"],
            "uuid": login_data["id"],
            "access_token": login_data["access_token"],
            "refresh_token": login_data.get("refresh_token", ""),
        }
        self.accounts = [a for a in self.accounts if a["id"] != acc["id"]]
        self.accounts.append(acc)
        self.active_id = acc["id"]
        self.save()
        return acc

    # ---- launch options ---------------------------------------------
    def launch_options(self, account):
        """Build the auth portion of minecraft-launcher-lib MinecraftOptions."""
        if account["type"] == "microsoft":
            return {
                "username": account["name"],
                "uuid": account["uuid"],
                "token": account.get("access_token", "0"),
            }
        # offline
        return {
            "username": account["name"],
            "uuid": account["uuid"],
            "token": "0",
        }


# --- Microsoft device-code sign-in --------------------------------------
#
# The device-code flow is what makes "Sign in with Microsoft" painless: the
# user is shown a short code and a URL, approves the sign-in in any browser,
# and the launcher polls in the background until it's done. No copying long
# redirect URLs out of the address bar, and it works even when the login page
# ends on a blank / "can't reach this page" screen (the old failure mode).
DEVICE_CODE_URL = "https://login.live.com/oauth20_connect.srf"
TOKEN_URL = "https://login.live.com/oauth20_token.srf"
SCOPE = "XboxLive.signin offline_access"


class MicrosoftAuthError(Exception):
    """Raised for a user-meaningful Microsoft/Xbox sign-in failure."""


def start_device_login():
    """Ask Microsoft for a device code. Returns a dict with user_code,
    verification_uri, device_code, interval and expires_in."""
    import requests
    r = requests.post(
        DEVICE_CODE_URL,
        data={"client_id": CLIENT_ID, "scope": SCOPE,
              "response_type": "device_code"},
        timeout=30,
    )
    if not r.ok:
        raise MicrosoftAuthError("Could not start Microsoft sign-in (HTTP %s)."
                                 % r.status_code)
    data = r.json()
    return {
        "user_code": data["user_code"],
        "verification_uri": data.get("verification_uri", "https://www.microsoft.com/link"),
        "device_code": data["device_code"],
        "interval": int(data.get("interval", 5)),
        "expires_in": int(data.get("expires_in", 900)),
    }


def _poll_device_token(device_code):
    """Poll once for the Microsoft OAuth token.

    Returns the token dict when approved, None while still pending, and raises
    MicrosoftAuthError if the user declined or the code expired.
    """
    import requests
    r = requests.post(
        TOKEN_URL,
        data={"client_id": CLIENT_ID,
              "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
              "device_code": device_code},
        timeout=30,
    )
    if r.ok:
        return r.json()
    try:
        err = r.json().get("error", "")
    except ValueError:
        err = ""
    if err in ("authorization_pending", "slow_down"):
        return None
    if err == "authorization_declined":
        raise MicrosoftAuthError("Sign-in was declined in the browser.")
    if err in ("expired_token", "code_expired"):
        raise MicrosoftAuthError("The code expired. Start the sign-in again.")
    raise MicrosoftAuthError("Microsoft sign-in failed: " + (err or "unknown error"))


def poll_device_login(device_code, interval, expires_in,
                      should_cancel=None, on_wait=None):
    """Block until the user approves the device code, then run the full
    Microsoft -> Xbox Live -> XSTS -> Minecraft chain. Returns a
    CompleteLoginResponse-style dict.

    ``should_cancel`` is called between polls; return True to abort.
    ``on_wait`` is called with the seconds until the next poll (for the UI).
    """
    import time
    deadline = time.time() + max(30, expires_in)
    wait = max(1, interval)
    token = None
    while True:
        if should_cancel and should_cancel():
            raise MicrosoftAuthError("Sign-in cancelled.")
        if time.time() > deadline:
            raise MicrosoftAuthError("The code expired. Start the sign-in again.")
        token = _poll_device_token(device_code)
        if token:
            break
        if on_wait:
            on_wait(wait)
        for _ in range(wait * 2):  # sleep in 0.5s slices so cancel is responsive
            if should_cancel and should_cancel():
                raise MicrosoftAuthError("Sign-in cancelled.")
            time.sleep(0.5)
    return _minecraft_from_ms_token(token)


def _minecraft_from_ms_token(token):
    """Turn a Microsoft OAuth token dict into a Minecraft login response."""
    import minecraft_launcher_lib as mll
    ma = mll.microsoft_account
    ms_access = token["access_token"]
    ms_refresh = token.get("refresh_token", "")

    xbl = ma.authenticate_with_xbl(ms_access)
    xbl_token = xbl["Token"]
    userhash = xbl["DisplayClaims"]["xui"][0]["uhs"]

    xsts = ma.authenticate_with_xsts(xbl_token)
    xsts_token = xsts["Token"]

    mc = ma.authenticate_with_minecraft(userhash, xsts_token)
    if "access_token" not in mc:
        raise MicrosoftAuthError(
            "This Microsoft account does not own Minecraft: Java Edition.")
    mc_access = mc["access_token"]

    try:
        profile = ma.get_profile(mc_access)
    except Exception:
        raise MicrosoftAuthError(
            "Signed in, but this account has no Minecraft: Java Edition profile.")
    if "id" not in profile or "name" not in profile:
        raise MicrosoftAuthError(
            "This Microsoft account does not own Minecraft: Java Edition.")

    return {
        "id": profile["id"],
        "name": profile["name"],
        "access_token": mc_access,
        "refresh_token": ms_refresh,
    }


def refresh_ms_token(refresh_token):
    """Exchange a stored refresh token for a fresh Microsoft OAuth token dict."""
    import requests
    r = requests.post(
        TOKEN_URL,
        data={"client_id": CLIENT_ID, "grant_type": "refresh_token",
              "scope": SCOPE, "refresh_token": refresh_token},
        timeout=30,
    )
    if not r.ok:
        raise MicrosoftAuthError("Could not refresh the Microsoft session.")
    return r.json()


def try_refresh(account):
    """Refresh a Microsoft login if possible. Returns updated account or raises."""
    if account.get("type") != "microsoft" or not account.get("refresh_token"):
        return account
    token = refresh_ms_token(account["refresh_token"])
    login = _minecraft_from_ms_token(token)
    account["access_token"] = login["access_token"]
    account["refresh_token"] = login.get("refresh_token") or account["refresh_token"]
    account["name"] = login["name"]
    account["uuid"] = login["id"]
    return account
