from __future__ import annotations

import customtkinter as ctk

from config import APP_NAME
from interface import theme
from interface.history_view import HistoryList


class Sidebar(ctk.CTkFrame):
    def __init__(self, master, actions: dict, history_callbacks: tuple):
        super().__init__(master, width=290, corner_radius=0, fg_color=theme.color("sidebar"))
        self.pack_propagate(False)
        self.actions = actions
        ctk.CTkLabel(self, text="◆  " + APP_NAME, font=theme.font(18, "bold"), anchor="w",
                     text_color=theme.color("text")).pack(fill="x", padx=18, pady=(18, 10))
        ctk.CTkButton(self, text="+  New Chat", height=38, corner_radius=10, font=theme.font(14, "bold"),
                      fg_color=theme.color("accent"), hover_color=theme.color("accent_hover"), text_color="#ffffff",
                      command=actions["new_chat"]).pack(fill="x", padx=14, pady=(0, 10))
        search = ctk.CTkEntry(self, placeholder_text="Search chat history", height=32, corner_radius=8,
                              border_color=theme.color("border"))
        search.pack(fill="x", padx=14, pady=(0, 6))
        search.bind("<KeyRelease>", lambda e: actions["search"](search.get()))
        ctk.CTkLabel(self, text="Chat History", font=theme.font(11, "bold"), text_color=theme.color("muted"),
                     anchor="w").pack(fill="x", padx=18)
        self.history = HistoryList(self, *history_callbacks)
        self.history.pack(fill="both", expand=True, padx=6, pady=(2, 6))
        ctk.CTkFrame(self, height=1, fg_color=theme.color("border")).pack(fill="x", padx=14)
        for label, key in (("Previous Projects", "projects"), ("Learning Resources", "resources"),
                           ("Settings", "settings"), ("User Profile", "profile")):
            self._nav(label, actions[key])
        self._nav("Clear Chat History", actions["clear_history"], danger=True)
        ctk.CTkFrame(self, height=8, fg_color="transparent").pack()

    def _nav(self, text: str, command, danger: bool = False) -> None:
        ctk.CTkButton(self, text=text, anchor="w", height=34, corner_radius=8, fg_color="transparent",
                      hover_color=theme.color("hover"), font=theme.font(13),
                      text_color=theme.color("danger") if danger else theme.color("text"),
                      command=command).pack(fill="x", padx=10, pady=1)
