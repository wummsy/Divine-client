"""The Home page: play one thing, see what is running, read what is new, see your friends.

Phase 9b put the launcher back here. The redesign moved Launch into the menu rail, which
sounds good in a mockup and is terrible in practice: the button is tiny, it is in a panel
people keep closed, and there is no way to see which version it will start without opening
another tab. So the play card is the first thing on Home again, with a dropdown of
instances next to it - the one place a version is picked *and* started in the same click.

The right-hand column is the friends panel, embedded rather than sliding in from the edge
of the screen. The news feed is a plain list; it is fetched off-thread because the site is
allowed to be slow but the launcher is not.

Nothing in this file animates. The old version had a canvas behind the hero card drawing a
slow aurora, and a ticker to keep it moving; on a machine already busy starting a game that
stole frames from the things that mattered.
"""
import os
import threading

import customtkinter as ctk

from .. import theme
from ..friends_panel import FriendsPanel
from ..widgets import (
    Card, Gradient, PageFrame, accent_button, danger_button, flow_label,
    ghost_button, row, section_label, pill, scroll_frame,
    clip_to_width, text_width,
)

from ...core import news

try:
    from PIL import Image as _PILImage
except Exception:                                        # no Pillow: flat banner
    _PILImage = None

HERO = "assets/hero_bg.png"


