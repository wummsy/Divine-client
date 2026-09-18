"""SQLite storage for the Divine social backend.

Tables (all created by init_db(), which app.py calls at import time so a fresh
file is ready under gunicorn as well as `python app.py`):
  users        - Discord users who have signed in (id, username, avatar, last_seen,
                 presence, presence_at, presence_detail)
  tokens       - launcher tokens -> user id
  links        - in-progress launcher link sessions (code -> user id once claimed)
  friendships  - requester/addressee pairs with a status (pending|accepted)
  announcements- the launcher's LATEST NEWS feed
  game_servers - hosted servers published for friends, keyed by join code
  server_invites - pending join requests for those servers
"""
import json
import os
import secrets
import sqlite3
import time

def _resolve_db_path():
    """Find or create the database path in a persistent data directory.

    Defaults to `server/data/divine.db`. If an existing `server/divine.db` is present,
    it automatically migrates it and its WAL/SHM files into `server/data/` so that
    updating server code or pulling new versions never wipes out existing database records.
    """
    env_val = os.environ.get("DIVINE_DB") or os.environ.get("DIVINE_DB")
    if env_val:
        if env_val in ("divine.db", "divine.db"):
            p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "divine.db")
        else:
            p = os.path.abspath(env_val) if not os.path.isabs(env_val) else env_val
        os.makedirs(os.path.dirname(p), exist_ok=True)
        return p

    server_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(server_dir, "data")
    os.makedirs(data_dir, exist_ok=True)
    target = os.path.join(data_dir, "divine.db")

    old_db = os.path.join(data_dir, "divine.db")
    if os.path.isfile(old_db) and not os.path.isfile(target):
        try:
            import shutil
            shutil.move(old_db, target)
        except Exception:
            pass

    return target

DB_PATH = _resolve_db_path()

_conn = None


