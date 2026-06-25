# 任务书:浏览器网页版看板(任何设备打开浏览器即可监控)

> ## ✅ 已实现(2026-06-23)—— §3 清单四项全部完成,255 测试绿
> - **① `/app` 全屏 + 设置齿轮 + wakeLock**:右下角浮层(`web/app.html` `#webctl`)。**仅普通浏览器显示**(`window.KDAndroid` 不存在),App 壳内不出现。⛶ Fullscreen API 进/退全屏(进全屏后淡到角落)、⚙ 跳 `/setup?token=`(沿用当前令牌)、`navigator.wakeLock` 静默尝试(HTTP 拿不到不报错,切回前台重申)。
> - **② 双向入口**:`/app` 齿轮 → `/setup`(上条);`/setup` 底部「📱 安卓 App 版」栏新增显眼按钮「🖥️ 在浏览器全屏看板」(`web/setup.html` `#app-open`,指向同令牌 `/app`)+ `/web-simple` 降级页提示。
> - **③ 降级页 `GET /web-simple`**:`server/app.py`,**经令牌不豁免**;静态 HTML 嵌 `/kindle/frame.png`(本就豁免、不另渲染)+ `meta refresh`(按 `page_interval`,显式回带令牌)+ 整图时间戳破缓存。无 JS,古董浏览器可用。
> - **④ 文档**:[`docs/browser-dashboard.md`](browser-dashboard.md)「用浏览器看板」——如实写清不息屏限制(HTTP 下 Wake Lock 拿不到、要么上 HTTPS 要么靠设备息屏设置、平板建议装 App)。HTTPS 一键脚本(可选项)未做,文档已指明路径。
> - **测试**:`tests/test_app.py` 新增 `test_web_simple_fallback_page_served` / `test_web_simple_requires_token_and_preserves_it`;`python3 -m pytest tests/ -q` → **255 passed**。未 `git push`(交回浩轩推)。
>
> ---
>
> **交付对象**:接手的开发者/AI。本文自包含。
>
> ### 接手须知(接入点已核对 2026-06-23,可直接动手)
> - **改动面极小、互不耦合**:① `web/app.html`(加全屏按钮 + 试 wakeLock)② 新增路由 `GET /web-simple`(`server/app.py`,经令牌)③ 文档。**不碰 `styles/` 任何 Kindle 模板** → "Kindle 出图逐字节不变"那条回归红线在本任务**不适用**,风险低。
> - **已核对接入点**:App 内检测就是 `window.KDAndroid`(见 `web/app.html` 内 `if (window.KDAndroid …)`)——`window.KDAndroid` 不存在=普通浏览器→显示全屏按钮;存在=App 内由原生全屏,**不显示**。`app.html` 里已有 `#banner`/`#toast`/`#detail`/`#panel` 等 `position:fixed` 浮层,全屏按钮照搬同款浮层加一个即可。
> - **降级页取图**:`GET /kindle/frame.png` 是当前看板整图、**本就在 `_AUTH_EXEMPT_*` 豁免**(给 Kindle 拉图用),`/web-simple` 可直接 `<img src="/kindle/frame.png">` 复用,不必另渲染。
> - **红线**:`/app`、`/web-simple` 经访问令牌(`/web-simple` 若嵌 `frame.png` 则图本身走豁免,页面外壳仍建议带令牌);**纯展示,绝不引入改设备状态的东西**;**别夸大"不息屏"**——HTTP 下 Wake Lock 基本拿不到,文档和 UI 都要如实写(见 §1②)。
> - **验证**:本机离线渲染/起本地实例自测即可,**别动用户线上服务**;跑 `python3 -m pytest tests/ -q` 保持全绿(新增 `/web-simple` 加一条路由+鉴权测试)。
> - **动手流程**:① 先读仓库根 `CLAUDE.md`(三条铁律 + 鉴权红线 + 已知坑)再动手 ② 照本任务书 §3「要做的清单」逐条做(全屏 / 双向入口 / 降级页 / 文档,共 4 项)③ 完成后跑测试全绿、`git status` 干净 ④ **不要 `git push`**(push 是用户红线,改完交回让浩轩自己推)。沟通用中文,结论先行。
>
> ---
>
> **目标**:任何能上网、能开浏览器的设备(电脑 / 平板 / Kindle 自带浏览器)直接打开一个网址,就看到**实时自动刷新**的看板;点一个「全屏」按钮(像视频播放器那样)就把浏览器导航栏/窗口栏都隐掉,只剩干净看板;尽量让屏幕**不息屏**。不用装 App、不用越狱。

