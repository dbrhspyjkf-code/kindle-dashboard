"""macOS 菜单栏:图标显示 + 看板服务控制。

仅 macOS(依赖 rumps/PyObjC,requirements.txt 用 marker 仅在 darwin 安装)。
由安装脚本生成 LSUIElement app bundle 后交给 LaunchAgent 登录自启。
读 config.yaml 的端口,每 5 秒轮询 /health,状态显示在下拉菜单中。
"""
import os
import plistlib
import subprocess
import threading
import urllib.request
import webbrowser

import rumps

from server import updater

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ICON_PATH = os.path.join(REPO, "data", "menubar-icon.png")
# 弹窗图标(彩色蓝底白卡):不指定的话系统会用 Python 解释器的小火箭图标。
ALERT_ICON = os.path.join(REPO, "installers", "macos", "appicon-1024.png")
_RUMPS_ALERT = rumps.alert   # 原始 alert,给 self._alert 内部用(避免下面把它也替换成 self._alert 导致递归)
SERVICE_LABEL = "com.kindle-dashboard"
PLIST = os.path.expanduser(f"~/Library/LaunchAgents/{SERVICE_LABEL}.plist")
MENUBAR_LABEL = "com.kindle-dashboard.menubar"
MENUBAR_PLIST = os.path.expanduser(f"~/Library/LaunchAgents/{MENUBAR_LABEL}.plist")
RESTART_SH = os.path.join(REPO, "installers", "macos", "restart.sh")
KINDLE_DIR = os.path.join(REPO, "installers", "kindle")
SUPPORT_DIR = os.path.dirname(REPO)            # .../Application Support/墨水桌面看板(.dmg 装法);git 装法是仓库父目录
# 在线更新查的 GitHub 仓库(与安卓 App 一致,.dmg 与 .apk 同一 Release)
GH_OWNER, GH_REPO = "yizhixiaoheigou", "kindle-dashboard"
# .dmg 安装的 .app 壳路径;被用户从 Finder 删掉时,菜单栏自检到后会自清(达到"删 App = 卸载干净")。
APP_BUNDLE = "/Applications/墨水桌面看板.app"
# 配置已外置到仓库外(与服务一致),菜单栏读写语言/端口/令牌都用这个路径。
CONFIG_PATH = os.environ.get("KINDLE_CONFIG") or os.path.expanduser("~/.config/kindle-dashboard/config.yaml")