def get_conn():
    global _conn, DB_PATH
    if _conn is None:
        target = DB_PATH or _resolve_db_path()
        if os.environ.get("DIVINE_DB"):
            target = _resolve_db_path()
            DB_PATH = target
        os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
        _conn = sqlite3.connect(target, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        # WAL lets the web app and the Discord bot read/write the same file at
        # the same time without "database is locked" errors; the busy timeout
        # makes a writer wait briefly for a lock instead of failing outright.
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA busy_timeout=5000")
        _conn.commit()
    return _conn


def init_db():
    c = get_conn()
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT,
            avatar_url TEXT,
            last_seen INTEGER,
            presence TEXT,           -- online | idle | in_game | offline
            presence_at INTEGER,     -- when the launcher last said it
            presence_detail TEXT     -- short line under it, e.g. "Playing 1.21.4"
        );
        CREATE TABLE IF NOT EXISTS tokens (
            token TEXT PRIMARY KEY,
            user_id TEXT,
            created INTEGER
        );
        CREATE TABLE IF NOT EXISTS links (
            link_id TEXT PRIMARY KEY,
            code TEXT UNIQUE,
            user_id TEXT,
            status TEXT,           -- pending | linked
            created INTEGER
        );
        CREATE TABLE IF NOT EXISTS friendships (
            requester TEXT,
            addressee TEXT,
            status TEXT,           -- pending | accepted
            created INTEGER,
            PRIMARY KEY (requester, addressee)
        );
        CREATE TABLE IF NOT EXISTS announcements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            body TEXT,
            tag TEXT,
            url TEXT,
            created INTEGER
        );
        CREATE TABLE IF NOT EXISTS game_servers (
            code TEXT PRIMARY KEY,
            host_id TEXT,
            address TEXT,
            name TEXT,
            mc_version TEXT,
            loader TEXT,
            status TEXT,           -- online | offline
            created INTEGER,
            updated INTEGER
        );
        CREATE TABLE IF NOT EXISTS server_invites (
            code TEXT,
            from_id TEXT,
            to_id TEXT,
            created INTEGER,
            PRIMARY KEY (code, to_id)
        );
        CREATE TABLE IF NOT EXISTS server_collaborators (
            code TEXT,
            user_id TEXT,
            username TEXT,
            permissions TEXT,
            created INTEGER,
            updated INTEGER,
            PRIMARY KEY (code, user_id)
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender TEXT,
            recipient TEXT,
            body TEXT,
            created INTEGER
        );
                CREATE TABLE IF NOT EXISTS banned_devices (
            device_code TEXT PRIMARY KEY,
            user_id TEXT,
            username TEXT,
            reason TEXT,
            banned_by TEXT,
            banned_at INTEGER,
            expires_at INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS user_devices (
            user_id TEXT,
            device_code TEXT,
            last_seen INTEGER,
            PRIMARY KEY (user_id, device_code)
        );
        CREATE TABLE IF NOT EXISTS room_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender TEXT,
            body TEXT,
            created INTEGER
        );
        CREATE TABLE IF NOT EXISTS bot_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE IF NOT EXISTS connection_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            username TEXT,
            device_code TEXT,
            event_type TEXT,
            ip TEXT,
            created INTEGER
        );
        CREATE TABLE IF NOT EXISTS redeem_codes (
            code TEXT PRIMARY KEY,
            product_id TEXT,
            created_by TEXT,
            created_at INTEGER,
            redeemed_by TEXT,
            device_code TEXT,
            redeemed_at INTEGER,
            is_revoked INTEGER DEFAULT 0,
            revoked_by TEXT,
            revoked_at INTEGER
        );
        """
    )
    c.commit()
    _add_missing_columns(c)
    for sql in (
        "CREATE INDEX IF NOT EXISTS messages_recipient ON messages(recipient, id)",
        "CREATE INDEX IF NOT EXISTS messages_sender ON messages(sender, id)",
        "CREATE INDEX IF NOT EXISTS room_order ON room_messages(id)",
    ):
        c.execute(sql)
    c.commit()


def _add_missing_columns(c):
    """Bring an existing database up to date.

    CREATE TABLE IF NOT EXISTS leaves an old ``users`` table exactly as it was, and the
    friend list now needs the presence columns, so add whatever is missing. This runs on
    every start and is a no-op once a database has them, which keeps a deployed site
    working after a pull with no manual migration step.
    """
    have = {r[1] for r in c.execute("PRAGMA table_info(users)").fetchall()}
    for name, decl in (("presence", "TEXT"),
                       ("presence_at", "INTEGER"),
                       ("presence_detail", "TEXT")):
        if name not in have:
            c.execute("ALTER TABLE users ADD COLUMN %s %s" % (name, decl))
    c.commit()


# ---- presence ----------------------------------------------------------------
# A launcher tells the site when Minecraft starts and when it quits. If it is killed
# instead, the last thing it said must stop being believed - hence the timestamp and
# this bound, which is what makes a friend turn orange/black on its own.
PRESENCE_STATES = ("online", "idle", "in_game", "offline")
PRESENCE_TTL = 180


def set_presence(uid, state, detail=""):
    """Store what the launcher says the player is doing right now. True if it took."""
    state = (state or "").strip().lower()
    if state not in PRESENCE_STATES:
        return False
    now = int(time.time())
    c = get_conn()
    cur = c.execute(
        "UPDATE users SET presence=?, presence_at=?, presence_detail=?, last_seen=? "
        "WHERE id=?", (state, now, (detail or "").strip()[:80], now, uid))
    c.commit()
    return (cur.rowcount or 0) > 0


# ---- announcements / news ---------------------------------------------------
def add_announcement(title, body, tag="Update", url=""):
    """Store an announcement so it shows in the launcher's news feed.

    Returns the new row id.
    """
    c = get_conn()
    cur = c.execute(
        "INSERT INTO announcements (title, body, tag, url, created) "
        "VALUES (?, ?, ?, ?, ?)",
        ((title or "").strip(), (body or "").strip(),
         (tag or "Update").strip(), (url or "").strip(), int(time.time())))
    c.commit()
    return cur.lastrowid


def list_announcements(limit=20):
    """Newest announcements first, as a list of dicts for the /api/news feed."""
    rows = get_conn().execute(
        "SELECT id, title, body, tag, url, created FROM announcements "
        "ORDER BY created DESC, id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def delete_announcement(ann_id):
    c = get_conn()
    c.execute("DELETE FROM announcements WHERE id=?", (ann_id,))
    c.commit()


# ---- users ------------------------------------------------------------------
def upsert_user(uid, username, avatar_url):
    c = get_conn()
    c.execute(
        "INSERT INTO users (id, username, avatar_url, last_seen) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET username=excluded.username, "
        "avatar_url=excluded.avatar_url, last_seen=excluded.last_seen",
        (uid, username, avatar_url, int(time.time())),
    )
    c.commit()


# ---- tokens -----------------------------------------------------------------
def issue_token(uid):
    token = secrets.token_urlsafe(32)
    c = get_conn()
    c.execute("INSERT INTO tokens (token, user_id, created) VALUES (?, ?, ?)",
              (token, uid, int(time.time())))
    c.commit()
    return token


def user_for_token(token):
    if not token:
        return None
    row = get_conn().execute("SELECT user_id FROM tokens WHERE token=?",
                             (token,)).fetchone()
    return row["user_id"] if row else None


# ---- launcher link sessions -------------------------------------------------
def _new_code():
    # short, unambiguous, uppercase (no O/0/I/1)
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(6))


def create_link():
    c = get_conn()
    link_id = secrets.token_urlsafe(18)
    for _ in range(10):
        code = _new_code()
        try:
            c.execute("INSERT INTO links (link_id, code, user_id, status, created) "
                      "VALUES (?, ?, NULL, 'pending', ?)",
                      (link_id, code, int(time.time())))
            c.commit()
            return code, link_id
        except sqlite3.IntegrityError:
            continue
    raise RuntimeError("could not allocate a link code")


def claim_link(code, uid):
    """Mark a link session as linked to a user. Returns True if a pending
    session with that code existed."""
    c = get_conn()
    row = c.execute("SELECT link_id FROM links WHERE code=? AND status='pending'",
                    (code.upper(),)).fetchone()
    if not row:
        return False
    c.execute("UPDATE links SET user_id=?, status='linked' WHERE code=?",
              (uid, code.upper()))
    c.commit()
    return True


def poll_link(link_id):
    """Return (status, user_id). status is pending|linked|expired."""
    row = get_conn().execute(
        "SELECT user_id, status, created FROM links WHERE link_id=?",
        (link_id,)).fetchone()
    if not row:
        return "expired", None
    if (time.time() - (row["created"] or 0)) > 600:
        return "expired", None
    if row["status"] == "linked":
        return "linked", row["user_id"]
    return "pending", None


def purge_expired():
    c = get_conn()
    cutoff = int(time.time()) - 3600
    c.execute("DELETE FROM links WHERE created < ?", (cutoff,))
    c.commit()


# ---- helpers shared with the Discord bot ------------------------------------
def find_user_by_name(name):
    """Look up an Divine user by their (case-insensitive) Discord name."""
    bare = (name or "").strip().lstrip("@").split("#")[0]
    if not bare:
        return None
    return get_conn().execute(
        "SELECT id, username, avatar_url FROM users WHERE lower(username)=lower(?) "
        "LIMIT 1", (bare,)).fetchone()


def get_user(uid):
    return get_conn().execute(
        "SELECT id, username, avatar_url, last_seen FROM users WHERE id=?",
        (uid,)).fetchone()


def friends_of(uid):
    """Return a list of (id, username) the user is accepted friends with."""
    rows = get_conn().execute(
        "SELECT requester, addressee FROM friendships WHERE status='accepted' "
        "AND (requester=? OR addressee=?)", (uid, uid)).fetchall()
    out = []
    for r in rows:
        other = r["addressee"] if r["requester"] == uid else r["requester"]
        u = get_user(other)
        if u:
            out.append((u["id"], u["username"]))
    return out


def add_friendship(requester, addressee):
    """Create or auto-accept a friendship, mirroring the web API's /add logic.

    Returns one of: 'sent', 'accepted', 'exists', 'self'.
    """
    if requester == addressee:
        return "self"
    c = get_conn()
    existing = c.execute(
        "SELECT requester, addressee, status FROM friendships WHERE "
        "(requester=? AND addressee=?) OR (requester=? AND addressee=?)",
        (requester, addressee, addressee, requester)).fetchone()
    if existing:
        if existing["status"] == "accepted":
            return "exists"
        if existing["requester"] == addressee:  # they already asked us
            c.execute("UPDATE friendships SET status='accepted' WHERE "
                      "requester=? AND addressee=?", (addressee, requester))
            c.commit()
            return "accepted"
        return "exists"
    c.execute("INSERT INTO friendships (requester, addressee, status, created) "
              "VALUES (?, ?, 'pending', ?)", (requester, addressee, int(time.time())))
    c.commit()
    return "sent"


# ---- game servers (host / join by code / invites) ---------------------------
def _server_code():
    import random
    import string
    alphabet = string.ascii_uppercase + string.digits
    # avoid ambiguous characters
    alphabet = alphabet.replace("O", "").replace("0", "").replace("I", "").replace("1", "")
    c = get_conn()
    for _ in range(50):
        code = "".join(random.choice(alphabet) for _ in range(6))
        if not c.execute("SELECT 1 FROM game_servers WHERE code=?", (code,)).fetchone():
            return code
    raise RuntimeError("could not allocate a server code")


def create_server(host_id, name, address, mc_version, loader):
    """Register a hosted server and return its join code."""
    code = _server_code()
    now = int(time.time())
    get_conn().execute(
        "INSERT INTO game_servers (code, host_id, address, name, mc_version, "
        "loader, status, created, updated) VALUES (?,?,?,?,?,?, 'online', ?, ?)",
        (code, host_id, address or "", name or "Server", mc_version or "",
         loader or "vanilla", now, now))
    get_conn().commit()
    return code


def update_server(code, host_id, address=None, status=None):
    c = get_conn()
    row = c.execute("SELECT host_id FROM game_servers WHERE code=?", (code,)).fetchone()
    if not row or row["host_id"] != host_id:
        return False
    fields = ["updated=?"]
    vals = [int(time.time())]
    if address is not None:
        fields.append("address=?")
        vals.append(address)
    if status is not None:
        fields.append("status=?")
        vals.append(status)
    vals += [code]
    c.execute("UPDATE game_servers SET " + ", ".join(fields) + " WHERE code=?", vals)
    c.commit()
    return True


def get_server(code):
    row = get_conn().execute(
        "SELECT * FROM game_servers WHERE code=?", (code,)).fetchone()
    return dict(row) if row else None


def close_server(code, host_id):
    c = get_conn()
    row = c.execute("SELECT host_id FROM game_servers WHERE code=?", (code,)).fetchone()
    if not row or row["host_id"] != host_id:
        return False
    c.execute("UPDATE game_servers SET status='offline', updated=? WHERE code=?",
              (int(time.time()), code))
    c.commit()
    return True


def add_invite(code, from_id, to_id):
    get_conn().execute(
        "INSERT OR REPLACE INTO server_invites (code, from_id, to_id, created) "
        "VALUES (?,?,?,?)", (code, from_id, to_id, int(time.time())))
    get_conn().commit()


def invites_for(uid, max_age=3600):
    """Pending server invites for a user, newest first, with server + sender info."""
    cutoff = int(time.time()) - max_age
    rows = get_conn().execute(
        "SELECT i.code, i.from_id, i.created, s.name, s.mc_version, s.loader, "
        "s.status, s.address FROM server_invites i "
        "JOIN game_servers s ON s.code = i.code "
        "WHERE i.to_id=? AND i.created>=? ORDER BY i.created DESC",
        (uid, cutoff)).fetchall()
    out = []
    for r in rows:
        sender = get_user(r["from_id"])
        out.append({
            "code": r["code"],
            "from": sender["username"] if sender else "A friend",
            "name": r["name"],
            "mc_version": r["mc_version"],
            "loader": r["loader"],
            "status": r["status"],
        })
    return out


def clear_invite(code, to_id):
    get_conn().execute(
        "DELETE FROM server_invites WHERE code=? AND to_id=?", (code, to_id))
    get_conn().commit()


def add_server_collaborator(code, user_id, username=None, permissions=None):
    """Add or update collaborator access permissions for a game server."""
    c = get_conn()
    now = int(time.time())
    if permissions is None:
        perms_str = json.dumps(["power", "console", "files", "players", "settings", "network"])
    elif isinstance(permissions, list):
        perms_str = json.dumps(permissions)
    else:
        perms_str = str(permissions)

    if not username and user_id:
        u = get_user(user_id)
        if u:
            username = u.get("username")

    c.execute(
        "INSERT INTO server_collaborators (code, user_id, username, permissions, created, updated) "
        "VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(code, user_id) DO UPDATE SET username=excluded.username, permissions=excluded.permissions, updated=excluded.updated",
        (code.upper(), str(user_id), username or str(user_id), perms_str, now, now)
    )
    c.commit()
    return True


def remove_server_collaborator(code, user_id):
    """Revoke a user's collaborator permissions for a game server."""
    c = get_conn()
    c.execute(
        "DELETE FROM server_collaborators WHERE code=? AND (user_id=? OR username=?)",
        (code.upper(), str(user_id), str(user_id))
    )
    c.commit()
    return True


