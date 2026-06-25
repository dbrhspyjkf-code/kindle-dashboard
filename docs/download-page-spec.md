# 施工图:下载看板页(qBittorrent + Transmission 合并)

> **交付对象**:接手的开发 AI(做 6 套风格模板)+ 本仓主开发(数据层)。本文自包含。
> **状态**:已实现(2026-06-17)。数据层(`downloader.py` 双 adapter + 合并 + schema `downloaders` 段 + contract `empty_download` + build_context 格式化/本地化 + active_pages)已落地,API 对两台真机(192.168.1.100 的 qB 8085 / Transmission 9091)实测验证;**7 套风格 `download.html` 全部完成**(style_a 样板 + bento/blueprint/gauge/minimal/newspaper/terminal),全套测试绿。本文保留作设计依据与字段契约参考。
> **铁律**:遵守三铁律(零硬编码 / 配置即页面 / 诚实降级)。不得破坏鉴权/设备/额度/i18n 等现有功能与测试(见 `CLAUDE.md`)。

---

## 1. 需求(用户已拍板)

把家里的 PT 下载客户端做成看板页:
- **同时接 qBittorrent + Transmission(可多台),展示时把两边所有种子合并成一个列表**(不标来源)。
- 墨水屏一屏:**顶部全局带**(总速度/数量/累计上传/全局分享率)+ **活跃优先的种子列表 ~6-8 条**(进度条/速度/分享率/状态)。
- PT 命根子突出:**分享率 + 累计上传量**。
- **7 套风格各一个模板**(红线);默认 zh,en 双语。

---

## 2. 实测结论(真机验证,字段名/鉴权都确定)

### qBittorrent(v4.6.4,端点 `/api/v2/...`)
- **登录**:`POST /api/v2/auth/login`,表单 `username`+`password`,**必须带 `Referer: http://<host>:<port>` 头**(不带 403,实测)。成功响应体 `Ok.` + `Set-Cookie: SID=...`,后续请求带 cookie。
- **种子**:`GET /api/v2/torrents/info` → 数组,字段:`name / progress(0~1) / dlspeed / upspeed / state(字符串) / ratio / uploaded / size / eta(秒) / num_seeds / category`。
- **全局(关键)**:`/api/v2/transfer/info` **只有本次会话**数据。**累计上传/全局分享率要从 `/api/v2/sync/maindata?rid=0` 的 `server_state`** 取:`dl_info_speed / up_info_speed / alltime_ul / alltime_dl / global_ratio / free_space_on_disk / connection_status`。
  - **坑**:`free_space_on_disk` 实测返回 `-1`(拿不到)→ **负数当「未知」、不显示**。
- `state` 取值:`downloading/forcedDL/metaDL/allocating/uploading/forcedUP/stalledDL/stalledUP/pausedDL/pausedUP/queuedDL/queuedUP/checkingDL/checkingUP/checkingResumeData/moving/error/missingFiles` 等。

### Transmission(端点 `/transmission/rpc`,POST JSON)
- **鉴权**:首次请求返回 **HTTP 409** + 响应头 `X-Transmission-Session-Id`,提取后在后续请求头带上(CSRF 握手);叠加 **HTTP Basic auth**(`admin:admin`)。
- **种子**:`{"method":"torrent-get","arguments":{"fields":[...]}}` → `arguments.torrents[]`,字段:`name / percentDone(0~1) / rateDownload / rateUpload / status(0-6 数字) / uploadRatio / uploadedEver / downloadedEver / totalSize / eta(秒) / peersConnected`。
- **全局**:`{"method":"session-stats"}` → `downloadSpeed / uploadSpeed / activeTorrentCount / pausedTorrentCount / torrentCount / cumulative-stats.{uploadedBytes,downloadedBytes}`。
- `status` 数值:`0=停止 1=校验排队 2=校验中 3=下载排队 4=下载中 5=做种排队 6=做种`。

