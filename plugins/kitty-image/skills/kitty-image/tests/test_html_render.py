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
