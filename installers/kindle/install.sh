#!/bin/sh
# Kindle 一键配置:推送 start/stop 脚本、写服务地址、装开机自启、启动显示。
# 在主机(Mac/Linux)运行。Kindle 需已越狱 + 已开 USBNetwork(SSH)。
# 用法:sh installers/kindle/install.sh [KINDLE_IP] [SERVER_URL] [INTERVAL]
#   KINDLE_IP   默认 192.168.15.244(USBNetwork)
#   SERVER_URL  默认自动探测本机 IP:8585
#   INTERVAL    Kindle 拉图刷新间隔(秒);不给则交互询问,非交互默认 20
set -e
KDIR="$(cd "$(dirname "$0")" && pwd)"
# --wait:循环等 Kindle SSH(22)就绪再刷,用来"抓开机/重连那一刻的窗口"
# (看板占屏会把 SSH 关掉,但 Kindle 重启的开机瞬间 SSH 是通的——这个模式守在那里自动抓住)。
WAIT=""
[ "$1" = "--wait" ] && { WAIT=1; shift; }
KINDLE_IP="${1:-192.168.15.244}"
SERVER_URL="$2"
INTERVAL="$3"

# 自动探测服务地址(本机局域网 IP)
if [ -z "$SERVER_URL" ]; then
  case "$(uname)" in
    Darwin) IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null) ;;
    *)      IP=$(hostname -I 2>/dev/null | awk '{print $1}') ;;
  esac
  SERVER_URL="http://${IP:-127.0.0.1}:8585"
fi
echo "Kindle: $KINDLE_IP    服务地址: $SERVER_URL"

# Kindle 拉图刷新间隔(秒):第三参数优先,否则交互询问,非 tty 默认 20。
# 注意:这是 Kindle 端"多久拉一张新图"(写进 dashboard.conf,刷机时定,网页改不了);
#       与服务端"页面轮播间隔"(page_interval,网页可配)是两回事。
ask_interval() {
  if [ -n "$INTERVAL" ]; then
    if echo "$INTERVAL" | grep -q '^[0-9][0-9]*$' && [ "$INTERVAL" -ge 5 ]; then return; fi
    echo "  (刷新间隔参数无效,改用默认 20)"; INTERVAL=20; return
  fi
  if [ -t 0 ]; then
    echo "==> Kindle 多久拉一次新图?越短越实时、越费电。常用 10/20/30/60,回车默认 20。"
    printf "    刷新间隔(秒) [20]: "
    read ans 2>/dev/null || ans=""
    if echo "$ans" | grep -q '^[0-9][0-9]*$' && [ "$ans" -ge 5 ]; then
      INTERVAL="$ans"
    else
      [ -n "$ans" ] && echo "    (输入无效,用默认 20)"
      INTERVAL=20
    fi
  else
    INTERVAL=20
  fi
}
ask_interval
echo "   刷新间隔:${INTERVAL}s"

# 备用 .local(mDNS)地址已移除:
#   ① 它只对"服务跑在本机"成立,服务在 NAS 上时算的是本机(Mac)名字,完全是错的;
#   ② 主流越狱 Kindle(busybox)根本解析不了 .local。
# 取而代之:看板服务所在那台机器的 IP 务必固定(见脚本结尾的提示)。
SERVER_URL_ALT=""

# USB 模式:自动给本机 USB 网卡配同网段 IP,最终用户无需手动 ifconfig(真·一键)
ensure_usb_route() {
  [ "$KINDLE_IP" = "192.168.15.244" ] || return 0          # 仅 USBNetwork 标准地址才需要
  ping -c1 -t2 "$KINDLE_IP" >/dev/null 2>&1 && return 0     # 已通则跳过(幂等)
  echo "==> USB 网络未通,自动配置本机 USB 接口(等待接口就绪,最多 ~12 秒)..."
  case "$(uname)" in
    Darwin)
      n=0
      while [ $n -lt 6 ]; do
        for ifc in $(ifconfig -l 2>/dev/null | tr ' ' '\n' | grep '^en'); do
          if ifconfig "$ifc" 2>/dev/null | grep -q "inet 169.254"; then
            echo "   检测到 Kindle USB 接口 $ifc,配 192.168.15.201(可能需 sudo 密码)"
            echo "   (仅给这块 Kindle USB 网卡临时配地址,不影响你的 WiFi/上网;拔线或重启即自动恢复,无需手动还原)"
            sudo ifconfig "$ifc" 192.168.15.201 255.255.255.0 || true
            sleep 1
            ping -c1 -t2 "$KINDLE_IP" >/dev/null 2>&1 && { echo "   ✓ USB 网络已通"; return 0; }
          fi
        done
        n=$((n + 1)); sleep 2
      done ;;
    *) echo "   (非 macOS,请手动把 USB 网络接口配为 192.168.15.201/24)" ;;
  esac
  return 1
}
ensure_usb_route || echo "⚠ USB 网络仍未通;若改用 WiFi:install.sh <KindleWiFiIP> http://<MacIP>:8585"

