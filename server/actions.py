"""设备动作接口 —— 安卓 App 点击 → 对 HA / qB / Transmission 的真实操作。

后台从「只读」变「可写」的唯一入口。两类:
- HA 实体控制  ha_action(cfg, entity_id, action, value) 全 kind 白名单(开关/锁/窗帘/空调/媒体/选择/数值/按钮/安防)
- 下载控制     torrent_action(cfg, client, tid, action) action ∈ pause/resume(按 client 名路由到 adapter)

  注:3D 打印机控制(pause/resume/stop)已于 2026-06-23 移除——经 HA 拓竹云模式
  (bambu_cloud)下控制指令发不到打印机(button.press 在 HA 成功但打印机不响应,
  真机实测进度照涨),纯属上游限制、非看板问题。打印机页改为只读显示(状态/进度/温度)。
  日后用户把拓竹集成切到 LAN 局域网模式即可重新启用,届时复活 printer_action 即可。

安全(docs/android-app-spec.md §3,务必守住):
- 全部经 app._auth 令牌保护(这些能改你家设备,绝不豁免、绝不进 _AUTH_EXEMPT_*)。
- **只做白名单内操作**(下方各 ACTIONS_* 常量 + _resolve_action 分发),不接受任意 service/命令透传(防注入)。
- 幂等:重复 pause 已暂停的种子不报错(下游 API 幂等)。
失败抛异常,由 app.py 路由捕获转成 {ok:false,error},前端提示、不崩。
"""
import httpx

from server.sources import homeassistant as ha
from server.sources import downloader as dl

# 白名单(超出即拒,不透传)
ACTIONS_TORRENT = ("pause", "resume")

# HVAC 模式白名单(climate.set_hvac_mode 的 value 只能是这些之一)
HVAC_MODES = ("off", "heat", "cool", "heat_cool", "auto", "dry", "fan_only")

# 各「可控 kind」支持的动作(给前端/测试页用,也是后端校验依据)。
# value 含义见 _resolve_action;无 value 的动作不读 value。
KIND_ACTIONS = {
    "toggle": ("on", "off", "toggle"),
    "lock":   ("on", "off"),                                      # on=锁 off=解锁
    "cover":  ("on", "off", "toggle", "stop"),                    # on=开 off=关
    "climate": ("on", "off", "set_temp", "set_mode"),            # set_temp:数值;set_mode:HVAC_MODES
    "media":  ("toggle", "play", "pause", "stop", "next", "prev",
               "vol_up", "vol_down", "mute", "unmute"),
    "select": ("select_option",),                                # value=选项(须在实体 options 内)
    "number": ("set_value",),                                    # value=数值
    "text":   ("set_value",),                                    # value=文本
    "button": ("press",),
    "scene":  ("activate",),
    "alarm":  ("arm_home", "arm_away", "arm_night", "disarm"),   # disarm 可带 code(value)
}


def _ha_creds(cfg):
    h = (cfg or {}).get("home_assistant", {}) or {}
    url = (h.get("url") or "").strip().rstrip("/")
    token = (h.get("token") or "").strip()
    if not (url and token):
        raise RuntimeError("Home Assistant 未配置(缺地址或令牌)")
    return url, token


def _ha_call(url, token, sdom, service, entity_id, extra=None):
    """调一次 HA 服务:POST /api/services/{domain}/{service},body {entity_id, **extra}。
    sdom/service 永远来自下方固定白名单映射,绝不取自用户输入(防注入);
    extra 只放按类型校验过的数值/选项(temperature/option/value/code/...)。"""
    body = {"entity_id": entity_id}
    if extra:
        body.update(extra)
    with httpx.Client(timeout=8) as c:
        r = c.post(f"{url}/api/services/{sdom}/{service}",
                   headers={"Authorization": f"Bearer {token}"},
                   json=body)
        r.raise_for_status()
    return True