def get_server_collaborators(code):
    """Return all collaborators and permissions for a given server code."""
    c = get_conn()
    rows = c.execute(
        "SELECT c.*, u.avatar_url, u.presence FROM server_collaborators c "
        "LEFT JOIN users u ON u.id = c.user_id "
        "WHERE c.code=? ORDER BY c.created ASC",
        (code.upper(),)
    ).fetchall()
    out = []
    for r in rows:
        perms = []
        try:
            perms = json.loads(r["permissions"]) if r["permissions"] else []
        except Exception:
            perms = ["power", "console", "files", "players"]
        out.append({
            "code": r["code"],
            "user_id": r["user_id"],
            "username": r["username"],
            "permissions": perms,
            "avatar_url": r["avatar_url"],
            "presence": r["presence"] or "offline",
            "created": r["created"],
            "updated": r["updated"],
        })
    return out


def get_shared_servers_for_user(user_id, online_only=False):
    """Return all servers where the given user has collaborator permissions."""
    c = get_conn()
    query = (
        "SELECT s.*, c.permissions, u.username as host_name "
        "FROM server_collaborators c "
        "JOIN game_servers s ON s.code = c.code "
        "LEFT JOIN users u ON u.id = s.host_id "
        "WHERE (c.user_id=? OR c.username=?) "
    )
    params = [str(user_id), str(user_id)]
    if online_only:
        query += " AND s.status = 'online'"
    query += " ORDER BY s.updated DESC"
    rows = c.execute(query, params).fetchall()
    out = []
    for r in rows:
        perms = []
        try:
            perms = json.loads(r["permissions"]) if r["permissions"] else []
        except Exception:
            perms = []
        out.append({
            "code": r["code"],
            "name": r["name"],
            "host_id": r["host_id"],
            "host_name": r["host_name"] or "Server Owner",
            "address": r["address"],
            "mc_version": r["mc_version"],
            "loader": r["loader"],
            "status": r["status"],
            "permissions": perms,
            "created": r["created"],
            "updated": r["updated"]
        })
    return out


