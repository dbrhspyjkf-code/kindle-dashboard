#!/bin/bash
# 墨水桌面看板 —— 在 Mac 上把仓库打包成「安装器 .dmg」。
# 只用 macOS 自带工具(sips/iconutil/codesign/hdiutil),无需 Xcode 完整环境、无需 py2app。
# 用法:bash installers/macos/build-mac-app.sh [版本号]
#   版本号 默认 1.0;会写进 Info.plist 与 .app 内 APP_VERSION(供菜单栏「检查更新」比对)。
# 产物:work/mac/墨水桌面看板-<版本>.dmg
#
# ⚠ 本次不签名(决策):用户首次打开需在「系统设置→隐私与安全性→仍要打开」放行一次。
#   若以后买了 Apple 开发者账号,设 DEVELOPER_ID="Developer ID Application: 名字 (TEAMID)" 再跑本脚本即自动签名+公证。
set -e

VERSION="${1:-1.0}"
APP_NAME="墨水桌面看板"
BUNDLE_ID="com.kindle-dashboard.app"

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="$REPO/work/mac"                                  # 最终 .dmg 输出(在 NAS/SMB 上也行,只是个普通文件)
# ⚠ 工作区常在 SMB 网络盘(NAS)上,直接在上面拼 .app 会丢 Unix 执行权限 → App 打不开。
#   所以在 Mac 本地盘的临时目录组装,只把最终 .dmg 写回 OUT。
BUILD="$(mktemp -d "${TMPDIR:-/tmp}/moshui-build.XXXXXX")"
trap 'rm -rf "$BUILD"' EXIT
APPDIR="$BUILD/$APP_NAME.app"
CONTENTS="$APPDIR/Contents"
RES="$CONTENTS/Resources"
APPSRC="$RES/app"                       # 打进包的源码子集

[ "$(uname)" = "Darwin" ] || { echo "✗ 只能在 Mac 上构建(需 sips/iconutil/hdiutil)。"; exit 1; }

echo "==> 准备目录(本地盘组装,规避 SMB 权限坑)"
mkdir -p "$OUT" "$CONTENTS/MacOS" "$APPSRC"

echo "==> 拷贝源码子集(server/styles/web/installers + 示例配置)"
for d in server styles web installers; do
  rsync -a --exclude '__pycache__' --exclude '*.pyc' --exclude '.venv' "$REPO/$d" "$APPSRC/"
done
cp "$REPO/config.example.yaml" "$APPSRC/"
echo "$VERSION" > "$APPSRC/APP_VERSION"

echo "==> 写 Info.plist"
cat > "$CONTENTS/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key><string>zh_CN</string>
  <key>CFBundleDisplayName</key><string>$APP_NAME</string>
  <key>CFBundleName</key><string>$APP_NAME</string>
  <key>CFBundleExecutable</key><string>launcher</string>
  <key>CFBundleIdentifier</key><string>$BUNDLE_ID</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundleVersion</key><string>$VERSION</string>
  <key>LSMinimumSystemVersion</key><string>10.15</string>
  <key>LSUIElement</key><true/>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
EOF

echo "==> 写 launcher(双击入口:首启 bootstrap,之后确保菜单栏在跑)"
cat > "$CONTENTS/MacOS/launcher" <<'EOF'
#!/bin/bash
# .app 可执行体:首次/版本变更跑 bootstrap;然后确保菜单栏 agent 在运行。
DIR="$(cd "$(dirname "$0")" && pwd)"
RES="$DIR/../Resources/app"
VER="$(cat "$RES/APP_VERSION" 2>/dev/null || echo 0)"
bash "$RES/installers/macos/bootstrap.sh" "$RES" "$VER"
rc=$?
MB="$HOME/Library/LaunchAgents/com.kindle-dashboard.menubar.plist"
if [ "$rc" -eq 0 ] && [ -f "$MB" ]; then
  launchctl load "$MB" 2>/dev/null || true
  launchctl kickstart "gui/$(id -u)/com.kindle-dashboard.menubar" 2>/dev/null || true
fi
exit 0
EOF
chmod +x "$CONTENTS/MacOS/launcher"

