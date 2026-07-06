"""本地文件夹相册采集。读取指定目录下的图片文件,处理为 E-ink 格式并缓存。"""
import os
import re
from server.sources import album_image
from server.config import schema

SUPPORTED_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tiff", ".tif", ".gif"}


def _image_files(folder: str) -> list:
    """返回文件夹内所有支持格式图片的绝对路径列表(按文件名排序)。"""
    try:
        entries = sorted(os.listdir(folder))
    except OSError:
        return []
    return [
        os.path.join(folder, f)
        for f in entries
        if os.path.splitext(f)[1].lower() in SUPPORTED_EXT
    ]


def _file_guid(filepath: str) -> str:
    """用文件名(不含扩展名)作为 guid;特殊字符替换为下划线。"""
    name = os.path.splitext(os.path.basename(filepath))[0]
    return re.sub(r"[^A-Za-z0-9_-]", "_", name)


def _cache_dir(cfg) -> str:
    data_dir = os.environ.get(
        "KINDLE_DATA_DIR",
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))), "data"),
    )
    return os.path.join(data_dir, "album")


def collect(cfg: dict):
    """扫描本地文件夹 → 处理+缓存图片。未配置路径或无可用图片 → None(诚实降级)。"""
    acfg = (cfg or {}).get("album", {}) or {}
    folder = (acfg.get("folder_path") or "").strip()
    if not folder:
        return None
    folder = os.path.expanduser(folder)
    if not os.path.isdir(folder):
        print(f"[local_album] folder not found: {folder}")
        return None
    try:
        max_n = int(acfg.get("max_photos", 200) or 200)
    except (TypeError, ValueError):
        max_n = 200
    size = schema.resolve_render_size((cfg or {}).get("server", {}) or {})
    cache_dir = _cache_dir(cfg)
    files = _image_files(folder)[:max_n]
    if not files:
        return None
    out = []
    for fp in files:
        guid = _file_guid(fp)
        cached = os.path.join(cache_dir, album_image.cache_filename(guid, size))
        if os.path.exists(cached):
            out.append({"guid": guid, "path": cached})
            continue
        try:
            with open(fp, "rb") as f:
                raw = f.read()
        except OSError as e:
            print(f"[local_album] read failed {fp}: {e}")
            continue
        path = album_image.process_to_cache(raw, guid, size, cache_dir)
        if path:
            out.append({"guid": guid, "path": path})
    if not out:
        return None
    # 清理不再在文件夹中的孤儿缓存文件,防止磁盘无限增长
    try:
        keep = {os.path.basename(p["path"]) for p in out}
        for fname in os.listdir(cache_dir):
            if fname.endswith(".png") and fname not in keep:
                try:
                    os.remove(os.path.join(cache_dir, fname))
                except Exception:
                    pass
    except Exception:
        pass
    return {"album_photos": out}