def check_server_permission(code, user_id, required_perm=None):
    """Check if user is owner or has the required permission for the server."""
    srv = get_server(code)
    if not srv:
        return False, "Server not found"
    if str(srv.get("host_id")) == str(user_id):
        return True, "owner"

    c = get_conn()
    row = c.execute(
        "SELECT permissions FROM server_collaborators WHERE code=? AND (user_id=? OR username=?)",
        (code.upper(), str(user_id), str(user_id))
    ).fetchone()
    if not row:
        return False, "No collaborator access"

    try:
        perms = json.loads(row["permissions"]) if row["permissions"] else []
    except Exception:
        perms = []

    if required_perm and required_perm not in perms and "admin" not in perms:
        return False, f"Missing required permission: {required_perm}"

    return True, perms


def list_all_game_servers(host_id=None, online_only=False):
    """Return all hosted / dedicated game servers in the network."""
    c = get_conn()
    query = "SELECT s.*, u.username as host_name FROM game_servers s LEFT JOIN users u ON u.id = s.host_id"
    params = []
    clauses = []
    if host_id:
        clauses.append("s.host_id = ?")
        params.append(str(host_id))
    if online_only:
        clauses.append("s.status = 'online'")
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY s.updated DESC LIMIT 50"
    rows = c.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def clear_user_servers(host_id):
    """Delete all hosted servers, invites, and collaborator records associated with a user."""
    c = get_conn()
    c.execute("DELETE FROM server_collaborators WHERE code IN (SELECT code FROM game_servers WHERE host_id=?)", (str(host_id),))
    c.execute("DELETE FROM server_collaborators WHERE user_id=?", (str(host_id),))
    c.execute("DELETE FROM server_invites WHERE code IN (SELECT code FROM game_servers WHERE host_id=?)", (str(host_id),))
    c.execute("DELETE FROM game_servers WHERE host_id=?", (str(host_id),))
    c.commit()
    return True


def clear_all_servers():
    """Wipe all hosted game servers, invites, and collaborator records across the database."""
    c = get_conn()
    c.execute("DELETE FROM server_collaborators")
    c.execute("DELETE FROM server_invites")
    c.execute("DELETE FROM game_servers")
    c.commit()
    return True


# ---- messages: direct messages between friends, and the Divine room ------------
# Two rules worth stating because they shape the endpoints. A DM is only ever delivered
# between people who accepted each other - a token must not become a way to write to any
# account on the site. And both writers are rate limited against the table itself rather
# than a counter in this process, so a restart or a second gunicorn worker cannot hand a
# spammer a fresh allowance.
DM_MAX_LEN = 500
ROOM_MAX_LEN = 400
SEND_WINDOW = 2          # seconds between two posts by the same person
STAFF_KEEP = 5000        # rows kept before the oldest are pruned


def is_friend(a, b):
    if not a or not b or a == b:
        return False
    row = get_conn().execute(
        "SELECT 1 FROM friendships WHERE status='accepted' "
        "AND ((requester=? AND addressee=?) OR (requester=? AND addressee=?))",
        (a, b, b, a)).fetchone()
    return row is not None


def resolve_user(name_or_id):
    """Find a user by Discord id or by exact username (case-insensitive)."""
    needle = (name_or_id or "").strip().lstrip("@")
    if not needle:
        return None
    row = get_conn().execute(
        "SELECT id, username FROM users WHERE id=? OR lower(username)=lower(?) "
        "LIMIT 1", (needle, needle)).fetchone()
    return dict(row) if row else None


def _too_soon(table, uid):
    """Seconds since this person last posted in ``table``; 0 when they may write."""
    row = get_conn().execute(
        "SELECT created FROM %s WHERE sender=? ORDER BY id DESC LIMIT 1" % table,
        (uid,)).fetchone()
    if not row:
        return 0
    gap = int(time.time()) - int(row["created"] or 0)
    return SEND_WINDOW - gap if gap < SEND_WINDOW else 0


def _prune(table):
    row = get_conn().execute("SELECT COUNT(*) AS n FROM %s" % table).fetchone()
    if row and row["n"] > STAFF_KEEP:
        get_conn().execute(
            "DELETE FROM %s WHERE id <= (SELECT MAX(id) - %d FROM %s)"
            % (table, STAFF_KEEP, table))


def send_message(sender_id, recipient, body):
    """Store a DM. Returns ``(ok, payload)``; payload carries ``status`` for the HTTP code."""
    body = (body or "").strip()[:DM_MAX_LEN]
    if not body:
        return False, {"error": "nothing to send", "status": 400}
    other = resolve_user(recipient)
    if not other:
        return False, {"error": "no such Divine user", "status": 404}
    if other["id"] == sender_id:
        return False, {"error": "you cannot message yourself", "status": 400}
    if not is_friend(sender_id, other["id"]):
        return False, {"error": "you can only message friends", "status": 403}
    wait = _too_soon("messages", sender_id)
    if wait > 0:
        return False, {"error": "slow down - try again in %ds" % wait, "status": 429}

    c = get_conn()
    now = int(time.time())
    cur = c.execute(
        "INSERT INTO messages (sender, recipient, body, created) VALUES (?,?,?,?)",
        (sender_id, other["id"], body, now))
    _prune("messages")
    c.commit()
    return True, {"id": cur.lastrowid, "to": other["username"], "ts": now}


