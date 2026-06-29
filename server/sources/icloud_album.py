"""iCloud 公开共享相册采集(匿名,不需登录)。

公开链接形如 https://www.icloud.com/sharedalbum/#B0Abc...,# 后是相册 token。
两步接口:
  1. POST {host}/{token}/sharedstreams/webstream  body {"streamCtag": null} → 照片清单
  2. POST {host}/{token}/sharedstreams/webasseturls body {"photoGuids":[...]} → 下载 URL
host 由 token 首字符定分区,首次可能 330 重定向到正确分区(见 fetch_album_photos)。
本模块只负责取数+解析;下载/抖动在 image_proc,轮播在 build_context。
"""
import string
import httpx

_BASE = ".icloud-content.com"  # 兜底,正常用 url_location 给的主机


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
