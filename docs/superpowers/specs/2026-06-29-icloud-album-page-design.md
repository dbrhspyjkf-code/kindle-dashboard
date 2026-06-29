# 相册页设计 · iCloud 公开共享相册（album page）

> 状态：已通过头脑风暴评审，待写实现计划。
> 作者出口：Kindle（E-ink 灰度）；本期不做 Android/浏览器额外适配（复用同一模板）。

## 目标

把一个 **iCloud 公开共享相册** 作为新数据源，新增一个「相册」页，定时同步相册里的照片，
经灰度 + 抖动处理后在 Kindle 上轮播，做成「电子相框」效果。

- **不碰 Apple 账号**：只用共享相册的「公开网站」链接，无需登录、无 2FA、不存任何凭据。
- **配置即页面**：填了链接才出相册页；没填/拉取失败则不显示，诚实降级、不白屏、不报错。
- **同步**：iPhone 往共享相册加照片后，看板定时（默认每小时）拉取新列表，自动更新。

## 非目标（YAGNI，本期不做）

- 网页拖拽上传照片
- 多个相册 / 相册切换
- 转场动画、Ken Burns 等特效
- 私有（需登录的）iCloud 相册
- 本期仅 `style_a` 一套皮肤；其余 7 套皮肤的 album.html 留待跑通后再铺。

## 数据流

```
iCloud 公开共享相册链接 (#token)
  → icloud_album.py：解析 token → webstream 拿照片清单 → webasseturls 拿下载 URL
  → 下载原图 → Pillow：缩放到机型分辨率 + 灰度 + Floyd–Steinberg 抖动
  → 缓存到 data/album/（按 photo guid + checksum 命名，去重、限量）
  → build_context：每轮按 period 选当前照片
  → styles/style_a/album.html 渲染 → pipeline 出 PNG → Kindle 拉图
```

采集与渲染分线程（沿用现有架构）：采集线程定时同步照片列表+下载；渲染线程每帧从缓存选图出图，不受同步快慢影响。

## iCloud 公开共享相册接口（无需登录）

公开链接形如 `https://www.icloud.com/sharedalbum/#B0Abc...`，`#` 后是相册 token。

1. **分区定位**：token 首字符决定初始分区主机 `p{NN}-sharedstreams.icloud.com`（A→01…）。
   首次 POST 可能返回 HTTP 330，body 里给出正确的 `X-Apple-MMe-Host`，需重试到正确分区。
2. **拉清单**：`POST https://{host}/{token}/sharedstreams/webstream`，body `{"streamCtag": null}`
   → 返回 `photos`（每张含 `photoGuid`、`derivatives`，derivatives 是不同尺寸的 checksum）。
3. **取下载 URL**：`POST https://{host}/{token}/sharedstreams/webasseturls`，
   body `{"photoGuids": [...]}` → 返回 `items`（checksum → `url_location` + `url_path`），
   拼成实际下载地址。选每张照片**最大尺寸** derivative。

实现要点：
- 用项目已有的 HTTP 客户端方式（参考 `sources/weather.py` / `homeassistant.py` 的请求封装与超时/重试）。
- 失败（链接失效、网络错误、解析异常）→ 返回空清单，触发降级，不抛到渲染层。
- 列表带 `streamCtag`/`photoGuid` 可做增量：guid 已缓存则跳过下载。

## 图片处理（E-ink 适配）

KO2 是 16 级灰度屏。处理步骤：

1. 按设置页选的 Kindle 机型分辨率确定目标画布（沿用现有 `display.model` → 分辨率映射）。
2. 等比缩放 + 居中裁剪/留边到画布。
3. 转灰度 `L`，做 **Floyd–Steinberg 抖动**（Pillow `convert("1")` 或自定义到 16 灰阶）。
4. 存为 PNG 到 `data/album/`，文件名含 `photoGuid` + 尺寸 + 处理版本，便于去重和缓存失效。

