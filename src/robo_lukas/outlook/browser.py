from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import SessionNotCreatedException
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.remote.webdriver import WebDriver


def quit_chrome_driver_best_effort(driver: WebDriver | None, *, timeout_s: float = 25.0) -> None:
    """
    ``driver.quit()`` sometimes blocks indefinitely (Chrome / ChromeDriver on Windows).

    Always call this from ``finally`` instead of bare ``quit()`` so the CLI can exit and
    stdout stays delivered even if the browser teardown hangs.
    """
    if driver is None:
        return
    err: list[BaseException] = []
    done = threading.Event()

    def _run() -> None:
        try:
            driver.quit()
        except BaseException as e:
            err.append(e)
        finally:
            done.set()

    t = threading.Thread(target=_run, name="selenium-quit", daemon=True)
    t.start()
    if not done.wait(timeout=max(3.0, timeout_s)):
        print(
            f"robo: WebDriver.quit() did not finish within {timeout_s:.0f}s "
            "(browser may exit on its own).",
            file=sys.stderr,
        )
    elif err:
        print(f"robo: quit() raised {err[0]!r}", file=sys.stderr)


def _running_in_wsl() -> bool:
    if os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP"):
        return True
    try:
        with open("/proc/sys/kernel/osrelease", encoding="utf-8") as f:
            return "microsoft" in f.read().lower()
    except OSError:
        return False


def _is_windows_chrome_binary(path: str | None) -> bool:
    if not path:
        return False
    return path.strip().lower().endswith(".exe")


def _wsl_chrome_flags_enabled(*, windows_chrome: bool) -> bool:
    """GPU/window workarounds for Chrome running *inside* Linux/WSL — not for Windows-hosted Chrome."""
    if windows_chrome:
        return False
    v = os.environ.get("ROBO_OUTLOOK_WSL_FLAGS", "")
    if v:
        return v.lower() in ("1", "true", "yes", "on")
    return _running_in_wsl()


def _discover_chrome_binary() -> str | None:
    for name in (
        "google-chrome-stable",
        "google-chrome",
        "chromium",
        "chromium-browser",
        "brave-browser",
    ):
        p = shutil.which(name)
        if p:
            return p
    return None


def _default_windows_chrome_exe() -> str | None:
    """Typical Google Chrome path on Windows (for WSL /mnt/c/...)."""
    candidates = (
        "/mnt/c/Program Files/Google/Chrome/Application/chrome.exe",
        "/mnt/c/Program Files (x86)/Google/Chrome/Application/chrome.exe",
    )
    for c in candidates:
        if Path(c).is_file():
            return c
    return None


def _default_native_windows_chrome_exe() -> str | None:
    """Google Chrome under Program Files when Python runs on Windows (not WSL)."""
    if sys.platform != "win32":
        return None
    for env_name in ("PROGRAMFILES", "PROGRAMFILES(X86)"):
        base = os.environ.get(env_name, "").strip()
        if not base:
            continue
        p = Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe"
        if p.is_file():
            return str(p)
    return None


def resolve_effective_chrome_binary(binary_location_arg: str | None) -> str | None:
    """CLI/env/defaults: Linux Chromium from PATH, or Windows Chrome when opted in from WSL."""
    r = (binary_location_arg or os.environ.get("CHROME_BINARY") or "").strip() or None
    if r:
        return r
    if _running_in_wsl() and os.environ.get("ROBO_OUTLOOK_USE_WINDOWS_CHROME", "").lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        return _default_windows_chrome_exe()
    if sys.platform == "win32" and not _running_in_wsl():
        win_chrome = _default_native_windows_chrome_exe()
        if win_chrome:
            return win_chrome
    return _discover_chrome_binary()


