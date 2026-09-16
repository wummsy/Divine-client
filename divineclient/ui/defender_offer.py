"""The one-time dialog that offers the Windows Defender exclusion.

Shown *after* the window is up and never in front of Launch: it is a ``Toplevel``, so the
person can dismiss it by clicking the main window and play straight away. The wording is
deliberately concrete - which folders, that Windows will ask for administrator rights, that
real-time protection stays on - because "trust me" is what a scam dialog says.
"""
import customtkinter as ctk

from ..core import defender
from . import theme


class DefenderOffer(ctk.CTkToplevel):
    def __init__(self, master, app=None, info=None):
        super().__init__(master)
        self.app = app
        self._info = info or defender.status(app.config_store if app is not None else None)
        self._busy = False

        self.title("Windows Defender")
        self.resizable(False, False)
        self.transient(master)
        self.configure(fg_color=theme.COL["bg2"])
        self.grab_set()

        card = ctk.CTkFrame(self, corner_radius=16, border_width=1,
                            border_color=theme.COL["border"], fg_color=theme.COL["bg2"])
        card.pack(fill="both", expand=True, padx=2, pady=2)
        card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(card, text="Windows Defender \u00b7 one small favour",
                     font=theme.title_font(19), text_color=theme.COL["text"]
                     ).grid(row=0, column=0, sticky="w", padx=22, pady=(20, 4))
        ctk.CTkLabel(card, font=theme.font(12), wraplength=430, justify="left", anchor="w",
                     text_color=theme.COL["text_dim"],
                     text=("This launcher is unsigned, so Defender can call it a threat on sight. "
                           "Adding one exclusion for the Divine folders stops that. Windows will ask "
                           "you to confirm (administrator rights), protection stays on, and you can "
                           "take the exclusion back out in Settings.")
                     ).grid(row=1, column=0, sticky="w", padx=22, pady=(0, 10))

        lines, rows = self._changes()
        if lines:
            box = ctk.CTkFrame(card, fg_color=theme.COL["bg3"], corner_radius=12)
            box.grid(row=2, column=0, sticky="ew", padx=22, pady=(0, 8))
            box.grid_columnconfigure(0, weight=1)
            for i, text in enumerate(lines):
                ctk.CTkLabel(box, text=text, font=theme.font(11), anchor="w", justify="left",
                             wraplength=400, text_color=theme.COL["text_dim"]
                             ).grid(row=i, column=0, sticky="w", padx=14, pady=(8, 0) if i == 0 else 0)
        note = ctk.CTkLabel(card, text=rows, font=theme.font(11), anchor="w", justify="left",
                            wraplength=430, text_color=theme.COL["text_faint"])
        note.grid(row=3, column=0, sticky="w", padx=22, pady=(2, 6))

        self.auto_chk = ctk.CTkCheckBox(
            card, text="If it ever disappears, add it back without asking me",
            font=theme.font(11), checkbox_width=18, checkbox_height=18,
            fg_color=theme.COL["accent"], hover_color=theme.COL["accent_hi"],
            border_color=theme.COL["border"], text_color=theme.COL["text_dim"])
        self.auto_chk.grid(row=4, column=0, sticky="w", padx=20, pady=(2, 10))
        if defender.auto_run(self._cfg()):
            self.auto_chk.select()

        row = ctk.CTkFrame(card, fg_color="transparent")
        row.grid(row=5, column=0, sticky="ew", padx=22, pady=(0, 20))
        row.grid_columnconfigure(0, weight=1)
        from .widgets import ghost_button, accent_button
        self.later_btn = ghost_button(row, "Not now", self._later, width=120, height=38)
        self.later_btn.grid(row=0, column=0, sticky="w")
        self.go_btn = accent_button(row, "Add for me", self._add, width=150, height=38)
        self.go_btn.grid(row=0, column=1)
        if not self._can_run():
            self.go_btn.configure(state="disabled", text="Nothing to add")

        self._center_over(master)
        self.protocol("WM_DELETE_WINDOW", self._later)
        self.after(40, lambda: self._safe(self.focus_force))

    # ------------------------------------------------------------------ parts
    def _cfg(self):
        return self.app.config_store if self.app is not None else None

    def _can_run(self) -> bool:
        return str(self._info.get("state") or "") in ("ready", "done", "asked", "declined")

    def _changes(self):
        """The list shown in the box, plus one line about what we could not work out."""
        paths = [p for p in (self._info.get("paths") or []) if p]
        lines = ["Excluded folder:  %s" % p for p in paths]
        lines.append("Excluded process: %s" % defender.EXE_NAME)
        state = str(self._info.get("state") or "")
        if state == "already":
            lines = ["Both folders are already on the list, so there is nothing to add."]
        elif state == "no-script":
            lines = [self._info.get("detail") or defender.SCRIPT_NAME + " was not found"]
        note = self._info.get("detail") or ""
        if state == "already":
            note = ""
        return lines, note

    def _center_over(self, master):
        try:
            self.update_idletasks()
            w, h = self.winfo_reqwidth(), self.winfo_reqheight()
            px, py = master.winfo_rootx(), master.winfo_rooty()
            pw, ph = master.winfo_width(), master.winfo_height()
            self.geometry("+%d+%d" % (px + max(0, (pw - w) // 2), py + max(0, (ph - h) // 3)))
        except Exception:
            pass

    # ---------------------------------------------------------------- answers
    def _add(self):
        if self._busy or not self._can_run():
            return
        self._busy = True
        cfg = self._cfg()
        try:
            defender.set_auto(cfg, bool(self.auto_chk.get()))
        except Exception:
            pass
        # close first: the elevated call can wait a minute on the UAC prompt, and a
        # modal dialog sitting there while the person reads it is a bad trade
        self._status("Waiting for Windows to confirm the exclusion\u2026")
        self.destroy()
        try:
            defender.apply_async(config=cfg, on_done=self._done)
        except Exception as exc:
            self._status("Could not ask Defender: %s" % exc)

    def _done(self, report):
        report_result(self.app, report)
        self._refresh_settings()

    def _later(self):
        try:
            defender.mark(self._cfg(), "declined")
        except Exception:
            pass
        self._status("No exclusion added - Settings \u25b8 Windows Defender has the button "
                     "for this whenever you want it")
        self.destroy()

    # ----------------------------------------------------------------- helpers
    def _refresh_settings(self):
        try:
            page = getattr(self.app, "settings_page", None) or {}
            if isinstance(page, dict):           # pages may be lazily built
                page = page.get("settings")
            fn = getattr(page, "refresh_defender", None)
            if fn:
                fn()
        except Exception:
            pass

    def _status(self, text):
        try:
            if self.app is not None:
                self.app._post_status(text)
        except Exception:
            pass

    def _safe(self, fn):
        try:
            fn()
        except Exception:
            pass


def report_result(app, report, remove=False):
    """Say in the status bar what the elevated helper actually did.

    Shared by the dialog and by the "just do it" path, so a silent re-add is still reported
    where the person will look at some point. "Added, but Defender did not confirm it" is a
    real state: reading the exclusion list can need rights the launcher does not have.
    """
    report = report or {}
    verb = "removal" if remove else "exclusion"
    if report.get("ok"):
        if report.get("verified") is False:
            text = ("Defender did not confirm the %s - open Windows Security \u25b8 Exclusions "
                    "to see what is on the list" % verb)
        else:
            text = "Defender %s done" % ("removal" if remove else "exclusion added")
    else:
        text = "Defender %s did not go through: %s" % (verb, report.get("reason") or "Windows said no")
    try:
        if app is not None:
            app._post_status(text)
    except Exception:
        pass
    try:
        page = (getattr(app, "pages", None) or {}).get("settings")
        fn = getattr(page, "refresh_defender", None)
        if fn:
            fn()
    except Exception:
        pass


def maybe_offer(app):
    """Show the dialog once, on the first open. Never raises, never blocks anything.

    Called from the loading-screen hand-off, where every other first-run job lives. If the
    person has already answered once, this returns immediately; if they ticked "just do it"
    and Defender has since dropped the exclusion, it re-adds it on a worker thread instead
    of asking again.
    """
    cfg = getattr(app, "config_store", None)
    try:
        if defender.first_run_pending(cfg):
            defender.mark(cfg, "asked")           # asked = shown, so it never nags
            app._defender_offer = DefenderOffer(app, app=app)
            return True
    except Exception:
        return False
    try:
        if defender.auto_pending(cfg):
            defender.apply_async(config=cfg,
                                 on_done=lambda rep: report_result(app, rep))
            return True
    except Exception:
        pass
    return False
