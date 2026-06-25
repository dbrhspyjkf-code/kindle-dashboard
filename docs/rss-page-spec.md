# 施工图:RSS 资讯页(默认订阅 AIHOT)

> **交付对象**:接手的开发 AI(做 6 套风格模板)+ 本仓主开发(数据层)。本文自包含,读完即可独立施工,无需追问。
> **状态**:数据采集层已实现(2026-06-17,`rss.py` + schema `news` 段 + contract `empty_news` + build_context + active_pages),本文保留作**数据层施工依据与字段契约**参考。
> ⚠️ **展示设计已被取代**:本文 §1 描述的「一屏一条轮播」页面排版**已由 `docs/news-redesign-spec.md` 的「自适应填充」重做**(2026-06-17;build_context 改给候选批、共享引擎 `shared/news_fit.html`、7 套 `news.html`)。**做/改 news 页展示请以 `news-redesign-spec.md` 为准**;本文的数据字段契约仍有效。
> ⚠️ **轮换模型已改(2026-06-18)**:本文 §4.4/schema 里的 `rotate_interval`(每条停留秒)和 `count`(每屏条数)字段**已删除**。news 改为**跟看板翻页节奏走**:取条周期 = `page_interval × 启用页数`(`build_context` 里算),即**每轮到资讯页一次才换一批新的、停留期间不变**(Kindle/安卓一致);安卓侧 `web/app.html` 对 news 页跳过轮询刷新钉住。`rotate`(随机/按时间)模式仍保留。以 `build_context.py` + `CLAUDE.md` 为准。
> **铁律**:遵守仓库三铁律(零硬编码 / 配置即页面 / 诚实降级)。新增可配置项 = 先改 `server/config/schema.py` 再改代码。改动**不得破坏访问令牌鉴权、设备/额度/提醒/HA、i18n 等现有功能与测试**(见 `CLAUDE.md`「安全与健壮性」「i18n」节)。

---

## 1. 需求(用户已拍板)

给看板加一个 **RSS 资讯页**,墨水屏上**一屏一条、内容要全、刷新轮播**:
- **通用 RSS 源**:能订阅任意 RSS feed,**默认预置 AIHOT 的 feed**(`https://aihot.virxact.com/feed.xml`)。以后想加别的源(36氪、少数派、任意博客),设置页填 URL 即可,不改代码。
- **一屏一条**:每屏只显示一条资讯,但**内容完整**(标题 + 来源 + 时间 + 整段正文)。**不生成摘要**——feed 的 `description` 本身就是精选好的中文内容,直接显示,我们零生成、零 AI 依赖。
- **轮播两种模式**(网页可配,二选一):
  - **按时间**:从新到旧循环轮播,每条都轮得到。
  - **随机**:从全部条目里随机挑一条(用户不会盯屏,随机最省心、不怕漏)。
- **7 套风格各出一个模板**,视觉语言各自匹配(红线,见 §6)。
- 默认语言 zh;现有行为在 `language=zh` 下像素级不变。

---

## 2. 关键发现(已实测 AIHOT feed)

`GET https://aihot.virxact.com/feed.xml` → 标准 **RSS 2.0**,50 条,无需鉴权,中文。逐条字段:

| 字段 | 内容 | 备注 |
|---|---|---|
| `title` | 中文标题 | 直接用 |
| `link` | 原文链接 | 墨水屏点不了,**不显示或仅作 guid**;可留作未来二维码 |
| `description` | **整段中文正文**(CDATA 纯文本,30~407 字,中位 213) | **这就是"内容",直接显示** |
| `pubDate` | RFC822 时间 | 解析成时间戳排序 + 显示 |
| `author` | `noreply@…(X:宝玉 (@dotey))` | **取括号内**当来源名 |
| `guid` | 唯一 id | 去重用 |

**⚠️ feed 没有 `<category>`** → **没有「话题」标签**(话题只在 AIHOT 网页上,RSS 不携带)。**诚实降级:不编造话题**。页面显示 = 来源 + 标题 + 时间 + 正文。若将来某 feed 提供 `<category>`,解析器顺带取、模板有则显示、无则省略。

**channel 头**:`<title>AI HOT — 精选</title>`、`<description>` 有整体说明,可作页面副标题兜底。

---

