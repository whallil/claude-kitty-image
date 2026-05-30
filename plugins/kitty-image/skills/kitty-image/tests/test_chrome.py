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