---

## 0. 重要前提:`/app` 已经是「浏览器可开的活看板」

`web/app.html`(路由 `GET /app?token=`)本身就是一个**纯网页**:JS 轮询拉各页、自动轮播、滑动翻页、按屏比 `cw` 自适应铺满。**在现代浏览器(电脑/平板的 Chrome/Edge/Safari)里直接打开它就能用**——文档里那条「二维码下方 `/app?token=` 链接可在任意手机浏览器打开预览」就是它。

所以本任务**不是从零做**,而是给 `/app`(或它的浏览器变体)补几样东西:① 一个可见的「全屏」按钮 ② 尽量保持不息屏 ③ 对**太老的浏览器(Kindle 自带)**给个降级页 ④ `/setup ↔ /app` 双向入口(见 §3 第 2 条)。下面 §1 先逐条说清前三件「能不能做到」。

---

## 1. 三件要补的事 + 各自能不能做到(诚实)

### ① 全屏(隐藏浏览器 chrome)—— ✅ 现代浏览器可做
- 用 **Fullscreen API**:页面放一个全屏按钮,点了 `document.documentElement.requestFullscreen()` → 浏览器进入全屏、导航栏/地址栏/标签栏全没,只剩页面;再点退出。
- 进全屏后把页面自己的全屏按钮也淡出/缩角,达到「跟 Kindle 面板一样干净」。
- **只在用户手势(点击)里能触发**(浏览器安全限制),不能自动进全屏。
- 现代浏览器(电脑/平板)都支持。**Kindle 自带浏览器:大概率不支持**(见 §2)。

### ② 不息屏 —— ⚠️ 这是最难的一块,要管理预期
- 标准做法 **Screen Wake Lock API**(`navigator.wakeLock.request('screen')`):**致命限制——只在「安全上下文」(HTTPS 或 localhost)可用**。看板是**局域网 HTTP**(`http://192.168.x.x:端口`),**绝大多数浏览器在 HTTP 下根本拿不到 Wake Lock** → **默认做不到**。
- 能做到的几条路(按推荐度):
  1. **给看板上 HTTPS**(自签证书有浏览器警告,或用反代/局域网证书)→ 现代浏览器的 Wake Lock 就能用、屏幕常亮。**这是唯一靠谱的"网页保持常亮"方案**,但要额外搭 HTTPS。
  2. **设备自己设"永不息屏"**(电脑电源设置/平板显示设置)→ 最省事最可靠,壁挂场景建议直接这么干,网页不用管。
  3. ~~隐藏循环静音 `<video>` 骗系统不息屏~~:老技巧,现代系统/浏览器多已失效、不稳定,**不建议**。
- **平板(安卓)其实最佳解是装我们的 App**(`FLAG_KEEP_SCREEN_ON` 原生常亮,100% 可靠),不用跟浏览器较劲。
- **结论写清楚给用户**:网页版「自动刷新 + 全屏」能做;「网页自己保持不息屏」在 HTTP 下基本做不到,要么上 HTTPS、要么靠设备自身息屏设置。别承诺"打开网页就永不息屏"。

