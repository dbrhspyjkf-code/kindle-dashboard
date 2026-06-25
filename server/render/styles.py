"""风格调度:扫描风格包、按配置选风格、Jinja2 渲染页面。

风格包 = styles/<name>/ 下的 <page>.html(home/ai/device/ha/printer)+ 可选 style.css。
页面文件名 == contract.PAGES 的 key,所有风格共享同一套数据契约(见 docs/data-contract.md)。

风格目录默认在仓库根 styles/;可用 KINDLE_STYLES_DIR 覆盖(测试/自定义路径用)。
"""
import os
import json
import random
from datetime import date

from jinja2 import Environment, FileSystemLoader, select_autoescape, TemplateNotFound

from server.render.contract import PAGES


def styles_dir() -> str:
    env = os.environ.get("KINDLE_STYLES_DIR")
    if env:
        return env
    # server/render/styles.py → 上三层是仓库根
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(root, "styles")


# 安卓 App 彩色主题:每套风格一个贴合其气质的强调色(墨水屏灰度版不变,仅 target=android 注入)。
ANDROID_ACCENTS = {
    "style_a":   "#b23a48",   # editorial 红
    "terminal":  "#2ecc71",   # 绿屏荧光绿
    "bento":     "#2f6fed",   # 便当蓝
    "blueprint": "#2f6fed",   # 蓝图蓝
    "minimal":   "#e8553d",   # 瑞士橙红
    "newspaper": "#a8332e",   # 报头朱红
    "gauge":     "#c0392b",   # 仪表红针
}
_DEFAULT_ACCENT = "#2f6fed"

# 安卓控件文案(中央定义,按 lang 合并进模板变量 t,仅 target=android)。
# 这样 7 套风格的 strings.json 一个不用动,i18n 仍走 t、英文缺回退中文。键名加 a_ 前缀避免撞现有文案。
ANDROID_STRINGS = {
    "zh": {"a_pause": "暂停", "a_resume": "恢复", "a_stop": "停止", "a_detail": "详情"},
    "en": {"a_pause": "Pause", "a_resume": "Resume", "a_stop": "Stop", "a_detail": "Details"},
}

# 注入到 target=android 每页 <style> 末尾的共享主题:tap 反馈 + 控制按钮 + 语义色 helper。
# 用 !important 让少量「可点感/语义色」压过各风格自有 CSS;版式不动,只上色 + 可交互。
ANDROID_THEME = """
/* ==== android 触控主题(仅活 HTML 注入;Kindle 灰度版永不含此段)==== */
:root{ --a-accent:__ACCENT__; --a-ok:#1f9d55; --a-bad:#d64545; --a-warn:#d98b1f; }
html,body{ -webkit-tap-highlight-color:rgba(0,0,0,.06); }
[data-action],[data-detail]{ cursor:pointer; }
[data-action]:active,[data-detail]:active{ filter:brightness(.93); }
[data-action].acting{ animation:a-pulse .8s ease-in-out infinite; }
@keyframes a-pulse{ 50%{ opacity:.5; } }
.act{ display:inline-flex; align-items:center; justify-content:center; gap:4px; border:0;
  border-radius:999px; padding:6px 14px; font-size:13px; font-weight:700; line-height:1;
  background:var(--a-accent); color:#fff !important; cursor:pointer; }
.act.ghost{ background:transparent; border:1.6px solid var(--a-accent); color:var(--a-accent) !important; }
.act.danger{ background:var(--a-bad); }
.act:active{ transform:scale(.94); }
.a-ok{ color:var(--a-ok) !important; } .a-bad{ color:var(--a-bad) !important; }
.a-warn{ color:var(--a-warn) !important; } .a-accent{ color:var(--a-accent) !important; }
.a-fill{ background:var(--a-accent) !important; }
.a-row{ display:flex; align-items:center; gap:8px; }
/* B/C 类卡右上角 › 角标:提示「单击弹面板/详情」(A 类直发无角标)。纯 ::after,不入 HTML、不入 Kindle。 */
[data-panel],[data-detail]{ position:relative; }
[data-panel]::after,[data-detail]::after{ content:'›'; position:absolute; top:3px; right:7px;
  font-size:15px; line-height:1; font-weight:800; color:var(--a-accent); opacity:.5; pointer-events:none; }
"""

# 安卓 4.x「图片相框」专用注入(target=legacy_photo):服务端渲成彩色 PNG 给老平板当相框。
# 借用 static(非 android)版式 → 不渲点不了的控件/歌词、封面墙走 data URI(file:// 出图能渲);
# 在此之上只做两件事:① 解除各风格为墨水屏写死的封面 grayscale → 还原彩色(pad 是彩色屏);
# ② 把纯白底 #fff 换成暖白 #ece8de(与图片相框外壳留白同色,营造纸感,普通 LCD 上不冷白)。
# 渲染由服务端 Chromium 执行(pad 只看图),故可放心用属性选择器等现代 CSS。**不碰 Kindle/android 路径。**
LEGACY_PHOTO_CSS = """
/* ==== 安卓4.x 图片相框(仅服务端出彩图;Kindle/手机版不含此段)==== */
html,body{ background:#ece8de !important; }
.cover,.cover-img,[class*="cover"] img,[class*="tile"] img,[class*="photo"] img,[class*="wall"] img{
  -webkit-filter:saturate(1.06) contrast(1.02) !important; filter:saturate(1.06) contrast(1.02) !important; }
"""


