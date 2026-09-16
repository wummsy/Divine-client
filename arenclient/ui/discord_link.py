"""Connect Discord to Divine Client.

Runs the server-driven link flow: the launcher asks the Divine server for a short
code + a link URL, the user approves in their browser (which handles the real
Discord OAuth), and the launcher polls until it's done. No secrets in the app.
"""
import threading
import webbrowser

import customtkinter as ctk

from ..core import social
from . import theme
from .widgets import Card, accent_button, ghost_button


class DiscordLinkDialog(ctk.CTkToplevel):
    def __init__(self, master, app, on_done=None):
        super().__init__(master)
        self.app = app
        self._on_done = on_done
        self._cancelled = False

        self.title("Connect Discord")
        self.geometry("520x430")
        self.configure(fg_color=theme.COL["bg2"])
        self.transient(master)
        self.grab_set()
        self.grid_columnconfigure(0, weight=1)
        self.protocol("WM_DELETE_WINDOW", self._cancel)

        ctk.CTkLabel(self, text="Connect Discord", font=theme.title_font(20),
                     text_color=theme.COL["text"]).grid(row=0, column=0, sticky="w",
                                                        padx=26, pady=(24, 2))
        ctk.CTkLabel(self, text="Link your Discord to add friends and show your name "
                     "and avatar. Approve it in your browser \u2014 it finishes on its own.",
                     font=theme.font(12), text_color=theme.COL["text_dim"],
                     wraplength=460, justify="left"
                     ).grid(row=1, column=0, sticky="w", padx=26)

        code_card = Card(self, fg_color=theme.COL["bg3"])
        code_card.grid(row=2, column=0, sticky="ew", padx=26, pady=(16, 10))
        code_card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(code_card, text="YOUR CODE", font=theme.font(11, "bold"),
                     text_color=theme.COL["text_faint"]).grid(row=0, column=0, pady=(14, 0))
        self.code_lbl = ctk.CTkLabel(code_card, text="\u2014 \u2014 \u2014 \u2014 \u2014",
                                     font=theme.title_font(28),
                                     text_color=theme.COL["accent2"])
        self.code_lbl.grid(row=1, column=0, pady=(2, 6))
        self.copy_btn = ghost_button(code_card, "Copy code", self._copy, width=130, height=34)
        self.copy_btn.grid(row=2, column=0, pady=(0, 14))
        self.copy_btn.configure(state="disabled")

        self.open_btn = accent_button(self, "Open link page", self._open, height=44)
        self.open_btn.grid(row=3, column=0, sticky="ew", padx=26, pady=(2, 6))
        self.open_btn.configure(state="disabled")

        self.status = ctk.CTkLabel(self, text="Preparing\u2026", font=theme.font(12),
                                   text_color=theme.COL["accent"], wraplength=460,
                                   justify="left")
        self.status.grid(row=4, column=0, sticky="w", padx=26, pady=(8, 0))

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.grid(row=5, column=0, sticky="ew", padx=26, pady=18)
        row.grid_columnconfigure(0, weight=1)
        ghost_button(row, "Cancel", self._cancel, width=120).grid(row=0, column=1)

        self._verify_url = None
        self._code = None
        threading.Thread(target=self._start, daemon=True).start()

    def _start(self):
        try:
            data = social.start_link(self.app.config_store)
        except Exception as e:
            msg = str(e)
            self.after(0, lambda: self.status.configure(text=msg,
                                                        text_color=theme.COL["danger"]))
            return
        self._code = data["code"]
        self._verify_url = data["verification_url"]
        self.after(0, self._show_code)
        threading.Thread(target=self._poll_worker, args=(data,), daemon=True).start()

    def _show_code(self):
        self.code_lbl.configure(text="  ".join(self._code) if self._code else "\u2014")
        self.copy_btn.configure(state="normal")
        self.open_btn.configure(state="normal")
        self.status.configure(
            text="1. Open the link.   2. Sign in with Discord.   3. Enter your code.\n"
                 "Waiting for you to finish in the browser\u2026",
            text_color=theme.COL["accent"])

    def _poll_worker(self, data):
        try:
            link = social.poll_link(self.app.config_store, data["link_id"],
                                    data["interval"], data["expires_in"],
                                    should_cancel=lambda: self._cancelled)
        except social.SocialError as e:
            if self._cancelled:
                return
            msg = str(e)
            self.after(0, lambda: self.status.configure(text=msg,
                                                        text_color=theme.COL["danger"]))
            return
        except Exception:
            if self._cancelled:
                return
            self.after(0, lambda: self.status.configure(
                text="Linking failed. Try again.", text_color=theme.COL["danger"]))
            return
        if self._cancelled:
            return
        self.after(0, lambda: self.status.configure(
            text="\u2713 Connected as " + (link.get("username") or "Discord") + "!",
            text_color=theme.COL["good"]))
        if self._on_done:
            self.after(0, self._on_done)
        self.after(1100, self.destroy)

    def _copy(self):
        if not self._code:
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(self._code)
            self.copy_btn.configure(text="Copied")
            self.after(1500, lambda: self.copy_btn.configure(text="Copy code"))
        except Exception:
            pass

    def _open(self):
        if self._verify_url:
            webbrowser.open(self._verify_url)
            self.status.configure(text="Browser opened. Approve, then this window updates "
                                  "automatically.", text_color=theme.COL["accent"])

    def _cancel(self):
        self._cancelled = True
        self.destroy()
