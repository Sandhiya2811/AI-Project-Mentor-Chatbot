"""AI Project Mentor.

    py main.py                 start the desktop application
    py main.py --benchmark     measure YOUR model: time to first token, tokens/second, model-load time
    py main.py --check-links   check every curated learning-resource URL (needs internet)
"""
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


def benchmark() -> None:
    """Measures the model the app is configured for, with the same kind of prompt the mentor sends."""
    import time

    from ai_engine import intent_router, prompts
    from ai_engine.llm_provider import LLMError, get_provider
    from config import settings

    print(f"Provider {settings.get('LLM_PROVIDER')}, model {settings.provider_value('model')}\n")
    t = time.perf_counter()
    try:
        llm = get_provider()
        ok, msg = llm.health()
        print(f"health check: {msg}")
        if not ok:
            return
        print("1) warm-up (loads the model into memory) ...")
        llm.warm_up()
        print(f"   done in {time.perf_counter() - t:.1f}s  <- this is paid once; later requests reuse the loaded model\n")
        tasks = [{"position": 1, "title": "Project Understanding and Planning", "status": "active", "description": ""}]
        t0 = time.perf_counter()
        for i in range(200):
            intent_router.classify("Libraries ennalam venum?", {"title": "Student Performance Predictor", "objective": ""}, tasks, ["Pandas"])
        print(f"2) intent routing: {(time.perf_counter() - t0) / 200 * 1000:.3f} ms per message (no LLM involved)\n")
        system = prompts.system_prompt("student", "Student Performance Predictor - predict grades", "Task 1", "", "", "reply in the student's language",
                                       roadmap="\n".join(f"{i}. [Locked] Stage {i}" for i in range(1, 9)))
        for label, question, limit in (("short answer", "Why do we need Pandas in this project? Answer in 3 sentences.", 120),
                                       ("detailed answer", "Which libraries do I need and why? Explain each in two sentences.", 400)):
            print(f"3) {label} (streaming, max {limit} tokens)")
            text, n = "", 0
            for piece in llm.stream_chat([{"role": "system", "content": system}, {"role": "user", "content": question}], max_tokens=limit):
                text, n = text + piece, n + 1
            s = llm.last_stats
            first = s.get("ttft_s")
            print(f"   first token after : {first:.2f}s" if first is not None else "   first token       : n/a")
            print(f"   total             : {s.get('total_s', 0):.1f}s for {n} streamed pieces")
            if s.get("eval_count") and s.get("eval_duration"):
                print(f"   generation speed  : {s['eval_count'] / (s['eval_duration'] / 1e9):.1f} tokens/s")
            if s.get("prompt_eval_count"):
                print(f"   prompt tokens     : {s['prompt_eval_count']} (evaluated in {s.get('prompt_eval_duration', 0) / 1e9:.2f}s)")
            if s.get("load_duration"):
                print(f"   model load time   : {s['load_duration'] / 1e9:.2f}s  (should be ~0 after warm-up)")
            print()
        print("Reading the result: 'first token' is what the student waits for. If it is above ~5 s, use a smaller or more\n"
              "quantised model, or a GPU. If tokens/s is low, answers stream slowly but still appear progressively.")
    except LLMError as exc:
        print(f"Cannot benchmark: {exc}")


def check_links() -> None:
    """HEAD/GET every curated URL; prints the ones that do not answer with a success or redirect status."""
    import requests

    from learning import resource_manager

    urls: dict[str, str] = {}
    for e in resource_manager.CATALOG.values():
        urls[e.official[1]] = f"{e.name} (official)"
        for title, url, _src in e.links:
            urls.setdefault(url, f"{e.name}: {title}")
    print(f"Checking {len(urls)} URLs ...")
    bad = 0
    for url, label in sorted(urls.items(), key=lambda kv: kv[1]):
        try:
            r = requests.head(url, allow_redirects=True, timeout=15, headers={"User-Agent": "mentor-link-check"})
            if r.status_code in (403, 405, 501):  # some sites refuse HEAD
                r = requests.get(url, stream=True, timeout=15, headers={"User-Agent": "mentor-link-check"})
            ok = r.status_code < 400
            detail = f"HTTP {r.status_code}"
        except requests.RequestException as exc:
            ok, detail = False, exc.__class__.__name__
        if not ok:
            bad += 1
            print(f"  BROKEN  {label}\n          {url}  ({detail})")
    print(f"Done: {len(urls) - bad} reachable, {bad} not reachable.")


def main() -> None:
    _check_environment()
    from config import APP_NAME, DB_PATH, STORAGE_DIR, settings
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    if "--benchmark" in sys.argv:
        return benchmark()
    if "--check-links" in sys.argv:
        return check_links()
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
    print("Opening the desktop window... (logs and errors appear here; per-answer timings are logged as 'chat timings')\n")

    from interface.app import App
    App().mainloop()


if __name__ == "__main__":
    main()
