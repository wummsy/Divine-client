"""The Instances page: every version, and everything you can do to it.

Phase 9 renamed this "Versions" and cut the launch button out of it, because a launch
button on a card and a launch button in a rail are two answers to one question. That is
reverted: the tab is Instances again and the LAUNCH button is on the card it belongs to,
where you can see what you are launching. (The app still accepts ``show_page("versions")``
so nothing else had to change.)

The card is the unit: name, Minecraft version, loader, mod/save/disk counts, and its own
actions - Launch, Edit, Mods, Folder, Clone, Delete. Nothing here animates: no stagger on
arrival, no lift under the pointer. Those were the two things that made the list feel
"glitchy" when rows resized underneath them.
"""
import os
import shutil
import threading
import tkinter as tk

import customtkinter as ctk

from ...core import playtime
from .. import theme
from ..widgets import flow_label
from ..widgets import (Card, accent_button, ghost_button, danger_button, load_glyph,
                      load_image_file, PageFrame, scroll_frame)


class InstancesPage(PageFrame):
    """The list of instances, each one launchable from its own card."""

    def __init__(self, master, app):
        super().__init__(master, kind="page")
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._cards = {}

        head = ctk.CTkFrame(self)
        head.grid(row=0, column=0, sticky="ew", padx=26, pady=(20, 8))
        head.grid_columnconfigure(0, weight=1)
        self.note_lbl = ctk.CTkLabel(head,
                                     text="Each instance is its own Minecraft install: its own "
                                          "saves, mods and settings",
                                     font=theme.font(13), text_color=theme.COL["text_dim"],
                                     anchor="w", justify="left")
        self.note_lbl.grid(row=0, column=0, sticky="w")
        btns = ctk.CTkFrame(head)
        btns.grid(row=0, column=1, sticky="e")
        btns.grid_columnconfigure(0, weight=1)
        # The plus mark is the one the sidebar's own "new" idea uses, so "make another one"
        # looks the same in both places.
        # The mark sits on the accent, so it is drawn in the ink that belongs on the accent -
        # the glyph's own colour is for dark panels, and on cyan it simply vanishes.
        accent_button(btns, "  New instance", self.open_create_dialog, width=168,
                      height=42, compound="left",
                      image=load_glyph("assets/ui_new.png", (18, 18),
                                       color="#04121a") or ""
                      ).grid(row=0, column=0, padx=(0, 6))
        ghost_button(btns, "Import instance", self.import_instance, width=140, height=42
                     ).grid(row=0, column=1, padx=(0, 6))
        ghost_button(btns, "Modpack", self.install_modpack, width=104, height=42
                     ).grid(row=0, column=2)

        self.list_frame = scroll_frame(self,
                                                 scrollbar_button_color="#22283d",
                                                 scrollbar_button_hover_color="#333c5c")
        self.list_frame.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 16))
        self.list_frame.grid_columnconfigure(0, weight=1, uniform="cards")
        self._cols = 1

        # How many columns of cards the window can carry. This is the only responsive thing
        # in the launcher, and it is deliberately arithmetic rather than a listener on every
        # widget: the column count changes on a handful of Configure events (a drag past a
        # threshold, a maximize) and the cards are then re-`grid`-ed - Tk moves the same
        # windows, nothing is destroyed, nothing is re-fetched, and a repaint stays a repaint.
        self.list_frame.bind("<Configure>", self._on_width, add="+")
        self.bind("<Configure>", self._fit_head, add="+")

    MIN_CARD = 500          # px, per card: below this the action row starts clipping

    def _on_width(self, _event=None):
        try:
            wide = int(self.list_frame.winfo_width()) - 12
        except Exception:
            return
        cols = max(1, wide // self.MIN_CARD) if wide > 0 else 1
        if cols == self._cols:
            return                          # the usual answer: nothing crossed a threshold
        self._cols = cols
        self._reflow()

    HEAD_ROOM = 448         # px the three header buttons and their padding take

    def _fit_head(self, _event=None):
        """Give the header's description the width the buttons leave it, so it wraps instead of clipping.

        Its sentence and the New instance / Import / Modpack row share one grid row, and below a
        window of about a thousand pixels the label runs under the buttons and is cut off in the
        middle of a word - which looks exactly like a bug in a screenshot. The cell is what
        shrinks, so the fix is to tell the label how wide its cell is; it then breaks onto a
        second line. Only the wraplength moves, driven by the page's width, the same way the
        card grid's column count is, and nothing else on the page can change size because of it.
        """
        try:
            wide = int(self.winfo_width())
        except Exception:
            return
        left = max(200, wide - 52 - self.HEAD_ROOM)
        if getattr(self, "_note_wrap", 0) and abs(left - self._note_wrap) < 16:
            return
        self._note_wrap = left
        try:
            self.note_lbl.configure(wraplength=left)
        except Exception:
            pass

    def _reflow(self):
        """Put the existing cards back into a grid with ``self._cols`` columns."""
        cols = max(1, self._cols)
        for c in range(cols):
            self.list_frame.grid_columnconfigure(c, weight=1, uniform="cards", minsize=0)
        for i, (_iid, card) in enumerate(list(self._cards.items())):
            try:
                card.grid(row=i // cols, column=i % cols, sticky="ew", padx=6,
                          pady=5)
            except Exception:
                pass

    # ------------------------------------------------------------------ hooks
    def on_show(self):
        self.refresh()

    def on_hide(self):
        pass

    def refresh(self):
        for w in self.list_frame.winfo_children():
            w.destroy()
        self._cards = {}
        try:
            self.app.instances.load()
        except Exception:
            pass
        insts = list(self.app.instances.instances or [])
        if not insts:
            self._empty_state()
            return
        for idx, inst in enumerate(insts):
            self._instance_card(inst, idx)
        theme.pin_surfaces(self)     # cards are new windows; they are only as good as their
                                     # own background, so say it now rather than on a resize

    def refresh_locks(self):
        """Re-decide, on every card, whether Launch is allowed right now.

        Called by LaunchFlow when the number of live games changes, so a card that has just
        become a second instance dims its button without the page being rebuilt - no refetch,
        no re-`grid`, no flash.
        """
        for iid, card in list(self._cards.items()):
            try:
                inst = self.app.instances.get(iid)
            except Exception:
                inst = None
            if inst is None:
                continue
            try:
                card.set_running(self.app.running_count(iid))
            except Exception:
                pass
            try:
                card.set_lock(bool(self.app.flow.locked_for(inst)))
            except Exception:
                pass

    def _note(self, text):
        """Page-level feedback. The window has one status line; use it."""
        try:
            self.app.set_status(text)
        except Exception:
            pass

    def _empty_state(self):
        card = Card(self.list_frame, fg_color="#101526", corner_radius=16)
        card.grid(row=0, column=0, sticky="ew", padx=6, pady=26)
        card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(card, text="No instances yet", font=theme.title_font(20),
                     text_color=theme.COL["text"], anchor="w"
                     ).grid(row=0, column=0, sticky="w", padx=20, pady=(18, 2))
        flow_label(card, text="An instance is an isolated Minecraft install: its own "
                                "saves, mods and settings. Make one and it appears here "
                                "with its own launch button.",
                     font=theme.font(12), text_color=theme.COL["text_dim"], anchor="w",
                     justify="left").grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 10))
        ghost_button(card, "Create the first one", self.open_create_dialog,
                     width=190, height=40).grid(row=2, column=0, sticky="w",
                                                padx=20, pady=(0, 20))

    # ------------------------------------------------------------------- cards
    def _instance_card(self, inst, idx):
        card = InstanceCard(self.list_frame, inst, page=self)
        card.grid(row=idx, column=0, sticky="ew", padx=6, pady=5)
        running = 0
        try:
            running = self.app.running_count(inst.id)
        except Exception:
            pass
        try:
            locked = bool(self.app.flow.locked_for(inst))
        except Exception:
            locked = False
        card.set_running(running)
        card.set_lock(locked)
        card.set_actions(
            launch=lambda: self._launch(inst),
            stop=lambda: self._stop(inst),
            others=[("Edit", lambda: self._open_editor(inst)),
                    ("Mods", lambda: self._open_mods(inst)),
                    ("Folder", lambda: self._open_folder(inst)),
                    ("Clone", lambda: self._clone(inst)),
                    ("Delete", lambda: self._delete(inst))])
        card.set_playtime(playtime.total(inst), playtime.since(playtime.last_played(inst)))
        self._cards[inst.id] = card
        return card

    # ------------------------------------------------------- import / modpack
    def import_instance(self):
        """Register a folder (or a zip of one) that already exists somewhere.

        The picker takes a folder; a zip is imported by name from wherever it lives, because
        people's first instinct is to point at the archive they were sent. Either way the
        instance is *copied* into the launcher's own folder: a half-referenced install on a
        USB stick is how people lose a world.
        """
        try:
            from tkinter import filedialog
            parent = filedialog.askdirectory(
                title="Pick the instance folder to import", mustexist=True)
            if not parent:
                return
        except Exception as exc:
            self._note("Could not open the folder picker: %s" % exc)
            return
        self._note("Importing…")

        def work():
            try:
                inst, notes = self.app.instances.import_from(parent)
            except Exception as exc:
                post_note = "Import failed: %s" % str(exc)[:160]
                self.after(0, lambda: self._note(post_note))
                return
            text = ("Imported %s (Minecraft %s, %s): %d things copied"
                    % (inst.name, inst.mc_version, inst.loader, notes.get("copied", 0)))
            if notes.get("failed"):
                text += ", %d could not be copied" % len(notes["failed"])
            if notes.get("skipped"):
                text += ", launcher files left out"
            self.after(0, lambda: self._after_import(inst, text))

        threading.Thread(target=work, daemon=True).start()

    def _after_import(self, inst, text):
        self.refresh()
        try:
            self.app.flow.refresh()
        except Exception:
            pass
        self._note(text)

    def install_modpack(self):
        """Search Modrinth and turn a pack into an instance."""
        from ..modpack_dialog import ModpackDialog
        dlg = ModpackDialog(self.winfo_toplevel(), self.app,
                            on_done=lambda inst: self._note(
                                "Installed %s - it is in the list now." % inst.name))
        dlg.after(120, dlg.lift)
        dlg.after(160, dlg.focus_force)

    # ----------------------------------------------------------------- picture
    def choose_picture(self, inst):
        """Give an instance its own picture. The file is copied into the instance folder."""
        try:
            from tkinter import filedialog
            picked = filedialog.askopenfilename(
                title="Choose a picture for %s" % inst.name,
                filetypes=[("Images", "*.png *.jpg *.jpeg *.gif *.webp"),
                           ("All files", "*.*")])
        except Exception as exc:
            self._note("Could not open the file picker: %s" % exc)
            return
        if not picked:
            return
        self.set_picture(inst, picked)

    def set_picture(self, inst, source, rel_name="instance.png"):
        """Copy ``source`` into the instance folder and remember it by name.

        Storing a relative name rather than the path is the whole trick: the picture then
        travels with the instance, survives the game-files folder moving (see Settings), and
        cannot point at a file someone deleted from their Downloads.
        """
        if not source or not os.path.isfile(source):
            self._note("That file is not there any more.")
            return False
        try:
            if os.path.getsize(source) > 8 * 1024 * 1024:
                self._note("That picture is over 8 MB; a smaller one will do.")
                return False
            dest = os.path.join(inst.game_dir, rel_name)
            shutil.copyfile(source, dest)
        except (OSError, shutil.Error) as exc:
            self._note("Could not store the picture: %s" % exc)
            return False
        inst.data["icon_file"] = rel_name
        try:
            self.app.instances.save()
        except Exception:
            pass
        card = self._cards.get(inst.id)
        if card is not None:
            card.set_picture(dest)
        self._note("Picture set for %s." % inst.name)
        return True

    def clear_picture(self, inst):
        name = inst.data.get("icon_file")
        inst.data.pop("icon_file", None)
        try:
            self.app.instances.save()
        except Exception:
            pass
        if name:
            try:
                os.remove(os.path.join(inst.game_dir, name))
            except OSError:
                pass
        card = self._cards.get(inst.id)
        if card is not None:
            card.set_picture(None)
        self._note("Picture removed from %s." % inst.name)

    def _launch(self, inst):
        """Choose it, then launch it - the flow owns the actual start-up."""
        try:
            self.app.flow.select(inst)
            self.app.flow.launch()
        except Exception as exc:
            self._note("Could not launch: %s" % exc)

    def _stop(self, inst):
        try:
            self.app.stop_instance(inst.id)
        except Exception as exc:
            self._note("Could not stop: %s" % exc)
        self.refresh()

    # ----------------------------------------------------------------- actions
    def _open_editor(self, inst):
        from ..instance_editor import InstanceEditor
        win = InstanceEditor(self.app, inst, on_change=self._on_editor_change)
        win.after(120, win.lift)
        win.after(160, win.focus_force)

    def _on_editor_change(self):
        self.refresh()
        try:
            self.app.flow.refresh()
        except Exception:
            pass

    def _open_mods(self, inst):
        from ..mod_browser import ModBrowser
        win = ModBrowser(self.app, inst)
        win.after(120, win.lift)
        win.after(160, win.focus_force)

    def _open_folder(self, inst):
        import os
        import subprocess
        import sys
        path = inst.game_dir
        try:
            if sys.platform == "win32":
                os.startfile(path)  # noqa: S606
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception:
            pass

    def _clone(self, inst):
        try:
            created = self.app.instances.create("%s (copy)" % inst.name, inst.mc_version,
                                                loader=inst.loader,
                                                loader_version=getattr(inst,
                                                                       "loader_version",
                                                                       None))
        except Exception:
            return
        self.refresh()
        try:
            self.app.flow.select(created)
        except Exception:
            pass
        self._note("Cloned %s" % inst.name)

    def _delete(self, inst):
        dlg = ConfirmDialog(self, "Delete \u201c%s\u201d?" % inst.name,
                            "This removes its saves, mods and settings from disk. "
                            "This cannot be undone.")
        self.wait_window(dlg)
        if dlg.result:
            try:
                self.app.instances.delete(inst.id, remove_files=True)
            except Exception:
                return
            self.refresh()
            try:
                self.app.flow.refresh()
            except Exception:
                pass

    def open_create_dialog(self):
        dlg = CreateVersionDialog(self, self.app)
        self.wait_window(dlg)
        if dlg.created:
            self.refresh()
            try:
                if dlg.created_id:
                    for i in self.app.instances.instances:
                        if i.id == dlg.created_id:
                            self.app.flow.select(i)
                            break
                self.app.flow.refresh()
            except Exception:
                pass


