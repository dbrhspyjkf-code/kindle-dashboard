# 安卓 App 版(触控 + 彩色 + 设备控制)

> 把闲置旧手机/平板(安卓 5.0+)变成**彩色、可触控**的家庭看板,还能点着**操作设备**(HA 实体开关/窗帘/空调/媒体/安防…、PT 种子暂停/恢复)。
> ⚠️ 3D 打印机控制(暂停/停止)已移除——经 HA 拓竹云模式控制指令到不了打印机(真机实测无效),打印机页改纯只读显示;切 LAN 模式后可恢复。
> 设计与一期范围见 `docs/android-app-spec.md`。本文讲**怎么用、怎么构建**。

> ✅ **主流目标:安卓 5.0+(API 21;更老的 4.x 到 4.2 另见下条 minSdk17 兼容方案)**(2026-06-17 拍板)。**用系统自带 WebView**(不打包引擎,APK 仅几 MB;5.0+ WebView 可经应用商店更新到新内核)。绝大多数"闲置旧手机/平板"(2014 年后)都覆盖。
> 🔄 **2026-06-23 方向更新**:不再"放弃 4.x"。用户目标机=**安卓 4.2**,**老系统兼容方案代码侧已实现**(⏳唯一剩 4.2 真机验):**一个 minSdk17 包通吃**——运行时 `SDK_INT` 守卫分流(≥21 走现状 `/app`;<21 极简纯 Activity 加载 `/app-legacy` float-CSS 降级活页)。**不改 7 风格**(legacy 是独立 `styles/legacy/` 模板集)。GeckoView 方案已废弃(minSdk21 装不到 4.2)。
> **构建要点**:`minSdk 21→17` 后,appcompat/zxing/security-crypto 等声明 minSdk21 的库需在 `AndroidManifest` 用 `tools:overrideLibrary` 压入;**所有现代 API/库调用必须包在 `SDK_INT` 守卫分支内,4.x 路径一个现代库都不碰**(否则老系统类加载即崩)。
> **浏览器/壳的 UA 三档分流**(服务端 `app._classify_ua`):古董(Kindle / Silk / NetFront / Android 0–2.x)→ `/web-simple`、老安卓(Android 3–4.x)→ `/app-legacy`、其余现代 → `/app`;`?force=app|legacy|simple` 可覆盖。

## 它是怎么工作的(一套 HTML,两个出口)

```
        一套 styles/<风格>/*.html 模板(唯一 UI 源)
        ├── Kindle 出口(现状,不变):服务端渲染 → Chromium 截图 → 灰度 PNG
        └── 安卓出口(新增):WebView 直接跑「活的 HTML」→ 彩色 + JS 轮询 + 点击调动作接口
```

- **没有第二套原生 UI**。安卓 App 是一个极薄的全屏 WebView 壳(用系统自带 `android.webkit.WebView`,不打包浏览器引擎,APK 仅几 MB),加载后台的 `/app` 活 HTML。
- 模板用 `{% if target == 'android' %}` 区分:安卓渲染可点控件 + 彩色;Kindle 渲染静态灰度版(**像素级不变**,见下「回归保证」)。
- 后台从「只读」变「可写」:新增动作接口把点击转成对 HA / qB / Transmission 的真实操作。

## 后台:新增了什么(服务端,已随主服务上线)

| 路由 | 作用 | 鉴权 |
|---|---|---|
| `GET /app` | App 外壳页(自动轮播 + 滑动翻页 + 轮询/动作 JS + 横屏自适应缩放)。`?token=` 带令牌。 | **需令牌** |
| `GET /app/page/<key>` | 用现有模板渲染**单页活 HTML 片段**(`target=android`,彩色可点)。不走截图。 | **需令牌** |
| `POST /api/action/ha` | 控制 HA 实体。body `{entity_id, action, value?}`。按 entity 域走白名单:开关 `toggle/on/off`、锁、窗帘(开/关/停)、空调(开关+`set_temp`/`set_mode`)、媒体(播放/暂停/上下曲/音量)、选择器 `select_option`、数值 `set_value`、按钮 `press`、安防 `arm_*/disarm`。service 固定、value 按类型校验(防注入)。 | **需令牌** |
| `POST /api/action/torrent` | 种子暂停/恢复。body `{client, id, action}`,action ∈ `pause/resume`。 | **需令牌** |
| `GET /api/action-state` | 所有可控目标当前状态(HA 用 `controllable_inventory` 全量按 kind 分组 + 只读传感器单列 / 打印机 online·status·progress / 每下载器每种子 state·progress),供测试台做点前/点后对照。各源独立降级。 | **需令牌** |
| `GET /action-test` | 动作接口真机测试控制台页(`web/action-test.html`,纯 HTML+fetch,带搜索)。按 kind 给对的控件,每个控制点「点前→点后」并排显示,逐项验真设备响应。 | **需令牌** |
| `GET /qrcode.js` | 设置页二维码库(公共 MIT 库,无密钥)。 | 豁免 |

