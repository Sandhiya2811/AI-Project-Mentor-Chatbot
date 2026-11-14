"""Safe handling of student uploads (zip-slip, zip bombs, symlinks, executables)."""
from __future__ import annotations

import re
import stat
import zipfile
from pathlib import Path

CODE_EXT = {
    ".py", ".ipynb", ".java", ".c", ".h", ".cpp", ".cc", ".cxx", ".hpp", ".js", ".jsx", ".mjs", ".ts", ".tsx",
    ".php", ".r", ".go", ".rb", ".cs", ".sql", ".html", ".htm", ".css", ".scss", ".sh", ".kt", ".swift", ".rs",
    ".vue", ".dart", ".m", ".scala", ".lua", ".pl",
}
TEXT_EXT = {".txt", ".md", ".rst", ".json", ".xml", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".env", ".gradle",
            ".properties", ".lock", ".csv", ".tsv", ".log"}
DOC_EXT = {".pdf", ".docx"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
ARCHIVE_EXT = {".zip"}
ALLOWED_EXT = CODE_EXT | TEXT_EXT | DOC_EXT | IMAGE_EXT | ARCHIVE_EXT
SPECIAL_NAMES = {"dockerfile", "makefile", "requirements.txt", "readme", "license", ".gitignore"}
SKIP_DIRS = {"__macosx", ".git", "node_modules", "venv", ".venv", "env", "__pycache__", ".idea", ".vscode",
             "dist", "build", "target", ".mypy_cache", ".pytest_cache", ".ruff_cache"}


def sanitize_filename(name: str) -> str:
    base = Path(str(name).replace("\\", "/")).name
    base = re.sub(r"[^\w.\- ]", "_", base).strip(" .") or "file"
    return base[:120]


def is_allowed(name: str) -> bool:
    p = Path(name)
    return p.suffix.lower() in ALLOWED_EXT or p.name.lower() in SPECIAL_NAMES


def _skipped_dir(parts: tuple[str, ...]) -> bool:
    return any(part.lower() in SKIP_DIRS for part in parts[:-1])


def safe_extract_zip(zip_path: Path, dest: Path, max_files: int, max_total_bytes: int, max_file_bytes: int):
    """Extract only allowed regular files. Returns (extracted_paths, skipped[(name, reason)])."""
    dest = dest.resolve()
    dest.mkdir(parents=True, exist_ok=True)
    extracted: list[Path] = []
    skipped: list[tuple[str, str]] = []
    total = 0
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = info.filename.replace("\\", "/")
            parts = tuple(p for p in name.split("/") if p not in ("", "."))
            if not parts or name.startswith("/") or ".." in parts or re.match(r"^[A-Za-z]:", name):
                skipped.append((name, "unsafe path"))
                continue
            if stat.S_ISLNK(info.external_attr >> 16):
                skipped.append((name, "symbolic link"))
                continue
            if _skipped_dir(parts):
                continue  # silently ignore vendor/cache folders
            if not is_allowed(parts[-1]):
                skipped.append((name, "file type not accepted"))
                continue
            if Path(parts[-1]).suffix.lower() in ARCHIVE_EXT:
                skipped.append((name, "nested archive"))
                continue
            if len(extracted) >= max_files:
                skipped.append((name, "too many files"))
                continue
            target = (dest.joinpath(*[sanitize_filename(p) for p in parts])).resolve()
            if dest != target and dest not in target.parents:
                skipped.append((name, "unsafe path"))
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            written = 0
            try:
                with zf.open(info) as src, open(target, "wb") as out:
                    while True:
                        chunk = src.read(1 << 16)
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > max_file_bytes or total + written > max_total_bytes:
                            raise ValueError("size limit exceeded")
                        out.write(chunk)
            except ValueError:
                target.unlink(missing_ok=True)
                skipped.append((name, "size limit exceeded"))
                if total + written > max_total_bytes:
                    break
                continue
            total += written
            extracted.append(target)
    return extracted, skipped
