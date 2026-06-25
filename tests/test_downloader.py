"""下载器采集器验证。可直接 `python3 tests/test_downloader.py` 跑,也兼容 pytest。
鉴权/字段均按真机(192.168.1.100 qB 8085 / Transmission 9091)实测响应构造 mock。"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from server.sources import downloader as dl  # noqa: E402
from server.render.build_context import prep_context  # noqa: E402
from datetime import datetime, timezone, timedelta  # noqa: E402


# ---------- 归一化 + 状态映射 ----------
def test_qb_norm_states():
    assert dl._qb_norm({"state": "downloading", "progress": 0.22, "dlspeed": 100, "ratio": 0})["state"] == "downloading"
    assert dl._qb_norm({"state": "stalledUP"})["state"] == "seeding"     # 空闲做种归 seeding
    assert dl._qb_norm({"state": "stalledDL"})["state"] == "stalled"
    assert dl._qb_norm({"state": "pausedUP"})["state"] == "paused"
    assert dl._qb_norm({"state": "missingFiles"})["state"] == "error"
    assert dl._qb_norm({"state": "什么鬼"})["state"] == "other"
    n = dl._qb_norm({"name": "X", "progress": 0.225, "dlspeed": 30000000, "upspeed": 0, "ratio": 1.5, "size": 9, "eta": 600})
    assert n["progress"] == 22 or n["progress"] == 23   # round(22.5)
    assert n["dl"] == 30000000 and n["ratio"] == 1.5


def test_tr_norm_states():
    assert dl._tr_norm({"status": 4})["state"] == "downloading"
    assert dl._tr_norm({"status": 6})["state"] == "seeding"
    assert dl._tr_norm({"status": 0})["state"] == "paused"
    assert dl._tr_norm({"status": 2})["state"] == "checking"
    assert dl._tr_norm({"status": 3})["state"] == "queued"
    assert dl._tr_norm({"status": 99})["state"] == "other"
    n = dl._tr_norm({"name": "Y", "percentDone": 1.0, "rateUpload": 500, "uploadRatio": -1, "totalSize": 8, "eta": -1})
    assert n["progress"] == 100 and n["up"] == 500
    assert n["ratio"] == 0.0          # tr 的 -1 分享率夹到 0


# ---------- 合并 + 排序 + 全局(monkeypatch adapter)----------
def _fake_adapters():
    def qb(c):
        return {"torrents": [
            {"name": "Titanic", "progress": 22, "dl": 30_000_000, "up": 0, "ratio": 0.0, "size": 9, "eta": 600, "state": "downloading"},
            {"name": "qb-seed", "progress": 100, "dl": 0, "up": 1000, "ratio": 2.0, "size": 9, "eta": 0, "state": "seeding"},
        ], "dl_speed": 30_000_000, "up_speed": 1000, "ul_bytes": 400_000_000, "dl_bytes": 13_000_000_000, "free": -1}

    def tr(c):
        return {"torrents": [
            {"name": "tr-dl", "progress": 99, "dl": 5_000_000, "up": 0, "ratio": 0.0, "size": 9, "eta": 60, "state": "downloading"},
            {"name": "tr-seed-fast", "progress": 100, "dl": 0, "up": 9000, "ratio": 0.4, "size": 9, "eta": 0, "state": "seeding"},
            {"name": "tr-paused", "progress": 100, "dl": 0, "up": 0, "ratio": 0.1, "size": 9, "eta": 0, "state": "paused"},
        ], "dl_speed": 5_000_000, "up_speed": 9000, "ul_bytes": 118_000_000_000, "dl_bytes": 892_000_000_000, "free": 1_000_000}
    return {"qbittorrent": qb, "transmission": tr}


def _cfg(rows=8):
    return {"downloaders": {"rows": rows, "clients": [
        {"name": "qB", "type": "qbittorrent", "host": "1.1.1.1", "port": 8080},
        {"name": "Tr", "type": "transmission", "host": "1.1.1.2", "port": 9091}]}}


def test_collect_merge_sort_global():
    orig = dl._ADAPTERS
    dl._ADAPTERS = _fake_adapters()
    try:
        out = dl.collect(_cfg())["download"]
    finally:
        dl._ADAPTERS = orig
    assert out["total"] == 5
    assert out["active"] == 4                 # 2 下载 + 2 做种(paused 不算活跃)
    # 全局累加
    assert out["dl_speed"] == 35_000_000 and out["up_speed"] == 10000
    assert out["ul_bytes"] == 118_400_000_000 and out["dl_bytes"] == 905_000_000_000
    assert out["free"] == 1_000_000           # 取第一个有效剩余空间(qB 是 -1,用 Tr 的)
    names = [t["name"] for t in out["torrents_raw"]]
    # 活跃优先:两条下载在最前;做种按上传速度(tr-seed-fast 9000 > qb-seed 1000);paused 垫底
    assert names[0] in ("Titanic", "tr-dl") and names[1] in ("Titanic", "tr-dl")
    assert names.index("tr-seed-fast") < names.index("qb-seed")
    assert names[-1] == "tr-paused"


def test_collect_rows_truncate():
    orig = dl._ADAPTERS
    dl._ADAPTERS = _fake_adapters()
    try:
        out = dl.collect(_cfg(rows=2))["download"]
    finally:
        dl._ADAPTERS = orig
    assert len(out["torrents_raw"]) == 2        # 截断
    assert out["total"] == 5                     # 但 total 仍是全部


def test_collect_no_clients_none():
    assert dl.collect({}) is None
    assert dl.collect({"downloaders": {"clients": []}}) is None
    assert dl.collect({"downloaders": {"clients": [{"name": "x", "host": ""}]}}) is None   # host 空跳过


def test_collect_partial_error_keeps_others():
    def boom(c):
        raise RuntimeError("connect refused")
    orig = dl._ADAPTERS
    dl._ADAPTERS = {"qbittorrent": _fake_adapters()["qbittorrent"], "transmission": boom}
    try:
        out = dl.collect(_cfg())["download"]
    finally:
        dl._ADAPTERS = orig
    assert out["errors"] == ["Tr"]              # Transmission 进 errors
    assert out["total"] == 2                     # 只剩 qB 的两条


def test_collect_all_error_none():
    def boom(c):
        raise RuntimeError("down")
    orig = dl._ADAPTERS
    dl._ADAPTERS = {"qbittorrent": boom, "transmission": boom}
    try:
        assert dl.collect(_cfg()) is None        # 全部连不上 → 保留上一帧
    finally:
        dl._ADAPTERS = orig


# ---------- httpx 鉴权握手(mock)----------
class _Resp:
    def __init__(self, status=200, text="", js=None, headers=None):
        self.status_code = status; self.text = text; self._js = js or {}; self.headers = headers or {}
    def json(self): return self._js


def test_qb_fetch_login_and_referer():
    seen = {}
    class _Client:
        def __init__(self, *a, **k): seen["headers"] = k.get("headers", {}); seen["base"] = k.get("base_url")
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, url, data=None, **k):
            seen["login"] = data; return _Resp(text="Ok.")
        def get(self, url, params=None, **k):
            if "torrents/info" in url:
                return _Resp(js=[{"name": "T", "progress": 0.5, "dlspeed": 100, "state": "downloading", "ratio": 1.0}])
            return _Resp(js={"server_state": {"dl_info_speed": 100, "alltime_ul": 5, "alltime_dl": 10, "free_space_on_disk": -1}})
    orig = dl.httpx.Client
    dl.httpx.Client = _Client
    try:
        d = dl._qb_fetch({"host": "1.2.3.4", "port": 8080, "username": "admin", "password": "p"})
    finally:
        dl.httpx.Client = orig
    assert seen["headers"]["Referer"] == "http://1.2.3.4:8080"   # 必须带 Referer
    assert d["torrents"][0]["state"] == "downloading"
    assert d["free"] == -1                                       # -1 当未知


def test_qb_fetch_login_fail_raises():
    class _Client:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, *a, **k): return _Resp(status=403, text="Fails.")
        def get(self, *a, **k): return _Resp(js={})
    orig = dl.httpx.Client
    dl.httpx.Client = _Client
    try:
        raised = False
        try:
            dl._qb_fetch({"host": "x", "port": 8080})
        except RuntimeError:
            raised = True
        assert raised
    finally:
        dl.httpx.Client = orig


def test_tr_fetch_409_handshake():
    calls = {"n": 0}
    class _Client:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, url, json=None, headers=None, **k):
            calls["n"] += 1
            if calls["n"] == 1:                        # 首请求:409 + session id
                assert not headers                     # 还没带 sid
                return _Resp(status=409, headers={"X-Transmission-Session-Id": "SID123"})
            assert headers.get("X-Transmission-Session-Id") == "SID123"   # 重试带上
            if json["method"] == "session-stats":
                return _Resp(js={"arguments": {"downloadSpeed": 7, "uploadSpeed": 8,
                                               "cumulative-stats": {"uploadedBytes": 100, "downloadedBytes": 200}}})
            return _Resp(js={"arguments": {"torrents": [{"name": "Z", "percentDone": 1.0, "status": 6, "uploadRatio": 0.5}]}})
    orig = dl.httpx.Client
    dl.httpx.Client = _Client
    try:
        d = dl._tr_fetch({"host": "x", "port": 9091, "username": "admin", "password": "p"})
    finally:
        dl.httpx.Client = orig
    assert d["dl_speed"] == 7 and d["ul_bytes"] == 100
    assert d["torrents"][0]["state"] == "seeding"


# ---------- build_context 格式化 + 本地化 ----------
def _ctx(lang="zh", raw=None):
    now = datetime.now(timezone(timedelta(hours=8)))
    cache = {"download": raw} if raw else {}
    return prep_context(now, cache, {"server": {"language": lang}})["download"]


def test_build_context_formats_and_localizes():
    raw = {"torrents_raw": [
        {"name": "A", "progress": 22, "dl": 30_000_000, "up": 0, "ratio": 0.0, "size": 9, "eta": 600, "state": "downloading"},
        {"name": "B", "progress": 100, "dl": 0, "up": 9000, "ratio": 0.43, "size": 9, "eta": 8640000, "state": "seeding"}],
        "dl_speed": 30_000_000, "up_speed": 9000, "ul_bytes": 118_000_000_000, "dl_bytes": 905_000_000_000,
        "free": -1, "active": 2, "total": 15, "errors": []}
    d = _ctx("zh", raw)
    assert d["ok"] and d["total"] == 15
    assert "MB/s" in d["dl_speed"]
    assert d["ratio"] == "0.13"                  # 118/905
    assert d["uploaded"].endswith("G")
    assert d["free"] == ""                        # -1 → 不显示
    assert d["torrents"][0]["state_text"] == "下载中"
    assert d["torrents"][0]["eta"] == "10分"      # 600s
    assert d["torrents"][1]["eta"] == "—"         # 8640000 = ∞
    en = _ctx("en", raw)
    assert en["torrents"][0]["state_text"] == "Downloading"


def test_build_context_empty():
    d = _ctx("zh", None)                          # 无下载数据 → 降级空
    assert d["ok"] is False and d["torrents"] == [] and d["total"] == 0


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  ✓ {fn.__name__}")
    print(f"\n{len(fns)} passed")