**安全(务必懂)**:`/app`、`/app/page/*`、`/api/action/*`、`/api/action-state`、`/action-test` 全部经访问令牌鉴权,**绝不豁免**(它们能改/暴露你家设备)。动作接口**只接受白名单操作**(HA 各 kind 白名单 + torrent pause/resume),不透传任意 service/命令(防注入)。强烈建议 App 场景在设置页设一个访问令牌。

**轮询间隔**可配:设置页「服务」段的 `App 刷新间隔(秒)`(`server.app_poll_interval`,默认 5),与 Kindle 出图间隔无关。

## 配置 App

App 首次启动是配置页,三种方式填服务器地址:

**A. 搜索局域网服务器(最省事,不用敲 IP)**
点「🔍 搜索局域网服务器」→ App 用 mDNS(`NsdManager`)发现广播 `_kindledash._tcp` 的看板 → 自动填好地址(多台则弹列表选)。**令牌不经 mDNS 广播**(密钥不上网),所以地址自动填好后,**令牌仍需扫码或手填**。
> 需服务端开着 mDNS 广播(装了 `zeroconf`、服务正常启动即自动广播;见下「服务端 mDNS」)。搜不到多半是:服务没跑 / 手机和服务器不在同一 WiFi / 路由器开了 AP 隔离 → 改用扫码或手填。

**B. 扫码(地址+令牌一次到位)**
1. 用带令牌的链接打开看板**设置页**(`http://<IP>:端口/setup?token=...`)。
2. 翻到「服务」段底部「📱 安卓 App」卡片,会显示一个**二维码**(编码 `{url, token}`)。
3. App 点「扫码配置」(竖屏扫)→ 扫这个二维码 → 自动填好服务器地址和令牌 → 保存。

**C. 手填**:服务器地址(如 `http://192.168.1.100:8585`)+ 访问令牌。

之后 App **锁横屏、全屏常亮**显示看板:**无底部页签**,页面**自动轮播**(间隔=设置页「服务」段 `翻页间隔`/`page_interval`,默认 20s),也可**左右滑动**像相册一样手动翻页;内容每几秒自动刷新(`app_poll_interval`,默认 5s);点 HA 卡(简单直发/复杂弹面板)、种子按钮即操作设备(打印机为只读)。地址/令牌**只存本机**(API 23+ 加密;21~22 明文回退)。二维码下方还有一条 `/app?token=...` 链接,可直接在任意手机浏览器打开预览活的 App 版(无需装 APK)。浏览器里点 ⛶ 可全屏、点 ⚙ 回设置页;Kindle 古董浏览器用静态降级页 `/web-simple`。**不装 App 直接用浏览器看板**的完整说明(含不息屏的诚实限制)见 [browser-dashboard.md](browser-dashboard.md)。

> **全屏/固定画布缩放(2026-06-24 重构,推翻旧 cw 方案)**:看板画布**恒 800×600**(与 Kindle 一致)。`web/app.html` 的 `fit()` 缩放整块画布:高度按 `min(屏宽/800, 屏高/600)` 等比填满,**横向在等比基础上再轻度拉伸(最多 `STRETCH=1.2` 倍)吃掉部分留白**;剩余留白用**看板自身背景色**填充(白底→白、深色→深),视觉填满。
> **为什么这么做**:「等比缩放 + 填满任意比例屏 + 内容不变形」三者几何上只能同时满足两个。旧方案(按 `cw` 重排内容铺满)能消留白,但要求每套风格每页在 800~1600 任意宽度都零溢出——对开源(用户屏幕千奇百怪)是修不完的 bug(踩过 home 宽屏溢出 30px);固定画布缩放是对**任意比例的通用解**,零溢出零适配。`STRETCH=1.2` 的轻度横向拉伸是「留白↔变形」折中(16:9 下变形≈20%、残留留白≈5%/侧,用户实测拍板)。**已删** `computeCW`/`?cw=`/服务端 cw 注入;7 套 `home.html` 旧的 `@media(min-width:900px)` 宽屏块也已删除(画布恒 800 永不触发=死代码)。

