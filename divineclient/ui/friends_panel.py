"""The friends panel: who is in Minecraft right now.

Phase 9b moved this from a sliding right-hand rail into a plain panel inside the Home
page - the data and the colours are unchanged, only the way it is attached to the window.

Three states, three colours, exactly as asked:

  * **bright green** - they are in Minecraft right now (the launcher tells the site
    when a game starts, so this is "playing", not "Discord is open");
  * **orange** - idle: their launcher or Discord is around but no game is up;
  * **black** - offline. On a dark panel pure black is invisible, so the name goes to
    the dimmest shade the theme can still find and the dot goes near-black. The point of
    the colour is "they are not there", not "you cannot read this".

The search bar filters the list as you type - names, the game they are in, and the
server address of anyone hosting.

One thing the rail version got wrong quietly: ``_avatar`` used ``os`` without importing it,
so every avatar raised NameError, was swallowed by the bare except, and nobody ever saw a
picture. The import is here now, and the fetch itself moved to ``ui.imagedesk`` - pulling a
Discord CDN image while the list is being built blocks the whole window, which is the same
mistake the mod browser was fixed for. Rows paint instantly with a letter tile and the
picture replaces it when it arrives.

The **Link Discord** button lives here rather than only in Settings, because this is the
screen where you notice you cannot see anybody: pressing it runs the same link flow the
settings page uses and refreshes the list when the browser part finishes.
"""
import json
import os
import threading

import customtkinter as ctk

from .. import paths
from ..core import social
from . import theme
from .discord_link import DiscordLinkDialog
from .imagedesk import ImageDesk
from .widgets import (Card, accent_button, danger_button, flow_label, ghost_button,
                     load_glyph, load_image_file, scroll_frame)

_REFRESH_MS = 45000        # the site also refreshes our own last_seen on every call


def friend_state(friend):
    """'playing' | 'idle' | 'offline' for one friend dict from the site.

    The site's ``presence`` field is the authority - it is written by the friend's own
    launcher when Minecraft starts and stops, so it survives a stale heartbeat. Only when
    a friend has never reported presence (an older launcher) does this fall back to the
    heartbeat plus whatever status text the site has.
    """
    presence = (friend.get("presence") or "").lower()
    if presence == "in_game":
        return "playing"
    if presence == "offline":
        return "offline"
    if presence in ("online", "idle"):
        return "idle"
    if not friend.get("online"):
        return "offline"
    detail = (friend.get("presence_detail") or friend.get("status") or "").lower()
    if "minecraft" in detail or detail.startswith("playing"):
        return "playing"
    return "idle"


