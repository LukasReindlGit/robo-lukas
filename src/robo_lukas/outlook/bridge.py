"""
Start (or reuse) Windows ChromeDriver from WSL so one command can run robo-outlook.

See ``with-bridge`` in :mod:`robo_lukas.outlook.cli`.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

from robo_lukas.outlook.browser import _running_in_wsl


def _wsl_guest_ip() -> str:
    out = subprocess.check_output(["hostname", "-I"], text=True, timeout=5).strip()
    parts = out.split()
    if not parts:
        raise RuntimeError("Could not parse WSL IP from: hostname -I")
    return parts[0]


def _windows_host_ip() -> str:
    with open("/etc/resolv.conf", encoding="utf-8") as f:
        for line in f:
            if line.strip().startswith("nameserver"):
                return line.split()[1]
    raise RuntimeError("No nameserver in /etc/resolv.conf (not WSL?)")


def _candidate_remote_bases(win_host: str, port: int) -> list[str]:
    """
    URLs to reach a ChromeDriver listening on Windows from WSL.

    WSL2 forwards ``127.0.0.1`` to the Windows host by default, so the driver on
    Windows loopback is often reachable as ``http://127.0.0.1:port`` from Linux.
    The ``nameserver`` IP is a fallback when forwarding is off or blocked.
    """
    return [
        f"http://127.0.0.1:{port}",
        f"http://{win_host}:{port}",
    ]


def _chromedriver_status_ok(base_url: str, timeout_s: float = 2.0) -> bool:
    url = base_url.rstrip("/") + "/status"
    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, OSError):
        return False


def _first_reachable_base(urls: list[str]) -> str | None:
    for u in urls:
        if _chromedriver_status_ok(u, timeout_s=1.5):
            return u
    return None


def _wait_chromedriver_any(
    base_urls: list[str],
    proc: subprocess.Popen | None,
    stderr_path: Path | None,
    *,
    timeout_s: float,
) -> str:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if proc is not None and proc.poll() is not None:
            tail = ""
            if stderr_path and stderr_path.is_file():
                try:
                    tail = stderr_path.read_text(encoding="utf-8", errors="replace")[-4000:]
                except OSError:
                    tail = ""
            raise RuntimeError(
                f"chromedriver.exe exited early (code {proc.returncode}).\n"
                f"Last stderr (if captured):\n{tail or '(empty)'}"
            )
        hit = _first_reachable_base(base_urls)
        if hit:
            return hit
        time.sleep(0.35)
    hint = (
        "Could not reach ChromeDriver from WSL.\n"
        "  • WSL2 usually needs http://127.0.0.1:PORT (localhost forwarding). Try: "
        f"curl -sS {base_urls[0]}/status\n"
        "  • If that fails, allow inbound TCP on the port in Windows Firewall, or run "
        "scripts/chromedriver-for-wsl.ps1 in PowerShell and set CHROMEDRIVER_REMOTE_URL.\n"
        f"  • Also tried: {base_urls!r}"
    )
    if stderr_path and stderr_path.is_file():
        try:
            hint += "\n\nchromedriver stderr:\n" + stderr_path.read_text(encoding="utf-8", errors="replace")[-4000:]
        except OSError:
            pass
    raise TimeoutError(hint)


def _default_chromedriver_exe() -> Path:
    raw = (os.environ.get("CHROMEDRIVER_WINDOWS_EXE") or "").strip()
    if raw:
        return Path(raw)
    raise FileNotFoundError(
        "Set CHROMEDRIVER_WINDOWS_EXE in .env to the WSL path to chromedriver.exe, e.g.\n"
        "  CHROMEDRIVER_WINDOWS_EXE=/mnt/c/Users/You/AppData/Local/robo-lukas/chromedriver-win64/chromedriver.exe"
    )


@contextlib.contextmanager
def managed_windows_chromedriver() -> Iterator[None]:
    """
    Ensure ``CHROMEDRIVER_REMOTE_URL`` works for the duration of the context:

    - If already set and reachable: no-op.
    - Else if something is listening on a known candidate URL: set env for this process only.
    - Else start ``chromedriver.exe`` via WSL interop (Windows process) and stop it on exit.
    """
    if not _running_in_wsl():
        yield
        return

    port = int(os.environ.get("ROBO_OUTLOOK_BRIDGE_PORT", "9515"))
    win_host = _windows_host_ip()
    bases = _candidate_remote_bases(win_host, port)
    start_timeout = float(os.environ.get("ROBO_OUTLOOK_BRIDGE_START_TIMEOUT", "40"))
    prior_remote = (os.environ.get("CHROMEDRIVER_REMOTE_URL") or "").strip()

    if prior_remote and _chromedriver_status_ok(prior_remote):
        yield
        return

    proc: subprocess.Popen | None = None
    stderr_path: Path | None = None
    try:
        existing = _first_reachable_base(bases)
        if existing:
            os.environ["CHROMEDRIVER_REMOTE_URL"] = existing
            yield
            return

        exe = _default_chromedriver_exe()
        if not exe.is_file():
            raise FileNotFoundError(str(exe))

        wsl_ip = _wsl_guest_ip()
        # 127.0.0.1: WSL localhost forwarding to Windows; wsl_ip: direct virtual NIC path
        allow_ips = f"127.0.0.1,{wsl_ip}"

        fd, stderr_tmp = tempfile.mkstemp(prefix="robo-chromedriver-", suffix=".log")
        os.close(fd)
        stderr_path = Path(stderr_tmp)

        stderr_f = open(stderr_path, "w", encoding="utf-8", errors="replace")
        try:
            proc = subprocess.Popen(
                [
                    str(exe),
                    f"--port={port}",
                    f"--allowed-ips={allow_ips}",
                    "--allowed-origins=*",
                ],
                stdout=subprocess.DEVNULL,
                stderr=stderr_f,
            )
        finally:
            stderr_f.close()

        good = _wait_chromedriver_any(bases, proc, stderr_path, timeout_s=start_timeout)
        os.environ["CHROMEDRIVER_REMOTE_URL"] = good
        yield
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
        if stderr_path is not None:
            try:
                stderr_path.unlink(missing_ok=True)
            except OSError:
                pass
        if prior_remote:
            os.environ["CHROMEDRIVER_REMOTE_URL"] = prior_remote
        else:
            os.environ.pop("CHROMEDRIVER_REMOTE_URL", None)


def run_under_windows_chromedriver_bridge(inner_argv: list[str]) -> int:
    from robo_lukas.outlook.cli import main as cli_main

    with managed_windows_chromedriver():
        return cli_main(inner_argv, _skip_bridge=True)
