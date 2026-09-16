"""Accounts page: manage offline and Microsoft accounts."""
import threading
import webbrowser

import customtkinter as ctk

from ...core import accounts as acc_mod
from .. import theme
from ..widgets import flow_label
from ..widgets import Card, PageFrame, accent_button, danger_button, ghost_button, scroll_frame


class AccountsPage(PageFrame):
    def __init__(self, master, app):
        super().__init__(master, kind="page")
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

# the page name lives in the bar above; repeating it here reads as a mistake

        addrow = ctk.CTkFrame(self)
        addrow.grid(row=1, column=0, sticky="ew", padx=26, pady=(6, 10))
        accent_button(addrow, "\u263A  Add offline account", self._add_offline,
                      width=220, height=42).pack(side="left", padx=(0, 10))
        ghost_button(addrow, "\u25A9  Sign in with Microsoft", self._add_microsoft,
                     width=240, height=42).pack(side="left")

        self.list_frame = scroll_frame(self)
        self.list_frame.grid(row=2, column=0, sticky="nsew", padx=20, pady=(0, 16))
        self.list_frame.grid_columnconfigure(0, weight=1)

    def on_show(self):
        self.refresh()

    def refresh(self):
        for w in self.list_frame.winfo_children():
            w.destroy()
        self.app.accounts.load()
        if not self.app.accounts.accounts:
            ctk.CTkLabel(self.list_frame,
                         text="No accounts yet.\nAdd an offline name to play singleplayer, "
                              "or sign in with Microsoft for premium servers.",
                         font=theme.font(14), text_color=theme.COL["text_faint"],
                         justify="left").grid(row=0, column=0, sticky="w", padx=10, pady=24)
            return
        active = self.app.accounts.get_active()
        for idx, a in enumerate(self.app.accounts.accounts):
            self._account_card(a, idx, is_active=(active and a["id"] == active["id"]))

    def _account_card(self, a, idx, is_active):
        card = Card(card_master := self.list_frame)
        card.grid(row=idx, column=0, sticky="ew", padx=6, pady=6)
        card.grid_columnconfigure(1, weight=1)
        if is_active:
            card.configure(border_color=theme.COL["accent"], border_width=2)

        initial = (a["name"][:1] or "?").upper()
        col = theme.COL["accent2"] if a["type"] == "microsoft" else theme.COL["accent"]
        ctk.CTkLabel(card, text=initial, width=48, height=48, corner_radius=24,
                     font=theme.font(20, "bold"), text_color="#04121a", fg_color=col
                     ).grid(row=0, column=0, rowspan=2, padx=(16, 14), pady=14)

        ctk.CTkLabel(card, text=a["name"], font=theme.font(16, "bold"),
                     text_color=theme.COL["text"], anchor="w"
                     ).grid(row=0, column=1, sticky="w", pady=(14, 0))
        kind = "Microsoft (premium)" if a["type"] == "microsoft" else "Offline"
        tag = "  \u2022  active" if is_active else ""
        ctk.CTkLabel(card, text=kind + tag, font=theme.font(12),
                     text_color=theme.COL["accent"] if is_active else theme.COL["text_dim"],
                     anchor="w").grid(row=1, column=1, sticky="w", pady=(0, 14))

        btns = ctk.CTkFrame(card)
        btns.grid(row=0, column=2, rowspan=2, padx=14)
        if not is_active:
            ghost_button(btns, "Use", lambda i=a["id"]: self._use(i),
                         width=80, height=38).grid(row=0, column=0, padx=4)
        danger_button(btns, "Remove", lambda i=a["id"]: self._remove(i),
                      width=90, height=38).grid(row=0, column=1, padx=4)

    def _use(self, account_id):
        self.app.accounts.set_active(account_id)
        self.refresh()
        self.app.pages["home"]._update_account()

    def _remove(self, account_id):
        self.app.accounts.remove(account_id)
        self.refresh()
        self.app.pages["home"]._update_account()

    def _add_offline(self):
        dlg = OfflineDialog(self)
        self.wait_window(dlg)
        if dlg.username:
            self.app.accounts.add_offline(dlg.username)
            self.refresh()
            self.app.pages["home"]._update_account()

    def _add_microsoft(self):
        dlg = MicrosoftDialog(self, self.app)
        self.wait_window(dlg)
        self.refresh()
        self.app.pages["home"]._update_account()


class OfflineDialog(ctk.CTkToplevel):
    def __init__(self, master):
        super().__init__(master)
        self.username = None
        self.title("Offline account")
        self.geometry("400x210")
        self.configure(fg_color=theme.COL["bg2"])
        self.transient(master)
        self.grab_set()
        ctk.CTkLabel(self, text="Offline account", font=theme.title_font(18),
                     text_color=theme.COL["text"]).pack(anchor="w", padx=22, pady=(20, 2))
        ctk.CTkLabel(self, text="Works for singleplayer and offline-mode servers.",
                     font=theme.font(12), text_color=theme.COL["text_dim"]
                     ).pack(anchor="w", padx=22)
        self.entry = ctk.CTkEntry(self, height=42, font=theme.font(14),
                                  fg_color=theme.COL["bg3"], border_color=theme.COL["border"],
                                  placeholder_text="Username")
        self.entry.pack(fill="x", padx=22, pady=(16, 0))
        self.entry.focus()
        self.entry.bind("<Return>", lambda e: self._ok())
        row = ctk.CTkFrame(self)
        row.pack(side="bottom", fill="x", padx=22, pady=18)
        ghost_button(row, "Cancel", self.destroy, width=110).pack(side="right", padx=(8, 0))
        accent_button(row, "Add", self._ok, width=120, height=40).pack(side="right")

    def _ok(self):
        name = self.entry.get().strip()
        if name:
            self.username = name
            self.destroy()


