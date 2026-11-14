"""Turns uploaded paths (files / zips / pasted answers) into a safe, readable Bundle."""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from code_review.language_detector import detect_file
from config import (MAX_FILES_PER_SUBMISSION, MAX_SUBMISSION_TOTAL_MB, MAX_TEXT_CHARS_PER_FILE, MAX_UPLOAD_FILE_MB)
from utils import security
from utils.helpers import sha256_file


@dataclass
class SubFile:
    rel: str
    path: Path
    size: int
    sha256: str
    kind: str                 # code | text | data | doc | image
    language: str | None = None
    text: str = ""
    extra_text: str = ""      # notebook markdown, docx/pdf text ...
    truncated: bool = False
    notebook: bool = False
    note: str = ""
    loc: int = 0


@dataclass
class Bundle:
    root: Path
    files: list[SubFile] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def of_kind(self, *kinds: str) -> list[SubFile]:
        return [f for f in self.files if f.kind in kinds]

    @property
    def code_files(self) -> list[SubFile]:
        return self.of_kind("code")

    def corpus(self) -> str:
        """Everything the student wrote (code, comments, notes, notebooks, docs), lower-cased."""
        parts = [f.text + "\n" + f.extra_text for f in self.files if f.kind in ("code", "text", "doc", "data")]
        return "\n".join(parts).lower()

    def code_text(self) -> str:
        return "\n".join(f.text for f in self.code_files).lower()


def _decode(raw: bytes) -> str | None:
    if b"\x00" in raw[:4096]:
        return None
    for enc in ("utf-8-sig", "utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else ("utf-8-sig", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return None


def _read_notebook(text: str) -> tuple[str, str]:
    try:
        nb = json.loads(text)
    except ValueError:
        return text, ""
    code, md = [], []
    for i, cell in enumerate(nb.get("cells", []), 1):
        src = cell.get("source", "")
        src = "".join(src) if isinstance(src, list) else str(src)
        if cell.get("cell_type") == "code":
            code.append(f"# %% [code cell {i}]\n{src}")
        elif cell.get("cell_type") == "markdown":
            md.append(src)
    return "\n\n".join(code), "\n\n".join(md)


def _extract_doc(path: Path) -> tuple[str, str]:
    if path.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader
            return "\n".join((p.extract_text() or "") for p in PdfReader(str(path)).pages[:40]), ""
        except ImportError:
            return "", "PDF text not extracted (install 'pypdf')."
        except Exception as exc:  # corrupt pdf
            return "", f"PDF could not be read: {exc.__class__.__name__}"
    try:
        import docx
        return "\n".join(p.text for p in docx.Document(str(path)).paragraphs), ""
    except ImportError:
        return "", "DOCX text not extracted (install 'python-docx')."
    except Exception as exc:
        return "", f"DOCX could not be read: {exc.__class__.__name__}"


def _describe(path: Path, root: Path) -> SubFile | None:
    rel = path.relative_to(root).as_posix()
    ext = path.suffix.lower()
    size = path.stat().st_size
    sf = SubFile(rel, path, size, sha256_file(path), "text")
    if ext in security.IMAGE_EXT:
        sf.kind, sf.note = "image", "Image stored. Automated checks do not analyse image content."
        return sf
    if ext in security.DOC_EXT:
        sf.kind = "doc"
        sf.text, sf.note = _extract_doc(path)
        return sf
    raw = path.read_bytes()[: MAX_TEXT_CHARS_PER_FILE * 4]
    text = _decode(raw)
    if text is None:
        sf.kind, sf.note = "text", "Binary content - not read."
        return sf
    if len(text) > MAX_TEXT_CHARS_PER_FILE:
        text, sf.truncated = text[:MAX_TEXT_CHARS_PER_FILE], True
    if ext in (".csv", ".tsv"):
        sf.kind = "data"
        sf.text = "\n".join(text.splitlines()[:6])[:3000]
        sf.note = "Data file - only the first rows are inspected."
        return sf
    if ext == ".ipynb":
        sf.kind, sf.notebook, sf.language = "code", True, "Python"
        sf.text, sf.extra_text = _read_notebook(text)
    elif ext in security.CODE_EXT or detect_file(path.name, text):
        sf.kind, sf.language, sf.text = "code", detect_file(path.name, text), text
    else:
        sf.text = text
    sf.loc = sum(1 for ln in sf.text.splitlines() if ln.strip()) if sf.kind == "code" else 0
    return sf


def ingest(paths: list[Path], dest_root: Path) -> Bundle:
    """Copy/extract the student's files into dest_root (never executed from here) and describe them."""
    dest_root.mkdir(parents=True, exist_ok=True)
    bundle = Bundle(root=dest_root)
    budget = MAX_SUBMISSION_TOTAL_MB << 20
    for src in paths:
        src = Path(src)
        if not src.is_file():
            bundle.skipped.append((src.name, "not a file"))
            continue
        if src.stat().st_size > MAX_UPLOAD_FILE_MB << 20:
            bundle.skipped.append((src.name, f"larger than {MAX_UPLOAD_FILE_MB} MB"))
            continue
        if not security.is_allowed(src.name):
            bundle.skipped.append((src.name, "file type not accepted"))
            continue
        if src.suffix.lower() == ".zip":
            try:
                _, skipped = security.safe_extract_zip(src, dest_root / security.sanitize_filename(src.stem),
                                                       MAX_FILES_PER_SUBMISSION, budget, MAX_UPLOAD_FILE_MB << 20)
                bundle.skipped.extend(skipped)
            except Exception as exc:  # bad zip
                bundle.skipped.append((src.name, f"could not open zip ({exc.__class__.__name__})"))
            continue
        target = dest_root / security.sanitize_filename(src.name)
        n = 1
        while target.exists():
            target = dest_root / f"{target.stem}_{n}{target.suffix}"
            n += 1
        shutil.copy2(src, target)
    for p in sorted(dest_root.rglob("*")):
        if p.is_file() and not p.is_symlink():
            sf = _describe(p, dest_root)
            if sf:
                bundle.files.append(sf)
    if len(bundle.files) > MAX_FILES_PER_SUBMISSION:
        bundle.files = bundle.files[:MAX_FILES_PER_SUBMISSION]
        bundle.notes.append("Too many files - only the first ones were reviewed.")
    for f in bundle.files:
        if f.note:
            bundle.notes.append(f"{f.rel}: {f.note}")
        if f.truncated:
            bundle.notes.append(f"{f.rel}: very large - only the first part was read.")
    return bundle
