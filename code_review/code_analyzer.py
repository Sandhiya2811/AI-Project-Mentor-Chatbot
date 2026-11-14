"""Structure analysis: functions, classes, imports, tests, manifests, frameworks (language-aware)."""
from __future__ import annotations

import ast
import re
from pathlib import Path

from code_review.file_reader import Bundle, SubFile
from code_review.language_detector import MANIFESTS, detect_project

PATTERNS = {  # language -> (function regex, class regex, import regex)
    "JavaScript": (r"function\s+(\w+)|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|\w+)\s*=>", r"class\s+(\w+)",
                   r"""import\s+.*?from\s+['"]([^'"]+)['"]|require\(\s*['"]([^'"]+)['"]\s*\)"""),
    "TypeScript": (r"function\s+(\w+)|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|\w+)\s*=>", r"(?:class|interface)\s+(\w+)",
                   r"""import\s+.*?from\s+['"]([^'"]+)['"]|require\(\s*['"]([^'"]+)['"]\s*\)"""),
    "Java": (r"(?:public|private|protected|static)[\w<>\[\], ]*\s+(\w+)\s*\([^;{)]*\)\s*(?:throws [\w, .]+)?\{", r"(?:class|interface|enum)\s+(\w+)", r"^import\s+([\w.*]+);"),
    "C#": (r"(?:public|private|protected|internal|static)[\w<>\[\], ]*\s+(\w+)\s*\([^;{)]*\)\s*\{", r"(?:class|interface|struct)\s+(\w+)", r"^using\s+([\w.]+);"),
    "C": (r"^[\w\*\s]+?\b(\w+)\s*\([^;]*\)\s*\{", r"struct\s+(\w+)", r"#include\s*[<\"]([^>\"]+)[>\"]"),
    "C++": (r"^[\w:<>\*&\s]+?\b(\w+)\s*\([^;]*\)\s*(?:const)?\s*\{", r"(?:class|struct)\s+(\w+)", r"#include\s*[<\"]([^>\"]+)[>\"]"),
    "PHP": (r"function\s+(\w+)", r"class\s+(\w+)", r"(?:use|require|include)(?:_once)?\s+['\"]?([\w\\/.]+)"),
    "Go": (r"func\s+(?:\([^)]*\)\s*)?(\w+)\s*\(", r"type\s+(\w+)\s+struct", r"\"([\w./-]+)\""),
    "Ruby": (r"def\s+(\w+)", r"class\s+(\w+)", r"require\s+['\"]([^'\"]+)['\"]"),
    "R": (r"(\w+)\s*<-\s*function", r"setRefClass\(\s*['\"](\w+)", r"library\(\s*['\"]?(\w+)"),
    "SQL": (r"create\s+(?:or\s+replace\s+)?(?:function|procedure|view|table)\s+(?:if\s+not\s+exists\s+)?([\w.]+)", r"^$a", r"^$a"),
    "Kotlin": (r"fun\s+(\w+)", r"class\s+(\w+)", r"^import\s+([\w.]+)"),
    "Rust": (r"fn\s+(\w+)", r"(?:struct|enum|trait)\s+(\w+)", r"^use\s+([\w:]+)"),
}
FRAMEWORKS = {
    "django": "Django", "flask": "Flask", "fastapi": "FastAPI", "pandas": "Pandas", "numpy": "NumPy",
    "sklearn": "Scikit-learn", "scikit-learn": "Scikit-learn", "torch": "PyTorch", "tensorflow": "TensorFlow",
    "keras": "Keras", "nltk": "NLTK", "spacy": "spaCy", "matplotlib": "Matplotlib", "streamlit": "Streamlit",
    "org.springframework": "Spring", "org.junit": "JUnit", "javax.persistence": "JPA", "java.sql": "JDBC",
    "react": "React", "express": "Express", "vue": "Vue", "next": "Next.js", "jquery": "jQuery",
    "laravel": "Laravel", "gin-gonic": "Gin", "rails": "Rails", "tkinter": "Tkinter", "customtkinter": "CustomTkinter",
    "pytest": "pytest", "unittest": "unittest", "jest": "Jest", "transformers": "Hugging Face Transformers",
}
TEST_NAME = re.compile(r"(^test_.*\.py$|.*_test\.(py|go)$|.*Test\.java$|.*Tests?\.cs$|.*\.(test|spec)\.[jt]sx?$|.*Test\.php$)", re.I)
TEST_CONTENT = re.compile(r"\bimport unittest\b|\bimport pytest\b|@Test\b|\bdescribe\(|\bTestCase\b|func Test\w+\(|\bit\(['\"]")
ENTRY_NAMES = {"main.py", "app.py", "run.py", "manage.py", "__main__.py", "index.js", "server.js", "app.js", "main.js",
               "main.go", "main.java", "main.c", "main.cpp", "index.php", "program.cs", "main.rb", "index.html"}


