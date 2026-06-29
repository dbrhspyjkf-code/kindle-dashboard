# 相册页（iCloud 公开共享相册）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增「相册」页：从 iCloud 公开共享相册定时拉照片，灰度+抖动处理后在 Kindle 上轮播。

**Architecture:** 沿用现有「数据源 collect → cache → build_context → 模板 → pipeline 出 PNG」管线，照搬 `rss`(news 页) 的模式。新增数据源 `icloud_album`，新增页 key `album`，新增 `styles/style_a/album.html`。照片下载后用 Pillow 缩放+灰度+Floyd–Steinberg 抖动、缓存到 `data/album/`；渲染时选中照片转 base64 data URI 内嵌（Kindle 出图是 file:// 临时 HTML，HTTP/相对图不稳，与 music 封面墙同理）。

**Tech Stack:** Python 3 / FastAPI / httpx / Pillow（均已是现有依赖）/ Jinja2 模板 / pytest。

## Global Constraints

- **零硬编码**：所有用户输入（公开链接、间隔、上限）必须是 `schema.py` 的字段，代码别处不写死。
- **配置即页面**：`album.shared_url` 非空才出相册页；空/拉取失败则该页隐藏（`active_pages` 过滤）。
- **诚实降级**：链接失效/网络失败/解析异常 → 数据源返回 `None`，保留上帧缓存；context 用 `empty_album()` 兜底，渲染出占位而非报错、不影响其他页。
- **不碰 Apple 账号**：仅用公开共享相册的匿名 `webstream`/`webasseturls` 接口，无登录、不存任何凭据。
- **Kindle 图片内嵌**：模板里照片用 base64 data URI（不用 HTTP URL）。
- **依赖**：Pillow 已在 `server/requirements.txt`（11.2.1），**不要重复添加**。
- **测试不打真实网络**：iCloud 接口测试用构造的样例 JSON / mock httpx。
- 现有测试须保持通过：`python3 -m pytest tests/ -q`。

---

### Task 1: iCloud 相册客户端 — 纯解析函数

**Files:**
- Create: `server/sources/icloud_album.py`
- Test: `tests/test_icloud_album.py`

**Interfaces:**
- Produces:
  - `parse_token(url: str) -> str` — 从公开链接取 `#` 后 token；无效返回 `""`。
  - `partition_host(token: str) -> str` — token 首字符 → 初始 `p{NN}-sharedstreams.icloud.com` 主机。
  - `parse_webstream(data: dict) -> list[dict]` — webstream JSON → `[{"guid","checksums":[...]}]`，每张取最大尺寸 derivative 的 checksum 列表（按 width*height 降序，取首个）。
  - `parse_asset_urls(data: dict) -> dict` — webasseturls JSON → `{checksum: "https://{url_location}{url_path}"}`。
  - `build_photo_list(stream: dict, assets: dict) -> list[dict]` — 合并 → `[{"guid","checksum","url"}]`（按 stream 顺序，跳过没拿到 url 的）。

- [ ] **Step 1: Write the failing test**