### 服务端 mDNS(自动发现的前提)
- 服务端启动时自动广播 `_kindledash._tcp.local.`(端口=看板端口,TXT 带 `path=/app`、`name=主机名`),退出时注销。依赖 `zeroconf`(已进 `server/requirements.txt`);**没装则静默跳过**(不影响服务启动),装上重启即生效。
- ⚠️ **NAS Docker**:桥接网络(默认)下 mDNS 多播出不了容器,App 搜不到 → 需用 host network 部署,或直接扫码/手填。

## 构建 APK(开发者)

工程在仓库 `android/`(Gradle,Java,minSdk 21)。**用系统自带 WebView**(`android.webkit.WebView`),不打包浏览器引擎 —— APK 仅几 MB(实测 debug **~4.2MB**)。

### 方式一:Android Studio(推荐)
1. Android Studio → Open → 选 `android/` 目录。
2. 等 Gradle 同步(会自动补 `gradle-wrapper.jar` + 下载 androidx/zxing 依赖)。
3. Build → Build Bundle(s) / APK(s) → Build APK(s)。产物在 `android/app/build/outputs/apk/`。

### 方式二:命令行
需要 JDK 17 + Android SDK(`ANDROID_HOME` 指向 SDK)。首次在 `android/` 跑一次 `gradle wrapper` 生成 wrapper jar(见 `android/gradle/wrapper/README.md`),然后:
```bash
cd android
./gradlew assembleRelease      # 或 assembleDebug
# 产物:app/build/outputs/apk/release/app-release-unsigned.apk(release 需自己签名)
```

### 侧载到设备
- `adb install -r app/build/outputs/apk/debug/app-debug.apk`,或把 APK 拷到设备点击安装(需开「未知来源」)。
- 旧设备当壁挂看板:开发者选项里关闭「自动息屏」更稳;App 已 `FLAG_KEEP_SCREEN_ON` 屏幕常亮 + 全屏沉浸。

### 渲染引擎:系统 WebView(不打包引擎)
- 看板用设备**自带的 `android.webkit.WebView`** 渲染。安卓 5.0+ 均内置,且自 5.0 起 WebView 是**可经应用商店独立更新**的系统组件 —— 正常用的设备早已更到新版 Chromium 内核,渲染现代 CSS(grid/flex/变量)无碍。
- **代价(要知道)**:渲染质量取决于该设备的 WebView 版本。极旧、从未更新过 WebView 的设备(无 Google Play 的国产纯净刷机包最极端)可能停在很老内核 → 渲染不了 grid 等 → 设备页可能散架。**靠目标真机实测定夺**;真崩再回退打包引擎(GeckoView)或做兜底。
- WebView 配置:`JavaScriptEnabled`(页面轮询/动作接口)+ `DomStorageEnabled`(令牌存 sessionStorage)。http 明文靠 Manifest `android:usesCleartextTraffic="true"`(系统 WebView 走安卓网络栈、受明文策略管)。

### 依赖版本(可按需升级)
- `androidx.security:security-crypto`(令牌加密存储)、`com.journeyapps:zxing-android-embedded`(扫码)、`androidx.appcompat` + `androidx.activity`
- AGP 8.1.4 / Gradle 8.2 / compileSdk 34
- ⚠️ **kotlin-stdlib 版本对齐**:zxing 拉 `kotlin-stdlib-jdk8:1.6.21`、androidx 拉 `kotlin-stdlib:1.8.22`;kotlin 1.8 起 jdk7/jdk8 的类并入主 stdlib,版本不一致会**重复类、构建失败**(`Duplicate class kotlin.*`)。`app/build.gradle` 用 `configurations.all { resolutionStrategy.force ... }` 把三个 stdlib 变体锁到 1.8.22 修掉。(早先打 GeckoView 时它顺带对齐了版本,移除后冲突才暴露。)
- 已验证本机自包含工具链(`~/android-build/setup.sh`,JDK17/SDK34/Gradle8.2,走代理)出 debug APK **~4.2MB**。

