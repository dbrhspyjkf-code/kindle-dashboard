import os, sys, io
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from server.sources import album_image as ai_img  # noqa: E402
from PIL import Image


def _png_bytes(w=400, h=300, color=(200, 50, 50)):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


def test_cache_filename_stable():
    assert ai_img.cache_filename("g1", (800, 600)) == "g1_800x600_v1.png"


def test_process_to_cache_outputs_grayscale_sized(tmp_path):
    raw = _png_bytes()
    path = ai_img.process_to_cache(raw, "g1", (800, 600), str(tmp_path))
    assert path and os.path.exists(path)
    im = Image.open(path)
    assert im.size == (800, 600)
    # 抖动后是 1-bit 或 L 模式灰度,绝非彩色 RGB
    assert im.mode in ("L", "1", "P")


def test_process_to_cache_is_cached(tmp_path):
    raw = _png_bytes()
    p1 = ai_img.process_to_cache(raw, "g1", (800, 600), str(tmp_path))
    mtime1 = os.path.getmtime(p1)
    # 第二次:命中缓存,不重写文件(mtime 不变)
    p2 = ai_img.process_to_cache(_png_bytes(color=(0, 0, 0)), "g1", (800, 600), str(tmp_path))
    assert p1 == p2
    assert os.path.getmtime(p2) == mtime1


def test_process_to_cache_bad_bytes(tmp_path):
    assert ai_img.process_to_cache(b"not an image", "g9", (800, 600), str(tmp_path)) is None


def test_cache_filename_path_traversal():
    """恶意 guid 不得在文件名中产生 / 或 .."""
    result = ai_img.cache_filename("../../etc/passwd", (800, 600))
    assert "/" not in result
    assert ".." not in result


def test_cache_filename_sanitize_leaves_normal_guid():
    """普通 UUID 类 guid 净化后不变。"""
    assert ai_img.cache_filename("g1", (800, 600)) == "g1_800x600_v1.png"


def test_process_to_cache_tmp_cleaned_on_failure(tmp_path, monkeypatch):
    """处理失败时 .tmp 文件必须被清理。"""
    raw = _png_bytes()

    # 让 im.save 抛出,但 tmp 文件已被创建
    original_save = None

    def _bad_save(self, fp, *args, **kwargs):
        # 先写入一些字节模拟部分写入
        with open(fp, "wb") as f:
            f.write(b"partial")
        raise OSError("disk full")

    from PIL import Image as PILImage
    monkeypatch.setattr(PILImage.Image, "save", _bad_save)
    path = ai_img.process_to_cache(raw, "fail_guid", (800, 600), str(tmp_path))
    assert path is None
    # .tmp 文件不应残留
    tmp_files = [f for f in os.listdir(str(tmp_path)) if f.endswith(".tmp")]
    assert tmp_files == []
