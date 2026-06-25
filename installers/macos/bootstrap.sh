#!/bin/bash
# 墨水桌面看板 —— .app 首次启动引导(GUI 版,无命令行)。
# 由 .app 的 launcher 调用:bootstrap.sh <APP_RES> <APP_VERSION>
#   APP_RES      .app/Contents/Resources/app 的绝对路径(打进包的源码子集)
#   APP_VERSION  .app 的版本号(CFBundleShortVersionString)
# 把源码复制到 Application Support、建 venv、探测/可选下载渲染引擎、装 launchd、起服务。
# 所有"询问/报错"走 osascript 弹窗(没有终端)。逻辑对标命令行版 install.sh,但非交互。
#
# 退出码:0=成功(或已安装无需动);非 0=失败(已弹窗告知用户)。

APP_RES="$1"
APP_VERSION="${2:-0}"

SUPPORT="$HOME/Library/Application Support/墨水桌面看板"
REPO="$SUPPORT/repo"
VENV="$REPO/.venv"
PY="$VENV/bin/python"
PIP="$VENV/bin/pip"
STAMP="$SUPPORT/.installed"
LOG="$SUPPORT/bootstrap.log"
CONFIG="${KINDLE_CONFIG:-$HOME/.config/kindle-dashboard/config.yaml}"
PLIST_LABEL="com.kindle-dashboard"
PLIST="$HOME/Library/LaunchAgents/$PLIST_LABEL.plist"
MB_LABEL="com.kindle-dashboard.menubar"
MB_PLIST="$HOME/Library/LaunchAgents/$MB_LABEL.plist"
# 安装窗口用的图标(.app 里的 AppIcon.icns,蓝底白卡);规范化掉 APP_RES 里的 ..
ICON_ICNS="$(cd "$APP_RES/.." 2>/dev/null && pwd)/AppIcon.icns"
# pip 源:安装时测速自动选(官方 pypi.org vs 国内清华镜像,哪个快用哪个;国内连镜像、国外连官方,全自动)。
# 只在真要装依赖时测一次,结果缓存在 PIP_IDX;PIP_INDEX_URL 环境变量可显式覆盖。
PIP_IDX=""
ensure_pip_index(){
  [ -n "$PIP_IDX" ] && return
  if [ -n "$PIP_INDEX_URL" ]; then PIP_IDX="$PIP_INDEX_URL"; echo "pip index (env): $PIP_IDX" >>"$LOG"; return; fi
  local best="" bestt=99 url tt
  echo "==> 测速选 pip 源(量首字节响应延迟,取最快):" >>"$LOG"
  for url in "https://pypi.org/simple/" "https://pypi.tuna.tsinghua.edu.cn/simple/"; do
    # time_starttransfer = 连上+服务器开始回应的延迟,不下整个大索引页(用 time_total 会两边都卡满超时)。
    tt="$(curl -o /dev/null -s -m 6 -w "%{time_starttransfer}" "$url" 2>/dev/null)"
    # 超时/失败 → curl 退出码非 0,tt 可能为 0 或空,都视作不可用。
    if [ -z "$tt" ] || awk "BEGIN{exit !($tt+0 <= 0)}" 2>/dev/null; then
      echo "     $url -> 超时/不可达" >>"$LOG"; continue
    fi
    echo "     $url -> ${tt}s" >>"$LOG"
    if awk "BEGIN{exit !($tt+0 < $bestt+0)}" 2>/dev/null; then bestt="$tt"; best="$url"; fi
  done
  PIP_IDX="${best:-https://pypi.tuna.tsinghua.edu.cn/simple/}"   # 两个都没测到→默认清华
  echo "     => 选用最快的: $PIP_IDX (${bestt}s)" >>"$LOG"
}

mkdir -p "$SUPPORT"
exec 2>>"$LOG"   # stderr 进日志,方便排错;弹窗只给用户看友好信息
echo "==== bootstrap $(date) app_ver=$APP_VERSION res=$APP_RES ====" >>"$LOG"

