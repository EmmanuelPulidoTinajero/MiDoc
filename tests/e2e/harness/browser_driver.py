"""Playwright browser driver helper (desktop + mobile 390px/320px + dialog/console checks)."""
from __future__ import annotations

from contextlib import contextmanager
import importlib
from pathlib import Path
import sys
import tempfile
from typing import Any, Iterator

from .config import ActiveContext


def _import_sync_playwright() -> Any:
    try:
        mod = importlib.import_module("playwright.sync_api")
        return mod.sync_playwright
    except ImportError:
        alt = Path(tempfile.gettempdir()) / "midoc-playwright"
        if alt.is_dir():
            if str(alt) not in sys.path:
                sys.path.insert(0, str(alt))
            try:
                mod = importlib.import_module("playwright.sync_api")
                return mod.sync_playwright
            except ImportError:
                pass
    return None


def playwright_available() -> bool:
    return _import_sync_playwright() is not None


@contextmanager
def open_browser_page(
    ctx: ActiveContext,
    *,
    width: int = 1280,
    height: int = 800,
) -> Iterator[tuple[Any, list[str], list[str]]]:
    """
    Launch headless Edge/Chrome/Chromium via Playwright.
    Returns (page, page_errors, native_dialogs).
    Fails loudly if Playwright is missing when `--with-browser` was requested.
    """
    sync_playwright = _import_sync_playwright()
    if sync_playwright is None:
        raise RuntimeError(
            "Playwright is not installed (checked standard Python env and %TEMP%/midoc-playwright). "
            "Install Playwright or pass `--skip-browser` for API-only execution."
        )

    page_errors: list[str] = []
    native_dialogs: list[str] = []

    with sync_playwright() as pw:
        browser = None
        last_err: Exception | None = None
        for kwargs in (
            {"channel": "msedge", "headless": True},
            {"channel": "chrome", "headless": True},
            {"headless": True},
        ):
            try:
                browser = pw.chromium.launch(**kwargs)
                break
            except Exception as err:
                last_err = err
        if browser is None:
            raise RuntimeError(f"Failed to launch Playwright browser: {last_err}")

        try:
            context = browser.new_context(viewport={"width": width, "height": height}, locale="es-MX")
            page = context.new_page()
            page.set_default_timeout(20000)
            page.on("pageerror", lambda err: page_errors.append(f"pageerror: {err}"))
            page.on(
                "console",
                lambda msg: page_errors.append(f"console.error: {msg.text}")
                if getattr(msg, "type", None) == "error"
                else None,
            )

            def _on_dialog(dialog: Any) -> None:
                native_dialogs.append(f"{dialog.type}:{dialog.message}")
                dialog.dismiss()

            page.on("dialog", _on_dialog)
            yield page, page_errors, native_dialogs
        finally:
            browser.close()


def assert_no_horizontal_overflow(page: Any) -> None:
    overflow = page.evaluate(
        """() => {
            const docOverflow = document.documentElement.scrollWidth > window.innerWidth;
            const elems = [...document.querySelectorAll('body *')].filter(el => {
                const r = el.getBoundingClientRect();
                return r.width > 0 && r.right > window.innerWidth + 1 && !el.closest('.table-scroll');
            }).slice(0, 10).map(el => ({tag: el.tagName, cls: el.className, right: el.getBoundingClientRect().right}));
            return { docOverflow, elems, scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth };
        }"""
    )
    if overflow["docOverflow"] or overflow["elems"]:
        raise AssertionError(f"Horizontal overflow detected: {overflow}")


def read_root_css_tokens(page: Any, token_names: list[str]) -> dict[str, str]:
    return page.evaluate(
        """(names) => {
            const cs = getComputedStyle(document.documentElement);
            const out = {};
            for (const n of names) out[n] = cs.getPropertyValue(n).trim();
            return out;
        }""",
        token_names,
    )
