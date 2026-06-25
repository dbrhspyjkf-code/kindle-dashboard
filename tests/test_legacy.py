"""安卓老系统兼容 —— 服务端 legacy 出口验证(施工图 docs/android-legacy-support-spec.md §2)。
覆盖:三档 UA 自动分流(/app)、?force= 覆盖、token 透传、/app-legacy 图片相框出口、
旧 /app-legacy-live 活页壳保留、legacy 模板渲染与降级、legacy 不入风格选择器。
用临时 config,不起服务、不触发采集/渲染线程。"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
TEST_DATA_DIR = tempfile.mkdtemp()
os.environ["KINDLE_CONFIG"] = os.path.join(TEST_DATA_DIR, "config.yaml")
os.environ["KINDLE_DATA_DIR"] = TEST_DATA_DIR

from fastapi.testclient import TestClient        # noqa: E402
from server.app import app, cm, _classify_ua     # noqa: E402
from server.render import styles, contract       # noqa: E402

client = TestClient(app)

# 真机校准锚点(附录B):安卓4.2→legacy、Kindle 自带浏览器→simple、现代→app。
UA_MODERN = "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Mobile Safari/537.36"
UA_OLD_ANDROID = "Mozilla/5.0 (Linux; U; Android 4.2.2; zh-cn; GT-N7100 Build/JDQ39) AppleWebKit/534.30 (KHTML, like Gecko) Version/4.0 Mobile Safari/534.30"
UA_KINDLE = "Mozilla/5.0 (X11; U; Linux armv7l like Android; en-us) AppleWebKit/531.2+ (KHTML, like Gecko) Version/5.0 Safari/533.2+ Kindle/3.0"
UA_DESKTOP = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"


# ---------- UA 三档判据 ----------
def test_classify_ua_three_tiers():
    assert _classify_ua(UA_MODERN) == "app"
    assert _classify_ua(UA_DESKTOP) == "app"
    assert _classify_ua(UA_OLD_ANDROID) == "legacy"   # 安卓 4.2 必落 legacy
    assert _classify_ua(UA_KINDLE) == "simple"        # Kindle 自带浏览器必落 simple
    assert _classify_ua("") == "app"                  # 空 UA 默认现代,不误降级


def test_classify_modern_android_not_misrouted():
    """现代安卓不能被老安卓正则误判。
    重点:现代 Android WebView UA 常带 `Version/4.0`,不能因为这个降到 legacy。"""
    for v in ("10", "11", "12", "13", "14", "15"):
        ua = f"Mozilla/5.0 (Linux; Android {v}; X) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/120 Mobile Safari/537.36"
        assert _classify_ua(ua) == "app", v


# ---------- /app 自动分流(默认 TestClient 不跟随重定向便于断言 Location)----------
def test_app_redirects_old_android_to_legacy():
    r = client.get("/app", headers={"user-agent": UA_OLD_ANDROID}, follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/app-legacy"


def test_app_redirects_kindle_to_web_simple():
    r = client.get("/app", headers={"user-agent": UA_KINDLE}, follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/web-simple"


def test_app_modern_not_redirected():
    r = client.get("/app", headers={"user-agent": UA_MODERN}, follow_redirects=False)
    assert r.status_code == 200          # 现代:原样给 /app 外壳,不跳


def test_app_force_override_and_token_passthrough():
    # ?force= 覆盖 UA 自动判断(误判时手动指定)
    r = client.get("/app?force=legacy", headers={"user-agent": UA_MODERN}, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/app-legacy"
    r = client.get("/app?force=simple", headers={"user-agent": UA_MODERN}, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/web-simple"
    r = client.get("/app?force=app", headers={"user-agent": UA_OLD_ANDROID}, follow_redirects=False)
    assert r.status_code == 200          # force=app 让老安卓也看现代版(调试用)
    # token 透传到重定向目标
    r = client.get("/app?token=abc%20x", headers={"user-agent": UA_OLD_ANDROID}, follow_redirects=False)
    assert r.headers["location"] == "/app-legacy?token=abc%20x"


# ---------- /app-legacy 外壳 ----------
def test_app_legacy_shell_served():
    r = client.get("/app-legacy")
    assert r.status_code == 200
    assert "__APP_CONFIG__" not in r.text       # 配置已注入
    assert "/app-legacy/frame.png" in r.text    # 默认走图片相框,老 WebView 只显示服务端 PNG
    assert "/app-legacy/page/" not in r.text    # 不再让 4.2 WebView 承载业务布局
    assert "background-size:contain" in r.text   # 图当背景图贴(无独立 <img> 元素边缘缝)
    assert "backgroundImage" in r.text           # JS 轮询换的是容器背景图
    # 纯 ES5:不得含现代语法(箭头/const/fetch/模板串)
    for modern in ("=>", "const ", "let ", "fetch(", "`"):
        assert modern not in r.text, modern


def test_app_legacy_live_shell_is_kept_for_debugging():
    r = client.get("/app-legacy-live")
    assert r.status_code == 200
    assert "__APP_CONFIG__" not in r.text
    assert "XMLHttpRequest" in r.text
    assert "/app-legacy/page/" in r.text
    assert "Legacy live HTML shell kept for reference and rollback" in r.text


def test_app_legacy_shell_requires_token():
    cm.get()["server"]["access_token"] = "T0KEN"
    try:
        assert client.get("/app-legacy").status_code == 401          # 绝不豁免
        assert client.get("/app-legacy?token=T0KEN").status_code == 200
        assert client.get("/app-legacy-live").status_code == 401
        assert client.get("/app-legacy-live?token=T0KEN").status_code == 200
        assert client.get("/app-legacy/frame.png").status_code == 401
        assert client.get("/app-legacy/frame.png?token=T0KEN").status_code == 200
        assert client.get("/app-legacy/page/home").status_code == 401
        assert client.get("/app-legacy/page/home?token=T0KEN").status_code == 200
    finally:
        cm.get()["server"]["access_token"] = ""


# ---------- /app-legacy/page/<key> 单页片段 ----------
def test_app_legacy_page_renders_and_degrades():
    for key in ("home", "ai", "device", "ha", "news", "download", "printer"):
        r = client.get(f"/app-legacy/page/{key}")
        assert r.status_code == 200, key
        assert "render error" not in r.text, key
        # legacy 片段不得泄漏现代 android 触控主题/控件标记
        for bad in ("data-action", "data-panel", "data-meta", "ANDROID_THEME"):
            assert bad not in r.text, f"{key}:{bad}"


def test_app_legacy_page_unknown_404():
    assert client.get("/app-legacy/page/nope").status_code == 404


def _legacy_ctx():
    ctx = contract.empty_context()
    ctx["lang"] = "zh"
    return ctx


def _ha_card(i):
    return {
        "name": f"实体{i}",
        "icon": "mdi:lightbulb",
        "kind": "toggle",
        "on": i % 2 == 0,
        "value": "开" if i % 2 == 0 else "关",
        "unit": "",
        "state_text": "开" if i % 2 == 0 else "关",
        "sub": "",
    }


def test_legacy_ha_grid_reflows_for_sparse_counts():
    cases = {
        1: ("width:420px;height:270px;margin-left:250px;margin-top:100px", "width:420px;height:270px"),
        3: ("width:918px;height:270px;margin-left:1px;margin-top:100px", "width:306px;height:270px"),
        5: ("width:918px;height:460px;margin-left:1px;margin-top:5px", "padding-left:153px"),
        9: ("width:918px;height:468px;margin-left:1px;margin-top:1px", "width:306px;height:156px"),
    }
    for n, (grid_style, marker) in cases.items():
        ctx = _legacy_ctx()
        ctx["ha"] = {"cards": [_ha_card(i) for i in range(n)]}
        html = styles.render_page("legacy", "ha", ctx, target="legacy")
        assert grid_style in html, n
        assert marker in html, n


def _machine(i):
    return {
        "name": f"设备{i}",
        "mem_used": "1G",
        "mem_total": "4G",
        "cpu": 12,
        "mem": 25,
        "net_rx": "0",
        "net_tx": "0",
        "disk_r": "0",
        "disk_w": "0",
        "show": {"cpu": True, "mem": True, "net": False, "disk_io": False},
        "vols": [],
    }


def test_legacy_device_grid_centers_single_and_odd_last_row():
    ctx = _legacy_ctx()
    ctx["device"] = {"machines": [_machine(1)]}
    html = styles.render_page("legacy", "device", ctx, target="legacy")
    assert "width:560px;height:320px;margin-left:180px;margin-top:75px" in html
    assert "width:560px;height:320px" in html

    ctx = _legacy_ctx()
    ctx["device"] = {"machines": [_machine(i) for i in range(3)]}
    html = styles.render_page("legacy", "device", ctx, target="legacy")
    assert "width:920px;height:470px;margin-left:0px;margin-top:0px" in html
    assert "padding-left:230px" in html


def test_legacy_printer_empty_state_has_dedicated_position():
    ctx = _legacy_ctx()
    ctx["printer"] = {"name": "A1", "online": True, "printing": False, "state_text": "打印完成", "nozzle": 30, "bed": 31}
    html = styles.render_page("legacy", "printer", ctx, target="legacy")
    assert "printer-empty" in html
    assert "printer-temp-line" in html
    assert "margin-top:18px" not in html


def test_app_legacy_shell_prioritizes_printer_empty_offset():
    r = client.get("/app-legacy-live")
    assert r.status_code == 200
    assert ".empty-box.printer-empty{padding-top:118px;}" in r.text


def test_app_legacy_live_uses_warm_reference_palette_not_dark_theme():
    """legacy 真机主题走 panel-legacy 同款暖浅色,避免再回退成纯黑省电版。"""
    shell = client.get("/app-legacy-live").text.lower()
    assert "#ece8de" in shell
    assert "#f5f1e8" in shell
    assert "#151515" in shell
    for pure in ("#000", "#fff", "#ffffff"):
        assert pure not in shell, pure

    ctx = _legacy_ctx()
    ctx["printer"] = {"name": "A1", "online": True, "printing": True, "progress": 42, "task": "cube", "state_text": "打印中", "layer": 1, "total_layer": 2, "remaining_text": "1h", "eta_clock": "--", "nozzle": 200, "nozzle_t": 220, "bed": 60, "bed_t": 60, "speed": "100%", "material": "PLA", "weight": 12, "cooling_fan": 80}
    printer_html = styles.render_page("legacy", "printer", ctx, target="legacy").lower()
    for pure in ("#000", "#fff", "#ffffff"):
        assert pure not in printer_html, pure


def test_app_legacy_no_store_cache_header():
    """外壳含 <style>(legacy 主题 CSS),老 WebView 会缓存住旧外壳 → 改样式设备不更新。
    /app-legacy 与片段都必须 Cache-Control: no-store(真机踩过:暗色重设计上线后仍显示旧浅色版)。"""
    assert client.get("/app-legacy").headers.get("cache-control") == "no-store"
    assert client.get("/app-legacy-live").headers.get("cache-control") == "no-store"
    assert client.get("/app-legacy/frame.png").headers.get("cache-control") == "no-store"
    assert client.get("/app-legacy/page/home").headers.get("cache-control") == "no-store"


# ---------- legacy 是内部模板集:不进风格选择器 ----------
def test_legacy_not_in_style_picker():
    assert "legacy" not in styles.list_styles()
    # 但能被 has_page / render_page 直接按名调用
    assert styles.has_page("legacy", "home")
    html = styles.render_page("legacy", "home", contract.empty_context(), target="legacy")
    assert html and "render error" not in html