# 内部模板集(不是可选的 Kindle 风格皮肤):不进风格选择器 / /api/styles / smoke 测试 / pick_style。
# legacy = 安卓 4.x 古董 WebView 降级活页专用(float-CSS+ES5),只由 /app-legacy 经
# render_page("legacy", ...) 与 has_page("legacy", ...) 直接按名调用,不走 list_styles。
_INTERNAL_STYLES = {"legacy"}


_envs: dict = {}


def _env(d: str) -> Environment:
    if d not in _envs:
        _envs[d] = Environment(
            loader=FileSystemLoader(d),
            autoescape=select_autoescape(["html"]),
        )
    return _envs[d]


def list_styles(d: str = None) -> list:
    """列出可用风格包(至少含一个页面模板的子目录),按名排序。"""
    d = d or styles_dir()
    if not os.path.isdir(d):
        return []
    out = []
    for name in sorted(os.listdir(d)):
        if name in _INTERNAL_STYLES:        # legacy 等内部模板集不算可选风格
            continue
        sub = os.path.join(d, name)
        if not os.path.isdir(sub):
            continue
        if any(os.path.exists(os.path.join(sub, f"{p}.html")) for p in PAGES):
            out.append(name)
    return out


def pick_style(cfg: dict, today: date = None, d: str = None) -> str:
    """按配置选风格。fixed→display.style;daily_random→按日期从随机池选。
    选中的风格不存在时回退到第一个可用风格(诚实降级)。"""
    avail = list_styles(d)
    disp = (cfg or {}).get("display", {})
    if disp.get("style_mode") == "daily_random":
        pool = [s for s in (disp.get("style_rotation") or []) if s in avail] or avail
        if not pool:
            return ""
        rng = random.Random((today or date.today()).toordinal())
        return rng.choice(pool)
    chosen = disp.get("style") or "style_a"
    if chosen in avail:
        return chosen
    return avail[0] if avail else ""


def read_css(style: str, d: str = None) -> str:
    path = os.path.join(d or styles_dir(), style, "style.css")
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def read_strings(style: str, d: str = None) -> dict:
    """读 styles/<style>/strings.json(i18n 文案表)。结构 {"zh":{...},"en":{...}}。
    缺文件/坏 JSON → 空 dict(诚实降级:模板 {{ t.x }} 渲染为空,不报错)。"""
    path = os.path.join(d or styles_dir(), style, "strings.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return {}


def render_page(style: str, page_key: str, ctx: dict, d: str = None,
                target: str = "kindle") -> str:
    """渲染 styles/<style>/<page_key>.html。模板缺失抛 TemplateNotFound,由上层降级。
    按 ctx['lang'] 注入该风格的文案表 t(英文缺条目回退中文)。

    target:渲染出口。默认 'kindle'(现状,静态灰度截图);'android' 时模板用
    `{% if target=='android' %}` 渲染可点控件 + 彩色覆盖(活 HTML)。
    默认 kindle 保证 Kindle 出图链路与所有现有调用像素级零影响。"""
    d = d or styles_dir()
    tpl = _env(d).get_template(f"{style}/{page_key}.html")
    full = dict(ctx)
    css = read_css(style, d)
    if target == "android":     # 灰度版不动;活 HTML 追加触控彩色主题(贴风格的强调色)
        css += ANDROID_THEME.replace("__ACCENT__", ANDROID_ACCENTS.get(style, _DEFAULT_ACCENT))
    elif target == "legacy_photo":   # 安卓4.x 图片相框:静态版式上还原彩色封面 + 暖白底(见 LEGACY_PHOTO_CSS)
        css += LEGACY_PHOTO_CSS
    full["css"] = css
    lang = (ctx.get("lang") or "zh")
    strings = read_strings(style, d)
    zh = strings.get("zh") or {}
    cur = strings.get(lang) or {}
    full["t"] = {**zh, **cur} if lang != "zh" else zh   # en 缺条目回退中文
    if target == "android":   # 合并中央控件文案(a_pause/a_resume/...);灰度版 t 不含,零影响
        astr = ANDROID_STRINGS.get(lang) or ANDROID_STRINGS["zh"]
        full["t"] = {**ANDROID_STRINGS["zh"], **full["t"], **astr}
    full["target"] = target
    full.setdefault("app_token", "")   # 动态版封面墙 <img> 用;静态/Kindle 渲染时为空(分支也不走它)
    return tpl.render(**full)


def has_page(style: str, page_key: str, d: str = None) -> bool:
    return os.path.exists(os.path.join(d or styles_dir(), style, f"{page_key}.html"))