# 菜单文案双语:zh 值与改动前完全一致(回归底线)。
MENU = {
    "zh": {
        "status_checking": "状态: 检测中",
        "status_running": "状态: 运行中",
        "status_stopped": "状态: 已停",
        "autostart": "开机自启",
        "open_setup": "打开设置页",
        "restart": "重启服务",
        "start": "启动服务",
        "stop": "停止服务",
        "quit": "退出状态栏",
        "quit_confirm_msg": "这只会退出顶部状态栏的图标。\n看板服务仍在后台运行,Kindle 照常更新。\n想重新打开状态栏:到「应用程序」里再打开一次「墨水桌面看板」即可。\n\n确定退出状态栏?",
        "cancel": "取消",
        "language": "语言 / Language",
        "lang_zh": "中文",
        "lang_en": "English",
        "autostart_fail_title": "开机自启设置失败",
        "fail_suffix": "失败",
        "restart_hint_title": "重开菜单栏生效",
        "restart_hint_msg": "语言已切换,请退出并重新打开菜单栏以应用。",
        "plist_not_found": "未找到服务 plist:{path}",
        "check_update": "检查更新",
        "version": "版本",
        "checking": "正在检查更新…",
        "up_to_date_title": "已是最新",
        "up_to_date_msg": "当前已是最新版本({v})。",
        "update_avail_title": "有新版本",
        "update_avail_msg": "落后 {n} 个更新({cur} → {latest})。现在升级?\n(升级会拉取最新代码并重启服务,不会动你的配置)",
        "update_fail_title": "检查更新失败",
        "upgrade_btn": "升级",
        "later_btn": "以后再说",
        "upgrade_ok_title": "升级完成",
        "upgrade_fail_title": "升级失败",
        # Kindle 刷入 / 退出
        "flash_kindle": "刷入 Kindle",
        "unflash_kindle": "退出 Kindle(还原阅读器)",
        "conn_title": "刷入 Kindle",
        "conn_prompt": "选择 Kindle 连接方式:",
        "conn_usb": "USB 数据线(免 WiFi)",
        "conn_wifi": "WiFi(同一局域网)",
        "ip_prompt_wifi": "输入 Kindle 的 WiFi IP 地址\n(在 Kindle 上:设置→设备信息里看):",
        "ip_prompt_any": "输入 Kindle 的 IP 地址:",
        "interval_prompt": "Kindle 多久拉一次新图?(秒)\n越短越实时、越费电,常用 20:",
        "flash_confirm_msg": "即将把看板刷入 Kindle({ip})。\n接下来可能要求:① 本机管理员密码(USB 配网用)② Kindle 的 SSH 密码(越狱默认 mario)。\n\n前提:Kindle 已越狱并开启 USBNetwork/SSH。继续?",
        "flashing": "正在刷入 Kindle,请按提示输入密码…",
        "flash_done_ok": "刷入完成",
        "flash_done_fail": "刷入失败",
        "unflash_confirm_msg": "将把 Kindle({ip})还原成正常阅读器(移除看板与开机自启)。继续?",
        "unflash_done_ok": "已还原 Kindle",
        "unflash_done_fail": "还原失败",
        "kindle_pw_prompt": "请输入 Kindle 的 root 密码(越狱 SSH 密码,默认 mario):",
        "admin_pw_prompt": "请输入本机管理员密码(用于配置 USB 网络):",
        "need_ip": "没有可用的 Kindle IP,已取消。",
        # 卸载
        "uninstall_app": "卸载墨水桌面看板…",
        "uninstall_confirm_msg": "确定卸载吗?将停止并移除后台服务、菜单栏和开机自启,删除程序文件。\n(已刷过的 Kindle 不会自动还原;如需还原请先点「退出 Kindle」)",
        "purge_ask_msg": "是否同时删除你的配置(天气 Key、设备、风格等)?\n选「否」会保留,下次重装即可恢复。",
        "uninstall_done_title": "卸载完成",
        "uninstall_done_msg": "后台服务与菜单栏已移除。最后把「墨水桌面看板」从「应用程序」拖进废纸篓即可。",
        # Release 在线更新(.dmg 安装版)
        "rel_update_msg": "发现新版本 {latest}(当前 {cur})。前往下载页?\n下载新的 .dmg 拖进「应用程序」覆盖即可,配置不受影响。",
        "rel_open_btn": "前往下载",
    },
    "en": {
        "status_checking": "Status: checking",
        "status_running": "Status: running",
        "status_stopped": "Status: stopped",
        "autostart": "Start at login",
        "open_setup": "Open settings",
        "restart": "Restart service",
        "start": "Start service",
        "stop": "Stop service",
        "quit": "Quit status bar",
        "quit_confirm_msg": "This only closes the status bar icon.\nThe dashboard service keeps running in the background; your Kindle keeps updating.\nTo bring it back, open \"Moshui Dashboard\" again from Applications.\n\nQuit the status bar?",
        "cancel": "Cancel",
        "language": "语言 / Language",
        "lang_zh": "中文",
        "lang_en": "English",
        "autostart_fail_title": "Failed to set start-at-login",
        "fail_suffix": " failed",
        "restart_hint_title": "Restart menu bar to apply",
        "restart_hint_msg": "Language changed. Quit and reopen the menu bar to apply.",
        "plist_not_found": "Service plist not found: {path}",
        "check_update": "Check for updates",
        "version": "Version",
        "checking": "Checking for updates…",
        "up_to_date_title": "Up to date",
        "up_to_date_msg": "You're on the latest version ({v}).",
        "update_avail_title": "Update available",
        "update_avail_msg": "{n} update(s) behind ({cur} → {latest}). Upgrade now?\n(Pulls latest code and restarts the service; your config is untouched.)",
        "update_fail_title": "Update check failed",
        "upgrade_btn": "Upgrade",
        "later_btn": "Later",
        "upgrade_ok_title": "Upgrade complete",
        "upgrade_fail_title": "Upgrade failed",
        "flash_kindle": "Flash to Kindle",
        "unflash_kindle": "Remove from Kindle (restore reader)",
        "conn_title": "Flash to Kindle",
        "conn_prompt": "Choose how the Kindle is connected:",
        "conn_usb": "USB cable (no WiFi)",
        "conn_wifi": "WiFi (same network)",
        "ip_prompt_wifi": "Enter the Kindle's WiFi IP address\n(on Kindle: Settings -> Device Info):",
        "ip_prompt_any": "Enter the Kindle's IP address:",
        "interval_prompt": "How often should the Kindle pull a new image? (sec)\nShorter = more live but more battery; 20 is common:",
        "flash_confirm_msg": "About to flash the dashboard to the Kindle ({ip}).\nYou may be asked for: 1) your Mac admin password (for USB networking) 2) the Kindle SSH password (jailbreak default: mario).\n\nRequires a jailbroken Kindle with USBNetwork/SSH enabled. Continue?",
        "flashing": "Flashing to Kindle, follow the password prompts...",
        "flash_done_ok": "Flash complete",
        "flash_done_fail": "Flash failed",
        "unflash_confirm_msg": "This will restore the Kindle ({ip}) to a normal reader (remove the dashboard and auto-start). Continue?",
        "unflash_done_ok": "Kindle restored",
        "unflash_done_fail": "Restore failed",
        "kindle_pw_prompt": "Enter the Kindle root password (jailbreak SSH password, default mario):",
        "admin_pw_prompt": "Enter your Mac admin password (to set up USB networking):",
        "need_ip": "No Kindle IP available; cancelled.",
        "uninstall_app": "Uninstall Moshui Dashboard...",
        "uninstall_confirm_msg": "Uninstall? This stops and removes the background service, menu bar, and auto-start, and deletes program files.\n(A flashed Kindle is NOT restored automatically; use \"Remove from Kindle\" first if needed.)",
        "purge_ask_msg": "Also delete your config (weather key, devices, style, etc.)?\nChoose No to keep it for a future reinstall.",
        "uninstall_done_title": "Uninstalled",
        "uninstall_done_msg": "The background service and menu bar are removed. Finally, drag \"Moshui Dashboard\" from Applications to the Trash.",
        "rel_update_msg": "New version {latest} available (current {cur}). Open the download page?\nDownload the new .dmg and drop it into Applications to replace; your config is untouched.",
        "rel_open_btn": "Open download",
    },
}