```python
# tests/test_icloud_album.py
"""iCloud 公开共享相册解析验证。可直接 python3 跑,也兼容 pytest。"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from server.sources import icloud_album as ia  # noqa: E402


def test_parse_token():
    assert ia.parse_token("https://www.icloud.com/sharedalbum/#B0ABCdef") == "B0ABCdef"
    assert ia.parse_token("https://www.icloud.com/sharedalbum/#A1xyz?q=1") == "A1xyz"
    assert ia.parse_token("not a url") == ""
    assert ia.parse_token("") == ""


def test_partition_host():
    # 'A' → p01, 'B' → p02 ... 首字符决定分区(A=1)
    assert ia.partition_host("A1xxx") == "p01-sharedstreams.icloud.com"
    assert ia.partition_host("B0xxx") == "p02-sharedstreams.icloud.com"


def test_parse_webstream_picks_largest():
    data = {"photos": [
        {"photoGuid": "g1", "derivatives": {
            "1": {"checksum": "cks_small", "width": "100", "height": "100"},
            "2": {"checksum": "cks_big", "width": "2000", "height": "1500"},
        }},
        {"photoGuid": "g2", "derivatives": {
            "1": {"checksum": "cks2", "width": "800", "height": "600"},
        }},
    ]}
    out = ia.parse_webstream(data)
    assert out == [
        {"guid": "g1", "checksums": ["cks_big"]},
        {"guid": "g2", "checksums": ["cks2"]},
    ]


def test_parse_asset_urls():
    data = {"items": {
        "cks_big": {"url_location": "cvws.icloud-content.com", "url_path": "/B/abc?o=1"},
    }}
    out = ia.parse_asset_urls(data)
    assert out == {"cks_big": "https://cvws.icloud-content.com/B/abc?o=1"}


def test_build_photo_list():
    stream = [{"guid": "g1", "checksums": ["cks_big"]},
              {"guid": "g2", "checksums": ["missing"]}]
    assets = {"cks_big": "https://h/p"}
    out = ia.build_photo_list({"photos_parsed": stream}, assets) if False else ia.build_photo_list(stream, assets)
    assert out == [{"guid": "g1", "checksum": "cks_big", "url": "https://h/p"}]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_icloud_album.py -v`
Expected: FAIL（`ModuleNotFoundError: server.sources.icloud_album`）

- [ ] **Step 3: Write minimal implementation**

```python
# server/sources/icloud_album.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_icloud_album.py -v`
Expected: PASS（5 个 test 全过）

- [ ] **Step 5: Commit**

```bash
git add server/sources/icloud_album.py tests/test_icloud_album.py
git commit -m "feat(album): iCloud 共享相册解析函数 + 测试"
```

---

### Task 2: iCloud 相册客户端 — 网络拉取（含 330 重定向）

**Files:**
- Modify: `server/sources/icloud_album.py`
- Test: `tests/test_icloud_album.py`（追加）

**Interfaces:**
- Consumes: Task 1 的解析函数。
- Produces:
  - `fetch_album_photos(shared_url: str, *, client=None) -> list[dict]` — 端到端：解析 token → webstream（处理 330 拿正确 host）→ webasseturls → `build_photo_list`。任何异常/无效链接 → 返回 `[]`。`client` 参数注入便于测试（默认 `httpx.Client`）。

- [ ] **Step 1: Write the failing test**

```python
# tests/test_icloud_album.py 追加
class _FakeResp:
    def __init__(self, status=200, payload=None, headers=None):
        self.status_code = status
        self._payload = payload or {}
        self.headers = headers or {}
    def json(self):
        return self._payload


class _FakeClient:
    """按 url 路径返回预设响应,记录调用。"""
    def __init__(self, routes):
        self.routes = routes          # path 子串 -> _FakeResp 或 list(按序弹出)
        self.calls = []
    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append(url)
        for key, resp in self.routes.items():
            if key in url:
                if isinstance(resp, list):
                    return resp.pop(0)
                return resp
        return _FakeResp(404, {})
    def __enter__(self): return self
    def __exit__(self, *a): return False


def test_fetch_album_photos_happy():
    stream_payload = {"photos": [
        {"photoGuid": "g1", "derivatives": {"2": {"checksum": "c1", "width": "2000", "height": "1500"}}},
    ]}
    asset_payload = {"items": {"c1": {"url_location": "h.com", "url_path": "/p?o=1"}}}
    fake = _FakeClient({
        "webstream": _FakeResp(200, stream_payload),
        "webasseturls": _FakeResp(200, asset_payload),
    })
    out = ia.fetch_album_photos("https://www.icloud.com/sharedalbum/#B0X", client=fake)
    assert out == [{"guid": "g1", "checksum": "c1", "url": "https://h.com/p?o=1"}]


def test_fetch_album_photos_330_redirect():
    stream_payload = {"photos": [
        {"photoGuid": "g1", "derivatives": {"2": {"checksum": "c1", "width": "10", "height": "10"}}},
    ]}
    asset_payload = {"items": {"c1": {"url_location": "h.com", "url_path": "/p"}}}
    fake = _FakeClient({
        "webstream": [
            _FakeResp(330, {}, {"X-Apple-MMe-Host": "p33-sharedstreams.icloud.com"}),
            _FakeResp(200, stream_payload),
        ],
        "webasseturls": _FakeResp(200, asset_payload),
    })
    out = ia.fetch_album_photos("https://www.icloud.com/sharedalbum/#B0X", client=fake)
    assert out and out[0]["url"] == "https://h.com/p"
    assert any("p33-sharedstreams" in u for u in fake.calls)   # 用了重定向后的 host


def test_fetch_album_photos_bad_url():
    assert ia.fetch_album_photos("", client=_FakeClient({})) == []
    assert ia.fetch_album_photos("https://x.com/no-hash", client=_FakeClient({})) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_icloud_album.py -k fetch -v`
