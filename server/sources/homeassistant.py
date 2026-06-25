"""Home Assistant 采集:借中枢拉取。一次 GET /api/states,既建打印机也建实体卡片墙。

依赖 home_assistant.url + token。两类消费者:
- printer 页:需 printer.enabled + entity_prefix(拓竹经 ha-bambulab,字段历史遗留)。
- ha 页:需 ha_page.entities(用户在设置网页挑的任意实体)。
任一需要就拉一次 states;两者共享同一份结果,不重复请求(spec docs/ha-page-spec.md §6.1)。

坑:HA 的 remaining_time 单位是【小时】(如 7.25=7h15m),原样透传为 remaining_min,
由 build_context 的 printer 段按小时换算(沿用现状,变量名历史遗留)。

诚实降级:HA 拉不通返回 None → _merge 不覆盖 cache → 保留上一帧。
"""
import httpx


# ============================================================
# 实体 → 卡片映射(spec §5)
# ============================================================
TOGGLE_DOMAINS = {"light", "switch", "fan", "input_boolean",
                  "automation", "script", "siren", "humidifier"}
# 合法 HVAC 模式(给空调面板的模式按钮过滤;与 actions.HVAC_MODES 同口径,
# 此处单列一份避免 homeassistant↔actions 循环导入)。
_HVAC_VALID = ("off", "heat", "cool", "heat_cool", "auto", "dry", "fan_only")
HVAC_CN = {"heat": "制热", "cool": "制冷", "heat_cool": "自动", "auto": "自动",
           "dry": "除湿", "fan_only": "送风", "off": "关"}
MEDIA_CN = {"playing": "播放中", "paused": "暂停", "idle": "空闲",
            "off": "关闭", "standby": "待机"}

# domain → 默认 mdi 图标(实体无自带 attributes.icon 时兜底)。
DOMAIN_ICON = {
    "light": "mdi:lightbulb", "switch": "mdi:power-socket", "fan": "mdi:fan",
    "input_boolean": "mdi:toggle-switch", "automation": "mdi:robot",
    "script": "mdi:script-text", "siren": "mdi:bullhorn", "humidifier": "mdi:air-humidifier",
    "lock": "mdi:lock", "cover": "mdi:window-shutter", "binary_sensor": "mdi:circle",
    "sensor": "mdi:gauge", "climate": "mdi:thermostat", "media_player": "mdi:play-circle",
    "person": "mdi:account", "device_tracker": "mdi:account",
    "weather": "mdi:weather-partly-cloudy",
}
SENSOR_DC_ICON = {
    "temperature": "mdi:thermometer", "humidity": "mdi:water-percent",
    "power": "mdi:flash", "energy": "mdi:lightning-bolt", "illuminance": "mdi:brightness-5",
    "battery": "mdi:battery", "pressure": "mdi:gauge",
    "carbon_dioxide": "mdi:molecule-co2", "co2": "mdi:molecule-co2", "pm25": "mdi:air-filter",
}
BINARY_DC_ICON = {
    "door": "mdi:door", "window": "mdi:window-closed", "garage_door": "mdi:garage",
    "motion": "mdi:motion-sensor", "occupancy": "mdi:account", "presence": "mdi:account",
    "moisture": "mdi:water-alert", "smoke": "mdi:smoke-detector",
    "gas": "mdi:gas-cylinder", "problem": "mdi:alert",
}


def _default_icon(domain, dc):
    if domain == "sensor" and dc in SENSOR_DC_ICON:
        return SENSOR_DC_ICON[dc]
    if domain == "binary_sensor" and dc in BINARY_DC_ICON:
        return BINARY_DC_ICON[dc]
    return DOMAIN_ICON.get(domain, "")


def _binary_text(dc, on):
    if dc in ("door", "window", "garage_door"):
        return "开" if on else "关"
    if dc in ("motion", "occupancy", "presence"):
        return "有人" if on else "无人"
    if dc == "moisture":
        return "漏水" if on else "正常"
    if dc in ("problem", "smoke", "gas"):
        return "异常" if on else "正常"
    return "是" if on else "否"


