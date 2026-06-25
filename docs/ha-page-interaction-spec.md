# 任务书:HA 页点击交互落地(看板 App / 网页版)

> **交付对象**:接手的开发者/AI。本文自包含——读完它 + 文中点到的几个文件就能独立完成,不需要别的上下文。
> **定稿日期**:2026-06-23(交互模型由项目主人浩轩拍板,见 §2)。
> **一句话**:看板「智能家居页」现在只会"单击切换",且一半实体类型还当只读卡。要按定稿的**混合交互模型**,让 App/网页版能正确控制所有类型的 HA 实体——**纯前端交互 + 卡片分类,后端控制接口已全部就绪**。

> ## ✅ 落地状态(2026-06-23 完成)
> 本任务书已实现并验收通过。改动:
> - **`server/sources/homeassistant.py`**:`_build_card` 新增 `select`/`number`/`button`/`scene`/`alarm` 五种 kind(含 `input_*` 变体),并给 `cover`/`climate`/`media`/`select`/`number`/`alarm` 追加 App 专用 `meta` 字典(面板控件数据)。Kindle-read 字段(on/value/unit/sub/state_text)保持与旧 text 兜底逐字节一致。
> - **`server/render/contract.py` + `docs/data-contract.md`**:`empty_ha` 卡片契约追加 kind 枚举 + `meta` 字段说明(三档交互表)。
> - **7 套 `styles/*/ha.html`**:android 分支由「ACTIONABLE 二档」改为 `DIRECT`(A 类 `data-action` 直发)/`PANEL`(B 类 `data-panel`+`data-meta` JSON)/兜底(C 类 `data-detail`)三档;blueprint 的 ON/OFF 角标排除新只读 kind(防 Kindle 回归)。
> - **`server/render/styles.py`**:`ANDROID_THEME` 加 `[data-panel],[data-detail]::after` 的 `›` 角标(纯 CSS、仅 android,不入 HTML/不入 Kindle)。
> - **`web/app.html`**:新增 `#panel` 底部 sheet,按 kind 渲染控件(照搬测试台)→ POST `/api/action/ha`,空调步进/数值滑块/选项即时高亮/撤防二次确认;A 类 `runAction` 沿用乐观更新。
> - **`server/app.py`**:`APP_PAGE_TEXTS` 加面板静态文案(中央注入、中英双语)。
> - **验收**:`tests/test_homeassistant.py` 加新 kind 分类 + meta + **Kindle 逐字节不变** + android 三档路由测试;`pytest tests/` 全绿(255);`work/android_preview.py` 七套风格出图、Kindle 零泄漏;26 个面板动作经 `_resolve_action` 全部解析为白名单 service。

---

## 0. 先懂架构(命根子,不懂会改错)

**一套 HTML 模板源,靠 `target` 参数分两种出口;三个设备,Kindle 走静态、APK 和网页版走同一个活出口。**

```
              styles/<风格>/*.html   ← 唯一一套模板(绝不分叉)
                       │
        ┌──────────────┴───────────────┐
 target='kindle'                   target='android'
 渲染→Chromium截图→灰度PNG            活的彩色可点 HTML(= GET /app 那套)
        │                                 │
        ▼                        ┌────────┴────────┐
  ① Kindle(静态画布·不可触)     ② APK            ③ 纯网页版(以后)
    不渲染 android 分支            系统WebView壳      浏览器直接开 /app
                                  装 /app?token=    ← 跟 APK 同一份 HTML
```

- **你做的交互只在 `target=='android'` 分支 + `web/app.html` 外壳里**。APK 和未来网页版用的是同一个 `/app` 活页,所以**交互写一遍两端通用**。
- **Kindle(target=kindle)是静态 PNG,没有触屏**,`{% if target=='android' %}` 的控件/上色它根本不渲染。
- 🔴 **回归红线**:改 `target=='android'` 分支后,`target=='kindle'` 出的 PNG **必须逐字节不变**。改完用 `python3 work/android_preview.py <风格...>` 出彩色图验交互 + 验 Kindle 零泄漏(详见 `CLAUDE.md` 安卓 App 段)。

---

## 1. 现状:已有什么(别重复造)

