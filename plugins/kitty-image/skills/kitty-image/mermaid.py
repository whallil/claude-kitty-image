#!/usr/bin/env python3
"""Render a Mermaid diagram definition to a PNG and display it inline.

This is the *render* half of the kitty-image skill; display is delegated to
show.py (which it execs on success), so all of show.py's PTY-detection and
text-overlap handling is reused unchanged.

Two backends, local-first for privacy:

  1. LOCAL (default) -- mermaid-cli (`mmdc`). If `mmdc` is on PATH it is used
     directly; otherwise we fall back to `npx -p @mermaid-js/mermaid-cli mmdc`
     pointed at an already-installed Chrome (so Puppeteer never downloads its
     own ~150MB Chromium). Fully offline once cached; nothing leaves the box.
  2. REMOTE (--remote, explicit opt-in) -- the public mermaid.ink HTTP service.
     The diagram is wrapped in a `pako:` envelope (zlib-deflate + base64url of
     `{"code": <diagram>, "mermaid": {"theme": <theme>}}`) and fetched as PNG.
     This SENDS THE DIAGRAM TEXT to a third party, so it is never automatic.

Usage:
    python3 mermaid.py <diagram.mmd>            # render -> /tmp PNG -> show.py
    python3 mermaid.py -                          # read diagram from stdin
    python3 mermaid.py <file> --remote            # opt in to mermaid.ink
    python3 mermaid.py <file> --theme dark        # mermaid theme (default dark)
    python3 mermaid.py <file> --bg '#10121a'      # background (default skill bg)
    python3 mermaid.py <file> --scale 2           # render scale, local only (default 2)
    python3 mermaid.py <file> --out /tmp/x.png    # output PNG path
    python3 mermaid.py <file> --no-show           # render only, print path, don't display
    python3 mermaid.py <file> --pts /dev/pts/N    # passthrough to show.py

Exit codes:
    0   success
    2   usage error (bad arguments; raised by argparse)
    10  no local renderer available and --remote not given
    11  local render failed (invalid mermaid, or no usable Chrome) -- stderr forwarded
    12  remote render failed (network / service / non-PNG response)
    13  input diagram missing/empty, or output path not writable
    (show.py's own codes 2-6 propagate when the display step runs)
"""
import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zlib
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

# npm package spec for the npx fallback; override to pin a version if needed.
MERMAID_CLI_SPEC = os.environ.get("KITTY_MERMAID_CLI_SPEC", "@mermaid-js/mermaid-cli")
MERMAID_INK_BASE = os.environ.get("KITTY_MERMAID_INK_BASE", "https://mermaid.ink")


# --------------------------------------------------------------------------- #
# Input
# --------------------------------------------------------------------------- #
def read_diagram(source: str) -> str:
    """Return the mermaid definition text from a file path or '-' (stdin).

    Exits 13 if a file path is missing, or if the resulting text is empty.
    """
    if source == "-":
        text = sys.stdin.read()
    else:
        p = Path(source)
        if not p.is_file():
            print(f"error: diagram file {p} not found", file=sys.stderr)
            sys.exit(13)
        text = p.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        print("error: diagram is empty", file=sys.stderr)
        sys.exit(13)
    return text


def default_out_path(source: str) -> Path:
    """Choose an output PNG path: /tmp/<stem>.png, or /tmp/mermaid.png for stdin."""
    stem = "mermaid" if source == "-" else (Path(source).stem or "mermaid")
    return Path(tempfile.gettempdir()) / f"{stem}.png"


# --------------------------------------------------------------------------- #
# Backend detection
# --------------------------------------------------------------------------- #
def find_chrome() -> str | None:
    """Return the path to a usable Chrome/Chromium binary, or None."""
    for name in CHROME_CANDIDATES:
        path = shutil.which(name)
        if path:
            return path
    return None