def _wsl_path_to_windows_user_data_arg(linux_path: Path) -> str:
    """Path string for Windows Chrome --user-data-dir."""
    override = os.environ.get("M365_BROWSER_USER_DATA_DIR_WINDOWS", "").strip()
    if override:
        return override
    resolved = str(linux_path.expanduser().resolve())
    if resolved.startswith("/mnt/c/"):
        return "C:\\" + resolved[7:].replace("/", "\\")
    try:
        r = subprocess.run(
            ["wslpath", "-w", resolved],
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
        return r.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as e:
        raise RuntimeError(
            "Could not convert Linux profile path to a Windows path for Chrome. "
            "Set M365_BROWSER_USER_DATA_DIR_WINDOWS to a Windows path like "
            "C:\\\\Users\\\\You\\\\AppData\\\\Local\\\\robo-lukas-chrome "
            f"(wslpath error: {e})"
        ) from e


def _warn_profile_lock(user_data_dir: Path) -> None:
    lock = user_data_dir / "SingletonLock"
    try:
        if lock.is_file():
            print(
                "robo-outlook: A SingletonLock file exists in your Chrome user-data-dir.\n"
                "  If another Chrome (or a previous robo-outlook run) is using this profile, close it.\n"
                "  If nothing is running, remove the lock: rm '" + str(lock) + "'",
                file=sys.stderr,
            )
    except OSError:
        pass


def _chrome_startup_failure_hint(*, binary_location: str | None, user_data_dir: Path | None) -> str:
    lines = [
        "Chrome exited immediately (SessionNotCreatedException). Common causes:",
        "",
        "  1) WSL2 + *Linux* Chrome: we add --disable-gpu when WSL is detected.",
        "  2) *Windows* Chrome from WSL: set CHROMEDRIVER_PATH to matching chromedriver.exe",
        "     (same major version). See https://googlechromelabs.github.io/chrome-for-testing/",
        "  3) Profile lock: close Chrome using the same profile or remove SingletonLock.",
        "  4) Version skew: delete ~/.cache/selenium (Linux driver) or update Windows chromedriver.",
        "",
        "Debug: ROBO_OUTLOOK_CHROMEDRIVER_LOG=/tmp/chromedriver.log",
    ]
    if binary_location:
        lines.insert(2, f"  (using binary: {binary_location})")
    if user_data_dir is not None:
        lines.insert(2, f"  (user-data-dir: {user_data_dir})")
    return "\n".join(lines)


def build_chrome_options(
    *,
    user_data_dir: Path | None,
    profile_directory: str | None,
    headless: bool,
    binary_location: str | None = None,
) -> ChromeOptions:
    """
    Chrome options for SSO (headed by default).

    When ``binary_location`` is a ``.exe`` and you run from WSL, Chrome runs on **Windows**.
    Use :envvar:`CHROMEDRIVER_PATH` (Windows ``chromedriver.exe``) — see ``create_chrome_driver``.
    """
    opts = ChromeOptions()

    resolved_binary = resolve_effective_chrome_binary(binary_location)

    windows_chrome = _is_windows_chrome_binary(resolved_binary)
    if resolved_binary:
        opts.binary_location = resolved_binary

    if user_data_dir is not None:
        p = user_data_dir.expanduser()
        try:
            p.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        try:
            if p.exists():
                _warn_profile_lock(p.resolve())
        except OSError:
            pass

        if windows_chrome and _running_in_wsl():
            uda = _wsl_path_to_windows_user_data_arg(p)
            opts.add_argument(f"--user-data-dir={uda}")
        else:
            opts.add_argument(f"--user-data-dir={p.resolve()}")

    if profile_directory:
        opts.add_argument(f"--profile-directory={profile_directory}")

    if headless:
        opts.add_argument("--headless=new")
    elif _wsl_chrome_flags_enabled(windows_chrome=windows_chrome):
        opts.add_argument("--window-size=1920,1080")
    else:
        opts.add_argument("--start-maximized")

    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-popup-blocking")
    opts.add_argument("--disable-setuid-sandbox")

    if _wsl_chrome_flags_enabled(windows_chrome=windows_chrome):
        opts.add_argument("--disable-gpu")
        opts.add_argument("--disable-software-rasterizer")

    extra = os.environ.get("OUTLOOK_CHROME_EXTRA_ARGS", "").strip()
    if extra:
        for arg in extra.split():
            if arg.startswith("--"):
                opts.add_argument(arg)

    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)

    return opts


