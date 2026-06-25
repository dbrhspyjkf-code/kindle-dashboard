"""RSS 资讯采集(通用 pull 直采)。默认订 AIHOT,可订任意 RSS 2.0 源。

和天气同型:collect(cfg) 返回 {"news_items": [...]} 或 None(降级,保留上一帧)。
不引第三方 RSS 库,用标准库 re + 已有依赖 httpx,轻量可控。
轮播在 build_context 里做(无状态时间分桶),本模块只负责取数+解析+排序。
"""
import re
import html
import random
from email.utils import parsedate_to_datetime

import httpx

_MAX_ITEMS = 80          # 合并后上限,防爆(够轮播,远超一屏)


def _source_name(author: str, feed_name: str, channel_title: str) -> str:
    """author='noreply@x (X:宝玉 (@dotey))' → 取最外层括号内;退回 feed 名 / channel 名。"""
    m = re.search(r"\(([^()]*(?:\([^()]*\)[^()]*)*)\)", author or "")
    if m and m.group(1).strip():
        return m.group(1).strip()
    return (feed_name or channel_title or "").strip()


def parse_rss(xml: str, feed_name: str = "") -> list:
    """解析 RSS 2.0 → [{title, summary, source, category, link, guid, ts}]。坏/空 XML 返回 []。"""
    items = []
    ch_title = ""
    mt = re.search(r"<channel>.*?<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", xml or "", re.S)
    if mt:
        ch_title = html.unescape(mt.group(1)).strip()
    for raw in re.findall(r"<item[ >].*?</item>", xml or "", re.S):
        def g(tag):
            m = re.search(rf"<{tag}[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</{tag}>", raw, re.S)
            return html.unescape(m.group(1)).strip() if m else ""
        title = g("title")
        if not title:
            continue
        ts = 0.0
        try:
            ts = parsedate_to_datetime(g("pubDate")).timestamp()
        except Exception:
            pass
        items.append({
            "title": title,
            "summary": re.sub(r"<[^>]+>", "", g("description")).strip(),  # 去残留 HTML 标签
            "source": _source_name(g("author"), feed_name, ch_title),
            "category": g("category"),    # feed 无则空串(诚实降级,模板据此决定显不显)
            "link": g("link"),
            "guid": g("guid") or g("link") or title,
            "ts": ts,
        })
    return items


def pick_index(n: int, mode: str, ts: float, period: int) -> int:
    """无状态轮播选条:按时间分桶。同一桶内结果稳定(渲染不抖),跨桶推进。
    mode='time' → 按时间顺序循环(items 已新→旧);否则随机(每桶伪随机一条)。"""
    if n <= 0:
        return 0
    period = max(5, int(period or 5))
    bucket = int(ts) // period
    if mode == "time":
        return bucket % n
    return random.Random(bucket).randrange(n)


def collect(cfg: dict):
    feeds = ((cfg or {}).get("news", {}) or {}).get("feeds", []) or []
    urls = [((f.get("url") or "").strip(), (f.get("name") or "").strip())
            for f in feeds if isinstance(f, dict)]
    urls = [(u, n) for u, n in urls if u]
    if not urls:
        return None                       # 没配 feed → 不出页(配置即页面)
    all_items, seen = [], set()
    for url, name in urls:
        try:
            with httpx.Client(timeout=10, follow_redirects=True) as c:
                xml = c.get(url, headers={"User-Agent": "kindle-dash/1.0"}).text
        except Exception as e:
            print(f"[rss] {url}: {e}")
            continue
        for it in parse_rss(xml, name):
            if it["guid"] in seen:
                continue
            seen.add(it["guid"])
            all_items.append(it)
    if not all_items:
        return None                       # 全失败 → 保留上一帧(_merge 不覆盖 None)
    all_items.sort(key=lambda x: x["ts"], reverse=True)   # 新→旧
    return {"news_items": all_items[:_MAX_ITEMS]}
