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
