# 风格开发任务书(交给风格作者 / AI)

> 你的任务:为 Kindle Dashboard 设计**新的风格皮肤**。每套风格 = 同一批数据的不同外观。
> 在本仓库根目录工作。**动手前必读 [`docs/data-contract.md`](data-contract.md)**(数据契约)。

## 背景(30 秒)

一台越狱 Kindle 558 横放当信息看板。服务端用 Jinja2 渲染 HTML → headless Chromium 截图成
**横屏 800×600** → 后端旋转成竖屏写墨水屏(**旋转你不用管**)。
所有风格共享同一套**数据契约**(字段名/类型已冻结),你只做外观,不碰数据。

## 交付物

每套风格一个目录:`styles/<风格名>/`,内含 6 个文件:
```
home.html  ai.html  device.html  ha.html  printer.html  style.css
```
风格名用小写+下划线(如 `newspaper`、`terminal`、`minimal`)。

## 硬性渲染约束(违反会错乱,必须遵守)

1. **画布固定 800×600 横屏**:`html,body{width:800px;height:600px;}`,不滚动、不溢出。
2. **纯灰度墨水屏**:只能用 `#000`~`#fff` 黑白灰,**禁止任何彩色**、禁止渐变滤镜。层级靠网点/斜线/纯色块。
3. **防溢出**:body 用 `display:flex;flex-direction:column`;主体 `flex:1;min-height:0;overflow:hidden`;
   页脚 `flex-shrink:0;margin-top:auto`。**不要用 `position:absolute`**(历史踩过溢出坑)。
4. **字体**:中文用 `'Noto Sans CJK SC','PingFang SC','Microsoft YaHei',sans-serif`(跨平台 fallback);
   数字/代码感可用 `monospace`。**无中文衬线字体**,报纸/杂志的"衬线感"靠排版而非 serif。
5. 数字一律加 `font-variant-numeric:tabular-nums`(等宽数字,防跳动)。
6. 每个 html 第一行必须是:
   `<!DOCTYPE html><html lang="zh"><head><meta charset="UTF-8"><style>` 紧跟 `{{ css|safe }}`,
   再写本页专属 CSS,然后 `</style></head><body>`。公共样式放 `style.css`,页面差异写各 html 的 `<style>`。
7. **静态截图**:禁止动画、JS、外部资源、网络字体。SVG(进度环等)可用。

## 数据契约(完整字段见 docs/data-contract.md,这里给关键点)

每页可直接用顶层字段:`now`、`time_hm`、`clock`、`battery.{level,charging,has}`。
缺数据时所有字段都有降级占位(数字→0,文本→`--`,列表→`[]`),**模板永远拿不到 undefined**。

页面对应数据段:
- **home**:`home.weather.*`(温度/天气/体感/湿度/风/今明温区)、`home.calendar`(月历周列表)、`home.reminders.{overdue,today,upcoming,total}`、农历干支节气
- **ai**:Claude/Codex 的 `five_pct`/`week_pct` 配额、今日花费、`chart`(近7天柱状图)、token 统计。**额度面板必做自适应**:用 `{% if ai.show_cc_quota %}`/`{% if ai.show_cx_quota %}` 包各自额度块(只显示一家时隐藏另一块);再用 `{% if ai.show_quota_panel %}原双栏{% else %}趋势图为主+底部 token/花费带{% endif %}` 包整个 `.main`——`none`(中转站用户无官方额度)时整列额度消失、页面收成图表主角。7 套已实现可参考,**别让额度块"硬隐藏"留空洞**。
- **printer**:打印状态/进度/层数/剩余时间/喷嘴热床温度等;整体可能为 None,需 `{% if printer %}` 保护
- **device**:见下方(结构和老看板不同,重点看)
- **ha**(智能家居实体墙,新增):`ha.cards` 数组,自适应瓦片;字段与做法见 `docs/data-contract.md` 的 `ha` 段;**本页有独立施工图 `docs/ha-page-styles-spec.md`(连样例数据脚本),做 ha 页以它为准**。`style_a/ha.html` 是已上线基准。

### ⚠️ device 页是动态机器列表(和老版不同!)

`device.machines` 是一个**数组**,0 到 N 台机器(Windows/Linux/Mac 都可能),要**遍历**渲染,自适应任意台数:

