# HTML→Image Render (`html.py`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an `html.py` to the kitty-image skill that renders a live URL, a local HTML file, or stdin HTML to a PNG (via Puppeteer-core + system Chrome) and displays it inline through `show.py`, with viewport / CSS-selector / full-page capture modes.

**Architecture:** A Python front-end (`html.py`) resolves the input to a `file://`/`http(s)` URL, ensures `puppeteer-core` is installed in a user cache dir, runs a small bundled Puppeteer script (`_snap.js`) against the system Chrome to produce a PNG, then execs `show.py`. Full-page captures display through a new `show.py --scroll` mode (fit-to-width, uncapped scrollable height). Browser detection / Puppeteer config / PNG checks / the `show.py` handoff are factored into a shared `_chrome.py` used by both `mermaid.py` and `html.py`.

**Tech Stack:** Python 3 (stdlib only), Node + `puppeteer-core` (no Chromium download), system Chrome/Chromium, pytest + Pillow for tests.

**Spec:** `docs/superpowers/specs/2026-05-30-html-render-design.md`

**Conventions:**
- All skill files live in `plugins/kitty-image/skills/kitty-image/` (abbreviated **SKILL/** below).
- Run tests from repo root: `pytest SKILL/tests -v` (replace SKILL/ with the full path).
- Commit messages: **no AI/Claude attribution** (maintainer preference).
- Work on branch `feature/v0.4.0-html-render` (already created).

---

### Task 1: Test scaffolding + `_chrome.py` shared helpers (TDD)

Extract the browser/PNG/display helpers currently inlined in `mermaid.py` into a shared `_chrome.py`, with unit tests. Modules in the skill dir are imported by name (the dir is on `sys.path` via `conftest.py`).

**Files:**
- Create: `plugins/kitty-image/skills/kitty-image/tests/conftest.py`
- Create: `plugins/kitty-image/skills/kitty-image/tests/test_chrome.py`
- Create: `plugins/kitty-image/skills/kitty-image/_chrome.py`

- [ ] **Step 1: Create the test conftest (puts the skill dir on sys.path)**

Create `plugins/kitty-image/skills/kitty-image/tests/conftest.py`:

```python
"""Make the skill's scripts importable by name in tests.

The skill dir contains plain scripts (show.py, mermaid.py, _chrome.py, html.py),
not an installable package, and its path has a hyphen — so tests put the skill
dir on sys.path and import the modules directly.

IMPORTANT: the skill dir contains a sibling `html.py`, which would shadow the
stdlib `html` module once the dir is on sys.path. We import stdlib `html` FIRST
so it is cached in sys.modules; any later bare `import html` (by a test, a pytest
plugin, or a transitively imported library, e.g. for html.escape) then keeps
resolving to the stdlib, not the skill script. The skill's own html.py is loaded
explicitly by file path under the alias `htmlpy` (see test_html.py).
"""
import sys
from pathlib import Path

import html  # noqa: F401  # cache stdlib html BEFORE the skill dir goes on sys.path

SKILL_DIR = Path(__file__).resolve().parents[1]
if str(SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(SKILL_DIR))
```

- [ ] **Step 2: Write the failing test for `_chrome.py`**

Create `plugins/kitty-image/skills/kitty-image/tests/test_chrome.py`:

```python
import _chrome


def test_find_chrome_returns_first_match(monkeypatch):
    monkeypatch.setattr(_chrome.shutil, "which",
                        lambda name: "/usr/bin/" + name if name == "chromium" else None)
    assert _chrome.find_chrome() == "/usr/bin/chromium"


def test_find_chrome_returns_none_when_absent(monkeypatch):
    monkeypatch.setattr(_chrome.shutil, "which", lambda name: None)
    assert _chrome.find_chrome() is None


def test_is_png_true_for_png_magic(tmp_path):
    p = tmp_path / "a.png"
    p.write_bytes(_chrome.PNG_MAGIC + b"rest")
    assert _chrome.is_png(p) is True


def test_is_png_false_for_other_bytes(tmp_path):
    p = tmp_path / "a.txt"
    p.write_bytes(b"not a png")
    assert _chrome.is_png(p) is False


def test_write_puppeteer_config_includes_executable(tmp_path):
    import json
    path = _chrome.write_puppeteer_config("/bin/google-chrome", str(tmp_path))
    cfg = json.loads(open(path).read())
    assert cfg["executablePath"] == "/bin/google-chrome"
    assert "--no-sandbox" in cfg["args"]
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `pytest plugins/kitty-image/skills/kitty-image/tests/test_chrome.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named '_chrome'`.

- [ ] **Step 4: Create `_chrome.py`**

Create `plugins/kitty-image/skills/kitty-image/_chrome.py`:

```python
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
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `pytest plugins/kitty-image/skills/kitty-image/tests/test_chrome.py -v`
Expected: PASS (5 tests).

- [ ] **Step 6: Commit**

```bash
git add plugins/kitty-image/skills/kitty-image/_chrome.py \
        plugins/kitty-image/skills/kitty-image/tests/conftest.py \
        plugins/kitty-image/skills/kitty-image/tests/test_chrome.py
git commit -m "Add shared _chrome.py helpers (browser detect, puppeteer cfg, png, display) with tests"
```

---

### Task 2: Point `mermaid.py` at `_chrome.py` (no behavior change)

Replace `mermaid.py`'s inlined copies with imports from `_chrome.py`. Behavior is identical; this removes duplication before `html.py` needs the same helpers.

**Files:**
- Modify: `plugins/kitty-image/skills/kitty-image/mermaid.py`

- [ ] **Step 1: Replace the inlined helpers with an import**

In `mermaid.py`, delete these definitions (they now live in `_chrome.py`):
- the `PNG_MAGIC`, `SKILL_DIR`, `SHOW_PY` module constants,
- the `CHROME_CANDIDATES` tuple,
- `def find_chrome(...)`,
- `def _write_puppeteer_config(...)`,
- `def _is_png(...)`,
- `def display(...)`.

Keep `MERMAID_CLI_SPEC` and `MERMAID_INK_BASE` (mermaid-specific). Add, right after the existing `from pathlib import Path` import line:

```python
from _chrome import (
    CHROME_CANDIDATES,
    PNG_MAGIC,
    display,
    find_chrome,
    is_png,
    write_puppeteer_config,
)
```

Do **not** import `SHOW_PY`: once `display()` moves to `_chrome.py`, mermaid.py no
longer references `SHOW_PY`, so importing it would be a dead import (flake8 F401).

- [ ] **Step 2: Update the two renamed call sites**

In `render_local()`, change `_write_puppeteer_config(chrome, tmpdir)` to `write_puppeteer_config(chrome, tmpdir)`.
In `render_local()`'s success check, change `not _is_png(out)` to `not is_png(out)`.
(`display(out, args.pts)` in `main()` still works — `scroll` defaults to False.)

- [ ] **Step 3: Verify mermaid.py still imports and parses**

Run:
```bash
python3 -c "import sys; sys.path.insert(0,'plugins/kitty-image/skills/kitty-image'); import mermaid; print('import OK')"
```
Expected: `import OK` (no ImportError, no NameError).

- [ ] **Step 4: Smoke-test a real render (skip if no chrome/node)**

Run:
```bash
printf 'graph LR\n A-->B\n' | python3 plugins/kitty-image/skills/kitty-image/mermaid.py - --no-show --out /tmp/mtest.png ; echo "exit=$?"
python3 -c "import sys;sys.path.insert(0,'plugins/kitty-image/skills/kitty-image');import _chrome;print('png ok', _chrome.is_png('/tmp/mtest.png'))"
```
Expected: `exit=0` and `png ok True` (if a local renderer is present; if exit is 10/11 because no renderer, that's an environment gap, not a regression — confirm the import in Step 3 instead).

- [ ] **Step 5: Commit**

```bash
git add plugins/kitty-image/skills/kitty-image/mermaid.py
git commit -m "mermaid.py: use shared _chrome.py helpers (no behavior change)"
```

---

### Task 3: Extract `fit_cells()` in `show.py` + add `fit_height` (TDD, regression-guarded)

Make the sizing math a pure, testable function and add the fit-to-width branch. Default behavior is unchanged from v0.3.0.

**Files:**
- Modify: `plugins/kitty-image/skills/kitty-image/show.py`
- Create: `plugins/kitty-image/skills/kitty-image/tests/test_fit_cells.py`

- [ ] **Step 1: Write the failing tests**

Create `plugins/kitty-image/skills/kitty-image/tests/test_fit_cells.py`:

```python
import show

# Terminal geometry used across cases: 192 cols x 45 rows, cell 10x22 px.
WS = dict(ws_row=45, ws_col=192, ws_xpixel=1920, ws_ypixel=990)  # cell_w=10, cell_h=22


def fit(w, h, fit_height=True):
    return show.fit_cells(w, h, WS["ws_row"], WS["ws_col"],
                          WS["ws_xpixel"], WS["ws_ypixel"], fit_height=fit_height)


def test_small_image_native_both_modes():
    # 240x120 px -> 24 cols x 6 rows; fits, so unchanged in either mode.
    assert fit(240, 120, fit_height=True) == (24, 6)
    assert fit(240, 120, fit_height=False) == (24, 6)


def test_fit_height_downscales_tall_image():
    # 400x2970 px native ~ 40c x 135r; avail_r = 45-2-6 = 37 -> must shrink.
    c, r = fit(400, 2970, fit_height=True)
    assert r <= 37 and c <= 191
    assert r >= 1 and c >= 1


def test_scroll_keeps_tall_image_native_uncapped():
    # Tall-narrow fits width (40c <= 191), so scroll mode keeps it native and
    # does NOT cap the height at the screen.
    assert fit(400, 2970, fit_height=False) == (40, 135)


def test_scroll_downscales_only_when_wider_than_terminal():
    # 4000x8000 px ~ 400c x 364r. Wider than avail 191 -> scale = 191/400; the
    # height scales by the SAME factor and is NOT capped at the screen:
    # round(364 * 0.4775) = 174 (a hard regression guard for "uncapped height").
    assert fit(4000, 8000, fit_height=False) == (191, 174)


def test_scroll_never_upscales():
    # A small image stays its native size; width is not stretched to 191.
    assert fit(100, 100, fit_height=False)[0] < 191


def test_bad_geometry_returns_unit():
    assert show.fit_cells(240, 120, 0, 0, 0, 0) == (1, 1)
    assert show.fit_cells(0, 0, 45, 192, 1920, 990) == (1, 1)
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest plugins/kitty-image/skills/kitty-image/tests/test_fit_cells.py -v`
Expected: FAIL — `AttributeError: module 'show' has no attribute 'fit_cells'`.

- [ ] **Step 3: Add `fit_cells()` and rewrite `placement_cells()` to call it**

In `show.py`, replace the entire body of `placement_cells()` with a thin wrapper and add the pure `fit_cells()` above it. The final two functions read:

```python
def fit_cells(img_w: int, img_h: int, ws_row: int, ws_col: int,
              ws_xpixel: int, ws_ypixel: int, fit_height: bool = True) -> tuple[int, int]:
    """Pure sizing math: native image px + terminal geometry -> (cols, rows).

    fit_height=True  (default): fit BOTH dims to the viewport (the v0.3.0 path).
    fit_height=False (--scroll): fit WIDTH only; never upscale; leave the height
        uncapped so the image scrolls. The terminal width is an upper bound, not
        a target — a capture narrower than the terminal keeps its native width.
    Returns (1, 1) when geometry is unusable.
    """
    if img_w <= 0 or img_h <= 0 or ws_row <= 0 or ws_ypixel <= 0:
        return (1, 1)
    cell_h = ws_ypixel / ws_row
    cell_w = (ws_xpixel / ws_col) if (ws_col > 0 and ws_xpixel > 0) else (cell_h / 2.0)
    nat_c = max(1, math.ceil(img_w / cell_w))
    nat_r = max(1, math.ceil(img_h / cell_h))
    avail_c = max(1, (ws_col - 1) if ws_col > 0 else nat_c)

    if not fit_height:
        # Fit width only. Never enlarge; height uncapped (scrolls).
        if nat_c <= avail_c:
            return (nat_c, nat_r)
        scale = avail_c / nat_c
        return (avail_c, max(1, round(nat_r * scale)))

    avail_r = max(1, ws_row - 2 - DRIFT_MARGIN)
    if nat_c <= avail_c and nat_r <= avail_r:
        return (nat_c, nat_r)
    scale = min(avail_c / nat_c, avail_r / nat_r)
    fit_c = max(1, min(avail_c, round(nat_c * scale)))
    fit_r = max(1, min(avail_r, round(nat_r * scale)))
    return (fit_c, fit_r)


def placement_cells(tty_fd: int, png_bytes: bytes, fit_height: bool = True) -> tuple[int, int]:
    """Return (cols, rows) for the image, querying the PTY geometry then
    delegating the math to fit_cells(). See fit_cells for the fit_height modes."""
    img_w, img_h = png_dimensions(png_bytes)
    try:
        packed = fcntl.ioctl(tty_fd, termios.TIOCGWINSZ, b"\x00" * 8)
        ws_row, ws_col, ws_xpixel, ws_ypixel = struct.unpack("HHHH", packed)
    except OSError:
        return (1, 1)
    return fit_cells(img_w, img_h, ws_row, ws_col, ws_xpixel, ws_ypixel, fit_height)
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest plugins/kitty-image/skills/kitty-image/tests/test_fit_cells.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add plugins/kitty-image/skills/kitty-image/show.py \
        plugins/kitty-image/skills/kitty-image/tests/test_fit_cells.py
git commit -m "show.py: extract pure fit_cells() and add fit-to-width (fit_height) branch"
```

---

### Task 4: Wire `show.py --scroll` through the render path

Expose `fit_height` to the CLI and the placement call.

**Files:**
- Modify: `plugins/kitty-image/skills/kitty-image/show.py`

- [ ] **Step 1: Thread `fit_height` into `send_kitty_graphics()`**

In `show.py`, change the `send_kitty_graphics` signature and its `placement_cells` call:

```python
def send_kitty_graphics(png_bytes: bytes, pts_path: str, fit_height: bool = True) -> tuple[int, int]:
```
and inside, change:
```python
        cols, rows = placement_cells(tty.fileno(), png_bytes)
```
to:
```python
        cols, rows = placement_cells(tty.fileno(), png_bytes, fit_height)
```

- [ ] **Step 2: Add the `--scroll` flag and pass it**

In `main()`'s argparse block (next to `--pts`/`--clear`), add:
```python
    ap.add_argument("--scroll", action="store_true",
                    help="fit to width only and leave the height uncapped so a tall "
                         "image scrolls (instead of being shrunk to fit the screen)")
```
Then change the render call in `main()`:
```python
    n, rows = send_kitty_graphics(png_data, pts)
```
to:
```python
    n, rows = send_kitty_graphics(png_data, pts, fit_height=not args.scroll)
```

- [ ] **Step 3: Verify default behavior unchanged + flag parses**

Run:
```bash
python3 plugins/kitty-image/skills/kitty-image/show.py --help | grep -- --scroll
python3 -c "import sys; sys.path.insert(0,'plugins/kitty-image/skills/kitty-image'); import show; print('ok')"
```
Expected: the `--scroll` help line prints, and `ok`.

- [ ] **Step 4: Commit**

```bash
git add plugins/kitty-image/skills/kitty-image/show.py
git commit -m "show.py: add --scroll (fit-to-width, scrollable height) flag"
```

---

### Task 5: Add the Puppeteer screenshot script `_snap.js`

**Files:**
- Create: `plugins/kitty-image/skills/kitty-image/_snap.js`

- [ ] **Step 1: Create `_snap.js`**

Create `plugins/kitty-image/skills/kitty-image/_snap.js`:

```javascript
// Screenshot driver for html.py. Config arrives as JSON in $SNAP_CFG; the
// caller sets NODE_PATH so `require('puppeteer-core')` resolves from the cache.
// Exit codes: 0 ok | 40 launch failed | 41 navigation/screenshot failed |
// 42 selector not found. A short "SNAPERR[phase] message" goes to stderr.
const puppeteer = require('puppeteer-core');

(async () => {
  const cfg = JSON.parse(process.env.SNAP_CFG);
  let phase = 'launch';
  let browser;
  try {
    browser = await puppeteer.launch({
      executablePath: cfg.chrome,
      args: ['--no-sandbox', '--disable-gpu'],
      headless: true,
    });
    const page = await browser.newPage();
    await page.setViewport({
      width: cfg.width,
      height: cfg.height,
      deviceScaleFactor: cfg.scale,
    });

    phase = 'navigate';
    await page.goto(cfg.url, { waitUntil: 'networkidle2', timeout: cfg.timeout });
    if (cfg.wait) {
      await new Promise((r) => setTimeout(r, cfg.wait));
    }

    if (cfg.selector) {
      phase = 'selector';
      await page.waitForSelector(cfg.selector, { timeout: cfg.timeout });
      const el = await page.$(cfg.selector);
      if (!el) throw new Error('selector matched no element: ' + cfg.selector);
      phase = 'shoot';
      await el.screenshot({ path: cfg.out });
    } else {
      phase = 'shoot';
      await page.screenshot({ path: cfg.out, fullPage: !!cfg.fullPage });
    }
  } catch (e) {
    process.stderr.write('SNAPERR[' + phase + '] ' + (e && e.message ? e.message : e) + '\n');
    process.exitCode = phase === 'selector' ? 42 : (phase === 'launch' ? 40 : 41);
  } finally {
    if (browser) {
      try { await browser.close(); } catch (_) { /* ignore */ }
    }
  }
})();
```

- [ ] **Step 2: Sanity-check the script parses**

Run: `node --check plugins/kitty-image/skills/kitty-image/_snap.js && echo "syntax OK"`
Expected: `syntax OK`.

- [ ] **Step 3: Commit**

```bash
git add plugins/kitty-image/skills/kitty-image/_snap.js
git commit -m "Add _snap.js: puppeteer-core screenshot driver (viewport/full-page/selector)"
```

---

### Task 6: Create `html.py` with unit tests (TDD)

**Files:**
- Create: `plugins/kitty-image/skills/kitty-image/html.py`
- Create: `plugins/kitty-image/skills/kitty-image/tests/test_html.py`

- [ ] **Step 1: Write the failing unit tests**

Create `plugins/kitty-image/skills/kitty-image/tests/test_html.py`:

```python
import importlib.util
import sys
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parents[1]
if str(SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(SKILL_DIR))