def count_instance(inst):
    """Mods, worlds, size on disk and playtime for one instance, as one dict.

    A folder walk: it must not run on the UI thread. Both the card and Home's play panel call it
    from a worker and hand the result back with ``after(0, ...)`` - one implementation, because
    two numbers for the same folder on two parts of one window is how a launcher starts lying.
    """
    import os
    out = {"mods": 0, "saves": 0, "size": 0, "play": 0, "when": ""}
    base = getattr(inst, "game_dir", "") or ""
    try:
        if base and os.path.isdir(base):
            d = os.path.join(base, "mods")
            if os.path.isdir(d):
                out["mods"] = len([n for n in os.listdir(d) if n.endswith(".jar")])
            out["saves"] = len([n for n in os.listdir(base)
                               if n.lower().startswith("save")
                               and os.path.isdir(os.path.join(base, n))])
            out["size"] = sum(os.path.getsize(os.path.join(r, f))
                              for r, _ds, fs in os.walk(base) for f in fs) // (1 << 20)
    except Exception:
        pass            # a folder that moved mid-walk is not worth a traceback over
    try:
        out["play"] = playtime.total(inst)
        out["when"] = playtime.since(playtime.last_played(inst))
    except Exception:
        pass
    return out


class InstanceCard(ctk.CTkFrame):
    """One instance: what it is on the left, what you can do to it underneath.

    Launch is the only button with colour. Everything else on the card is a quiet ghost
    button, so the answer to "which click starts a game" is visible from across the room.
    """

    #: the two states of a card's panel, from the palette rather than fixed: with a background
    #: chosen in Settings, a card that stays #0f1420 would be a grey island in a grey sea.
    IDLE = None
    HOT = None

    @classmethod
    def tone(cls, hot):
        return theme.COL["bg3"] if hot else theme.COL["bg2"]

    def __init__(self, master, inst, page=None):
        super().__init__(master, corner_radius=14, border_width=1,
                         border_color=theme.COL["border"], fg_color=self.tone(False))
        self.inst = inst
        self.page = page
        self.running = 0
        self.locked = False
        self._launch_btn = None
        self._launch_cb = None
        self._stop_cb = None
        self._counts = {"mods": 0, "saves": 0, "size": 0, "play": 0, "when": ""}
        self._picture = None
        self.grid_columnconfigure(1, weight=1)
        self._build()

    def _build(self):
        inst = self.inst
        fabric = inst.loader == "fabric"
        accent = theme.COL["accent2"] if fabric else theme.COL["accent"]
        self._letter = "F" if fabric else "V"
        # A 50x50 square, deliberately: a CTkLabel adds its own corner_radius to whatever
        # it holds, so a rounded tile asks for 76 px once a picture lands and the row
        # reshuffles under the pointer. Square means the picture and the letter take exactly
        # the same room, and the picture is the whole point of this tile.
        self.mark = ctk.CTkLabel(self, text=self._letter, width=50, height=50,
                                 font=theme.title_font(22), text_color="#04121a",
                                 fg_color=accent, corner_radius=0, compound="none",
                                 cursor="hand2")
        self.mark.grid(row=0, column=0, rowspan=2, padx=(16, 14), pady=16)
        pic = self._picture_path()
        if pic:
            self.set_picture(pic)
        # Right-click for the menu, double-click for the picker: the picture belongs to the
        # tile, and neither of them costs the action row another 76 px of buttons.
        self.mark.bind("<Button-3>", self._picture_menu)
        self.mark.bind("<Double-Button-1>", lambda e: self._ask_picture())

        text = ctk.CTkFrame(self)
        text.grid(row=0, column=1, sticky="ew", pady=(15, 0))
        text.grid_columnconfigure(0, weight=1)
        self.name_row = ctk.CTkFrame(text)
        self.name_row.grid(row=0, column=0, sticky="w")
        self.name_lbl = ctk.CTkLabel(self.name_row, text=inst.name, anchor="w",
                                     font=theme.font(18, "bold"),
                                     text_color=theme.COL["text"])
        self.name_lbl.grid(row=0, column=0)
        sub = "Minecraft %s   \u00b7   %s" % (inst.mc_version,
                                              "Fabric" if fabric else "Vanilla")
        lv = getattr(inst, "loader_version", "") or ""
        if fabric and lv:
            sub += "  \u00b7  loader %s" % lv
        ctk.CTkLabel(text, text=sub, anchor="w", font=theme.font(11),
                     text_color=theme.COL["text_dim"]).grid(row=1, column=0, sticky="w",
                                                             pady=(1, 0))
        self.stats = ctk.CTkLabel(text, text="", anchor="w", font=theme.font(10),
                                  text_color=theme.COL["text_faint"])
        self.stats.grid(row=2, column=0, sticky="w", pady=(2, 0))

        self.right = ctk.CTkFrame(self)
        self.right.grid(row=0, column=2, sticky="e", padx=(6, 14))
        self.state_lbl = ctk.CTkLabel(self.right, text="", font=theme.font(10, "bold"),
                                      text_color=theme.COL["good"])
        self.state_lbl.grid(row=1, column=0, sticky="e", pady=(2, 0))

        self.actions = ctk.CTkFrame(self)
        self.actions.grid(row=1, column=0, columnspan=3, sticky="ew", padx=12,
                          pady=(0, 12))
        self.actions.grid_columnconfigure(0, weight=1)
        threading.Thread(target=self._count, daemon=True).start()

    def set_actions(self, launch=None, stop=None, others=()):
        """Launch (or Stop) on the top right, everything else underneath.

        A locked card still shows its button, greyed, because "where did the button go" is a
        worse question than "why is this one dim" - the reason is written next to it.
        """
        self._launch_cb, self._stop_cb = launch, stop
        self._paint_power()
        for i, (label, fn) in enumerate(others):
            last = i == len(others) - 1
            btn = (danger_button(self.actions, label, fn, width=76, height=30)
                   if last else
                   ghost_button(self.actions, label, fn, width=76, height=30))
            btn.grid(row=0, column=i + 1, padx=3)

    def _paint_power(self):
        """Draw the one button that starts or stops this instance.

        Separate from ``set_actions`` because the flow tells the card its running state many
        times without the page being rebuilt: the Launch button has to become Stop the moment a
        game comes up, and rebuilding the card to do it is exactly the reflow that used to make
        the page jump under the pointer.
        """
        for w in list(self.right.winfo_children()):
            if w is self.state_lbl:
                continue
            try:
                w.destroy()
            except Exception:
                pass
        self._launch_btn = None
        if self.running:
            if self._stop_cb is not None:
                danger_button(self.right, "\u25A0  Stop", self._stop_cb, width=124, height=34
                              ).grid(row=0, column=0)
        elif self._launch_cb is not None:
            btn = accent_button(self.right, "\u25B6  Launch", self._launch_cb,
                                width=124, height=34)
            btn.grid(row=0, column=0)
            self._launch_btn = btn      # so a later lock can reach it without rebuilding
            self._apply_lock_color()

    def _apply_lock_color(self):
        """A locked Launch reads as unavailable: no accent, no hover, disabled."""
        btn = getattr(self, "_launch_btn", None)
        if btn is None:
            return
        try:
            if self.locked:
                btn.configure(state="disabled", fg_color=theme.COL["bg3"],
                              hover_color=theme.COL["bg3"],
                              text_color=theme.COL["text_faint"])
            else:
                btn.configure(state="normal")
        except Exception:
            pass

    def set_running(self, count):
        count = int(count or 0)
        if count != self.running:
            self.running = count
            self._paint_power()          # Launch <-> Stop, in place
        if count:
            self.state_lbl.configure(text="\u25CF  Running",
                                     text_color=theme.COL["good"])
            try:
                self.configure(border_color=theme.COL["good"], fg_color=self.tone(True))
            except Exception:
                pass
        elif not self.locked:
            self.state_lbl.configure(text="")
            try:
                self.configure(border_color=theme.COL["border"], fg_color=self.tone(False))
            except Exception:
                pass

    def set_lock(self, locked):
        """Whether this card's Launch is allowed. Only the flow decides the value.

        The button is kept and greyed rather than removed: the card has to stay the same
        shape, because rows that resize under the pointer are what the old "it glitches"
        reports were about, and a greyed button can carry the reason next to it.
        """
        self.locked = bool(locked) and not self.running
        self._apply_lock_color()
        try:
            if self.locked:
                self.state_lbl.configure(text="another game is open",
                                         text_color=theme.COL["warn"])
            elif not self.running:
                self.state_lbl.configure(text="")
        except Exception:
            pass

    def _count(self):
        """Mods / saves / size off-thread: a folder walk must not stall the page."""
        counts = count_instance(self.inst)

        def apply():
            self._counts.update(counts)
            self._render_stats()

        try:
            self.after(0, apply)
        except Exception:
            pass

    def _render_stats(self):
        c = self._counts
        bits = ["%d mods" % c["mods"], "%d saves" % c["saves"],
                "%d MB on disk" % c["size"]]
        if c["play"]:
            bits.append("%s played" % playtime.human(c["play"]))
        if c.get("when") and c["when"] != "never":
            bits.append("last %s" % c["when"])
        try:
            self.stats.configure(text="   \u00b7   ".join(bits))
        except Exception:
            pass

    def set_playtime(self, seconds, when=""):
        """Push a fresh session count without rebuilding the card."""
        self._counts["play"] = int(seconds or 0)
        self._counts["when"] = when or ""
        self._render_stats()

    # ----------------------------------------------------------------- picture
    def _picture_path(self):
        name = (self.inst.data or {}).get("icon_file") if hasattr(self.inst, "data") else ""
        if not name:
            return ""
        full = name if os.path.isabs(name) else os.path.join(self.inst.game_dir, name)
        return full if os.path.isfile(full) else ""

    def set_picture(self, source):
        """Show the instance's own picture, or the loader letter again when ``source`` is None."""
        img = load_image_file(source, (50, 50)) if source else None
        self._picture = source if img is not None else None
        try:
            if img is None:
                self.mark.configure(image="", text=self._letter, compound="none")
            else:
                self.mark.configure(image=img, text="", compound="none")
        except Exception:
            pass

    def _ask_picture(self):
        page = getattr(self, "page", None)
        if page is not None:
            try:
                page.choose_picture(self.inst)
            except Exception:
                pass

    def _picture_menu(self, event):
        page = getattr(self, "page", None)
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Change picture\u2026",
                        command=lambda: page and page.choose_picture(self.inst))
        if self._picture:
            menu.add_command(label="Remove picture",
                             command=lambda: page and page.clear_picture(self.inst))
        menu.add_command(label="Open instance folder",
                         command=lambda: page and page._open_folder(self.inst))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()