```jinja
{% if device.machines %}
  {% for m in device.machines %}
    <!-- m.name 显示名;m.show 控制哪些指标条显示;m.vols 已按勾选过滤 -->
    <h3>{{ m.name }}</h3>
    {% if m.show.cpu %}CPU {{ m.cpu }}%{% endif %}
    {% if m.show.mem %}内存 {{ m.mem }}% {{ m.mem_used }}/{{ m.mem_total }}{% endif %}
    {% if m.show.net %}网络 ↓{{ m.net_rx }} ↑{{ m.net_tx }}{% endif %}
    {% if m.show.disk_io %}磁盘 读{{ m.disk_r }} 写{{ m.disk_w }}{% endif %}
    {% for v in m.vols %}{{ v.name }} {{ v.used }}/{{ v.total }} {{ v.pct }}%{% endfor %}
  {% endfor %}
{% else %}
  <div>暂无设备数据</div>
{% endif %}
```

单台字段:`m.name`、`m.cpu`(int%)、`m.mem`(int%)、`m.mem_used`/`m.mem_total`、`m.net_rx`/`m.net_tx`、`m.disk_r`/`m.disk_w`、`m.vols[]`(`{name,pct,used,total}`)、`m.show.{cpu,mem,net,disk_io}`(bool,用户勾选)。
**布局要能优雅处理 1 台、2 台、4 台**(用 flex-wrap 网格,别写死两栏)。

## 页脚统一(5 页一致)

每页页脚固定:更新时间 · Kindle 电量 · 页标识。电量必须出现:
```jinja
{% if battery.charging %}充电 {% else %}电量 {% endif %}{{ battery.level }}%
```

## 横屏布局建议(800 宽,务必左右分栏,别照搬竖屏堆叠)

- 页眉横跨整宽,页脚横跨整宽,中间主体 2~3 栏
- home:天气 | 月历 | 提醒
- ai:左(配额条+今日花费)| 右(token 统计+7天柱状图)
- device:机器卡片网格(自适应台数)
- ha:自适应瓦片墙(`cols=ceil(sqrt(n))` 上限 4),开/关靠实心 vs 描边区分(见专项施工图)
- printer:左(进度环+任务+层数+剩余)| 右(温度+详情)

## 开发与预览

**预览工具**(不用起服务,一条命令渲染所有页到 PNG):
```bash
python3 scripts/preview_style.py <风格名>          # 真实 mock 数据,横屏正立
python3 scripts/preview_style.py <风格名> --empty   # 空数据,验证降级不报错
# 输出 /tmp/preview_<风格名>_<页>.png,打开看效果
```
迭代循环:改模板 → 跑预览 → 看 PNG → 再改。

## 验收标准

1. 6 个文件齐全,风格名目录正确。
2. `preview_style.py <风格名>` 和 `--empty` **都不报错**,5 页都输出 800×600。
3. 不溢出、不滚动、纯灰度、无彩色。
4. device 页能正确遍历 1~N 台机器、尊重 `m.show` 勾选。
5. 视觉方向**独立鲜明**,不要抄 style_a 的外观(参考其数据绑定和防溢出写法即可)。

## 参考

学任意已内置风格的数据绑定与防溢出写法,但做出你自己的视觉方向。

## 已内置风格(7 套,**别重复造,可当参考**)

均已验证(各覆盖 home/ai/device/ha/printer 全页,真实+空数据都过):

- **style_a** — 杂志 / editorial(基准参考)
- **terminal** — TUI 命令行,等宽 + 窗口边框 + ASCII 分隔
- **bento** — 便当格子,圆角柔灰卡片
- **blueprint** — 工程蓝图(灰度),方格底纹 + 双线图框 + 标注
- **minimal** — 瑞士极简,大留白 + 超大数字 + 发丝线
- **newspaper** — 报纸,粗报头 + 多栏细线 + 小字密排
- **gauge** — 模拟仪表盘,半圆指针表盘(圆形语言)

想新增风格 → 挑一个与上面都不同的方向(如 dot-matrix 点阵、almanac 老黄历、brutalist 粗野等),按本文约束做,跑 `python3 scripts/preview_style.py <名字>` 验证。