## 3. 架构:一个 pull 源 + 一个新页 + 无状态轮播

完全复用现有 **pull 直采**范式(和天气同型,零新机制):

```
config.news.feeds[]  (RSS URL 列表,默认含 AIHOT)
        │
  server/sources/rss.py  ── 每 interval 拉各 feed → 解析 → 合并去重 → 按时间排序 → 写 cache["news_items"]
        │
  build_context  ── 按 now + rotate 模式 无状态选 1 条 → ctx["news"]
        │
  active_pages   ── feeds 非空即出 news 页(配置即页面)
        │
  styles/<风格>/news.html  ── 7 套各自渲染同一份 ctx["news"]
```

**无凭据**(无 key/无登录),设置页就是「feed URL 列表 + 轮播模式 + 间隔」。

---

## 4. 逐层改动

> 命名统一:**页面 key = `news`**,**配置段 = `news`**,**模板 = `<风格>/news.html`**。下面所有文件路径均为真实现状。

### 4.1 数据源 `server/sources/rss.py`(新建,pull 直采)

参照 `server/sources/weather.py` 的 `collect(cfg)` 范式(返回 dict 或 `None` 降级):

```python
"""RSS 资讯采集(通用 pull 直采)。默认订 AIHOT,可订任意 RSS。"""
import re, html, time
from email.utils import parsedate_to_datetime
import httpx

_MAX_ITEMS = 80          # 合并后上限,防爆(够轮播,远超一屏)

def _source_name(author: str, feed_name: str, channel_title: str) -> str:
    """author='noreply@x (X:宝玉 (@dotey))' → 取最外层括号内;退回 feed 名/channel 名。"""
    m = re.search(r"\(([^)]*(?:\([^)]*\)[^)]*)*)\)", author or "")
    if m and m.group(1).strip():
        return m.group(1).strip()
    return (feed_name or channel_title or "").strip()

def parse_rss(xml: str, feed_name: str = "") -> list:
    """解析 RSS 2.0 → [{title, summary, source, link, guid, ts}]。坏 XML 返回 []。"""
    items = []
    ch_title = ""
    mt = re.search(r"<channel>.*?<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", xml or "", re.S)
    if mt: ch_title = html.unescape(mt.group(1)).strip()
    for raw in re.findall(r"<item>(.*?)</item>", xml or "", re.S):
        def g(tag):
            m = re.search(rf"<{tag}>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</{tag}>", raw, re.S)
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
            "summary": re.sub(r"<[^>]+>", "", g("description")).strip(),  # 去残留 HTML
            "source": _source_name(g("author"), feed_name, ch_title),
            "link": g("link"),
            "guid": g("guid") or g("link") or title,
            "ts": ts,
            "category": g("category"),   # feed 没有就是空串(诚实降级,模板据此决定显不显)
        })
    return items

def collect(cfg: dict):
    feeds = ((cfg or {}).get("news", {}) or {}).get("feeds", []) or []
    urls = [(f.get("url") or "").strip(), f.get("name") or ""] if False else [
        ((f.get("url") or "").strip(), (f.get("name") or "").strip()) for f in feeds]
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
            seen.add(it["guid"]); all_items.append(it)
    if not all_items:
        return None                       # 全失败 → 保留上一帧(_merge 不覆盖 None)
    all_items.sort(key=lambda x: x["ts"], reverse=True)   # 新→旧
    return {"news_items": all_items[:_MAX_ITEMS]}
```

要点:
- 失败返回 `None`,`app._merge(None)` 不动 cache → 保留上一帧(诚实降级,断网不空屏)。
- 用标准库 `re` 解析,**不引第三方 RSS 库**(轻量、可控、与 ccusage 解析同风格)。`httpx` 已是依赖。
- 去重按 `guid`;多 feed 合并后统一按时间排序。

### 4.2 注册进主循环 `server/app.py`

1. 顶部 import:`from server.sources import ... rss`(与 weather/homeassistant 同处)。
2. `SOURCES = (weather, ccusage_cli, homeassistant, metrics, mstodo, rss)`(L98 加 `rss`)。
3. 采集间隔:找到 `SOURCE_INTERVAL` 映射表(`source_loop` 用它),加一行
   `"rss": ("news", "interval", 1800),`(默认 30 分钟拉一次;资讯变化慢)。
   ——键是模块名末段(`src.__name__.rsplit(".",1)[-1]`),即 `rss`。

