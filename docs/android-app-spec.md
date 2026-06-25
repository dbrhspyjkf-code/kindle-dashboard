# 任务书:安卓 App 版(触控 + 彩色 + 设备控制)

> **交付对象**:接手的开发 AI。本文自包含,读完即可独立施工。
> **状态**:一期**已实现**(2026-06-17,见 [android-app.md](android-app.md));235 测试绿、Kindle 出图逐字节零回归、动作接口真机验证。
> ✅ **最低版本已定:安卓 5.0+(2026-06-17 用户拍板)**。曾考虑兼容 4.0(用户唯一旧设备是 4.x、参考旧项目 `/mnt/work/屏幕监测`=系统 WebView+float/ES5 老式面板),但要 4.0 又不分叉,只能把全部风格改老式 CSS、永久禁用 grid/flex,代价过大;4.0–4.4 设备(2011–2013)也几近绝迹。结论:**只支持 5.0+**;那台 4.0 平板放弃。
> 🔄 **引擎改定(2026-06-17,晚于上面拍板当天)**:渲染引擎从「打包 GeckoView」改为「**用系统自带 WebView**」。原因:GeckoView 把 Firefox 引擎 ×4 ABI 打进 APK = ~300MB;系统 WebView 安卓 5.0+ 均内置、自 5.0 起可经应用商店更新到新版 Chromium 内核,**APK 仅 ~4.2MB**。代价是渲染质量取决于设备 WebView 版本(极旧/从未更新的可能渲染不了 grid),靠真机实测定夺、真崩再回退打包引擎。下文凡提「GeckoView/打包引擎」均按此改读「系统 WebView」;详见 `docs/android-app.md` + `CLAUDE.md`「为什么不用 GeckoView」。
> **铁律**:遵守仓库三铁律(零硬编码 / 配置即页面 / 诚实降级)。**不得破坏 Kindle 现有出图链路、访问令牌鉴权、各数据源采集、i18n、已落地的 8 个页面**(见 `CLAUDE.md`「安全与健壮性」)。新增可配置项 = 先改 `server/config/schema.py`。

---

## 0. 一句话目标
把现有 Kindle 看板**移植成安卓 App**(5.0+),让闲置旧手机/平板当**彩色、可触控**的家庭看板:UI 复用现有风格,且能**点击操作**家里的设备(HA 实体开关等、PT 下载暂停/恢复;3D 打印机控制后于 2026-06-23 移除见 §2.2、改纯只读)。

---

## 1. 已拍板的架构决策(不要推翻,照此实现)

1. **最低安卓 5.0(API 21)**。
2. **WebView 薄壳(用系统自带 WebView)**:App 本体是一个极薄的全屏 WebView 壳,用 `android.webkit.WebView`(安卓 5.0+ 内置、可经应用商店更新),**不打包浏览器引擎**,APK 仅 ~4.2MB。〔原案为「内置 GeckoView 规避旧机渲染坑」,2026-06-17 改定为系统 WebView,见上「引擎改定」〕
3. **单一 UI 真相源 = 现有 HTML 模板**。**绝不另写一套原生 UI**——那会和网页版永久分叉(每次改动做两遍、必然飘移)。Kindle 和安卓**消费同一套 `styles/<风格>/*.html` 模板**:
   ```
           一套 HTML/CSS 模板(唯一 UI 源)
           ├── Kindle 路径(现状,不动):服务端渲染 → Chromium 截图 → 灰度 PNG
           └── 安卓路径(新增):WebView 直接跑「活的 HTML」→ 彩色 + JS 轮询刷新 + 点击调动作接口
   ```
   模板用**目标感知开关** `{% if target == 'android' %}…{% endif %}`(就像现有的 `{% if lang=='zh' %}`)区分:安卓渲染可点控件,Kindle 渲染静态版。**一套源码,两种出口。**
4. **后台从「只读」变「可写」**:新增**动作接口**,把点击转成对 HA / qB / Transmission 的真实操作。
5. **一期范围**(本任务书):后台动作接口 + 交互 HTML + 彩色主题(复用现有 7 套)+ 系统 WebView 壳 + 配置/令牌 + **全部一期交互**(HA 开关 / 打印机控制 / 下载控制 / 点击看详情)+ **JS 轮询刷新**。
6. **二期范围**(本期不做,仅记):安卓专属新风格(控制中心/滚动流/彩色动态图表/左右滑翻页)、SSE/WebSocket 秒级推送、深色 AMOLED 主题。

