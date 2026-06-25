"""chrome-headless-shell 优先 + 判定:macOS 上完整 Chrome 的 --headless=new 会闪 Dock,
chrome-headless-shell 不弹。find_chrome 优先用它;渲染对 shell 不加 --headless。"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from server.render import pipeline   # noqa: E402


def test_is_headless_shell():
    assert pipeline.is_headless_shell("/x/chrome-headless-shell") is True
    assert pipeline.is_headless_shell("/x/chrome-headless-shell-mac-arm64/chrome-headless-shell") is True
    assert pipeline.is_headless_shell("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome") is False
    assert pipeline.is_headless_shell("/usr/bin/chromium") is False
    assert pipeline.is_headless_shell("") is False


def test_find_chrome_prefers_headless_shell(monkeypatch):
    """有 chrome-headless-shell 时,find_chrome 优先返回它(macOS 不弹 Dock),不退回完整 Chrome。"""
    monkeypatch.delenv("CHROME_BIN", raising=False)
    monkeypatch.setattr(pipeline, "_headless_shell", lambda: "/fake/chrome-headless-shell")
    assert pipeline.find_chrome() == "/fake/chrome-headless-shell"


def test_find_chrome_falls_back_without_shell(monkeypatch):
    """没有 shell 时回退系统浏览器(行为不变)。"""
    monkeypatch.delenv("CHROME_BIN", raising=False)
    monkeypatch.setattr(pipeline, "_headless_shell", lambda: "")
    monkeypatch.setattr(pipeline.shutil, "which",
                        lambda n: "/usr/bin/chromium" if n == "chromium" else None)
    assert pipeline.find_chrome() == "/usr/bin/chromium"


def test_chrome_bin_env_wins(monkeypatch, tmp_path):
    """CHROME_BIN 显式指定时优先级最高,盖过 shell 探测。"""
    fake = tmp_path / "mychrome"
    fake.write_text("")
    monkeypatch.setenv("CHROME_BIN", str(fake))
    monkeypatch.setattr(pipeline, "_headless_shell", lambda: "/fake/chrome-headless-shell")
    assert pipeline.find_chrome() == str(fake)


if __name__ == "__main__":
    test_is_headless_shell()
    print("ok")