# html.py shares a name with the stdlib `html` module, so load it explicitly.
_spec = importlib.util.spec_from_file_location("htmlpy", SKILL_DIR / "html.py")
htmlpy = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(htmlpy)


def test_parse_viewport_valid():
    assert htmlpy.parse_viewport("1280x800") == (1280, 800)


@pytest.mark.parametrize("bad", ["1280", "1280X800x2", "axb", "0x600", "800x0", ""])
def test_parse_viewport_invalid(bad):
    import argparse
    with pytest.raises(argparse.ArgumentTypeError):
        htmlpy.parse_viewport(bad)


def test_resolve_scale_defaults():
    assert htmlpy.resolve_scale(full_page=False, scale=None) == 2
    assert htmlpy.resolve_scale(full_page=True, scale=None) == 1
    assert htmlpy.resolve_scale(full_page=True, scale=3) == 3


def test_resolve_source_http_passthrough(tmp_path):
    assert htmlpy.resolve_source("https://example.com/x", str(tmp_path)) == "https://example.com/x"
    assert htmlpy.resolve_source("HTTP://EXAMPLE", str(tmp_path)) == "HTTP://EXAMPLE"


def test_resolve_source_existing_file(tmp_path):
    f = tmp_path / "page.html"
    f.write_text("<h1>hi</h1>")
    uri = htmlpy.resolve_source(str(f), str(tmp_path))
    assert uri.startswith("file://") and uri.endswith("page.html")