def _cover(path, w, h):
    """The hero art, centre-cropped to the banner's box.

    Stretching a 1584x672 photo into a 4:1 strip bends the mountains and smears the
    aurora, and cropping blind cuts the sky off - so crop to the target aspect first and
    scale that. BILINEAR because this runs on the UI thread; it is deliberately the cheap
    filter, and it is called on a debounce, not on every pixel of a window drag.
    """
    if not (_PILImage and path):
        return None
    try:
        img = _PILImage.open(path).convert("RGB")
    except Exception:
        return None
    iw, ih = img.size
    if iw <= 0 or ih <= 0 or w <= 0 or h <= 0:
        return None
    target = float(w) / float(h)
    src = float(iw) / float(ih)
    if src > target:                        # too wide: take a vertical slice
        cw = int(round(ih * target))
        x0 = (iw - cw) // 2
        img = img.crop((x0, 0, x0 + cw, ih))
    else:                                   # too tall: keep the middle band
        ch = int(round(iw / target))
        y0 = max(0, (ih - ch) * 2 // 5)     # favour the top: that is where the sky is
        img = img.crop((0, y0, iw, min(ih, y0 + ch)))
    return img.resize((int(w), int(h)), _PILImage.BILINEAR)


# The right rail: the panel keeps its own height (_RAIL_PANEL_MIN is the floor under it, not a
# claim on space) and the news card is a guest that leaves when the column cannot hold it. The
# numbers are module constants because `_fit_rail`, the row configuration and the layout test
# all have to agree on them - the bug this is here to prevent is Tk quietly taking the height
# out of whichever row it likes, which left the friends list 62 px tall at the default size.
_RAIL_PANEL_MIN = 400
_RAIL_NEWS_MIN = 150

class Banner(Gradient):
    """The hero strip: the aurora art, the name, and how many things are up.

    The art is a *canvas image item*, not a label holding a ``CTkImage``. A label image is a
    rectangle Tk centres inside the label, so when the card is wider than the image the picture
    floats with a band of bare card beside it, and when it is narrower the picture is simply
    cut off at both ends - and a ``CTkImage`` additionally *scales* its picture to the widget,
    which is how a maximize ends up with a stretched banner for as long as the debounce takes.
    An item on the canvas is drawn at a fixed point, clipped by the canvas, and redrawn from
    its geometry on every expose, so the worst case is a slightly stale crop at the right size.
    """

    HEIGHT = 168

    def __init__(self, master, app):
        super().__init__(master, kind="main", corner_radius=16, border_width=0,
                         height=self.HEIGHT)
        self.app = app
        self._shown_w = 0
        self._job = None
        self._photo = None
        self.grid_propagate(False)
        self.configure(height=self.HEIGHT)
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        cv = self.art_canvas()
        if cv is not None:
            try:
                cv.create_image(2, 2, anchor="nw", image="", tags="divinecover")
            except Exception:
                pass

        # Written on the canvas, not as two labels. A label is its own Tk window and a Tk
        # window has to have *a* background - it cannot be "the photo behind me" - so a
        # caption over artwork is a grey box with words in it, which is what this was. Text
        # items sit on the same canvas as the picture, so they blend, they cannot flicker, and
        # they are redrawn from geometry on every expose like everything else here.
        self._has_caption = cv is not None
        self._caption = ("DIVINE CLIENT", "Your versions, your servers, your friends")
        if cv is not None:
            try:
                cv.create_text(26, self.HEIGHT - 46, anchor="sw", text="DIVINE CLIENT",
                               font=theme.title_font(26), fill="#ffffff", tags="divinehero")
                cv.create_text(26, self.HEIGHT - 22, anchor="sw",
                               text="Your versions, your servers, your friends",
                               font=theme.font(12), fill="#c9d3e6", tags="divinehero")
            except Exception:
                pass

        self.status_pill = pill(self, "nothing running", theme.COL["bg2"],
                                text_color="#c9d3e6")
        self.status_pill.grid(row=0, column=0, sticky="ne", padx=18, pady=16)
        self.bind("<Configure>", self._on_configure)

    def art_canvas(self):
        """CustomTkinter's own canvas, if this build of the library has one.

        Reached for with ``getattr`` on purpose - ``_canvas`` belongs to CTkFrame, not to this
        file, and a version of the library that renames it should leave the banner plain
        rather than raise inside a paint.
        """
        return getattr(self, "_canvas", None)

    def set_caption(self, title, subtitle=""):
        """Change the two lines on the art."""
        self._caption = (title or "", subtitle or "")
        self._apply_caption()

    def _apply_caption(self):
        """Draw the caption at the largest title size the card can actually hold.

        Two steps, in this order: shrink the type while the name does not fit, and only then
        ellipsise. A launcher hero that says "Fabric 1.21.11" at 20 px is a better sight than the
        same name truncated at 26 px, and neither is a clipped half-word.
        """
        cv = self.art_canvas()
        if cv is None:
            return
        title, subtitle = getattr(self, "_caption", ("", ""))
        room = max(120, int(self.winfo_width() or 0) - 2 * 26)
        size = 26
        while size > 16 and text_width(title, theme.title_font(size)) > room:
            size -= 1
        shown = clip_to_width(title, theme.title_font(size), room)
        sub = clip_to_width(subtitle, theme.font(12), room)
        try:
            items = cv.find_withtag("divinehero")
            if len(items) >= 2:
                cv.itemconfigure(items[0], text=shown, font=theme.title_font(size))
                cv.itemconfigure(items[1], text=sub)
            else:
                cv.delete("divinehero")
                cv.create_text(26, self.HEIGHT - 46, anchor="sw", text=shown,
                               font=theme.title_font(size), fill="#ffffff", tags="divinehero")
                if sub:
                    cv.create_text(26, self.HEIGHT - 22, anchor="sw", text=sub,
                                   font=theme.font(12), fill="#c9d3e6", tags="divinehero")
        except Exception:
            pass

    def _draw(self, no_color_updates=False):
        super()._draw(no_color_updates)
        cv = self.art_canvas()
        if cv is None:
            return
        try:
            # CustomTkinter redraws its own fill on a resize and my items are older than that
            # fill, so the order has to be asserted after every draw, not just the first
            cv.tag_lower("divinewash")
            cv.tag_raise("divinecover")
            cv.tag_raise("divinehero")
        except Exception:
            pass

    def _on_configure(self, event):
        w = max(1, int(event.width))
        if abs(w - self._shown_w) < 24:
            return                          # a two-pixel nudge is not a resize
        self._shown_w = w
        if self._job is not None:
            try:
                self.after_cancel(self._job)
            except Exception:
                pass
        # once per idle, not once per Configure and not on a timer: Tk is already going to
        # redraw at the end of this batch of events, so waiting for the idle moment costs no
        # visible delay while a drag cannot queue forty resizes of the same photo
        self._job = self.after_idle(lambda: self._paint(w))

    def _paint(self, width=None):
        self._job = None
        self._apply_caption()          # the room changed, so the fitting has to be redone
        from ... import paths
        w = int(width or self._shown_w or self.winfo_width() or 640)
        img = _cover(paths.resource_path(HERO), max(160, w - 4), self.HEIGHT - 4)
        if img is None:
            return
        try:
            from PIL import ImageTk
        except Exception:
            return
        cv = self.art_canvas()
        if cv is None:
            return
        try:
            self._photo = ImageTk.PhotoImage(img)
            cv.itemconfig("divinecover", image=self._photo)
        except Exception:
            self._photo = None

    def set_running(self, count, servers=0):
        bits = []
        if count:
            bits.append("%d game%s running" % (count, "" if count == 1 else "s"))
        if servers:
            bits.append("%d server%s up" % (servers, "" if servers == 1 else "s"))
        try:
            self.status_pill.configure(text="  \u00b7  ".join(bits) or "nothing running")
        except Exception:
            pass



class HomePage(PageFrame):
    def __init__(self, master, app):
        super().__init__(master, kind="page")
        self.app = app
        self._news_items = []
        self._news_loading = False

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Both of these are pure layout containers, so they get the page's colour out loud.
        # Left at CustomTkinter's default they paint the *theme's* grey over the whole page -
        # a full-size frame that covers the fill it is sitting on - and that is the grey band a
        # maximize used to leave behind: not a stale image, a wrapper that was never told what
        # colour it is.
        body = ctk.CTkFrame(self, fg_color=theme.COL["bg"], corner_radius=0, border_width=0)
        body.grid(row=0, column=0, sticky="nsew")
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, minsize=272)
        body.grid_rowconfigure(0, weight=1)

        left = ctk.CTkFrame(body, fg_color=theme.COL["bg"], corner_radius=0, border_width=0)
        left.grid(row=0, column=0, sticky="nsew", padx=(26, 12), pady=(20, 16))
        left.grid_columnconfigure(0, weight=1)
        left.grid_rowconfigure(2, weight=1)      # what is running takes the slack, not the fold

        # The right rail: friends on top, the site's news under it. News used to be the last row
        # of the left column, where a window of 780 px put it below the bottom edge of the page
        # with nothing to scroll it into view - content you cannot reach is a bug no colour can
        # talk you out of. Both of them fit in the rail down to the smallest window the app
        # allows, and the news box takes whatever height the rail has left.
        right = ctk.CTkFrame(body, fg_color=theme.COL["bg"], corner_radius=0, border_width=0)
        right.grid(row=0, column=1, sticky="nsew", padx=(0, 20), pady=(20, 16))
        right.grid_columnconfigure(0, weight=1)
        # Who gives way when the rail runs short. Tk's default is to shave whichever row it
        # feels like, which at 1240x780 used to leave the friends list 62 px tall: a list you
        # cannot read is not a smaller list, it is a broken one. So the panel owns the column
        # and is never given less than _RAIL_PANEL_MIN, and the news card - the only part of
        # Home a person can live without - is laid out only when the rail has that plus
        # _RAIL_NEWS_MIN. `_fit_rail` is the switch, and it is why nothing is clipped at 620 px.
        right.grid_rowconfigure(0, weight=0, minsize=_RAIL_PANEL_MIN)
        right.grid_rowconfigure(1, weight=1)

        # one card for "what am I launching" - the art on top, the picker and the button
        # underneath, in the same panel, clean centered Play block on its home screen
        self.play_card = Card(left, fg_color=theme.COL["bg2"], corner_radius=18)
        self.play_card.grid(row=0, column=0, sticky="ew")
        self.play_card.grid_columnconfigure(0, weight=1)
        self.banner = Banner(self.play_card, app)
        self.banner.grid(row=0, column=0, sticky="ew", padx=3, pady=3)
        self._build_play(self.play_card)
        self._build_running(left)
        self._build_news(right, 1)

        # Sized by what it holds and stopping there, because a friends list that reserves the
        # whole window height reads as an empty box.
        self.friends = FriendsPanel(right, app)
        self.friends.grid(row=0, column=0, sticky="n")
        self._rail = right
        right.bind("<Configure>", lambda e: self._fit_rail(), add="+")

        # one display of the launch flow: the card is the single place launch state shows
        try:
            app.flow.add_display(self)
        except Exception:
            pass

    # ------------------------------------------------------------- play card
    def _build_play(self, card):
        # ``card`` is the hero panel built in __init__, and the rows start at 1 because the
        # banner occupies row 0: the art and the launch controls are one object, so they are
        # one grid.

        section_label(card, "PLAY").grid(row=1, column=0, columnspan=2, sticky="w",
                                        padx=22, pady=(14, 0))
        self.play_title = flow_label(card, text="Pick an instance and go", wrap=520,
                                     font=theme.title_font(24),
                                     text_color=theme.COL["text"])
        self.play_title.grid(row=2, column=0, columnspan=2, sticky="w", padx=22,
                             pady=(2, 6))

        pick = ctk.CTkFrame(card)
        pick.grid(row=3, column=0, columnspan=2, sticky="ew", padx=22)
        pick.grid_columnconfigure(0, weight=1)
        self.inst_menu = ctk.CTkOptionMenu(pick, values=["No instances yet"],
                                           font=theme.font(14, "bold"), height=40,
                                           corner_radius=11,
                                           fg_color=theme.COL["bg3"],
                                           button_color=theme.COL["border"],
                                           button_hover_color=theme.COL["bg_hover"],
                                           dropdown_fg_color=theme.COL["bg2"],
                                           text_color=theme.COL["text"],
                                           command=self._pick_instance)
        self.inst_menu.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.play_btn = accent_button(pick, "\u25B6   Launch Game", self._launch_pressed,
                                      width=200, height=44)
        self.play_btn.grid(row=0, column=1, sticky="e")

        self.stop_btn = danger_button(card, "Stop", self._stop_pressed, width=120,
                                      height=32)
        self.stop_btn.grid(row=5, column=1, padx=(0, 22), pady=(8, 0))
        self.stop_btn.grid_remove()

        # The four numbers that make the choice real. The picker says which instance, the
        # button says go - between them is the thing people actually check: is this the modded
        # one, how much room does it take, when did I last play it. Computed off-thread by the
        # same function the instance cards use, so one folder cannot have two answers.
        meta = row(card, fg=theme.COL["bg3"])
        meta.grid(row=4, column=0, columnspan=2, sticky="ew", padx=22, pady=(12, 0))
        self._meta_cells = {}
        for i, (key, name) in enumerate((("mods", "MODS"), ("saves", "WORLDS"),
                                         ("size", "ON DISK"), ("when", "LAST PLAYED"))):
            meta.grid_columnconfigure(i, weight=1, uniform="meta")
            cell = ctk.CTkFrame(meta, fg_color=theme.COL["bg3"], corner_radius=0,
                                border_width=0)
            cell.grid(row=0, column=i, sticky="nsew", padx=(14 if i else 10, 10),
                      pady=(7, 8))
            ctk.CTkLabel(cell, text=name, font=theme.font(8, "bold"),
                         text_color=theme.COL["text_faint"], anchor="w"
                         ).grid(row=0, column=0, sticky="w")
            val = flow_label(cell, text="\u2014", min_px=52, font=theme.font(13, "bold"),
                             text_color=theme.COL["text"])
            val.grid(row=1, column=0, sticky="w", pady=(1, 0))
            self._meta_cells[key] = val

        self.play_summary = flow_label(card, text="", wrap=420, font=theme.font(11),
                                       text_color=theme.COL["text_dim"])
        self.play_summary.grid(row=5, column=0, sticky="w", padx=22, pady=(8, 0))

        self.bar = ctk.CTkProgressBar(card, height=8, corner_radius=4,
                                      progress_color=theme.COL["accent"],
                                      fg_color=theme.COL["bg3"])
        self.bar.grid(row=6, column=0, columnspan=2, sticky="ew", padx=22,
                      pady=(12, 0))
        self.bar.set(0.0)
        self.bar.grid_remove()

        self.status = ctk.CTkLabel(card, text="", anchor="w", justify="left",
                                   font=theme.font(11),
                                   text_color=theme.COL["text_dim"])
        self.status.grid(row=7, column=0, columnspan=2, sticky="w", padx=22,
                         pady=(6, 16))

        self._instances = []
        self._menu_by_id = {}
        self._meta_token = None
        self._busy = False

    def _build_running(self, parent):
        section_label(parent, "RUNNING NOW", glyph="ui_play").grid(
            row=1, column=0, sticky="w", padx=4, pady=(18, 4))
        self.running_card = Card(parent, fg_color=theme.COL["bg2"], corner_radius=14)
        self.running_card.grid(row=2, column=0, sticky="nsew")
        self.running_card.grid_columnconfigure(0, weight=1)
        self.running_lbl = ctk.CTkLabel(self.running_card, text="Nothing is running.",
                                       anchor="w", font=theme.font(12),
                                       text_color=theme.COL["text_dim"], justify="left")
        self.running_lbl.grid(row=0, column=0, sticky="ew", padx=18, pady=14)

    def _fit_rail(self):
        """Put the news card in the rail if the rail can actually hold it.

        Home is not a scrolling page, so a row that does not fit is not "below the fold", it is
        cut off - and half a card looks exactly like a rendering bug. The rail keeps the friends
        panel whole and drops the news instead: somebody resizing the window small is trying to
        work in it, not read a headline.
        """
        head = getattr(self, "news_head", None)
        if head is None or not hasattr(self, "_rail"):
            return
        try:
            room = self._rail.winfo_height() - self.friends.winfo_reqheight()
            if room >= _RAIL_NEWS_MIN and not head.winfo_manager():
                head.grid()
            elif room < _RAIL_NEWS_MIN and head.winfo_manager():
                head.grid_remove()
        except Exception:
            pass

    def _build_news(self, parent, row=3):
        head = self.news_head = ctk.CTkFrame(parent)
        head.grid(row=row, column=0, sticky="nsew", pady=(12, 0))
        head.grid_columnconfigure(0, weight=1)
        head.grid_rowconfigure(1, weight=1)
        box = Card(head, fg_color=theme.COL["bg2"], corner_radius=14)
        box.grid(row=0, column=0, sticky="nsew")
        box.grid_columnconfigure(0, weight=1)
        box.grid_rowconfigure(1, weight=1)
        top = ctk.CTkFrame(box)
        top.grid(row=0, column=0, sticky="ew", padx=18, pady=(14, 0))
        top.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(top, text="NEWS", font=theme.font(10, "bold"),
                     text_color=theme.COL["text_faint"], anchor="w"
                     ).grid(row=0, column=0, sticky="w")
        ghost_button(top, "Refresh", lambda: self.refresh_news(force=True), width=92,
                     height=28).grid(row=0, column=1, sticky="e")
        self.news_scroll = scroll_frame(box,
                                                 scrollbar_button_color="#22283d",
                                                 scrollbar_button_hover_color="#333c5c")
        self.news_scroll.grid(row=1, column=0, sticky="nsew", padx=10, pady=(6, 10))
        self.news_scroll.grid_columnconfigure(0, weight=1)
        self._news_row = 0
        self._render_news(["Loading the news\u2026"])
        self.refresh_news()

    def _render_news(self, lines=None):
        for w in self.news_scroll.winfo_children():
            w.destroy()
        self._news_row = 0
        if lines:
            for text in lines:
                flow_label(self.news_scroll, text=text, anchor="w", justify="left",
                             font=theme.font(12), text_color=theme.COL["text_dim"]).grid(row=self._news_row, column=0,
                                                  sticky="ew", padx=8, pady=3)
                self._news_row += 1
        for item in self._news_items:
            self._news_row = self._news_card(item)
        if not self._news_items and not lines:
            flow_label(self.news_scroll, text="The site did not answer. Nothing here "
                                                "depends on it.", anchor="w",
                         justify="left", font=theme.font(12),
                         text_color=theme.COL["text_faint"]).grid(row=0, column=0, sticky="ew", padx=8, pady=8)

    def _news_card(self, item):
        row = self._news_row
        card = Card(self.news_scroll, fg_color="#10151f", corner_radius=12)
        card.grid(row=row, column=0, sticky="ew", padx=4, pady=4)
        card.grid_columnconfigure(0, weight=1)
        tag = (item.get("tag") or "").strip()
        title = item.get("title") or "(untitled)"
        flow_label(card, text=title, anchor="w", font=theme.font(13, "bold"),
                     text_color=theme.COL["text"], justify="left").grid(row=0, column=0, sticky="ew", padx=14, pady=(10, 0))
        if tag:
            ctk.CTkLabel(card, text=tag.upper(), font=theme.font(9, "bold"),
                         fg_color=theme.COL["accent"], text_color="#04121a",
                         corner_radius=6, padx=7, pady=1
                         ).grid(row=0, column=1, sticky="ne", padx=(0, 12), pady=(10, 0))
        body = (item.get("body") or "").strip()
        if body:
            flow_label(card, text=body[:300], anchor="w", justify="left",
                         font=theme.font(11), text_color=theme.COL["text_dim"]).grid(row=1, column=0, columnspan=2, sticky="ew",
                                              padx=14, pady=(2, 4))
        url = (item.get("url") or "").strip()
        if url:
            ctk.CTkLabel(card, text="Open \u2197", font=theme.font(10, "bold"),
                         text_color=theme.COL["accent"], cursor="hand2"
                         ).grid(row=2, column=0, sticky="w", padx=14, pady=(0, 10))
            card.bind("<Button-1>", lambda e, u=url: self._open_url(u))
        else:
            ctk.CTkFrame(card, height=6).grid(
                row=2, column=0, sticky="w")
        return row + 1

    def _open_url(self, url):
        import webbrowser
        try:
            webbrowser.open(url)
        except Exception:
            pass

    # --------------------------------------------------------------- refresh
    def refresh(self):
        self.refresh_instances()
        self.refresh_running()

    def on_show(self):
        self.refresh()
        try:
            self.friends.refresh()
        except Exception:
            pass

    def on_hide(self):
        pass

    def refresh_instances(self):
        """Fill the dropdown from the instance manager and keep the flow's choice."""
        try:
            self.app.instances.load()
            self._instances = list(self.app.instances.instances or [])
        except Exception:
            self._instances = []
        names = []
        self._menu_by_id = {}
        for inst in self._instances:
            label = inst.name
            n = 1
            base = label
            while label in names:
                n += 1
                label = "%s (%d)" % (base, n)
            names.append(label)
            self._menu_by_id[label] = inst.id
        try:
            selected = self.app.flow.selected()
        except Exception:
            selected = None
        if not names:
            names = ["No instances yet"]
            self._menu_by_id[names[0]] = None
        self.inst_menu.configure(values=names)
        if selected is not None:
            for label, iid in self._menu_by_id.items():
                if iid == selected.id:
                    self.inst_menu.set(label)
                    break
            self._describe(selected)
        else:
            self.inst_menu.set(names[0])
            self._describe(None)

    def _describe(self, inst):
        if inst is None:
            self.play_summary.configure(text="Nothing to launch yet \u2014 make an instance "
                                             "on the Instances page.")
            self.play_title.configure(text="No instance selected")
            self._meta_load(None)
            return
        loader = "Fabric" if inst.loader == "fabric" else "Vanilla"
        lv = getattr(inst, "loader_version", "") or ""
        if lv:
            loader += " " + lv
        self.play_title.configure(text=inst.name)
        self._meta_load(inst)
        self.play_summary.configure(text="Minecraft %s  \u00b7  %s  \u00b7  folder %s"
                                   % (inst.mc_version, loader,
                                      os.path.basename(inst.game_dir or "") or "\u2014"))

    def _meta_load(self, inst):
        """Count the selected instance's files in a worker, then paint the four cells.

        A folder walk on the UI thread is the one thing that would make this panel slower than
        it looks, so it runs beside it. Two guards matter: only the newest request may paint,
        because clicking through five instances fast would otherwise end with the third one's
        mod count next to the fifth one's name; and the values are flow labels, because
        "3 weeks ago" is longer than a quarter of the panel.
        """
        if inst is None:
            self._meta_token = None
            for lbl in self._meta_cells.values():
                try:
                    lbl.configure(text="\u2014")
                except Exception:
                    pass
            return
        token = getattr(inst, "id", None)
        self._meta_token = token
        import threading
        from .instances_page import count_instance

        def work():
            data = count_instance(inst)
            try:
                self.after(0, lambda: self._meta_paint(token, data))
            except Exception:
                pass        # the page is gone; nobody is waiting for the numbers

        threading.Thread(target=work, daemon=True).start()

    def _meta_paint(self, token, data):
        if token is not None and token != getattr(self, "_meta_token", None):
            return
        mb = int(data.get("size") or 0)
        when = (data.get("when") or "never") or "never"
        vals = {"mods": "%d" % int(data.get("mods") or 0),
                "saves": "%d" % int(data.get("saves") or 0),
                "size": ("%d MB" % mb) if mb < 1024 else ("%.1f GB" % (mb / 1024.0)),
                "when": "never" if when in ("", "never") else when}
        for key, text in vals.items():
            lbl = self._meta_cells.get(key)
            if lbl is not None:
                try:
                    lbl.configure(text=text)
                except Exception:
                    pass

    def _pick_instance(self, label):
        iid = self._menu_by_id.get(label)
        if not iid:
            return
        for inst in self._instances:
            if inst.id == iid:
                try:
                    self.app.flow.select(inst)
                except Exception:
                    pass
                self._describe(inst)
                break

    def refresh_running(self):
        lines = []
        try:
            procs = dict(self.app.running_procs or {})
        except Exception:
            procs = {}
        for iid, plist in procs.items():
            alive = [p for p in plist if getattr(p, "poll", lambda: 0)() is None]
            if not alive:
                continue
            inst = None
            try:
                inst = self.app.instances.get(iid)
            except Exception:
                inst = None
            name = getattr(inst, "name", iid[:8])
            pid = ", ".join(str(getattr(p, "pid", "?")) for p in alive)
            lines.append("\u25CF  %s   \u00b7   pid %s" % (name, pid))
        try:
            n_servers = self.app.servers.running_count()
        except Exception:
            n_servers = 0
        if n_servers:
            lines.append("\u2601  %d hosted server%s running"
                         % (n_servers, "" if n_servers == 1 else "s"))
        if not lines:
            self.running_lbl.configure(text="Nothing is running.")
        else:
            self.running_lbl.configure(text="\n".join(lines))
        try:
            self.banner.set_running(self.app.total_running(), n_servers)
        except Exception:
            pass

    # ----------------------------------------------------------- flow display
    # LaunchFlow calls these on whatever object it has been given a display of; they are
    # all optional, and every one of them must survive being called on a half-built page.
    def set_selected(self, inst):
        try:
            self.refresh_instances()
        except Exception:
            pass
        try:
            if inst is None:
                self.banner.set_caption("DIVINE CLIENT",
                                        "Your versions, your servers, your friends")
            else:
                self.banner.set_caption(
                    inst.name, "Minecraft %s  \u00b7  %s%s" % (
                        inst.mc_version, "Fabric" if inst.loader == "fabric" else "Vanilla",
                        ""))
        except Exception:
            pass
        self._sync_lock()

    def refresh_locks(self):
        """Called by the flow when the number of live games changes."""
        self._sync_lock()

    def _sync_lock(self):
        """Grey out Launch while *another* instance is up, and write the reason on it.

        The button is not hidden and the page does not pop a dialog: a dimmed button with a
        sentence under it can be read without clicking it, and it cannot be missed the way a
        modal can be dismissed by reflex.
        """
        locked = False
        try:
            locked = bool(self.app.flow.locked_for(self.app.flow.selected()))
        except Exception:
            locked = False
        try:
            if locked and not self._busy:
                self.play_btn.configure(state="disabled",
                                        text="\u25B6  Another game is open")
                self.status.configure(text="Divine runs one instance at a time. Stop the open "
                                           "game and this button works again.",
                                      text_color=theme.COL["warn"])
            elif not self._busy:
                self.play_btn.configure(state="normal", text="\u25B6   Launch Game")
        except Exception:
            pass

    def set_state(self, busy, running, text=""):
        self._busy = bool(busy)
        try:
            if busy:
                self.play_btn.configure(text="Starting\u2026", state="disabled")
                self.bar.grid()
                self.bar.set(0.0)
            else:
                self.play_btn.configure(text="\u25B6   Launch Game", state="normal")
                if not running:
                    self.bar.grid_remove()
                    self.bar.set(0.0)
            if running:
                self.stop_btn.grid()
                self.status.configure(text=text or "The game is up.",
                                      text_color=theme.COL["good"])
            else:
                self.stop_btn.grid_remove()
                if text:
                    self.status.configure(text=text, text_color=theme.COL["text_dim"])
        except Exception:
            pass
        self._sync_lock()

    def set_progress(self, frac, status=""):
        try:
            self.bar.grid()
            self.bar.set(max(0.0, min(1.0, float(frac))))
            if status:
                self.status.configure(text=status, text_color=theme.COL["text_dim"])
        except Exception:
            pass

    def launch_error(self, msg):
        try:
            self.status.configure(text=msg or "Launch failed.",
                                  text_color=theme.COL["danger"])
            self.bar.grid_remove()
        except Exception:
            pass

    # --------------------------------------------------------------- buttons
    def _launch_pressed(self):
        try:
            self.app.flow.launch()
        except Exception as exc:
            self.launch_error(str(exc))

    def _stop_pressed(self):
        try:
            self.app.flow.stop()
        except Exception as exc:
            self.status.configure(text=str(exc), text_color=theme.COL["danger"])
        self.refresh_running()

    # --------------------------------------------------------------- news
    def refresh_news(self, force=False):
        if self._news_loading:
            return
        self._news_loading = True

        def work():
            try:
                items = news.get_news(self.app.config_store, force=force) or []
            except Exception as exc:
                items = []
                err = str(exc)
            else:
                err = ""
            self._news_loading = False
            try:
                self.app.after(0, lambda: self._news_ready(items, err))
            except Exception:
                pass
        threading.Thread(target=work, daemon=True).start()

    def _news_ready(self, items, err=""):
        self._news_items = list(items or [])[:6]
        if not self._news_items and err:
            self._render_news(["News could not be loaded: %s" % err[:120]])
            return
        self._render_news()

    def destroy(self):
        try:
            self.app.flow.remove_display(self)
        except Exception:
            pass
        super().destroy()