### 后端控制接口——**已全 kind 就绪,不用动**
`server/actions.py`:
- `ha_action(cfg, entity_id, action, value=None)` → `_resolve_action` **白名单分发器**,已支持全部类型(service 硬编码、value 按类型校验、防注入):
  - toggle:`on`/`off`/`toggle`;lock:`on`(锁)/`off`(解锁);cover:`on`/`off`/`toggle`/`stop`
  - climate:`on`/`off`/`set_temp`(value=数值)/`set_mode`(value=HVAC 模式枚举)
  - media:`toggle`/`play`/`pause`/`stop`/`next`/`prev`/`vol_up`/`vol_down`/`mute`/`unmute`
  - select:`select_option`(value=选项);number:`set_value`(value=数值);text:`set_value`(value=文本)
  - button:`press`;scene:`activate`;alarm:`arm_home`/`arm_away`/`arm_night`/`disarm`(value=可选 code)
- 路由 `POST /api/action/ha`,body `{entity_id, action, value?}`,经令牌(`_AUTH_EXEMPT_*` 之外)。
- `controllable_inventory(cfg)`:已把全 HA 按 kind 分组 + 附带控件元数据(options/min/max/step/hvac_modes/target_temp/position/...)。**这就是分类逻辑的参考实现**,§4 的 `_build_card` 扩展应与它同口径(建议抽公共函数,别写两份分类)。
- `web/action-test.html`(动作测试台)里每个 kind 的控件 HTML 是**已真机验证过的样子**,面板控件可直接照搬。

### 前端现状——**这才是要改的**
- `server/sources/homeassistant.py::_build_card`(约 line 70-152):把配置的实体 → 卡片 dict,赋 `kind`。**现有 kind**:`toggle`/`lock`/`cover`/`binary`/`sensor`/`climate`/`media`/`presence`/`text`。
  - ❌ **缺口**:select、number、button、scene、alarm 现在都落到兜底的 `text`(只读),HA 页里点不了。
- `styles/<风格>/ha.html` 的 `{% if target=='android' %}` 分支(以 `style_a/ha.html` 为准,约 line 78-97):
  - `ACTIONABLE = ['toggle','lock','cover','climate','media']` → 卡片带 `data-action="ha" data-entity=.. data-cmd=..`(单击发动作,cmd 默认 toggle,lock 按当前态发 on/off)。
  - 非 ACTIONABLE → 带 `data-detail*`(单击弹只读详情)。
- `web/app.html` 外壳已有现成钩子:
  - 点击分发(约 line 145-148):`[data-action]`→`runAction()`、`[data-detail]`→`showDetail()`。
  - `runAction(el)`(line 150-167):读 `data-action`/`data-cmd`/`data-entity` → POST `/api/action/*` → 失败 toast。
  - `#detail` 弹层(line 25-41、174-188):居中遮罩 + 标题 + 行 + 关闭。**控制面板可基于这套扩**(把只读 detail 升级成"按 kind 渲染控件的控制 sheet")。

---

## 2. 交互模型(定稿,按"这实体有几个动作"分三档)

### A. 单击卡片 = 直接动(无面板)
| kind | 单击 = | 下发 `/api/action/ha` |
|---|---|---|
| toggle(灯/开关/风扇/script/automation/siren/humidifier) | 切换当前态 | `{action:"toggle"}` |
| lock | 锁 ↔ 解锁(按当前态取反) | `{action: on?"off":"on"}` |
| scene | 激活 | `{action:"activate"}` |
| button | 按一下 | `{action:"press"}` |

- **乐观更新**:点完立即切 UI 态(灯立即显示关),异步确认;失败回滚 + toast。
- scene/button 是一次性动作,点完给短暂"已执行"反馈,不改持久态。

### B. 单击卡片 = 弹底部控制面板
| kind | 面板控件(照搬 `web/action-test.html` 同 kind 控件) |
|---|---|
| cover | 打开 / 关闭 / 停止 (+ 位置 %) |
| climate | 开 / 关 + 温度 −/+ + 模式按钮(按实体 `hvac_modes`) + 当前·目标温度 |
| media | 播放·暂停 / 上一首 / 下一首 / 音量 −/+ / 静音 (+ 标题) |
| select | 选项列表(单选,点即 `select_option`) |
| number | 滑块/步进(`min`/`max`/`step`)+ 当前值,确认 `set_value` |
| alarm | 在家/离家/夜间 布防 + 撤防(可填 code);**撤防二次确认** |