> 不需要新增任何接收端点(纯 pull,不是 push)。鉴权白名单**不用动**(没有新的设备调用口)。

### 4.3 数据契约 `server/render/contract.py`

(a) `PAGES` 加一页(L20 区块):
```python
"news": {"title": "资讯", "section": "news", "needs": ["news"]},
```

(b) 新增 `empty_news()`(冻结字段,模板只认这些):
```python
def empty_news():
    """RSS 资讯页:轮播选中的 1 条(或多条)。未配 feed/拉不到 → items 空,该页隐藏。
    单条对象(契约,冻结字段名):
        title    str  标题
        summary  str  正文整段(feed 的 description,已去 HTML)
        source   str  来源名(author 括号内 / feed 名)
        category str  话题(feed 带 <category> 才有,AIHOT 无 → 空串,模板有则显示)
        when     str  相对时间,如 "2小时前" / "2h ago" / 日期(已按 lang 本地化)
        link     str  原文链接(墨水屏不可点,默认不显示)
    """
    return {
        # ⚠️ 字段名用 entries 不用 items:Jinja2 `news.items` 会解析成 dict.items() 方法(经典坑),
        #    entries 不撞方法名。模板里一律 news.entries。
        "entries": [],   # [单条, ...] 轮播选中的条目(默认 1 条)
        "index": 0,      # 当前在全部条目中的序号(从 1 起,给模板显示"第 x 条")
        "total": 0,      # 全部条目数(显示"/N")
        "title": "--",   # 页面主标题(channel 标题兜底,通常来自 strings.json 的 t)
    }
```
(c) `empty_context()` 末尾加 `ctx["news"] = empty_news()`(L154 区块,与 `ctx["ha"]` 同处)。

> `docs/data-contract.md` 同步加 `news` 页字段(与本契约逐字一致)。

### 4.4 整合 + 轮播 `server/render/build_context.py`

在 `prep_context` 里(HA 段 `ctx["ha"]` 附近)加 news 段。**轮播无状态、按时间分桶**(不依赖渲染节拍、纯函数可测):

```python
import random as _random   # 文件已 import random?没有则加(styles.py 已用 random,此处独立)

# ---- News(RSS 资讯,轮播) ----
news_cfg = (cfg or {}).get("news", {}) or {}
raw_items = cache.get("news_items") or []
n = len(raw_items)
news = {"entries": [], "index": 0, "total": n, "title": news_cfg.get("title") or ("Headlines" if en else "AI 热点")}
if n:
    mode = news_cfg.get("rotate", "random")          # random | time
    period = max(5, int(news_cfg.get("rotate_interval", 60) or 60))   # 秒/条
    count = min(max(1, int(news_cfg.get("count", 1) or 1)), 3)        # 一屏几条,默认 1,上限 3
    bucket = int(now.timestamp()) // period
    if mode == "time":
        start = bucket % n                            # 按时间循环(raw_items 已新→旧)
    else:
        start = _random.Random(bucket).randrange(n)   # 每个时间桶伪随机一条,桶内稳定不抖
    picked = [raw_items[(start + k) % n] for k in range(min(count, n))]
    news["entries"] = [{
        "title": it.get("title", ""),
        "summary": it.get("summary", ""),
        "source": it.get("source", ""),
        "category": it.get("category", ""),
        "when": _rel_time(it.get("ts", 0), now, lang),   # 见下,相对时间本地化
        "link": it.get("link", ""),
    } for it in picked]
    news["index"] = start + 1                          # 显示"第 start+1 / n 条"
ctx["news"] = news     # 实际写法:放进最后 return 的 dict,与 "ha" 并列
```

`_rel_time(ts, now, lang)`:本地化相对时间(放本文件,和 `fmt_countdown` 同处)。规则:
- `<1h` → `刚刚`/`just now`;`<24h` → `N小时前`/`Nh ago`;否则 `MM.DD`(en `MM/DD`)。
- `ts<=0`(没解析出时间)→ 空串。

**i18n 注意**:资讯正文/标题是**外部数据**,是什么语言显示什么语言(AIHOT 是中文)——和天气文字、设备名一样,**不翻译**。只有静态 chrome(页面标题、"来源"、"第 x/N 条"、相对时间词)走 lang 本地化。en 模式**不隐藏**任何东西(此页无中国文化元素)。

