"""About page: credits, paths and the built-in performance pack list."""
import os

import customtkinter as ctk

from ... import __version__, paths
from ...core import mods
from .. import theme
from ..widgets import flow_label
from ..widgets import Card, PageFrame, load_ctk_image, scroll_frame, section_label


class AboutPage(PageFrame):
    def __init__(self, master, app):
        super().__init__(master, kind="page")
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

# the page name lives in the bar above; repeating it here reads as a mistake

        scroll = scroll_frame(self)
        scroll.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 14))
        scroll.grid_columnconfigure(0, weight=1)

        top = Card(scroll)
        top.grid(row=0, column=0, sticky="ew", padx=6, pady=8)
        top.grid_columnconfigure(1, weight=1)
        logo = load_ctk_image(os.path.join("assets", "emblem.png"), size=(96, 96))
        if logo:
            ctk.CTkLabel(top, image=logo, text="").grid(row=0, column=0, rowspan=3,
                                                        padx=(18, 16), pady=18)
        ctk.CTkLabel(top, text="Divine Client", font=theme.title_font(24),
                     text_color=theme.COL["text"]).grid(row=0, column=1, sticky="w", pady=(18, 0))
        ctk.CTkLabel(top, text=f"Version {__version__}", font=theme.font(13),
                     text_color=theme.COL["accent"]).grid(row=1, column=1, sticky="w")
        ctk.CTkLabel(top, text="A fast, modern Minecraft launcher built by the Divine Dev Team.\n"
                              "Multi-instance \u2022 Java auto-download \u2022 Fabric \u2022 performance mods \u2022 Discord presence.",
                     font=theme.font(12), text_color=theme.COL["text_dim"], justify="left"
                     ).grid(row=2, column=1, sticky="w", pady=(2, 18))

        # performance pack
        pack = Card(scroll)
        pack.grid(row=1, column=0, sticky="ew", padx=6, pady=8)
        pack.grid_columnconfigure(0, weight=1)
        section_label(pack, "BUILT-IN PERFORMANCE PACK").grid(row=0, column=0, sticky="w",
                                                              padx=18, pady=(16, 6))
        row = 0
        for title, entries, note in (
                ("IN EVERY FABRIC INSTANCE", mods.PERFORMANCE_PACK,
                 "Client-only ones are kept off your hosted server automatically."),
                ("ON A HOSTED SERVER", mods.SERVER_PACK,
                 "Added when you press Host; remove them from the server's mods folder.")):
            ctk.CTkLabel(pack, text=title, font=theme.font(10, "bold"),
                         text_color=theme.COL["text_faint"], anchor="w"
                         ).grid(row=row, column=0, sticky="w", padx=22, pady=(10, 2))
            row += 1
            for slug, desc in entries:
                line = ctk.CTkFrame(pack)
                line.grid(row=row, column=0, sticky="ew", padx=22, pady=1)
                line.grid_columnconfigure(1, weight=1)
                ctk.CTkLabel(line, text="\u2022  " + slug, font=theme.font(12, "bold"),
                             text_color=theme.COL["accent"], anchor="w", width=150
                             ).grid(row=0, column=0, sticky="w")
                flow_label(line, text=desc, font=theme.font(11),
                             text_color=theme.COL["text_dim"], anchor="w", justify="left"
                             ).grid(row=0, column=1, sticky="ew")
                row += 1
            flow_label(pack, text=note, font=theme.font(10),
                         text_color=theme.COL["text_faint"], anchor="w", justify="left"
                         ).grid(row=row, column=0, sticky="w", padx=26, pady=(0, 4))
            row += 1
        flow_label(pack, text="Fetched from Modrinth for your exact Minecraft version, checksum-checked, and "
                     "skipped when a mod has no build for it - so nothing here can break an older instance.",
                     font=theme.font(10), text_color=theme.COL["text_faint"], anchor="w", justify="left"
                     ).grid(row=row, column=0, sticky="ew", padx=22, pady=(10, 16))

        # paths
        p = Card(scroll)
        p.grid(row=2, column=0, sticky="ew", padx=6, pady=8)
        p.grid_columnconfigure(0, weight=1)
        section_label(p, "FILE LOCATIONS").grid(row=0, column=0, sticky="w", padx=18, pady=(16, 6))
        for label, val in [("Data folder", paths.DATA_DIR),
                           ("Minecraft files", paths.MINECRAFT_DIR),
                           ("Instances", paths.INSTANCES_DIR)]:
            flow_label(p, text=f"{label}:  {val}", font=theme.font(11, ),
                         text_color=theme.COL["text_dim"], anchor="w", justify="left"
                         ).grid(sticky="ew", padx=22, pady=2)
        ctk.CTkLabel(p, text="", height=8).grid()

    def on_show(self):
        pass