### C. 单击卡片 = 只读详情(无控制,沿用现有 `#detail`)
- sensor/weather → 数值+单位;binary_sensor → 状态文案;person/device_tracker → 在家/外出。

### 视觉
- **B / C 类卡片右上角加 `›`(或 `⋯`)角标**,提示"点了弹面板",和 A 类"单击即动"区分;A 类不加。
- 面板形态:**底部滑出 sheet**(移动端友好;网页/平板居中弹窗也可)。内容 = 实体名 + 当前态 + 控件 + 关闭;点遮罩/关闭即退。
- 危险动作(alarm 撤防)面板内二次确认(同 printer stop 的 `confirm()`)。

---

## 3. 要做的清单

1. **`_build_card` 扩 kind 分类**(server/sources/homeassistant.py):新增 select/input_select→`select`、number/input_number→`number`、button/input_button→`button`、scene→`scene`、alarm_control_panel→`alarm`。补面板所需元数据字段。**与 `actions.controllable_inventory` 同口径**(抽公共分类函数最好)。
2. **数据契约**(`server/render/contract.py` 的 `empty_ha` 卡片结构 + `docs/data-contract.md`):卡片**只追加**字段——`options`(select)、`min`/`max`/`step`/`unit`(number)、`hvac_modes`/`target_temp`/`current_temp`(climate)、`position`(cover)、`title`(media)。🔴 别用 dict 方法名当字段名(`items`/`keys`/`get`…会被 Jinja 当方法,沿用 `entries`/`torrents` 前例)。
3. **`ha.html`(7 套风格的 android 分支)**:
   - A 类卡(toggle/lock/scene/button)→ 维持/改成 `data-action` 直发(scene/button 用对应 cmd)。
   - B 类卡(cover/climate/media/select/number/alarm)→ 改成 `data-panel="<kind>"` + 把控件需要的实体数据塞进 data-* 属性(或塞一个 JSON)。
   - B/C 类卡加 `›` 角标。更新 `ACTIONABLE`/`TAG_KINDS` 等模板常量。
4. **`web/app.html` 外壳**:把 `#detail` 扩成通用控制 sheet,或新增 `#panel`。按 `data-panel` 的 kind 渲染对应控件(照搬测试台控件),控件 onclick → POST `/api/action/ha` `{entity_id, action, value?}`;成功后局部刷新该卡/面板状态。A 类 `runAction` 加乐观更新 + 失败回滚。
5. **i18n**:面板里的静态文案(开/关/暂停/布防…)走中央注入(`styles.py` 的 `ANDROID_STRINGS`,只在 target=android),别在模板写死中文(沿用现有 `a_pause/a_resume` 等做法)。

---

## 4. 验收

- **离线渲染**(绝不起服务):`python3 work/android_preview.py <风格...>` 出彩色图,确认 B 类卡有 `›` 角标、点击能弹面板(可在预览里注入交互或人工核 HTML)、A 类直发。
- 🔴 **Kindle 零泄漏**:同一脚本验 `target=kindle` 出图与改动前**逐字节相同**(android 分支不能漏进灰度版)。
- 真机/浏览器开 `/app?token=`:A 类单击秒变(乐观更新);B 类弹面板、控件生效、点前点后状态对;撤防二次确认。7 套风格都要扫一眼。
- 测试:`python3 -m pytest tests/ -q` 全绿;给 `_build_card` 新 kind 分类补单测(参考 `tests/test_*`,断言 select/number/alarm 实体被分对 kind + 带对元数据)。

## 5. 安全 / 红线
- `/api/action/ha` 经令牌、绝不豁免;**只走白名单 action**(已在 `actions._resolve_action` 实现),前端别绕过传任意 service。
- alarm 撤防、cover stop 等"重"动作放面板 + 二次确认,不做 A 类单击(防手滑)。
- 真机 HA 地址/令牌/内网信息不进公开仓库。
- 改完 7 套 `ha.html` 后**必须**跑离线渲染验 Kindle 逐字节不变——这是看板"一套 HTML 不分叉"的命根子。

## 6. 相关
- 后端控制接口/inventory 实现:`server/actions.py`;动作测试台(控件样板):`web/action-test.html`。
- 架构/红线背景:仓库根 `CLAUDE.md`「安卓 App 版」段 + 「动作接口」段。
- 数据契约:`docs/data-contract.md`、`server/render/contract.py`。