### 4.5 schema `server/config/schema.py`

(a) 在 `mstodo` / `ai_usage` 段附近加一个 Section(参照 `ha_page` 的 `module_list` 写法 + `weather` 的 enum/interval):

```python
Section(
    key="news", label="资讯(RSS)", page="news",
    help="把任意 RSS 订阅源显示成一屏资讯,自动轮播。默认已预置 AIHOT(AI 行业每日精选),"
         "无需任何账号/密钥。想换源/加源,改下面的列表即可。",
    label_en="News (RSS)",
    help_en="Show any RSS feed as a rotating headline page. Comes preloaded with AIHOT "
            "(curated daily AI news); no account or key needed. Add or change feeds below.",
    enable_when=["feeds"],          # 列表非空即启用(list 特判见 enabled_modules,同 ha_page/devices)
    fields=[
        Field("feeds", "订阅源", "module_list",
              default=[{"url": "https://aihot.virxact.com/feed.xml", "name": "AIHOT"}],
              label_en="Feeds",
              item_fields=[
                  Field("url", "RSS 地址", "str", "", required=True,
                        help="任意 RSS 2.0 订阅地址。", label_en="RSS URL"),
                  Field("name", "来源名(可选)", "str", "",
                        help="留空=用 feed 自带的来源。", label_en="Name"),
              ]),
        Field("rotate", "轮播方式", "enum", "random",
              options=[("random", "随机"), ("time", "按时间(新→旧)")],
              label_en="Rotation", help_en="random | by time (newest first)",
              help="随机=每次随机挑一条(不怕漏);按时间=从新到旧循环。"),
        Field("rotate_interval", "每条停留(秒)", "int", 60,
              label_en="Seconds per item",
              help="多久换下一条。和看板翻页是两回事:这是同一页内换内容。"),
        Field("count", "每屏条数", "int", 1,
              label_en="Items per screen",
              help="一屏显示几条(默认 1,内容最全);上限 3。"),
        Field("interval", "拉取间隔(秒)", "int", 1800,
              label_en="Fetch interval (s)",
              help="多久从 RSS 拉一次。资讯变化慢,建议 ≥1800。"),
    ],
),
```

(b) `enabled_modules`(L351):在 `ha_page` 特判旁加 `news` 特判(列表非空即启用):
```python
if sec.key == "news":               # 同 ha_page:订阅源列表非空即启用
    out[sec.key] = len((secd.get("feeds") or [])) > 0
    continue
```

(c) `active_pages`(L370 `page_ready`):加一行
```python
"news": enabled.get("news"),        # feeds 非空即出页;无凭据依赖
```
并把 `"news"` 加进 `default_order`(放哪自定:建议 `["home", "ai", "news", "device", "ha", "printer"]`)。

> **默认行为**:`feeds` 默认含 AIHOT 一条 → **news 页默认开**(零配置就能看)。这是有意为之的展示位(无凭据、纯展示);用户在设置页删空订阅源即可关掉。已与"配置即页面"自洽(列表空=隐藏)。
> `config.example.yaml` 的对应段同步加 `news`(否则 `test_example_yaml_matches_schema` 红)。

### 4.6 设置页 `web/setup.html`

- `news` 段大部分是**标准 schema 渲染**(module_list 订阅源 + enum 轮播方式 + int 间隔)——若现有表单已能渲染 `module_list`(ha_page 的 entities 就是),则**基本零额外前端代码**,跟着 schema 自动出。
- 确认 enum「轮播方式」下拉、module_list「订阅源」增删行能正常渲染(参照 ha_page entities 控件)。
- 静态文案(若有写死的)进 `I18N` 字典 zh/en,zh 字节级不变(见 CLAUDE.md i18n 红线)。schema 来的 label/help 已由后端按 lang 给,前端不用翻。

---

## 5. 7 套风格模板 `styles/<风格>/news.html`(红线:各自视觉语言)

**这是交给开发 AI 的主体工作**,完全照搬「HA 页其余 6 套风格」那次的协作方式(见 `docs/ha-page-styles-spec.md`)。
> ✅ **已实现(2026-06-17)**:7 套 `news.html` 全部上线,各用独立视觉语言(报头/命令行/便当大卡/蓝图/仪表面板/极简),长正文用 `-webkit-line-clamp`/分栏 + `overflow:hidden` 优雅截断,空态/话题 chip/中英 chrome 均按契约处理。下面要求保留作字段契约与验收基线。