def _read_config():
    try:
        import yaml
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _language():
    lang = (_read_config().get("server", {}) or {}).get("language", "zh")
    return lang if lang in MENU else "zh"


def _set_language(lang):
    """写 config.server.language;尽量保留其余配置(直接 yaml 读改写)。"""
    import yaml
    cfg = _read_config()
    cfg.setdefault("server", {})["language"] = lang
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)


def _get_kindle(key, default=""):
    return (_read_config().get("kindle", {}) or {}).get(key, default)


def _set_kindle(key, val):
    """记住上次刷入用的 Kindle IP / 间隔,下次默认带出。"""
    try:
        import yaml
        cfg = _read_config()
        cfg.setdefault("kindle", {})[key] = val
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
    except Exception:
        pass


# 菜单栏所有弹窗已统一用 rumps 原生 NSAlert / Window(见 DashboardBar._alert / _prompt)——
# osascript 弹窗从后台菜单栏程序调出来会置顶、抢不到焦点、卡死,故弃用。askpass 仍用 osascript(ssh/sudo 调外部脚本)。
def _write_askpass(path, prompt, default=""):
    """生成一个 askpass 脚本:ssh/sudo 需要密码时调它 → 弹 osascript 隐藏输入框 → echo 密码。"""
    h = " with hidden answer"
    body = ('#!/bin/bash\n'
            "osascript -e 'text returned of (display dialog \"%s\" "
            "with title \"墨水桌面看板\" default answer \"%s\"%s)' 2>/dev/null\n"
            ) % (prompt.replace('"', '\\"'), default, h)
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
    os.chmod(path, 0o700)