## 回归保证(Kindle 不受影响)
- `render_page(..., target)` **默认 `kindle`**,所有现有调用零改变。
- 模板新增控件全部包在 `{% if target=='android' %}`;`target=kindle` 渲染出的 **PNG 与改动前逐字节相同**(已用 7 风格 × 交互页验证)。
- 契约新增字段(`ha.cards[].entity_id`、`ha.cards[].meta`、`download.torrents[].{id,client}`、`printer.paused`)是**追加**,Kindle 模板不读,见 `docs/data-contract.md`。
- **HA 页三档点击交互(2026-06-23 落地)**:A 类(toggle/lock/scene/button)单击直发动作、B 类(cover/climate/media/select/number/alarm)单击弹 `app.html` 的 `#panel` 底部控制 sheet(数据走卡片 `meta`)、C 类(传感器等)只读详情;B/C 卡 `›` 角标(纯 CSS,仅 android)。`_build_card` 给新 kind 分类时 **Kindle-read 字段逐字节不变**(有字节对比测试背书)。完整定稿见 `docs/ha-page-interaction-spec.md`。

## 一期不做(仅记)
安卓专属新风格(控制中心/滚动流)、SSE/WebSocket 秒推、AMOLED 深色主题。见 `docs/android-app-spec.md §1.6`。

---

## v2:原生设置页 + 图标/启动图 + 签名 release(纯壁挂 kiosk)

> 任务书 `docs/android-app-v2-spec.md`;签名出包 `docs/android-release.md`。用法=纯壁挂 kiosk,**不做**双模式/日常手机 app。

### A. 悬浮齿轮设置入口(每页可见、**可拖动**)
- `MainActivity` 根 `FrameLayout` 上叠一个**单色圆形磨砂**小齿轮(`ImageButton`,36dp、深灰 `#4D4D4D` 齿轮 + `gear_bg` 半透明浅圆+细描边、alpha 0.5)。单色磨砂跟墨水屏单色调一致,不突兀。所有页面都在(原生悬浮层,不碰 WebView 页面模板、不影响 Kindle 出图),错误层在它之上,断线时盖住。
- **可拖动 + 记忆位置**(2026-06-22 用户要求):绝对定位(`gravity TOP|START` + `leftMargin/topMargin`),`onTouch` 里**轻点=进设置**(`performClick`)、**拖动=挪位置**(靠 `ViewConfiguration.getScaledTouchSlop()` 区分),拖到哪松手就**按比例(0~1)存 `Prefs`**(`gear_fx/fy`,换分辨率/旋转也稳),下次打开还在那。初始位置 `placeGearInitial()`(首帧 `root.post` 后 root 才有尺寸):读存的比例,没有则默认**右下角**(页脚区最不抢眼)。拖动时约束在屏幕内。
- 点击 → `startActivity(SettingsActivity)`。**(演进:v2 初版右上+蓝方块撞天气/农历且突兀 → 右下单色磨砂圆 → 用户要求改为可拖动,自己摆到顺手处)**

