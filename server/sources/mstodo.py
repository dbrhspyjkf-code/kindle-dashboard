"""Microsoft To Do 采集器 + 设备码登录(服务端直采)。

可选数据源:用户在设置网页点【连接】走 OAuth 2.0 设备码流程登录自己的微软账号,
拿到 refresh token 存本地;之后服务端定时用它换 access token,调 Microsoft Graph
读 To Do 列表与任务,归一化成和苹果提醒**完全相同的字段**,渲染时合并(见 build_context)。

设计对应 CLAUDE.md 三铁律:
- 零硬编码:client_id 从配置读(有内置默认值);凭据只存本地。
- 配置即页面:未启用/未登录 → collect 返回 None,不影响其他源。
- 诚实降级:token 失效/网络错/API 非 2xx → 返回 None,绝不抛到主循环。

凭据安全:token 存 data/mstodo_token.json(已被 .gitignore 的 data/ 忽略),权限 600;
任何日志/接口都不输出 token 内容。

登录方案见 docs/mstodo-integration.md。当前内置的是微软官方公开客户端 ID(免注册,
授权页显示 "Microsoft Graph Command Line Tools");维护者注册自有 Azure 应用后,
把 client_id 换成自己的即可(授权页将显示自有应用名)。
"""
import os
import json
import time
import uuid
import threading

import httpx

# 微软官方公开客户端(Graph CLI)。个人账号 + 设备码可用,免注册。
DEFAULT_CLIENT_ID = "14d82eec-204b-4c2f-b7e8-296a70dab67e"
AUTHORITY = "https://login.microsoftonline.com/consumers"   # 个人账号
SCOPE = "Tasks.Read offline_access openid profile"
GRAPH = "https://graph.microsoft.com/v1.0"

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# token 默认跟随 KINDLE_DATA_DIR(与 apple/ccusage 一致):Docker 下落 /data 卷,
# 容器重建/升级不丢登录。KINDLE_MSTODO_TOKEN 仍可单独覆盖(向后兼容)。
_DATA_DIR = os.environ.get("KINDLE_DATA_DIR", os.path.join(_REPO, "data"))
TOKEN_FILE = os.environ.get(
    "KINDLE_MSTODO_TOKEN", os.path.join(_DATA_DIR, "mstodo_token.json"))

_token_lock = threading.RLock()
_sessions = {}                 # 进行中的登录会话 {sid: {state, account?, lists?, error?}}
_sessions_lock = threading.Lock()


