"""Build the shippable archives.

    python3 tools/make_release_zip.py [output.zip]

Two artifacts, one command, because the order matters: `server/` is zipped up first and
dropped in the project root as `divine-server.zip`, then the whole project is zipped with
that file inside it. A user who unzips the outer archive has the launcher *and* the
server panel they are told to deploy, in one file.

Everything in both archives is stored under a fixed 1980 timestamp and mode 0644, so two
builds of the same tree produce the same bytes and a diff of two zips means the code
actually changed. Junk that must never ship: caches, build output, screenshots, logs, and
any database file (the panel's `divine.db` holds accounts and pairings from testing).
"""
import io
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))     # the project
EXCLUDE_DIRS = {"__pycache__", ".git", "build", "dist", "node_modules", ".venv",
                "shots", ".pytest_cache", ".idea", ".vscode",
                # Gradle's own scratch space, and the runClient folder a mod build makes.
                # Without these a built mod's caches ride along in the release.
                ".gradle", ".kotlin", "run"}
EXCLUDE_SUFFIX = (".pyc", ".log", ".tmp", ".db", ".db-shm", ".db-wal", ".sqlite",
                  ".sqlite3", ".egg-info")
EXCLUDE_NAMES = {".DS_Store"}
#: dev-only screenshots, by pattern - naming them one by one meant the next one shipped
EXCLUDE_PREFIX = ("preview_", "shot", "_s10_", "tmp_")
# fixed so the archive is reproducible
STAMP = (1980, 1, 2, 0, 0, 0)


def _wants(rel):
    parts = rel.split("/")
    if any(p in EXCLUDE_DIRS for p in parts[:-1]):
        return False
    name = parts[-1]
    if name in EXCLUDE_NAMES or name.startswith(EXCLUDE_PREFIX):
        return False
    if name.endswith(".zip") and name != "divine-server.zip":
        return False
    low = name.lower()
    if any(low.endswith(s) for s in EXCLUDE_SUFFIX):
        return False
    if ".db" in low and not low.endswith((".md", ".py")):
        return False
    return True


def _add(zf, src, arcname):
    with open(src, "rb") as f:
        data = f.read()
    info = zipfile.ZipInfo(arcname, date_time=STAMP)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    zf.writestr(info, data)


def build_inner(server_dir, dest_path):
    """Zip server/ into dest_path (bytes written to disk), rooted at the archive top."""
    buf = io.BytesIO()
    count = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(server_dir):
            dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDE_DIRS)
            for name in sorted(filenames):
                full = os.path.join(dirpath, name)
                rel = os.path.relpath(full, server_dir).replace(os.sep, "/")
                if not _wants(rel):
                    continue
                _add(zf, full, rel)
                count += 1
    data = buf.getvalue()
    with open(dest_path, "wb") as f:
        f.write(data)
    return count, len(data)


def build_outer(project=ROOT, out="/home/user/i-hopr-fixed.zip", prefix="divine-client/"):
    inner_count, inner_bytes = build_inner(os.path.join(project, "server"),
                                          os.path.join(project, "divine-server.zip"))
    files = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(project):
            dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDE_DIRS)
            for name in sorted(filenames):
                full = os.path.join(dirpath, name)
                rel = os.path.relpath(full, project).replace(os.sep, "/")
                if not _wants(rel):
                    continue
                _add(zf, full, prefix + rel)
                files += 1
    with zipfile.ZipFile(out) as zf:
        bad = zf.testzip()
    size = os.path.getsize(out)
    print("%s: %d files, %.1f MB  (inner divine-server.zip: %d files, %d KB)%s"
          % (out, files, size / 1048576.0, inner_count, inner_bytes // 1024,
             "" if bad is None else "  BROKEN ENTRY: " + bad))
    if bad is not None:
        return 1
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1:
        sys.exit(build_outer(out=sys.argv[1]))
    sys.exit(build_outer())
