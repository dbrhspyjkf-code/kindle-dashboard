"""iCloud 公开共享相册解析验证。可直接 python3 跑,也兼容 pytest。"""
import os
import sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from server.sources import icloud_album as ia  # noqa: E402


def test_parse_token():
    assert ia.parse_token("https://www.icloud.com/sharedalbum/#B0ABCdef") == "B0ABCdef"
    assert ia.parse_token("https://www.icloud.com/sharedalbum/#A1xyz?q=1") == "A1xyz"
    assert ia.parse_token("not a url") == ""
    assert ia.parse_token("") == ""


def test_partition_host():
    # 'A' → p01, 'B' → p02 ... 首字符决定分区(A=1)
    assert ia.partition_host("A1xxx") == "p01-sharedstreams.icloud.com"
    assert ia.partition_host("B0xxx") == "p02-sharedstreams.icloud.com"


def test_parse_webstream_picks_largest():
    data = {"photos": [
        {"photoGuid": "g1", "derivatives": {
            "1": {"checksum": "cks_small", "width": "100", "height": "100"},
            "2": {"checksum": "cks_big", "width": "2000", "height": "1500"},
        }},
        {"photoGuid": "g2", "derivatives": {
            "1": {"checksum": "cks2", "width": "800", "height": "600"},
        }},
    ]}
    out = ia.parse_webstream(data)
    assert out == [
        {"guid": "g1", "checksums": ["cks_big"]},
        {"guid": "g2", "checksums": ["cks2"]},
    ]


def test_parse_asset_urls():
    data = {"items": {
        "cks_big": {"url_location": "cvws.icloud-content.com", "url_path": "/B/abc?o=1"},
    }}
    out = ia.parse_asset_urls(data)
    assert out == {"cks_big": "https://cvws.icloud-content.com/B/abc?o=1"}


def test_build_photo_list():
    stream = [{"guid": "g1", "checksums": ["cks_big"]},
              {"guid": "g2", "checksums": ["missing"]}]
    assets = {"cks_big": "https://h/p"}
    out = ia.build_photo_list({"photos_parsed": stream}, assets) if False else ia.build_photo_list(stream, assets)
    assert out == [{"guid": "g1", "checksum": "cks_big", "url": "https://h/p"}]


class _FakeResp:
    def __init__(self, status=200, payload=None, headers=None):
        self.status_code = status
        self._payload = payload or {}
        self.headers = headers or {}
    def json(self):
        return self._payload


class _FakeClient:
    """按 url 路径返回预设响应,记录调用。"""
    def __init__(self, routes):
        self.routes = routes          # path 子串 -> _FakeResp 或 list(按序弹出)
        self.calls = []
    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append(url)
        for key, resp in self.routes.items():
            if key in url:
                if isinstance(resp, list):
                    return resp.pop(0)
                return resp
        return _FakeResp(404, {})
    def __enter__(self): return self
    def __exit__(self, *a): return False


def test_fetch_album_photos_happy():
    stream_payload = {"photos": [
        {"photoGuid": "g1", "derivatives": {"2": {"checksum": "c1", "width": "2000", "height": "1500"}}},
    ]}
    asset_payload = {"items": {"c1": {"url_location": "h.com", "url_path": "/p?o=1"}}}
    fake = _FakeClient({
        "webstream": _FakeResp(200, stream_payload),
        "webasseturls": _FakeResp(200, asset_payload),
    })
    out = ia.fetch_album_photos("https://www.icloud.com/sharedalbum/#B0X", client=fake)
    assert out == [{"guid": "g1", "checksum": "c1", "url": "https://h.com/p?o=1"}]


