"""Restricted subprocess runner.

Honest limits: CPU-time / file-size / (optional) memory rlimits and a hard wall-clock timeout are applied on
POSIX. Network isolation uses `unshare -rn` (Linux only). When isolation is unavailable, student code is NEVER
executed (only syntax-only tools run). Always run inside a throw-away copy of the submission.
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
from dataclasses import dataclass

from config import SANDBOX_TIMEOUT_SECONDS, settings

_ISOLATION: bool | None = None


@dataclass
class RunResult:
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    error: str = ""


def network_isolation_available() -> bool:
    global _ISOLATION
    if _ISOLATION is None:
        _ISOLATION = False
        if sys.platform.startswith("linux") and shutil.which("unshare"):
            try:
                _ISOLATION = subprocess.run(["unshare", "-rn", "true"], capture_output=True, timeout=5).returncode == 0
            except (OSError, subprocess.SubprocessError):
                _ISOLATION = False
    return _ISOLATION


def execution_enabled() -> bool:
    return settings.get("CODE_EXECUTION") == "auto" and network_isolation_available()


def execution_status() -> str:
    if settings.get("CODE_EXECUTION") == "off":
        return "Code execution: OFF (disabled in settings). Only static checks run."
    if not network_isolation_available():
        return ("Code execution: unavailable (no network-isolation support on this OS). "
                "Submitted code is never run; only static checks are performed.")
    return "Code execution: sandboxed (no network, time/CPU/file limits)."


def _preexec(mem_mb):
    if os.name != "posix":
        return None

    def apply():  # runs in the child just before exec
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (SANDBOX_TIMEOUT_SECONDS + 5, SANDBOX_TIMEOUT_SECONDS + 5))
        resource.setrlimit(resource.RLIMIT_FSIZE, (20 << 20, 20 << 20))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        if mem_mb:
            resource.setrlimit(resource.RLIMIT_AS, (mem_mb << 20, mem_mb << 20))

    return apply


def run(cmd, cwd, timeout=SANDBOX_TIMEOUT_SECONDS, isolate_network=False, mem_mb=None, max_output=40_000) -> RunResult:
    if isolate_network:
        if not network_isolation_available():
            return RunResult(error="network isolation unavailable - refusing to run")
        cmd = ["unshare", "-rn"] + list(cmd)
    env = {"PATH": os.environ.get("PATH", ""), "HOME": cwd, "TMPDIR": cwd, "LANG": "C.UTF-8",
           "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1"}
    for key in ("SYSTEMROOT", "COMSPEC"):
        if os.environ.get(key):
            env[key] = os.environ[key]
    try:
        proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, errors="replace",
                                preexec_fn=_preexec(mem_mb), start_new_session=(os.name == "posix"))
    except OSError as exc:
        return RunResult(error=str(exc))
    try:
        out, err = proc.communicate(timeout=timeout)
        return RunResult(proc.returncode, out[:max_output], err[:max_output])
    except subprocess.TimeoutExpired:
        try:
            if os.name == "posix":
                os.killpg(proc.pid, signal.SIGKILL)
            else:
                proc.kill()
        except OSError:
            pass
        out, err = proc.communicate()
        return RunResult(None, (out or "")[:max_output], (err or "")[:max_output], timed_out=True)