def messages_for(uid, since=0, limit=200):
    """Everything this user sent or received with ``id > since``, oldest first."""
    try:
        since = int(since or 0)
    except (TypeError, ValueError):
        since = 0
    rows = get_conn().execute(
        "SELECT m.id, m.sender, m.recipient, m.body, m.created, "
        "       u.username AS sender_name "
        "FROM messages m LEFT JOIN users u ON u.id = m.sender "
        "WHERE (m.sender=? OR m.recipient=?) AND m.id>? "
        "ORDER BY m.id ASC LIMIT ?", (uid, uid, since, max(1, min(int(limit), 400)))
    ).fetchall()
    out = []
    for r in rows:
        out.append({"id": r["id"], "from": r["sender_name"] or "?",
                    "to": r["recipient"] if r["sender"] == uid else r["sender"],
                    "text": r["body"], "ts": r["created"], "room": False,
                    "mine": r["sender"] == uid})
    return out


def post_room(sender_id, body, sender_name=""):
    body = (body or "").strip()[:ROOM_MAX_LEN]
    if not body:
        return False, {"error": "nothing to send", "status": 400}
    wait = _too_soon("room_messages", sender_id)
    if wait > 0:
        return False, {"error": "slow down - try again in %ds" % wait, "status": 429}
    c = get_conn()
    now = int(time.time())
    cur = c.execute("INSERT INTO room_messages (sender, body, created) VALUES (?,?,?)",
                    (sender_id, body, now))
    _prune("room_messages")
    c.commit()
    return True, {"id": cur.lastrowid, "ts": now}


def room_messages(since=0, limit=200):
    try:
        since = int(since or 0)
    except (TypeError, ValueError):
        since = 0
    rows = get_conn().execute(
        "SELECT r.id, r.sender, r.body, r.created, u.username AS name "
        "FROM room_messages r LEFT JOIN users u ON u.id = r.sender "
        "WHERE r.id>? ORDER BY r.id ASC LIMIT ?",
        (since, max(1, min(int(limit), 400)))).fetchall()
    return [{"id": r["id"], "from": r["name"] or "?", "to": "", "text": r["body"],
             "ts": r["created"], "room": True} for r in rows]


def online_server_for(uid):
    """The address a friend's launcher last volunteered while their server is online."""
    row = get_conn().execute(
        "SELECT address, code, updated FROM game_servers WHERE host_id=? "
        "AND status='online' AND address IS NOT NULL AND address != '' "
        "ORDER BY updated DESC LIMIT 1", (uid,)).fetchone()
    if not row:
        return None
    return {"address": row["address"], "code": row["code"], "updated": row["updated"]}


# ---- bans & device tracking -------------------------------------------------
def get_setting(key, default=None):
    c = get_conn()
    row = c.execute("SELECT value FROM bot_settings WHERE key=?", (str(key),)).fetchone()
    return row["value"] if row else default


def set_setting(key, value):
    c = get_conn()
    c.execute(
        "INSERT INTO bot_settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (str(key), str(value))
    )
    c.commit()


def log_connection_event(user_id=None, username=None, device_code=None, event_type="login", ip=""):
    c = get_conn()
    now = int(time.time())
    if not username and user_id:
        u = get_user(str(user_id))
        if u:
            username = u["username"]
    c.execute(
        "INSERT INTO connection_logs (user_id, username, device_code, event_type, ip, created) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (str(user_id or ""), str(username or ""), str(device_code or "").upper(), str(event_type or "login"), str(ip or ""), now)
    )
    c.commit()


def get_connection_logs(since=0, limit=50):
    c = get_conn()
    rows = c.execute(
        "SELECT id, user_id, username, device_code, event_type, ip, created FROM connection_logs "
        "WHERE id > ? ORDER BY id ASC LIMIT ?", (int(since or 0), int(limit or 50))
    ).fetchall()
    return [dict(r) for r in rows]


def record_device_activity(device_code, user_id=None, username=None, event_type="active", ip=""):
    """Update last seen for a device and user without spamming connection logs."""
    if not device_code:
        return
    device_code = str(device_code).strip().upper()
    now = int(time.time())
    c = get_conn()
    if user_id:
        c.execute(
            "INSERT INTO user_devices (user_id, device_code, last_seen) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id, device_code) DO UPDATE SET last_seen=excluded.last_seen",
            (str(user_id), device_code, now)
        )
        c.commit()


def is_banned(device_code=None, user_id=None):
    """Checks if a device code or user is banned. Returns dict with ban details or None."""
    c = get_conn()
    now = int(time.time())
    
    if device_code:
        dcode = str(device_code).strip().upper()
        row = c.execute("SELECT * FROM banned_devices WHERE device_code=?", (dcode,)).fetchone()
        if row:
            if row["expires_at"] and row["expires_at"] > 0 and now > row["expires_at"]:
                # Expired ban
                c.execute("DELETE FROM banned_devices WHERE device_code=?", (dcode,))
                c.commit()
            else:
                return dict(row)

    if user_id:
        uid = str(user_id).strip()
        row = c.execute("SELECT * FROM banned_devices WHERE user_id=?", (uid,)).fetchone()
        if row:
            if row["expires_at"] and row["expires_at"] > 0 and now > row["expires_at"]:
                c.execute("DELETE FROM banned_devices WHERE user_id=?", (uid,))
                c.commit()
            else:
                return dict(row)
                
        # Also check all device codes associated with this user
        dev_rows = c.execute("SELECT device_code FROM user_devices WHERE user_id=?", (uid,)).fetchall()
        for drow in dev_rows:
            dcode = drow["device_code"]
            brow = c.execute("SELECT * FROM banned_devices WHERE device_code=?", (dcode,)).fetchone()
            if brow:
                if brow["expires_at"] and brow["expires_at"] > 0 and now > brow["expires_at"]:
                    c.execute("DELETE FROM banned_devices WHERE device_code=?", (dcode,))
                    c.commit()
                else:
                    return dict(brow)

    return None


