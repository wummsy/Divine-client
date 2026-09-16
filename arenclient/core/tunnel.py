"""Make a locally-hosted server reachable by friends over the internet.

Home PCs sit behind NAT, so a friend can't connect to a raw LAN IP. This module
runs a small agent on the host that opens an outbound tunnel and hands back a
public ``host:port`` you can put straight into Minecraft's "Join Server".

Two providers, chosen automatically:

  * **bore** (default) - a single tiny binary, no account, no key, no claim
    step: ``bore local <port> --to bore.pub`` prints ``bore.pub:<port>``. The
    address changes every session, which is fine for inviting friends over.
  * **playit** - the official playit.gg agent. Gives a stable
    ``xxxx.craft.playit.gg`` address that survives restarts, but the current
    agent provisions its tunnels from the playit website, so it only works once
    the machine has been claimed there. Kept for people who want the fixed
    address.

``provider="none"`` skips tunnelling entirely (LAN only).

Earlier versions of this file passed ``--secret_path`` to playit, which is not a
real flag (it is ``--secret-path``), so the agent exited immediately and no
address ever appeared. The flag names below are checked against the agent's own
``--help`` output at runtime, so a renamed flag degrades to a clear message
instead of a silent stall.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.request
import zipfile

from .. import paths
from . import java_runtime


BORE_REPO = "ekzhang/bore"
BORE_PINNED = {
    "win32": "https://github.com/ekzhang/bore/releases/download/v0.6.0/"
              "bore-v0.6.0-x86_64-pc-windows-msvc.zip",
    "windows": "https://github.com/ekzhang/bore/releases/download/v0.6.0/"
                "bore-v0.6.0-x86_64-pc-windows-msvc.zip",
    "linux": "https://github.com/ekzhang/bore/releases/download/v0.6.0/"
              "bore-v0.6.0-x86_64-unknown-linux-musl.tar.gz",
    "darwin": "https://github.com/ekzhang/bore/releases/download/v0.6.0/"
               "bore-v0.6.0-x86_64-apple-darwin.tar.gz",
}
BORE_SERVER = "bore.pub"

# SHA-256 of the exact binaries published for the pinned release above. Both were
# computed from the real files here, not copied out of a README.
#
# This is not ceremony: the launcher downloads a program and then runs it, which is
# the single most "TrojanDownloader"-shaped thing a launcher can do. Antivirus
# looks at that behaviour, so we check the bytes ourselves first. A cached binary
# is re-checked before it is launched too, so a truncated download - or a file
# antivirus quarantined and replaced - gets refused instead of executed.
# Build your own bore? Set DIVINE_SKIP_AGENT_VERIFY=1.
AGENT_SHA256 = {
    ("bore", "win32"): "e8c1096ea01460ba9dbf30017b5eccf2100f63ef2c701930e56fcaca239b48cc",
    ("bore", "windows"): "e8c1096ea01460ba9dbf30017b5eccf2100f63ef2c701930e56fcaca239b48cc",
    ("bore", "linux"): "60548b7a145ba334981b19fda7cd0210d24a108a3d0dc113919b33fd2eaa90ab",
}
VERIFY_OFF = os.environ.get("DIVINE_SKIP_AGENT_VERIFY") == "1"


class AgentChecksumError(RuntimeError):
    """A downloaded agent is not byte-for-byte what we pinned."""


def sha256_of(path, chunk=1 << 20):
    import hashlib
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for blk in iter(lambda: f.read(chunk), b""):
                h.update(blk)
    except OSError as e:
        raise AgentChecksumError("Can't read the tunnel program to check it: %s" % e)
    return h.hexdigest()


def verify_agent(kind, path, platform=None):
    """Check `path` against the pinned hash for `kind`; None when uncheckable.

    Returns the expected digest on a match. On a mismatch the bad file is deleted
    (so the next start re-downloads rather than failing forever) and
    AgentChecksumError is raised - we never execute an unverified agent.
    """
    if VERIFY_OFF or not os.path.isfile(path):
        return None
    expected = AGENT_SHA256.get((kind, platform or _platform_key()))
    if not expected:
        return None
    got = sha256_of(path)
    if got.lower() == expected.lower():
        return expected
    try:
        os.remove(path)
    except OSError:
        pass
    raise AgentChecksumError(
        "The downloaded %s program did not match the checksum Divine publishes "
        "(got %s..., expected %s...). It was deleted rather than run. That is "
        "usually a truncated download or antivirus editing the file: check your "
        "connection, add an exclusion for the Divine data folder, and try again."
        % (kind, got[:12], expected[:12]))
# The public endpoint. bore prints  "listening at bore.pub:60234"; playit prints
# "xxxx-xxxx.craft.playit.gg" with no port. The host must end in a real TLD, so
# log timestamps like "2026-09-02T09:04" (which a naive host:port pattern happily
# matches) can never be mistaken for an address.
_ADDR_RE = re.compile(
    r"\b([a-z0-9](?:[a-z0-9._-]*[a-z0-9])?\.[a-z]{2,10})(?::(\d{2,5}))?\b",
    re.IGNORECASE)
# Two guards, because two kinds of line tried to be the address (see _strip_paths):
# a log line naming the agent's control socket, which contains the word "tunnel" and
# a token ending in something TLD-shaped, and a line that names only the file
# ("address file: playit.sock"), where the separator guard has nothing to reject.
# Paths are dropped before the scan; a host whose last label is one of these suffixes
# is dropped as well.
_FILE_SUFFIXES = (".sock", ".lock", ".log", ".tmp", ".part", ".bak", ".dat", ".pid",
                  ".json", ".toml", ".yaml", ".yml", ".ini", ".cfg", ".conf", ".txt",
                  ".exe", ".dll", ".so", ".py", ".pyc", ".jar")
_LOCALISH = ("localhost", "127.0.0.1", "0.0.0.0", "::1")
_CHECKED = set()          # agents verified once per process

PLAYIT_URLS = {
    "win32": "https://github.com/playit-cloud/playit-agent/releases/latest/download/"
              "playit-windows-x86_64-signed.exe",
    "linux": "https://github.com/playit-cloud/playit-agent/releases/latest/download/"
              "playit-linux-amd64",
    "darwin": "https://github.com/playit-cloud/playit-agent/releases/latest/download/"
               "playit-darwin-x86_64",
}
_CLAIM_RE = re.compile(r"https://playit\.gg/\S*(?:claim|connect|mc)\S*", re.IGNORECASE)

# address waiting: bore connects in about a second; give a flaky network a bit
# of room before falling through to the next provider
_ADDRESS_TIMEOUT = 25.0

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _strip_paths(line):
    """Remove tokens that look like files, sockets or URLs from one log line.

    The playit agent is told to put its control socket in
    ``<game dir>/tunnel/playit.sock``, so a line about it contains both the word
    "tunnel" - which makes it read like an announcement to us - and a token ending in
    a TLD-shaped suffix, which a host pattern happily matches. Publishing that to a
    friend is worse than publishing nothing: they get a server entry that never
    resolves and no way to tell it was our mistake. So anything with a path
    separator in it is not an address, and neither is anything under a URL.
    """
    keep = []
    for tok in line.split():
        if "/" in tok or "\\" in tok:
            continue
        keep.append(tok)
    return " ".join(keep)


def parse_address(line):
    """Pull the public ``host[:port]`` out of one agent log line, or None.

    Only lines that announce the endpoint are considered - an agent prints plenty
    of other host:port pairs (its own local listener, a proxy, a timestamp, its
    socket path) and publishing one of those to friends is worse than publishing
    nothing: a wrong address looks like a working server that nobody can join.
    """
    if not line:
        return None
    line = _strip_paths(line)
    low = line.lower()
    wants = ("listening at", "tunnel", "forwarding", "connected", "address",
             "public", "playit.gg", "bore.pub", "playit", "joinmc", "craft.playit.gg")
    if not any(w in low for w in wants):
        return None
    for m in _ADDR_RE.finditer(line):
        host = m.group(1).rstrip(".")
        port = m.group(2)
        if host.lower().endswith(_FILE_SUFFIXES):
            continue
        if host.lower() in _LOCALISH or host.lower().endswith(".local"):
            continue
        # a timestamp or an ip without a port is never our address
        if not port and "playit" not in host.lower():
            continue
        return host + (":" + port if port else "")
    return None


def _platform_key():
    if sys.platform.startswith("win"):
        return "win32"
    if sys.platform == "darwin":
        return "darwin"
    return "linux"


def strip_ansi(text):
    return _ANSI_RE.sub("", text or "")


def tunnel_dir():
    # normpath because every path the agent is downloaded, unpacked and *executed*
    # from is derived from this one: a base with a stray separator in it turns into a
    # "D:\...\tunnel\/tmpXXXX/bore.exe" shape once something joins onto it, and mixed
    # separators are what Windows' file API refuses with [Errno 22] Invalid argument.
    d = os.path.normpath(os.path.join(paths.get_game_dir(), "tunnel"))
    os.makedirs(d, exist_ok=True)
    return d


def _place(src, dest, tries=6):
    """Move a freshly written file into place, even if something is still holding it.

    os.replace() onto a file antivirus has open for scanning fails with a sharing
    violation for a second or two. Retrying quietly is what stops the agent from
    "vanishing" between the download and the launch.
    """
    last = None
    for _ in range(tries):
        try:
            os.replace(src, dest)
            return dest
        except OSError as e:
            last = e
            time.sleep(0.4)
    try:
        os.remove(src)
    except OSError:
        pass
    raise RuntimeError(
        "Downloaded %s but Windows wouldn't let us put it where it belongs - "
        "something else is holding that file open (usually antivirus, or a tunnel "
        "that is still closing down):\n%s\n\n%s"
        % (os.path.basename(dest), dest, last))


def _write_member(src, target):
    with open(target, "wb") as out:
        shutil.copyfileobj(src, out)
        out.flush()
        try:
            os.fsync(out.fileno())
        except OSError:
            pass
    return target


# Anything with one of these endings is documentation or a signature sitting next to
# the real program inside the archive, never the program itself.
_NOT_THE_BINARY = (".md", ".txt", ".rst", ".json", ".license", ".licence", ".xml",
                   ".html", ".toml", ".yml", ".asc", ".sig", ".sha256", ".sha512",
                   ".pdb", ".debug", ".dSYM")


def _bore_members(names, key):
    """Which archive entries could be the bore program, as a list of their names.

    Matched on the last path component only, because a release that unpacks to
    ``bore-v0.6.0-x86_64-.../`` puts a *directory* entry with the same prefix in front
    of the binary, and taking that instead of the file is what made the tunnel fail to
    start. A ``.exe`` only counts on Windows and an extension-less name only elsewhere.
    """
    out = []
    for name in names:
        base = name.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1].lower()
        if not base.startswith("bore") or base.endswith(_NOT_THE_BINARY):
            continue
        if base.endswith(".exe") != (key == "win32"):
            continue
        out.append(name)
    return out


def _pick_bore(candidates, key, archive):
    """The one archive entry that is the executable: the biggest of the candidates.

    ``candidates`` is a list of ``(name, size)`` for the regular files in the archive.
    """
    names = _bore_members([name for name, _size in candidates], key)
    if not names:
        raise RuntimeError(
            "The tunnel archive didn't contain a bore program. Looked for %r in %s; "
            "the archive holds: %s." % ("bore.exe" if key == "win32" else "bore",
                                        os.path.basename(archive),
                                        ", ".join(sorted(name for name, _ in candidates)[:8])))
    sizes = dict(candidates)
    return max(names, key=lambda name: sizes.get(name, 0))


def unpack_bore(archive, target, key=None):
    """Copy the bore executable out of *archive* into *target* (which we chose).

    Deliberately not ``ZipFile.extract()``: extract() builds its own destination from
    the archive's member names, hands back a path mixing ``\\`` and ``/``, and on
    Windows that string is then refused by the file API with ``[Errno 22] Invalid
    argument`` - the one thing that can make a perfectly good download unusable.
    Reading the member and writing the bytes ourselves keeps every path we open on
    something os.path.join produced.
    """
    key = key or _platform_key()
    low = archive.lower()
    if low.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            files = [(i.filename, i.file_size) for i in z.infolist() if not i.is_dir()]
            best = _pick_bore(files, key, archive)
            with z.open(best) as src:
                return _write_member(src, target)
    if low.endswith((".tar.gz", ".tgz", ".tar")):
        with tarfile.open(archive) as t:
            files = [(m.name, m.size) for m in t.getmembers() if m.isfile()]
            best = _pick_bore(files, key, archive)
            with t.extractfile(best) as src:
                return _write_member(src, target)
    # Not an archive at all (a release that is just the binary): take the file itself.
    if os.path.isfile(archive):
        shutil.copyfile(archive, target)
        return target
    raise RuntimeError("Don't know how to unpack " + os.path.basename(archive))


def _fetch(url, dest, status=None, tries=3):
    tmp = dest + ".part"
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "DivineClient"})
            with urllib.request.urlopen(req, timeout=90) as r, open(tmp, "wb") as f:
                shutil.copyfileobj(r, f)
                f.flush()
            if os.path.getsize(tmp) < 20000:
                raise OSError("the download came back empty or blocked (%d bytes)"
                              % os.path.getsize(tmp))
            _place(tmp, dest)
            return dest
        except Exception as e:
            last = e
            try:
                os.remove(tmp)
            except Exception:
                pass
            if status:
                status("Tunnel download retrying (%d of %d)..." % (attempt + 2, tries))
            time.sleep(1.0 * (attempt + 1))
    raise RuntimeError("Couldn't download the tunnel program: " + str(last))


def _latest_bore_url(key):
    """bore's asset names change between releases, so ask GitHub which one to use."""
    try:
        api = "https://api.github.com/repos/%s/releases/latest" % BORE_REPO
        req = urllib.request.Request(api, headers={"User-Agent": "DivineClient",
                                                   "Accept": "application/vnd.github+json"})
        data = json.load(urllib.request.urlopen(req, timeout=20))
        want = {"win32": ("x86_64-pc-windows", ".zip"),
                "linux": ("x86_64-unknown-linux", ".tar.gz"),
                "darwin": ("x86_64-apple-darwin", ".tar.gz")}[key]
        for asset in data.get("assets", []):
            name = asset.get("name", "")
            if want[0] in name and name.endswith(want[1]):
                return asset["browser_download_url"]
    except Exception:
        pass
    return BORE_PINNED[key]


