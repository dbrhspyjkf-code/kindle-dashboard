# 数据契约(给风格作者看)

> **风格 = 同一批数据字段的不同皮肤。** 你做新风格时,模板里能用的变量就是本文列出的这些,名字/类型都已冻结。契约稳了,你随便换布局换 CSS,数据层一个字不用动。
>
> 权威定义在 `server/render/contract.py`(本文是它的人类可读摘要,改契约要两边同步)。
> 缺数据/未配置时所有字段都有降级占位(数字→`0`,文本→`--`,列表→`[]`),所以模板**永远不会拿到 undefined**,放心用。
>
> **安卓 App 版**(触控 + 彩色 + 设备控制)复用同一套契约,只**追加**了几个 App-only 字段(`ha.cards[].entity_id`、`ha.cards[].meta`、`download.torrents[].{id,client}`、`printer.paused`),供 `{% if target=='android' %}` 控件路由到动作接口用;Kindle 出图不读这些字段,**不影响现有风格**。机制见 [android-app.md](android-app.md);HA 页三档点击交互见 [ha-page-interaction-spec.md](ha-page-interaction-spec.md)。

## 页面 → 数据段

| 页面 key | 标题 | 用的数据段 | 依赖的数据源(没配则页面隐藏) |
|---|---|---|---|
| `home` | 首页 | `home` + 顶层 | 天气、提醒事项 |
| `ai` | AI 用量 | `ai` | AI 用量(ccusage) |
| `device` | 设备 | `device` | 设备监控 |
| `ha` | 智能家居 | `ha` | Home Assistant + 选了实体 |
| `printer` | 打印机 | `printer` | Home Assistant |
| `news` | 资讯 | `news` | RSS 订阅源(默认预置 AIHOT,无需密钥) |
| `download` | 下载 | `download` | qBittorrent / Transmission(可多台,合并显示) |
| `music` | 音乐 | `music` | Mac 上的 Music agent 推送(Apple Music / Music.app) |

## 顶层字段(所有页可用)

| 字段 | 类型 | 例 | 说明 |
|---|---|---|---|
| `lang` | str | `zh` / `en` | 界面/看板语言。模板用 `{% if lang == 'zh' %}…{% endif %}` 隐藏中国元素(英文版) |
| `now` | str | `05/27 14:30` | 日期+时间 |
| `time_hm` | str | `14:30` | 时:分 |
| `clock` | str | `14:30:05` | 时:分:秒 |
| `battery.level` | int\|`--` | `87` | 电量。Kindle 出图=Kindle 经 `/api/kindle-status` 上报;安卓 App `/app` 出图=手机经 `?kbatt=` 传来 |
| `battery.charging` | bool | | 是否充电 |
| `battery.has` | bool | | 有无电池数据;false 时模板**必须**不渲染电池块(`{% if battery.has %}…`)。**`/app/page` 与 `/app-legacy/page` 永远不是 Kindle 在请求,无 `kbatt` 即 has=False、不显示**,绝不退回显示 Kindle 电量(误导)。普通浏览器开 `/app` 同理不显示 |
| `page_no` | int | `3` | 当前页在「实际启用页顺序」中的序号(从 1)。渲染入口按 `active_pages` 注入,**反映用户在设置页手动排的页序** |
| `page_total` | int | `7` | 启用页总数。页脚用 `{{ page_no }} / {{ page_total }}` 显示「当前/总数」,加页/调序自动跟着变(**别再写死 `1/5`**) |

> **i18n(中英双语)**:全局开关 `config.server.language`(zh|en,默认 zh)。
> - **数据值已按语言产出**(模板直接显示,勿再翻):`home.weekday`(周X/Mon-Sun)、`printer.state_text`/`speed`/`remaining_text`、`ai.*_reset` 倒计时、提醒 `.dt` 标签、设备分区名 `总容量`/`Total`。
> - **中国元素在英文版置空**:`home.lunar`/`ganzhi`/`term` = `""`,日历每格 `l`=`""` 且 `holiday`=False(公历数字保留)。
> - **静态 UI 文案**:每套风格自带 `styles/<风格>/strings.json`(`{"zh":{...},"en":{...}}`),`render_page` 按 `lang` 注入为模板变量 `t`,模板写 `{{ t.键 }}`(英文缺键回退中文)。zh 值与原模板逐字一致 → 默认中文像素级不变。