def _spawn_cleanup(purge=False, remove_app=True):
    """后台独立进程清理(用系统 bash,不在被删目录里跑,避免自删僵死)。
    供「卸载」菜单和「检测到 .app 被删自愈」共用。purge=True 连配置一起删;
    remove_app=False 用于自愈(此时 .app 已被用户删掉,不必再删)。"""
    rem_plist = os.path.expanduser("~/Library/LaunchAgents/com.kindle-dashboard.reminders.plist")
    lines = ["sleep 1"]
    for label, p in ((SERVICE_LABEL, PLIST), (MENUBAR_LABEL, MENUBAR_PLIST),
                     ("com.kindle-dashboard.reminders", rem_plist)):
        lines.append('launchctl unload "%s" 2>/dev/null' % p)
        lines.append('launchctl remove "%s" 2>/dev/null' % label)
        lines.append('rm -f "%s"' % p)
    # 先杀进程(菜单栏自己可能还没完全退),再删 venv —— 顺序反了会删到正在运行的文件导致僵死。
    lines.append('pkill -9 -f server.menubar 2>/dev/null')
    lines.append('pkill -9 -f server.run 2>/dev/null')
    # 仅 .dmg 安装(REPO 在 Application Support 下)才删程序目录,避免误删命令行用户的 git 仓库。
    if "Application Support" in REPO:
        lines.append('rm -rf "%s"' % SUPPORT_DIR)
    if remove_app:
        lines.append('rm -rf "%s"' % APP_BUNDLE)
    if purge:
        lines.append('rm -rf "%s"' % os.path.dirname(CONFIG_PATH))
    lines.append('killall Dock 2>/dev/null')   # 刷新状态栏/启动台残留
    subprocess.Popen(["bash", "-c", "\n".join(lines)], start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _hide_dock_icon():
    try:
        from AppKit import NSApplication, NSApplicationActivationPolicyAccessory
        NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    except Exception:
        pass


def _ensure_icon():
    try:
        from PIL import Image, ImageDraw
        os.makedirs(os.path.dirname(ICON_PATH), exist_ok=True)
        size = 20
        scale = 4
        img = Image.new("RGBA", (size * scale, size * scale), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        ink = (0, 0, 0, 255)
        def box(values):
            return tuple(int(round(v * scale)) for v in values)

        def px(value):
            return int(round(value * scale))

        # Kindle 外框 + dashboard 信息块,模板图标在深浅菜单栏都可反色。
        d.rounded_rectangle(box((3, 1.8, 17, 18.2)), radius=px(3), outline=ink, width=px(1.7))
        d.rounded_rectangle(box((6, 5, 14, 8)), radius=px(1), fill=ink)
        d.rounded_rectangle(box((6, 10, 9, 13.5)), radius=px(0.8), fill=ink)
        d.rounded_rectangle(box((11, 10, 14, 13.5)), radius=px(0.8), fill=ink)
        d.rounded_rectangle(box((8.2, 16, 11.8, 17)), radius=px(0.5), fill=ink)
        resampling = getattr(Image, "Resampling", Image).LANCZOS
        img.resize((size, size), resampling).save(ICON_PATH)
        return ICON_PATH
    except Exception:
        return None


def _service_autostart_enabled():
    try:
        with open(PLIST, "rb") as f:
            data = plistlib.load(f)
        return bool(data.get("RunAtLoad")) and bool(data.get("KeepAlive"))
    except Exception:
        return False


def _set_service_autostart(enabled):
    with open(PLIST, "rb") as f:
        data = plistlib.load(f)
    data["RunAtLoad"] = bool(enabled)
    data["KeepAlive"] = bool(enabled)
    with open(PLIST, "wb") as f:
        plistlib.dump(data, f, sort_keys=False)


def _port():
    try:
        import yaml
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        return int(cfg.get("server", {}).get("port", 8585))
    except Exception:
        return 8585


def _launchctl(*args):
    return subprocess.run(["launchctl", *args], capture_output=True, text=True)


def _start_service():
    if not os.path.exists(PLIST):
        raise FileNotFoundError(
            MENU[_language()]["plist_not_found"].format(path=PLIST))
    _launchctl("load", PLIST)
    _launchctl("start", SERVICE_LABEL)


def _stop_service():
    _launchctl("unload", PLIST)


def _restart_service():
    _launchctl("unload", PLIST)
    _launchctl("load", PLIST)
    _launchctl("start", SERVICE_LABEL)


def _set_checked(item, checked):
    try:
        item.state = 1 if checked else 0
    except Exception:
        pass


class DashboardBar(rumps.App):
    def __init__(self):
        kwargs = {"quit_button": None}
        icon = _ensure_icon()
        if icon:
            kwargs["icon"] = icon
            kwargs["template"] = True
        title = "" if icon else "▣"
        try:
            super().__init__("Kindle Dashboard", title=title, **kwargs)
        except TypeError:
            kwargs.pop("template", None)
            try:
                super().__init__("Kindle Dashboard", title=title, **kwargs)
            except TypeError:
                super().__init__(title, **kwargs)
        self.port = _port()
        self._has_icon = bool(icon)
        self.lang = _language()
        t = MENU[self.lang]
        # 用带 callback 的 MenuItem(而非 @rumps.clicked 装饰器),菜单项标题可随语言变化。
        self.status_item = rumps.MenuItem(t["status_checking"])
        self.autostart_item = rumps.MenuItem(t["autostart"], callback=self._toggle_autostart)
        # 启停分两个独立项,避免动态改标题导致回调失效
        lang_menu = rumps.MenuItem(t["language"])
        self.lang_zh_item = rumps.MenuItem(t["lang_zh"], callback=lambda _: self._set_lang("zh"))
        self.lang_en_item = rumps.MenuItem(t["lang_en"], callback=lambda _: self._set_lang("en"))
        _set_checked(self.lang_zh_item, self.lang == "zh")
        _set_checked(self.lang_en_item, self.lang == "en")
        lang_menu.add(self.lang_zh_item)
        lang_menu.add(self.lang_en_item)
        # 安装形态:git clone(命令行老用户)走 git 升级;.dmg 安装包走 GitHub Release 提示。
        self.is_git = updater.is_git_repo(REPO)
        ver = updater.current_version(REPO) if self.is_git else updater.installed_version(REPO)
        # 存「检查更新」项的引用:后台自动查到新版时把它标红
        self.update_item = rumps.MenuItem(t["check_update"], callback=self._check_update)
        self.menu = [
            self.status_item, self.autostart_item, None,
            rumps.MenuItem(t["open_setup"], callback=self._open),
            rumps.MenuItem(t["restart"], callback=self._restart),
            rumps.MenuItem(t["start"], callback=self._start),
            rumps.MenuItem(t["stop"], callback=self._stop),
            None,
            rumps.MenuItem(t["flash_kindle"], callback=self._flash_kindle),
            rumps.MenuItem(t["unflash_kindle"], callback=self._unflash_kindle),
            None,
            rumps.MenuItem(f"{t['version']}: {ver}"),  # 无回调=仅显示
            self.update_item,
            None, lang_menu, None,
            rumps.MenuItem(t["uninstall_app"], callback=self._uninstall_app),
            rumps.MenuItem(t["quit"], callback=self._quit),
        ]
        self._app_missing = 0   # 连续几次检测不到 .app 壳(自愈卸载用)
        self._pending_update = None   # 后台自动检查发现的新版信息(主线程 refresh 据此标红菜单)
        self._update_marked = False
        self._timer = rumps.Timer(self.refresh, 5)
        self._timer.start()
        self.refresh()
        self._start_auto_update()   # .dmg 装法:启动后 + 每 6h 后台静默查更新

    def _alive(self):
        try:
            with urllib.request.urlopen(
                    "http://127.0.0.1:%d/health" % self.port, timeout=2) as r:
                return b'"status":"ok"' in r.read()
        except Exception:
            return False

    def refresh(self, _=None):
        t = MENU[self.lang]
        self.title = "" if self._has_icon else "▣"
        self.status_item.title = t["status_running"] if self._alive() else t["status_stopped"]
        _set_checked(self.autostart_item, _service_autostart_enabled())
        # 后台自动检查查到新版 → 把「检查更新」标红(主线程改 UI,避免后台线程碰 UI)
        if self._pending_update and not self._update_marked:
            self.update_item.title = "🔴 %s (%s)" % (
                t["check_update"], self._pending_update.get("latest", ""))
            self._update_marked = True
        self._self_heal_if_app_deleted()

    # ---- 自动检查更新(.dmg 装法:后台线程查 GitHub Release,不阻塞菜单栏;git 装法不自动查)----
    def _start_auto_update(self):
        if self.is_git:
            return
        self._schedule_auto_check(8)            # 启动 8 秒后查一次

    def _schedule_auto_check(self, delay):
        tm = threading.Timer(delay, self._auto_check_worker)
        tm.daemon = True                        # 守护线程,进程退出即结束
        tm.start()

    def _auto_check_worker(self):
        try:
            info = updater.check_release(GH_OWNER, GH_REPO,
                                         current=updater.installed_version(REPO))
            if info.get("ok") and info.get("newer"):
                self._pending_update = info     # 只置数据,UI 留给主线程 refresh 改
        except Exception:
            pass
        self._schedule_auto_check(6 * 3600)     # 之后每 6 小时

    def _self_heal_if_app_deleted(self):
        """.dmg 安装:用户从 Finder 删了 .app 壳 → 自动清理后台服务/菜单栏/程序文件,
        让"删 App = 卸载干净"。连续两次(~10s)检测不到才动手,避免瞬时误判。"""
        if "Application Support" not in REPO:   # git 装法没有 .app 壳,不适用
            return
        if os.path.exists(APP_BUNDLE):
            self._app_missing = 0
            return
        self._app_missing += 1
        if self._app_missing >= 2:
            # 静默清理(不发 osascript 通知,图标丑);状态栏图标随进程退出而消失,即是反馈。
            _spawn_cleanup(purge=False, remove_app=False)   # .app 已被删,只清后台与程序文件
            rumps.quit_application()

    def _toggle_autostart(self, _):
        enabled = not _service_autostart_enabled()
        try:
            _set_service_autostart(enabled)
            _set_checked(self.autostart_item, enabled)
        except Exception as e:
            self._alert(MENU[self.lang]["autostart_fail_title"], str(e))

    def _set_lang(self, lang):
        t = MENU[self.lang]
        try:
            _set_language(lang)
        except Exception as e:
            self._alert(MENU[self.lang]["fail_suffix"].strip() or "Error", str(e))
            return
        # rumps 已建好的菜单标题改起来繁琐,直接提示重开菜单栏生效(与设置页"重载"等价)。
        _set_checked(self.lang_zh_item, lang == "zh")
        _set_checked(self.lang_en_item, lang == "en")
        self._alert(t["restart_hint_title"], t["restart_hint_msg"])

    def _check_update(self, _):
        """检查更新。git 装法→git pull 自更新;.dmg 装法→查 Release,有新版引导去下载。
        同步执行(点击后菜单栏会短暂无响应,几秒~几十秒,完成弹结果)。"""
        t = MENU[self.lang]
        if not self.is_git:
            cur = updater.installed_version(REPO)
            info = updater.check_release(GH_OWNER, GH_REPO, current=cur)
            if not info.get("ok"):
                self._alert(t["update_fail_title"], info.get("error", ""))
                return
            if not info.get("newer"):
                self._alert(t["up_to_date_title"], t["up_to_date_msg"].format(v=cur))
                return
            resp = self._alert(
                t["update_avail_title"],
                t["rel_update_msg"].format(latest=info.get("latest", "?"), cur=cur),
                ok=t["rel_open_btn"], cancel=t["later_btn"])
            if resp == 1 and info.get("url"):
                webbrowser.open(info["url"])
            return
        info = updater.check_for_update(REPO)
        if not info.get("ok"):
            self._alert(t["update_fail_title"], info.get("error", ""))
            return
        if info.get("behind", 0) <= 0:
            self._alert(t["up_to_date_title"], t["up_to_date_msg"].format(v=info.get("current", "?")))
            return
        resp = self._alert(
            t["update_avail_title"],
            t["update_avail_msg"].format(n=info["behind"], cur=info.get("current", "?"),
                                         latest=info.get("latest", "?")),
            ok=t["upgrade_btn"], cancel=t["later_btn"])
        if resp != 1:
            return
        ok, msg = updater.do_upgrade(REPO, restart_script=RESTART_SH)
        self._alert(t["upgrade_ok_title"] if ok else t["upgrade_fail_title"], msg)
        if ok:
            self._delayed_relaunch_menubar()
        self.refresh()

    def _delayed_relaunch_menubar(self):
        """升级后延迟重启菜单栏自己:fork 一个后台进程,等 2 秒再 unload+load。
        不能同步做——restart.sh 的 unload 会杀掉当前进程,rumps.alert 来不及显示。"""
        mb_plist = os.path.expanduser("~/Library/LaunchAgents/com.kindle-dashboard.menubar.plist")
        if not os.path.exists(mb_plist):
            return
        subprocess.Popen(
            ["bash", "-c", f"sleep 2 && launchctl unload '{mb_plist}' 2>/dev/null; launchctl load '{mb_plist}' 2>/dev/null"],
            start_new_session=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # ---- Kindle 刷入 / 退出 ----
    def _kindle_env(self):
        """给 kindle 脚本准备 askpass:无终端时 ssh/sudo 也能弹图形密码框。"""
        t = MENU[self.lang]
        ssh_ap = os.path.join(SUPPORT_DIR, "askpass-ssh.sh")
        sudo_ap = os.path.join(SUPPORT_DIR, "askpass-sudo.sh")
        try:
            os.makedirs(SUPPORT_DIR, exist_ok=True)
            _write_askpass(ssh_ap, t["kindle_pw_prompt"], default="mario")
            _write_askpass(sudo_ap, t["admin_pw_prompt"])
        except Exception:
            pass
        env = dict(os.environ)
        env["SSH_ASKPASS"] = ssh_ap
        env["SSH_ASKPASS_REQUIRE"] = "force"   # OpenSSH 8.4+/macOS 12+:无 tty 也强制走 askpass
        env["SUDO_ASKPASS"] = sudo_ap          # 配合 install.sh 的 `sudo -A`
        env.setdefault("DISPLAY", ":0")
        return env

    def _run_kindle(self, script, args):
        path = os.path.join(KINDLE_DIR, script)
        try:
            r = subprocess.run(["bash", path, *args], capture_output=True, text=True,
                               timeout=600, env=self._kindle_env(), cwd=REPO)
            out = (r.stdout or "") + (("\n" + r.stderr) if r.stderr else "")
            return r.returncode, out.strip()[-1500:]   # 截尾,弹窗别太长
        except Exception as e:
            return 1, str(e)

    def _alert(self, title, message="", ok=None, cancel=None, other=None):
        """原生弹窗(NSAlert),带我们的图标(告别小火箭),焦点正常(不像 osascript 那样置顶卡死)。"""
        try:
            return _RUMPS_ALERT(title, message, ok=ok, cancel=cancel, other=other, icon_path=ALERT_ICON)
        except TypeError:   # 老版 rumps 可能没 icon_path 参数
            return _RUMPS_ALERT(title, message, ok=ok, cancel=cancel, other=other)

    def _prompt(self, message, default="", title="墨水桌面看板"):
        """原生输入框;返回输入文本(strip),取消返回 None。"""
        w = rumps.Window(message=message, title=title, default_text=str(default),
                         ok="确定", cancel="取消", dimensions=(240, 24))
        try:
            w.icon = ALERT_ICON
        except Exception:
            pass
        r = w.run()
        return r.text.strip() if r.clicked else None

    def _flash_kindle(self, _):
        t = MENU[self.lang]
        # 连接方式:点「USB」=ok(1);点「WiFi」=cancel(0)。取消整个流程可在后续输入框点取消。
        usb = self._alert(t["conn_title"], t["conn_prompt"],
                          ok=t["conn_usb"], cancel=t["conn_wifi"]) == 1
        if usb:
            ip = "192.168.15.244"
        else:
            ip = self._prompt(t["ip_prompt_wifi"], _get_kindle("last_ip", "192.168."), t["conn_title"])
            if not ip:
                return
        interval = self._prompt(t["interval_prompt"], str(_get_kindle("last_interval", "20")), t["conn_title"])
        if not interval:
            return
        if self._alert(t["conn_title"], t["flash_confirm_msg"].format(ip=ip), ok="继续", cancel="取消") != 1:
            return
        _set_kindle("last_ip", ip)
        _set_kindle("last_interval", interval)
        rc, out = self._run_kindle("install.sh", [ip, "", interval])   # 空 SERVER_URL=脚本自动探测本机 IP
        self._alert(t["flash_done_ok"] if rc == 0 else t["flash_done_fail"], out or "")

    def _unflash_kindle(self, _):
        t = MENU[self.lang]
        ip = self._prompt(t["ip_prompt_any"], _get_kindle("last_ip", "192.168.15.244"), t["unflash_kindle"])
        if not ip:
            return
        if self._alert(t["unflash_kindle"], t["unflash_confirm_msg"].format(ip=ip), ok="继续", cancel="取消") != 1:
            return
        rc, out = self._run_kindle("uninstall.sh", [ip])
        self._alert(t["unflash_done_ok"] if rc == 0 else t["unflash_done_fail"], out or "")

    # ---- 一键卸载 ----
    def _uninstall_app(self, _):
        # 用 rumps 原生弹窗(NSAlert),不用 osascript —— 后者从后台菜单栏程序调出来会置顶、抢不到焦点、卡死。
        t = MENU[self.lang]
        if self._alert(t["uninstall_app"], t["uninstall_confirm_msg"], ok="继续", cancel="取消") != 1:
            return
        purge = self._alert(t["uninstall_app"], t["purge_ask_msg"], ok="删除配置", cancel="保留配置") == 1
        _spawn_cleanup(purge=purge, remove_app=True)
        # 不弹"完成"窗:后台 1 秒后会删掉本进程的 venv,若此时还卡在弹窗会僵死。图标消失即反馈。
        rumps.quit_application()

    def _open(self, _):
        tok = ""
        try:
            tok = (_read_config().get("server", {}) or {}).get("access_token", "") or ""
        except Exception:
            pass
        q = ("?token=" + tok) if tok else ""   # 带令牌才能打开,否则页面里 /api/* 全 401
        webbrowser.open("http://127.0.0.1:%d/setup%s" % (self.port, q))

    def _restart(self, _):
        self._run_control(MENU[self.lang]["restart"], _restart_service)

    def _start(self, _):
        self._run_control(MENU[self.lang]["start"], _start_service)

    def _stop(self, _):
        self._run_control(MENU[self.lang]["stop"], _stop_service)

    def _run_control(self, title, action):
        try:
            action()
        except Exception as e:
            self._alert(f"{title}{MENU[self.lang]['fail_suffix']}", str(e))
        self.refresh()

    def _quit(self, _):
        # 退出前提示:只退状态栏,看板服务继续后台跑(用户常误以为"退出=停服务")。
        t = MENU[self.lang]
        if self._alert(t["quit"], t["quit_confirm_msg"], ok=t["quit"], cancel=t["cancel"]) == 1:
            rumps.quit_application()


def main():
    _hide_dock_icon()
    DashboardBar().run()


if __name__ == "__main__":
    main()