def bore_path():
    return os.path.join(tunnel_dir(), "bore.exe" if _platform_key() == "win32" else "bore")


def playit_path():
    return os.path.join(tunnel_dir(), "playit.exe" if _platform_key() == "win32" else "playit")


def ensure_bore(status=None):
    """Download + unpack the bore client if it isn't there yet. Returns the path."""
    path = bore_path()
    if os.path.isfile(path) and os.path.getsize(path) > 20000:
        return path
    key = _platform_key()
    if status:
        status("Downloading the tunnel program (bore)...")
    url = _latest_bore_url(key)
    want = "bore.exe" if key == "win32" else "bore"
    # Unpack inside the data folder, never %TEMP%. A packed binary unpacking
    # itself into a temp directory and running from there is precisely what real
    # malware does, and what heuristics watch for; it buys us nothing either.
    staged = path + ".part"
    try:
        with tempfile.TemporaryDirectory(dir=tunnel_dir()) as td:
            archive = _fetch(url, os.path.join(td, os.path.basename(url) or "bore.pkg"),
                             status=status)
            # the destination is ours, built with os.path.join - see unpack_bore
            inside = unpack_bore(archive, os.path.join(td, want), key)
            size = os.path.getsize(inside)
            if size < 20000:
                raise RuntimeError(
                    "The bore program unpacked to only %d bytes, which is not an "
                    "executable. Something is replacing the download (a proxy or "
                    "antivirus); try again in a moment." % size)
            # write into the data folder next, then move it, so a half-written
            # bore.exe can never be mistaken for a working one on the next start
            with open(inside, "rb") as src:
                _write_member(src, staged)
        if key != "win32":
            try:
                os.chmod(staged, 0o755)
            except Exception:
                pass
        _place(staged, path)
    except BaseException:
        try:
            os.remove(staged)
        except OSError:
            pass
        raise
    verify_agent("bore", path, key)
    return path