Expected: FAIL（`AttributeError: module ... has no attribute 'fetch_album_photos'`）

- [ ] **Step 3: Write minimal implementation**

```python
# server/sources/icloud_album.py 追加(顶部已 import httpx)

def _post(client, host, token, endpoint, body):
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_icloud_album.py -v`
Expected: PASS（全部，含新增 3 个）

- [ ] **Step 5: Commit**

```bash
git add server/sources/icloud_album.py tests/test_icloud_album.py
git commit -m "feat(album): iCloud 相册端到端拉取(含 330 重定向)"
```

---

### Task 3: 图片处理 — 缩放 + 灰度 + 抖动 + 缓存

**Files:**
- Create: `server/sources/album_image.py`
- Test: `tests/test_album_image.py`

**Interfaces:**
- Produces:
  - `process_to_cache(raw: bytes, guid: str, size: tuple[int,int], cache_dir: str) -> str | None` —
    原图字节 → 等比缩放居中裁到 `size`(横屏 w,h) → 灰度 → Floyd–Steinberg 抖动到 16 灰阶 → 存 PNG，
    文件名 `{guid}_{w}x{h}_v1.png`。返回缓存文件**绝对路径**；失败返回 `None`。已存在则直接返回路径（缓存命中，不重处理）。
  - `cache_filename(guid: str, size: tuple[int,int]) -> str` — 纯函数算文件名（供 collect 去重/清理用）。

- [ ] **Step 1: Write the failing test**

```python
# tests/test_album_image.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_album_image.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: Write minimal implementation**

```python
# server/sources/album_image.py
"""相册图片处理:下载得到的原图 → 适配 E-ink(缩放+灰度+Floyd–Steinberg 抖动)→ 缓存 PNG。

Kindle 是灰度屏,彩色照片必须抖动才不糊。文件名带 guid+尺寸+版本号,便于去重与缓存失效。
"""
import io
import os
from PIL import Image

_VERSION = "v1"     # 处理算法版本;改算法时 +1 让旧缓存失效


def cache_filename(guid: str, size) -> str:
    w, h = size
    return f"{guid}_{w}x{h}_{_VERSION}.png"


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
    """原图字节 → 适配缓存 PNG,返回绝对路径;失败 None;已存在则直接返回(缓存命中)。"""
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
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_album_image.py -v`
Expected: PASS（4 个）

- [ ] **Step 5: Commit**

```bash
git add server/sources/album_image.py tests/test_album_image.py
git commit -m "feat(album): 照片 E-ink 处理(缩放+灰度+抖动)+缓存"
```

---

### Task 4: 契约 — PAGES 注册 + empty_album

**Files:**
- Modify: `server/render/contract.py`
- Modify: `tests/test_contract.py`

**Interfaces:**
- Produces:
  - `PAGES["album"]` = `{"title": "相册", "section": "album", "needs": ["album"]}`
  - `empty_album() -> dict` = `{"photo": {"src": "", "guid": ""}, "index": 0, "total": 0}`
  - `empty_context()["album"]` 用 `empty_album()` 填充。

- [ ] **Step 1: Write the failing test**

```python
# tests/test_contract.py 追加(若无该文件按 test_rss.py 头部样式新建)
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from server.render import contract  # noqa: E402


