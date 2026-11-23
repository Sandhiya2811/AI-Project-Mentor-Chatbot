"""Colours (light, dark), fonts and appearance handling."""
from __future__ import annotations

import sys

import customtkinter as ctk

PALETTE = {
    "bg": ("#ffffff", "#212121"), "sidebar": ("#f4f4f5", "#171717"), "card": ("#f4f4f5", "#2a2a2a"),
    "user_bubble": ("#e3edff", "#2f3a55"), "ai_bubble": ("#f4f4f5", "#2a2b2e"),
    "review_bubble": ("#fff6dd", "#2d2a1f"), "notice_bubble": ("#fdeceb", "#3a2523"),
    "text": ("#1f1f1f", "#ececec"), "muted": ("#6b6b6b", "#a0a0a0"),
    "accent": ("#10a37f", "#10a37f"), "accent_hover": ("#0d8c6d", "#0d8c6d"),
    "border": ("#d9d9dc", "#3a3a3a"), "hover": ("#e4e4e7", "#2f2f2f"), "selected": ("#e0e0e4", "#343434"),
    "ok": ("#13795b", "#4cd9a6"), "bad": ("#c62828", "#ff7b72"), "warn": ("#a35f00", "#f0b429"),
    "code_bg": ("#e8e8ec", "#161616"), "danger": ("#d64545", "#d64545"), "link": ("#0b57d0", "#7ab7ff"), "danger_hover": ("#b83838", "#b83838"),
}

FAMILY = "Segoe UI" if sys.platform == "win32" else ("Helvetica Neue" if sys.platform == "darwin" else "DejaVu Sans")
MONO = "Consolas" if sys.platform == "win32" else ("Menlo" if sys.platform == "darwin" else "DejaVu Sans Mono")


def color(name: str) -> tuple[str, str]:
    return PALETTE[name]


def resolve(name: str) -> str:
    """Single colour string for plain tkinter widgets, based on the current appearance."""
    return PALETTE[name][1 if ctk.get_appearance_mode() == "Dark" else 0]


def font(size: int = 13, weight: str = "normal") -> ctk.CTkFont:
    return ctk.CTkFont(family=FAMILY, size=size, weight=weight)


def apply_mode(mode: str) -> None:
    ctk.set_appearance_mode({"dark": "dark", "light": "light"}.get(mode, "system"))
    ctk.set_default_color_theme("blue")
