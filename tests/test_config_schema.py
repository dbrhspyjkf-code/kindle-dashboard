"""配置 schema 的验证。可直接 `python3 tests/test_config_schema.py` 跑,也兼容 pytest。"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from server.config import schema  # noqa: E402


def test_default_config_validates():
    """默认配置(所有模块未启用)应校验通过 —— 诚实降级:没填不报错。"""
    cfg = schema.default_config()
    errors = schema.validate(cfg)
    assert errors == [], f"默认配置不该有错: {errors}"


def test_default_has_no_secrets():
    """默认/示例里 secret 字段必须为空(零凭据)。"""
    cfg = schema.default_config()
    for sec in schema.SCHEMA:
        for f in sec.fields:
            if f.secret:
                assert cfg[sec.key][f.key] == "", f"{sec.key}.{f.key} 不该带默认凭据"


def test_enable_when_drives_pages():
    """填了天气 key+location → home 页出现;没填 → 不出现。"""
    cfg = schema.default_config()
    assert "home" not in schema.active_pages(cfg)
    cfg["weather"]["key"] = "x"
    cfg["weather"]["location"] = "101010100"
    assert "home" in schema.active_pages(cfg)


def test_news_default_on_with_aihot():
    """资讯页默认就预置 AIHOT 订阅源 → 全新配置即默认开 news(无需凭据,无需手配)。
    回归:曾因 default_config() 把 module_list 一律置空、忽略 Field 的 default,
    导致 AIHOT 默认源丢失、news 页默认不出现。"""
    cfg = schema.default_config()
    feeds = cfg["news"]["feeds"]
    assert feeds and any("aihot" in (f.get("url") or "").lower() for f in feeds), \
        f"news.feeds 默认应预置 AIHOT: {feeds}"
    assert schema.enabled_modules(cfg).get("news") is True
    assert "news" in schema.active_pages(cfg)


def test_other_module_lists_default_empty():
    """除 news 外的 module_list(设备/下载器/HA 实体)默认仍为空,不凭空启用。"""
    cfg = schema.default_config()
    assert cfg["devices"]["machines"] == []
    assert cfg["downloaders"]["clients"] == []
    assert cfg["ha_page"]["entities"] == []


def test_pages_custom_order_and_appends_unlisted():
    """display.pages 自定义顺序生效;且没列进顺序但已配的页自动补末尾(不凭空消失)。"""
    cfg = schema.default_config()
    cfg["weather"]["key"] = "x"; cfg["weather"]["location"] = "101010100"   # home 就绪
    cfg["ai_usage"]["enabled"] = True                                       # ai 就绪
    cfg["news"]["feeds"] = [{"url": "http://x/feed.xml", "name": "X"}]       # news 就绪
    # 用户只把 ai 拖到第一,没列 home/news
    cfg["display"]["pages"] = ["ai"]
    pages = schema.active_pages(cfg)
    assert pages[0] == "ai"                          # 自定义顺序:ai 在最前
    assert "home" in pages and "news" in pages       # 没列进去但已配 → 仍出现(补在后面)


def test_hidden_pages_overrides_configured():
    """display.hidden_pages 里的页即使数据源就绪也撤下(用户在设置页主动关闭);其它页不受影响。"""
    cfg = schema.default_config()
    cfg["weather"]["key"] = "x"; cfg["weather"]["location"] = "101010100"   # home 就绪
    cfg["ai_usage"]["enabled"] = True                                       # ai 就绪
    assert "home" in schema.active_pages(cfg)
    assert "ai" in schema.active_pages(cfg)
    cfg["display"]["hidden_pages"] = ["home"]
    pages = schema.active_pages(cfg)
    assert "home" not in pages          # 配了天气数据源也被手动关掉
    assert "ai" in pages                # 没关的页不受影响


def test_required_only_checked_when_enabled():
    """HA token 必填,但只在 HA 模块启用(填了 url)时才校验。"""
    cfg = schema.default_config()
    assert schema.validate(cfg) == []          # 没填 url,不强求 token
    cfg["home_assistant"]["url"] = "http://x:8123"
    errors = schema.validate(cfg)
    assert any("令牌" in e for e in errors), f"启用 HA 后应要求 token: {errors}"


def test_devices_enable_and_validate():
    """设备列表:有机器才启用;每台 name 必填。"""
    cfg = schema.default_config()
    assert "device" not in schema.active_pages(cfg)
    cfg["devices"]["machines"] = [{"name": "Mac", "mode": "local"}]
    assert "device" in schema.active_pages(cfg)
    cfg["devices"]["machines"] = [{"name": "", "mode": "local"}]
    assert any("名称" in e for e in schema.validate(cfg))


def test_ha_page_enable_and_pages():
    """ha_page:选了实体才启用、才出 ha 页;空=隐藏(配置即页面)。"""
    cfg = schema.default_config()
    assert "ha" not in schema.active_pages(cfg)
    cfg["ha_page"]["entities"] = [{"entity_id": "light.x", "name": "", "icon": ""}]
    assert "ha" not in schema.active_pages(cfg)        # 只选实体不够,还需 HA 地址/令牌都配好
    cfg["home_assistant"]["url"] = "http://h:8123"
    cfg["home_assistant"]["token"] = "t"
    assert "ha" in schema.active_pages(cfg)
    # entity_id 必填(空 → 报错)
    cfg["ha_page"]["entities"] = [{"entity_id": "", "name": "", "icon": ""}]
    assert any("实体" in e for e in schema.validate(cfg))


def test_type_check():
    cfg = schema.default_config()
    cfg["server"]["port"] = "8585"   # 应为 int
    assert any("端口" in e for e in schema.validate(cfg))


def test_example_yaml_matches_schema():
    """config.example.yaml 的结构必须与 schema 一致(防漂移)。"""
    import yaml
    with open(os.path.join(ROOT, "config.example.yaml"), encoding="utf-8") as fp:
        ex = yaml.safe_load(fp)
    default = schema.default_config()
    assert set(ex.keys()) == set(default.keys()), \
        f"模块不一致: 仅schema={set(default)-set(ex)} 仅example={set(ex)-set(default)}"
    for sec_key, sec_val in default.items():
        assert set(ex[sec_key].keys()) == set(sec_val.keys()), \
            f"[{sec_key}] 字段不一致: 仅schema={set(sec_val)-set(ex[sec_key])} 仅example={set(ex[sec_key])-set(sec_val)}"


def test_to_json_serializable():
    import json
    json.dumps(schema.to_json())  # 不抛异常即可给前端


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  ✓ {fn.__name__}")
    print(f"\n{len(fns)} passed")
