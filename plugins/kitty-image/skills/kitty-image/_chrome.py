#!/usr/bin/env python3
"""Shared helpers for the kitty-image render front-ends (mermaid.py, html.py).

Browser detection, the Puppeteer config file, PNG sniffing, and the hand-off to
show.py live here so the render scripts don't each fork their own copy.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
SKILL_DIR = Path(__file__).resolve().parent
SHOW_PY = SKILL_DIR / "show.py"

# Chrome/Chromium binaries to reuse, in preference order. Reusing a system
# browser keeps Puppeteer from downloading its own copy.
CHROME_CANDIDATES = (
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
    "chrome",
)


def find_chrome() -> str | None:
    """Return the path to a usable Chrome/Chromium binary, or None."""
    for name in CHROME_CANDIDATES:
        path = shutil.which(name)
        if path:
            return path
    return None


def write_puppeteer_config(chrome: str | None, tmpdir: str) -> str:
    """Write a Puppeteer config JSON and return its path.

    `executablePath` reuses an installed browser (officially documented, version
    robust). `--no-sandbox` is required running headless Chrome as root / in many
    containers; `--disable-gpu` avoids GPU init noise in headless environments.
    """
    cfg: dict = {"args": ["--no-sandbox", "--disable-gpu"]}
    if chrome:
        cfg["executablePath"] = chrome
    path = os.path.join(tmpdir, "puppeteer.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f)
    return path


def is_png(path) -> bool:
    """True if the file begins with the PNG magic bytes."""
    try:
        with open(path, "rb") as f:
            return f.read(len(PNG_MAGIC)) == PNG_MAGIC
    except OSError:
        return False


def display(png, pts: str | None = None, scroll: bool = False) -> int:
    """Exec show.py on the rendered PNG; return its exit code.

    `scroll=True` passes show.py --scroll (fit-to-width, uncapped scrollable
    height) for content meant to be scrolled rather than fit on one screen.
    """
    cmd = [sys.executable, str(SHOW_PY), str(png)]
    if scroll:
        cmd.append("--scroll")
    if pts:
        cmd += ["--pts", pts]
    return subprocess.run(cmd).returncode
