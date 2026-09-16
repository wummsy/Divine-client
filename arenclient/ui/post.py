"""Thread-safe hand-off back to the Tk main loop.

Python's tkinter refuses to register a Tcl callback from any thread except the one that
owns the interpreter: ``widget.after(0, fn)`` from a worker thread raises
``RuntimeError: main thread is not in main loop``. The launcher calls it from worker
threads in a dozen places - version lists, news, the update download, Java detection,
the per-card file counts - and every one of those calls sits inside a ``try/except``
that keeps the app alive. So the exception was swallowed and the *result never arrived*:
the loading screen sat at 0%, Home kept saying "Checking for news...", and a card's
mod count never showed.

Fixing it once here, at ``tkinter.Misc``, means no call site has to remember which
thread it is in, and third-party widgets get the same protection. On the main thread
everything behaves exactly as before; from any other thread the callback is queued and
run by the main loop a few dozen times a second.
"""
import queue
import threading
import tkinter as tk

_Q = queue.Queue()
_TOKENS = {}
_installed = False
_running = False

_MAX_PER_DRAIN = 48        # keep each pass short so the UI stays responsive


def install():
    """Patch tkinter so ``after``/``after_idle`` are safe to call from a worker thread."""
    global _installed
    if _installed:
        return
    _installed = True

    real_after = tk.Misc.after
    real_idle = tk.Misc.after_idle
    real_cancel = tk.Misc.after_cancel
    main_thread = threading.main_thread()

    def _queue_call(func, args):
        token = [False]                       # [cancelled]
        key = id(token)
        _TOKENS[key] = token

        def run():
            _TOKENS.pop(key, None)
            if not token[0]:
                func(*args)

        _Q.put(run)
        return ("divine-queued", key)

    def after(self, ms=None, func=None, *args):
        if func is not None and self is not None and threading.current_thread() is not main_thread:
            return _queue_call(func, args)
        try:
            return real_after(self, ms, func, *args) if func is not None else real_after(self, ms)
        except (RuntimeError, tk.TclError):
            return _queue_call(func or (lambda: None), args)

    def after_idle(self, func=None, *args):
        if func is not None and threading.current_thread() is not main_thread:
            return _queue_call(func, args)
        try:
            return real_idle(self, func, *args) if func is not None else real_idle(self)
        except (RuntimeError, tk.TclError):
            return _queue_call(func or (lambda: None), args)

    def after_cancel(self, id):
        if isinstance(id, tuple) and id and id[0] == "divine-queued":
            token = _TOKENS.get(id[1])
            if token is not None:
                token[0] = True             # the drain will drop it instead of running it
            return
        if threading.current_thread() is not main_thread:
            return                          # cancelling on Tcl from here is not allowed
        try:
            return real_cancel(self, id)
        except tk.TclError:
            return

    tk.Misc.after = after
    tk.Misc.after_idle = after_idle
    tk.Misc.after_cancel = after_cancel


def post(func, *args):
    """Run ``func(*args)`` on the main thread, from anywhere. Explicit version of the patch."""
    if threading.current_thread() is threading.main_thread():
        try:
            func(*args)
        except Exception:
            pass
        return
    _Q.put(lambda: func(*args))


def start(widget):
    """Begin draining the queue. Called once by the app, on the main thread."""
    global _running
    if _running:
        return
    _running = True

    def drain():
        global _running
        done = 0
        while done < _MAX_PER_DRAIN:
            try:
                fn = _Q.get_nowait()
            except queue.Empty:
                break
            done += 1
            try:
                fn()
            except Exception:
                pass        # one broken callback must not stop the others, or the loop
        try:
            if widget.winfo_exists():
                widget.after(45, drain)
            else:
                _running = False
        except Exception:
            _running = False

    drain()
