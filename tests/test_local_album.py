"""本地文件夹相册采集验证。"""
import io
import os
import sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PIL import Image
from server.sources import local_album as la  # noqa: E402


def _make_img(path, size=(400, 300), mode="RGB", fmt="PNG"):
    buf = io.BytesIO()
    Image.new(mode, size).save(buf, fmt)
    path.write_bytes(buf.getvalue())


def test_image_files_sorted(tmp_path):
    (tmp_path / "b.jpg").write_bytes(b"")
    (tmp_path / "a.png").write_bytes(b"")
    (tmp_path / "c.txt").write_bytes(b"")  # ignored
    result = la._image_files(str(tmp_path))
    assert [os.path.basename(f) for f in result] == ["a.png", "b.jpg"]


def test_image_files_missing_dir():
    assert la._image_files("/nonexistent/path/xyz") == []


def test_file_guid_safe():
    assert la._file_guid("/home/user/my photo (1).jpg") == "my_photo__1_"
    assert la._file_guid("/a/b/IMG-2025.png") == "IMG-2025"


def test_collect_no_path_returns_none():
    assert la.collect({}) is None
    assert la.collect({"album": {"folder_path": ""}}) is None
    assert la.collect({"album": {}}) is None


def test_collect_nonexistent_folder_returns_none():
    assert la.collect({"album": {"folder_path": "/nonexistent/xyz/abc"}}) is None


def test_collect_empty_folder_returns_none(tmp_path):
    (tmp_path / "notes.txt").write_bytes(b"text")  # 无图片
    result = la.collect({"album": {"folder_path": str(tmp_path)},
                         "server": {"kindle_model": "base"}})
    assert result is None


def test_collect_processes_images(tmp_path, monkeypatch):
    monkeypatch.setattr(la, "_cache_dir", lambda cfg: str(tmp_path / "cache"))
    img_dir = tmp_path / "photos"
    img_dir.mkdir()
    _make_img(img_dir / "photo1.jpg")
    _make_img(img_dir / "photo2.png")

    cfg = {"album": {"folder_path": str(img_dir), "max_photos": 10},
           "server": {"kindle_model": "base"}}
    out = la.collect(cfg)
    assert out is not None
    assert len(out["album_photos"]) == 2
    for p in out["album_photos"]:
        assert os.path.exists(p["path"])


def test_collect_cache_hit_skips_reprocess(tmp_path, monkeypatch):
    """已缓存的图片不会被重复处理。"""
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr(la, "_cache_dir", lambda cfg: str(cache_dir))
    img_dir = tmp_path / "photos"
    img_dir.mkdir()
    _make_img(img_dir / "photo1.jpg")

    cfg = {"album": {"folder_path": str(img_dir), "max_photos": 10},
           "server": {"kindle_model": "base"}}
    # 第一次:处理并缓存
    out1 = la.collect(cfg)
    assert out1 is not None
    cached_path = out1["album_photos"][0]["path"]
    mtime_before = os.path.getmtime(cached_path)

    # 第二次:命中缓存,文件不变
    out2 = la.collect(cfg)
    assert out2 is not None
    assert os.path.getmtime(cached_path) == mtime_before


def test_collect_prunes_orphan_cache(tmp_path, monkeypatch):
    """文件夹内移除的照片对应缓存文件应被清理。"""
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr(la, "_cache_dir", lambda cfg: str(cache_dir))
    cache_dir.mkdir()
    # 预置孤儿缓存文件
    orphan = cache_dir / "old_guid_800x600_v1.png"
    orphan.write_bytes(b"stale")

    img_dir = tmp_path / "photos"
    img_dir.mkdir()
    _make_img(img_dir / "photo1.jpg")

    cfg = {"album": {"folder_path": str(img_dir), "max_photos": 10},
           "server": {"kindle_model": "base"}}
    out = la.collect(cfg)
    assert out is not None
    assert not orphan.exists()


def test_collect_no_prune_on_failure(tmp_path, monkeypatch):
    """扫描结果为空(返回 None)时,已有缓存文件不应被删除。"""
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr(la, "_cache_dir", lambda cfg: str(cache_dir))
    cache_dir.mkdir()
    existing = cache_dir / "good_800x600_v1.png"
    existing.write_bytes(b"last_good")

    # 空文件夹 → collect 返回 None
    img_dir = tmp_path / "empty"
    img_dir.mkdir()

    cfg = {"album": {"folder_path": str(img_dir)}, "server": {"kindle_model": "base"}}
    result = la.collect(cfg)
    assert result is None
    assert existing.exists()


def test_collect_max_photos_limit(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr(la, "_cache_dir", lambda cfg: str(cache_dir))
    img_dir = tmp_path / "photos"
    img_dir.mkdir()
    for i in range(5):
        _make_img(img_dir / f"photo{i}.jpg")

    cfg = {"album": {"folder_path": str(img_dir), "max_photos": 3},
           "server": {"kindle_model": "base"}}
    out = la.collect(cfg)
    assert out is not None
    assert len(out["album_photos"]) == 3


def test_collect_tilde_expansion(tmp_path, monkeypatch):
    """folder_path 支持 ~ 展开。"""
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr(la, "_cache_dir", lambda cfg: str(cache_dir))
    img_dir = tmp_path / "photos"
    img_dir.mkdir()
    _make_img(img_dir / "x.png")

    # 用绝对路径但通过 monkeypatch expanduser
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(img_dir) if p == "~/myphotos" else p)
    cfg = {"album": {"folder_path": "~/myphotos", "max_photos": 10},
           "server": {"kindle_model": "base"}}
    out = la.collect(cfg)
    assert out is not None
