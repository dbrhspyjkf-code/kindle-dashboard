"""下载器采集(qBittorrent + Transmission,合并)。服务端 pull 直采。

可配多台下载器,各自 adapter 鉴权采集 → 归一化 → 合并成一个种子列表 + 全局统计。
adapter 产出原始数值(bytes、秒);格式化(速度/容量/eta/状态本地化)留给 build_context。
失败:某台连不上记进 errors、其余照常;全部连不上返回 None(保留上一帧,诚实降级)。

鉴权细节均经真机实测(见 docs/download-page-spec.md §2):
- qB:登录必须带 Referer 头;累计上传/全局分享率在 sync/maindata 的 server_state(不在 transfer/info)。
- Transmission:首请求 409 拿 X-Transmission-Session-Id 再重试;叠加 HTTP Basic auth。
"""
import httpx

# 两边状态 → 统一枚举
_QB_STATE = {
    "downloading": "downloading", "forcedDL": "downloading", "metaDL": "downloading", "allocating": "downloading",
    "uploading": "seeding", "forcedUP": "seeding", "stalledUP": "seeding",
    "stalledDL": "stalled",
    "checkingDL": "checking", "checkingUP": "checking", "checkingResumeData": "checking", "moving": "checking",
    "queuedDL": "queued", "queuedUP": "queued",
    "pausedDL": "paused", "pausedUP": "paused", "stoppedDL": "paused", "stoppedUP": "paused",
    "error": "error", "missingFiles": "error",
}
_TR_STATE = {0: "paused", 1: "checking", 2: "checking", 3: "queued", 4: "downloading", 5: "queued", 6: "seeding"}
# 活跃优先排序权重
_ORDER = {"downloading": 0, "stalled": 1, "seeding": 2, "checking": 3, "queued": 4, "paused": 5, "error": 6, "other": 7}
_ACTIVE = ("downloading", "seeding", "stalled", "checking")


def _qb_norm(t):
    return {
        "name": t.get("name", "") or "",
        "id": t.get("hash", "") or "",        # 仅 App 控制用(pause/resume 按 hash 路由);Kindle 无视
        "progress": round((t.get("progress", 0) or 0) * 100),
        "dl": int(t.get("dlspeed", 0) or 0),
        "up": int(t.get("upspeed", 0) or 0),
        "ratio": max(float(t.get("ratio", 0) or 0), 0.0),
        "size": int(t.get("size", 0) or 0),
        "eta": int(t.get("eta", 0) or 0),
        "state": _QB_STATE.get(t.get("state", ""), "other"),
    }


def _tr_norm(t):
    return {
        "name": t.get("name", "") or "",
        "id": t.get("id", ""),                # 仅 App 控制用(torrent-stop/start 按数字 id);Kindle 无视
        "progress": round((t.get("percentDone", 0) or 0) * 100),
        "dl": int(t.get("rateDownload", 0) or 0),
        "up": int(t.get("rateUpload", 0) or 0),
        "ratio": max(float(t.get("uploadRatio", 0) or 0), 0.0),   # tr 用 -1 表示无分享率
        "size": int(t.get("totalSize", 0) or 0),
        "eta": int(t.get("eta", 0) or 0),                          # tr -1/-2 = 未知
        "state": _TR_STATE.get(t.get("status"), "other"),
    }


def _qb_fetch(client):
    base = f"http://{(client.get('host') or '').strip()}:{int(client.get('port') or 8080)}"
    with httpx.Client(timeout=8, base_url=base, headers={"Referer": base}) as c:
        r = c.post("/api/v2/auth/login",
                   data={"username": client.get("username", "") or "", "password": client.get("password", "") or ""})
        if r.text.strip() != "Ok.":
            raise RuntimeError(f"qB 登录失败 (HTTP {r.status_code})")
        tor = c.get("/api/v2/torrents/info").json()
        ss = c.get("/api/v2/sync/maindata", params={"rid": 0}).json().get("server_state", {}) or {}
    free = ss.get("free_space_on_disk", -1)
    return {
        "torrents": [_qb_norm(t) for t in tor],
        "dl_speed": int(ss.get("dl_info_speed", 0) or 0),
        "up_speed": int(ss.get("up_info_speed", 0) or 0),
        "ul_bytes": int(ss.get("alltime_ul", 0) or 0),
        "dl_bytes": int(ss.get("alltime_dl", 0) or 0),
        "free": int(free) if isinstance(free, (int, float)) and free >= 0 else -1,
    }


def _tr_fetch(client):
    base = f"http://{(client.get('host') or '').strip()}:{int(client.get('port') or 9091)}/transmission/rpc"
    auth = (client.get("username", "") or "", client.get("password", "") or "")

    def _rpc(c, sid, payload):
        headers = {"X-Transmission-Session-Id": sid} if sid else {}
        return c.post(base, json=payload, headers=headers)

    with httpx.Client(timeout=8, auth=auth) as c:
        r = _rpc(c, "", {"method": "session-stats"})
        if r.status_code == 409:                      # CSRF 握手:取 session id 重试
            sid = r.headers.get("X-Transmission-Session-Id", "")
            r = _rpc(c, sid, {"method": "session-stats"})
        else:
            sid = r.headers.get("X-Transmission-Session-Id", "")
        st = r.json().get("arguments", {}) or {}
        fields = ["id", "name", "percentDone", "rateDownload", "rateUpload", "status",
                  "uploadRatio", "eta", "totalSize"]
        tr = _rpc(c, sid, {"method": "torrent-get", "arguments": {"fields": fields}})
        torrents = (tr.json().get("arguments", {}) or {}).get("torrents", []) or []
    cum = st.get("cumulative-stats", {}) or {}
    return {
        "torrents": [_tr_norm(t) for t in torrents],
        "dl_speed": int(st.get("downloadSpeed", 0) or 0),
        "up_speed": int(st.get("uploadSpeed", 0) or 0),
        "ul_bytes": int(cum.get("uploadedBytes", 0) or 0),
        "dl_bytes": int(cum.get("downloadedBytes", 0) or 0),
        "free": -1,                                   # session-stats 不含剩余空间
    }