def ban_device(device_code, reason="Violation of Terms of Service", banned_by="Admin", user_id=None, username=None, expires_at=0):
    """Ban a specific device code from accessing the Divine network."""
    if not device_code:
        return False
    dcode = str(device_code).strip().upper()
    now = int(time.time())
    c = get_conn()
    c.execute(
        "INSERT INTO banned_devices (device_code, user_id, username, reason, banned_by, banned_at, expires_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(device_code) DO UPDATE SET user_id=excluded.user_id, username=excluded.username, "
        "reason=excluded.reason, banned_by=excluded.banned_by, banned_at=excluded.banned_at, expires_at=excluded.expires_at",
        (dcode, str(user_id or ""), str(username or ""), reason, banned_by, now, int(expires_at or 0))
    )
    c.commit()
    return True


def ban_user(user_id_or_name, reason="Violation of Terms of Service", banned_by="Admin", expires_at=0):
    """Ban a user and all of their associated device codes."""
    u = resolve_user(user_id_or_name)
    if not u:
        return False, "User not found."
    uid = str(u["id"])
    uname = u["username"]
    now = int(time.time())
    c = get_conn()
    
    # Find all device codes linked to this user
    dev_rows = c.execute("SELECT device_code FROM user_devices WHERE user_id=?", (uid,)).fetchall()
    banned_codes = []
    
    if dev_rows:
        for r in dev_rows:
            dcode = r["device_code"]
            ban_device(dcode, reason=reason, banned_by=banned_by, user_id=uid, username=uname, expires_at=expires_at)
            banned_codes.append(dcode)
    else:
        # User has no recorded device code yet, record user-level ban placeholder
        pseudo_code = f"USER-{uid}"
        ban_device(pseudo_code, reason=reason, banned_by=banned_by, user_id=uid, username=uname, expires_at=expires_at)
        banned_codes.append(pseudo_code)
        
    return True, f"Banned user {uname} ({uid}) across {len(banned_codes)} device code(s): {', '.join(banned_codes)}"


def unban(target):
    """Unban by device code, user ID, or username."""
    if not target:
        return False, "Target required."
    target = str(target).strip()
    c = get_conn()
    
    # 1. Try matching exact device code
    cur = c.execute("DELETE FROM banned_devices WHERE upper(device_code)=upper(?)", (target,))
    if cur.rowcount > 0:
        c.commit()
        return True, f"Unbanned device code {target.upper()}."
        
    # 2. Try matching user
    u = resolve_user(target)
    if u:
        uid = str(u["id"])
        c.execute("DELETE FROM banned_devices WHERE user_id=? OR upper(device_code)=?", (uid, f"USER-{uid}".upper()))
        # Also remove bans on device codes tied to user
        dev_rows = c.execute("SELECT device_code FROM user_devices WHERE user_id=?", (uid,)).fetchall()
        for r in dev_rows:
            c.execute("DELETE FROM banned_devices WHERE device_code=?", (r["device_code"],))
        c.commit()
        return True, f"Unbanned user {u['username']} and associated devices."
        
    c.commit()
    return False, "No active ban found matching that target."


