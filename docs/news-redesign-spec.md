# 任务书:AI 热点页重新设计 — 自适应填充排版

> **交付对象**:接手的开发 AI(做 6 套风格的新 `news.html`)+ 本仓主开发(数据层 + 自适应引擎 + style_a 样板)。本文自包含。
> **状态**:**已实现并提交(2026-06-17,d8ef11e:数据层+共享引擎+7套风格)**。数据层(build_context 给候选批)+ 共享引擎 `styles/shared/news_fit.html` + `style_a` 样板 + 其余 6 套(bento/blueprint/gauge/minimal/newspaper/terminal)`news.html` 全部完成,235 测试绿,各风格短/长/超长/空出图验证通过。**替换** `docs/rss-page-spec.md` 里「一屏一条轮播」的展示设计;数据采集层(`rss.py`)不变。
> **已知特性(非 bug)**:共享引擎放大上限 22px。**中等长度的单条**(放不下与他条并排、又短到放大封顶仍填不满)底部会留约 15-20% 白——这是冻结引擎的放大上限决定的,7 套一致。真实 AIHOT 数据中位 ~209 字,绝大多数以「多条并排」铺满,极少命中此档;要消除须调引擎放大上限(`shared/news_fit.html` 的 `GROW` 数组,属主开发引擎职责,改即影响 7 套)。
> **铁律**:三铁律(零硬编码 / 配置即页面 / 诚实降级)。不得破坏 Kindle 其他页出图、鉴权、采集、i18n。

---

## 0. 为什么重做(现状问题,已看图确认)
现 AI 热点页是「**一屏只显示一条**」,丑在:
- 内容短(30 字)→ **大片死白**(bento 下半屏全空、newspaper 下 2/3 空);
- 内容长(400 字)→ **一堵字墙**;
- 通篇纯文字、无层次。

## 1. 关键事实(已拉真实 feed 核实,别再纠结)
- AIHOT feed **50/50 条都有 `<description>`**,长度 **30~407 字,中位 ~209**。`rss.py` 已解析成 `news.entries[].summary`。
- **`description` 就是这条的全部内容,不是某篇长文的摘要**——背后**没有可点开的全文**,每条是**自包含**的一小段。
- ⟹ 本页**没有"点开看详情/read more"**;就是把一堆「标题 + 这段内容 + 来源 + 时间」的小块**排好版**。
- **不接 AI、不生成任何摘要**;feed 给什么显示什么,没有 `description` 的源就只有标题(自然短)。

## 2. 已确认的设计:自适应填充(adaptive fill)
不再写死条数。**根据内容多少自动决定放几条 + 多大字,始终把屏幕填满、不溢出、不留大白**:
- 内容短(30~100 字)→ 一屏并 **2~3 条**(甚至更多);
- 内容长(400 字)→ **缩小字号**,让这**一条**刚好铺满一屏;
- 超长缩到下限仍放不下 → 末尾 **省略号截断**(别缩成蚂蚁字)。
- 轮播保留:每次刷新换一批(起始位轮转,沿用 config `news.rotate` random/time)。

## 3. 核心机制:页面内「自适应引擎」(单一源,两端通用)
**唯一可靠量出真实渲染高度的办法是在浏览器里测**(字体度量)。我们两条出口**都过浏览器**——Kindle 走服务端 Chromium 截图、安卓走 WebView——所以**同一段 JS 引擎两端都跑**(不分叉):

引擎逻辑(放共享脚本,见 §5;**由本仓主开发提供**):
1. 服务端把**一批候选条目**(见 §4,约 12 条)塞进内容容器,容器高度 = 该页可用区高度。
2. 引擎从第一条往下**逐条量累计高度**:
   - 还放得下 → 保留,继续下一条;放不下 → 砍掉这条及之后(多条模式)。
   - 若**第一条单独就超高**(长文)→ **逐级降字号**(如 18→16→14→12px 离散档)直到放下;到**字号下限**仍超 → 该条**省略号截断**填满(单条模式)。
3. 排完**置就绪标记**(见 §6,给截图用)。

> 结果:短讯自动并多条、长文自动缩字铺满、超长截断,**永远填满不溢出**。各风格只管"单条长什么样",装几条/多大字交引擎。