def _num(value):
    try:
        f = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"需要一个数值,收到:{value!r}")
    return int(f) if f == int(f) else f


def _kind_of(domain):
    """entity domain → 可控 kind(与 homeassistant._build_card 同口径);不可控返回 None。"""
    if domain in ha.TOGGLE_DOMAINS:
        return "toggle"
    return {
        "lock": "lock", "cover": "cover", "climate": "climate",
        "media_player": "media", "select": "select", "input_select": "select",
        "number": "number", "input_number": "number", "text": "text",
        "button": "button", "input_button": "button", "scene": "scene",
        "alarm_control_panel": "alarm",
    }.get(domain)


def _resolve_action(domain, action, value):
    """把 (domain, action, value) 映射成固定的 (service_domain, service, extra_dict)。
    **service 全部硬编码、只认白名单 action**;value 按目标类型强制转换/校验,只进 extra 的固定字段。
    返回的 service 绝不含任何用户字符串(防注入)。超出白名单即抛 ValueError。"""
    # 通用开关(switch/light/fan/... 以及 climate on/off 也走它,最兼容)
    if domain in ha.TOGGLE_DOMAINS or domain == "climate":
        if action in ("on", "off", "toggle"):
            return ("homeassistant", {"on": "turn_on", "off": "turn_off",
                                      "toggle": "toggle"}[action], {})
    if domain == "lock":
        m = {"on": "lock", "off": "unlock"}
        if action in m:
            return ("lock", m[action], {})
    elif domain == "cover":
        m = {"on": "open_cover", "off": "close_cover",
             "toggle": "toggle", "stop": "stop_cover"}
        if action in m:
            return ("cover", m[action], {})
    elif domain == "climate":
        if action == "set_temp":
            return ("climate", "set_temperature", {"temperature": _num(value)})
        if action == "set_mode":
            mode = str(value)
            if mode not in HVAC_MODES:
                raise ValueError(f"非法 HVAC 模式:{mode}")
            return ("climate", "set_hvac_mode", {"hvac_mode": mode})
    elif domain == "media_player":
        m = {"toggle": "media_play_pause", "play": "media_play",
             "pause": "media_pause", "stop": "media_stop",
             "next": "media_next_track", "prev": "media_previous_track",
             "vol_up": "volume_up", "vol_down": "volume_down"}
        if action in m:
            return ("media_player", m[action], {})
        if action in ("mute", "unmute"):
            return ("media_player", "volume_mute",
                    {"is_volume_muted": action == "mute"})
    elif domain in ("select", "input_select"):
        if action == "select_option":
            return (domain, "select_option", {"option": str(value)})
    elif domain in ("number", "input_number"):
        if action == "set_value":
            return (domain, "set_value", {"value": _num(value)})
    elif domain == "text":
        if action == "set_value":
            return ("text", "set_value", {"value": str(value)})
    elif domain in ("button", "input_button"):
        if action == "press":
            return (domain, "press", {})
    elif domain == "scene":
        if action == "activate":
            return ("scene", "turn_on", {})
    elif domain == "alarm_control_panel":
        m = {"arm_home": "alarm_arm_home", "arm_away": "alarm_arm_away",
             "arm_night": "alarm_arm_night", "disarm": "alarm_disarm"}
        if action in m:
            extra = {}
            if value not in (None, ""):       # 部分安防需要 code 才能撤防/布防
                extra["code"] = str(value)
            return ("alarm_control_panel", m[action], extra)
    raise ValueError(f"{domain} 不支持操作 {action}")


def ha_action(cfg, entity_id, action, value=None):
    """控制一个 HA 实体。action/value 经 _resolve_action 白名单解析(超出即拒,防注入)。
    domain 由 entity_id 前缀决定;支持 开关/锁/窗帘/空调(开关+调温+模式)/媒体/选择/
    数值/文本/按钮/场景/安防(布防撤防)。"""
    entity_id = (entity_id or "").strip()
    if "." not in entity_id:
        raise ValueError("非法 entity_id")
    domain = entity_id.split(".")[0]
    url, token = _ha_creds(cfg)
    sdom, service, extra = _resolve_action(domain, action, value)
    return _ha_call(url, token, sdom, service, entity_id, extra)