- 7 套:`style_a / bento / blueprint / gauge / minimal / newspaper / terminal`。
- **消费同一份 `ctx["news"]` 契约**(§4.3),不改任何 Python/schema/契约。
- 每套用自己的视觉语言渲染,**绝不靠颜色**(墨水屏纯灰度):
  - `newspaper`:天然契合——报纸头条排版,大标题 + 来源行 + 正文分栏。
  - `terminal`:`$ feed --latest`、来源当 `[SOURCE]`、正文等宽。
  - `bento`:一个大卡装这条(标题区 + 正文区 + 底部来源/序号条)。
  - `blueprint`:蓝图框 + 标题 + 正文,角标 `NEWS`。
  - `gauge` / `minimal` / `style_a`:各自现有语言延伸。
- **布局要求**:
  - 一屏一条为主(`news.entries` 默认 1 条);正文 `summary` 可能长达 400 字,**要能容纳、超长优雅截断/缩字号,不溢出不塌**(墨水屏 800×600 横屏画布)。
  - 顶部显示 `news.title`(页面名,来自 `{{ t.news_title }}`)、来源 `{{ item.source }}`、`item.when`、底部 `第 {{ news.index }} / {{ news.total }} 条`(文案走 `t`)。
  - `item.category` 非空才显示话题 chip(`{% if item.category %}`);AIHOT 无,默认不显示。
  - `count>1` 时 `items` 有多条:主条大、其余压成紧凑行(可选,优先保证 1 条完美)。
  - 空态(`news.entries` 为空)分支:显示占位"暂无资讯",不报错(渲染冒烟会跑空数据)。
- **i18n**:每套 `styles/<风格>/strings.json` 的 `zh`/`en` 各加本页静态键(见 §7);模板写死中文一律换 `{{ t.键 }}`。**zh 值与模板原文逐字一致**(回归红线)。

---

## 6. strings.json 新增键(7 套都加,zh 必填、en 必填)

每套 `styles/<风格>/strings.json` 的 `zh` 和 `en` 各加(键名统一,值按风格语气微调):
```json
"news_title":  "AI 热点"   / "Headlines",
"news_source": "来源"      / "Source",
"news_pos":    "第"        / "#",         // 或直接在模板拼 "{{news.index}}/{{news.total}}"
"news_of":     "条"        / "",
"news_empty":  "暂无资讯"  / "No news yet"
```
(具体键集合由模板决定;原则:**任何要显示给用户的固定词都进 strings.json**,别在模板写死中文。)

---

## 7. 测试

- **新增 `tests/test_rss.py`**:
  - `parse_rss` 解析样例 XML(可内嵌一段精简 AIHOT feed)→ 断言 title/summary/source/ts 正确;`_source_name` 从 `author` 取括号内(含嵌套括号 `X:宝玉 (@dotey)`)。
  - 坏 XML / 空 XML → 返回 `[]` 不抛。
  - `collect` 无 feeds → `None`;全部 feed 失败 → `None`(保留上一帧)。
  - **轮播**:固定 `now` + `time` 模式 → `index` 随时间桶递增、循环;`random` 模式同一桶内稳定(两次调用同一条)、跨桶变化。建议把分桶选择抽成纯函数 `_pick_index(n, mode, ts, period)` 便于断言。
- **`tests/test_contract.py`**:`empty_news()` 字段齐备、`empty_context()` 含 `news`。
- **`tests/test_config_schema.py`**:`news` 段在 schema;`enabled_modules`(feeds 空=禁用、含默认 AIHOT=启用);`active_pages` 含/不含 news;`to_json('en')` 给英文 label;`config.example.yaml` 同步。
- **`tests/test_render_smoke.py`**:已有「遍历 `list_styles()`×`has_page` 空数据降级」用例——加了 7 个 `news.html` 后会自动覆盖到(确认空 `news` 渲染不报错、纯灰度、尺寸对)。再加一条「有 1 条真实数据」的渲染断言更好。
- 跑 `python3 -m pytest tests/ -q` 全绿(当前 184,新增后应 ≥190)。