## `home` —— 首页

| 字段 | 类型 | 例 | 说明 |
|---|---|---|---|
| `date_md` / `date_dot` | str | `05/27` / `05.27` | 两种日期写法 |
| `weekday` | str | `周三` | |
| `lunar` | str | `四月初一` | 农历 |
| `ganzhi` | str | `丙午马年` | 干支生肖 |
| `term` | str | `今日芒种` / `夏至还有3天` / `` | 节气,可能为空 |
| `year` / `month` | int | | |
| `weather.city` | str | `北京` | 城市名(GeoAPI 反查 location);未配置/查不到则空 |
| `weather.temp` | str | `24` | 当前温度 |
| `weather.cond` | str | `多云` | 天气 |
| `weather.feels` | str | `26` | 体感 |
| `weather.humidity` | str | `65` | 湿度 |
| `weather.wind` | str | `西北风3级` | |
| `weather.today_range` | str | `18–26°` | 今日温区 |
| `weather.tmr_range` | str | `19–27°` | 明日温区 |
| `weather.tmr_cond` | str | `晴` | 明日天气 |
| `calendar` | list | | 月历:周行数组,每格 `None`(空)或 `{d, l, today, holiday, weekend}` |
| `reminders.overdue` | list | `[{title, dt}]` | 逾期;dt 如 `05.20` |
| `reminders.today` | list | `[{title, dt}]` | 今日 |
| `reminders.upcoming` | list | `[{title, dt}]` | 将到期;dt 如 `明天`/`+3天`/`05.30` |
| `reminders.total` | int | | 未完成总数 |

**日历格子** `{d:日, l:副文本(节假日/节气/农历), today:bool, holiday:bool, weekend:bool}`

## `ai` —— AI 用量

| 字段 | 类型 | 例 | 说明 |
|---|---|---|---|
| `five_pct` / `five_reset` | int / str | `42` / `2小时后` | Claude 5h 额度已用% / 重置倒计时 |
| `week_pct` / `week_reset` | int / str | | Claude 周额度 |
| `cx_five_pct` / `cx_five_reset` | int / str | | Codex 5h 额度 |
| `cx_week_pct` / `cx_week_reset` | int / str | | Codex 周额度 |
| `today_cost` | str | `$12.30` | 今日总花费 |
| `cc_cost` / `cc_tok` | str | `$8.10` / `1.2M` | Claude 今日花费 / token |
| `cx_cost` / `cx_tok` | str | `$4.20` / `0.6M` | Codex 今日花费 / token |
| `tok_7d` / `tok_30d` / `tok_all` | str | `8M` / `30M` / `120M` | token 累计 |
| `chart` | list | `[{day:"27", cc_h:60, cx_h:30, val:"1.2M"}]` | 近 7 天柱状图;`cc_h`/`cx_h` 是 0-100 的高度% |
| `custom_total` | str | `¥12.34` | 今日官方价 × 倍率(`ai_usage.claude_rate`/`codex_rate` 各一档)。两档都=1.0 时为空(不显示) |
| `custom_name` | str | | 供应商名,当前恒空 → 模板回落显示「自定义」 |
| `show_cc_quota` / `show_cx_quota` | bool | `True` | 是否显示 Claude / Codex 额度块。由配置 `ai_usage.quota_show`(both/claude/codex/none)推导 |
| `show_quota_panel` | bool | `True` | 整列额度面板是否显示(=两者之一为真)。**`none` 时为 `False`**——模板须收成「趋势图为主+花费带」,详见 [style-authoring](style-authoring.md) |

## `device` —— 设备监控

`device.machines` 是**动态机器列表**(0~N 台,Windows/Linux/Mac 均可),**遍历渲染**。无机器时为空,该页隐藏。
> 新风格按"可遍历的机器列表"设计,自适应 1 台 / 多台,**别写死台数或机器名**。每台按 `show` 决定显示哪些指标条。

