"""Sandboxed execution of Python tests / entry points. Disabled unless network isolation is available."""
from __future__ import annotations

import importlib.util
import re
import shutil
import sys
import tempfile

from code_review.file_reader import Bundle
from config import SANDBOX_MEMORY_MB, SANDBOX_TIMEOUT_SECONDS
from utils import sandbox


def _run_python(bundle: Bundle, argv: list[str]):
    with tempfile.TemporaryDirectory(prefix="mentor_exec_") as work:
        shutil.copytree(bundle.root, work, dirs_exist_ok=True)
        return sandbox.run([sys.executable, "-I"] + argv, cwd=work, timeout=SANDBOX_TIMEOUT_SECONDS,
                           isolate_network=True, mem_mb=SANDBOX_MEMORY_MB)


def _classify(res) -> tuple[str, str]:
    """-> (status, evidence); missing third-party modules are 'skipped', not the student's failure."""
    blob = (res.stderr or "") + (res.stdout or "")
    if res.error:
        return "skipped", f"could not run: {res.error}"
    if res.timed_out:
        return "failed", f"timed out after {SANDBOX_TIMEOUT_SECONDS}s (infinite loop or waiting for input?)"
    m = re.search(r"ModuleNotFoundError: No module named '([\w.]+)'", blob)
    if res.returncode != 0 and m:
        return "skipped", (f"module '{m.group(1)}' is not installed in the validation environment, so the code "
                           "could not be executed here (this is not counted against you)")
    tail = blob.strip().splitlines()[-3:]
    return ("passed" if res.returncode == 0 else "failed"), " | ".join(tail)[:300] or f"exit code {res.returncode}"


def run_python_tests(bundle: Bundle) -> tuple[str, str]:
    if not sandbox.execution_enabled():
        return "skipped", sandbox.execution_status()
    if not any(f.language == "Python" for f in bundle.code_files):
        return "skipped", "test execution is only implemented for Python submissions"
    if importlib.util.find_spec("pytest"):
        res = _run_python(bundle, ["-m", "pytest", "-q", "-x", "--disable-warnings", "-p", "no:cacheprovider"])
        if res.returncode == 5:
            return "failed", "pytest found no tests"
    else:
        res = _run_python(bundle, ["-m", "unittest", "discover", "-v"])
    return _classify(res)


def run_python_entry(bundle: Bundle, entry: str | None) -> tuple[str, str]:
    if not sandbox.execution_enabled():
        return "skipped", sandbox.execution_status()
    candidates = [f.rel for f in bundle.code_files if f.language == "Python" and not f.notebook]
    target = next((c for c in candidates if entry and c.endswith(entry)), None) or (candidates[0] if candidates else None)
    if not target:
        return "skipped", "no runnable Python file found"
    return _classify(_run_python(bundle, [target]))
