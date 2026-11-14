"""Curated official-documentation links (so the LLM never has to invent URLs) + offline notes."""
from __future__ import annotations

import re

from rag import retriever

OFFICIAL_DOCS = {
    "python": "https://docs.python.org/3/", "pandas": "https://pandas.pydata.org/docs/",
    "numpy": "https://numpy.org/doc/stable/", "matplotlib": "https://matplotlib.org/stable/",
    "seaborn": "https://seaborn.pydata.org/", "nltk": "https://www.nltk.org/", "spacy": "https://spacy.io/usage",
    "scikit-learn": "https://scikit-learn.org/stable/user_guide.html",
    "tf-idf": "https://scikit-learn.org/stable/modules/feature_extraction.html#tfidf-term-weighting",
    "logistic regression": "https://scikit-learn.org/stable/modules/linear_model.html#logistic-regression",
    "naive bayes": "https://scikit-learn.org/stable/modules/naive_bayes.html",
    "random forest": "https://scikit-learn.org/stable/modules/ensemble.html#random-forests",
    "git": "https://git-scm.com/doc", "github": "https://docs.github.com/", "streamlit": "https://docs.streamlit.io/",
    "flask": "https://flask.palletsprojects.com/", "django": "https://docs.djangoproject.com/",
    "fastapi": "https://fastapi.tiangolo.com/", "pytorch": "https://pytorch.org/docs/stable/",
    "tensorflow": "https://www.tensorflow.org/api_docs", "keras": "https://keras.io/api/",
    "transformers": "https://huggingface.co/docs/transformers", "hugging face": "https://huggingface.co/docs",
    "langchain": "https://python.langchain.com/docs/", "faiss": "https://faiss.ai/",
    "chromadb": "https://docs.trychroma.com/", "opencv": "https://docs.opencv.org/",
    "pytest": "https://docs.pytest.org/", "sqlite": "https://www.sqlite.org/docs.html",
    "postgresql": "https://www.postgresql.org/docs/", "mysql": "https://dev.mysql.com/doc/",
    "java": "https://docs.oracle.com/en/java/javase/", "oop": "https://docs.oracle.com/javase/tutorial/java/concepts/",
    "collections": "https://docs.oracle.com/javase/tutorial/collections/",
    "jdbc": "https://docs.oracle.com/javase/tutorial/jdbc/", "maven": "https://maven.apache.org/guides/",
    "junit": "https://junit.org/junit5/docs/current/user-guide/", "spring": "https://docs.spring.io/spring-boot/",
    "javascript": "https://developer.mozilla.org/en-US/docs/Web/JavaScript",
    "html": "https://developer.mozilla.org/en-US/docs/Web/HTML", "css": "https://developer.mozilla.org/en-US/docs/Web/CSS",
    "node": "https://nodejs.org/docs/latest/api/", "node.js": "https://nodejs.org/docs/latest/api/",
    "express": "https://expressjs.com/", "react": "https://react.dev/",
    "typescript": "https://www.typescriptlang.org/docs/", "php": "https://www.php.net/docs.php",
    "go": "https://go.dev/doc/", "ruby": "https://www.ruby-lang.org/en/documentation/",
    "r": "https://cran.r-project.org/manuals.html", "c#": "https://learn.microsoft.com/en-us/dotnet/csharp/",
    "c++": "https://en.cppreference.com/w/cpp", "c": "https://en.cppreference.com/w/c",
    "tkinter": "https://docs.python.org/3/library/tkinter.html", "sql": "https://www.sqlite.org/lang.html",
    "requests": "https://requests.readthedocs.io/", "docker": "https://docs.docker.com/",
    "speechrecognition": "https://pypi.org/project/SpeechRecognition/", "pyttsx3": "https://pypi.org/project/pyttsx3/",
}


def find_doc(tool: str) -> str:
    key = re.sub(r"\s+", " ", tool.lower().strip())
    if key in OFFICIAL_DOCS:
        return OFFICIAL_DOCS[key]
    for name, url in sorted(OFFICIAL_DOCS.items(), key=lambda kv: -len(kv[0])):
        if len(name) > 2 and re.search(rf"(?<![\w]){re.escape(name)}(?![\w])", key):
            return url
    return ""


def offline_note(tool: str, role: str, doc_url: str, project: dict, position: int, total: int) -> str:
    """Non-AI note: project role + local knowledge-base excerpts + official docs link. Clearly labelled."""
    chunks = retriever.retrieve(f"{tool} {project['title']}", k=3)
    parts = [f"# {tool}", "_Offline note: the AI model was not available, so this note was assembled from your "
                          "project plan and the local knowledge base. Press **Regenerate with AI** for a full personalised note._",
             f"## Where it is used in this project\n{role or 'Listed as a requirement of your project.'}",
             f"## Suggested learning order\nTool {position} of {total} for this project."]
    if chunks:
        parts.append("## Reference excerpts from the local knowledge base")
        parts += [f"**{c.source}**\n{c.text}" for c in chunks]
    parts.append("## Official documentation\n" + (doc_url if doc_url else
                 f"No curated link is stored for {tool}. Search for the official documentation site of {tool}."))
    return "\n\n".join(parts)