---

## 8. 验收标准

1. `news.feeds` 默认含 AIHOT → 看板**默认多出一页 AI 热点**,显示一条真实资讯(标题/来源/时间/整段正文)。
2. 轮播:`rotate=time` 从新到旧循环、每条都轮得到;`rotate=random` 每次(每个时间桶)随机一条。设置页能切。
3. 删空 `feeds` → news 页消失(配置即页面),不报错。
4. 断网/RSS 挂 → 保留上一帧,不空屏不崩(诚实降级)。
5. `language=en`:页面 chrome(标题/来源/序号/相对时间)变英文;资讯正文按原文(中文 feed 仍中文,合理)。默认 zh 像素级不变。
6. 7 套风格各出一张图自检:一屏一条、长正文不溢出、纯灰度、空态优雅、`category` 无则不显话题。
7. 鉴权/设备/额度/提醒/HA/i18n 现有功能与防回归红线一个没破;全套测试绿。

---

## 9. 范围边界 / 防回归

- ❌ 不引第三方 RSS 库;`re` + `httpx`(已有依赖)解析。
- ❌ 不编造「话题」——feed 无 `<category>` 就不显示话题 chip。
- ❌ 不加任何接收端点/鉴权豁免(纯 pull,不是 push)。
- ❌ 不动 `_merge`/`_prune`/`kill_stale_chrome`/渲染串行锁/日志轮转/配置外置等(见 CLAUDE.md)。
- ❌ 轮播**无状态**(时间分桶),不引入模块级可变计数器(避免多线程/重启状态问题、保证可测)。
- ✅ 默认 `zh` 与现状完全一致;news 页默认开是有意的展示位(无凭据)。

---

## 10. 分工

| 模块 | 谁做 | 说明 |
|---|---|---|
| **数据层**(§4.1~4.5)`rss.py` + app 注册 + contract `empty_news` + build_context 轮播 + schema `news` 段 + active_pages | **本仓主开发(我 Claude)** | 要和现有采集循环/契约/i18n/鉴权精确咬合,我有上下文,风险集中在这里 |
| **设置页**(§4.6) | **我** | 确认 module_list/enum 跟着 schema 自动渲染,补 I18N 静态键 |
| **测试**(§7)`test_rss.py` + 契约/schema/smoke 接入 | **我** | 数据层我写就顺手带测试 |
| **`style_a/news.html`(参考样板)** | **我** | 出一套冻结契约的标杆,供 6 套对齐 |
| **其余 6 套 `news.html`**(bento/blueprint/gauge/minimal/newspaper/terminal)+ 各自 strings.json 键 | **新 AI** ✅ 已完成(2026-06-17) | 纯视觉、可并行、契约已冻结;照 `ha-page-styles-spec.md` 那次的协作模式 |
| `data-contract.md` / `CLAUDE.md` 回写 news 机制 | **我** | 数据层落地后顺手 |

**交接顺序**:我先做数据层 + `style_a/news.html` + 测试并跑绿、**冻结 `ctx["news"]` 契约**;然后把 §3/§4.3/§5/§6 + 一张 `style_a/news.html` 样板交给新 AI 批量做另 6 套。

---

## 11. 建议实现顺序(数据层,我执行)

1. `sources/rss.py`(parse + collect + 轮播纯函数 `_pick_index`)+ `test_rss.py`,先把解析/轮播测绿。
2. `contract.py`(`empty_news` + PAGES + empty_context)+ `test_contract.py`。
3. `schema.py`(`news` 段 + enabled_modules/active_pages 特判 + label_en/help_en)+ `config.example.yaml` 同步 + `test_config_schema.py`。
4. `app.py`(SOURCES + SOURCE_INTERVAL 注册)。
5. `build_context.py`(news 段 + `_rel_time`)接 cache → ctx。
6. `styles/style_a/news.html` + `style_a/strings.json` 键;真实数据出图自检(中/英各一张、长正文不溢出)。
7. `setup.html` 确认 news 段渲染 + I18N 键;`render_smoke` 跑全 7 风格空数据(此时只有 style_a 有 news.html,其余 6 套 has_page=False 自动跳过,不报错)。
8. 全套 pytest 绿 → 冻结契约 → 交 6 套风格给新 AI。
