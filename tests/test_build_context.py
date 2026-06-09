"""数据整合层验证:mock cache → prep_context → 符合数据契约。"""
import os
import sys
import time
from datetime import date, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from server.render import build_context as bc          # noqa: E402
from server.render.contract import empty_context        # noqa: E402

NOW = datetime(2026, 6, 7, 14, 30, 5)


def _mock_cache():
    soon = time.time() + 3600
    return {
        "weather_now": {"temp": "24", "text": "多云", "feelsLike": "26",
                        "humidity": "65", "windDir": "西北风", "windScale": "3"},
        "weather_daily": [{"tempMin": "18", "tempMax": "26", "textDay": "多云"},
                          {"tempMin": "19", "tempMax": "27", "textDay": "晴"}],
        "reminders": [
            {"title": "交资料", "dueDate": "2026-06-01", "completed": False},
            {"title": "今天开会", "dueDate": "2026-06-07", "completed": False},
            {"title": "明天体检", "dueDate": "2026-06-08", "completed": False},
            {"title": "已完成的", "dueDate": "2026-06-07", "completed": True},
        ],
        "ccusage": {"ok": True,
                    "cc": {"daily": [{"date": "2026-06-07", "totalTokens": 1_200_000, "totalCost": 8.1}]},
                    "codex": {"daily": [{"date": "2026-06-07", "totalTokens": 600_000, "costUSD": 4.2}]}},
        "rate_limits": {"five_hour": {"used_percentage": 42, "resets_at": soon},
                        "seven_day": {"used_percentage": 30, "resets_at": soon}},
        "codex_rate_limits": {"five_hour": {"used_percentage": 15, "resets_at": soon},
                              "seven_day": {"used_percentage": 10, "resets_at": soon}},
        "devices_metrics": {"nas-01": {"hostname": "nas-01",
                       "cpu_pct": 23, "mem_used": 8 * 1024**3, "mem_total": 16 * 1024**3,
                       "net_rx": 1_200_000, "net_tx": 300_000,
                       "disk_read": 0, "disk_write": 500_000,
                       "disks": [{"name": "vol1", "pct": 61, "used": 600 * 1024**3, "total": 1024**4}]}},
        "printer": {"online": True, "status": "running", "progress": 47,
                    "task": "benchy.3mf", "layer": "120", "total_layer": "256",
                    "remaining_min": 2.25, "nozzle": "210", "nozzle_t": "210",
                    "bed": "60", "bed_t": "60", "speed": "standard",
                    "weight": "15", "material": "PLA", "cooling_fan": "100",
                    "printer_name": "A1"},
        "kindle_battery": 87, "kindle_charging": False,
    }


def test_full_cache_matches_contract_shape():
    """有数据时,产出的 ctx 顶层结构与 empty_context 同构。"""
    ctx = bc.prep_context(NOW, _mock_cache())
    empty = empty_context()
    assert set(ctx.keys()) >= set(empty.keys()) - {"printer"} | {"printer"}
    for k in ("now", "time_hm", "clock", "battery", "home", "ai", "device", "printer"):
        assert k in ctx, f"缺 {k}"


def test_home_weather_and_reminders():
    ctx = bc.prep_context(NOW, _mock_cache())
    w = ctx["home"]["weather"]
    assert w["temp"] == "24" and w["cond"] == "多云"
    assert w["today_range"] == "18–26°"
    r = ctx["home"]["reminders"]
    assert r["total"] == 3                                  # 排除已完成
    assert any(x["title"] == "交资料" for x in r["overdue"])
    assert any(x["title"] == "今天开会" for x in r["today"])
    assert any(x["title"] == "明天体检" for x in r["upcoming"])


def test_apple_utc_due_date_uses_local_day():
    now = datetime(2026, 6, 8, 9, 0)
    ctx = bc.prep_context(now, {
        "reminders": [
            {"title": "本地今天", "dueDate": "2026-06-07T16:00:00.000Z", "completed": False},
        ],
    })
    assert [x["title"] for x in ctx["home"]["reminders"]["today"]] == ["本地今天"]


def test_ai_section():
    ctx = bc.prep_context(NOW, _mock_cache())
    ai = ctx["ai"]
    assert ai["five_pct"] == 42 and ai["cx_five_pct"] == 15
    assert ai["cc_tok"] == "1M" or ai["cc_tok"].endswith("M")
    assert ai["custom_total"] == ""                         # 无 cfg=倍率默认 1.0,不显示自定义价
    assert len(ai["chart"]) == 7                            # 近 7 天


def test_custom_rate_two_tier():
    """Claude/Codex 各一档倍率,自定义价 = 各自官方价 × 倍率 之和。"""
    cfg = {"ai_usage": {"claude_rate": 0.5, "codex_rate": 0.1}}
    ai = bc.prep_context(NOW, _mock_cache(), cfg)["ai"]
    # cc 8.1×0.5=4.05 + cx 4.2×0.1=0.42 = 4.47
    assert ai["custom_total"] == "¥4.47"


def test_custom_rate_default_hidden():
    """两档都=1.0 视为未配置,自定义价隐藏(避免与官方价重复)。"""
    ai = bc.prep_context(NOW, _mock_cache(), {"ai_usage": {"claude_rate": 1.0, "codex_rate": 1.0}})["ai"]
    assert ai["custom_total"] == ""


