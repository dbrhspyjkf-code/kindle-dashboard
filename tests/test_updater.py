"""在线升级模块:版本读取 + 非 git 目录的诚实降级(不依赖网络)。"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from server import updater          # noqa: E402


def test_version_on_real_repo():
    """本仓库是 git clone,应能读到当前短哈希版本。"""
    assert updater.is_git_repo(ROOT) is True
    v = updater.current_version(ROOT)
    assert v and v != "?" and len(v) >= 4


def test_non_git_dir_degrades_gracefully(tmp_path):
    """非 git 目录:不报错,check/upgrade 都返回失败 + 明确提示(诚实降级)。"""
    d = str(tmp_path)
    assert updater.is_git_repo(d) is False
    assert updater.current_version(d) == "?"
    info = updater.check_for_update(d)
    assert info["ok"] is False and "git" in info["error"]
    ok, msg = updater.do_upgrade(d)
    assert ok is False and "git" in msg


def test_norm_ver():
    """版本号规整:能从 'v2.0' / 'mac-1.0' 抽数字元组,可大小比较。"""
    assert updater._norm_ver("v2.0") == (2, 0)
    assert updater._norm_ver("mac-1.0") == (1, 0)
    assert updater._norm_ver("v2.1") > updater._norm_ver("v2.0")
    assert updater._norm_ver("nodigits") is None


def test_installed_version_prefers_app_version_file(tmp_path):
    """.dmg 安装包写了 APP_VERSION 文件 → 用它;否则非 git 目录退回 '?'。"""
    (tmp_path / "APP_VERSION").write_text("3.5\n", encoding="utf-8")
    assert updater.installed_version(str(tmp_path)) == "3.5"
    empty = tmp_path / "empty"
    empty.mkdir()
    assert updater.installed_version(str(empty)) == "?"


def test_ver_from_asset():
    """从资产文件名取版本号:墨水桌面看板-1.0.dmg → 1.0。"""
    assert updater._ver_from_asset("墨水桌面看板-1.0.dmg", ".dmg") == "1.0"
    assert updater._ver_from_asset("墨水桌面看板-2.3.1.dmg", ".dmg") == "2.3.1"
    assert updater._ver_from_asset("no-version.dmg", ".dmg") == ""


def test_check_release_parses_and_compares(monkeypatch):
    """check_release:mock GitHub releases 列表,从 .dmg 资产文件名取版本比对(不打真网络)。"""
    import io
    import json as _json

    releases = [{
        "tag_name": "v2.0", "html_url": "https://example/r/v2.0", "name": "墨水 2.0",
        "draft": False, "prerelease": False,
        "assets": [
            {"name": "墨水桌面看板-2.0.dmg", "browser_download_url": "https://example/dl/app.dmg"},
            {"name": "MoshuiDesktop-2.0-2.apk", "browser_download_url": "https://example/dl/app.apk"},
        ],
    }]

    class _Resp(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): self.close()

    def fake_urlopen(req, timeout=0):
        return _Resp(_json.dumps(releases).encode("utf-8"))

    monkeypatch.setattr(updater.urllib.request, "urlopen", fake_urlopen)
    # Mac 查 .dmg:从文件名取 2.0,当前 1.0 → newer,asset_url 指向 .dmg(不会误拿同 release 的 apk)
    r = updater.check_release("o", "r", current="1.0", asset_suffix=".dmg")
    assert r["ok"] and r["newer"] and r["latest"] == "2.0" and r["asset_url"].endswith(".dmg")
    # 当前已是 2.0 → 不更新
    r2 = updater.check_release("o", "r", current="2.0", asset_suffix=".dmg")
    assert r2["ok"] and r2["newer"] is False


def test_check_release_no_matching_asset(monkeypatch):
    """release 里没有 .dmg(只有 apk)→ ok=False,不误报有更新。"""
    import io
    import json as _json
    releases = [{"tag_name": "v2.0", "draft": False, "prerelease": False,
                 "assets": [{"name": "only.apk", "browser_download_url": "x"}]}]

    class _Resp(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): self.close()
    monkeypatch.setattr(updater.urllib.request, "urlopen",
                        lambda req, timeout=0: _Resp(_json.dumps(releases).encode("utf-8")))
    r = updater.check_release("o", "r", current="1.0", asset_suffix=".dmg")
    assert r["ok"] is False


def test_check_release_network_error(monkeypatch):
    """网络失败:不抛异常,返回 ok=False + 提示。"""
    def boom(req, timeout=0):
        raise OSError("no network")
    monkeypatch.setattr(updater.urllib.request, "urlopen", boom)
    r = updater.check_release("o", "r", current="1.0")
    assert r["ok"] is False and "失败" in r["error"]


if __name__ == "__main__":
    import tempfile
    test_version_on_real_repo()
    test_norm_ver()
    with tempfile.TemporaryDirectory() as d:
        assert updater.is_git_repo(d) is False
        assert updater.check_for_update(d)["ok"] is False
    print("ok")
