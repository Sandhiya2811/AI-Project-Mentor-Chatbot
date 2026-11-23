"""Home ("Create Your Project") and Previous Projects screens."""
from __future__ import annotations

import customtkinter as ctk

from interface import theme
from utils.helpers import strip_non_bmp

EXAMPLES = ["Fake News Detection", "AI Voice Assistant", "Student Performance Prediction", "Disease Prediction",
            "E-commerce Recommendation System"]


class HomeView(ctk.CTkFrame):
    def __init__(self, master, on_start):
        super().__init__(master, fg_color=theme.color("bg"), corner_radius=0)
        self.on_start = on_start
        center = ctk.CTkFrame(self, fg_color="transparent")
        center.place(relx=0.5, rely=0.45, anchor="center")
        ctk.CTkLabel(center, text="Create Your Project", font=theme.font(34, "bold")).pack(pady=(0, 10))
        ctk.CTkLabel(center, text=("Let's turn your project idea into a real working project. I'll guide you step by "
                                   "step, review your work, explain errors, and help you complete your project."),
                     font=theme.font(14), text_color=theme.color("muted"), wraplength=640, justify="center").pack(pady=(0, 18))
        self.idea = ctk.CTkTextbox(center, width=640, height=96, wrap="word", font=theme.font(14), corner_radius=12,
                                   border_width=1, border_color=theme.color("border"), fg_color=theme.color("card"))
        self.idea.pack()
        self.idea.bind("<Return>", self._enter)
        self.start_btn = ctk.CTkButton(center, text="Start Your Project", height=42, width=240, corner_radius=12,
                                       font=theme.font(15, "bold"), fg_color=theme.color("accent"),
                                       hover_color=theme.color("accent_hover"), text_color="#ffffff", command=self.start)
        self.start_btn.pack(pady=14)
        self.status = ctk.CTkLabel(center, text="", font=theme.font(12), text_color=theme.color("accent"), wraplength=640)
        self.status.pack()
        ctk.CTkLabel(center, text="Need inspiration? Try one of these:", font=theme.font(12),
                     text_color=theme.color("muted")).pack(pady=(14, 6))
        chips = ctk.CTkFrame(center, fg_color="transparent")
        chips.pack()
        for i, ex in enumerate(EXAMPLES):
            ctk.CTkButton(chips, text=f"{i + 1}. {ex}", height=32, corner_radius=16, font=theme.font(12),
                          fg_color=theme.color("card"), hover_color=theme.color("hover"), text_color=theme.color("text"),
                          command=lambda e=ex: self._fill(e)).grid(row=i // 3, column=i % 3, padx=4, pady=4)
        self.banner = ctk.CTkLabel(self, text="", font=theme.font(12), text_color=theme.color("warn"), wraplength=760)
        self.banner.place(relx=0.5, rely=0.96, anchor="center")

    def _enter(self, event):
        if event.state & 0x1:
            return None
        self.start()
        return "break"

    def _fill(self, text: str) -> None:
        self.idea.delete("1.0", "end")
        self.idea.insert("1.0", f"I want to build a {text} project.")

    def start(self) -> None:
        idea = self.idea.get("1.0", "end-1c").strip()
        if len(idea) < 4:
            self.status.configure(text="Please describe your project idea first.", text_color=theme.color("warn"))
            return
        self.on_start(idea)

    def set_busy(self, busy: bool, text: str = "") -> None:
        self.start_btn.configure(state="disabled" if busy else "normal", text="Working..." if busy else "Start Your Project")
        self.status.configure(text=strip_non_bmp(text), text_color=theme.color("accent"))

    def reset(self) -> None:
        self.idea.delete("1.0", "end")
        self.set_busy(False)

    def set_banner(self, text: str, ok: bool = False) -> None:
        """Status line at the bottom of the home screen: green = AI connected, amber = problem."""
        self.banner.configure(text=strip_non_bmp(text), text_color=theme.color("ok" if ok else "warn"))


class ProjectsView(ctk.CTkFrame):
    def __init__(self, master, on_resume, on_delete, on_notes):
        super().__init__(master, fg_color=theme.color("bg"), corner_radius=0)
        self.on_resume, self.on_delete, self.on_notes = on_resume, on_delete, on_notes
        ctk.CTkLabel(self, text="Previous Projects", font=theme.font(24, "bold"), anchor="w").pack(fill="x", padx=32, pady=(24, 4))
        ctk.CTkLabel(self, text="Each project keeps its own roadmap, submissions and conversation.",
                     font=theme.font(13), text_color=theme.color("muted"), anchor="w").pack(fill="x", padx=32)
        self.list = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.list.pack(fill="both", expand=True, padx=24, pady=12)

    def set_projects(self, projects: list[dict]) -> None:
        for w in self.list.winfo_children():
            w.destroy()
        if not projects:
            ctk.CTkLabel(self.list, text="No projects yet. Start one from New Chat.", text_color=theme.color("muted")).pack(pady=30)
            return
        for p in projects:
            card = ctk.CTkFrame(self.list, fg_color=theme.color("card"), corner_radius=14)
            card.pack(fill="x", pady=6, padx=6)
            top = ctk.CTkFrame(card, fg_color="transparent")
            top.pack(fill="x", padx=16, pady=(12, 0))
            ctk.CTkLabel(top, text=strip_non_bmp(p["title"]), font=theme.font(16, "bold"), anchor="w").pack(side="left")
            state = "Completed" if p["status"] == "completed" else "In progress"
            ctk.CTkLabel(top, text=state, font=theme.font(12, "bold"),
                         text_color=theme.color("ok") if p["status"] == "completed" else theme.color("warn")).pack(side="right")
            ctk.CTkLabel(card, text=f"{p['programming_language']}  |  {p['domain']}  |  {p['difficulty']}  |  "
                                    f"roadmap: {'AI-designed' if p['roadmap_source'] == 'llm' else 'template'}",
                         font=theme.font(12), text_color=theme.color("muted"), anchor="w").pack(fill="x", padx=16)
            bar = ctk.CTkProgressBar(card, height=8, progress_color=theme.color("accent"))
            bar.set((p["percent"] or 0) / 100)
            bar.pack(fill="x", padx=16, pady=(8, 2))
            ctk.CTkLabel(card, text=f"{p['completed_tasks'] or 0}/{p['total_tasks'] or 0} tasks completed",
                         font=theme.font(12), text_color=theme.color("muted"), anchor="w").pack(fill="x", padx=16)
            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(fill="x", padx=12, pady=10)
            ctk.CTkButton(row, text="Resume", width=90, fg_color=theme.color("accent"), hover_color=theme.color("accent_hover"),
                          text_color="#ffffff", command=lambda i=p["id"]: self.on_resume(i)).pack(side="left", padx=4)
            ctk.CTkButton(row, text="Learning notes", width=120, fg_color=theme.color("bg"), hover_color=theme.color("hover"),
                          text_color=theme.color("text"), command=lambda i=p["id"]: self.on_notes(i)).pack(side="left", padx=4)
            ctk.CTkButton(row, text="Delete", width=80, fg_color=theme.color("danger"), hover_color=theme.color("danger_hover"),
                          text_color="#ffffff", command=lambda i=p["id"], t=p["title"]: self.on_delete(i, t)).pack(side="right", padx=4)