def list_bans():
    """Return all active bans from database."""
    rows = get_conn().execute(
        "SELECT device_code, user_id, username, reason, banned_by, banned_at, expires_at "
        "FROM banned_devices ORDER BY banned_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def lookup_device_info(target):
    """Search for device code(s), user information, and ban records for a target.

    Accepts:
      - Discord Mention (<@123...>)
      - Discord User ID (e.g. 1544313910096560128)
      - Discord / Account username (e.g. 'wummsy', 'notch')
      - Hardware Device Code (e.g. 'DEV-A1B2-C3D4-E5F6-7890')

    Returns a structured dict with resolved details or None if nothing matched.
    """
    if not target:
        return None

    target = str(target).strip()
    clean = target.lstrip("<@!").rstrip(">").strip()
    c = get_conn()

    # 1. Is target a Device Code directly?
    if clean.upper().startswith("DEV-") or clean.upper().startswith("USER-"):
        dcode = clean.upper()
        # Find ban status
        ban_row = c.execute("SELECT * FROM banned_devices WHERE upper(device_code)=?", (dcode,)).fetchone()
        ban_info = dict(ban_row) if ban_row else None

        # Find associated users
        dev_rows = c.execute("SELECT * FROM user_devices WHERE upper(device_code)=? ORDER BY last_seen DESC", (dcode,)).fetchall()
        users_list = []
        for dr in dev_rows:
            uid = dr["user_id"]
            u_row = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
            if u_row:
                users_list.append({
                    "id": u_row["id"],
                    "username": u_row["username"],
                    "avatar_url": u_row["avatar_url"] if "avatar_url" in u_row.keys() else "",
                    "presence": u_row["presence"] if "presence" in u_row.keys() else "offline",
                    "presence_detail": u_row["presence_detail"] if "presence_detail" in u_row.keys() else "",
                    "last_seen": dr["last_seen"] or (u_row["last_seen"] if "last_seen" in u_row.keys() else 0)
                })
            else:
                users_list.append({
                    "id": uid,
                    "username": f"User {uid}",
                    "avatar_url": "",
                    "presence": "offline",
                    "presence_detail": "",
                    "last_seen": dr["last_seen"] or 0
                })

        # If no users in user_devices but ban record has username/user_id
        if not users_list and ban_info and (ban_info.get("user_id") or ban_info.get("username")):
            users_list.append({
                "id": ban_info.get("user_id") or "Unknown",
                "username": ban_info.get("username") or "Unknown",
                "avatar_url": "",
                "presence": "offline",
                "presence_detail": "",
                "last_seen": ban_info.get("banned_at", 0)
            })

        return {
            "query_type": "device",
            "device_code": dcode,
            "banned": ban_info is not None,
            "ban_info": ban_info,
            "associated_users": users_list,
            "devices": [{
                "device_code": dcode,
                "last_seen": dev_rows[0]["last_seen"] if dev_rows else 0,
                "banned": ban_info is not None,
                "ban_reason": ban_info.get("reason") if ban_info else None
            }]
        }

    # 2. Lookup by Discord User ID or Username
    u_row = c.execute("SELECT * FROM users WHERE id=? OR lower(username)=lower(?)", (clean, clean)).fetchone()

    # If not found with exact match, try prefix/contains
    if not u_row:
        u_row = c.execute("SELECT * FROM users WHERE lower(username) LIKE lower(?) LIMIT 1", (f"%{clean}%",)).fetchone()

    user_id = None
    username = None
    avatar_url = ""
    presence = "offline"
    presence_detail = ""
    last_seen = 0

    if u_row:
        user_id = str(u_row["id"])
        username = u_row["username"]
        avatar_url = u_row["avatar_url"] if "avatar_url" in u_row.keys() else ""
        presence = u_row["presence"] if "presence" in u_row.keys() else "offline"
        presence_detail = u_row["presence_detail"] if "presence_detail" in u_row.keys() else ""
        last_seen = u_row["last_seen"] if "last_seen" in u_row.keys() else 0
    else:
        # Check if ID exists in user_devices
        ud_row = c.execute("SELECT * FROM user_devices WHERE user_id=? LIMIT 1", (clean,)).fetchone()
        if ud_row:
            user_id = str(clean)
            username = f"User {clean}"
        else:
            # Check banned_devices
            bd_row = c.execute("SELECT * FROM banned_devices WHERE user_id=? OR lower(username)=lower(?) OR lower(username) LIKE lower(?) LIMIT 1", (clean, clean, f"%{clean}%")).fetchone()
            if bd_row:
                user_id = bd_row["user_id"] or clean
                username = bd_row["username"] or f"User {clean}"

    if not user_id and not username:
        return None

    # Gather all device codes for this user
    dev_rows = c.execute("SELECT * FROM user_devices WHERE user_id=? ORDER BY last_seen DESC", (user_id,)).fetchall() if user_id else []

    devices = []
    seen_codes = set()
    for dr in dev_rows:
        dcode = dr["device_code"]
        seen_codes.add(dcode.upper())
        b_row = c.execute("SELECT * FROM banned_devices WHERE upper(device_code)=?", (dcode.upper(),)).fetchone()
        devices.append({
            "device_code": dcode,
            "last_seen": dr["last_seen"] or 0,
            "banned": b_row is not None,
            "ban_reason": b_row["reason"] if b_row else None
        })

    # Also check if user has pseudo-ban USER-... or ban by user_id
    ban_info = is_banned(user_id=user_id) if user_id else None

    # If user has no devices in user_devices but has a banned device code in banned_devices
    if not devices and user_id:
        b_rows = c.execute("SELECT * FROM banned_devices WHERE user_id=? OR upper(device_code)=?", (user_id, f"USER-{user_id}")).fetchall()
        for br in b_rows:
            dcode = br["device_code"]
            if dcode.upper() not in seen_codes:
                seen_codes.add(dcode.upper())
                devices.append({
                    "device_code": dcode,
                    "last_seen": br["banned_at"] or 0,
                    "banned": True,
                    "ban_reason": br["reason"]
                })

    return {
        "query_type": "user",
        "user_id": user_id,
        "username": username,
        "avatar_url": avatar_url,
        "presence": presence,
        "presence_detail": presence_detail,
        "last_seen": last_seen,
        "banned": ban_info is not None or any(d["banned"] for d in devices),
        "ban_info": ban_info,
        "devices": devices
    }


# ---- redeem codes -----------------------------------------------------------
def _generate_code_string():
    """Generates an authentic 16-character code like AREV-E9X2-74KP-81BZ."""
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    parts = []
    for _ in range(3):
        chunk = "".join(secrets.choice(chars) for _ in range(4))
        parts.append(chunk)
    return "AREV-" + "-".join(parts)


def create_redeem_code(product_id="server_slot", created_by="Admin", custom_code=None):
    """Generate and store a new one-time redemption code."""
    c = get_conn()
    code = (custom_code or _generate_code_string()).strip().upper()
    now = int(time.time())
    c.execute(
        "INSERT INTO redeem_codes (code, product_id, created_by, created_at, is_revoked) "
        "VALUES (?, ?, ?, ?, 0)",
        (code, str(product_id).strip(), str(created_by).strip(), now)
    )
    c.commit()
    return code


def get_code_info(code):
    if not code:
        return None
    code_clean = str(code).strip().upper()
    row = get_conn().execute("SELECT * FROM redeem_codes WHERE upper(code)=?", (code_clean,)).fetchone()
    return dict(row) if row else None


def redeem_code(code, user_id, username, device_code="", ip=""):
    """Redeem a one-time code for a specific user and device.

    Enforces:
      1. Code must exist.
      2. Code must not be revoked.
      3. Code must not have already been redeemed by anyone.
      4. Tracks user, device code, timestamp, and writes an audit log in connection_logs.
    """
    if not code:
        return {"success": False, "error": "Redemption code is required."}

    code_clean = str(code).strip().upper()
    c = get_conn()
    row = c.execute("SELECT * FROM redeem_codes WHERE upper(code)=?", (code_clean,)).fetchone()

    if not row:
        return {"success": False, "error": "Invalid redemption code. Please verify the code and try again."}

    if row["is_revoked"]:
        return {"success": False, "error": "This redemption code has been revoked by an administrator."}

    if row["redeemed_at"]:
        return {
            "success": False,
            "error": "This redemption code has already been claimed and used.",
            "already_redeemed": True
        }

    now = int(time.time())
    user_id_str = str(user_id) if user_id else "anonymous"
    username_str = str(username) if username else f"User-{user_id_str[:6]}"
    dcode_str = str(device_code).strip().upper() if device_code else "DEV-UNKNOWN"

    # Mark code as redeemed
    c.execute(
        "UPDATE redeem_codes SET redeemed_by=?, device_code=?, redeemed_at=? WHERE upper(code)=?",
        (user_id_str, dcode_str, now, code_clean)
    )

    # Record audit log event
    c.execute(
        "INSERT INTO connection_logs (user_id, username, device_code, event_type, ip, created) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (user_id_str, username_str, dcode_str, f"code_redeemed:{row['product_id']}:{code_clean}", str(ip or ""), now)
    )
    c.commit()

    return {
        "success": True,
        "code": code_clean,
        "product_id": row["product_id"],
        "redeemed_at": now,
        "user_id": user_id_str,
        "username": username_str,
        "device_code": dcode_str,
    }


def get_user_redeemed_codes(user_id):
    """Retrieve all codes redeemed by a specific user."""
    if not user_id:
        return []
    rows = get_conn().execute(
        "SELECT * FROM redeem_codes WHERE redeemed_by=? ORDER BY redeemed_at DESC",
        (str(user_id),)
    ).fetchall()
    return [dict(r) for r in rows]


def revoke_code(code, revoked_by="Admin"):
    """Revoke an active code so it cannot be used or remains invalid."""
    if not code:
        return False
    code_clean = str(code).strip().upper()
    c = get_conn()
    now = int(time.time())
    cur = c.execute(
        "UPDATE redeem_codes SET is_revoked=1, revoked_by=?, revoked_at=? WHERE upper(code)=?",
        (str(revoked_by), now, code_clean)
    )
    c.commit()
    return (cur.rowcount or 0) > 0


def list_all_codes(limit=50):
    rows = get_conn().execute(
        "SELECT * FROM redeem_codes ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


def get_live_player_stats(active_window_seconds=600):
    """Retrieve comprehensive live metrics of launcher presence and registered userbase.

    active_window_seconds: window (default 10 minutes / 600s) to consider a user active.
    """
    c = get_conn()
    now = int(time.time())
    cutoff = now - active_window_seconds

    # Total registered / linked users
    total_users_row = c.execute("SELECT COUNT(*) FROM users").fetchone()
    total_registered = total_users_row[0] if total_users_row else 0

    # Total unique device codes seen
    total_devices_row = c.execute("SELECT COUNT(DISTINCT device_code) FROM user_devices").fetchone()
    total_devices = total_devices_row[0] if total_devices_row else 0

    # Total active hardware bans
    total_bans_row = c.execute("SELECT COUNT(*) FROM banned_devices").fetchone()
    total_bans = total_bans_row[0] if total_bans_row else 0

    # Total active dedicated servers
    active_servers_row = c.execute("SELECT COUNT(*) FROM game_servers WHERE status = 'online'").fetchone()
    active_servers = active_servers_row[0] if active_servers_row else 0

    # Query all users who have active presence or were seen within active window
    active_rows = c.execute(
        """
        SELECT id, username, presence, presence_detail, presence_at, last_seen
        FROM users
        WHERE (
            (presence IN ('online', 'idle', 'in_game') AND (presence_at IS NULL OR presence_at >= ? OR last_seen >= ?))
            OR (presence_at >= ? OR last_seen >= ?)
        ) AND COALESCE(presence, '') != 'offline'
        ORDER BY COALESCE(presence_at, last_seen, 0) DESC
        """,
        (cutoff, cutoff, cutoff, cutoff)
    ).fetchall()

    playing_list = []
    in_launcher_list = []

    for row in active_rows:
        uid = row["id"]
        uname = row["username"] or f"User-{uid[:6]}"
        pres = (row["presence"] or "online").lower()
        detail = row["presence_detail"] or ""
        p_at = row["presence_at"] or row["last_seen"] or now

        user_info = {
            "id": uid,
            "username": uname,
            "presence": pres,
            "detail": detail,
            "active_at": p_at,
        }

        if pres in ("in_game", "playing") or "playing" in detail.lower():
            playing_list.append(user_info)
        else:
            in_launcher_list.append(user_info)

    total_online = len(playing_list) + len(in_launcher_list)
    total_offline = max(0, total_registered - total_online)

    # Also fetch recent registered users (up to 5) for quick overview
    recent_users = []
    recent_rows = c.execute(
        "SELECT id, username, last_seen FROM users ORDER BY last_seen DESC LIMIT 5"
    ).fetchall()
    for rr in recent_rows:
        recent_users.append({
            "id": rr["id"],
            "username": rr["username"] or f"User-{rr['id'][:6]}",
            "last_seen": rr["last_seen"] or 0
        })

    return {
        "total_registered": total_registered,
        "total_devices": total_devices,
        "total_bans": total_bans,
        "active_servers": active_servers,
        "total_online": total_online,
        "total_offline": total_offline,
        "playing_count": len(playing_list),
        "in_launcher_count": len(in_launcher_list),
        "playing_users": playing_list,
        "in_launcher_users": in_launcher_list,
        "recent_users": recent_users,
        "active_window_seconds": active_window_seconds,
        "timestamp": now,
    }




def sync_mutual_friends(user_id, mutual_ids):
    """Ensure accepted mutual friendships exist between user_id and all mutual_ids."""
    if not user_id or not mutual_ids:
        return 0
    c = get_conn()
    now = int(time.time())
    synced_count = 0
    for mid in mutual_ids:
        if not mid or str(mid) == str(user_id):
            continue
        existing = c.execute(
            "SELECT requester, addressee, status FROM friendships WHERE "
            "(requester=? AND addressee=?) OR (requester=? AND addressee=?)",
            (str(user_id), str(mid), str(mid), str(user_id))).fetchone()
        if existing:
            if existing["status"] != "accepted":
                c.execute("UPDATE friendships SET status='accepted' WHERE "
                          "(requester=? AND addressee=?) OR (requester=? AND addressee=?)",
                          (str(user_id), str(mid), str(mid), str(user_id)))
                synced_count += 1
        else:
            c.execute("INSERT INTO friendships (requester, addressee, status, created) "
                      "VALUES (?, ?, 'accepted', ?)", (str(user_id), str(mid), now))
            synced_count += 1
    c.commit()
    return synced_count

def get_all_users_except(user_id):
    """Get all registered users in the database except the given user ID."""
    c = get_conn()
    return c.execute("SELECT id, username, avatar_url, last_seen, presence, presence_at, presence_detail FROM users WHERE id!=?", (str(user_id),)).fetchall()