# 复用 SSH 连接,只输一次密码
CP="/tmp/kindle-ctl-%r@%h:%p"
SSHOPT="-o StrictHostKeyChecking=no -o ControlMaster=auto -o ControlPath=$CP -o ControlPersist=120"
echo "提示:接下来会要求输入 Kindle 的 root 密码(越狱后的 SSH 密码)。"
echo "      越狱包常见默认密码是 mario;若你改过,请用你设的密码。"
if [ -n "$WAIT" ]; then
  echo "==> 等待模式:每 5 秒探测 Kindle SSH(22),就绪即自动开刷。"
  echo "    现在去【重启 Kindle】——开机那一刻 SSH 一通,这里就抓到并开始刷。(Ctrl-C 取消)"
  while ! { nc -z -G 3 "$KINDLE_IP" 22 2>/dev/null || nc -z -w 3 "$KINDLE_IP" 22 2>/dev/null; }; do
    printf "\r    %s 等 Kindle SSH 就绪…  " "$(date +%H:%M:%S)"
    sleep 5
  done
  echo ""; echo "   ✓ Kindle SSH 就绪,开始刷入(接下来输一次密码 mario)"
fi
ssh $SSHOPT root@"$KINDLE_IP" "echo connected" || { echo "✗ 无法 SSH 到 Kindle,先跑 detect.sh 排查"; exit 1; }

echo "==> 备份旧版(若有)..."
ssh $SSHOPT root@"$KINDLE_IP" "
  if [ -f /mnt/us/start.sh ] || [ -f /mnt/us/stop.sh ]; then
    mkdir -p /mnt/us/kindle-dash-backup
    cp /mnt/us/start.sh /mnt/us/kindle-dash-backup/ 2>/dev/null
    cp /mnt/us/stop.sh  /mnt/us/kindle-dash-backup/ 2>/dev/null
    cp /etc/crontab/root /mnt/us/kindle-dash-backup/crontab.root 2>/dev/null
    echo '  ✓ 旧 start.sh/stop.sh/crontab 已备份到 /mnt/us/kindle-dash-backup/'
  else echo '  (无旧版,跳过)'; fi
"

echo "==> 推送脚本..."
scp $SSHOPT "$KDIR/start.sh" "$KDIR/stop.sh" root@"$KINDLE_IP":/mnt/us/

echo "==> 写配置、装自启、启动..."
ssh $SSHOPT root@"$KINDLE_IP" "
  echo 'SERVER_URL=$SERVER_URL' > /mnt/us/dashboard.conf
  echo 'SERVER_URL_ALT=$SERVER_URL_ALT' >> /mnt/us/dashboard.conf
  echo 'INTERVAL=$INTERVAL' >> /mnt/us/dashboard.conf
  chmod +x /mnt/us/start.sh /mnt/us/stop.sh
  /usr/sbin/mntroot rw 2>/dev/null || true
  grep -v '/mnt/us/start.sh' /etc/crontab/root > /tmp/cr.tmp 2>/dev/null && mv /tmp/cr.tmp /etc/crontab/root
  echo '@reboot sleep 30 && /mnt/us/start.sh # kindle-dashboard' >> /etc/crontab/root
  /usr/sbin/mntroot ro 2>/dev/null || true
  command -v fbink >/dev/null 2>&1 || echo 'WARN: 未找到 fbink,刷屏会失败 —— 请通过 KUAL/越狱工具安装 fbink 后重跑'
  setsid /mnt/us/start.sh < /dev/null > /mnt/us/dashboard.log 2>&1 &
  echo started
"

# 关闭复用连接
ssh $SSHOPT -O exit root@"$KINDLE_IP" 2>/dev/null || true

echo "✓ 完成。Kindle 应开始显示看板(横放摆,顶边朝右)。"
echo "  之后改配置在网页保存即可,Kindle 侧不用再碰。"
echo
echo "⚠ 重要:Kindle 是按固定地址 $SERVER_URL 拉图的——【看板服务所在那台机器】的 IP 一旦变,Kindle 就拉不到图、看板停更。请把它固定:"
echo "  • 服务在 NAS / 常开主机:去路由器给它的 MAC 绑定一个固定 IP(DHCP 保留地址),或在那台机器上设静态 IP。一次到位、最稳。"
echo "  • 服务在 Mac:Mac 的 IP 老变多半是 Apple『私有 Wi-Fi 地址』在轮替 MAC → 系统设置→Wi-Fi→当前网络『详细信息』→『私有 Wi-Fi 地址』改成『固定』(想更稳再去路由器绑 IP)。"
echo "  IP 真变了:重跑本命令、SERVER_URL 换成新地址即可。"
echo
echo "🛟 救命开关(防变砖):万一看板占了屏又连不上(没开 USBNetwork、WiFi 也没连),"
echo "   把 Kindle 插任意电脑(默认是 U 盘模式,不需要 USBNetwork/WiFi),在盘根目录新建一个空文件"
echo "   叫 dashboard.off,重启 Kindle 就回到正常界面;删掉它恢复看板。"
echo
echo "  不想用了:sh installers/kindle/uninstall.sh $KINDLE_IP"
