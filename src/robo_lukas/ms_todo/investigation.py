"""
Optional diagnostics for Microsoft To Do automation: phase logging and browser snapshots.

Used with ``--investigate [DIR]`` so operators (or future tooling) can see where a run
spends time and what the page looked like (URL, title, HTML, screenshot, DOM probes).
"""

from __future__ import annotations

import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, TextIO

if TYPE_CHECKING:
    from selenium.webdriver.remote.webdriver import WebDriver


_SLUG_BAD = re.compile(r"[^a-zA-Z0-9._-]+")


def _slug(label: str, max_len: int = 72) -> str:
    s = _SLUG_BAD.sub("_", (label or "phase").strip()) or "phase"
    return s[:max_len].strip("_") or "phase"


def _probe_page(driver: "WebDriver") -> dict[str, Any]:
    """Lightweight DOM/state snapshot without importing heavy helpers at module load."""
    data: dict[str, Any] = {"error": None}
    try:
        data["url"] = driver.current_url or ""
    except Exception as e:
        data["url"] = ""
        data["error"] = f"current_url: {e!r}"
    try:
        data["title"] = driver.title or ""
    except Exception as e:
        data["title"] = ""
        if not data.get("error"):
            data["error"] = f"title: {e!r}"
    try:
        data["ready_state"] = driver.execute_script("return document.readyState")
    except Exception as e:
        data["ready_state"] = None
        if not data.get("error"):
            data["error"] = f"readyState: {e!r}"
    try:
        body = driver.find_element("tag name", "body")
        txt = (body.text or "").strip()
        data["body_text_preview"] = txt[:12_000] if txt else ""
        data["body_text_len"] = len(txt)
    except Exception as e:
        data["body_text_preview"] = ""
        data["body_text_len"] = 0
        if not data.get("error"):
            data["error"] = f"body: {e!r}"
    try:
        from robo_lukas.ms_todo.reader import (
            _main_has_task_checkboxes,
            _main_has_task_placeholder,
            _nav_candidates,
            _visible_task_rows,
            is_todo_shell_ready,
            is_todo_task_pane_ready,
            task_list_resolved_for_export,
        )

        rows = _visible_task_rows(driver)
        data["todo_probe"] = {
            "visible_task_row_count": len(rows),
            "nav_candidate_count": len(_nav_candidates(driver)),
            "main_placeholder": _main_has_task_placeholder(driver),
            "main_checkbox": _main_has_task_checkboxes(driver),
            "shell_ready": is_todo_shell_ready(driver),
            "task_pane_ready": is_todo_task_pane_ready(driver),
            "task_list_resolved": task_list_resolved_for_export(driver),
        }
    except Exception as e:
        data["todo_probe"] = {"error": repr(e)}
    return data


@dataclass
class InvestigationReporter:
    """Writes ``investigation.log`` plus numbered HTML/PNG/JSON under ``out_dir``."""

    out_dir: Path
    log_stream: TextIO | None = None
    heartbeat_interval_s: float = 16.0
    _start: float = 0.0
    _seq: int = 0

    def __post_init__(self) -> None:
        self.out_dir = Path(self.out_dir).resolve()
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._start = time.monotonic()
        self._seq = 0
        self.log_stream = self.log_stream if self.log_stream is not None else sys.stderr
        self.log_line(f"sessions dir={self.out_dir!r}")

    def _elapsed(self) -> float:
        return time.monotonic() - self._start

    def log_line(self, message: str) -> None:
        ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
        line = f"[investigate +{self._elapsed():7.2f}s] {ts} {message}\n"
        try:
            with (self.out_dir / "investigation.log").open("a", encoding="utf-8", errors="replace") as f:
                f.write(line)
        except OSError:
            pass
        try:
            self.log_stream.write(line)
        except OSError:
            pass

    def _next_basename(self, label: str) -> str:
        self._seq += 1
        return f"{self._seq:03d}_{_slug(label)}"

    def snapshot(self, driver: "WebDriver", label: str) -> Path:
        """Write ``.html``, ``.png`` (best effort), ``.json`` probe; return stem path."""
        base = self.out_dir / self._next_basename(label)
        stem = base  # without extension
        meta = _probe_page(driver)
        meta["phase"] = label
        meta["elapsed_s"] = round(self._elapsed(), 3)

        try:
            html = driver.page_source or ""
            (stem.with_suffix(".html")).write_text(html, encoding="utf-8", errors="replace")
        except Exception as e:
            self.log_line(f"snapshot html failed: {e!r}")

        png_path = stem.with_suffix(".png")
        try:
            driver.save_screenshot(str(png_path))
            meta["screenshot"] = png_path.name
        except Exception as e:
            try:
                png_path.unlink(missing_ok=True)
            except OSError:
                pass
            self.log_line(f"snapshot png skipped: {e!r}")

        try:
            (stem.with_suffix(".json")).write_text(
                json.dumps(meta, indent=2, ensure_ascii=False),
                encoding="utf-8",
                errors="replace",
            )
        except OSError as e:
            self.log_line(f"snapshot json failed: {e!r}")

        self.log_line(f"snapshot {stem.name}.* phase={label!r} url={meta.get('url', '')[:120]!r}")
        return stem

    def phase(self, label: str, driver: "WebDriver | None" = None, *, snapshot: bool = True) -> None:
        extra = ""
        if driver is not None:
            try:
                extra = f" url={(driver.current_url or '')[:160]!r}"
            except Exception:
                extra = " url=<error>"
        self.log_line(f"phase {label!r}{extra}")
        if snapshot and driver is not None:
            try:
                self.snapshot(driver, label)
            except Exception as e:
                self.log_line(f"phase snapshot error: {e!r}")

    def heartbeat(
        self,
        driver: "WebDriver",
        note: str,
        *,
        snapshot: bool = False,
        force_snapshot: bool = False,
    ) -> None:
        """Log stall/progress during long polls; optional periodic full snapshot."""
        meta = _probe_page(driver)
        probe = meta.get("todo_probe") or {}
        self.log_line(
            f"heartbeat {note!r} rows={probe.get('visible_task_row_count')} "
            f"nav={probe.get('nav_candidate_count')} pane={probe.get('task_pane_ready')} "
            f"resolved={probe.get('task_list_resolved')} readyState={meta.get('ready_state')!r}"
        )
        if force_snapshot or snapshot:
            try:
                self.snapshot(driver, f"heartbeat_{_slug(note, 48)}")
            except Exception as e:
                self.log_line(f"heartbeat snapshot error: {e!r}")
