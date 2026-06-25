"""HA 实体 → 卡片映射(spec §5)与降级。用 states fixture,不打网络。
可直接 `python3 tests/test_homeassistant.py`,也兼容 pytest。"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from server.sources import homeassistant as ha  # noqa: E402


# 一份覆盖各 domain / device_class / 降级的 states fixture
STATES = [
    {"entity_id": "light.living", "state": "on",
     "attributes": {"friendly_name": "客厅灯", "icon": "mdi:lightbulb"}},
    {"entity_id": "switch.kettle", "state": "off",
     "attributes": {"friendly_name": "热水壶"}},
    {"entity_id": "sensor.temp", "state": "23.5",
     "attributes": {"friendly_name": "客厅温度", "device_class": "temperature",
                    "unit_of_measurement": "°C"}},
    {"entity_id": "sensor.power", "state": "unavailable",
     "attributes": {"friendly_name": "功率", "device_class": "power",
                    "unit_of_measurement": "W"}},
    {"entity_id": "lock.front", "state": "locked",
     "attributes": {"friendly_name": "前门锁"}},
    {"entity_id": "cover.blind", "state": "open",
     "attributes": {"friendly_name": "窗帘", "current_position": 60}},
    {"entity_id": "binary_sensor.door1", "state": "on",
     "attributes": {"friendly_name": "大门", "device_class": "door"}},
    {"entity_id": "binary_sensor.motion1", "state": "off",
     "attributes": {"friendly_name": "走廊", "device_class": "motion"}},
    {"entity_id": "binary_sensor.leak", "state": "on",
     "attributes": {"friendly_name": "水浸", "device_class": "moisture"}},
    {"entity_id": "climate.ac", "state": "cool",
     "attributes": {"friendly_name": "空调", "current_temperature": 26, "temperature": 24,
                    "hvac_modes": ["off", "cool", "heat", "bogus"]}},
    {"entity_id": "media_player.tv", "state": "playing",
     "attributes": {"friendly_name": "电视", "media_title": "某部名字非常非常长一定会超过十八个字的电影标题"}},
    {"entity_id": "person.me", "state": "home",
     "attributes": {"friendly_name": "我"}},
    {"entity_id": "vacuum.robot", "state": "docked",
     "attributes": {"friendly_name": "扫地机"}},
    # 新增可控 kind(spec ha-page-interaction-spec.md §2)
    {"entity_id": "select.fan", "state": "中",
     "attributes": {"friendly_name": "风扇档位", "options": ["低", "中", "高"]}},
    {"entity_id": "input_select.mode", "state": "day",
     "attributes": {"friendly_name": "模式", "options": ["day", "night"]}},
    {"entity_id": "number.target", "state": "55",
     "attributes": {"friendly_name": "目标湿度", "min": 30, "max": 80, "step": 5,
                    "unit_of_measurement": "%"}},
    {"entity_id": "input_number.vol", "state": "7",
     "attributes": {"friendly_name": "音量", "min": 0, "max": 10, "step": 1}},
    {"entity_id": "button.bell", "state": "2026-06-23T10:00:00+00:00",
     "attributes": {"friendly_name": "门铃"}},
    {"entity_id": "input_button.ping", "state": "unknown",
     "attributes": {"friendly_name": "Ping"}},
    {"entity_id": "scene.movie", "state": "2026-06-23T09:00:00+00:00",
     "attributes": {"friendly_name": "观影"}},
    {"entity_id": "alarm_control_panel.home", "state": "armed_home",
     "attributes": {"friendly_name": "安防"}},
]
BY_ID = {s["entity_id"]: s for s in STATES}


def card(eid, **ent):
    ent["entity_id"] = eid
    return ha._build_card(BY_ID, ent)


def test_toggle():
    c = card("light.living")
    assert c["kind"] == "toggle" and c["on"] is True and c["state_text"] == "开"
    assert c["icon"] == "mdi:lightbulb"          # 透传 HA 自带 icon
    c2 = card("switch.kettle")
    assert c2["on"] is False and c2["state_text"] == "关"
    assert c2["icon"] == "mdi:power-socket"       # 无自带 → domain 默认


def test_sensor_and_unit():
    c = card("sensor.temp")
    assert c["kind"] == "sensor" and c["value"] == "23.5" and c["unit"] == "°C"
    assert c["on"] is False
    assert c["icon"] == "mdi:thermometer"         # device_class 细分图标


def test_sensor_unavailable_keeps_unit():
    c = card("sensor.power")
    assert c["value"] == "--" and c["unit"] == "W" and c["on"] is False


def test_lock():
    c = card("lock.front")
    assert c["kind"] == "lock" and c["on"] is True and c["state_text"] == "已锁"


def test_cover_position():
    c = card("cover.blind")
    assert c["kind"] == "cover" and c["on"] is True and c["state_text"] == "60%"


def test_binary_classes():
    assert card("binary_sensor.door1")["state_text"] == "开"
    assert card("binary_sensor.motion1")["state_text"] == "无人"
    assert card("binary_sensor.leak")["state_text"] == "漏水"
    assert card("binary_sensor.leak")["on"] is True


def test_climate():
    c = card("climate.ac")
    assert c["kind"] == "climate" and c["on"] is True
    assert c["state_text"] == "制冷" and c["value"] == "26" and c["sub"] == "目标 24°"


def test_media_truncates_title():
    c = card("media_player.tv")
    assert c["kind"] == "media" and c["on"] is True and c["state_text"] == "播放中"
    assert c["sub"].endswith("…") and len(c["sub"]) <= 18


def test_presence():
    c = card("person.me")
    assert c["kind"] == "presence" and c["on"] is True and c["state_text"] == "在家"


def test_unknown_domain_falls_back_to_text():
    c = card("vacuum.robot")
    assert c["kind"] == "text" and c["state_text"] == "docked"   # 兜底:原文,不报错


def test_missing_entity():
    c = card("light.ghost", name="幽灵")
    assert c["state_text"] == "未知实体" and c["kind"] == "text" and c["name"] == "幽灵"


def test_name_and_icon_override():
    c = card("light.living", name="主灯", icon="mdi:ceiling-light")
    assert c["name"] == "主灯" and c["icon"] == "mdi:ceiling-light"


def test_list_entities_filter_and_truncate():
    big = [{"entity_id": f"light.l{i}", "state": "on",
            "attributes": {"friendly_name": f"灯{i}"}} for i in range(60)]
    big.append({"entity_id": "sensor.s1", "state": "1",
                "attributes": {"friendly_name": "传感"}})
    import server.sources.homeassistant as mod
    orig = mod._fetch_states
    mod._fetch_states = lambda url, token: big
    try:
        r = mod.list_entities("http://x", "t", domain="light")
        assert all(e["domain"] == "light" for e in r["entities"])
        assert len(r["entities"]) == 50 and r["truncated"] is True
        r2 = mod.list_entities("http://x", "t", q="传感")
        assert len(r2["entities"]) == 1 and r2["entities"][0]["entity_id"] == "sensor.s1"
    finally:
        mod._fetch_states = orig


def test_printer_prefix_autodetects_unique_short_prefix():
    states = [
        {"entity_id": "binary_sensor.a1_123_online", "state": "on", "attributes": {}},
        {"entity_id": "sensor.a1_123_print_progress", "state": "42", "attributes": {}},
        {"entity_id": "sensor.a1_123_print_status", "state": "running", "attributes": {}},
        {"entity_id": "sensor.a1_123_remaining_time", "state": "1.5", "attributes": {}},
        {"entity_id": "sensor.a1_123_nozzle_temperature", "state": "210", "attributes": {}},
        {"entity_id": "sensor.a1_123_bed_temperature", "state": "60", "attributes": {}},
        {"entity_id": "sensor.a1_123_printer_name", "state": "A1-01", "attributes": {}},
    ]
    pr = ha._build_printer(states, "a1_")
    assert pr["online"] is True
    assert pr["status"] == "running"
    assert pr["progress"] == 42
    assert pr["remaining_min"] == 1.5
    assert pr["nozzle"] == "210" and pr["bed"] == "60"
    assert pr["printer_name"] == "A1-01"


def test_printer_prefix_keeps_ambiguous_short_prefix():
    states = [
        {"entity_id": "sensor.a1_111_print_progress", "state": "10", "attributes": {}},
        {"entity_id": "sensor.a1_222_print_progress", "state": "20", "attributes": {}},
    ]
    assert ha._resolve_printer_prefix(states, "a1_") == "a1_"


def test_list_printers(monkeypatch=None):
    states = [
        {"entity_id": "binary_sensor.a1_123_online", "state": "on",
         "attributes": {"friendly_name": "A1_123 在线"}},
        {"entity_id": "sensor.a1_123_print_progress", "state": "42", "attributes": {}},
        {"entity_id": "sensor.a1_123_print_status", "state": "running", "attributes": {}},
        {"entity_id": "sensor.a1_123_nozzle_temperature", "state": "210", "attributes": {}},
        {"entity_id": "sensor.a1_123_bed_temperature", "state": "60", "attributes": {}},
        {"entity_id": "sensor.a1_123_printer_name", "state": "A1-01", "attributes": {}},
    ]
    import server.sources.homeassistant as mod
    orig = mod._fetch_states
    mod._fetch_states = lambda url, token: states
    try:
        printers = mod.list_printers("http://x", "t")["printers"]
        assert printers == [{
            "prefix": "a1_123", "name": "A1-01", "online": True,
            "status": "running", "stage": "", "progress": 42,
            "nozzle": "210", "bed": "60",
        }]
    finally:
        mod._fetch_states = orig


# ============================================================
# 新可控 kind 分类 + 面板元数据(spec ha-page-interaction-spec.md §2/§3)
# ============================================================
def test_select_classification():
    c = card("select.fan")
    assert c["kind"] == "select" and c["state_text"] == "中"
    assert c["value"] == "" and c["on"] is False        # 不改 Kindle 主次
    assert c["meta"] == {"options": ["低", "中", "高"], "current": "中"}
    assert card("input_select.mode")["kind"] == "select"


def test_number_classification():
    c = card("number.target")
    assert c["kind"] == "number" and c["state_text"] == "55" and c["value"] == ""
    m = c["meta"]
    assert m["min"] == 30 and m["max"] == 80 and m["step"] == 5
    assert m["unit"] == "%" and m["value"] == 55.0
    assert card("input_number.vol")["kind"] == "number"


def test_button_and_scene_classification():
    assert card("button.bell")["kind"] == "button"
    assert card("input_button.ping")["kind"] == "button"
    assert card("scene.movie")["kind"] == "scene"
    # 一次性动作(A 类单击直发)不带面板 meta
    assert "meta" not in card("button.bell")
    assert "meta" not in card("scene.movie")


def test_alarm_classification():
    c = card("alarm_control_panel.home")
    assert c["kind"] == "alarm" and c["on"] is False     # 不给 Kindle 加重音边框
    assert c["state_text"] == "armed_home" and c["meta"] == {"state": "armed_home"}


def test_panel_meta_for_cover_climate_media():
    assert card("cover.blind")["meta"] == {"on": True, "position": 60}
    cm = card("climate.ac")["meta"]
    assert cm["on"] is True and cm["mode"] == "cool"
    assert cm["current"] == 26.0 and cm["target"] == 24.0
    assert cm["modes"] == ["off", "cool", "heat"]        # bogus 被过滤
    assert card("media_player.tv")["meta"]["title"].startswith("某部")


def _render_kindle(style, sd, card_obj):
    from server.render import styles, contract
    ctx = contract.empty_context(); ctx["lang"] = "zh"; ctx["ha"] = {"cards": [card_obj]}
    return styles.render_page(style, "ha", ctx, d=sd, target="kindle")


def test_kindle_render_byte_identical_for_new_kinds():
    """🔴 命根子:Kindle(target=kindle)出的 HTML 逐字节不受本次改动影响。
    ① 追加的 meta 字段绝不进 Kindle;② 新 kind 分类后,Kindle 渲染与「当成 text 卡」逐字节一致。"""
    import copy
    from server.render import styles
    sd = os.path.join(ROOT, "styles")
    new_kinds = {"select.fan", "number.target", "button.bell", "scene.movie", "alarm_control_panel.home"}
    for eid in new_kinds | {"cover.blind", "climate.ac", "media_player.tv"}:
        c = card(eid)
        no_meta = copy.deepcopy(c); no_meta.pop("meta", None)
        as_text = copy.deepcopy(no_meta); as_text["kind"] = "text"
        for style in styles.list_styles(sd):
            real = _render_kindle(style, sd, c)
            assert real == _render_kindle(style, sd, no_meta), f"{style}/{eid}: meta 泄漏进 Kindle!"
            if eid in new_kinds:   # 新 kind:必须与旧「兜底 text 卡」渲染逐字节相同
                assert real == _render_kindle(style, sd, as_text), \
                    f"{style}/{eid}: 新 kind 改变了 Kindle 渲染!"


def test_android_routes_kinds_to_three_tiers():
    """android 出口:A 类 data-action 直发、B 类 data-panel 弹面板、C 类 data-detail;Kindle 零泄漏。"""
    from server.render import styles, contract
    sd = os.path.join(ROOT, "styles")
    cards = [card(e) for e in ("light.living", "scene.movie", "button.bell", "lock.front",
                               "cover.blind", "climate.ac", "media_player.tv", "select.fan",
                               "number.target", "alarm_control_panel.home", "sensor.temp")]
    ctx = contract.empty_context(); ctx["lang"] = "zh"; ctx["ha"] = {"cards": cards}
    h = styles.render_page("style_a", "ha", ctx, d=sd, target="android")
    # A 类直发
    assert 'data-entity="scene.movie" data-cmd="activate"' in h
    assert 'data-entity="button.bell" data-cmd="press"' in h
    assert 'data-entity="light.living" data-cmd="toggle"' in h
    assert 'data-entity="lock.front" data-cmd="off"' in h    # 已锁 → 单击解锁
    # B 类弹面板
    for k in ("cover", "climate", "media", "select", "number", "alarm"):
        assert f'data-panel="{k}"' in h, f"缺 data-panel={k}"
    assert '"options": ["低", "中", "高"]' in h or '&#34;options&#34;' in h or "options" in h
    # C 类只读详情(传感器)
    assert 'data-detail="客厅温度"' in h
    # Kindle 零泄漏
    hk = styles.render_page("style_a", "ha", ctx, d=sd, target="kindle")
    assert "data-panel" not in hk and "data-action" not in hk and "data-detail" not in hk


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  ✓ {fn.__name__}")
    print(f"\n{len(fns)} passed")
