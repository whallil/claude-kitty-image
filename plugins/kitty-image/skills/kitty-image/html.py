#!/usr/bin/env python3
"""Render HTML to a PNG and display it inline (kitty-image).

Accepts a live URL, a local HTML file, or HTML on stdin ('-'); drives
Puppeteer-core (pointed at the system Chrome) to screenshot it, then execs
show.py to display it. Puppeteer-core is installed once into a user cache dir;
no Chromium is ever downloaded.

Capture modes: viewport (default), --selector <css> (one element), --full-page
(whole scroll height, displayed via show.py --scroll so it stays readable and
scrolls instead of being shrunk to fit).

Usage:
    html.py <source>                 # URL (http/https), file path, or '-' (stdin HTML)
    html.py https://example.com
    echo '<h1>hi</h1>' | html.py -
    html.py page.html --selector '.hero'
    html.py https://x.com --full-page
    html.py <src> --viewport 1280x800 --scale 2 --wait 500 --timeout 30000
    html.py <src> --out /tmp/x.png --no-show --pts /dev/pts/N

Exit codes:
    0   success
    2   usage error (bad args; --full-page + --selector)
    20  no usable renderer (no npm/node, or no Chrome/Chromium)
    21  navigation/load failed (bad URL, timeout, missing local file)
    22  --selector element not found
    23  input/output error (empty stdin, output dir not writable)
    (show.py's own codes 2-6 propagate when the display step runs)
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from _chrome import CHROME_CANDIDATES, display, find_chrome, is_png

SKILL_DIR = Path(__file__).resolve().parent
SNAP_JS = SKILL_DIR / "_snap.js"
CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")) / "kitty-image"
# Hardcoded: the cache fast-path check and _snap.js's require() both assume this
# exact package name, so it is not env-overridable (a different name would
# silently reinstall every run and then fail require() at runtime).
PUPPETEER_PKG = "puppeteer-core"


def parse_viewport(s: str) -> tuple[int, int]:
    """Parse 'WIDTHxHEIGHT' into (w, h); raise for argparse on bad input."""
    m = re.fullmatch(r"\s*(\d+)x(\d+)\s*", s)
    if not m:
        raise argparse.ArgumentTypeError("viewport must be WIDTHxHEIGHT, e.g. 1280x800")
    w, h = int(m.group(1)), int(m.group(2))
    if w <= 0 or h <= 0:
        raise argparse.ArgumentTypeError("viewport dimensions must be > 0")
    return (w, h)


def resolve_scale(full_page: bool, scale: int | None) -> int:
    """Default deviceScaleFactor: 2 normally (crisp), 1 for full-page (sane height)."""
    if scale is not None:
        return scale
    return 1 if full_page else 2


def resolve_source(source: str, tmpdir: str) -> str:
    """Return a navigable URL for the source.

    '-'        -> read stdin -> temp .html in tmpdir -> file:// URI (exit 23 if empty)
    http(s):// -> returned unchanged
    file path  -> file:// URI if it exists, else exit 21
    """
    if source == "-":
        html_text = sys.stdin.read()
        if not html_text.strip():
            print("error: stdin HTML is empty", file=sys.stderr)
            sys.exit(23)
        p = Path(tmpdir) / "input.html"
        p.write_text(html_text, encoding="utf-8")
        return p.resolve().as_uri()
    if re.match(r"^https?://", source, re.IGNORECASE):
        return source
    p = Path(source)
    if p.is_file():
        return p.resolve().as_uri()
    print(f"error: source {source!r} is not a URL or an existing file", file=sys.stderr)
    sys.exit(21)


def ensure_puppeteer() -> str:
    """Ensure puppeteer-core is in the cache dir; return the node_modules path.

    Installs once via `npm install --prefix <cache>` (no Chromium download).
    Exits 20 if npm is missing or the install fails.
    """
    node_modules = CACHE_DIR / "node_modules"
    if (node_modules / "puppeteer-core" / "package.json").is_file():
        return str(node_modules)
    npm = shutil.which("npm")
    if not npm:
        print("error: npm not found; install Node.js (npm) to use html.py", file=sys.stderr)
        sys.exit(20)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [npm, "install", "--prefix", str(CACHE_DIR),
         "--no-save", "--no-audit", "--no-fund", PUPPETEER_PKG],
        capture_output=True, text=True,
    )
    if proc.returncode != 0 or not (node_modules / "puppeteer-core").exists():
        sys.stderr.write(proc.stdout)
        sys.stderr.write(proc.stderr)
        print("error: failed to install puppeteer-core into the cache", file=sys.stderr)
        sys.exit(20)
    return str(node_modules)


def run_snap(cfg: dict, node_path: str) -> None:
    """Run _snap.js to produce cfg['out']. Maps its exit code to ours."""
    node = shutil.which("node")
    if not node:
        print("error: node not found; install Node.js to use html.py", file=sys.stderr)
        sys.exit(20)
    env = dict(os.environ)
    env["NODE_PATH"] = node_path
    env["SNAP_CFG"] = json.dumps(cfg)
    proc = subprocess.run([node, str(SNAP_JS)], env=env, capture_output=True, text=True)
    if proc.returncode == 0 and is_png(cfg["out"]):
        return
    sys.stderr.write(proc.stderr)
    if proc.returncode == 42:
        print(f"error: selector not found: {cfg.get('selector')!r}", file=sys.stderr)
        sys.exit(22)
    if proc.returncode == 40:
        print("error: could not launch Chrome (browser missing, or missing system "
              "libraries like libnss3/libgbm)", file=sys.stderr)
        sys.exit(20)
    print("error: failed to render the page (navigation/timeout/screenshot)", file=sys.stderr)
    sys.exit(21)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Render HTML (URL/file/stdin) to a PNG and display it inline (kitty-image).")
    ap.add_argument("source", help="URL (http/https), a file path, or '-' to read HTML from stdin")
    ap.add_argument("--selector", help="screenshot only the first element matching this CSS selector")
    ap.add_argument("--full-page", action="store_true",
                    help="capture the full scroll height (displayed via show.py --scroll)")
    ap.add_argument("--viewport", type=parse_viewport, default=(1280, 800),
                    help="render viewport WIDTHxHEIGHT (default 1280x800)")
    ap.add_argument("--scale", type=int, default=None,
                    help="device scale factor (default 2; 1 for --full-page)")
    ap.add_argument("--wait", type=int, default=0,
                    help="extra milliseconds to wait after network idle (default 0)")
    ap.add_argument("--timeout", type=int, default=30000,
                    help="navigation/selector timeout in ms (default 30000)")
    ap.add_argument("--out", help="output PNG path (default: /tmp/html.png)")
    ap.add_argument("--no-show", action="store_true",
                    help="render only; print the PNG path and do not display it")
    ap.add_argument("--pts", help="override show.py's auto-detected PTY (e.g. /dev/pts/4)")
    args = ap.parse_args()

    if args.full_page and args.selector:
        ap.error("--full-page and --selector are mutually exclusive")
    scale = resolve_scale(args.full_page, args.scale)
    if scale <= 0:
        ap.error("--scale must be a positive integer")

    chrome = find_chrome()
    if not chrome:
        print("error: no Chrome/Chromium found (" + ", ".join(CHROME_CANDIDATES) + "). "
              "Install one, e.g. `apt install google-chrome-stable`.", file=sys.stderr)
        return 20

    out = Path(args.out) if args.out else Path(tempfile.gettempdir()) / "html.png"
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"error: cannot create output directory {out.parent}: {e}", file=sys.stderr)
        return 23

    width, height = args.viewport
    with tempfile.TemporaryDirectory(prefix="kitty-html-") as tmpdir:
        url = resolve_source(args.source, tmpdir)
        node_path = ensure_puppeteer()
        cfg = {
            "chrome": chrome,
            "url": url,
            "width": width,
            "height": height,
            "scale": scale,
            "timeout": args.timeout,
            "wait": args.wait,
            "out": str(out),
            "fullPage": bool(args.full_page),
            "selector": args.selector,
        }
        run_snap(cfg, node_path)

    if args.no_show:
        print(out)
        return 0
    return display(out, args.pts, scroll=bool(args.full_page))


if __name__ == "__main__":
    sys.exit(main())
