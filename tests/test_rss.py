"""RSS 资讯采集器验证。可直接 `python3 tests/test_rss.py` 跑,也兼容 pytest。"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from server.sources import rss  # noqa: E402


SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<title>AI HOT — 精选</title>
<item>
  <title><![CDATA[baoyu-design 本地动画视频导出]]></title>
  <link>https://x.com/dotey/status/1</link>
  <description><![CDATA[baoyu-design(本地运行 Claude Design 的 Skill)新增动画视频导出功能。<b>正文</b>]]></description>
  <author>noreply@aihot.virxact.com (X:宝玉 (@dotey))</author>
  <pubDate>Wed, 17 Jun 2026 00:21:40 GMT</pubDate>
  <guid>g1</guid>
</item>
<item>
  <title>Anthropic 份额首超 OpenAI</title>
  <link>https://techcrunch.com/2</link>
  <description>Anthropic 5月企业AI订阅市场份额达41%。</description>
  <author>noreply@aihot.virxact.com (TechCrunch:AI(RSS))</author>
  <pubDate>Tue, 16 Jun 2026 22:34:17 GMT</pubDate>
  <guid>g2</guid>
</item>
</channel></rss>"""


def test_parse_basic():
    items = rss.parse_rss(SAMPLE, "AIHOT")
    assert len(items) == 2
    a = items[0]
    assert a["title"] == "baoyu-design 本地动画视频导出"
    assert a["summary"].startswith("baoyu-design")
    assert "<b>" not in a["summary"] and "正文" in a["summary"]   # 去 HTML 标签
    assert a["ts"] > 0
    assert a["guid"] == "g1"


def test_source_name_nested_parens():
    """author 括号内含嵌套括号(@dotey)也要完整取出。"""
    items = rss.parse_rss(SAMPLE, "AIHOT")
    assert items[0]["source"] == "X:宝玉 (@dotey)"
    assert items[1]["source"] == "TechCrunch:AI(RSS)"


def test_source_name_fallback():
    """author 无括号 → 退回 feed 名;feed 名也空 → channel 名。"""
    assert rss._source_name("plain@x.com", "我的源", "频道") == "我的源"
    assert rss._source_name("", "", "频道标题") == "频道标题"


def test_category_empty_when_absent():
    assert rss.parse_rss(SAMPLE)[0]["category"] == ""    # AIHOT 无 category


def test_bad_and_empty_xml():
    assert rss.parse_rss("") == []
    assert rss.parse_rss("<rss><channel></channel></rss>") == []
    assert rss.parse_rss("总之不是 XML <item><title>") == []   # 无闭合 item,不抛


def test_collect_no_feeds_returns_none():
    assert rss.collect({}) is None
    assert rss.collect({"news": {"feeds": []}}) is None
    assert rss.collect({"news": {"feeds": [{"url": ""}]}}) is None


def test_collect_all_fail_returns_none(monkeypatch=None):
    """所有 feed 拉取失败 → None(保留上一帧,不空屏)。"""
    import httpx

    class _BoomClient:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, *a, **k): raise httpx.ConnectError("boom")

    orig = rss.httpx.Client
    rss.httpx.Client = _BoomClient
    try:
        assert rss.collect({"news": {"feeds": [{"url": "http://x/feed.xml"}]}}) is None
    finally:
        rss.httpx.Client = orig


def test_pick_index_time_mode_cycles():
    """按时间模式:随时间桶递增并循环,每条都轮得到。"""
    n, period = 3, 10
    seen = set()
    for sec in range(0, 30, 10):           # 三个桶
        seen.add(rss.pick_index(n, "time", sec, period))
    assert seen == {0, 1, 2}               # 0..n-1 全覆盖
    assert rss.pick_index(n, "time", 30, period) == 0   # 第 4 桶回到 0(循环)


def test_pick_index_stable_within_bucket():
    """同一时间桶内多次调用结果一致(渲染不抖)。"""
    n, period = 50, 60
    a = rss.pick_index(n, "random", 120.0, period)
    b = rss.pick_index(n, "random", 179.9, period)       # 同桶 [120,180)
    assert a == b
    assert 0 <= a < n


def test_pick_index_random_changes_across_buckets():
    n, period = 50, 60
    vals = {rss.pick_index(n, "random", b * 60, period) for b in range(8)}
    assert len(vals) > 1                   # 跨桶有变化(不是恒定一条)


def test_pick_index_empty():
    assert rss.pick_index(0, "time", 123, 60) == 0       # n=0 不崩


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  ✓ {fn.__name__}")
    print(f"\n{len(fns)} passed")