def test_album_page_registered():
    assert "album" in contract.PAGES
    assert contract.PAGES["album"]["needs"] == ["album"]


def test_empty_album_shape():
    a = contract.empty_album()
    assert a["photo"]["src"] == ""
    assert a["total"] == 0


def test_empty_context_has_album():
    assert "album" in contract.empty_context()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_contract.py -k album -v`
Expected: FAIL（`'album' not in PAGES` / `no attribute empty_album`）

- [ ] **Step 3: Write minimal implementation**

在 `server/render/contract.py` 的 `PAGES` dict 末尾加一行：

```python
    "music":   {"title": "音乐",   "section": "music",   "needs": ["music"]},
    "album":   {"title": "相册",   "section": "album",   "needs": ["album"]},
}
```

在 `empty_music()` 之后、`empty_context()` 之前加：

```python
def empty_album():
    """相册页:轮播选中的 1 张照片。未配链接/拉不到 → src 空,该页隐藏。
    photo.src 是处理后照片的 base64 data URI(Kindle 出图内嵌,与 music 封面墙同理)。
    """
    return {
        "photo": {"src": "", "guid": ""},   # 当前展示的照片(data URI)
        "index": 0,                          # 当前序号(从 1 起,给模板显示"第 x 张")
        "total": 0,                          # 相册照片总数
    }
```

在 `empty_context()` 的 return 前补一行：

```python
    ctx["music"] = empty_music()
    ctx["album"] = empty_album()
    return ctx
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_contract.py -k album -v`
Expected: PASS（3 个）

- [ ] **Step 5: Commit**

```bash
git add server/render/contract.py tests/test_contract.py
git commit -m "feat(album): 契约注册 album 页 + empty_album 降级"
```

---

### Task 5: 配置 schema — album 段 + active_pages

**Files:**
- Modify: `server/config/schema.py`
- Modify: `tests/test_config_schema.py`

**Interfaces:**
- Consumes: Task 4 的 `PAGES["album"]`。
- Produces:
  - `SCHEMA` 含 `Section(key="album", page="album", enable_when=["shared_url"], fields=[shared_url, sync_interval, order, max_photos])`。
  - `active_pages(config)`：当 `album.shared_url` 非空时含 `"album"`，空时不含。
  - `default_order` 含 `"album"`（放 `home` 之后）。

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config_schema.py 追加
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from server.config import schema  # noqa: E402


def test_album_section_present():
    keys = [s.key for s in schema.SCHEMA]
    assert "album" in keys
    sec = next(s for s in schema.SCHEMA if s.key == "album")
    assert sec.page == "album"
    assert "shared_url" in [f.key for f in sec.fields]


def test_album_active_when_url_set():
    cfg = {"album": {"shared_url": "https://www.icloud.com/sharedalbum/#B0X"}}
    assert "album" in schema.active_pages(cfg)


def test_album_hidden_when_no_url():
    cfg = {"album": {"shared_url": ""}}
    assert "album" not in schema.active_pages(cfg)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_config_schema.py -k album -v`
Expected: FAIL（`'album' not in keys`）

- [ ] **Step 3: Write minimal implementation**

在 `server/config/schema.py` 的 `SCHEMA` 列表里、`news` Section 之后加一个 Section：