### 统一状态枚举(两边各自映射成同一套)
| 统一枚举 | qB state | Transmission status |
|---|---|---|
| `downloading` | downloading/forcedDL/metaDL/allocating | 4 |
| `seeding` | uploading/forcedUP/stalledUP | 6 |
| `stalled` | stalledDL | — |
| `checking` | checkingDL/checkingUP/checkingResumeData/moving | 1,2 |
| `queued` | queuedDL/queuedUP | 3,5 |
| `paused` | pausedDL/pausedUP | 0 |
| `error` | error/missingFiles | — |
| (兜底) | 原值 | `?` |

---

## 3. 架构:多下载器 adapter + 合并(pull 直采)

```
config.downloaders.clients[]  (列表:qB/Transmission,可多台)
        │
  sources/downloader.py
   ├─ _qb_fetch(client)   → 登录+torrents/info+sync/maindata → 归一化
   ├─ _tr_fetch(client)   → 409握手+torrent-get+session-stats → 归一化
   └─ 合并所有种子 + 全局统计累加 + 活跃优先排序 + 截断 → cache["download"]
        │
  build_context → ctx["download"](状态本地化、速度/容量格式化)
        │
  styles/<风格>/download.html  ── 7 套渲染同一份 ctx["download"]
```

复用现有 pull 直采(每 N 秒轮询);失败返回 `None` → `_merge` 保留上一帧。

---

## 4. 逐层改动

> 命名:**页面 key = `download`**,**配置段 = `downloaders`**,**模板 = `<风格>/download.html`**。

### 4.1 `server/sources/downloader.py`(新建)

要点:
- `collect(cfg)`:读 `cfg.downloaders.clients`,逐个调对应 adapter,**合并**;全失败返回 `None`,部分失败把出错的下载器名记进 `errors`(诚实降级)。
- 每个 adapter 返回 `{"torrents": [...归一化...], "g": {dl_speed,up_speed,active,total,ul_bytes,dl_bytes,free}}`(原始数值,格式化留给 build_context)。
- 归一化种子(adapter 产出,原始数值):
  ```
  {name, progress(0~100 int), dl(bytes/s int), up(bytes/s int),
   state(统一枚举 str), ratio(float), size(bytes int), eta(秒 int)}
  ```
- 鉴权细节按 §2 实测写(qB Referer 头、Transmission 409+Basic)。httpx 已是依赖。
- 排序:`downloading < stalled < seeding < checking < queued < paused < error`,同级按 up 速降序、再 dl 速降序。截断到 `cfg.downloaders.rows`(默认 8)。

### 4.2 `server/app.py`
- import `downloader`,加进 `SOURCES`;`SOURCE_INTERVAL` 加 `"downloader": ("downloaders","interval",15)`(下载状态变化快,默认 15s)。

### 4.3 数据契约 `server/render/contract.py`
- `PAGES` 加:`"download": {"title":"下载","section":"download","needs":["downloaders"]}`。
- `empty_download()`(冻结字段,模板只认这些):
  ```python
  def empty_download():
      return {
          "ok": False,
          "dl_speed": "0", "up_speed": "0",   # 已格式化 "29 MB/s"
          "active": 0, "total": 0,
          "ratio": "0.00",                    # 聚合全局分享率
          "uploaded": "--", "downloaded": "--",  # 累计(已格式化 "118 G")
          "free": "",                         # qB 剩余空间;未知=空串(模板不显)
          "torrents": [],                     # 已排序+截断;字段见下
          "errors": [],                       # 连不上的下载器名(提示用)
      }
  ```
  单条种子(`torrents[*]`,冻结):
  ```
  name        str  种子名
  progress    int  0~100
  dl / up     str  速度,已格式化 "29 MB/s" / "0"
  ratio       str  "0.43"
  size        str  "12.3G"
  eta         str  "12分" / "1时5分" / "—"(已本地化)
  state       str  统一枚举(downloading/seeding/paused/checking/queued/stalled/error)——模板用它选图标/处理
  state_text  str  已本地化的状态文字(下载中/做种/暂停…)——模板显示用
  ```
- `empty_context()` 加 `ctx["download"] = empty_download()`。

