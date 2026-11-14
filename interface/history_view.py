"""Chat-history list shown inside the sidebar."""
from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

from interface import theme
from utils.helpers import short_title


class HistoryList(ctk.CTkScrollableFrame):
    def __init__(self, master, on_open, on_rename, on_delete):
        super().__init__(master, fg_color="transparent", corner_radius=0)
        self.on_open, self.on_rename, self.on_delete = on_open, on_rename, on_delete
        self._rows: list[ctk.CTkFrame] = []

    def set_items(self, conversations: list[dict], active_id: int | None) -> None:
        for r in self._rows:
            r.destroy()
        self._rows = []
        if not conversations:
            lbl = ctk.CTkLabel(self, text="No conversations yet", text_color=theme.color("muted"), font=theme.font(12))
            lbl.pack(pady=12)
            self._rows.append(lbl)
            return
        for conv in conversations:
            row = ctk.CTkFrame(self, fg_color=theme.color("selected") if conv["id"] == active_id else "transparent",
                               corner_radius=8)
            row.pack(fill="x", pady=1)
            btn = ctk.CTkButton(row, text=short_title(conv["title"], 26), anchor="w", fg_color="transparent",
                                hover_color=theme.color("hover"), text_color=theme.color("text"), height=32,
                                font=theme.font(13), command=lambda c=conv["id"]: self.on_open(c))
            btn.pack(side="left", fill="x", expand=True)
            more = ctk.CTkButton(row, text="...", width=28, height=28, fg_color="transparent",
                                 hover_color=theme.color("hover"), text_color=theme.color("muted"),
                                 command=lambda c=conv: self._menu(c, more))
            more.pack(side="right", padx=(0, 4))
            for w in (row, btn):
                w.bind("<Button-3>", lambda e, c=conv: self._menu(c, e.widget, e))
            self._rows.append(row)

    def _menu(self, conv: dict, widget, event=None) -> None:
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Rename", command=lambda: self.on_rename(conv["id"], conv["title"]))
        menu.add_command(label="Delete", command=lambda: self.on_delete(conv["id"]))
        x = event.x_root if event else widget.winfo_rootx()
        y = event.y_root if event else widget.winfo_rooty() + widget.winfo_height()
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()