```python
    Section(
        key="album", label="相册(iCloud 共享)", page="album",
        help="把一个 iCloud 公开共享相册显示成轮播相框。iPhone:相册 → 共享相册 → 右上设置 "
             "→ 打开「公开网站」→ 复制链接粘到下面。不需要 Apple 登录,链接清空则关闭此页。",
        label_en="Album (iCloud Shared)",
        help_en="Show an iCloud public shared album as a rotating photo frame. On iPhone: Photos "
                "→ Shared Album → settings → enable 'Public Website' → copy the link here. "
                "No Apple sign-in; clear the link to hide this page.",
        enable_when=["shared_url"],
        fields=[
            Field("shared_url", "公开相册链接", "str", "",
                  help="形如 https://www.icloud.com/sharedalbum/#B0...",
                  label_en="Public album URL"),
            Field("sync_interval", "同步间隔(秒)", "int", 3600,
                  help="多久拉一次照片列表。相册变化慢,建议 ≥3600。",
                  label_en="Sync interval (s)"),
            Field("order", "轮播顺序", "enum", "sequential",
                  options=[("sequential", "顺序"), ("random", "随机")],
                  label_en="Order", help_en="sequential | random"),
            Field("max_photos", "缓存上限(张)", "int", 200,
                  help="最多缓存多少张处理后的照片。",
                  label_en="Max cached photos"),
        ],
    ),
```

在 `active_pages()` 里：
1. `page_ready` dict 加一行（紧跟 `"music": ...` 后）：
```python
        "album": enabled.get("album"),                  # 填了公开链接即出页
```
2. `default_order` 改为把 `album` 放在 `home` 后：
```python
    default_order = ["home", "album", "ai", "news", "music", "download", "device", "ha", "printer"]
```

> 说明：`enabled_modules` 对 `enable_when=["shared_url"]` 用通用 `_is_filled` 判断（str 非空即启用），无需像 list 字段那样特判，沿用现有逻辑即可。

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_config_schema.py -k album -v`
Expected: PASS（3 个）

- [ ] **Step 5: Commit**

```bash
git add server/config/schema.py tests/test_config_schema.py
git commit -m "feat(album): schema album 段 + active_pages 接入"
```

---

### Task 6: 数据源 collect + 注册到采集循环

**Files:**
- Modify: `server/sources/icloud_album.py`（加 `collect`）
- Modify: `server/app.py`（import / `SOURCES` / `SOURCE_INTERVAL`）
- Test: `tests/test_icloud_album.py`（追加 collect 测试）

**Interfaces:**
- Consumes: Task 2 `fetch_album_photos`、Task 3 `album_image.process_to_cache`、Task 5 配置段、`schema.resolve_render_size`。
- Produces:
  - `collect(cfg: dict) -> dict | None` — 读 `album.shared_url`，拉照片列表，逐张下载+处理+缓存（限 `max_photos`），返回 `{"album_photos": [{"guid","path"}]}`；无链接返回 `None`；全失败返回 `None`。
  - `app.py`：`SOURCES` 含 `icloud_album`；`SOURCE_INTERVAL["icloud_album"] = ("album", "sync_interval", 3600)`。

- [ ] **Step 1: Write the failing test**

```python
# tests/test_icloud_album.py 追加
def test_collect_no_url_returns_none():
    assert ia.collect({"album": {"shared_url": ""}}) is None
    assert ia.collect({}) is None


def test_collect_processes_and_caches(tmp_path, monkeypatch):
    # mock 拉列表
    monkeypatch.setattr(ia, "fetch_album_photos",
                        lambda url, **k: [{"guid": "g1", "checksum": "c", "url": "https://h/p"}])
    # mock 下载
    from PIL import Image
    import io
    def _fake_dl(url):
        buf = io.BytesIO(); Image.new("RGB", (400, 300)).save(buf, "PNG"); return buf.getvalue()
    monkeypatch.setattr(ia, "_download", _fake_dl)
    # 缓存目录指向 tmp
    monkeypatch.setattr(ia, "_cache_dir", lambda cfg: str(tmp_path))
    cfg = {"album": {"shared_url": "https://www.icloud.com/sharedalbum/#B0X", "max_photos": 10},
           "server": {"kindle_model": "base"}}
    out = ia.collect(cfg)
    assert out and len(out["album_photos"]) == 1
    assert os.path.exists(out["album_photos"][0]["path"])
    assert out["album_photos"][0]["guid"] == "g1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_icloud_album.py -k collect -v`