class FriendsPanel(ctk.CTkFrame):
    """Fixed-width friends column; nothing about it slides."""

    def __init__(self, master, app):
        super().__init__(master, fg_color=theme.COL["bg2"],
                         corner_radius=16, border_width=1, border_color=theme.COL["border"])
        # the old class got `app` from the rail base class; as a plain frame it has to
        # hold its own, or every path that reaches the config store or the app dies
        self.app = app
        self._data = {"friends": [], "incoming": [], "outgoing": []}
        self._query = ""
        self._loading = False
        self._icon_refs = []
        self._desk = ImageDesk()
        self._build()
        self._sync_link()
        self.refresh()
        self._schedule()

    # ------------------------------------------------------------------ build
    def _build(self):
        head = ctk.CTkFrame(self)
        head.pack(fill="x", padx=12, pady=(12, 0))
        head.grid_columnconfigure(0, weight=1)
        # The friends mark rather than a text glyph: the panel is narrow, and a drawn
        # group of three reads as "people" a whole lot faster than a smiley does.
        self.title_lbl = ctk.CTkLabel(head, text="  FRIENDS", anchor="w",
                                      font=theme.title_font(15),
                                      text_color=theme.COL["text"], compound="left",
                                      corner_radius=0,
                                      image=load_glyph("assets/ui_friends.png", (18, 18)) or "")
        self.title_lbl.grid(row=0, column=0, sticky="w")
        # The count rides on the title row instead of getting a row of its own. Every row in
        # this panel costs the friends list a row of friends, and "3 online" is a caption on
        # the heading, not a section.
        self.count_lbl = ctk.CTkLabel(head, text="", anchor="e", font=theme.font(10),
                                      text_color=theme.COL["accent"])
        self.count_lbl.grid(row=0, column=1, sticky="e", padx=(10, 0), pady=(3, 0))

        # who you are on the friends server, and the one button that fixes it when
        # you are not anyone yet
        link = ctk.CTkFrame(self, fg_color="#0f1622", corner_radius=12)
        link.pack(fill="x", padx=12, pady=(8, 0))
        link.grid_columnconfigure(1, weight=1)
        self.me_lbl = ctk.CTkLabel(link, text="", width=24, height=24, corner_radius=12,
                                   font=theme.font(11, "bold"), text_color="#04121a",
                                   fg_color=theme.COL["bg3"])
        self.me_lbl.grid(row=0, column=0, rowspan=2, padx=(10, 8), pady=9)
        self.who_lbl = ctk.CTkLabel(link, text="Not linked", anchor="w",
                                    font=theme.font(12, "bold"),
                                    text_color=theme.COL["text"])
        self.who_lbl.grid(row=0, column=1, sticky="w", pady=(9, 0))
        self.link_btn = ctk.CTkButton(link, text="  Link Discord", width=118, height=26,
                                      corner_radius=8, font=theme.font(10, "bold"),
                                      fg_color=theme.COL["accent"],
                                      hover_color=theme.COL["accent_hi"],
                                      text_color="#04121a", compound="left",
                                      image=load_glyph("assets/ui_discord.png", (15, 15)) or "",
                                      command=self._link_pressed)
        self.link_btn.grid(row=0, column=2, rowspan=2, padx=(6, 8))
        self.unlink_btn = ctk.CTkLabel(link, text="unlink", anchor="w",
                                       font=theme.font(9), cursor="hand2",
                                       text_color=theme.COL["text_faint"])
        self.unlink_btn.grid(row=1, column=1, sticky="w", pady=(0, 8))
        self.unlink_btn.bind("<Button-1>", lambda e: self._unlink_pressed())

        # the search bar: filters what is already loaded, and looks up a name if empty
        self.search = ctk.CTkEntry(self, height=34, corner_radius=10,
                                   fg_color="#111a26", border_width=1,
                                   border_color=theme.COL["border"],
                                   placeholder_text="Search friends, games, servers\u2026",
                                   font=theme.font(12), text_color=theme.COL["text"])
        self.search.pack(fill="x", padx=12, pady=(8, 3))
        self.search.bind("<KeyRelease>", lambda e: self._filter())
        self.search.bind("<Return>", lambda e: self._search_pressed())

        # The footer is packed against the bottom edge *before* the list exists, and the list
        # is packed last with expand. Order is the whole point: packed top-down, a panel that
        # runs out of height takes it out of whatever came last - which was the "add a friend"
        # row and its note, and they did not shrink, they silently stopped existing. Now the list
        # is the thing that gets short, because a list is the one part that can be.
        foot = self.foot = ctk.CTkFrame(self)
        foot.pack(side="bottom", fill="x", padx=12, pady=(2, 9))
        foot.grid_columnconfigure(0, weight=1)
        self.add_entry = ctk.CTkEntry(foot, height=32, corner_radius=10,
                                      placeholder_text="Discord name to add",
                                      font=theme.font(11), fg_color="#111a26",
                                      border_width=1, border_color=theme.COL["border"],
                                      text_color=theme.COL["text"])
        self.add_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.add_btn = ctk.CTkButton(foot, text="+", width=34, height=32,
                                     corner_radius=10, font=theme.font(15, "bold"),
                                     fg_color=theme.COL["accent"], hover_color="#5ff2e3",
                                     text_color="#04121a", command=self._add_friend)
        self.add_btn.grid(row=0, column=1)
        self.add_entry.bind("<Return>", lambda e: self._add_friend())

        self.note_lbl = flow_label(foot, text="", font=theme.font(10), wrap=208,
                               text_color=theme.COL["text_faint"], anchor="w")
        self.note_lbl.grid(row=1, column=0, columnspan=2, sticky="w", pady=(5, 0))
        self.note_lbl.grid_remove()        # nothing to say: no row, not an empty band

        # 150 rather than 96: the panel is sized by what it holds and is never squeezed, so this
        # number is the friends list, not a reservation. Below about this the panel's own header,
        # link box and footer leave a strip you cannot read.
        self.list = scroll_frame(self, height=150,
                                 scrollbar_button_color="#1e2a3a",
                                 scrollbar_button_hover_color="#2d3f56")
        self.list.pack(fill="both", expand=True, padx=6, pady=(0, 0))
        self.list.grid_columnconfigure(0, weight=1)

    # ------------------------------------------------------------- discord link
    def _sync_link(self):
        """Header line + button text, from the locally stored link."""
        try:
            link = social.get_link() or {}
        except Exception:
            link = {}
        name = link.get("username") or ""
        if name:
            self.who_lbl.configure(text=name)
            self.link_btn.configure(text="Re-link")
            self.unlink_btn.grid()
            url = (link.get("avatar_url") or "").strip()
            if url:
                self._desk.show(self.me_lbl, key=url, url=url, size=(24, 24))
            else:
                self.me_lbl.configure(text=(name[:1].upper() or "?"),
                                      fg_color=theme.COL["accent"])
        else:
            self.who_lbl.configure(text="Not linked")
            self.link_btn.configure(text="Link Discord")
            self.unlink_btn.grid_remove()
            self.me_lbl.configure(text="\u263a", fg_color=theme.COL["bg3"])

    def _link_pressed(self):
        """The same flow the Settings page offers, from where you can see it is needed."""
        box = DiscordLinkDialog(self.winfo_toplevel(), self.app,
                                on_done=self._after_link)
        box.after(120, box.lift)

    def _after_link(self, *_args):
        self._sync_link()
        self._loading = False
        self.refresh(force=True)
        try:
            self.app.refresh_discord()
        except Exception:
            pass

    def _unlink_pressed(self):
        try:
            social.clear_link()
        except Exception:
            pass
        self._desk.clear()
        self._sync_link()
        self._loading = False
        self.refresh()

    # ------------------------------------------------------------------ state
    def _schedule(self):
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        self.after(_REFRESH_MS, self.refresh)
        self.after(_REFRESH_MS, self._schedule)

    def refresh(self, force=True):
        self._sync_link()
        if self._loading:
            return
        self._loading = True
        if not social.is_linked():
            self._loading = False
            self._data = {"friends": [], "incoming": [], "outgoing": []}
            self._note("Press Link Discord above, approve it in your browser, and the "
                       "list fills itself in.")
            self._render()
            return
        self._note("updating\u2026")

        def work():
            try:
                data = social.list_friends(self.app.config_store)
            except Exception as e:
                self.app.after(0, lambda m=str(e): self._note(m[:110]))
                self._loading = False
                return
            self._loading = False
            self._data = data
            try:
                self.app.after(0, self._render)
            except Exception:
                pass
        threading.Thread(target=work, daemon=True).start()

    def _note(self, text):
        """The one line under the add box, and only when it has something to say.

        It lives inside the footer - which is anchored to the bottom of the panel - rather than
        being another packed row, because the row that takes the last of the height is the row
        that gets dropped when the panel runs short, and dropping the "add a friend" box to show
        a sentence nobody is reading is the wrong trade. Empty means no row at all.
        """
        try:
            self.note_lbl.configure(text=text or "")
            if text:
                self.note_lbl.grid()
            else:
                self.note_lbl.grid_remove()
        except Exception:
            pass

    def _matches(self, f):
        if not self._query:
            return True
        q = self._query.lower()
        for key in ("username", "name", "presence_detail", "status", "address"):
            if q in str(f.get(key, "")).lower():
                return True
        return False

    def _filter(self):
        self._query = (self.search.get() or "").strip()
        self._render()

    def _search_pressed(self):
        self._filter()
        if not any(self._matches(f) for f in self._data.get("friends", [])):
            name = self._query
            if name:
                self._note("no friend called %s yet - press + to add them" % name[:20])

    # ----------------------------------------------------------------- render
    def _render(self):
        # A refresh that changes nothing must not tear the list down: the rows would be
        # rebuilt, the image desk would be handed the same URLs for widgets that no longer
        # exist, and every avatar would blink out for a second each 45 s.
        sig = json.dumps([self._data, self._query], sort_keys=True, default=str)
        if sig == getattr(self, "_last_sig", None):
            try:
                if self.list.winfo_children():
                    return
            except Exception:
                return
        self._last_sig = sig
        try:
            for w in self.list.winfo_children():
                w.destroy()
            self._icon_refs.clear()
        except Exception:
            return
        friends = [f for f in self._data.get("friends", []) if self._matches(f)]
        incoming = [f for f in self._data.get("incoming", []) if self._matches(f)]
        outgoing = self._data.get("outgoing", [])
        order = {"playing": 0, "idle": 1, "offline": 2}
        friends.sort(key=lambda f: (order.get(friend_state(f), 3),
                                    str(f.get("username", "")).lower()))
        online = sum(1 for f in self._data.get("friends", []) if f.get("online"))
        playing = sum(1 for f in self._data.get("friends", [])
                      if friend_state(f) == "playing")
        self.count_lbl.configure(text="%d in Minecraft \u00b7 %d online \u00b7 %d total"
                                 % (playing, online, len(self._data.get("friends", []))))
        row = 0
        if incoming:
            row = self._section("REQUESTS", row)
            for f in incoming:
                self._row(f, row, "incoming")
                row += 1
        for f in friends:
            self._row(f, row, "friend")
            row += 1
        for f in outgoing:
            self._row(f, row, "outgoing")
            row += 1
        if not (friends or incoming or outgoing):
            # The panel is a third of the window at the smallest size the app allows, so the
            # hint has to be told where to break: asked to fit 240 px it wraps instead of
            # running under the card's edge, where it read as a defect.
            flow_label(self.list, text="Nobody here matches." if self._query else
                       "No friends yet. Type a Discord name below and press +.",
                       font=theme.font(12), text_color=theme.COL["text_faint"],
                       min_px=120).grid(row=0, column=0, sticky="we", padx=12, pady=16)
        self._note("")

    def _section(self, text, row):
        ctk.CTkLabel(self.list, text=text, font=theme.font(9, "bold"),
                     text_color=theme.COL["text_faint"], anchor="w"
                     ).grid(row=row, column=0, sticky="w", padx=12, pady=(8, 2))
        return row + 1

    def _row(self, f, row, kind):
        state = friend_state(f) if kind == "friend" else "idle"
        name_col, dot_col = theme.friend_color(state)
        card = Card(self.list, fg_color="#141b2b", corner_radius=12)
        card.grid(row=row, column=0, sticky="ew", padx=5, pady=3)
        card.grid_columnconfigure(2, weight=1)

        self._avatar(f, card, 0, 0)
        ctk.CTkLabel(card, text="\u25CF", font=theme.font(11),
                     text_color=dot_col).grid(row=0, column=1, padx=(6, 2), pady=(9, 0))
        label = str(f.get("username", "unknown"))
        ctk.CTkLabel(card, text=label, font=theme.font(13, "bold"),
                     text_color=name_col, anchor="w"
                     ).grid(row=0, column=2, sticky="w", pady=(9, 0))
        if kind == "friend":
            sub = {"playing": (f.get("presence_detail") or "playing Minecraft"),
                   "idle": "idle", "offline": "offline"}[state]
            ctk.CTkLabel(card, text=sub[:44], font=theme.font(10),
                         text_color=(theme.COL["text_dim"] if state == "playing"
                                     else theme.COL["text_faint"]), anchor="w"
                         ).grid(row=1, column=2, sticky="w", pady=(0, 9))
        elif kind == "incoming":
            # No status line here on purpose. Accept and the cross already say what the
            # row is, and the panel is 290px wide: a label in this cell sets a floor on
            # the name column and both the name and the text ended up clipped.
            accent_button(card, "Accept", lambda i=f.get("id"): self._accept(i),
                          width=62, height=26).grid(row=0, column=3, rowspan=2, padx=4)
            danger_button(card, "\u2715", lambda i=f.get("id"): self._remove(i),
                          width=30, height=26).grid(row=0, column=4, rowspan=2,
                                                     padx=(0, 8))
            ctk.CTkLabel(card, text="", font=theme.font(10)).grid(row=1, column=2)
        else:
            ctk.CTkLabel(card, text="request sent", font=theme.font(10),
                         text_color=theme.COL["text_faint"], anchor="w"
                         ).grid(row=1, column=2, sticky="w", pady=(0, 9))

    def _avatar(self, f, parent, row, column):
        """The friend's picture, filled in by the image desk.

        Painted as a letter tile first so the row has its final size immediately; the
        desk swaps the real image in when it has downloaded and decoded it. Nothing here
        touches the network on the UI thread.
        """
        url = (f.get("avatar_url") or "").strip()
        initial = (str(f.get("username", "?"))[:1] or "?").upper()
        state = friend_state(f)
        _name_col, dot = theme.friend_color(state)
        # Two CTkLabel details decide whether this fits its row slot:
        # compound="none" - while there is no picture the label shows its letter, and once
        # the desk sets an image Tk shows the image alone instead of painting the letter
        # next to it; corner_radius=0 - CTkLabel pads its content by the corner radius, so
        # a radius of 15 around a 30px image asks for 60px and the tile becomes a pill that
        # eats the name column. The tile is square, like the rest of the flat shell.
        lbl = ctk.CTkLabel(parent, text=initial, width=30, height=30, corner_radius=0,
                           font=theme.font(13, "bold"), text_color="#04121a",
                           fg_color=dot, compound="none")
        lbl.grid(row=row, column=column, rowspan=2, padx=(10, 0), pady=9)
        if url:
            self._desk.show(lbl, key=url, url=url, size=(30, 30))
        return lbl

    # ---------------------------------------------------------------- actions
    def destroy(self):
        try:
            self._desk.clear()
        except Exception:
            pass
        super().destroy()

    def _add_friend(self):
        name = (self.add_entry.get() or "").strip()
        if not name:
            self._note("Type a Discord name first.")
            return
        self.add_entry.delete(0, "end")
        self._note("sending the request\u2026")

        def work():
            try:
                social.add_friend(self.app.config_store, name)
                self.app.after(0, self.refresh)
            except Exception as e:
                self.app.after(0, lambda m=str(e): self._note(m[:110]))
        threading.Thread(target=work, daemon=True).start()

    def _accept(self, user_id):
        def work():
            try:
                social.accept_friend(self.app.config_store, user_id)
                self.app.after(0, self.refresh)
            except Exception as e:
                self.app.after(0, lambda m=str(e): self._note(m[:110]))
        threading.Thread(target=work, daemon=True).start()

    def _remove(self, user_id):
        def work():
            try:
                social.remove_friend(self.app.config_store, user_id)
                self.app.after(0, self.refresh)
            except Exception as e:
                self.app.after(0, lambda m=str(e): self._note(m[:110]))
        threading.Thread(target=work, daemon=True).start()