## 4. 数据层改动(本仓主开发做)
- `server/render/build_context.py` 的 news 段:**从「挑 1 条」改为「给一批候选」**。`news.entries` = 从轮转起始位开始的 **N 条候选(默认 12,wrapping)**,顺序排好;起始位沿用现有 `pick_index(n, rotate, now, period)`。字段不变(title/summary/source/category/when/link)。
- `news.total` 仍为全部条数;`news.index` = 本批起始序号(可显示"第 X 起")。
- `contract.empty_news` 注释更新:`entries` 现在是"候选批",页面按高度取前缀显示。
- `docs/data-contract.md` 的 news 段同步:说明 entries 是候选批 + 自适应取前缀。
- **不动 `rss.py`**(采集/解析不变)。

## 5. 模板 / 6 套风格 `styles/<风格>/news.html`(交另一个 AI)
每套提供三样,**引入共享自适应引擎**:
- **内容容器**:一个填满页面可用高度的容器(`flex:1; overflow:hidden`),带引擎能认的 class/id(契约:`<div class="news-fit" data-news-fit>`)。
- **单条卡片标记**:遍历 `news.entries` 渲染每条 = 标题 + 来源 + `when` + `summary`(+ `category` 非空才显 chip)。**每条外层带 `data-news-item`**(引擎按它量高/增删)。字号用 CSS 变量(如 `--news-fs`)便于引擎降档。
- **引入引擎**:`{% include 'shared/news_fit.js.html' %}` 或页面底部 `<script>`(共享片段,本仓主开发提供;6 套直接用,别各写一套)。
- 视觉:各风格自己的语言(newspaper 报头/分栏、terminal 列表行、bento 卡、blueprint 图框、gauge、minimal),但**单条结构统一**、**字号走 `--news-fs`**。
- 空态(`news.entries` 空)→ `{{ t.news_empty }}`,不报错。
- i18n:chrome 文案走 `strings.json` 的 `t.*`(`news_*` 键已存在);**内容是外部数据,原文显示不翻**。zh 字节级不变(回归红线)。
- **去掉**任何"点击看详情/展开"(本页无详情)。

### 5.1 视觉设计规范(经 ui-ux-pro-max 查证;务必遵守,别再做成字墙)
当前丑除了排版,还有**视觉层次太弱**(巨标题 + 一坨平铺正文)。每条按下面做:
- **层次靠字号/字重/灰度分,不靠颜色(e-ink 友好)**:
  - 来源 + `when`:小字(~11–12px)、中灰(`--ink3`),放标题上方一行
  - 标题:大字加粗,是焦点(**新闻/杂志感**);**有 CJK 衬线字体可用时标题用衬线**(newspaper/style_a 尤其有效)
  - 正文:可读字号,行高 1.5–1.6
  - 话题 chip:`category` 非空才显,描边小标签
- **字号走固定档**(自适应引擎只在这些档里降,别任意缩):标题 26/22/19/17、正文 17/15/14/13(px,示意,各风格可定自己的档但要成体系)。
- **留白分组**:一条内部「来源→标题→正文」收紧成一组;**条与条之间**用明显间距或分隔线隔开——多条时一眼看清是几条(治字墙)。
- **行宽别铺满 800**:长正文单条时用**多栏**(newspaper 已是)或限宽,每行别超 ~40 汉字(太长难读、又填不匀)。
- **数字用等宽**(`.tnum`:时间/序号),防跳动。
- **安卓彩色克制**:仅给 来源/序号/话题 一个强调色点缀,正文仍近黑配近白;Kindle 灰度不变。
- **字体方向**(库荐「新闻编辑」型 = 衬线标题 + 无衬线正文;拉丁示例 Newsreader+Roboto):中文等价 = **思源宋体 / Noto Serif CJK SC 标题 + Noto Sans 正文**。**渲染机已确认装了 `Noto Serif CJK SC`(全套粗细)→ Kindle 路径(服务端渲染)标题上宋体可直接用**,newspaper/style_a 尤其推荐(报纸/杂志感)。⚠️ 安卓端 WebView 用的是设备字体:若目标设备没有 CJK 衬线会回退(老设备常无)→ 要安卓也保证衬线,得把字体做成 web font 随 `/app` 下发(5.0+ 支持 woff2);不想下发就让安卓回退 Noto Sans,不强求两端字体完全一致。
- 无 emoji(项目本就用内联 SVG/字符)。