# ---------------- token 文件 ----------------
def _load_token():
    with _token_lock:
        try:
            with open(TOKEN_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None


def _save_token(tok):
    with _token_lock:
        os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
        tmp = TOKEN_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(tok, f)
        os.replace(tmp, TOKEN_FILE)
        try:
            os.chmod(TOKEN_FILE, 0o600)
        except Exception:
            pass


def _client_id(cfg):
    return ((cfg or {}).get("mstodo", {}).get("client_id") or "").strip() or DEFAULT_CLIENT_ID


# ---------------- Graph 调用 ----------------
def _graph_get(path, at):
    with httpx.Client(timeout=20) as c:
        r = c.get(GRAPH + path, headers={"Authorization": "Bearer " + at})
    r.raise_for_status()
    return r.json()


def _graph_get_all(path, at):
    """跟随 @odata.nextLink 取完所有分页。"""
    out = []
    url = GRAPH + path + ("&" if "?" in path else "?") + "$top=100"
    with httpx.Client(timeout=20) as c:
        while url:
            r = c.get(url, headers={"Authorization": "Bearer " + at})
            r.raise_for_status()
            j = r.json()
            out.extend(j.get("value", []))
            url = j.get("@odata.nextLink")
    return out


# ---------------- access token(过期才刷新,刷新即轮换) ----------------
def _ensure_access_token(cfg):
    with _token_lock:
        tok = _load_token()
        if not tok or not tok.get("refresh_token"):
            return None
        now = time.time()
        if tok.get("access_token") and tok.get("access_token_exp", 0) > now + 60:
            return tok["access_token"]
        try:
            with httpx.Client(timeout=20) as c:
                r = c.post(f"{AUTHORITY}/oauth2/v2.0/token", data={
                    "grant_type": "refresh_token",
                    "client_id": _client_id(cfg),
                    "refresh_token": tok["refresh_token"],
                    "scope": SCOPE,
                })
            j = r.json()
        except Exception as e:
            print(f"[mstodo] refresh: {e}")
            return None
        if "access_token" not in j:
            print(f"[mstodo] refresh failed: {j.get('error')}")
            return None
        tok["access_token"] = j["access_token"]
        tok["access_token_exp"] = now + int(j.get("expires_in", 3600))
        if j.get("refresh_token"):          # 微软可能轮换 refresh token,带了就覆盖保存
            tok["refresh_token"] = j["refresh_token"]
        _save_token(tok)
        return tok["access_token"]


def _due_iso(dd):
    """微软 dueDateTime → 规范化 ISO:截断 7 位小数到 6 位 + 给 UTC 补时区标记。
    微软默认返回 UTC(timeZone='UTC')。原来只取 dateTime 字符串、丢了时区,下游 reminder_due_date
    又当本地时间取日期 → 傍晚后到期(UTC 日期比北京早一天)的任务被算早一天、误判过期、从"今天/即将"
    区消失。补上 UTC 标记后,交由 reminder_due_date 按看板时区换算到正确的本地日。"""
    s = ((dd or {}).get("dateTime") or "").strip()
    if not s:
        return None
    tz = ((dd or {}).get("timeZone") or "UTC").upper()
    if "." in s:                      # 微软给 7 位小数,Python datetime 只认到微秒 6 位,多了会解析失败
        head, frac = s.split(".", 1)
        digits = ""
        for ch in frac:
            if ch.isdigit():
                digits += ch
            else:
                break
        s = head + "." + digits[:6] + frac[len(digits):]
    tail = s[11:]                     # T 之后的时间部分
    if tz == "UTC" and "Z" not in tail and "+" not in tail and "-" not in tail:
        s += "+00:00"                 # 标记 UTC,下游按看板时区换算到本地日
    return s


def _normalize(t, lst):
    """归一化为和苹果提醒相同的字段(下游零改动)。"""
    due = _due_iso(t.get("dueDateTime"))
    return {
        "title": t.get("title", ""),
        "completed": t.get("status") == "completed",
        "dueDate": due or None,
        "priority": 1 if t.get("importance") == "high" else 0,
        "list": lst.get("displayName", ""),
        "source": "mstodo",          # 内部留存,面板不展示、不据此区分(见合并策略)
        "id": t.get("id"),
        "list_id": lst.get("id"),
    }


# ---------------- 采集主入口 ----------------
def collect(cfg):
    m = (cfg or {}).get("mstodo", {})
    if not m.get("enabled"):
        return None
    at = _ensure_access_token(cfg)
    if not at:
        return None
    try:
        lists = _graph_get("/me/todo/lists", at)
    except Exception as e:
        print(f"[mstodo] lists: {e}")
        return None
    reminders = []
    for lst in lists.get("value", []):
        if lst.get("wellknownListName") == "flaggedEmails" and not m.get("include_flagged_emails"):
            continue
        try:
            for t in _graph_get_all(f"/me/todo/lists/{lst['id']}/tasks", at):
                reminders.append(_normalize(t, lst))
        except Exception as e:
            print(f"[mstodo] tasks {lst.get('displayName')}: {e}")
            continue
    return {"reminders_mstodo": reminders}


# ---------------- 设备码登录(给设置网页) ----------------
def _set_session(sid, **kw):
    with _sessions_lock:
        if sid in _sessions:
            _sessions[sid].update(kw)


def _probe(at):
    """登录成功后取账号名 + 列表数,供网页显示(非敏感)。"""
    account, lists_n = "", 0
    try:
        me = _graph_get("/me", at)
        account = me.get("userPrincipalName") or me.get("displayName") or ""
    except Exception:
        pass
    try:
        lst = _graph_get("/me/todo/lists", at)
        lists_n = len(lst.get("value", []))
    except Exception:
        pass
    return account, lists_n


def _poll_login(sid, client_id, dc):
    interval = dc.get("interval", 5)
    deadline = time.time() + dc.get("expires_in", 900)
    while time.time() < deadline:
        time.sleep(interval)
        try:
            with httpx.Client(timeout=20) as c:
                r = c.post(f"{AUTHORITY}/oauth2/v2.0/token", data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "client_id": client_id,
                    "device_code": dc["device_code"],
                })
            j = r.json()
        except Exception as e:
            _set_session(sid, state="error", error=str(e))
            return
        if "access_token" in j:
            account, lists_n = _probe(j["access_token"])
            _save_token({
                "client_id": client_id, "authority": AUTHORITY, "scope": SCOPE,
                "refresh_token": j.get("refresh_token"),
                "access_token": j["access_token"],
                "access_token_exp": time.time() + int(j.get("expires_in", 3600)),
                "account": account,
            })
            _set_session(sid, state="success", account=account, lists=lists_n)
            return
        err = j.get("error")
        if err == "authorization_pending":
            continue
        if err == "slow_down":
            interval += 5
            continue
        _set_session(sid, state="error", error=j.get("error_description") or err)
        return
    _set_session(sid, state="expired")


def login_start(cfg):
    """发起设备码登录,返回 {session,user_code,verification_uri,expires_in,interval};
    后台线程轮询,成功即写 token 文件。"""
    client_id = _client_id(cfg)
    with httpx.Client(timeout=20) as c:
        r = c.post(f"{AUTHORITY}/oauth2/v2.0/devicecode",
                   data={"client_id": client_id, "scope": SCOPE})
    dc = r.json()
    if "user_code" not in dc:
        raise RuntimeError(dc.get("error_description") or dc.get("error") or "设备码申请失败")
    sid = uuid.uuid4().hex
    with _sessions_lock:
        _sessions[sid] = {"state": "pending"}
    threading.Thread(target=_poll_login, args=(sid, client_id, dc), daemon=True).start()
    return {
        "session": sid,
        "user_code": dc["user_code"],
        "verification_uri": dc.get("verification_uri") or dc.get("verification_url"),
        "expires_in": dc.get("expires_in", 900),
        "interval": dc.get("interval", 5),
    }


def login_status(sid):
    with _sessions_lock:
        s = _sessions.get(sid)
    return dict(s) if s else {"state": "error", "error": "无效会话"}


def logout():
    with _token_lock:
        try:
            os.remove(TOKEN_FILE)
        except FileNotFoundError:
            pass
        except Exception as e:
            print(f"[mstodo] logout: {e}")


def state():
    """给设置网页:是否已连接 + 账号名(非敏感)。"""
    tok = _load_token()
    return {"connected": bool(tok and tok.get("refresh_token")),
            "account": (tok or {}).get("account", "")}
