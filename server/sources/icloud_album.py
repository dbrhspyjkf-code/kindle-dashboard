"""iCloud 公开共享相册采集(匿名,不需登录)。

公开链接形如 https://www.icloud.com/sharedalbum/#B0Abc...,# 后是相册 token。
两步接口:
  1. POST {host}/{token}/sharedstreams/webstream  body {"streamCtag": null} → 照片清单
  2. POST {host}/{token}/sharedstreams/webasseturls body {"photoGuids":[...]} → 下载 URL
host 由 token 首字符定分区,首次可能 330 重定向到正确分区(见 fetch_album_photos)。
本模块只负责取数+解析;下载/抖动在 image_proc,轮播在 build_context。
"""
import os
import string
import httpx
from server.sources import album_image
from server.config import schema


def parse_token(url: str) -> str:
    """取 # 后 token(到 ? 或末尾)。无 # 返回空。"""
    url = (url or "").strip()
    if "#" not in url:
        return ""
    tok = url.split("#", 1)[1]
    tok = tok.split("?", 1)[0].split("/", 1)[0]
    return tok.strip()


def partition_host(token: str) -> str:
    """token 首字符 → p{NN}-sharedstreams.icloud.com。A→01,B→02...(大写字母序,1 基)。
    非字母或空 → 回落 p01。"""
    t = (token or "").strip()
    n = 1
    if t and t[0].upper() in string.ascii_uppercase:
        n = string.ascii_uppercase.index(t[0].upper()) + 1
    return f"p{n:02d}-sharedstreams.icloud.com"


def parse_webstream(data: dict) -> list:
    """webstream JSON → [{guid, checksums:[最大尺寸 checksum]}]。坏数据返回 []。"""
    out = []
    for p in (data or {}).get("photos", []) or []:
        guid = p.get("photoGuid")
        derivs = (p.get("derivatives") or {})
        best, best_area = None, -1
        for d in derivs.values():
            try:
                area = int(d.get("width", 0)) * int(d.get("height", 0))
            except (TypeError, ValueError):
                area = 0
            cks = d.get("checksum")
            if cks and area >= best_area:
                best, best_area = cks, area
        if guid and best:
            out.append({"guid": guid, "checksums": [best]})
    return out


def parse_asset_urls(data: dict) -> dict:
    """webasseturls JSON → {checksum: 完整下载 URL}。"""
    out = {}
    for cks, it in ((data or {}).get("items") or {}).items():
        loc = it.get("url_location")
        path = it.get("url_path")
        if loc and path:
            out[cks] = f"https://{loc}{path}"
    return out


def build_photo_list(stream: list, assets: dict) -> list:
    """合并 stream 顺序 + asset url。拿不到 url 的跳过。"""
    out = []
    for s in stream or []:
        cks = (s.get("checksums") or [None])[0]
        url = (assets or {}).get(cks)
        if cks and url:
            out.append({"guid": s.get("guid"), "checksum": cks, "url": url})
    return out


def _post(client, host, token, endpoint, body):
    """构建 POST 请求到 iCloud 相册分区服务。"""
    url = f"https://{host}/{token}/sharedstreams/{endpoint}"
    return client.post(url, json=body, headers={"Content-Type": "text/plain"}, timeout=15)


def fetch_album_photos(shared_url: str, *, client=None) -> list:
    """端到端拉取公开共享相册照片列表。任何失败 → [](诚实降级)。"""
    token = parse_token(shared_url)
    if not token:
        return []
    own = client is None
    client = client or httpx.Client(follow_redirects=False)
    try:
        host = partition_host(token)
        # webstream:首发可能 330 重定向到正确分区
        r = _post(client, host, token, "webstream", {"streamCtag": None})
        if getattr(r, "status_code", 200) == 330:
            host = r.headers.get("X-Apple-MMe-Host") or host
            r = _post(client, host, token, "webstream", {"streamCtag": None})
        if r.status_code != 200:
            return []
        stream = parse_webstream(r.json())
        if not stream:
            return []
        guids = [s["guid"] for s in stream]
        ra = _post(client, host, token, "webasseturls", {"photoGuids": guids})
        if ra.status_code != 200:
            return []
        assets = parse_asset_urls(ra.json())
        return build_photo_list(stream, assets)
    except Exception as e:
        print(f"[icloud_album] fetch failed: {e}")
        return []
    finally:
        if own:
            try:
                client.close()
            except Exception:
                pass


def _cache_dir(cfg) -> str:
    data_dir = os.environ.get("KINDLE_DATA_DIR",
                              os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
                                  os.path.abspath(__file__)))), "data"))
    return os.path.join(data_dir, "album")


def _download(url: str) -> bytes:
    with httpx.Client(timeout=20, follow_redirects=True) as c:
        return c.get(url).content


def collect(cfg: dict):
    """拉公开相册 → 逐张下载+处理+缓存。无链接 None;全失败 None(降级保留上帧)。"""
    acfg = (cfg or {}).get("album", {}) or {}
    url = (acfg.get("shared_url") or "").strip()
    if not url:
        return None
    photos = fetch_album_photos(url)
    if not photos:
        return None
    try:
        max_n = int(acfg.get("max_photos", 200) or 200)
    except (TypeError, ValueError):
        max_n = 200
    size = schema.resolve_render_size((cfg or {}).get("server", {}) or {})
    cache_dir = _cache_dir(cfg)
    out = []
    for p in photos[:max_n]:
        guid = p.get("guid")
        cached = os.path.join(cache_dir, album_image.cache_filename(guid, size))
        if os.path.exists(cached):
            out.append({"guid": guid, "path": cached})
            continue
        try:
            raw = _download(p["url"])
        except Exception as e:
            print(f"[icloud_album] download failed {guid}: {e}")
            continue
        path = album_image.process_to_cache(raw, guid, size, cache_dir)
        if path:
            out.append({"guid": guid, "path": path})
    if not out:
        return None
    return {"album_photos": out}