echo "==> 生成图标 AppIcon.icns"
SRC_PNG="$REPO/installers/macos/appicon-1024.png"
[ -f "$SRC_PNG" ] || { echo "✗ 缺图标源 $SRC_PNG"; exit 1; }
ICONSET="$BUILD/AppIcon.iconset"
mkdir -p "$ICONSET"
gen(){ sips -z "$1" "$1" "$SRC_PNG" --out "$ICONSET/$2" >/dev/null; }
gen 16   icon_16x16.png;     gen 32   icon_16x16@2x.png
gen 32   icon_32x32.png;     gen 64   icon_32x32@2x.png
gen 128  icon_128x128.png;   gen 256  icon_128x128@2x.png
gen 256  icon_256x256.png;   gen 512  icon_256x256@2x.png
gen 512  icon_512x512.png;   gen 1024 icon_512x512@2x.png
iconutil -c icns "$ICONSET" -o "$RES/AppIcon.icns"

echo "==> 签名"
if [ -n "$DEVELOPER_ID" ]; then
  echo "   用 Developer ID 签名:$DEVELOPER_ID"
  codesign --force --deep --options runtime --sign "$DEVELOPER_ID" "$APPDIR"
  echo "   ⓘ 如需公证:xcrun notarytool submit <dmg> --keychain-profile <profile> --wait,然后 xcrun stapler staple <dmg>"
else
  echo "   未设 DEVELOPER_ID → ad-hoc 签名(不公证;用户首开需在系统设置放行一次)"
  codesign --force --deep --sign - "$APPDIR" 2>/dev/null || true
fi

# 先装到 /Applications(若开关开)——放在 dmg 之前,保证即使 dmg 失败 App 也已装好可验证。
if [ "$INSTALL_TO_APPLICATIONS" = "1" ]; then
  echo "==> 安装到 /Applications(覆盖旧版)"
  rm -rf "/Applications/$APP_NAME.app"
  cp -R "$APPDIR" "/Applications/$APP_NAME.app"
  # 自动启动一次:触发 bootstrap 更新代码 + 重启状态栏(否则旧状态栏进程不会自己换新)。
  open "/Applications/$APP_NAME.app" 2>/dev/null || true
  echo "   ✓ 已装好并启动。状态栏图标会刷新到新版。"
fi

# 打 .dmg(分发用)。在本地盘生成再拷回 OUT —— hdiutil 直接往 SMB 网络盘写会失败(资源暂时不可用)。
# SKIP_DMG=1 可跳过(只装不打包,迭代更快)。dmg 失败不致命:上面的安装已完成。
DMG="(本次未生成)"
if [ "$SKIP_DMG" = "1" ]; then
  echo "==> 跳过 .dmg(SKIP_DMG=1)"
else
  echo "==> 打 .dmg(本地生成→拷回 NAS,失败不影响已安装的 App)"
  STAGE="$BUILD/dmg"
  rm -rf "$STAGE"; mkdir -p "$STAGE"
  cp -R "$APPDIR" "$STAGE/"
  ln -s /Applications "$STAGE/Applications"
  LOCAL_DMG="$BUILD/$APP_NAME-$VERSION.dmg"
  if hdiutil create -volname "$APP_NAME" -srcfolder "$STAGE" -ov -format UDZO "$LOCAL_DMG" >/dev/null 2>&1; then
    mkdir -p "$OUT"
    if cp -f "$LOCAL_DMG" "$OUT/$APP_NAME-$VERSION.dmg" 2>/dev/null; then
      DMG="$OUT/$APP_NAME-$VERSION.dmg"; echo "   ✓ $DMG"
    else
      echo "   ⚠ 复制到 $OUT 失败(网络盘?);dmg 暂在本地,稍后可手动拷:$LOCAL_DMG"
      DMG="$LOCAL_DMG(本地临时,脚本结束会清,需要请手动保存)"
    fi
  else
    echo "   ⚠ 打 dmg 失败(常见于输出在网络盘);不影响已安装的 App,可重试或用 INSTALL_TO_APPLICATIONS=1 直接装。"
  fi
fi

echo
echo "================================================================"
if [ "$INSTALL_TO_APPLICATIONS" = "1" ]; then
  echo "  ✅ 已安装到 /Applications,直接双击「$APP_NAME」即可。"
fi
echo "  📦 分发包(.dmg):$DMG"
echo "  分发:作为附件传到 GitHub Release(与安卓 .apk 同一个 Release)。"
echo "  首开未签名提示:右键『打开』或 系统设置→隐私与安全性→仍要打开(一次即可)。"
echo "================================================================"
