"""安卓 App 版后台:target 渲染开关、契约可操作 id、动作接口。
全部离线(mock HA/qB/Transmission),不打真机网络。可直接 `python3 tests/test_android.py`,也兼容 pytest。

红线对应(docs/android-app-spec.md §5):
- target 默认 kindle,现有调用零影响;android 才出控件 + 彩色。
- 契约新增字段只追加(entity_id / id / client),Kindle 模板不读。
- 动作接口只接受白名单操作,不透传任意 service/命令。
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from server.render import styles                       # noqa: E402
from server.render.build_context import prep_context   # noqa: E402
from server.sources import homeassistant as ha         # noqa: E402
from server.sources import downloader as dl            # noqa: E402
from datetime import datetime, timezone, timedelta     # noqa: E402


# ============================================================
# Step 1:模板 target 参数(默认 kindle,android 注入控件)
# ============================================================
def _tmp_style(body):
    """造一个临时风格包,模板回显 target,验证注入。"""
    d = tempfile.mkdtemp()
    sd = os.path.join(d, "probe")
    os.makedirs(sd)
    with open(os.path.join(sd, "home.html"), "w", encoding="utf-8") as f:
        f.write(body)
    return d


def test_target_default_kindle():
    d = _tmp_style("T=[{{ target }}]")
    assert styles.render_page("probe", "home", {"lang": "zh"}, d=d) == "T=[kindle]"


def test_target_android_injected():
    d = _tmp_style("T=[{{ target }}]")
    assert styles.render_page("probe", "home", {"lang": "zh"}, d=d, target="android") == "T=[android]"


def test_target_gates_controls():
    """模板用 {% if target=='android' %} 时:kindle 不出控件、android 出。"""
    d = _tmp_style("{% if target=='android' %}<button>x</button>{% endif %}静态")
    assert styles.render_page("probe", "home", {"lang": "zh"}, d=d) == "静态"            # kindle 无控件
    out = styles.render_page("probe", "home", {"lang": "zh"}, d=d, target="android")
    assert "<button>" in out and out.endswith("静态")                                    # android 有控件


def test_kindle_no_android_leak_all_styles():
    """红线 §5:target=kindle 渲染绝不含任何 android 控件/主题标记(全 7 风格 × 3 交互页)。"""
    raw_dl = {"torrents_raw": [{"name": "A", "id": "H1", "client": "qB", "progress": 50, "dl": 1, "up": 0,
                               "ratio": 0.1, "size": 9, "eta": 0, "state": "downloading"}],
              "dl_speed": 1, "up_speed": 0, "ul_bytes": 0, "dl_bytes": 0, "free": -1,
              "active": 1, "total": 1, "errors": []}
    cache = {"ha": {"cards": [{"name": "灯", "kind": "toggle", "icon": "mdi:lightbulb", "on": True,
                               "state_text": "开", "value": "", "unit": "", "sub": "", "entity_id": "light.x"}]},
             "download": raw_dl,
             "printer": {"online": True, "status": "running", "progress": 40, "task": "t",
                         "layer": "1", "total_layer": "2", "remaining_min": 1.0, "nozzle": "200",
                         "nozzle_t": "200", "bed": "60", "bed_t": "60", "speed": "standard",
                         "weight": "1", "material": "PLA", "cooling_fan": "100", "printer_name": "A1"}}
    ctx = prep_context(datetime.now(timezone(timedelta(hours=8))), cache,
                       {"server": {"language": "zh"}, "printer": {"enabled": True}})
    markers = ("data-action", "data-detail", "data-cmd", "android 触控主题", ".act{", "a-fill", "a-accent")
    for style in styles.list_styles():
        for page in ("ha", "printer", "download"):
            if not styles.has_page(style, page):
                continue
            html = styles.render_page(style, page, ctx)          # 默认 kindle
            hit = [m for m in markers if m in html]
            assert not hit, f"{style}/{page} Kindle 版泄漏 android 标记 {hit}"


def test_kindle_render_unchanged_vs_no_target():
    """回归:target 默认 kindle 与不传 target 逐字一致(Kindle 出图链路零影响)。"""
    ctx = prep_context(datetime.now(timezone(timedelta(hours=8))), {}, {"server": {"language": "zh"}})
    for page in ("home", "ai", "device", "ha", "printer", "news", "download"):
        if not styles.has_page("style_a", page):
            continue
        a = styles.render_page("style_a", page, ctx)
        b = styles.render_page("style_a", page, ctx, target="kindle")
        assert a == b, f"{page}: 默认与 target=kindle 不一致"


# ============================================================
# Step 2:契约追加可操作 id(entity_id / id+client)
# ============================================================
_STATES = [
    {"entity_id": "light.living", "state": "on", "attributes": {"friendly_name": "客厅灯"}},
]
_BY_ID = {s["entity_id"]: s for s in _STATES}


def test_ha_card_carries_entity_id():
    c = ha._build_card(_BY_ID, {"entity_id": "light.living"})
    assert c["entity_id"] == "light.living"


def test_ha_missing_entity_carries_entity_id():
    c = ha._build_card(_BY_ID, {"entity_id": "light.ghost"})
    assert c["entity_id"] == "light.ghost" and c["state_text"] == "未知实体"


def test_qb_norm_has_id():
    n = dl._qb_norm({"name": "X", "hash": "ABC123", "state": "downloading"})
    assert n["id"] == "ABC123"


def test_tr_norm_has_id():
    n = dl._tr_norm({"name": "Y", "id": 7, "status": 4})
    assert n["id"] == 7


def _fake_adapters():
    def qb(c):
        return {"torrents": [{"name": "A", "id": "H1", "progress": 50, "dl": 1, "up": 0,
                              "ratio": 0.0, "size": 9, "eta": 0, "state": "downloading"}],
                "dl_speed": 1, "up_speed": 0, "ul_bytes": 0, "dl_bytes": 0, "free": -1}

    def tr(c):
        return {"torrents": [{"name": "B", "id": 5, "progress": 100, "dl": 0, "up": 1,
                              "ratio": 0.4, "size": 9, "eta": 0, "state": "seeding"}],
                "dl_speed": 0, "up_speed": 1, "ul_bytes": 0, "dl_bytes": 0, "free": -1}
    return {"qbittorrent": qb, "transmission": tr}


def _cfg():
    return {"downloaders": {"clients": [
        {"name": "群晖qB", "type": "qbittorrent", "host": "1.1.1.1", "port": 8080},
        {"name": "TrBox", "type": "transmission", "host": "1.1.1.2", "port": 9091}]}}


def test_collect_tags_client_and_id():
    orig = dl._ADAPTERS
    dl._ADAPTERS = _fake_adapters()
    try:
        out = dl.collect(_cfg())["download"]
    finally:
        dl._ADAPTERS = orig
    by_name = {t["name"]: t for t in out["torrents_raw"]}
    assert by_name["A"]["client"] == "群晖qB" and by_name["A"]["id"] == "H1"
    assert by_name["B"]["client"] == "TrBox" and by_name["B"]["id"] == 5


def test_build_context_propagates_id_client():
    raw = {"torrents_raw": [
        {"name": "A", "id": "H1", "client": "群晖qB", "progress": 50, "dl": 1, "up": 0,
         "ratio": 0.0, "size": 9, "eta": 0, "state": "downloading"}],
        "dl_speed": 1, "up_speed": 0, "ul_bytes": 0, "dl_bytes": 0, "free": -1,
        "active": 1, "total": 1, "errors": []}
    now = datetime.now(timezone(timedelta(hours=8)))
    d = prep_context(now, {"download": raw}, {"server": {"language": "zh"}})["download"]
    assert d["torrents"][0]["id"] == "H1" and d["torrents"][0]["client"] == "群晖qB"


# ============================================================
# Step 3:动作接口(mock HA / qB / Transmission)
# ============================================================
from server import actions   # noqa: E402


class _Resp:
    def __init__(self, status=200, text="", js=None, headers=None):
        self.status_code = status; self.text = text; self._js = js or {}; self.headers = headers or {}
    def json(self): return self._js
    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _capture_ha_client(sink):
    class _C:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, url, headers=None, json=None, **k):
            sink["url"] = url; sink["headers"] = headers or {}; sink["json"] = json or {}
            return _Resp(200)
    return _C


_HA_CFG = {"home_assistant": {"url": "http://ha.local:8123", "token": "TK"}}


def test_ha_action_toggle_maps_generic_service():
    sink = {}
    orig = actions.httpx.Client; actions.httpx.Client = _capture_ha_client(sink)
    try:
        actions.ha_action(_HA_CFG, "light.living", "toggle")
    finally:
        actions.httpx.Client = orig
    assert sink["url"] == "http://ha.local:8123/api/services/homeassistant/toggle"
    assert sink["json"] == {"entity_id": "light.living"}
    assert sink["headers"]["Authorization"] == "Bearer TK"


def test_ha_action_lock_and_cover_specific_service():
    for eid, act, exp in [("lock.front", "on", "lock/lock"),
                          ("lock.front", "off", "lock/unlock"),
                          ("cover.blind", "off", "cover/close_cover"),
                          ("cover.blind", "on", "cover/open_cover")]:
        sink = {}
        orig = actions.httpx.Client; actions.httpx.Client = _capture_ha_client(sink)
        try:
            actions.ha_action(_HA_CFG, eid, act)
        finally:
            actions.httpx.Client = orig
        assert sink["url"].endswith(f"/api/services/{exp}"), f"{eid} {act} → {sink['url']}"


def test_ha_action_rejects_non_whitelist():
    for bad in ("delete", "run_script", "", "service.call"):
        try:
            actions.ha_action(_HA_CFG, "light.x", bad); assert False, f"{bad} 应被拒"
        except ValueError:
            pass


def test_ha_action_rejects_bad_entity_and_unconfigured():
    try:
        actions.ha_action(_HA_CFG, "noentitydot", "toggle"); assert False
    except ValueError:
        pass
    try:
        actions.ha_action({"home_assistant": {}}, "light.x", "toggle"); assert False
    except RuntimeError:
        pass


# 注:打印机控制(printer_action)已于 2026-06-23 移除(HA 拓竹云模式控不了打印机),
# 对应测试一并删除;打印机页改为只读显示。


def test_torrent_action_routes_by_client_name():
    calls = []
    orig = dl._WRITE_ADAPTERS
    dl._WRITE_ADAPTERS = {
        "qbittorrent": lambda c, tid, a: calls.append(("qb", c["name"], tid, a)) or True,
        "transmission": lambda c, tid, a: calls.append(("tr", c["name"], tid, a)) or True,
    }
    try:
        actions.torrent_action(_cfg(), "TrBox", 5, "pause")
        actions.torrent_action(_cfg(), "群晖qB", "H1", "resume")
    finally:
        dl._WRITE_ADAPTERS = orig
    assert ("tr", "TrBox", 5, "pause") in calls
    assert ("qb", "群晖qB", "H1", "resume") in calls


def test_torrent_action_unknown_client_and_bad_action():
    try:
        actions.torrent_action(_cfg(), "不存在", "x", "pause"); assert False
    except RuntimeError:
        pass
    try:
        actions.torrent_action(_cfg(), "TrBox", 5, "delete"); assert False
    except ValueError:
        pass


def test_qb_action_falls_back_on_404():
    """qB 5.0 端点名是 stop/start;若先试的端点 404,自动换另一个(版本兼容)。"""
    seen = []
    class _C:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, url, data=None, **k):
            if "auth/login" in url:
                return _Resp(text="Ok.")
            seen.append(url)
            return _Resp(404) if "torrents/stop" in url else _Resp(200)
    orig = dl.httpx.Client; dl.httpx.Client = _C
    try:
        assert dl.qb_action({"host": "h", "port": 8080}, "HASH", "pause") is True
    finally:
        dl.httpx.Client = orig
    assert any("torrents/stop" in u for u in seen) and any("torrents/pause" in u for u in seen)


def test_tr_action_409_handshake():
    calls = {"n": 0}
    class _C:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, url, json=None, headers=None, **k):
            calls["n"] += 1
            assert json["method"] == "torrent-stop" and json["arguments"]["ids"] == [9]
            if calls["n"] == 1:
                return _Resp(status=409, headers={"X-Transmission-Session-Id": "SID"})
            assert headers.get("X-Transmission-Session-Id") == "SID"
            return _Resp(200)
    orig = dl.httpx.Client; dl.httpx.Client = _C
    try:
        assert dl.tr_action({"host": "h", "port": 9091, "username": "a", "password": "b"}, 9, "pause") is True
    finally:
        dl.httpx.Client = orig
    assert calls["n"] == 2


def test_action_routes_require_token():
    """/api/action/* 绝不豁免鉴权:无令牌一律 401(红线 §3)。"""
    from fastapi.testclient import TestClient
    from server.app import app, cm
    c = TestClient(app)
    cm.get()["server"]["access_token"] = "T0KEN"
    try:
        for path, body in [("/api/action/ha", {"entity_id": "light.x", "action": "toggle"}),
                           ("/api/action/torrent", {"client": "x", "id": "y", "action": "pause"})]:
            assert c.post(path, json=body).status_code == 401, f"{path} 未鉴权!"
        # 带令牌 → 放行进入业务(HA 未配 → 400 ok:false,但已过鉴权)
        r = c.post("/api/action/ha", json={"entity_id": "light.x", "action": "toggle"},
                   headers={"X-Access-Token": "T0KEN"})
        assert r.status_code in (200, 400) and r.status_code != 401
    finally:
        cm.get()["server"]["access_token"] = ""


# ============================================================
# Step 4:活 HTML 路由(/app 外壳 + /app/page/* 单页)
# ============================================================
def test_app_shell_injects_config_and_no_placeholder():
    from fastapi.testclient import TestClient
    from server.app import app
    c = TestClient(app)
    r = c.get("/app")
    assert r.status_code == 200
    assert "__APP_CONFIG__" not in r.text          # 占位符已被替换
    assert '"interval"' in r.text and '"pages"' in r.text and '"texts"' in r.text


def test_app_page_renders_android_html():
    from fastapi.testclient import TestClient
    from server.app import app
    c = TestClient(app)
    r = c.get("/app/page/home")
    assert r.status_code == 200 and "<html" in r.text.lower()
    assert "android 触控主题" in r.text                       # 确实走了 target=android(注入了触控彩色主题)
    assert c.get("/app/page/nonsense").status_code == 404   # 未知页 → 404


def test_app_routes_require_token():
    """/app 与 /app/page/* 绝不豁免鉴权(不是 Kindle 拉图)。"""
    from fastapi.testclient import TestClient
    from server.app import app, cm
    c = TestClient(app)
    cm.get()["server"]["access_token"] = "T0KEN"
    try:
        assert c.get("/app").status_code == 401
        assert c.get("/app/page/home").status_code == 401
        assert c.get("/app?token=T0KEN").status_code == 200            # query 令牌放行
        assert c.get("/app/page/home", headers={"X-Access-Token": "T0KEN"}).status_code == 200
    finally:
        cm.get()["server"]["access_token"] = ""


def test_qrcode_lib_served_and_exempt():
    """二维码库本地内联离线可用;是公共 MIT 库,豁免鉴权(设置页 <script src> 加载)。"""
    from fastapi.testclient import TestClient
    from server.app import app, cm
    c = TestClient(app)
    r = c.get("/qrcode.js")
    assert r.status_code == 200 and "qrcode" in r.text and "MIT" in r.text
    cm.get()["server"]["access_token"] = "T0KEN"
    try:
        assert c.get("/qrcode.js").status_code == 200    # 设了令牌也放行(无密钥,设置页要用)
    finally:
        cm.get()["server"]["access_token"] = ""


def test_app_shell_not_in_auth_exempt():
    """白名单审计:/app* 不在任何豁免列表里(红线 §3)。"""
    from server.app import _AUTH_EXEMPT_PREFIXES, _AUTH_EXEMPT_EXACT
    for p in ("/app", "/app/page/home", "/api/action/ha", "/api/action/torrent"):
        assert p not in _AUTH_EXEMPT_EXACT
        assert not any(p.startswith(x) for x in _AUTH_EXEMPT_PREFIXES), f"{p} 不该被豁免"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  ✓ {fn.__name__}")
    print(f"\n{len(fns)} passed")