_ADAPTERS = {"qbittorrent": _qb_fetch, "transmission": _tr_fetch}


# ============================================================
# 写操作(安卓 App 控制用)—— 暂停/恢复单个种子。只接受 pause/resume 白名单。
# ============================================================
def qb_action(client, thash, action):
    """qB 暂停/恢复某种子(按 hash)。复用带 Referer 的登录流程。
    qB 4.x = /torrents/pause|resume;5.0 改名 /stop|/start —— 两个端点都试(404 换下一个)。"""
    if action not in ("pause", "resume"):
        raise ValueError(f"不支持的操作:{action}")
    if not (thash or "").strip():
        raise ValueError("缺种子 id(hash)")
    eps = {"pause": ("torrents/stop", "torrents/pause"),
           "resume": ("torrents/start", "torrents/resume")}[action]
    base = f"http://{(client.get('host') or '').strip()}:{int(client.get('port') or 8080)}"
    with httpx.Client(timeout=8, base_url=base, headers={"Referer": base}) as c:
        r = c.post("/api/v2/auth/login",
                   data={"username": client.get("username", "") or "", "password": client.get("password", "") or ""})
        if r.text.strip() != "Ok.":
            raise RuntimeError(f"qB 登录失败 (HTTP {r.status_code})")
        for ep in eps:
            rr = c.post(f"/api/v2/{ep}", data={"hashes": thash})
            if rr.status_code != 404:        # 命中本版本的端点(另一个版本名会 404)
                rr.raise_for_status()
                return True
    raise RuntimeError("qB pause/resume 端点均 404(版本不支持?)")


def tr_action(client, tid, action):
    """Transmission 暂停/恢复某种子(按数字 id)。复用 409 握手 + Basic auth。"""
    if action not in ("pause", "resume"):
        raise ValueError(f"不支持的操作:{action}")
    method = {"pause": "torrent-stop", "resume": "torrent-start"}[action]
    base = f"http://{(client.get('host') or '').strip()}:{int(client.get('port') or 9091)}/transmission/rpc"
    auth = (client.get("username", "") or "", client.get("password", "") or "")
    if isinstance(tid, str) and tid.lstrip("-").isdigit():   # 前端 data-id 是字符串;Transmission 要数字 id
        tid = int(tid)
    payload = {"method": method, "arguments": {"ids": [tid]}}
    with httpx.Client(timeout=8, auth=auth) as c:
        r = c.post(base, json=payload)
        if r.status_code == 409:                      # CSRF 握手:取 session id 重试
            sid = r.headers.get("X-Transmission-Session-Id", "")
            r = c.post(base, json=payload, headers={"X-Transmission-Session-Id": sid})
        r.raise_for_status()
    return True


_WRITE_ADAPTERS = {"qbittorrent": qb_action, "transmission": tr_action}


def collect(cfg):
    dl_cfg = (cfg or {}).get("downloaders", {}) or {}
    clients = [c for c in (dl_cfg.get("clients", []) or [])
               if isinstance(c, dict) and (c.get("host") or "").strip()]
    if not clients:
        return None                                   # 没配 → 不出页(配置即页面)
    all_t, dl, up, ulb, dlb, free, errors = [], 0, 0, 0, 0, -1, []
    for c in clients:
        try:
            d = _ADAPTERS.get(c.get("type", "qbittorrent"), _qb_fetch)(c)
        except Exception as e:
            print(f"[downloader] {c.get('name') or c.get('host')}: {e}")
            errors.append(c.get("name") or c.get("host") or "?")
            continue
        cname = c.get("name") or c.get("host") or "?"
        for t in d["torrents"]:
            t["client"] = cname               # 仅 App 控制用(按下载器名路由到对应 adapter);Kindle 无视
        all_t += d["torrents"]
        dl += d["dl_speed"]; up += d["up_speed"]; ulb += d["ul_bytes"]; dlb += d["dl_bytes"]
        if free < 0 and d.get("free", -1) >= 0:
            free = d["free"]
    if len(errors) >= len(clients):
        return None                                   # 全部连不上 → 保留上一帧
    all_t.sort(key=lambda t: (_ORDER.get(t["state"], 7), -t["up"], -t["dl"]))
    rows = max(1, int(dl_cfg.get("rows", 8) or 8))
    return {"download": {
        "torrents_raw": all_t[:rows],
        "dl_speed": dl, "up_speed": up, "ul_bytes": ulb, "dl_bytes": dlb, "free": free,
        "active": sum(1 for t in all_t if t["state"] in _ACTIVE),
        "total": len(all_t),
        "errors": errors,                             # 部分下载器离线(全部离线已返回 None)
    }}