---

## 2. 模块分解(一期)

### A. 后台:活的交互 HTML 路由
现状:`server/app.py` 给 Kindle 出 PNG(`/kindle/frame.png` 等)。新增**给安卓出 HTML**:
- `GET /app`:返回 App 外壳页(HTML)——含底部/侧边**页面切换标签**(active_pages 的页)、一段**通用 JS**(见下)、彩色主题 CSS。**不含**页面具体内容(内容靠轮询拉)。
- `GET /app/page/<page_key>`:用**现有模板**渲染**单页 HTML 片段**(彩色、带可点控件),供 JS 轮询拉取并替换。实现:
  ```python
  ctx = prep_context(now, dict(cache), cfg)          # 复用现有整合层
  html = styles.render_page(style, page_key, ctx, target="android")  # 复用现有模板,加 target
  return HTMLResponse(html)
  ```
  **不走 Chromium 截图**(安卓不需要 PNG),纯 Jinja 渲染,很轻。
- 通用 JS(写在 `/app` 外壳里,或 `web/app.js`):
  - 每 N 秒(可配,默认 5s)`fetch('/app/page/<当前页>')` → `innerHTML` 替换内容区;
  - 事件委托:点击带 `data-action` 的元素 → POST 动作接口(见 B)→ **乐观更新**(立即给 UI 反馈)→ 成功后立刻重新拉一次该页确认;
  - 页面切换标签:点了切 `<当前页>` 并立即拉;
  - 断线/出错:显示"重连中",退避重试,不白屏(诚实降级)。
- **鉴权**:`/app` 与 `/app/page/*` 与动作接口都要带访问令牌。App 把令牌放在请求头或 query(参照现有 setup 页 `?token=` + `X-Access-Token` 头的做法)。`/app*` **不要**加进 `_AUTH_EXEMPT_*`(它不是 Kindle 拉图,必须鉴权)。

### B. 后台:动作接口(`/api/action/*`,**必须挂在访问令牌后**)
新增 `server/sources/` 之外的动作模块(建议 `server/actions.py`)+ `app.py` 路由。**全部经 `_auth` 保护**(这些能改你家设备,绝不能豁免)。

1. **HA 实体开关** `POST /api/action/ha` body `{entity_id, action}`:
   - 调 HA REST:`POST {ha.url}/api/services/{domain}/{service}` 头 `Authorization: Bearer {ha.token}`,body `{"entity_id": entity_id}`。
   - `domain` = entity_id 前缀(`light`/`switch`/`fan`/`lock`/`cover`…);`service` 按 kind 映射:开关类→`toggle`(或 `turn_on`/`turn_off`);锁→`lock`/`unlock`;窗帘→`open_cover`/`close_cover`。建议 action 传 `toggle`/`on`/`off`,后台按 domain 转具体 service。
2. **打印机控制** `POST /api/action/printer` body `{action: pause|resume|stop}`:
   - 经 HA(拓竹集成把暂停/恢复/停止暴露为 button/switch 实体或 service)。后台调对应 HA 服务。**stop 属危险操作**,前端必须二次确认(见 D)。
   - ❌ **已于 2026-06-23 移除**(本设计稿保留作历史):真机实测云模式(`bambu_cloud`)下 `button.press` 在 HA 成功但打印机不响应,纯属上游限制;打印机页改纯只读。切拓竹 LAN 模式后可复活。详见 `docs/android-app.md` 与记忆 `bambu-ha-cloud-offline-quirk`。
3. **下载控制** `POST /api/action/torrent` body `{client, id, action: pause|resume}`:
   - 按 `client`(下载器名)找到配置 → 对应 adapter 的**写方法**:
     - qB:`POST /api/v2/torrents/pause?hashes={hash}` 与 `/resume?hashes={hash}`(qB 4.x;**注意 qB 5.0 改名 `/stop`、`/start`**,实现时按版本兼容或两个都试)。登录态复用 `_qb_fetch` 的登录流程(带 Referer)。
     - Transmission:`{"method":"torrent-stop","arguments":{"ids":[id]}}` / `"torrent-start"`,复用 409 握手 + Basic auth。
   - `server/sources/downloader.py` 加 `qb_action(client, hash, action)` / `tr_action(client, id, action)`。