单台机器对象字段:

| 字段 | 类型 | 说明 |
|---|---|---|
| `name` | str | 显示名(可自定义;push 设备默认 hostname) |
| `cpu` | int | CPU 使用率 % |
| `mem` | int | 内存使用率 % |
| `mem_used` / `mem_total` | str | 内存 |
| `net_rx` / `net_tx` | str | 网络收发速率 |
| `disk_r` / `disk_w` | str | 磁盘读写速率 |
| `vols` | list | `[{name, pct, used, total}]` 各分区(已按勾选过滤) |
| `show` | dict | `{cpu, mem, net, disk_io}` 各指标条是否显示(用户勾选;留空配置=全 True) |

遍历范式:`{% for m in device.machines %} ... {% if m.show.cpu %}CPU {{ m.cpu }}%{% endif %} ... {% endfor %}`

## `ha` —— 智能家居(实体卡片墙)

`ha.cards` 是一个列表;空列表时该页隐藏(配置即页面)。每张卡片字段已冻结:

| 字段 | 类型 | 说明 |
|---|---|---|
| `name` | str | 显示名(用户覆盖 or HA 友好名) |
| `kind` | str | `toggle`/`lock`/`cover`/`binary`/`sensor`/`climate`/`media`/`presence`/`text`/`select`/`number`/`button`/`scene`/`alarm` |
| `icon` | str | MDI 图标名(`mdi:xxx`);空串=不显图标 |
| `on` | bool | 激活态强调(开/有人/已锁/播放中…);sensor/select/number/button/scene/alarm 恒 `false` |
| `state_text` | str | 主显文本(除 sensor 外各 kind) |
| `value` | str | 主显数值(sensor;非 sensor 为空) |
| `unit` | str | 数值单位(sensor;如 `°C` / `%` / `W`) |
| `sub` | str | 次要行(climate 目标温度、media 标题…),可空 |
| `entity_id` | str | HA 实体 id。**仅安卓 App 交互用**(点卡→`/api/action/ha`);Kindle 模板无视 |
| `meta` | dict | **仅安卓 App 控制面板用**(B 类可控卡才有);Kindle 模板无视,不影响出图。结构见下 |

> 主显规则:`value` 非空 → `value` 大字 + `unit` 小字;否则 `state_text` 大字。`sub` 非空再加一行小字。
> 遍历范式:`{% for c in ha.cards %} ... {% if c.value %}{{ c.value }}{{ c.unit }}{% else %}{{ c.state_text }}{% endif %} ... {% endfor %}`
> on/off 在墨水屏上靠「描边 vs 加重描边 + 实心点」区分,不靠颜色。

### `kind` 三档交互(安卓 App / 网页版,定稿见 [ha-page-interaction-spec.md](ha-page-interaction-spec.md))

| 档 | kind | 单击交互 | `meta` |
|---|---|---|---|
| A 直发 | `toggle`/`lock`/`scene`/`button` | 单击即下发动作(乐观更新) | 无 |
| B 弹面板 | `cover`/`climate`/`media`/`select`/`number`/`alarm` | 单击弹底部控制面板 | 见下 |
| C 只读 | `sensor`/`binary`/`presence`/`text` | 单击弹只读详情 | 无 |

> B/C 卡 android 出口右上角加 `›` 角标(A 类不加);Kindle 出图三档都不渲染角标/控件。

`meta`(B 类卡,App-only)结构:

| kind | `meta` |
|---|---|
| `cover` | `{on, position}`(position 可为 `null`) |
| `climate` | `{on, mode, modes[], current, target}`(modes=合法 HVAC 模式;temp 为数值/`null`) |
| `media` | `{on, title}` |
| `select` | `{options[], current}` |
| `number` | `{min, max, step, unit, value}` |
| `alarm` | `{state}`(`armed_home`/`armed_away`/`disarmed`…) |

> `meta` 是安卓 App 出口追加的字段名(非 dict 方法名,Jinja 安全)。Kindle 出图链路不读它,逐字节不变。

## `printer` —— 打印机

整体为 `None` 时该页降级/隐藏。否则:

| 字段 | 类型 | 说明 |
|---|---|---|
| `online` / `printing` | bool | 在线 / 正在打印 |
| `paused` | bool | 是否暂停中。**已弃用(2026-06-23):打印机控制移除**(HA 拓竹云模式控不了);字段仍产出但无消费方,Kindle 一直无视 |
| `state_text` | str | `打印中`/`空闲`/`离线`... |
| `progress` | int | 0-100 |
| `task` | str | 文件名 |
| `layer` / `total_layer` | str | 当前层 / 总层 |
| `remaining_text` | str | `2小时15分` |
| `eta_clock` | str | 预计完成时刻 `16:45` |
| `nozzle` / `nozzle_t` | str | 喷嘴温度 / 目标 |
| `bed` / `bed_t` | str | 热床温度 / 目标 |
| `speed` | str | 速度档位 |
| `weight` / `material` | str | 耗材重量 / 类型 |
| `cooling_fan` | str | 风扇转速 |
| `name` | str | 打印机名 |

> 当前贴合单台 3D 打印机(拓竹)。P2 会抽象成「任意 HA 实体卡片」以降低品牌绑定,届时契约扩展、本表更新。

## `news` —— 资讯(RSS,默认订 AIHOT)

`news.entries` 是从轮转起始位起取的**一批候选条目**(默认 12,wrapping,顺序排好);页面用共享自适应引擎按容器高度**取前缀**显示(短讯多并、长文缩字铺满)。空列表时该页隐藏。

| 字段 | 类型 | 说明 |
|---|---|---|
| `entries` | list | 候选批(默认 12 条);模板**遍历**渲染、引擎按高度取前缀。**字段名是 `entries` 不是 `items`**(Jinja `news.items` 会撞 `dict.items()` 方法) |
| `index` | int | 本批起始条在全部条目中的序号(从 1 起,显示「第 x 起」) |
| `total` | int | 全部条目数(显示「/N」) |
| `title` | str | 页面主标题(默认「AI 热点」/「Headlines」,可被 config `news.title` 覆盖) |

`entries[*]` 单条字段(冻结):

| 字段 | 类型 | 说明 |
|---|---|---|
| `title` | str | 标题 |
| `summary` | str | 正文整段(feed 的 `description`,已去 HTML;可长达 ~400 字,模板须能容纳) |
| `source` | str | 来源名(author 括号内 / feed 名) |
| `category` | str | 话题(feed 带 `<category>` 才有;AIHOT 无 → 空串,**非空才显示话题 chip,别编造**) |
| `when` | str | 相对时间 `2小时前`/`2h ago`/`MM.DD`(已按 lang 本地化) |
| `link` | str | 原文链接(墨水屏不可点,默认不显示) |

> 资讯正文/标题是**外部数据**,什么语言显示什么(中文 feed 仍中文);只有 chrome(页标题/来源/序号/相对时间)走 lang。
> 轮播在 `build_context` 做(无状态时间分桶选起始位,`server/sources/rss.pick_index`);模板不管轮播,遍历整批 `entries`。
> **遍历范式(自适应填充)**:容器 `<div class="news-fit" data-news-fit>`,每条 `<div class="nitem" data-news-item>`,正文 `font-size:var(--news-fs)`,`</body>` 前 `{% include 'shared/news_fit.html' %}`。引擎按高度自动决定显示几条/多大字。详见 `docs/news-redesign-spec.md` §6b、样板 `styles/style_a/news.html`(**用 `news.entries` 不要写 `news.items`**)。

## `download` —— 下载看板(qBittorrent + Transmission 合并)

`download.torrents` 是合并+活跃优先+截断后的种子列表;空且 `total==0` 时该页隐藏。顶层全局字段已格式化好,直接显示。

