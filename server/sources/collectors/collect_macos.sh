#!/bin/sh
# macOS 指标采集 —— 输出统一 JSON(字段同 collect_linux.sh)。
# 基于 top/vm_stat/sysctl/netstat/df 标准命令。⚠️ 待真机(macOS)验证。
# 磁盘 IO 速率 macOS 解析复杂,暂置 0(TODO);cpu/mem/net/分区 已实现。
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
SLEEP="${COLLECT_INTERVAL:-1}"

# CPU:top -l 2 取第二次采样的 idle(第一次不准)
idle=$(top -l 2 -n 0 -s "$SLEEP" 2>/dev/null | awk '/CPU usage/{i=$7} END{gsub("%","",i); print i}')
cpu=$(awk -v i="${idle:-100}" 'BEGIN{printf "%d", 100 - i}')

# 内存:active + wired + compressed
ps=$(sysctl -n hw.pagesize); mt=$(sysctl -n hw.memsize)
vm=$(vm_stat)
active=$(echo "$vm" | awk '/Pages active/{gsub("\\.","",$3); print $3}')
wired=$(echo "$vm"  | awk '/Pages wired/{gsub("\\.","",$4); print $4}')
comp=$(echo "$vm"   | awk '/occupied by compressor/{gsub("\\.","",$5); print $5}')
mu=$(awk -v a="${active:-0}" -v w="${wired:-0}" -v c="${comp:-0}" -v p="$ps" 'BEGIN{printf "%.0f", (a+w+c)*p}')

# 网络:netstat -nib 两次采样,累加各接口(去重接口名,排除 lo)
read_net() {
  netstat -nib | awk '!seen[$1]++ && $1!~/^lo/ && $7 ~ /^[0-9]+$/ {rx+=$7; tx+=$10} END{printf "%.0f %.0f\n", rx, tx}'
}
set -- $(read_net); rx1=$1; tx1=$2
sleep "$SLEEP"
set -- $(read_net); rx2=$1; tx2=$2
nrx=$(( (rx2 - rx1) / SLEEP )); [ "$nrx" -lt 0 ] && nrx=0
ntx=$(( (tx2 - tx1) / SLEEP )); [ "$ntx" -lt 0 ] && ntx=0

# 分区(macOS APFS):一块物理盘被切成多个共享同一容器的卷(只读系统卷 / 数据卷 / VM /
# Preboot…)。别用 df 列所有 /dev/ 卷——"总存储"会读成只读系统卷的 ~12G、严重偏低,还混进
# VM/Preboot/外接盘/网络盘/TimeMachine 快照噪音。
# 取数据卷(/System/Volumes/Data;老系统回退 /):容量=容器大小($2),已用=该卷 Used 列($3)——
# 与系统"关于本机→储存"口径一致。⚠ 别用 total-avail:那会把 macOS 的【可清除空间】
# (TimeMachine 本地快照、缓存等,可达 ~20G)算进已用、比系统显示偏高;可清除空间 shell 拿不到精确值。
dline=$(df -k /System/Volumes/Data 2>/dev/null | awk 'NR==2{print; exit}')
[ -z "$dline" ] && dline=$(df -k / 2>/dev/null | awk 'NR==2{print; exit}')
disks=$(echo "$dline" | awk '$2+0>0 {
    total=$2*1024; used=$3*1024;
    pct=int(used*100/total+0.5);
    printf "{\"name\":\"/\",\"used\":%.0f,\"total\":%.0f,\"pct\":%d}", used, total, pct
  }')

printf '{"cpu_pct":%d,"mem_used":%s,"mem_total":%s,"net_rx":%d,"net_tx":%d,"disk_read":0,"disk_write":0,"disks":[%s]}\n' \
  "$cpu" "$mu" "$mt" "$nrx" "$ntx" "$disks"