### ③ 自动刷新 —— ✅ 已有(老浏览器要降级)
- `/app` 已经 JS 轮询自刷新。
- **Kindle 自带浏览器太老**(古董 WebKit,可能没有 `fetch`/Fullscreen/Wake Lock/现代 CSS),`/app` 那套花哨 JS 八成跑不动 → 给它一个**降级页** `GET /web-simple`(或 `/kindle-web`):服务端直接吐**静态 HTML**(甚至就嵌一张 `/kindle/frame.png` 当前看板图)+ `<meta http-equiv="refresh" content="20">` 整页定时重载。古董浏览器也能显示+刷新。全屏/不息屏对 Kindle 浏览器就别指望了(Kindle 真要常亮,**越狱安装那条路才是正解**,不是浏览器)。

---

## 2. 各设备能做到什么(给用户的真实对照表)

| 设备/浏览器 | 看板显示+自刷新 | 全屏隐 chrome | 网页保持不息屏 |
|---|---|---|---|
| 电脑 Chrome/Edge | ✅ `/app` | ✅ Fullscreen API | ⚠️ 仅 HTTPS;否则靠系统电源设置 |
| 平板浏览器 | ✅ `/app` | ✅ | ⚠️ 同上;**更建议直接装 App(原生常亮)** |
| Kindle 自带浏览器 | ⚠️ 古董,需降级页 `/web-simple`(静态+meta refresh) | ❌ 多半不支持 | ❌ 浏览器做不到(常亮走越狱安装) |

## 3. 要做的清单
1. `/app` 加「全屏」按钮(仅在浏览器、非 App 内显示:`window.KDAndroid` 不存在=浏览器→显示;App 内由原生全屏,不显示)+ 进/退全屏切换 + 尝试 `navigator.wakeLock`(拿不到就静默,不报错)。
2. **双向入口动线**(`/setup` ↔ `/app`,全站共用同一个 `server.access_token`,只是路径不同):
   - **`/app` 加「⚙ 设置」齿轮** → 点了跳 `/setup?token=<当前令牌>`。**和全屏按钮同一个判断:仅 `window.KDAndroid` 不存在(普通浏览器)时显示;App 壳里不放**(壳是壁挂全屏看的易误触,且 App 配置走原生设置页 v2、不是这个网页 setup)。令牌就用看板页自己当前那个(它本就带令牌打开),拼 `/setup?token=` 同值即可,别让用户重输。
   - **`/setup` 强化跳 `/app` 的入口**:`web/setup.html` 底部已有一句「在浏览器打开活的 App 版预览」指向 `/app`(`appUrl` 变量已拼好同令牌),把它做成一个显眼按钮(如「🖥️ 在浏览器全屏看板」),形成清晰动线:进 setup 配好 → 一键跳 `/app` 全屏挂着看。
   - **概念别混(写文档时讲清)**:`/setup` 右侧的「实时预览」是**配置的所见即所得静态镜子**(`/kindle/preview.png` 单页、切风格立即变),`/app` 是**会自动轮播刷新的活看板成品**——两者受众/场景不同,**不合并、不互相取代**。
3. `GET /web-simple`(经令牌):古董浏览器降级页,静态 HTML 嵌当前看板图 + `meta refresh`,Kindle 自带浏览器可用。
4. 文档:在 `docs/` 写「用浏览器看板」一节,**如实写清不息屏的限制 + 上 HTTPS 才能常亮 + 平板建议装 App**。可选:`installers/` 给一个一键上 HTTPS(自签/局域网证书)的脚本,让 Wake Lock 在 LAN 可用。

## 4. 安全 / 红线
- `/app`、`/web-simple` 经访问令牌(看板数据,沿用现有鉴权;`/kindle/frame.png` 本就豁免给 Kindle 拉图,降级页可复用)。
- 不为了"全屏/常亮"引入任何会改设备状态的东西(纯展示)。
- 不夸大能力:**不息屏在 HTTP 下做不到这件事要在文档和 UI 上如实说**,别让用户以为打开网页就永不息屏。