## 6. 关键技术现实(已实测落地)
1. **截图无需改 pipeline(实测确认)**:本仓 Kindle 走 Chrome 单发 `--screenshot`(headless 真渲染,**会跑 JS 且等 load 才截**)。引擎写成**同步**(`shared/news_fit.html`,body 末尾执行)→ 在 load 前就排完版 → 截图截到的就是排好版画面。**`pipeline.py` 一字未动**(避开核心敏感件,零回归风险)。✅ 已用真实数据出图验证(短/长/混合)。
2. **字号机制(已实现于 `shared/news_fit.html`)**:多条放下→`space-between` 在列里均摊铺满;单条放下→**反向放大字号填满**(上限 22px,不超标题);单条都放不下→**逐级缩字**(19→12px 档);到 12px 仍超→`data-clamped` 标记 + 容器 `overflow:hidden` 截断。
3. **无 `description` 的源**:条目只有标题(短)→ 引擎自然多并几条。
4. **轮播**:每次刷新起始位轮转换一批;安卓轮询刷新即换批,Kindle 每轮渲染换批。
5. **无详情/无点开**:内容自包含。

## 6b. 已冻结的契约(6 套风格照此做,别改)
- **共享引擎**:`styles/shared/news_fit.html`(已做好)。每套 news.html 在 `</body>` 前 `{% include 'shared/news_fit.html' %}`,**别各写一套**。
- **容器**:`<div class="news-fit" data-news-fit>`,CSS 必须 `display:flex; flex-direction:column; flex:1; min-height:0; overflow:hidden;` 且声明默认 `--news-fs`(如 17px)。引擎会按需设 `justify-content:space-between` 和 `--news-fs`。
- **每条**:外层 `<div class="nitem" data-news-item>`,**必须 `flex-shrink:0`**(否则内容超高时被 flex 压扁、引擎测不到溢出 → 裁切);**正文字号必须用 `font-size: var(--news-fs)`**(引擎靠它缩放/放大)。
- **遍历**:`{% for it in news.entries %}`(候选批,引擎取前缀);字段 `it.{title,summary,source,category,when}`。`summary` 空就不渲染正文;`category` 非空才显 chip。
- **样板**:照 `styles/style_a/news.html` 抄结构,换各风格视觉(见 §5/§5.1)。
- **schema 残留**:`news.count` 字段已不再被 build_context 使用(改给批量),无害,可后续清理。

## 7. 验收标准
1. 短讯一屏并 2~3 条、长文缩字铺满一屏、超长省略号截断;**任何长度都填满、不溢出、不留大白**(逐条造数据 + 真实 AIHOT 数据各出图验)。
2. **Kindle 截图截到的是"排好版后"的画面**(不是半成品);其他 6 页出图与改动前一致(回归)。
3. 安卓 WebView 下同一套模板/引擎同样自适应;彩色(沿用 android target 上色)。
4. 7 套风格各出图自检(短/中/长/超长/空 各一张),纯灰度(Kindle)无误。
5. `python3 -m pytest tests/ -q` 全绿;新增:build_context 给候选批的测试、引擎核心逻辑(可抽成纯函数/jsdom 测高度决策)、Kindle news 等就绪截图不回退其他页。

## 8. 红线 / 防回归
- ❌ 不接 AI、不生成摘要;feed 无内容就不显示(诚实降级)。
- ❌ 自适应引擎是**一段共享脚本**,6 套风格共用,别各写一套(防分叉)。
- ❌ `pipeline` 的"等就绪"只作用于 news 页,**绝不改其他页/并发渲染/清理逻辑**(CLAUDE.md 渲染红线)。
- ❌ 不动 `rss.py` 采集层;不动鉴权/i18n;`strings.json` 的 zh 与 news 非新增键逐字不变。
- ✅ Kindle 与安卓共用同一套 `news.html` + 引擎(单一源)。

## 9. 分工 + 实现顺序
- **本仓主开发(我)**:① build_context 改给候选批 + 契约/data-contract 同步;② **共享自适应引擎**脚本(measure + fill + 降字号 + 截断 + 就绪标记);③ `pipeline` news 页"等就绪"截图(敏感,我来 + 回归);④ `styles/style_a/news.html` 样板(容器 + 单条卡 + 引入引擎),真实数据出图验证、**冻结容器/单条/引擎契约**。
- **另一个 AI**:照 style_a 样板 + 本文 §5,给 **bento/blueprint/gauge/minimal/newspaper/terminal** 各写新 `news.html`(各自视觉、统一单条结构、走 `--news-fs`、引入共享引擎)。短/中/长/超长/空 各出图自检;`pytest` 全绿。
- 顺序:我先做 ①②③④ 跑绿、冻结契约 → 交样板 + 本文给另一个 AI 做 6 套。
