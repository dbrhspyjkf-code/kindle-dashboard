#!/bin/bash
# Kindle Dashboard —— macOS 一键安装
# 装依赖(venv)、生成 config.yaml、装 launchd 开机自启、启动服务,并自检确认真的起来了。
# 用法:bash installers/macos/install.sh
# 不用 set -e:逐步显式检查,失败给中文指引,方便非技术用户。

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
VENV="$REPO/.venv"
PY="$VENV/bin/python"
PIP="$VENV/bin/pip"
PLIST_LABEL="com.kindle-dashboard"
PLIST="$HOME/Library/LaunchAgents/$PLIST_LABEL.plist"

die(){ echo "✗ $1"; exit 1; }

echo "==> 仓库目录:$REPO"
case "$REPO" in
  /Volumes/*) echo "⚠ 你在网络共享盘(/Volumes)上安装,Python 环境可能建不起来。";
              echo "  强烈建议先复制到本地盘:cp -R \"$REPO\" ~/kindle-dashboard && cd ~/kindle-dashboard";;
esac

# 1. Python3
command -v python3 >/dev/null 2>&1 || die "未找到 python3。请先装:brew install python(或 https://python.org)"
echo "✓ python3: $(python3 --version 2>&1)"

# 2. 渲染引擎检测移到依赖安装之后(可能用 playwright 自带 chromium,需先装好 playwright)

# 3. venv + 依赖
echo "==> 创建虚拟环境并安装依赖(首次约 1-2 分钟)..."
[ -d "$VENV" ] && [ ! -x "$PY" ] && rm -rf "$VENV"   # 清理上次失败的残留,保证重跑干净
python3 -m venv "$VENV" 2>/tmp/venv_err || {
  echo "venv 创建失败:"; cat /tmp/venv_err
  die "若代码放在网络盘(/Volumes)上,请先复制到本地盘:cp -R \"$REPO\" ~/kindle-dashboard,再到那边重装。"
}
"$PIP" install -q --upgrade pip 2>/dev/null
"$PIP" install -q -r "$REPO/server/requirements.txt" || die "依赖安装失败(检查网络)。可重跑本脚本。"
"$PY" -c "import fastapi,uvicorn,httpx,PIL,lunardate,jinja2,yaml" 2>/dev/null || die "依赖导入校验失败,请把上面输出贴给我。"
echo "✓ 依赖就绪"

# 3b. 渲染引擎 = chrome-headless-shell(macOS 渲染不弹 Dock;完整 Chrome 的 --headless=new 会让 Dock 周期抖动)
echo "==> 检测渲染引擎..."
KIND=$(cd "$REPO" && "$PY" -c "from server.render.pipeline import find_chrome,is_headless_shell as s;c=find_chrome();print('SHELL' if c and s(c) else ('FULL' if c else 'NONE'))" 2>/dev/null)
if [ "$KIND" = "SHELL" ]; then
  echo "✓ 渲染引擎就绪(chrome-headless-shell,不弹 Dock)"
else
  if [ "$KIND" = "FULL" ]; then
    echo "已装完整 Chrome,但它渲染时会让 macOS Dock 周期性闪图标。"
  else
    echo "未检测到渲染引擎。"
  fi
  echo "建议用专用无头壳 chrome-headless-shell(约 100MB,不弹 Dock、更轻)。"
  printf "现在下载?[Y/n] "
  read -r ans
  case "$ans" in
    [Nn]*) [ "$KIND" = "FULL" ] && echo "⚠ 跳过。将用系统 Chrome 渲染,Dock 会周期闪一下(可重跑本脚本下载消除)。" \
                                || echo "⚠ 跳过。当前没有渲染引擎,看板无法出图,直到你下载或装 Chrome。" ;;
    *) bash "$REPO/installers/macos/get-headless-shell.sh" && echo "✓ 无头引擎就绪" \
         || echo "⚠ 下载失败(国内访问 Google 慢/不通时先 export https_proxy=http://代理:端口),可稍后重跑本脚本。" ;;
  esac
fi

# 4. config.yaml —— 外置到仓库外(~/.config/kindle-dashboard/),升级/重装/删库重拉都不丢配置。
CONFIG="${KINDLE_CONFIG:-$HOME/.config/kindle-dashboard/config.yaml}"
mkdir -p "$(dirname "$CONFIG")"
if [ -f "$CONFIG" ]; then
  echo "✓ 配置已存在,保留:$CONFIG"
elif [ -f "$REPO/config.yaml" ]; then
  cp "$REPO/config.yaml" "$CONFIG" && echo "✓ 已把仓库内旧 config.yaml 迁移到 $CONFIG(以后不再丢)"
else
  cp "$REPO/config.example.yaml" "$CONFIG" && echo "✓ 已生成配置(从示例):$CONFIG"
fi
mkdir -p "$REPO/data"

PORT=$("$PY" -c "import yaml;print((yaml.safe_load(open('$CONFIG')) or {}).get('server',{}).get('port',8585))" 2>/dev/null || echo 8585)

# 4b. AI 用量统计(可选)—— 询问 + 自动检测/安装 Node + ccusage(Node 不再问用户)
echo
echo "【可选】AI 用量统计:读本机 Claude Code / Codex 的本地日志,在看板上显示每日 token 与花费。"
printf "是否启用?(会自动检测/安装 Node + ccusage,无需你手动)[y/N] "
read -r ai_ans
case "$ai_ans" in
  [Yy]*)
    NODE_BIN=$(command -v node 2>/dev/null || true)
    [ -z "$NODE_BIN" ] && [ -x "$REPO/.node/bin/node" ] && NODE_BIN="$REPO/.node/bin/node"
    if [ -z "$NODE_BIN" ]; then
      echo "  未检测到 Node,自动安装..."
      if command -v brew >/dev/null 2>&1; then
        brew install node >/dev/null 2>&1 && NODE_BIN=$(command -v node 2>/dev/null)
      else
        NV="v20.18.1"; [ "$(uname -m)" = "arm64" ] && NA="arm64" || NA="x64"
        echo "  下载 Node $NV ($NA) 到项目本地..."
        mkdir -p "$REPO/.node"
        curl -fsSL "https://nodejs.org/dist/$NV/node-$NV-darwin-$NA.tar.gz" \
          | tar -xz -C "$REPO/.node" --strip-components=1 && NODE_BIN="$REPO/.node/bin/node"
      fi
    fi
    if [ -n "$NODE_BIN" ] && [ -x "$NODE_BIN" ]; then
      echo "  ✓ Node: $($NODE_BIN --version 2>&1)"
      NDIR="$(dirname "$NODE_BIN")"
      CCUSAGE_PATH=$(PATH="$NDIR:$REPO/.node/bin:/usr/local/bin:/opt/homebrew/bin:$HOME/.npm-global/bin:$PATH" command -v ccusage 2>/dev/null || true)
      if [ -n "$CCUSAGE_PATH" ]; then
        echo "  ✓ ccusage: $($CCUSAGE_PATH --version 2>&1) ($CCUSAGE_PATH)"
      else
        NPM_BIN="$NDIR/npm"
        [ -x "$NPM_BIN" ] || NPM_BIN=$(PATH="$NDIR:$PATH" command -v npm 2>/dev/null || true)
        if [ -n "$NPM_BIN" ] && [ -x "$NPM_BIN" ]; then
          CCUSAGE_LOG="$REPO/data/ccusage-install.log"
          echo "  未检测到 ccusage,开始安装..."
          if PATH="$NDIR:$PATH" "$NPM_BIN" install -g ccusage >"$CCUSAGE_LOG" 2>&1; then
            CCUSAGE_PATH=$(PATH="$NDIR:$REPO/.node/bin:/usr/local/bin:/opt/homebrew/bin:$HOME/.npm-global/bin:$PATH" command -v ccusage 2>/dev/null || true)
            echo "  ✓ ccusage 已装${CCUSAGE_PATH:+:$CCUSAGE_PATH}"
          else
            echo "  ⚠ ccusage 安装失败(可稍后 npm i -g ccusage)"
            echo "    日志:$CCUSAGE_LOG"
          fi
        else
          echo "  ⚠ 未找到 npm,无法自动安装 ccusage(可稍后安装 Node/npm 后重跑)"
        fi
      fi
      "$PY" - <<PYEOF
import yaml
p = "$CONFIG"
c = yaml.safe_load(open(p, encoding="utf-8")) or {}
c.setdefault("ai_usage", {})["enabled"] = True
yaml.safe_dump(c, open(p, "w", encoding="utf-8"), allow_unicode=True, sort_keys=False)
PYEOF
      echo "  ✓ 已启用 AI 用量(服务起来会自动读 ccusage 数据)"
    else
      echo "  ⚠ Node 安装失败,跳过 AI 用量(可稍后手动装 node + ccusage 再重跑)"
    fi ;;
  *) echo "  跳过 AI 用量(以后在设置页开启 ai_usage 或重跑本脚本即可)" ;;
esac

# 4c. 本机性能监控(可选)—— 在「设备」页显示这台 Mac 的 CPU/内存/磁盘(local 直读,零额外安装)
echo
echo "【可选】本机性能监控:在看板「设备」页显示这台 Mac 的 CPU / 内存 / 磁盘。"
printf "是否启用?[y/N] "
read -r dev_ans
case "$dev_ans" in
  [Yy]*)
    printf "  多久采集一次(秒)?[默认 30] "
    read -r dev_int
    case "$dev_int" in ''|*[!0-9]*) dev_int=30;; esac
    [ "$dev_int" -lt 5 ] 2>/dev/null && dev_int=30
    DEV_NAME=$(scutil --get LocalHostName 2>/dev/null || hostname 2>/dev/null || echo "这台Mac")
    "$PY" - "$CONFIG" "$DEV_NAME" "$dev_int" <<'PYEOF'
import sys, yaml
p, name, interval = sys.argv[1], sys.argv[2], int(sys.argv[3])
c = yaml.safe_load(open(p, encoding="utf-8")) or {}
dev = c.setdefault("devices", {})
machines = dev.setdefault("machines", []) or []
# 幂等:已有 local 设备就不重复加(重跑安装不叠加)
if not any((m or {}).get("mode") == "local" for m in machines):
    machines.append({"name": name, "mode": "local", "platform": "auto"})
dev["machines"] = machines
dev["interval"] = interval
yaml.safe_dump(c, open(p, "w", encoding="utf-8"), allow_unicode=True, sort_keys=False)
PYEOF
    echo "  ✓ 已启用本机性能监控($DEV_NAME,每 ${dev_int} 秒采集)" ;;
  *) echo "  跳过本机性能监控(以后在设置页「设备监控」加一台『本机直读』设备即可)" ;;
esac

# 5. launchd 开机自启
echo "==> 安装 launchd 服务(端口 $PORT)..."
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$PLIST_LABEL</string>
  <key>ProgramArguments</key>
  <array>
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
launchctl load -w "$PLIST" 2>/tmp/lc_err || { echo "launchctl 输出:"; cat /tmp/lc_err; die "launchd 加载失败。"; }

# 6. 健康自检 —— 确认服务真的起来了(不只是注册了)
echo "==> 等待服务启动并自检..."
OK=0
for i in $(seq 1 20); do
  if curl -s -m 2 "http://127.0.0.1:$PORT/health" 2>/dev/null | grep -q '"status":"ok"'; then OK=1; break; fi
  sleep 1
done

if [ "$OK" != 1 ]; then
  echo "✗ 服务在 20 秒内未响应。最近日志:"
  echo "----------------------------------------------------------------"
  tail -25 "$REPO/data/service.log" 2>/dev/null || echo "(暂无日志)"
  echo "----------------------------------------------------------------"
  echo "把上面日志贴给我排查。常见:依赖缺失 / 端口 $PORT 被占用。"
  exit 1
fi

# 6b. 提醒事项同步(可选)—— 交互询问;选「是」则一键装(配置+agent+前台触发授权)
#     生命周期由 enable/disable 脚本管理,以后想加/想撤都能在设置页复制命令自己跑,无需重跑整个安装。
echo
echo "【可选】提醒事项同步:把本机「提醒事项」App(含 iPhone 经 iCloud 同步过来的)显示到看板上。"
printf "是否启用?(需要会请求一次「访问提醒事项」授权)[y/N] "
read -r rem_ans
case "$rem_ans" in
  [Yy]*)
    bash "$REPO/installers/macos/enable_reminders.sh"
    ;;
  *)
    echo "  跳过提醒事项(以后想加:在设置页复制那行命令,在终端运行 enable_reminders.sh 即可,不必重装)"
    ;;
esac

# 6c. AI 额度(可选)—— Claude 5h/周 + Codex 5h/周 额度上报(push:Claude 走 statusLine,Codex 走 launchd)
echo
echo "【可选】AI 额度:在看板 AI 页显示 Claude / Codex 的「5 小时 & 周额度」用量%(需在本机用 Claude Code / Codex CLI)。"
printf "是否启用?[y/N] "
read -r quota_ans
case "$quota_ans" in
  [Yy]*)
    printf "  Codex 额度多久上报一次?(秒,≥60,回车默认 600)[600] "
    read -r q_int
    if echo "$q_int" | grep -q '^[0-9][0-9]*$' && [ "$q_int" -ge 60 ]; then
      "$PY" - <<PYEOF
import yaml
p = "$CONFIG"
c = yaml.safe_load(open(p, encoding="utf-8")) or {}
c.setdefault("ai_usage", {})["codex_quota_interval"] = $q_int
yaml.safe_dump(c, open(p, "w", encoding="utf-8"), allow_unicode=True, sort_keys=False)
PYEOF
      echo "  ✓ Codex 上报间隔设为 ${q_int}s"
    fi
    bash "$REPO/installers/macos/enable_quota.sh"
    ;;
  *)
    echo "  跳过 AI 额度(以后想加:终端跑 installers/macos/enable_quota.sh 即可,不必重装)"
    ;;
esac

# 7. 菜单栏程序(登录自启 + 立即启动;失败不影响主服务)
echo "==> 安装菜单栏程序..."
MB_LABEL="com.kindle-dashboard.menubar"
MB_PLIST="$HOME/Library/LaunchAgents/$MB_LABEL.plist"
MB_APP="$REPO/data/Kindle Dashboard Menu.app"
MB_EXEC="$MB_APP/Contents/MacOS/KindleDashboardMenu"
# 兜底:老环境的 venv 可能没装 rumps(早期 requirements 没它)→ 自动补,免得菜单栏静默缺失
"$PY" -c "import rumps" 2>/dev/null || { echo "  补装菜单栏依赖 rumps..."; "$PIP" install -q rumps 2>/dev/null; }
if "$PY" -c "import rumps" 2>/dev/null; then
  rm -rf "$MB_APP"
  mkdir -p "$MB_APP/Contents/MacOS"
  cat > "$MB_APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key><string>zh_CN</string>
  <key>CFBundleDisplayName</key><string>Kindle Dashboard</string>
  <key>CFBundleExecutable</key><string>KindleDashboardMenu</string>
  <key>CFBundleIdentifier</key><string>$MB_LABEL</string>
  <key>CFBundleName</key><string>Kindle Dashboard</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSUIElement</key><true/>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
EOF
  cat > "$MB_EXEC" <<EOF
#!/bin/bash
cd "$REPO" || exit 1
export KINDLE_CONFIG="$CONFIG"
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin"
exec "$PY" -m server.menubar
EOF
  chmod +x "$MB_EXEC"
  cat > "$MB_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$MB_LABEL</string>
  <key>ProgramArguments</key>
  <array><string>$MB_EXEC</string></array>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>EnvironmentVariables</key><dict><key>KINDLE_CONFIG</key><string>$CONFIG</string></dict>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$REPO/data/menubar.log</string>
  <key>StandardErrorPath</key><string>$REPO/data/menubar.log</string>
</dict>
</plist>
EOF
  launchctl unload "$MB_PLIST" 2>/dev/null || true
  if launchctl load "$MB_PLIST" 2>/dev/null; then echo "✓ 菜单栏程序已启动(顶部状态栏显示 Kindle 小图标)"; else echo "⚠ 菜单栏启动失败(不影响看板服务)"; fi
else
  echo "⚠ 未装 rumps,跳过菜单栏(不影响看板服务;可 $PIP install rumps 后重跑)"
fi

# 8. 成功,打印地址
get_ip(){ for i in en0 en1 en2 en3 en4; do ip=$(ipconfig getifaddr $i 2>/dev/null); [ -n "$ip" ] && { echo "$ip"; return; }; done; }
IP=$(get_ip)
# 读访问令牌(服务首次启动自动生成,写进 config.yaml);设置页链接带上它才能打开
TOKEN=$("$PY" -c "import yaml;print((yaml.safe_load(open('$CONFIG')) or {}).get('server',{}).get('access_token','') or '')" 2>/dev/null || echo "")
Q=""; [ -n "$TOKEN" ] && Q="?token=$TOKEN"
echo "✓ 服务已启动并自检通过(开机自启已设置)"
echo
echo "================================================================"
echo "  ✅ 安装完成!打开设置页配置你的看板(链接含访问令牌,请收藏):"
echo "      http://localhost:$PORT/setup$Q"
[ -n "$TOKEN" ] && echo "  🔑 访问令牌:$TOKEN(同 WiFi 别人没它进不了设置页;Kindle 拉图不受影响)"
if [ -n "$IP" ]; then
  echo "  局域网访问 / Kindle 拉图地址用这个 IP($IP):"
  echo "      设置页:        http://$IP:$PORT/setup$Q"
  echo "      Kindle 拉图地址:http://$IP:$PORT/kindle/frame.png"
else
  echo "  (未自动取到局域网 IP,配 Kindle 时用:系统设置→网络 里看本机 IP)"
fi
echo "================================================================"