缓存策略：限量（如最多 N 张，可配），LRU 或按相册当前 guid 集合清理已删除的照片。
新增 Pillow 依赖 → 加进 `server/requirements.txt` 及 NAS Dockerfile（若尚无）。

## 契约 / 配置改动

### contract.py
- `PAGES` 加：`"album": {"title": "相册", "section": "album", "needs": ["album"]}`
- 新增 `empty_album()`：返回降级结构，至少含
  `{"photo": {"src": "", "caption": "", "date": ""}, "count": 0, "index": 0}`。
- 同步更新 `docs/data-contract.md`（契约权威定义须与文档一致）。

### schema.py
- 新增 `album` 段，字段：
  - `shared_url`（str，公开链接，必填才启用）
  - `sync_interval`（int，秒，默认 3600，列表同步间隔）
  - `order`（enum：`sequential` | `random`，默认 `sequential`，轮播顺序）
  - `max_photos`（int，缓存上限，默认如 200）
- `active_pages()` / `enabled_modules()`：`album` 在 `shared_url` 非空时启用，page_ready 同理。
- `default_order` 里给 album 安排一个位置（如 home 之后）。

### build_context.py
- 加 `album` context 组装：按 period（`page_interval × 启用页数`）推进 index，
  `sequential` 顺序、`random` 用稳定随机；选出当前 photo 的缓存 src（相对 URL 或 data 路径）。
- 顶层 context 注入 album 段（参考 news 轮播的 period 推进写法）。

### app.py
- 若模板用 URL 引照片：加一个服务静态/缓存图片的端点（参考 music artwork 端点 `_music_artwork_*` 的 blob 服务方式），或直接让 album.html 内嵌 data URI / 指向 data 目录。优先复用 music 的图片服务范式。

## 模板 styles/style_a/album.html

电子相框风格：满屏单张照片 + 细相框边/留白 + 角落小字（日期/序号 `index/count`）。
- 复用 `style.css` 既有变量与页脚页码 `{{ page_no }}/{{ page_total }}`。
- 照片缺失（降级）：显示占位框 + "相册同步中…/未配置" 文案，不报错。
- 先只做 `style_a`；其余皮肤后续按 `docs/style-authoring.md` 铺。

## 设置页 web/setup.html

新增「相册」卡片：
- 输入公开链接、同步间隔、轮播顺序、缓存上限。
- 卡片下方给操作指引：iPhone → 相册 → 共享相册 → 设置 → 打开「公开网站」→ 复制链接。
- 右侧实时预览复用现有预览机制。

## 错误处理 / 降级

- 链接无效 / 网络失败 / 解析失败：相册数据源返回空，相册页降级显示占位，其他页不受影响（铁律：一个源挂掉不影响其他源）。
- 同步与渲染解耦：同步失败时仍用上次缓存的照片继续轮播。

## 测试（沿用 tests/ pytest 体系）

- iCloud 接口解析：用录制/构造的 webstream + webasseturls 样例 JSON，断言解析出正确的下载 URL（不打真实网络）。
- 图片处理：给定一张测试图，断言输出尺寸=目标分辨率、模式=灰度、文件落到缓存目录、重复 guid 命中缓存不重复下载。
- 契约：`empty_album()` 结构、`active_pages()` 在有/无 `shared_url` 时是否含 album。
- 渲染：album.html 用真实 context 出图不报错（接入现有渲染管线测试）。
- 降级：source 返回空时，相册页渲染为占位而非异常。

## 交付与上线

1. 本仓库改代码 → `.venv/bin/python -m server.run` 本地跑，设置页填链接验证出图。
2. 真机：`installers/kindle/install.sh` 刷到 KO2 看效果（横屏灰度）。
3. 让状态栏的 .app 用上：`bash installers/macos/build-mac-app.sh <版本号>` 重新打包 dmg。
4. 提交到 fork（origin = dbrhspyjkf-code）。