class MicrosoftDialog(ctk.CTkToplevel):
    """Microsoft sign-in via the device-code flow.

    The user gets a short code and a link, approves the sign-in in any browser,
    and the launcher finishes automatically. No copying redirect URLs.
    """
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self._cancelled = False
        self._done = False

        self.title("Sign in with Microsoft")
        self.geometry("520x430")
        self.configure(fg_color=theme.COL["bg2"])
        self.transient(master)
        self.grab_set()
        self.grid_columnconfigure(0, weight=1)
        self.protocol("WM_DELETE_WINDOW", self._cancel)

        ctk.CTkLabel(self, text="Sign in with Microsoft", font=theme.title_font(20),
                     text_color=theme.COL["text"]).grid(row=0, column=0, sticky="w",
                                                        padx=26, pady=(24, 2))
        flow_label(self, text="Approve this sign-in in your browser \u2014 no copying "
                     "links, it finishes on its own.", font=theme.font(12),
                     text_color=theme.COL["text_dim"], justify="left"
                     ).grid(row=1, column=0, sticky="ew", padx=26)

        # step 1: the code
        code_card = Card(self, fg_color=theme.COL["bg3"])
        code_card.grid(row=2, column=0, sticky="ew", padx=26, pady=(16, 10))
        code_card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(code_card, text="YOUR CODE", font=theme.font(11, "bold"),
                     text_color=theme.COL["text_faint"]).grid(row=0, column=0, pady=(14, 0))
        self.code_lbl = ctk.CTkLabel(code_card, text="\u2014 \u2014 \u2014 \u2014 \u2014",
                                     font=theme.title_font(30),
                                     text_color=theme.COL["accent"])
        self.code_lbl.grid(row=1, column=0, pady=(2, 6))
        self.copy_btn = ghost_button(code_card, "Copy code", self._copy_code,
                                     width=130, height=34)
        self.copy_btn.grid(row=2, column=0, pady=(0, 14))
        self.copy_btn.configure(state="disabled")

        self.open_btn = accent_button(self, "Open microsoft.com/link", self._open, height=44)
        self.open_btn.grid(row=3, column=0, sticky="ew", padx=26, pady=(2, 6))
        self.open_btn.configure(state="disabled")

        self.status = flow_label(self, text="Preparing sign-in...", font=theme.font(12),
                                   text_color=theme.COL["accent"],
                                   justify="left")
        self.status.grid(row=4, column=0, sticky="w", padx=26, pady=(8, 0))

        row = ctk.CTkFrame(self)
        row.grid(row=5, column=0, sticky="ew", padx=26, pady=18)
        row.grid_columnconfigure(0, weight=1)
        ghost_button(row, "Cancel", self._cancel, width=120).grid(row=0, column=1)

        self._verify_uri = "https://www.microsoft.com/link"
        self._user_code = None
        threading.Thread(target=self._start, daemon=True).start()

    # ---- device flow ------------------------------------------------
    def _start(self):
        try:
            dc = acc_mod.start_device_login()
        except Exception as e:
            msg = str(e)
            self.after(0, lambda: self.status.configure(
                text=msg, text_color=theme.COL["danger"]))
            return
        self._user_code = dc["user_code"]
        self._verify_uri = dc["verification_uri"]
        self.after(0, self._show_code)
        # begin polling in the background
        threading.Thread(target=self._poll_worker, args=(dc,), daemon=True).start()

    def _show_code(self):
        self.code_lbl.configure(text="  ".join(self._user_code))
        self.copy_btn.configure(state="normal")
        self.open_btn.configure(state="normal")
        self.status.configure(
            text="1. Open the link.   2. Enter the code above.   3. Approve.\n"
                 "Waiting for you to finish in the browser...",
            text_color=theme.COL["accent"])

    def _poll_worker(self, dc):
        try:
            login = acc_mod.poll_device_login(
                dc["device_code"], dc["interval"], dc["expires_in"],
                should_cancel=lambda: self._cancelled)
        except acc_mod.MicrosoftAuthError as e:
            if self._cancelled:
                return
            msg = str(e)
            self.after(0, lambda: self.status.configure(
                text=msg, text_color=theme.COL["danger"]))
            return
        except Exception as e:
            if self._cancelled:
                return
            msg = str(e)
            self.after(0, lambda: self.status.configure(
                text="Sign-in failed: " + msg[:120], text_color=theme.COL["danger"]))
            return
        if self._cancelled:
            return
        self.app.accounts.add_microsoft(login)
        self._done = True
        self.after(0, lambda: self.status.configure(
            text="\u2713 Signed in as " + login["name"] + "!",
            text_color=theme.COL["good"]))
        self.after(1100, self.destroy)

    def _copy_code(self):
        if not self._user_code:
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(self._user_code)
            self.copy_btn.configure(text="Copied")
            self.after(1500, lambda: self.copy_btn.configure(text="Copy code"))
        except Exception:
            pass

    def _open(self):
        webbrowser.open(self._verify_uri)
        self.status.configure(
            text="Browser opened. Enter your code and approve \u2014 this window "
                 "updates automatically.", text_color=theme.COL["accent"])

    def _cancel(self):
        self._cancelled = True
        self.destroy()