def remote_chromedriver_url() -> str | None:
    """If set, Selenium talks to an already-running ChromeDriver (e.g. on Windows while Python runs in WSL)."""
    u = (os.environ.get("CHROMEDRIVER_REMOTE_URL") or os.environ.get("SELENIUM_REMOTE_URL") or "").strip()
    return u or None


def _binary_location_from_options(options: ChromeOptions) -> str | None:
    try:
        b = options.binary_location
        return b if b else None
    except Exception:
        return None


def create_chrome_driver(
    options: ChromeOptions,
    *,
    profile_dir: Path | None = None,
    remote_command_executor: str | None = None,
) -> WebDriver:
    """
    Start Chrome locally, or attach to a **remote** ChromeDriver via :envvar:`CHROMEDRIVER_REMOTE_URL`.

    **WSL + Windows Chrome:** Linux cannot use ``127.0.0.1`` to reach ChromeDriver spawned as
    ``chromedriver.exe`` on Windows. Run ChromeDriver on Windows (see ``scripts/chromedriver-for-wsl.ps1``)
    with ``--allowed-ips=<your WSL IP>``, then set ``CHROMEDRIVER_REMOTE_URL=http://<Windows host>:port``
    (Windows host = first ``nameserver`` line in WSL ``/etc/resolv.conf``).
    """
    remote = (remote_command_executor or remote_chromedriver_url() or "").strip() or None
    if remote:
        try:
            return webdriver.Remote(command_executor=remote, options=options)
        except OSError as e:
            print(
                f"robo-outlook: cannot connect to CHROMEDRIVER_REMOTE_URL={remote!r}: {e}\n"
                "  Start ChromeDriver on Windows with scripts/chromedriver-for-wsl.ps1 (see README).",
                file=sys.stderr,
            )
            raise
        except Exception:
            print(
                f"robo-outlook: failed to attach to remote WebDriver at {remote!r}.",
                file=sys.stderr,
            )
            raise

    log_file = os.environ.get("ROBO_OUTLOOK_CHROMEDRIVER_LOG")
    service_kw: dict = {}
    if log_file:
        service_kw["log_output"] = log_file

    bl = _binary_location_from_options(options)
    windows_chrome_wsl = bool(bl and _is_windows_chrome_binary(bl) and _running_in_wsl())

    if windows_chrome_wsl:
        drv = os.environ.get("CHROMEDRIVER_PATH", "").strip()
        if not drv:
            print(
                "robo-outlook: Windows Chrome from WSL requires either:\n"
                "  • CHROMEDRIVER_REMOTE_URL=http://<windows-host>:<port> "
                "(ChromeDriver running on Windows; see scripts/chromedriver-for-wsl.ps1), or\n"
                "  • CHROMEDRIVER_PATH=/mnt/c/.../chromedriver.exe (often fails: WSL cannot reach "
                "Windows localhost — prefer REMOTE_URL).\n"
                "  Download matching driver: https://googlechromelabs.github.io/chrome-for-testing/",
                file=sys.stderr,
            )
            raise RuntimeError("CHROMEDRIVER_PATH or CHROMEDRIVER_REMOTE_URL required for Windows Chrome from WSL")
        drv_path = Path(drv)
        if not drv_path.is_file():
            raise FileNotFoundError(f"CHROMEDRIVER_PATH is not a file: {drv}")
        service = ChromeService(executable_path=str(drv_path), **service_kw)
    else:
        service = ChromeService(**service_kw)

    try:
        return webdriver.Chrome(service=service, options=options)
    except SessionNotCreatedException:
        hint_bl = bl or _discover_chrome_binary()
        print(_chrome_startup_failure_hint(binary_location=hint_bl, user_data_dir=profile_dir), file=sys.stderr)
        raise