def test_resolve_source_missing_file_exits_21(tmp_path):
    with pytest.raises(SystemExit) as e:
        htmlpy.resolve_source(str(tmp_path / "nope.html"), str(tmp_path))
    assert e.value.code == 21


def test_resolve_source_stdin(monkeypatch, tmp_path):
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO("<p>from stdin</p>"))
    uri = htmlpy.resolve_source("-", str(tmp_path))
    assert uri.startswith("file://")
    assert "from stdin" in (tmp_path / "input.html").read_text()


def test_resolve_source_empty_stdin_exits_23(monkeypatch, tmp_path):
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO("   \n"))
    with pytest.raises(SystemExit) as e:
        htmlpy.resolve_source("-", str(tmp_path))
    assert e.value.code == 23


def test_full_page_and_selector_conflict_exits_2():
    import subprocess
    r = subprocess.run(
        [sys.executable, str(SKILL_DIR / "html.py"), "x.html", "--full-page", "--selector", ".a"],
        capture_output=True, text=True,
    )
    assert r.returncode == 2
    assert "mutually exclusive" in r.stderr.lower()


def test_no_chrome_returns_20(monkeypatch, tmp_path, capsys):
    # find_chrome() check runs before any source/render work, so the source need
    # not exist. main() returns 20 and the message lists the candidate binaries.
    monkeypatch.setattr(htmlpy, "find_chrome", lambda: None)
    monkeypatch.setattr(sys, "argv", ["html.py", str(tmp_path / "x.html")])
    assert htmlpy.main() == 20
    assert "google-chrome" in capsys.readouterr().err


