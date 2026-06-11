# 数据契约(给风格作者看)

> **风格 = 同一批数据字段的不同皮肤。** 你做新风格时,模板里能用的变量就是本文列出的这些,名字/类型都已冻结。契约稳了,你随便换布局换 CSS,数据层一个字不用动。
>
> 权威定义在 `server/render/contract.py`(本文是它的人类可读摘要,改契约要两边同步)。
> 缺数据/未配置时所有字段都有降级占位(数字→`0`,文本→`--`,列表→`[]`),所以模板**永远不会拿到 undefined**,放心用。

## 页面 → 数据段

| 页面 key | 标题 | 用的数据段 | 依赖的数据源(没配则页面隐藏) |
|---|---|---|---|
| `home` | 首页 | `home` + 顶层 | 天气、提醒事项 |
| `ai` | AI 用量 | `ai` | AI 用量(ccusage) |
| `device` | 设备 | `device` | 设备监控 |
| `ha` | 智能家居 | `ha` | Home Assistant + 选了实体 |
| `printer` | 打印机 | `printer` | Home Assistant |

## 顶层字段(所有页可用)

| 字段 | 类型 | 例 | 说明 |
|---|---|---|---|
| `lang` | str | `zh` / `en` | 界面/看板语言。模板用 `{% if lang == 'zh' %}…{% endif %}` 隐藏中国元素(英文版) |
| `now` | str | `05/27 14:30` | 日期+时间 |
| `time_hm` | str | `14:30` | 时:分 |
| `clock` | str | `14:30:05` | 时:分:秒 |
| `battery.level` | int\|`--` | `87` | Kindle 电量 |
| `battery.charging` | bool | | 是否充电 |
| `battery.has` | bool | | 无电池数据时为 false,模板应据此决定渲不渲电池块 |

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
| `kind` | str | `toggle`/`lock`/`cover`/`binary`/`sensor`/`climate`/`media`/`presence`/`text` |
| `icon` | str | MDI 图标名(`mdi:xxx`);空串=不显图标 |
| `on` | bool | 激活态强调(开/有人/已锁/播放中…);sensor 恒 `false` |
| `state_text` | str | 主显文本(toggle/lock/cover/binary/climate/media/presence/text) |
| `value` | str | 主显数值(sensor;非 sensor 为空) |
| `unit` | str | 数值单位(sensor;如 `°C` / `%` / `W`) |
| `sub` | str | 次要行(climate 目标温度、media 标题…),可空 |

> 主显规则:`value` 非空 → `value` 大字 + `unit` 小字;否则 `state_text` 大字。`sub` 非空再加一行小字。
> 遍历范式:`{% for c in ha.cards %} ... {% if c.value %}{{ c.value }}{{ c.unit }}{% else %}{{ c.state_text }}{% endif %} ... {% endfor %}`
> on/off 在墨水屏上靠「描边 vs 加重描边 + 实心点」区分,不靠颜色。

## `printer` —— 打印机

整体为 `None` 时该页降级/隐藏。否则:

| 字段 | 类型 | 说明 |
|---|---|---|
| `online` / `printing` | bool | 在线 / 正在打印 |
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
