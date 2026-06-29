"""端到端渲染冒烟测试:降级空数据 + style_a → 每页出有效 PNG。
验证 契约 + 风格调度 + 渲染管线 串通,且缺数据也能出图(诚实降级)。
需要 Chrome/Chromium;无则跳过。可直接 `python3 tests/test_render_smoke.py`。
"""
import io
import os
import sys

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from server.render import styles, pipeline           # noqa: E402
from server.render.contract import empty_context, PAGES  # noqa: E402

STYLE = "style_a"


def _chrome_or_skip():
    if not pipeline.find_chrome():
        try:
            import pytest
            pytest.skip("无 Chrome/Chromium,跳过渲染冒烟")
        except ImportError:
            print("  ⚠ 跳过:无 Chrome/Chromium")
            raise SystemExit(0)


def test_style_a_present():
    assert STYLE in styles.list_styles(), "style_a 风格包缺失"


def test_render_all_pages_smoke():
    _chrome_or_skip()
    rc = pipeline.RenderConfig()          # 默认 800x600 rotate270 灰度
    ctx = empty_context()
    failures = []
    rendered = 0
    for page in PAGES:
        if not styles.has_page(STYLE, page):
            continue
        try:
            html = styles.render_page(STYLE, page, ctx)
            png = pipeline.render_html_to_png(html, rc)
            img = Image.open(io.BytesIO(png))
            # 横屏 800x600 旋转 270 → 竖屏 600x800
            assert img.size == (rc.height, rc.width), f"{page} 尺寸 {img.size}"
            assert img.mode == "L", f"{page} 非灰度"
            rendered += 1
        except Exception as e:
            failures.append(f"{page}: {type(e).__name__}: {e}")
    assert not failures, "降级渲染失败:\n" + "\n".join(failures)
    assert rendered >= 1


def test_render_every_style_every_page_smoke():
    """遍历所有风格 × 各自拥有的页,空数据降级渲染都要出图、尺寸对、灰度、不报错。
    覆盖全部风格的 ha 页等新模板(配置即页面缺数据也不崩)。"""
    _chrome_or_skip()
    rc = pipeline.RenderConfig()          # 默认 800x600 rotate270 灰度
    ctx = empty_context()
    failures = []
    checked = 0
    for style in styles.list_styles():
        for page in PAGES:
            if not styles.has_page(style, page):
                continue
            try:
                png = pipeline.render_html_to_png(styles.render_page(style, page, ctx), rc)
                img = Image.open(io.BytesIO(png))
                assert img.size == (rc.height, rc.width), f"{style}/{page} 尺寸 {img.size}"
                assert img.mode == "L", f"{style}/{page} 非灰度"
                checked += 1
            except Exception as e:
                failures.append(f"{style}/{page}: {type(e).__name__}: {e}")
    assert not failures, "风格×页降级渲染失败:\n" + "\n".join(failures)
    assert checked >= len(styles.list_styles()), "渲染页数异常偏少"


def test_style_a_album_renders():
    ctx = empty_context()
    assert styles.has_page("style_a", "album")
    html = styles.render_page("style_a", "album", ctx)   # 降级(空 src)也要出 HTML 不报错
    assert "<" in html and len(html) > 50


def test_style_a_album_renders_with_photo():
    ctx = empty_context()
    ctx["album"]["photo"]["src"] = "data:image/png;base64,iVBORw0KGgo="
    ctx["album"]["total"] = 3
    ctx["album"]["index"] = 1
    html = styles.render_page("style_a", "album", ctx)
    assert "data:image/png;base64" in html


if __name__ == "__main__":
    test_style_a_present()
    print("  ✓ test_style_a_present")
    test_render_all_pages_smoke()
    print("  ✓ test_render_all_pages_smoke")
    test_render_every_style_every_page_smoke()
    print("  ✓ test_render_every_style_every_page_smoke")
    test_style_a_album_renders()
    print("  ✓ test_style_a_album_renders")
    test_style_a_album_renders_with_photo()
    print("  ✓ test_style_a_album_renders_with_photo")
    print("\nok")