def test_npm_missing_exits_20(monkeypatch, tmp_path):
    # Empty cache dir -> the puppeteer-core fast-path is skipped; then npm is
    # absent, so ensure_puppeteer() exits 20.
    monkeypatch.setattr(htmlpy, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(htmlpy.shutil, "which", lambda name: None)
    with pytest.raises(SystemExit) as e:
        htmlpy.ensure_puppeteer()
    assert e.value.code == 20


def test_output_dir_unwritable_returns_23(monkeypatch, tmp_path):
    # Chrome mocked present so we reach the output-dir step; --out's parent sits
    # under an existing FILE, so mkdir(parents=True) raises NotADirectoryError.
    monkeypatch.setattr(htmlpy, "find_chrome", lambda: "/bin/google-chrome")
    blocker = tmp_path / "afile"
    blocker.write_text("x")
    bad_out = blocker / "sub" / "out.png"
    monkeypatch.setattr(sys, "argv",
                        ["html.py", str(tmp_path / "x.html"), "--out", str(bad_out)])
    assert htmlpy.main() == 23
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest plugins/kitty-image/skills/kitty-image/tests/test_html.py -v`
Expected: FAIL — `FileNotFoundError`/exec error because `html.py` does not exist yet.

- [ ] **Step 3: Create `html.py`**

Create `plugins/kitty-image/skills/kitty-image/html.py`:

```python
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
```

- [ ] **Step 4: Run unit tests to verify they pass**

Run: `pytest plugins/kitty-image/skills/kitty-image/tests/test_html.py -v`
Expected: PASS — 17 collected items (the 6-case `parse_viewport` parametrize plus the
resolve_source, scale, conflict→exit 2, no-chrome→20, npm-missing→20, and
output-dir→23 cases).

- [ ] **Step 5: Commit**

```bash
git add plugins/kitty-image/skills/kitty-image/html.py \
        plugins/kitty-image/skills/kitty-image/tests/test_html.py
git commit -m "Add html.py: render URL/file/stdin HTML to inline image (viewport/selector/full-page)"
```

---

### Task 7: Integration smoke test (real render, auto-skipped without deps)

**Files:**
- Create: `plugins/kitty-image/skills/kitty-image/tests/test_html_render.py`

- [ ] **Step 1: Write the smoke test**

Create `plugins/kitty-image/skills/kitty-image/tests/test_html_render.py`:

```python
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parents[1]
HTML_PY = SKILL_DIR / "html.py"

_have_deps = bool(shutil.which("node") and shutil.which("npm") and (
    shutil.which("google-chrome") or shutil.which("google-chrome-stable")
    or shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("chrome")
))
pytestmark = pytest.mark.skipif(not _have_deps, reason="node/npm/Chrome not available")


@pytest.fixture(scope="module")
def snap_env(tmp_path_factory):
    """Env that isolates puppeteer-core into a throwaway cache dir.

    NOTE: the FIRST render here performs a one-time `npm install puppeteer-core`
    into this cache (needs network); later renders reuse it. A module-scoped temp
    XDG_CACHE_HOME keeps the install out of the user's real ~/.cache and runs it
    exactly once for all tests in this file.
    """
    cache = tmp_path_factory.mktemp("xdg-cache")
    env = dict(os.environ)
    env["XDG_CACHE_HOME"] = str(cache)
    return env


def _render(args, out, env):
    return subprocess.run(
        [sys.executable, str(HTML_PY), *args, "--no-show", "--out", str(out)],
        capture_output=True, text=True, timeout=180, env=env,
    )


def test_renders_local_file_viewport(tmp_path, snap_env):
    page = tmp_path / "p.html"
    page.write_text("<!doctype html><body style='margin:0'>"
                    "<div class='box' style='width:300px;height:150px;background:#1f3a5f'>hi</div>")
    out = tmp_path / "out.png"
    proc = _render([str(page), "--viewport", "800x600", "--scale", "1"], out, snap_env)
    assert proc.returncode == 0, proc.stderr
    from PIL import Image
    assert Image.open(out).size == (800, 600)


def test_renders_selector(tmp_path, snap_env):
    page = tmp_path / "p.html"
    page.write_text("<!doctype html><body>"
                    "<div class='box' style='width:300px;height:150px;background:#1f3a5f'></div></body>")
    out = tmp_path / "out.png"
    proc = _render([str(page), "--selector", ".box", "--scale", "1"], out, snap_env)
    assert proc.returncode == 0, proc.stderr
    from PIL import Image
    w, h = Image.open(out).size
    assert w >= 300 and h >= 150  # the element box (plus any borders)


def test_renders_full_page_exceeds_viewport(tmp_path, snap_env):
    # Page taller than the viewport -> --full-page must capture beyond it.
    page = tmp_path / "p.html"
    page.write_text("<!doctype html><body style='margin:0'>"
                    "<div style='height:3000px;background:#10121a'></div></body>")
    out = tmp_path / "out.png"
    proc = _render([str(page), "--viewport", "800x600", "--scale", "1", "--full-page"], out, snap_env)
    assert proc.returncode == 0, proc.stderr
    from PIL import Image
    w, h = Image.open(out).size
    assert w == 800 and h > 600  # full scroll height captured, not just the viewport


def test_missing_selector_exits_22(tmp_path, snap_env):
    page = tmp_path / "p.html"
    page.write_text("<!doctype html><body><p>no box here</p></body>")
    out = tmp_path / "out.png"
    proc = _render([str(page), "--selector", ".nope", "--timeout", "3000"], out, snap_env)
    assert proc.returncode == 22, proc.stderr
```

- [ ] **Step 2: Run the smoke test**

Run: `pytest plugins/kitty-image/skills/kitty-image/tests/test_html_render.py -v`
Expected: PASS (4 tests) where Node/Chrome exist; otherwise SKIPPED. The first test
triggers a one-time `npm install puppeteer-core` into an isolated temp cache (needs
network); if offline on a deps-present box, expect that first render to fail.

- [ ] **Step 3: Run the whole suite**

Run: `pytest plugins/kitty-image/skills/kitty-image/tests -v`
Expected: all PASS/SKIP, no failures.

- [ ] **Step 4: Commit**

```bash
git add plugins/kitty-image/skills/kitty-image/tests/test_html_render.py
git commit -m "Add html.py integration smoke tests (viewport, selector, missing-selector)"
```

---

### Task 8: Docs, version bump, changelog

**Files:**
- Modify: `plugins/kitty-image/.claude-plugin/plugin.json`
- Modify: `plugins/kitty-image/skills/kitty-image/SKILL.md`
- Modify: `README.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Bump the plugin version to 0.4.0**

In `plugins/kitty-image/.claude-plugin/plugin.json`, change `"version": "0.3.0",` to `"version": "0.4.0",`. In the same file's `description`, append a sentence: ` Also renders HTML (a URL, a local file, or stdin) to an inline image via headless Chrome.` And add to `keywords`: `"html"`, `"screenshot"`, `"webpage"`.

- [ ] **Step 2: Add the SKILL.md frontmatter trigger + when-to-invoke bullet**

In `SKILL.md`, in the YAML `description:` value, append before the final sentence: ` Also renders a web page or HTML (a live URL, a local .html file, or an HTML string) to an inline image via html.py (headless Chrome).`

In the "## When to invoke this skill" list, add a bullet after the Mermaid bullet:
```markdown
- The user wants to **see a web page, a URL, or a chunk of HTML** as it renders — use `html.py` (headless Chrome screenshot). Viewport by default; `--selector` for one element; `--full-page` for the whole page (shown scrolling, not shrunk).
```

- [ ] **Step 3: Add the SKILL.md "HTML & web page rendering" section**

In `SKILL.md`, immediately before the "## Override and clear" section, insert:

````markdown
## HTML & web page rendering

Render a **live URL, a local `.html` file, or an HTML string (stdin)** to a PNG
and display it inline with `html.py`. Like `mermaid.py`, it execs `show.py`, so
all the PTY/fit-to-screen handling is reused. It drives **Puppeteer-core pointed
at your system Chrome** — the same browser `mermaid.py` uses; puppeteer-core is
installed once into `${XDG_CACHE_HOME:-~/.cache}/kitty-image` and downloads no
Chromium.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/kitty-image/html.py" https://example.com
echo '<h1 style="font:48px sans-serif">hi</h1>' | python3 "${CLAUDE_PLUGIN_ROOT}/skills/kitty-image/html.py" -
python3 "${CLAUDE_PLUGIN_ROOT}/skills/kitty-image/html.py" page.html --selector '.hero'
python3 "${CLAUDE_PLUGIN_ROOT}/skills/kitty-image/html.py" https://x.com --full-page
```

### Capture modes
- **Viewport (default):** the visible window at `--viewport WxH` (default `1280x800`). Best for inline display.
- **`--selector <css>`:** screenshot just the first matching element — crisp, ideal for one component.
- **`--full-page`:** the entire scroll height. Displayed via `show.py --scroll` (fit-to-width, **scrollable**, not shrunk to fit), so it stays readable. Defaults to `--scale 1` to keep the row count sane.

### Options
```
--viewport WxH   render viewport (default 1280x800)
--scale N        device scale factor (default 2; 1 for --full-page)
--wait MS        extra wait after network-idle (default 0)
--timeout MS     navigation/selector timeout (default 30000)
--out PATH       output PNG (default /tmp/html.png)
--no-show        render only; print the path
--pts /dev/pts/N passthrough to show.py
```

### Privacy & requirements
- **Local file / stdin render fully offline**; a **live URL** fetches that page (its whole point) and makes no other calls. There is **no third-party screenshot service**.
- Needs `node`/`npm` (already required by `mermaid.py`) and a system Chrome/Chromium **plus its OS libraries** (`libnss3`, `libgbm`, `libasound2`, …). These can't be auto-installed; on a bare server install them with your package manager. Exit codes: `20` no renderer/Chrome, `21` load failed, `22` selector not found, `23` bad input/output.
- For crisp inline output prefer viewport or `--selector`; `--full-page` is for scrolling through or saving with `--no-show`.
````

Also append four `html.py` rows to the existing "## Failure modes and what they mean"
table in `SKILL.md` (it currently has show.py 2–6 and mermaid.py 10–13 rows), so the
table stays the single reference for exit codes:

```markdown
| 20 | html.py | No usable renderer — no `npm`/Node, or no Chrome/Chromium found | Install Node and a Chrome/Chromium (and its OS libs); see message |
| 21 | html.py | Navigation/load failed — bad URL, timeout, or missing local file | Check the URL/path and connectivity; raise `--timeout` |
| 22 | html.py | `--selector` element not found before timeout | Fix the selector or raise `--timeout` |
| 23 | html.py | Input/output error — empty stdin, or output dir not writable | Provide HTML on stdin / choose a writable `--out` |
```

- [ ] **Step 4: Update README — add an "HTML & web pages" subsection**

`README.md` has no bulleted feature list (features are prose; Mermaid lives in a
`### Mermaid diagrams` subsection). Add a new `### HTML & web pages` subsection
**immediately after** the `### Mermaid diagrams` subsection and **before**
`## Known limitations`, mirroring the Mermaid subsection's prose-plus-code-block
style:

```markdown
### HTML & web pages

Render a live URL, a local `.html` file, or an HTML string (stdin) to an inline
image with `html.py` — a headless-Chrome screenshot that hands off to `show.py`.
It uses your **system Chrome** (no Chromium download); `puppeteer-core` is
installed once into `~/.cache/kitty-image`.

```bash
html.py https://example.com                 # viewport screenshot
html.py page.html --selector '.hero'         # just one element
html.py https://example.com --full-page      # whole page, shown scrolling
echo '<h1>hi</h1>' | html.py -                # HTML from stdin
```

Local files and stdin render fully offline; a URL fetches only that page (no
third-party screenshot service). Requires Node and a Chrome/Chromium plus its OS
libraries.
```

- [ ] **Step 5: Update CHANGELOG**

In `CHANGELOG.md`, under `## [Unreleased]`, add a new released section:
```markdown
## [0.4.0] - 2026-05-30
### Added
- **HTML → inline image** (`html.py`): render a live URL, a local HTML file, or stdin HTML to a PNG and display it inline. Drives Puppeteer-core against the system Chrome (installed once into a user cache; no Chromium download), then hands off to `show.py`. Capture modes: viewport (default), `--selector` (one element), `--full-page`.
- `show.py --scroll`: fit-to-width display with uncapped, scrollable height — never upscales. Used for full-page captures so long pages stay readable instead of being shrunk to fit.

### Changed
- Extracted shared browser/PNG/display helpers into `_chrome.py`, used by both `mermaid.py` and `html.py` (no behavior change to mermaid rendering).
- `show.py`'s sizing math is now a pure `fit_cells()` function (unit-tested); default fit-to-screen behavior is unchanged.
```
Then update the link references at the bottom: change the `[Unreleased]` compare to `v0.4.0...HEAD` and add `[0.4.0]: https://github.com/whallil/claude-kitty-image/compare/v0.3.0...v0.4.0`.

- [ ] **Step 6: Verify version + full suite once more**

Run:
```bash
grep '"version"' plugins/kitty-image/.claude-plugin/plugin.json
pytest plugins/kitty-image/skills/kitty-image/tests -q
```
Expected: `"version": "0.4.0",` and a green suite (skips allowed).

- [ ] **Step 7: Commit**

```bash
git add plugins/kitty-image/.claude-plugin/plugin.json \
        plugins/kitty-image/skills/kitty-image/SKILL.md README.md CHANGELOG.md
git commit -m "Docs + v0.4.0: document html.py and show.py --scroll; bump version"
```

---

### Task 9: End-to-end manual verification (live terminal)

Not automated — confirms real inline display in Kitty.

- [ ] **Step 1: Viewport render of a real page**

Run: `python3 plugins/kitty-image/skills/kitty-image/html.py https://example.com`
Expected: the page appears inline above a `└─ html.png` caption; exit 0.

- [ ] **Step 2: Full-page scroll mode**

Run: `python3 plugins/kitty-image/skills/kitty-image/html.py https://example.com --full-page`
Expected: a taller image at readable width that scrolls with the conversation (not a shrunk thumbnail).

- [ ] **Step 3: Selector + stdin**

Run: `echo '<div class="c" style="width:420px;padding:40px;background:#10121a;color:#eee;font:28px sans-serif">hello</div>' | python3 plugins/kitty-image/skills/kitty-image/html.py - --selector .c`
Expected: just the card renders inline.

- [ ] **Step 4: Note results** in the PR description when shipping.

---

## Notes for the implementer
- **DRY/YAGNI/TDD/frequent commits** as structured above.
- The skill scripts are standalone (run via `python3 <script>.py`); `_chrome` resolves because the script's own dir is `sys.path[0]`. Tests add the dir explicitly via `conftest.py` and load `html.py` by file path (its name shadows stdlib `html`).
- Do **not** add AI/Claude attribution to commits (maintainer preference, recorded in project memory).
- First `html.py` run triggers a ~1s `npm install` of puppeteer-core into the cache; subsequent runs are instant.