Expected: FAIL（`no attribute 'collect'`）

- [ ] **Step 3: Write minimal implementation**

在 `server/sources/icloud_album.py` 顶部 import 处加：

```python
import os
from server.sources import album_image
from server.config import schema
```

文件末尾加：

```python
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
```

在 `server/app.py`：
1. 第 29 行 import 末尾加 `icloud_album`：
```python
from server.sources import weather, ccusage_cli, homeassistant, metrics, mstodo, rss, downloader, lyrics, icloud_album
```
2. `SOURCE_INTERVAL` dict 加一行：
```python
                   "downloader":    ("downloaders", "interval", 15),
                   "icloud_album":  ("album", "sync_interval", 3600)}
```
3. `SOURCES` 元组加 `icloud_album`：
```python
SOURCES = (weather, ccusage_cli, homeassistant, metrics, mstodo, rss, downloader, icloud_album)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_icloud_album.py -v`
Expected: PASS（全部）

- [ ] **Step 5: Run full suite + import check**

Run: `python3 -c "import server.app" && python3 -m pytest tests/ -q`
Expected: import 无错；测试全绿。

- [ ] **Step 6: Commit**

```bash
git add server/sources/icloud_album.py server/app.py tests/test_icloud_album.py
git commit -m "feat(album): collect 数据源 + 注册到采集循环"
```

---

### Task 7: build_context 组装 album（选图 + data URI）

**Files:**
- Modify: `server/render/build_context.py`
- Test: `tests/test_build_context.py`

**Interfaces:**
- Consumes: `cache["album_photos"]`（Task 6 产出）、`schema.active_pages`、`server.sources.rss.pick_index`（已有的无状态分桶轮播）。
- Produces: `prep_context(...)` 返回值含 `"album"` 段，结构同 `empty_album()`，`photo.src` 为选中照片的 base64 data URI；无照片时为 `empty_album()`。

- [ ] **Step 1: Write the failing test**

```python
# tests/test_build_context.py 追加
import os, sys, io, datetime
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from server.render.build_context import prep_context  # noqa: E402
from PIL import Image


def _make_png(path):
    Image.new("L", (10, 10)).save(path, "PNG")


def test_album_context_empty_when_no_cache():
    ctx = prep_context(datetime.datetime.now(), {}, {})
    assert ctx["album"]["total"] == 0
    assert ctx["album"]["photo"]["src"] == ""


def test_album_context_picks_data_uri(tmp_path):
    p = str(tmp_path / "g1.png"); _make_png(p)
    cache = {"album_photos": [{"guid": "g1", "path": p}]}
    cfg = {"album": {"shared_url": "https://www.icloud.com/sharedalbum/#B0X", "order": "sequential"}}
    ctx = prep_context(datetime.datetime.now(), cache, cfg)
    assert ctx["album"]["total"] == 1
    assert ctx["album"]["photo"]["src"].startswith("data:image/png;base64,")
    assert ctx["album"]["index"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_build_context.py -k album -v`
Expected: FAIL（`KeyError: 'album'`）

- [ ] **Step 3: Write minimal implementation**

在 `server/render/build_context.py` 的 News 段之后（Download 段之前）加 album 组装。参照 news 的 period 写法：