# ---- 架构:用硬件检测(sysctl),不是 uname -m ----
# 本进程可能被 macOS 丢进 Rosetta(x86_64)跑,uname 会误报 x86_64,而 launchd 起服务是原生 arm64。
# 必须按硬件强制 arm64:venv 创建、pip、每一次跑 venv python、launchd 全部加 arm64,两边架构才一致。
ARCH=()
[ "$(sysctl -n hw.optional.arm64 2>/dev/null)" = "1" ] && ARCH=(arch -arm64)
ARCH_PA=""      # launchd plist 的 ProgramArguments 架构前缀
[ ${#ARCH[@]} -gt 0 ] && ARCH_PA="    <string>/usr/bin/arch</string>
    <string>-arm64</string>"
DEPS="fastapi,uvicorn,httpx,PIL,lunardate,jinja2,yaml,rumps"
PYR(){ "${ARCH[@]}" "$PY" "$@"; }   # 跑 venv python(强制原生架构)的统一入口
venv_ok(){ [ -x "$PY" ] && PYR -c "import $DEPS" >>"$LOG" 2>&1; }

# ---- osascript 小工具(注意:AppleScript 字符串不支持 \n 转义,文案一律写单行,dialog 会自动折行)----
notify(){ osascript -e "display notification \"$1\" with title \"墨水桌面看板\"" >/dev/null 2>&1; }
errbox(){ osascript -e "display dialog \"$1\" with title \"墨水桌面看板 · 安装出错\" buttons {\"好\"} default button 1 with icon stop" >/dev/null 2>&1; }
# 是/否询问:必须看"按钮文字",不能用退出码——display dialog 点"否"和"是"退出码都是 0。
ask(){ [ "$(osascript -e "button returned of (display dialog \"$1\" with title \"墨水桌面看板\" buttons {\"否\",\"是\"} default button 2)" 2>/dev/null)" = "是" ]; }
# 安装进度窗口:同一个窗口随步骤刷新(kill 旧的弹新的),让用户看到"第几步 / 在干嘛 / 下一步"。
STAGE_PID=""
# 进度窗口:$1=步骤(如"第 2 步 / 共 5 步")  $2=当前在做什么  $3=下一步(可空)。
# 用 AppleScript 的 return 拼真正的换行(分行排版);图标用我们的 .icns(不再是默认便签图标)。
stage(){
  [ -n "$STAGE_PID" ] && kill "$STAGE_PID" 2>/dev/null
  local body="\"$1\" & return & return & \"$2\""
  [ -n "$3" ] && body="$body & return & return & \"下一步:$3\""
  local ic=""
  [ -f "$ICON_ICNS" ] && ic="with icon (POSIX file \"$ICON_ICNS\")"
  osascript -e "display dialog $body with title \"墨水桌面看板 · 首次安装\" $ic buttons {\"在后台继续\"} default button 1 giving up after 900" >/dev/null 2>&1 &
  STAGE_PID=$!
  disown 2>/dev/null || true   # 让 bash 不追踪这个后台 job,kill 时不打印 "Terminated: 15" 噪音
}
stage_done(){ [ -n "$STAGE_PID" ] && kill "$STAGE_PID" 2>/dev/null; STAGE_PID=""; }
fail(){ echo "FAIL: $1" >>"$LOG"; stage_done; errbox "$1(详细日志:$LOG)"; exit 1; }

# ---- 幂等:已装、版本一致且 venv 健康 → 直接返回(launcher 负责把菜单栏拉起来)----
# 健康检查用 arm64 去 import:坏的 x86_64 venv 会被正确判为"坏"而重建,而不是误判健康直接 skip。
if [ -f "$STAMP" ]; then
  installed_ver="$(cat "$STAMP" 2>/dev/null)"
  if [ "$installed_ver" = "$APP_VERSION" ] && venv_ok; then
    echo "already installed ($installed_ver), venv healthy, skip" >>"$LOG"
    exit 0
  fi
  echo "re-bootstrap: version change or broken venv ($installed_ver -> $APP_VERSION)" >>"$LOG"
fi

[ -d "$APP_RES" ] || fail "找不到应用内的程序文件($APP_RES)。请重新下载安装包。"

# ---- 步骤 1/5:铺源码 ----
stage "第 1 步 / 共 5 步" "正在准备程序文件" "配置运行环境"
echo "==> copy source" >>"$LOG"
mkdir -p "$REPO"
if command -v rsync >/dev/null 2>&1; then
  rsync -a --delete --exclude '.venv' --exclude 'data' "$APP_RES"/ "$REPO"/ >>"$LOG" 2>&1 \
    || fail "复制程序文件失败。"
else
  cp -R "$APP_RES"/. "$REPO"/ >>"$LOG" 2>&1 || fail "复制程序文件失败。"
fi
mkdir -p "$REPO/data"

# ---- python3 ----
PY3="$(command -v python3 2>/dev/null)"
if [ -z "$PY3" ]; then
  stage_done
  errbox "需要先安装「命令行开发者工具」(Apple 官方组件,一次性)。点「好」后系统会弹出安装窗口,按提示装好后再次打开本应用即可。"
  xcode-select --install >/dev/null 2>&1 || true
  exit 1
fi
echo "python3: $("$PY3" --version 2>&1)" >>"$LOG"

# ---- 步骤 2/5:venv + 依赖(强制 arm64;坏环境自动重建;--no-cache 绕开污染缓存)----
echo "==> venv + deps (arch=${ARCH[*]:-native})" >>"$LOG"
if venv_ok; then
  stage "第 2 步 / 共 5 步" "正在检查运行环境" "检测浏览器引擎"
  echo "existing venv healthy, reuse" >>"$LOG"
else
  stage "第 2 步 / 共 5 步" "正在配置运行环境(下载并安装看板需要的程序库,约 1–3 分钟,这步最久)" "检测浏览器引擎"
  echo "building venv fresh" >>"$LOG"
  ensure_pip_index   # 测速选最快的 pip 源
  rm -rf "$VENV"
  "${ARCH[@]}" "$PY3" -m venv "$VENV" >>"$LOG" 2>&1 || fail "创建 Python 环境失败(详见日志)。"
  "${ARCH[@]}" "$PIP" install -q --upgrade -i "$PIP_IDX" pip >>"$LOG" 2>&1
  "${ARCH[@]}" "$PIP" install -q --no-cache-dir -i "$PIP_IDX" -r "$REPO/server/requirements.txt" >>"$LOG" 2>&1 \
    || fail "安装依赖失败,通常是网络问题。请联网后重新打开本应用。"
fi
venv_ok || fail "依赖校验失败(可能芯片架构不匹配,详见日志)。"

# ---- 步骤 3/5:渲染引擎 = chrome-headless-shell(macOS 渲染不弹 Dock)----
# 完整 Chrome 的 --headless=new 渲染时会让 Dock 周期抖动,所以即便系统装了 Chrome,也优先用专用无头壳;
# 已有无头壳(缓存里)就直接用、不下载;没有就自动下载(无需用户手动)。下载失败才退回系统 Chrome 兜底。
# 注意:PYR 带 arm64,否则 Rosetta 进程下 import 失败误判。
stage "第 3 步 / 共 5 步" "正在准备渲染引擎" ""
echo "==> render engine" >>"$LOG"
KIND="$(cd "$REPO" && PYR -c "from server.render.pipeline import find_chrome,is_headless_shell as s;c=find_chrome();print('SHELL' if c and s(c) else ('FULL' if c else 'NONE'))" 2>>"$LOG")"
echo "engine kind: $KIND" >>"$LOG"
if [ "$KIND" = "SHELL" ]; then
  echo "已有无头壳,直接用、不下载" >>"$LOG"
else
  # FULL(只有完整 Chrome,会弹 Dock)或 NONE(没引擎)→ 自动下载无头壳
  stage "第 3 步 / 共 5 步" "正在下载无头渲染引擎(约 100MB,避免 Dock 抖动)" ""
  if bash "$REPO/installers/macos/get-headless-shell.sh" >>"$LOG" 2>&1; then
    echo "chrome-headless-shell 下载就绪" >>"$LOG"
  elif [ "$KIND" = "FULL" ]; then
    echo "shell 下载失败,退回系统 Chrome(会弹 Dock)" >>"$LOG"
    errbox "无头渲染引擎下载失败,暂用系统 Chrome 渲染——看板能出图,但 Dock 会周期性闪一下。联网(国内可能需挂代理)后重开本应用会自动重试下载、消除抖动。"
  else
    errbox "渲染引擎下载失败,看板暂时无法出图。请联网(国内可能需挂代理)后重新打开本应用。"
  fi
fi

# ---- 配置(外置,升级/重装不丢)----
mkdir -p "$(dirname "$CONFIG")"
if [ ! -f "$CONFIG" ]; then
  cp "$REPO/config.example.yaml" "$CONFIG" && echo "config created: $CONFIG" >>"$LOG"
fi
PORT="$(PYR -c "import yaml;print((yaml.safe_load(open('$CONFIG')) or {}).get('server',{}).get('port',8585))" 2>/dev/null || echo 8585)"

# ---- 步骤 4/5:launchd 服务(开机自启 + 崩溃自重启)----
stage "第 4 步 / 共 5 步" "正在启动看板服务" "马上完成"
echo "==> launchd service" >>"$LOG"
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$PLIST_LABEL</string>
  <key>ProgramArguments</key>
  <array>
$ARCH_PA
    <string>$PY</string>
    <string>-m</string>
    <string>server.run</string>
  </array>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>KINDLE_CONFIG</key><string>$CONFIG</string>
    <key>PATH</key><string>/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$REPO/data/service.log</string>
  <key>StandardErrorPath</key><string>$REPO/data/service.log</string>
</dict>
</plist>
EOF
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load -w "$PLIST" >>"$LOG" 2>&1 || fail "启动服务失败(launchd 加载失败,详见日志)。"

# ---- 健康自检 ----
echo "==> health check" >>"$LOG"
OK=0
for i in $(seq 1 25); do
  if curl -s -m 2 "http://127.0.0.1:$PORT/health" 2>/dev/null | grep -q '"status":"ok"'; then OK=1; break; fi
  sleep 1
done
[ "$OK" = 1 ] || fail "服务在 25 秒内未响应。最近日志见 $REPO/data/service.log。常见原因:依赖缺失 / 端口 $PORT 被占用。"

# ---- 菜单栏 launchd(登录自启;arm64 起 venv python -m server.menubar)----
echo "==> launchd menubar" >>"$LOG"
cat > "$MB_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$MB_LABEL</string>
  <key>ProgramArguments</key>
  <array>
$ARCH_PA
    <string>$PY</string>
    <string>-m</string>
    <string>server.menubar</string>
  </array>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>KINDLE_CONFIG</key><string>$CONFIG</string>
    <key>PATH</key><string>/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$REPO/data/menubar.log</string>
  <key>StandardErrorPath</key><string>$REPO/data/menubar.log</string>
</dict>
</plist>
EOF
launchctl unload "$MB_PLIST" 2>/dev/null || true
launchctl load "$MB_PLIST" >>"$LOG" 2>&1 || echo "menubar load failed (non-fatal)" >>"$LOG"

# ---- 步骤 5/5:落地完成 ----
echo "$APP_VERSION" > "$STAMP"
echo "==== bootstrap done ====" >>"$LOG"
stage_done

# 设置页链接(带访问令牌)
TOKEN="$(PYR -c "import yaml;print((yaml.safe_load(open('$CONFIG')) or {}).get('server',{}).get('access_token','') or '')" 2>/dev/null || echo "")"
Q=""; [ -n "$TOKEN" ] && Q="?token=$TOKEN"
# 不发 osascript 通知(图标是系统脚本工具的,丑)。完成信号靠:状态栏出现蓝色图标 + 自动打开设置页。
open "http://localhost:$PORT/setup$Q" >/dev/null 2>&1 || true
exit 0