### B. 原生分类设置页 `SettingsActivity`(完全 schema 驱动,不硬编码字段)
- **数据流(全用现成接口,服务端零改动)**:进入并发拉 `GET /api/schema`(分类+字段,服务端已按 `server.language` 本地化)+ `GET /api/config`(当前脱敏值);令牌走 **header `X-Access-Token`**(不进 URL/日志)。改完 `POST /api/config`,body `{config: <整份脱敏 config>}`(和网页同款整份提交,服务端 `_merge_for_save` 合并 + 热重载)。
- **两级导航**:第一屏=分类列表(schema 各 section 的 `label`,全隐藏字段的段不显示)+ 顶部额外「本机 / 服务器连接」;点一类→二级页只显示该类字段;返回键二级→一级。全程序化 UI(不依赖布局 XML)。
- **字段类型→控件**:`str`/`secret`=EditText(secret 用 password inputType、不回显原值、**留空=不改**)、`int`/`float`=数字 EditText、`bool`=Switch、`enum`=Spinner(`options` 取 `[value,label]`)、`str_list`=多行(一行一项)、**`module_list`=原生增删改**(每项一张卡片内联渲染其 `item_fields`,可「添加一项」/「删除该项」/逐项改;复用同一套 `buildControl` 渲染子字段;item 里的特殊类型 `ha_entity`/`city`/`printer` 退化成文本框可手填)。`hidden=true` 字段不显示(列表项里的隐藏子字段如 HA `icon` 不渲染但**保留原值**回传)。
- **保存后停留在当前二级页(2026-06-22 改)**:保存=原地禁用按钮→POST→Toast「已保存」,**不重建 UI、不回分类列表、滚动位置不变**(用户可接着改下一项)。旧行为保存即跳回列表顶部、要重新滑下来,已修。
- **分类列表返回保留滚动位置(2026-06-22 用户要求)**:分类列表视图**缓存复用**(同一个 `ScrollView` 实例);列表滑到某项→点进二级页(`render` 把列表 detach 但字段仍持有)→返回(`onBackPressed`→`showCategoryList` 重新 attach 同实例)→**`scrollY` 原样保留**,不再弹回顶部。仅在去过子 Activity(本机连接/网页高级设置)回来才置 `reloadOnResume` 重拉重建(此时按新数据重建到顶,合理);普通 resume(焦点变化)不动状态。`loadSchemaAndConfig` 成功后作废缓存(schema 可能变)。
- **复杂选择器走网页高级入口**:城市搜索 / 浏览 HA 实体 / 发现 push 设备 / 扫描打印机这些**专用控件**(非纯 schema)本期原生退化成文本框,段底部留一个「网页高级设置」链接→应用内 `WebPageActivity` 开 `/setup?token=` 用网页那套(返回时 `onResume` 重拉同步)。
- **secret 安全**:脱敏 config 里 secret 是掩码 `••••••`;原生不回显原值,EditText 留空则保持掩码回传,服务端 `_merge_for_save`/`_merge_list` 据掩码**保留原值**(防泄漏+防误清)。`module_list` 整份回传脱敏列表,secret 子字段按 `item_fields[0]` 标识匹配回填旧值(改名=视为新项需重填,同网页)。
- **「本机连接」段**(设备本地,不在服务端 schema):改这台设备连哪个服务器 + 访问令牌(存 `Prefs`,不进服务端 config),复用 v1 `SetupActivity`(扫码/mDNS/手填)。
- 网络:`ApiClient`(`HttpURLConnection`,不引第三方库,工作线程同步调用 + Handler 回主线程);加载/出错/重试态。

### C. 图标 + 启动图 + 签名 release
- **自适应图标**:`mipmap-anydpi-v26/ic_launcher(.xml/_round.xml)` = `<adaptive-icon>`(背景 `ic_launcher_background`=**品牌蓝 `#2F6FED` 满铺** + 前景 `ic_launcher_foreground`=**白色「看板磁贴」字形**(白卡+蓝条),落安全区;2026-06-23 由「深底+蓝卡」改为「蓝底+白卡」=方案2,去掉突兀大黑底);pre-26 用各密度 PNG `mipmap-{mdpi..xxxhdpi}/ic_launcher(.png/_round.png)`(同配色,PIL 生成)。Manifest `icon=@mipmap/ic_launcher`、`roundIcon=@mipmap/ic_launcher_round`。**应用名「墨水桌面看板」**(`strings.xml` 的 `app_name`;2026-06-23 由「Kindle 看板」改——定位=个人桌面信息面板,去 Kindle 绑定;「墨水」接 7 套风格的墨水屏美学。项目名/仓库/包名 `com.kindledash.app` 不动)。
- **启动图**:Android 12+ `values-v31/themes.xml` 用 SplashScreen API(`windowSplashScreenBackground`=**品牌蓝** + `windowSplashScreenAnimatedIcon`=白色看板前景);11 及以下 `Theme.KindleDash.Splash` 的 `windowBackground=@drawable/splash_bg`(layer-list:蓝底 + 居中白卡)兜底。**与图标同蓝、统一**。`MainActivity` 用 Splash 主题,WebView 绘出后即盖住。
- **签名 release**:`app/build.gradle` 加 `signingConfigs.release`,**keystore 路径+口令从 `android/keystore.properties`(gitignore 已排除)或环境变量读**,绝不进 git;没配=release 不签名(debug 不受影响)。`versionCode 2`/`versionName 2.0`。生成 keystore + 出签名 APK 步骤见 `docs/android-release.md`。