### 4.4 整合 `server/render/build_context.py`
- 加 download 段:读 `cache.get("download")`(adapter 合并后的原始结构)→ 格式化(速度 `fmt_speed`、容量 `fmt_bytes`、eta 本地化、`state`→`state_text` 本地化映射表 `DL_STATE`)。
- `DL_STATE = {"zh":{downloading:"下载中",seeding:"做种",paused:"暂停",checking:"校验",queued:"排队",stalled:"卡住",error:"错误"}, "en":{...Downloading/Seeding/Paused/Checking/Queued/Stalled/Error}}`。
- 聚合分享率 = 总累计上传 / 总累计下载(跨所有下载器);格式化两位小数。
- 缺数据/未配 → `empty_download()`(诚实降级,该页隐藏)。

### 4.5 schema `server/config/schema.py`
新增 Section(参照 `devices`:module_list + 标量字段):
```python
Section(
    key="downloaders", label="下载器", page="download",
    help="接入 qBittorrent / Transmission(可多台),把所有种子合并显示成一屏下载看板。"
         "填了至少一个才出此页;清空则隐藏。",
    label_en="Downloaders",
    help_en="Connect qBittorrent / Transmission (multiple OK); shows all torrents merged on one page.",
    enable_when=["clients"],     # 列表非空即启用(list 特判见 enabled_modules)
    fields=[
        Field("clients", "下载器", "module_list", default=[],
              label_en="Clients",
              item_fields=[
                  # name 必须放第一位:loader 的 secret 回填按 item_fields[0] 匹配(密码不串台)
                  Field("name", "名称", "str", "", required=True,
                        help="自己起个名,如「群晖 qB」。", label_en="Name"),
                  Field("type", "类型", "enum", "qbittorrent",
                        options=[("qbittorrent","qBittorrent"),("transmission","Transmission")],
                        label_en="Type"),
                  Field("host", "地址", "str", "", required=True,
                        help="如 192.168.x.x", label_en="Host"),
                  Field("port", "端口", "int", 8080,
                        help="qB 默认 8080;Transmission 默认 9091。", label_en="Port"),
                  Field("username", "用户名", "str", "", label_en="Username"),
                  Field("password", "密码", "str", "", secret=True, label_en="Password"),
              ]),
        Field("rows", "显示条数", "int", 8,
              help="种子列表最多显示几条(活跃优先);全局统计仍含全部。", label_en="Rows"),
        Field("interval", "采集间隔(秒)", "int", 15,
              help="多久拉一次下载状态。下载变化快,建议 10~30。", label_en="Interval (s)"),
    ],
),
```
- `enabled_modules`:加 `downloaders` 特判(`clients` 列表非空即启用)。
- `active_pages`:`page_ready` 加 `"download": enabled.get("downloaders")`;`default_order` 把 `"download"` 放进去(建议 home→ai→news→**download**→device→ha→printer)。
- `config.example.yaml` 同步加 `downloaders` 段(clients 空列表 + rows + interval),否则 example 匹配测试红。

### 4.6 设置页 `web/setup.html`
- `downloaders` 段大部分是 **schema 自动驱动**(module_list + enum 类型下拉 + int 字段),参照 devices/ha_page 控件应能自动渲染。确认类型下拉(qB/Transmission)、增删行、密码脱敏正常。
- 静态文案进 `I18N` 字典 zh/en(zh 字节级不变)。

---

## 5. 7 套风格 `styles/<风格>/download.html`(红线:各自视觉语言)

交给开发 AI 的主体工作(照 `ha-page-styles-spec.md` 模式)。

- 7 套:`style_a/bento/blueprint/gauge/minimal/newspaper/terminal`,消费同一份 `ctx["download"]`,不改任何 Python/schema/契约。
- 布局(墨水屏 800×600 横屏):
  - **顶部全局带**:总↓ `{{ download.dl_speed }}` / 总↑ `{{ download.up_speed }}` / 活动 `{{ download.active }}`/`{{ download.total }}` / 累计上传 `{{ download.uploaded }}` / 全局分享率 `{{ download.ratio }}`。这几个是**全部种子**的汇总,显著呈现。
  - **种子列表** `{% for t in download.torrents %}`:每行 `t.name`(截断)+ **进度条**(`t.progress`%)+ `↓{{ t.dl }} ↑{{ t.up }}` + `{{ t.ratio }}` + 状态 `{{ t.state_text }}`(可按 `t.state` 给图标/处理)。约 6-8 行。
  - **进度条是墨水屏主场**:实心/斜纹填充表示进度,别用颜色。下载中显进度+eta,做种显分享率+上传。
  - `download.errors` 非空 → 角落提示「N 个下载器离线」(诚实降级)。
  - 空态(`download.torrents` 空且 `download.total==0`)→ 占位「暂无任务」,不报错。