# 只读域(测试页只显示数值/状态,不放控制按钮)
READONLY_DOMAINS = {"sensor", "binary_sensor", "weather", "person",
                    "device_tracker", "sun", "update", "image", "camera",
                    "event", "conversation", "zone"}


def controllable_inventory(cfg):
    """拉全 HA 实体,按「可控 kind」分组 + 只读传感器单列(供测试台全量覆盖)。
    返回 {groups:{kind:[entry,...]}, readonly:[...], counts:{...}}。
    entry 带控件所需元数据(select.options / number.min·max·step / climate.hvac_modes·温度 等)。"""
    url, token = _ha_creds(cfg)
    states = ha._fetch_states(url, token)
    groups, readonly = {}, []
    for s in states:
        eid = s.get("entity_id", "")
        if "." not in eid:
            continue
        domain = eid.split(".")[0]
        attrs = s.get("attributes") or {}
        name = attrs.get("friendly_name") or eid
        state = s.get("state", "")
        kind = _kind_of(domain)
        if kind:
            e = {"entity_id": eid, "name": name, "domain": domain, "kind": kind,
                 "state": state, "actions": list(KIND_ACTIONS.get(kind, ()))}
            if kind == "select":
                e["options"] = attrs.get("options") or []
            elif kind == "number":
                e["min"] = attrs.get("min"); e["max"] = attrs.get("max")
                e["step"] = attrs.get("step"); e["unit"] = attrs.get("unit_of_measurement") or ""
            elif kind == "climate":
                e["current_temp"] = attrs.get("current_temperature")
                e["target_temp"] = attrs.get("temperature")
                e["hvac_modes"] = [m for m in (attrs.get("hvac_modes") or []) if m in HVAC_MODES]
                e["on"] = state not in ("off", "unavailable", "unknown", "")
            elif kind == "cover":
                e["position"] = attrs.get("current_position")
                e["on"] = state == "open"
            elif kind == "media":
                e["title"] = attrs.get("media_title") or ""
                e["on"] = state == "playing"
            elif kind == "lock":
                e["on"] = state == "locked"
            elif kind == "text":
                e["value"] = state
            elif kind == "toggle":
                e["on"] = state == "on"
            groups.setdefault(kind, []).append(e)
        elif domain in READONLY_DOMAINS:
            readonly.append({"entity_id": eid, "name": name, "domain": domain,
                             "state": state, "unit": attrs.get("unit_of_measurement") or ""})
    for lst in groups.values():
        lst.sort(key=lambda x: x["name"])
    readonly.sort(key=lambda x: (x["domain"], x["name"]))
    counts = {k: len(v) for k, v in groups.items()}
    counts["readonly"] = len(readonly)
    return {"groups": groups, "readonly": readonly, "counts": counts}


def torrent_action(cfg, client, tid, action):
    """暂停/恢复某下载器里的某种子。按 client(下载器名)在配置里找到它 → 对应 adapter 写方法。"""
    if action not in ACTIONS_TORRENT:
        raise ValueError(f"非法操作:{action}")
    client = (client or "").strip()
    clients = (((cfg or {}).get("downloaders", {}) or {}).get("clients", []) or [])
    match = next((c for c in clients if isinstance(c, dict)
                  and ((c.get("name") or c.get("host") or "?") == client)), None)
    if match is None:
        raise RuntimeError(f"找不到下载器:{client}")
    fn = dl._WRITE_ADAPTERS.get(match.get("type", "qbittorrent"))
    if fn is None:
        raise RuntimeError(f"下载器类型不支持控制:{match.get('type')}")
    return fn(match, tid, action)