```python
    # ---- Album(iCloud 共享相册,无状态时间分桶轮播,选中 1 张转 data URI) ----
    import base64 as _b64
    from server.sources.rss import pick_index as _pick
    album_cfg = (cfg or {}).get("album", {}) or {}
    photos = cache.get("album_photos") or []
    an = len(photos)
    album = {"photo": {"src": "", "guid": ""}, "index": 0, "total": an}
    if an:
        from server.config import schema as _schema
        order = album_cfg.get("order", "sequential")
        mode = "time" if order == "sequential" else "random"
        page_interval = max(5, int((cfg.get("server", {}) or {}).get("page_interval", 20) or 20))
        n_pages = max(1, len(_schema.active_pages(cfg)))
        period = page_interval * n_pages
        idx = _pick(an, mode, now.timestamp(), period)
        pick = photos[idx % an]
        try:
            with open(pick.get("path", ""), "rb") as f:
                b64 = _b64.b64encode(f.read()).decode()
            album["photo"] = {"src": f"data:image/png;base64,{b64}", "guid": pick.get("guid", "")}
            album["index"] = idx + 1
        except Exception:
            pass   # 读图失败 → 保持空 photo(降级)
```

在 `prep_context` 的 return dict 里、`"music": music,` 之后加一行：

```python
        "music": music,
        "album": album,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_build_context.py -k album -v`
Expected: PASS（2 个）

- [ ] **Step 5: Commit**

```bash
git add server/render/build_context.py tests/test_build_context.py
git commit -m "feat(album): build_context 选图 + data URI 注入"
```

---

### Task 8: style_a 相册模板 + 渲染冒烟

**Files:**
- Create: `styles/style_a/album.html`
- Modify: `tests/test_render_smoke.py`

**Interfaces:**
- Consumes: context 的 `album` 段（Task 7）、顶层 `time_hm` / `page_no` / `page_total`。
- Produces: `styles/style_a/album.html` —— `styles.has_page("style_a", "album")` 为真且渲染不报错。

- [ ] **Step 1: Write the failing test**

先确认现有冒烟测试如何遍历页/风格（读 `tests/test_render_smoke.py` 头部），追加针对 album 的断言：

```python
# tests/test_render_smoke.py 追加
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from server.render import styles, contract  # noqa: E402


def test_style_a_album_renders():
    ctx = contract.empty_context()
    assert styles.has_page("style_a", "album")
    html = styles.render_page("style_a", "album", ctx)   # 降级(空 src)也要出 HTML 不报错
    assert "<" in html and len(html) > 50


def test_style_a_album_renders_with_photo():
    ctx = contract.empty_context()
    ctx["album"]["photo"]["src"] = "data:image/png;base64,iVBORw0KGgo="
    ctx["album"]["total"] = 3
    ctx["album"]["index"] = 1
    html = styles.render_page("style_a", "album", ctx)
    assert "data:image/png;base64" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_render_smoke.py -k album -v`
Expected: FAIL（`has_page` 为 False / 模板缺失渲染抛错）

- [ ] **Step 3: Write minimal implementation**

创建 `styles/style_a/album.html`（电子相框：满屏单图 + 细框 + 角落日期/序号，降级显占位）。复用 `style.css` 的 `--ink` 等变量，结构对齐其他页模板的外壳（先读 `styles/style_a/news.html` 看页眉/页脚/页码的标准外壳，保持一致）：

```html
{# 相册页:iCloud 共享相册轮播。满屏单张照片 + 细相框,降级显占位。 #}
<div class="page album-page">
  <div class="frame">
    {% if album.photo.src %}
      <img class="photo" src="{{ album.photo.src }}" alt="">
      <div class="caption">{{ album.index }}/{{ album.total }}</div>
    {% else %}
      <div class="photo-empty">相册同步中…</div>
    {% endif %}
  </div>
  <div class="foot">
    <span>{{ time_hm }}</span>
    <span>{{ page_no }}/{{ page_total }}</span>
  </div>
</div>
<style>
.album-page{width:100%;height:100%;display:flex;flex-direction:column;box-sizing:border-box;}
.album-page .frame{flex:1;border:2px solid var(--ink);padding:6px;background:#fff;
  display:flex;align-items:center;justify-content:center;position:relative;overflow:hidden;}
.album-page .photo{max-width:100%;max-height:100%;width:100%;height:100%;object-fit:cover;}
.album-page .photo-empty{color:var(--ink3);font-size:20px;}
.album-page .caption{position:absolute;right:10px;bottom:10px;background:#fff;
  border:1.5px solid var(--ink);padding:1px 6px;font-size:14px;}
.album-page .foot{display:flex;justify-content:space-between;font-size:14px;
  padding:4px 2px 0;color:var(--ink2);}
</style>
```