def test_device_and_printer():
    # push 设备必须在 config 里才上看板(不再自动采纳未配置的)
    cfg = {"devices": {"machines": [{"id": "nas-01", "name": "nas-01", "mode": "push"}]}}
    ctx = bc.prep_context(NOW, _mock_cache(), cfg)
    ms = ctx["device"]["machines"]
    assert len(ms) == 1
    nas = ms[0]
    assert nas["name"] == "nas-01"
    assert nas["cpu"] == 23 and nas["mem"] == 50
    assert nas["vols"][0]["name"] == "vol1"
    assert nas["show"]["cpu"] is True       # 无 fields=全显示
    pr = ctx["printer"]
    assert pr is not None and pr["printing"] is True
    assert pr["remaining_text"] == "2小时15分"               # 2.25 小时换算
    assert pr["state_text"] == "打印中"


def test_unconfigured_push_device_not_on_dashboard():
    """未在 config 加进来的 push 设备不上看板。"""
    ctx = bc.prep_context(NOW, _mock_cache())
    assert ctx["device"]["machines"] == []


def _cache_with_push(secs_ago):
    """加一台 updated_at 在 secs_ago 秒前上报过的 push 设备(模拟 agent 关机)。"""
    cache = _mock_cache()
    cache["devices_metrics"]["win-pc"] = {
        "hostname": "win-pc", "cpu_pct": 5,
        "mem_used": 4 * 1024**3, "mem_total": 16 * 1024**3,
        "updated_at": time.time() - secs_ago,
    }
    return cache


_PUSH_PC = {"id": "win-pc", "name": "win-pc", "mode": "push"}


def test_offline_push_device_hidden():
    """push 设备关机后(updated_at 超时)不再上看板——Windows 关机不该残留占用。"""
    cfg = {"devices": {"machines": [_PUSH_PC]}}
    ms = bc.prep_context(NOW, _cache_with_push(9999), cfg)["device"]["machines"]
    assert [m["name"] for m in ms] == []


def test_fresh_push_device_shown():
    """刚上报过的 push 设备正常显示。"""
    cfg = {"devices": {"machines": [_PUSH_PC]}}
    ms = bc.prep_context(NOW, _cache_with_push(1), cfg)["device"]["machines"]
    assert [m["name"] for m in ms] == ["win-pc"]


def test_local_device_not_time_filtered():
    """local/ssh 直采设备无 updated_at,不参与离线过滤(采集器在跑就常驻)。"""
    cfg = {"devices": {"machines": [{"id": "nas-01", "name": "nas-01", "mode": "local"}]}}
    ms = bc.prep_context(NOW, _mock_cache(), cfg)["device"]["machines"]
    assert [m["name"] for m in ms] == ["nas-01"]


def test_offline_after_configurable():
    """offline_after 可配:调小后较早的上报即算离线。"""
    cache = _cache_with_push(100)                      # 100s 前上报
    assert bc.prep_context(NOW, cache,                 # 默认 180s 内 → 显示
                           {"devices": {"machines": [_PUSH_PC]}})["device"]["machines"]
    cfg = {"devices": {"machines": [_PUSH_PC], "offline_after": 60}}
    assert bc.prep_context(NOW, cache, cfg)["device"]["machines"] == []


def test_battery():
    ctx = bc.prep_context(NOW, _mock_cache())
    assert ctx["battery"]["level"] == 87 and ctx["battery"]["has"] is True


def test_empty_cache_degrades_without_error():
    """空 cache 不报错,各段降级。"""
    ctx = bc.prep_context(NOW, {})
    assert ctx["home"]["weather"]["temp"] == "--"
    assert ctx["home"]["reminders"]["total"] == 0
    assert ctx["device"]["machines"] == []
    assert ctx["printer"] is None
    assert ctx["battery"]["has"] is False


def test_device_rename_and_field_filter():
    """配置可重命名设备 + 勾选显示项。"""
    cfg = {"devices": {"machines": [
        {"id": "nas-01", "name": "客厅NAS", "mode": "push", "fields": ["cpu", "mem"]}]}}
    ms = bc.prep_context(NOW, _mock_cache(), cfg)["device"]["machines"]
    nas = next(x for x in ms if x["name"] == "客厅NAS")     # 重命名生效
    assert nas["show"]["cpu"] and nas["show"]["mem"]
    assert not nas["show"]["net"] and not nas["show"]["disk_io"]
    assert nas["vols"] == []                                 # 未勾选任何分区


def test_calendar_solar_terms_are_calculated_after_2026():
    """节气按年份计算;2028 小寒会从 2026 的 1/5 漂移到 1/6。"""
    cal = bc.build_calendar(date(2028, 1, 1))
    labels = {cell["d"]: cell["l"] for row in cal for cell in row if cell}
    assert labels[5] != "小寒"
    assert labels[6] == "小寒"
    assert bc.solar_term_text(date(2028, 1, 6)) == "今日小寒"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  ✓ {fn.__name__}")
    print(f"\n{len(fns)} passed")