- 所有动作接口:成功返 `{ok:true}`,失败返 `{ok:false, error}`(前端提示,不崩);**幂等**(重复点不出错)。

### C. 契约改动:把「可操作 id」透出来(只给 App 用,Kindle 无视)
现有契约只够**显示**,要**点了能操作**必须带路由 id。**追加字段(向后兼容,Kindle 不读)**:
- `ha.cards[*]` 加 `entity_id`(`server/sources/homeassistant.py` 的 `_build_card` 里塞进去)。
- `download.torrents[*]` 加 `id`(qB=torrent `hash`,Transmission=`id`)+ `client`(下载器名,路由用)。`server/sources/downloader.py` 的 `_qb_norm`/`_tr_norm` 各加,collect 合并时把 `client` 名带上。
- 同步更新 `contract.empty_ha`/`empty_download` 与 `docs/data-contract.md`(标注「仅 App 交互用」)。
- **注意 Jinja 坑**:字段名别撞 dict 方法(已有 `entries`/`torrents` 的前例)。

### D. 彩色主题(一期:复用现有 7 套,加颜色)
现有 7 套是灰度墨水屏设计(`--ink`/`--ink2`/`--ink3` 变量)。一期**不重画**,加一层颜色:
- 每套 `style.css` 顶部的 CSS 变量已是单一调色入口。新增**彩色变量覆盖**:`target == 'android'` 时注入一组强调色(状态绿/红/蓝、进度条色、激活态色),保持版式不变、只上色。
- 实现建议:`render_page(..., target)` 在 android 时多注入一个 `theme` 变量或一段 `:root{}` 覆盖 CSS;或模板顶部 `{% if target=='android' %}<link/style 彩色覆盖>{% endif %}`。**灰度默认值不动**(Kindle 像素级不变,回归红线)。
- 上色克制:状态用色(在线绿/离线灰/告警红)、进度条/图表着色、激活态强调;别花哨。
- **交互控件的"可点感"**:android 下给可操作元素加按钮样式/涟漪/按压反馈(纯 CSS/JS),让人知道能点。

### E. 模板目标感知(交互控件)
- `styles.render_page(style, page_key, ctx, d=None, target="kindle")` 加 `target` 参数(默认 kindle,保证现有调用与 Kindle 路径**零改变**)。注入模板变量 `target`。
- 各页模板在需要操作处加 `{% if target=='android' %}<button data-action=...>{% endif %}`:
  - HA 卡:整卡可点 `data-action="ha" data-entity="{{ c.entity_id }}"`。
  - 打印机:暂停/恢复/停止按钮 `data-action="printer" data-cmd="pause|resume|stop"`。
  - 下载:每条种子暂停/恢复 `data-action="torrent" data-client="{{ t.client }}" data-id="{{ t.id }}" data-cmd="pause|resume"`。
  - 「点击看详情」:卡片 `data-detail`,JS 弹出详情层(纯前端,展示更多字段)。
- **Kindle 路径不渲染这些控件**(target=kindle),静态版与现状完全一致。

### F. 安卓 App(系统 WebView 薄壳)
- **Android 项目**(Gradle),`minSdkVersion 21`,**用系统自带 `android.webkit.WebView`**(不打包引擎)。
- 职责(全是「非 UI」能力,不会和网页分叉):
  1. 启动一个全屏 `WebView`(`JavaScriptEnabled` + `DomStorageEnabled`),加载 `http://<服务器>:<端口>/app?token=<令牌>`。
  2. **全屏沉浸**(隐藏状态栏/导航栏)、**屏幕常亮**(`FLAG_KEEP_SCREEN_ON`)——壁挂常亮看板。
  3. **首次配置页**(唯一的原生界面):填**服务器地址 + 访问令牌**;最好支持**扫二维码**(设置页生成,见 G)。存本地(加密 SharedPreferences)。
  4. **断网/服务器不可达**:显示重连提示,自动重试(别白屏崩溃)。
  5. (可选)**开机自启**、亮屏保持、防休眠——kiosk 壁挂场景。
- **不写任何业务 UI**:页面、卡片、风格、交互全在 WebView 里的 HTML。原生只有「配置页 + 一个 WebView」。
- **分发**:构建 APK,侧载(旧设备当看板,不上应用商店)。README/文档给安装说明。

