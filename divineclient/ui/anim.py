"""Animation helpers - and the switch that turns every one of them off.

The launcher's tweens were taken out in phase 9b: on a remote/virtual display (and on a
busy machine generally) they stutter, and a panel that animates its width while the middle
column reflows *looks* broken even when the result is correct. Rather than delete the
helpers - the colour and easing maths is still used, and an opt-in later is one line -
everything that repeats on a timer asks first:

    anim.enabled()      # False, and it stays that way unless a build asks otherwise

``Ticker.start()`` does nothing while the switch is off, so a widget that was built to
animate simply draws its final state instead. Nothing functional may live in a Ticker for
that reason: log streaming, polling and process watching use their own ``after`` loops,
which is why they survived the change untouched.

The switch is deliberately not a setting. There is a ``set_enabled`` because the tests
need to be able to say "and nothing moved", not because the user gets a checkbox.
"""


def _hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _rgb_to_hex(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(c)))) for c in rgb)


_ENABLED = False            # phase 9b default: no animation unless the user asks


def set_enabled(on):
    """Turn interface animation on or off, app-wide. Returns what was set."""
    global _ENABLED
    _ENABLED = bool(on)
    return _ENABLED


def enabled():
    return _ENABLED


def lerp(a, b, t):
    """Linear interpolate between two numbers."""
    return a + (b - a) * t


def lerp_color(c1, c2, t):
    """Blend two #rrggbb colours; t in 0..1."""
    r1, g1, b1 = _hex_to_rgb(c1)
    r2, g2, b2 = _hex_to_rgb(c2)
    return _rgb_to_hex((lerp(r1, r2, t), lerp(g1, g2, t), lerp(b1, b2, t)))


def ease_in_out(t):
    """Smooth 0..1 easing (cosine)."""
    import math
    return 0.5 - 0.5 * math.cos(math.pi * max(0.0, min(1.0, t)))


class Ticker:
    """A cancellable repeating step, driven by widget.after().

    step(frame) is called every `interval` ms with an increasing frame counter. Return
    False from step to stop. Safe to start/stop repeatedly; it stops quietly if the widget
    goes away. When animations are off, ``start()`` does nothing at all - the caller's
    final state is expected to have been drawn already, which is why no animation here is
    allowed to be the only thing that updates a widget.
    """

    def __init__(self, widget, step, interval=40):
        self.widget = widget
        self.step = step
        self.interval = interval
        self._job = None
        self._frame = 0
        self._running = False

    def start(self):
        if self._running or not _ENABLED:
            return
        self._running = True
        self._tick()

    def _tick(self):
        if not self._running:
            return
        try:
            keep = self.step(self._frame)
        except Exception:
            self._running = False
            return
        if keep is False:
            self._running = False
            return
        self._frame += 1
        try:
            self._job = self.widget.after(self.interval, self._tick)
        except Exception:
            self._running = False

    def stop(self):
        self._running = False
        job, self._job = self._job, None
        if job is not None:
            try:
                self.widget.after_cancel(job)
            except Exception:
                pass


class SmoothScroll:
    """Kept as a no-op so the pages can still call it.

    It used to take over the mouse wheel and glide the canvas to a target position, which
    is precisely the "the list jumps around when something changes" complaint: a glide
    toward a number computed before the rows resized lands somewhere else entirely. Native
    Tk scrolling cannot be wrong about that, so this class now binds nothing. The name
    stays because three pages construct it, and a no-op they can keep calling is cheaper
    than touching all of them.
    """

    active = False

    def __init__(self, scrollable, speed=0.12, friction=0.75):
        self.sf = scrollable
        self.canvas = getattr(scrollable, "_parent_canvas", None)

    def bind_child(self, widget):
        return

    def stop(self):
        return
