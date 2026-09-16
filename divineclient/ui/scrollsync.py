"""Don't repaint rows underneath a scroll that is still moving.

Two things used to happen together in the mod/pack lists, and they are what looks
like "the visuals glitch for a second" when you wheel fast:

* worker results landing mid-scroll changed row geometry (a Modrinth link appearing
  added a third grid row, a longer name widened the column), so every row below the
  pointer jumped while the list was still moving;
* even with geometry fixed, CustomTkinter rows are real windows inside a scrolled
  canvas: Tk scrolls that by copying pixels and repositioning the child windows, so
  a repaint issued between two wheel events shows up as a half-updated strip.

The fix here is deliberately boring: anything urgent (the scroll itself) is left
completely alone, and anything cosmetic (row text, icons, links) waits until the
view has been still for ~140 ms and is then applied in one pass. Nothing is dropped
and nothing is lost - a queued update is applied on settle, on tab switch, or on
close, whichever comes first.

The "is it scrolling" question is answered by watching the canvas' yview rather than
by binding mouse-wheel events: the wheel, a dragged scrollbar, PageUp, a touchpad
and a programmatic `yview_moveto` all move that number, and no binding order or
CTk version detail can hide one of them.
"""

POLL_MS = 45              # how often the view position is sampled while waiting
SETTLE_MS = 140           # ...and how long it must sit still before we repaint


class Gate:
    """Queue cosmetic UI work while a scrolled view is moving."""

    def __init__(self, owner, canvas=None, poll_ms=POLL_MS, settle_ms=SETTLE_MS):
        self._owner = owner                  # any widget with after()/after_cancel()
        self._canvas = canvas
        self._poll = max(10, int(poll_ms))
        self._ticks = max(2, int(settle_ms) // self._poll)
        self._pending = {}
        self._job = None
        self._pos = None
        self._still = 0
        self._closed = False

    # ------------------------------------------------------------- watching
    def _position(self):
        if self._canvas is None:
            return None
        try:
            return self._canvas.yview()[0]
        except Exception:
            return None                       # destroyed / no scroll range yet

    def moving(self):
        """True if the view has shifted since we last looked."""
        pos = self._position()
        moved = pos != self._pos
        self._pos = pos
        return moved

    # ------------------------------------------------------------ submitting
    def submit(self, key, fn):
        """Apply `fn` now, or as soon as the view settles.

        `key` collapses repeat requests about the same row: the queue is a dict, so
        three updates for one card during a long scroll cost one repaint.
        """
        if self._closed:
            return
        if not self._pending and not self.moving():
            self._run(fn)
            return
        self._pending[key] = fn
        if self._job is None:
            self._still = 0
            try:
                self._job = self._owner.after(self._poll, self._tick)
            except Exception:
                self._pending.clear()         # no mainloop: drop, don't raise

    def _run(self, fn):
        try:
            fn()
        except Exception:
            pass        # a row destroyed between the worker and now is normal

    def _tick(self):
        self._job = None
        if self._closed or not self._pending:
            return
        if self.moving():
            self._still = 0
        else:
            self._still += 1
        if self._still < self._ticks:
            try:
                self._job = self._owner.after(self._poll, self._tick)
            except Exception:
                return
            return
        self.apply_now()

    def apply_now(self):
        """Flush the queue immediately (tab switch, list rebuild, window close)."""
        if self._job is not None:
            try:
                self._owner.after_cancel(self._job)
            except Exception:
                pass
            self._job = None
        todo, self._pending = self._pending, {}
        for fn in todo.values():
            self._run(fn)

    def clear(self):
        """Forget anything queued - the rows they refer to are gone."""
        if self._job is not None:
            try:
                self._owner.after_cancel(self._job)
            except Exception:
                pass
            self._job = None
        self._pending.clear()
        self._pos = self._position()

    def close(self):
        self._closed = True
        self.clear()

    # ------------------------------------------------------------- internals
    @property
    def pending(self):
        return len(self._pending)