def _num_or_none(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _build_card(by_id, ent):
    """把一个配置项 {entity_id,name,icon} + states 映射成一张契约卡片(contract.empty_ha 的卡片结构)。"""
    eid = (ent.get("entity_id") or "").strip()
    name_override = (ent.get("name") or "").strip()
    icon_override = (ent.get("icon") or "").strip()

    s = by_id.get(eid)
    if s is None:                       # 实体被删/写错 → 兜底文本卡,不报错(spec §5 降级)
        return {"name": name_override or eid or "未知实体", "kind": "text",
                "icon": icon_override, "on": False, "state_text": "未知实体",
                "value": "", "unit": "", "sub": "", "entity_id": eid}

    attrs = s.get("attributes") or {}
    state = (s.get("state") or "").strip()
    domain = eid.split(".")[0] if "." in eid else ""
    dc = attrs.get("device_class") or ""
    name = name_override or attrs.get("friendly_name") or eid
    icon = icon_override or attrs.get("icon") or _default_icon(domain, dc)
    bad = state.lower() in ("unavailable", "unknown", "")   # 离线/无数据 → 主显 --

    card = {"name": name, "kind": "text", "icon": icon, "on": False,
            "state_text": "", "value": "", "unit": "", "sub": "",
            "entity_id": eid}     # 仅 App 交互用(点卡→/api/action/ha);Kindle 模板无视

    if domain in TOGGLE_DOMAINS:
        card["kind"] = "toggle"
        card["on"] = state == "on"
        card["state_text"] = "--" if bad else ("开" if state == "on" else "关")
    elif domain == "lock":
        card["kind"] = "lock"
        card["on"] = state == "locked"
        card["state_text"] = "--" if bad else ("已锁" if state == "locked" else "未锁")
    elif domain == "cover":
        card["kind"] = "cover"
        card["on"] = state == "open"
        pos = attrs.get("current_position")
        pos_int = None
        if bad:
            card["state_text"] = "--"
        elif pos is not None and str(pos) != "":
            try:
                pos_int = int(float(pos))
                card["state_text"] = f"{pos_int}%"
            except (TypeError, ValueError):
                card["state_text"] = "开" if state == "open" else "关"
        else:
            card["state_text"] = "开" if state == "open" else "关"
        card["meta"] = {"on": card["on"], "position": pos_int}   # 仅 App 面板用;Kindle 无视
    elif domain == "binary_sensor":
        card["kind"] = "binary"
        card["on"] = state == "on"
        card["state_text"] = "--" if bad else _binary_text(dc, state == "on")
    elif domain == "sensor":
        card["kind"] = "sensor"
        card["value"] = "--" if bad else state
        card["unit"] = attrs.get("unit_of_measurement") or ""
    elif domain == "weather":
        card["kind"] = "sensor"
        t = attrs.get("temperature")
        card["value"] = "--" if (bad or t is None) else str(t)
        card["unit"] = "°"
    elif domain == "climate":
        card["kind"] = "climate"
        card["on"] = (not bad) and state != "off"
        card["state_text"] = "--" if bad else HVAC_CN.get(state, state)
        ct = attrs.get("current_temperature")
        card["value"] = "" if (ct is None or bad) else str(ct)
        tgt = attrs.get("temperature")
        card["sub"] = "" if tgt is None else f"目标 {tgt}°"
        modes = [m for m in (attrs.get("hvac_modes") or []) if m in _HVAC_VALID]
        card["meta"] = {"on": card["on"], "mode": state, "modes": modes,
                        "current": _num_or_none(ct), "target": _num_or_none(tgt)}
    elif domain == "media_player":
        card["kind"] = "media"
        card["on"] = state == "playing"
        card["state_text"] = "--" if bad else MEDIA_CN.get(state, state or "空闲")
        title = attrs.get("media_title") or ""
        card["sub"] = (title[:17] + "…") if len(title) > 18 else title
        card["meta"] = {"on": card["on"], "title": title}
    elif domain in ("person", "device_tracker"):
        card["kind"] = "presence"
        card["on"] = state == "home"
        card["state_text"] = "--" if bad else ("在家" if state == "home" else "外出")
    # ↓ 新增可控 kind(spec docs/ha-page-interaction-spec.md §2)。Kindle 字段(on/value/
    #   unit/sub 留默认、state_text 同旧 text 兜底)保持与改动前逐字节一致;只追加 App 用 meta。
    elif domain in ("select", "input_select"):
        card["kind"] = "select"
        card["state_text"] = "--" if bad else (state or "--")
        opts = [str(o) for o in (attrs.get("options") or [])]
        card["meta"] = {"options": opts, "current": state}
    elif domain in ("number", "input_number"):
        card["kind"] = "number"
        card["state_text"] = "--" if bad else (state or "--")
        card["meta"] = {"min": attrs.get("min"), "max": attrs.get("max"),
                        "step": attrs.get("step"),
                        "unit": attrs.get("unit_of_measurement") or "",
                        "value": _num_or_none(state)}
    elif domain in ("button", "input_button"):
        card["kind"] = "button"            # 一次性动作,A 类单击直发,无面板/meta
        card["state_text"] = "--" if bad else (state or "--")
    elif domain == "scene":
        card["kind"] = "scene"             # 一次性动作,A 类单击直发
        card["state_text"] = "--" if bad else (state or "--")
    elif domain == "alarm_control_panel":
        card["kind"] = "alarm"
        card["state_text"] = "--" if bad else (state or "--")
        card["meta"] = {"state": state}    # 面板按当前布防态给布防/撤防按钮
    else:                               # 兜底:任意 domain 都有显示,不报错
        card["kind"] = "text"
        card["state_text"] = "--" if bad else (state or "--")
    return card


# ============================================================
# 实体选择器(spec §6.2)—— 设置网页搜索候选
# ============================================================
def list_entities(url, token, q="", domain=""):
    """列出 HA 实体供设置网页选择。返回 {entities:[...], truncated:bool}。
    凭据只在服务端用;按 q(匹配 entity_id 或 name)和 domain 过滤;按 name 排序;截断到前 50。"""
    states = _fetch_states(url.strip().rstrip("/"), token.strip())
    q = (q or "").strip().lower()
    domain = (domain or "").strip()
    items = []
    for s in states:
        eid = s.get("entity_id", "")
        dom = eid.split(".")[0] if "." in eid else ""
        if domain and dom != domain:
            continue
        attrs = s.get("attributes") or {}
        name = attrs.get("friendly_name") or eid
        if q and q not in eid.lower() and q not in str(name).lower():
            continue
        items.append({
            "entity_id": eid, "name": name, "domain": dom,
            "device_class": attrs.get("device_class", "") or "",
            "state": s.get("state", ""),
            "unit": attrs.get("unit_of_measurement", "") or "",
            "icon": attrs.get("icon", "") or "",
        })
    items.sort(key=lambda x: str(x["name"]).lower())
    truncated = len(items) > 50
    return {"entities": items[:50], "truncated": truncated}


# ============================================================
# 打印机卡片(沿用现状,行为不变)
# ============================================================
def _state(states, prefix, entity):
    eid = f"sensor.{prefix}_{entity}"
    for s in states:
        if s["entity_id"] == eid:
            return s["state"]
    return None


def _printer_prefixes(states):
    suffix = "_print_progress"
    out = []
    for s in states:
        eid = s.get("entity_id", "")
        if eid.startswith("sensor.") and eid.endswith(suffix):
            out.append(eid[len("sensor."):-len(suffix)])
    return sorted(set(out))


def _resolve_printer_prefix(states, prefix):
    prefix = (prefix or "").strip()
    if prefix.startswith("sensor."):
        prefix = prefix[len("sensor."):]
    for suffix in ("_print_progress", "_print_status", "_remaining_time"):
        if prefix.endswith(suffix):
            prefix = prefix[:-len(suffix)]
    if not prefix:
        return prefix
    candidates = _printer_prefixes(states)
    if prefix in candidates:
        return prefix
    probes = [prefix]
    trimmed = prefix.rstrip("_")
    if trimmed and trimmed != prefix:
        probes.append(trimmed)
    matches = [c for c in candidates if any(c.startswith(p) for p in probes)]
    return matches[0] if len(matches) == 1 else prefix


def _build_printer(states, prefix):
    prefix = _resolve_printer_prefix(states, prefix)
    g = lambda e: _state(states, prefix, e)
    online = None
    for s in states:
        if s["entity_id"] == f"binary_sensor.{prefix}_online":
            online = s["state"]
    progress = g("print_progress")
    rem = g("remaining_time")
    try:
        rem_min = float(rem) if rem not in (None, "unavailable", "unknown") else None
    except (TypeError, ValueError):
        rem_min = None
    return {
        "online": online == "on",
        "status": g("print_status"), "stage": g("current_stage"),
        "progress": int(float(progress)) if progress not in (None, "unavailable", "unknown") else 0,
        "task": g("task_name") or "--",
        "layer": g("current_layer") or "0",
        "total_layer": g("total_layer_count") or "0",
        "remaining_min": rem_min,                 # 实为小时,build_context 换算
        "end_time": g("end_time"),
        "nozzle": g("nozzle_temperature") or "--",
        "nozzle_t": g("nozzle_target_temperature") or "--",
        "bed": g("bed_temperature") or "--",
        "bed_t": g("bed_target_temperature") or "--",
        "speed": g("speed_profile") or "--",
        "weight": g("print_weight") or "--",
        "material": g("active_tray") or "--",
        "cooling_fan": g("cooling_fan_speed") or "0",
        "printer_name": g("printer_name") or "A1",
    }


def _printer_name(states, prefix):
    name = _state(states, prefix, "printer_name")
    if name not in (None, "", "unavailable", "unknown"):
        return name
    for s in states:
        if s.get("entity_id") == f"binary_sensor.{prefix}_online":
            return (s.get("attributes") or {}).get("friendly_name") or prefix
    return prefix


def list_printers(url, token):
    """扫描 HA states,返回可作为打印机页数据源的拓竹打印机候选。"""
    states = _fetch_states(url.strip().rstrip("/"), token.strip())
    printers = []
    for prefix in _printer_prefixes(states):
        pr = _build_printer(states, prefix)
        printers.append({
            "prefix": prefix,
            "name": _printer_name(states, prefix),
            "online": pr["online"],
            "status": pr.get("status") or "",
            "stage": pr.get("stage") or "",
            "progress": pr.get("progress") or 0,
            "nozzle": pr.get("nozzle") or "",
            "bed": pr.get("bed") or "",
        })
    printers.sort(key=lambda x: (not x["online"], str(x["name"]).lower()))
    return {"printers": printers}


# ============================================================
# 拉取
# ============================================================
def _fetch_states(url, token):
    with httpx.Client(timeout=8) as client:
        r = client.get(f"{url}/api/states",
                       headers={"Authorization": f"Bearer {token}"})
        return r.json()


def collect(cfg: dict):
    ha = (cfg or {}).get("home_assistant", {})
    url = (ha.get("url") or "").strip().rstrip("/")
    token = (ha.get("token") or "").strip()
    if not (url and token):
        return None
    pr_cfg = (cfg or {}).get("printer", {})
    prefix = (pr_cfg.get("entity_prefix") or "").strip()
    want_printer = bool(pr_cfg.get("enabled") and prefix)
    entities = ((cfg or {}).get("ha_page", {}) or {}).get("entities", []) or []
    if not (want_printer or entities):
        return None
    try:
        states = _fetch_states(url, token)
    except Exception as e:
        print(f"[homeassistant] {e}")
        return None                     # 不覆盖 cache,保留上一帧
    out = {}
    if want_printer:
        out["printer"] = _build_printer(states, prefix)
    if entities:
        by_id = {s.get("entity_id"): s for s in states}
        cards = [_build_card(by_id, e) for e in entities]
        print(f"[homeassistant] ha 页渲染 {len(cards)} 张卡片")
        out["ha"] = {"cards": cards}
    return out or None