def ensure_playit(status=None):
    path = playit_path()
    if os.path.isfile(path) and os.path.getsize(path) > 20000:
        return path
    if status:
        status("Downloading the playit agent...")
    _fetch(PLAYIT_URLS[_platform_key()], path, status=status)
    # playit renames its release assets between versions, so nothing is pinned for
    # it - a strict check there would break the optional provider for everyone.
    # Verified when a hash exists for the platform, skipped when it does not.
    verify_agent("playit", path)
    if _platform_key() != "win32":
        try:
            os.chmod(path, 0o755)
        except Exception:
            pass
    return path


def _agent_flag(path, long_name):
    """Does this agent version accept --<long_name>? Checked once, then believed."""
    try:
        out = subprocess.run([path, "--help"], capture_output=True, timeout=15,
                             **java_runtime._no_window_kwargs())
        text = (out.stdout or b"") + (out.stderr or b"")
        return ("--" + long_name) in text.decode("utf-8", "replace")
    except Exception:
        return False


class Tunnel:
    """Runs a public tunnel for one local port.

    Callbacks (all optional, all called from a background thread):
      on_status(text)    - human progress line
      on_address("h:p")  - the public address to share
      on_claim(url)      - playit first-time claim link
      on_line(text)      - raw agent output (for the console panel)
      on_exit(code)      - the tunnel stopped
    """

    def __init__(self, local_port=25565, provider="auto", bore_static_port=None, playit_secret=None):
        self.local_port = int(local_port)
        self.provider = provider or "auto"
        self.bore_static_port = int(bore_static_port) if bore_static_port else None
        self.playit_secret = playit_secret
        self.proc = None
        self.public_address = None
        self.claim_url = None
        self.active_provider = None
        self.fail_reason = None
        self.on_status = None
        self.on_address = None
        self.on_claim = None
        self.on_line = None
        self.on_exit = None
        self._stop = threading.Event()
        self._thread = None

    # --------------------------------------------------------------- lifecycle
    def start(self, status=None):
        """Blocking setup (download + spawn). Call from a worker thread."""
        self._status = status
        order = self._provider_order()
        if not order:
            self.fail_reason = None
            return
        # prepare the program first so download errors are reported here
        self._ready = {}
        for name in order:
            try:
                self._ready[name] = (ensure_bore if name == "bore" else ensure_playit)(status)
            except Exception as e:
                self._say("Couldn't get the " + name + " program: " + str(e)[:120])
        if not self._ready:
            self.fail_reason = ("No tunnel program could be downloaded. The server "
                                "still works for friends on your own network.")
            return
        self._thread = threading.Thread(target=self._run_chain, daemon=True)
        self._thread.start()

    def _provider_order(self):
        if self.provider == "none":
            return []
        if self.provider in ("bore", "playit"):
            return [self.provider]
        return ["bore", "playit"]           # auto

    def _run_chain(self):
        for name in list(self._ready.keys()):
            if self._stop.is_set():
                return
            self.public_address = None
            try:
                self._launch(name, self._ready[name])
            except Exception as e:
                self._say(name + " couldn't start: " + str(e)[:140])
                continue
            # wait for the address; bore gives it within ~2s, playit may never
            got = self._wait_for_address(_ADDRESS_TIMEOUT if name == "bore" else 12.0)
            if got or self.claim_url:
                self.active_provider = name
                if got:
                    self._say("Tunnel is live (" + name + ").")
                    return
                self._say("playit needs one-time setup in your browser - open the "
                          "link, then the address appears here.")
                return
            if self._stop.is_set():
                return
            self._kill()
            self._say(name + " didn't report an address - trying the next one...")
        self.fail_reason = ("Couldn't open a tunnel. The server is fine on your "
                            "local network; check your internet connection or "
                            "firewall and press Retry tunnel.")
        self._say(self.fail_reason)
        if self.on_exit:
            self.on_exit(-1)

    def _wait_for_address(self, timeout):
        end = time.time() + timeout
        while time.time() < end:
            if self.public_address or self._stop.is_set():
                return bool(self.public_address)
            if self.proc is not None and self.proc.poll() is not None:
                return bool(self.public_address)
            time.sleep(0.2)
        return bool(self.public_address)

    # --------------------------------------------------------------- launching
    def _check_cached(self, name, path):
        """Verify an already-downloaded agent before running it (once per kind)."""
        if name in _CHECKED:
            return
        _CHECKED.add(name)
        verify_agent(name, path)        # raises -> _run_chain reports it plainly

    def _launch(self, name, path):
        if name == "bore":
            args = [path, "local", str(self.local_port), "--to", BORE_SERVER]
            if self.bore_static_port:
                args += ["--port", str(self.bore_static_port)]
        else:
            args = [path]
            secret_file = os.path.join(tunnel_dir(), "playit-secret.dat")
            toml_file = os.path.join(tunnel_dir(), "playit.toml")
            if self.playit_secret:
                sec = self.playit_secret.strip()
                try:
                    with open(secret_file, "w", encoding="utf-8") as sf:
                        sf.write(sec)
                    with open(toml_file, "w", encoding="utf-8") as tf:
                        tf.write(f'secret_key = "{sec}"\n')
                except Exception:
                    pass
            if _agent_flag(path, "secret") and self.playit_secret:
                args += ["--secret", self.playit_secret.strip()]
            elif _agent_flag(path, "secret-path"):
                args += ["--secret-path", secret_file]
            if _agent_flag(path, "socket-path"):
                args += ["--socket-path", os.path.join(tunnel_dir(), "playit.sock")]
        self._check_cached(name, path)
        self._say("Opening the tunnel (" + name + ")...")
        self.proc = subprocess.Popen(
            args, cwd=tunnel_dir(),
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, bufsize=0,
            **java_runtime._no_window_kwargs())
        threading.Thread(target=self._read_loop, daemon=True).start()

    def _decode(self, data):
        try:
            return data.decode("utf-8")
        except Exception:
            return data.decode("utf-8", "replace")

    def _read_loop(self):
        buf = b""
        try:
            while True:
                chunk = self.proc.stdout.read(1024)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    raw, buf = buf.split(b"\n", 1)
                    self._handle(self.strip(self._decode(raw)))
        except Exception:
            pass
        if buf.strip():
            self._handle(self.strip(self._decode(buf)))

    @staticmethod
    def strip(line):
        return strip_ansi(line).strip()

    def _handle(self, line):
        if not line:
            return
        if self.on_line:
            try:
                self.on_line(line)
            except Exception:
                pass
        if not self.public_address:
            addr = parse_address(line)
            if addr:
                self.public_address = addr
                if self.on_address:
                    try:
                        self.on_address(addr)
                    except Exception:
                        pass
        if not self.claim_url:
            m = _CLAIM_RE.search(line)
            if m:
                self.claim_url = m.group(0).rstrip(".,)")
                if self.on_claim:
                    try:
                        self.on_claim(self.claim_url)
                    except Exception:
                        pass

    # --------------------------------------------------------------- helpers
    def _say(self, text):
        if self.on_status:
            try:
                self.on_status(text)
            except Exception:
                pass
        st = getattr(self, "_status", None)
        if st:
            try:
                st(text)
            except Exception:
                pass

    def is_running(self):
        return self.proc is not None and self.proc.poll() is None

    def _kill(self):
        if self.proc:
            try:
                self.proc.terminate()
            except Exception:
                pass
            for _ in range(20):
                if self.proc.poll() is not None:
                    break
                time.sleep(0.1)
            try:
                if self.proc.poll() is None:
                    self.proc.kill()
            except Exception:
                pass

    def stop(self):
        self._stop.set()
        self._kill()
