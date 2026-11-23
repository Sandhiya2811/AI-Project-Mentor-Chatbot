"""Learning resources: coverage of the requested technologies, relevance, format, de-duplication, clickable links.

GUI tests need a display (run them under `xvfb-run` on Linux; on Windows they run normally). They skip when no display.
Not tested: that the URLs are live today - run `py main.py --check-links` with internet access.
"""
import os
import re
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

os.environ["MENTOR_STORAGE_DIR"] = tempfile.mkdtemp(prefix="mentor_res_")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from learning import resource_manager as rm  # noqa: E402

REQUESTED = """Python Java C C++ JavaScript TypeScript C# PHP Go Rust R Ruby Kotlin Swift Dart Scala
NumPy Pandas Matplotlib Seaborn Plotly SQL MySQL PostgreSQL MongoDB Statistics Excel Power|BI Tableau
Scikit-learn XGBoost LightGBM CatBoost Feature|Engineering Model|Evaluation Hyperparameter|Tuning
TensorFlow Keras PyTorch JAX OpenCV CNN RNN LSTM Transformers
Natural|Language|Processing Hugging|Face LangChain LangGraph RAG LLMs Prompt|Engineering Fine-Tuning Vector|Databases FAISS ChromaDB Pinecone Ollama
HTML CSS React Angular Vue.js Node.js Express.js FastAPI Flask Django REST|APIs GraphQL
AWS Microsoft|Azure Google|Cloud|Platform Docker Kubernetes Git GitHub Streamlit Render Vercel CI/CD
Apache|Spark PySpark Hadoop Kafka Airflow Databricks ETL|Pipelines""".replace("\n", " ").split()
REQUESTED = [r.replace("|", " ") for r in REQUESTED]
LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")


def valid(url):
    u = urlparse(url)
    return u.scheme in ("http", "https") and "." in u.netloc and " " not in url


def test_every_requested_technology_has_official_docs_and_a_beginner_resource():
    missing, thin = [], []
    for name in REQUESTED:
        es = rm.find_entries(name)
        if not es:
            missing.append(name)
            continue
        if not all(valid(e.official[1]) for e in es) or not any(e.links for e in es):
            thin.append(name)
    assert not missing, f"no catalog entry for: {missing}"
    assert not thin, f"no 'Start with' resource or invalid URL for: {thin}"
    assert len(REQUESTED) == 88                      # 16 languages + 13 data + 7 ML + 9 DL + 13 AI + 12 web + 11 cloud + 7 big data


def test_catalog_urls_are_well_formed_and_unique_per_entry():
    for e in rm.CATALOG.values():
        urls = [e.official[1]] + [u for _t, u, _s in e.links]
        assert all(valid(u) for u in urls), e.key
        assert len(urls) == len(set(urls)), f"duplicate link inside {e.key}"
        assert all(t.strip() and s.strip() for t, _u, s in e.links), e.key           # every link has a title and a source name


TOOLS = [{"name": "Python", "detail": ""}, {"name": "NumPy", "detail": ""}, {"name": "PyTorch", "detail": ""}]
TASKS = [{"position": 1, "title": "Plan", "description": "", "status": "passed", "tools": ["Python"], "subtasks": []},
         {"position": 2, "title": "Prepare tensors", "description": "", "status": "active", "tools": ["NumPy", "PyTorch"], "subtasks": []},
         {"position": 3, "title": "Train", "description": "", "status": "locked", "tools": ["PyTorch"], "subtasks": []},
         {"position": 6, "title": "Report", "description": "", "status": "locked", "tools": ["Python"], "subtasks": []}]


def test_learning_path_has_the_requested_structure_and_only_relevant_technologies():
    text = rm.learning_path({"title": "Demo"}, TOOLS, TASKS)
    assert "## 1. Python  (needed for: Task 1, Task 6)" in text
    assert "## 2. NumPy  (needed for: Task 2)" in text and "## 3. PyTorch  (needed for: Task 2, Task 3)" in text
    assert "Official Documentation – [Python documentation](https://docs.python.org/3/)" in text
    assert "Start with – [The Python Tutorial](https://docs.python.org/3/tutorial/)" in text
    assert "Start with – [Virtual environments and packages]" in text
    assert "Start with – [Learn the Basics](https://pytorch.org/tutorials/beginner/basics/intro.html)" in text
    assert "## Start here - Task 2" in text                                              # the CURRENT task comes first
    for unrelated in ("Pandas", "Docker", "Kubernetes", "React", "TensorFlow", "Java "):
        assert unrelated not in text
    # no raw "label: url" plain-text layout any more - every URL sits inside a markdown link
    assert not re.search(r"(?<!\()https?://\S+", LINK.sub("", text))


def test_no_resource_is_listed_twice():
    tools = [{"name": n, "detail": ""} for n in ("Scikit-learn", "TF-IDF", "Logistic Regression", "Model Evaluation", "Feature Engineering")]
    urls = [u for _t, u in LINK.findall(rm.learning_path({"title": "x"}, tools, []))]
    assert urls and len(urls) == len(set(urls))
    block = rm.chat_block(tools, [])
    urls = [u for _t, u in LINK.findall(block)]
    assert len(urls) == len(set(urls))


def test_chat_links_block_is_clickable_markdown_and_limited_to_the_named_tools():
    block = rm.links_block(["Pandas", "Seaborn"])
    assert "**Pandas**" in block and "**Seaborn**" in block and "numpy.org" not in block
    assert all(valid(u) for _t, u in LINK.findall(block)) and "Official Documentation –" in block
    assert rm.links_block(["SomethingUnknown123"]) == ""                                  # never a guessed link


def test_unknown_technology_gets_no_invented_url():
    assert rm.find_doc("TotallyMadeUpFramework") == ""
    assert "No curated link" in rm.links_markdown("TotallyMadeUpFramework")


