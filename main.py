"""AI Project Mentor - run with:  python main.py"""
from __future__ import annotations

import logging
import sys

MIN_PY = (3, 9)


def _check_environment() -> None:
    if sys.version_info < MIN_PY:
        sys.exit(f"Python {MIN_PY[0]}.{MIN_PY[1]}+ is required (found {sys.version.split()[0]}).")
    missing = []
    for mod, pkg in (("customtkinter", "customtkinter"), ("requests", "requests"), ("numpy", "numpy")):
        try:
            __import__(mod)
        except ImportError:
            missing.append(pkg)
    if missing:
        sys.exit("Missing packages: " + ", ".join(missing) + "\nInstall with:  pip install -r requirements.txt")


def main() -> None:
    _check_environment()
    from config import APP_NAME, DB_PATH, STORAGE_DIR, settings
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(STORAGE_DIR / "app.log", encoding="utf-8")])
    from database.db import init_db
    from ai_engine.llm_provider import quick_health
    from rag import knowledge_base
    from utils import sandbox

    init_db()
    ok, msg = quick_health()
    print(f"\n=== {APP_NAME} ===")
    print(f"Database      : {DB_PATH}")
    print(f"LLM provider  : {settings.get('LLM_PROVIDER')} -> {'OK' if ok else 'NOT READY'} ({msg})")
    print(f"RAG           : {'FAISS' if knowledge_base.faiss else 'numpy fallback (pip install faiss-cpu for FAISS)'}, "
          f"embeddings={settings.get('EMBEDDING_BACKEND')}")
    print(f"Sandbox       : {sandbox.execution_status()}")
    print("Opening the desktop window... (logs and errors appear here)\n")

    from interface.app import App
    App().mainloop()


if __name__ == "__main__":
    main()