# --------------------------------------------------------------------------- #
# Local rendering (mmdc / npx)
# --------------------------------------------------------------------------- #
def _write_puppeteer_config(chrome: str | None, tmpdir: str) -> str:
    """Write a puppeteer config JSON and return its path.

    `executablePath` (when a system Chrome was found) is the officially
    documented, version-robust way to reuse an installed browser. `--no-sandbox`
    is required when running headless Chrome as root or in many containers;
    `--disable-gpu` avoids GPU init noise in headless environments.
    """
    cfg: dict = {"args": ["--no-sandbox", "--disable-gpu"]}
    if chrome:
        cfg["executablePath"] = chrome
    path = os.path.join(tmpdir, "puppeteer.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f)
    return path


def render_local(diagram: str, out: Path, theme: str, bg: str, scale: int) -> None:
    """Render via mermaid-cli. Exits 10 if no local renderer, 11 on render error.

    Resolution order:
      1. `mmdc` on PATH               -> use it directly.
      2. else `npx` + a Chrome binary -> npx -p @mermaid-js/mermaid-cli mmdc.
      3. else                         -> exit 10 (suggest --remote).
    """
    mmdc = shutil.which("mmdc")
    npx = shutil.which("npx")
    chrome = find_chrome()

    if mmdc:
        base_cmd = [mmdc]
    elif npx and chrome:
        # --yes: don't interactively prompt to install on first run.
        base_cmd = [npx, "--yes", "-p", MERMAID_CLI_SPEC, "mmdc"]
    else:
        print(
            "error: no local mermaid renderer found.\n"
            "  Need `mmdc` on PATH, or `npx` (Node) plus a Chrome/Chromium binary "
            f"({', '.join(CHROME_CANDIDATES)}).\n"
            "  Re-run with --remote to render via mermaid.ink instead "
            "(note: this sends the diagram text to a third-party service).",
            file=sys.stderr,
        )
        sys.exit(10)

    with tempfile.TemporaryDirectory(prefix="kitty-mermaid-") as tmpdir:
        mmd_path = os.path.join(tmpdir, "diagram.mmd")
        with open(mmd_path, "w", encoding="utf-8") as f:
            f.write(diagram)
        cfg_path = _write_puppeteer_config(chrome, tmpdir)

        cmd = [
            *base_cmd,
            "-i", mmd_path,
            "-o", str(out),
            "-t", theme,
            "-b", bg,
            "-s", str(scale),
            "-p", cfg_path,
        ]

        env = dict(os.environ)
        # Keep Puppeteer from fetching its own Chromium during an npx install;
        # also export the path as a runtime backup to the config's executablePath.
        env["PUPPETEER_SKIP_DOWNLOAD"] = "1"
        if chrome:
            env["PUPPETEER_EXECUTABLE_PATH"] = chrome

        proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
        if proc.returncode != 0 or not _is_png(out):
            sys.stderr.write(proc.stdout)
            sys.stderr.write(proc.stderr)
            if proc.returncode != 0:
                # mmdc can fail for an invalid diagram OR because Puppeteer found
                # no usable browser (no system Chrome and no bundled Chromium).
                # Don't assume syntax — point at both, and offer the remote escape.
                msg = (
                    f"error: local mermaid render failed (renderer exited {proc.returncode}). "
                    "See the output above — likely an invalid Mermaid diagram, or no usable "
                    "Chrome/Chromium for the renderer. You can also try --remote."
                )
            else:
                msg = (
                    "error: the renderer exited cleanly but did not produce a valid PNG. "
                    "Check the diagram and the output above."
                )
            print(msg, file=sys.stderr)
            sys.exit(11)


# --------------------------------------------------------------------------- #
# Remote rendering (mermaid.ink, pako envelope)
# --------------------------------------------------------------------------- #
def _pako_encode(diagram: str, theme: str) -> str:
    """Build the `pako:`-prefixed token mermaid.ink expects.

    Envelope: {"code": <diagram>, "mermaid": {"theme": <theme>}} -> JSON ->
    zlib deflate (level 9) -> base64url. base64url (-, _ instead of +, /) is
    required so the token is safe inside a URL path.
    """
    envelope = {"code": diagram, "mermaid": {"theme": theme}}
    raw = json.dumps(envelope).encode("utf-8")
    compressed = zlib.compress(raw, 9)
    token = base64.urlsafe_b64encode(compressed).decode("ascii")
    return f"pako:{token}"


def _bg_query(bg: str) -> str | None:
    """Map a --bg value to mermaid.ink's bgColor query param, or None.

    mermaid.ink wants a bare hex (no '#') or a named color prefixed with '!'.
    'transparent' (or empty) means: send no bgColor at all.
    """
    bg = bg.strip()
    if not bg or bg.lower() == "transparent":
        return None
    if bg.startswith("#"):
        return bg[1:]
    if all(c in "0123456789abcdefABCDEF" for c in bg) and len(bg) in (3, 6):
        return bg
    return "!" + bg  # treat as a named color


def render_remote(diagram: str, out: Path, theme: str, bg: str) -> None:
    """Render via mermaid.ink. Exits 12 on network/service/non-PNG failure."""
    token = _pako_encode(diagram, theme)  # base64url -> already URL-path-safe
    params = {"type": "png"}
    bgq = _bg_query(bg)
    if bgq:
        params["bgColor"] = bgq
    # urlencode so a bgColor with reserved/space chars can't produce an invalid
    # URL (urllib would otherwise raise http.client.InvalidURL, which our except
    # clauses below don't catch -> uncaught traceback instead of a clean exit 12).
    url = f"{MERMAID_INK_BASE}/img/{token}?{urllib.parse.urlencode(params)}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "kitty-image/mermaid"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
            ctype = resp.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        body = e.read(300).decode("utf-8", "replace")
        print(f"error: mermaid.ink returned HTTP {e.code}: {body}", file=sys.stderr)
        sys.exit(12)
    except (urllib.error.URLError, OSError) as e:
        print(f"error: could not reach mermaid.ink: {e}", file=sys.stderr)
        sys.exit(12)

    if not data.startswith(PNG_MAGIC):
        head = data[:300].decode("utf-8", "replace")
        print(
            f"error: mermaid.ink did not return a PNG (Content-Type: {ctype}). "
            f"Response head: {head}",
            file=sys.stderr,
        )
        sys.exit(12)

    try:
        out.write_bytes(data)
    except OSError as e:
        print(f"error: could not write output {out}: {e}", file=sys.stderr)
        sys.exit(13)


# --------------------------------------------------------------------------- #
# Display handoff
# --------------------------------------------------------------------------- #
def _is_png(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(len(PNG_MAGIC)) == PNG_MAGIC
    except OSError:
        return False


def display(png: Path, pts: str | None) -> int:
    """Exec show.py on the rendered PNG; return its exit code."""
    cmd = [sys.executable, str(SHOW_PY), str(png)]
    if pts:
        cmd += ["--pts", pts]
    return subprocess.run(cmd).returncode


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(
        description="Render a Mermaid diagram to PNG and display it inline (kitty-image)."
    )
    ap.add_argument("diagram", help="path to a .mmd file, or '-' to read from stdin")
    ap.add_argument("--remote", action="store_true",
                    help="render via mermaid.ink instead of locally (sends diagram offsite)")
    ap.add_argument("--theme", default="dark",
                    help="mermaid theme: default, dark, forest, neutral (default: dark)")
    ap.add_argument("--bg", default="#10121a",
                    help="background color; hex like '#10121a', a name, or 'transparent' "
                         "(default: #10121a, the skill's chart background)")
    ap.add_argument("--scale", type=int, default=2,
                    help="render scale factor, local renderer only (default: 2)")
    ap.add_argument("--out", help="output PNG path (default: /tmp/<name>.png)")
    ap.add_argument("--no-show", action="store_true",
                    help="render only; print the PNG path and do not display it")
    ap.add_argument("--pts", help="override show.py's auto-detected PTY (e.g. /dev/pts/4)")
    args = ap.parse_args()

    if args.scale <= 0:
        ap.error("--scale must be a positive integer")
    if args.remote and args.scale != 2:
        print("warning: --scale has no effect with --remote (mermaid.ink has no scale knob)",
              file=sys.stderr)

    diagram = read_diagram(args.diagram)
    out = Path(args.out) if args.out else default_out_path(args.diagram)
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"error: cannot create output directory {out.parent}: {e}", file=sys.stderr)
        return 13

    if args.remote:
        render_remote(diagram, out, args.theme, args.bg)
    else:
        render_local(diagram, out, args.theme, args.bg, args.scale)

    if args.no_show:
        print(out)
        return 0
    return display(out, args.pts)


if __name__ == "__main__":
    sys.exit(main())
