#!/usr/bin/env python3
"""The browsing-lag regression test.

Mod / resource-pack browsing used to feel sticky because the Tk main thread did
the slow work itself: opening every mod jar for its name, walking every world
folder for its size, and - the worst one - a blocking icon download per search
result, one after another, before the list could paint.

This test runs the real widgets under a deliberately slow fake network and a
tripwire that fails if anything touches the network from the UI thread, and then
asserts:

  * opening the instance editor and starting a search return promptly;
  * the rows and results do arrive (icons, real mod names, counts);
  * repeat browsing is served from cache (no second request);
  * two widgets asking for the same icon cause exactly one download.

Run it headless:

    xvfb-run -a python3 tests/test_ui_lag.py
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import zipfile

_TMP = tempfile.mkdtemp(prefix="divine-lag-")
os.environ["XDG_DATA_HOME"] = os.path.join(_TMP, "data")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from PIL import Image                                   # noqa: E402
import customtkinter as ctk                              # noqa: E402

from arenclient import paths                             # noqa: E402
paths.ensure_dirs()
from arenclient.core import content_meta, instance_content, mod_manager   # noqa: E402
from arenclient.core import net, modrinth                # noqa: E402
from arenclient.core.instances import Instance, InstanceManager          # noqa: E402
from arenclient.ui import imagedesk                      # noqa: E402
from arenclient.ui.instance_editor import InstanceEditor  # noqa: E402
from arenclient.ui.mod_browser import ModBrowser          # noqa: E402

SLOW = 0.40                     # pretend Modrinth is having a bad day
HITS = 20
CALLS = []                      # ("json"|"file", url)
VIOLATIONS = []                 # anything the tripwires caught
MAIN = threading.main_thread()


def _tripwire(what):
    if threading.current_thread() is MAIN:
        VIOLATIONS.append("%s was called from the UI thread" % what)


def slow_get_json(url, params=None, **kw):
    _tripwire("modrinth API call")
    time.sleep(SLOW)
    CALLS.append(("json", url))
    if url.endswith("/search"):
        return {"hits": [{"project_id": "p%d" % i, "slug": "mod-%d" % i,
                          "title": "Mod %d" % i, "description": "makes it faster",
                          "author": "someone", "downloads": 1000 * i,
                          "icon_url": "https://cdn.test/i%d.png" % i,
                          "categories": []} for i in range(HITS)],
                "total_hits": HITS * 2}
    return {}


def slow_download(url, dest, **kw):
    _tripwire("icon download")
    time.sleep(SLOW)
    CALLS.append(("file", url))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    Image.new("RGBA", (16, 16), (56, 225, 208, 255)).save(dest)
    return dest


def _has_image(widget):
    """True if this Tk widget is currently showing an image."""
    try:
        return bool(widget.cget("image"))
    except Exception:
        return False


class FakeConfig(dict):
    def get(self, k, d=None):
        return dict.get(self, k, d)

    def set(self, k, v):
        self[k] = v

    def save(self):
        pass


class FakeApp(ctk.CTk):
    """The editor/browser are built with the launcher window as their master."""

    def __init__(self):
        super().__init__()
        self.config_store = FakeConfig(ram_mb=2048)
        self.instances = InstanceManager()
        self._inst = Instance({"id": "lagger", "name": "lagger", "mc_version": "1.20.4",
                               "loader": "fabric", "loader_version": None, "icon": "grass"})
        self.instances.instances = [self._inst]

    def get_versions(self):
        return [{"id": "1.20.4", "type": "release"}]

    def get_fabric_versions(self):
        return {"1.20.4"}


def seed_files(app, mods=12, worlds=3, packs=3):
    """Real jars / worlds / packs, so the code under test does its real work."""
    gd = app._inst.game_dir
    mods_dir = os.path.join(gd, "mods")
    os.makedirs(mods_dir, exist_ok=True)
    for i in range(mods):
        meta = {"id": "mod%d" % i, "name": "Real Name %d" % i, "version": "1.%d" % i,
                "description": "a mod that does something useful for players",
                "environment": "*"}
        path = os.path.join(mods_dir, "mod%d-1.jar" % i)
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("fabric.mod.json", json.dumps(meta))
            img = Image.new("RGBA", (32, 32), (155, 123, 255, 255))
            import io as _io
            buf = _io.BytesIO()
            img.save(buf, "PNG")
            z.writestr("assets/icon.png", buf.getvalue())
    saves = os.path.join(gd, "saves")
    for i in range(worlds):
        w = os.path.join(saves, "World %d" % i)
        os.makedirs(w, exist_ok=True)
        with open(os.path.join(w, "level.dat"), "wb") as f:
            f.write(b"\x00not real nbt")            # parses to nothing, still counted
        region = os.path.join(w, "region")
        os.makedirs(region, exist_ok=True)
        for r in range(30):                          # files to walk when sizing
            with open(os.path.join(region, "r.%d.0.mca" % r), "wb") as f:
                f.write(b"x" * 2048)
    rp = os.path.join(gd, "resourcepacks")
    os.makedirs(rp, exist_ok=True)
    for i in range(packs):
        path = os.path.join(rp, "pack%d.zip" % i)
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("pack.mcmeta", json.dumps({"pack": {"description": "pretty",
                                                            "pack_format": 22}}))
            import io as _io
            buf = _io.BytesIO()
            Image.new("RGBA", (64, 64), (75, 224, 138, 255)).save(buf, "PNG")
            z.writestr("pack.png", buf.getvalue())


def main():
    net.get_json = slow_get_json
    net.download = slow_download
    modrinth.net.get_json = slow_get_json          # same module object, be explicit
    modrinth.net.download = slow_download

    app = FakeApp()
    # The launcher installs the thread-safe `after` and starts its pump at boot
    # (ui/app.py); a harness that hands widgets to the image desk from a worker thread
    # has to do the same, or nothing that arrives off-thread is ever delivered.
    from arenclient.ui import post as _post_mod
    _post_mod.install()
    _post_mod.start(app)
    app.geometry("1000x700")
    seed_files(app)
    results = []
    repeat_at = [0]

    def ok(msg):
        results.append(("ok", msg))
        print("  ok -", msg)

    def fail(msg):
        results.append(("fail", msg))
        print("  FAIL -", msg)
    finished = [False]

    def guarded(fn):
        """An exception inside a Tk callback would otherwise be printed by Tk and
        leave mainloop() running forever, so every step reports and exits."""
        def inner(*a, **k):
            try:
                fn(*a, **k)
            except Exception as e:
                import traceback
                traceback.print_exc()
                fail("exception in %s: %r" % (getattr(fn, "__name__", "step"), e))
                finish()
        return inner

    def later(ms, fn, *args):
        if finished[0]:
            return
        app.after(ms, guarded(lambda: fn(*args)))

    def watchdog():
        if not finished[0]:
            fail("the test never reached a verdict (something hung)")
            finish()

    # What building 120 Tk frames costs on a quiet machine. Only used to scale the
    # editor budget below; measured on the box this runs on, so the number is not a
    # guess about someone else's laptop.
    CALIBRATION = 0.26

    def load_factor():
        """How slow Tk itself is right now, as a multiplier for the timing budget.

        The open-the-editor check is the only one in here that measures wall-clock,
        so a busy box can fail it for the wrong reason: with a real Minecraft server
        booting next to this test, Tk's own widget work alone pushed the editor from
        0.6s to 1.8s without anything blocking on I/O. A load-average reading is no
        help (a 1-minute average does not notice a build that started two seconds
        ago), so calibrate against the same kind of work instead - build a few dozen
        frames, time it, scale the budget. The UI-thread tripwire installed above is
        what actually proves nothing blocked, and it is not scaled by anything.
        """
        t0 = time.perf_counter()
        probes = [ctk.CTkFrame(app) for _ in range(120)]
        dt = time.perf_counter() - t0
        for f in probes:
            try:
                f.destroy()
            except Exception:
                pass
        return max(1.0, min(6.0, dt / CALIBRATION)) if dt > 0 else 1.0

    # ---------------------------------------------------------------- editor
    def step_editor():
        t0 = time.perf_counter()
        ed = InstanceEditor(app, app._inst)
        build_dt = time.perf_counter() - t0
        ed._show_section("mods")
        show_dt = time.perf_counter() - t0 - build_dt
        app._ed = ed
        budget = 1.0 * load_factor()
        if build_dt < budget:
            ok("editor with %d mods / %d worlds / %d packs built in %.2fs "
               "(slow network, nothing blocked; budget %.2fs on this load)"
               % (12, 3, 3, build_dt, budget))
        else:
            fail("editor took %.2fs to open (budget %.2fs) - something slow ran "
                 "on the UI thread" % (build_dt, budget))
        # rows exist immediately, before any of the slow work can have finished
        rows = len(ed.mods_list.winfo_children())
        if rows == 12:
            ok("all %d mod rows painted before the network finished" % rows)
        else:
            fail("expected 12 mod rows at once, got %d" % rows)
        titles = [ed._rows_by_path[p]["title"].cget("text") for p in ed._rows_by_path]
        if any(t.startswith("mod") for t in titles):
            ok("rows start with filename-derived names and enrich later")
        else:
            fail("expected filenames first, got %r" % titles[:3])

        def wait_enriched(deadline):
            if VIOLATIONS:
                fail("; ".join(sorted(set(VIOLATIONS))))
                return finish()
            titles = [ed._rows_by_path[p]["title"].cget("text")
                      for p in ed._rows_by_path] if ed._rows_by_path else []
            got = sum(1 for t in titles if t.startswith("Real Name"))
            icons = sum(1 for p, row in ed._rows_by_path.items()
                        if row["icon"].cget("image"))
            if got >= 12 and icons >= 12:
                ok("jar names + embedded icons arrived from the worker "
                   "(%d titles, %d icons)" % (got, icons))
                step_scroll_stability()
            elif time.time() > deadline:
                fail("enrichment stalled: %d/12 titles, %d/12 icons" % (got, icons))
                finish()
            else:
                later(150, wait_enriched, deadline)

        later(200, wait_enriched, time.time() + 12)

    # ------------------------------------------------------- scroll stability
    def geometry(list_attr="mods_list", table_attr="_rows_by_path"):
        ed = app._ed
        canvas = getattr(getattr(ed, list_attr, None), "_parent_canvas", None)
        table = getattr(ed, table_attr, {}) or {}
        heights = tuple(row["card"].winfo_height() for row in table.values())
        region = tuple(int(v) for v in str(canvas.cget("scrollregion")).split()) \
            if canvas is not None else ()
        return heights, region

    def step_scroll_stability():
        """A row being filled in must not move any other row, and must wait for the
        scroll to settle. This is the "visuals glitch when I scroll fast" bug: the
        Modrinth link used to be gridded into the card when the worker found it, so
        the card grew by a row and everything under the pointer jumped."""
        ed = app._ed
        canvas = getattr(ed.mods_list, "_parent_canvas", None)
        if canvas is None:
            fail("CTkScrollableFrame kept no canvas to watch - the gate is inert")
            return step_browser()
        before = geometry()
        link_row = list(ed._rows_by_path.values())[0]["link"]
        if link_row.winfo_manager() != "grid":
            fail("the Modrinth link is not reserved in the layout (found %r)"
                 % link_row.winfo_manager())
        else:
            ok("every row reserves its link slot, so filling it in cannot resize it")

        # the ugly case: a much longer name/description than the filename one
        gen = ed._gens.get("_rows_by_path", 1)
        long_title = "Sodium: Renderer Rewrite for Fabric (1.16.5-1.21.4, stable)"
        long_desc = ("Replaces the light pipeline and model builder of Minecraft with "
                     "much faster alternatives, and this description is deliberately "
                     "long enough that a wrapping label would grow the row.")
        updates = [(path, {"title": long_title, "desc": long_desc,
                           "url": "https://modrinth.com/mod/sodium"})
                   for path in list(ed._rows_by_path)]

        # hold the wheel down: keep moving the view while the updates arrive
        offset = 0.0
        for i in range(4):
            offset = (offset + 0.07) % 0.5
            canvas.yview_moveto(offset)
            ed._apply_updates(gen, "_rows_by_path", updates[:1] if i == 0 else updates)
            app.update()
        gate = ed._gates.get("_rows_by_path")
        texts = [row["title"].cget("text") for row in ed._rows_by_path.values()]
        if gate and gate.pending and not any(t.startswith("Sodium") for t in texts):
            ok("cosmetic row updates are held back while the list is scrolling "
               "(%d queued)" % gate.pending)
        else:
            fail("updates were applied mid-scroll (pending=%s, texts=%r)"
                 % (getattr(gate, "pending", None), texts[:2]))
        mid = geometry()

        def when_settled(deadline):
            texts = [row["title"].cget("text") for row in ed._rows_by_path.values()]
            done = sum(1 for t in texts if t.startswith("Sodium"))
            if done >= 12:
                after = geometry()
                if after[0] == before[0] and after[1] == before[1]:
                    ok("all 12 rows re-filled after the scroll settled with the "
                       "layout untouched (%d cards, %s px list, %d/%d pending)"
                       % (len(after[0]), after[1][3] if after[1] else "?",
                          app._ed._gates["_rows_by_path"].pending, 12))
                else:
                    fail("row geometry changed while enriching: heights %s -> %s, "
                         "scrollregion %s -> %s"
                         % (before[0][:4], after[0][:4], before[1], after[1]))
                step_browser()
            elif time.time() > deadline:
                fail("queued rows never got their text (%d/12 after settling)" % done)
                finish()
            else:
                later(60, when_settled, deadline)

        # the same trap in the resource-pack list: its Modrinth link used to be
        # gridded only when the match arrived, growing that card mid-scroll too
        packs = list(app._ed._pack_rows.values())
        if packs:
            before_p = geometry("packs_list", "_pack_rows")
            if packs[0].get("link") and packs[0]["link"].winfo_manager() == "grid":
                ok("pack rows reserve their link slot as well (%d cards, %s px)"
                   % (len(before_p[0]), before_p[1][3] if before_p[1] else "?"))
            else:
                fail("a pack row can still be resized from the worker (link not "
                     "gridded at build time)")
            gen = app._ed._gens.get("_pack_rows", 1)
            app._ed._apply_updates(gen, "_pack_rows", [
                (path, {"title": "A Really Long Resource Pack Name For Fabric 1.16.5 "
                                 "With Extra Words",
                        "desc": long_desc,
                        "url": "https://modrinth.com/texturepack/x"})
                for path in list(app._ed._pack_rows)])
            app._ed._flush_gates()
            app.update()
            after_p = geometry("packs_list", "_pack_rows")
            if after_p[0] == before_p[0] and after_p[1] == before_p[1]:
                ok("pack rows kept their geometry through the same enrichment "
                   "(%d cards at %s px)" % (len(after_p[0]),
                                            after_p[1][3] if after_p[1] else "?"))
            else:
                fail("pack rows moved while enriching: %s -> %s"
                     % (before_p[0], after_p[0]))

        # the pointer stops moving; the gate should flush on its own
        later(60, when_settled, time.time() + 4)

    # --------------------------------------------------------------- browser
    def step_browser():
        t0 = time.perf_counter()
        br = ModBrowser(app, app._inst, project_type="mod")
        open_dt = time.perf_counter() - t0
        app._br = br
        if open_dt < 1.0:
            ok("search window opened in %.2fs with the request still in flight"
               % open_dt)
        else:
            fail("opening the browser blocked for %.2fs" % open_dt)
        # nothing counted here: the first request is still in flight, so the cache
        # check below counts at the moment it repeats the same search

        def wait_cards(deadline):
            """Cards show at once; icons land as their (slow) downloads finish.

            Checking once would be a race against the fake 0.4s-per-icon network,
            so poll: cards first, then the images.
            """
            cards = len(br.results.winfo_children())
            # a CTkFrame owns its own canvas child, so look at every child for one
            # carrying an image instead of trusting index 0
            imgs = sum(1 for card in br.results.winfo_children()
                       if any(_has_image(ch) for ch in card.winfo_children()))
            if cards >= HITS and imgs >= HITS:
                ok("all %d result cards rendered in chunks" % cards)
                ok("%d/%d icons decoded off-thread and swapped in" % (imgs, cards))
                check_cache(br)
            elif time.time() > deadline:
                if cards >= HITS:
                    fail("cards painted but only %d/%d icons arrived" % (imgs, cards))
                else:
                    fail("only %d/%d cards rendered" % (cards, HITS))
                finish()
            else:
                later(150, wait_cards, deadline)

        later(200, wait_cards, time.time() + 30)

    def check_cache(br):
        # same query and same offset again: the cached wrapper means no new request
        repeat_at[0] = len([c for c in CALLS if c[0] == "json" and c[1].endswith("/search")])
        br._run_search(reset=True)
        later(700, _cache_done)

    def _cache_done():
        br = app._br
        json_after = len([c for c in CALLS if c[0] == "json" and c[1].endswith("/search")])
        if json_after == repeat_at[0]:
            ok("repeat search answered from cache (no extra HTTP call)")
        else:
            fail("repeat search hit the network %d more time(s)"
                 % (json_after - repeat_at[0]))
        # re-rendering the same rows must not re-download the same icons
        for card in br.results.winfo_children()[:5]:
            lbl = card.winfo_children()[0]
            imagedesk.DESK.show(lbl, "https://cdn.test/i0.png",
                                url="https://cdn.test/i0.png", size=(54, 54))
        later(400, check_dedupe)

    # ------------------------------------------------------------- desk checks
    def check_dedupe():
        a = ctk.CTkLabel(app, text="x")
        b = ctk.CTkLabel(app, text="y")
        url = "https://cdn.test/shared.png"
        before = len([c for c in CALLS if c[0] == "file" and c[1] == url])
        imagedesk.DESK.show(a, url, url=url, size=(46, 46))
        imagedesk.DESK.show(b, url, url=url, size=(46, 46))

        def wait_both(deadline):
            if a.cget("image") and b.cget("image"):
                after = len([c for c in CALLS if c[0] == "file" and c[1] == url])
                if after - before == 1:
                    ok("two labels asking for one icon caused exactly one download")
                    a.destroy(); b.destroy()
                    check_session_tab()
                else:
                    fail("%d downloads for one icon" % (after - before))
                    finish()
            elif time.time() > deadline:
                fail("shared icon never arrived (a=%r b=%r)" % (a.cget("image"),
                                                                b.cget("image")))
                finish()
            else:
                later(150, wait_both, deadline)

        later(150, wait_both, time.time() + 8)

    def check_session_tab():
        """The game window's Mods tab used to open every jar on the UI thread."""
        t0 = time.perf_counter()
        ed = app._ed
        # building the whole session window needs a live game, so exercise the
        # list path it uses instead
        try:
            mods = mod_manager.list_mods(os.path.join(ed.instance.game_dir, "mods"),
                                        with_meta=False)
            dt = time.perf_counter() - t0
            if len(mods) == 12 and all(m["name"].startswith("mod") for m in mods):
                ok("list_mods(with_meta=False) returned %d rows in %.3fs without "
                   "opening a jar" % (len(mods), dt))
            else:
                fail("fast listing returned %r" % (mods[:2],))
        except Exception as e:
            fail("fast listing raised %s" % e)
        full = mod_manager.list_mods(os.path.join(ed.instance.game_dir, "mods"))
        if full[0]["name"].startswith("Real Name"):
            ok("with_meta=True still reads the real names (%s)" % full[0]["name"])
        else:
            fail("metadata path broken: %r" % full[0])
        if net.session() is net.session():
            ok("one pooled HTTP session is reused")
        else:
            fail("session() is not shared")
        check_thread_report()

    def check_thread_report():
        if VIOLATIONS:
            fail("; ".join(sorted(set(VIOLATIONS))))
        else:
            ok("no network or file-decode work ever ran on the UI thread "
               "(%d API calls, %d downloads, all off-thread)"
               % (len([c for c in CALLS if c[0] == "json"]),
                  len([c for c in CALLS if c[0] == "file"])))
        finish()

    def finish():
        finished[0] = True
        try:
            app.after(50, app.quit)
        except Exception:
            pass

    later(300, step_editor)
    later(120000, watchdog)
    app.mainloop()

    bad = [r for r in results if r[0] == "fail"]
    shutil.rmtree(_TMP, ignore_errors=True)
    if bad:
        print("\nLAG REGRESSION TEST FAILED (%d ok, %d failed)"
              % (len(results) - len(bad), len(bad)))
        return 1
    print("\nLAG REGRESSION TEST PASSED (%d checks)" % len(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
