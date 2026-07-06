"""相册图片处理:下载得到的原图 → 适配 E-ink(缩放+灰度+Floyd–Steinberg 抖动)→ 缓存 PNG。

Kindle 是灰度屏,彩色照片必须抖动才不糊。文件名带 guid+尺寸+版本号,便于去重与缓存失效。
"""
import io
import os
import re
from PIL import Image

_VERSION = "v1"     # 处理算法版本;改算法时 +1 让旧缓存失效


def cache_filename(guid: str, size) -> str:
    """纯函数:根据 guid 和尺寸计算缓存文件名。guid 净化为安全字符集,防路径遍历。"""
    safe_guid = re.sub(r"[^A-Za-z0-9_-]", "", guid)
    w, h = size
    return f"{safe_guid}_{w}x{h}_{_VERSION}.png"


def _fit_center_crop(im, size):
    """等比缩放后居中裁剪到目标尺寸(填满,不留边)。"""
    tw, th = size
    sw, sh = im.size
    scale = max(tw / sw, th / sh)
    nw, nh = max(1, round(sw * scale)), max(1, round(sh * scale))
    im = im.resize((nw, nh), Image.LANCZOS)
    left, top = (nw - tw) // 2, (nh - th) // 2
    return im.crop((left, top, left + tw, top + th))


def process_to_cache(raw: bytes, guid: str, size, cache_dir: str):
    """原图字节 → 适配缓存 PNG,返回绝对路径;失败 None;已存在则直接返回(缓存命中)。

    处理流程:
    1. 检查缓存:存在则直接返回路径(不重处理)
    2. 解码原图为 RGB
    3. 等比缩放+居中裁剪到目标尺寸
    4. 转灰度 + Floyd–Steinberg 抖动到 16 灰阶
    5. 原子写入(先写 .tmp 再 os.replace)

    参数:
      raw: 原图字节
      guid: 图片唯一 ID
      size: 目标尺寸 (w, h)
      cache_dir: 缓存目录

    返回:
      缓存文件绝对路径,或 None(解码失败/处理失败)
    """
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, cache_filename(guid, size))
    if os.path.exists(path):
        return path
    try:
        im = Image.open(io.BytesIO(raw)).convert("RGB")
    except Exception:
        return None
    try:
        im = _fit_center_crop(im, size)
        im = im.convert("L")                  # 灰度
        im = im.convert("1")                  # Floyd–Steinberg 抖动(Pillow 默认)
        tmp = path + ".tmp"
        im.save(tmp, format="PNG")
        os.replace(tmp, path)                 # 原子落盘
        return path
    except Exception as e:
        print(f"[album_image] process failed {guid}: {e}")
        try:
            os.remove(tmp)          # 清理可能遗留的 .tmp 文件
        except Exception:
            pass
        return None