# ---------------------------------------------------------------------------------------------- GUI
@pytest.fixture(scope="module")
def tk_root():
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available (run under xvfb-run)")
    root.geometry("900x700+0+0")
    yield root
    root.destroy()


@pytest.fixture(autouse=True)
def _clean_gui(request):
    yield
    if "tk_root" in request.fixturenames:                  # earlier widgets must not squeeze the next test's widget to 0 px
        for child in request.getfixturevalue("tk_root").winfo_children():
            child.destroy()


def click_first_link(root, md, text):
    import tkinter as tk
    w = md.make_text(root, size=12)
    w.pack(fill="both", expand=True)
    md.render(w, text)
    w.configure(height=30)
    root.update()
    tags = [t for t in w.tag_names() if t.startswith("link_")]
    return w, tags


def fire(root, w, tag):
    """Move the pointer onto the link, then click (Tk only dispatches tag bindings after pointer motion)."""
    start = w.tag_ranges(tag)[0]
    w.see(start)
    root.update()
    x, y, wd, ht = w.bbox(start)
    w.event_generate("<Enter>", x=x + 1, y=y + ht // 2)
    for dx in (1, 4, 8):                                                      # a real mouse sends many motion events
        w.event_generate("<Motion>", x=x + dx, y=y + ht // 2)
        root.update()
    assert str(w.cget("cursor")) == "hand2"                                    # pointer turns into a hand over a link
    w.event_generate("<Button-1>", x=x + 8, y=y + ht // 2)
    root.update()


def test_learning_resource_titles_are_clickable_and_open_the_right_page(tk_root, monkeypatch):
    from interface import markdown_text as md
    opened = []
    monkeypatch.setattr(md, "_opener", lambda u: opened.append(u) or True)
    text = rm.learning_path({"title": "Demo"}, TOOLS, TASKS)
    w, tags = click_first_link(tk_root, md, text)
    expected = [u for _t, u in LINK.findall(text)]
    assert len(tags) == len(expected) >= 6
    assert all(str(w.tag_cget(t, "underline")) in ("1", "true") for t in tags)               # visibly a link
    assert w.tag_cget(tags[0], "foreground") == md.theme.resolve("link")
    for i, tag in enumerate(tags):
        fire(tk_root, w, tag)
        assert opened[-1] == expected[i]                                                        # each title opens ITS url
    assert "https://" not in w.get("1.0", "end")                                                # titles shown, not raw URLs


def test_bare_urls_and_punctuation(tk_root, monkeypatch):
    from interface import markdown_text as md
    opened = []
    monkeypatch.setattr(md, "_opener", lambda u: opened.append(u) or True)
    w, tags = click_first_link(tk_root, md, "Read https://docs.python.org/3/tutorial/venv.html. Then relax.")
    assert len(tags) == 1
    fire(tk_root, w, tags[0])
    assert opened == ["https://docs.python.org/3/tutorial/venv.html"]                          # trailing '.' is not part of the link
    assert w.get("1.0", "end").strip().endswith("Then relax.")


def test_links_survive_repeated_rendering_while_streaming(tk_root, monkeypatch):
    from interface import markdown_text as md
    opened = []
    monkeypatch.setattr(md, "_opener", lambda u: opened.append(u) or True)
    w, _ = click_first_link(tk_root, md, "Start")
    for i in range(30):
        md.render(w, "Intro\n[Docs](https://docs.python.org/3/)\n" + "x" * i)
    tk_root.update()
    assert len([t for t in w.tag_names() if t.startswith("link_")]) == 1                         # old tags removed, none leaked
    fire(tk_root, w, [t for t in w.tag_names() if t.startswith("link_")][0])
    assert opened == ["https://docs.python.org/3/"]


def test_invalid_or_unopenable_links_are_handled_gracefully(tk_root, monkeypatch):
    from interface import markdown_text as md
    warned = []
    monkeypatch.setattr(md, "_warn", lambda title, msg: warned.append((title, msg)))
    monkeypatch.setattr(md, "_opener", lambda u: (_ for _ in ()).throw(AssertionError("must not open invalid links")))
    assert md.open_url("javascript:alert(1)", tk_root) is False
    assert md.open_url("not a url", tk_root) is False
    assert md.open_url("file:///etc/passwd", tk_root) is False
    assert len(warned) == 3 and "not a valid web address" in warned[0][1]
    # a valid link but no browser available -> copied to the clipboard + explained
    warned.clear()
    monkeypatch.setattr(md, "_opener", lambda u: False)
    assert md.open_url("https://docs.python.org/3/", tk_root) is False
    assert tk_root.clipboard_get() == "https://docs.python.org/3/" and "copied to the clipboard" in warned[0][1]
    monkeypatch.setattr(md, "_opener", lambda u: (_ for _ in ()).throw(OSError("no browser")))   # webbrowser raising must not crash
    assert md.open_url("https://docs.python.org/3/", tk_root) is False


def test_chat_bubbles_and_the_resources_screen_use_the_same_clickable_renderer(tk_root, monkeypatch):
    import tkinter as tk
    from interface import markdown_text as md
    from interface.chat_view import Bubble
    opened = []
    monkeypatch.setattr(md, "_opener", lambda u: opened.append(u) or True)
    canvas = tk.Canvas(tk_root)
    b = Bubble(tk_root, canvas, "assistant", "chat", rm.links_block(["Pandas"]))
    b.pack(fill="both", expand=True)
    b.text.configure(height=20)
    tk_root.update()
    tag = [t for t in b.text.tag_names() if t.startswith("link_")][0]
    fire(tk_root, b.text, tag)
    assert opened and opened[0].startswith("https://pandas.pydata.org/")
    b.destroy()
