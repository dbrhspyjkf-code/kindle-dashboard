"""数据契约验证:empty_context() 完整且各页可降级渲染。"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from server.render import contract  # noqa: E402


def test_empty_context_has_all_top_keys():
    ctx = contract.empty_context()
    for k in ("now", "time_hm", "clock", "battery", "home", "ai", "device"):
        assert k in ctx, f"缺顶层字段 {k}"
    assert ctx["printer"] is None  # 默认无打印机


def test_pages_sections_resolve():
    """PAGES 引用的 section 都能在 empty_context 找到对应数据。"""
    ctx = contract.empty_context()
    for page, meta in contract.PAGES.items():
        sec = meta["section"]
        # printer 段是 None(降级),其余必须是 dict
        if sec == "printer":
            continue
        assert isinstance(ctx[sec], dict), f"{page} 的段 {sec} 缺失"


def test_empty_lists_are_lists():
    ctx = contract.empty_context()
    assert ctx["home"]["reminders"]["overdue"] == []
    assert ctx["home"]["calendar"] == []
    assert ctx["ai"]["chart"] == []


def test_battery_has_flag():
    ctx = contract.empty_context()
    assert ctx["battery"]["has"] is False


def test_album_page_registered():
    assert "album" in contract.PAGES
    assert contract.PAGES["album"]["needs"] == ["album"]


def test_empty_album_shape():
    a = contract.empty_album()
    assert a["photo"]["src"] == ""
    assert a["total"] == 0


def test_empty_context_has_album():
    assert "album" in contract.empty_context()


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  ✓ {fn.__name__}")
    print(f"\n{len(fns)} passed")