> 注：若 `style.css` 没有 `--ink2`/`--ink3` 变量，读 `styles/style_a/style.css` 确认实际变量名后替换；保持与同目录其他模板一致。

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_render_smoke.py -k album -v`
Expected: PASS（2 个）

- [ ] **Step 5: Run full suite**

Run: `python3 -m pytest tests/ -q`
Expected: 全绿。

- [ ] **Step 6: Commit**

```bash
git add styles/style_a/album.html tests/test_render_smoke.py
git commit -m "feat(album): style_a 相册模板 + 渲染冒烟测试"
```

---

### Task 9: 端到端真机验证 + 文档对齐

**Files:**
- Modify: `docs/data-contract.md`（补 album 段契约，与 contract.py 同步）
- Modify: `README.md`（数据源表加一行 iCloud 相册——可选）

- [ ] **Step 1: 本地起服务手验**

```bash
.venv/bin/python -m server.run
```
打开带令牌的设置页 → 「相册(iCloud 共享)」卡片填入你的公开相册链接 → 保存。
等一个同步周期，`curl http://localhost:8585/health` 的 `rendered` 里应出现 `album`；
浏览器开 `/kindle/page/album.png?...` 看出图是否为灰度相框。

- [ ] **Step 2: 文档对齐**

在 `docs/data-contract.md` 增补 `album` 段字段说明（`photo.src` / `index` / `total`），与 `contract.empty_album()` 一致。

- [ ] **Step 3: 刷到 Kindle 真机（可选,需 KO2 在线）**

```bash
sh installers/kindle/install.sh <KINDLE_IP>
```
翻到相册页确认照片清晰、无糊。

- [ ] **Step 4: Commit + 推到 fork**

```bash
git add docs/data-contract.md README.md
git commit -m "docs(album): 数据契约补 album 段 + README 数据源表"
git push -u origin feat/icloud-album-page
```

- [ ] **Step 5: 让状态栏 app 用上（可选，发布时）**

```bash
bash installers/macos/build-mac-app.sh <版本号>
```
重新打包 dmg，覆盖安装后状态栏 app 即含相册功能。

---

## Self-Review

- **Spec coverage**：数据流(T1-3,6,7)、iCloud 接口(T1-2)、E-ink 处理(T3)、契约(T4)、配置+active_pages(T5)、采集注册(T6)、轮播选图(T7)、style_a 模板(T8)、降级(贯穿 empty_album + collect 返回 None)、测试(每任务 TDD)、设置页(schema 自动生成,无需改 setup.html)、交付(T9) —— 全覆盖。
- **Placeholder scan**：无 TBD；每个代码步骤给出完整代码与确切命令/预期。
- **Type consistency**：`fetch_album_photos`→`collect`→`cache["album_photos"]`(含 guid/path)→build_context 读 path、`empty_album` 结构 `{photo:{src,guid},index,total}` 在 T4/T7/T8 一致;`cache_filename(guid,size)`/`process_to_cache(raw,guid,size,cache_dir)` 签名 T3/T6 一致。
- **未决小项**：T8 的 CSS 变量名以实际 `style.css` 为准（已在步骤注明先读后用）；`partition_host` 的字母→分区映射为常见实现，真机若命中 330 会自动用返回的正确 host 兜底（T2 已处理）。
