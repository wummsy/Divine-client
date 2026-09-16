"""Background image loading for mod / resource-pack lists and search results.

Why this exists: building a search page used to do, per row, a blocking
`requests.get()` for the project icon plus a PIL decode - inside the Tk main
loop. Twenty results meant twenty sequential network round-trips with the UI
thread blocked, which is exactly the "lag when I search for a mod" report. Same
shape in the instance editor: every jar was opened again for its embedded icon,
and every enriched row spawned its own thread to fetch a remote one.

Now: rows are painted immediately with a letter tile, and this desk fills in
icons on three shared worker threads, with a decoded-image cache so scrolling
back or reopening the window is instant. Never call `requests` from the UI
thread for a thumbnail.
"""
import os
import queue
import threading

import customtkinter as ctk

try:
    from PIL import Image
    _HAS_PIL = True
except Exception:
    _HAS_PIL = False

from ..core import net

CACHE_LIMIT = 400


def _fit(img, size):
    """Scale to `size` keeping the aspect ratio, centred on a transparent tile.

    Stretching a wide logo into a square looks bad, and cropping it hides the
    part that identifies the mod, so pad instead.
    """
    w, h = size
    tile = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    img = img.convert("RGBA")
    img.thumbnail((w, h), Image.LANCZOS)
    x = (w - img.width) // 2
    y = (h - img.height) // 2
    tile.paste(img, (x, y), img)
    return tile


class ImageDesk:
    def __init__(self, workers=3):
        self._q = queue.Queue()
        self._n = workers
        self._threads = []
        self._lock = threading.Lock()
        self._images = {}                 # key -> CTkImage (decoded, ready)
        self._pil = {}                    # key -> PIL image, pre-Tk (built off-thread)
        self._order = []                  # insertion order for eviction
        self._pending = {}                # key -> [ (label, size) ]
        self._started = False
        self.jobs = 0                     # stats, used by the tests
        self.downloads = 0

    # ------------------------------------------------------------------ setup
    def _start(self):
        with self._lock:
            if self._started:
                return
            self._started = True
            for i in range(self._n):
                t = threading.Thread(target=self._run, name="imagedesk%d" % i,
                                     daemon=True)
                t.start()
                self._threads.append(t)

    # ----------------------------------------------------------------- public
    def show(self, label, key, path=None, url=None, size=(46, 46)):
        """Give `label` the image for `key` as soon as it is ready.

        `path` is a local file, `url` something to fetch into the cache first.
        Returns True when it was applied synchronously (already in the cache),
        False when it is still coming.
        """
        if not key or not _HAS_PIL:
            return False
        self._start()
        cached = self._cached(key, size)
        if cached is not None:
            self._apply(label, cached)
            return True
        with self._lock:
            waiting = self._pending.setdefault(key, [])
            waiting.append((label, size))
            fresh = len(waiting) == 1
            if fresh:
                self._q.put((key, path, url, size))
        return False

    def has(self, key, size=(46, 46)):
        return self._cached(key, size) is not None

    def wait_idle(self, timeout=10.0):
        """Block until every queued job has been worked off (tests, and the
        startup cache-prime). Callbacks are already posted by then; the caller
        still has to pump the Tk event loop for them to run."""
        import time
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._q.unfinished_tasks == 0:
                return True
            time.sleep(0.02)
        return False

    # ---------------------------------------------------------------- worker
    def _run(self):
        while True:
            key, path, url, size = self._q.get()
            try:
                self._work(key, path, url, size)
            except Exception:
                pass
            finally:
                self._q.task_done()

    def _work(self, key, path, url, size):
        self.jobs += 1
        local = path
        if local and not os.path.exists(local):
            local = None
        if local is None and url:
            dest = net.cached_path(url, _cache_dir())
            if os.path.exists(dest) and os.path.getsize(dest) > 0:
                local = dest
            else:
                local = net.download(url, dest)
                self.downloads += 1
        if not local or not os.path.exists(local):
            self._finish(key, None)
            return
        try:
            with Image.open(local) as img:
                img.load()
                fitted = _fit(img, size)
        except Exception:
            fitted = None
        self._finish(key, fitted)

    def _finish(self, key, pil_img):
        with self._lock:
            targets = self._pending.pop(key, [])
            if pil_img is not None:
                self._pil[key] = pil_img
        # CTkImage touches Tk, so build it on the main thread
        for label, size in targets:
            _post(label, lambda l=label, k=key, s=size: self._deliver(l, k, s))

    def _deliver(self, label, key, size):
        img = self._cached(key, size)
        if img is None:
            pil = self._pil.get(key)
            if pil is None:
                return
            img = ctk.CTkImage(light_image=pil, dark_image=pil, size=size)
            with self._lock:
                self._images[key] = img
                self._order.append(key)
                if len(self._order) > CACHE_LIMIT:
                    for old in self._order[:len(self._order) // 3]:
                        self._images.pop(old, None)
                        self._pil.pop(old, None)
                        try:
                            self._order.remove(old)
                        except ValueError:
                            pass
        self._apply(label, img)

    def _cached(self, key, size):
        with self._lock:
            return self._images.get(key)

    def _apply(self, label, img):
        def do():
            try:
                if label.winfo_exists():
                    label.configure(image=img, text="")
            except Exception:
                pass
        _post(label, do)

    def clear(self):
        with self._lock:
            self._images.clear()
            self._pil.clear()
            self._order = []
            self._pending = {}


def _post(widget, fn):
    """Run `fn` on the UI thread if `widget` is still alive.

    The existence check has to happen *there*, not here: `winfo_exists()` is a Tcl call,
    and Tcl answers a call from a worker thread with `RuntimeError: main thread is not in
    main loop` whenever the UI thread happens to be inside its event loop - which is
    exactly when a finished download gets delivered. That exception used to be swallowed by
    the `except` below, so an icon that was ready was simply never shown, and the bug only
    appeared under load (a friend list refreshing, a page of search results), never in a
    quiet test.

    So: hand the work to ui.post, which knows how to queue across threads, and check the
    widget once we are back on the main thread.
    """
    from . import post as _post_mod

    def safe():
        try:
            if widget.winfo_exists():
                fn()
        except Exception:
            pass        # a window closed mid-delivery has nowhere to put the image

    try:
        if threading.current_thread() is threading.main_thread():
            widget.after(0, safe)      # the loop is right here, no need for the queue
            return
        _post_mod.post(safe)           # off-thread: only the queue may carry it
    except Exception:
        pass


_CACHE_DIR = None


def _cache_dir():
    global _CACHE_DIR
    if _CACHE_DIR is None:
        from .. import paths
        _CACHE_DIR = os.path.join(paths.DATA_DIR, "cache", "content_icons")
    return _CACHE_DIR


DESK = ImageDesk()