### D. 在线更新(2026-06-23 实现)
- 设置页加「检查更新」→ `UpdateChecker` 查 `api.github.com/repos/yizhixiaoheigou/kindle-dashboard/releases/latest`(常量 `OWNER`/`REPO`,带 `User-Agent` 否则 403)→ 解析 assets 里 `.apk` 附件 → **从文件名尾部解析 versionCode**(约定 `MoshuiDesktop-<vName>-<vCode>.apk`)与本机 `PackageManager` versionCode 比 → 大于则弹更新框(标题=tag、正文=Release body)。
- 下载:`HttpURLConnection` 下到 `getExternalFilesDir/update/`,**手动跟随重定向**(GitHub 下载 302 到对象存储、默认不跨 http↔https 跟随),`ProgressDialog` 显进度。安装:`FileProvider`(`${applicationId}.fileprovider` + `res/xml/file_paths.xml`)生成 `content://` → `ACTION_VIEW`+`application/vnd.android.package-archive` 拉系统安装器。**侧载不能静默**:API26+ 先 `canRequestPackageInstalls()`,没授权引导去 `ACTION_MANAGE_UNKNOWN_APP_SOURCES`。
- **签名一致是前提**(新旧同 keystore 否则拒装)→ 依赖正式签名(已就绪)。新增 `REQUEST_INSTALL_PACKAGES` 权限 + FileProvider + `UpdateChecker.java`;改 `SettingsActivity`/Manifest/strings/`build-release.sh`(产物按版本号命名直接传 Release)。
- **自动检查 + 齿轮红点(2026-06-23,用户要求)**:`MainActivity` 启动 8 秒后查一次 + 之后**每 6 小时**静默查(`handler.postDelayed` 循环 + 工作线程 `UpdateChecker.check`),发现新版→**悬浮齿轮右上角亮小红点**(`red_dot` drawable;齿轮包进 `gearWrap` FrameLayout=齿轮+红点,拖动/定位的是 wrap、红点天然跟随);进设置页静默查一次(本会话只查一次,省请求)→「检查更新」行副标题标红「发现新版 vX.Y · 点此更新」。**侧载装那一下仍须用户点系统安装框**(自动只到"发现+提示",不能无人值守静默装)。`onDestroy` 清定时器。

### 发版流程(以后每次)
1. `app/build.gradle` `versionCode`+1、`versionName` 改新。2. `bash ~/android-build/build-release.sh` → 出 `work/apk/MoshuiDesktop-<vName>-<vCode>.apk`(签名+版本号命名)。3. GitHub 建 Release 把该 APK 当附件传,body 写更新内容。4. 用户点「检查更新」即可。

### 正式签名(2026-06-23 已生成跑通)
`signingConfigs.release` 从 `android/keystore.properties`(gitignore)读;keystore 在用户本机 `~/kindledash-release.jks`(仓库外),alias `kindledash`,DN `CN=Moshui Desktop, O=yizhixiaoheigou, C=CN`,SHA-256 `3b104757…6579b7`,**口令只在用户手里**。详见 `docs/android-release.md`。

### 服务端改动
**无**。`/api/schema`、`/api/config`(GET/POST)v1 已在且带令牌,原生设置页直接用;整份提交走 `_merge_for_save`(网页同款)。在线更新只读 GitHub 公共 API,服务端不参与。241 测试绿、零回归。

### 构建验证
本机自包含工具链(`~/android-build/`,`rebuild.sh` 复用已装 JDK/SDK/Gradle 不重下载)`assembleDebug` 通过,**APK ~4.4MB**(v1 ~4.36MB,无引擎膨胀);aapt 验:5 个 Activity 注册齐(Main/Setup/Settings/WebPage/PortraitCapture)、icon=自适应、versionCode 2。⏳ 待用户:Android Studio/工具链装到真机走一遍设置页改值往返(含 module_list 增删一项)+ 出签名 release 包。

## v3 待排期(任务书 §6,本期不做)
看板播报(横幅 + 语音 TTS)、屏幕控制(真息屏/定时息屏亮屏,需设备管理员权限)、在线升级 B(要发 GitHub Release 才做)。