class ConfirmDialog(ctk.CTkToplevel):
    def __init__(self, master, title, message):
        super().__init__(master)
        self.result = False
        self.title("Confirm")
        self.geometry("430x200")
        self.configure(fg_color=theme.COL["bg2"])
        self.transient(master)
        self.grab_set()
        flow_label(self, text=title, font=theme.font(16, "bold"),
                     text_color=theme.COL["text"], justify="left"
                     ).pack(fill="x", padx=22, pady=(22, 6), anchor="w")
        flow_label(self, text=message, font=theme.font(12),
                     text_color=theme.COL["text_dim"], justify="left"
                     ).pack(fill="x", padx=22, anchor="w")
        row = ctk.CTkFrame(self)
        row.pack(side="bottom", fill="x", padx=22, pady=18)
        ghost_button(row, "Cancel", self._cancel, width=120).pack(side="right", padx=(8, 0))
        danger_button(row, "Delete", self._ok, width=120, height=38).pack(side="right")

    def _ok(self):
        self.result = True
        self.destroy()

    def _cancel(self):
        self.result = False
        self.destroy()


class CreateVersionDialog(ctk.CTkToplevel):
    """New version: name, Minecraft version, loader. Same fields as before, better order."""

    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.created = False
        self.created_id = None
        self.title("New version")
        self.geometry("520x500")
        self.configure(fg_color=theme.COL["bg2"])
        self.transient(master)
        self.grab_set()
        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self, text="Create a new version", font=theme.title_font(21),
                     text_color=theme.COL["text"]).grid(row=0, column=0, sticky="w",
                                                         padx=24, pady=(22, 4))
        flow_label(self, text="Each version is fully isolated: its own saves, mods and "
                                "settings.",
                     font=theme.font(12), text_color=theme.COL["text_dim"], justify="left").grid(row=1, column=0, sticky="ew",
                                                           padx=24)

        ctk.CTkLabel(self, text="Name", font=theme.font(12, "bold"),
                     text_color=theme.COL["text_faint"]).grid(row=2, column=0, sticky="w",
                                                               padx=24, pady=(18, 2))
        self.name_entry = ctk.CTkEntry(self, height=40, font=theme.font(14),
                                       fg_color=theme.COL["bg3"],
                                       border_color=theme.COL["border"],
                                       placeholder_text="My Survival World")
        self.name_entry.grid(row=3, column=0, sticky="ew", padx=24)

        filt = ctk.CTkFrame(self)
        filt.grid(row=4, column=0, sticky="ew", padx=24, pady=(16, 2))
        ctk.CTkLabel(filt, text="Minecraft version", font=theme.font(12, "bold"),
                     text_color=theme.COL["text_faint"]).pack(side="left")
        self.show_snapshots = ctk.CTkCheckBox(filt, text="Show snapshots",
                                              font=theme.font(11), checkbox_width=18,
                                              checkbox_height=18,
                                              fg_color=theme.COL["accent"],
                                              command=self._reload_versions)
        self.show_snapshots.pack(side="right")

        self.version_menu = ctk.CTkOptionMenu(
            self, values=["loading..."], height=40, font=theme.font(14),
            fg_color=theme.COL["bg3"], button_color=theme.COL["bg_hover"],
            button_hover_color=theme.COL["accent"],
            dropdown_fg_color=theme.COL["bg3"], dropdown_hover_color=theme.COL["bg_hover"],
            command=self._on_version_change)
        self.version_menu.grid(row=5, column=0, sticky="ew", padx=24, pady=(4, 0))

        ctk.CTkLabel(self, text="Mod loader", font=theme.font(12, "bold"),
                     text_color=theme.COL["text_faint"]).grid(row=6, column=0, sticky="w",
                                                               padx=24, pady=(16, 2))
        self.loader_var = ctk.StringVar(value="vanilla")
        loader_row = ctk.CTkFrame(self)
        loader_row.grid(row=7, column=0, sticky="ew", padx=24)
        ctk.CTkRadioButton(loader_row, text="Vanilla", variable=self.loader_var,
                           value="vanilla", font=theme.font(13),
                           fg_color=theme.COL["accent"]).pack(side="left", padx=(0, 20))
        self.fabric_radio = ctk.CTkRadioButton(loader_row,
                                                text="Fabric + Divine performance pack",
                                                variable=self.loader_var, value="fabric",
                                                font=theme.font(13),
                                                fg_color=theme.COL["accent2"])
        self.fabric_radio.pack(side="left")
        self.fabric_hint = flow_label(self, text="", font=theme.font(11),
                                       text_color=theme.COL["warn"], justify="left")
        self.fabric_hint.grid(row=8, column=0, sticky="w", padx=24, pady=(6, 0))

        row = ctk.CTkFrame(self)
        row.grid(row=9, column=0, sticky="ew", padx=24, pady=20)
        row.grid_columnconfigure(0, weight=1)
        ghost_button(row, "Cancel", self.destroy, width=110).grid(row=0, column=1,
                                                                  padx=(8, 0))
        accent_button(row, "Create", self._create, width=150, height=42).grid(row=0,
                                                                             column=2)

        self._all_versions = []
        threading.Thread(target=self._load_versions_thread, daemon=True).start()

    def _load_versions_thread(self):
        try:
            self._all_versions = self.app.get_versions()
        except Exception:
            self._all_versions = []
        try:
            self.after(0, self._reload_versions)
        except Exception:
            pass

    def _reload_versions(self):
        versions = self._all_versions
        if not versions:
            self.version_menu.configure(values=["(offline - type manually)"])
            return
        if self.show_snapshots.get():
            ids = [v["id"] for v in versions]
        else:
            ids = [v["id"] for v in versions if v["type"] == "release"]
        ids = ids[:400]
        self.version_menu.configure(values=ids)
        if ids:
            self.version_menu.set(ids[0])
            self._on_version_change(ids[0])

    def _on_version_change(self, version):
        try:
            fabric_ok = version in self.app.get_fabric_versions()
        except Exception:
            fabric_ok = False
        if fabric_ok:
            self.fabric_radio.configure(state="normal")
            self.fabric_hint.configure(text="")
        else:
            if self.loader_var.get() == "fabric":
                self.loader_var.set("vanilla")
            self.fabric_radio.configure(state="disabled")
            self.fabric_hint.configure(text="Fabric is not available for this version "
                                            "\u2014 vanilla only.")

    def _create(self):
        name = self.name_entry.get().strip()
        version = self.version_menu.get().strip()
        if not name:
            name = version
        if not version or version.startswith("("):
            self.fabric_hint.configure(text="Pick a valid version first.",
                                       text_color=theme.COL["danger"])
            return
        try:
            created = self.app.instances.create(name, version, loader=self.loader_var.get())
            self.created = True
            self.created_id = getattr(created, "id", None)
        except Exception:
            self.fabric_hint.configure(text="Could not create it - check the name.",
                                       text_color=theme.COL["danger"])
            return
        self.destroy()


# Names other modules still use. ``VersionsPage`` is the tab's brief phase-9 name and
# ``CreateInstanceDialog`` is what the dialog was called before the rename; both resolve to
# the same objects, so no import anywhere has to be chased down.
VersionsPage = InstancesPage
VersionCard = InstanceCard
CreateInstanceDialog = CreateVersionDialog

__all__ = ["InstancesPage", "InstanceCard", "ConfirmDialog", "CreateVersionDialog",
           "VersionsPage", "VersionCard", "CreateInstanceDialog"]