### G. 配置/令牌下发(设置页生成二维码)
- `web/setup.html` 加一块「安卓 App」:显示一个**二维码**,编码 `{url, token}`(或一条深链)。App 扫码即完成配置,免手敲 IP 和令牌。
- 二维码用前端 JS 库生成(轻量,本地内联,别引 CDN——离线可用)。

---

## 3. 安全(动作接口是能改你家设备的口,务必守住)
- `/app`、`/app/page/*`、`/api/action/*` **全部经 `_auth` 鉴权**,**绝不进 `_AUTH_EXEMPT_*`**。令牌空=放行的向后兼容逻辑仍在,但文档要强烈建议 App 场景设令牌。
- **危险动作二次确认**(前端):停止打印、(未来)删除种子等 → 弹确认框再发。
- 动作接口**只做白名单内的操作**(toggle/on/off/pause/resume/stop),不接受任意 service/任意命令透传(防注入)。
- 令牌在 App 端加密存储;不进日志。

---

## 4. 验收标准(一期)
1. 安卓 5.0+ 设备装上 APK、扫码配置后,全屏彩色显示看板,**复用现有风格**、内容每 5s 自动刷新。
2. **Kindle 路径完全不受影响**:`/kindle/frame.png` 出图、各页、灰度、像素级与改动前一致(target=kindle 默认)。
3. 交互全部生效(经真机后台验证):
   - 点 HA 实体 → 灯/开关真的开关,状态下一轮变;
   - 点打印机暂停/恢复 → 经 HA 真的暂停/恢复,停止有二次确认;
   - 点种子暂停/恢复 → qB/Transmission 真的暂停/恢复;
   - 点卡片 → 弹详情。
4. 鉴权:无令牌/错令牌访问 `/app`、`/api/action/*` 被拒。
5. 断网/服务器挂 → App 显示重连、不崩;某动作失败 → 提示、不崩。
6. `python3 -m pytest tests/ -q` 全绿;**新增**:动作接口(mock HA/qB/Transmission)、`render_page(target='android')` 含控件而 `target='kindle'` 不含、契约新增字段的测试。

---

## 5. 红线 / 防回归
- ❌ **不另写原生 UI**——单一 HTML 源是这个方案的命根子,违背它=分叉地狱。
- ❌ 不动 Kindle 出图链路、`_auth`、各 source 采集、i18n、已有 8 页的现状(target 默认 kindle,保证零影响)。
- ❌ 动作接口不豁免鉴权、不透传任意命令。
- ❌ 契约新增字段是**追加**(Kindle 模板不读),别改/删现有字段;别用 dict 方法名当字段名。
- ❌ 彩色只在 `target=='android'` 生效;灰度默认值与现状逐字一致(Kindle 回归)。
- ✅ 用系统自带 WebView 渲染(不打包引擎);渲染质量靠目标真机实测,旧机渲染崩再回退打包引擎。

---

## 6. 实现顺序建议
1. **模板 target 参数** + Kindle 路径回归测试(先证明 target=kindle 零影响)。
2. **契约追加 id**(ha.entity_id / torrent.id+client)+ 测试。
3. **动作接口**(actions.py + HA/qB/Transmission 写方法)+ mock 测试 + **真机后台验证**(HA 192.168.1.100 / qB 8085 / Transmission 9091)。
4. **活 HTML 路由** `/app` + `/app/page/*` + 通用轮询/动作 JS。
5. **彩色主题**覆盖(7 套)+ 模板交互控件 `{% if target=='android' %}`。
6. **设置页二维码**下发。
7. **安卓系统 WebView 壳**(Gradle 项目 + 配置页 + 全屏常亮 + 扫码 + 重连)→ 构建 APK。
8. 文档:`docs/android-app.md`(安装/配置/构建说明)+ 回写 `CLAUDE.md`(新机制:target 双出口 / 动作接口 / 鉴权)与 `CLAUDE_TASK_QUEUE.md`。

## 7. 分工建议
- **后台(2.A–E)+ 模板 target/彩色/交互控件 + 动作接口 + 测试**:熟悉本仓的开发(可连真机验证),风险集中、要和现有链路精确咬合。
- **安卓壳(2.F)+ 二维码(2.G)**:需 Android 构建工具链;greenfield,可并行。
- 两边接口契约(`/app`、`/api/action/*`、令牌头)先冻结,再并行。
