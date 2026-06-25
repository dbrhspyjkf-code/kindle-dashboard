"""在线升级:两种安装形态各一套。

1. **git clone 安装**(命令行老用户):`check_for_update` / `do_upgrade` 走 git pull。
2. **.dmg 安装包安装**(Mac App):无 git 仓库,走 `check_release` 查 GitHub Release,
   有新版只提示去下新 .dmg(不在应用内静默替换 .app)。

全部**不依赖 rumps**(纯 subprocess + urllib),可在任意平台单元测试。
配置已外置到仓库外(见 app._resolve_config_path),升级**绝不会动到用户配置**。
"""
import json
import os
import subprocess
import urllib.request


def _git(repo, *args, timeout=30):
    return subprocess.run(["git", "-C", repo, *args],
                          capture_output=True, text=True, timeout=timeout)


def is_git_repo(repo):
    try:
        r = _git(repo, "rev-parse", "--is-inside-work-tree")
        return r.returncode == 0 and r.stdout.strip() == "true"
    except Exception:
        return False


def current_version(repo):
    """当前版本(短哈希);非 git 或失败返回 '?'。"""
    try:
        r = _git(repo, "rev-parse", "--short", "HEAD")
        return r.stdout.strip() or "?" if r.returncode == 0 else "?"
    except Exception:
        return "?"


def check_for_update(repo, branch="main"):
    """联网比对本地与 origin/<branch>。返回:
    {ok: True, current, latest, behind}  或  {ok: False, error}。"""
    if not is_git_repo(repo):
        return {"ok": False, "error": "不是 git 仓库,无法在线升级(请用 git clone 方式安装)。"}
    try:
        f = _git(repo, "fetch", "--quiet", "origin", branch, timeout=40)
    except Exception as e:
        return {"ok": False, "error": f"拉取远程失败:{e}"}
    if f.returncode != 0:
        return {"ok": False, "error": "拉取远程失败(检查网络/代理):" + (f.stderr.strip()[:200])}
    cur = _git(repo, "rev-parse", "HEAD").stdout.strip()
    rem = _git(repo, "rev-parse", f"origin/{branch}").stdout.strip()
    cnt = _git(repo, "rev-list", "--count", f"HEAD..origin/{branch}").stdout.strip()
    try:
        behind = int(cnt)
    except ValueError:
        behind = 0
    return {"ok": True, "current": cur[:7], "latest": rem[:7], "behind": behind}


def installed_version(repo):
    """安装版本:.dmg 安装包写了 APP_VERSION 文件则用它,否则退回 git 短哈希。"""
    vf = os.path.join(repo, "APP_VERSION")
    try:
        if os.path.exists(vf):
            with open(vf, encoding="utf-8") as f:
                v = f.read().strip()
            if v:
                return v
    except Exception:
        pass
    return current_version(repo)


def _norm_ver(tag):
    """把 'v2.0' / 'mac-2.0' 之类规整成可比较的 (int, ...) 元组;失败回退原串。"""
    import re
    nums = re.findall(r"\d+", tag or "")
    return tuple(int(n) for n in nums) if nums else None


def _ver_from_asset(name, suffix):
    """从资产文件名取版本号:墨水桌面看板-1.0.dmg → '1.0'。取不到返回 ''。"""
    import re
    m = re.search(r"-(\d+(?:\.\d+)*)" + re.escape(suffix) + r"$", name or "", re.I)
    return m.group(1) if m else ""


def check_release(owner, repo_name, current=None, asset_suffix=".dmg", timeout=10):
    """查 GitHub Release 里挂了 asset_suffix(.dmg/.apk)的最新版本,从**资产文件名**取版本号比对。
    遍历 releases(不是 releases/latest)——Mac 只认 .dmg、安卓只认 .apk,与对方平台的 release 互不干扰,
    共用同一 Release 或各发各的都不会错判。返回:
    {ok: True, latest, url, asset_url, name, newer: bool}  或  {ok: False, error}。"""
    url = "https://api.github.com/repos/%s/%s/releases?per_page=30" % (owner, repo_name)
    req = urllib.request.Request(url, headers={
        "User-Agent": "kindle-dashboard-mac",          # GitHub API 要求带 UA,否则 403
        "Accept": "application/vnd.github+json",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"ok": False, "error": "查询 GitHub 发布失败(检查网络/代理):%s" % e}
    if not isinstance(data, list):
        return {"ok": False, "error": "GitHub 发布列表格式异常。"}
    # GitHub 按发布时间倒序返回;取第一个挂了对应安装包的正式 release。
    for rel in data:
        if rel.get("draft") or rel.get("prerelease"):
            continue
        for asset in (rel.get("assets") or []):
            name = asset.get("name", "")
            if not name.lower().endswith(asset_suffix):
                continue
            ver = _ver_from_asset(name, asset_suffix) or (rel.get("tag_name") or "").strip()
            newer = False
            if current:
                cv, lv = _norm_ver(current), _norm_ver(ver)
                newer = (lv > cv) if (cv and lv) else (ver != current.strip())
            return {"ok": True, "latest": ver, "url": rel.get("html_url", ""),
                    "asset_url": asset.get("browser_download_url", ""),
                    "name": rel.get("name", "") or ver, "newer": newer}
    return {"ok": False, "error": "未找到 %s 安装包(还没发布?)。" % asset_suffix}


def do_upgrade(repo, branch="main", restart_script=None):
    """git pull --ff-only,可选地跑重启脚本。返回 (ok: bool, message: str)。
    --ff-only:本地若改过代码导致无法快进,直接报错(不强行合并/丢改动),诚实降级。"""
    if not is_git_repo(repo):
        return False, "不是 git 仓库,无法升级。"
    try:
        p = _git(repo, "pull", "--ff-only", "origin", branch, timeout=180)
    except Exception as e:
        return False, f"升级失败:{e}"
    if p.returncode != 0:
        return False, "升级失败(本地可能改过代码,无法快进):" + (p.stderr.strip()[:200])
    msg = "代码已更新到最新。"
    if restart_script and os.path.exists(restart_script):
        try:
            env = dict(os.environ, KINDLE_SKIP_MENUBAR_RESTART="1")
            r = subprocess.run(["bash", restart_script],
                               capture_output=True, text=True, timeout=180, env=env)
            msg += "服务已重启。" if r.returncode == 0 else "但重启脚本返回非 0,请手动重启服务。"
        except Exception as e:
            msg += f"但自动重启失败({e}),请手动重启服务。"
    return True, msg