| 字段 | 类型 | 例 | 说明 |
|---|---|---|---|
| `ok` | bool | | 是否有下载器连上 |
| `dl_speed` / `up_speed` | str | `5.2 MB/s` / `0` | 已格式化的总下载/上传速度(全部种子汇总) |
| `active` / `total` | int | `3` / `18` | 活动数 / 总种子数 |
| `ratio` | str | `0.13` | 聚合全局分享率(跨所有下载器,累计上传/累计下载) |
| `uploaded` / `downloaded` | str | `119.7G` / `880.2G` | 累计(已格式化);未知为 `--` |
| `free` | str | `1.2T` | 剩余空间;**空串=未知,空就别显示**(qB 实测可能返回 -1) |
| `errors` | list | `["群晖 qB"]` | 连不上的下载器名;**非空=部分离线,角落提示「N 个下载器离线」**(诚实降级) |
| `torrents` | list | | 单条种子,字段见下(已排序+截断到 `downloaders.rows`) |

`torrents[*]` 单条字段(冻结):

| 字段 | 类型 | 说明 |
|---|---|---|
| `name` | str | 种子名(可能很长,模板须截断) |
| `progress` | int | 0~100 |
| `dl` / `up` | str | 速度,已格式化 `29 MB/s` / `0` |
| `ratio` | str | 分享率 `0.43` |
| `size` | str | `12.3G` |
| `eta` | str | `12分` / `1时5分` / `—`(已本地化;异常值统一 `—`) |
| `state` | str | 统一枚举 `downloading`/`seeding`/`paused`/`checking`/`queued`/`stalled`/`error`/`other`——**模板用它选图标/分支** |
| `state_text` | str | 已本地化状态文字(下载中/做种/暂停…)——**模板直接显示** |
| `id` | str/int | 种子 id(qB=hash / Transmission=数字)。**仅安卓 App 控制用**(`/api/action/torrent`);Kindle 无视 |
| `client` | str | 所属下载器名。**仅安卓 App 控制用**(按它路由到对应 adapter);Kindle 无视 |

> 进度条是墨水屏主场:实心/斜纹填充表示进度,**不靠颜色**。下载中显进度+eta,做种显分享率+上传。
> 种子名是**外部数据**按原文显示(不翻译);只有 chrome(标题/标签/单位/空态)走 lang。
> 遍历范式:`{% for tr in download.torrents %}`(**字段名 `torrents` 不撞 dict 方法,放心用**)。机制/鉴权见 `docs/download-page-spec.md`。

## `music` —— 音乐播放(Apple Music / Music.app,Mac agent 推送)

`has_track==False` → 空状态「当前无播放」:模板显占位框、**不显假进度条**(对标打印机页「无任务」)。**渲染目标分层**:静态目标(`target=kindle`/`legacy`、`/web-simple`)**不显** progress/position/递增时间,只显「当前是哪首歌」;动态目标(`target=android`)前端据 `position`+`duration`+`sampled_at` 自走进度条。`*_text` 字段全由 `build_context` 按 lang 产出,**模板别写死中文**。

| 字段 | 类型 | 例 | 说明 |
|---|---|---|---|
| `available` | bool | | 模块已启用且 agent 有效 |
| `has_track` | bool | | 有无当前曲目;false=空状态 |
| `state` / `state_text` | str | `playing` / `播放中` | 枚举 playing/paused/stopped;`_text` 已本地化 |
| `name` / `artist` / `album` | str | | 歌名 / 艺人 / 专辑(后两者可空) |
| `duration` / `duration_text` | int / str | `314` / `5:14` | 总时长(秒 / 已格式化);动态目标用秒 |
| `position` / `position_text` | int / str | `103` / `1:43` | 当前进度(秒 / 已格式化);动态目标用秒 |
| `progress_pct` / `sampled_at` | int / int | `33` / epoch 秒 | 进度% / 采样时刻(动态目标据此推实时进度) |
| `shuffle` / `shuffle_text` | bool / str | | 随机;`_text` 已本地化(随机开/关) |
| `repeat` / `repeat_text` | str / str | `all` / `列表循环` | off/all/one;`_text` 已本地化 |
| `artwork_url` | str | | 封面 URL;空=显占位框 |

> 完整字段(含 album_artist/composer/genre/year/track_number/loved/play_count 等可选项,及 state_since/paused_for/artwork_wall* 等屏保态字段)见 `server/render/contract.py` 的 `empty_music()`(逐字段注释,为权威定义)。字段名不用 dict 方法名。