def test_fetch_album_photos_330_redirect():
    stream_payload = {"photos": [
        {"photoGuid": "g1", "derivatives": {"2": {"checksum": "c1", "width": "10", "height": "10"}}},
    ]}
    asset_payload = {"items": {"c1": {"url_location": "h.com", "url_path": "/p"}}}
    fake = _FakeClient({
        "webstream": [
            _FakeResp(330, {}, {"X-Apple-MMe-Host": "p33-sharedstreams.icloud.com"}),
            _FakeResp(200, stream_payload),
        ],
        "webasseturls": _FakeResp(200, asset_payload),
    })
    out = ia.fetch_album_photos("https://www.icloud.com/sharedalbum/#B0X", client=fake)
    assert out and out[0]["url"] == "https://h.com/p"
    assert any("p33-sharedstreams" in u for u in fake.calls)   # 用了重定向后的 host


def test_fetch_album_photos_bad_url():
    assert ia.fetch_album_photos("", client=_FakeClient({})) == []
    assert ia.fetch_album_photos("https://x.com/no-hash", client=_FakeClient({})) == []


def test_collect_no_url_returns_none():
    assert ia.collect({"album": {"shared_url": ""}}) is None
    assert ia.collect({}) is None


def test_collect_processes_and_caches(tmp_path, monkeypatch):
    # mock 拉列表
    monkeypatch.setattr(ia, "fetch_album_photos",
                        lambda url, **k: [{"guid": "g1", "checksum": "c", "url": "https://h/p"}])
    # mock 下载
    from PIL import Image
    import io
    def _fake_dl(url):
        buf = io.BytesIO(); Image.new("RGB", (400, 300)).save(buf, "PNG"); return buf.getvalue()
    monkeypatch.setattr(ia, "_download", _fake_dl)
    # 缓存目录指向 tmp
    monkeypatch.setattr(ia, "_cache_dir", lambda cfg: str(tmp_path))
    cfg = {"album": {"shared_url": "https://www.icloud.com/sharedalbum/#B0X", "max_photos": 10},
           "server": {"kindle_model": "base"}}
    out = ia.collect(cfg)
    assert out and len(out["album_photos"]) == 1
    assert os.path.exists(out["album_photos"][0]["path"])
    assert out["album_photos"][0]["guid"] == "g1"


def test_collect_prunes_orphan_cache_files(tmp_path, monkeypatch):
    """collect 成功后应删除缓存目录中不属于当前相册的孤儿 .png 文件。"""
    # 预先放一个孤儿文件
    orphan = tmp_path / "old_800x600_v1.png"
    orphan.write_bytes(b"stale")

    monkeypatch.setattr(ia, "fetch_album_photos",
                        lambda url, **k: [{"guid": "g2", "checksum": "c2", "url": "https://h/p"}])
    from PIL import Image
    import io
    def _fake_dl(url):
        buf = io.BytesIO(); Image.new("RGB", (400, 300)).save(buf, "PNG"); return buf.getvalue()
    monkeypatch.setattr(ia, "_download", _fake_dl)
    monkeypatch.setattr(ia, "_cache_dir", lambda cfg: str(tmp_path))

    cfg = {"album": {"shared_url": "https://www.icloud.com/sharedalbum/#B0X", "max_photos": 10},
           "server": {"kindle_model": "base"}}
    out = ia.collect(cfg)
    assert out is not None
    # 孤儿文件已被删除
    assert not orphan.exists()
    # 当前照片的缓存文件仍在
    assert os.path.exists(out["album_photos"][0]["path"])


def test_collect_no_prune_when_returns_none(tmp_path, monkeypatch):
    """collect 返回 None(拉取失败)时,不应删除缓存目录中已有的文件。"""
    existing = tmp_path / "old_800x600_v1.png"
    existing.write_bytes(b"last_good")

    monkeypatch.setattr(ia, "fetch_album_photos", lambda url, **k: [])
    monkeypatch.setattr(ia, "_cache_dir", lambda cfg: str(tmp_path))

    cfg = {"album": {"shared_url": "https://www.icloud.com/sharedalbum/#B0X"},
           "server": {"kindle_model": "base"}}
    result = ia.collect(cfg)
    assert result is None
    # 已有缓存文件未被删除
    assert existing.exists()