def _python(sf: SubFile) -> dict:
    info = {"functions": [], "classes": [], "imports": [], "long_functions": [], "syntax_error": None}
    src = "\n".join(l if not l.lstrip().startswith(("%", "!")) else "# " + l for l in sf.text.splitlines())
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        info["syntax_error"] = f"line {exc.lineno}: {exc.msg}"
        return info
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            info["functions"].append(node.name)
            if (node.end_lineno or 0) - node.lineno > 60:
                info["long_functions"].append(node.name)
        elif isinstance(node, ast.ClassDef):
            info["classes"].append(node.name)
        elif isinstance(node, ast.Import):
            info["imports"] += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            info["imports"].append(node.module)
    return info


def _generic(sf: SubFile) -> dict:
    info = {"functions": [], "classes": [], "imports": [], "long_functions": [], "syntax_error": None}
    pats = PATTERNS.get(sf.language or "")
    if not pats:
        return info
    flags = re.M | re.I if sf.language == "SQL" else re.M
    for key, pat in zip(("functions", "classes", "imports"), pats):
        for m in re.finditer(pat, sf.text, flags):
            name = next((g for g in m.groups() if g), None)
            if name and name not in ("if", "for", "while", "switch", "catch", "return"):
                info[key].append(name)
    return info


def analyze(bundle: Bundle) -> dict:
    per_file, deps, frameworks = [], set(), set()
    comments_total = todo = 0
    for sf in bundle.code_files:
        info = _python(sf) if sf.language == "Python" else _generic(sf)
        lines = sf.text.splitlines()
        comment_prefix = ("#",) if sf.language in ("Python", "R", "Ruby", "Shell") else ("//", "/*", "*", "--")
        comments = sum(1 for ln in lines if ln.strip().startswith(comment_prefix))
        comments_total += comments
        todo += sum(1 for ln in lines if re.search(r"\b(TODO|FIXME)\b", ln))
        deps.update(i.split(".")[0] if sf.language == "Python" else i for i in info["imports"])
        per_file.append({"file": sf.rel, "language": sf.language, "loc": sf.loc, "comments": comments, **info,
                         "notebook": sf.notebook})
    # manifests and frameworks
    manifests, manifest_text = [], ""
    for f in bundle.files:
        if Path(f.rel).name.lower() in MANIFESTS:
            manifests.append(f.rel)
            manifest_text += "\n" + f.text.lower()
    haystack = " ".join(deps).lower() + manifest_text
    for key, name in FRAMEWORKS.items():
        if re.search(rf"(?<![\w-]){re.escape(key)}", haystack):
            frameworks.add(name)
    primary, langs = detect_project(bundle.files)
    tests = [f.rel for f in bundle.files if f.kind == "code" and (TEST_NAME.match(Path(f.rel).name) or
                                                                  TEST_CONTENT.search(f.text))]
    tests += [f.rel for f in bundle.files if "/tests/" in "/" + f.rel and f.kind == "code" and f.rel not in tests]
    return {
        "primary_language": primary, "languages": langs, "files": per_file, "total_loc": sum(f["loc"] for f in per_file),
        "comment_lines": comments_total, "todo_markers": todo, "dependencies": sorted(deps)[:60],
        "manifests": manifests, "frameworks": sorted(frameworks), "tests": tests,
        "entry_points": [f.rel for f in bundle.files if Path(f.rel).name.lower() in ENTRY_NAMES],
        "has_readme": any(Path(f.rel).name.lower().startswith("readme") for f in bundle.files),
        "function_count": sum(len(f["functions"]) for f in per_file),
        "class_count": sum(len(f["classes"]) for f in per_file),
    }