- **i18n**:每套 `strings.json` 加本页静态键(标题/来源标签/单位/空态/全局带标签如「累计上传」「分享率」);写死中文换 `{{ t.键 }}`;zh 逐字一致。状态文字 `state_text` 已由 build_context 本地化,模板直接用。

---

## 6. strings.json 新增键(7 套都加,zh+en)
```
dl_title    "下载" / "Downloads"
dl_kicker   "仪表盘 · 下载" / "DASHBOARD · DOWNLOADS"
dl_up_total "累计上传" / "Uploaded"
dl_ratio    "分享率" / "Ratio"
dl_active   "活动" / "Active"
dl_empty    "暂无任务" / "No tasks"
dl_offline  "下载器离线" / "client(s) offline"
```
(具体键集合由模板定;原则:显示给用户的固定词都进 strings.json。)

---

## 7. 测试 `tests/test_downloader.py`
- **adapter 解析**:喂一段真机抓的 qB `/torrents/info` + `/sync/maindata` JSON、Transmission `torrent-get` + `session-stats` JSON(mock httpx),断言归一化字段、状态映射(qB 字符串 / Transmission 0-6 数字 → 统一枚举)。
- **鉴权握手**:qB 登录失败(非 `Ok.`)→ 抛/降级;Transmission 409 → 取 session-id 重试(mock 两次响应)。
- **合并 + 排序**:两边各几条 → 合并后活跃优先、截断到 rows、全局累加正确。
- **降级**:无 clients → `None`;某下载器连不上 → 进 `errors`、其余正常。
- `contract.empty_download` 字段齐;`schema` 的 downloaders 段/enabled/active_pages;`config.example` 同步;`render_smoke` 自动覆盖 download.html 空数据。
- 全套 `pytest -q` 绿。
- **真机端到端**(本仓特有便利):数据层做完直接连 192.168.1.100 的 qB/Transmission 验证合并出图。

---

## 8. 验收标准
1. 配了 qB + Transmission → 看板多出「下载」页,合并显示两边种子;顶部全局带数对(总速度/累计上传/聚合分享率)。
2. 活跃优先排序;下载中显进度+eta,做种显分享率。
3. 删空 clients → 页消失;某下载器离线 → 提示且不影响另一个(诚实降级)。
4. `language=en` chrome 英文化(种子名是外部数据,保持原文);默认 zh 像素级不变。
5. 鉴权/设备/额度/i18n 现有功能与防回归红线一个没破;全套测试绿。

## 9. 范围边界 / 防回归
- ❌ 契约字段别用 dict 方法名(`items`/`keys`/`values`)——用 `torrents`(已避坑)。
- ❌ 不引第三方下载器库;`httpx` 直连。
- ❌ 密码 secret、只存本地、不回传前端(item_fields[0]=name 保证回填不串台)。
- ❌ qB `free_space_on_disk<0` 当未知不显示;eta 异常值(qB 8640000/负数、Tr -1/-2)显「—」。
- ✅ 默认 zh 与现状一致。

## 10. 分工
- **数据层(downloader.py 双 adapter+合并+schema+setup+测试)+ style_a 样板 = 本仓主开发(我)**,连真机验证。
- **其余 6 套 download.html = 新 AI** ✅ 已完成(2026-06-17),契约冻结后交付(`docs/download-page-spec.md` §5/§6 + `styles/style_a/download.html` 样板)。各用独立视觉语言:terminal=transmission-cli/ASCII 进度条、newspaper=传输清单表、bento=统计卡+列表、blueprint=点阵量规、gauge=进度环、minimal=发丝线。
